"""macOS Notification — desktop glass notification banner sliding from right.

Catalog ``macos-notification`` animates an authentic macOS dark-mode notification
with app icon, app name, timestamp, notification title, and body message.
Rebuilt for 9:16 vertical placement (top-right / upper third).
No tween of width/height/filter/clip-path/strokeDashoffset; no textContent writes.
Inter font, brand accents.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_MN_CATALOG = 5.0

_MN_DEFAULTS = {
    "appName": "HyperFrames",
    "time": "now",
    "title": "Build complete",
    "body": "Video rendered in 1.4s with zero frame drops.",
    "iconText": "HF",
}

_MN_MAX = {
    "appName": 28,
    "time": 12,
    "title": 60,
    "body": 140,
    "iconText": 4,
}


def _mn_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _mn_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = ("title", "body", "appName", "text", "snippet", "domain", "name", "content")
    return any(str(params.get(k) or "").strip() for k in keys)


def _mn_copy(params: dict[str, Any]) -> dict[str, Any]:
    app_name = (
        params.get("appName")
        or params.get("domain")
        or params.get("name")
        or _MN_DEFAULTS["appName"]
    )
    title = (
        params.get("title")
        or params.get("heading")
        or _MN_DEFAULTS["title"]
    )
    body = (
        params.get("body")
        or params.get("text")
        or params.get("snippet")
        or params.get("content")
        or _MN_DEFAULTS["body"]
    )
    time_label = params.get("time") or _MN_DEFAULTS["time"]
    icon_text = params.get("iconText") or _MN_DEFAULTS["iconText"]

    return {
        "appName": _mn_clip(app_name, _MN_DEFAULTS["appName"], _MN_MAX["appName"]),
        "time": _mn_clip(time_label, _MN_DEFAULTS["time"], _MN_MAX["time"]),
        "title": _mn_clip(title, _MN_DEFAULTS["title"], _MN_MAX["title"]),
        "body": _mn_clip(body, _MN_DEFAULTS["body"], _MN_MAX["body"]),
        "iconText": _mn_clip(icon_text, _MN_DEFAULTS["iconText"], _MN_MAX["iconText"]),
    }


def ov_macos_notification(ctx: TemplateCtx) -> Piece:
    """macOS Notification: slide in from right with glass banner."""
    if not _mn_has_copy(ctx.params):
        return Piece()

    copy = _mn_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 2.0)
    scale = duration / _MN_CATALOG

    def dur(catalog_sec: float) -> float:
        return max(0.001, catalog_sec * scale)

    tweens: list[str] = []

    # Slide in from right (power3.out)
    t_in = start + dur(0.15)
    tweens.append(
        f'tl.fromTo("#{node_id}-card",{{opacity:0,x:600}},'
        f'{{opacity:1,x:0,duration:{_num(dur(0.55))},ease:"power3.out"}},'
        f'{_num(t_in)});'
    )

    # Slide out to right before clip end (power3.in)
    t_out = max(t_in + dur(1.0), start + duration - dur(0.4))
    tweens.append(
        f'tl.to("#{node_id}-card",{{opacity:0,x:600,duration:{_num(dur(0.35))},ease:"power3.in"}},'
        f'{_num(t_out)});'
    )

    node = (
        f'<div id="{node_id}" class="clip overlay macos-notification" {_timing(ctx)}>'
        f'<div id="{node_id}-card" class="mn-card" style="opacity:0">'
        f'<div class="mn-app-icon">'
        f'<svg viewBox="0 0 72 72" fill="none">'
        f'<defs>'
        f'<linearGradient id="{node_id}-mn-grad" x1="0" y1="0" x2="72" y2="72" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0%" stop-color="#C8453D"/>'
        f'<stop offset="100%" stop-color="#E4726A"/>'
        f'</linearGradient>'
        f'</defs>'
        f'<rect width="72" height="72" rx="16" fill="url(#{node_id}-mn-grad)"/>'
        f'<text x="36" y="46" text-anchor="middle" font-family="Inter, sans-serif" font-size="28" font-weight="700" fill="#fff">'
        f'{_esc(copy["iconText"])}'
        f'</text>'
        f'</svg>'
        f'</div>'
        f'<div class="mn-content">'
        f'<div class="mn-header">'
        f'<span class="mn-app-name">{_esc(copy["appName"])}</span>'
        f'<span class="mn-time">{_esc(copy["time"])}</span>'
        f'</div>'
        f'<div class="mn-title">{_esc(copy["title"])}</div>'
        f'<div class="mn-body">{_esc(copy["body"])}</div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def mn_overlay_css() -> str:
    """CSS for macOS Notification template."""
    return (
        ".macos-notification{position:absolute;inset:0;width:1080px;height:1920px;"
        "pointer-events:none;font-family:Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}"
        ".macos-notification .mn-card{position:absolute;top:180px;right:60px;width:820px;"
        "background:rgba(28,28,30,0.85);backdrop-filter:blur(40px);-webkit-backdrop-filter:blur(40px);"
        "border-radius:24px;padding:26px 28px;box-shadow:0 16px 48px rgba(0,0,0,0.55);"
        "border:1px solid rgba(255,255,255,0.14);display:flex;gap:20px;align-items:flex-start;"
        "box-sizing:border-box;will-change:transform,opacity}"
        ".macos-notification .mn-app-icon{width:72px;height:72px;border-radius:16px;flex-shrink:0;overflow:hidden}"
        ".macos-notification .mn-app-icon svg{width:72px;height:72px;display:block}"
        ".macos-notification .mn-content{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px}"
        ".macos-notification .mn-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:2px}"
        ".macos-notification .mn-app-name{font-size:24px;font-weight:600;color:rgba(255,255,255,0.55);"
        "text-transform:uppercase;letter-spacing:0.02em}"
        ".macos-notification .mn-time{font-size:22px;font-weight:400;color:rgba(255,255,255,0.35)}"
        ".macos-notification .mn-title{font-size:32px;font-weight:700;color:#ffffff;line-height:1.25}"
        ".macos-notification .mn-body{font-size:26px;font-weight:400;color:rgba(255,255,255,0.7);"
        "line-height:1.35;word-break:break-word}"
    )
