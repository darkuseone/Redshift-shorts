"""Notification Cascade — cascading iOS/mobile notification banners and closing card.

Catalog ``notification-cascade`` stacks 4 incoming alert banners with
dynamic upward restacking, top "Show less" pill, and transition into
a closing brand end-card.
No tween of width/height/filter/clip-path/strokeDashoffset; no textContent writes.
Brandbook ink #111214, accent #C8453D / #E4726A, Inter font.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_NC_CATALOG = 14.0

_NC_DEFAULTS = {
    "notifTitle": "New render",
    "message1": "Launch video is ready.",
    "message2": "All checks passed.",
    "message3": "4K render done in 92s.",
    "message4": "Published to the catalog.",
    "appName": "HyperFrames",
    "headlineTop": "SHIP VIDEO",
    "headlineAccent": "FROM HTML",
    "footerText": "hyperframes.heygen.com",
}

_NC_MAX = {
    "title": 60,
    "message": 80,
    "app": 32,
    "headline": 40,
    "footer": 50,
}


def _nc_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _nc_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = (
        "notifTitle", "message1", "message2", "message3", "message4",
        "appName", "headlineTop", "headlineAccent", "footerText",
        "title", "snippet", "prompt", "domain",
    )
    return any(str(params.get(k) or "").strip() for k in keys)


def _nc_copy(params: dict[str, Any]) -> dict[str, Any]:
    title = params.get("notifTitle") or params.get("title") or _NC_DEFAULTS["notifTitle"]
    m1 = params.get("message1") or params.get("snippet") or _NC_DEFAULTS["message1"]
    m2 = params.get("message2") or _NC_DEFAULTS["message2"]
    m3 = params.get("message3") or _NC_DEFAULTS["message3"]
    m4 = params.get("message4") or _NC_DEFAULTS["message4"]
    app = params.get("appName") or params.get("domain") or _NC_DEFAULTS["appName"]
    top = params.get("headlineTop") or _NC_DEFAULTS["headlineTop"]
    accent = params.get("headlineAccent") or _NC_DEFAULTS["headlineAccent"]
    footer = params.get("footerText") or params.get("domain") or _NC_DEFAULTS["footerText"]
    return {
        "notifTitle": _nc_clip(title, _NC_DEFAULTS["notifTitle"], _NC_MAX["title"]),
        "message1": _nc_clip(m1, _NC_DEFAULTS["message1"], _NC_MAX["message"]),
        "message2": _nc_clip(m2, _NC_DEFAULTS["message2"], _NC_MAX["message"]),
        "message3": _nc_clip(m3, _NC_DEFAULTS["message3"], _NC_MAX["message"]),
        "message4": _nc_clip(m4, _NC_DEFAULTS["message4"], _NC_MAX["message"]),
        "appName": _nc_clip(app, _NC_DEFAULTS["appName"], _NC_MAX["app"]),
        "headlineTop": _nc_clip(top, _NC_DEFAULTS["headlineTop"], _NC_MAX["headline"]),
        "headlineAccent": _nc_clip(accent, _NC_DEFAULTS["headlineAccent"], _NC_MAX["headline"]),
        "footerText": _nc_clip(footer, _NC_DEFAULTS["footerText"], _NC_MAX["footer"]),
    }


def ov_notification_cascade(ctx: TemplateCtx) -> Piece:
    """Notification Cascade: cascading iOS alert banners and closing card."""
    if not _nc_has_copy(ctx.params):
        return Piece()

    copy = _nc_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 3.0)
    scale = duration / _NC_CATALOG

    def dur(catalog_sec: float) -> float:
        return max(0.001, catalog_sec * scale)

    tweens: list[str] = []

    # Timing constants from measured catalog reference
    pitch = 214
    entry_times = [1.6, 3.6, 5.6, 7.6]
    exit_time = 9.2
    endcard_time = 9.9

    # Backdrop push-in
    tweens.append(
        f'tl.fromTo("#{node_id}-bg",{{scale:1.0}},'
        f'{{scale:1.08,duration:{_num(dur(13.4))},ease:"none"}},'
        f'{_num(start + dur(0.2))});'
    )

    # Initial states for banners and pill
    tweens.append(
        f'tl.set("#{node_id}-pill-row",{{opacity:0}},{_num(start + 0.001)});'
    )
    for i in range(1, 5):
        tweens.append(
            f'tl.set("#{node_id}-banner-{i}",{{opacity:0}},{_num(start + 0.001)});'
        )
    tweens.append(
        f'tl.set("#{node_id}-endcard",{{opacity:0}},{_num(start + 0.001)});'
    )

    # Banner 1 + Pill entry
    t0 = start + dur(entry_times[0])
    tweens.append(
        f'tl.fromTo("#{node_id}-banner-1",{{opacity:0,y:24}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.5))},ease:"power3.out"}},'
        f'{_num(t0)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-pill-row",{{opacity:0,y:16}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.4))},ease:"power3.out"}},'
        f'{_num(t0)});'
    )

    # Banner 2 entry + restack 1
    t1 = start + dur(entry_times[1])
    tweens.append(
        f'tl.to("#{node_id}-banner-1",{{y:{-pitch},duration:{_num(dur(0.85))},ease:"power3.out"}},'
        f'{_num(t1)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-pill-row",{{y:{-pitch},duration:{_num(dur(0.85))},ease:"power3.out"}},'
        f'{_num(t1)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-banner-2",{{opacity:0,y:24}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.5))},ease:"power3.out"}},'
        f'{_num(t1)});'
    )

    # Banner 3 entry + restack 2
    t2 = start + dur(entry_times[2])
    tweens.append(
        f'tl.to("#{node_id}-banner-1",{{y:{-2 * pitch},duration:{_num(dur(0.85))},ease:"power3.out"}},'
        f'{_num(t2)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-pill-row",{{y:{-2 * pitch},duration:{_num(dur(0.85))},ease:"power3.out"}},'
        f'{_num(t2)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-banner-2",{{y:{-pitch},duration:{_num(dur(0.85))},ease:"power3.out"}},'
        f'{_num(t2)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-banner-3",{{opacity:0,y:24}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.5))},ease:"power3.out"}},'
        f'{_num(t2)});'
    )

    # Banner 4 entry + restack 3
    t3 = start + dur(entry_times[3])
    tweens.append(
        f'tl.to("#{node_id}-banner-1",{{y:{-3 * pitch},duration:{_num(dur(0.85))},ease:"power3.out"}},'
        f'{_num(t3)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-pill-row",{{y:{-3 * pitch},duration:{_num(dur(0.85))},ease:"power3.out"}},'
        f'{_num(t3)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-banner-2",{{y:{-2 * pitch},duration:{_num(dur(0.85))},ease:"power3.out"}},'
        f'{_num(t3)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-banner-3",{{y:{-pitch},duration:{_num(dur(0.85))},ease:"power3.out"}},'
        f'{_num(t3)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-banner-4",{{opacity:0,y:24}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.5))},ease:"power3.out"}},'
        f'{_num(t3)});'
    )

    # Group exit
    t_ex = start + dur(exit_time)
    tweens.append(
        f'tl.to("#{node_id}-stack-inner",{{y:-560,opacity:0,duration:{_num(dur(0.48))},ease:"power3.in"}},'
        f'{_num(t_ex)});'
    )

    # Endcard entrance
    t_ec = start + dur(endcard_time)
    tweens.append(
        f'tl.fromTo("#{node_id}-endcard",{{opacity:0,scale:0.96}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.55))},ease:"power2.out"}},'
        f'{_num(t_ec)});'
    )

    messages = [
        copy["message1"],
        copy["message2"],
        copy["message3"],
        copy["message4"],
    ]

    banners_html = []
    for i, msg in enumerate(messages, start=1):
        banners_html.append(
            f'<div class="nc-banner" id="{node_id}-banner-{i}" style="top:1260px">'
            f'<div class="nc-icon">'
            f'<svg width="56" height="56" viewBox="0 0 24 24" fill="none">'
            f'<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="M13.73 21a2 2 0 0 1-3.46 0" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
            f'</svg>'
            f'</div>'
            f'<div class="nc-title">{_esc(copy["notifTitle"])}</div>'
            f'<div class="nc-subtitle">{_esc(msg)}</div>'
            f'<div class="nc-now">NOW</div>'
            f'<div class="nc-credit">{_esc(copy["appName"])}</div>'
            f'</div>'
        )

    node = (
        f'<div id="{node_id}" class="clip overlay notification-cascade" {_timing(ctx)}>'
        f'<div id="{node_id}-bg" class="nc-backdrop"></div>'
        f'<div class="nc-vignette"></div>'
        f'<div id="{node_id}-stack-inner" class="nc-stack-inner">'
        f'<div id="{node_id}-pill-row" class="nc-pill-row">'
        f'<div class="nc-pill">'
        f'<svg width="24" height="24" viewBox="0 0 24 24" fill="none">'
        f'<path d="M6 9l6 6 6-6" stroke="#7A7D82" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
        f'<span>Show less</span>'
        f'</div>'
        f'<div class="nc-pill-x">'
        f'<svg width="24" height="24" viewBox="0 0 24 24" fill="none">'
        f'<path d="M6 6l12 12M18 6L6 18" stroke="#7A7D82" stroke-width="3" stroke-linecap="round"/>'
        f'</svg>'
        f'</div>'
        f'</div>'
        f'{" ".join(banners_html)}'
        f'</div>'
        f'<div id="{node_id}-endcard" class="nc-endcard" style="opacity:0">'
        f'<div class="nc-endcard-scrim"></div>'
        f'<div class="nc-endcard-inner">'
        f'<div class="nc-ec-top">{_esc(copy["headlineTop"])}</div>'
        f'<div class="nc-ec-accent">{_esc(copy["headlineAccent"])}</div>'
        f'<div class="nc-ec-mark">'
        f'<svg width="120" height="120" viewBox="0 0 100 100" fill="none">'
        f'<rect x="10" y="10" width="80" height="80" rx="24" fill="#C8453D"/>'
        f'<path d="M36 30l36 20-36 20V30z" fill="#fff"/>'
        f'</svg>'
        f'</div>'
        f'<div class="nc-ec-footer">{_esc(copy["footerText"])}</div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def nc_overlay_css() -> str:
    """CSS for Notification Cascade template."""
    return (
        ".notification-cascade{position:absolute;inset:0;width:1080px;height:1920px;"
        "overflow:hidden;background:#111214;font-family:Inter,system-ui,sans-serif;"
        "-webkit-font-smoothing:antialiased;color:#111214}"
        ".notification-cascade .nc-backdrop{position:absolute;inset:-40px;"
        "background:radial-gradient(circle at 50% 38%,#111214 0%,#0a0a0c 100%);"
        "will-change:transform}"
        ".notification-cascade .nc-vignette{position:absolute;inset:0;"
        "background:radial-gradient(ellipse 120% 90% at 50% 42%,transparent 55%,rgba(20,10,5,0.45) 100%)}"
        ".notification-cascade .nc-stack-inner{position:absolute;inset:0;will-change:transform,opacity}"
        ".notification-cascade .nc-pill-row{position:absolute;left:0;top:1164px;width:1080px;height:72px;"
        "display:flex;justify-content:flex-end;padding-right:135px;gap:18px;will-change:transform,opacity}"
        ".notification-cascade .nc-pill{height:72px;border-radius:36px;background:rgba(247,245,243,0.92);"
        "display:flex;align-items:center;padding:0 24px;gap:10px;font-size:27px;font-weight:600;"
        "color:#111214;box-shadow:0 8px 24px rgba(30,15,5,0.18);backdrop-filter:blur(16px)}"
        ".notification-cascade .nc-pill-x{width:72px;height:72px;border-radius:36px;"
        "background:rgba(247,245,243,0.92);display:flex;align-items:center;justify-content:center;"
        "box-shadow:0 8px 24px rgba(30,15,5,0.18);backdrop-filter:blur(16px)}"
        ".notification-cascade .nc-banner{position:absolute;left:135px;width:810px;height:176px;"
        "border-radius:26px;background:rgba(247,245,243,0.95);box-shadow:0 14px 32px rgba(25,12,4,0.22);"
        "border:1px solid rgba(255,255,255,0.45);will-change:transform,opacity}"
        ".notification-cascade .nc-icon{position:absolute;left:23px;top:38px;width:100px;height:100px;"
        "border-radius:24px;background:linear-gradient(135deg,#C8453D 0%,#E4726A 100%);"
        "display:flex;align-items:center;justify-content:center;box-shadow:0 6px 16px rgba(200,69,61,0.3)}"
        ".notification-cascade .nc-title{position:absolute;left:148px;top:38px;font-size:35px;"
        "font-weight:700;color:#111214;letter-spacing:0.25px}"
        ".notification-cascade .nc-subtitle{position:absolute;left:148px;top:88px;font-size:32px;"
        "font-weight:400;color:#7A7D82;letter-spacing:-0.5px;max-width:630px;white-space:nowrap;"
        "overflow:hidden;text-overflow:ellipsis}"
        ".notification-cascade .nc-now{position:absolute;right:26px;top:32px;font-size:22px;"
        "font-weight:600;color:#7A7D82;letter-spacing:1px}"
        ".notification-cascade .nc-credit{position:absolute;right:26px;bottom:14px;font-size:24px;"
        "font-style:italic;color:#7A7D82}"
        ".notification-cascade .nc-endcard{position:absolute;inset:0;z-index:10;will-change:transform,opacity}"
        ".notification-cascade .nc-endcard-scrim{position:absolute;inset:0;"
        "background:#111214}"
        ".notification-cascade .nc-endcard-inner{position:absolute;inset:0;display:flex;"
        "flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:0 60px}"
        ".notification-cascade .nc-ec-top{font-size:86px;font-weight:900;letter-spacing:3px;"
        "color:#F7F5F3;margin-bottom:12px;text-transform:uppercase}"
        ".notification-cascade .nc-ec-accent{font-size:72px;font-weight:900;letter-spacing:2px;"
        "color:#C8453D;margin-bottom:44px;text-transform:uppercase}"
        ".notification-cascade .nc-ec-mark{margin-bottom:48px}"
        ".notification-cascade .nc-ec-footer{font-size:36px;font-weight:700;color:#E4726A;letter-spacing:1px}"
    )
