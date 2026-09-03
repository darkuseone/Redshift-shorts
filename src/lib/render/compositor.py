"""Покадровый композитор: edit-план → MP4.

Архитектура рендера:

1. ffmpeg приводит каждый план к 1080×1920 @ 30 fps (``shots.prepare_shot``).
2. Композитор читает нормализованные планы как сырые кадры, применяет Ken Burns,
   переходы и графику, и отдаёт кадры энкодеру ffmpeg через pipe.
3. Энкодер мультиплексирует видео со звуком и ставит ``+faststart``.

Потоковая схема выбрана намеренно: за раз в памяти живёт один кадр, поэтому
50-секундный ролик 1080×1920 собирается на CPU-раннере без риска упереться в
память (§10.5.1).
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np
from PIL import Image, ImageFilter

from ...errors import RenderError
from ..ffmpeg import ffmpeg_bin, probe
from ..logging import get_logger
from .canvas import clamp01, ease
from .layers import Ctx
from .shots import apply_kenburns, kenburns_window

_log = get_logger("compositor")


class FrameSource:
    """Последовательное чтение кадров клипа как сырого rgb24 через pipe."""

    def __init__(self, path: Path, size: tuple[int, int], fps: int) -> None:
        self.path = Path(path)
        self.size = size
        self.fps = fps
        self.frame_bytes = size[0] * size[1] * 3
        self._proc: subprocess.Popen | None = None
        self._last: Image.Image | None = None
        self._exhausted = False

    def _open(self) -> None:
        self._proc = subprocess.Popen(
            [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-nostdin",
             "-i", str(self.path), "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{self.size[0]}x{self.size[1]}", "-r", str(self.fps), "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=self.frame_bytes * 2)

    def next_frame(self) -> Image.Image:
        """Следующий кадр; после конца клипа — замирание на последнем."""
        if self._exhausted and self._last is not None:
            return self._last
        if self._proc is None:
            self._open()
        assert self._proc is not None and self._proc.stdout is not None
        raw = self._proc.stdout.read(self.frame_bytes)
        if not raw or len(raw) < self.frame_bytes:
            self._exhausted = True
            if self._last is None:
                raise RenderError("клип не отдал ни одного кадра", path=str(self.path))
            return self._last
        frame = Image.frombytes("RGB", self.size, raw)
        self._last = frame
        return frame

    def close(self) -> None:
        if self._proc is not None:
            try:
                if self._proc.stdout:
                    self._proc.stdout.close()
                self._proc.terminate()
                self._proc.wait(timeout=10)
            except Exception:  # noqa: BLE001 — закрытие не должно ронять рендер
                pass
            self._proc = None


# --- переходы (§4.3) ----------------------------------------------------------

TransitionFn = Callable[[Image.Image, Image.Image | None, float, dict[str, Any], Ctx], Image.Image]


def _tr_cut(incoming, outgoing, progress, params, ctx):
    return incoming


def _tr_zoom_punch(incoming, outgoing, progress, params, ctx):
    from_scale = float(params.get("from_scale", 1.3))
    eased = ease("ease_out_cubic", clamp01(progress), ctx.brandbook)
    scale = from_scale + (1.0 - from_scale) * eased
    if abs(scale - 1.0) < 1e-3:
        return incoming
    w, h = incoming.size
    if scale > 1.0:
        win_w, win_h = w / scale, h / scale
        box = ((w - win_w) / 2, (h - win_h) / 2, (w + win_w) / 2, (h + win_h) / 2)
        return incoming.resize((w, h), Image.Resampling.BILINEAR, box=box)
    small = incoming.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                            Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    canvas.paste(small, ((w - small.width) // 2, (h - small.height) // 2))
    return canvas


def _tr_whip_pan(incoming, outgoing, progress, params, ctx):
    direction = int(params.get("direction", 1))
    blur = float(params.get("blur", 24))
    w, h = incoming.size
    eased = ease("ease_out_cubic", clamp01(progress), ctx.brandbook)
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    if outgoing is not None:
        out_shift = int(direction * w * eased)
        canvas.paste(outgoing, (-out_shift, 0))
    in_shift = int(direction * w * (1.0 - eased))
    canvas.paste(incoming, (in_shift, 0))
    amount = blur * math.sin(math.pi * clamp01(progress))
    if amount > 0.6:
        canvas = canvas.filter(ImageFilter.GaussianBlur(amount / 3.0))
    return canvas


def _tr_paper_slide(incoming, outgoing, progress, params, ctx):
    axis = params.get("axis", "x")
    direction = int(params.get("direction", 1))
    w, h = incoming.size
    eased = ease("ease_out_cubic", clamp01(progress), ctx.brandbook)
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    if outgoing is not None:
        canvas.paste(outgoing, (0, 0))
    if axis == "y":
        canvas.paste(incoming, (0, int(direction * h * (1.0 - eased))))
    else:
        canvas.paste(incoming, (int(direction * w * (1.0 - eased)), 0))
    return canvas


def _tr_mask_wipe(incoming, outgoing, progress, params, ctx):
    from PIL import ImageDraw

    shape = params.get("shape", "circle")
    w, h = incoming.size
    eased = ease("ease_out_cubic", clamp01(progress), ctx.brandbook)
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    if shape == "circle":
        radius = eased * math.hypot(w, h) / 2 * 1.05
        draw.ellipse((w / 2 - radius, h / 2 - radius, w / 2 + radius, h / 2 + radius), fill=255)
    else:
        offset = int((w + h) * eased)
        draw.polygon([(0, 0), (offset, 0), (0, offset)], fill=255)
        draw.polygon([(w, h), (w - offset, h), (w, h - offset)], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(6))
    base = outgoing if outgoing is not None else Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(incoming, base, mask)


def _tr_blur_dip(incoming, outgoing, progress, params, ctx):
    max_blur = float(params.get("max_blur", 18))
    amount = max_blur * math.sin(math.pi * clamp01(progress))
    base = incoming
    if outgoing is not None and progress < 0.5:
        base = Image.blend(outgoing, incoming, clamp01(progress * 2))
    return base.filter(ImageFilter.GaussianBlur(amount / 2)) if amount > 0.6 else base


def _tr_white_flash(incoming, outgoing, progress, params, ctx):
    peak = float(params.get("peak", 0.85))
    amount = peak * math.sin(math.pi * clamp01(progress))
    if amount < 0.02:
        return incoming
    white = Image.new("RGB", incoming.size, (255, 255, 255))
    return Image.blend(incoming, white, clamp01(amount))


def _zoom_crop(img: Image.Image, scale: float) -> Image.Image:
    """Наезд: scale>1 вырезает центр. Как zoom_punch, без letterbox."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    scale = max(1.0, float(scale))
    if abs(scale - 1.0) < 1e-3:
        return rgb
    win_w, win_h = w / scale, h / scale
    box = ((w - win_w) / 2, (h - win_h) / 2, (w + win_w) / 2, (h + win_h) / 2)
    return rgb.resize((w, h), Image.Resampling.BILINEAR, box=box)


