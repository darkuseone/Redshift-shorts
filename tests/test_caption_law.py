"""Закон субтитров канала на реальной дорожке 0050.

Один жест, один слой, белая фраза, заливка текущего слова только #C8453D,
одна строка и целые слова. Проверка идёт на настоящем `speech_map.json`, а не
на выдуманных двух словах: ровно там и жили браки 0049/0050 — «ВРЁТСАМОЛЁТ»,
белый ряд с цветным дублём сверху и кириллический «КЛЕЙ».
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.lib.render.hyperframes.captions import (
    _visible_words, build_gradient_fill, caption_css, fit_wipe_group,
    gradient_fill_params, group_caption_phrases, pick_caption_style,
    resolve_caption, split_phrases_to_fit,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEECH_MAP = REPO_ROOT / "assets" / "voice" / "redshift_0050" / "speech_map.json"

FORBIDDEN_COLOURS = ("#e4726a", "#36efff", "#7af0ff", "#fe9f1b", "#f76e49",
                     "#ffd700", "#ff2063", "#fd56cb")


@pytest.fixture(scope="module")
def brandbook() -> dict:
    return json.loads((REPO_ROOT / "config" / "brandbook.json")
                      .read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cues() -> list[dict]:
    if not SPEECH_MAP.exists():
        pytest.skip("нет дорожки 0050")
    speech = json.loads(SPEECH_MAP.read_text(encoding="utf-8"))
    return [{"display": w["word"], "start": w["start"], "end": w["end"],
             "block_id": block["id"]}
            for block in speech["blocks"] for w in block["words"]]


@pytest.fixture(scope="module")
def markup(brandbook, cues) -> str:
    plan = {"subtitles": cues, "subtitle_style": {"baseline_y": 975}}
    nodes, tweens, _ = build_gradient_fill(plan, brandbook, duration=70.0)
    return "\n".join([*nodes, *tweens])


def _phrases(brandbook, cues):
    params = gradient_fill_params(brandbook)
    words = _visible_words(cues, params["case"])
    grouped = group_caption_phrases(
        words, max_words=params["max_words"],
        pause_break_sec=params["pause_break_sec"])
    return params, split_phrases_to_fit(
        grouped, max_width=params["frame_w"], base=params["base_px"],
        letter_spacing_em=params["letter_spacing_em"],
        gap_em=params["gap_em"], comfort_px=params["comfort_px"],
        min_size=params["min_px"])


class TestOnlyOneGestureShipsOnTheChannel:

    def test_a_plain_video_always_gets_gradient_fill(self, brandbook):
        assert pick_caption_style({"category": "science"}, brandbook) == "gradient-fill"
        assert pick_caption_style({}, brandbook) == "gradient-fill"

    def test_only_declared_space_may_leave_gradient_fill(self, brandbook):
        assert pick_caption_style({"category": "space"}, brandbook) == "clip-wipe"

    def test_no_data_can_switch_on_the_stacked_gestures(self):
        for name in ("camera-follow", "blend-difference", "pop-in", "word-pop", ""):
            assert resolve_caption(name) == "gradient-fill"


class TestThePhraseIsWhiteAndTheSpokenWordIsRed:

    def test_the_fill_is_the_only_accent_colour(self, markup, brandbook):
        assert brandbook["colors"]["accent"] == "#C8453D"
        assert "#C8453D" in markup
        for colour in FORBIDDEN_COLOURS:
            assert colour not in markup.lower(), colour

    def test_a_word_is_exactly_one_layer(self, markup):
        words = markup.count('class="gf-word"')
        assert words > 100
        # Два <text> на слово — белый и красный поверх него в том же <svg>.
        assert markup.count('<text class="gf-ink"') == words * 2
        assert "gf-base" not in markup and "gf-accent" not in markup

    def test_every_word_fills_and_hands_the_colour_on(self, markup):
        fills = re.findall(r'fromTo\("#(gf-\d+-w\d+)-r"', markup)
        assert len(fills) == markup.count('class="gf-word"')
        for target in fills:
            assert f'tl.set("#{target}-r",{{scaleX:0}}' in markup


class TestAWordIsNeverBrokenOrGlued:

    def test_the_group_never_wraps(self, brandbook):
        block = caption_css(brandbook).split(".gf-group{")[1].split("}")[0]
        assert "flex-wrap:nowrap" in block

    def test_every_phrase_fits_one_line(self, brandbook, cues):
        params, phrases = _phrases(brandbook, cues)
        for phrase in phrases:
            texts = [w["display"] for w in phrase]
            size, widths = fit_wipe_group(
                texts, max_width=params["frame_w"], base=params["base_px"],
                letter_spacing_em=params["letter_spacing_em"],
                gap_em=params["gap_em"], min_size=params["min_px"])
            total = sum(widths) + size * params["gap_em"] * (len(texts) - 1)
            assert total <= params["frame_w"], (size, texts)

    def test_no_phrase_shrinks_into_a_footnote(self, brandbook, cues):
        params, phrases = _phrases(brandbook, cues)
        for phrase in phrases:
            texts = [w["display"] for w in phrase]
            size, _ = fit_wipe_group(
                texts, max_width=params["frame_w"], base=params["base_px"],
                letter_spacing_em=params["letter_spacing_em"],
                gap_em=params["gap_em"], min_size=params["min_px"])
            assert size >= params["min_px"], texts

    def test_vryot_samolyot_are_two_words(self, markup):
        assert ">ВРЁТ<" in markup and ">САМОЛЁТ<" in markup
        assert "ВРЁТСАМОЛЁТ" not in markup


class TestBrandsAreLatinAndWhole:

    def test_clay_is_not_spelled_in_cyrillic(self, markup):
        assert ">CLAY<" in markup
        assert "КЛЕЙ" not in markup

    def test_openai_is_one_word_not_three_syllables(self, markup):
        assert ">OPENAI<" in markup
        for syllable in (">ОПЕН<", ">ЭЙ<", ">АЙ<"):
            assert syllable not in markup

    def test_lean_is_latin(self, markup):
        assert ">LEAN<" in markup
        assert ">ЛИН<" not in markup


class TestNumbersReadAsNumbers:

    def test_the_year_is_not_spelled_out_in_pieces(self, markup):
        assert ">2026<" in markup
        assert ">ТЫСЯЧИ<" not in markup

    def test_compound_numbers_are_joined(self, markup):
        assert ">88<" in markup
        assert ">10 000<" in markup
        assert ">2 700 000<" in markup

    def test_the_tts_stress_mark_never_reaches_the_frame(self, markup):
        assert "́" not in markup
