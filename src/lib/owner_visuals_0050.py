"""0050 owner visual QC — rewrite after P11, no new TTS/HeyGen."""
from __future__ import annotations

from typing import Any, Callable

_HERO_BAN = {
    "hero-devices/icons-behind-head",
    "hero-devices/footage-plate-pop",
    "hero-devices/card-stack-top",
    "hero-devices/exhibit-card",
}

_CHIP_ROTATION = [
    ("FLUIDS", "lower-thirds/dark-card", "lt_dark_card"),
    ("WEATHER", "lower-thirds/name-title", "lt_name_title"),
    ("AIRFOIL", "lower-thirds/note-pin", "lt_note_pin"),
    ("VALVES", "lower-thirds/metric-badge", "lt_metric_badge"),
    ("PLASMA", "lower-thirds/dark-card", "lt_dark_card"),
    ("REJECTED", "lower-thirds/name-title", "lt_name_title"),
    ("FOLLOWUP", "lower-thirds/note-pin", "lt_note_pin"),
]
_CHIP_MAP = {name: (tmpl, rend) for name, tmpl, rend in _CHIP_ROTATION}

_DECLINE = ("data-viz/decline-chart", "data-viz/mk-line-graph")
_COMPARE = {
    "values": [88.0, 17.0],
    "labels": ["SEARCH", "LEAN"],
    "unit": "h",
    "value_suffix": " h",
    "tone": "ink",
    "theme": "dark",
    "dark": True,
}
_HOOK_END = 3.2
_NO_RED = {
    "dark_card": True,
    "accent": False,
    "accent_underline": False,
    "no_red": True,
    "source_chip": True,
    "background": "dark",
    "position": "bottom",
    "clean_bar": False,
    "tone": "ink",
}


def _is_lone_six(text: str, params: dict[str, Any]) -> bool:
    val = params.get("value")
    values = params.get("values") or []
    return (
        (val in (6, 6.0) and not values)
        or (isinstance(values, list) and list(values) == [6])
        or str(text).strip() in {"6", "6.0"}
    )


def _relabel_stack(obj: dict[str, Any]) -> bool:
    text = str(obj.get("content") or "")
    params = dict(obj.get("params") or {})
    blob = " ".join((text, str(params.get("content") or "")))
    if "25 Y" not in blob and "7 · $1 000 000 · 25 Y" not in blob:
        return False
    obj["content"] = "7 TASKS · $1 000 000 · 25 YEARS"
    params["content"] = obj["content"]
    obj["params"] = params
    return True


def _force_compare(obj: dict[str, Any]) -> bool:
    tid = str(obj.get("template") or "")
    if tid not in _DECLINE:
        return False
    obj["template"] = "data-viz/compare-bars"
    obj["renderer"] = "dataviz"
    obj["params"] = dict(_COMPARE)
    return True


def _mute_hook_captions(plan: dict[str, Any]) -> int:
    fs_windows: list[tuple[float, float]] = [(0.0, _HOOK_END)]
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        if str(shot.get("kind")) == "fullscreen_text":
            fs_windows.append((float(shot.get("start") or 0), float(shot.get("end") or 0)))
    subs = list(plan.get("subtitles") or [])
    if not subs:
        return 0
    kept = []
    dropped = 0
    for su in subs:
        if not isinstance(su, dict):
            kept.append(su)
            continue
        start = float(su.get("start") or 0)
        display = str(su.get("display") or "")
        if any(a - 0.05 <= start < b for a, b in fs_windows):
            dropped += 1
            continue
        if display.strip() in {"Клей", "клей", "КЛЕЙ"}:
            su["display"] = "Clay"
            dropped += 1
        kept.append(su)
    if dropped:
        plan["subtitles"] = kept
    style = dict(plan.get("subtitle_style") or {})
    if int(style.get("baseline_y") or 0) >= 700:
        style["baseline_y"] = 520
        plan["subtitle_style"] = style
        dropped += 1
    return dropped


def _hold_hook_card(plan: dict[str, Any]) -> int:
    shots = plan.get("shots") or []
    if not shots:
        return 0
    changed = 0
    vortex = None
    hook0 = shots[0]
    vortex = hook0.get("file") or (hook0.get("params") or {}).get("media")
    for shot in shots:
        if float(shot.get("start") or 99) >= _HOOK_END:
            break
        if str(shot.get("kind")) == "fullscreen_text" and "$1" in str(shot.get("content") or ""):
            if vortex is None:
                vortex = shot.get("file")
            continue
        shot["kind"] = "fullscreen_text"
        shot["template"] = "intro-hooks/hook-number-slam"
        shot["renderer"] = "fullscreen_text"
        shot["content"] = "$1 000 000"
        shot["carries_line"] = True
        shot["hook"] = True
        shot["hero"] = None
        if vortex:
            shot["file"] = vortex
        params = dict(shot.get("params") or {})
        params["content"] = "$1 000 000"
        params["text"] = "$1 000 000"
        if vortex:
            params["media"] = vortex
        shot["params"] = params
        changed += 1
    return changed