def _tr_cinematic_zoom(incoming, outgoing, progress, params, ctx):
    """From зумит наружу, to — внутрь из tight, RGB-сдвиг по радиусу.

    Каталог — WebGL 12 семплов. Здесь crop-zoom, mix и лёгкий blur к середине.
    """
    p = clamp01(progress)
    eased = 2 * p * p if p < 0.5 else 1 - ((-2 * p + 2) ** 2) / 2
    from_scale = float(params.get("from_scale", 1.16))
    to_frame = _zoom_crop(incoming, from_scale + (1.0 - from_scale) * eased)
    if outgoing is not None:
        from_frame = _zoom_crop(outgoing, 1.0 + 0.14 * eased)
        mixed = Image.blend(from_frame, to_frame, eased)
    else:
        mixed = to_frame
    blur_amt = 8.0 * math.sin(math.pi * eased)
    if blur_amt > 0.6:
        mixed = mixed.filter(ImageFilter.GaussianBlur(blur_amt / 2.5))
    fringe = 0.045 * math.sin(math.pi * eased)
    if fringe > 0.004:
        red = _zoom_crop(mixed, 1.0 + fringe * 1.06)
        blue = _zoom_crop(mixed, 1.0 + fringe * 0.94)
        mixed = Image.merge("RGB", (red.split()[0], mixed.split()[1], blue.split()[2]))
    return mixed


