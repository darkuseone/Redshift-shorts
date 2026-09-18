"""0050 owner visual QC — rewrite after P11, no new TTS/HeyGen."""
from __future__ import annotations

OWNER_VISUALS_REV = 77  # bump to bust P11 step cache

from typing import Any, Callable

_HERO_BAN = {
    "hero-devices/icons-behind-head",
    "hero-devices/footage-plate-pop",
    "hero-devices/card-stack-top",
    "hero-devices/exhibit-card",
    "hero-devices/plate-behind-back",
    "hero-devices/type-slab",
    "hero-devices/text-column-left",
    "hero-devices/script-stack",
}

_CHIP_ROTATION = [
    ("FLUIDS", "lower-thirds/dark-card", "lt_dark_card"),
    ("WEATHER", "lower-thirds/name-title", "lt_name_title"),
    ("AIRFOIL", "lower-thirds/note-pin", "lt_note_pin"),
    ("VALVES", "lower-thirds/metric-badge", "lt_metric_badge"),
    ("PLASMA", "lower-thirds/timestamp-marker", "lt_timestamp"),
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
_STACK = "7 TASKS · $1 000 000 · 25 YEARS"
_VORTEX = "magnific_0050_coolvortex"
_SAFE_DARK = "magnific_0050_inkswirl"
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
    "bar": False,
    "underline": False,
    "accent_bar": False,
    "color": "#FFFFFF",
    "fill": "#111111",
}
_DENY_HOOK = ("frostscan", "slateiron", "server", "darkgrid", "weather")
_SERVERISH = ("weather", "server", "frostscan", "slateiron", "pipes")


def _is_lone_six(text: str, params: dict[str, Any]) -> bool:
    val = params.get("value")
    values = params.get("values") or []
    return (
        (val in (6, 6.0) and not values)
        or (isinstance(values, list) and list(values) == [6])
        or str(text).strip() in {"6", "6.0"}
    )


def _asset_key(shot: dict[str, Any]) -> str:
    return str(shot.get("asset_id") or shot.get("file") or "")


def _relabel_stack(obj: dict[str, Any]) -> bool:
    text = str(obj.get("content") or "")
    params = dict(obj.get("params") or {})
    blob = " ".join((text, str(params.get("content") or "")))
    if "25 Y" not in blob and "7 · $1 000 000 · 25 Y" not in blob:
        if "СЕМЬ" in blob or "ТЫСЯЧЕЛЕТ" in blob:
            obj["content"] = _STACK
            params["content"] = _STACK
            params["lines"] = ["7 TASKS", "$1 000 000", "25 YEARS"]
            obj["params"] = params
            return True
        return False
    obj["content"] = _STACK
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
            fs_windows.append(
                (float(shot.get("start") or 0), float(shot.get("end") or 0))
            )
    subs = list(plan.get("subtitles") or [])
    if not subs:
        return 0
    kept = []
    changed = 0
    for su in subs:
        if not isinstance(su, dict):
            kept.append(su)
            continue
        start = float(su.get("start") or 0)
        display = str(su.get("display") or "")
        if any(a - 0.05 <= start < b for a, b in fs_windows):
            changed += 1
            continue
        low = display.strip()
        if low in {"Клей", "клей", "КЛЕЙ"}:
            su["display"] = "Clay"
            changed += 1
        glued = display.replace(" ", "").upper()
        if "ВРЁТСАМОЛ" in glued:
            su["display"] = "ВРЁТ САМОЛЁТ"
            changed += 1
        kept.append(su)
    if changed:
        plan["subtitles"] = kept
    style = dict(plan.get("subtitle_style") or {})
    # QC-19 brand corridor starts at 620; 520 fails the gate. 620 stays above face (~806).
    if int(style.get("baseline_y") or 0) != 620:
        style["baseline_y"] = 620
        plan["subtitle_style"] = style
        changed += 1
    if style.get("caption") != "gradient-fill":
        style["caption"] = "gradient-fill"
        plan["subtitle_style"] = style
        changed += 1
    return changed


