"""Dissolve transitions — smooth crossfade and scale drift.

Catalog ``transitions-dissolve`` demonstrates crossfade, blur crossfade,
focus pull, and color dip transitions between scenes.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
dual-layer crossfade with subtle scale drift, soft blur wash,
and clean opacity blend.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _td_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.5
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "swap_at": mid,
        "to_out_at": mid + 0.001,
        "to_out": max(0.001, d - mid - 0.002),
    }


def tr_transitions_dissolve(ctx: TemplateCtx) -> Piece:
    """Dissolve: smooth crossfade from SCENE A to SCENE B with scale drift."""
    from_scale = float(ctx.params.get("from_scale", 1.10))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _td_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-a",{{scale:1,opacity:1}},'
        f'{{scale:1.05,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-b",{{scale:0.96,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.to("#{node_id}-b",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.75}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-transitions-dissolve" {_timing(ctx)}>'
        f'<span class="td-stage">'
        f'<span id="{node_id}-blur" class="td-blur"></span>'
        f'<span id="{node_id}-a" class="td-face td-a">'
        f'<span class="td-big">ONE</span>'
        f'<span class="td-label">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-b" class="td-face td-b">'
        f'<span class="td-big">TWO</span>'
        f'<span class="td-label">SCENE B</span>'
        f'</span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def td_transition_css() -> str:
    """CSS for Transitions Dissolve."""
    return (
        f".tr-transitions-dissolve{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-dissolve .td-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-transitions-dissolve .td-blur,.tr-transitions-dissolve .td-face{"
        "position:absolute;inset:0;display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;transform-origin:50% 50%}"
        ".tr-transitions-dissolve .td-blur{backdrop-filter:blur(14px);opacity:0}"
        ".tr-transitions-dissolve .td-a{background:#1b263b;opacity:0}"
        ".tr-transitions-dissolve .td-b{background:#e07a5f;opacity:0}"
        ".tr-transitions-dissolve .td-big{font-family:Inter,system-ui,sans-serif;font-size:220px;"
        "font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}"
        ".tr-transitions-dissolve .td-a .td-big{color:rgba(255,255,255,0.08)}"
        ".tr-transitions-dissolve .td-b .td-big{color:rgba(255,255,255,0.15)}"
        ".tr-transitions-dissolve .td-label{font-family:Inter,system-ui,sans-serif;font-size:36px;"
        "font-weight:700;letter-spacing:6px;margin-top:10px}"
        ".tr-transitions-dissolve .td-a .td-label{color:#778da9}"
        ".tr-transitions-dissolve .td-b .td-label{color:#ffffff}"
    )