def _horizon_darken(img: Image.Image, amount: float) -> Image.Image:
    """Затемнение к центру — event horizon без шейдера."""
    if amount < 0.02:
        return img.convert("RGB")
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w = arr.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    cx, cy = w / 2.0, h / 2.0
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    maxd = math.hypot(cx, cy) or 1.0
    falloff = np.clip(dist / (maxd * 0.38), 0.0, 1.0)
    factor = 1.0 - amount * (1.0 - falloff)
    arr *= factor[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _tr_gravitational_lens(incoming, outgoing, progress, params, ctx):
    """From затягивает к центру, to выходит из well, RGB-сдвиг.

    Каталог — WebGL warp + horizon. Здесь crop-zoom, mix smoothstep и затемнение.
    """
    p = clamp01(progress)
    eased = 2 * p * p if p < 0.5 else 1 - ((-2 * p + 2) ** 2) / 2
    from_scale = float(params.get("from_scale", 1.14))
    to_frame = _zoom_crop(incoming, from_scale + (1.0 - from_scale) * eased)
    if outgoing is not None:
        from_frame = _zoom_crop(outgoing, 1.0 + 0.32 * eased)
        mix_t = 0.0 if eased < 0.3 else (1.0 if eased > 0.9 else (eased - 0.3) / 0.6)
        mixed = Image.blend(from_frame, to_frame, mix_t)
    else:
        mixed = to_frame
    mixed = _horizon_darken(mixed, 0.62 * math.sin(math.pi * eased))
    fringe = 0.05 * math.sin(math.pi * eased)
    if fringe > 0.004:
        red = _zoom_crop(mixed, 1.0 + fringe * 1.08)
        blue = _zoom_crop(mixed, 1.0 + fringe * 0.92)
        mixed = Image.merge("RGB", (red.split()[0], mixed.split()[1], blue.split()[2]))
    return mixed


def _aces_tonemap(arr: np.ndarray) -> np.ndarray:
    """ACES filmic, как в шейдере light-leak каталога."""
    return np.clip(
        (arr * (2.51 * arr + 0.03)) / (arr * (2.43 * arr + 0.59) + 0.14),
        0.0, 1.0)


def _tr_light_leak(incoming, outgoing, progress, params, ctx):
    """Тёплый Beer-Lambert засвет сверху-справа и mix. Без WebGL."""
    p = clamp01(progress)
    eased = 2 * p * p if p < 0.5 else 1 - ((-2 * p + 2) ** 2) / 2
    a = np.asarray(incoming.convert("RGB"), dtype=np.float32) / 255.0
    h, w = a.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    uv_x = xx / max(w - 1, 1)
    uv_y = yy / max(h - 1, 1)
    dist = np.sqrt((uv_x - 1.3) ** 2 + (uv_y + 0.2) ** 2)
    leak = np.clip(np.exp(-dist * 1.8) * eased * 4.0, 0.0, 1.0)
    t = np.clip(dist * 0.7, 0.0, 1.0)[..., None]
    warm = (np.array([1.0, 0.5, 0.15], dtype=np.float32) * (1.0 - t)
            + np.array([1.0, 0.9, 0.75], dtype=np.float32) * t)
    flare = np.exp(-np.abs(uv_y - (-0.2 + uv_x * 0.3)) * 15.0) * leak * 0.3
    over = (a + warm * leak[..., None] * 3.0
            + np.array([1.0, 0.8, 0.5], dtype=np.float32) * flare[..., None])
    over = _aces_tonemap(over)
    if outgoing is not None:
        b = np.asarray(outgoing.convert("RGB"), dtype=np.float32) / 255.0
        mix_t = 0.0 if eased < 0.15 else (
            1.0 if eased > 0.85 else (eased - 0.15) / 0.70)
        over = over * (1.0 - mix_t) + b * mix_t
    return Image.fromarray(np.clip(over * 255.0, 0, 255).astype(np.uint8))


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0 + 1e-12), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _tr_sdf_iris(incoming, outgoing, progress, params, ctx):
    """Круг SDF из центра, три кольца glow. Без WebGL."""
    p = clamp01(progress)
    eased = 2 * p * p if p < 0.5 else 1 - ((-2 * p + 2) ** 2) / 2
    a = np.asarray(incoming.convert("RGB"), dtype=np.float32) / 255.0
    h, w = a.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    uv_x = (xx / max(w - 1, 1) - 0.5) * (w / max(h, 1))
    uv_y = yy / max(h - 1, 1) - 0.5
    dist = np.sqrt(uv_x ** 2 + uv_y ** 2)
    radius = eased * 1.2
    fw = 0.003
    edge = _smoothstep(radius + fw, radius - fw, dist)
    if outgoing is not None:
        b = np.asarray(outgoing.convert("RGB"), dtype=np.float32) / 255.0
        mixed = a * (1.0 - edge[..., None]) + b * edge[..., None]
    else:
        mixed = a
    ring1 = np.exp(-np.abs(dist - radius) * 25.0)
    ring2 = np.exp(-np.abs(dist - radius + 0.04) * 20.0) * 0.5
    ring3 = np.exp(-np.abs(dist - radius + 0.08) * 15.0) * 0.25
    glow = (ring1 + ring2 + ring3) * eased * (1.0 - eased) * 4.0
    warm = np.array([1.0, 0.85, 0.6], dtype=np.float32)
    mixed = mixed + warm * glow[..., None] * 0.6
    return Image.fromarray(np.clip(mixed * 255.0, 0, 255).astype(np.uint8))


