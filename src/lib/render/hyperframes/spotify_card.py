"""Spotify Card — music track player card with album art breathe.

Catalog ``spotify-card`` animates an authentic Spotify glassmorphic player card
with album art, track title, artist name, and Spotify branding.
No tween of width/height/filter/clip-path/strokeDashoffset; no textContent writes.
Inter font, 9:16 vertical placement.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_SC_CATALOG = 5.0

_SC_DEFAULTS = {
    "trackName": "HyperFrames",
    "artistName": "HeyGen",
    "brandText": "Spotify",
}

_SC_MAX = {
    "track": 60,
    "artist": 50,
    "brand": 30,
}


def _sc_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _sc_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = ("trackName", "artistName", "title", "snippet", "domain", "name", "brandText")
    return any(str(params.get(k) or "").strip() for k in keys)


def _sc_copy(params: dict[str, Any]) -> dict[str, Any]:
    track = (
        params.get("trackName")
        or params.get("title")
        or params.get("name")
        or _SC_DEFAULTS["trackName"]
    )
    artist = (
        params.get("artistName")
        or params.get("domain")
        or params.get("snippet")
        or _SC_DEFAULTS["artistName"]
    )
    brand = params.get("brandText") or _SC_DEFAULTS["brandText"]

    return {
        "trackName": _sc_clip(track, _SC_DEFAULTS["trackName"], _SC_MAX["track"]),
        "artistName": _sc_clip(artist, _SC_DEFAULTS["artistName"], _SC_MAX["artist"]),
        "brandText": _sc_clip(brand, _SC_DEFAULTS["brandText"], _SC_MAX["brand"]),
    }


def ov_spotify_card(ctx: TemplateCtx) -> Piece:
    """Spotify Card: glassmorphic player with album art breathe and staggered text."""
    if not _sc_has_copy(ctx.params):
        return Piece()

    copy = _sc_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 2.5)
    scale = duration / _SC_CATALOG

    def dur(catalog_sec: float) -> float:
        return max(0.001, catalog_sec * scale)

    tweens: list[str] = []

    # Card entrance (power3.out)
    t_in = start + dur(0.1)
    tweens.append(
        f'tl.fromTo("#{node_id}-card",{{opacity:0,y:60,scale:0.94}},'
        f'{{opacity:1,y:0,scale:1,duration:{_num(dur(0.7))},ease:"power3.out"}},'
        f'{_num(t_in)});'
    )

    # Track name entrance
    t_track = start + dur(0.55)
    tweens.append(
        f'tl.fromTo("#{node_id}-track",{{opacity:0,y:20}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.5))},ease:"power2.out"}},'
        f'{_num(t_track)});'
    )

    # Artist name entrance
    t_artist = start + dur(0.7)
    tweens.append(
        f'tl.fromTo("#{node_id}-artist",{{opacity:0,y:16}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.45))},ease:"power2.out"}},'
        f'{_num(t_artist)});'
    )

    # Spotify brand entrance
    t_brand = start + dur(0.85)
    tweens.append(
        f'tl.fromTo("#{node_id}-brand",{{opacity:0,y:12}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.4))},ease:"power2.out"}},'
        f'{_num(t_brand)});'
    )

    # Album art breathe
    t_breathe = start + dur(1.2)
    tweens.append(
        f'tl.to("#{node_id}-album-art",{{scale:1.025,duration:{_num(dur(1.5))},'
        f'ease:"power1.inOut",yoyo:true,repeat:1}},'
        f'{_num(t_breathe)});'
    )

    # Card exit (power2.in)
    t_out = max(t_brand + dur(1.2), start + duration - dur(0.5))
    tweens.append(
        f'tl.to("#{node_id}-card",{{opacity:0,y:-40,scale:0.96,duration:{_num(dur(0.5))},ease:"power2.in"}},'
        f'{_num(t_out)});'
    )

    node = (
        f'<div id="{node_id}" class="clip overlay spotify-card" {_timing(ctx)}>'
        f'<div id="{node_id}-card" class="sc-card" style="opacity:0">'
        f'<div id="{node_id}-album-art" class="sc-album-art">'
        f'<svg class="sc-album-art-icon" width="200" height="200" viewBox="0 0 24 24" fill="none">'
        f'<path d="M9 18V5l12-2v13" stroke="rgba(255,255,255,0.7)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="6" cy="18" r="3" stroke="rgba(255,255,255,0.7)" stroke-width="1.5"/>'
        f'<circle cx="18" cy="16" r="3" stroke="rgba(255,255,255,0.7)" stroke-width="1.5"/>'
        f'</svg>'
        f'</div>'
        f'<div class="sc-track-info">'
        f'<div id="{node_id}-track" class="sc-track-name">{_esc(copy["trackName"])}</div>'
        f'<div id="{node_id}-artist" class="sc-artist-name">{_esc(copy["artistName"])}</div>'
        f'</div>'
        f'<div id="{node_id}-brand" class="sc-brand">'
        f'<div class="sc-brand-logo">'
        f'<svg width="32" height="32" viewBox="0 0 16 16" fill="#1db954">'
        f'<path d="M8 0a8 8 0 1 0 0 16A8 8 0 0 0 8 0m3.669 11.538a.5.5 0 0 1-.686.165c-1.879-1.147-4.243-1.407-7.028-.77a.499.499 0 0 1-.222-.973c3.048-.696 5.662-.397 7.77.892a.5.5 0 0 1 .166.686m.979-2.178a.624.624 0 0 1-.858.205c-2.15-1.321-5.428-1.704-7.972-.932a.625.625 0 0 1-.362-1.194c2.905-.881 6.517-.454 8.986 1.063a.624.624 0 0 1 .206.858m.084-2.268C10.154 5.56 5.9 5.419 3.438 6.166a.748.748 0 1 1-.434-1.432c2.825-.857 7.523-.692 10.492 1.07a.747.747 0 1 1-.764 1.288"/>'
        f'</svg>'
        f'</div>'
        f'<span class="sc-brand-text">{_esc(copy["brandText"])}</span>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def sc_overlay_css() -> str:
    """CSS for Spotify Card template."""
    return (
        ".spotify-card{position:absolute;inset:0;width:1080px;height:1920px;"
        "pointer-events:none;font-family:Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}"
        ".spotify-card .sc-card{position:absolute;top:465px;left:150px;width:780px;"
        "background:linear-gradient(165deg,rgba(140,155,170,0.42) 0%,rgba(100,115,130,0.35) 30%,rgba(75,88,105,0.38) 60%,rgba(60,72,88,0.44) 100%);"
        "border-radius:28px;padding:36px;border:1px solid rgba(255,255,255,0.22);"
        "box-shadow:0 24px 48px rgba(0,0,0,0.3),0 2px 6px rgba(0,0,0,0.12),inset 0 1px 0 rgba(255,255,255,0.32),inset 0 -1px 0 rgba(0,0,0,0.12);"
        "backdrop-filter:blur(40px) saturate(180%);-webkit-backdrop-filter:blur(40px) saturate(180%);"
        "overflow:hidden;box-sizing:border-box;will-change:transform,opacity}"
        ".spotify-card .sc-album-art{width:708px;height:708px;border-radius:16px;overflow:hidden;"
        "position:relative;z-index:1;background:linear-gradient(145deg,#1db954 0%,#17a34a 30%,#0f7234 60%,#191414 100%);"
        "margin-bottom:36px;display:flex;align-items:center;justify-content:center;will-change:transform}"
        ".spotify-card .sc-album-art-icon{opacity:0.25}"
        ".spotify-card .sc-track-info{position:relative;z-index:1;margin-bottom:28px;padding:0 8px}"
        ".spotify-card .sc-track-name{font-size:52px;font-weight:700;color:#ffffff;letter-spacing:-0.02em;"
        "line-height:1.15;margin-bottom:8px;will-change:transform,opacity}"
        ".spotify-card .sc-artist-name{font-size:34px;font-weight:400;color:rgba(255,255,255,0.7);"
        "line-height:1.3;will-change:transform,opacity}"
        ".spotify-card .sc-brand{position:relative;z-index:1;display:flex;align-items:center;gap:12px;"
        "padding:0 8px;will-change:transform,opacity}"
        ".spotify-card .sc-brand-logo{display:flex;align-items:center;justify-content:center}"
        ".spotify-card .sc-brand-text{font-size:26px;font-weight:600;color:rgba(255,255,255,0.55);letter-spacing:0.01em}"
    )
