"""0042 B: smart captions — punch-family mute, card mute, no face-zone raise."""

from __future__ import annotations

from src.lib.text import punch_families_overlap
from src.lib.render.hyperframes.captions import _phrase_baseline
from src.p11_assemble.assemble import _build_subtitle_cues


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


def test_card_overlap_mutes_cue_instead_of_raising_baseline():
    words = [
        {"display": "квантовый", "start": 4.0, "end": 4.4, "block_id": "b1",
         "emphasis": False},
        {"display": "чип", "start": 4.4, "end": 4.8, "block_id": "b1",
         "emphasis": False},
        {"display": "потом", "start": 8.0, "end": 8.3, "block_id": "b1",
         "emphasis": False},
    ]
    cues = _build_subtitle_cues(
        words, punch_windows=[], mute_windows=[(3.5, 6.0)])
    assert [c["display"] for c in cues] == ["потом"]
    assert all("baseline_y" not in c for c in cues)


def test_cta_window_mutes_all_cues():
    words = [
        {"display": "деньги", "start": 42.6, "end": 43.0, "block_id": "b6",
         "emphasis": False},
        {"display": "напиши", "start": 43.0, "end": 43.4, "block_id": "b6",
         "emphasis": False},
    ]
    cues = _build_subtitle_cues(
        words, punch_windows=[], mute_windows=[(42.5, 44.5)])
    assert cues == []


def test_orphan_two_letter_chips_dropped_after_glue():
    words = [
        {"display": "почти", "start": 5.0, "end": 5.3, "block_id": "b1",
         "emphasis": False},
        {"display": "ТИ", "start": 8.0, "end": 8.2, "block_id": "b1",
         "emphasis": False},
        {"display": "верим", "start": 39.0, "end": 39.4, "block_id": "b5",
         "emphasis": False},
        {"display": "ВЕ", "start": 39.9, "end": 40.1, "block_id": "b5",
         "emphasis": False},
    ]
    cues = _build_subtitle_cues(words, punch_windows=[], mute_windows=[])
    shown = [c["display"] for c in cues]
    assert "ТИ" not in shown
    assert "ВЕ" not in shown
    assert "почти" in shown
    assert "верим" in shown


def test_punch_family_mute_keeps_unrelated_words():
    words = [
        {"display": "наоборот", "start": 18.1, "end": 18.5, "block_id": "b4",
         "emphasis": False},
        {"display": "кубитов", "start": 18.5, "end": 18.9, "block_id": "b4",
         "emphasis": False},
    ]
    cues = _build_subtitle_cues(
        words,
        punch_windows=[(18.0, 19.5, "ЗДЕСЬ ВСЁ НАОБОРОТ")],
        mute_windows=[],
    )
    assert [c["display"] for c in cues] == ["кубитов"]
