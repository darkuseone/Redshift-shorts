"""Жесты субтитров, которых нет в каталоге §15.

``caption-camera-follow``: слова стоят на месте, едет камера. Раскладка
самоподобная — каждое новое слово меряется от коробки уже написанного, камера
отъезжает так, чтобы новое слово садилось в кадр тем же размером. Старые
остаются гореть и просто мельчают к левому верхнему углу.

Это не шаблон каталога и не вендорный HTML с examples HyperFrames: жест
переложен на Oswald, кровь ``accent`` вместо золота, тайминг — реальные слова
пайплайна, без ``filter``-смаза (его нет в списке анимируемых свойств).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Callable

from ..text_rules import subtitle_word
from .templates import text_width

# Совпадает с brand_css.Z_SUBTITLE: субтитр поверх оверлеев.
Z_CAPTION = 40

# Соседние фразы стыкуются встык, окно клипа включает оба конца — как шоты.
TRACK_CAPTION_EVEN = 18
TRACK_CAPTION_ODD = 19

FRAMINGS = {"tight": 0.82, "standard": 1.0, "wide": 1.25}

# Каталог: «уходит быстро, большую часть времени доезжает».
EASE_STEP = "cubic-bezier(0.31,0,0.11,1)"
EASE_WIDE = "cubic-bezier(0.42,0,0.14,1)"
EASE_INK = "cubic-bezier(0.2,0.7,0.3,1)"


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
            if new_block or gap >= pause_break_sec or len(current) >= max_words:
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


def _ease(brandbook: dict[str, Any], name: str, fallback: str) -> str:
    curve = (brandbook.get("easing") or {}).get(name)
    if not curve:
        return fallback
    return f"cubic-bezier({curve[0]},{curve[1]},{curve[2]},{curve[3]})"


def caption_css(brandbook: dict[str, Any]) -> str:
    """Стили камеры. Без filter: смаз каталога сюда не переносится."""
    subs = brandbook.get("subtitles") or {}
    spec = subs.get("camera_follow") or {}
    halo = subs.get("shadow") or {}
    blur = int(halo.get("blur_px", 20))
    offset = int(halo.get("offset_y_px", 4))
    alpha = float(halo.get("alpha", 0.5))
    tracking = float(spec.get("letter_spacing_em", 0.005))
    line_height = float(spec.get("line_height", 0.78))
    color = str(subs.get("color", "#FFFFFF"))
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
        f"line-height:{line_height};color:{color};opacity:0;"
        f"text-shadow:0 {offset}px {blur}px rgba(0,0,0,{alpha:.2f}),"
        f"0 {max(1, offset // 2)}px {max(2, blur // 5)}px "
        f"rgba(0,0,0,{alpha * 0.8:.2f})}}"
        ".cf-word.is-accent{color:var(--color-accent)}"
        ".cf-vignette{position:absolute;inset:0;pointer-events:none;"
        "background:radial-gradient(ellipse at 50% 50%,"
        "rgba(0,0,0,0) 42%,rgba(0,0,0,0.4) 100%)}"
    )


def _visible_words(raw: list[dict[str, Any]], case_mode: str) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for word in raw:
        display = subtitle_word(str(word.get("display") or ""), case_mode)
        if not display:
            continue
        item = dict(word)
        item["display"] = display
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
        end = max(start + 0.05, next_start)
        track = TRACK_CAPTION_EVEN if p % 2 == 0 else TRACK_CAPTION_ODD
        clip_id = f"cf-{p:02d}"
        world_id = f"{clip_id}-world"

        accent_at = _accent_index(phrase)
        flags = [i == accent_at for i in range(len(phrase))]
        laid = layout_camera_follow(
            [w["display"] for w in phrase],
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
