"""NYC–Paris flight: plane along a cubic, landing doodle, ARRIVED.

Catalog ``nyc-paris-flight`` is 1920×1080 / 6s. It tweens
``strokeDashoffset`` on the route, ``offsetDistance`` on the plane,
and ``filter``. Here the route is an SVG-mask ``scaleX``; the plane
is sampled ``x`` / ``y`` / ``rotation``; the doodle is a mask
``scaleX``. Paper ``#f5f5f7``, ink ``#1d1d1f``, route ``#0071e3``,
doodle ``#ff3b30`` as in the catalog — Apple flight gesture, not
channel palette. Inter, not ``-apple-system``.
``us-map-flow`` / ``world-map`` stay separate.
"""

from __future__ import annotations

import math
from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing
from .wmp_shapes import WMP_SHAPES

_NPF_CATALOG = 6.0
_NPF_MAP_AT = 0.16
_NPF_MAP_DUR = 1.05
_NPF_TITLE_AT = 0.24
_NPF_TITLE_DUR = 0.52
_NPF_EYE_AT = 0.32
_NPF_HL_AT = 0.4
_NPF_META_AT = 0.58
_NPF_NYC_AT = 0.7
_NPF_PARIS_AT = 0.86
_NPF_PLANE_AT = 1.08
_NPF_ROUTE_AT = 1.2
_NPF_ROUTE_DUR = 3.05
_NPF_FLY_AT = 1.17
_NPF_FLY_DUR = 3.25
_NPF_TICK_AT = 1.34
_NPF_TICK_GAP = 0.44
_NPF_DOODLE_AT = 4.18
_NPF_DOODLE_DUR = 0.54
_NPF_PULSE_AT = 4.06
_NPF_BADGE_AT = 5.02
_NPF_WHITE_AT = 5.5

_NPF_PAPER = "#f5f5f7"
_NPF_INK = "#1d1d1f"
_NPF_MUTED = "#6e6e73"
_NPF_BLUE = "#0071e3"
_NPF_SEA = "#dce6f0"
_NPF_LAND = "#fbfbfc"
_NPF_STROKE = "#d2d2d7"
_NPF_DOODLE = "#ff3b30"
_NPF_BADGE = "#d70015"

_NPF_VB = (280.0, 70.0, 480.0, 200.0)
_NPF_PANEL = (0.0, 520.0, 1080.0, 980.0)
_NPF_LAND_CODES = (
    "840", "124", "250", "724", "620", "826", "372", "276", "380",
    "056", "528", "208", "352", "372", "442", "040", "756", "191",
)
_NPF_NYC = (455.0, 175.0)
_NPF_PARIS = (676.0, 158.0)
_NPF_SEGS = 8

_PLANE_PATH = (
    "M 58 0 C 52 -10 37 -15 15 -16 L -18 -56 C -23 -62 -34 -58 -32 -49 "
    "L -21 -15 L -48 -12 C -56 -11 -60 -6 -60 0 C -60 6 -56 11 -48 12 "
    "L -21 15 L -32 49 C -34 58 -23 62 -18 56 L 15 16 C 37 15 52 10 58 0 Z"
)
_PLANE_INNER = (
    "M 54 0 C 46 -6 33 -9 14 -10 L -19 -50 C -21 -53 -25 -52 -25 -47 "
    "L -15 -10 L -49 -6 C -53 -5 -55 -2 -55 0 C -55 2 -53 5 -49 6 "
    "L -15 10 L -25 47 C -25 52 -21 53 -19 50 L 14 10 C 33 9 46 6 54 0 Z"
)


def _npf_play(dur: float) -> float:
    return dur if dur <= 0.001 else max(0.001, dur - 0.001)


def _npf_at(catalog: float, duration: float) -> float:
    return catalog * (max(duration, 0.2) / _NPF_CATALOG)


def _npf_dur(catalog: float, duration: float) -> float:
    return _npf_play(_npf_at(catalog, duration))


