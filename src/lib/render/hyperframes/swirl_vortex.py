"""Swirl Vortex — opposing spiral swirl rotation and organic vortex transition.

Catalog ``swirl-vortex`` swirls both scenes in opposite directions along
an FBM-warped spiral path with organic vortex distortion.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
dual-layer crossfade with counter-rotating spiral trajectories,
seafoam vortex glow accent, and soft blur.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _sv_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.48
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "to_out_at": mid + 0.001,
        "to_out": max(0.001, d - mid - 0.002),
    }


def tr_swirl_vortex(ctx: TemplateCtx) -> Piece:
    """Swirl vortex: counter-rotating swirl crossfade with organic vortex glow."""
    from_scale = float(ctx.params.get("from_scale", 1.12))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _sv_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-from",{{rotation:0,scale:1,opacity:1}},'
        f'{{rotation:28,scale:0.88,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.in"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{rotation:-28,scale:1.12,opacity:0}},'
        f'{{rotation:0,scale:1,opacity:1,duration:{_num(times["dur"])},'
        f'ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-vortex",{{rotation:0,scale:0.7,opacity:0.9}},'
        f'{{rotation:60,scale:1.35,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.8}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-vortex",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-swirl-vortex" {_timing(ctx)}>'
        f'<span class="sv-stage">'
        f'<span id="{node_id}-blur" class="sv-blur"></span>'
        f'<span id="{node_id}-from" class="sv-face sv-from">'
        f'<span class="sv-big">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-to" class="sv-face sv-to">'
        f'<span class="sv-big">SCENE B</span>'
        f'</span>'
        f'<span id="{node_id}-vortex" class="sv-vortex"></span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def sv_transition_css() -> str:
    """CSS for Swirl Vortex transition."""
    return (
        f".tr-swirl-vortex{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-swirl-vortex .sv-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-swirl-vortex .sv-blur,.tr-swirl-vortex .sv-face,"
        ".tr-swirl-vortex .sv-vortex{"
        "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-swirl-vortex .sv-blur{backdrop-filter:blur(14px);opacity:0}"
        ".tr-swirl-vortex .sv-from{background:#111214;color:#C8453D;opacity:0}"
        ".tr-swirl-vortex .sv-to{background:#C8453D;color:#ffffff;opacity:0}"
        ".tr-swirl-vortex .sv-big{font-family:Inter,system-ui,sans-serif;font-size:120px;"
        "font-weight:900;letter-spacing:0.06em;opacity:0.18;user-select:none}"
        ".tr-swirl-vortex .sv-vortex{"
        "background:radial-gradient(circle at 50% 50%,rgba(200,69,61,0.65) 0%,rgba(17,18,20,0.3) 40%,transparent 70%);"
        "mix-blend-mode:screen;opacity:0}"
    )
