"""Жесты субтитров, которых нет в каталоге §15.

``caption-gradient-fill`` (прод по умолчанию): слово стоит, при произнесении
через него проезжает заливка. В каталоге это ``backgroundPosition`` по
Siri-радуге — свойства нет в списке движка, поэтому SVG-маска букв и сдвиг
``x`` у широкого градиентного rect. Радуга → кровь ``accent → accent_soft``,
одно слово на фразу. Остальные слова белые, с тем же bounce.

``caption-clip-wipe`` (космос): слово стоит, раскрывается слева направо.
В каталоге это ``clip-path: inset``. Маска — белый SVG-rect, вход ``scaleX``,
уход сдвигом ``x``. Жёлтая вспышка → ``accent``.

``caption-camera-follow``: слова стоят, едет камера. Раскладка самоподобная.

``caption-blend-difference``: белые слова инвертируются по пикселю
(``mix-blend-mode: difference``, не твин). Акцент изолирован — остаётся
``accent``, не уходит в циан. Каталог: ``isolation: isolate`` на корне.
Включается явным ``caption`` в плане, прод по умолчанию не меняет.

Это не шаблон каталога и не вендорный HTML: жесты переложены на Oswald,
тайминг — слова пайплайна. Pop-in Nunito в проекте больше нет.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Callable

from ...text import prefer_nichem_spelling
from ..text_rules import (
    merge_brand_phrases, merge_number_phrases, subtitle_word,
)
from .templates import opacity_hard_kill, text_width

# Совпадает с brand_css.Z_SUBTITLE: субтитр поверх оверлеев.
Z_CAPTION = 40

# Соседние фразы стыкуются встык, окно клипа включает оба конца — как шоты.
TRACK_CAPTION_EVEN = 18
TRACK_CAPTION_ODD = 19

# After the last spoken word a phrase may sit a beat, then fade. It must not
# stretch until the next *visible* phrase: mute windows drop karaoke in
# between, and that left «ДНЯ» on screen for 17 seconds on 0048.
_PHRASE_HOLD_CAP = 0.45
# Сколько заливка держится после того, как слово отзвучало. Ноль читался бы
# как мигание на стыке, полсекунды — как «вся фраза красная».
_FILL_HOLD_SEC = 0.12


# Оверлеи, которым караоке уступает кадр: они занимают его целиком или почти
# целиком. Тот же набор читает clip-wipe (``overlay_cuts``).
_CAPTION_YIELDS_TO = frozenset({"plaque", "cta", "dataviz", "source_card"})


def _frame_taking_starts(plan: dict[str, Any]) -> list[float]:
    """Моменты, с которых кадр занят не субтитром.

    Полноэкранная карточка — это **шот**, а не оверлей: она приходит в план
    как ``kind: "fullscreen_text"`` в ``shots``. Список, собранный по одним
    ``overlays``, её не видел, и хвост «НЕ БРАЛ» так и лежал поверх карточки
    «7 · $1 000 000 · 25 Y» — при том что слово отзвучало за 0.14 с до её
    начала. Смотрим обе коллекции.
    """
    starts = [
        float(ovl.get("start") or 0)
        for ovl in (plan.get("overlays") or [])
        if str(ovl.get("type") or "") in _CAPTION_YIELDS_TO
    ]
    starts += [
        float(shot.get("start") or 0)
        for shot in (plan.get("shots") or [])
        if str(shot.get("kind") or "") == "fullscreen_text"
    ]
    return starts


def phrase_clip_span(
    start: float,
    last_end: float,
    next_start: float,
    *,
    hold_sec: float = _PHRASE_HOLD_CAP,
    fade_sec: float = 0.25,
) -> tuple[float, float, float]:
    """Return ``(end, fade_start, fade_dur)`` for one caption phrase clip.

    Tight gaps (next word soon) still fill through to the next phrase.
    A mute hole longer than ``hold_sec + fade_sec`` stays empty.
    """
    gap = max(0.0, next_start - last_end)
    hold = min(max(hold_sec, 0.0), gap)
    remain = max(0.0, gap - hold)
    fade_dur = min(max(fade_sec, 0.0), remain) if remain > 0.04 else 0.0
    end = last_end + hold + fade_dur
    end = min(end, next_start)
    end = max(end, start + 0.05)
    fade_start = end - fade_dur if fade_dur else last_end
    return end, fade_start, fade_dur
# Акцент blend-difference лежит отдельным клипом: difference на родителе
# инвертирует кровь в циан, а два клипа одной фразы не делят трек.
TRACK_CAPTION_ACCENT_EVEN = 21
TRACK_CAPTION_ACCENT_ODD = 22
Z_CAPTION_ACCENT = Z_CAPTION + 1


def _phrase_baseline(phrase: list[dict[str, Any]], default: float) -> float:
    """Per-cue baseline when assemble raised captions to clear a card."""
    for word in phrase:
        raw = word.get("baseline_y")
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return float(default)



FRAMINGS = {"tight": 0.82, "standard": 1.0, "wide": 1.25}

# Каталог: «уходит быстро, большую часть времени доезжает».
EASE_STEP = "cubic-bezier(0.31,0,0.11,1)"
EASE_WIDE = "cubic-bezier(0.42,0,0.14,1)"
EASE_INK = "cubic-bezier(0.2,0.7,0.3,1)"

# Старые имена однословного pop-in: композитор больше его не собирает.
_LEGACY_POP = frozenset({"", "word-pop", "pop-in", "pop", "nunito"})
_BLEND_NAMES = frozenset({
    "blend-difference", "caption-blend-difference", "blend_difference",
})

_SPACE_RE = re.compile(
    r"космос|космическ|орбит[аеуы]|астронавт|галактик|вселенн|"
    r"\bnasa\b|\besa\b|spacex|starship|"
    r"спутник|телескоп|\bмарс[аеу]?\b|\bлун[аеуы]\b|"
    r"ракет[аеуы]|astronaut|\bgalaxy\b|\buniverse\b|"
    r"хаббл|\bhubble\b|уэбб|\bwebb\b|\bмкс\b|\biss\b|"
    r"черн\w*\s*дыр|black\s*hole|туманност",
    re.I,
)


def is_space_theme(plan: dict[str, Any]) -> bool:
    """Космос — категория ``space`` или космические слова в теме ролика."""
    if str(plan.get("category") or "").lower() == "space":
        return True
    meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
    chunks = [
        plan.get("title"), plan.get("topic"), plan.get("category"),
        meta.get("title"), meta.get("topic"), meta.get("category"),
    ]
    for block in plan.get("blocks") or []:
        chunks += [block.get("text"), block.get("spoken_text"),
                   block.get("visual_intent")]
    blob = " ".join(str(c or "") for c in chunks)
    return bool(_SPACE_RE.search(blob))


def is_explicit_space(plan: dict[str, Any]) -> bool:
    """Космос объявлен категорией, а не угадан по словам темы.

    Закон канала: clip-wipe живёт только на явном ``category: space``.
    Эвристика по тексту ловила «орбиту продаж» и «чёрную дыру в бюджете» и
    уводила обычный ролик с gradient-fill — поэтому выбор жеста её не видит.
    """
    return str(plan.get("category") or "").strip().lower() == "space"


def pick_caption_style(plan: dict[str, Any],
                       brandbook: dict[str, Any] | None = None) -> str:
    """Один жест канала: gradient-fill. clip-wipe — только явный ``space``.

    camera-follow и blend-difference не выбираются автоматически ни для
    какого ролика: они дают второй ряд слов поверх первого, что запрещено.
    """
    if is_explicit_space(plan):
        return "clip-wipe"
    return "gradient-fill"


def resolve_caption(name: str | None) -> str:
    """Имя из плана → существующий жест.

    Всё, кроме ``clip-wipe`` (явный космос), сводится к ``gradient-fill``:
    pop-in, camera-follow и blend-difference рисуют белый ряд и цветной
    дубль поверх него — это брак по закону канала, а не вариант вёрстки.
    """
    raw = str(name or "").strip()
    if raw == "clip-wipe":
        return "clip-wipe"
    return "gradient-fill"


def _num(value: float) -> str:
    return f"{float(value):.3f}".rstrip("0").rstrip(".") or "0"


def _px(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".") or "0"


def _scale(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".") or "0"


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    scale: float


@dataclass(frozen=True)
class LaidWord:
    text: str
    x: float
    y: float
    fs: float
    width: float
    height: float
    box: Box
    accent: bool = False


def measure_word(text: str, fs: float, letter_spacing_em: float = 0.005) -> float:
    """Ширина слова в мире: Oswald + трекинг каталога."""
    raw = text_width(text, 100) * fs / 100.0
    extra = letter_spacing_em * fs * max(0, len(text) - 1)
    return raw + extra


def camera_follow_params(brandbook: dict[str, Any]) -> dict[str, Any]:
    spec = (brandbook.get("subtitles") or {}).get("camera_follow") or {}
    framing_name = str(spec.get("framing", "standard"))
    safe = brandbook["safe_zones"]["work_area"]
    frame_w = float(safe["x_max"]) - float(safe["x_min"])
    frame_h = float(safe["y_max"]) - float(safe["y_min"])
    return {
        "framing": FRAMINGS.get(framing_name, 1.0),
        "ratio": float(spec.get("ratio", 0.72)),
        "margin": float(spec.get("margin", 1.36)),
        "close_margin": float(spec.get("close_margin", 1.2)),
        "move_sec": float(spec.get("move_sec", 0.4)),
        "ink_sec": float(spec.get("ink_sec", 0.16)),
        "close_sec": float(spec.get("close_sec", 0.94)),
        "max_words": int(spec.get("max_words", 12)),
        "pause_break_sec": float(spec.get("pause_break_sec", 0.45)),
        "line_height": float(spec.get("line_height", 0.78)),
        "font_size_base": float(spec.get("font_size_base", 0.16)),
        "letter_spacing_em": float(spec.get("letter_spacing_em", 0.005)),
        "gap_em": float(spec.get("gap_em", 0.07)),
        "case": str(spec.get("case", "upper")),
        "frame_w": frame_w,
        "frame_h": frame_h,
        "origin_x": float(safe["x_min"]),
        "origin_y": float(safe["y_min"]),
    }


def group_caption_phrases(
    words: list[dict[str, Any]],
    *,
    max_words: int = 12,
    pause_break_sec: float = 0.45,
) -> list[list[dict[str, Any]]]:
    """Нарезать ролик на фразы: пауза, смена блока, потолок длины.

    Весь ролик одной камерой превращает первые слова в пыль — каталог пишет
    одно предложение. Потолок 12 слов держит кегль читаемым.
    """
    phrases: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        if current:
            gap = float(word["start"]) - float(current[-1]["end"])
            prev_block = current[-1].get("block_id")
            block = word.get("block_id")
            new_block = (
                prev_block is not None and block is not None and prev_block != block
            )
            prev_y = current[-1].get("baseline_y")
            new_y = word.get("baseline_y")
            baseline_break = False
            if prev_y is not None and new_y is not None:
                try:
                    baseline_break = abs(float(prev_y) - float(new_y)) > 1.0
                except (TypeError, ValueError):
                    baseline_break = False
            prev_disp = str(current[-1].get("display") or "").strip()
            # `_visible_words` strips the period before grouping. Without the
            # flag, «силой.» + «Гладкий.» became one karaoke phrase (0048
            # printed СИЛЫПУНКТЫ / ШАГ ПУНКТЫ).
            sentence_break = bool(
                current[-1].get("sentence_end")
                or prev_disp.endswith((".", "!", "?", "…"))
                or prev_disp.endswith(('".', "».", ".”", ".'"))
            )
            # Comma/colon after two+ words: «спагетти, которое» used to wrap
            # as СПАГЕТТИКОТОРОЕ on the same karaoke line (0048).
            clause_break = bool(
                current[-1].get("clause_end") and len(current) >= 2
            )
            if (new_block or baseline_break or sentence_break or clause_break
                    or gap >= pause_break_sec
                    or len(current) >= max_words):
                phrases.append(current)
                current = []
        current.append(word)
    if current:
        phrases.append(current)
    return phrases


def layout_camera_follow(
    texts: list[str],
    *,
    frame_w: float,
    frame_h: float,
    base: float,
    ratio: float = 0.72,
    line_height: float = 0.78,
    letter_spacing_em: float = 0.005,
    gap_em: float = 0.07,
    measure: Callable[[str, float, float], float] = measure_word,
    accents: list[bool] | None = None,
) -> list[LaidWord]:
    """Самоподобная вёрстка каталога, без измерения в браузере."""
    box: Box | None = None
    out: list[LaidWord] = []
    aspect = frame_w / max(frame_h, 1e-6)
    flags = accents or [False] * len(texts)
    for i, text in enumerate(texts):
        fs = base if i == 0 or box is None else (box.y1 - box.y0) * ratio
        width = measure(text, fs, letter_spacing_em)
        height = fs * line_height
        gap = fs * gap_em
        if i == 0 or box is None:
            x = 0.0
            y = 0.0
        elif (box.x1 - box.x0) / max(box.y1 - box.y0, 1e-6) < aspect:
            # Уже написанное уже кадра — растём вправо, по общему базовому краю.
            x = box.x1 + gap
            y = box.y1 - height
        else:
            # Уже достаточно широко — новая строка под блоком, левые края вместе.
            x = box.x0
            y = box.y1 + gap
        word_box = Box(x, y, x + width, y + height)
        if box is None:
            box = word_box
        else:
            box = Box(
                min(box.x0, word_box.x0),
                min(box.y0, word_box.y0),
                max(box.x1, word_box.x1),
                max(box.y1, word_box.y1),
            )
        out.append(LaidWord(
            text=text, x=x, y=y, fs=fs, width=width, height=height,
            box=box, accent=bool(flags[i]),
        ))
    return out


def pose_for(box: Box, margin: float, frame_w: float, frame_h: float,
             origin_x: float = 0.0, origin_y: float = 0.0) -> Pose:
    bw = max((box.x1 - box.x0) * margin, 1.0)
    bh = max((box.y1 - box.y0) * margin, 1.0)
    scale = min(frame_w / bw, frame_h / bh)
    return Pose(
        x=origin_x + frame_w / 2 - (scale * (box.x0 + box.x1)) / 2,
        y=origin_y + frame_h / 2 - (scale * (box.y0 + box.y1)) / 2,
        scale=scale,
    )


def _accent_index(words: list[dict[str, Any]]) -> int:
    """Одно красное слово на фразу: акцент сценария, иначе последнее."""
    for i, word in enumerate(words):
        if word.get("emphasis"):
            return i
    return len(words) - 1


def _accent_cyan(word: dict[str, Any]) -> bool:
    """Красить ли акцент этого слова в cyan (§7.1).

    Семейство приезжает со словом из сборки (`accent_family`), а не выводится
    здесь: цвет — свойство смысла блока, а не длины фразы.
    """
    return str((word or {}).get("accent_family") or "red") == "cyan"


def _ease(brandbook: dict[str, Any], name: str, fallback: str) -> str:
    curve = (brandbook.get("easing") or {}).get(name)
    if not curve:
        return fallback
    return f"cubic-bezier({curve[0]},{curve[1]},{curve[2]},{curve[3]})"


def caption_css(brandbook: dict[str, Any]) -> str:
    """Стили жестов субтитра. Без filter и clip-path: их нет в списке движка."""
    subs = brandbook.get("subtitles") or {}
    spec = subs.get("camera_follow") or {}
    wipe = subs.get("clip_wipe") or {}
    glow = subs.get("glow") or {}
    bloom = glow.get("bloom") or [{"blur_px": 20, "alpha": 0.5}]
    widest = max(bloom, key=lambda b: int(b.get("blur_px", 0)))
    blur = int(widest.get("blur_px", 20))
    offset = int(glow.get("rim_px", 2))
    alpha = float(widest.get("alpha", 0.5))
    tracking = float(spec.get("letter_spacing_em", 0.005))
    line_height = float(spec.get("line_height", 0.78))
    color = str(subs.get("color", "#FFFFFF"))
    wipe_track = float(wipe.get("letter_spacing_em", 0.04))
    fill = subs.get("gradient_fill") or {}
    fill_track = float(fill.get("letter_spacing_em", 0.04))
    # End-card / busy mesh: thin white glyphs blend without a hard stroke.
    stroke = (
        "-webkit-text-stroke:2.4px rgba(0,0,0,0.88);"
        "paint-order:stroke fill;"
    )
    shadow = (
        f"{stroke}"
        f"text-shadow:0 {offset}px {blur}px rgba(0,0,0,{max(alpha, 0.72):.2f}),"
        f"0 {max(1, offset // 2)}px {max(2, blur // 5)}px "
        f"rgba(0,0,0,{max(alpha * 0.9, 0.65):.2f}),"
        "0 0 2px rgba(0,0,0,0.95)"
    )
    return (
        f".caption-camera{{position:absolute;inset:0;z-index:{Z_CAPTION};"
        "overflow:hidden;pointer-events:none;"
        "width:var(--frame-w);height:var(--frame-h)}"
        ".cf-stage{position:absolute;inset:0;overflow:hidden}"
        ".cf-world{position:absolute;left:0;top:0;width:0;height:0;"
        "transform-origin:0 0;will-change:transform}"
        ".cf-word{position:absolute;white-space:nowrap;"
        "font-family:var(--font-display);font-weight:700;"
        f"text-transform:uppercase;letter-spacing:{tracking}em;"
        f"line-height:{line_height};color:{color};opacity:0;{shadow}}}"
        ".cf-word.is-accent{color:var(--color-accent)}"
        ".cf-word.is-accent.cyan{color:var(--color-cyan)}"
        ".cf-vignette{position:absolute;inset:0;pointer-events:none;"
        "background:radial-gradient(ellipse at 50% 50%,"
        "rgba(0,0,0,0) 42%,rgba(0,0,0,0.4) 100%)}"
        f".caption-wipe{{position:absolute;inset:0;z-index:{Z_CAPTION};"
        "overflow:hidden;pointer-events:none;"
        "width:var(--frame-w);height:var(--frame-h)}"
        ".cw-group{position:absolute;left:var(--safe-x-min);"
        "width:calc(var(--safe-x-max) - var(--safe-x-min));"
        "display:flex;flex-wrap:wrap;justify-content:center;align-items:flex-end;"
        "overflow:visible}"
        ".cw-mask{display:block;flex:0 0 auto;overflow:visible}"
        ".cw-mask svg{display:block;overflow:visible}"
        ".cw-wipe-r{transform-origin:0px 50%;transform-box:fill-box}"
        ".cw-ink{font-family:var(--font-display);font-weight:700;"
        f"text-transform:uppercase;letter-spacing:{wipe_track}em;"
        f"fill:currentColor;color:{color};{shadow}}}"
        f".caption-grad{{position:absolute;inset:0;z-index:{Z_CAPTION};"
        "overflow:hidden;pointer-events:none;"
        "width:var(--frame-w);height:var(--frame-h)}"
        # nowrap: перенос строки склеивал соседние слова в одно (ВРЁТСАМОЛЁТ).
        # Фраза либо влезает в рабочую зону кеглем, либо ужимается, но остаётся
        # одной строкой.
        ".gf-group{position:absolute;left:var(--safe-x-min);"
        "width:calc(var(--safe-x-max) - var(--safe-x-min));"
        "display:flex;flex-wrap:nowrap;justify-content:center;align-items:flex-end}"
        ".gf-word{display:block;flex:0 0 auto;position:relative;"
        "transform-origin:50% 50%}"
        ".gf-word svg{display:block;overflow:visible}"
        ".gf-wipe-r{transform-origin:0px 50%;transform-box:fill-box}"
        # Обводка живёт на самом глифе SVG: text-shadow до <text> не доходит,
        # а второй HTML-слой под SVG запрещён законом канала.
        ".gf-ink{font-family:var(--font-display);font-weight:700;"
        f"letter-spacing:{fill_track}em;"
        "stroke:rgba(0,0,0,0.88);stroke-width:2.4px;"
        "stroke-linejoin:round;paint-order:stroke fill}"
        f".caption-blend{{position:absolute;inset:0;z-index:{Z_CAPTION};"
        "pointer-events:none;overflow:visible;"
        "width:var(--frame-w);height:var(--frame-h);"
        "mix-blend-mode:var(--blend-mode,difference)}"
        f".caption-blend-accent{{position:absolute;inset:0;z-index:{Z_CAPTION_ACCENT};"
        "pointer-events:none;overflow:visible;"
        "width:var(--frame-w);height:var(--frame-h);"
        "mix-blend-mode:normal;isolation:isolate}"
        ".caption-blend.mode-exclusion{--blend-mode:exclusion}"
        ".caption-blend.mode-screen{--blend-mode:screen}"
        ".bd-group{position:absolute;left:var(--safe-x-min);"
        "width:calc(var(--safe-x-max) - var(--safe-x-min));"
        "display:flex;flex-wrap:wrap;justify-content:center;align-items:flex-end;"
        "opacity:0}"
        ".bd-word{display:block;flex:0 0 auto;white-space:nowrap;"
        "font-family:var(--font-display);font-weight:700;"
        f"text-transform:uppercase;letter-spacing:{fill_track}em;"
        f"color:{color};line-height:1.15}}"
        ".bd-word.is-spacer{visibility:hidden}"
        ".bd-word.is-accent{"
        f"color:var(--color-accent);{shadow}}}"
        ".bd-word.is-accent.cyan{"
        f"color:var(--color-cyan);{shadow}}}"
    )


def _caption_shown(word: dict[str, Any]) -> str:
    """On-screen token: lead + display so digits glued as lead still paint."""
    lead = str(word.get("lead") or "").strip()
    display = str(word.get("display") or "").strip()
    if lead:
        return f"{lead} {display}".strip()
    return display


def _visible_words(raw: list[dict[str, Any]], case_mode: str) -> list[dict[str, Any]]:
    # Склейки идут по произнесённым словам, до оцифровки и регистра: после
    # них «две тысячи двадцать шесть» уже распалось на «2 ТЫСЯЧИ 20 6», а
    # «опен эй ай» — на три отдельных субтитра.
    raw = merge_number_phrases(merge_brand_phrases(list(raw)))
    visible: list[dict[str, Any]] = []
    for word in raw:
        raw_disp = str(word.get("display") or "")
        stripped = raw_disp.strip()
        sentence_end = bool(
            stripped.endswith((".", "!", "?", "…"))
            or stripped.endswith(('".', "».", ".”", ".'"))
        )
        clause_end = (not sentence_end) and bool(
            stripped.endswith((",", ";", ":"))
        )
        display = prefer_nichem_spelling(subtitle_word(raw_disp, case_mode))
        lead = prefer_nichem_spelling(subtitle_word(str(word.get("lead") or ""), case_mode))
        if lead and any(ch.isdigit() for ch in lead):
            display = f"{lead} {display}".strip()
            lead = ""
        if not display:
            continue
        item = dict(word)
        item["display"] = display
        item["lead"] = lead
        item["sentence_end"] = sentence_end
        item["clause_end"] = clause_end
        visible.append(item)
    return visible


def build_camera_follow(
    plan: dict[str, Any],
    brandbook: dict[str, Any],
    *,
    duration: float,
) -> tuple[list[str], list[str], int]:
    """Клипы фраз + твины камеры. Твины на мире и словах, не на ``.clip``."""
    params = camera_follow_params(brandbook)
    words = _visible_words(plan.get("subtitles") or [], params["case"])
    if not words:
        return [], [], 0

    phrases = group_caption_phrases(
        words,
        max_words=params["max_words"],
        pause_break_sec=params["pause_break_sec"],
    )
    ease_step = _ease(brandbook, "caption_camera_step", EASE_STEP)
    ease_wide = _ease(brandbook, "caption_camera_wide", EASE_WIDE)
    ease_ink = _ease(brandbook, "caption_camera_ink", EASE_INK)
    margin = params["margin"] * params["framing"]
    close_margin = params["close_margin"] * params["framing"]
    base = max(params["frame_w"], params["frame_h"]) * params["font_size_base"]

    nodes: list[str] = []
    tweens: list[str] = []
    count = 0

    for p, phrase in enumerate(phrases):
        start = float(phrase[0]["start"])
        last_end = float(phrase[-1]["end"])
        next_start = (
            float(phrases[p + 1][0]["start"]) if p + 1 < len(phrases) else duration
        )
        end, _, _ = phrase_clip_span(start, last_end, next_start, fade_sec=0.0)
        track = TRACK_CAPTION_EVEN if p % 2 == 0 else TRACK_CAPTION_ODD
        clip_id = f"cf-{p:02d}"
        world_id = f"{clip_id}-world"

        accent_at = _accent_index(phrase)
        flags = [i == accent_at for i in range(len(phrase))]
        laid = layout_camera_follow(
            [_caption_shown(w) for w in phrase],
            frame_w=params["frame_w"],
            frame_h=params["frame_h"],
            base=base,
            ratio=params["ratio"],
            line_height=params["line_height"],
            letter_spacing_em=params["letter_spacing_em"],
            gap_em=params["gap_em"],
            accents=flags,
        )
        poses = [
            pose_for(w.box, margin, params["frame_w"], params["frame_h"],
                     params["origin_x"], params["origin_y"])
            for w in laid
        ]
        wide = pose_for(
            laid[-1].box, close_margin, params["frame_w"], params["frame_h"],
            params["origin_x"], params["origin_y"],
        )

        word_nodes: list[str] = []
        for i, word in enumerate(laid):
            wid = f"{clip_id}-w{i}"
            klass = "cf-word is-accent" if word.accent else "cf-word"
            if word.accent and _accent_cyan(phrase[i]):
                klass += " cyan"
            # Геометрия мира — инлайн, не твин. Первое слово сразу видно:
            # каталог не оставляет кадр нулевым пустым.
            opacity = ";opacity:1" if i == 0 else ""
            word_nodes.append(
                f'<div id="{wid}" class="{klass}" '
                f'style="left:{_px(word.x)}px;top:{_px(word.y)}px;'
                f'font-size:{_px(word.fs)}px{opacity}">'
                f"{_esc(word.text)}</div>"
            )
            count += 1

        nodes.append(
            f'<div id="{clip_id}" class="clip caption-camera" '
            f'data-start="{_num(start)}" data-duration="{_num(end - start)}" '
            f'data-track-index="{track}">'
            f'<div id="{clip_id}-stage" class="cf-stage">'
            f'<div id="{world_id}" class="cf-world">'
            f'{"".join(word_nodes)}</div></div>'
            f'<div class="cf-vignette"></div></div>'
        )

        first_pose = poses[0]
        tweens.append(
            f'tl.set("#{world_id}",{{x:{_px(first_pose.x)},y:{_px(first_pose.y)},'
            f'scale:{_scale(first_pose.scale)}}},{_num(start)});'
        )
        tweens.append(
            f'tl.set("#{clip_id}-w0",{{opacity:1}},{_num(start)});'
        )

        cam_free = start
        for i, word in enumerate(phrase):
            if i == 0:
                continue
            at = float(word["start"])
            wid = f"{clip_id}-w{i}"
            ink = min(params["ink_sec"], max(0.05, float(word["end"]) - at))
            tweens.append(
                f'tl.fromTo("#{wid}",{{opacity:0}},{{opacity:1,'
                f'duration:{_num(ink)},ease:"{ease_ink}"}},{_num(at)});'
            )
            # Ход камеры влезает в щель до следующего слова — на одном узле
            # x/y/scale не имеют права пересечься по времени.
            nxt = float(phrase[i + 1]["start"]) if i + 1 < len(phrase) else end
            move = min(params["move_sec"], max(0.0, nxt - at))
            if move < 0.04:
                tweens.append(
                    f'tl.set("#{world_id}",{{x:{_px(poses[i].x)},'
                    f'y:{_px(poses[i].y)},scale:{_scale(poses[i].scale)}}},'
                    f'{_num(at)});'
                )
                cam_free = at
            else:
                tweens.append(
                    _camera_from_to(world_id, poses[i - 1], poses[i],
                                    move, at, ease_step)
                )
                cam_free = at + move

        close_at = max(cam_free, last_end)
        remain = end - close_at
        if remain >= 0.35:
            close_dur = min(params["close_sec"], remain)
            tweens.append(
                _camera_from_to(world_id, poses[-1], wide, close_dur,
                                close_at, ease_wide)
            )

        for i in range(len(laid)):
            tweens.append(
                f'tl.set("#{clip_id}-w{i}",{{opacity:0}},{_num(end)});'
            )

    return nodes, tweens, count


def _camera_from_to(world_id: str, src: Pose, dst: Pose, dur: float,
                    at: float, ease: str) -> str:
    return (
        f'tl.fromTo("#{world_id}",{{x:{_px(src.x)},y:{_px(src.y)},'
        f'scale:{_scale(src.scale)}}},{{x:{_px(dst.x)},y:{_px(dst.y)},'
        f'scale:{_scale(dst.scale)},duration:{_num(dur)},ease:"{ease}"}},'
        f'{_num(at)});'
    )


def clip_wipe_params(brandbook: dict[str, Any]) -> dict[str, Any]:
    spec = (brandbook.get("subtitles") or {}).get("clip_wipe") or {}
    subs = brandbook.get("subtitles") or {}
    safe = brandbook["safe_zones"]["work_area"]
    return {
        "base_px": int(spec.get("base_px", subs.get("size_px_default", 144))),
        "min_px": int(spec.get("min_px", 84)),
        "wipe_sec": float(spec.get("wipe_sec", 0.3)),
        "exit_sec": float(spec.get("exit_sec", 0.25)),
        "stagger_sec": float(spec.get("stagger_sec", 0.04)),
        "flash_delay_sec": float(spec.get("flash_delay_sec", 0.1)),
        "flash_sec": float(spec.get("flash_sec", 0.05)),
        "dim_sec": float(spec.get("dim_sec", 0.2)),
        "hold_sec": float(spec.get("hold_sec", 0.5)),
        "max_words": int(spec.get("max_words", 3)),
        "pause_break_sec": float(spec.get("pause_break_sec", 0.45)),
        "letter_spacing_em": float(spec.get("letter_spacing_em", 0.02)),
        "gap_em": float(spec.get("gap_em", 0.18)),
        "case": str(spec.get("case", "upper")),
        "dim_color": str(spec.get("dim_color", "rgba(255,255,255,0.4)")),
        "frame_w": float(safe["x_max"]) - float(safe["x_min"]),
        "origin_x": float(safe["x_min"]),
        "baseline_y": float(subs.get("baseline_y_default", 975)),
        "accent": str((brandbook.get("colors") or {}).get("accent", "#C8453D")),
        "ink": str(subs.get("color", "#FFFFFF")),
    }


def fit_wipe_group(
    texts: list[str],
    *,
    max_width: float,
    base: int,
    letter_spacing_em: float,
    gap_em: float,
    min_size: int = 12,
) -> tuple[int, list[float]]:
    """Кегль фразы, чтобы слова в ряд влезли в рабочую зону.

    Ниже ``min_size`` не опускаемся: группа уже ``flex-wrap``, и лучше две
    читаемые строки, чем одна нечитаемая. Прод передаёт ``min_px`` из
    брендбука; тесты без него оставляют старый пол 12.
    """
    size = int(base)
    floor = max(12, int(min_size))
    while size >= floor:
        widths = [measure_word(t, size, letter_spacing_em) for t in texts]
        gap = size * gap_em
        total = sum(widths) + gap * max(0, len(texts) - 1)
        if total <= max_width:
            return size, widths
        size -= 2
    widths = [measure_word(t, floor, letter_spacing_em) for t in texts]
    return floor, widths


def build_clip_wipe(
    plan: dict[str, Any],
    brandbook: dict[str, Any],
    *,
    duration: float,
) -> tuple[list[str], list[str], int]:
    """Фразы с wipe слева направо. Твины на маске и чернилах, не на ``.clip``."""
    params = clip_wipe_params(brandbook)
    baseline = float(plan.get("subtitle_style", {}).get(
        "baseline_y", params["baseline_y"]))
    words = _visible_words(plan.get("subtitles") or [], params["case"])
    if not words:
        return [], [], 0

    phrases = group_caption_phrases(
        words,
        max_words=params["max_words"],
        pause_break_sec=params["pause_break_sec"],
    )
    overlay_cuts = [
        float(ovl.get("start") or 0)
        for ovl in (plan.get("overlays") or [])
        if str(ovl.get("type") or "") in {"plaque", "cta", "dataviz", "source_card"}
    ]
    nodes: list[str] = []
    tweens: list[str] = []
    count = 0

    for p, phrase in enumerate(phrases):
        start = float(phrase[0]["start"])
        last_end = float(phrase[-1]["end"])
        next_start = (
            float(phrases[p + 1][0]["start"]) if p + 1 < len(phrases) else duration
        )
        texts = [_caption_shown(w) for w in phrase]
        pad_budget = max(1, len(texts)) * 2 * max(6, int(params["base_px"] * 0.12))
        size, widths = fit_wipe_group(
            texts,
            max_width=max(200.0, params["frame_w"] - pad_budget),
            base=params["base_px"],
            letter_spacing_em=params["letter_spacing_em"],
            gap_em=params["gap_em"],
            min_size=int(params.get("min_px", 84)),
        )
        gap_px = size * params["gap_em"]
        n = len(phrase)
        exit_span = params["exit_sec"] + params["stagger_sec"] * max(0, n - 1)
        hold_end = min(last_end + params["hold_sec"], next_start)
        for cut in overlay_cuts:
            if last_end < cut < hold_end + 1e-6:
                hold_end = cut
                break
        exit_at = min(hold_end - params["exit_sec"], next_start - exit_span)
        last_wipe = max(float(w["start"]) + params["wipe_sec"] for w in phrase)
        exit_at = max(start, last_wipe, exit_at)
        end = max(exit_at + exit_span, start + 0.05)
        if p + 1 < len(phrases):
            # Exclusive end so even/odd tracks never share a frame at the join
            # (clip visibility includes both endpoints). One frame at 30 fps.
            end = min(end, next_start - (1.0 / 30.0))
            exit_at = max(start, end - exit_span)

        track = TRACK_CAPTION_EVEN if p % 2 == 0 else TRACK_CAPTION_ODD
        clip_id = f"cw-{p:02d}"
        accent_at = _accent_index(phrase)
        # Unique y so a leftover even-track glyph cannot sit on the odd line.
        track_y = 0 if p % 2 == 0 else int(size * 0.42)
        top = int(_phrase_baseline(phrase, baseline) - size / 2 + track_y)
        word_nodes: list[str] = []
        glyph_pad = max(6, int(size * 0.12))
        for i, word in enumerate(phrase):
            wid = f"{clip_id}-w{i}"
            shown = texts[i]
            svg_w = widths[i] + 2 * glyph_pad
            wpx = _px(svg_w)
            margin = _px(gap_px) if i < n - 1 else "0"
            # Маска — белый rect в SVG. Тянем scaleX rect, не clip-path и не
            # контр-масштаб букв: слой 1000× в Chrome растрится в кашу.
            # Left pad keeps Oswald side-bearing of «Л»/«Г» inside the box.
            word_nodes.append(
                f'<div id="{wid}" class="cw-mask" '
                f'style="width:{wpx}px;height:{size}px;margin-right:{margin}px">'
                f'<svg width="{wpx}" height="{size}" viewBox="0 0 {wpx} {size}">'
                f'<defs><mask id="{wid}-m" maskUnits="userSpaceOnUse" '
                f'maskContentUnits="userSpaceOnUse">'
                f'<rect id="{wid}-r" class="cw-wipe-r" x="0" y="0" '
                f'width="{wpx}" height="{size}" fill="#fff"/></mask></defs>'
                f'<text id="{wid}-ink" class="cw-ink" mask="url(#{wid}-m)" '
                f'x="{_px(glyph_pad)}" y="{_px(size * 0.82)}" font-size="{size}px">'
                f"{_esc(shown)}</text></svg></div>"
            )
            count += 1

        group_id = f"{clip_id}-g"
        nodes.append(
            f'<div id="{clip_id}" class="clip caption-wipe" '
            f'data-start="{_num(start)}" data-duration="{_num(end - start)}" '
            f'data-track-index="{track}">'
            f'<div id="{group_id}" class="cw-group" '
            f'style="top:{top}px;left:{int(params["origin_x"])}px;'
            f'width:{int(params["frame_w"])}px;gap:0">'
            f'{"".join(word_nodes)}</div></div>'
        )
        # Tweens sit on the inner group, never the clip: the engine owns clip
        # visibility. Kill every previous group at this start so even/odd
        # tracks cannot stack uncleared glyphs mid B-roll.
        if p > 0:
            for prev in range(p):
                tweens.append(opacity_hard_kill(f"#cw-{prev:02d}-g", start))
        tweens.append(opacity_hard_kill(f"#{group_id}", end))

        for i, word in enumerate(phrase):
            wid = f"{clip_id}-w{i}"
            at = float(word["start"])
            wipe = params["wipe_sec"]
            if at + wipe > exit_at:
                wipe = max(0.08, exit_at - at)
            tweens.append(
                f'tl.fromTo("#{wid}-r",{{scaleX:0}},{{scaleX:1,'
                f'duration:{_num(wipe)},ease:"power2.out"}},{_num(at)});'
            )
            ink = params["ink"]
            dim_from = ink
            if i == accent_at:
                flash_at = at + params["flash_delay_sec"]
                flash_end = flash_at + params["flash_sec"]
                if flash_at + 0.02 < exit_at:
                    tweens.append(
                        f'tl.fromTo("#{wid}-ink",{{color:"{ink}"}},'
                        f'{{color:"{params["accent"]}",'
                        f'duration:{_num(params["flash_sec"])},ease:"power1.out"}},'
                        f'{_num(flash_at)});'
                    )
                    dim_from = params["accent"]
                else:
                    flash_end = at
            else:
                flash_end = at
            dim_at = max(float(word["end"]), flash_end)
            if dim_at + 0.04 < exit_at:
                dim_dur = min(params["dim_sec"], max(0.05, exit_at - dim_at))
                tweens.append(
                    f'tl.fromTo("#{wid}-ink",{{color:"{dim_from}"}},'
                    f'{{color:"{params["dim_color"]}",'
                    f'duration:{_num(dim_dur)},ease:"power1.out"}},'
                    f'{_num(dim_at)});'
                )
            stagger = i * params["stagger_sec"]
            tweens.append(
                f'tl.fromTo("#{wid}-r",{{x:0}},{{x:{_px(widths[i])},'
                f'duration:{_num(params["exit_sec"])},ease:"power2.in"}},'
                f'{_num(exit_at + stagger)});'
            )

    return nodes, tweens, count


def gradient_fill_params(brandbook: dict[str, Any]) -> dict[str, Any]:
    spec = (brandbook.get("subtitles") or {}).get("gradient_fill") or {}
    subs = brandbook.get("subtitles") or {}
    colors = brandbook.get("colors") or {}
    safe = brandbook["safe_zones"]["work_area"]
    return {
        "base_px": int(spec.get("base_px", subs.get("size_px_default", 144))),
        # Пол кегля ниже прежних 84: строка не переносится, а ужимается.
        # 84 на рабочей зоне 740 px не держал даже двух длинных слов, группа
        # уходила во вторую строку и «ВРЁТ»/«САМОЛЁТ» читались как одно слово.
        "min_px": int(spec.get("min_px", 58)),
        # Ниже этого кегля фраза не ужимается, а разбивается на две: мелкий
        # субтитр под аватаром читается как сноска, а не как речь.
        "comfort_px": int(spec.get("comfort_px", 84)),
        "max_words": int(spec.get("max_words", 2)),
        "pause_break_sec": float(spec.get("pause_break_sec", 0.45)),
        "letter_spacing_em": float(spec.get("letter_spacing_em", 0.02)),
        "gap_em": float(spec.get("gap_em", 0.18)),
        "case": str(spec.get("case", "upper")),
        "bounce_scale": float(spec.get("bounce_scale", 1.04)),
        "bounce_out_sec": float(spec.get("bounce_out_sec", 0.15)),
        "fade_sec": float(spec.get("fade_sec", 0.25)),
        "wipe_sec": float(spec.get("wipe_sec", 0.0)),
        "frame_w": float(safe["x_max"]) - float(safe["x_min"]),
        "origin_x": float(safe["x_min"]),
        "baseline_y": float(subs.get("baseline_y_default", 975)),
        # Один цвет заливки на весь канал. Ни accent_soft, ни cyan, ни
        # градиента: «текущее слово красится #C8453D» — закон, а не настройка.
        "accent": str(colors.get("accent", "#C8453D")),
        "ink": str(subs.get("color", "#FFFFFF")),
    }


def split_phrases_to_fit(
    phrases: list[list[dict[str, Any]]],
    *,
    max_width: float,
    base: int,
    letter_spacing_em: float,
    gap_em: float,
    comfort_px: int,
    min_size: int,
) -> list[list[dict[str, Any]]]:
    """Разбить фразу, которая влезает в строку только мелким кеглем.

    Строка у нас одна и не переносится, поэтому длинная пара слов раньше
    доезжала до пола кегля и превращалась в мелкий шрифт под аватаром.
    «ПЕРЕЛОЖИЛИ ДОКАЗАТЕЛЬСТВО» требовало 50 px — это не субтитр, это сноска.

    Дешевле показать те же слова двумя фразами подряд крупно: речь их всё
    равно произносит последовательно, и караоке от этого только честнее.
    """
    out: list[list[dict[str, Any]]] = []
    queue = [list(p) for p in phrases if p]
    while queue:
        phrase = queue.pop(0)
        size, _ = fit_wipe_group(
            [_caption_shown(w) for w in phrase],
            max_width=max_width, base=base,
            letter_spacing_em=letter_spacing_em, gap_em=gap_em,
            min_size=min_size,
        )
        if size >= comfort_px or len(phrase) < 2:
            out.append(phrase)
            continue
        half = len(phrase) // 2
        queue.insert(0, phrase[half:])
        queue.insert(0, phrase[:half])
    return out


def build_gradient_fill(
    plan: dict[str, Any],
    brandbook: dict[str, Any],
    *,
    duration: float,
) -> tuple[list[str], list[str], int]:
    """Караоке канала: белая фраза, текущее слово заливается по буквам.

    Один слой. Слово — ровно один ``<svg>``: белый ``<text>`` и поверх него
    тот же ``<text>`` цветом ``#C8453D`` под маской, которая растёт слева
    направо за время произнесения слова. Ни HTML-дубля под SVG, ни второго
    ряда слов сверху: белый ряд плюс цветной дубль — это брак, который и
    ловили на 0049/0050.

    Фраза всегда одна строка: группа не переносится (``flex-wrap:nowrap``),
    кегль подбирается под рабочую зону. Перенос склеивал соседние слова в
    одно — «ВРЁТСАМОЛЁТ».
    """
    params = gradient_fill_params(brandbook)
    baseline = float(plan.get("subtitle_style", {}).get(
        "baseline_y", params["baseline_y"]))
    words = _visible_words(plan.get("subtitles") or [], params["case"])
    if not words:
        return [], [], 0

    phrases = group_caption_phrases(
        words,
        max_words=params["max_words"],
        pause_break_sec=params["pause_break_sec"],
    )
    phrases = split_phrases_to_fit(
        phrases,
        max_width=params["frame_w"],
        base=params["base_px"],
        letter_spacing_em=params["letter_spacing_em"],
        gap_em=params["gap_em"],
        comfort_px=int(params["comfort_px"]),
        min_size=int(params["min_px"]),
    )
    # Фраза не должна доживать до карточки или диаграммы, которая займёт тот
    # же кадр. Хвост «НЕ БРАЛ» висел поверх карточки «7 · $1 000 000 · 25 Y»,
    # а «СООБЩЕНИЙ» и «17 ЧАСОВ» ложились на линию графика b4: караоке знает
    # только тайминг слов и про оверлеи под собой не спрашивает. У clip-wipe
    # такая развязка есть с самого начала (``overlay_cuts``), у заливки её
    # не было — добавляем ту же: держать хвост до начала оверлея, не дальше.
    overlay_cuts = sorted(_frame_taking_starts(plan))
    nodes: list[str] = []
    tweens: list[str] = []
    count = 0
    bounce = params["bounce_scale"]
    bounce_out = params["bounce_out_sec"]
    ink = params["ink"]
    accent = params["accent"]

    for p, phrase in enumerate(phrases):
        start = float(phrase[0]["start"])
        last_end = float(phrase[-1]["end"])
        next_start = (
            float(phrases[p + 1][0]["start"]) if p + 1 < len(phrases) else duration
        )
        texts = [_caption_shown(w) for w in phrase]
        size, widths = fit_wipe_group(
            texts,
            max_width=params["frame_w"],
            base=params["base_px"],
            letter_spacing_em=params["letter_spacing_em"],
            gap_em=params["gap_em"],
            min_size=int(params.get("min_px", 58)),
        )
        gap_px = size * params["gap_em"]
        n = len(phrase)
        end, fade_start, fade_dur = phrase_clip_span(
            start, last_end, next_start, fade_sec=params["fade_sec"])
        for cut in overlay_cuts:
            # Режем только хвост: слово, которое звучит, с экрана не снимаем.
            if last_end < cut < end:
                end = max(cut, start + 0.05)
                fade_dur = min(fade_dur, max(0.0, end - last_end))
                fade_start = end - fade_dur if fade_dur else last_end
                break
        if p + 1 < len(phrases):
            # Exclusive end so even/odd tracks never share a frame at the join
            # (clip visibility includes both endpoints). One frame at 30 fps.
            end = min(end, next_start - (1.0 / 30.0))
            end = max(end, start + 0.05)
            if fade_dur:
                fade_start = min(fade_start, end)

        track = TRACK_CAPTION_EVEN if p % 2 == 0 else TRACK_CAPTION_ODD
        clip_id = f"gf-{p:02d}"
        group_id = f"{clip_id}-g"
        # Одна строка и один baseline: смещения чётных/нечётных фраз больше
        # нет. Оно разводило соседние фразы по вертикали и на стыке читалось
        # как второй ряд слов.
        top = int(_phrase_baseline(phrase, baseline) - size / 2)
        # Маска шире кегля: у прописных Д/У/Ц выносные элементы уходят ниже
        # базовой линии, и маска высотой в кегль срезала бы им заливку.
        mask_y = -size * 0.30
        mask_h = size * 1.60
        text_y = size * 0.82
        word_nodes: list[str] = []

        for i, word in enumerate(phrase):
            wid = f"{clip_id}-w{i}"
            wpx = widths[i]
            margin = _px(gap_px) if i < n - 1 else "0"
            shown = texts[i]
            word_nodes.append(
                f'<div id="{wid}" class="gf-word" '
                f'style="width:{_px(wpx)}px;height:{size}px;'
                f'margin-right:{margin}px">'
                f'<svg width="{_px(wpx)}" height="{size}" '
                f'viewBox="0 0 {_px(wpx)} {size}">'
                f'<defs><mask id="{wid}-m" maskUnits="userSpaceOnUse" '
                f'maskContentUnits="userSpaceOnUse">'
                f'<rect id="{wid}-r" class="gf-wipe-r" x="0" y="{_px(mask_y)}" '
                f'width="{_px(wpx)}" height="{_px(mask_h)}" fill="#fff"/>'
                f"</mask></defs>"
                f'<text class="gf-ink" x="0" y="{_px(text_y)}" '
                f'font-size="{size}px" fill="{ink}">{_esc(shown)}</text>'
                f'<text class="gf-ink" mask="url(#{wid}-m)" x="0" '
                f'y="{_px(text_y)}" font-size="{size}px" '
                f'fill="{accent}">{_esc(shown)}</text>'
                f"</svg></div>"
            )
            count += 1

        nodes.append(
            f'<div id="{clip_id}" class="clip caption-grad" '
            f'data-start="{_num(start)}" data-duration="{_num(end - start)}" '
            f'data-track-index="{track}">'
            f'<div id="{group_id}" class="gf-group" '
            f'style="top:{top}px;left:{int(params["origin_x"])}px;'
            f'width:{int(params["frame_w"])}px;gap:0">'
            f'{"".join(word_nodes)}</div></div>'
        )

        for i, word in enumerate(phrase):
            wid = f"{clip_id}-w{i}"
            at = float(word["start"])
            word_end = float(word["end"])
            dur = max(0.05, word_end - at)
            # Красным светится ровно одно слово — то, которое звучит.
            #
            # Гаснет оно сразу, как слово отзвучало, а не висит до конца
            # фразы. Фраза канала часто состоит из одного экранного токена
            # («ПОГОДА», «НЕ БРАЛ» со склеенным предлогом), и удержание
            # заливки до конца клипа красило всю строку целиком на весь её
            # хвост: в кадре вместо белой фразы с одним красным словом стоял
            # сплошной красный. Передаём эстафету следующему слову, а на
            # последнем просто гасим.
            hand_off = (float(phrase[i + 1]["start"]) if i + 1 < n
                        else word_end + _FILL_HOLD_SEC)
            hand_off = min(max(hand_off, word_end), end)
            tweens.append(
                f'tl.set("#{wid}",{{scale:{_scale(bounce)}}},{_num(at)});'
            )
            tweens.append(
                f'tl.to("#{wid}",{{scale:1,duration:{_num(bounce_out)},'
                f'ease:"power2.out"}},{_num(word_end)});'
            )
            wipe = dur if params["wipe_sec"] <= 0 else min(dur, params["wipe_sec"])
            tweens.append(
                f'tl.fromTo("#{wid}-r",{{scaleX:0}},{{scaleX:1,'
                f'duration:{_num(wipe)},ease:"none"}},{_num(at)});'
            )
            tweens.append(
                f'tl.set("#{wid}-r",{{scaleX:0}},{_num(hand_off)});'
            )

        if fade_dur >= 0.04:
            tweens.append(
                f'tl.to("#{group_id}",{{opacity:0,duration:{_num(fade_dur)},'
                f'ease:"power1.out"}},{_num(fade_start)});'
            )
        tweens.append(
            f'tl.set("#{group_id}",{{opacity:0}},{_num(end)});'
        )

    return nodes, tweens, count


_BLEND_MODES = {"difference", "exclusion", "screen"}


def _bd_row(
    phrase: list[dict[str, Any]],
    *,
    clip_id: str,
    size: float,
    gap_px: float,
    accent_at: int,
    kind: str,
) -> list[str]:
    """Один ряд слов: в blend-слое акцент — спейсер, в акцент-слое наоборот."""
    n = len(phrase)
    nodes: list[str] = []
    for i, word in enumerate(phrase):
        if kind == "blend":
            cls = "bd-word is-spacer" if i == accent_at else "bd-word"
        else:
            cls = "bd-word is-accent" if i == accent_at else "bd-word is-spacer"
            if i == accent_at and _accent_cyan(word):
                cls += " cyan"
        margin = _px(gap_px) if i < n - 1 else "0"
        nodes.append(
            f'<div id="{clip_id}-w{i}" class="{cls}" '
            f'style="font-size:{size}px;line-height:{size}px;'
            f'margin-right:{margin}px">{_esc(word["display"])}</div>'
        )
    return nodes


def _bd_clip(
    clip_id: str,
    group_id: str,
    css: str,
    *,
    start: float,
    duration: float,
    track: int,
    top: int,
    origin_x: float,
    frame_w: float,
    words: list[str],
) -> str:
    return (
        f'<div id="{clip_id}" class="clip {css}" '
        f'data-start="{_num(start)}" data-duration="{_num(duration)}" '
        f'data-track-index="{track}">'
        f'<div id="{group_id}" class="bd-group" '
        f'style="top:{top}px;left:{int(origin_x)}px;'
        f'width:{int(frame_w)}px;gap:0">'
        f'{"".join(words)}</div></div>'
    )


def _bd_group_motion(
    group_id: str,
    *,
    start: float,
    end: float,
    enter_dur: float,
    rise: float,
    fade_dur: float,
    fade_start: float,
) -> list[str]:
    tweens = [
        f'tl.fromTo("#{group_id}",{{opacity:0,y:{_num(rise)}}},'
        f'{{opacity:1,y:0,duration:{_num(enter_dur)},ease:"expo.out"}},'
        f'{_num(start)});'
    ]
    if fade_dur >= 0.04:
        fade_at = max(fade_start, start + enter_dur + 0.04)
        if fade_at + fade_dur > end + 1e-6:
            fade_dur = end - fade_at
        if fade_dur >= 0.04:
            tweens.append(
                f'tl.to("#{group_id}",{{opacity:0,duration:{_num(fade_dur)},'
                f'ease:"power1.out"}},{_num(fade_at)});'
            )
    tweens.append(f'tl.set("#{group_id}",{{opacity:0}},{_num(end)});')
    return tweens


def blend_difference_params(brandbook: dict[str, Any]) -> dict[str, Any]:
    spec = (brandbook.get("subtitles") or {}).get("blend_difference") or {}
    fill = gradient_fill_params(brandbook)
    mode = str(spec.get("mode") or "difference").lower()
    if mode not in _BLEND_MODES:
        mode = "difference"
    fill["mode"] = mode
    fill["enter_sec"] = float(spec.get("enter_sec", 0.6))
    fill["rise_em"] = float(spec.get("rise_em", 0.42))
    fill["max_words"] = int(spec.get("max_words", fill["max_words"]))
    fill["fade_sec"] = float(spec.get("fade_sec", fill["fade_sec"]))
    return fill


def build_blend_difference(
    plan: dict[str, Any],
    brandbook: dict[str, Any],
    *,
    duration: float,
) -> tuple[list[str], list[str], int]:
    """Белые слова инвертируются о фон. Акцент не блендится — остаётся кровью.

    ``mix-blend-mode`` стоит на клипе — соседе видео. На слове внутри
    трансформируемой группы invert не видит футаж. Акцент вынесен во второй
    клип: difference на общем родителе уводит ``accent`` в циан.
    """
    params = blend_difference_params(brandbook)
    baseline = float(plan.get("subtitle_style", {}).get(
        "baseline_y", params["baseline_y"]))
    words = _visible_words(plan.get("subtitles") or [], params["case"])
    if not words:
        return [], [], 0

    phrases = group_caption_phrases(
        words,
        max_words=params["max_words"],
        pause_break_sec=params["pause_break_sec"],
    )
    nodes: list[str] = []
    tweens: list[str] = []
    count = 0
    mode_cls = "" if params["mode"] == "difference" else f" mode-{params['mode']}"
    enter = params["enter_sec"]

    for p, phrase in enumerate(phrases):
        start = float(phrase[0]["start"])
        last_end = float(phrase[-1]["end"])
        next_start = (
            float(phrases[p + 1][0]["start"]) if p + 1 < len(phrases) else duration
        )
        texts = [_caption_shown(w) for w in phrase]
        size, widths = fit_wipe_group(
            texts,
            max_width=params["frame_w"],
            base=params["base_px"],
            letter_spacing_em=params["letter_spacing_em"],
            gap_em=params["gap_em"],
            min_size=int(params.get("min_px", 84)),
        )
        gap_px = size * params["gap_em"]
        n = len(phrase)
        end, fade_start, fade_dur = phrase_clip_span(
            start, last_end, next_start, fade_sec=params["fade_sec"])
        rise = size * params["rise_em"]
        span = max(0.08, end - start)
        enter_dur = min(enter, max(0.08, span - 0.04))

        track = TRACK_CAPTION_EVEN if p % 2 == 0 else TRACK_CAPTION_ODD
        accent_track = (
            TRACK_CAPTION_ACCENT_EVEN if p % 2 == 0 else TRACK_CAPTION_ACCENT_ODD
        )
        clip_id = f"bd-{p:02d}"
        accent_id = f"{clip_id}a"
        group_id = f"{clip_id}-g"
        accent_group = f"{accent_id}-g"
        accent_at = _accent_index(phrase)
        top = int(_phrase_baseline(phrase, baseline) - size / 2)
        dur = end - start
        layout = dict(
            start=start, duration=dur, top=top,
            origin_x=params["origin_x"], frame_w=params["frame_w"],
        )
        nodes.append(_bd_clip(
            clip_id, group_id, f"caption-blend{mode_cls}",
            track=track,
            words=_bd_row(
                phrase, clip_id=clip_id, size=size, gap_px=gap_px,
                accent_at=accent_at, kind="blend"),
            **layout,
        ))
        nodes.append(_bd_clip(
            accent_id, accent_group, "caption-blend-accent",
            track=accent_track,
            words=_bd_row(
                phrase, clip_id=accent_id, size=size, gap_px=gap_px,
                accent_at=accent_at, kind="accent"),
            **layout,
        ))
        count += n
        motion = dict(
            start=start, end=end, enter_dur=enter_dur, rise=rise,
            fade_dur=fade_dur, fade_start=fade_start,
        )
        tweens.extend(_bd_group_motion(group_id, **motion))
        tweens.extend(_bd_group_motion(accent_group, **motion))

    return nodes, tweens, count

