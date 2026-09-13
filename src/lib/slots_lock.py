"""Phrase-anchored slot lock. Chat authors it; Actions only obeys.

A lock line is {block, on, asset, plaque?, template?, avatar?}.
``on`` matches overlapping speech (not wall-clock seconds).
"""
from __future__ import annotations

from typing import Any

from .pin_match import overlapping_speech


def load_slots_lock(cfg: Any, video_id: str,
                    plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Pins file first, script/plan second."""
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
            "plaque": (str(item["plaque"]).strip()
                       if item.get("plaque") else ""),
            "template": str(item.get("template") or "").strip(),
            "avatar": bool(item.get("avatar")),
            "reuse": bool(item.get("reuse")),
        })
    return out


def lock_targets(spec: dict[str, Any], slots: list[dict[str, Any]],
                 words: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Slots whose spoken window contains the lock phrase."""
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
        lock: list[dict[str, Any]],
        default_span,
        max_sec: float = 3.5) -> tuple[float, float]:
    """Park a Latin plaque on the locked phrase, not the first footage of the block."""
    label = str(content or "").strip()
    spec = next((s for s in lock if s.get("plaque")
                 and s["plaque"].strip().upper() == label.upper()), None)
    if spec is None:
        return default_span()
    hits = lock_targets(spec, block_slots, words)
    footage = [
        s for s in hits
        if str(s.get("kind") or "") not in {"avatar", "split", "talking_head"}
    ]
    use = footage or hits
    if not use:
        return default_span()
    start = float(use[0]["start"])
    end = min(start + max_sec, float(use[-1]["end"]))
    if end - start < 0.35:
        end = min(start + max_sec, float(use[-1]["end"]))
    return round(start, 3), round(end, 3)
