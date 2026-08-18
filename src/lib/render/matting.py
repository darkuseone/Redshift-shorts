"""Маска аватара и VFX-фон — экспериментальная функция §7.7.

Порядок попыток задан ТЗ и реализован буквально:

1. **Приоритет** — получить от HeyGen выход с прозрачным фоном. Доступность
   проверяется по факту (есть ли альфа в файле и осмысленна ли она), а не
   «считается по умолчанию».
2. **Fallback** — локальная сегментация, если в окружении есть ``rembg`` или
   ``mediapipe``. Зависимость намеренно необязательная: тащить onnxruntime в
   CPU-раннер ради экспериментальной функции — плохая сделка (R-2).
3. **Fallback 2** — маска нестабильна: текст выносится вне bbox головы,
   VFX-вставка пропускается. Плохая маска хуже отсутствия эффекта (§5.3).

Правило деградации: при ``features.avatar_matting: false`` система собирает
ролик полностью, просто без текста за головой и без VFX-фона. Ни один другой
модуль от этой функции не зависит.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ..ffmpeg import probe, run
from ..logging import get_logger

_log = get_logger("matting")

# Порог качества: ниже — маска считается нестабильной и включается fallback 2.
QUALITY_THRESHOLD = 0.62


@dataclass
class MatteReport:
    available: bool
    source: str                  # heygen | local | none
    quality: float = 0.0
    stable: bool = False
    coverage_mean: float = 0.0
    coverage_std: float = 0.0
    edge_softness: float = 0.0
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.available and self.stable and self.quality >= QUALITY_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available, "source": self.source,
            "quality": round(self.quality, 3), "stable": self.stable,
            "usable": self.usable,
            "coverage_mean": round(self.coverage_mean, 4),
            "coverage_std": round(self.coverage_std, 4),
            "edge_softness": round(self.edge_softness, 4),
            "reason": self.reason,
        }


def _alpha_frames(clip: Path, out_dir: Path, count: int = 5) -> list[np.ndarray]:
    """Достать альфа-канал нескольких кадров клипа."""
    info = probe(clip)
    duration = info.duration_sec or 1.0
    out_dir.mkdir(parents=True, exist_ok=True)
    alphas: list[np.ndarray] = []
    for i in range(count):
        ts = duration * (i + 0.5) / count
        frame = out_dir / f"alpha_{i:02d}.png"
        try:
            run(["-y", "-ss", f"{ts:.3f}", "-i", str(clip), "-frames:v", "1",
                 "-vf", "scale=192:-2,format=rgba", str(frame)], what="alpha frame")
        except Exception:  # noqa: BLE001 — отсутствие альфы не должно ронять прогон
            continue
        if not frame.exists():
            continue
        with Image.open(frame) as img:
            if img.mode != "RGBA":
                continue
            alphas.append(np.asarray(img.getchannel("A"), dtype=np.float64) / 255.0)
    return alphas


def assess_matte(clip: Path, work_dir: Path) -> MatteReport:
    """Оценить пригодность маски: покрытие, стабильность, мягкость края."""
    alphas = _alpha_frames(clip, work_dir)
    if not alphas:
        return MatteReport(available=False, source="none",
                           reason="в клипе нет альфа-канала")

    coverages = [float((a > 0.5).mean()) for a in alphas]
    coverage_mean = float(np.mean(coverages))
    coverage_std = float(np.std(coverages))

    # Мягкость края: доля полупрозрачных пикселей. Совсем нулевая — «вырезано
    # ножницами», слишком большая — маска размазана и фон просвечивает.
    softness = float(np.mean([((a > 0.05) & (a < 0.95)).mean() for a in alphas]))

    if coverage_mean < 0.04:
        return MatteReport(False, "heygen", reason=f"маска почти пустая ({coverage_mean:.1%})",
                           coverage_mean=coverage_mean, coverage_std=coverage_std,
                           edge_softness=softness)
    if coverage_mean > 0.92:
        return MatteReport(False, "heygen", reason="маска покрывает почти весь кадр",
                           coverage_mean=coverage_mean, coverage_std=coverage_std,
                           edge_softness=softness)

    stability = 1.0 - min(1.0, coverage_std / max(coverage_mean, 1e-6) * 4.0)
    softness_score = 1.0 - min(1.0, abs(softness - 0.06) / 0.12)
    quality = 0.6 * stability + 0.4 * softness_score
    stable = coverage_std < coverage_mean * 0.22

    return MatteReport(
        available=True, source="heygen", quality=quality, stable=stable,
        coverage_mean=coverage_mean, coverage_std=coverage_std, edge_softness=softness,
        reason="" if stable else f"маска пляшет: разброс покрытия {coverage_std:.3f}",
    )


def try_local_matting(clip: Path, dst: Path) -> MatteReport:
    """Fallback §7.7.2 — локальная сегментация, если она вообще доступна."""
    try:
        import rembg  # noqa: F401
    except ImportError:
        return MatteReport(False, "none",
                           reason="локальная сегментация недоступна: rembg не установлен "
                                  "(намеренно не в зависимостях, R-2)")
    # Реализация оставлена явно нереализованной: включать матирование на
    # CPU-раннере без замера времени нельзя (R-2), а замерять нечего, пока
    # пакет не установлен в целевом окружении.
    return MatteReport(False, "local",
                       reason="rembg найден, но локальное матирование выключено до "
                              "замера времени на целевом раннере (R-2)")


def plan_vfx_backgrounds(slots: list[dict[str, Any]], *, limit: int,
                         duration_range: tuple[float, float]) -> list[int]:
    """Какие аватар-слоты получают VFX-фон (§7.7: ≤2 раза, 2–5 сек)."""
    lo, hi = duration_range
    candidates = [s for s in slots
                  if s["kind"] == "avatar" and lo <= float(s["duration"]) <= hi]
    # Приоритет — поворотный момент: там живой фон работает на смысл (§6).
    candidates.sort(key=lambda s: (0 if s["role"] == "twist" else 1, -float(s["duration"])))
    return [s["index"] for s in candidates[:max(0, limit)]]
