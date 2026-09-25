#!/usr/bin/env python3
"""«Всратая» стикерная анимация поверх реального кадра → mp4 9:16 для таймлайна.

Заказчик 22.09: героя-кота показывать не съёмкой, а нарисованной картинкой,
как гифка, и анимировать нарочно дёшево — рывками. Инструмент общий: любой
вырезанный стикер (PNG с альфой) и любой фон (фото/кадр NASA и т.п.).

Режимы:
  fall     — стикер крутится и по спирали уменьшается к точке (чёрная дыра)
  stretch  — стикер тянет в «макаронину» к точке: узкий и длинный
  float    — стикер болтается и медленно вращается в невесомости

Смена картинки по ходу (заказчик 24.09): --swap-sticker cat_x.png --swap-at 0.7 —
падает кот с круглыми глазами, внутри дыры глаза уже крестиками. Вращение
равномерное (--spins оборотов за клип), рывками — видно каждый шаг, как гифка.

    python tools/sticker_anim.py fall --sticker cat.png --bg smbh.jpg \\
        --target 0.52,0.68 --sec 4 --out assets/footage/director/<id>/cat_fall.mp4

Движение стикера квантуется до --step-fps (по умолчанию 10) — «гифочность»;
фон едет плавно с наездом Ken Burns. Результат идёт в director.footage как
обычный футаж (license = лицензия стикера, source = откуда стикер).
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image

W, H, FPS = 1080, 1920, 30


def _bg_frame(bg: Image.Image, target: tuple[float, float], t: float, zoom_to: float) -> Image.Image:
    """Кадр фона 9:16 с наездом к цели."""
    bw, bh = bg.size
    scale = max(W / bw, H / bh) * (1.0 + (zoom_to - 1.0) * t)
    sw, sh = int(bw * scale), int(bh * scale)
    img = bg.resize((sw, sh), Image.LANCZOS)
    cx, cy = target[0] * sw, target[1] * sh
    x0 = int(min(max(cx - W / 2, 0), sw - W))
    y0 = int(min(max(cy - H / 2, 0), sh - H))
    return img.crop((x0, y0, x0 + W, y0 + H)), (cx - x0, cy - y0)


def _ease_in(t: float) -> float:
    return t * t


def render(mode: str, sticker: Path, bg_path: Path, target: tuple[float, float],
           sec: float, out: Path, step_fps: int, spins: float, seed: int,
           swap: Path | None = None, swap_at: float = 1.0, turns: float = 0.0,
           scale: float = 1.0, pos: tuple[float, float] = (0.5, 0.45)) -> None:
    st0 = Image.open(sticker).convert("RGBA")
    st1 = Image.open(swap).convert("RGBA") if swap else st0
    bg = Image.open(bg_path).convert("RGB")
    n = int(sec * FPS)
    tmp = out.with_suffix(".frames")
    tmp.mkdir(parents=True, exist_ok=True)
    base_w = int(W * 0.78 * scale)
    for i in range(n):
        t_smooth = i / max(n - 1, 1)
        # Стикер двигается рывками: время квантуется до step_fps.
        q = math.floor(i * step_fps / FPS) / (sec * step_fps)
        q = min(max(q, 0.0), 1.0)
        frame, (tx, ty) = _bg_frame(bg, target, t_smooth, 1.18)
        frame = frame.convert("RGBA")
        wob = math.sin((i // max(FPS // step_fps, 1)) * 2.1 + seed) * 6
        st = st1 if q >= swap_at else st0
        if mode == "fall":
            k = _ease_in(q)
            # Размер падает равномерно с первого кадра (заказчик 24.09: «чем
            # ближе к дыре, тем меньше»); по ease кот до середины оставался
            # крупным и схлопывался только у самого горизонта.
            size = base_w * (1.0 - 0.94 * q)
            # Вращение равномерное, не по ease: разгон к концу читался как
            # мельтешение, а заказчик хочет видеть каждый поворот.
            ang = 360 * spins * q + wob
            k = q ** 1.3   # путь к дыре — почти равномерный, лёгкий разгон
            radius = (1.0 - k) * W * 0.28
            phi = 2 * math.pi * 1.25 * k + seed
            cx = tx + radius * math.cos(phi) * (1.0 - k * 0.3)
            cy = ty - (1.0 - k) * H * 0.34 + radius * math.sin(phi) * 0.35
            sx, sy = size, size * st.height / st.width
            alpha = 1.0 if k < 0.9 else max(0.0, (1.0 - k) / 0.1)
        elif mode == "stretch":
            k = _ease_in(q)
            sx = base_w * (0.95 - 0.62 * k)
            sy = base_w * st.height / st.width * (0.85 + 1.5 * k)
            ang = math.degrees(math.atan2(tx - W / 2, ty + H)) * k + wob
            cx = W / 2 + (tx - W / 2) * (0.4 + 0.5 * k)
            cy = H * 0.42 + (ty - H * 0.42) * 0.8 * k + sy * 0.12 * k
            alpha = 1.0
        else:  # float
            sx = base_w * 0.8
            sy = sx * st.height / st.width
            ang = math.sin(q * math.pi * 2) * 18 + wob * 2 + 360 * turns * q
            cx = W * pos[0] + math.sin(q * math.pi * 3 + seed) * 60 * scale
            cy = H * pos[1] + math.cos(q * math.pi * 2) * 70 * scale
            alpha = 1.0
        spr = st.resize((max(2, int(sx)), max(2, int(sy))), Image.LANCZOS)
        spr = spr.rotate(ang, resample=Image.BICUBIC, expand=True)
        if alpha < 1.0:
            a = spr.getchannel("A").point(lambda v, al=alpha: int(v * al))
            spr.putalpha(a)
        frame.alpha_composite(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2)))
        frame.convert("RGB").save(tmp / f"f{i:05d}.jpg", quality=90)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", str(tmp / "f%05d.jpg"), "-c:v", "libx264", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)
    for f in tmp.glob("*.jpg"):
        f.unlink()
    tmp.rmdir()
    print(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("mode", choices=("fall", "stretch", "float"))
    p.add_argument("--sticker", required=True)
    p.add_argument("--bg", required=True)
    p.add_argument("--target", default="0.5,0.5", help="точка притяжения на фоне, доли x,y")
    p.add_argument("--sec", type=float, default=4.0)
    p.add_argument("--step-fps", type=int, default=10, help="«гифочность» движения стикера")
    p.add_argument("--spins", type=float, default=4.0, help="обороты в режиме fall")
    p.add_argument("--seed", type=float, default=0.0)
    p.add_argument("--swap-sticker", help="картинка, которая сменит стикер по ходу")
    p.add_argument("--swap-at", type=float, default=0.7, help="доля клипа, где сменить")
    p.add_argument("--turns", type=float, default=0.0, help="обороты в режиме float")
    p.add_argument("--scale", type=float, default=1.0, help="размер стикера, доля от базового")
    p.add_argument("--pos", default="0.5,0.45", help="центр стикера в режиме float, доли x,y")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    tx, ty = (float(v) for v in a.target.split(","))
    render(a.mode, Path(a.sticker), Path(a.bg), (tx, ty), a.sec, Path(a.out),
           a.step_fps, a.spins, a.seed,
           Path(a.swap_sticker) if a.swap_sticker else None, a.swap_at, a.turns,
           a.scale, tuple(float(v) for v in a.pos.split(",")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
