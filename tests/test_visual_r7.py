"""0042 visual r7: glass cards, plain on-screen copy, Grok thumb cards."""

from __future__ import annotations

import json
from pathlib import Path

from src.lib.text import soften_on_screen_copy
from src.p12_render_qc.render import _thumbnail_prompt


ROOT = Path(__file__).resolve().parents[1]


def test_soften_quantum_chip_to_computer():
    assert "компьютер" in soften_on_screen_copy("Это квантовый чип.").lower()
    assert "чип" not in soften_on_screen_copy("квантовый чип").lower()


def test_soften_english_surface_code_highlight():
    out = soften_on_screen_copy("below the surface code threshold")
    assert "порог" in out.lower()
    assert "surface" not in out.lower()


def test_soften_qubit_gloss_on_phrase_not_singleton():
    assert soften_on_screen_copy("кубитов") == "кубитов"
    glossed = soften_on_screen_copy("105 кубитов внутри")
    assert "квантовый бит" in glossed.lower()


def test_thumbnail_prompt_requires_glass_cards_and_markus_like():
    script = json.loads((ROOT / "scripts/redshift_0042.json").read_text())
    prompt = _thumbnail_prompt({"meta": script["meta"]}, script, variant="A")
    low = prompt.lower()
    assert "frosted" in low or "glass" in low
    assert "markus" in low or "green" in low
    assert "morph" in low  # forbidden morph face called out
    assert "card" in low


def test_plaque_brandbook_is_glass_not_opaque():
    bb = json.loads((ROOT / "config/brandbook.json").read_text())
    assert float(bb["plaque"]["bg_alpha"]) <= 0.6
    assert int(bb["plaque"].get("glass_blur_px") or 0) >= 12
    assert float(bb["fullscreen_text"]["scrim_alpha"]) <= 0.45


def test_invert_fact_and_slam_cards_use_glass_css():
    from src.lib.render.hyperframes.templates import overlay_css
    css = overlay_css(json.loads((ROOT / "config/brandbook.json").read_text()))
    compact = css.replace(" ", "").replace("\n", "")
    assert "backdrop-filter:blur" in css
    assert "invert.fs-fact{background:rgba(26,31,46,0.52)" in compact
    assert "invert.fs-slam-card{background:rgba(26,31,46,0.52)" in compact
    assert "lt-dc-card{display:flex;flex-direction:column;gap:12px;" \
           "background:rgba(26,31,46,0.52)" in compact
    assert "lt-dc-card{display:flex;flex-direction:column;gap:12px;" \
           "background:#111214" not in compact


def test_compose_zoom_unchanged_for_0042_r7():
    # Steering: do not touch avatar/zoom this run (native 9:16 is NEXT videos).
    import yaml
    cfg = yaml.safe_load((ROOT / "config/config.yaml").read_text())
    assert float(cfg["heygen"]["compose_zoom"]) == 2.7
