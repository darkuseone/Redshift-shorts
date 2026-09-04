"""Push transitions — directional push slide and displace.

Catalog ``transitions-push`` demonstrates directional push, vertical push,
elastic overshoot, and squeeze transitions between scenes.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
synchronized directional slide of outgoing and incoming scenes with
scale drift and soft blur wash.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _tp_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.5
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "swap_at": mid,
        "to_out_at": mid + 0.001,
        "to_out": max(0.001, d - mid - 0.002),
    }


def tr_transitions_push(ctx: TemplateCtx) -> Piece:
    """Push: synchronized directional push slide from SCENE A to SCENE B."""
    from_scale = float(ctx.params.get("from_scale", 1.10))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _tp_times(d)
    start = ctx.start

    direction = str(ctx.params.get("direction", "left")).lower()
    if direction == "right":
        from_x, to_x = 1080, -1080
        from_y, to_y = 0, 0
    elif direction == "up":
        from_x, to_x = 0, 0
        from_y, to_y = -1920, 1920
    elif direction == "down":
        from_x, to_x = 0, 0
        from_y, to_y = 1920, -1920
    else:  # "left" default
        from_x, to_x = -1080, 1080
        from_y, to_y = 0, 0

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.set("#{node_id}-a",{{opacity:1,x:0,y:0}},{_num(start)});',
        f'tl.set("#{node_id}-b",{{opacity:1}},{_num(start)});',
        f'tl.to("#{node_id}-a",{{x:{from_x},y:{from_y},duration:{_num(times["dur"])},'
        f'ease:"power3.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-b",{{x:{to_x},y:{to_y}}},'
        f'{{x:0,y:0,duration:{_num(times["dur"])},ease:"power3.inOut"}},{_num(start)});',
        f'tl.to("#{node_id}-b",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.6}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-transitions-push" {_timing(ctx)}>'
        f'<span class="tpush-stage">'
        f'<span id="{node_id}-blur" class="tpush-blur"></span>'
        f'<span id="{node_id}-a" class="tpush-face tpush-a">'
        f'<span class="tpush-big">ONE</span>'
        f'<span class="tpush-label">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-b" class="tpush-face tpush-b">'
        f'<span class="tpush-big">TWO</span>'
        f'<span class="tpush-label">SCENE B</span>'
        f'</span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def tp_transition_css() -> str:
    """CSS for Transitions Push."""
    return (
        f".tr-transitions-push{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-push .tpush-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-transitions-push .tpush-blur,.tr-transitions-push .tpush-face{"
        "position:absolute;inset:0;display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;transform-origin:50% 50%}"
        ".tr-transitions-push .tpush-blur{backdrop-filter:blur(12px);opacity:0}"
        ".tr-transitions-push .tpush-a{background:#111214;opacity:0}"
        ".tr-transitions-push .tpush-b{background:#C8453D;opacity:0}"
        ".tr-transitions-push .tpush-big{font-family:Inter,system-ui,sans-serif;font-size:220px;"
        "font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}"
        ".tr-transitions-push .tpush-a .tpush-big{color:rgba(255,255,255,0.08)}"
        ".tr-transitions-push .tpush-b .tpush-big{color:rgba(255,255,255,0.15)}"
        ".tr-transitions-push .tpush-label{font-family:Inter,system-ui,sans-serif;font-size:36px;"
        "font-weight:700;letter-spacing:6px;margin-top:10px}"
        ".tr-transitions-push .tpush-a .tpush-label{color:#7A7D82}"
        ".tr-transitions-push .tpush-b .tpush-label{color:#ffffff}"
    )
