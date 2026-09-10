"""Цифры в субтитрах: речь словами, экран — числом."""

from __future__ import annotations

from src.lib.render.number_display import (
    NARROW_NBSP,
    extract_fact_numbers,
    format_grouped_int,
    format_number_display,
    has_money_number,
    number_word_to_digit_display,
)
from src.lib.render.text_rules import subtitle_word
from src.lib.text import normalize_text, spoken_text


def test_grouped_thousands_use_narrow_nbsp():
    assert format_grouped_int(12000) == f"12{NARROW_NBSP}000"
    assert format_number_display("12000") == f"12{NARROW_NBSP}000"
    assert "двенадцать" not in format_number_display("12000")


def test_years_and_small_ints_ungrouped():
    assert format_number_display("2024") == "2024"
    assert format_number_display("105") == "105"


def test_decimals_and_percent():
    assert format_number_display("2.4") == "2.4"
    assert format_number_display("2,4") == "2,4"
    assert format_number_display("12%") == "12%"


def test_money_keeps_currency_glyph():
    assert format_number_display("$2.4") == "$2.4"
    assert "два" not in format_number_display("$2.4")


def test_subtitle_word_digitizes_russian_ones():
    assert subtitle_word("двенадцать", "lower") == "12"
    assert subtitle_word("12000", "lower") == f"12{NARROW_NBSP}000"


def test_phrase_twelve_thousand_becomes_digits():
    tokens = normalize_text("двенадцать тысяч долларов")
    displays = [t.display for t in tokens]
    assert any(NARROW_NBSP in d or d == f"12{NARROW_NBSP}000" for d in displays)
    assert spoken_text(tokens).lower().replace("́", "").find("двенадцать") >= 0


def test_speech_digits_stay_digits_on_screen():
    tokens = normalize_text("Внутри 105 кубитов. Бюджет $2.4 млрд. Рост 12%. Год 2024.")
    displays = " ".join(t.display for t in tokens)
    assert "105" in displays
    assert "$2.4" in displays
    assert "12%" in displays
    assert "2024" in displays
    assert "сто пять" not in displays
    assert "двенадцать процентов" not in displays


def test_extract_fact_numbers_and_money():
    blob = "105 кубитов, ошибка падает вдвое, задача за пять минут, убыток $2.4 млрд"
    found = extract_fact_numbers(blob)
    assert any("105" in x or x == "105" for x in found)
    assert has_money_number("убыток $2.4 млрд")
    assert not has_money_number("Доверил бы ты такому ответу свои деньги?")
