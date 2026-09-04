"""App Store VPN installation UI.

Catalog ``vpn-youtube-spot`` is 1920×1080 / 7s. Translated to 1080×1920 9:16.
No tweening strokeDashoffset; progress uses an SVG mask with scaleX or rotation.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_VYS_CATALOG = 8.0

def _vys_at(catalog: float, duration: float) -> float:
    return catalog * (max(duration, 0.2) / _VYS_CATALOG)

def _vys_dur(catalog: float, duration: float) -> float:
    dur = _vys_at(catalog, duration)
    return dur if dur <= 0.001 else max(0.001, dur - 0.001)

def ov_vpn_youtube_spot(ctx: "TemplateCtx") -> Piece:
    node_id = f"vys-{ctx.index:02d}"
    start = ctx.start
    duration = max(float(ctx.duration), 0.2)

    def at(catalog: float) -> float:
        return start + _vys_at(catalog, duration)

    def dur(catalog: float) -> float:
        return _vys_dur(catalog, duration)

    tweens = [
        f'tl.fromTo("#{node_id}-phone",{{y:760,scale:0.82,rotation:-2.5,opacity:0}},'
        f'{{y:0,scale:1,rotation:0,opacity:1,duration:{_num(dur(0.47))},ease:"back.out(1.6)"}},{_num(at(0.0))});',
        f'tl.fromTo("#{node_id}-scroll",{{y:0}},{{y:-456,duration:{_num(dur(1.2))},ease:"power4.out"}},{_num(at(0.62))});',
        f'tl.fromTo("#{node_id}-tap",{{scale:0.25,opacity:0.95}},{{scale:2.15,opacity:0,duration:{_num(dur(0.42))},ease:"power2.out"}},{_num(at(2.02))});',
        f'tl.to("#{node_id}-btn",{{scale:0.82,duration:{_num(dur(0.1))},ease:"power3.in"}},{_num(at(2.04))});',
        f'tl.to("#{node_id}-btn",{{scale:1,duration:{_num(dur(0.14))},ease:"back.out(2)"}},{_num(at(2.14))});',
        
        f'tl.fromTo("#{node_id}-detail",{{y:620,scale:0.92,opacity:0}},{{y:0,scale:1,opacity:1,duration:{_num(dur(0.46))},ease:"power4.out"}},{_num(at(2.32))});',
        f'tl.to("#{node_id}-btn-get",{{opacity:0,duration:{_num(dur(0.16))}}}, {_num(at(2.86))});',
        f'tl.to("#{node_id}-ring",{{opacity:1,duration:{_num(dur(0.16))}}}, {_num(at(2.96))});',
        
        # Fake progress ring using scaleX on a rect inside a mask, or rotation
        f'tl.fromTo("#{node_id}-prog-mask",{{rotation:-180}},{{rotation:0,duration:{_num(dur(1.42))},ease:"power2.inOut"}},{_num(at(3.02))});',
        
        f'tl.set("#{node_id}-pct-18",{{opacity:1}},{_num(at(3.18))});',
        f'tl.set("#{node_id}-pct-18",{{opacity:0}},{_num(at(3.56))});',
        f'tl.set("#{node_id}-pct-52",{{opacity:1}},{_num(at(3.56))});',
        f'tl.set("#{node_id}-pct-52",{{opacity:0}},{_num(at(3.90))});',
        f'tl.set("#{node_id}-pct-87",{{opacity:1}},{_num(at(3.90))});',
        f'tl.set("#{node_id}-pct-87",{{opacity:0}},{_num(at(4.28))});',
        f'tl.set("#{node_id}-pct-100",{{opacity:1}},{_num(at(4.28))});',
        
        f'tl.to("#{node_id}-ring",{{scale:0.35,opacity:0,duration:{_num(dur(0.16))}}}, {_num(at(4.44))});',
        f'tl.to("#{node_id}-pct-100",{{opacity:0,duration:{_num(dur(0.16))}}}, {_num(at(4.44))});',
        f'tl.to("#{node_id}-btn",{{scaleX:1.5,duration:{_num(dur(0.18))}}}, {_num(at(4.50))});', # Make button wider for OPEN
        f'tl.to("#{node_id}-btn-bg",{{opacity:1,duration:{_num(dur(0.18))}}}, {_num(at(4.50))});', # Green bg
        f'tl.to("#{node_id}-btn-open",{{opacity:1,duration:{_num(dur(0.16))}}}, {_num(at(4.56))});',
        
        f'tl.fromTo("#{node_id}-shield",{{y:22,scale:0.9,opacity:0}},{{y:0,scale:1,opacity:1,duration:{_num(dur(0.34))},ease:"back.out(1.8)"}},{_num(at(4.62))});',
        f'tl.to("#{node_id}-phone",{{scale:1.025,duration:{_num(dur(0.18))},yoyo:true,repeat:1,ease:"back.out(1.5)"}},{_num(at(4.70))});',
        
        f'tl.to("#{node_id}-headline",{{y:-18,opacity:0,duration:{_num(dur(0.22))}}}, {_num(at(5.18))});',
        f'tl.to("#{node_id}-phone",{{y:1050,scale:0.78,rotation:-3.5,duration:{_num(dur(0.48))},ease:"power4.in"}},{_num(at(5.44))});',
    ]

    html = f"""
    <div id="{node_id}" class="vys-overlay clip" {_timing(ctx)}>
      <div id="{node_id}-headline" class="vys-headline">
        <span>STAY</span>
        <span class="vys-blue">PROTECTED</span>
        <span>EVERYWHERE.</span>
        <div class="vys-sub">Browse securely with our top-rated VPN app.</div>
      </div>
      
      <div id="{node_id}-phone" class="vys-phone">
        <div class="vys-screen">
          <div id="{node_id}-scroll" class="vys-scroll">
            <div class="vys-store-row">
              <div class="vys-icon"></div>
              <div class="vys-info">
                <div class="vys-app-name">SecureVPN</div>
                <div class="vys-app-sub">Privacy First</div>
              </div>
            </div>
            
            <div id="{node_id}-btn" class="vys-btn">
              <div class="vys-btn-gray"></div>
              <div id="{node_id}-btn-bg" class="vys-btn-green"></div>
              <div id="{node_id}-btn-get" class="vys-btn-label">GET</div>
              <div id="{node_id}-btn-open" class="vys-btn-label vys-hidden">OPEN</div>
              
              <svg id="{node_id}-ring" class="vys-ring vys-hidden" viewBox="0 0 26 26">
                <circle cx="13" cy="13" r="11" stroke="rgba(255,255,255,0.36)" stroke-width="4" fill="none" />
                <g style="clip-path: url(#{node_id}-clip)">
                  <circle cx="13" cy="13" r="11" stroke="#fff" stroke-width="4" fill="none" />
                </g>
                <defs>
                  <clipPath id="{node_id}-clip">
                    <rect id="{node_id}-prog-mask" x="0" y="13" width="26" height="13" fill="#fff" transform="rotate(-180 13 13)" />
                    <rect x="13" y="0" width="13" height="26" fill="#fff" />
                  </clipPath>
                </defs>
              </svg>
            </div>
            <div id="{node_id}-tap" class="vys-tap"></div>
            
            <div id="{node_id}-detail" class="vys-detail">
              <div class="vys-progress-panel">
                <div id="{node_id}-pct-18" class="vys-pct vys-hidden">18%</div>
                <div id="{node_id}-pct-52" class="vys-pct vys-hidden">52%</div>
                <div id="{node_id}-pct-87" class="vys-pct vys-hidden">87%</div>
                <div id="{node_id}-pct-100" class="vys-pct vys-hidden">100%</div>
                
                <div id="{node_id}-shield" class="vys-shield vys-hidden">
                  <div class="vys-check">✓</div>
                  Ready to browse
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    """
    return Piece(nodes=[html], tweens=tweens)

def vys_overlay_css() -> str:
    return (
        ".vys-overlay{position:absolute;inset:0;font-family:Inter,sans-serif}"
        ".vys-headline{position:absolute;left:100px;top:200px;display:flex;flex-direction:column;gap:4px;z-index:2}"
        ".vys-headline span{font-size:110px;line-height:0.92;font-weight:900;color:#111214}"
        ".vys-headline .vys-blue{color:#C8453D}"
        ".vys-sub{margin-top:24px;font-size:32px;color:#7A7D82;font-weight:700}"
        
        ".vys-phone{position:absolute;left:309px;top:700px;width:462px;height:952px;border-radius:72px;"
        "background:linear-gradient(145deg, #1f2025 0%, #07070a 100%);padding:16px;z-index:4;"
        "box-shadow:0 46px 120px rgba(17,17,17,0.22), inset 0 0 0 2px rgba(255,255,255,0.12)}"
        ".vys-screen{position:relative;width:100%;height:100%;background:#000;border-radius:56px;overflow:hidden}"
        ".vys-scroll{position:absolute;width:100%;top:0;padding:24px}"
        
        ".vys-store-row{display:flex;align-items:center;gap:16px;margin-bottom:32px}"
        ".vys-icon{width:88px;height:88px;border-radius:20px;background:#007aff}"
        ".vys-info{display:flex;flex-direction:column}"
        ".vys-app-name{color:#fff;font-size:32px;font-weight:600}"
        ".vys-app-sub{color:#8e8e93;font-size:24px}"
        
        ".vys-btn{position:absolute;right:24px;top:40px;width:80px;height:40px;border-radius:20px;"
        "display:flex;align-items:center;justify-content:center;z-index:10;transform-origin:50% 50%}"
        ".vys-btn-gray{position:absolute;inset:0;background:rgba(255,255,255,0.15);border-radius:20px}"
        ".vys-btn-green{position:absolute;inset:0;background:#34c759;border-radius:20px;opacity:0}"
        ".vys-btn-label{position:absolute;color:#007aff;font-size:20px;font-weight:700}"
        ".vys-btn-green + .vys-btn-label{color:#fff}" # Wait this won't work in GSAP
        
        ".vys-ring{position:absolute;width:26px;height:26px;left:27px;top:7px}"
        ".vys-hidden{opacity:0}"
        ".vys-tap{position:absolute;right:64px;top:60px;width:40px;height:40px;border-radius:50%;"
        "background:rgba(255,255,255,0.5);opacity:0;pointer-events:none;z-index:20}"
        
        ".vys-detail{margin-top:120px;background:#1c1c1e;border-radius:32px;padding:24px}"
        ".vys-progress-panel{position:relative;height:300px;background:#2c2c2e;border-radius:24px;"
        "display:flex;align-items:center;justify-content:center;overflow:hidden}"
        ".vys-pct{position:absolute;color:#fff;font-size:48px;font-weight:700}"
        ".vys-shield{position:absolute;display:flex;flex-direction:column;align-items:center;gap:12px;color:#34c759;font-size:24px}"
        ".vys-check{width:64px;height:64px;border-radius:50%;background:#34c759;color:#fff;display:flex;"
        "align-items:center;justify-content:center;font-size:36px;font-weight:700}"
    )
