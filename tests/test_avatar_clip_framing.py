"""Клип ведущего попадает в кадр конвейера без искажения пропорции.

Инструмент `tools/reframe_avatar.py` писался под ландшафтный лук 1920×1080:
он вырезает окно по измеренной голове и добавляет поле сверху. Заказчик сменил
лук на снятый вертикально — и кроп поехал уже по нему. На 720×1280 он вырезает
полный кадр и вписывает его в 1080×1689 с полем: по горизонтали 1.50, по
вертикали 1.32, то есть ведущий на 14 % шире себя. Плюс в контейнере оставался
неквадратный пиксель (SAR 317:360), и верный по размерам кадр показывался
сплющенным. Ровно та «растяжка с плохим качеством», из-за которой лук и меняли.
"""
import pytest

from tools.fetch_avatar_clips import FRAME_H, FRAME_W, _is_frame_ratio


@pytest.mark.parametrize("size", [(720, 1280), (1080, 1920), (1440, 2560),
                                  (540, 960),
                                  # Исходник лука: 0.558 против 0.5625 — это
                                  # 0.8 % по ширине. Равномерное увеличение
                                  # стоит дешевле кропа по голове, который
                                  # обходится в 14 %.
                                  (1536, 2752)])
def test_a_vertical_source_is_recognised_as_frame_ratio(size):
    assert _is_frame_ratio(*size)


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1080), (1280, 720),
                                  (1024, 1280)])
def test_anything_else_is_not(size):
    assert not _is_frame_ratio(*size)


def test_a_zero_size_is_not_a_frame(): 
    assert not _is_frame_ratio(0, 1920)
    assert not _is_frame_ratio(1080, 0)


def test_the_frame_is_the_pipeline_frame():
    assert (FRAME_W, FRAME_H) == (1080, 1920)


def test_the_prepared_clips_are_square_pixel_frame_size():
    """Готовые клипы 0050 — 1080×1920 с квадратным пикселем.

    Меряется файл, а не намерение: прошлый прогон оставил в контейнере
    SAR 317:360, и по размерам всё выглядело правильно.
    """
    from pathlib import Path

    from src.lib.ffmpeg import probe

    clips = sorted((Path(__file__).resolve().parents[1] / "assets"
                    / "avatar_clips" / "redshift_0050").glob("seg_*.webm"))
    if not clips:
        pytest.skip("клипов ведущего нет на диске")
    for clip in clips:
        info = probe(clip)
        assert (int(info.width), int(info.height)) == (FRAME_W, FRAME_H), clip.name