def _npf_times(duration: float) -> dict[str, float]:
    return {
        "map_at": _npf_at(_NPF_MAP_AT, duration),
        "map_dur": _npf_dur(_NPF_MAP_DUR, duration),
        "title_at": _npf_at(_NPF_TITLE_AT, duration),
        "title_dur": _npf_dur(_NPF_TITLE_DUR, duration),
        "eye_at": _npf_at(_NPF_EYE_AT, duration),
        "hl_at": _npf_at(_NPF_HL_AT, duration),
        "meta_at": _npf_at(_NPF_META_AT, duration),
        "nyc_at": _npf_at(_NPF_NYC_AT, duration),
        "paris_at": _npf_at(_NPF_PARIS_AT, duration),
        "plane_at": _npf_at(_NPF_PLANE_AT, duration),
        "route_at": _npf_at(_NPF_ROUTE_AT, duration),
        "route_dur": _npf_dur(_NPF_ROUTE_DUR, duration),
        "fly_at": _npf_at(_NPF_FLY_AT, duration),
        "fly_dur": _npf_dur(_NPF_FLY_DUR, duration),
        "tick_at": _npf_at(_NPF_TICK_AT, duration),
        "tick_gap": _npf_at(_NPF_TICK_GAP, duration),
        "doodle_at": _npf_at(_NPF_DOODLE_AT, duration),
        "doodle_dur": _npf_dur(_NPF_DOODLE_DUR, duration),
        "pulse_at": _npf_at(_NPF_PULSE_AT, duration),
        "badge_at": _npf_at(_NPF_BADGE_AT, duration),
        "white_at": _npf_at(_NPF_WHITE_AT, duration),
    }


def _npf_xy(x: float, y: float) -> tuple[float, float]:
    vb_x, vb_y, vb_w, vb_h = _NPF_VB
    px, py, pw, ph = _NPF_PANEL
    scale = min(pw / vb_w, ph / vb_h)
    dw, dh = vb_w * scale, vb_h * scale
    ox = px + (pw - dw) / 2.0
    oy = py + (ph - dh) / 2.0
    return ox + (x - vb_x) * scale, oy + (y - vb_y) * scale


def _npf_cubic(p0: tuple[float, float], p1: tuple[float, float],
               p2: tuple[float, float], p3: tuple[float, float],
               t: float) -> tuple[float, float]:
    u = 1.0 - t
    x = (u * u * u * p0[0] + 3 * u * u * t * p1[0]
         + 3 * u * t * t * p2[0] + t * t * t * p3[0])
    y = (u * u * u * p0[1] + 3 * u * u * t * p1[1]
         + 3 * u * t * t * p2[1] + t * t * t * p3[1])
    return x, y


def _npf_angle(p0: tuple[float, float], p1: tuple[float, float],
               p2: tuple[float, float], p3: tuple[float, float],
               t: float) -> float:
    u = 1.0 - t
    dx = (3 * u * u * (p1[0] - p0[0]) + 6 * u * t * (p2[0] - p1[0])
          + 3 * t * t * (p3[0] - p2[0]))
    dy = (3 * u * u * (p1[1] - p0[1]) + 6 * u * t * (p2[1] - p1[1])
          + 3 * t * t * (p3[1] - p2[1]))
    return math.degrees(math.atan2(dy, dx))


def _npf_spec(params: dict[str, Any]
              ) -> tuple[str, str, str, str, str] | None:
    if not params:
        return None
    origin = str(params.get("origin") or params.get("from") or "New York").strip()
    dest = str(params.get("dest") or params.get("to") or "Paris").strip()
    origin_code = str(params.get("origin_code") or "JFK / NYC").strip()
    dest_code = str(params.get("dest_code") or "CDG / FR").strip()
    km = params.get("km", params.get("distance", "5,837"))
    return origin or "New York", dest or "Paris", origin_code, dest_code, str(km)


