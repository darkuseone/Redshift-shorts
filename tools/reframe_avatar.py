#!/usr/bin/env python3
"""Ландшафтный клип аватара → вертикальный кадр 1080×1920.

Луки HeyGen со студийной обстановкой отдаются в 16:9: в кадре стол, микрофон и
руки — ровно то, что просил заказчик показать. Конвейер же работает с 1080×1920,
и просто растянуть одно в другое нельзя.

Окно кадрирования считается по **измеренной голове**, а не по середине кадра:
ведущий в студийном луке стоит не по центру, и обрезка по середине срезала бы
ему плечо. Голова ставится левее середины — правую треть вертикального кадра
занимает колонка интерфейса (§3.2), и держать лицо под ней незачем.

Запас над макушкой добавляется прозрачными полями, а не обрезкой: в исходнике
макушка почти касается верхней кромки, а приёмам «за головой» нужно место.
Поле прозрачное, поэтому в кадре его занимает сцена, а не чёрная полоса.

Запуск: python tools/reframe_avatar.py in.webm out.webm
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.lib.ffmpeg import ffmpeg_bin, head_box, probe    # noqa: E402

FRAME_W, FRAME_H = 1080, 1920

# Доля кадра над макушкой. Меньше — приёму «за головой» некуда встать, больше —
# ведущий проваливается вниз и перестаёт быть главным в кадре.
HEADROOM = 0.12
# Где по горизонтали стоит центр головы. Правая треть — колонка интерфейса.
HEAD_AT = 0.43


def plan(src: Path, *, at_sec: float = 3.0) -> dict[str, int]:
    """Окно кадрирования по измеренной голове."""
    info = probe(src)
    sw, sh = int(info.width), int(info.height)
    box = head_box(src, at_sec=at_sec)
    head_cx = (box[0] + box[2]) // 2 if box else sw // 2

    top = int(FRAME_H * HEADROOM)
    height = FRAME_H - top
    # Ширина окна — из подобия: вырезанный кусок ляжет в 1080 на height.
    width = min(sw, int(round(sh * FRAME_W / height)))
    scale = FRAME_W / width

    # Центр окна — такой, чтобы голова встала в HEAD_AT от левого края.
    x0 = int(round(head_cx - FRAME_W * HEAD_AT / scale))
    x0 = max(0, min(sw - width, x0))
    return {"x0": x0, "width": width, "height": sh, "top": top,
            "scaled_h": height, "head_cx": head_cx}


def reframe(src: Path, dst: Path, *, at_sec: float = 3.0) -> dict[str, int]:
    p = plan(src, at_sec=at_sec)
    # Альфа обязана дожить до выхода: pad заливает прозрачным, а не чёрным,
    # и кодек на выходе тот же vp9 с yuva420p.
    vf = (f"crop={p['width']}:{p['height']}:{p['x0']}:0,"
          f"scale={FRAME_W}:{p['scaled_h']}:flags=lanczos,"
          f"pad={FRAME_W}:{FRAME_H}:0:{p['top']}:color=#00000000")
    args = [ffmpeg_bin(), "-v", "error", "-y", "-c:v", "libvpx-vp9", "-i", str(src),
            "-vf", vf, "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
            "-b:v", "0", "-crf", "24", "-row-mt", "1",
            "-c:a", "libopus", "-b:a", "128k", str(dst)]
    subprocess.run(args, check=True)
    return p


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", type=Path)
    parser.add_argument("dst", type=Path)
    parser.add_argument("--at", type=float, default=3.0,
                        help="секунда, на которой меряется голова")
    args = parser.parse_args()

    p = reframe(args.src, args.dst, at_sec=args.at)
    print(f"окно {p['width']}×{p['height']} от x={p['x0']} "
          f"(центр головы {p['head_cx']}), поле сверху {p['top']} px")
    print(f"готово: {args.dst} ({args.dst.stat().st_size // 1024} КБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