def _chip_label(ovl: dict[str, Any]) -> str:
    params = ovl.get("params") or {}
    return str(params.get("text") or params.get("content") or ovl.get("content") or "").upper()


def _lock_cards(plan: dict[str, Any]) -> int:
    changed = 0
    has_browser = any(
        isinstance(o, dict) and str(o.get("template") or "").startswith("browser-ui/")
        for o in (plan.get("overlays") or [])
    )
    kept: list[dict[str, Any]] = []
    for ovl in list(plan.get("overlays") or []):
        if not isinstance(ovl, dict):
            kept.append(ovl)
            continue
        tmpl = str(ovl.get("template") or "")
        label = _chip_label(ovl)
        params = dict(ovl.get("params") or {})
        if has_browser and tmpl == "lower-thirds/source-domain" and "OPENAI" in label:
            changed += 1
            continue
        if label in _CHIP_MAP:
            want, rend = _CHIP_MAP[label]
            if tmpl != want:
                ovl["template"] = want
                ovl["renderer"] = rend
                changed += 1
            params.update(_NO_RED)
            ovl["params"] = params
        kept.append(ovl)
    plan["overlays"] = kept
    return changed


def apply_0050_owner_visuals(plan: dict[str, Any]) -> int:
    if str(plan.get("video_id") or "") != "redshift_0050":
        return 0
    changed = 0
    changed += _hold_hook_card(plan)
    changed += _mute_hook_captions(plan)
    changed += _lock_cards(plan)
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        if _relabel_stack(shot):
            changed += 1
        if _force_compare(shot):
            changed += 1
        credit = str(shot.get("credit") or "")
        if credit and "NASA" in credit.upper():
            if credit.strip() != "NASA":
                shot["credit"] = "NASA"
                changed += 1
        hero = shot.get("hero") if isinstance(shot.get("hero"), dict) else None
        if hero and str(hero.get("template") or "") in _HERO_BAN:
            hero["template"] = "hero-devices/headline-over-head"
            hero["renderer"] = "hero-headline-over"
            changed += 1
        if str(shot.get("template") or "") in _HERO_BAN:
            shot["template"] = "hero-devices/headline-over-head"
            changed += 1
        if _is_lone_six(str(shot.get("content") or ""), dict(shot.get("params") or {})):
            shot["content"] = "GPT-6 ASTRA"
            shot["template"] = "hero-devices/brand-pill"
            shot["params"] = {"content": "GPT-6 ASTRA"}
            changed += 1
        asset = str(shot.get("asset_id") or shot.get("file") or "")
        if "frostscan" in asset and float(shot.get("start") or 0) < _HOOK_END:
            shot["kind"] = "fullscreen_text"
            shot["template"] = "intro-hooks/hook-number-slam"
            shot["content"] = "$1 000 000"
            changed += 1
    kept: list[dict[str, Any]] = []
    for ovl in list(plan.get("overlays") or []):
        if not isinstance(ovl, dict):
            kept.append(ovl)
            continue
        params = dict(ovl.get("params") or {})
        content = str(params.get("content") or ovl.get("content") or "")
        if _is_lone_six(content, params):
            changed += 1
            continue
        if _relabel_stack(ovl):
            changed += 1
        if _force_compare(ovl):
            changed += 1
        kept.append(ovl)
    plan["overlays"] = kept
    return changed


def apply_0050_owner_visuals_after_p11(ctx: Any) -> int:
    try:
        plan = ctx.read("edit_plan_A.json")
    except Exception:
        return 0
    changed = apply_0050_owner_visuals(plan)
    if changed:
        ctx.write("edit_plan_A.json", plan)
    return changed


def wrap_p11_visuals(run_p11: Callable) -> Callable:
    def _wrapped(ctx):
        out = run_p11(ctx)
        apply_0050_owner_visuals_after_p11(ctx)
        return out
    _wrapped.__module__ = getattr(run_p11, "__module__", _wrapped.__module__)
    _wrapped.__name__ = getattr(run_p11, "__name__", _wrapped.__name__)
    return _wrapped
