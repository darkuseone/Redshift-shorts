"""X Post — social post card with interactive like reaction.

Catalog ``x-post`` animates an authentic X (Twitter) dark card with user header,
verified badge, tweet body, timestamp, engagement metrics, and an animated heart like button.
No tween of width/height/filter/clip-path/strokeDashoffset; no textContent writes.
All copy pre-baked with dual-state like counters cross-faded via opacity.
Inter font, 9:16 vertical placement.
"""

from __future__ import annotations

import html
from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_XP_CATALOG = 5.0

_XP_DEFAULTS = {
    "displayName": "Hyperframes",
    "handle": "@hyperframes",
    "text": "Write HTML, render pixel-perfect video. Zero external dependencies, pure web standards. #HyperFrames",
    "timestamp": "1:10 PM · Apr 7, 2026",
    "replies": "34",
    "reposts": "2.3K",
    "likes": "10.9K",
    "likesActive": "11.0K",
    "views": "150K",
}

_XP_MAX = {
    "name": 32,
    "handle": 32,
    "text": 280,
    "time": 36,
    "metric": 12,
}


def _xp_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _xp_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = ("text", "displayName", "handle", "tweet", "title", "snippet", "domain", "name")
    return any(str(params.get(k) or "").strip() for k in keys)


def _xp_copy(params: dict[str, Any]) -> dict[str, Any]:
    name = (
        params.get("displayName")
        or params.get("name")
        or params.get("title")
        or _XP_DEFAULTS["displayName"]
    )
    raw_handle = params.get("handle") or params.get("domain") or _XP_DEFAULTS["handle"]
    handle_str = str(raw_handle).strip()
    if handle_str and not handle_str.startswith("@"):
        handle_str = f"@{handle_str}"

    body_text = (
        params.get("text")
        or params.get("tweet")
        or params.get("snippet")
        or _XP_DEFAULTS["text"]
    )

    likes_init = params.get("likes") or _XP_DEFAULTS["likes"]
    likes_act = params.get("likesActive") or _XP_DEFAULTS["likesActive"]

    return {
        "displayName": _xp_clip(name, _XP_DEFAULTS["displayName"], _XP_MAX["name"]),
        "handle": _xp_clip(handle_str, _XP_DEFAULTS["handle"], _XP_MAX["handle"]),
        "text": _xp_clip(body_text, _XP_DEFAULTS["text"], _XP_MAX["text"]),
        "timestamp": _xp_clip(params.get("timestamp"), _XP_DEFAULTS["timestamp"], _XP_MAX["time"]),
        "replies": _xp_clip(params.get("replies"), _XP_DEFAULTS["replies"], _XP_MAX["metric"]),
        "reposts": _xp_clip(params.get("reposts"), _XP_DEFAULTS["reposts"], _XP_MAX["metric"]),
        "likes": _xp_clip(likes_init, _XP_DEFAULTS["likes"], _XP_MAX["metric"]),
        "likesActive": _xp_clip(likes_act, _XP_DEFAULTS["likesActive"], _XP_MAX["metric"]),
        "views": _xp_clip(params.get("views"), _XP_DEFAULTS["views"], _XP_MAX["metric"]),
    }


def _format_tweet_body(raw_text: str) -> str:
    """Escape text and highlight hashtags with Twitter cyan."""
    escaped = _esc(raw_text)
    words = escaped.split(" ")
    formatted = []
    for word in words:
        if word.startswith("#") and len(word) > 1:
            formatted.append(f'<span class="xp-hashtag">{word}</span>')
        else:
            formatted.append(word)
    return " ".join(formatted)


