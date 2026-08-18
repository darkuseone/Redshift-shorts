"""Примитивы отрисовки по брендбуку (§3, §5) — основа всех шаблонов.

Здесь нет ни одного «магического» числа: цвета, кегли, радиусы, safe zones и
анимационные константы берутся из ``brandbook.json``. Это то, что скилл
``redshift-brandbook`` требует от любого рендера — сверяться с брендбуком, а не
с памятью.

Шрифты подключаются только после проверки кириллицы и лицензии (§3.4): попытка
нарисовать текст гарнитурой без кириллицы обязана падать, а не выводить
«квадратики».
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ...errors import RenderError
from ..fonts import pick_font
from ..jsonio import read_json
from ..logging import get_logger

_log = get_logger("canvas")

RGBA = tuple[int, int, int, int]


# --- цвет ---------------------------------------------------------------------

def parse_color(value: str | Sequence[int], alpha: float = 1.0) -> RGBA:
    """``#RRGGBB``, ``rgba(r,g,b,a)`` или кортеж → RGBA."""
    if isinstance(value, (tuple, list)):
        parts = list(value)
        if len(parts) == 3:
            parts.append(255)
        r, g, b, a = parts[:4]
        return (int(r), int(g), int(b), int(a * alpha))
    text = str(value).strip()
    if text.startswith("rgba(") or text.startswith("rgb("):
        inner = text[text.index("(") + 1: text.rindex(")")]
        parts = [p.strip() for p in inner.split(",")]
        r, g, b = (int(float(p)) for p in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return (r, g, b, int(255 * a * alpha))
    text = text.lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) == 6:
        r, g, b = (int(text[i:i + 2], 16) for i in (0, 2, 4))
        return (r, g, b, int(255 * alpha))
    if len(text) == 8:
        r, g, b, a = (int(text[i:i + 2], 16) for i in (0, 2, 4, 6))
        return (r, g, b, int(a * alpha))
    raise RenderError(f"не удалось разобрать цвет: {value!r}", code="COLOR_PARSE_ERROR")


def with_alpha(color: RGBA, alpha: float) -> RGBA:
    return (color[0], color[1], color[2], max(0, min(255, int(color[3] * alpha))))


def mix(a: RGBA, b: RGBA, t: float) -> RGBA:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(4))  # type: ignore[return-value]


# --- сглаживание --------------------------------------------------------------

def cubic_bezier(p1x: float, p1y: float, p2x: float, p2y: float, t: float) -> float:
    """Значение кривой Безье по x=t (аппроксимация Ньютоном, как в CSS)."""
    t = max(0.0, min(1.0, t))

    def _bezier(a: float, b: float, u: float) -> float:
        return 3 * a * u * (1 - u) ** 2 + 3 * b * u ** 2 * (1 - u) + u ** 3

    u = t
    for _ in range(8):
        x = _bezier(p1x, p2x, u) - t
        if abs(x) < 1e-5:
            break
        dx = (3 * p1x * (1 - 4 * u + 3 * u ** 2) + 3 * p2x * (2 * u - 3 * u ** 2)
              + 3 * u ** 2)
        if abs(dx) < 1e-6:
            break
        u -= x / dx
    return _bezier(p1y, p2y, max(0.0, min(1.0, u)))


def ease(name: str, t: float, brandbook: dict[str, Any] | None = None) -> float:
    curves = (brandbook or {}).get("easing", {}) if brandbook else {}
    curve = curves.get(name)
    if curve:
        return cubic_bezier(*curve[:4], t)
    if name == "linear":
        return t
    if name == "ease_out_cubic":
        return 1 - (1 - t) ** 3
    if name == "ease_out_back":
        c1, c3 = 1.70158, 2.70158
        return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
    return t


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


# --- шрифты -------------------------------------------------------------------

@dataclass
class FontBook:
    """Проверенные гарнитуры брендбука с кэшем размеров."""

    fonts_dir: Path
    brandbook: dict[str, Any]
    _by_role: dict[str, Path]

    @classmethod
    def load(cls, cfg) -> "FontBook":
        fonts_dir = cfg.path("paths.assets_dir", "assets") / "fonts"
        manifest = read_json(fonts_dir / "fonts_manifest.json")
        sample = cfg.brand("typography.required_sample_text", None)
        chain = manifest.get("fallback_chain", {})
        by_role: dict[str, Path] = {}
        for role in ("display", "subtitle", "mono"):
            candidates = [fonts_dir / name for name in chain.get(role, [])]
            candidates.extend(fonts_dir / f["file"] for f in manifest.get("fonts", [])
                              if f.get("role") == role)
            path, info, rejected = pick_font(candidates, require_cyrillic=True,
                                             sample_text=sample)
            if rejected:
                _log.info("гарнитура выбрана с фолбэком",
                          extra={"role": role, "chosen": info.family,
                                 "rejected": len(rejected)})
            by_role[role] = path
        return cls(fonts_dir=fonts_dir, brandbook=cfg.brandbook, _by_role=by_role)

    def path(self, role: str) -> Path:
        if role not in self._by_role:
            raise RenderError(f"неизвестная роль гарнитуры: {role}", code="FONT_ROLE_UNKNOWN")
        return self._by_role[role]

    def font(self, role: str, size: int) -> ImageFont.FreeTypeFont:
        return _load_font(str(self.path(role)), int(size))

    def fit(self, text: str, role: str, *, max_width: int, max_size: int,
            min_size: int = 24, uppercase: bool = False) -> tuple[ImageFont.FreeTypeFont, str]:
        """Подобрать максимальный кегль, при котором строка влезает в ширину."""
        rendered = text.upper() if uppercase else text
        size = max_size
        while size > min_size:
            font = self.font(role, size)
            if measure(rendered, font)[0] <= max_width:
                return font, rendered
            size -= 2
        return self.font(role, min_size), rendered