def _tr_thermal_distortion(incoming, outgoing, progress, params, ctx):
    """Heat shimmer снизу и тёплый haze. Без WebGL / FBM."""
    p = clamp01(progress)
    eased = 2 * p * p if p < 0.5 else 1 - ((-2 * p + 2) ** 2) / 2
    src_a = outgoing if outgoing is not None else incoming
    a = np.asarray(src_a.convert("RGB"), dtype=np.float32) / 255.0
    b = np.asarray(incoming.convert("RGB"), dtype=np.float32) / 255.0
    h, w = a.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    uv_x = xx / max(w - 1, 1)
    uv_y = yy / max(h - 1, 1)
    y_fade = _smoothstep(0.08, 1.0, uv_y)
    heat = eased * 1.5
    shimmer = np.sin(uv_y * 40.0 + np.sin(uv_x * 18.0 + eased * 8.0) * 2.0 + eased * 6.0)
    disp = np.rint(shimmer * heat * 0.03 * y_fade * w).astype(np.int32)
    src_x = np.clip(xx + disp, 0, w - 1)
    warped_a = np.take_along_axis(a, src_x[..., None], axis=1)
    inv = np.sin(uv_y * 40.0 + np.sin(uv_x * 18.0 + 3.0) * 2.0 + eased * 6.0)
    disp2 = np.rint(inv * (1.0 - eased) * 0.03 * y_fade * w).astype(np.int32)
    src_x2 = np.clip(xx + disp2, 0, w - 1)
    warped_b = np.take_along_axis(b, src_x2[..., None], axis=1)
    mixed = warped_a * (1.0 - eased) + warped_b * eased
    haze = heat * y_fade * 0.15 * (1.0 - eased)
    warm = np.array([1.0, 0.9, 0.7], dtype=np.float32)
    mixed = mixed + warm * haze[..., None]
    return Image.fromarray(np.clip(mixed * 255.0, 0, 255).astype(np.uint8))


def _tr_whip_pan_shader(incoming, outgoing, progress, params, ctx):
    """Горизонтальный whip с 10 семплами направленного смаза. Без WebGL."""
    p = clamp01(progress)
    eased = 2 * p * p if p < 0.5 else 1 - ((-2 * p + 2) ** 2) / 2
    src_a = outgoing if outgoing is not None else incoming
    a = np.asarray(src_a.convert("RGB"), dtype=np.float32)
    b = np.asarray(incoming.convert("RGB"), dtype=np.float32)
    _h, w = a.shape[:2]
    n = 10
    from_off = eased * 1.5
    to_off = (1.0 - eased) * 1.5
    cols = np.arange(w)
    from_acc = np.zeros_like(a)
    to_acc = np.zeros_like(b)
    for i in range(n):
        f = float(i)
        from_shift = int(round((from_off + eased * 0.08 * f) * w))
        to_shift = int(round((to_off + (1.0 - eased) * 0.08 * f) * w))
        from_acc += a[:, np.clip(cols + from_shift, 0, w - 1)]
        to_acc += b[:, np.clip(cols - to_shift, 0, w - 1)]
    mixed = from_acc / n * (1.0 - eased) + to_acc / n * eased
    return Image.fromarray(np.clip(mixed, 0, 255).astype(np.uint8))


