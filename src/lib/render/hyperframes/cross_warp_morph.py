"""Cross-Warp Morph — dual-scene noise displacement and morph transition.

Catalog ``cross-warp-morph`` displaces both scenes along a shared FBM noise
field in opposite directions with a noise-driven blend boundary.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
opposing coordinate drift, scale expansion/contraction, dual-layer crossfade,
screen/multiply warp gradients, and soft blur.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _cwm_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.5
    to_out_at = mid + 0.001
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "to_out_at": to_out_at,
        "to_out": max(0.001, d - to_out_at - 0.001),
    }


def tr_cross_warp_morph(ctx: TemplateCtx) -> Piece:
    """Cross-warp morph: dual scene displacement in opposite directions with blend."""
    from_scale = float(ctx.params.get("from_scale", 1.12))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _cwm_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-from",{{x:0,scale:1,opacity:1}},'
        f'{{x:60,scale:1.08,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{x:-60,scale:1.08,opacity:0}},'
        f'{{x:0,scale:1,opacity:1,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-warp-a",{{x:-80,scaleX:1.15,opacity:0.75}},'
        f'{{x:80,scaleX:0.9,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-warp-b",{{x:80,scaleX:0.9,opacity:0.65}},'
        f'{{x:-80,scaleX:1.15,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.8}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-warp-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-warp-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-cross-warp-morph" {_timing(ctx)}>'
        f'<span class="cwm-stage">'
        f'<span id="{node_id}-blur" class="cwm-blur"></span>'
        f'<span id="{node_id}-from" class="cwm-face cwm-from">'
        f'<span class="cwm-big">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-to" class="cwm-face cwm-to">'
        f'<span class="cwm-big">SCENE B</span>'
        f'</span>'
        f'<span id="{node_id}-warp-a" class="cwm-warp cwm-warp-a"></span>'
        f'<span id="{node_id}-warp-b" class="cwm-warp cwm-warp-b"></span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def cwm_transition_css() -> str:
    """CSS for Cross-Warp Morph transition."""
    return (
        f".tr-cross-warp-morph{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-cross-warp-morph .cwm-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-cross-warp-morph .cwm-blur,.tr-cross-warp-morph .cwm-face,"
        ".tr-cross-warp-morph .cwm-warp{"
        "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-cross-warp-morph .cwm-blur{backdrop-filter:blur(14px);opacity:0}"
        ".tr-cross-warp-morph .cwm-from{background:#283618;color:#a7c957;opacity:0}"
        ".tr-cross-warp-morph .cwm-to{background:#a7c957;color:#283618;opacity:0}"
        ".tr-cross-warp-morph .cwm-big{font-family:Inter,system-ui,sans-serif;font-size:120px;"
        "font-weight:900;letter-spacing:0.06em;opacity:0.18;user-select:none}"
        ".tr-cross-warp-morph .cwm-warp-a{"
        "background:radial-gradient(ellipse at 40% 50%,rgba(167,201,87,0.45) 0%,transparent 70%);"
        "mix-blend-mode:screen;opacity:0}"
        ".tr-cross-warp-morph .cwm-warp-b{"
        "background:radial-gradient(ellipse at 60% 50%,rgba(40,54,24,0.7) 0%,transparent 70%);"
        "mix-blend-mode:multiply;opacity:0}"
    )
