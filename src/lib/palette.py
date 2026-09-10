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

import math
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image

# Кадр меряется уменьшенным: цветовой сдвиг живёт в крупных пятнах, а не в
# отдельных точках, и полное разрешение здесь только тратит время.
SAMPLE = (160, 284)


def _cover_9x16(image: Image.Image, size: tuple[int, int] = SAMPLE) -> Image.Image:
    """Centre-crop to 9:16 like the compositor, then downscale.

    ``Image.resize`` to portrait squashes a landscape still and dilutes a
    cyan column that the 9:16 plate keeps. QC-30 samples the finished
    file; P8 must see the same frame. ``fp_blue_bubbles`` passed P8 as a
    wide still and failed QC-30 at 40 % cyan on the crop.
    """
    tw, th = size
    rgb = image.convert("RGB")
    w, h = rgb.size
    if w <= 0 or h <= 0:
        return rgb.resize(size)
    target = tw / float(th)
    ratio = w / float(h)
    if ratio > target + 1e-6:
        new_w = max(1, int(round(h * target)))
        left = max(0, (w - new_w) // 2)
        rgb = rgb.crop((left, 0, min(w, left + new_w), h))
    elif ratio < target - 1e-6:
        new_h = max(1, int(round(w / target)))
        top = max(0, (h - new_h) // 2)
        rgb = rgb.crop((0, top, w, min(h, top + new_h)))
    return rgb.resize(size)


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


# Коридоры двух акцентов канала в HSV. Границы взяты от токенов брендбука
# (`accent #C8453D` → hue ≈ 4°, `cyan #36EFFF` → hue ≈ 186°) и расширены ровно
# настолько, чтобы поймать слово под свечением и антиалиасингом, но не поймать
# кожу ведущего (hue 20-40° при низкой насыщенности) и не поймать небо.
ACCENT_CORRIDORS = {
    "red": {"hue": (348.0, 18.0), "sat_min": 0.35, "value_min": 0.30},
    "cyan": {"hue": (168.0, 204.0), "sat_min": 0.35, "value_min": 0.35},
}


def accent_share(image: Image.Image | Path | str,
                 corridors: dict[str, Any] | None = None) -> dict[str, float]:
    """Какую долю кадра занимает каждый акцент канала.

    `render_stats.accent_share_max` на пути HyperFrames оставался нулём: доля
    считалась только в старом PIL-компоновщике (`overlays.py:158`), а бюджет
    `color_rules.accent_max_frame_share = 0.12` объявлен и не измерялся ни
    разу (N-11). Возвращается доля по каждому семейству и их сумма: гейт
    смотрит на сумму, а разбор — на слагаемые.
    """
    if not isinstance(image, Image.Image):
        image = Image.open(image)
    rgb = np.asarray(_cover_9x16(image), dtype=np.float32) / 255.0
    hue, sat, value = _hsv(rgb)
    out: dict[str, float] = {}
    for name, spec in (corridors or ACCENT_CORRIDORS).items():
        lo, hi = float(spec["hue"][0]), float(spec["hue"][1])
        # Красный лежит на стыке круга, поэтому коридор может быть «через ноль».
        in_hue = (hue >= lo) | (hue <= hi) if lo > hi else (hue >= lo) & (hue <= hi)
        mask = in_hue & (sat >= float(spec["sat_min"])) \
            & (value >= float(spec["value_min"]))
        out[name] = float(mask.mean())
    out["total"] = float(sum(v for k, v in out.items() if k != "total"))
    return out


def accent_share_max(frames: Sequence[Image.Image | Path | str],
                     corridors: dict[str, Any] | None = None) -> dict[str, Any]:
    """Худший кадр решает за ролик — как и в проверке палитры.

    Среднее размажет вспышку акцента на весь хронометраж и пропустит кадр,
    который зритель увидит целиком красным.
    """
    per_frame = [accent_share(f, corridors) for f in frames]
    if not per_frame:
        return {"max": 0.0, "red": 0.0, "cyan": 0.0, "frames": 0}
    worst = max(per_frame, key=lambda d: d["total"])
    return {
        "max": round(worst["total"], 4),
        "red": round(max(d["red"] for d in per_frame), 4),
        "cyan": round(max(d["cyan"] for d in per_frame), 4),
        "frames": len(per_frame),
    }


def accent_cap_verdict(frames: Sequence[Image.Image | Path | str],
                       cap: float) -> dict[str, Any]:
    """Full-frame B-roll may not exceed the accent budget QC-30 measures.

    Off-palette pink is a different gate. Brand red and cyan are legal until
    they eat the frame: the heartbeat clip sat on 16 % red as a 9:16 plate
    and failed QC-30. No frames to measure is not a rejection — the cheap
    path still has nothing to show the gate.
    """
    live = [f for f in frames
            if isinstance(f, Image.Image) or Path(f).exists()]
    if not live:
        return {"measured": False, "max": 0.0, "red": 0.0, "cyan": 0.0,
                "passed": True, "reason": ""}
    measured = accent_share_max(live)
    over = float(measured["max"]) > float(cap) + 1e-9
    return {
        "measured": True,
        "max": measured["max"],
        "red": measured["red"],
        "cyan": measured["cyan"],
        "passed": not over,
        "reason": (f"акцент {measured['max']:.0%} кадра при пределе "
                   f"{float(cap):.0%} (§7.5 / QC-30)" if over else ""),
    }


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

def frame_light(frames: Sequence[Image.Image | Path | str],
                *, floor: float = 0.15) -> dict[str, Any]:
    """Сколько в кадре вообще видно: доля пикселей ярче ``floor``.

    Мера нужна не всем кадрам, а перебивке. Перебивка живёт 1.4 секунды и
    существует ровно затем, чтобы в кадре что-то произошло; если материал в
    этот момент почти чёрный, зритель видит субтитр на пустоте. Именно так
    вышло в пересобранном 0047 на 40.5 и 50.0 секунде: средняя яркость 17.7 и
    20.1 из 255, восемь пикселей из десяти темнее 20.

    Судит **худший** кадр: перебивка показывает один момент, а не среднее по
    клипу. Замер по базе: медиана 55 % видимого, у клипа, давшего ту самую
    чёрную перебивку, — 16 %.
    """
    live = [f for f in frames if isinstance(f, Image.Image) or Path(f).exists()]
    if not live:
        return {"measured": False, "visible_share": 1.0, "mean": 1.0}
    shares, means = [], []
    for frame in live:
        image = frame if isinstance(frame, Image.Image) else Image.open(frame)
        grey = np.asarray(image.convert("L").resize(SAMPLE), dtype=np.float32) / 255.0
        shares.append(float((grey > floor).mean()))
        means.append(float(grey.mean()))
    return {"measured": True,
            "visible_share": round(min(shares), 4),
            "mean": round(min(means), 4)}


# MUST-021: HyperFrames overlay fills never went through footage-palette QC.
# Allowlist is brandbook colors plus white/ink. ΔE lets anti-alias neighbours
# through; magenta #FF00AA and leftover gold stay out. Do not recolor the
# 14k template catalog because one overlay carried a foreign hex.
FILL_DELTA_E_MAX = 12.0
_HEX_RE = re.compile(r"#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
_COLOR_KEYS = frozenset({
    "fill", "color", "bg", "background", "accent", "accent_color",
    "stroke", "border", "border_color", "highlight_color", "text_color",
    "ink", "paper", "tint", "glow", "rule", "underline",
})
TECH_THEMES = frozenset({
    "tech", "ai", "ai-tool", "ai_tool", "aitool", "ai-tools",
})
# Cyan on these themes is the 0047-class mistake: a second accent where the
# card is not about a tool. Number/source stay out of this set so MEGA D-9
# cyan on those families does not fail a live 0042 plan.
MEDICINE_THEMES = frozenset({
    "medicine", "medical", "health", "healthcare", "vaccine",
    "clinic", "pharma",
})


def normalize_hex(raw: str) -> str | None:
    """`#RGB` / `#RRGGBB` / `#RRGGBBAA` → uppercase `#RRGGBB`, or None."""
    text = str(raw or "").strip()
    if not text.startswith("#"):
        return None
    body = text[1:]
    if len(body) == 8 and all(c in "0123456789abcdefABCDEF" for c in body):
        body = body[:6]
    elif len(body) == 3 and all(c in "0123456789abcdefABCDEF" for c in body):
        body = "".join(ch * 2 for ch in body)
    elif not (len(body) == 6 and all(c in "0123456789abcdefABCDEF" for c in body)):
        return None
    return f"#{body.upper()}"


def brandbook_fill_allowlist(brandbook: dict[str, Any] | None) -> set[str]:
    """Every hex the brandbook names, plus white and ink as the card requires."""
    allowed: set[str] = set()
    for extra in ("#FFFFFF", "#000000", "#111214"):
        norm = normalize_hex(extra)
        if norm:
            allowed.add(norm)
    colors = (brandbook or {}).get("colors") or {}
    if isinstance(colors, dict):
        for value in colors.values():
            if not isinstance(value, str):
                continue
            norm = normalize_hex(value.strip())
            if norm:
                allowed.add(norm)
            rgb = _rgb_from_css(value)
            if rgb is not None:
                allowed.add(_hex_from_rgb(rgb))
    return allowed


def hex_in_allowlist(raw: str, allowlist: Iterable[str], *,
                     max_de: float = FILL_DELTA_E_MAX) -> bool:
    needle = normalize_hex(raw)
    if needle is None:
        return True
    allowed = {normalize_hex(item) for item in allowlist}
    allowed.discard(None)
    if needle in allowed:
        return True
    rgb = _hex_to_rgb(needle)
    if rgb is None:
        return True
    return any(_delta_e76(rgb, _hex_to_rgb(item)) <= max_de
               for item in allowed if _hex_to_rgb(item) is not None)


def overlay_fill_hexes(overlay: dict[str, Any]) -> list[str]:
    """Hex fills declared on the overlay (params + nested color keys)."""
    found: list[str] = []
    seen: set[str] = set()

    def take(raw: str) -> None:
        for match in _HEX_RE.findall(str(raw)):
            norm = normalize_hex(match)
            if norm and norm not in seen:
                seen.add(norm)
                found.append(norm)

    def walk(node: Any, *, color_context: bool) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, color_context=color_context or str(key) in _COLOR_KEYS)
        elif isinstance(node, list):
            for item in node:
                walk(item, color_context=color_context)
        elif isinstance(node, str) and color_context:
            take(node)

    params = overlay.get("params") if isinstance(overlay.get("params"), dict) else {}
    for key in _COLOR_KEYS:
        if key in overlay and overlay.get(key) is not None:
            walk(overlay.get(key), color_context=True)
        if key in params:
            walk(params.get(key), color_context=True)
    return found


def overlay_offbrand_fills(overlays: Sequence[dict[str, Any]],
                           brandbook: dict[str, Any] | None,
                           *, max_de: float = FILL_DELTA_E_MAX) -> list[dict[str, Any]]:
    """Overlays whose declared fill is not a brandbook colour."""
    allow = brandbook_fill_allowlist(brandbook)
    hits: list[dict[str, Any]] = []
    for overlay in overlays:
        if not isinstance(overlay, dict):
            continue
        foreign = [hex_ for hex_ in overlay_fill_hexes(overlay)
                   if not hex_in_allowlist(hex_, allow, max_de=max_de)]
        if foreign:
            hits.append({
                "overlay": overlay.get("type"),
                "hex": foreign,
                "start": overlay.get("start"),
            })
    return hits


def overlay_uses_cyan(overlay: dict[str, Any],
                      brandbook: dict[str, Any] | None) -> bool:
    params = overlay.get("params") if isinstance(overlay.get("params"), dict) else {}
    family = str(params.get("accent_family") or overlay.get("accent_family") or "")
    if family.strip().lower() == "cyan":
        return True
    cyan_tokens = []
    colors = (brandbook or {}).get("colors") or {}
    if isinstance(colors, dict):
        for name in ("cyan", "cyan_soft", "cyan_deep"):
            norm = normalize_hex(str(colors.get(name) or ""))
            if norm:
                cyan_tokens.append(norm)
    if not cyan_tokens:
        cyan_tokens = ["#36EFFF", "#7AF0FF", "#0BB8C9"]
    for hex_ in overlay_fill_hexes(overlay):
        if hex_in_allowlist(hex_, cyan_tokens, max_de=FILL_DELTA_E_MAX):
            return True
    return False


def overlay_theme(overlay: dict[str, Any],
                  script: dict[str, Any] | None = None) -> str:
    params = overlay.get("params") if isinstance(overlay.get("params"), dict) else {}
    for key in ("theme", "slot_theme", "domain_theme", "topic"):
        raw = params.get(key) or overlay.get(key)
        if raw:
            return str(raw).strip().lower()
    block_id = overlay.get("block_id") or params.get("block_id")
    if block_id is None:
        return ""
    for block in (script or {}).get("blocks") or []:
        if not isinstance(block, dict):
            continue
        if str(block.get("id")) != str(block_id):
            continue
        nested = block.get("overlay") if isinstance(block.get("overlay"), dict) else {}
        for key in ("theme", "slot_theme", "topic"):
            raw = nested.get(key) or block.get(key)
            if raw:
                return str(raw).strip().lower()
        family = str(block.get("emphasis_family") or "").strip().lower()
        return family
    return ""


def overlay_cyan_misuse(overlays: Sequence[dict[str, Any]],
                        brandbook: dict[str, Any] | None,
                        script: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Cyan fill/family on a medicine (non-tech) card — blocking MUST-021."""
    hits: list[dict[str, Any]] = []
    for overlay in overlays:
        if not isinstance(overlay, dict):
            continue
        if not overlay_uses_cyan(overlay, brandbook):
            continue
        theme = overlay_theme(overlay, script)
        if theme in TECH_THEMES:
            continue
        if theme not in MEDICINE_THEMES:
            continue
        hits.append({
            "overlay": overlay.get("type"),
            "theme": theme,
            "start": overlay.get("start"),
        })
    return hits


def _hex_to_rgb(hex_: str | None) -> tuple[int, int, int] | None:
    norm = normalize_hex(hex_ or "")
    if norm is None:
        return None
    body = norm[1:]
    return int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16)


def _hex_from_rgb(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _rgb_from_css(value: str) -> tuple[int, int, int] | None:
    text = str(value or "").strip()
    match = re.match(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text, flags=re.I)
    if not match:
        return None
    return (max(0, min(255, int(match.group(1)))),
            max(0, min(255, int(match.group(2)))),
            max(0, min(255, int(match.group(3)))))


def _srgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def channel(c: int) -> float:
        x = c / 255.0
        return ((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92

    r, g, b = channel(rgb[0]), channel(rgb[1]), channel(rgb[2])
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505

    def pivot(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else (7.787 * t) + 16.0 / 116.0

    fx, fy, fz = pivot(x / 0.95047), pivot(y / 1.0), pivot(z / 1.08883)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def _delta_e76(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, aa, ba = _srgb_to_lab(a)
    lb, ab, bb = _srgb_to_lab(b)
    return math.sqrt((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2)
