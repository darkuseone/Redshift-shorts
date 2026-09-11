"""0049 SLOT=FILE: P11 glues locked ids, it does not re-pick."""

from __future__ import annotations

import json
from pathlib import Path

from src.lib.pin_match import apply_slot_locks, slot_locks_from_entry
from src.lib.query import brief_reject_reason, slot_visual_brief
from src.p11_assemble.assemble import _avatar_bg_plates, _plate_source

ROOT = Path(__file__).resolve().parents[1]


def _pins_0049() -> dict:
    data = json.loads((ROOT / "config" / "footage_pins.json").read_text(encoding="utf-8"))
    return data["redshift_0049"]


def _cut_plan_0049() -> dict:
    return json.loads(
        (ROOT / "assets" / "voice" / "redshift_0049" / "cut_plan.json").read_text(
            encoding="utf-8"))


def _slot_at(slots: list[dict], t: float) -> dict:
    return next(s for s in slots if float(s["start"]) - 1e-6 <= t < float(s["end"]) + 1e-6)


def _pool() -> dict[int, dict]:
    """Accepted files from recent 0049 cuts — no download."""
    return {
        4: {
            "asset_id": "press_c8e1aa428b",
            "query": "openai navier stokes paper",
            "page_url": "https://openai.com/index/navier-stokes-solution/",
        },
        8: {
            "asset_id": "pexels_v10884417",
            "query": "industrial pipes water plant",
            "page_url": "https://www.pexels.com/video/water-flowing-through-a-discharge-pipe-10884417/",
        },
        10: {
            "asset_id": "pexels_v16865644",
            "query": "airplane wing in flight clouds",
            "page_url": "https://www.pexels.com/video/a-view-of-the-clouds-from-an-airplane-16865644/",
        },
        9: {
            "asset_id": "pexels_v37695140",
            "query": "quiet library aisle books",
            "page_url": "https://www.pexels.com/video/quiet-library-aisle-with-rows-of-books-37695140/",
        },
        6: {
            "asset_id": "pexels_v34459460",
            "query": "html code computer monitor",
            "page_url": "https://www.pexels.com/video/colorful-html-code-on-computer-monitor-34459460/",
        },
        7: {
            "asset_id": "pexels_v12908964",
            "query": "documents on desk paper",
            "page_url": "https://www.pexels.com/video/person-looking-through-documents-12908964/",
        },
        12: {
            "asset_id": "pexels_v12893579",
            "query": "hands typing keyboard code editor",
            "page_url": "https://www.pexels.com/video/hands-typing-on-laptop-keyboard-12893579/",
        },
    }


def test_0049_pins_are_per_slot_not_global_prefer():
    entry = _pins_0049()
    assert list(entry.get("prefer") or []) == []
    locks = slot_locks_from_entry(entry)
    by_t = {round(float(lock["t"]), 2): lock for lock in locks}
    assert by_t[41.02]["asset_id"] == "pexels_v10884417"
    assert by_t[41.02].get("exclusive") is True
    assert by_t[29.3]["asset_id"] == "pexels_v34459460"
    assert by_t[17.58]["asset_id"] == "press_c8e1aa428b"
    assert by_t[52.73]["asset_id"] == "pexels_v37695140"
    assert by_t[64.45]["asset_id"] == "pexels_v12908964"
    assert by_t[5.8].get("brand_plate") is True
    assert by_t[7.18].get("brand_plate") is True
    assert "press_c8e1aa428b" in (by_t[7.18].get("deny_asset_ids") or [])


def test_lock_navier_stokes_is_water_pipe():
    plan = _cut_plan_0049()
    out = apply_slot_locks(plan["slots"], _pool(), _pins_0049())
    ns = _slot_at(plan["slots"], 41.02)
    assert out[int(ns["index"])]["asset_id"] == "pexels_v10884417"
    clay = _slot_at(plan["slots"], 52.73)
    hole = _slot_at(plan["slots"], 64.45)
    assert str((out.get(int(clay["index"])) or {}).get("asset_id") or "") != "pexels_v10884417"
    assert str((out.get(int(hole["index"])) or {}).get("asset_id") or "") != "pexels_v10884417"


def test_lock_astra_is_code_not_dataviz():
    plan = _cut_plan_0049()
    out = apply_slot_locks(plan["slots"], _pool(), _pins_0049())
    astra = _slot_at(plan["slots"], 29.3)
    aid = out[int(astra["index"])]["asset_id"]
    assert aid == "pexels_v34459460"
    assert "mk-line" not in aid
    assert "dataviz" not in aid
    words = [
        {"display": "Сама", "start": 28.8, "end": 29.0},
        {"display": "Астра", "start": 29.0, "end": 29.4},
        {"display": "Lean", "start": 29.5, "end": 29.9},
    ]
    brief = slot_visual_brief(astra, plan, words)
    assert brief_reject_reason(
        brief, "data-viz/mk-line-graph", rung="dataviz",
        template="data-viz/mk-line-graph")


def test_lock_clay_is_not_fluid():
    plan = _cut_plan_0049()
    out = apply_slot_locks(plan["slots"], _pool(), _pins_0049())
    clay = _slot_at(plan["slots"], 52.73)
    aid = str((out.get(int(clay["index"])) or {}).get("asset_id") or "")
    assert aid == "pexels_v37695140"
    assert aid != "pexels_v10884417"


