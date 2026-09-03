"""Data-viz templates: oscilloscope-trace and weight-wave.

Catalog translated to 1080×1920 9:16.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

def _osc_dur(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)

def dv_oscilloscope_trace(ctx: "TemplateCtx") -> Piece:
    node_id = f"osc-{ctx.index:02d}"
    start = ctx.start
    duration = max(float(ctx.duration), 0.4)
    
    tweens = [
        f'tl.fromTo("#{node_id}",{{opacity:0}},{{opacity:1,duration:0.4}},{_num(start)});',
        f'tl.to("#{node_id}",{{opacity:0,duration:0.4}},{_num(start + duration - 0.4)});',
        f'tl.fromTo("#{node_id}-wave",{{scaleX:0}},{{scaleX:1,duration:{_num(duration)},ease:"none"}},{_num(start)});'
    ]

    html = f"""
    <div id="{node_id}" class="osc-overlay clip" {_timing(ctx)}>
      <div class="osc-bg">
        <svg class="osc-svg" viewBox="0 0 1080 600" preserveAspectRatio="none">
          <path id="{node_id}-wave" class="osc-path" d="M0,300 Q100,100 200,300 T400,300 T600,300 T800,300 T1000,300" />
        </svg>
      </div>
    </div>
    """
    return Piece(nodes=[html], tweens=tweens)

def dv_weight_wave(ctx: "TemplateCtx") -> Piece:
    node_id = f"wwv-{ctx.index:02d}"
    start = ctx.start
    duration = max(float(ctx.duration), 0.4)
    
    tweens = [
        f'tl.fromTo("#{node_id}",{{opacity:0}},{{opacity:1,duration:0.4}},{_num(start)});',
        f'tl.to("#{node_id}",{{opacity:0,duration:0.4}},{_num(start + duration - 0.4)});',
        f'tl.fromTo("#{node_id}-wave",{{scaleY:0.2}},{{scaleY:1,duration:{_num(duration)},ease:"sine.inOut",yoyo:true,repeat:-1}},{_num(start)});'
    ]

    html = f"""
    <div id="{node_id}" class="wwv-overlay clip" {_timing(ctx)}>
      <div class="wwv-bg">
        <svg class="wwv-svg" viewBox="0 0 1080 600" preserveAspectRatio="none">
          <path id="{node_id}-wave" class="wwv-path" d="M0,500 C200,500 300,100 540,100 C780,100 880,500 1080,500" />
        </svg>
      </div>
    </div>
    """
    return Piece(nodes=[html], tweens=tweens)

def wv_css() -> str:
    return (
        ".osc-overlay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,20,0,0.8)}"
        ".osc-bg{width:1080px;height:600px;background:linear-gradient(0deg, transparent 49%, rgba(0,255,0,0.2) 50%, transparent 51%), linear-gradient(90deg, transparent 49%, rgba(0,255,0,0.2) 50%, transparent 51%);background-size:40px 40px}"
        ".osc-svg{width:100%;height:100%}"
        ".osc-path{fill:none;stroke:#0f0;stroke-width:6;transform-origin:0 50%;filter:drop-shadow(0 0 10px #0f0)}"
        ".wwv-overlay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:#111214}"
        ".wwv-bg{width:1080px;height:600px}"
        ".wwv-svg{width:100%;height:100%}"
        ".wwv-path{fill:none;stroke:#c8453d;stroke-width:12;transform-origin:50% 100%}"
    )