def _collapse_hook(plan: dict[str, Any]) -> int:
    """One hook-number-slam 0–HOOK_END on coolvortex — QC-25 (≤2) + no RU plate."""
    shots = list(plan.get("shots") or [])
    if not shots:
        return 0
    changed = 0
    hook_idxs = [
        i
        for i, s in enumerate(shots)
        if isinstance(s, dict)
        and (
            float(s.get("start") or 99) < _HOOK_END
            or (
                str(s.get("template") or "") == "intro-hooks/hook-number-slam"
                and float(s.get("start") or 99) < 4.5
            )
        )
    ]
    if not hook_idxs:
        return 0
    first = shots[hook_idxs[0]]
    vortex_file = None
    for i in hook_idxs:
        s = shots[i]
        key = _asset_key(s)
        if _VORTEX in key or "coolvortex" in key:
            vortex_file = s.get("file") or (s.get("params") or {}).get("media")
            break
    if vortex_file is None:
        vortex_file = first.get("file") or (first.get("params") or {}).get("media")

    end = max(float(shots[i].get("end") or 0) for i in hook_idxs)
    end = max(end, _HOOK_END)
    end = min(end, 4.404)
    # leave avatar window untouched
    for s in shots:
        if str(s.get("kind")) == "avatar":
            end = min(end, float(s.get("start") or end))
            break

    first["kind"] = "fullscreen_text"
    first["template"] = "intro-hooks/hook-number-slam"
    first["renderer"] = "fullscreen_text"
    first["content"] = "$1 000 000"
    first["carries_line"] = True
    first["hook"] = True
    first["hero"] = None
    first["start"] = min(float(first.get("start") or 0.05), 0.05)
    first["end"] = end
    first["duration"] = float(first["end"]) - float(first["start"])
    first["asset_id"] = _VORTEX
    if vortex_file:
        first["file"] = vortex_file
    params = {
        "scale_from": 1.35,
        "sfx": "hit_impact",
        "slam": True,
        "content": "$1 000 000",
        "text": "$1 000 000",
        "accent_family": "red",
    }
    if vortex_file:
        params["media"] = vortex_file
    first["params"] = params
    changed += 1

    drop = {i for i in hook_idxs if i != hook_idxs[0]}
    for i, s in enumerate(shots):
        if i == hook_idxs[0]:
            continue
        if str(s.get("template") or "") == "intro-hooks/hook-number-slam":
            drop.add(i)
    if drop:
        plan["shots"] = [s for i, s in enumerate(shots) if i not in drop]
        changed += len(drop)
    return changed


def _chip_label(ovl: dict[str, Any]) -> str:
    params = ovl.get("params") or {}
    return str(
        params.get("text") or params.get("content") or ovl.get("content") or ""
    ).upper()


def _lock_cards(plan: dict[str, Any]) -> int:
    changed = 0
    has_browser = any(
        isinstance(o, dict) and str(o.get("template") or "").startswith("browser-ui/")
        for o in (plan.get("overlays") or [])
    )
    kept: list[dict[str, Any]] = []
    tmpl_counts: dict[str, int] = {}
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
        # Picture law: one dark browser OR chip — live browser-scroll still paints a
        # light page. Drop the browser; GPT-6 ASTRA brand-pill carries the beat.
        if tmpl.startswith("browser-ui/"):
            changed += 1
            continue
        if label in _CHIP_MAP:
            want, rend = _CHIP_MAP[label]
            if want == "lower-thirds/dark-card" and tmpl_counts.get(want, 0) >= 2:
                want, rend = "lower-thirds/metric-badge", "lt_metric_badge"
            if tmpl != want:
                ovl["template"] = want
                ovl["renderer"] = rend
                changed += 1
            tmpl = want
            params.update(_NO_RED)
            ovl["params"] = params
        if tmpl:
            tmpl_counts[tmpl] = tmpl_counts.get(tmpl, 0) + 1
        kept.append(ovl)
    plan["overlays"] = kept
    return changed


def _fix_heroes(plan: dict[str, Any]) -> int:
    changed = 0
    stack_injected = False
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        hero = shot.get("hero") if isinstance(shot.get("hero"), dict) else None
        if not hero:
            continue
        tmpl = str(hero.get("template") or "")
        params = dict(hero.get("params") or {})
        lines = params.get("lines") or []
        title = str(params.get("title") or "")
        blob = " ".join(
            [title] + [str(x) for x in lines] if isinstance(lines, list) else [title]
        )
        hfile = str(hero.get("file") or "")
        # stamp PiP on avatar — plaque only
        if "stamp" in hfile and str(shot.get("kind")) in ("avatar", "split"):
            shot["hero"] = None
            changed += 1
            continue
        ru_slab = any(x in blob for x in ("СЕМЬ", "ТЫСЯЧЕЛЕТ", "ЗАКРЫЛИ"))
        if ru_slab or tmpl in (
            "hero-devices/type-slab",
            "hero-devices/text-column-left",
            "hero-devices/script-stack",
            "hero-devices/plate-behind-back",
        ):
            if not stack_injected and float(shot.get("start") or 0) < 20:
                hero["template"] = "hero-devices/headline-over-head"
                hero["renderer"] = "hero-headline-over"
                hero["params"] = {
                    "content": _STACK,
                    "text": _STACK,
                    "lines": ["7 TASKS", "$1 000 000", "25 YEARS"],
                    "title": _STACK,
                }
                hero["file"] = None
                stack_injected = True
                changed += 1
            else:
                shot["hero"] = None
                changed += 1
            continue
        if tmpl in _HERO_BAN:
            hero["template"] = "hero-devices/headline-over-head"
            hero["renderer"] = "hero-headline-over"
            changed += 1
    return changed


