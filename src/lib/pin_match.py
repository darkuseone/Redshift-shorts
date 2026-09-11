"""Match hard-prefer footage pins to the slot they actually belong on.

Prefer lists used to be consumed in list/score order. The first evidence
split then took a stock ticker while the Nature figure landed on «внутри»,
and the supercomputer hall sat on the twist instead of the spoken
«суперкомпьютеру». Matching looks at overlapping speech first.
"""

from __future__ import annotations

from typing import Any

from .query import PASSENGER_CABIN_MARKERS, _hay_has_marker


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
        # OpenAI card belongs on the article window, not on «Навье-Стокса».
        if any(token in speech for token in (
                "nature", "опублик", "openai", "выкладыва")):
            bonus = -25
        elif role == "evidence":
            bonus = -18
        else:
            bonus = 6
    elif any(token in aid for token in ("10884417", "16865644")):
        hay = speech or intent
        if any(token in hay for token in (
                "навье", "жидкост", "крыло", "труб", "крови", "кровь",
                "погод", "течёт")):
            bonus = -22
        elif any(token in hay for token in ("lean", "openai", "выкладыва")):
            bonus = 14
    elif "cryostat" in aid:
        hay = speech or intent
        if any(token in hay for token in (
                "криостат", "процессор", "чип", "cryostat", "chip",
                "нуле", "абсолют")):
            bonus = -15
        elif role == "evidence":
            # Leftover fill used to park the gold fridge on Nature «внутри».
            bonus = 8
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
    else:
        aid_l = aid.lower()
        hay = speech or intent
        wall = any(token in aid_l for token in (
            "cracked", "peeling", "plaster", "rock_surface"))
        staple = "stapling" in aid_l or "staple" in aid_l
        hole = any(token in hay for token in ("дыр", "глух", "стен", "трещин"))
        busy = any(token in hay for token in (
            "агент", "сообщен", "публик", "спагетти", "вихр", "час", "lean"))
        flow = any(token in hay for token in (
            "поток", "вихр", "спагетти", "сингуляр", "жидкост", "пункт"))
        hours = any(token in hay for token in ("час", "восем", "агент", "lean"))
        if wall:
            # 0048: drought/crack plates parked on «88 часов / 2.7 млн», while
            # the twist said «дыра в стене / глухой». Smooth plaster is a wall,
            # not a hole — leftover then parks cracked/peeling on the twist.
            cracked_like = any(token in aid_l for token in ("cracked", "peeling"))
            if hole:
                if cracked_like:
                    bonus = -22
                elif "plaster" in aid_l or "rock_surface" in aid_l:
                    bonus = 4
                else:
                    bonus = -10
            elif busy:
                bonus = 10
        elif staple:
            if any(token in hay for token in ("публик", "документ", "бумаг")):
                bonus = -12
            elif hole:
                bonus = 18
        elif any(token in aid_l for token in ("chalkboard_eq", "writing_equations")):
            if hours:
                bonus = -16
            elif hole or flow:
                bonus = 10
        elif "blackboard" in aid_l:
            # Walking body on the board — Gemini 0.4 on the 88-hours probe.
            if hours or flow:
                bonus = 12
        elif "white_ink" in aid_l:
            if "поток" in hay:
                bonus = -22
            elif flow:
                bonus = -16
            elif hours:
                bonus = 12
        elif "sand_ripples" in aid_l:
            if any(token in hay for token in ("вихр", "спагетти")):
                bonus = -18
            elif hours:
                bonus = 12
        elif any(token in aid_l for token in ("typing", "desk_code")):
            if flow:
                bonus = 14
            elif any(token in hay for token in ("lean", "код", "проверя")):
                bonus = -10
    try:
        rank = list(pin_prefer).index(aid)
    except ValueError:
        rank = 99
    return (bonus, rank)


