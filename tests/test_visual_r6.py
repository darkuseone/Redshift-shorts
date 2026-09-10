"""0042 visual r6: VO-gated punches, punch-family dedupe, empty end tagline."""

from __future__ import annotations

import json
from pathlib import Path

from src.lib.text import (
    enrich_overlay_punch, punch_families_overlap, spoken_onset_for_content,
)
from src.p11_assemble.assemble import gap_phrase, _retime_fullscreen_slots


ROOT = Path(__file__).resolve().parents[1]


def _words():
    sm = json.loads((ROOT / "assets/voice/redshift_0042/speech_map.json").read_text())
    out = []
    for b in sm["blocks"]:
        for w in b["words"]:
            ww = dict(w)
            ww["block_id"] = b["id"]
            out.append(ww)
    return out


def _script_block(bid: str):
    script = json.loads((ROOT / "scripts/redshift_0042.json").read_text())
    return next(b for b in script["blocks"] if b["id"] == bid)


def test_enrich_keeps_authored_two_word_overlay():
    assert enrich_overlay_punch(
        "Проверить нечем",
        "Проверить результат мы не можем — нечем.",
    ) == "Проверить нечем"


def test_enrich_expands_short_stub():
    out = enrich_overlay_punch("5 МИНУТ", "задача решена за пять минут.")
    assert "минут" in out.lower()
    assert "решена" in out.lower()


def test_enrich_keeps_long_single_word_punch():
    assert enrich_overlay_punch(
        "СИНГУЛЯРНОСТЬ",
        "За семнадцать часов она переложила его в Lean. "
        "За конечное время — сингулярность.",
    ) == "СИНГУЛЯРНОСТЬ"


def test_punch_family_overlap_nechem():
    assert punch_families_overlap("ПРОВЕРИТЬ НЕЧЕМ", "нечем")
    assert punch_families_overlap("Вообще ничем", "НЕЧЕМ")


def test_gap_phrase_blocks_future_punch():
    words = _words()
    b4 = _script_block("b4")
    early = gap_phrase(words, {"start": 18.5, "end": 19.7}, b4, used=set())
    assert "минут" not in early.lower()
    assert "решена" not in early.lower()
    late = gap_phrase(words, {"start": 29.5, "end": 31.8}, b4, used=set())
    assert "минут" in late.lower()


def test_retime_demotes_early_intentional_fs():
    words = _words()
    b4 = _script_block("b4")
    slots = [{
        "index": 10, "start": 18.42, "end": 19.62, "duration": 1.2,
        "kind": "fullscreen_text", "block_id": "b4",
        "content": "решена за пять минут",
        "reason": "полноэкранный текст (§5.2)",
    }]
    _retime_fullscreen_slots(slots, {"blocks": [b4]}, words)
    assert slots[0]["kind"] == "footage"


def test_retime_syncs_cached_stub_to_authored_punch():
    from src.p11_assemble.assemble import _sync_fullscreen_overlay_content

    b4 = {
        "id": "b4",
        "text": (
            "За семнадцать часов она переложила его в Lean. "
            "За конечное время — сингулярность."
        ),
        "emphasis_word": "сингулярность",
        "overlay": {"type": "fullscreen_text", "content": "СИНГУЛЯРНОСТЬ"},
    }
    slots = [{
        "index": 15, "start": 34.579, "end": 35.779, "duration": 1.2,
        "kind": "fullscreen_text", "block_id": "b4",
        "content": "За семнадцать часов",
        "reason": "полноэкранный текст (§5.2)",
    }]
    words = [
        {"display": "семнадцать", "start": 34.08, "end": 34.53, "block_id": "b4"},
        {"display": "часов", "start": 34.53, "end": 34.83, "block_id": "b4"},
        {"display": "сингулярность.", "start": 44.70, "end": 45.15, "block_id": "b4"},
    ]
    plan = {"blocks": [b4]}
    _sync_fullscreen_overlay_content(slots, plan)
    assert slots[0]["content"] == "СИНГУЛЯРНОСТЬ"
    _retime_fullscreen_slots(slots, plan, words)
    assert slots[0]["kind"] == "footage"


def test_hero_word_requires_spoken_overlap():
    from src.p11_assemble.assemble import _hero_content

    block = {
        "emphasis_word": "миллион",
        "text": "Миллион долларов за каждую. Пуанкаре закрыли.",
    }
    slot = {"start": 13.2, "end": 16.4, "role": "setup"}
    quiet = _hero_content(block, slot, None, words=[
        {"display": "уравнения", "start": 13.7, "end": 14.1},
        {"display": "Навье-Стокса", "start": 14.5, "end": 14.9},
    ])
    assert quiet["word"] == ""
    spoken = _hero_content(block, slot, None, words=[
        {"display": "Миллион", "start": 7.6, "end": 8.0},
    ])
    assert spoken["word"].lower() == "миллион"


def test_logo_brand_close_default_tagline_empty():
    from src.lib.render.hyperframes.templates import _LBC_DEFAULT_TAG, _lbc_copy
    assert _LBC_DEFAULT_TAG == ""
    wm, tag, url = _lbc_copy({"wordmark": "REDSHIFT", "tagline": "", "url": "redshift.shorts"})
    assert tag == ""
    assert url == "redshift.shorts"


def test_sync_overlays_from_script_restores_punch():
    from src.lib.text import sync_overlays_from_script

    plan = {
        "video_id": "redshift_0048",
        "blocks": [{
            "id": "b4",
            "overlay": {"type": "fullscreen_text", "content": "88 ЧАСОВ"},
        }],
    }
    script = {
        "blocks": [{
            "id": "b4",
            "overlay": {
                "type": "fullscreen_text",
                "content": "СИНГУЛЯРНОСТЬ",
                "template_hint": "text-fullscreen/impact-01",
            },
        }],
    }
    assert sync_overlays_from_script(plan, script=script) == 1
    assert plan["blocks"][0]["overlay"]["content"] == "СИНГУЛЯРНОСТЬ"


def test_script_overlay_beats_stale_hours_punch():
    """Stale «88 ЧАСОВ» must not park the card on «семнадцать часов»."""
    from src.lib.text import sync_overlays_from_script
    from src.p11_assemble.assemble import split_empty_at_authored_punch

    plan = {
        "blocks": [{
            "id": "b4",
            "text": (
                "За семнадцать часов она переложила его в Lean. "
                "За конечное время — сингулярность."
            ),
            "emphasis_word": "сингулярность",
            "overlay": {"type": "fullscreen_text", "content": "88 ЧАСОВ"},
        }],
    }
    sync_overlays_from_script(plan, script={"blocks": [{
        "id": "b4",
        "overlay": {"type": "fullscreen_text", "content": "СИНГУЛЯРНОСТЬ"},
    }]})
    slots = [{
        "index": 19, "start": 42.866, "end": 45.151, "duration": 2.285,
        "block_id": "b4", "kind": "footage", "needs_asset": True,
    }]
    words = [
        {"display": "часов", "start": 34.53, "end": 34.83, "block_id": "b4"},
        {"display": "сингулярность.", "start": 44.70, "end": 45.15, "block_id": "b4"},
    ]
    out = split_empty_at_authored_punch(
        slots, plan, {19: {"asset_id": "fp_rock_surface"}}, words)
    tails = [s for s in out if s.get("authored_punch")]
    assert len(tails) == 1
    assert float(tails[0]["start"]) >= 43.9
    assert float(tails[0]["end"]) == 45.151
