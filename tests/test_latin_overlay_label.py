"""Latin authored overlay labels stay verbatim and skip punch expansion."""

from __future__ import annotations

import pytest

from src.lib.text import (
    enrich_overlay_punch, is_latin_overlay_label, punch_families_overlap,
)


@pytest.mark.parametrize("label", [
    "WEATHER", "AIRFOIL", "PLASMA", "FOLLOWUP", "CLAY REJECT", "REJECTED",
    "FLUIDS", "VALVES",
])
def test_is_latin_overlay_label_accepts_ascii_labels(label):
    assert is_latin_overlay_label(label)


@pytest.mark.parametrize("label", [
    "", "   ", "НЕЧЕМ", "Проверить нечем", "5 МИНУТ", "кровь",
])
def test_is_latin_overlay_label_rejects_empty_and_cyrillic(label):
    assert not is_latin_overlay_label(label)


@pytest.mark.parametrize("label", [
    "WEATHER", "AIRFOIL", "PLASMA", "FOLLOWUP", "CLAY REJECT", "REJECTED",
])
def test_enrich_overlay_punch_does_not_expand_latin_labels(label):
    block = (
        "как течёт жидкость, когда её толкают. Погода. Крыло самолёта. "
        "Трубы в доме. Ток крови. Если формула врёт — самолёт не извиняется."
    )
    assert enrich_overlay_punch(label, block) == label


def test_latin_plaque_skips_avatar_clamp():
    from src.p11_assemble.assemble import _clamp_plaques_at_avatar_cuts

    overlays = [{
        "type": "plaque", "start": 55.21, "end": 56.61,
        "template": "lower-thirds/dark-card",
        "params": {"text": "REJECTED", "content": "REJECTED"},
    }]
    shots = [
        {"kind": "avatar", "start": 54.0, "end": 55.21},
        {"kind": "footage", "start": 55.21, "end": 56.61},
        {"kind": "avatar", "start": 56.61, "end": 60.0},
    ]
    out = _clamp_plaques_at_avatar_cuts(overlays, shots)
    assert out[0]["end"] == 56.61


def test_cyrillic_plaque_still_clamps_at_avatar():
    from src.p11_assemble.assemble import _clamp_plaques_at_avatar_cuts

    overlays = [{
        "type": "plaque", "start": 35.0, "end": 39.5,
        "template": "lower-thirds/note-pin",
        "params": {"text": "Проверить нечем", "position": "top"},
    }]
    shots = [
        {"kind": "footage", "start": 31.0, "end": 37.6},
        {"kind": "avatar", "start": 37.6, "end": 42.0},
    ]
    out = _clamp_plaques_at_avatar_cuts(overlays, shots)
    assert out[0]["end"] == 37.6


def test_punch_overlap_clay_vs_clay_reject_but_identity_differs():
    """Punch stems fire clay/clay; latin FS path must use identity, not stems."""
    fs = "CLAY: НЕТ"
    plaque = "CLAY REJECT"
    assert punch_families_overlap(fs, plaque)
    assert fs.strip() != plaque.strip()
    # REJECTED avoids stem clash entirely (belt-and-suspenders with code fix).
    assert not punch_families_overlap(fs, "REJECTED")


def test_clear_plate_gap_when_covered_strips_marker():
    from src.p11_assemble.assemble import _clear_plate_gap_when_covered

    shots = [
        {
            "kind": "footage", "start": 45.43, "end": 48.83,
            "gap_reason": "no unique phrase: plate without text",
        },
        {
            "kind": "footage", "start": 63.06, "end": 65.86,
            "gap_reason": "fullscreen cap or duplicate phrase: plate without text",
        },
        {
            "kind": "footage", "start": 10.0, "end": 12.0,
            "gap_reason": "no unique phrase: plate without text",
        },
    ]
    overlays = [
        {"type": "plaque", "start": 45.43, "end": 48.83,
         "params": {"text": "PLASMA"}},
        {"type": "plaque", "start": 63.06, "end": 65.86,
         "params": {"text": "FOLLOWUP"}},
    ]
    out = _clear_plate_gap_when_covered(shots, overlays)
    assert "gap_reason" not in out[0]
    assert "gap_reason" not in out[1]
    # uncovered shot keeps the reason
    assert out[2].get("gap_reason") == "no unique phrase: plate without text"
