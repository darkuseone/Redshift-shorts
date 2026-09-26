"""Brandbook four-color lock: black / white / red / turquoise (token `cyan`)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.lib.render.hyperframes.brand_css import build_css

ROOT = Path(__file__).resolve().parents[1]
BRANDBOOK = ROOT / "config" / "brandbook.json"

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_CYAN = {
    "cyan": "#36EFFF",
    "cyan_soft": "#7AF0FF",
    "cyan_deep": "#0BB8C9",
}


def _brandbook() -> dict:
    return json.loads(BRANDBOOK.read_text(encoding="utf-8"))


def test_cyan_tokens_are_first_class_and_valid_hex():
    colors = _brandbook()["colors"]
    for name, hex_ in _CYAN.items():
        assert name in colors, name
        assert _HEX.match(str(colors[name])), colors[name]
        assert str(colors[name]).upper() == hex_


def test_brand_red_is_d7263d_owners_pick():
    colors = _brandbook()["colors"]
    assert str(colors["accent"]).upper() == "#D7263D"
    assert str(colors["accent_soft"]).upper() == "#D7263D"
    assert str(colors["accent_deep"]).upper() == "#8E1627"


def test_accent_tokens_are_red_and_cyan():
    rules = _brandbook()["color_rules"]
    assert rules["accent_tokens"] == ["accent", "cyan"]
    assert float(rules["accent_max_frame_share"]) == 0.12


def test_palette_is_the_owners_four_colours():
    """Заказчик 22.09: белый, чёрный, красный, бирюзовый — и роли у каждого."""
    book = _brandbook()
    comment = str(book["colors"]["_comment"])
    for word in ("БЕЛЫЙ", "ЧЁРНЫЙ", "КРАСНЫЙ", "БИРЮЗОВЫЙ", "#D7263D", "#36EFFF"):
        assert word in comment, word
    roles = book["brand_roles"]
    assert set(roles) >= {"black", "white", "red", "turquoise"}
    assert roles["emphasis_family_map"]["number"] == "turquoise"
    assert roles["emphasis_family_map"]["emotion"] == "red"


def test_signature_elements_are_declared():
    sig = _brandbook()["signature"]
    for key in ("subtitles", "hook_card", "tech_frame", "plates", "end_card"):
        assert sig.get(key), key


def test_generated_css_exposes_cyan_vars_and_classes():
    css = build_css(_brandbook(), {"display": "Oswald-Bold.ttf",
                                   "subtitle": "Montserrat-Black.ttf",
                                   "mono": "JetBrainsMono-Bold.ttf"})
    for token, hex_ in _CYAN.items():
        var = "--color-" + token.replace("_", "-")
        assert f"{var}: {hex_}" in css or f"{var}: {hex_.lower()}" in css, var
    assert ".word.emphasis.cyan{color:var(--color-cyan)}" in css
    assert ".fullscreen-text .accent-cyan{color:var(--color-cyan)}" in css
    assert ".sb-clone-cyan{color:var(--color-cyan)" in css


def test_scan_band_cyan_clone_uses_the_token_not_a_literal():
    css = build_css(_brandbook(), {"subtitle": "Nunito-ExtraBold.ttf"})
    clone = re.search(r"\.sb-clone-cyan\{[^}]+\}", css)
    assert clone, "missing .sb-clone-cyan rule"
    assert "var(--color-cyan)" in clone.group(0)
    assert "#36efff" not in clone.group(0).lower()


def test_no_light_red_anywhere():
    """Заказчик 23.09: светло-красного нет. Красный — один, #D7263D."""
    import subprocess
    out = subprocess.run(
        ["git", "grep", "-niIE", r"#f2566b|242, ?86, ?107", "--", "src", "config", "tools", ":(exclude)*.md"],
        capture_output=True, text=True,
    ).stdout
    assert out == "", out
