"""Поле графика кончается выше полосы субтитров.

decline-chart занимал 387..1766 из 1920 — почти весь кадр по высоте, и
караоке шло прямо по падающей линии: «СООБЩЕНИЙ» и «17 ЧАСОВ» ложились на
неё. Увести субтитр было некуда: брендбук разрешает базовую линию только в
620..1280, и весь этот диапазон был внутри поля графика.
"""
import json

from src.lib.render.hyperframes import templates as T

BRANDBOOK = json.load(open("config/brandbook.json", encoding="utf-8"))
SUBS = BRANDBOOK["subtitles"]


def _caption_top() -> float:
    """Верх самой высокой строки субтитра при максимальном кегле."""
    return float(SUBS["baseline_y_default"]) - float(SUBS["size_px_default"]) / 2.0


def test_the_plot_ends_above_the_caption_line():
    assert T._DCL_PLOT_TOP + T._DCL_PLOT_H < _caption_top()


def test_the_plot_still_owns_the_upper_half_of_the_frame():
    # Развод не должен превратить график в полоску: он остаётся главным в кадре.
    height = float(BRANDBOOK["canvas"]["height"])
    assert T._DCL_PLOT_H / height >= 0.30


def test_the_plot_starts_below_the_chart_header():
    assert T._DCL_PLOT_TOP >= T._DCL_PAD_TOP + T._DCL_HEADER_H


def test_the_axis_labels_stay_inside_the_plot():
    # Подписи оси садятся на PLOT_TOP + PLOT_H - 48 — они не должны уехать
    # вниз вместе с нижней границей поля.
    assert T._DCL_PLOT_TOP + T._DCL_PLOT_H - 48 < _caption_top()
