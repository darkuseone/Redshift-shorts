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


# 0050 life-beats: speech first, then role. Opening «Навье-Стокса / жидкость»
# is fluids (water pins), not weather — weather is only «Погода».
_BEAT_SPEECH: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("blood", ("кров", "blood", "artery", "клетк", "извиня")),
    ("wing", ("крыл", "airplane", "wing")),
    ("pipes", ("труб", "pipe", "valve", "industrial")),
    ("weather", ("погод", "radar", "storm", "weather", "satellite")),
    ("fluids", ("навье", "уравнен", "жидкост", "стокс", "течёт", "течет", "толка")),
    ("stamp", ("клей", "приня", "reject", "stamp", "документ", "бумаг")),
    ("city", ("город", "ноч", "aerial", "traffic")),
    ("notebook", ("notebook", "тетрад", "записн")),
)
_BEAT_QUERY: dict[str, tuple[str, ...]] = {
    "weather": ("weather", "radar", "storm", "satellite"),
    "wing": ("airplane", "wing", "flight", "aircraft", "cloud"),
    "pipes": ("pipe", "valve", "industrial"),
    "blood": ("blood", "artery", "cell"),
    "fluids": ("fluid", "liquid", "vortex", "water", "current", "ink", "flow"),
    "stamp": ("stamp", "document", "paperwork", "stapling", "paper", "notebook"),
    "city": ("city", "night", "aerial", "traffic", "notebook"),
    "notebook": ("notebook",),
}


def slot_visual_beat(slot: dict[str, Any],
                     words: list[dict[str, Any]] | None) -> str:
    """One beat for this slot from overlapping speech, else authored intent."""
    speech = overlapping_speech(slot, words).lower()
    intent = str(slot.get("visual_intent") or "").lower()
    role = str(slot.get("role") or "")
    for beat, tokens in _BEAT_SPEECH:
        if any(token in speech for token in tokens):
            return beat
    if role == "twist" and any(token in intent for token in (
            "stamp", "reject", "clay", "paperwork", "документ")):
        return "stamp"
    if role == "cta" and any(token in intent for token in (
            "city", "night", "aerial", "notebook", "redshift")):
        return "city"
    return ""