def _tr_mk_clone_wall(incoming, outgoing, progress, params, ctx):
    """Бумага и инверсия: стенка слов в HTML; здесь paper wipe без WebGL."""
    p = clamp01(progress)
    eased = 2 * p * p if p < 0.5 else 1 - ((-2 * p + 2) ** 2) / 2
    src_a = outgoing if outgoing is not None else incoming
    a = np.asarray(src_a.convert("RGB"), dtype=np.float32)
    b = np.asarray(incoming.convert("RGB"), dtype=np.float32)
    paper = np.array([255.0, 255.0, 255.0], dtype=np.float32)
    ink = np.array([29.0, 29.0, 31.0], dtype=np.float32)
    if eased < 0.4:
        t = eased / 0.4
        mixed = a * (1.0 - t) + paper * t
    elif eased < 0.7:
        t = (eased - 0.4) / 0.3
        mixed = paper * (1.0 - t) + ink * t
    else:
        t = (eased - 0.7) / 0.3
        mixed = ink * (1.0 - t) + b * t
    return Image.fromarray(np.clip(mixed, 0, 255).astype(np.uint8))


def _tr_transitions_3d(incoming, outgoing, progress, params, ctx):
    """Card flip stand-in: navy → terracotta через ребро. Без rotationY."""
    p = clamp01(progress)
    eased = 2 * p * p if p < 0.5 else 1 - ((-2 * p + 2) ** 2) / 2
    src_a = outgoing if outgoing is not None else incoming
    a = np.asarray(src_a.convert("RGB"), dtype=np.float32)
    b = np.asarray(incoming.convert("RGB"), dtype=np.float32)
    navy = np.array([27.0, 38.0, 59.0], dtype=np.float32)
    terra = np.array([224.0, 122.0, 95.0], dtype=np.float32)
    if eased < 0.5:
        t = eased / 0.5
        mixed = a * (1.0 - t) + navy * t
    else:
        t = (eased - 0.5) / 0.5
        mixed = terra * (1.0 - t) + b * t
    return Image.fromarray(np.clip(mixed, 0, 255).astype(np.uint8))


def _tr_transitions_blur(incoming, outgoing, progress, params, ctx):
    """Blur through stand-in: navy → terracotta через GaussianBlur. Без tween filter."""
    p = clamp01(progress)
    src_a = outgoing if outgoing is not None else incoming
    a = np.asarray(src_a.convert("RGB"), dtype=np.float32)
    b = np.asarray(incoming.convert("RGB"), dtype=np.float32)
    navy = np.array([27.0, 38.0, 59.0], dtype=np.float32)
    terra = np.array([224.0, 122.0, 95.0], dtype=np.float32)
    if p < 0.5:
        t = p / 0.5
        eased = t * t
        mixed = a * (1.0 - eased) + navy * eased
        blur = 7.5 * eased
    else:
        t = (p - 0.5) / 0.5
        eased = 1 - (1 - t) * (1 - t)
        mixed = terra * (1.0 - eased) + b * eased
        blur = 7.5 * (1.0 - eased)
    img = Image.fromarray(np.clip(mixed, 0, 255).astype(np.uint8))
    if blur > 0.6:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return img


def _tr_light_sweep(incoming, outgoing, progress, params, ctx):
    from .layers import light_sweep

    frame = incoming.convert("RGBA")
    frame.alpha_composite(light_sweep(ctx, progress))
    return frame.convert("RGB")


def _tr_glitch(incoming, outgoing, progress, params, ctx):
    from .layers import glitch_bars

    frame = incoming.convert("RGBA")
    frame.alpha_composite(glitch_bars(ctx, progress, seed=int(params.get("seed", 0))))
    return frame.convert("RGB")