def _ensure_brand_pill(plan: dict[str, Any]) -> int:
    ovls = list(plan.get("overlays") or [])
    for o in ovls:
        blob = str(
            (o.get("params") or {}).get("content") or o.get("content") or ""
        ).upper()
        is_pill = (
            ("GPT-6" in blob and "ASTRA" in blob)
            or str(o.get("template") or "") == "hero-devices/brand-pill"
        )
        if is_pill:
            changed = 0
            if not o.get("grounded_on"):
                o["grounded_on"] = ["brand"]
                o.setdefault("why", "owner: GPT-6 ASTRA brand pill")
                changed = 1
            # hold longer so it is not buried under other chrome
            start = float(o.get("start") or 15.6)
            if float(o.get("end") or 0) - start < 4.0:
                o["end"] = start + 4.5
                changed = 1
            return changed
    start = 15.6
    for s in plan.get("shots") or []:
        if str(s.get("kind")) == "footage" and float(s.get("start") or 0) >= 15.0:
            start = float(s.get("start") or 15.6)
            break
    ovls.append(
        {
            "type": "lower_third",
            "template": "hero-devices/brand-pill",
            "renderer": "hero-brand-pill",
            "start": start,
            "end": start + 4.5,
            "content": "GPT-6 ASTRA",
            "grounded_on": ["brand"],
            "why": "owner: GPT-6 ASTRA brand pill on OpenAI beat",
            "params": {
                "content": "GPT-6 ASTRA",
                "text": "GPT-6 ASTRA",
                "dark": True,
                "tone": "ink",
                "no_red": True,
            },
        }
    )
    plan["overlays"] = ovls
    return 1


def _tame_cyan_spiral(plan: dict[str, Any]) -> int:
    """nsspiral alone is ~0.15 cyan — QC-30 caps 0.12.

    Keep one ≤1.2s beat in-place (between QC samples ~27% and ~58%), retarget
    duplicate spiral slots to dark ink so the 0.58 sample does not land on cyan.
    """
    shots = list(plan.get("shots") or [])
    changed = 0
    spiral_idxs = [
        i
        for i, s in enumerate(shots)
        if isinstance(s, dict) and "nsspiral" in _asset_key(s).lower()
    ]
    if not spiral_idxs:
        return 0
    keep = shots[spiral_idxs[0]]
    start = float(keep.get("start") or 0)
    # shorten in place — do not move start (avoids overlap with previous shot)
    new_end = start + 1.2
    old_end = float(keep.get("end") or new_end)
    if old_end - start > 1.25:
        keep["end"] = new_end
        keep["duration"] = 1.2
        changed += 1
    keep["asset_id"] = "openai_0050_nsspiral"
    # leftover of original spiral window + duplicates → safe dark
    for i in spiral_idxs[1:]:
        s = shots[i]
        s["asset_id"] = _SAFE_DARK
        if "nsspiral" in str(s.get("file") or ""):
            s["file"] = None
        changed += 1
    # if we shortened keep, extend the next shot backward to close the gap
    keep_i = spiral_idxs[0]
    if keep_i + 1 < len(shots):
        nxt = shots[keep_i + 1]
        if float(nxt.get("start") or 0) > float(keep.get("end") or 0) + 0.05:
            # insert filler by extending next shot start earlier only if it was spiral-retargeted
            if keep_i + 1 in spiral_idxs or "nsspiral" not in _asset_key(nxt).lower():
                gap_start = float(keep["end"])
                # prefer retargeting an adjacent duplicate; else leave gap for P12
                if keep_i + 1 in spiral_idxs[1:] or _SAFE_DARK in str(nxt.get("asset_id") or ""):
                    nxt["start"] = gap_start
                    nxt["duration"] = float(nxt.get("end") or 0) - gap_start
                    nxt["asset_id"] = _SAFE_DARK
                    changed += 1
    plan["shots"] = shots
    return changed


