"""Ключевание фона аватара.

HeyGen прозрачности не отдаёт — альфа добывается своим ffmpeg из однотонного
фона. Проверяется то, что легко испортить незаметно: радиус захвата, который
съедает самого ведущего.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.errors import RenderError
from src.lib.ffmpeg import alpha_opacity, ffmpeg_bin, has_alpha
from src.lib.render.chroma import CHROMA_GREEN, _hex_to_ffmpeg, key_out


def _synthetic_clip(path: Path) -> Path:
    """Кадр «тёмный объект на зелёном» — ровно тот случай, где ключ ошибается."""
    frame = Image.new("RGB", (320, 480), (11, 177, 64))       # #00B140
    # Тёмная фигура: у неё низкая цветность, и YUV-ключ норовит съесть её.
    for x in range(120, 200):
        for y in range(150, 380):
            frame.putpixel((x, y), (18, 18, 22))
    raw = path.with_suffix(".png")
    frame.save(raw)
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                    "-loop", "1", "-i", str(raw), "-t", "0.5", "-r", "10",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   check=True, capture_output=True)
    return path


@pytest.fixture
def green_clip(tmp_path):
    return _synthetic_clip(tmp_path / "green.mp4")


def test_hex_is_translated_for_ffmpeg():
    assert _hex_to_ffmpeg(CHROMA_GREEN) == "0x00B140"
    assert _hex_to_ffmpeg("00b140") == "0x00B140"


def test_background_goes_transparent_and_subject_stays(green_clip, tmp_path):
    out = key_out(green_clip, tmp_path / "keyed.mov")
    assert out.exists()

    png = tmp_path / "frame.png"
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(out), "-frames:v", "1", str(png)],
                   check=True, capture_output=True)
    alpha = np.asarray(Image.open(png).convert("RGBA").getchannel("A"))

    assert alpha[10, 10] < 10, "зелёный угол обязан стать прозрачным"
    # Тёмная фигура должна остаться непрозрачной: именно её съедал широкий
    # радиус захвата, и заметить это можно было только глазами.
    assert alpha[260, 160] > 245, "тёмный объект не должен уходить в полупрозрачность"


def test_semitransparent_pixels_stay_rare(green_clip, tmp_path):
    """Полутон допустим только на кромке, а не по всей фигуре."""
    out = key_out(green_clip, tmp_path / "keyed.mov")
    png = tmp_path / "frame.png"
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(out), "-frames:v", "1", str(png)],
                   check=True, capture_output=True)
    alpha = np.asarray(Image.open(png).convert("RGBA").getchannel("A"))
    partial = ((alpha >= 10) & (alpha <= 245)).mean()
    assert partial < 0.05, f"полутоновых пикселей {partial:.1%} — ключ съедает фигуру"


def test_missing_source_fails_loudly(tmp_path):
    with pytest.raises(RenderError) as exc:
        key_out(tmp_path / "нет.mp4", tmp_path / "out.mov")
    assert exc.value.code == "CHROMA_KEY_FAILED"


def test_alpha_is_measured_and_not_guessed_from_the_extension(green_clip, tmp_path):
    """Прозрачность определяется по кадру, а не по имени файла.

    Дефект был ровно такой: провайдер считал альфой всё, что называется .mov
    или .webm. HeyGen прислал .webm без прозрачности, приёмы за головой ушли
    за непрозрачный план, и в кадре их не было — молча.
    """
    # Непрозрачный h264: альфа-плоскости в потоке нет вовсе.
    assert alpha_opacity(green_clip) is None
    assert not has_alpha(green_clip)

    # Тот же кадр после ключевания: альфа есть и она работает.
    keyed = key_out(green_clip, tmp_path / "keyed.mov")
    opacity = alpha_opacity(keyed)
    assert opacity is not None and 0.05 < opacity < 0.95, opacity
    assert has_alpha(keyed)


def test_alpha_filled_with_ones_does_not_count_as_alpha(tmp_path):
    """Формально существующий, но целиком непрозрачный канал — не альфа.

    Такой файл и приходил от прошлого аватара: контейнер с альфой, залитой
    единицами. Верить самому факту наличия канала нельзя.
    """
    opaque = tmp_path / "opaque.mov"
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=0xE04040@1.0:s=320x480:d=0.5:r=10",
                    "-vf", "format=rgba", "-c:v", "png", str(opaque)],
                   check=True, capture_output=True)
    assert alpha_opacity(opaque) == pytest.approx(1.0, abs=1e-3)
    assert not has_alpha(opaque)


def _portrait_clip(path: Path) -> Path:
    """Портрет с альфой — ровно та геометрия, на которой ломался замер головы.

    Три детали здесь не для красоты, каждая воспроизводит свой дефект:

    * **плечи начинаются выше подбородка** — как в реальном плане, где шею
      закрывает воротник. Профиль ширины проваливается на скулах, а не под
      челюстью, и «самое узкое место» указывает на верхнюю губу;
    * **стойка микрофона** — тонкая полоса справа, входящая в кадр на уровне
      черепа. По размаху строки голова получалась вдвое шире, чем она есть;
    * **пропорции головы человеческие** — овал 120×160, чтобы проверять
      измеренную высоту, а не подогнанную.
    """
    frame = Image.new("RGBA", (360, 640), (0, 0, 0, 0))
    px = frame.load()
    for y in range(640):
        for x in range(360):
            head = ((x - 180) / 60.0) ** 2 + ((y - 170) / 80.0) ** 2 <= 1.0
            body = y >= 210 and abs(x - 180) <= 40 + (y - 210) * 110 / 430
            boom = 330 <= x <= 340 and y >= 150
            if head or body or boom:
                px[x, y] = (30, 30, 34, 255)
    raw = path.with_suffix(".png")
    frame.save(raw)
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                    "-loop", "1", "-i", str(raw), "-t", "0.5", "-r", "10",
                    "-c:v", "qtrle", "-pix_fmt", "argb", str(path)],
                   check=True, capture_output=True)
    return path


def test_head_box_measures_the_head_and_not_the_props(tmp_path):
    """Коробка головы: от макушки до подбородка, без стойки микрофона.

    Оба промаха ловились только глазами на кадре. Коробка, кончавшаяся на губе,
    сажала круг на 60 px выше головы — сверху пустота, снизу подбородок наружу.
    Коробка, вобравшая стойку, делала голову вдвое шире.
    """
    from src.lib.ffmpeg import head_box

    box = head_box(_portrait_clip(tmp_path / "portrait.mov"), at_sec=0.1)
    assert box is not None
    x0, y0, x1, y1 = box

    assert y0 == pytest.approx(90, abs=6), "макушка"
    # Подбородок овала — 250. Скулы, куда указывал прежний поиск, — около 232.
    assert 244 <= y1 <= 264, f"подбородок, а не скулы: {y1}"
    assert x0 == pytest.approx(120, abs=6) and x1 == pytest.approx(240, abs=6), \
        f"ширина головы без стойки: {x0}..{x1}"


def test_bubble_circle_leaves_the_asked_for_margin_around_the_head(tmp_path):
    """Круг обязан вместить голову и оставить 5–7 % поля — как просил заказчик.

    Радиус по полудиагонали коробки формально голову вмещал, но поле выходило
    вдвое больше просимого: лицо болталось в середине пустого круга.
    """
    import math

    from src.lib.render.hyperframes.templates import bubble_radius

    head_w, head_h = 120, 160
    radius = bubble_radius({"head_w": head_w, "head_h": head_h})

    # Голова — овал: самая дальняя её точка от центра лежит на длинной полуоси.
    reach = max(head_w, head_h) / 2
    assert radius > reach, "голова обязана помещаться целиком"
    assert 1.05 <= radius / reach <= 1.07, f"поле {radius / reach:.3f}"
    # Полудиагональ коробки — прежнее правило — дала бы заметно больший круг.
    assert radius < math.hypot(head_w, head_h) / 2
