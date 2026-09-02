"""Слои графики: полноэкранный текст, плашки, подсветка, карточки.

Каждая функция возвращает RGBA-слой размером с кадр, который композитор кладёт
поверх видеоряда. Вся геометрия считается от safe zones брендбука (§3.2), все
анимационные константы — из ``brandbook.json`` (§5). Субтитры рисует HyperFrames (gradient-fill / clip-wipe / blend-difference).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from PIL import Image, ImageDraw, ImageFilter

from ..logging import get_logger
from .canvas import (
    FontBook, RGBA, SafeZones, clamp01, cut_hole, dim_layer, draw_text, ease, measure,
    mix, new_layer, parse_color, rounded_rect, with_alpha,
)

_log = get_logger("layers")


@dataclass
class Ctx:
    """Общий контекст отрисовки: размеры, брендбук, гарнитуры."""

    width: int
    height: int
    fps: int
    brandbook: dict[str, Any]
    fonts: FontBook
    safe: SafeZones

    @classmethod
    def build(cls, cfg, fonts: FontBook | None = None) -> "Ctx":
        width, height = cfg.resolution
        return cls(width=width, height=height, fps=cfg.fps, brandbook=cfg.brandbook,
                   fonts=fonts or FontBook.load(cfg),
                   safe=SafeZones.from_brandbook(cfg.brandbook))

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def center_x(self) -> int:
        """Оптический центр кадра.

        Рабочая зона (§3.2) ужата справа под колонку лайк/коммент/шер, поэтому
        её середина лежит левее центра кадра. Всё, что по замыслу стоит «ровно
        по центру» — субтитры, полноэкранный текст, CTA, слово за головой, —
        центрируется отсюда, иначе кадр читается как заваленный влево.
        """
        return self.width // 2

    @property
    def centered_width(self) -> int:
        """Ширина блока, симметричного относительно центра кадра.

        Зеркалим левое поле рабочей зоны: правое поле шире только из-за
        интерфейса YouTube, и растягивать по нему симметричный блок нельзя.
        """
        return self.width - 2 * self.safe.x_min

    def color(self, name: str, alpha: float = 1.0) -> RGBA:
        return parse_color(self.brandbook["colors"][name], alpha)

    def ease(self, name: str, t: float) -> float:
        return ease(name, t, self.brandbook)

    def new(self) -> Image.Image:
        return new_layer(self.size)


# --- перенос текста -----------------------------------------------------------

def wrap_to_lines(ctx: Ctx, text: str, role: str, *, max_width: int, size: int,
                  max_lines: int = 3) -> list[str]:
    font = ctx.fonts.font(role, size)
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        probe = f"{current} {word}".strip()
        if current and measure(probe, font)[0] > max_width:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
        else:
            current = probe
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines or [text]


def fit_block(ctx: Ctx, text: str, role: str, *, max_width: int, max_size: int,
              min_size: int, max_lines: int = 3, uppercase: bool = False
              ) -> tuple[int, list[str]]:
    """Максимальный кегль, при котором текст укладывается в блок нужной ширины."""
    rendered = text.upper() if uppercase else text
    size = max_size
    while size > min_size:
        lines = wrap_to_lines(ctx, rendered, role, max_width=max_width, size=size,
                              max_lines=max_lines)
        font = ctx.fonts.font(role, size)
        if len(lines) <= max_lines and all(measure(l, font)[0] <= max_width for l in lines):
            return size, lines
        size -= 4
    lines = wrap_to_lines(ctx, rendered, role, max_width=max_width, size=min_size,
                          max_lines=max_lines)
    return min_size, lines


# --- субтитры (§5.1) ----------------------------------------------------------
# Pop-in Nunito удалён. Жесты рисует HyperFrames: gradient-fill и clip-wipe.


def subtitle_baseline(ctx: Ctx, *, face_bbox: tuple[int, int, int, int] | None) -> int:
    """§5.1: в режиме A блок субтитров опускается, если лицо ушло вниз."""
    spec = ctx.brandbook["subtitles"]
    default = int(spec["baseline_y_default"])
    if not face_bbox:
        return default
    if face_bbox[3] > int(spec["face_bbox_shift_trigger_y"]):
        return int(spec["baseline_y_avatar_shift"])
    return default


# --- полноэкранный текст (§5.2) ----------------------------------------------

def fullscreen_text(ctx: Ctx, content: str, *, progress: float, style: str = "impact-01",
                    accent_word: str | None = None, invert: bool = False) -> Image.Image:
    """Крупный текст на однотонном фоне — замена видеоряда."""
    spec = ctx.brandbook["fullscreen_text"]
    layer = Image.new("RGBA", ctx.size, ctx.color("ink") if invert else ctx.color("bg_pure"))

    text = (content or "").strip()
    if not text:
        return layer

    max_width = ctx.safe.width
    size, lines = fit_block(ctx, text, "display", max_width=max_width,
                            max_size=int(spec["size_px"][1]),
                            min_size=96, max_lines=3, uppercase=True)
    font = ctx.fonts.font("display", size)
    line_height = int(size * float(ctx.brandbook["typography"]["roles"]["display"]["line_height"]))

    # Вход снизу 180–250 мс + приближение 1.0 → 1.06 (§5.2)
    enter = clamp01(progress / 0.18) if progress < 0.18 else 1.0
    eased = ctx.ease("ease_out_cubic", enter)
    offset_y = int((1.0 - eased) * 90)
    scale = 1.0 + 0.06 * clamp01(progress)

    text_layer = ctx.new()
    total_h = line_height * len(lines)
    start_y = (ctx.safe.y_min + ctx.safe.y_max) // 2 - total_h // 2 + line_height // 2

    base_color = ctx.color("bg_pure") if invert else ctx.color("ink")
    for i, line in enumerate(lines):
        y = start_y + i * line_height + offset_y
        if accent_word and accent_word.upper() in line:
            _draw_line_with_accent(ctx, text_layer, line, accent_word.upper(), font,
                                   y, base_color, eased)
        else:
            draw_text(text_layer, (ctx.center_x, y), line, font,
                      fill=with_alpha(base_color, eased), anchor="mm")

    if style.endswith("impact-02"):
        underline_y = start_y + total_h - line_height // 2 + int(size * 0.34) + offset_y
        width_px = int(measure(lines[-1], font)[0] * clamp01(progress * 2.5))
        draw = ImageDraw.Draw(text_layer)
        draw.rounded_rectangle(
            (ctx.center_x - width_px // 2, underline_y,
             ctx.center_x + width_px // 2, underline_y + max(6, size // 22)),
            radius=6, fill=ctx.color("accent"))

    if abs(scale - 1.0) > 1e-3:
        new_w, new_h = int(ctx.width * scale), int(ctx.height * scale)
        text_layer = text_layer.resize((new_w, new_h), Image.Resampling.BILINEAR)
        crop_x, crop_y = (new_w - ctx.width) // 2, (new_h - ctx.height) // 2
        text_layer = text_layer.crop((crop_x, crop_y, crop_x + ctx.width, crop_y + ctx.height))

    layer.alpha_composite(text_layer)
    return layer


def _draw_line_with_accent(ctx: Ctx, layer: Image.Image, line: str, accent: str,
                           font, y: int, base: RGBA, alpha: float) -> None:
    """§3.3.2: красным выделяется одно слово, не строка."""
    parts = line.split()
    widths = [measure(p, font)[0] for p in parts]
    space = measure(" ", font)[0]
    total = sum(widths) + space * (len(parts) - 1)
    x = ctx.center_x - total // 2
    for part, width in zip(parts, widths):
        color = ctx.color("accent") if part == accent else base
        draw_text(layer, (x, y), part, font, fill=with_alpha(color, alpha), anchor="lm")
        x += width + space


# --- плашки и нижние трети (§5.4) --------------------------------------------

def plaque(ctx: Ctx, text: str, *, progress: float, out_progress: float = 0.0,
           position: str = "bottom", direction: str = "left", subtitle_text: str = "",
           icon: str = "") -> Image.Image:
    """Скруглённая плашка с выездом и bounce (overshoot 6–8 %)."""
    spec = ctx.brandbook["plaque"]
    layer = ctx.new()
    if not text:
        return layer

    size, lines = fit_block(ctx, text, "subtitle", max_width=ctx.safe.width - 120,
                            max_size=54, min_size=30, max_lines=2)
    font = ctx.fonts.font("subtitle", size)
    sub_font = ctx.fonts.font("subtitle", max(22, size - 18))

    text_w = max(measure(l, font)[0] for l in lines)
    if subtitle_text:
        text_w = max(text_w, measure(subtitle_text, sub_font)[0])
    pad_x, pad_y = 40, 26
    box_w = min(text_w + pad_x * 2, ctx.safe.width)
    line_h = int(size * 1.15)
    box_h = line_h * len(lines) + (int(size * 0.9) if subtitle_text else 0) + pad_y * 2

    y_center = {"bottom": ctx.safe.y_max - box_h // 2 - 60,
                "top": ctx.safe.y_min + box_h // 2 + 40,
                "middle": (ctx.safe.y_min + ctx.safe.y_max) // 2}[position]
    x_center = ctx.center_x

    # Вход с overshoot, выход — в ту же сторону, без затухания.
    if out_progress > 0:
        shift = int(ctx.width * 0.6 * ctx.ease("ease_out_cubic", out_progress))
        alpha = 1.0
    else:
        eased = ctx.ease("ease_out_back", clamp01(progress))
        shift = int(ctx.width * 0.6 * (1.0 - eased))
        alpha = clamp01(progress * 3)
    dx = -shift if direction == "left" else shift
    if position == "top":
        dy, dx = -shift, 0
    elif position == "bottom" and direction == "up":
        dy, dx = shift, 0
    else:
        dy = 0

    box = (x_center - box_w / 2 + dx, y_center - box_h / 2 + dy,
           x_center + box_w / 2 + dx, y_center + box_h / 2 + dy)
    rounded_rect(layer, box, radius=int(spec["radius_px_default"]),
                 fill=with_alpha(ctx.color("bg_light", float(spec["bg_alpha"])), alpha),
                 outline=with_alpha(ctx.color("accent", float(spec["border_alpha"])), alpha),
                 width=int(spec["border_px"]),
                 shadow=spec.get("shadow"))

    text_y = box[1] + pad_y + line_h // 2
    for line in lines:
        draw_text(layer, (x_center + dx, text_y), line, font,
                  fill=with_alpha(ctx.color("ink"), alpha), anchor="mm")
        text_y += line_h
    if subtitle_text:
        draw_text(layer, (x_center + dx, text_y + 4), subtitle_text, sub_font,
                  fill=with_alpha(ctx.color("muted"), alpha), anchor="mm")
    return layer


# --- фокусная подсветка (§5.5) -----------------------------------------------

def highlight(ctx: Ctx, box: tuple[float, float, float, float], *, progress: float,
              label: str = "", label_below_y: float | None = None) -> Image.Image:
    """Затемнение фона 70–85 % + вырез вокруг цели."""
    spec = ctx.brandbook["highlight"]
    opacity = float(spec["dim_opacity_default"]) * clamp01(progress / 0.2 if progress < 0.2 else 1.0)
    layer = dim_layer(ctx.size, opacity, ctx.color("ink"))
    cut_hole(layer, box, radius=int(spec["cutout_radius_px"]),
             feather=int(spec["cutout_padding_px"]))

    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle(tuple(int(v) for v in box), radius=int(spec["cutout_radius_px"]),
                           outline=ctx.color("accent"), width=4)
    if label:
        font = ctx.fonts.font("subtitle", 34)
        # Подпись ставим над вырезом, если под ним мало места до нижней
        # границы рабочей зоны, — иначе она ляжет поверх содержимого.
        # Подпись не должна лечь поверх содержимого выреза: caller передаёт
        # нижнюю границу всего объекта (например, карточки источника).
        below_y = (label_below_y if label_below_y is not None else box[3]) + 52
        y = below_y if below_y < ctx.safe.y_max - 40 else box[1] - 48
        draw_text(layer, (ctx.center_x, y), label, font,
                  fill=ctx.color("bg_pure"), stroke_width=5,
                  stroke_fill=ctx.color("accent_deep"), anchor="mm")
    return layer


# --- доказательная база (§5.6) -----------------------------------------------

def source_card(ctx: Ctx, *, template: str, domain: str, title: str, snippet: str = "",
                progress: float = 1.0, scroll: float = 0.0,
                typed_chars: int | None = None) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Окно источника. Возвращает слой и bbox самой карточки (для подсветки).

    §5.6: домен и заголовок читаемы, скриншот не мельче 60 % ширины кадра.
    """
    # Ширина карточки — вся рабочая зона: это 68 % ширины кадра, что выше
    # минимума §5.6 (60 %) и при этом не вылезает за safe zones (§3.2).
    width = ctx.safe.width
    x0 = ctx.safe.x_min
    y0 = ctx.safe.y_min + 160

    # Высота — по содержимому: пустая половина карточки читается как ошибка
    # вёрстки и крадёт место у кадра.
    chrome_h = 74
    title_size, title_lines = fit_block(ctx, title, "subtitle", max_width=width - 72,
                                        max_size=46, min_size=28, max_lines=2)
    snippet_lines = wrap_to_lines(ctx, snippet, "subtitle", max_width=width - 72,
                                  size=30, max_lines=3) if snippet else []
    height = (chrome_h + 28 + int(title_size * 1.2) * len(title_lines)
              + (40 * len(snippet_lines) + 12 if snippet_lines else 0) + 32)
    box = (x0, y0, x0 + width, y0 + height)

    layer = ctx.new()
    eased = ctx.ease("ease_out_cubic", clamp01(progress / 0.25 if progress < 0.25 else 1.0))
    dy = int((1 - eased) * 120)
    box = (box[0], box[1] - dy, box[2], box[3] - dy)

    rounded_rect(layer, box, radius=22, fill=ctx.color("bg_pure"),
                 outline=ctx.color("muted", 0.35), width=2,
                 shadow={"blur_px": 30, "offset_y_px": 10, "alpha": 0.2})

    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle((box[0], box[1], box[2], box[1] + chrome_h),
                           radius=22, fill=ctx.color("bg_light"))
    draw.rectangle((box[0], box[1] + chrome_h - 22, box[2], box[1] + chrome_h),
                   fill=ctx.color("bg_light"))

    if template in ("browser", "search", "chat_ai"):
        for i, tone in enumerate((ctx.color("accent_soft"), ctx.color("muted", 0.5),
                                  ctx.color("muted", 0.3))):
            draw.ellipse((box[0] + 26 + i * 34, box[1] + 26,
                          box[0] + 44 + i * 34, box[1] + 44), fill=tone)
        bar = (box[0] + 140, box[1] + 20, box[2] - 30, box[1] + 54)
        draw.rounded_rectangle(bar, radius=17, fill=ctx.color("bg_pure"))
        url_font = ctx.fonts.font("mono", 26)
        shown = domain if typed_chars is None else domain[:typed_chars]
        draw_text(layer, (bar[0] + 20, (bar[1] + bar[3]) // 2), shown, url_font,
                  fill=ctx.color("ink"), anchor="lm")
        if typed_chars is not None and typed_chars < len(domain):
            caret_x = bar[0] + 20 + measure(shown, url_font)[0] + 4
            draw.rectangle((caret_x, bar[1] + 8, caret_x + 3, bar[3] - 8),
                           fill=ctx.color("accent"))
    else:
        label = {"notepad": "Блокнот", "arxiv_card": "arXiv", "patent_card": "Патент"}.get(
            template, template)
        draw_text(layer, (box[0] + 30, box[1] + chrome_h // 2), label,
                  ctx.fonts.font("subtitle", 28), fill=ctx.color("muted"), anchor="lm")

    inner_top = box[1] + chrome_h + 28
    title_font = ctx.fonts.font("subtitle", title_size)
    y = inner_top - int(scroll * 60)
    title_box = (box[0] + 36, y, box[2] - 36, y)
    for line in title_lines:
        draw_text(layer, (box[0] + 36, y), line, title_font, fill=ctx.color("ink"),
                  anchor="la")
        y += int(title_size * 1.2)
    title_box = (title_box[0] - 8, title_box[1] - 8, title_box[2] + 8, y + 4)

    if snippet_lines:
        snip_font = ctx.fonts.font("subtitle", 30)
        for line in snippet_lines:
            if y > box[3] - 44:
                break
            draw_text(layer, (box[0] + 36, y + 12), line, snip_font,
                      fill=ctx.color("muted"), anchor="la")
            y += 40

    # Обрезаем всё, что вылезло за карточку при скролле.
    mask = Image.new("L", ctx.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(tuple(int(v) for v in box), radius=22, fill=255)
    layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", ctx.size, 0), mask))
    return layer, tuple(int(v) for v in title_box)  # type: ignore[return-value]


# --- CTA (§6, §11.1 QC-16) ----------------------------------------------------

def subscribe_button(ctx: Ctx, *, progress: float, text: str = "ПОДПИСАТЬСЯ") -> Image.Image:
    """Анимированная кнопка подписки — обязательна в последние 2 сек."""
    layer = ctx.new()
    font = ctx.fonts.font("display", 62)
    tw, th = measure(text, font)
    pad_x, pad_y = 56, 30
    box_w, box_h = tw + pad_x * 2, th + pad_y * 2

    pulse_hz = float(ctx.brandbook["cta"].get("button_pulse_hz", 1.6))
    pulse = 1.0 + 0.035 * math.sin(progress * math.pi * 2 * pulse_hz)
    enter = ctx.ease("ease_out_back", clamp01(progress * 4))

    x_center = ctx.center_x
    y_center = ctx.safe.y_max - box_h // 2 - 40
    w, h = box_w * pulse * enter, box_h * pulse * enter
    box = (x_center - w / 2, y_center - h / 2, x_center + w / 2, y_center + h / 2)

    rounded_rect(layer, box, radius=int(h / 2), fill=ctx.color("accent"),
                 shadow={"blur_px": 34, "offset_y_px": 10, "alpha": 0.25})
    if enter > 0.35:
        draw_text(layer, (x_center, y_center), text,
                  ctx.fonts.font("display", max(20, int(62 * enter))),
                  fill=ctx.color("bg_pure"), anchor="mm")
    return layer


# --- текст за головой аватара (§5.3) -----------------------------------------

def text_behind_head(ctx: Ctx, text: str, *, progress: float,
                     color_name: str = "ink") -> Image.Image:
    """Крупное слово позади головы (§5.3).

    Цвет по умолчанию — ``ink``: фон под аватаром светлый, и ``accent_soft``
    на нём попросту не читается. ``accent_soft`` остаётся вариантом для тёмного
    фона, но выбирает его вызывающий код, а не константа по умолчанию.
    """
    spec = ctx.brandbook["text_behind_head"]
    layer = ctx.new()
    size, lines = fit_block(ctx, text, "display", max_width=ctx.safe.width,
                            max_size=int(spec["size_px"][1]),
                            min_size=int(spec["size_px"][0]) - 60,
                            max_lines=2, uppercase=True)
    font = ctx.fonts.font("display", size)
    alpha = clamp01(progress * 3)
    y = int(ctx.height * 0.34)
    for line in lines:
        draw_text(layer, (ctx.center_x, y), line, font,
                  fill=with_alpha(ctx.color(color_name), alpha * 0.55), anchor="mm")
        y += int(size * 0.98)
    return layer


# --- вспышки и переходы (§4.3) -----------------------------------------------

def white_flash(ctx: Ctx, intensity: float) -> Image.Image:
    return Image.new("RGBA", ctx.size,
                     (255, 255, 255, int(255 * clamp01(intensity))))


def light_sweep(ctx: Ctx, progress: float) -> Image.Image:
    """Диагональный световой блик — динамический переход без смены картинки."""
    layer = ctx.new()
    band_w = int(ctx.width * 0.45)
    x = int(-band_w + (ctx.width + band_w * 2) * clamp01(progress))
    draw = ImageDraw.Draw(layer)
    for i in range(band_w):
        alpha = int(120 * math.sin(math.pi * i / band_w) ** 2)
        draw.line([(x + i, 0), (x + i - int(ctx.height * 0.25), ctx.height)],
                  fill=(255, 255, 255, alpha), width=2)
    return layer.filter(ImageFilter.GaussianBlur(8))


def glitch_bars(ctx: Ctx, progress: float, seed: int = 0) -> Image.Image:
    """Короткий глитч: смещённые полосы с акцентным цветом."""
    import random

    rng = random.Random(seed)
    layer = ctx.new()
    draw = ImageDraw.Draw(layer)
    count = 7
    for _ in range(count):
        y = rng.randint(0, ctx.height)
        h = rng.randint(6, 40)
        alpha = int(160 * (1.0 - abs(progress - 0.5) * 2))
        color = ctx.color("accent") if rng.random() < 0.4 else (255, 255, 255, 255)
        draw.rectangle((0, y, ctx.width, y + h), fill=with_alpha(color, alpha / 255))
    return layer


def vignette(ctx: Ctx, strength: float = 0.25) -> Image.Image:
    """Лёгкая виньетка — удерживает взгляд в центре кадра."""
    import numpy as np

    ys, xs = np.mgrid[0:ctx.height, 0:ctx.width]
    cx, cy = ctx.width / 2, ctx.height / 2
    dist = np.sqrt(((xs - cx) / cx) ** 2 + ((ys - cy) / cy) ** 2)
    alpha = np.clip((dist - 0.75) / 0.9, 0, 1) * strength * 255
    arr = np.zeros((ctx.height, ctx.width, 4), dtype=np.uint8)
    arr[:, :, 3] = alpha.astype(np.uint8)
    return Image.fromarray(arr, "RGBA")
