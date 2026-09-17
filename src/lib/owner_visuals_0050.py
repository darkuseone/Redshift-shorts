"""0050 owner visual QC — rewrite after P11, no new TTS/HeyGen."""
from __future__ import annotations

from typing import Any, Callable

_HERO_BAN = {
    "hero-devices/icons-behind-head",
    "hero-devices/footage-plate-pop",
    "hero-devices/card-stack-top",
    "hero-devices/exhibit-card",
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


def apply_0050_owner_visuals(plan: dict[str, Any]) -> int:
    if str(plan.get("video_id") or "") != "redshift_0050":
        return 0
    changed = 0
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
