"""YouTube Lower-Third — YouTube channel profile lower-third with animated Subscribe button.

Catalog ``yt-lower-third`` animates a lower-third profile pill with avatar,
channel name, subscriber count, and YouTube dark button press-in with bounce to "Subscribed".
No tween of width/height/filter/clip-path/strokeDashoffset; no textContent writes.
Brandbook ink #111214, Inter font, 9:16 vertical lower-third.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_YLT_CATALOG = 4.5

_YLT_DEFAULTS = {
    "channelName": "HeyGen",
    "subscriberCount": "82.2K subscribers",
    "buttonText": "Subscribe",
    "subscribedText": "Subscribed",
}

_YLT_MAX = {
    "name": 32,
    "subs": 28,
    "btn": 20,
}


def _ylt_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _ylt_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = (
        "channelName",
        "subscriberCount",
        "displayName",
        "name",
        "title",
        "snippet",
        "domain",
        "followers",
        "subscribers",
    )
    return any(str(params.get(k) or "").strip() for k in keys)


def _ylt_copy(params: dict[str, Any]) -> dict[str, Any]:
    name = (
        params.get("channelName")
        or params.get("displayName")
        or params.get("name")
        or params.get("title")
        or _YLT_DEFAULTS["channelName"]
    )
    subs = (
        params.get("subscriberCount")
        or params.get("subscribers")
        or params.get("followers")
        or params.get("snippet")
        or _YLT_DEFAULTS["subscriberCount"]
    )
    btn = params.get("buttonText") or _YLT_DEFAULTS["buttonText"]
    subd = (
        params.get("subscribedText")
        or params.get("followingText")
        or _YLT_DEFAULTS["subscribedText"]
    )

    return {
        "channelName": _ylt_clip(name, _YLT_DEFAULTS["channelName"], _YLT_MAX["name"]),
        "subscriberCount": _ylt_clip(subs, _YLT_DEFAULTS["subscriberCount"], _YLT_MAX["subs"]),
        "buttonText": _ylt_clip(btn, _YLT_DEFAULTS["buttonText"], _YLT_MAX["btn"]),
        "subscribedText": _ylt_clip(subd, _YLT_DEFAULTS["subscribedText"], _YLT_MAX["btn"]),
    }


def ov_yt_lower_third(ctx: TemplateCtx) -> Piece:
    """YouTube Lower-Third: channel profile lower-third with animated Subscribe button."""
    if not _ylt_has_copy(ctx.params):
        return Piece()

    copy = _ylt_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 2.0)
    scale = duration / _YLT_CATALOG

    def dur(catalog_sec: float) -> float:
        return max(0.001, catalog_sec * scale)

    tweens: list[str] = []

    # Slide in from bottom
    t_in = start + dur(0.1)
    tweens.append(
        f'tl.fromTo("#{node_id}-card",{{opacity:0,y:280}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.5))},ease:"power3.out"}},'
        f'{_num(t_in)});'
    )

    # Button press-in
    t_press = start + dur(1.0)
    tweens.append(
        f'tl.to("#{node_id}-btn",{{scale:0.92,duration:{_num(dur(0.15))},ease:"power2.out"}},'
        f'{_num(t_press)});'
    )

    # Button release with spring bounce and background shift
    t_release = start + dur(1.15)
    tweens.append(
        f'tl.to("#{node_id}-btn",{{scale:1,duration:{_num(dur(0.38))},ease:"back.out(1.8)"}},'
        f'{_num(t_release)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-btn",{{backgroundColor:"#272727",duration:{_num(dur(0.12))},ease:"none"}},'
        f'{_num(t_release)});'
    )

    # Crossfade Subscribe -> Subscribed text
    tweens.append(
        f'tl.to("#{node_id}-btn-sub",{{opacity:0,duration:{_num(dur(0.08))},ease:"none"}},'
        f'{_num(t_release)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-btn-subd",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.08))},ease:"none"}},'
        f'{_num(t_release + dur(0.03))});'
    )

    # Slide out to bottom before clip end
    t_out = max(t_release + dur(0.6), start + duration - dur(0.35))
    tweens.append(
        f'tl.to("#{node_id}-card",{{opacity:0,y:280,duration:{_num(dur(0.3))},ease:"power3.in"}},'
        f'{_num(t_out)});'
    )

    node = (
        f'<div id="{node_id}" class="clip overlay yt-lower-third" {_timing(ctx)}>'
        f'<div id="{node_id}-card" class="ylt-card" style="opacity:0;transform:translateY(280px)">'
        f'<div class="ylt-avatar">'
        f'<svg width="110" height="110" viewBox="0 0 110 110">'
        f'<defs>'
        f'<linearGradient id="{node_id}-yt-grad" x1="0%" y1="0%" x2="100%" y2="100%">'
        f'<stop offset="0%" stop-color="#FF0000"/>'
        f'<stop offset="100%" stop-color="#CC0000"/>'
        f'</linearGradient>'
        f'</defs>'
        f'<circle cx="55" cy="55" r="53" fill="url(#{node_id}-yt-grad)"/>'
        f'<path d="M44 37 L76 55 L44 73 Z" fill="#ffffff"/>'
        f'</svg>'
        f'</div>'
        f'<div class="ylt-channel-info">'
        f'<div class="ylt-channel-name">{_esc(copy["channelName"])}</div>'
        f'<div class="ylt-subscribers">{_esc(copy["subscriberCount"])}</div>'
        f'</div>'
        f'<div id="{node_id}-btn" class="ylt-subscribe-btn">'
        f'<span id="{node_id}-btn-sub" class="ylt-btn-text ylt-btn-sub">{_esc(copy["buttonText"])}</span>'
        f'<span id="{node_id}-btn-subd" class="ylt-btn-text ylt-btn-subd" style="opacity:0">'
        f'<svg class="ylt-check" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">'
        f'<polyline points="20 6 9 17 4 12"/>'
        f'</svg>'
        f'<span>{_esc(copy["subscribedText"])}</span>'
        f'</span>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def ylt_overlay_css() -> str:
    """CSS for YouTube Lower-Third template."""
    return (
        ".yt-lower-third{position:absolute;inset:0;width:1080px;height:1920px;"
        "pointer-events:none;font-family:Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}"
        ".yt-lower-third .ylt-card{position:absolute;bottom:160px;left:50%;"
        "transform:translateX(-50%);display:flex;align-items:center;gap:24px;"
        "background:#ffffff;border-radius:75px;"
        "padding:20px 36px 20px 20px;box-shadow:0 16px 48px rgba(0,0,0,0.18);"
        "will-change:transform,opacity}"
        ".yt-lower-third .ylt-avatar{width:110px;height:110px;border-radius:50%;"
        "flex-shrink:0;overflow:hidden;display:flex;"
        "align-items:center;justify-content:center}"
        ".yt-lower-third .ylt-channel-info{display:flex;flex-direction:column;"
        "gap:3px;margin-right:16px}"
        ".yt-lower-third .ylt-channel-name{font-size:38px;font-weight:700;color:#0f0f0f;"
        "line-height:1.2;letter-spacing:-0.01em}"
        ".yt-lower-third .ylt-subscribers{font-size:25px;font-weight:400;color:#606060;line-height:1.2}"
        ".yt-lower-third .ylt-subscribe-btn{position:relative;width:240px;height:76px;border-radius:38px;"
        "background:#0f0f0f;flex-shrink:0;display:flex;align-items:center;justify-content:center;"
        "overflow:hidden;will-change:transform,background-color}"
        ".yt-lower-third .ylt-btn-text{position:absolute;font-size:28px;font-weight:700;"
        "color:#ffffff;letter-spacing:0.02em;white-space:nowrap;display:flex;align-items:center;"
        "gap:8px;will-change:opacity}"
        ".yt-lower-third .ylt-check{display:inline-block;width:22px;height:22px}"
    )
