"""AI generates an intro video with avatar.

Catalog ``blue-sweater-intro-video`` is 1920×1080 / 12s. Translated to 1080×1920 9:16.
Uses GSAP staggered opacity for typing, scale/opacity for loading/generating.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_BS_CATALOG = 12.0

def _bs_at(catalog: float, duration: float) -> float:
    return catalog * (max(duration, 0.4) / _BS_CATALOG)

def _bs_dur(catalog: float, duration: float) -> float:
    dur = _bs_at(catalog, duration)
    return dur if dur <= 0.001 else max(0.001, dur - 0.001)

def ov_blue_sweater(ctx: "TemplateCtx") -> Piece:
    node_id = f"bs-{ctx.index:02d}"
    start = ctx.start
    duration = max(float(ctx.duration), 0.4)

    def at(catalog: float) -> float:
        return start + _bs_at(catalog, duration)

    def dur(catalog: float) -> float:
        return _bs_dur(catalog, duration)

    prompt = "A man in a blue sweater introduces a video..."
    spans = "".join(f'<span>{c}</span>' if c != " " else '<span>&nbsp;</span>' for c in prompt)

    tweens = [
        # Initial pop-in
        f'tl.fromTo("#{node_id}-panel",{{y:200,scale:0.9,opacity:0}},{{y:0,scale:1,opacity:1,duration:{_num(dur(0.6))},ease:"back.out(1.4)"}},{_num(at(0.0))});',
        
        # Cursor moves to input box
        f'tl.fromTo("#{node_id}-cursor",{{x:500,y:800,opacity:0}},{{x:200,y:400,opacity:1,duration:{_num(dur(0.8))},ease:"power3.out"}},{_num(at(0.2))});',
        
        # Type the text (stagger opacity on spans)
        f'tl.fromTo("#{node_id}-prompt span",{{opacity:0}},{{opacity:1,stagger:{_num(dur(0.05))},duration:{_num(dur(0.1))},ease:"none"}},{_num(at(1.0))});',
        
        # Cursor clicks generate
        f'tl.to("#{node_id}-cursor",{{x:800,y:600,duration:{_num(dur(0.6))},ease:"power2.inOut"}},{_num(at(3.5))});',
        f'tl.to("#{node_id}-cursor",{{scale:0.8,duration:{_num(dur(0.1))},yoyo:true,repeat:1}},{_num(at(4.1))});',
        
        # Transition to generating state
        f'tl.to("#{node_id}-panel",{{scale:0.95,opacity:0,duration:{_num(dur(0.3))},ease:"power2.in"}},{_num(at(4.3))});',
        f'tl.fromTo("#{node_id}-generating",{{scale:1.05,opacity:0}},{{scale:1,opacity:1,duration:{_num(dur(0.4))},ease:"power2.out"}},{_num(at(4.6))});',
        
        # Loading bar fills (scaleX)
        f'tl.fromTo("#{node_id}-load-fill",{{scaleX:0}},{{scaleX:1,duration:{_num(dur(3.0))},ease:"power1.inOut"}},{_num(at(5.0))});',
        
        # Finish generating, show result
        f'tl.to("#{node_id}-generating",{{scale:0.95,opacity:0,duration:{_num(dur(0.3))},ease:"power2.in"}},{_num(at(8.2))});',
        f'tl.fromTo("#{node_id}-result",{{scale:0.8,opacity:0}},{{scale:1,opacity:1,duration:{_num(dur(0.6))},ease:"back.out(1.2)"}},{_num(at(8.5))});',
        
        # Final fade out
        f'tl.to("#{node_id}-result",{{scale:1.1,opacity:0,duration:{_num(dur(0.5))},ease:"power3.in"}},{_num(at(11.5))});',
    ]

    html = f"""
    <div id="{node_id}" class="bs-overlay clip" {_timing(ctx)}>
      <!-- Input Panel -->
      <div id="{node_id}-panel" class="bs-panel">
        <div class="bs-header">Generate Video</div>
        <div id="{node_id}-prompt" class="bs-prompt">{spans}</div>
        <div class="bs-btn">GENERATE</div>
      </div>
      
      <!-- Generating Panel -->
      <div id="{node_id}-generating" class="bs-panel bs-generating">
        <div class="bs-spinner"></div>
        <div class="bs-loading-text">Generating Avatar...</div>
        <div class="bs-load-bar"><div id="{node_id}-load-fill" class="bs-load-fill"></div></div>
      </div>
      
      <!-- Result Panel -->
      <div id="{node_id}-result" class="bs-result">
        <div class="bs-avatar-img"></div>
        <div class="bs-play-btn">▶</div>
      </div>
      
      <!-- Cursor -->
      <svg id="{node_id}-cursor" class="bs-cursor" width="48" height="48" viewBox="0 0 24 24">
        <path d="M7 2l12 11.2-5.8.5 3.3 7.3-2.2 1-3.2-7.4-4.4 4.8z" fill="#ffffff" stroke="#111214" stroke-width="1.5"/>
      </svg>
    </div>
    """
    return Piece(nodes=[html], tweens=tweens)

def bs_overlay_css() -> str:
    return (
        ".bs-overlay{position:absolute;inset:0;font-family:Inter,sans-serif;background:rgba(10,10,12,0.78)}"
        ".bs-panel{position:absolute;left:140px;top:700px;width:800px;background:#111214;border-radius:24px;padding:40px;box-shadow:0 24px 48px rgba(0,0,0,0.5);border:1px solid #7A7D82}"
        ".bs-header{color:#ffffff;font-size:36px;font-weight:600;margin-bottom:24px}"
        ".bs-prompt{color:#F7F5F3;font-size:42px;line-height:1.4;background:#111214;border:1px solid #7A7D82;padding:24px;border-radius:16px;min-height:160px;display:flex;flex-wrap:wrap}"
        ".bs-btn{margin-top:32px;background:#C8453D;color:#ffffff;font-size:28px;font-weight:600;padding:20px 40px;border-radius:16px;text-align:center;width:fit-content;float:right}"
        
        ".bs-generating{display:flex;flex-direction:column;align-items:center;padding:80px 40px}"
        ".bs-spinner{width:80px;height:80px;border:8px solid #7A7D82;border-top-color:#C8453D;border-radius:50%;animation:bs-spin 1s linear infinite}"
        "@keyframes bs-spin{to{transform:rotate(360deg)}}"
        ".bs-loading-text{color:#ffffff;font-size:32px;margin-top:32px;margin-bottom:32px}"
        ".bs-load-bar{width:100%;height:16px;background:rgba(122,125,130,0.25);border-radius:8px;overflow:hidden}"
        ".bs-load-fill{width:100%;height:100%;background:#C8453D;transform-origin:0 50%}"
        
        ".bs-result{position:absolute;left:140px;top:400px;width:800px;height:1000px;background:#111214;border-radius:32px;overflow:hidden;box-shadow:0 32px 64px rgba(0,0,0,0.6);border:2px solid #7A7D82;display:flex;align-items:center;justify-content:center}"
        ".bs-avatar-img{position:absolute;inset:0;background:url('assets/joe-sai-avatar.png') center/cover}"
        ".bs-play-btn{width:120px;height:120px;background:rgba(255,255,255,0.2);backdrop-filter:blur(10px);border-radius:50%;display:flex;align-items:center;justify-content:center;color:#ffffff;font-size:48px;padding-left:8px;z-index:2}"
        
        ".bs-cursor{position:absolute;z-index:100}"
    )