def slot_locks_from_entry(entry: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Per-slot file locks. Prefer/deny lists are not a substitute."""
    raw = (entry or {}).get("slot_locks") or (entry or {}).get("slots") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and "t" in item]


def slot_lock_hits(lock: dict[str, Any], slot: dict[str, Any]) -> bool:
    """True when this lock's time window covers the slot."""
    try:
        t = float(lock.get("t"))
        start = float(slot.get("start") or 0.0)
        end = float(slot.get("end") or 0.0)
    except (TypeError, ValueError):
        return False
    kind = str(lock.get("kind") or "").strip()
    slot_kind = str(slot.get("kind") or "")
    if kind == "avatar" and slot_kind not in ("avatar", "split"):
        return False
    if kind == "footage" and slot_kind in ("avatar", "split"):
        return False
    try:
        min_dur = float(lock.get("min_duration") or 0.0)
    except (TypeError, ValueError):
        min_dur = 0.0
    if min_dur > 0:
        half = min_dur / 2.0
        return end > (t - half) and start < (t + half)
    return start - 1e-6 <= t < end + 1e-6


def exclusive_lock_owners(
        slots: list[dict[str, Any]],
        locks: list[dict[str, Any]]) -> dict[str, int]:
    """asset_id → slot index that exclusively owns that file."""
    owners: dict[str, int] = {}
    for lock in locks:
        if not lock.get("exclusive"):
            continue
        aid = str(lock.get("asset_id") or "")
        if not aid:
            continue
        for slot in slots:
            if slot_lock_hits(lock, slot):
                owners[aid] = int(slot["index"])
                break
    return owners


def _lock_asset_hay(asset: dict[str, Any]) -> str:
    return " ".join([
        str(asset.get("query") or ""),
        " ".join(str(t) for t in (asset.get("tags") or [])),
        str(asset.get("page_url") or ""),
        str(asset.get("asset_id") or ""),
    ])


def _fluid_fallback_rank(hay: str) -> tuple[int, int]:
    """Water/pipes first; cabin last. Wing is fluid-family but not NS water."""
    hay_l = str(hay or "").lower()
    water = _hay_has_marker(hay_l, ("water", "pipes", "pipe", "turbulence"))
    cabin = _hay_has_marker(hay_l, PASSENGER_CABIN_MARKERS)
    wing = _hay_has_marker(hay_l, ("wing", "airplane"))
    return (0 if water else 1 if not wing else 2, 1 if cabin else 0)


def resolve_locked_asset(
        lock: dict[str, Any],
        pool: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the locked id from already-accepted files. No download."""
    wanted: list[str] = []
    aid = lock.get("asset_id")
    if aid:
        wanted.append(str(aid))
    for extra in lock.get("fallback_asset_ids") or []:
        if extra:
            wanted.append(str(extra))
    by_id: dict[str, dict[str, Any]] = {}
    for item in pool:
        if not isinstance(item, dict):
            continue
        key = str(item.get("asset_id") or "")
        if key and key not in by_id:
            by_id[key] = item
    for key in wanted:
        if key in by_id:
            return by_id[key]
    if str(lock.get("fallback_kind") or "") != "fluid":
        return None
    ranked: list[tuple[tuple[int, int], dict[str, Any]]] = []
    waterish = ("water", "pipes", "pipe", "turbulence", "blood", "radar")
    for item in pool:
        if not isinstance(item, dict):
            continue
        hay = _lock_asset_hay(item)
        if not _hay_has_marker(hay, waterish):
            continue
        if _hay_has_marker(hay, ("wing", "airplane")) and not _hay_has_marker(
                hay, ("water", "pipes", "pipe")):
            continue
        ranked.append((_fluid_fallback_rank(hay), item))
    if not ranked:
        return None
    ranked.sort(key=lambda row: row[0])
    return ranked[0][1]


def apply_slot_locks(
        slots: list[dict[str, Any]],
        assets: dict[int, dict[str, Any]],
        entry: dict[str, Any] | None,
        extra_pool: list[dict[str, Any]] | None = None,
        ) -> dict[int, dict[str, Any]]:
    """Force locked asset_id onto overlapping slots. P11 glues; it does not re-pick.

    Empty ``asset_id`` + ``brand_plate`` clears the slot (avatar uses a brand
    grid, not a neighbour plate). Exclusive ids are removed from every slot
    that does not own that lock.
    """
    locks = slot_locks_from_entry(entry)
    if not locks:
        return assets
    out: dict[int, dict[str, Any]] = {}
    for key, value in assets.items():
        if value:
            out[int(key)] = value
    pool = list(out.values())
    if extra_pool:
        pool.extend(item for item in extra_pool if isinstance(item, dict))
    for lock in locks:
        deny = {str(x) for x in (lock.get("deny_asset_ids") or []) if x}
        brand = bool(lock.get("brand_plate")) or (
            not lock.get("asset_id") and str(lock.get("kind") or "") == "avatar")
        resolved = None if brand else resolve_locked_asset(lock, pool)
        for slot in slots:
            if not slot_lock_hits(lock, slot):
                continue
            idx = int(slot["index"])
            current = out.get(idx)
            if current and str(current.get("asset_id") or "") in deny:
                out.pop(idx, None)
            if brand:
                out.pop(idx, None)
                continue
            if resolved is None:
                continue
            if str(resolved.get("asset_id") or "") in deny:
                continue
            copied = dict(resolved)
            copied["slot_index"] = idx
            copied["slot_lock"] = True
            copied["speech_locked"] = True
            out[idx] = copied
    for idx, asset in list(out.items()):
        aid = str(asset.get("asset_id") or "")
        keep = False
        owned = False
        for lock in locks:
            if not lock.get("exclusive"):
                continue
            if str(lock.get("asset_id") or "") != aid:
                continue
            owned = True
            slot = next((s for s in slots if int(s["index"]) == int(idx)), None)
            if slot is not None and slot_lock_hits(lock, slot):
                keep = True
                break
        if owned and not keep:
            out.pop(idx, None)
    return out