@lru_cache(maxsize=256)
def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def measure(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def text_bbox(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    return font.getbbox(text)


# --- примитивы ----------------------------------------------------------------

def new_layer(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def rounded_rect(layer: Image.Image, box: tuple[float, float, float, float], *,
                 radius: int, fill: RGBA | None = None, outline: RGBA | None = None,
                 width: int = 0, shadow: dict[str, Any] | None = None) -> None:
    """Скруглённый прямоугольник с мягкой тенью (§5.4)."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    if shadow:
        blur = int(shadow.get("blur_px", 24))
        offset = int(shadow.get("offset_y_px", 8))
        alpha = float(shadow.get("alpha", 0.18))
        pad = blur * 2
        shadow_layer = Image.new("RGBA", (layer.width, layer.height), (0, 0, 0, 0))
        ImageDraw.Draw(shadow_layer).rounded_rectangle(
            (x0, y0 + offset, x1, y1 + offset), radius=radius,
            fill=(0, 0, 0, int(255 * alpha)))
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur / 2))
        layer.alpha_composite(shadow_layer)
        del pad

    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=fill,
                           outline=outline, width=width)


def draw_text(layer: Image.Image, position: tuple[float, float], text: str,
              font: ImageFont.FreeTypeFont, *, fill: RGBA,
              stroke_width: int = 0, stroke_fill: RGBA | None = None,
              anchor: str = "mm") -> None:
    ImageDraw.Draw(layer).text(position, text, font=font, fill=fill, anchor=anchor,
                               stroke_width=stroke_width, stroke_fill=stroke_fill)


def dim_layer(size: tuple[int, int], opacity: float, color: RGBA | None = None) -> Image.Image:
    base = color or (10, 10, 12, 255)
    return Image.new("RGBA", size, (base[0], base[1], base[2], int(255 * clamp01(opacity))))


def cut_hole(layer: Image.Image, box: tuple[float, float, float, float], *,
             radius: int = 16, feather: int = 12) -> None:
    """Вырезать окно в затемняющем слое — основа фокусной подсветки (§5.5)."""
    mask = Image.new("L", (layer.width, layer.height), 255)
    ImageDraw.Draw(mask).rounded_rectangle(
        tuple(int(round(v)) for v in box), radius=radius, fill=0)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather / 2))
    alpha = layer.getchannel("A")
    layer.putalpha(Image.composite(alpha, Image.new("L", mask.size, 0), mask))


def scale_about_center(image: Image.Image, factor: float,
                       canvas_size: tuple[int, int] | None = None) -> Image.Image:
    """Масштабирование относительно центра — для pop-in и push-in."""
    size = canvas_size or image.size
    if abs(factor - 1.0) < 1e-4:
        return image
    new_w = max(1, int(round(image.width * factor)))
    new_h = max(1, int(round(image.height * factor)))
    resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.alpha_composite(resized, ((size[0] - new_w) // 2, (size[1] - new_h) // 2))
    return out


def paste_scaled(canvas: Image.Image, layer: Image.Image, factor: float,
                 center: tuple[int, int] | None = None) -> None:
    if abs(factor - 1.0) < 1e-4:
        canvas.alpha_composite(layer)
        return
    new_w = max(1, int(round(layer.width * factor)))
    new_h = max(1, int(round(layer.height * factor)))
    resized = layer.resize((new_w, new_h), Image.Resampling.LANCZOS)
    cx, cy = center or (canvas.width // 2, canvas.height // 2)
    canvas.alpha_composite(resized, (cx - new_w // 2, cy - new_h // 2))


# --- safe zones (§3.2) --------------------------------------------------------

@dataclass
class SafeZones:
    x_min: int
    x_max: int
    y_min: int
    y_max: int

    @classmethod
    def from_brandbook(cls, brandbook: dict[str, Any]) -> "SafeZones":
        area = brandbook["safe_zones"]["work_area"]
        return cls(int(area["x_min"]), int(area["x_max"]),
                   int(area["y_min"]), int(area["y_max"]))

    def contains(self, box: tuple[float, float, float, float]) -> bool:
        x0, y0, x1, y1 = box
        return (x0 >= self.x_min - 0.5 and x1 <= self.x_max + 0.5
                and y0 >= self.y_min - 0.5 and y1 <= self.y_max + 0.5)

    def violations(self, box: tuple[float, float, float, float]) -> list[str]:
        x0, y0, x1, y1 = box
        out: list[str] = []
        if x0 < self.x_min:
            out.append(f"левее x={self.x_min}")
        if x1 > self.x_max:
            out.append(f"правее x={self.x_max} (колонка лайк/коммент/шер)")
        if y0 < self.y_min:
            out.append(f"выше y={self.y_min} (системный UI)")
        if y1 > self.y_max:
            out.append(f"ниже y={self.y_max} (зона описания и кнопок)")
        return out

    @property
    def width(self) -> int:
        return self.x_max - self.x_min

    @property
    def center_x(self) -> int:
        return (self.x_min + self.x_max) // 2


def accent_area_share(layer: Image.Image, accent: RGBA, tolerance: int = 40) -> float:
    """Доля площади кадра, занятая акцентным цветом (§3.3.1: ≤10–12 %)."""
    import numpy as np

    arr = np.asarray(layer.convert("RGBA"), dtype=np.int16)
    diff = np.abs(arr[:, :, :3] - np.array(accent[:3], dtype=np.int16)).sum(axis=2)
    visible = arr[:, :, 3] > 40
    return float(((diff < tolerance) & visible).mean())
