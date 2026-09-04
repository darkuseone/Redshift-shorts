"""Mechanical transitions — industrial shutter slam and mechanical reveal.

Catalog ``transitions-mechanical`` demonstrates industrial shutter slam
and aperture reveal transitions between scenes.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
dual opposing shutter plates with seam impact spark and scene swap.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _tm_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    close_dur = round(d * 0.40, 4)
    hold_dur = round(d * 0.15, 4)
    open_dur = max(0.001, round(d - close_dur - hold_dur, 4))
    mid = close_dur
    return {
        "dur": d,
        "close": close_dur,
        "hold": hold_dur,
        "open": open_dur,
        "mid": mid,
        "open_start": close_dur + hold_dur,
        "to_out": max(0.001, open_dur * 0.8),
    }


def tr_transitions_mechanical(ctx: TemplateCtx) -> Piece:
    """Mechanical: industrial dual shutter slam and reveal."""
    from_scale = float(ctx.params.get("from_scale", 1.10))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _tm_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.set("#{node_id}-top",{{opacity:1}},{_num(start)});',
        f'tl.set("#{node_id}-bot",{{opacity:1}},{_num(start)});',
        f'tl.fromTo("#{node_id}-a",{{scale:1,opacity:1}},'
        f'{{scale:1.04,opacity:0,duration:{_num(times["close"])},ease:"power2.in"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-top",{{y:-960}},'
        f'{{y:0,duration:{_num(times["close"])},ease:"power3.in"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-bot",{{y:960}},'
        f'{{y:0,duration:{_num(times["close"])},ease:"power3.in"}},{_num(start)});',
        f'tl.set("#{node_id}-b",{{opacity:1}},{_num(start + times["mid"])});',
        f'tl.fromTo("#{node_id}-seam",{{opacity:1,scaleX:1.05}},'
        f'{{opacity:0,scaleX:1,duration:{_num(min(0.12, d * 0.2))},ease:"power2.out"}},'
        f'{_num(start + times["mid"])});',
        f'tl.set("#{node_id}-seam",{{opacity:0}},{_num(start + times["mid"] + min(0.12, d * 0.2))});',
        f'tl.to("#{node_id}-top",{{y:-960,duration:{_num(times["open"])},ease:"power3.out"}},'
        f'{_num(start + times["open_start"])});',
        f'tl.to("#{node_id}-bot",{{y:960,duration:{_num(times["open"])},ease:"power3.out"}},'
        f'{_num(start + times["open_start"])});',
        f'tl.to("#{node_id}-b",{{opacity:0,duration:{_num(times["to_out"])},ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["open_start"])});',
        f'tl.set("#{node_id}-top",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-bot",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-seam",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-transitions-mechanical" {_timing(ctx)}>'
        f'<span class="tm-stage">'
        f'<span id="{node_id}-a" class="tm-face tm-a">'
        f'<span class="tm-big">ONE</span>'
        f'<span class="tm-label">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-b" class="tm-face tm-b">'
        f'<span class="tm-big">TWO</span>'
        f'<span class="tm-label">SCENE B</span>'
        f'</span>'
        f'<span id="{node_id}-top" class="tm-shutter tm-shutter-top">'
        f'<span class="tm-shutter-lip tm-lip-top"></span>'
        f'</span>'
        f'<span id="{node_id}-bot" class="tm-shutter tm-shutter-bot">'
        f'<span class="tm-shutter-lip tm-lip-bot"></span>'
        f'</span>'
        f'<span id="{node_id}-seam" class="tm-seam"></span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def tm_transition_css() -> str:
    """CSS for Transitions Mechanical."""
    return (
        f".tr-transitions-mechanical{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-mechanical .tm-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-transitions-mechanical .tm-face{"
        "position:absolute;inset:0;display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;transform-origin:50% 50%}"
        ".tr-transitions-mechanical .tm-a{background:#111214;opacity:0}"
        ".tr-transitions-mechanical .tm-b{background:#C8453D;opacity:0}"
        ".tr-transitions-mechanical .tm-big{font-family:Inter,system-ui,sans-serif;font-size:220px;"
        "font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}"
        ".tr-transitions-mechanical .tm-a .tm-big{color:rgba(255,255,255,0.08)}"
        ".tr-transitions-mechanical .tm-b .tm-big{color:rgba(255,255,255,0.15)}"
        ".tr-transitions-mechanical .tm-label{font-family:Inter,system-ui,sans-serif;font-size:36px;"
        "font-weight:700;letter-spacing:6px;margin-top:10px}"
        ".tr-transitions-mechanical .tm-a .tm-label{color:#7A7D82}"
        ".tr-transitions-mechanical .tm-b .tm-label{color:#ffffff}"
        ".tr-transitions-mechanical .tm-shutter{position:absolute;left:0;width:100%;height:50%;"
        "background:#111214;opacity:0;z-index:50}"
        ".tr-transitions-mechanical .tm-shutter-top{top:0;"
        "background:linear-gradient(180deg,#111214 0%,#111214 92%,#C8453D 100%)}"
        ".tr-transitions-mechanical .tm-shutter-bot{bottom:0;"
        "background:linear-gradient(0deg,#111214 0%,#111214 92%,#C8453D 100%)}"
        ".tr-transitions-mechanical .tm-shutter-lip{position:absolute;left:0;right:0;height:4px;"
        "background:#C8453D;display:block}"
        ".tr-transitions-mechanical .tm-lip-top{bottom:0}"
        ".tr-transitions-mechanical .tm-lip-bot{top:0}"
        ".tr-transitions-mechanical .tm-seam{position:absolute;top:50%;left:0;width:100%;"
        "height:8px;margin-top:-4px;background:#ffffff;"
        "box-shadow:0 0 24px #C8453D,0 0 48px rgba(200,69,61,0.6);opacity:0;z-index:52}"
    )
