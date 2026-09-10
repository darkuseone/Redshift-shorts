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
    # Sparse punch: drop the overlapping word, keep the rest of the phrase.
    words = [
        {"display": w, "start": 18.0 + i * 0.28, "end": 18.22 + i * 0.28,
         "block_id": "b4", "emphasis": False}
        for i, w in enumerate(
            ["Чем", "больше", "кубитов", "связке", "падает", "вселенная"])
    ]
    cues = _build_subtitle_cues(
        words,
        punch_windows=[(18.0, 18.25, "ЧЕМ БОЛЬШЕ")],
        mute_windows=[],
    )
    assert [c["display"] for c in cues] == [
        "больше", "кубитов", "связке", "падает", "вселенная"]


def _six_words():
    return [
        {"display": w, "start": 18.0 + i * 0.28, "end": 18.22 + i * 0.28,
         "block_id": "b4", "emphasis": False}
        for i, w in enumerate(
            ["Чем", "больше", "кубитов", "связке", "падает", "вселенная"])
    ]


def test_majority_mute_drops_the_whole_phrase():
    words = _six_words()[:3]
    # Two of three words sit under the card → the 3-word group is gone.
    cues = _build_subtitle_cues(
        words, punch_windows=[], mute_windows=[(18.27, 18.80)])
    assert cues == []


def test_majority_mute_keeps_the_next_phrase_group():
    words = _six_words()
    cues = _build_subtitle_cues(
        words, punch_windows=[], mute_windows=[(18.0, 18.80)])
    assert [c["display"] for c in cues] == ["связке", "падает", "вселенная"]


def test_sparse_mute_drops_only_muted_words():
    words = _six_words()
    # 1/6 muted → five words remain (not the whole phrase, not empty).
    cues = _build_subtitle_cues(
        words, punch_windows=[], mute_windows=[(18.27, 18.54)])
    assert [c["display"] for c in cues] == [
        "Чем", "кубитов", "связке", "падает", "вселенная"]


def test_fullscreen_line_mute_covers_the_whole_shot():
    from src.p11_assemble.assemble import (
        FS_MUTE_SEC, _caption_line_windows, _caption_mute_windows,
    )

    shots = [{"kind": "fullscreen_text", "start": 8.0, "end": 10.5,
              "content": "РАБОТА ОПУБЛИКОВАНА В NATURE", "params": {}}]
    assert _caption_mute_windows(shots, []) == [(8.0, 8.0 + FS_MUTE_SEC)]
    assert _caption_line_windows(shots, []) == [(8.0, 10.5)]


def test_hook_fullscreen_mutes_karaoke_for_the_whole_hook_block():
    from src.p11_assemble.assemble import _caption_line_windows

    shots = [
        {"kind": "fullscreen_text", "start": 0.0, "end": 0.93, "content": "ФУРОР",
         "role": "hook", "block_id": "b1", "hook": True, "params": {}},
        {"kind": "footage", "start": 0.93, "end": 3.2, "role": "hook",
         "block_id": "b1"},
    ]
    windows = _caption_line_windows(shots, [])
    assert any(s <= 0.01 and e >= 3.19 for s, e in windows)


def test_title_behind_carries_line_mutes_its_window():
    from src.p11_assemble.assemble import _caption_line_windows, _caption_mute_windows

    shots = [{
        "kind": "avatar", "start": 32.0, "end": 36.0,
        "hero": {"renderer": "hero-title-behind", "carries_line": True,
                 "covers_frame": False,
                 "params": {"head": "КВАНТОВЫЙ", "tail": "ЧИП"}},
    }]
    assert _caption_mute_windows(shots, []) == [(32.0, 36.0)]
    assert _caption_line_windows(shots, []) == [(32.0, 36.0)]


def test_carries_line_drops_the_whole_phrase():
    words = _six_words()
    cues = _build_subtitle_cues(
        words, punch_windows=[], mute_windows=[],
        line_windows=[(18.0, 19.70)])
    assert cues == []


def test_line_window_kiss_does_not_swallow_the_previous_phrase():
    """0048: «поток» ended on the next hero start and muted «дэ: трёхмерный»."""
    words = [
        {"display": "дэ:", "start": 39.66, "end": 39.92, "block_id": "b4",
         "emphasis": False},
        {"display": "трёхмерный", "start": 39.92, "end": 40.37, "block_id": "b4",
         "emphasis": False},
        {"display": "поток", "start": 40.37, "end": 40.76, "block_id": "b4",
         "emphasis": False},
    ]
    cues = _build_subtitle_cues(
        words, punch_windows=[], mute_windows=[],
        line_windows=[(40.757, 42.87)])
    shown = [c["display"] for c in cues]
    assert "трёхмерный" in shown
    assert "дэ:" in shown or any(c.get("lead") for c in cues)


def test_slam_hero_still_mutes_its_own_window():
    from src.p11_assemble.assemble import _caption_mute_windows

    shots = [{
        "kind": "avatar", "start": 4.0, "end": 8.0,
        "hero": {"renderer": "hero-slam", "carries_line": True,
                 "covers_frame": True, "duration": 1.8},
    }]
    assert _caption_mute_windows(shots, []) == [(4.0, 5.8)]


def test_digit_token_stays_in_display_not_lead():
    words = [
        {"display": "Внутри", "start": 4.0, "end": 4.3, "block_id": "b2",
         "emphasis": False},
        {"display": "105", "start": 4.3, "end": 4.6, "block_id": "b2",
         "emphasis": False},
        {"display": "кубитов", "start": 4.6, "end": 5.1, "block_id": "b2",
         "emphasis": False},
    ]
    cues = _build_subtitle_cues(words, punch_windows=[], mute_windows=[])
    shown = [c["display"] for c in cues]
    assert "105" in shown
    assert not any(str(c.get("lead") or "") == "105" for c in cues)


def test_dataviz_card_does_not_mute_captions():
    from src.p11_assemble.assemble import _caption_mute_windows

    overlays = [{
        "type": "dataviz", "start": 21.5, "end": 23.6,
        "template": "data-viz/stat-countup-card", "renderer": "dataviz",
        "params": {"value": 2_700_000.0, "suffix": "", "label": "два миллиона"},
    }]
    assert _caption_mute_windows([], overlays) == []


def test_headline_kicker_does_not_mute_the_whole_avatar_shot():
    from src.p11_assemble.assemble import _caption_mute_windows

    shots = [{
        "kind": "avatar", "start": 8.8, "end": 12.0,
        "hero": {"renderer": "hero-headline", "carries_line": True,
                 "covers_frame": False, "duration": 1.5,
                 "params": {"word": "МИЛЛИОН", "kicker": "С ЧЕГО НАЧАЛОСЬ"}},
    }]
    assert _caption_mute_windows(shots, []) == []


def test_top_note_pin_does_not_mute_captions():
    from src.p11_assemble.assemble import _caption_mute_windows

    overlays = [{
        "type": "plaque", "start": 2.0, "end": 4.0,
        "template": "lower-thirds/note-pin",
        "params": {"text": "105 КУБИТОВ", "position": "top"},
    }]
    assert _caption_mute_windows([], overlays) == []
