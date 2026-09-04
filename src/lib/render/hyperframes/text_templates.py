"""Text-fullscreen templates: split-flap-board and news-ticker.

Catalog translated to 1080×1920 9:16.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing


def _sf_dur(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


def txt_split_flap_board(ctx: "TemplateCtx") -> Piece:
    node_id = f"sfb-{ctx.index:02d}"
    start = ctx.start
    duration = max(float(ctx.duration), 0.4)
    word = str(ctx.params.get("word", "FLIGHT"))[:8]
    fade = min(0.4, duration * 0.45)
    out_at = start + duration - fade

    # Opacity on an inner stage, not the clip: HyperFrames owns clip visibility.
    # CSS starts at opacity:0 so the full-frame board cannot flash white before
    # the first tween (gsap_fullscreen_overlay_starts_visible).
    tweens = [
        f'tl.fromTo("#{node_id}-stage",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(fade)},ease:"power2.out"}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-stage",{{opacity:1}},'
        f'{{opacity:0,duration:{_num(fade)},ease:"power2.in",'
        f'immediateRender:false}},{_num(out_at)});',
        f'tl.set("#{node_id}-stage",{{opacity:0}},{_num(out_at + fade)});',
    ]

    letters = []
    for i, char in enumerate(word):
        lid = f"{node_id}-l{i}"
        letters.append(f'<div id="{lid}" class="sfb-char">{_esc(char)}</div>')
        tweens.append(
            f'tl.fromTo("#{lid}",{{rotationX:-90,opacity:0}},'
            f'{{rotationX:0,opacity:1,duration:0.3,ease:"back.out(1.5)"}},'
            f'{_num(start + i * 0.1)});'
        )

    html = (
        f'<div id="{node_id}" class="sfb-overlay clip" {_timing(ctx)}>'
        f'<div id="{node_id}-stage" class="sfb-stage">'
        f'<div class="sfb-board">{"".join(letters)}</div></div></div>'
    )
    return Piece(nodes=[html], tweens=tweens)


def txt_news_ticker(ctx: "TemplateCtx") -> Piece:
    node_id = f"ntk-{ctx.index:02d}"
    start = ctx.start
    duration = max(float(ctx.duration), 0.4)
    text = str(ctx.params.get("text", "BREAKING NEWS"))
    fade = min(0.4, duration * 0.45)
    out_at = start + duration - fade

    tweens = [
        f'tl.fromTo("#{node_id}-stage",{{y:200,opacity:0}},'
        f'{{y:0,opacity:1,duration:{_num(min(0.6, fade + 0.2))},ease:"power3.out"}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-scroll",{{x:1080}},'
        f'{{x:-1500,duration:{_num(duration)},ease:"none"}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-stage",{{y:0,opacity:1}},'
        f'{{y:200,opacity:0,duration:{_num(fade)},ease:"power2.in",'
        f'immediateRender:false}},{_num(out_at)});',
        f'tl.set("#{node_id}-stage",{{y:200,opacity:0}},{_num(out_at + fade)});',
    ]

    html = (
        f'<div id="{node_id}" class="ntk-overlay clip" {_timing(ctx)}>'
        f'<div id="{node_id}-stage" class="ntk-stage">'
        f'<div class="ntk-bar">'
        f'<div class="ntk-label">NEWS</div>'
        f'<div id="{node_id}-scroll" class="ntk-scroll">{_esc(text)}</div>'
        f'</div></div></div>'
    )
    return Piece(nodes=[html], tweens=tweens)


def sfb_css() -> str:
    return (
        ".sfb-overlay{position:absolute;inset:0;font-family:monospace;"
        "display:flex;align-items:center;justify-content:center;"
        "background:transparent}"
        ".sfb-stage{position:absolute;inset:0;display:flex;align-items:center;"
        "justify-content:center;background:#111214;opacity:0}"
        ".sfb-board{display:flex;gap:12px}"
        ".sfb-char{width:100px;height:140px;background:#111214;"
        "border:2px solid #7A7D82;border-radius:12px;display:flex;"
        "align-items:center;justify-content:center;color:#ffffff;"
        "font-size:80px;font-weight:bold;transform-origin:50% 50%;"
        "box-shadow:inset 0 -2px 10px rgba(0,0,0,0.8)}"
        ".ntk-overlay{position:absolute;left:0;right:0;bottom:100px;"
        "height:120px;font-family:Inter,sans-serif}"
        ".ntk-stage{position:absolute;inset:0;opacity:0}"
        ".ntk-bar{position:absolute;inset:0;background:#C8453D;display:flex;"
        "align-items:center;overflow:hidden}"
        ".ntk-label{position:absolute;left:0;top:0;bottom:0;width:200px;"
        "background:#111214;color:#ffffff;font-size:48px;font-weight:900;"
        "display:flex;align-items:center;justify-content:center;z-index:10}"
        ".ntk-scroll{position:absolute;left:240px;white-space:nowrap;"
        "color:#ffffff;font-size:48px;font-weight:700}"
    )
