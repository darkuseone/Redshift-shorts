"""Phrase-anchored slot lock. Chat authors it; Actions only obeys.

A lock line is {block, on, asset, plaque?, template?, avatar?}.
``on`` matches overlapping speech (not wall-clock seconds).
"""
from __future__ import annotations

from typing import Any, Callable

from .pin_match import ctx_words, overlapping_speech


def load_slots_lock(cfg: Any, video_id: str,
                    plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    raw: list[Any] = []
    try:
        from ..p7_broll_search.search import _footage_pin_entry
        entry = _footage_pin_entry(cfg, str(video_id or ""))
        raw = list(entry.get("slots_lock") or [])
    except Exception:
        raw = []
    if not raw and plan:
        raw = list(plan.get("slots_lock") or [])
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        asset = str(item.get("asset") or "").strip()
        on = str(item.get("on") or "").strip()
        if not asset or not on:
            continue
        out.append({
            "block": str(item.get("block") or "").strip(),
            "on": on,
            "asset": asset,
            "plaque": (str(item["plaque"]).strip() if item.get("plaque") else ""),
            "template": str(item.get("template") or "").strip(),
            "avatar": bool(item.get("avatar")),
            "reuse": bool(item.get("reuse")),
        })
    return out


def lock_targets(spec: dict[str, Any], slots: list[dict[str, Any]],
                 words: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    needle = spec["on"].lower()
    bid = spec.get("block") or ""
    hits: list[dict[str, Any]] = []
    for slot in slots:
        if bid and str(slot.get("block_id") or "") != bid:
            continue
        speech = overlapping_speech(slot, words).lower()
        if needle and needle in speech:
            hits.append(slot)
    if hits:
        return hits
    tokens = [t for t in needle.split() if len(t) > 3]
    if not tokens:
        return []
    for slot in slots:
        if bid and str(slot.get("block_id") or "") != bid:
            continue
        speech = overlapping_speech(slot, words).lower()
        reason = str(slot.get("reason") or "").lower()
        if any(t in speech for t in tokens) or (
                "gap fill" in reason and any(t in speech for t in tokens)):
            hits.append(slot)
    return hits


def plaque_span_for_content(
        *, content: str, block_slots: list[dict[str, Any]],
        all_slots: list[dict[str, Any]], words: list[dict[str, Any]] | None,
        lock: list[dict[str, Any]], default_span, max_sec: float = 3.5):
    label = str(content or "").strip()
    spec = next((s for s in lock if s.get("plaque")
                 and s["plaque"].strip().upper() == label.upper()), None)
    if spec is None:
        return default_span()
    hits = lock_targets(spec, block_slots, words)
    footage = [s for s in hits if str(s.get("kind") or "") not in {"avatar", "split", "talking_head"}]
    use = footage or hits
    if not use:
        return default_span()
    start = float(use[0]["start"])
    end = min(start + max_sec, float(use[-1]["end"]))
    if end - start < 0.35:
        end = min(start + max_sec, float(use[-1]["end"]))
    return round(start, 3), round(end, 3)


def _accepted_map(doc: dict[str, Any]) -> dict[int, dict[str, Any]]:
    raw = (doc or {}).get("accepted") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for key, val in raw.items():
        try:
            out[int(key)] = val
        except (TypeError, ValueError):
            continue
    return out


def _donor_has_media(donor: dict[str, Any]) -> bool:
    return bool(donor.get("file") or donor.get("dst") or donor.get("path") or donor.get("local_path"))


def apply_lock_after_p8(ctx: Any) -> int:
    try:
        plan = ctx.read("cut_plan.json")
        doc = ctx.read("accepted_assets.json")
    except Exception:
        return 0
    lock = load_slots_lock(getattr(ctx, "cfg", None), str(plan.get("video_id") or ""), plan)
    if not lock:
        return 0
    words = ctx_words(ctx)
    accepted = _accepted_map(doc)
    by_id: dict[str, dict[str, Any]] = {}
    for entry in accepted.values():
        if isinstance(entry, dict) and entry.get("asset_id") and _donor_has_media(entry):
            by_id[str(entry["asset_id"])] = entry
    fill_roles = ("broll", "evidence", "meme", "interstitial")
    slots = [s for s in (plan.get("slots") or [])
             if s.get("needs_asset") and s.get("asset_role") in fill_roles]
    moved = 0
    for spec in lock:
        pid = spec["asset"]
        targets = lock_targets(spec, slots, words)
        if not targets:
            continue
        donor = by_id.get(pid)
        if donor is None or not _donor_has_media(donor):
            continue
        target_idx = int(targets[0]["index"])
        cur = accepted.get(target_idx) or {}
        if str(cur.get("asset_id") or "") == pid:
            continue
        if not spec.get("reuse"):
            for other_idx, entry in list(accepted.items()):
                if int(other_idx) == target_idx:
                    continue
                if str((entry or {}).get("asset_id") or "") == pid:
                    del accepted[int(other_idx)]
        accepted[target_idx] = {
            **donor,
            "slot_index": target_idx,
            "speech_locked": True,
            "fallback_reason": f"slots_lock:{spec['on']}",
        }
        moved += 1
    if not moved:
        return 0
    doc = dict(doc)
    doc["accepted"] = {str(k): v for k, v in accepted.items()}
    ctx.write("accepted_assets.json", doc)
    return moved


def retarget_plaques_after_p11(ctx: Any) -> int:
    try:
        plan = ctx.read("edit_plan_A.json")
        cut = ctx.read("cut_plan.json")
    except Exception:
        return 0
    lock = load_slots_lock(getattr(ctx, "cfg", None),
                           str((plan or cut).get("video_id") or ""), cut or plan)
    if not lock:
        return 0
    words = ctx_words(ctx)
    slots = list((plan or {}).get("slots") or (cut or {}).get("slots") or [])
    overlays = list((plan or {}).get("overlays") or [])
    if not overlays:
        return 0
    changed = 0
    for ovl in overlays:
        if not isinstance(ovl, dict):
            continue
        content = str((ovl.get("params") or {}).get("content") or ovl.get("content") or "").strip()
        if not content:
            continue
        spec = next((s for s in lock if s.get("plaque") and s["plaque"].upper() == content.upper()), None)
        if spec is None:
            continue
        start, end = plaque_span_for_content(
            content=content,
            block_slots=[s for s in slots if str(s.get("block_id") or "") == spec["block"]] or slots,
            all_slots=slots, words=words, lock=lock,
            default_span=lambda: (float(ovl.get("start") or 0), float(ovl.get("end") or 0)),
        )
        if abs(float(ovl.get("start") or 0) - start) < 0.05 and abs(float(ovl.get("end") or 0) - end) < 0.05:
            continue
        ovl["start"] = start
        ovl["end"] = end
        changed += 1
    if changed:
        plan = dict(plan)
        plan["overlays"] = overlays
        ctx.write("edit_plan_A.json", plan)
    return changed


def wrap_p8(run_p8: Callable) -> Callable:
    def _wrapped(ctx):
        out = run_p8(ctx)
        apply_lock_after_p8(ctx)
        return out
    return _wrapped


def wrap_p11(run_p11: Callable) -> Callable:
    def _wrapped(ctx):
        out = run_p11(ctx)
        retarget_plaques_after_p11(ctx)
        return out
    return _wrapped
