"""Карточка переносится по разделителю, а не посреди числа.

На 0050 карточка b4 «10 000 · 88 Ч · 2 700 000 · 17 Ч LEAN» вставала в кадр
четырьмя строками, из которых две рвали число: «2 700» и «000» порознь, «88»
без своего «Ч».
"""
from src.lib.render.hyperframes.templates import (
    glue_number_runs, is_unbreakable_number)

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
