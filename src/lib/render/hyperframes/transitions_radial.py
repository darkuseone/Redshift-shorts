"""Radial transitions — circular iris wipe and radial reveal.

Catalog ``transitions-radial`` demonstrates circle iris, diamond iris,
and diagonal aperture transitions between scenes.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
expanding circular iris mask with perimeter glow ring and dual-scene crossfade.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _trad_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.5
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "swap_at": mid,
        "to_out_at": mid + 0.001,
        "to_out": max(0.001, d - mid - 0.002),
    }


def tr_transitions_radial(ctx: TemplateCtx) -> Piece:
    """Radial: expanding circular iris aperture reveal."""
    from_scale = float(ctx.params.get("from_scale", 1.10))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _trad_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.set("#{node_id}-a",{{opacity:1}},{_num(start)});',
        f'tl.set("#{node_id}-iris",{{opacity:1}},{_num(start)});',
        f'tl.fromTo("#{node_id}-a",{{scale:1}},'
        f'{{scale:1.06,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-iris",{{scale:0}},'
        f'{{scale:1,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-ring",{{scale:0,opacity:0.9}},'
        f'{{scale:1,opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-iris",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.6}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-iris",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-ring",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-transitions-radial" {_timing(ctx)}>'
        f'<span class="trad-stage">'
        f'<span id="{node_id}-blur" class="trad-blur"></span>'
        f'<span id="{node_id}-a" class="trad-face trad-a">'
        f'<span class="trad-big">ONE</span>'
        f'<span class="trad-label">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-iris" class="trad-iris">'
        f'<span class="trad-inner trad-b">'
        f'<span class="trad-big">TWO</span>'
        f'<span class="trad-label">SCENE B</span>'
        f'</span>'
        f'</span>'
        f'<span id="{node_id}-ring" class="trad-ring"></span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def trad_transition_css() -> str:
    """CSS for Transitions Radial."""
    return (
        f".tr-transitions-radial{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-radial .trad-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-transitions-radial .trad-blur,.tr-transitions-radial .trad-face{"
        "position:absolute;inset:0;display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;transform-origin:50% 50%}"
        ".tr-transitions-radial .trad-blur{backdrop-filter:blur(14px);opacity:0}"
        ".tr-transitions-radial .trad-a{background:#111214;opacity:0}"
        ".tr-transitions-radial .trad-inner{position:absolute;left:50%;top:50%;"
        "width:1080px;height:1920px;margin-left:-540px;margin-top:-960px;"
        "display:flex;flex-direction:column;align-items:center;justify-content:center}"
        ".tr-transitions-radial .trad-b{background:#C8453D}"
        ".tr-transitions-radial .trad-big{font-family:Inter,system-ui,sans-serif;font-size:220px;"
        "font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}"
        ".tr-transitions-radial .trad-a .trad-big{color:rgba(255,255,255,0.08)}"
        ".tr-transitions-radial .trad-b .trad-big{color:rgba(255,255,255,0.15)}"
        ".tr-transitions-radial .trad-label{font-family:Inter,system-ui,sans-serif;font-size:36px;"
        "font-weight:700;letter-spacing:6px;margin-top:10px}"
        ".tr-transitions-radial .trad-a .trad-label{color:#7A7D82}"
        ".tr-transitions-radial .trad-b .trad-label{color:#ffffff}"
        ".tr-transitions-radial .trad-iris{position:absolute;left:50%;top:50%;"
        "width:2240px;height:2240px;margin-left:-1120px;margin-top:-1120px;"
        "border-radius:50%;overflow:hidden;transform-origin:50% 50%;opacity:0}"
        ".tr-transitions-radial .trad-ring{position:absolute;left:50%;top:50%;"
        "width:2240px;height:2240px;margin-left:-1120px;margin-top:-1120px;"
        "border-radius:50%;border:4px solid #C8453D;"
        "box-shadow:0 0 32px #C8453D;opacity:0;pointer-events:none;transform-origin:50% 50%}"
    )
