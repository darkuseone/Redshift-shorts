"""MUST-022: тип карты → SFX role; density keeps first card; adjacent bed excluded."""

from __future__ import annotations

import pytest

from src.lib.config import load_config
from src.lib.manifest import open_library
from src.lib.music_library import BED_PICK_MAX, pick_bed
from src.lib.sfx_library import (
    CARD_TYPE_TO_INTENT, SFX_PICK_MAX, pick_sfx, sfx_for_card_type,
)
from src.p10_audio.audio_build import _plan_sfx, sfx_skipped_from_events


def test_card_type_maps_to_intent_not_picture_in():
    assert sfx_for_card_type("plaque") == ("plaque", "ui_click")
    assert sfx_for_card_type("source_card") == ("card_appear", "pop")
    assert sfx_for_card_type("highlight") == ("card_appear", "pop")
    assert sfx_for_card_type("", fullscreen_card=True) == ("card_appear", "pop")
    assert sfx_for_card_type("footage") == ("", "")
    assert "picture_in" not in CARD_TYPE_TO_INTENT.values()
    assert CARD_TYPE_TO_INTENT["plaque"] != "picture_in"


def test_density_keeps_the_first_card_appear_of_the_slot(cfg):
    """Dynamic whoosh at t=0 used to eat the card click at t=0.4."""
    plan = {
        "video_id": "must022_density",
        "duration_sec": 12.0,
        "cta_window": [10.0, 12.0],
        "blocks": [{
            "id": "b1", "sfx": "none",
            "overlay": {"type": "source_card", "content": "X"},
        }],
        "slots": [{
            "index": 0, "start": 0.0, "end": 10.0, "kind": "footage",
            "block_id": "b1", "transition_in": "dynamic",
        }],
    }
    events = _plan_sfx(plan, cfg)
    cards = [e for e in events if e["intent"] == "card_appear"]
    pictures = [e for e in events if e["intent"] == "picture_in"]
    assert cards, events
    assert cards[0].get("keep") is True
    assert not pictures


def test_plaque_block_fires_plaque_intent_not_whoosh(cfg):
    plan = {
        "video_id": "must022_plaque",
        "duration_sec": 8.0,
        "cta_window": [6.0, 8.0],
        "blocks": [{
            "id": "b1", "sfx": "none",
            "overlay": {"type": "plaque", "content": "X"},
        }],
        "slots": [{
            "index": 0, "start": 0.0, "end": 6.0, "kind": "footage",
            "block_id": "b1", "transition_in": "cut",
        }],
    }
    events = _plan_sfx(plan, cfg)
    assert any(e["intent"] == "plaque" for e in events)
    assert not any(e["intent"] == "picture_in" for e in events)


def test_consecutive_picks_do_not_reuse_the_adjacent_bed():
    cfg = load_config()
    lib = open_library(cfg, "music")
    if len(lib.items) < 2:
        pytest.skip("в пуле меньше двух кроватей")
    first = pick_bed(cfg, want=[], video_id="must022_a")
    assert first is not None
    second = pick_bed(cfg, want=[], video_id="must022_b", bed_ring=[first.id])
    assert second is not None
    assert second.id != first.id


def test_adjacent_video_used_in_is_excluded_when_a_substitute_exists():
    cfg = load_config()
    lib = open_library(cfg, "music")
    used = next((item for item in lib.items if item.used_in), None)
    if used is None or len(lib.items) < 2:
        pytest.skip("нет беда с used_in или пул из одной кровати")
    vid = str(used.used_in[-1])
    picked = pick_bed(cfg, want=[], video_id="must022_c", adjacent_video_id=vid)
    assert picked is not None
    sharing = {item.id for item in lib.items if vid in set(item.used_in or ())}
    if sharing != {item.id for item in lib.items}:
        assert picked.id not in sharing


def test_catalog_caps_are_fifteen_beds_and_twenty_sfx(cfg):
    assert cfg.get("libraries.music.max_items") == BED_PICK_MAX == 15
    assert cfg.get("libraries.sfx.max_items") == SFX_PICK_MAX == 20


def test_missing_sfx_file_skips_without_crash(tmp_path):
    cfg = load_config()
    cfg.set("paths.assets_dir", str(tmp_path / "assets"))
    (tmp_path / "assets" / "sfx").mkdir(parents=True)
    assert pick_sfx(cfg, want=("click", "snap"), video_id="ghost") is None
    skipped = sfx_skipped_from_events([{
        "t": 0.4, "intent": "card_appear", "role": "pop",
        "status": "file_missing", "file": str(tmp_path / "no.wav"),
        "why": "карточка блока b1",
    }])
    assert skipped and skipped[0]["status"] == "file_missing"
