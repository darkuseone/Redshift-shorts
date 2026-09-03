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
    
    tweens = [
        f'tl.fromTo("#{node_id}",{{opacity:0}},{{opacity:1,duration:0.4}},{_num(start)});',
        f'tl.to("#{node_id}",{{opacity:0,duration:0.4}},{_num(start + duration - 0.4)});'
    ]
    
    letters = []
    for i, char in enumerate(word):
        lid = f"{node_id}-l{i}"
        letters.append(f'<div id="{lid}" class="sfb-char">{_esc(char)}</div>')
        tweens.append(
            f'tl.fromTo("#{lid}",{{rotationX:-90,opacity:0}},{{rotationX:0,opacity:1,duration:0.3,ease:"back.out(1.5)"}},{_num(start + i * 0.1)});'
        )

    html = f"""
    <div id="{node_id}" class="sfb-overlay clip" {_timing(ctx)}>
      <div class="sfb-board">
        {"".join(letters)}
      </div>
    </div>
    """
    return Piece(nodes=[html], tweens=tweens)

def txt_news_ticker(ctx: "TemplateCtx") -> Piece:
    node_id = f"ntk-{ctx.index:02d}"
    start = ctx.start
    duration = max(float(ctx.duration), 0.4)
    text = str(ctx.params.get("text", "BREAKING NEWS"))
    
    tweens = [
        f'tl.fromTo("#{node_id}",{{y:200,opacity:0}},{{y:0,opacity:1,duration:0.6,ease:"power3.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-scroll",{{x:1080}},{{x:-1500,duration:{_num(duration)},ease:"none"}},{_num(start)});',
        f'tl.to("#{node_id}",{{y:200,opacity:0,duration:0.4}},{_num(start + duration - 0.4)});'
    ]

    html = f"""
    <div id="{node_id}" class="ntk-overlay clip" {_timing(ctx)}>
      <div class="ntk-bar">
        <div class="ntk-label">NEWS</div>
        <div id="{node_id}-scroll" class="ntk-scroll">{_esc(text)}</div>
      </div>
    </div>
    """
    return Piece(nodes=[html], tweens=tweens)

def sfb_css() -> str:
    return (
        ".sfb-overlay{position:absolute;inset:0;font-family:monospace;display:flex;align-items:center;justify-content:center;background:#111}"
        ".sfb-board{display:flex;gap:12px}"
        ".sfb-char{width:100px;height:140px;background:#222;border:2px solid #444;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:80px;font-weight:bold;transform-origin:50% 50%;box-shadow:inset 0 -2px 10px rgba(0,0,0,0.8)}"
        ".ntk-overlay{position:absolute;left:0;right:0;bottom:100px;height:120px;font-family:Inter,sans-serif}"
        ".ntk-bar{position:absolute;inset:0;background:#c8453d;display:flex;align-items:center;overflow:hidden}"
        ".ntk-label{position:absolute;left:0;top:0;bottom:0;width:200px;background:#111214;color:#fff;font-size:48px;font-weight:900;display:flex;align-items:center;justify-content:center;z-index:10}"
        ".ntk-scroll{position:absolute;left:240px;white-space:nowrap;color:#fff;font-size:48px;font-weight:700}"
    )
