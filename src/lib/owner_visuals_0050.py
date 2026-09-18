"""0050 owner visual QC — rewrite after P11, no new TTS/HeyGen."""
from __future__ import annotations

from typing import Any, Callable

_HERO_BAN = {
    "hero-devices/icons-behind-head",
    "hero-devices/footage-plate-pop",
    "hero-devices/card-stack-top",
    "hero-devices/exhibit-card",
}

_RED_PLAQUE = {
    "lower-thirds/accent-underline",
    "lower-thirds/source-domain",
    "lower-thirds/tag-chips",
    "lower-thirds/timestamp-marker",
    "lower-thirds/progress-step",
    "lower-thirds/clean-bar",
}

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
        if start < _HOOK_END:
            dropped += 1
            continue
        if display.strip() in {"Клей", "клей", "КЛЕЙ"}:
            su["display"] = "Clay"
            dropped += 1
        kept.append(su)
    if dropped:
        plan["subtitles"] = kept
    style = dict(plan.get("subtitle_style") or {})
    if style.get("baseline_y") == 720:
        style["baseline_y"] = 520
        plan["subtitle_style"] = style
        dropped += 1
    return dropped


def _hold_hook_card(plan: dict[str, Any]) -> int:
    shots = plan.get("shots") or []
    if len(shots) < 2:
        return 0
    hook = shots[0]
    nxt = shots[1]
    if float(hook.get("start") or 0) > 0.2:
        return 0
    if str(nxt.get("role") or hook.get("role")) != "hook":
        return 0
    if str(nxt.get("kind")) == "fullscreen_text" and "$1" in str(nxt.get("content") or ""):
        return 0
    vortex = hook.get("file") or (hook.get("params") or {}).get("media")
    nxt["kind"] = "fullscreen_text"
    nxt["template"] = "intro-hooks/hook-number-slam"
    nxt["renderer"] = "fullscreen_text"
    nxt["content"] = "$1 000 000"
    nxt["carries_line"] = True
    nxt["hook"] = True
    nxt["file"] = vortex
    params = dict(hook.get("params") or {})
    params["content"] = "$1 000 000"
    params["text"] = "$1 000 000"
    if vortex:
        params["media"] = vortex
    nxt["params"] = params
    nxt["hero"] = None
    return 1


def _de_red_plaques(plan: dict[str, Any]) -> int:
    changed = 0
    for ovl in plan.get("overlays") or []:
        if not isinstance(ovl, dict):
            continue
        tmpl = str(ovl.get("template") or "")
        params = dict(ovl.get("params") or {})
        text = str(params.get("text") or params.get("content") or "").upper()
        if tmpl in _RED_PLAQUE or text in {"REJECTED", "FOLLOWUP", "FLUIDS", "WEATHER", "AIRFOIL", "VALVES", "PLASMA"}:
            if tmpl != "lower-thirds/dark-card":
                ovl["template"] = "lower-thirds/dark-card"
                ovl["renderer"] = "lt_dark_card"
                changed += 1
            params["dark_card"] = True
            params["accent"] = False
            params["accent_underline"] = False
            params["no_red"] = True
            params["source_chip"] = True
            params["background"] = "dark"
            ovl["params"] = params
    return changed


def apply_0050_owner_visuals(plan: dict[str, Any]) -> int:
    if str(plan.get("video_id") or "") != "redshift_0050":
        return 0
    changed = 0
    changed += _hold_hook_card(plan)
    changed += _mute_hook_captions(plan)
    changed += _de_red_plaques(plan)
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
