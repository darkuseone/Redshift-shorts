"""Chromatic Radial Split — RGB channels separate and converge radially on cut.

Catalog ``chromatic-radial-split`` runs a WebGL fragment shader with radial UV shift
for R and B channels around screen center.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
radial color rings with screen blend, scale expansion/contraction, and soft blur.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _crs_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.5
    to_out_at = mid + 0.001
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "to_out_at": to_out_at,
        "to_out": max(0.001, d - to_out_at - 0.001),
    }


def tr_chromatic_radial_split(ctx: TemplateCtx) -> Piece:
    """Chromatic radial split: R/B channels expand/converge radially."""
    from_scale = float(ctx.params.get("from_scale", 1.14))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _crs_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-from",{{scale:1,opacity:0.6}},'
        f'{{scale:1.18,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{scale:1.15}},'
        f'{{scale:1,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{opacity:0}},'
        f'{{opacity:0.45,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-r",{{scale:0.88,opacity:0.7}},'
        f'{{scale:1.24,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-b",{{scale:1.22,opacity:0.65}},'
        f'{{scale:0.92,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.85}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-r",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-chromatic-radial-split" {_timing(ctx)}>'
        f'<span class="crs-stage">'
        f'<span id="{node_id}-blur" class="crs-blur"></span>'
        f'<span id="{node_id}-from" class="crs-from"></span>'
        f'<span id="{node_id}-to" class="crs-to"></span>'
        f'<span id="{node_id}-r" class="crs-r"></span>'
        f'<span id="{node_id}-b" class="crs-b"></span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def crs_transition_css() -> str:
    """CSS for Chromatic Radial Split transition."""
    return (
        f".tr-chromatic-radial-split{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-chromatic-radial-split .crs-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-chromatic-radial-split .crs-blur,.tr-chromatic-radial-split .crs-from,"
        ".tr-chromatic-radial-split .crs-to,.tr-chromatic-radial-split .crs-r,"
        ".tr-chromatic-radial-split .crs-b{"
        "position:absolute;inset:0;display:block;opacity:0;transform-origin:50% 50%}"
        ".tr-chromatic-radial-split .crs-blur{backdrop-filter:blur(14px)}"
        ".tr-chromatic-radial-split .crs-from{background:#22223b;mix-blend-mode:overlay}"
        ".tr-chromatic-radial-split .crs-to{background:#7678ed;mix-blend-mode:overlay}"
        ".tr-chromatic-radial-split .crs-r{inset:-20%;border-radius:50%;"
        "background:radial-gradient(circle,rgba(255,51,102,0.75) 0%,transparent 60%);mix-blend-mode:screen}"
        ".tr-chromatic-radial-split .crs-b{inset:-16%;border-radius:50%;"
        "background:radial-gradient(circle,rgba(51,136,255,0.7) 0%,transparent 60%);mix-blend-mode:screen}"
    )
