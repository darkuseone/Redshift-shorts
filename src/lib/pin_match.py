"""Match hard-prefer footage pins to the slot they actually belong on.

Prefer lists used to be consumed in list/score order. The first evidence
split then took a stock ticker while the Nature figure landed on «внутри»,
and the supercomputer hall sat on the twist instead of the spoken
«суперкомпьютеру». Matching looks at overlapping speech first.
"""

from __future__ import annotations

from typing import Any


def ctx_words(ctx: Any) -> list[dict[str, Any]]:
    """Word timings from the pipeline context; empty when the step has none."""
    reader = getattr(ctx, "read_or", None)
    if callable(reader):
        doc = reader("words.json", {}) or {}
        return list(doc.get("words") or [])
    reader = getattr(ctx, "read", None)
    if callable(reader):
        try:
            doc = reader("words.json") or {}
        except (KeyError, FileNotFoundError, OSError):
            return []
        return list(doc.get("words") or [])
    return []


def overlapping_speech(slot: dict[str, Any],
                       words: list[dict[str, Any]] | None) -> str:
    """Concatenation of words whose time window overlaps the slot."""
    if not words:
        return ""
    try:
        start = float(slot.get("start") or 0.0)
        end = float(slot.get("end") or 0.0)
    except (TypeError, ValueError):
        return ""
    parts: list[str] = []
    for word in words:
        try:
            ws = float(word.get("start") or 0.0)
            we = float(word.get("end") or 0.0)
        except (TypeError, ValueError):
            continue
        if we > start and ws < end:
            parts.append(str(word.get("display") or word.get("word") or ""))
    return " ".join(parts)


def pin_slot_prefer_key(asset_id: str, slot: dict[str, Any],
                        pin_prefer: list[str], *,
                        words: list[dict[str, Any]] | None = None,
                        ) -> tuple[int, int]:
    """Sort key for a prefer pin on this slot. Lower bonus wins.

    Speech overlap beats visual_intent: a whole-block intent like «скриншот
    статьи» is shared by every evidence split, so it cannot tell Nature from
    «внутри него».
    """
    aid = str(asset_id or "")
    role = str(slot.get("asset_role") or "")
    speech = overlapping_speech(slot, words).lower()
    intent = str(slot.get("visual_intent") or "").lower()
    bonus = 0
    if aid.startswith("press_"):
        if any(token in speech for token in ("nature", "опублик")):
            bonus = -25
        elif role == "evidence":
            bonus = -18
    elif "cryostat" in aid:
        hay = speech or intent
        if any(token in hay for token in (
                "криостат", "процессор", "чип", "cryostat", "chip")):
            bonus = -15
    elif "supercomputer" in aid:
        if any(token in speech for token in (
                "суперкомп", "вселенн", "supercomputer")):
            bonus = -20
        elif any(token in intent for token in (
                "суперкомп", "вселенн", "supercomputer")):
            bonus = -15
    elif "38431825" in aid:
        if any(token in speech for token in ("финальн", "подписк", "деньг")):
            bonus = -15
        elif role == "evidence":
            bonus = 12
        else:
            # Ticker is a money shot. Equal-bonus score order used to put it
            # on the hook, then rebalance kept it there to get it off evidence.
            bonus = 8
    try:
        rank = list(pin_prefer).index(aid)
    except ValueError:
        rank = 99
    return (bonus, rank)
