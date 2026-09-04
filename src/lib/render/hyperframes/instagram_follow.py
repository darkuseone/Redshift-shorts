"""Instagram Follow — Instagram profile lower-third with animated Follow / Following button.

Catalog ``instagram-follow`` animates lower-third profile pill with avatar,
verified badge, follower count, and button press-in with bounce to "Following".
No tween of width/height/filter/clip-path/strokeDashoffset; no textContent writes.
Brandbook ink #111214, Inter font, 9:16 vertical lower-third.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_IF_CATALOG = 4.5

_IF_DEFAULTS = {
    "displayName": "HeyGen",
    "handle": "@heygen_official",
    "followers": "47.5K followers",
    "buttonText": "Follow",
    "followingText": "Following",
}

_IF_MAX = {
    "name": 32,
    "handle": 32,
    "followers": 24,
    "btn": 20,
}


def _if_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _if_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = ("displayName", "handle", "followers", "title", "snippet", "domain", "name", "text")
    return any(str(params.get(k) or "").strip() for k in keys)


def _if_copy(params: dict[str, Any]) -> dict[str, Any]:
    name = (
        params.get("displayName")
        or params.get("name")
        or params.get("title")
        or _IF_DEFAULTS["displayName"]
    )
    raw_handle = params.get("handle") or params.get("domain") or _IF_DEFAULTS["handle"]
    handle_str = str(raw_handle).strip()
    if handle_str and not handle_str.startswith("@"):
        handle_str = f"@{handle_str}"

    return {
        "displayName": _if_clip(name, _IF_DEFAULTS["displayName"], _IF_MAX["name"]),
        "handle": _if_clip(handle_str, _IF_DEFAULTS["handle"], _IF_MAX["handle"]),
        "followers": _if_clip(params.get("followers"), _IF_DEFAULTS["followers"], _IF_MAX["followers"]),
        "buttonText": _if_clip(params.get("buttonText"), _IF_DEFAULTS["buttonText"], _IF_MAX["btn"]),
        "followingText": _if_clip(params.get("followingText"), _IF_DEFAULTS["followingText"], _IF_MAX["btn"]),
    }


def ov_instagram_follow(ctx: TemplateCtx) -> Piece:
    """Instagram Follow: profile lower-third with animated Follow button."""
    if not _if_has_copy(ctx.params):
        return Piece()

    copy = _if_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 2.0)
    scale = duration / _IF_CATALOG

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

    # Button release with spring bounce and color switch
    t_release = start + dur(1.15)
    tweens.append(
        f'tl.to("#{node_id}-btn",{{scale:1,duration:{_num(dur(0.38))},ease:"back.out(1.8)"}},'
        f'{_num(t_release)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-btn",{{backgroundColor:"#2f2f2f",duration:{_num(dur(0.12))},ease:"none"}},'
        f'{_num(t_release)});'
    )

    # Crossfade Follow -> Following text
    tweens.append(
        f'tl.to("#{node_id}-btn-follow",{{opacity:0,duration:{_num(dur(0.08))},ease:"none"}},'
        f'{_num(t_release)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-btn-following",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.08))},ease:"none"}},'
        f'{_num(t_release + dur(0.03))});'
    )

    # Slide out to bottom before clip end
    t_out = max(t_release + dur(0.6), start + duration - dur(0.35))
    tweens.append(
        f'tl.to("#{node_id}-card",{{opacity:0,y:280,duration:{_num(dur(0.3))},ease:"power3.in"}},'
        f'{_num(t_out)});'
    )

    initial_char = _esc(copy["displayName"][:1].upper() if copy["displayName"] else "R")

    node = (
        f'<div id="{node_id}" class="clip overlay instagram-follow" {_timing(ctx)}>'
        f'<div id="{node_id}-card" class="if-card" style="opacity:0">'
        f'<div class="if-avatar">'
        f'<svg width="120" height="120" viewBox="0 0 120 120">'
        f'<defs>'
        f'<linearGradient id="{node_id}-av-grad" x1="0%" y1="0%" x2="100%" y2="100%">'
        f'<stop offset="0%" stop-color="#C8453D"/>'
        f'<stop offset="50%" stop-color="#E4726A"/>'
        f'<stop offset="100%" stop-color="#f59e0b"/>'
        f'</linearGradient>'
        f'</defs>'
        f'<circle cx="60" cy="60" r="58" fill="url(#{node_id}-av-grad)"/>'
        f'<text x="60" y="74" text-anchor="middle" font-size="44" font-weight="800" fill="#ffffff" font-family="Inter,sans-serif">{initial_char}</text>'
        f'</svg>'
        f'</div>'
        f'<div class="if-profile-info">'
        f'<div class="if-name-row">'
        f'<span class="if-display-name">{_esc(copy["displayName"])}</span>'
        f'<span class="if-verified-badge">'
        f'<svg width="32" height="32" viewBox="0 0 40 40" fill="none">'
        f'<circle cx="20" cy="20" r="20" fill="#0095F6"/>'
        f'<path d="M17.5 27.5L10 20l2.5-2.5 5 5 10-10L30 15 17.5 27.5z" fill="#fff"/>'
        f'</svg>'
        f'</span>'
        f'</div>'
        f'<div class="if-handle">{_esc(copy["handle"])}</div>'
        f'<div class="if-follower-count">{_esc(copy["followers"])}</div>'
        f'</div>'
        f'<div id="{node_id}-btn" class="if-follow-btn">'
        f'<span id="{node_id}-btn-follow" class="if-btn-text if-btn-text-follow">{_esc(copy["buttonText"])}</span>'
        f'<span id="{node_id}-btn-following" class="if-btn-text if-btn-text-following" style="opacity:0">'
        f'<span>{_esc(copy["followingText"])}</span>'
        f'<svg class="if-chevron" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
        f'<polyline points="6 9 12 15 18 9"/>'
        f'</svg>'
        f'</span>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def if_overlay_css() -> str:
    """CSS for Instagram Follow template."""
    return (
        ".instagram-follow{position:absolute;inset:0;width:1080px;height:1920px;"
        "pointer-events:none;font-family:Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}"
        ".instagram-follow .if-card{position:absolute;bottom:160px;left:50%;"
        "transform:translateX(-50%);display:flex;align-items:center;gap:26px;"
        "background:#1a1a1a;border:1px solid rgba(255,255,255,0.08);border-radius:75px;"
        "padding:22px 36px 22px 22px;box-shadow:0 16px 48px rgba(0,0,0,0.55);"
        "will-change:transform,opacity}"
        ".instagram-follow .if-avatar{width:120px;height:120px;border-radius:50%;"
        "flex-shrink:0;border:3px solid #333;overflow:hidden;display:flex;"
        "align-items:center;justify-content:center}"
        ".instagram-follow .if-profile-info{display:flex;flex-direction:column;"
        "gap:3px;margin-right:16px}"
        ".instagram-follow .if-name-row{display:flex;align-items:center;gap:10px}"
        ".instagram-follow .if-display-name{font-size:40px;font-weight:700;color:#ffffff;"
        "line-height:1.2;letter-spacing:-0.01em}"
        ".instagram-follow .if-verified-badge{width:32px;height:32px;flex-shrink:0;"
        "display:flex;align-items:center}"
        ".instagram-follow .if-handle{font-size:27px;font-weight:400;color:#a0a0a0;line-height:1.2}"
        ".instagram-follow .if-follower-count{font-size:24px;font-weight:400;color:#737373;line-height:1.2}"
        ".instagram-follow .if-follow-btn{position:relative;width:240px;height:78px;border-radius:39px;"
        "background:#0095f6;flex-shrink:0;display:flex;align-items:center;justify-content:center;"
        "overflow:hidden;will-change:transform,background-color}"
        ".instagram-follow .if-btn-text{position:absolute;font-size:29px;font-weight:700;"
        "color:#ffffff;letter-spacing:0.02em;white-space:nowrap;display:flex;align-items:center;"
        "gap:8px;will-change:opacity}"
        ".instagram-follow .if-chevron{display:inline-block;width:20px;height:20px}"
    )
