"""Числительное словом — это слово целиком, а не его начало.

0050 r61: хвост `\\w*` в `_WORD_NUM_RE` делал числом любое слово, начинающееся
с числительного. «Навье-Стокса» читалось как «сто», и поверх футажа встала
диаграмма «100 СТОКСА» — число, которого в реплике нет.
"""
import pytest

from src.p11_assemble.assemble import _stats_from_text


def _values(text):
    return [n["value"] for n in _stats_from_text(text)]


@pytest.mark.parametrize("text", [
    "Называются уравнения Навье-Стокса.",
    "Стокгольм и Стоунхендж.",
    "Тристан и Изольда.",
])
def test_a_word_that_merely_starts_like_a_numeral_is_not_a_number(text):
    assert _stats_from_text(text) == []


def test_plain_numerals_still_parse():
    assert _values("сто пять кубитов") == [105.0]
    assert _values("семь задач") == [7.0]
    assert _values("пятью процентами") == [5.0]


def test_the_0050_develop_block_keeps_all_four_numbers():
    text = ("Десять тысяч агентов. Восемьдесят восемь часов. "
            "Два миллиона семьсот тысяч сообщений. "
            "Семнадцать часов переложили доказательство в Lean.")
    assert _values(text) == [10_000.0, 88.0, 2_700_000.0, 17.0]