def filter_queries_for_beat(queries: list[str], beat: str) -> list[str]:
    """Keep author queries that name this beat; otherwise leave the list."""
    markers = _BEAT_QUERY.get(str(beat or ""), ())
    if not markers:
        return list(queries)
    hit = [q for q in queries if any(m in str(q).lower() for m in markers)]
    return hit or list(queries)


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
    aid_l = aid.lower()
    role = str(slot.get("asset_role") or "")
    block_role = str(slot.get("role") or "")
    speech = overlapping_speech(slot, words).lower()
    intent = str(slot.get("visual_intent") or "").lower()
    hook_blob = f"{speech} {intent}".strip()
    bonus = 0
    if aid.startswith("press_"):
        press_blob = hook_blob if block_role == "hook" else speech
        if any(token in press_blob for token in (
                "nature", "опублик", "openai", "астра", "выклад", "gpt-6", "astra")):
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
    elif ("supercomputer" in aid or "server_room" in aid_l
          or any(token in aid for token in ("5200850", "1914869", "8112758"))):
        blob = hook_blob if block_role == "hook" else (speech or intent)
        if any(token in speech for token in (
                "суперкомп", "вселенн", "supercomputer")):
            bonus = -20
        elif any(token in blob for token in (
                "суперкомп", "вселенн", "supercomputer", "сервер",
                "датацентр", "data-center", "data center", "cluster", "gpu")):
            bonus = -16
        elif any(token in intent for token in (
                "суперкомп", "вселенн", "supercomputer")):
            bonus = -15
    elif "38431825" in aid:
        if block_role == "hook":
            # Hook already carries $1 000 000 as type; ticker would duplicate.
            bonus = 8
        elif any(token in speech for token in (
                "финальн", "подписк", "деньг", "миллион", "доллар")):
            bonus = -15
        elif any(token in intent for token in (
                "ticker", "money numbers", "stock market")):
            bonus = -14
        elif role == "evidence":
            bonus = 12
        else:
            # Ticker is a money shot. Equal-bonus score order used to put it
            # on the hook, then rebalance kept it there to get it off evidence.
            bonus = 8
    else:
        hay = speech or intent
        if "magnific_0050_" in aid_l:
            beat = slot_visual_beat(slot, words)
            kind = aid_l.rsplit("_", 1)[-1]
            intent = str(slot.get("visual_intent") or "").lower()
            queries = " ".join(str(q).lower() for q in (slot.get("queries") or []))
            hay = f"{intent} {queries}"
            markers = {
                "weather": ("weather", "radar", "storm", "satellite", "stormscreen"),
                "wing": ("airplane", "wing", "airfoil", "flight", "winglet"),
                "pipes": ("pipe", "valve", "industrial", "factorypipes"),
                "blood": ("blood", "plasma", "cell", "microscope", "plasmaflow"),
                "stamp": ("stamp", "reject", "paperwork", "deskstamp", "declined"),
                "city": ("city", "night", "aerial", "traffic", "notebook", "citynight"),
            }.get(kind, ())
            if kind and kind == beat:
                bonus = -22
            elif kind and markers and any(m in hay for m in markers):
                bonus = -20  # authored intent/queries even if speech window drifted
            else:
                bonus = 10
            try:
                rank = list(pin_prefer).index(aid)
            except ValueError:
                rank = 99
            return (bonus, rank)
        wall = any(token in aid_l for token in (
            "cracked", "peeling", "plaster", "rock_surface"))
        staple = "stapling" in aid_l or "staple" in aid_l
        hole = any(token in hay for token in ("дыр", "глух", "стен", "трещин"))
        busy = any(token in hay for token in (
            "агент", "сообщен", "публик", "спагетти", "вихр", "час", "lean"))
        flow = any(token in hay for token in (
            "поток", "вихр", "спагетти", "сингуляр", "жидкост", "пункт"))
        hours = any(token in hay for token in ("час", "восем", "агент", "lean"))
        water = any(token in aid_l for token in (
            "water_vortex", "river_current", "blue_ink", "7565432",
            "3111227", "1257662"))
        if water:
            blob = hook_blob if block_role == "hook" else hay
            # Develop «жидкость» is the Navier–Stokes life-beat, not the
            # setup river. Leave those slots for weather/wing/pipes/blood.
            beat = slot_visual_beat(slot, words)
            if beat in ("weather", "wing", "pipes", "blood"):
                bonus = 8
            elif beat == "fluids" or any(token in blob for token in (
                    "вод", "теч", "жидкост", "water", "vortex", "river",
                    "flowing", "ink")):
                bonus = -18
            elif hours:
                bonus = 8
        elif wall:
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
        elif staple or any(token in aid_l for token in (
                "2435788", "1033903", "1114799")):
            beat = slot_visual_beat(slot, words)
            if beat == "stamp" or any(token in hay for token in (
                    "публик", "документ", "бумаг", "клей", "clay", "приня",
                    "reject", "stamp")):
                bonus = -12
            elif hole:
                bonus = 18
        elif any(token in aid_l for token in (
                "chalkboard_eq", "writing_equations", "quad_formula")):
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
        elif any(token in aid_l for token in (
                "typing", "desk_code", "code_editor", "9127165", "7800435",
                "9115967")):
            if flow:
                bonus = 14
            elif any(token in hay for token in ("lean", "код", "проверя")):
                bonus = -10
        elif any(token in aid_l for token in ("8945319", "682745")):
            beat = slot_visual_beat(slot, words)
            if beat == "wing" or any(token in speech for token in (
                    "крыл", "самолёт", "самолет", "airplane", "wing", "flight")):
                bonus = -18
        elif any(token in aid_l for token in ("4175316", "3497298")):
            beat = slot_visual_beat(slot, words)
            if beat == "weather" or any(token in speech for token in (
                    "погод", "radar", "storm", "weather", "satellite",
                    "погод")):
                bonus = -18
        elif any(token in aid_l for token in ("8816084", "6468157", "2321764")):
            beat = slot_visual_beat(slot, words)
            if beat == "pipes" or any(token in speech for token in (
                    "труб", "pipe", "valve", "industrial")):
                bonus = -18
        elif any(token in aid_l for token in ("6468280", "2341975", "2989050")):
            beat = slot_visual_beat(slot, words)
            if beat == "blood" or any(token in speech for token in (
                    "кров", "blood", "artery", "клетк")):
                bonus = -18
        elif any(token in aid_l for token in (
                "5504514", "7749931", "3449792", "3543840")):
            beat = slot_visual_beat(slot, words)
            if beat in ("city", "notebook"):
                bonus = -18
        elif "library_books" in aid_l:
            if any(token in hay for token in (
                    "клей", "clay", "документ", "книг", "institute")):
                bonus = -12
            elif hole:
                bonus = 10
    try:
        rank = list(pin_prefer).index(aid)
    except ValueError:
        rank = 99
    return (bonus, rank)
