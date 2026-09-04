"""Scale transitions — zoom-through and zoom-out scale dynamics.

Catalog ``transitions-scale`` demonstrates zoom-through and zoom-out
scale transitions between scenes.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
dynamic scale expansion/contraction, dual-scene crossfade, and soft blur wash.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _ts_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.48
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "swap_at": mid,
        "to_out_at": mid + 0.001,
        "to_out": max(0.001, d - mid - 0.002),
    }


def tr_transitions_scale(ctx: TemplateCtx) -> Piece:
    """Scale: zoom-through or zoom-out scale transition."""
    from_scale = float(ctx.params.get("from_scale", 1.12))
    mode = str(ctx.params.get("mode", "zoom_through")).lower()
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _ts_times(d)
    start = ctx.start

    if mode == "zoom_out":
        a_scale_to = 0.35
        b_scale_from = 1.18
    else:  # zoom_through default
        a_scale_to = 2.40
        b_scale_from = 0.55

    half = times["dur"] * 0.55
    b_start = start + times["swap_at"] * 0.4

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.set("#{node_id}-a",{{opacity:1}},{_num(start)});',
        f'tl.fromTo("#{node_id}-a",{{scale:1}},'
        f'{{scale:{_num(a_scale_to)},opacity:0,duration:{_num(half)},ease:"power3.in"}},{_num(start)});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + half)});',
        f'tl.fromTo("#{node_id}-b",{{scale:{_num(b_scale_from)},opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(half)},ease:"power3.out"}},{_num(b_start)});',
        f'tl.to("#{node_id}-b",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.7}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-transitions-scale" {_timing(ctx)}>'
        f'<span class="tscale-stage">'
        f'<span id="{node_id}-blur" class="tscale-blur"></span>'
        f'<span id="{node_id}-a" class="tscale-face tscale-a">'
        f'<span class="tscale-big">ONE</span>'
        f'<span class="tscale-label">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-b" class="tscale-face tscale-b">'
        f'<span class="tscale-big">TWO</span>'
        f'<span class="tscale-label">SCENE B</span>'
        f'</span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def ts_transition_css() -> str:
    """CSS for Transitions Scale."""
    return (
        f".tr-transitions-scale{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-scale .tscale-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-transitions-scale .tscale-blur,.tr-transitions-scale .tscale-face{"
        "position:absolute;inset:0;display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;transform-origin:50% 50%}"
        ".tr-transitions-scale .tscale-blur{backdrop-filter:blur(14px);opacity:0}"
        ".tr-transitions-scale .tscale-a{background:#111214;opacity:0}"
        ".tr-transitions-scale .tscale-b{background:#C8453D;opacity:0}"
        ".tr-transitions-scale .tscale-big{font-family:Inter,system-ui,sans-serif;font-size:220px;"
        "font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}"
        ".tr-transitions-scale .tscale-a .tscale-big{color:rgba(255,255,255,0.08)}"
        ".tr-transitions-scale .tscale-b .tscale-big{color:rgba(255,255,255,0.15)}"
        ".tr-transitions-scale .tscale-label{font-family:Inter,system-ui,sans-serif;font-size:36px;"
        "font-weight:700;letter-spacing:6px;margin-top:10px}"
        ".tr-transitions-scale .tscale-a .tscale-label{color:#7A7D82}"
        ".tr-transitions-scale .tscale-b .tscale-label{color:#ffffff}"
    )
