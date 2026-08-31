"""Цвет кадра против палитры канала.

Палитра канала — чёрный, белый и красный: ``#C8453D``, ``#E4726A``, ``#8E2F2A``,
все три стоят на оттенке 3–4°. Золото и жёлтый из референсов в неё не входят
намеренно. Проверял это до сих пор только человек, глядя на готовый ролик, —
ни в поиске футажа, ни у судьи со зрением правила про цвет не было. На 0047 это
вышло наружу: по запросу «abstract dark red gradient background» сток отдал
стену из ярко-розовых кубов, а судья её принял, потому что оценивал
соответствие речи, а не цвет.

Мерка выведена из этих же кадров, а не назначена. Считается доля точек, которые
одновременно насыщенные, светлые и по оттенку далеко от красного канала —
«цветной посторонний». Все три условия нужны:

* только насыщенность — и тёмный камень с холодным бликом (годный кадр)
  набирает 0.42, вровень с жёлтой лавой (негодный, 0.47);
* добавили яркость — и тот же камень падает до 0.00, лава остаётся 0.40;
* без оттенка не отличить фирменный красный от чужого пурпура.

На двенадцати кадрах живого прогона годные дали 0.00–0.03, негодные 0.40 и 0.93.
Порог 0.15 стоит посередине этого разрыва, а не на краю.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# Кадр меряется уменьшенным: цветовой сдвиг живёт в крупных пятнах, а не в
# отдельных точках, и полное разрешение здесь только тратит время.
SAMPLE = (160, 284)


def _hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Оттенок в градусах, насыщенность и яркость. Быстрее поточечного HSV."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    value = rgb.max(2)
    delta = value - rgb.min(2)
    sat = np.where(value > 0, delta / np.maximum(value, 1e-9), 0.0)
    hue = np.zeros_like(value)
    nz = delta > 1e-9
    idx = (value == r) & nz
    hue[idx] = 60 * ((g - b)[idx] / delta[idx]) % 360
    idx = (value == g) & nz
    hue[idx] = 60 * ((b - r)[idx] / delta[idx]) + 120
    idx = (value == b) & nz
    hue[idx] = 60 * ((r - g)[idx] / delta[idx]) + 240
    return hue, sat, value


def off_palette_share(image: Image.Image | Path | str, rules: dict[str, Any]) -> float:
    """Доля кадра, занятая цветом не из палитры канала. 0.0 — чисто."""
    if not isinstance(image, Image.Image):
        image = Image.open(image)
    rgb = np.asarray(image.convert("RGB").resize(SAMPLE), dtype=np.float32) / 255.0
    hue, sat, value = _hsv(rgb)

    brand = float(rules.get("hue_deg", 3.5))
    tolerance = float(rules.get("hue_tolerance_deg", 20.0))
    distance = np.abs((hue - brand + 180.0) % 360.0 - 180.0)
    off = ((sat > float(rules.get("saturation_min", 0.35)))
           & (value > float(rules.get("value_min", 0.40)))
           & (distance > tolerance))
    return float(off.mean())


def palette_verdict(frames: list[Path], rules: dict[str, Any]) -> dict[str, Any]:
    """Приговор кадрам кандидата: худший кадр решает за весь клип.

    Именно худший, а не средний: посторонний цвет на трети клипа зритель
    увидит, а среднее по кадрам его размажет и пропустит.
    """
    shares = [off_palette_share(f, rules) for f in frames if Path(f).exists()]
    if not shares:
        return {"measured": False, "off_share": 0.0, "passed": True,
                "reason": "кадров для замера нет"}
    worst = max(shares)
    limit = float(rules.get("off_share_max", 0.15))
    passed = worst <= limit
    return {
        "measured": True,
        "off_share": round(worst, 4),
        "limit": limit,
        "passed": passed,
        "reason": "" if passed else (
            f"посторонний цвет на {worst:.0%} кадра при пределе {limit:.0%}: "
            f"палитра канала — чёрный, белый и красный (§3.1)"),
    }
