"""Distortion transitions — glitch slices and chromatic channel displacement.

Catalog ``transitions-distortion`` demonstrates glitch, chromatic, and ripple
distortion transitions with RGB channel separation.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
dual-layer crossfade with scale settle, jittering chromatic R/B slices,
and soft blur.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _tdist_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.48
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "swap_at": mid,
        "to_out_at": mid + 0.001,
        "to_out": max(0.001, d - mid - 0.002),
    }


def tr_transitions_distortion(ctx: TemplateCtx) -> Piece:
    """Distortion: chromatic RGB displacement and glitch crossfade."""
    from_scale = float(ctx.params.get("from_scale", 1.12))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _tdist_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-a",{{scale:1,x:0,opacity:1}},'
        f'{{scale:1.06,x:-24,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.in"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-b",{{scale:1.05,x:24,opacity:0}},'
        f'{{scale:1,x:0,opacity:1,duration:{_num(times["dur"])},'
        f'ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-b",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-r",{{x:-18,opacity:0.8}},'
        f'{{x:22,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"steps(4)"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-b-chroma",{{x:18,opacity:0.75}},'
        f'{{x:-22,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"steps(4)"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.8}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-r",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b-chroma",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-transitions-distortion" {_timing(ctx)}>'
        f'<span class="tdist-stage">'
        f'<span id="{node_id}-blur" class="tdist-blur"></span>'
        f'<span id="{node_id}-a" class="tdist-face tdist-a">'
        f'<span class="tdist-big">ONE</span>'
        f'<span class="tdist-label">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-b" class="tdist-face tdist-b">'
        f'<span class="tdist-big">TWO</span>'
        f'<span class="tdist-label">SCENE B</span>'
        f'</span>'
        f'<span id="{node_id}-r" class="tdist-chroma tdist-r"></span>'
        f'<span id="{node_id}-b-chroma" class="tdist-chroma tdist-b-chroma"></span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def tdist_transition_css() -> str:
    """CSS for Transitions Distortion."""
    return (
        f".tr-transitions-distortion{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-distortion .tdist-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-transitions-distortion .tdist-blur,.tr-transitions-distortion .tdist-face,"
        ".tr-transitions-distortion .tdist-chroma{"
        "position:absolute;inset:0;display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;transform-origin:50% 50%}"
        ".tr-transitions-distortion .tdist-blur{backdrop-filter:blur(14px);opacity:0}"
        ".tr-transitions-distortion .tdist-a{background:#111214;opacity:0}"
        ".tr-transitions-distortion .tdist-b{background:#C8453D;opacity:0}"
        ".tr-transitions-distortion .tdist-big{font-family:Inter,system-ui,sans-serif;font-size:220px;"
        "font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}"
        ".tr-transitions-distortion .tdist-a .tdist-big{color:rgba(255,255,255,0.08)}"
        ".tr-transitions-distortion .tdist-b .tdist-big{color:rgba(255,255,255,0.15)}"
        ".tr-transitions-distortion .tdist-label{font-family:Inter,system-ui,sans-serif;font-size:36px;"
        "font-weight:700;letter-spacing:6px;margin-top:10px}"
        ".tr-transitions-distortion .tdist-a .tdist-label{color:#7A7D82}"
        ".tr-transitions-distortion .tdist-b .tdist-label{color:#ffffff}"
        ".tr-transitions-distortion .tdist-r{background:rgba(200,69,61,0.35);mix-blend-mode:screen;opacity:0}"
        ".tr-transitions-distortion .tdist-b-chroma{background:rgba(228,114,106,0.35);mix-blend-mode:screen;opacity:0}"
    )