def _tr_glitch_shader(incoming, outgoing, progress, params, ctx):
    """Scan lines stand-in: RGB-сдвиг, mix и flicker — без WebGL."""
    from PIL import ImageChops

    p = clamp01(progress)
    eased = 2 * p * p if p < 0.5 else 1 - ((-2 * p + 2) ** 2) / 2
    inten = eased * (1.0 - eased) * 4.0
    seed = int(params.get("seed", 0))
    src = incoming.convert("RGB")
    w, _h = src.size
    shift = max(0, int(round(w * 0.035 * inten)))
    if shift:
        red, green, blue = src.split()
        red = ImageChops.offset(red, shift, 0)
        blue = ImageChops.offset(blue, -shift, 0)
        src = Image.merge("RGB", (red, green, blue))
    if outgoing is not None:
        src = Image.blend(src, outgoing.convert("RGB"), eased)
    flick = 1.0 + ((((seed * 23 + int(eased * 11)) % 100) / 100.0) - 0.5) * 0.3 * inten
    if abs(flick - 1.0) > 0.01:
        src = src.point(lambda v, f=flick: max(0, min(255, int(v * f))))
    return src


TRANSITIONS: dict[str, TransitionFn] = {
    "cut": _tr_cut,
    "zoom_punch": _tr_zoom_punch,
    "whip_pan": _tr_whip_pan,
    "whip_pan_shader": _tr_whip_pan_shader,
    "mk_clone_wall": _tr_mk_clone_wall,
    "transitions_3d": _tr_transitions_3d,
    "transitions_blur": _tr_transitions_blur,
    "paper_slide": _tr_paper_slide,
    "mask_wipe": _tr_mask_wipe,
    "blur_dip": _tr_blur_dip,
    "white_flash": _tr_white_flash,
    "light_sweep": _tr_light_sweep,
    "glitch": _tr_glitch,
    "glitch_shader": _tr_glitch_shader,
    "cinematic_zoom": _tr_cinematic_zoom,
    "gravitational_lens": _tr_gravitational_lens,
    "light_leak": _tr_light_leak,
    "sdf_iris": _tr_sdf_iris,
    "thermal_distortion": _tr_thermal_distortion,
}


# --- композитор ---------------------------------------------------------------

@dataclass
class RenderStats:
    frames: int = 0
    duration_sec: float = 0.0
    shots: int = 0
    overlay_draws: int = 0
    safe_zone_violations: list[dict[str, Any]] = field(default_factory=list)
    accent_share_max: float = 0.0
    subtitle_frames: int = 0
    speech_frames: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames": self.frames, "duration_sec": round(self.duration_sec, 3),
            "shots": self.shots, "overlay_draws": self.overlay_draws,
            "safe_zone_violations": self.safe_zone_violations,
            "accent_share_max": round(self.accent_share_max, 4),
            "subtitle_frames": self.subtitle_frames,
            "speech_frames": self.speech_frames,
        }


