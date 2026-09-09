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


# --- Q3.7: раскладки звука, потолок повтора, кольца (§10.1–10.4) -------------

import pytest

from src.lib.sfx_library import (
    DEFAULT_SCENARIO, SFX_SCENARIOS, pick_scenario, scenario_tags,
)


class TestTheSoundLayoutRotatesNotTheFiles:
    """Библиотека заморожена на двадцати записях — различие даёт отображение."""

    def test_three_named_layouts_exist(self):
        assert set(SFX_SCENARIOS) == {"glass", "impact", "soft"}
        assert DEFAULT_SCENARIO == "glass"

    def test_every_layout_answers_the_same_events(self):
        keys = [set(table) for table in SFX_SCENARIOS.values()]
        assert all(k == keys[0] for k in keys), "раскладки отвечают на разные события"

    def test_the_layouts_actually_differ_on_the_signature_event(self):
        cards = {name: table["card_appear"] for name, table in SFX_SCENARIOS.items()}
        assert len(set(cards.values())) == len(cards), f"раскладки совпали: {cards}"

    def test_an_event_outside_the_layout_falls_back_to_the_common_meaning(self):
        assert scenario_tags("impact", "meme") == INTENTS["meme"]

    def test_an_unknown_layout_is_the_common_meaning(self):
        assert scenario_tags("нет такой", "card_appear") == INTENTS["card_appear"]

    def test_medicine_goes_soft(self):
        assert pick_scenario(video_id="x", category="medicine") == "soft"

    def test_a_binary_vote_hits(self):
        assert pick_scenario(video_id="x", category="space",
                             cta_type="binary_vote") == "impact"

    def test_the_ring_overrides_the_preference(self):
        """Два соседних ролика не звучат одной раскладкой даже в одной рубрике."""
        first = pick_scenario(video_id="a", category="medicine")
        second = pick_scenario(video_id="a", category="medicine", recent=[first])
        assert second != first

    def test_the_choice_is_reproducible(self):
        """Пересборка того же ролика обязана дать ту же раскладку."""
        args = dict(video_id="redshift_0042", category="ai", cta_type="")
        assert pick_scenario(**args) == pick_scenario(**args)

    def test_a_full_ring_still_returns_a_layout(self):
        """Тишины не бывает: кольцо шире набора — берём что есть."""
        assert pick_scenario(video_id="x", recent=list(SFX_SCENARIOS)) in SFX_SCENARIOS


class TestTheSameFileDoesNotLoop:
    """§10.2: `sfx_min_gap_sec` разводит во времени, но не мешает петле."""

    def test_the_cap_is_in_the_config(self):
        cfg = load_config()
        assert int(cfg.get("limits.sfx_same_file_max", 0)) == 3

    def test_a_saturated_file_is_avoided_on_the_next_event(self, tmp_path):
        """Насыщенный id уходит в `avoid_ids` — это и есть механизм потолка."""
        cfg = load_config()
        counts = {"sfx_click_01": 3}
        cap = int(cfg.get("limits.sfx_same_file_max", 3))
        saturated = [aid for aid, n in counts.items() if n >= cap]
        assert saturated == ["sfx_click_01"]
        chosen = pick_sfx(cfg, want=("click", "snap"), video_id="redshift_9001",
                          avoid_ids=saturated)
        if chosen is not None:
            assert chosen.id != "sfx_click_01"


class TestTheBedRing:
    """§10.3: счётчик `used_in` не отвечает на вопрос «что играло вчера»."""

    def test_a_bed_in_the_ring_loses_to_an_equally_good_free_one(self):
        """Кольцо — тайбрейк при равном совпадении, а не поверх смысла.

        Совпадение тегов важнее свежести и остаётся таким: просили «пульс,
        техника» — получите пульс. Кольцо решает спор между бедами, которые
        подходят одинаково, — а именно там канал и звучит одинаково.
        """
        from collections import Counter

        from src.lib.manifest import open_library
        from src.lib.music_library import pick_bed

        cfg = load_config()
        lib = open_library(cfg, "music")
        shared = [tag for tag, n in Counter(
            t for item in lib.items for t in item.tags).items() if n >= 2]
        if not shared:
            pytest.skip("нет тега, который делят два беда — кольцу нечего решать")
        want = [shared[0]]
        free = pick_bed(cfg, want=want, video_id="redshift_9001")
        assert free is not None
        ringed = pick_bed(cfg, want=want, video_id="redshift_9001",
                          bed_ring=[free.id])
        assert ringed is not None and ringed.id != free.id

    def test_the_ring_does_not_override_meaning(self):
        """Единственный подходящий по смыслу бед берётся, даже если он в кольце."""
        from src.lib.manifest import open_library
        from src.lib.music_library import pick_bed

        cfg = load_config()
        lib = open_library(cfg, "music")
        unique = None
        for item in lib.items:
            others = {t for other in lib.items if other.id != item.id
                      for t in other.tags}
            solo = [t for t in item.tags if t not in others]
            if solo:
                unique = (item, solo[:1])
                break
        if unique is None:
            pytest.skip("нет беда с уникальным тегом")
        item, want = unique
        assert pick_bed(cfg, want=want, video_id="redshift_9001",
                        bed_ring=[item.id]).id == item.id

    def test_the_ring_is_stored_beside_the_ending_ring(self):
        import json
        from pathlib import Path

        cfg = load_config()
        prefs = json.loads(
            (Path(cfg.repo_root) / "config" / "editing_preferences.json")
            .read_text(encoding="utf-8"))
        assert "bed_ring" in prefs and "sfx_scenario_ring" in prefs
        assert "ending_ring" in prefs, "кольца живут в одном файле — одна механика"

    def test_pushing_a_ring_keeps_only_the_last_three(self):
        from src.lib.endings import RING_MAX, push_ring

        cfg = load_config()

        class _Cfg:
            repo_root = None

        import tempfile
        from pathlib import Path as _P

        with tempfile.TemporaryDirectory() as tmp:
            (_P(tmp) / "config").mkdir()
            (_P(tmp) / "config" / "editing_preferences.json").write_text(
                '{"version": 1}', encoding="utf-8")
            _Cfg.repo_root = _P(tmp)
            for value in ("a", "b", "c", "d"):
                out = push_ring(_Cfg(), "bed_ring", value)
            assert out == ["b", "c", "d"] and len(out) == RING_MAX

    def test_an_empty_value_does_not_enter_the_ring(self):
        from src.lib.endings import push_ring

        import tempfile
        from pathlib import Path as _P

        class _Cfg:
            repo_root = None

        with tempfile.TemporaryDirectory() as tmp:
            (_P(tmp) / "config").mkdir()
            (_P(tmp) / "config" / "editing_preferences.json").write_text(
                '{"version": 1, "bed_ring": ["a"]}', encoding="utf-8")
            _Cfg.repo_root = _P(tmp)
            assert push_ring(_Cfg(), "bed_ring", "") == ["a"]
