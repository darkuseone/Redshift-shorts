"""App Showcase — three phones fan out, ring/bars/graph breathe.

Catalog ``app-showcase`` is 1920×1080 / 5.5s. It tweens ``width`` on bars,
``strokeDashoffset`` on the ring and graph, and ``getTotalLength``. Here the
fan is ``opacity`` / ``scale`` / ``x`` / ``rotation``, bars grow ``scaleX``,
the ring fills by half-disc ``rotation`` (same idea as conic-progress-ring),
the graph wipes with an SVG-mask ``scaleX``. Lime ``#e4fa72``, ink ``#271f15``,
cream ``#f1f2ec`` as in the catalog — product gesture, not channel palette.
Inter, not ``DM Sans`` / ``-apple-system``. ``phone-notification`` /
``hero-phone-mock`` / ``ai-chat-reveal`` stay separate.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_APS_CATALOG = 5.5
_APS_FAN_X = 268
_APS_FAN_ROT = 12
_APS_PHONE_W = 360
_APS_PHONE_H = 731
_APS_PHONE_LEFT = 360
_APS_PHONE_TOP = 480
_APS_FILL = 2.0 / 3.0
_APS_RING_R = -180.0
_APS_RING_L = (_APS_FILL - 0.5) / 0.5 * 180.0  # 60°

_APS_DOTS = (
    (10, 105), (50, 80), (90, 90), (130, 45), (170, 60), (210, 25), (250, 35),
)
_APS_AREA = "M10,105 L50,80 90,90 130,45 170,60 210,25 250,35 250,115 10,115 Z"
_APS_LINE = "M10,105 L50,80 90,90 130,45 170,60 210,25 250,35"

_APS_DEFAULTS = {
    "tagline": "Unleash Full Potential",
    "cta": "START NOW",
    "name": "James Medrano",
    "subtitle": "Premium Member",
    "goalNum": "2",
    "goalDen": "3",
    "calories": "740",
    "active": "540",
    "rest": "200",
}

_APS_BARS = (
    ("Running", "5.2 km", 0.75, "star"),
    ("Cycling", "12.8 km", 0.50, "cycle"),
    ("Strength", "45 min", 0.90, "bag"),
)

_APS_MAX = {
    "tagline": 42,
    "cta": 16,
    "name": 28,
    "subtitle": 24,
    "barName": 14,
    "barVal": 12,
}


def _aps_play(dur: float) -> float:
    return dur if dur <= 0.001 else max(0.001, dur - 0.001)


def _aps_at(catalog: float, duration: float) -> float:
    return catalog * (max(duration, 0.2) / _APS_CATALOG)


def _aps_dur(catalog: float, duration: float) -> float:
    return _aps_play(_aps_at(catalog, duration))


def _aps_clip(text: Any, key: str) -> str:
    raw = str(text or "").strip()
    limit = _APS_MAX.get(key, 40)
    if len(raw) > limit:
        raw = raw[: limit - 1].rstrip() + "…"
    return raw


def _aps_initials(name: str) -> str:
    parts = [p for p in name.replace(".", " ").split() if p]
    if not parts:
        return "RS"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _aps_copy(params: dict[str, Any]) -> dict[str, str]:
    tagline = (params.get("tagline") or params.get("title")
               or params.get("headline") or _APS_DEFAULTS["tagline"])
    name = params.get("name") or params.get("user") or _APS_DEFAULTS["name"]
    copy = {
        "tagline": _aps_clip(tagline, "tagline"),
        "cta": _aps_clip(params.get("cta") or _APS_DEFAULTS["cta"], "cta"),
        "name": _aps_clip(name, "name"),
        "subtitle": _aps_clip(
            params.get("subtitle") or params.get("role")
            or _APS_DEFAULTS["subtitle"], "subtitle"),
        "goalNum": _aps_clip(params.get("goalNum") or _APS_DEFAULTS["goalNum"],
                             "barVal"),
        "goalDen": _aps_clip(params.get("goalDen") or _APS_DEFAULTS["goalDen"],
                             "barVal"),
        "calories": _aps_clip(
            params.get("calories") or _APS_DEFAULTS["calories"], "barVal"),
        "active": _aps_clip(params.get("active") or _APS_DEFAULTS["active"],
                            "barVal"),
        "rest": _aps_clip(params.get("rest") or _APS_DEFAULTS["rest"], "barVal"),
    }
    copy["initials"] = _aps_clip(
        params.get("initials") or _aps_initials(copy["name"]), "cta")
    return copy


def _aps_bars(params: dict[str, Any]) -> list[tuple[str, str, float, str]]:
    raw = params.get("bars")
    if not isinstance(raw, list) or len(raw) < 3:
        return list(_APS_BARS)
    out: list[tuple[str, str, float, str]] = []
    icons = ("star", "cycle", "bag")
    for i, row in enumerate(raw[:3]):
        if isinstance(row, dict):
            name = _aps_clip(row.get("name") or _APS_BARS[i][0], "barName")
            val = _aps_clip(row.get("val") or row.get("value")
                            or _APS_BARS[i][1], "barVal")
            try:
                fill = float(row.get("fill", _APS_BARS[i][2]))
            except (TypeError, ValueError):
                fill = _APS_BARS[i][2]
        else:
            name, val, fill = _APS_BARS[i][0], str(row), _APS_BARS[i][2]
        fill = max(0.08, min(1.0, fill))
        out.append((name, val, fill, icons[i]))
    while len(out) < 3:
        out.append(_APS_BARS[len(out)])
    return out


def _aps_icon(kind: str) -> str:
    if kind == "star":
        return ('<svg viewBox="0 0 16 16" width="16" height="16" fill="none">'
                '<path d="M8 2l1.5 3H13l-2.5 2 1 3L8 8.5 4.5 10l1-3L3 5h3.5z"'
                ' fill="#e4fa72"/></svg>')
    if kind == "cycle":
        return ('<svg viewBox="0 0 16 16" width="16" height="16" fill="none">'
                '<circle cx="8" cy="8" r="5" stroke="#e4fa72" stroke-width="2"/>'
                '</svg>')
    return ('<svg viewBox="0 0 16 16" width="16" height="16" fill="none">'
            '<rect x="3" y="6" width="10" height="6" rx="1" stroke="#e4fa72"'
            ' stroke-width="1.5"/>'
            '<path d="M6 6V4a2 2 0 014 0v2" stroke="#e4fa72" stroke-width="1.5"/>'
            '</svg>')


def _aps_figure() -> str:
    return (
        '<svg viewBox="0 0 304 400" xmlns="http://www.w3.org/2000/svg" fill="none">'
        '<circle cx="152" cy="80" r="28" fill="#271f15" opacity="0.15"/>'
        '<line x1="152" y1="108" x2="152" y2="200" stroke="#271f15"'
        ' stroke-width="6" stroke-linecap="round" opacity="0.15"/>'
        '<line x1="152" y1="145" x2="115" y2="175" stroke="#271f15"'
        ' stroke-width="6" stroke-linecap="round" opacity="0.15"/>'
        '<line x1="152" y1="145" x2="195" y2="165" stroke="#271f15"'
        ' stroke-width="6" stroke-linecap="round" opacity="0.15"/>'
        '<line x1="152" y1="200" x2="120" y2="260" stroke="#271f15"'
        ' stroke-width="6" stroke-linecap="round" opacity="0.15"/>'
        '<line x1="152" y1="200" x2="190" y2="255" stroke="#271f15"'
        ' stroke-width="6" stroke-linecap="round" opacity="0.15"/>'
        '<path d="M60 300 Q152 240 244 300" stroke="#e4fa72" stroke-width="3"'
        ' fill="none" opacity="0.5"/>'
        '<path d="M40 330 Q152 260 264 330" stroke="#e4fa72" stroke-width="2"'
        ' fill="none" opacity="0.3"/>'
        '</svg>'
    )


def _aps_bell() -> str:
    return (
        '<svg viewBox="0 0 20 20" width="22" height="22" fill="none">'
        '<path d="M10 2a5 5 0 00-5 5v3l-1.5 2.5h13L15 10V7a5 5 0 00-5-5z"'
        ' stroke="#7c857c" stroke-width="1.4" stroke-linejoin="round"/>'
        '<path d="M8 16.5a2 2 0 004 0" stroke="#7c857c" stroke-width="1.4"'
        ' stroke-linecap="round"/>'
        '<circle cx="14" cy="5" r="3" fill="#e4fa72"/>'
        '</svg>'
    )


def ov_app_showcase(ctx: "TemplateCtx") -> Piece:
    """Three-phone product fan: center lands, sides peel, UI breathes."""
    copy = _aps_copy(ctx.params)
    bars = _aps_bars(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 0.2)
    sid = f"{node_id}-stage"
    bgid = f"{node_id}-bg"
    gid = f"{node_id}-glow"
    pc, pl, pr = f"{node_id}-pc", f"{node_id}-pl", f"{node_id}-pr"
    ra, rb = f"{node_id}-ra", f"{node_id}-rb"
    rp, lp = f"{node_id}-rp", f"{node_id}-lp"
    tag, cta = f"{node_id}-tag", f"{node_id}-cta"
    wid = f"{node_id}-gw"
    gline = f"{node_id}-gline"
    garea = f"{node_id}-garea"
    b1, b2, b3 = f"{node_id}-b1", f"{node_id}-b2", f"{node_id}-b3"

    def at(catalog: float) -> float:
        return start + _aps_at(catalog, duration)

    def dur(catalog: float) -> float:
        return _aps_dur(catalog, duration)

    tweens = [
        f'tl.set("#{ra}",{{rotation:{_num(_APS_RING_R)}}},{_num(start)});',
        f'tl.set("#{rb}",{{rotation:0}},{_num(start)});',
        f'tl.fromTo("#{bgid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.8))},ease:"power1.out"}},'
        f'{_num(at(0))});',
        f'tl.fromTo("#{gid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(1.2))},ease:"power1.out"}},'
        f'{_num(at(0.2))});',
        f'tl.fromTo("#{pc}",{{opacity:0,scale:0.85}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.7))},ease:"back.out(1.4)"}},'
        f'{_num(at(0.2))});',
        f'tl.fromTo("#{pl}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.7))},ease:"back.out(1.4)"}},'
        f'{_num(at(0.3))});',
        f'tl.fromTo("#{pl}",{{x:0,rotation:0}},'
        f'{{x:{-_APS_FAN_X},rotation:{-_APS_FAN_ROT},duration:{_num(dur(1.2))},'
        f'ease:"expo.out",immediateRender:false}},{_num(at(0.3))});',
        f'tl.fromTo("#{pr}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.7))},ease:"back.out(1.4)"}},'
        f'{_num(at(0.4))});',
        f'tl.fromTo("#{pr}",{{x:0,rotation:0}},'
        f'{{x:{_APS_FAN_X},rotation:{_APS_FAN_ROT},duration:{_num(dur(1.2))},'
        f'ease:"expo.out",immediateRender:false}},{_num(at(0.4))});',
        f'tl.fromTo("#{ra}",{{rotation:{_num(_APS_RING_R)}}},'
        f'{{rotation:0,duration:{_num(dur(1.2))},ease:"circ.out"}},'
        f'{_num(at(1.8))});',
        f'tl.fromTo("#{rb}",{{rotation:0}},'
        f'{{rotation:{_num(_APS_RING_L)},duration:{_num(dur(1.2))},'
        f'ease:"circ.out"}},'
        f'{_num(at(1.8))});',
        f'tl.fromTo("#{b1}",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(dur(0.8))},ease:"power3.out"}},'
        f'{_num(at(2.1))});',
        f'tl.fromTo("#{b2}",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(dur(0.8))},ease:"power3.out"}},'
        f'{_num(at(2.3))});',
        f'tl.fromTo("#{b3}",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(dur(0.8))},ease:"power3.out"}},'
        f'{_num(at(2.5))});',
        f'tl.fromTo("#{wid}",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(dur(1.4))},ease:"sine.inOut"}},'
        f'{_num(at(2.0))});',
        f'tl.fromTo("#{garea}",{{opacity:0}},'
        f'{{opacity:0.15,duration:{_num(dur(0.8))},ease:"power1.out"}},'
        f'{_num(at(2.6))});',
        f'tl.fromTo("#{tag}",{{opacity:0,y:20}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.6))},ease:"power2.out"}},'
        f'{_num(at(2.2))});',
        f'tl.fromTo("#{cta}",{{opacity:0,y:12}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.5))},ease:"power2.out"}},'
        f'{_num(at(2.5))});',
        f'tl.fromTo("#{sid}",{{scale:1}},'
        f'{{scale:1.02,duration:{_num(dur(3.5))},ease:"sine.inOut"}},'
        f'{_num(at(2.0))});',
    ]
    for i, _pt in enumerate(_APS_DOTS):
        did = f"{node_id}-d{i}"
        tweens.append(
            f'tl.fromTo("#{did}",{{opacity:0,scale:0}},'
            f'{{opacity:1,scale:1,duration:{_num(dur(0.3))},ease:"back.out(2)"}},'
            f'{_num(at(3.0 + i * 0.06))});')

    pulse_ids = (rp, lp, b1, b2, b3, gline)
    for pid in pulse_ids:
        off = 0.0 if pid in (rp, lp) else (0.1 if pid.startswith(f"{node_id}-b") else 0.05)
        tweens.append(
            f'tl.fromTo("#{pid}",{{opacity:1}},'
            f'{{opacity:0.65,duration:{_num(dur(0.6))},ease:"sine.inOut",'
            f'immediateRender:false}},{_num(at(4.0 + off))});')
        tweens.append(
            f'tl.fromTo("#{pid}",{{opacity:0.65}},'
            f'{{opacity:1,duration:{_num(dur(0.6))},ease:"sine.inOut",'
            f'immediateRender:false}},{_num(at(4.6 + off))});')

    kill_at = start + duration
    tweens.append(f'tl.set("#{bgid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{gid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{pc}",{{opacity:0,scale:0.85}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{pl}",{{opacity:0,x:0,rotation:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{pr}",{{opacity:0,x:0,rotation:0}},{_num(kill_at)});')

    bar_rows = []
    for i, (name, val, fill, icon) in enumerate(bars):
        bid = (b1, b2, b3)[i]
        pct = int(round(fill * 100))
        bar_rows.append(
            f'<div class="aps-barrow">'
            f'<div class="aps-baricon">{_aps_icon(icon)}</div>'
            f'<div class="aps-barinfo"><span class="aps-barname">'
            f'{_esc(name)}</span><span class="aps-barval">{_esc(val)}</span>'
            f'</div>'
            f'<div class="aps-bartrack"><div id="{bid}" class="aps-barfill"'
            f' style="width:{pct}%"></div></div></div>')

    dots = []
    for i, (x, y) in enumerate(_APS_DOTS):
        dots.append(
            f'<circle id="{node_id}-d{i}" class="aps-dot" cx="{x}" cy="{y}"'
            f' r="3.5" fill="#e4fa72"/>')

    days = []
    for i, letter in enumerate("MTWTFSS"):
        done = " aps-done" if i < 2 else ""
        days.append(f'<span class="aps-day{done}">{letter}</span>')

    mid = f"{node_id}-gm"
    left_phone = (
        f'<div id="{pl}" class="aps-phone aps-side-l">'
        f'<div class="aps-bezel"><div class="aps-notch"></div>'
        f'<div class="aps-screen aps-screen-left">'
        f'<div class="aps-shapes">{_aps_figure()}</div>'
        f'<div class="aps-leftbot">'
        f'<div id="{tag}" class="aps-tagline">{_esc(copy["tagline"])}</div>'
        f'<div id="{cta}" class="aps-cta">{_esc(copy["cta"])}</div>'
        f'</div></div></div></div>'
    )
    center_phone = (
        f'<div id="{pc}" class="aps-phone aps-side-c">'
        f'<div class="aps-bezel"><div class="aps-notch"></div>'
        f'<div class="aps-screen aps-screen-center">'
        f'<div class="aps-chead">'
        f'<div class="aps-avatar">{_esc(copy["initials"])}</div>'
        f'<div class="aps-uinfo"><div class="aps-uname">{_esc(copy["name"])}</div>'
        f'<div class="aps-usub">{_esc(copy["subtitle"])}</div></div>'
        f'<div class="aps-bell">{_aps_bell()}</div></div>'
        f'<div class="aps-goal"><div class="aps-glabel">Weekly Goal</div>'
        f'<div class="aps-ringwrap">'
        f'<div class="aps-disc">'
        f'<div class="aps-half aps-half-r"><div id="{ra}" class="aps-rot">'
        f'<div id="{rp}" class="aps-paint"></div></div></div>'
        f'<div class="aps-half aps-half-l"><div id="{rb}" class="aps-rot">'
        f'<div id="{lp}" class="aps-paint"></div></div></div></div>'
        f'<div class="aps-hole" data-layout-allow-overlap=""></div>'
        f'<div class="aps-count" data-layout-allow-overlap="">'
        f'<span class="aps-gnum">{_esc(copy["goalNum"])}</span>'
        f'<span class="aps-gsep">/</span>'
        f'<span class="aps-gden">{_esc(copy["goalDen"])}</span></div></div>'
        f'<div class="aps-days">{"".join(days)}</div></div>'
        f'<div class="aps-progress">'
        f'<div class="aps-phead"><span class="aps-ptitle">Your Progress</span>'
        f'<span class="aps-plink">See all</span></div>'
        f'<div class="aps-bars">{"".join(bar_rows)}</div></div>'
        f'</div></div></div>'
    )
    right_phone = (
        f'<div id="{pr}" class="aps-phone aps-side-r">'
        f'<div class="aps-bezel"><div class="aps-notch"></div>'
        f'<div class="aps-screen aps-screen-right">'
        f'<div class="aps-rhead"><div class="aps-rtitle">Burned Calories</div>'
        f'<div class="aps-rval">{_esc(copy["calories"])} '
        f'<span class="aps-runit">kcal</span></div></div>'
        f'<div class="aps-graph">'
        f'<svg class="aps-gsvg" viewBox="0 0 260 130"'
        f' xmlns="http://www.w3.org/2000/svg">'
        f'<defs><mask id="{mid}" maskUnits="userSpaceOnUse"'
        f' maskContentUnits="userSpaceOnUse">'
        f'<rect id="{wid}" class="aps-wipe" x="0" y="0" width="260"'
        f' height="130" fill="#fff"/></mask></defs>'
        f'<line x1="10" y1="25" x2="250" y2="25" stroke="#d9e0bc"'
        f' stroke-width="0.5" opacity="0.5"/>'
        f'<line x1="10" y1="55" x2="250" y2="55" stroke="#d9e0bc"'
        f' stroke-width="0.5" opacity="0.5"/>'
        f'<line x1="10" y1="85" x2="250" y2="85" stroke="#d9e0bc"'
        f' stroke-width="0.5" opacity="0.5"/>'
        f'<line x1="10" y1="115" x2="250" y2="115" stroke="#d9e0bc"'
        f' stroke-width="0.5" opacity="0.5"/>'
        f'<path id="{garea}" class="aps-area" d="{_APS_AREA}" fill="#e4fa72"'
        f' mask="url(#{mid})"/>'
        f'<path id="{gline}" class="aps-gline" d="{_APS_LINE}" fill="none"'
        f' stroke="#e4fa72" stroke-width="2.5" stroke-linecap="round"'
        f' stroke-linejoin="round" mask="url(#{mid})"/>'
        f'{"".join(dots)}</svg>'
        f'<div class="aps-rlabels"><span>Mon</span><span>Tue</span>'
        f'<span>Wed</span><span>Thu</span><span>Fri</span>'
        f'<span>Sat</span><span>Sun</span></div></div>'
        f'<div class="aps-stats">'
        f'<div class="aps-pill"><span class="aps-dotc aps-lime"></span>'
        f'<span class="aps-plabel">Active</span>'
        f'<span class="aps-pnum">{_esc(copy["active"])}</span></div>'
        f'<div class="aps-pill"><span class="aps-dotc aps-mute"></span>'
        f'<span class="aps-plabel">Rest</span>'
        f'<span class="aps-pnum">{_esc(copy["rest"])}</span></div>'
        f'</div></div></div></div>'
    )
    node = (
        f'<div id="{node_id}" class="clip overlay app-showcase" {_timing(ctx)}>'
        f'<div id="{bgid}" class="aps-bg"></div>'
        f'<div id="{gid}" class="aps-glow"></div>'
        f'<div id="{sid}" class="aps-stage">'
        f'{left_phone}{center_phone}{right_phone}'
        f'</div></div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def aps_overlay_css() -> str:
    """Full-bleed three-phone fan. Catalog lime/cream/ink, Inter."""
    left = f"{_APS_PHONE_LEFT:g}"
    top = f"{_APS_PHONE_TOP:g}"
    pw = f"{_APS_PHONE_W:g}"
    ph = f"{_APS_PHONE_H:g}"
    return (
        ".app-showcase{left:0;top:0;width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden;font-family:Inter,var(--font-subtitle),sans-serif;"
        "color:#271f15;background:#0a0a0f}"
        ".app-showcase .aps-bg{position:absolute;inset:0;opacity:0;background:"
        "linear-gradient(160deg,#f1f2ec 0%,#e8ecda 40%,#f1f2ec 100%)}"
        ".app-showcase .aps-glow{position:absolute;width:720px;height:720px;"
        "top:50%;left:50%;margin:-360px 0 0 -360px;opacity:0;border-radius:50%;"
        "background:radial-gradient(circle,rgba(228,250,114,0.18) 0%,transparent 70%)}"
        ".app-showcase .aps-stage{position:absolute;inset:0;"
        "transform-origin:center center}"
        ".app-showcase .aps-phone{position:absolute;width:__PW__px;height:__PH__px;"
        "left:__LEFT__px;top:__TOP__px;transform-origin:50% 50%;"
        "will-change:transform,opacity}"
        ".app-showcase .aps-side-c{z-index:30;opacity:0}"
        ".app-showcase .aps-side-l,.app-showcase .aps-side-r{z-index:20;opacity:0}"
        ".app-showcase .aps-bezel{width:100%;height:100%;border-radius:48px;"
        "background:#271f15;padding:9px;position:relative;overflow:hidden;"
        "box-shadow:0 24px 64px rgba(39,31,21,0.35),0 4px 16px rgba(39,31,21,0.15)}"
        ".app-showcase .aps-notch{position:absolute;top:9px;left:50%;"
        "width:112px;height:28px;margin-left:-56px;background:#271f15;"
        "border-radius:0 0 18px 18px;z-index:5}"
        ".app-showcase .aps-screen{width:100%;height:100%;border-radius:40px;"
        "overflow:hidden;position:relative}"
        ".app-showcase .aps-screen-left{background:"
        "linear-gradient(160deg,#d9e0bc 0%,#c8d4a0 50%,#b8c78a 100%)}"
        ".app-showcase .aps-shapes{position:absolute;top:36px;left:0;right:0;"
        "height:360px;display:flex;align-items:center;justify-content:center}"
        ".app-showcase .aps-shapes svg{width:200px;height:280px}"
        ".app-showcase .aps-leftbot{position:absolute;left:28px;right:28px;"
        "bottom:40px}"
        ".app-showcase .aps-tagline{font-size:30px;font-weight:700;color:#271f15;"
        "line-height:1.15;letter-spacing:-0.02em;margin-bottom:16px;opacity:0}"
        ".app-showcase .aps-cta{display:inline-block;background:#271f15;"
        "color:#e4fa72;font-size:14px;font-weight:700;letter-spacing:0.08em;"
        "padding:10px 28px;border-radius:24px;opacity:0}"
        ".app-showcase .aps-screen-center{background:#1a1a1a;padding:48px 24px 24px}"
        ".app-showcase .aps-chead{display:flex;align-items:center;gap:10px;"
        "margin-bottom:18px}"
        ".app-showcase .aps-avatar{width:44px;height:44px;border-radius:50%;"
        "background:linear-gradient(135deg,#e4fa72,#d9e0bc);display:flex;"
        "align-items:center;justify-content:center;font-size:16px;font-weight:700;"
        "color:#271f15;flex-shrink:0}"
        ".app-showcase .aps-uinfo{flex:1;min-width:0}"
        ".app-showcase .aps-uname{font-size:18px;font-weight:700;color:#f1f2ec;"
        "line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
        ".app-showcase .aps-usub{font-size:12px;font-weight:400;color:#7c857c;"
        "margin-top:1px}"
        ".app-showcase .aps-bell{flex-shrink:0}"
        ".app-showcase .aps-goal{background:#242424;border-radius:20px;"
        "padding:16px 14px;margin-bottom:16px}"
        ".app-showcase .aps-glabel{font-size:14px;font-weight:500;color:#7c857c;"
        "margin-bottom:10px}"
        ".app-showcase .aps-ringwrap{position:relative;width:130px;height:130px;"
        "margin:0 auto 12px}"
        ".app-showcase .aps-disc{position:absolute;inset:0;border-radius:50%;"
        "overflow:hidden;background:#333}"
        ".app-showcase .aps-half{position:absolute;top:0;width:50%;height:100%;"
        "overflow:hidden}"
        ".app-showcase .aps-half-r{left:50%}"
        ".app-showcase .aps-half-l{left:0}"
        ".app-showcase .aps-rot{position:absolute;top:0;left:-100%;width:200%;"
        "height:100%;transform-origin:50% 50%}"
        ".app-showcase .aps-half-l .aps-rot{left:0}"
        ".app-showcase .aps-paint{position:absolute;left:50%;top:0;width:50%;"
        "height:100%;background:#e4fa72}"
        ".app-showcase .aps-hole{position:absolute;left:13px;top:13px;"
        "width:104px;height:104px;border-radius:50%;background:#242424}"
        ".app-showcase .aps-count{position:absolute;inset:0;display:flex;"
        "align-items:center;justify-content:center;gap:2px;z-index:2}"
        ".app-showcase .aps-gnum{font-size:36px;font-weight:700;color:#e4fa72}"
        ".app-showcase .aps-gsep,.app-showcase .aps-gden{font-size:24px;"
        "font-weight:400;color:#7c857c}"
        ".app-showcase .aps-days{display:flex;justify-content:center;gap:7px}"
        ".app-showcase .aps-day{width:28px;height:28px;border-radius:50%;"
        "display:flex;align-items:center;justify-content:center;font-size:11px;"
        "font-weight:500;color:#7c857c;background:#1a1a1a}"
        ".app-showcase .aps-done{background:#e4fa72;color:#271f15;font-weight:700}"
        ".app-showcase .aps-phead{display:flex;justify-content:space-between;"
        "align-items:center;margin-bottom:12px}"
        ".app-showcase .aps-ptitle{font-size:15px;font-weight:500;color:#f1f2ec}"
        ".app-showcase .aps-plink{font-size:12px;font-weight:400;color:#e4fa72}"
        ".app-showcase .aps-barrow{display:flex;align-items:center;gap:10px;"
        "margin-bottom:12px}"
        ".app-showcase .aps-baricon{width:28px;height:28px;border-radius:8px;"
        "background:#2a2a2a;display:flex;align-items:center;justify-content:center;"
        "flex-shrink:0}"
        ".app-showcase .aps-barinfo{width:78px;flex-shrink:0}"
        ".app-showcase .aps-barname{display:block;font-size:12px;font-weight:500;"
        "color:#f1f2ec;line-height:1.2}"
        ".app-showcase .aps-barval{display:block;font-size:10px;font-weight:400;"
        "color:#7c857c}"
        ".app-showcase .aps-bartrack{flex:1;height:8px;background:#2a2a2a;"
        "border-radius:4px;overflow:hidden}"
        ".app-showcase .aps-barfill{height:100%;border-radius:4px;"
        "background:#e4fa72;transform-origin:0% 50%;transform:scaleX(0);"
        "will-change:transform,opacity}"
        ".app-showcase .aps-screen-right{background:#f1f2ec;padding:48px 22px 26px}"
        ".app-showcase .aps-rtitle{font-size:14px;font-weight:500;color:#7c857c}"
        ".app-showcase .aps-rval{font-size:42px;font-weight:700;color:#271f15;"
        "line-height:1;letter-spacing:-0.03em;margin:6px 0 12px}"
        ".app-showcase .aps-runit{font-size:20px;font-weight:400;color:#7c857c}"
        ".app-showcase .aps-gsvg{width:100%;height:160px;display:block}"
        ".app-showcase .aps-wipe{transform-origin:0px 50%;transform-box:fill-box;"
        "transform:scaleX(0)}"
        ".app-showcase .aps-area{opacity:0}"
        ".app-showcase .aps-gline{fill:none}"
        ".app-showcase .aps-dot{transform-box:fill-box;transform-origin:50% 50%;"
        "opacity:0}"
        ".app-showcase .aps-rlabels{display:flex;justify-content:space-between;"
        "padding:4px 6px 0;font-size:11px;font-weight:400;color:#7c857c}"
        ".app-showcase .aps-stats{display:flex;gap:12px;margin-top:16px}"
        ".app-showcase .aps-pill{display:flex;align-items:center;gap:6px;"
        "background:#e8ecda;border-radius:20px;padding:8px 14px}"
        ".app-showcase .aps-dotc{width:8px;height:8px;border-radius:50%;"
        "flex-shrink:0}"
        ".app-showcase .aps-lime{background:#e4fa72}"
        ".app-showcase .aps-mute{background:#7c857c}"
        ".app-showcase .aps-plabel{font-size:12px;font-weight:400;color:#7c857c}"
        ".app-showcase .aps-pnum{font-size:13px;font-weight:700;color:#271f15}"
    ).replace("__LEFT__", left).replace("__TOP__", top).replace(
        "__PW__", pw).replace("__PH__", ph)
