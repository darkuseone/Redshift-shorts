"""Flowchart template for dataviz.

Catalog ``flowchart`` is 1920×1080 / 12s. Translated to 1080×1920 9:16.
Uses GSAP to draw boxes and connecting lines.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_FLC_CATALOG = 12.0

def _flc_at(catalog: float, duration: float) -> float:
    return catalog * (max(duration, 0.4) / _FLC_CATALOG)

def _flc_dur(catalog: float, duration: float) -> float:
    dur = _flc_at(catalog, duration)
    return dur if dur <= 0.001 else max(0.001, dur - 0.001)

def dv_flowchart(ctx: "TemplateCtx") -> Piece:
    node_id = f"flc-{ctx.index:02d}"
    start = ctx.start
    duration = max(float(ctx.duration), 0.4)

    def at(catalog: float) -> float:
        return start + _flc_at(catalog, duration)

    def dur(catalog: float) -> float:
        return _flc_dur(catalog, duration)
        
    nodes = list(ctx.params.get("nodes", ["Start", "Process", "Decision", "End"]))[:5]
    if not nodes:
        nodes = ["Start", "Process", "End"]

    tweens = [
        f'tl.fromTo("#{node_id}-bg",{{opacity:0}},{{opacity:1,duration:{_num(dur(0.8))},ease:"power2.out"}},{_num(at(0.0))});',
    ]
    
    html_nodes = []
    html_lines = []
    
    # Simple vertical layout
    spacing = 200
    y_start = 400
    x_center = 540
    
    for i, title in enumerate(nodes):
        nid = f"{node_id}-n{i}"
        y = y_start + i * spacing
        html_nodes.append(
            f'<div id="{nid}" class="flc-node" style="top:{y}px;">{_esc(title)}</div>'
        )
        tweens.append(
            f'tl.fromTo("#{nid}",{{scale:0.5,opacity:0,y:-20}},{{scale:1,opacity:1,y:0,duration:{_num(dur(0.6))},ease:"back.out(1.5)"}},{_num(at(0.5 + i * 1.5))});'
        )
        
        if i > 0:
            lid = f"{node_id}-l{i}"
            # Line goes from bottom of previous node to top of this node
            ly = y_start + (i - 1) * spacing + 100
            html_lines.append(
                f'<div id="{lid}" class="flc-line" style="top:{ly}px;height:{spacing - 100}px;"><div id="{lid}-fill" class="flc-line-fill"></div></div>'
            )
            tweens.append(
                f'tl.fromTo("#{lid}-fill",{{scaleY:0}},{{scaleY:1,duration:{_num(dur(0.8))},ease:"power2.inOut"}},{_num(at(1.1 + (i-1) * 1.5))});'
            )

    tweens.append(f'tl.to("#{node_id}",{{opacity:0,duration:{_num(dur(0.6))},ease:"power2.inOut"}},{_num(at(11.4))});')

    html = f"""
    <div id="{node_id}" class="flc-overlay clip" {_timing(ctx)}>
      <div id="{node_id}-bg" class="flc-bg">
        {"".join(html_lines)}
        {"".join(html_nodes)}
      </div>
    </div>
    """
    return Piece(nodes=[html], tweens=tweens)

def flc_css() -> str:
    return (
        ".flc-overlay{position:absolute;inset:0;font-family:Inter,sans-serif}"
        ".flc-bg{position:absolute;inset:0;background:#0d1117}"
        ".flc-node{position:absolute;left:340px;width:400px;height:100px;background:#161b22;border:2px solid #30363d;border-radius:16px;display:flex;align-items:center;justify-content:center;color:#c9d1d9;font-size:36px;font-weight:600;box-shadow:0 12px 24px rgba(0,0,0,0.4);z-index:10}"
        ".flc-line{position:absolute;left:538px;width:4px;background:#21262d;z-index:5}"
        ".flc-line-fill{width:100%;height:100%;background:#58a6ff;transform-origin:50% 0}"
    )
