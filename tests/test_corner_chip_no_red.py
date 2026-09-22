"""Красный в кадре: кант у карточки-героя есть, у подписи в углу — нет.

Gemini выписал красную полосу в FLUIDS, WEATHER, AIRFOIL, VALVES, PLASMA,
REJECTED и FOLLOWUP семью отдельными строками. Это один брак, а не семь:
подпись источника в углу красного не носит.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.lib.render.hyperframes.templates import (
    OVERLAYS, TemplateCtx, fs_fact_card, fs_number_slam, fs_stack_lines,
    is_unbreakable_number, overlay_css, split_leading_number, text_width,
)
from src.p11_assemble.assemble import _coerce_latin_cleanbar_dark

LOWER_THIRDS = ("lt_dark_card", "lt_clean_bar", "lt_accent_underline")
LABELS = ("FLUIDS", "WEATHER", "AIRFOIL", "VALVES", "PLASMA",
          "REJECTED", "FOLLOWUP")


def _ctx(**params):
    return TemplateCtx(index=1, start=0.0, duration=3.0, target="ov-01",
                       track=5, params=params)


class TestP11MarksEveryCornerLabel:

    @pytest.mark.parametrize("label", LABELS)
    def test_a_latin_corner_label_asks_for_no_red(self, label):
        out = _coerce_latin_cleanbar_dark({}, content=label,
                                          template_id="lower-thirds/dark-card")
        assert out["no_red"] is True
        assert out["accent"] is False
        assert out["source_chip"] is True
        assert out["dark_card"] is True

    def test_an_unlisted_label_is_left_alone(self):
        out = _coerce_latin_cleanbar_dark({}, content="ИСТОЧНИК",
                                          template_id="lower-thirds/dark-card")
        assert "no_red" not in out


class TestTheRendererHonoursIt:

    @pytest.mark.parametrize("name", LOWER_THIRDS)
    def test_the_flag_reaches_the_markup(self, name):
        plain = "".join(OVERLAYS[name](_ctx(name="WEATHER")).nodes)
        chip = "".join(OVERLAYS[name](
            _ctx(name="WEATHER", no_red=True, source_chip=True)).nodes)
        assert "no-red" not in plain
        assert "no-red" in chip

    @pytest.mark.parametrize("name", LOWER_THIRDS)
    def test_the_hero_card_keeps_its_red(self, name):
        """Правило снимает красный только с подписи, не с языка канала."""
        assert "no-red" not in "".join(OVERLAYS[name](_ctx(name="ГЕРОЙ")).nodes)

    def test_the_neutral_colour_is_declared_in_css(self):
        brandbook = json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "brandbook.json")
            .read_text(encoding="utf-8"))
        css = overlay_css(brandbook)
        for rule in (".lt-dc-rule.no-red", ".lt-cb-tab.no-red",
                     ".lt-au-rule.no-red", ".lt-dc-card.no-red"):
            assert rule in css, rule
        # Нейтраль — серый брендбука, а не второй акцент.
        assert "#D7263D" not in css.split(".lt-dc-rule.no-red{")[1].split("}")[0]


class TestANumberIsNeverBrokenAcrossLines:

    @pytest.mark.parametrize("text,expected", [
        ("$1 000 000", True), ("88", True), ("2 700 000", True),
        ("ВЕКА НИКТО БРАЛ", False), ("10 000 · 88 Ч", False),
    ])
    def test_what_counts_as_one_number(self, text, expected):
        assert is_unbreakable_number(text) is expected

    def test_the_hook_sum_stays_on_one_line_inside_its_card(self):
        html = "".join(fs_fact_card(_ctx(content="$1 000 000", card=True)).nodes)
        assert "fs-nowrap" in html
        size = int(html.split("font-size:")[1].split("px")[0])
        # Строка плюс поля карточки обязаны влезть в рабочую зону, иначе
        # «$1» уезжает на одну строку, а «000 000» — на другую.
        assert text_width("$1 000 000", size) + 44 * 2 + 4 <= 740

    def test_a_phrase_is_still_allowed_to_wrap(self):
        html = "".join(fs_fact_card(_ctx(content="ВЕКА НИКТО БРАЛ", card=True)).nodes)
        assert "fs-nowrap" not in html


class TestAFullscreenLineFitsTheFrame:
    """Кегль лесенки считается по строке, а не по слову внутри неё.

    Перенос лесенка раскладывает сама, поэтому мерить слово бессмысленно:
    «7 · $1 000 000 · 25 Y» получало кегль по «000», три строки уезжали за
    край кадра и накрывали собой субтитр (0050, прогон 165).
    """

    @pytest.mark.parametrize("content", [
        "7 · $1 000 000 · 25 Y",
        "10 000 · 88 Ч · 2 700 000 · 17 Ч LEAN",
        "ВЕКА НИКТО БРАЛ",
    ])
    def test_every_line_fits_the_work_area(self, content):
        html = "".join(fs_stack_lines(_ctx(content=content)).nodes)
        size = int(html.split("font-size:")[1].split("px")[0])
        lines = [re.sub(r"<[^>]+>", "", m)
                 for m in re.findall(r'class="fs-line">(.*?)</span>', html)]
        assert lines
        for line in lines:
            assert text_width(line, size) <= 740, (line, size)


class TestTheHookSumIsNotCutInHalf:
    """Пробелы в «$1 000 000» — разряды, а не граница слов.

    Приём hook-number-slam делил содержимое по первому пробелу на «число» и
    «подпись». В хуке 0050 это давало огромное «$1» и мелкое «000 000» под
    ним: приз читался как один доллар (прогоны 164–170).
    """

    @pytest.mark.parametrize("content,number,caption", [
        ("$1 000 000", "$1 000 000", ""),
        ("10 000 АГЕНТОВ", "10 000", "АГЕНТОВ"),
        ("2 700 000 СООБЩЕНИЙ", "2 700 000", "СООБЩЕНИЙ"),
        ("88 ЧАСОВ", "88", "ЧАСОВ"),
        ("ВЕКА НИКТО БРАЛ", "ВЕКА НИКТО БРАЛ", ""),
    ])
    def test_the_whole_number_stays_together(self, content, number, caption):
        assert split_leading_number(content) == (number, caption)

    def test_the_hook_renders_the_sum_as_one_number(self):
        html = "".join(fs_number_slam(_ctx(content="$1 000 000", slam=True)).nodes)
        painted = re.sub(r"<[^>]+>", "",
                         re.search(r'class="fs-num[^"]*"[^>]*>(.*?)</span>',
                                   html, re.S).group(1))
        assert painted == "$1 000 000"
        assert 'class="fs-cap"' not in html
        size = int(re.search(r"font-size:(\d+)px", html).group(1))
        assert text_width(painted, size) <= 740