def ov_x_post(ctx: TemplateCtx) -> Piece:
    """X Post: tweet card with like spring bounce and metrics counter."""
    if not _xp_has_copy(ctx.params):
        return Piece()

    copy = _xp_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 2.5)
    scale = duration / _XP_CATALOG

    def dur(catalog_sec: float) -> float:
        return max(0.001, catalog_sec * scale)

    tweens: list[str] = []

    # Slide card in from bottom
    t_in = start + dur(0.1)
    tweens.append(
        f'tl.fromTo("#{node_id}-card",{{opacity:0,y:400}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.6))},ease:"power3.out"}},'
        f'{_num(t_in)});'
    )

    # Like button press-in
    t_press = start + dur(1.5)
    tweens.append(
        f'tl.to("#{node_id}-like-btn",{{scale:0.85,duration:{_num(dur(0.12))},ease:"power2.out"}},'
        f'{_num(t_press)});'
    )

    # Like button release bounce
    t_release = start + dur(1.62)
    tweens.append(
        f'tl.to("#{node_id}-like-btn",{{scale:1,duration:{_num(dur(0.38))},ease:"back.out(1.8)"}},'
        f'{_num(t_release)});'
    )

    # Swap outline heart with filled pink heart
    tweens.append(
        f'tl.to("#{node_id}-heart-outline",{{opacity:0,duration:{_num(dur(0.05))},ease:"none"}},'
        f'{_num(t_release)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-heart-filled",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.1))},ease:"none"}},'
        f'{_num(t_release)});'
    )

    # Swap like count (initial grey -> active pink)
    tweens.append(
        f'tl.to("#{node_id}-like-init",{{opacity:0,duration:{_num(dur(0.08))},ease:"none"}},'
        f'{_num(t_release)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-like-act",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.08))},ease:"none"}},'
        f'{_num(t_release + dur(0.02))});'
    )

    # Slide card out to bottom before clip end
    t_out = max(t_release + dur(0.8), start + duration - dur(0.35))
    tweens.append(
        f'tl.to("#{node_id}-card",{{opacity:0,y:400,duration:{_num(dur(0.3))},ease:"power3.in"}},'
        f'{_num(t_out)});'
    )

    formatted_body = _format_tweet_body(copy["text"])

    node = (
        f'<div id="{node_id}" class="clip overlay x-post" {_timing(ctx)}>'
        f'<div id="{node_id}-card" class="xp-card" style="opacity:0">'
        f'<div class="xp-glow"></div>'
        f'<div class="xp-header">'
        f'<div class="xp-avatar">'
        f'<svg viewBox="0 0 52 52" fill="none">'
        f'<circle cx="26" cy="26" r="26" fill="#536471"/>'
        f'<circle cx="26" cy="21" r="10" fill="#8b98a5"/>'
        f'<ellipse cx="26" cy="42" rx="16" ry="12" fill="#8b98a5"/>'
        f'</svg>'
        f'</div>'
        f'<div class="xp-user-info">'
        f'<div class="xp-name-row">'
        f'<span class="xp-display-name">{_esc(copy["displayName"])}</span>'
        f'<span class="xp-verified-badge">'
        f'<svg viewBox="0 0 22 22" fill="none">'
        f'<circle cx="11" cy="11" r="11" fill="#1d9bf0"/>'
        f'<path d="M9.5 14.25L6.25 11l1.06-1.06 2.19 2.19 4.69-4.69L15.25 8.5 9.5 14.25z" fill="#fff"/>'
        f'</svg>'
        f'</span>'
        f'</div>'
        f'<span class="xp-handle">{_esc(copy["handle"])}</span>'
        f'</div>'
        f'<div class="xp-x-logo">'
        f'<svg viewBox="0 0 24 24" fill="#e7e9ea">'
        f'<path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>'
        f'</svg>'
        f'</div>'
        f'</div>'
        f'<div class="xp-tweet-body">{formatted_body}</div>'
        f'<div class="xp-timestamp">{_esc(copy["timestamp"])}</div>'
        f'<div class="xp-metrics-bar">'
        f'<div class="xp-metrics-left">'
        f'<div class="xp-metric">'
        f'<div class="xp-metric-icon">'
        f'<svg viewBox="0 0 24 24" fill="#8b98a5">'
        f'<path d="M1.751 10c0-4.42 3.584-8 8.005-8h4.366c4.49 0 8.129 3.64 8.129 8.13 0 2.96-1.607 5.68-4.196 7.11l-8.054 4.46v-3.69h-.067c-4.49.1-8.183-3.51-8.183-8.01zm8.005-6c-3.317 0-6.005 2.69-6.005 6 0 3.37 2.77 6.08 6.138 6.01l.351-.01h1.761v2.3l5.087-2.81c1.951-1.08 3.163-3.13 3.163-5.36 0-3.39-2.744-6.13-6.129-6.13H9.756z"/>'
        f'</svg>'
        f'</div>'
        f'<span class="xp-metric-count">{_esc(copy["replies"])}</span>'
        f'</div>'
        f'<div class="xp-metric">'
        f'<div class="xp-metric-icon">'
        f'<svg viewBox="0 0 24 24" fill="#8b98a5">'
        f'<path d="M4.5 3.88l4.432 4.14-1.364 1.46L5.5 7.55V16c0 1.1.896 2 2 2H13v2H7.5c-2.209 0-4-1.79-4-4V7.55L1.432 9.48.068 8.02 4.5 3.88zM16.5 6H11V4h5.5c2.209 0 4 1.79 4 4v8.45l2.068-1.93 1.364 1.46-4.432 4.14-4.432-4.14 1.364-1.46 2.068 1.93V8c0-1.1-.896-2-2-2z"/>'
        f'</svg>'
        f'</div>'
        f'<span class="xp-metric-count">{_esc(copy["reposts"])}</span>'
        f'</div>'
        f'<div id="{node_id}-like-btn" class="xp-metric xp-like-btn">'
        f'<div class="xp-metric-icon">'
        f'<svg viewBox="0 0 24 24">'
        f'<path id="{node_id}-heart-outline" d="M16.697 5.5c-1.222-.06-2.679.51-3.89 2.16l-.805 1.09-.806-1.09C9.984 6.01 8.526 5.44 7.304 5.5c-1.243.07-2.349.78-2.91 1.91-.552 1.12-.633 2.78.479 4.82 1.074 1.97 3.257 4.27 7.129 6.61 3.87-2.34 6.052-4.64 7.126-6.61 1.111-2.04 1.03-3.7.477-4.82-.561-1.13-1.666-1.84-2.908-1.91zm4.187 7.69c-1.351 2.48-4.001 5.12-8.379 7.67l-.503.3-.504-.3c-4.379-2.55-7.029-5.19-8.382-7.67-1.36-2.5-1.41-4.86-.514-6.67.887-1.79 2.647-2.91 4.601-3.01 1.651-.09 3.368.56 4.798 2.01 1.429-1.45 3.146-2.1 4.796-2.01 1.954.1 3.714 1.22 4.601 3.01.896 1.81.846 4.17-.514 6.67z" fill="#8b98a5"/>'
        f'<path id="{node_id}-heart-filled" d="M20.884 13.19c-1.351 2.48-4.001 5.12-8.379 7.67l-.503.3-.504-.3c-4.379-2.55-7.029-5.19-8.382-7.67-1.36-2.5-1.41-4.86-.514-6.67.887-1.79 2.647-2.91 4.601-3.01 1.651-.09 3.368.56 4.798 2.01 1.429-1.45 3.146-2.1 4.796-2.01 1.954.1 3.714 1.22 4.601 3.01.896 1.81.846 4.17-.514 6.67z" fill="#f91880" style="opacity:0"/>'
        f'</svg>'
        f'</div>'
        f'<div class="xp-like-wrap">'
        f'<span id="{node_id}-like-init" class="xp-metric-count xp-like-init">{_esc(copy["likes"])}</span>'
        f'<span id="{node_id}-like-act" class="xp-metric-count xp-like-act" style="opacity:0">{_esc(copy["likesActive"])}</span>'
        f'</div>'
        f'</div>'
        f'<div class="xp-metric">'
        f'<div class="xp-metric-icon">'
        f'<svg viewBox="0 0 24 24" fill="#8b98a5">'
        f'<path d="M8.75 21V3h2v18h-2zM18 21V8.5h2V21h-2zM4 21l.004-10h2L6 21H4zm9.248 0v-7h2v7h-2z"/>'
        f'</svg>'
        f'</div>'
        f'<span class="xp-metric-count">{_esc(copy["views"])}</span>'
        f'</div>'
        f'</div>'
        f'<div class="xp-metrics-right">'
        f'<div class="xp-metric">'
        f'<div class="xp-metric-icon">'
        f'<svg viewBox="0 0 24 24" fill="#8b98a5">'
        f'<path d="M4 4.5C4 3.12 5.119 2 6.5 2h11C18.881 2 20 3.12 20 4.5v18.44l-8-5.71-8 5.71V4.5zM6.5 4c-.276 0-.5.22-.5.5v14.56l6-4.29 6 4.29V4.5c0-.28-.224-.5-.5-.5h-11z"/>'
        f'</svg>'
        f'</div>'
        f'</div>'
        f'<div class="xp-metric">'
        f'<div class="xp-metric-icon">'
        f'<svg viewBox="0 0 24 24" fill="#8b98a5">'
        f'<path d="M12 2.59l5.7 5.7-1.41 1.42L13 6.41V16h-2V6.41l-3.3 3.3-1.41-1.42L12 2.59zM21 15l-.02 3.51c0 1.38-1.12 2.49-2.5 2.49H5.5C4.11 21 3 19.88 3 18.5V15h2v3.5c0 .28.22.5.5.5h12.98c.28 0 .5-.22.5-.5L19 15h2z"/>'
        f'</svg>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def xp_overlay_css() -> str:
    """CSS for X Post template."""
    return (
        ".x-post{position:absolute;inset:0;width:1080px;height:1920px;"
        "pointer-events:none;font-family:Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}"
        ".x-post .xp-card{position:absolute;top:620px;left:80px;"
        "width:920px;background:#15202b;"
        "border-radius:28px;padding:42px 42px 34px;"
        "box-shadow:0 16px 56px rgba(0,0,0,0.6);border:1px solid #38444d;"
        "overflow:hidden;box-sizing:border-box;will-change:transform,opacity}"
        ".x-post .xp-glow{position:absolute;bottom:0;left:0;right:0;height:90px;"
        "background:linear-gradient(to top,rgba(29,155,240,0.08),transparent);pointer-events:none}"
        ".x-post .xp-header{display:flex;align-items:flex-start;gap:18px;margin-bottom:22px;position:relative}"
        ".x-post .xp-avatar{width:64px;height:64px;flex-shrink:0;border-radius:50%;overflow:hidden}"
        ".x-post .xp-avatar svg{width:64px;height:64px;display:block}"
        ".x-post .xp-user-info{display:flex;flex-direction:column;gap:3px;flex:1}"
        ".x-post .xp-name-row{display:flex;align-items:center;gap:8px}"
        ".x-post .xp-display-name{font-size:32px;font-weight:700;color:#e7e9ea;line-height:1.2}"
        ".x-post .xp-verified-badge svg{width:26px;height:26px;display:block}"
        ".x-post .xp-handle{font-size:26px;font-weight:400;color:#8b98a5;line-height:1.2}"
        ".x-post .xp-x-logo{position:absolute;top:2px;right:0;width:38px;height:38px}"
        ".x-post .xp-x-logo svg{width:38px;height:38px;display:block}"
        ".x-post .xp-tweet-body{font-size:34px;font-weight:400;color:#e7e9ea;line-height:1.45;margin-bottom:18px}"
        ".x-post .xp-hashtag{color:#1d9bf0}"
        ".x-post .xp-timestamp{font-size:25px;color:#8b98a5;padding-bottom:24px;border-bottom:1px solid #38444d;margin-bottom:20px}"
        ".x-post .xp-metrics-bar{display:flex;align-items:center;justify-content:space-between;position:relative;z-index:1}"
        ".x-post .xp-metrics-left{display:flex;align-items:center;flex:1;justify-content:space-between;padding-right:48px}"
        ".x-post .xp-metrics-right{display:flex;align-items:center;gap:24px}"
        ".x-post .xp-metric{display:flex;align-items:center;gap:10px}"
        ".x-post .xp-metric-icon{width:40px;height:40px;display:flex;align-items:center;justify-content:center}"
        ".x-post .xp-metric-icon svg{width:40px;height:40px;display:block}"
        ".x-post .xp-metric-count{font-size:24px;font-weight:400;color:#8b98a5}"
        ".x-post .xp-like-btn{will-change:transform}"
        ".x-post .xp-like-wrap{position:relative;display:inline-flex;align-items:center}"
        ".x-post .xp-like-init{color:#8b98a5}"
        ".x-post .xp-like-act{position:absolute;left:0;top:0;color:#f91880}"
    )