def dv_nyc_paris_flight(ctx: "TemplateCtx") -> Piece:
    """Plane flies NYC→Paris. No offsetDistance, no strokeDashoffset."""
    spec = _npf_spec(ctx.params)
    if spec is None:
        return Piece()
    origin, dest, origin_code, dest_code, km = spec
    times = _npf_times(ctx.duration)
    node_id = f"npf-{ctx.index:02d}"
    start = ctx.start
    nyc = _npf_xy(*_NPF_NYC)
    paris = _npf_xy(*_NPF_PARIS)
    c1 = (nyc[0] + (paris[0] - nyc[0]) * 0.28, nyc[1] - 220)
    c2 = (nyc[0] + (paris[0] - nyc[0]) * 0.72, paris[1] - 260)
    vb = " ".join(_num(v) for v in _NPF_VB)
    wanted = set(_NPF_LAND_CODES)
    paths = [
        f'<path class="npf-land" d="{_esc(item["d"])}"></path>'
        for item in WMP_SHAPES if str(item["code"]) in wanted
    ]
    route_d = (
        f"M {_num(nyc[0])} {_num(nyc[1])} "
        f"C {_num(c1[0])} {_num(c1[1])} {_num(c2[0])} {_num(c2[1])} "
        f"{_num(paris[0])} {_num(paris[1])}"
    )
    ticks: list[str] = []
    tweens: list[str] = [
        f'tl.fromTo("#{node_id}-map",{{scale:1.1,x:-24,y:18,opacity:0.94}},'
        f'{{scale:1,x:0,y:0,opacity:1,duration:{_num(times["map_dur"])},'
        f'ease:"power2.out"}},{_num(start + times["map_at"])});',
        f'tl.fromTo("#{node_id}-title",{{y:28,scale:0.97,opacity:0}},'
        f'{{y:0,scale:1,opacity:1,duration:{_num(times["title_dur"])},'
        f'ease:"expo.out"}},{_num(start + times["title_at"])});',
        f'tl.fromTo("#{node_id}-eye",{{x:-22,opacity:0}},'
        f'{{x:0,opacity:1,duration:{_num(_npf_dur(0.36, ctx.duration))},'
        f'ease:"power3.out"}},{_num(start + times["eye_at"])});',
        f'tl.fromTo("#{node_id}-hl",{{y:34,opacity:0}},'
        f'{{y:0,opacity:1,duration:{_num(_npf_dur(0.5, ctx.duration))},'
        f'ease:"back.out(1.45)"}},{_num(start + times["hl_at"])});',
        f'tl.fromTo("#{node_id}-meta",{{x:-26,opacity:0}},'
        f'{{x:0,opacity:1,duration:{_num(_npf_dur(0.38, ctx.duration))},'
        f'ease:"circ.out"}},{_num(start + times["meta_at"])});',
        f'tl.fromTo("#{node_id}-nyc",{{scale:0.12,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(_npf_dur(0.34, ctx.duration))},'
        f'ease:"back.out(2.8)"}},{_num(start + times["nyc_at"])});',
        f'tl.fromTo("#{node_id}-par",{{scale:0.12,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(_npf_dur(0.34, ctx.duration))},'
        f'ease:"elastic.out(1, 0.5)"}},{_num(start + times["paris_at"])});',
        f'tl.fromTo("#{node_id}-pln",{{scale:0.48,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(_npf_dur(0.3, ctx.duration))},'
        f'ease:"back.out(2.2)"}},{_num(start + times["plane_at"])});',
        f'tl.fromTo("#{node_id}-rw",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(times["route_dur"])},ease:"power2.inOut"}},'
        f'{_num(start + times["route_at"])});',
    ]
    segs = _NPF_SEGS
    fly_seg = times["fly_dur"] / segs
    prev_x = prev_y = prev_ang = 0.0
    for i in range(segs + 1):
        t = i / segs
        x, y = _npf_cubic(nyc, c1, c2, paris, t)
        ang = _npf_angle(nyc, c1, c2, paris, t)
        if i == 0:
            tweens.append(
                f'tl.set("#{node_id}-pln",{{x:{_num(x - 48)},y:{_num(y - 48)},'
                f'rotation:{_num(ang)}}},{_num(start + times["fly_at"])});')
            prev_x, prev_y, prev_ang = x, y, ang
            continue
        tweens.append(
            f'tl.fromTo("#{node_id}-pln",'
            f'{{x:{_num(prev_x - 48)},y:{_num(prev_y - 48)},'
            f'rotation:{_num(prev_ang)}}},'
            f'{{x:{_num(x - 48)},y:{_num(y - 48)},rotation:{_num(ang)},'
            f'duration:{_num(fly_seg)},ease:"none",immediateRender:false}},'
            f'{_num(start + times["fly_at"] + (i - 1) * fly_seg)});')
        prev_x, prev_y, prev_ang = x, y, ang
    for i in range(6):
        t = (i + 1) / 7
        tx, ty = _npf_cubic(nyc, c1, c2, paris, t)
        ticks.append(
            f'<div id="{node_id}-t{i}" class="npf-tick" '
            f'style="left:{_num(tx - 7)}px;top:{_num(ty - 7)}px"></div>'
        )
        at = start + times["tick_at"] + i * times["tick_gap"]
        tweens.append(
            f'tl.fromTo("#{node_id}-t{i}",{{scale:0.2,opacity:0}},'
            f'{{scale:1,opacity:1,duration:{_num(_npf_dur(0.16, ctx.duration))},'
            f'ease:"back.out(3)"}},{_num(at)});')
        tweens.append(
            f'tl.to("#{node_id}-t{i}",{{scale:0.6,opacity:0.18,'
            f'duration:{_num(_npf_dur(0.34, ctx.duration))},ease:"power2.out",'
            f'immediateRender:false}},'
            f'{_num(at + _npf_dur(0.14, ctx.duration))});')
    tweens.extend([
        f'tl.fromTo("#{node_id}-pulse",{{scale:0.52,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(_npf_dur(0.26, ctx.duration))},'
        f'ease:"back.out(2.4)"}},{_num(start + times["pulse_at"])});',
        f'tl.fromTo("#{node_id}-da",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(times["doodle_dur"])},ease:"power2.out"}},'
        f'{_num(start + times["doodle_at"])});',
        f'tl.fromTo("#{node_id}-db",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(_npf_dur(0.36, ctx.duration))},'
        f'ease:"power3.out"}},{_num(start + times["doodle_at"] + _npf_at(0.18, ctx.duration))});',
        f'tl.to("#{node_id}-pulse",{{scale:1.5,opacity:0,'
        f'duration:{_num(_npf_dur(0.58, ctx.duration))},ease:"power3.out",'
        f'immediateRender:false}},'
        f'{_num(start + times["pulse_at"] + _npf_at(0.58, ctx.duration))});',
        f'tl.fromTo("#{node_id}-badge",{{scale:0.78,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(_npf_dur(0.28, ctx.duration))},'
        f'ease:"back.out(2.4)"}},{_num(start + times["badge_at"])});',
        f'tl.set("#{node_id}-white",{{opacity:1}},'
        f'{_num(start + times["white_at"])});',
    ])
    kill_at = start + max(ctx.duration - 0.001, 0.001)
    tweens.append(f'tl.set("#{node_id}-white",{{opacity:1}},{_num(kill_at)});')

    headline = (
        f'{_esc(origin.upper())} <span>TO</span> {_esc(dest.upper())}'
    )
    node = (
        f'<div id="{node_id}" class="clip overlay npf-chart" {_timing(ctx)}>'
        f'<div id="{node_id}-map" class="npf-map">'
        f'<svg class="npf-svg" viewBox="{vb}" '
        f'preserveAspectRatio="xMidYMid meet" aria-hidden="true">'
        f'<rect class="npf-sea" x="{_num(_NPF_VB[0])}" y="{_num(_NPF_VB[1])}" '
        f'width="{_num(_NPF_VB[2])}" height="{_num(_NPF_VB[3])}"></rect>'
        f'{"".join(paths)}</svg>'
        f'<div class="npf-ocean"></div></div>'
        f'<svg class="npf-route" viewBox="0 0 1080 1920" aria-hidden="true">'
        f'<defs><mask id="{node_id}-rm">'
        f'<rect id="{node_id}-rw" class="npf-wipe" x="0" y="0" '
        f'width="1080" height="1920" fill="#fff"></rect></mask></defs>'
        f'<path class="npf-glow" d="{_esc(route_d)}" '
        f'mask="url(#{node_id}-rm)"></path>'
        f'<path class="npf-line" d="{_esc(route_d)}" '
        f'mask="url(#{node_id}-rm)"></path>'
        f'<path class="npf-thread" d="{_esc(route_d)}" '
        f'mask="url(#{node_id}-rm)"></path></svg>'
        f'{"".join(ticks)}'
        f'<div id="{node_id}-nyc" class="npf-pin" '
        f'style="left:{_num(nyc[0])}px;top:{_num(nyc[1])}px">'
        f'<div class="npf-plab npf-plab-l">{_esc(origin)}'
        f'<span>{_esc(origin_code)}</span></div></div>'
        f'<div id="{node_id}-par" class="npf-pin" '
        f'style="left:{_num(paris[0])}px;top:{_num(paris[1])}px">'
        f'<div class="npf-plab npf-plab-r">{_esc(dest)}'
        f'<span>{_esc(dest_code)}</span></div></div>'
        f'<div id="{node_id}-pln" class="npf-plane">'
        f'<svg viewBox="-64 -64 128 128" aria-hidden="true">'
        f'<path d="{_PLANE_PATH}" fill="#ffffff"></path>'
        f'<path d="{_PLANE_INNER}" fill="{_NPF_BLUE}"></path>'
        f'<circle cx="18" cy="0" r="6" fill="{_NPF_PAPER}"></circle>'
        f'</svg></div>'
        f'<svg class="npf-doodle" viewBox="0 0 1080 1920" aria-hidden="true">'
        f'<defs><mask id="{node_id}-dm">'
        f'<rect id="{node_id}-da" class="npf-wipe" x="0" y="0" '
        f'width="1080" height="1920" fill="#fff"></rect></mask>'
        f'<mask id="{node_id}-dn">'
        f'<rect id="{node_id}-db" class="npf-wipe" x="0" y="0" '
        f'width="1080" height="1920" fill="#fff"></rect></mask></defs>'
        f'<ellipse class="npf-circ npf-circ-a" cx="{_num(paris[0])}" '
        f'cy="{_num(paris[1])}" rx="90" ry="70" '
        f'mask="url(#{node_id}-dm)"></ellipse>'
        f'<ellipse class="npf-circ npf-circ-b" cx="{_num(paris[0])}" '
        f'cy="{_num(paris[1])}" rx="78" ry="58" '
        f'mask="url(#{node_id}-dn)"></ellipse></svg>'
        f'<div id="{node_id}-pulse" class="npf-pulse" '
        f'style="left:{_num(paris[0] - 63)}px;top:{_num(paris[1] - 63)}px">'
        f'</div>'
        f'<div id="{node_id}-badge" class="npf-badge" '
        f'style="left:{_num(paris[0] - 70)}px;top:{_num(paris[1] + 86)}px">'
        f'ARRIVED</div>'
        f'<div id="{node_id}-title" class="npf-title">'
        f'<div id="{node_id}-eye" class="npf-eye">Six-second transatlantic hop</div>'
        f'<div id="{node_id}-hl" class="npf-hl">{headline}</div>'
        f'<div id="{node_id}-meta" class="npf-meta"><i></i>'
        f'<span>{_esc(km)} km compressed</span></div></div>'
        f'<div class="npf-attr">Natural Earth</div>'
        f'<div id="{node_id}-white" class="npf-white"></div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def npf_css() -> str:
    """Full-bleed Apple flight. Catalog paper/ink/blue, Inter."""
    px, py, pw, ph = (int(v) for v in _NPF_PANEL)
    return (
        ".npf-chart{left:0;top:0;width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden;font-family:Inter,var(--font-subtitle),sans-serif;"
        f"color:{_NPF_INK};background:{_NPF_PAPER}}}"
        f".npf-map{{position:absolute;left:{px}px;top:{py}px;"
        f"width:{pw}px;height:{ph}px;transform-origin:52% 48%;"
        "will-change:transform,opacity}"
        ".npf-svg{position:absolute;inset:0;width:100%;height:100%}"
        f".npf-sea{{fill:{_NPF_SEA}}}"
        f".npf-land{{fill:{_NPF_LAND};stroke:{_NPF_STROKE};stroke-width:0.4;"
        "vector-effect:non-scaling-stroke}"
        ".npf-ocean{position:absolute;inset:0;pointer-events:none;"
        "background:radial-gradient(circle at 50% 24%,rgba(0,113,227,0.14),"
        "rgba(0,113,227,0) 34%)}"
        ".npf-route,.npf-doodle{position:absolute;inset:0;width:1080px;"
        "height:1920px;overflow:visible;pointer-events:none}"
        ".npf-glow{fill:none;stroke:rgba(0,113,227,0.23);stroke-width:18;"
        "stroke-linecap:round}"
        f".npf-line{{fill:none;stroke:{_NPF_BLUE};stroke-width:8;"
        "stroke-linecap:round}"
        ".npf-thread{fill:none;stroke:rgba(255,255,255,0.86);stroke-width:3;"
        "stroke-linecap:round}"
        ".npf-wipe{transform-origin:0px 960px}"
        ".npf-tick{position:absolute;width:14px;height:14px;border-radius:999px;"
        f"background:#fff;border:3px solid {_NPF_BLUE};opacity:0;"
        "transform-origin:50% 50%}"
        ".npf-pin{position:absolute;width:26px;height:26px;margin:-13px 0 0 -13px;"
        "border-radius:999px;background:#fff;"
        f"border:7px solid {_NPF_BLUE};opacity:0;"
        "transform-origin:50% 50%;z-index:5}"
        ".npf-plab{position:absolute;top:32px;min-width:142px;"
        "padding:12px 16px 13px;border-radius:20px;"
        "background:rgba(255,255,255,0.9);"
        f"color:{_NPF_INK};font-size:22px;font-weight:800;line-height:1;"
        "white-space:nowrap}"
        f".npf-plab span{{display:block;margin-top:7px;color:{_NPF_MUTED};"
        "font-size:13px;font-weight:700}"
        ".npf-plab-l{left:28px}"
        ".npf-plab-r{right:28px}"
        ".npf-plane{position:absolute;left:0;top:0;width:96px;height:96px;"
        "z-index:6;opacity:0;transform-origin:50% 50%;will-change:transform}"
        ".npf-plane svg{width:100%;height:100%;overflow:visible}"
        f".npf-circ{{fill:none;stroke:{_NPF_DOODLE};stroke-linecap:round}}"
        ".npf-circ-a{stroke-width:12}"
        ".npf-circ-b{stroke-width:6;opacity:0.82}"
        ".npf-pulse{position:absolute;width:126px;height:126px;border-radius:999px;"
        "border:4px solid rgba(255,59,48,0.34);opacity:0;z-index:4}"
        ".npf-badge{position:absolute;padding:15px 20px 16px;border-radius:999px;"
        "background:rgba(255,255,255,0.92);"
        f"color:{_NPF_BADGE};font-size:24px;font-weight:900;opacity:0;"
        "transform-origin:50% 50%;z-index:7}"
        ".npf-title{position:absolute;left:40px;top:80px;z-index:8;width:1000px;"
        "padding:28px 32px 30px;border-radius:28px;"
        "background:rgba(255,255,255,0.82);opacity:0;"
        "transform-origin:0% 0%}"
        f".npf-eye{{color:{_NPF_MUTED};font-size:20px;font-weight:800;opacity:0}}"
        f".npf-hl{{margin-top:10px;color:{_NPF_INK};font-size:56px;font-weight:900;"
        "line-height:0.94;opacity:0}"
        f".npf-hl span{{color:{_NPF_BLUE}}}"
        f".npf-meta{{display:flex;align-items:center;gap:14px;margin-top:16px;"
        f"color:{_NPF_MUTED};font-size:24px;font-weight:800;opacity:0}}"
        f".npf-meta i{{display:block;width:54px;height:6px;border-radius:999px;"
        f"background:{_NPF_BLUE}}}"
        ".npf-attr{position:absolute;right:28px;bottom:28px;z-index:5;"
        "padding:8px 12px;border-radius:999px;"
        "background:rgba(255,255,255,0.68);"
        "color:rgba(29,29,31,0.76);font-size:14px;font-weight:700}"
        ".npf-white{position:absolute;inset:0;z-index:30;background:#ffffff;"
        "opacity:0}"
    )
