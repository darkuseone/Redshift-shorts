"""Генерация недостающего материала (§7.2 «Абстрактные data-виз», P9, §7.7 VFX).

Live — Magnific: эндпоинты вынесены в конфиг (``magnific.endpoints``), потому что
маршруты и имена моделей у сервиса меняются чаще, чем код пайплайна; менять их
правкой YAML безопаснее, чем правкой модуля.

Mock — генерация фирменного абстрактного клипа средствами ffmpeg в цветах
брендбука. Материал честно помечается ``ai_generated``, чтобы QC-14 считал долю
AI-футажа по фактам, а не по намерениям.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...errors import ProviderError
from ..ffmpeg import run
from ..logging import get_logger
from ..retry import call_with_retry
from .base import Provider, ProviderMode, resolve_mode

# Типы градиента фильтра ffmpeg ``gradients`` в порядке предпочтения. Набор
# зависит от сборки: в imageio-ffmpeg 7.0 их пять, в ubuntu-сборке CI — четыре,
# а ``conical`` из документации другой версии не существует нигде и стоил
# провала P9 на четвёртом ролике. Поэтому список — только пожелание, а
# фактический набор берётся у самого ffmpeg.
GRADIENT_TYPES = ("linear", "radial", "circular", "spiral", "square")


@lru_cache(maxsize=1)
def supported_gradient_types() -> tuple[str, ...]:
    """Типы градиента, которые понимает установленная сборка ffmpeg."""
    import subprocess

    from ..ffmpeg import ffmpeg_bin

    try:
        out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-h", "filter=gradients"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ("linear",)
    found = tuple(name for name in GRADIENT_TYPES
                  if re.search(rf"^\s+{name}\s+\d+\s", out, re.MULTILINE))
    # ``linear`` — значение по умолчанию самого фильтра: если разобрать справку
    # не удалось, лучше один рабочий тип, чем падение в середине прогона.
    return found or ("linear",)

_log = get_logger("generation")


@dataclass
class GeneratedAsset:
    id: str
    path: Path
    kind: str                      # video | photo
    prompt: str
    model: str
    duration_sec: float = 0.0
    width: int = 1080
    height: int = 1920
    paid_model: bool = False
    mock: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "path": str(self.path), "kind": self.kind,
            "prompt": self.prompt, "model": self.model,
            "duration_sec": round(self.duration_sec, 2),
            "width": self.width, "height": self.height,
            "paid_model": self.paid_model, "mock": self.mock,
            "license": "generated-owned", "ai_generated": True,
        }


class GenerationProvider(Provider):
    def generate(self, prompt: str, dst: Path, *, kind: str = "video",
                 duration_sec: float = 4.0, prefer_free: bool = True) -> GeneratedAsset:
        raise NotImplementedError


class MockGeneration(GenerationProvider):
    """Фирменный абстрактный B-roll: градиент брендбука + мягкое движение."""

    def __init__(self, cfg, costs) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.MOCK, name="magnific")

    def generate(self, prompt: str, dst: Path, *, kind: str = "video",
                 duration_sec: float = 4.0, prefer_free: bool = True) -> GeneratedAsset:
        seed = int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)
        width, height = self.cfg.resolution
        palette = [str(self.cfg.color(name)).lstrip("#")
                   for name in ("accent", "accent_deep", "ink", "accent_soft", "muted")]
        c0 = palette[seed % len(palette)]
        c1 = palette[(seed // 7 + 2) % len(palette)]
        # Разные промпты обязаны давать визуально разный кадр: одинаковый
        # градиент — это готовый дубль, который завалит QC-5.
        types = supported_gradient_types()
        gradient_type = types[seed % len(types)]

        dst.parent.mkdir(parents=True, exist_ok=True)
        source = (f"gradients=s={width}x{height}:c0=0x{c0}:c1=0x{c1}"
                  f":x0={seed % max(width, 1)}:y0={(seed // 3) % max(height, 1)}"
                  f":speed={0.008 + (seed % 9) / 500.0:.4f}"
                  f":d={duration_sec:.2f}:type={gradient_type}")
        if kind == "photo":
            run(["-y", "-f", "lavfi", "-i", source, "-frames:v", "1", str(dst)],
                what="mock generation photo")
        else:
            run(["-y", "-f", "lavfi", "-i", source, "-t", f"{duration_sec:.2f}",
                 "-r", str(self.cfg.fps), "-c:v", "libx264", "-preset", "ultrafast",
                 "-crf", "30", "-g", "30", "-pix_fmt", "yuv420p", str(dst)],
                what="mock generation video")

        price_key = "magnific_per_video_sec" if kind == "video" else "magnific_per_image"
        units = duration_sec if kind == "video" else 1
        self.charge("generate", units, "sec" if kind == "video" else "image",
                    units * float(self.cfg.get(f"budget.price.{price_key}", 0.08)))
        return GeneratedAsset(
            id=f"gen_mock_{seed:08x}", path=dst, kind=kind, prompt=prompt,
            model="mock-gradient-v1", duration_sec=duration_sec,
            width=width, height=height, paid_model=False, mock=True,
        )


class MagnificGeneration(GenerationProvider):
    def __init__(self, cfg, costs, api_key: str) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="magnific")
        self.api_key = api_key

    def generate(self, prompt: str, dst: Path, *, kind: str = "video",
                 duration_sec: float = 4.0, prefer_free: bool = True) -> GeneratedAsset:
        import requests

        base = str(self.cfg.get("magnific.api_base", "https://api.magnific.ai"))
        endpoints = self.cfg.get("magnific.endpoints", {}) or {}
        path = endpoints.get("video" if kind == "video" else "image",
                             "/v1/video/generate" if kind == "video" else "/v1/image/generate")
        models = self.cfg.get("magnific.models", {}) or {}
        model = models.get(("free_" if prefer_free else "paid_") + kind) or models.get(kind, "")
        width, height = self.cfg.resolution

        payload: dict[str, Any] = {
            "prompt": prompt, "width": width, "height": height,
            "aspect_ratio": "9:16",
        }
        if model:
            payload["model"] = model
        if kind == "video":
            payload["duration"] = round(duration_sec, 2)

        def _call() -> dict[str, Any]:
            resp = requests.post(f"{base}{path}", json=payload,
                                 headers={"Authorization": f"Bearer {self.api_key}"},
                                 timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"Magnific вернул {resp.status_code}",
                                    status=resp.status_code, body=resp.text[:300])
            return resp.json()

        data = call_with_retry(_call, **self._retry_kwargs("Magnific generate"))
        url = _first_url(data)
        if not url:
            raise ProviderError("Magnific не вернул ссылку на результат", keys=list(data)[:10])

        dst.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=self._timeout()) as resp:
            if resp.status_code >= 400:
                raise ProviderError("не удалось скачать результат Magnific",
                                    status=resp.status_code)
            with open(dst, "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    fh.write(chunk)

        price_key = "magnific_per_video_sec" if kind == "video" else "magnific_per_image"
        units = duration_sec if kind == "video" else 1
        self.charge("generate", units, "sec" if kind == "video" else "image",
                    units * float(self.cfg.get(f"budget.price.{price_key}", 0.08)),
                    model=model or "default")
        return GeneratedAsset(
            id=f"gen_{hashlib.sha256(prompt.encode()).hexdigest()[:12]}",
            path=dst, kind=kind, prompt=prompt, model=model or "magnific-default",
            duration_sec=duration_sec, width=width, height=height,
            paid_model=not prefer_free,
        )


def _first_url(data: Any) -> str:
    """Найти первую http-ссылку в ответе произвольной формы."""
    if isinstance(data, str):
        return data if data.startswith("http") else ""
    if isinstance(data, dict):
        for key in ("url", "output_url", "result_url", "video_url", "image_url"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        for value in data.values():
            found = _first_url(value)
            if found:
                return found
    if isinstance(data, list):
        for value in data:
            found = _first_url(value)
            if found:
                return found
    return ""


def build_generation_provider(cfg, costs) -> GenerationProvider:
    key = cfg.secret_for("magnific.api_key_env", purpose="Magnific")
    if resolve_mode(cfg, api_key=key, service="magnific") is ProviderMode.LIVE:
        return MagnificGeneration(cfg, costs, key or "")
    return MockGeneration(cfg, costs)
