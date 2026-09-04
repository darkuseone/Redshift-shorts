"""Flash Through White — dual-scene white flare midpoint transition.

Catalog ``flash-through-white`` brightens both scenes to a white midpoint,
providing high-contrast transition on dark backgrounds.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
dual-layer crossfade with scale settle, blooming white flare,
warm amber/gold glow, and soft blur.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION


def _ftw_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.48
    flash_in = mid
    flash_out = max(0.001, d - mid)
    return {
        "d": d,
        "mid": mid,
        "flash_in": flash_in,
        "flash_out": flash_out,
        "swap_at": mid,
        "to_out": max(0.001, d - mid - 0.001),
    }


def tr_flash_through_white(ctx: TemplateCtx) -> Piece:
    """Flash through white: dual scenes brighten to white flare midpoint."""
    from_scale = float(ctx.params.get("from_scale", 1.12))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _ftw_times(d)
    start = ctx.start

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-from",{{scale:1,opacity:1}},'
        f'{{scale:1.06,opacity:0,duration:{_num(times["mid"])},'
        f'ease:"power1.in"}},{_num(start)});',
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + times["mid"])});',
        f'tl.fromTo("#{node_id}-flash",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(times["flash_in"])},'
        f'ease:"power2.in"}},{_num(start)});',
        f'tl.to("#{node_id}-flash",{{opacity:0,duration:{_num(times["flash_out"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["mid"])});',
        f'tl.fromTo("#{node_id}-glow",{{scale:0.8,opacity:0}},'
        f'{{scale:1.2,opacity:0.9,duration:{_num(times["flash_in"])},'
        f'ease:"power2.in"}},{_num(start)});',
        f'tl.to("#{node_id}-glow",{{scale:1.3,opacity:0,duration:{_num(times["flash_out"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["mid"])});',
        f'tl.fromTo("#{node_id}-to",{{scale:1.05,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["to_out"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["swap_at"])});',
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-flash",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-glow",{{opacity:0}},{_num(start + d)});',
    ]

    node = (
        f'<div id="{node_id}" class="clip tr-flash-through-white" {_timing(ctx)}>'
        f'<span class="ftw-stage">'
        f'<span id="{node_id}-from" class="ftw-face ftw-from">'
        f'<span class="ftw-big">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-to" class="ftw-face ftw-to">'
        f'<span class="ftw-big">SCENE B</span>'
        f'</span>'
        f'<span id="{node_id}-glow" class="ftw-glow"></span>'
        f'<span id="{node_id}-flash" class="ftw-flash"></span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def ftw_transition_css() -> str:
    """CSS for Flash Through White transition."""
    return (
        f".tr-flash-through-white{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-flash-through-white .ftw-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-flash-through-white .ftw-face,.tr-flash-through-white .ftw-glow,"
        ".tr-flash-through-white .ftw-flash{"
        "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-flash-through-white .ftw-from{background:#111214;color:#C8453D;opacity:0}"
        ".tr-flash-through-white .ftw-to{background:#C8453D;color:#ffffff;opacity:0}"
        ".tr-flash-through-white .ftw-big{font-family:Inter,system-ui,sans-serif;font-size:120px;"
        "font-weight:900;letter-spacing:0.06em;opacity:0.18;user-select:none}"
        ".tr-flash-through-white .ftw-glow{"
        "background:radial-gradient(circle at 50% 50%,rgba(200,69,61,0.7) 0%,rgba(255,255,255,0.4) 40%,transparent 70%);"
        "mix-blend-mode:screen;opacity:0}"
        ".tr-flash-through-white .ftw-flash{background:#ffffff;opacity:0}"
    )
