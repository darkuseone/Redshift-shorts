"""MUST-016: 3–5 смысловых EN-запросов, сущности блока, negatives."""

from __future__ import annotations

import json
from pathlib import Path

from src.lib.query import (
    QUERY_MAX, compile_slot_search, negative_reject_reason, search_report_payload,
    slot_negatives,
)
from src.p7_broll_search.search import _stage1_reject, pad_slot_queries
from src.lib.providers.stock import StockCandidate

REPO_ROOT = Path(__file__).resolve().parents[1]


def _script(name: str) -> dict:
    return json.loads((REPO_ROOT / "scripts" / name).read_text(encoding="utf-8"))


def _plan_from_script(script: dict) -> dict:
    meta = script.get("meta") or {}
    return {
        "blocks": script["blocks"],
        "sources": script.get("sources") or [],
        "category": meta.get("category", ""),
        "video_id": meta.get("video_id", ""),
        "meta": meta,
    }


def _slot_from_block(block: dict, index: int) -> dict:
    return {
        "index": index,
        "block_id": block["id"],
        "role": block.get("role", ""),
        "queries": list(block.get("broll_queries") or []),
        "visual_intent": block.get("visual_intent") or "",
    }


def _cand(**kwargs) -> StockCandidate:
    base = dict(id="x", source="pexels", kind="video", query="q", width=1080, height=1920,
                duration_sec=5.0, license="Pexels License", license_confirmed=True)
    base.update(kwargs)
    return StockCandidate(**base)


def test_queries_per_slot_capped_at_five(cfg):
    assert int(cfg.get("stock.queries_per_slot", 99)) <= QUERY_MAX


def test_willow_quantum_block_queries_carry_entity_not_random_pad():
    script = _script("redshift_0042.json")
    plan = _plan_from_script(script)
    block = next(b for b in script["blocks"] if b["id"] == "b2")
    slot = _slot_from_block(block, 1)
    compiled = compile_slot_search(slot, plan, count=5)
    queries = compiled["queries"]
    blob = " ".join(queries).lower()
    assert 3 <= len(queries) <= 5, queries
    assert all(q.isascii() for q in queries), queries
    assert any("willow" in q.lower() for q in queries), queries
    assert "north korea" not in blob
    assert "galaxy nebula" not in blob
    assert "newsroom" not in blob
    assert "Willow quantum chip" in compiled["entities"]
    assert "talking head" in compiled["negatives"]
    assert "stock smile lab" in compiled["negatives"]


def test_0042_and_0047_search_dump_is_three_to_five_with_entity():
    entries = []
    for name in ("redshift_0042.json", "redshift_0047.json"):
        script = _script(name)
        plan = _plan_from_script(script)
        for i, block in enumerate(script["blocks"]):
            slot = _slot_from_block(block, i)
            compiled = compile_slot_search(slot, plan, count=5)
            padded = pad_slot_queries(
                compiled["queries"], queries_per_slot=5,
                category=str(plan.get("category") or ""),
                slot=slot, plan=plan, entities=compiled["entities"])
            assert 3 <= len(padded) <= 5, (name, block["id"], padded)
            blob = " ".join(padded).lower()
            assert "north korea" not in blob
            entries.append({
                "slot_index": i,
                "queries": padded,
                "entities": compiled["entities"],
                "negatives": compiled["negatives"],
            })
        dump = search_report_payload(entries[-len(script["blocks"]):])
        for key, qs in dump["queries"].items():
            assert 3 <= len(qs) <= 5, (name, key, qs)
            assert dump["negatives"][key]


def test_kola_slot_does_not_pad_quantum_or_korea():
    script = _script("redshift_0047.json")
    plan = _plan_from_script(script)
    block = next(b for b in script["blocks"] if b["id"] == "b2")
    slot = _slot_from_block(block, 1)
    compiled = compile_slot_search(slot, plan, count=5)
    padded = pad_slot_queries(
        compiled["queries"], queries_per_slot=5,
        intent_kind="lab", category="science",
        slot=slot, plan=plan, entities=compiled["entities"])
    blob = " ".join(padded).lower()
    assert 3 <= len(padded) <= 5
    assert "quantum processor" not in blob
    assert "north korea" not in blob
    assert any("kola" in e.lower() or "borehole" in e.lower()
               for e in compiled["entities"]), compiled["entities"]
    assert any("kola" in q.lower() or "borehole" in q.lower() or "crust" in q.lower()
               or "drill" in q.lower() for q in padded), padded


def test_search_report_payload_shape():
    payload = search_report_payload([{
        "slot_index": 0,
        "queries": ["Willow quantum chip", "quantum computer laboratory wide",
                    "cryostat laboratory"],
        "entities": ["Willow quantum chip"],
        "negatives": ["talking head", "watermark"],
    }])
    assert payload["queries"]["0"][0].startswith("Willow")
    assert 3 <= len(payload["queries"]["0"]) <= 5
    assert payload["entities"]["0"] == ["Willow quantum chip"]
    assert "talking head" in payload["negatives"]["0"]


def test_stock_smile_lab_skipped_only_for_medicine_procedure():
    slot = {"block_id": "b1", "visual_intent": "", "queries": []}
    medicine = {"category": "medicine", "blocks": [
        {"id": "b1", "text": "Хирург проводит процедуру на открытом сердце."}]}
    other = {"category": "ai", "blocks": [
        {"id": "b1", "text": "Это квантовый чип."}]}
    assert "stock smile lab" not in slot_negatives(slot, medicine)
    assert "stock smile lab" in slot_negatives(slot, other)


def test_stage1_rejects_talking_head_negative(cfg):
    negatives = ["talking head", "watermark", "UI screenshot",
                 "clickbait thumbnail", "stock smile lab"]
    reason = _stage1_reject(
        _cand(tags=["talking head presenter"], attribution="vlog talking head"),
        cfg, 3.0, negatives=negatives)
    assert reason and "talking head" in reason
    clean = _stage1_reject(_cand(tags=["quantum", "chip"]), cfg, 3.0, negatives=negatives)
    assert clean is None


def test_negative_reject_reason_matches_aliases():
    assert negative_reject_reason("youtube thumbnail clickbait face",
                                  ["clickbait thumbnail"])
    assert negative_reject_reason("smiling scientist stock smile",
                                  ["stock smile lab"])
    assert not negative_reject_reason("quantum processor macro",
                                      ["talking head", "stock smile lab"])
