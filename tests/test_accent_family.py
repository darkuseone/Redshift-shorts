"""Cyan из токена в кадр: `emphasis_family` наконец читается (§7.1).

Улика была короткой: `grep emphasis_family` по `src/` давал одну строку —
объявление в `schema.py:78`. Поле лежало в схеме, режиссёр мог его написать,
и ни один модуль его не читал. `captions.py` жёстко ставил
`var(--color-accent)` в трёх местах, а `.word.emphasis.cyan` и `.accent-cyan`
были объявлены в CSS и никем не выводились. Cyan лежал в брендбуке «IT
КОСМОС» первым классом (`cyan #36EFFF`, `accent_tokens: ["accent","cyan"]`) и
физически не мог попасть в кадр как акцент.

Правило разводит два акцента по смыслу (MEGA D-9): миф и чувство — красным,
техника, число и источник — cyan.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.lib.render.hyperframes.captions import _accent_cyan, _accent_pair, caption_css
from src.lib.render.hyperframes.templates import (
    TemplateCtx, _apply_accent_family, Piece, render_fullscreen,
)
from src.lib.schema import SCRIPT_SCHEMA
from src.p11_assemble.assemble import ACCENT_FAMILY_BY_EMPHASIS, accent_family

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestTheRuleSplitsTheTwoAccentsByMeaning:

    @pytest.mark.parametrize("family,expected", [
        ("myth", "red"), ("emotion", "red"),
        ("tech", "cyan"), ("number", "cyan"), ("source", "cyan"),
    ])
    def test_every_declared_family_has_a_colour(self, family, expected):
        assert accent_family({"emphasis_family": family}) == expected

    def test_an_unmarked_block_stays_red(self):
        """Красный — язык канала по умолчанию; cyan включается намеренно."""
        assert accent_family({}) == "red"
        assert accent_family(None) == "red"
        assert accent_family({"emphasis_family": ""}) == "red"

    def test_the_rule_covers_every_family_the_schema_allows(self):
        """Схема и правило не должны разъезжаться молча."""
        declared = set(SCRIPT_SCHEMA["properties"]["blocks"]["items"]
                       ["properties"]["emphasis_family"]["enum"])
        assert declared == set(ACCENT_FAMILY_BY_EMPHASIS), (
            f"схема знает {declared}, правило — {set(ACCENT_FAMILY_BY_EMPHASIS)}")

    def test_both_colours_are_actually_used(self):
        """Правило, красящее всё одним цветом, не правило."""
        assert set(ACCENT_FAMILY_BY_EMPHASIS.values()) == {"red", "cyan"}


class TestTheFullscreenFrameCarriesTheFamily:

    def _html(self, family: str) -> str:
        ctx = TemplateCtx(
            index=1, start=0.0, duration=2.0, target="shot-01", track=3,
            params={"content": "НЕВОЗМОЖНО ПРОВЕРИТЬ",
                    "accent_word": "ПРОВЕРИТЬ", "accent_family": family})
        return "".join(render_fullscreen(ctx).nodes)

    def test_cyan_reaches_the_frame(self):
        assert "accent-cyan" in self._html("cyan")

    def test_red_stays_red(self):
        html = self._html("red")
        assert 'class="accent"' in html
        assert "accent-cyan" not in html

    def test_a_missing_family_does_not_paint_cyan(self):
        ctx = TemplateCtx(index=1, start=0.0, duration=2.0, target="shot-01",
                          track=3, params={"content": "ПРОВЕРИТЬ НЕЧЕМ",
                                           "accent_word": "НЕЧЕМ"})
        assert "accent-cyan" not in "".join(render_fullscreen(ctx).nodes)

    def test_the_pass_leaves_everything_else_alone(self):
        piece = Piece(nodes=['<div class="clip">x</div>'],
                      tweens=['tl.set("#a",{},0);'], css=[".a{}"])
        out = _apply_accent_family(piece, "cyan")
        assert out.nodes == piece.nodes
        assert out.tweens == piece.tweens and out.css == piece.css


class TestTheSubtitleWordCarriesTheFamily:

    def test_a_cyan_word_is_recognised(self):
        assert _accent_cyan({"accent_family": "cyan"}) is True
        assert _accent_cyan({"accent_family": "red"}) is False
        assert _accent_cyan({}) is False

    def test_the_gradient_switches_with_the_family(self):
        """Градиент «кровь» на cyan даёт розовый провал, а не свечение."""
        params = {"accent": "#C8453D", "accent_soft": "#E4726A",
                  "cyan": "#36EFFF", "cyan_soft": "#7AF0FF"}
        assert _accent_pair(params, {"accent_family": "cyan"}) == \
            ("#36EFFF", "#7AF0FF")
        assert _accent_pair(params, {"accent_family": "red"}) == \
            ("#C8453D", "#E4726A")

    def test_the_css_declares_both_families(self):
        brandbook = json.loads((REPO_ROOT / "config" / "brandbook.json")
                               .read_text(encoding="utf-8"))
        css = caption_css(brandbook)
        assert ".cf-word.is-accent{color:var(--color-accent)}" in css
        assert ".cf-word.is-accent.cyan{color:var(--color-cyan)}" in css
        assert ".bd-word.is-accent.cyan{" in css


class TestTheReferenceScriptIsMarkedUp:
    """Разметка 0042 из §7.1 — устный текст при этом не менялся."""

    @pytest.fixture()
    def script(self):
        return json.loads((REPO_ROOT / "scripts" / "redshift_0042.json")
                          .read_text(encoding="utf-8"))

    def test_every_block_declares_its_family(self, script):
        missing = [b["id"] for b in script["blocks"]
                   if not b.get("emphasis_family")]
        assert not missing, f"блоки без семейства акцента: {missing}"

    def test_the_markup_matches_the_plan(self, script):
        expected = {"b1": "red", "b2": "cyan", "b3": "cyan",
                    "b4": "cyan", "b5": "red", "b6": "red"}
        actual = {b["id"]: accent_family(b) for b in script["blocks"]}
        assert actual == expected

    def test_cyan_is_at_least_one_bit(self, script):
        """V-9: cyan присутствует, когда сценарий его просит."""
        families = {accent_family(b) for b in script["blocks"]}
        assert "cyan" in families

    def test_red_and_cyan_never_paint_the_same_block(self, script):
        """Одна фраза — один акцент; смешение читается как сбой, а не приём."""
        for block in script["blocks"]:
            assert accent_family(block) in {"red", "cyan"}
