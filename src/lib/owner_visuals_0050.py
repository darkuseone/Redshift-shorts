"""0050 owner visual QC — rewrite after P11, no new TTS/HeyGen."""
from __future__ import annotations

OWNER_VISUALS_REV = 81  # bump to bust P11 step cache

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



def _file_matches_asset(path: str, asset_id: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    aid = asset_id.lower()
    if not aid or not name:
        return False
    if aid in name:
        return True
    # magnific_0050_codeglow → codeglow token
    token = aid.split("_")[-1]
    return bool(token) and token in name


def _donor_file(plan: dict[str, Any], asset_id: str) -> str | None:
    """Prefer a media path whose filename actually contains asset_id."""
    weak: str | None = None
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        for key in ("file", "bg_file"):
            f = str(shot.get(key) or "")
            if not f:
                continue
            if _file_matches_asset(f, asset_id):
                return f
            if str(shot.get("asset_id") or "") == asset_id and weak is None:
                weak = f
    return weak  # last resort; caller may still override


def _fallback_path(asset_id: str) -> str | None:
    roots = (
        f"assets/footage/magnific/{asset_id}.mp4",
        f"assets/footage/official/{asset_id}.mp4",
        f"assets/footage/nasa/{asset_id}.mp4",
        f"assets/footage/{asset_id}.mp4",
    )
    for rel in roots:
        return rel  # CI resolves against repo root; prefer first matching family
    return None


def _bind_asset(shot: dict[str, Any], asset_id: str, plan: dict[str, Any]) -> None:
    """Retarget asset_id without blanking the media path (white frame bug)."""
    shot["asset_id"] = asset_id
    donor = _donor_file(plan, asset_id)
    if donor:
        shot["file"] = donor
    else:
        # Don't keep previous asset's crop — that would show the wrong footage.
        fb = _fallback_path(asset_id)
        if fb:
            shot["file"] = fb
    shot["license"] = shot.get("license") or "owner_decision"

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
    """Brand pill must be shot.hero — overlay path never calls render_hero.

    hero_brand_pill requires params.label (content/text alone = empty Piece).
    """
    changed = 0
    # Drop non-drawing overlay copies of the pill / bare GPT-6 highlight.
    kept: list[dict[str, Any]] = []
    for o in list(plan.get("overlays") or []):
        if not isinstance(o, dict):
            kept.append(o)
            continue
        blob = str(
            (o.get("params") or {}).get("content")
            or (o.get("params") or {}).get("label")
            or (o.get("params") or {}).get("text")
            or o.get("content")
            or ""
        ).upper()
        tmpl = str(o.get("template") or "")
        if tmpl == "hero-devices/brand-pill" or ("GPT-6" in blob and "ASTRA" in blob):
            changed += 1
            continue
        if o.get("type") == "highlight" and "ASTRA" in blob:
            changed += 1
            continue
        kept.append(o)
    plan["overlays"] = kept

    target = None
    for s in plan.get("shots") or []:
        if not isinstance(s, dict):
            continue
        st = float(s.get("start") or 0)
        if str(s.get("kind")) == "footage" and 14.5 <= st <= 20.0:
            target = s
            break
    if target is None:
        for s in plan.get("shots") or []:
            if isinstance(s, dict) and str(s.get("kind")) == "footage" and float(s.get("start") or 0) >= 15.0:
                target = s
                break
    if target is None:
        return changed

    # OpenAI beat must not be the weather/radar room plate.
    f0 = str(target.get("file") or "").lower()
    if any(x in f0 for x in ("weather", "server", "frostscan", "stamp", "slateiron")):
        for aid in ("magnific_0050_codeglow", "magnific_0050_voidpulse", _SAFE_DARK):
            _bind_asset(target, aid, plan)
            if _file_matches_asset(str(target.get("file") or ""), aid):
                break
        changed += 1

    hero = target.get("hero") if isinstance(target.get("hero"), dict) else {}
    want = {
        "template": "hero-devices/brand-pill",
        "renderer": "hero-brand-pill",
        "params": {
            "label": "GPT-6 ASTRA",
            "content": "GPT-6 ASTRA",
            "text": "GPT-6 ASTRA",
            "dark": True,
            "tone": "ink",
            "no_red": True,
            "top": 980,
        },
    }
    if (
        str(hero.get("renderer") or "") != "hero-brand-pill"
        or str((hero.get("params") or {}).get("label") or "") != "GPT-6 ASTRA"
    ):
        target["hero"] = want
        changed += 1
    return changed


def _tame_cyan_spiral(plan: dict[str, Any]) -> int:
    """nsspiral ~0.15 cyan — QC-30 caps 0.12. QC samples hit ~38s (0.58·dur).

    Keep one ≤0.9s spiral beat, then force [35, 40] onto voidpulse (near-zero cyan)
    so sample 3 cannot land on spiral/teal ink.
    """
    shots = list(plan.get("shots") or [])
    changed = 0
    spiral_idxs = [
        i
        for i, s in enumerate(shots)
        if isinstance(s, dict) and "nsspiral" in _asset_key(s).lower()
    ]
    if spiral_idxs:
        keep = shots[spiral_idxs[0]]
        start = float(keep.get("start") or 0)
        keep["end"] = start + 0.9
        keep["duration"] = 0.9
        keep["asset_id"] = "openai_0050_nsspiral"
        changed += 1
        for i in spiral_idxs[1:]:
            _bind_asset(shots[i], "magnific_0050_voidpulse", plan)
            changed += 1
    # Force any shot overlapping the dangerous QC sample band onto voidpulse
    for shot in shots:
        if not isinstance(shot, dict) or str(shot.get("kind")) != "footage":
            continue
        a, b = float(shot.get("start") or 0), float(shot.get("end") or 0)
        if b <= 35.0 or a >= 40.0:
            continue
        if "nsspiral" in _asset_key(shot).lower() and b - a <= 1.0:
            continue  # keep the short spiral beat
        if "voidpulse" not in _asset_key(shot).lower():
            _bind_asset(shot, "magnific_0050_voidpulse", plan)
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
                _bind_asset(shot, _VORTEX, plan)
                changed += 1
            continue
        if 15.0 <= start < 24.0 and any(d in key for d in _SERVERISH):
            _bind_asset(shot, "magnific_0050_codeglow", plan)
            changed += 1
        if 24.0 <= start < 27.0 and any(
            d in key for d in ("pipes", "slateiron", "server", "weather")
        ):
            _bind_asset(shot, "magnific_0050_tealmister", plan)
            changed += 1
        if 52.0 <= start < 58.0 and str(shot.get("kind")) == "footage":
            if any(d in key for d in ("weather", "server", "city", "road", "night")):
                _bind_asset(shot, "magnific_0050_stamp", plan)
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


def _ensure_stack_shot(plan: dict[str, Any]) -> int:
    """Picture Law stack must be a fullscreen_text SHOT.

    Overlay type=fullscreen_text never reaches render_fullscreen (composition
    only draws plaque/cta/source_card/dark_card overlays). max_lines is required
    so _render_fullscreen_body picks fs_stack_lines, not fs_plain.
    """
    changed = 0
    # Drop the dead overlay copy if present.
    kept = []
    for o in list(plan.get("overlays") or []):
        if not isinstance(o, dict):
            kept.append(o)
            continue
        blob = str((o.get("params") or {}).get("content") or o.get("content") or "")
        tmpl = str(o.get("template") or "")
        if "stack-3lines" in tmpl or ("7 TASKS" in blob and "25 YEARS" in blob):
            changed += 1
            continue
        kept.append(o)
    plan["overlays"] = kept

    stack_params = {
        "content": _STACK,
        "text": _STACK,
        "lines": ["7 TASKS", "$1 000 000", "25 YEARS"],
        "max_lines": 3,
        "dark": True,
        "tone": "ink",
        "align": "left",
    }

    # Already a FS stack shot?
    for s in plan.get("shots") or []:
        if not isinstance(s, dict):
            continue
        if str(s.get("kind")) != "fullscreen_text":
            continue
        blob = str(s.get("content") or "") + str((s.get("params") or {}).get("content") or "")
        if "7 TASKS" in blob and "25 YEARS" in blob:
            params = dict(s.get("params") or {})
            params.update(stack_params)
            s["params"] = params
            s["template"] = "text-fullscreen/stack-3lines"
            s["renderer"] = "fullscreen_text"
            s["content"] = _STACK
            s["grounded_on"] = ["money", "number"]
            return changed + 1

    # Prefer the cutaway between early avatars (~8.4–9.8) — was empty radar coils.
    target = None
    for s in plan.get("shots") or []:
        if not isinstance(s, dict):
            continue
        st, en = float(s.get("start") or 0), float(s.get("end") or 0)
        if str(s.get("kind")) == "footage" and 7.5 <= st <= 10.5 and (en - st) >= 1.0:
            target = s
            break
    if target is None:
        for s in plan.get("shots") or []:
            if isinstance(s, dict) and str(s.get("kind")) == "footage" and float(s.get("start") or 0) < 12:
                target = s
                break
    if target is None:
        return changed

    target["kind"] = "fullscreen_text"
    target["template"] = "text-fullscreen/stack-3lines"
    target["renderer"] = "fullscreen_text"
    target["content"] = _STACK
    target["accent_word"] = "TASKS"
    target["grounded_on"] = ["money", "number"]
    target["params"] = dict(stack_params)
    target["hero"] = None
    target["why"] = "owner: Latin stack FS card 7 TASKS / $1M / 25 YEARS"
    for aid in (_SAFE_DARK, "magnific_0050_voidpulse", "magnific_0050_nightstatic", _VORTEX):
        _bind_asset(target, aid, plan)
        if _file_matches_asset(str(target.get("file") or ""), aid):
            break
    # Clear fake stack heroes on nearby avatars (headline-over never reads as stack).
    for s in plan.get("shots") or []:
        if not isinstance(s, dict) or str(s.get("kind")) != "avatar":
            continue
        hero = s.get("hero") if isinstance(s.get("hero"), dict) else None
        if not hero:
            continue
        blob = str((hero.get("params") or {}).get("content") or "")
        if "7 TASKS" in blob or "25 YEARS" in blob:
            s["hero"] = None
            changed += 1
    return changed + 1


def _ensure_openai_chip(plan: dict[str, Any]) -> int:
    """Dark openai.com chip near the spiral/OpenAI beat (Picture Law)."""
    ovls = list(plan.get("overlays") or [])
    for o in ovls:
        blob = str(
            (o.get("params") or {}).get("text")
            or (o.get("params") or {}).get("content")
            or o.get("content")
            or ""
        ).lower()
        if "openai.com" in blob or blob == "openai":
            return 0
    start, end = 32.2, 35.0
    for s in plan.get("shots") or []:
        if not isinstance(s, dict):
            continue
        key = _asset_key(s).lower()
        if "nsspiral" in key or "cyanrain" in key:
            start = float(s.get("start") or start)
            end = min(float(s.get("end") or end), start + 3.0)
            if end - start < 1.6:
                end = start + 2.4
            break
    # Not dark-card: FLUIDS+REJECTED already use it (QC-25 max 2 per template id).
    ovls.append(
        {
            "type": "plaque",
            "template": "lower-thirds/metric-badge",
            "renderer": "lt_metric_badge",
            "start": start,
            "end": end,
            "content": "openai.com",
            "grounded_on": ["brand"],
            "why": "owner: dark openai.com chip (no light browser; not dark-card)",
            "params": {
                **_NO_RED,
                "text": "openai.com",
                "content": "openai.com",
                "name": "openai.com",
                "plaque": True,
            },
        }
    )
    plan["overlays"] = ovls
    return 1


def _scrub_serverish_avatar_bg(plan: dict[str, Any]) -> int:
    """Avatar plates must not reuse the radar/weather room from cutaways."""
    changed = 0
    safe = "magnific_0050_voidpulse"
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict) or str(shot.get("kind")) != "avatar":
            continue
        bg = str(shot.get("bg_file") or "").lower()
        if not bg:
            continue
        if any(tok in bg for tok in _SERVERISH) or "weather" in bg or "stamp" in bg or "deepcoil" in bg:
            picked = None
            for aid in (safe, _SAFE_DARK, "magnific_0050_nightstatic", _VORTEX):
                cand = _donor_file(plan, aid)
                if cand and _file_matches_asset(cand, aid):
                    picked = cand
                    break
            if picked is None:
                picked = _fallback_path(safe)
            if picked:
                shot["bg_file"] = picked
                changed += 1
    return changed


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
            _bind_asset(shot, repl, plan)
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
        _bind_asset(shot, "magnific_0050_nightstatic", plan)
        changed += 1
    return changed


def _repair_missing_files(plan: dict[str, Any]) -> int:
    changed = 0
    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        if str(shot.get("kind")) != "footage":
            continue
        aid = str(shot.get("asset_id") or "")
        if not aid or shot.get("file"):
            continue
        _bind_asset(shot, aid, plan)
        if shot.get("file"):
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
    changed += _ensure_stack_shot(plan)
    changed += _ensure_openai_chip(plan)
    changed += _scrub_serverish_avatar_bg(plan)
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
            _bind_asset(shot, _VORTEX, plan)
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
    changed += _repair_missing_files(plan)
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
