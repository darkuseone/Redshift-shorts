"""Latin authored overlay labels stay verbatim and skip punch expansion."""

from __future__ import annotations

import pytest

from src.lib.text import enrich_overlay_punch, is_latin_overlay_label


@pytest.mark.parametrize("label", [
    "WEATHER", "AIRFOIL", "PLASMA", "FOLLOWUP", "CLAY REJECT",
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
    "WEATHER", "AIRFOIL", "PLASMA", "FOLLOWUP", "CLAY REJECT",
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
        "params": {"text": "CLAY REJECT", "content": "CLAY REJECT"},
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
