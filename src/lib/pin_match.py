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
        else:
            bonus = 6
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
        elif any(token in aid_l for token in (
                "red_heartbeat", "red_pulse", "red_gradient")):
            # ECG / red wash is on-brand hue and still blows QC-30 as a plate.
            if any(token in hay for token in ("кров", "сердц", "пульс")):
                bonus = -8
            else:
                bonus = 22
        elif any(token in aid_l for token in (
                "water_vortex", "river_current", "blue_ink")):
            if any(token in hay for token in (
                    "вод", "жидк", "поток", "труб", "крыл", "погод",
                    "самолёт", "кров")):
                bonus = -18
            elif hole:
                bonus = 10
        elif any(token in aid_l for token in ("green_glitch", "matrix_code")):
            if any(token in hay for token in ("фурор", "openai")):
                bonus = 16
    try:
        rank = list(pin_prefer).index(aid)
    except ValueError:
        rank = 99
    return (bonus, rank)
