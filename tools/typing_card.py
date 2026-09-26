#!/usr/bin/env python3
"""Окно с формулой, которое печатается по буквам → mp4 9:16 для таймлайна.

Заказчик 25.09 (0052): вместо карточки «БЫСТРО ГРУСТНО БЕЗ ШАНСОВ» — «график
или формулу показать там в браузере». Шаблоны каталога (code-typing,
notepad-typing, terminal-simulator) в вертикальном кадре выходят мелким окном
в углу: текст не читается с телефона. Этот инструмент рисует окно на всю
ширину, крупным моноширинным кеглем, в палитре канала, поверх затемнённого
кадра того же блока (правило «один фон на блок»).

Стиль ``editor`` — окно редактора с именем файла, ``browser`` — окно браузера
с адресом и заголовком страницы. Строка — куски ``цвет:текст`` через ``|``:

    python tools/typing_card.py --style editor --title tidal.py \\
        --line "#8B98A9:# кот 0,5 м · дыра в |#36EFFF:10|#8B98A9: Солнц" \\
        --line "#FFFFFF:Δa = c⁶·L / (4·G²·M²)" \\
        --line "#FFFFFF:Δa = |#D7263D:5 000 000 g" \\
        --bg tde.jpg --sec 3 --out assets/footage/director/<id>/formula.mp4

Результат идёт в ``director.footage`` как обычный футаж
(``source: redshift``, ``license: generated-owned``, не ИИ).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, H, FPS = 1080, 1920, 30
BG = (10, 10, 11)
PANEL = (17, 19, 24)
BAR = (27, 30, 37)
MUTED = (139, 152, 169)
WHITE = (255, 255, 255)
RED = (215, 38, 61)
CYAN = (54, 239, 255)
MONO = ROOT / "assets" / "fonts" / "JetBrainsMono-Bold.ttf"
DISPLAY = ROOT / "assets" / "fonts" / "Oswald-Bold.ttf"
CHARS_PER_SEC = 30.0
ENTER_SEC = 0.25


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def parse_line(spec: str) -> list[tuple[str, tuple[int, int, int]]]:
    """``#RRGGBB:текст|#RRGGBB:текст`` → [(текст, цвет)]; без цвета — белый."""
    out: list[tuple[str, tuple[int, int, int]]] = []
    for part in spec.split("|"):
        if part.startswith("#") and ":" in part[:8]:
            color, text = part.split(":", 1)
            out.append((text, _hex(color)))
        else:
            out.append((part, WHITE))
    return out


def _background(path: Path | None) -> Image.Image:
    if path is None:
        return Image.new("RGB", (W, H), BG)
    img = Image.open(path).convert("RGB")
    scale = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    x0, y0 = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((x0, y0, x0 + W, y0 + H)).filter(ImageFilter.GaussianBlur(10))
    return Image.blend(img, Image.new("RGB", (W, H), BG), 0.72)


