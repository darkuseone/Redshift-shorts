"""Domain Warp Dissolve — cascaded warp displacement and iridescent edge dissolve.

Catalog ``domain-warp-dissolve`` applies cascaded FBM domain warping with
an iridescent cosine-palette edge glow across the dissolve transition.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
dual-layer crossfade with scale drift, iridescent spectral edge glow,
and soft backdrop blur.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _dwd_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.5
    to_out_at = mid + 0.001
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "to_out_at": to_out_at,
        "to_out": max(0.001, d - to_out_at - 0.001),
    }


def tr_domain_warp_dissolve(ctx: TemplateCtx) -> Piece:
    """Domain warp dissolve: cascaded warp crossfade with iridescent glow."""
    from_scale = float(ctx.params.get("from_scale", 1.14))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _dwd_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-from",{{scale:1,opacity:1}},'
        f'{{scale:1.1,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{scale:1.08,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-glow",{{scale:0.9,opacity:0.85}},'
        f'{{scale:1.25,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.8}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-glow",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-domain-warp-dissolve" {_timing(ctx)}>'
        f'<span class="dwd-stage">'
        f'<span id="{node_id}-blur" class="dwd-blur"></span>'
        f'<span id="{node_id}-from" class="dwd-face dwd-from">'
        f'<span class="dwd-big">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-to" class="dwd-face dwd-to">'
        f'<span class="dwd-big">SCENE B</span>'
        f'</span>'
        f'<span id="{node_id}-glow" class="dwd-glow"></span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def dwd_transition_css() -> str:
    """CSS for Domain Warp Dissolve transition."""
    return (
        f".tr-domain-warp-dissolve{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-domain-warp-dissolve .dwd-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-domain-warp-dissolve .dwd-blur,.tr-domain-warp-dissolve .dwd-face,"
        ".tr-domain-warp-dissolve .dwd-glow{"
        "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-domain-warp-dissolve .dwd-blur{backdrop-filter:blur(14px);opacity:0}"
        ".tr-domain-warp-dissolve .dwd-from{background:#0d1b2a;color:#00f5d4;opacity:0}"
        ".tr-domain-warp-dissolve .dwd-to{background:#00f5d4;color:#0d1b2a;opacity:0}"
        ".tr-domain-warp-dissolve .dwd-big{font-family:Inter,system-ui,sans-serif;font-size:120px;"
        "font-weight:900;letter-spacing:0.06em;opacity:0.18;user-select:none}"
        ".tr-domain-warp-dissolve .dwd-glow{"
        "background:radial-gradient(circle at 50% 50%,rgba(0,245,212,0.6) 0%,rgba(123,44,191,0.5) 45%,transparent 70%);"
        "mix-blend-mode:screen;opacity:0}"
    )
