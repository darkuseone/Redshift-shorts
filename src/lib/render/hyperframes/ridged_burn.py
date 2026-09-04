"""Ridged Burn — sharp lightning-crack burn with blackbody embers and sparks.

Catalog ``ridged-burn`` uses ridged multifractal noise to create sharp
lightning-crack edges and blackbody color gradient with ember sparks.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
dual-layer crossfade with scale drift, fiery blackbody gradient wash,
ember spark accents, and soft blur.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _rb_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.48
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "to_out_at": mid + 0.001,
        "to_out": max(0.001, d - mid - 0.002),
    }


def tr_ridged_burn(ctx: TemplateCtx) -> Piece:
    """Ridged burn: fiery blackbody burn and ember crack crossfade."""
    from_scale = float(ctx.params.get("from_scale", 1.14))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _rb_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-from",{{scale:1,opacity:1}},'
        f'{{scale:1.12,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.in"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{scale:1.08,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["dur"])},'
        f'ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-ember",{{scale:0.8,opacity:0}},'
        f'{{scale:1.3,opacity:0.9,duration:{_num(times["mid"])},'
        f'ease:"power2.in"}},{_num(start)});',
        f'tl.to("#{node_id}-ember",{{scale:1.45,opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-sparks",{{scale:0.7,rotation:0,opacity:0}},'
        f'{{scale:1.2,rotation:25,opacity:0.85,duration:{_num(times["mid"])},'
        f'ease:"power3.out"}},{_num(start)});',
        f'tl.to("#{node_id}-sparks",{{scale:1.4,rotation:40,opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.85}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-ember",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-sparks",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-ridged-burn" {_timing(ctx)}>'
        f'<span class="rb-stage">'
        f'<span id="{node_id}-blur" class="rb-blur"></span>'
        f'<span id="{node_id}-from" class="rb-face rb-from">'
        f'<span class="rb-big">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-to" class="rb-face rb-to">'
        f'<span class="rb-big">SCENE B</span>'
        f'</span>'
        f'<span id="{node_id}-ember" class="rb-ember"></span>'
        f'<span id="{node_id}-sparks" class="rb-sparks"></span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def rb_transition_css() -> str:
    """CSS for Ridged Burn transition."""
    return (
        f".tr-ridged-burn{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-ridged-burn .rb-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-ridged-burn .rb-blur,.tr-ridged-burn .rb-face,"
        ".tr-ridged-burn .rb-ember,.tr-ridged-burn .rb-sparks{"
        "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-ridged-burn .rb-blur{backdrop-filter:blur(14px);opacity:0}"
        ".tr-ridged-burn .rb-from{background:#0b090a;color:#e5383b;opacity:0}"
        ".tr-ridged-burn .rb-to{background:#e5383b;color:#0b090a;opacity:0}"
        ".tr-ridged-burn .rb-big{font-family:Inter,system-ui,sans-serif;font-size:120px;"
        "font-weight:900;letter-spacing:0.06em;opacity:0.18;user-select:none}"
        ".tr-ridged-burn .rb-ember{"
        "background:radial-gradient(circle at 50% 50%,rgba(255,255,255,0.85) 0%,rgba(255,183,3,0.75) 25%,rgba(229,56,59,0.8) 50%,transparent 72%);"
        "mix-blend-mode:screen;opacity:0}"
        ".tr-ridged-burn .rb-sparks{"
        "background:radial-gradient(circle at 35% 45%,rgba(255,220,100,0.8) 0%,transparent 12%),"
        "radial-gradient(circle at 65% 55%,rgba(255,183,3,0.75) 0%,transparent 15%),"
        "radial-gradient(circle at 50% 30%,rgba(255,100,50,0.8) 0%,transparent 14%);"
        "mix-blend-mode:screen;opacity:0}"
    )
