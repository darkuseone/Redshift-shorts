"""US Map with Bubbles.

Catalog ``us-map-bubble`` is 1920×1080 / 12s. Translated to 1080×1920 9:16.
Uses GSAP scale/opacity for bubbles.
"""

from __future__ import annotations

from typing import Any
import math

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_UMB_CATALOG = 12.0

def _umb_at(catalog: float, duration: float) -> float:
    return catalog * (max(duration, 0.4) / _UMB_CATALOG)

def _umb_dur(catalog: float, duration: float) -> float:
    dur = _umb_at(catalog, duration)
    return dur if dur <= 0.001 else max(0.001, dur - 0.001)

def dv_us_map_bubble(ctx: "TemplateCtx") -> Piece:
    node_id = f"umb-{ctx.index:02d}"
    start = ctx.start
    duration = max(float(ctx.duration), 0.4)

    def at(catalog: float) -> float:
        return start + _umb_at(catalog, duration)

    def dur(catalog: float) -> float:
        return _umb_dur(catalog, duration)
        
    title = str(ctx.params.get("title", "Major Tech Hubs"))
    subtitle = str(ctx.params.get("subtitle", "Tech employment by city, 2024"))

    # Some arbitrary cities for bubbles (x, y coords mapping to US map)
    # Using 1080x1920 scale
    cities = [
        {"name": "San Francisco", "x": 180, "y": 700, "r": 60, "delay": 0.5},
        {"name": "New York", "x": 860, "y": 620, "r": 50, "delay": 0.7},
        {"name": "Austin", "x": 520, "y": 950, "r": 40, "delay": 0.9},
        {"name": "Seattle", "x": 160, "y": 500, "r": 35, "delay": 1.1},
        {"name": "Chicago", "x": 650, "y": 650, "r": 30, "delay": 1.3},
    ]

    tweens = [
        # Map fade in
        f'tl.fromTo("#{node_id}-map",{{opacity:0,scale:0.95}},{{opacity:1,scale:1,duration:{_num(dur(0.8))},ease:"power2.out"}},{_num(at(0.0))});',
        # Text slide in
        f'tl.fromTo("#{node_id}-title",{{y:30,opacity:0}},{{y:0,opacity:1,duration:{_num(dur(0.6))},ease:"back.out(1.4)"}},{_num(at(0.3))});',
        f'tl.fromTo("#{node_id}-sub",{{y:20,opacity:0}},{{y:0,opacity:1,duration:{_num(dur(0.6))},ease:"back.out(1.4)"}},{_num(at(0.4))});',
    ]
    
    bubbles_html = []
    for i, city in enumerate(cities):
        bid = f"{node_id}-b{i}"
        r = city["r"]
        x = city["x"] - r
        y = city["y"] - r
        bubbles_html.append(
            f'<div id="{bid}" class="umb-bubble" style="left:{x}px;top:{y}px;width:{r*2}px;height:{r*2}px;"></div>'
        )
        tweens.append(
            f'tl.fromTo("#{bid}",{{scale:0,opacity:0}},{{scale:1,opacity:0.8,duration:{_num(dur(0.6))},ease:"back.out(1.5)"}},{_num(at(city["delay"]))});'
        )
        # Pulse effect
        tweens.append(
            f'tl.to("#{bid}",{{scale:1.1,opacity:0.6,duration:{_num(dur(2.0))},yoyo:true,repeat:-1,ease:"sine.inOut"}},{_num(at(city["delay"] + 0.6))});'
        )

    # Fade out
    tweens.append(f'tl.to("#{node_id}",{{opacity:0,duration:{_num(dur(0.6))},ease:"power2.inOut"}},{_num(at(11.4))});')

    html = f"""
    <div id="{node_id}" class="umb-overlay clip" {_timing(ctx)}>
      <div id="{node_id}-map" class="umb-map"></div>
      {"".join(bubbles_html)}
      <div class="umb-header">
        <div id="{node_id}-title" class="umb-title">{_esc(title)}</div>
        <div id="{node_id}-sub" class="umb-sub">{_esc(subtitle)}</div>
      </div>
    </div>
    """
    return Piece(nodes=[html], tweens=tweens)

def umb_css() -> str:
    return (
        ".umb-overlay{position:absolute;inset:0;font-family:Inter,sans-serif;background:#111214}"
        ".umb-map{position:absolute;left:50px;top:400px;width:980px;height:700px;background:rgba(255,255,255,0.08);border-radius:40px;mask-image:url('assets/us-map-mask.svg');-webkit-mask-image:url('assets/us-map-mask.svg');mask-size:contain;mask-repeat:no-repeat}"
        ".umb-bubble{position:absolute;background:radial-gradient(circle at 30% 30%, #E4726A, #C8453D);border-radius:50%;box-shadow:0 0 20px rgba(200,69,61,0.5);mix-blend-mode:screen}"
        ".umb-header{position:absolute;left:80px;top:150px;width:920px;display:flex;flex-direction:column;gap:16px;z-index:10}"
        ".umb-title{color:#ffffff;font-size:72px;font-weight:800;letter-spacing:-0.02em}"
        ".umb-sub{color:#7A7D82;font-size:36px;font-weight:500}"
    )