def render(lines: list[list[tuple[str, tuple[int, int, int]]]], *, style: str, title: str,
           heading: str, bg: Path | None, sec: float, out: Path, font_px: int = 56) -> Path:
    mono = ImageFont.truetype(str(MONO), font_px)
    small = ImageFont.truetype(str(MONO), 28)
    head = ImageFont.truetype(str(DISPLAY), 52)
    base = _background(bg)
    card_x0, card_x1 = 48, W - 48
    pad = 44
    bar_h = 76
    line_h = int(font_px * 1.5)
    head_h = 96 if (style == "browser" and heading) else 0
    body_h = pad * 2 + head_h + line_h * len(lines)
    card_h = bar_h + body_h
    # Окно — над зоной субтитров (базовая линия 1280): верх около трети кадра.
    card_y0 = max(260, int(H * 0.60) - card_h)
    total_chars = sum(len(t) for line in lines for t, _c in line)
    frames = int(round(sec * FPS))
    tmp = out.with_suffix(".frames")
    tmp.mkdir(parents=True, exist_ok=True)
    for i in range(frames):
        t = i / FPS
        frame = base.copy()
        d = ImageDraw.Draw(frame, "RGBA")
        k = min(1.0, t / ENTER_SEC)
        dy = int((1 - k) * 40)
        alpha = int(255 * k)
        y0 = card_y0 + dy
        d.rounded_rectangle([card_x0, y0, card_x1, y0 + card_h], 28, fill=(*PANEL, alpha),
                            outline=(255, 255, 255, int(40 * k)), width=2)
        d.rounded_rectangle([card_x0, y0, card_x1, y0 + bar_h], 28, fill=(*BAR, alpha))
        d.rectangle([card_x0, y0 + bar_h - 28, card_x1, y0 + bar_h], fill=(*BAR, alpha))
        for j, col in enumerate((RED, (255, 255, 255, 90), (255, 255, 255, 90))):
            cx = card_x0 + 40 + j * 34
            fill = (*col[:3], alpha if len(col) == 3 else int(col[3] * k))
            d.ellipse([cx - 10, y0 + bar_h / 2 - 10, cx + 10, y0 + bar_h / 2 + 10], fill=fill)
        if style == "browser":
            pill = [card_x0 + 150, y0 + 16, card_x1 - 32, y0 + bar_h - 16]
            d.rounded_rectangle(pill, 22, fill=(10, 10, 11, alpha))
            d.text((pill[0] + 26, (pill[1] + pill[3]) / 2), title, font=small,
                   fill=(*MUTED, alpha), anchor="lm")
        else:
            d.text(((card_x0 + card_x1) / 2, y0 + bar_h / 2), title, font=small,
                   fill=(*MUTED, alpha), anchor="mm")
        # Набор: сколько знаков уже «напечатано» к моменту t.
        typed = int(max(0.0, t - ENTER_SEC) * CHARS_PER_SEC)
        y = y0 + bar_h + pad
        if head_h:
            d.text((card_x0 + pad, y), heading, font=head, fill=(*WHITE, alpha), anchor="lt")
            y += head_h
        left = typed
        caret = None
        for line in lines:
            x = card_x0 + pad
            for text, color in line:
                shown = text[:max(0, left)]
                left -= len(text)
                if shown:
                    d.text((x, y), shown, font=mono, fill=(*color, alpha), anchor="lt")
                    x += d.textlength(shown, font=mono)
                if left < 0 and caret is None:
                    caret = (x, y)
            if left >= 0:
                caret = (x, y)
            y += line_h
            if left < 0:
                break
        blink = (typed < total_chars) or (int(t * 2) % 2 == 0)
        if caret and blink:
            cx, cy = caret
            d.rectangle([cx + 4, cy + 6, cx + 4 + font_px * 0.5, cy + font_px * 1.1], fill=(*CYAN, alpha))
        frame.save(tmp / f"f{i:05d}.jpg", quality=92)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", str(tmp / "f%05d.jpg"), "-c:v", "libx264", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)
    for f in tmp.glob("*.jpg"):
        f.unlink()
    tmp.rmdir()
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--style", choices=("editor", "browser"), default="editor")
    p.add_argument("--title", required=True, help="имя файла (editor) или адрес (browser)")
    p.add_argument("--heading", default="", help="заголовок страницы (browser)")
    p.add_argument("--line", action="append", required=True, help="#цвет:текст|#цвет:текст")
    p.add_argument("--bg", default=None, help="кадр блока под затемнение")
    p.add_argument("--sec", type=float, default=3.0)
    p.add_argument("--font-px", type=int, default=56)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    print(render([parse_line(s) for s in a.line], style=a.style, title=a.title,
                 heading=a.heading, bg=Path(a.bg) if a.bg else None, sec=a.sec,
                 out=Path(a.out), font_px=a.font_px))
    return 0


if __name__ == "__main__":
    sys.exit(main())