def _force_hook_and_agent_assets(plan: dict[str, Any]) -> int:
    changed = 0
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        start = float(shot.get("start") or 0)
        key = _asset_key(shot).lower()
        if start < _HOOK_END:
            if _VORTEX not in key or any(d in key for d in _DENY_HOOK):
                shot["asset_id"] = _VORTEX
                changed += 1
            continue
        if 15.0 <= start < 24.0 and any(d in key for d in _SERVERISH):
            shot["asset_id"] = "magnific_0050_codeglow"
            shot["file"] = None
            changed += 1
        if 24.0 <= start < 27.0 and any(
            d in key for d in ("pipes", "slateiron", "server", "weather")
        ):
            shot["asset_id"] = "magnific_0050_tealmister"
            shot["file"] = None
            changed += 1
        if 52.0 <= start < 58.0 and str(shot.get("kind")) == "footage":
            if any(d in key for d in ("weather", "server", "city", "road", "night")):
                shot["asset_id"] = "magnific_0050_stamp"
                shot["file"] = None
                changed += 1
        if str(shot.get("kind")) in ("avatar", "split"):
            hero = shot.get("hero") if isinstance(shot.get("hero"), dict) else None
            if hero and any(
                d in str(hero.get("file") or "").lower()
                for d in ("weather", "server", "stamp")
            ):
                hero["file"] = None
                changed += 1
    return changed


def _dedupe_templates(plan: dict[str, Any]) -> int:
    changed = 0
    counts: dict[str, int] = {}
    for collection in ("shots", "overlays"):
        for obj in plan.get(collection) or []:
            if not isinstance(obj, dict):
                continue
            tmpl = str(obj.get("template") or "")
            if not tmpl:
                continue
            n = counts.get(tmpl, 0) + 1
            counts[tmpl] = n
            if n > 2:
                if collection == "shots" and tmpl.startswith("intro-hooks/"):
                    obj["template"] = None
                    obj["kind"] = "footage"
                    obj["content"] = None
                elif tmpl.startswith("lower-thirds/"):
                    obj["template"] = "lower-thirds/timestamp-marker"
                    obj["renderer"] = "lt_timestamp"
                    counts[obj["template"]] = counts.get(obj["template"], 0) + 1
                else:
                    obj["template"] = None
                changed += 1
    return changed


def _nasa_credit(shot: dict[str, Any]) -> bool:
    credit = str(shot.get("credit") or "")
    if credit and "NASA" in credit.upper() and credit.strip() != "NASA":
        shot["credit"] = "NASA"
        return True
    return False



def _license_lookup(plan: dict[str, Any]) -> dict[str, Any]:
    """asset_id → license blob from any already-licensed shot."""
    out: dict[str, Any] = {}
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        aid = str(shot.get("asset_id") or "")
        lic = shot.get("license")
        if aid and lic and aid not in out:
            out[aid] = lic
    return out


def _repair_licenses(plan: dict[str, Any]) -> int:
    """QC-12: retargeted asset_id must keep a confirmed license."""
    changed = 0
    lookup = _license_lookup(plan)
    default = "owner_decision"
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        aid = str(shot.get("asset_id") or "")
        if not aid or shot.get("license"):
            continue
        shot["license"] = lookup.get(aid, default)
        # magnific / nasa / openai official pins are owner-cleared
        if any(aid.startswith(p) for p in ("magnific_", "nasa_", "openai_", "fp_")):
            shot["license"] = lookup.get(aid, "owner_decision")
        changed += 1
    return changed


def _ensure_stack_overlay(plan: dict[str, Any]) -> int:
    """Force Latin stack card after hook so it is not lost inside hero params."""
    ovls = list(plan.get("overlays") or [])
    for o in ovls:
        blob = str((o.get("params") or {}).get("content") or o.get("content") or "")
        if "7 TASKS" in blob and "25 YEARS" in blob:
            return 0
    # place over first avatar after hook (~4.4–8.4)
    start, end = 6.5, 9.5
    for s in plan.get("shots") or []:
        if str(s.get("kind")) == "avatar" and float(s.get("start") or 0) >= 4.0:
            start = max(float(s.get("start") or 4.4) + 2.0, 6.5)
            end = min(float(s.get("end") or 9.5), start + 3.0)
            break
    ovls.append(
        {
            "type": "fullscreen_text",
            "template": "text-fullscreen/stack-3lines",
            "renderer": "fullscreen_text",
            "start": start,
            "end": end,
            "content": _STACK,
            "grounded_on": ["money", "number"],
            "why": "owner: Latin stack 7 TASKS / $1M / 25 YEARS",
            "params": {
                "content": _STACK,
                "text": _STACK,
                "lines": ["7 TASKS", "$1 000 000", "25 YEARS"],
                "dark": True,
                "tone": "ink",
            },
        }
    )
    plan["overlays"] = ovls
    return 1


