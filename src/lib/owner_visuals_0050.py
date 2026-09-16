"""0050 owner 5-frame QC — rewrite after P11, no new TTS/HeyGen."""
from __future__ import annotations

from typing import Any, Callable

_HERO_BAN = {
    "hero-devices/icons-behind-head",
    "hero-devices/footage-plate-pop",
    "hero-devices/card-stack-top",
    "hero-devices/exhibit-card",
}


def apply_0050_owner_visuals(plan: dict[str, Any]) -> int:
    if str(plan.get("video_id") or "") != "redshift_0050":
        return 0
    changed = 0
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        text = str(shot.get("content") or "")
        if text == "7 · $1 000 000 · 25 Y" or text.endswith("25 Y"):
            shot["content"] = "7 TASKS · $1 000 000 · 25 YEARS"
            params = dict(shot.get("params") or {})
            params["content"] = shot["content"]
            shot["params"] = params
            changed += 1
        hero = shot.get("hero") if isinstance(shot.get("hero"), dict) else None
        if hero and str(hero.get("template") or "") in _HERO_BAN:
            hero["template"] = "hero-devices/headline-over-head"
            hero["renderer"] = "hero-headline-over"
            changed += 1
        if str(shot.get("template") or "") in _HERO_BAN:
            shot["template"] = "hero-devices/headline-over-head"
            changed += 1
    kept: list[dict[str, Any]] = []
    for ovl in list(plan.get("overlays") or []):
        if not isinstance(ovl, dict):
            kept.append(ovl)
            continue
        tid = str(ovl.get("template") or "")
        params = dict(ovl.get("params") or {})
        content = str(params.get("content") or ovl.get("content") or "")
        val = params.get("value")
        values = params.get("values") or []
        lone_six = (
            (val in (6, 6.0) and not values)
            or (isinstance(values, list) and list(values) == [6])
            or content.strip() in {"6", "6.0"}
        )
        if lone_six:
            changed += 1
            continue
        if tid in ("data-viz/decline-chart", "data-viz/mk-line-graph"):
            ovl = dict(ovl)
            ovl["template"] = "data-viz/compare-bars"
            ovl["renderer"] = "dataviz"
            ovl["params"] = {
                "values": [88.0, 17.0],
                "labels": ["SEARCH", "LEAN"],
                "unit": "h",
                "value_suffix": " h",
                "tone": "ink",
                "theme": "dark",
                "dark": True,
            }
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
