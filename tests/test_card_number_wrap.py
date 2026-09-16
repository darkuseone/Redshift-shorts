"""Карточка переносится по разделителю, а не посреди числа.

На 0050 карточка b4 «10 000 · 88 Ч · 2 700 000 · 17 Ч LEAN» вставала в кадр
четырьмя строками, из которых две рвали число: «2 700» и «000» порознь, «88»
без своего «Ч».
"""
from src.lib.render.hyperframes.templates import (
    glue_number_runs, is_unbreakable_number, stack_lines)

CARD = "10 000 · 88 Ч · 2 700 000 · 17 Ч LEAN"
NBSP = " "


def test_digit_groups_stop_being_break_opportunities():
    assert "2" + NBSP + "700" + NBSP + "000" in glue_number_runs(CARD)


def test_a_number_keeps_its_unit():
    glued = glue_number_runs(CARD)
    assert "88" + NBSP + "Ч" in glued
    assert "17" + NBSP + "Ч" in glued


def test_the_separator_stays_a_break_opportunity():
    # иначе строка не влезет ни при каком кегле
    assert " · " in glue_number_runs(CARD)


def test_a_word_after_a_number_may_still_wrap():
    assert "Ч LEAN" in glue_number_runs(CARD)


def test_gluing_does_not_break_the_whole_number_check():
    assert is_unbreakable_number(glue_number_runs("$1 000 000"))


def test_plain_prose_is_left_alone():
    text = "Миллион OpenAI не берёт"
    assert glue_number_runs(text) == text


def test_a_middot_card_breaks_on_the_separator_not_on_words():
    """«7 · $1 000 000 · 25 Y» — три величины, а не пять слов.

    Упаковщик по словам ставил «7 ·» / «$1 000 000 ·» / «25 Y»: одинокая
    семёрка с висящей точкой на первой строке, точка следующей величины —
    в конце предыдущей. Заказчик прислал этот кадр как брак.
    """
    lines = stack_lines("7 · $1 000 000 · 25 Y")
    assert lines == ["7", "$1 000 000", "25 Y"]


def test_a_card_without_a_separator_still_packs_by_words():
    assert len(stack_lines("ДВА МИЛЛИОНА СЕМЬСОТ ТЫСЯЧ СООБЩЕНИЙ")) <= 3
