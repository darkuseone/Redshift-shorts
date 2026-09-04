"""Наложение графики поверх видеоряда на каждом кадре.

Порядок слоёв задан смыслом, а не случайностью: карточка источника лежит под
подсветкой (подсветка затемняет всё, кроме цели), плашки — над ними. Субтитры
рисует HyperFrames. Кнопка подписки обязана быть видна всегда (§6).
"""

from __future__ import annotations

from typing import Any, Callable

from PIL import Image

from ..lib.render.canvas import SafeZones, accent_area_share, clamp01
from ..lib.render.layers import (
    Ctx, highlight, plaque, source_card, subscribe_button, subtitle, subtitle_baseline,
    text_behind_head,
)

# Слои, идущие ниже субтитров
BACKGROUND_OVERLAYS = ("source_card", "highlight", "plaque", "text_behind_head")


def _active(items: list[dict[str, Any]], t: float) -> list[dict[str, Any]]:
    return [i for i in items if float(i["start"]) <= t < float(i["end"])]


def _progress(item: dict[str, Any], t: float) -> float:
    start, end = float(item["start"]), float(item["end"])
    return clamp01((t - start) / max(end - start, 1e-6))


def build_overlay_renderer(ctx: Ctx, plan: dict[str, Any], *,
                           avatar_face_bbox: dict[str, Any] | None = None,
                           check_safe_zones: bool = True) -> Callable:
    """Замыкание, которое композитор вызывает на каждом кадре."""
    overlays = plan.get("overlays", [])
    subtitles = plan.get("subtitles", [])
    style = plan.get("subtitle_style", {})
    mode = str(style.get("mode", "stroke"))
    shots = plan.get("shots", [])
    accent = ctx.color("accent")
    safe: SafeZones = ctx.safe

    # Индексы для быстрого поиска активного элемента.
    subtitle_index = 0
    card_bbox_cache: dict[int, tuple[int, int, int, int]] = {}

    def _shot_at(t: float) -> dict[str, Any]:
        for shot in shots:
            if float(shot["start"]) <= t < float(shot["end"]):
                return shot
        return shots[-1] if shots else {}

    def render(frame: Image.Image, t: float, frame_no: int, stats) -> Image.Image:
        nonlocal subtitle_index
        canvas = frame.convert("RGBA")
        shot = _shot_at(t)
        drew = 0

        active = _active(overlays, t)
        cards = [o for o in active if o["type"] == "source_card"]
        card_box: tuple[int, int, int, int] | None = None
        card_bottom: float | None = None

        for item in cards:
            params = item.get("params", {})
            progress = _progress(item, t)
            typed = None
            if params.get("typing"):
                domain = str(params.get("domain", ""))
                typed = int(len(domain) * clamp01(progress / 0.5))
            layer, box = source_card(
                ctx, template=str(params.get("template", "browser")),
                domain=str(params.get("domain", "")),
                title=str(params.get("title", "")),
                snippet=str(params.get("snippet", "")),
                progress=progress,
                scroll=progress * 0.6 if params.get("scroll") else 0.0,
                typed_chars=typed)
            canvas.alpha_composite(layer)
            card_box = box
            card_bottom = box[3] + 140
            card_bbox_cache[frame_no] = box
            drew += 1

        for item in _active(overlays, t):
            kind = item["type"]
            params = item.get("params", {})
            progress = _progress(item, t)
            if kind == "highlight":
                target = card_box or (safe.x_min, 600, safe.x_max, 760)
                canvas.alpha_composite(highlight(
                    ctx, target, progress=progress,
                    label=str(params.get("label", "")), label_below_y=card_bottom))
                drew += 1
            elif kind == "plaque":
                out = clamp01((t - (float(item["end"]) - 0.2)) / 0.2)
                canvas.alpha_composite(plaque(
                    ctx, str(params.get("text", "")), progress=progress,
                    out_progress=out,
                    position=str(params.get("position", "bottom")),
                    direction=str(params.get("direction", "left")),
                    subtitle_text=str(params.get("subtitle", ""))))
                drew += 1
            elif kind == "text_behind_head":
                canvas.alpha_composite(text_behind_head(
                    ctx, str(params.get("text", "")), progress=progress))
                drew += 1

        # Субтитры рисует HyperFrames (gradient-fill / clip-wipe /
        # blend-difference). Покадровый композитор больше не кладёт
        # pop-in Nunito поверх кадра.
        if shot.get("kind") != "fullscreen_text":
            while (subtitle_index < len(subtitles)
                   and float(subtitles[subtitle_index]["end"]) <= t):
                subtitle_index += 1
            if subtitle_index < len(subtitles):
                word = subtitles[subtitle_index]
                if float(word["start"]) <= t < float(word["end"]):
                    baseline = subtitle_baseline(
                        ctx, face_bbox=(avatar_face_bbox or {}).get(shot.get("block_id"))
                        if shot.get("kind") in ("avatar", "split") else None)
                    elapsed = t - float(word["start"])
                    # Приклеенное начало реплики (§5.1) рисуется вместе со
                    # словом: этот движок кладёт слово одной строкой, и цвет
                    # акцента здесь достаётся ей целиком. Разложить его на два
                    # цвета умеет только композиция HyperFrames — она и рисует
                    # готовый ролик, а этот путь остаётся для проб и QC.
                    text = str(word["display"])
                    if word.get("lead"):
                        text = f'{word["lead"]} {text}'
                    canvas.alpha_composite(subtitle(
                        ctx, text, progress=clamp01(elapsed / 0.11),
                        emphasis=bool(word.get("emphasis")),
                        baseline_y=baseline, mode=mode))
                    stats.subtitle_frames += 1
                    drew += 1
            stats.speech_frames += 1

        for item in _active(overlays, t):
            if item["type"] == "cta":
                params = item.get("params") or {}
                if (item.get("renderer") == "logo_brand_close"
                        or params.get("logo_close")):
                    # Локуп рисует HyperFrames; пилюля поверх вордмарка не нужна.
                    continue
                canvas.alpha_composite(subscribe_button(
                    ctx, progress=t - float(item["start"]),
                    text=str(params.get("text", "ПОДПИСАТЬСЯ"))))
                drew += 1

        stats.overlay_draws += drew

        # Контроль брендбука прямо на кадре: доля акцента и safe zones (§3.3, §3.2).
        if check_safe_zones and frame_no % 15 == 0 and drew:
            share = accent_area_share(canvas, accent)
            stats.accent_share_max = max(stats.accent_share_max, share)

        return canvas.convert("RGB")

    return render
