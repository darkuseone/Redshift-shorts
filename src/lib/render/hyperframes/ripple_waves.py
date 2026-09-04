"""Ripple Waves — concentric exponential sine ripple waves with opposite phases.

Catalog ``ripple-waves`` creates exponential sine waves with sharp crests
and broad troughs, rippling both scenes in opposite phases.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
dual-layer crossfade with scale drift, concentric wave rings in counter-phase,
water-ripple highlights, and soft blur.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _rw_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.48
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "to_out_at": mid + 0.001,
        "to_out": max(0.001, d - mid - 0.002),
    }


def tr_ripple_waves(ctx: TemplateCtx) -> Piece:
    """Ripple waves: concentric wave rings with counter-phase ripple crossfade."""
    from_scale = float(ctx.params.get("from_scale", 1.12))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _rw_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-from",{{scale:1,opacity:1}},'
        f'{{scale:1.08,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{scale:1.06,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-w1",{{scale:0.75,opacity:0.85}},'
        f'{{scale:1.35,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-w2",{{scale:1.3,opacity:0.8}},'
        f'{{scale:0.8,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.8}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-w1",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-w2",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-ripple-waves" {_timing(ctx)}>'
        f'<span class="rw-stage">'
        f'<span id="{node_id}-blur" class="rw-blur"></span>'
        f'<span id="{node_id}-from" class="rw-face rw-from">'
        f''
        f'</span>'
        f'<span id="{node_id}-to" class="rw-face rw-to">'
        f''
        f'</span>'
        f'<span id="{node_id}-w1" class="rw-wave rw-w1"></span>'
        f'<span id="{node_id}-w2" class="rw-wave rw-w2"></span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def rw_transition_css() -> str:
    """CSS for Ripple Waves transition."""
    return (
        f".tr-ripple-waves{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-ripple-waves .rw-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-ripple-waves .rw-blur,.tr-ripple-waves .rw-face,"
        ".tr-ripple-waves .rw-wave{"
        "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-ripple-waves .rw-blur{backdrop-filter:blur(14px);opacity:0}"
        ".tr-ripple-waves .rw-from{background:#111214;color:#C8453D;opacity:0}"
        ".tr-ripple-waves .rw-to{background:#C8453D;color:#ffffff;opacity:0}"
        ".tr-ripple-waves .rw-big{font-family:Inter,system-ui,sans-serif;font-size:120px;"
        "font-weight:900;letter-spacing:0.06em;opacity:0.18;user-select:none}"
        ".tr-ripple-waves .rw-w1{"
        "background:radial-gradient(circle at 50% 50%,rgba(200,69,61,0.6) 0%,rgba(17,18,20,0.3) 35%,transparent 65%);"
        "mix-blend-mode:screen;opacity:0}"
        ".tr-ripple-waves .rw-w2{"
        "background:radial-gradient(circle at 50% 50%,rgba(255,255,255,0.7) 0%,rgba(228,114,106,0.4) 30%,transparent 60%);"
        "mix-blend-mode:overlay;opacity:0}"
    )
