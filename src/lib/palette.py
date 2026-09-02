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
from typing import Any, Sequence

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

    off, _hue = _off_mask(hue, sat, value, rules)
    return float(off.mean())


def _off_mask(hue: np.ndarray, sat: np.ndarray, value: np.ndarray,
              rules: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Маска «цветной посторонний» и оттенки этих точек.

    Коридор вокруг фирменного красного намеренно несимметричен. К оранжевому
    он широкий: тёплая сторона — это огонь, лава, закат, ржавчина, всё то, чем
    ролики и живут. К пурпуру узкий: ровно там начинается розовое, которое
    заказчик назвал прямо. Симметричные ±20° впускали розовую дымку с тоном
    347° как «красную» — клип 15168370 набирал 0.026 при пороге 0.15.

    Порог насыщенности низкий по той же причине. При 0.35 бледный розовый
    (медиана насыщенности 0.25) не считался вовсе, а фиолетовые чернила
    (0.27) не считались тем более. От серого их отделяет не насыщенность, а
    яркость: тёмная порода с холодным бликом стоит на 0.18 и остаётся серой,
    розовая дымка — на 0.33 и читается цветом.
    """
    brand = float(rules.get("hue_deg", 3.5))
    warm = float(rules.get("hue_warm_deg", rules.get("hue_tolerance_deg", 20.0)))
    cool = float(rules.get("hue_cool_deg", 12.0))
    signed = (hue - brand + 180.0) % 360.0 - 180.0     # + к оранжевому, − к пурпуру
    lit = ((sat > float(rules.get("saturation_min", 0.12)))
           & (value > float(rules.get("value_min", 0.28))))
    inside = (signed <= warm) & (signed >= -cool)
    # Земля прощается, золото — нет, и различает их не оттенок, а насыщенность.
    # Песок карьера и порода стоят на 30–45° при насыщенности 0.46–0.58; жёлто-
    # оранжевая лава — там же, но на 0.83. Без этой поправки пришлось бы выбирать
    # между двумя ошибками: либо снятый материал уходит в брак вместе с золотом,
    # либо золото проходит вместе с землёй.
    earth = float(rules.get("hue_earth_deg", warm))
    earth_sat = float(rules.get("earth_saturation_max", 0.62))
    inside |= (signed > warm) & (signed <= earth) & (sat <= earth_sat)
    return lit & ~inside, hue


def dominant_off_hue(image: Image.Image | Path | str,
                     rules: dict[str, Any]) -> tuple[float, float]:
    """Самый крупный посторонний тон кадра: его доля и он сам, в градусах.

    Общая доля постороннего цвета не отличает розовое поле от живой сцены.
    Замер это показал ребром: рабочий стол с деревом, кожей и зелёными
    клавишами набрал 0.217 — больше, чем фиолетовые чернила. У настоящей
    съёмки цвет разный и каждого понемногу, у абстрактного поля — один и
    сразу на пол-кадра. Поэтому меряется не сумма, а самый крупный тон.
    """
    if not isinstance(image, Image.Image):
        image = Image.open(image)
    rgb = np.asarray(image.convert("RGB").resize(SAMPLE), dtype=np.float32) / 255.0
    hue, sat, value = _hsv(rgb)
    off, _ = _off_mask(hue, sat, value, rules)
    if not off.any():
        return 0.0, -1.0
    width = float(rules.get("hue_bucket_deg", 30.0))
    buckets = np.bincount((hue[off] // width).astype(int),
                          minlength=int(360 // width) + 1)
    top = int(buckets.argmax())
    return float(buckets[top] / hue.size), top * width


def palette_verdict(frames: Sequence[Image.Image | Path | str],
                    rules: dict[str, Any]) -> dict[str, Any]:
    """Приговор кадрам кандидата: худший кадр решает за весь клип.

    Именно худший, а не средний: посторонний цвет на трети клипа зритель
    увидит, а среднее по кадрам его размажет и пропустит.
    """
    # Кадр может прийти путём (так делает конвейер) или уже открытой картинкой
    # (так удобнее тесту: держать в git 58 МБ брака ради проверки незачем).
    live = [f for f in frames
            if isinstance(f, Image.Image) or Path(f).exists()]
    if not live:
        return {"measured": False, "off_share": 0.0, "passed": True,
                "reason": "кадров для замера нет"}
    worst = max(off_palette_share(f, rules) for f in live)
    dominant, dom_hue = max((dominant_off_hue(f, rules) for f in live),
                            key=lambda pair: pair[0])
    limit = float(rules.get("off_share_max", 0.15))
    dom_limit = float(rules.get("dominant_off_share_max", 0.18))
    # Пурпурно-розовая полоса судится строже прочих. Синева рабочего стола или
    # зелень листвы — случайный цвет живой сцены, и его прощают. Розовое поле
    # случайным не бывает: это заливка кадра цветом, которого в палитре канала
    # нет и не будет. Заказчик назвал его прямо, поэтому у него свой порог.
    lo, hi = rules.get("magenta_band_deg", [300.0, 345.0])
    in_magenta = dom_hue >= 0 and float(lo) <= dom_hue <= float(hi)
    mag_limit = float(rules.get("magenta_share_max", 0.10))

    reasons: list[str] = []
    if worst > limit:
        reasons.append(f"посторонний цвет на {worst:.0%} кадра при пределе {limit:.0%}")
    if dominant > dom_limit:
        reasons.append(f"один посторонний тон ({dom_hue:.0f}°) занимает "
                       f"{dominant:.0%} кадра при пределе {dom_limit:.0%}")
    if in_magenta and dominant > mag_limit:
        reasons.append(f"пурпурно-розовый тон ({dom_hue:.0f}°) на {dominant:.0%} "
                       f"кадра при пределе {mag_limit:.0%}")
    return {
        "measured": True,
        "off_share": round(worst, 4),
        "dominant_off_share": round(dominant, 4),
        "dominant_off_hue": round(dom_hue, 1),
        "limit": limit,
        "passed": not reasons,
        "reason": "" if not reasons else (
            "; ".join(reasons)
            + ": палитра канала — чёрный, белый и красный (§3.1)"),
    }
