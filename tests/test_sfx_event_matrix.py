"""Card pop and avatar entry must be different files (P0b-2)."""

from __future__ import annotations

from src.lib.config import load_config
from src.lib.sfx_library import INTENTS, ROLE_TO_INTENT, WHOOSH_INTENTS, pick_sfx
from src.p10_audio.audio_build import _plan_sfx, _resolve_sfx


def test_intents_contains_card_appear():
    assert "card_appear" in INTENTS
    assert INTENTS["card_appear"] == ("click", "snap")


def test_card_appear_is_not_collapsed_as_a_whoosh():
    assert "card_appear" not in WHOOSH_INTENTS


def test_pop_role_maps_to_card_appear():
    assert ROLE_TO_INTENT["pop"] == "card_appear"


def test_card_appear_and_avatar_in_pick_different_files_within_two_seconds():
    cfg = load_config()
    plan = {
        "video_id": "redshift_0042",
        "duration_sec": 12.0,
        "cta_window": [10.0, 12.0],
        "blocks": [{
            "id": "b1",
            "sfx": "none",
            "overlay": {"type": "highlight", "content": "порог"},
        }, {
            "id": "b2",
            "sfx": "none",
            "overlay": {"type": "none"},
        }],
        "slots": [
            {"index": 0, "start": 0.0, "end": 2.0, "kind": "footage",
             "block_id": "b1", "transition_in": "cut"},
            {"index": 1, "start": 1.6, "end": 6.0, "kind": "avatar",
             "block_id": "b2", "transition_in": "cut"},
        ],
    }
    events = _plan_sfx(plan, cfg)
    card = next(e for e in events if e["intent"] == "card_appear")
    avatar = next(e for e in events if e["intent"] == "avatar_in")
    assert abs(card["t"] - avatar["t"]) <= 2.0 + 1e-6

    card_rec = _resolve_sfx(cfg, card, video_id=plan["video_id"], avoid_ids=())
    avatar_rec = _resolve_sfx(cfg, avatar, video_id=plan["video_id"], avoid_ids=())
    assert card_rec is not None and avatar_rec is not None
    assert card_rec.file != avatar_rec.file
    assert card_rec.id != avatar_rec.id

    # Same split via the tag dictionaries, independent of role short-circuit.
    by_intent_card = pick_sfx(cfg, want=INTENTS["card_appear"], video_id=plan["video_id"])
    by_intent_avatar = pick_sfx(cfg, want=INTENTS["avatar_in"], video_id=plan["video_id"])
    assert by_intent_card.file != by_intent_avatar.file


def test_cta_resolves_to_soft_whoosh_not_coin():
    cfg = load_config()
    plan = {
        "video_id": "redshift_0042",
        "duration_sec": 12.0,
        "cta_window": [10.0, 12.0],
        "blocks": [{"id": "b1", "sfx": "none", "overlay": {"type": "none"}}],
        "slots": [
            {"index": 0, "start": 0.0, "end": 10.0, "kind": "footage",
             "block_id": "b1", "transition_in": "cut"},
            {"index": 1, "start": 10.0, "end": 12.0, "kind": "footage",
             "block_id": "b1", "transition_in": "cut"},
        ],
    }
    events = _plan_sfx(plan, cfg)
    cta = next(e for e in events if e["intent"] == "subscribe_cta")
    assert cta["intent"] not in WHOOSH_INTENTS
    rec = _resolve_sfx(cfg, cta, video_id=plan["video_id"], avoid_ids=())
    assert rec is not None
    assert rec.id != "sfx_coin_pickup"
    assert "soft" in rec.tags
    assert INTENTS["subscribe_cta"] == ("whoosh", "soft")
    assert INTENTS["avatar_in"] == ("whoosh", "soft")


def test_avatar_in_resolves_to_existing_soft_whoosh():
    cfg = load_config()
    rec = pick_sfx(cfg, want=INTENTS["avatar_in"], video_id="redshift_0042")
    assert rec is not None
    from src.lib.manifest import open_library
    path = open_library(cfg, "sfx").file_path(rec)
    assert path.is_file(), path
    assert rec.id != "sfx_coin_pickup"
    assert "whoosh" in rec.tags or "soft" in rec.tags