class Compositor:
    """Собирает кадры по edit-плану и пишет их в энкодер."""

    def __init__(self, ctx: Ctx, cfg, *, overlay_renderer: Callable | None = None) -> None:
        self.ctx = ctx
        self.cfg = cfg
        self.overlay_renderer = overlay_renderer
        self.stats = RenderStats()

    def _encoder(self, out_path: Path, audio_path: Path | None, duration: float
                 ) -> subprocess.Popen:
        render = self.cfg.get("render")
        args = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{self.ctx.width}x{self.ctx.height}",
                "-r", str(self.ctx.fps), "-i", "-"]
        if audio_path is not None:
            args += ["-i", str(audio_path)]
        args += [
            "-c:v", str(render.get("video_codec", "libx264")),
            "-profile:v", str(render.get("profile", "high")),
            "-preset", str(render.get("preset", "medium")),
            "-crf", str(render.get("crf", 19)),
            "-pix_fmt", str(render.get("pix_fmt", "yuv420p")),
            "-color_primaries", str(render.get("color_primaries", "bt709")),
            "-color_trc", "bt709", "-colorspace", "bt709",
            "-r", str(self.ctx.fps),
        ]
        if audio_path is not None:
            args += ["-c:a", str(render.get("audio_codec", "aac")),
                     "-b:a", str(render.get("audio_bitrate", "224k")),
                     "-ar", "48000", "-ac", "2", "-shortest"]
        if render.get("faststart", True):
            args += ["-movflags", "+faststart"]
        args += ["-t", f"{duration:.3f}", str(out_path)]
        return subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def render(self, plan: dict[str, Any], out_path: Path,
               audio_path: Path | None = None) -> RenderStats:
        fps = self.ctx.fps
        duration = float(plan["duration_sec"])
        total_frames = int(round(duration * fps))
        shots = plan["shots"]
        self.stats.shots = len(shots)
        self.stats.duration_sec = duration

        sources: dict[int, FrameSource] = {}
        for index, shot in enumerate(shots):
            if shot.get("file"):
                sources[index] = FrameSource(Path(shot["file"]), self.ctx.size, fps)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        encoder = self._encoder(out_path, audio_path, duration)
        assert encoder.stdin is not None

        shot_index = 0
        last_frame_of_prev: Image.Image | None = None
        try:
            for frame_no in range(total_frames):
                t = frame_no / fps
                while (shot_index + 1 < len(shots)
                       and t >= float(shots[shot_index]["end"]) - 1e-9):
                    last_frame_of_prev = self._current_still
                    shot_index += 1
                shot = shots[shot_index]

                frame = self._shot_frame(shot, shot_index, t, sources)
                frame = self._apply_transition(shot, frame, last_frame_of_prev, t)
                self._current_still = frame

                if self.overlay_renderer is not None:
                    frame = self.overlay_renderer(frame, t, frame_no, self.stats)

                encoder.stdin.write(frame.tobytes())
                self.stats.frames += 1
        finally:
            try:
                encoder.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            stderr = b""
            if encoder.stderr is not None:
                stderr = encoder.stderr.read()
            code = encoder.wait()
            for source in sources.values():
                source.close()
            if code != 0:
                raise RenderError("энкодер завершился с ошибкой",
                                  code_returned=code,
                                  stderr=stderr.decode("utf-8", "replace")[-2000:])
        return self.stats

    _current_still: Image.Image | None = None

    def _shot_frame(self, shot: dict[str, Any], index: int, t: float,
                    sources: dict[int, FrameSource]) -> Image.Image:
        start = float(shot["start"])
        end = float(shot["end"])
        local = clamp01((t - start) / max(end - start, 1e-6))

        source = sources.get(index)
        if source is None:
            # Слот без видеоряда (полноэкранный текст) рисуется целиком графикой.
            return self._generated_frame(shot, local)

        frame = source.next_frame()
        kb = shot.get("kenburns")
        if kb:
            zoom, sx, sy = kenburns_window(
                local, zoom_from=float(kb.get("zoom", [1.0, 1.1])[0]),
                zoom_to=float(kb.get("zoom", [1.0, 1.1])[1]),
                pan=kb.get("pan", (0.0, 0.0)),
                easing_fn=lambda p: ease("ease_out_cubic", p, self.ctx.brandbook))
            frame = apply_kenburns(frame, zoom, sx, sy, self.ctx.size)
        elif frame.size != self.ctx.size:
            frame = frame.resize(self.ctx.size, Image.Resampling.BILINEAR)
        return frame

    def _generated_frame(self, shot: dict[str, Any], local: float) -> Image.Image:
        from .layers import fullscreen_text

        if shot.get("kind") == "fullscreen_text":
            layer = fullscreen_text(
                self.ctx, shot.get("content", ""), progress=local,
                style=shot.get("template", "text-fullscreen/impact-01"),
                accent_word=shot.get("accent_word"),
                invert=bool(shot.get("invert")))
            return layer.convert("RGB")
        return Image.new("RGB", self.ctx.size, self.ctx.color("bg_light")[:3])

    def _apply_transition(self, shot: dict[str, Any], frame: Image.Image,
                          previous: Image.Image | None, t: float) -> Image.Image:
        transition = shot.get("transition")
        if not transition or transition.get("renderer") in (None, "cut"):
            return frame
        start = float(shot["start"])
        length = float(transition.get("duration", 0.22))
        if length <= 0 or t > start + length:
            return frame
        progress = clamp01((t - start) / length)
        fn = TRANSITIONS.get(str(transition.get("renderer")), _tr_cut)
        return fn(frame, previous, progress, transition.get("params", {}), self.ctx)