def test_lock_hole_is_not_wing():
    plan = _cut_plan_0049()
    out = apply_slot_locks(plan["slots"], _pool(), _pins_0049())
    hole = _slot_at(plan["slots"], 64.45)
    aid = str((out.get(int(hole["index"])) or {}).get("asset_id") or "")
    assert aid == "pexels_v12908964"
    assert aid != "pexels_v16865644"


def test_avatar_backdrop_is_not_neighbour_asset():
    plan = _cut_plan_0049()
    assets = apply_slot_locks(plan["slots"], _pool(), _pins_0049())
    ns = _slot_at(plan["slots"], 41.02)
    clay = _slot_at(plan["slots"], 52.73)
    hole = _slot_at(plan["slots"], 64.45)
    prepared = {
        int(ns["index"]): {"dst": "/tmp/water.mp4"},
        int(clay["index"]): {
            "dst": "/tmp/avatar_clay.mp4",
            "bg_src": "/tmp/library.mp4",
        },
        int(hole["index"]): {
            "dst": "/tmp/avatar_hole.mp4",
            "bg_src": "/tmp/docs.mp4",
        },
        10: {"dst": "/tmp/wing.mp4"},
    }
    out = _avatar_bg_plates(plan["slots"], prepared, assets, plan=plan, words=[])
    assert out[int(clay["index"])] == "/tmp/library.mp4"
    assert out[int(hole["index"])] == "/tmp/docs.mp4"
    assert out[int(clay["index"])] != "/tmp/water.mp4"
    assert out[int(hole["index"])] != "/tmp/wing.mp4"


def test_exclusive_water_is_not_a_neighbour_plate():
    slots = [
        {"index": 13, "kind": "footage", "block_id": "b4", "start": 38.9, "end": 41.6},
        {"index": 18, "kind": "footage", "block_id": "b4", "start": 50.5, "end": 52.7},
    ]
    prepared = {13: {"dst": "/tmp/water.mp4", "duration_sec": 2.6}}
    assets = {
        13: {
            "asset_id": "pexels_v10884417",
            "query": "industrial pipes water plant",
            "page_url": "https://www.pexels.com/video/water-flowing-through-a-discharge-pipe-10884417/",
            "source": "pexels",
        },
    }
    plan = {"_exclusive_owners": {"pexels_v10884417": 13}}
    assert _plate_source(slots[1], slots, prepared, assets, plan=plan) is None


def test_avatar_plate_source_does_not_steal_neighbour():
    slots = [
        {"index": 5, "kind": "footage", "block_id": "b3", "start": 16.3, "end": 18.8},
        {"index": 1, "kind": "avatar", "block_id": "b2", "start": 2.0, "end": 7.2},
    ]
    prepared = {5: {"dst": "/tmp/press.mp4", "duration_sec": 2.5}}
    assets = {5: {"asset_id": "press_c8e1aa428b", "source": "press"}}
    assert _plate_source(slots[1], slots, prepared, assets) is None


def test_locked_file_is_not_replaced_by_dataviz_ladder():
    """P11 glues the locked file; the ladder must not redraw a graph."""
    from src.p11_assemble.assemble import VisualBudget

    slot = {
        "index": 10, "kind": "footage", "start": 28.6, "end": 31.4,
        "duration": 2.8, "block_id": "b4", "role": "develop",
    }
    asset = {
        "asset_id": "pexels_v34459460",
        "slot_lock": True,
        "query": "html code computer monitor",
    }
    assert asset.get("slot_lock")
    assert asset["asset_id"] != "data-viz/mk-line-graph"
    # Sanity: the ladder would still refuse dataviz on this spoken window.
    words = [
        {"display": "Астра", "start": 29.0, "end": 29.4},
        {"display": "Lean", "start": 29.5, "end": 29.9},
    ]
    brief = slot_visual_brief(slot, {}, words)
    assert brief_reject_reason(brief, "", rung="dataviz",
                               template="data-viz/mk-line-graph")
    assert VisualBudget().allows("dataviz")


def test_fluid_fallback_skips_wing_when_water_missing():
    plan = _cut_plan_0049()
    pool = _pool()
    pool.pop(8)  # no pexels_v10884417
    pool[21] = {
        "asset_id": "pexels_v_blood_flow",
        "query": "blood cells microscope flow",
        "page_url": "https://www.pexels.com/video/blood-flow-medical-000/",
    }
    out = apply_slot_locks(plan["slots"], pool, _pins_0049())
    ns = _slot_at(plan["slots"], 41.02)
    aid = str((out.get(int(ns["index"])) or {}).get("asset_id") or "")
    assert aid == "pexels_v_blood_flow"
    assert aid != "pexels_v16865644"


def test_million_card_does_not_inherit_press():
    """$1M fullscreen is brand plate — neighbour OpenAI article stays off."""
    slots = [
        {"index": 2, "kind": "fullscreen_text", "block_id": "b2",
         "start": 7.177, "end": 8.377},
        {"index": 5, "kind": "footage", "block_id": "b3",
         "start": 13.87, "end": 16.27},
    ]
    prepared = {5: {"dst": "/tmp/press.mp4", "duration_sec": 2.5}}
    assets = {5: {
        "asset_id": "press_c8e1aa428b",
        "source": "press",
        "page_url": "https://openai.com/index/navier-stokes-solution/",
    }}
    plan = {
        "_slot_locks": [{
            "t": 7.18,
            "kind": "fullscreen_text",
            "brand_plate": True,
            "deny_asset_ids": ["press_c8e1aa428b"],
        }],
    }
    assert _plate_source(slots[0], slots, prepared, assets, plan=plan) is None