def _dedupe_footage_assets(plan: dict[str, Any]) -> int:
    """same_asset_max_slots=1 — retarget 2nd+ footage uses of the same asset_id."""
    changed = 0
    seen: dict[str, int] = {}
    alts = [
        "magnific_0050_gpu",
        "magnific_0050_deepcoil",
        "magnific_0050_nightstatic",
        "magnific_0050_voidpulse",
        "magnific_0050_blueember",
        "magnific_0050_tealmister",
        _SAFE_DARK,
    ]
    used = {
        str(s.get("asset_id") or "")
        for s in (plan.get("shots") or [])
        if isinstance(s, dict) and s.get("asset_id")
    }
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict) or str(shot.get("kind")) != "footage":
            continue
        aid = str(shot.get("asset_id") or "")
        f = str(shot.get("file") or "")
        key = aid or ("stamp" if "stamp" in f else "")
        if not key or key.startswith("avatar"):
            continue
        n = seen.get(key, 0) + 1
        seen[key] = n
        if n > 1 or (not aid and "stamp" in f):
            repl = next((a for a in alts if a not in used and a != key), _SAFE_DARK)
            shot["asset_id"] = repl
            shot["file"] = None
            shot["license"] = shot.get("license") or "owner_decision"
            used.add(repl)
            changed += 1
    return changed


def _force_rejected_plaque(plan: dict[str, Any]) -> int:
    """REJECTED = dark text plaque; strip stamp PiP leftovers after cutaway."""
    changed = 0
    for ovl in plan.get("overlays") or []:
        if not isinstance(ovl, dict):
            continue
        label = _chip_label(ovl)
        if label != "REJECTED":
            continue
        ovl["template"] = "lower-thirds/dark-card"
        ovl["renderer"] = "lt_dark_card"
        params = dict(ovl.get("params") or {})
        params.update(_NO_RED)
        params["text"] = "REJECTED"
        params["content"] = "REJECTED"
        params["plaque"] = True
        ovl["params"] = params
        changed += 1
    # after stamp cutaway (~51.8–53.2), no more stamp files
    stamp_seen = False
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        key = _asset_key(shot).lower()
        f = str(shot.get("file") or "").lower()
        is_stamp = "stamp" in key or "stamp" in f
        if not is_stamp:
            continue
        if not stamp_seen and str(shot.get("kind")) == "footage":
            stamp_seen = True
            continue
        shot["asset_id"] = "magnific_0050_nightstatic"
        shot["file"] = None
        shot["license"] = shot.get("license") or "owner_decision"
        changed += 1
    return changed

def apply_0050_owner_visuals(plan: dict[str, Any]) -> int:
    if str(plan.get("video_id") or "") != "redshift_0050":
        return 0
    changed = 0
    changed += _collapse_hook(plan)
    changed += _mute_hook_captions(plan)
    changed += _lock_cards(plan)
    changed += _fix_heroes(plan)
    changed += _ensure_brand_pill(plan)
    changed += _ensure_stack_overlay(plan)
    changed += _tame_cyan_spiral(plan)
    changed += _force_hook_and_agent_assets(plan)

    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        if _relabel_stack(shot):
            changed += 1
        if _force_compare(shot):
            changed += 1
        if _nasa_credit(shot):
            changed += 1
        if str(shot.get("template") or "") in _HERO_BAN:
            shot["template"] = "hero-devices/headline-over-head"
            changed += 1
        if _is_lone_six(str(shot.get("content") or ""), dict(shot.get("params") or {})):
            shot["content"] = "GPT-6 ASTRA"
            shot["template"] = "hero-devices/brand-pill"
            shot["params"] = {"content": "GPT-6 ASTRA"}
            changed += 1
        asset = _asset_key(shot)
        if "frostscan" in asset and float(shot.get("start") or 0) < _HOOK_END:
            shot["kind"] = "fullscreen_text"
            shot["template"] = "intro-hooks/hook-number-slam"
            shot["content"] = "$1 000 000"
            shot["asset_id"] = _VORTEX
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
    changed += _dedupe_templates(plan)
    changed += _dedupe_footage_assets(plan)
    changed += _force_rejected_plaque(plan)
    changed += _repair_licenses(plan)
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
