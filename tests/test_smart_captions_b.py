"""0042 B: smart captions — punch-family mute only + baseline reposition."""

from __future__ import annotations

from src.lib.text import punch_families_overlap
from src.lib.render.hyperframes.captions import _phrase_baseline


def test_punch_family_only_overlap_not_unrelated():
    assert punch_families_overlap("НАОБОРОТ", "здесь всё наоборот")
    assert not punch_families_overlap("НАОБОРОТ", "кубитов внутри")


def test_phrase_baseline_prefers_cue_override():
    phrase = [
        {"display": "Здесь", "start": 18.1, "end": 18.3, "baseline_y": 820},
        {"display": "всё", "start": 18.3, "end": 18.5},
    ]
    assert _phrase_baseline(phrase, 1180) == 820.0
    assert _phrase_baseline([{"display": "x"}], 1180) == 1180.0
