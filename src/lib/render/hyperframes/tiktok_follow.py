"""TikTok Follow — TikTok profile lower-third with animated Follow / Following button.

Catalog ``tiktok-follow`` animates a lower-third profile pill with avatar,
display name, handle, follower count, and a TikTok-crimson button press-in with bounce to "Following".
No tween of width/height/filter/clip-path/strokeDashoffset; no textContent writes.
Brandbook ink #111214, Inter font, 9:16 vertical lower-third.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_TT_CATALOG = 4.5

_TT_DEFAULTS = {
    "displayName": "HeyGen",
    "handle": "@heygen.com",
    "followers": "1,999 followers",
    "buttonText": "Follow",
    "followingText": "Following",
}

_TT_MAX = {
    "name": 32,
    "handle": 32,
    "followers": 24,
    "btn": 20,
}


def _tt_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _tt_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = ("displayName", "handle", "followers", "title", "snippet", "domain", "name", "text")
    return any(str(params.get(k) or "").strip() for k in keys)


def _tt_copy(params: dict[str, Any]) -> dict[str, Any]:
    name = (
        params.get("displayName")
        or params.get("name")
        or params.get("title")
        or _TT_DEFAULTS["displayName"]
    )
    raw_handle = params.get("handle") or params.get("domain") or _TT_DEFAULTS["handle"]
    handle_str = str(raw_handle).strip()
    if handle_str and not handle_str.startswith("@"):
        handle_str = f"@{handle_str}"

    return {
        "displayName": _tt_clip(name, _TT_DEFAULTS["displayName"], _TT_MAX["name"]),
        "handle": _tt_clip(handle_str, _TT_DEFAULTS["handle"], _TT_MAX["handle"]),
        "followers": _tt_clip(params.get("followers"), _TT_DEFAULTS["followers"], _TT_MAX["followers"]),
        "buttonText": _tt_clip(params.get("buttonText"), _TT_DEFAULTS["buttonText"], _TT_MAX["btn"]),
        "followingText": _tt_clip(params.get("followingText"), _TT_DEFAULTS["followingText"], _TT_MAX["btn"]),
    }


def ov_tiktok_follow(ctx: TemplateCtx) -> Piece:
    """TikTok Follow: profile lower-third with animated TikTok follow button."""
    if not _tt_has_copy(ctx.params):
        return Piece()

    copy = _tt_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 2.0)
    scale = duration / _TT_CATALOG

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

    # Button release with spring bounce and color change
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

    initial_char = _esc(copy["displayName"][:1].upper() if copy["displayName"] else "T")

    node = (
        f'<div id="{node_id}" class="clip overlay tiktok-follow" {_timing(ctx)}>'
        f'<div id="{node_id}-card" class="tf-card" style="opacity:0">'
        f'<div class="tf-avatar">'
        f'<svg width="120" height="120" viewBox="0 0 120 120">'
        f'<defs>'
        f'<linearGradient id="{node_id}-tt-grad" x1="0%" y1="0%" x2="100%" y2="100%">'
        f'<stop offset="0%" stop-color="#25F4EE"/>'
        f'<stop offset="100%" stop-color="#FE2C55"/>'
        f'</linearGradient>'
        f'</defs>'
        f'<circle cx="60" cy="60" r="58" fill="url(#{node_id}-tt-grad)"/>'
        f'<text x="60" y="74" text-anchor="middle" font-size="44" font-weight="800" fill="#ffffff" font-family="Inter,sans-serif">{initial_char}</text>'
        f'</svg>'
        f'</div>'
        f'<div class="tf-profile-info">'
        f'<div class="tf-display-name">{_esc(copy["displayName"])}</div>'
        f'<div class="tf-handle">{_esc(copy["handle"])}</div>'
        f'<div class="tf-follower-count">{_esc(copy["followers"])}</div>'
        f'</div>'
        f'<div id="{node_id}-btn" class="tf-follow-btn">'
        f'<span id="{node_id}-btn-follow" class="tf-btn-text tf-btn-text-follow">{_esc(copy["buttonText"])}</span>'
        f'<span id="{node_id}-btn-following" class="tf-btn-text tf-btn-text-following" style="opacity:0">'
        f'<span>{_esc(copy["followingText"])}</span>'
        f'<svg class="tf-check" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">'
        f'<polyline points="20 6 9 17 4 12"/>'
        f'</svg>'
        f'</span>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def tf_overlay_css() -> str:
    """CSS for TikTok Follow template."""
    return (
        ".tiktok-follow{position:absolute;inset:0;width:1080px;height:1920px;"
        "pointer-events:none;font-family:Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}"
        ".tiktok-follow .tf-card{position:absolute;bottom:160px;left:50%;"
        "transform:translateX(-50%);display:flex;align-items:center;gap:26px;"
        "background:#1a1a1a;border:1px solid rgba(255,255,255,0.08);border-radius:75px;"
        "padding:22px 36px 22px 22px;box-shadow:0 16px 48px rgba(0,0,0,0.55);"
        "will-change:transform,opacity}"
        ".tiktok-follow .tf-avatar{width:120px;height:120px;border-radius:50%;"
        "flex-shrink:0;border:3px solid #333;overflow:hidden;display:flex;"
        "align-items:center;justify-content:center}"
        ".tiktok-follow .tf-profile-info{display:flex;flex-direction:column;"
        "gap:3px;margin-right:16px}"
        ".tiktok-follow .tf-display-name{font-size:40px;font-weight:700;color:#ffffff;"
        "line-height:1.2;letter-spacing:-0.01em}"
        ".tiktok-follow .tf-handle{font-size:27px;font-weight:400;color:#a0a0a0;line-height:1.2}"
        ".tiktok-follow .tf-follower-count{font-size:24px;font-weight:400;color:#737373;line-height:1.2}"
        ".tiktok-follow .tf-follow-btn{position:relative;width:240px;height:78px;border-radius:39px;"
        "background:#fe2c55;flex-shrink:0;display:flex;align-items:center;justify-content:center;"
        "overflow:hidden;will-change:transform,background-color}"
        ".tiktok-follow .tf-btn-text{position:absolute;font-size:29px;font-weight:700;"
        "color:#ffffff;letter-spacing:0.02em;white-space:nowrap;display:flex;align-items:center;"
        "gap:8px;will-change:opacity}"
        ".tiktok-follow .tf-check{display:inline-block;width:22px;height:22px}"
    )
