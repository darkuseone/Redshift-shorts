"""Reddit Post — social card with interactive upvote reaction.

Catalog ``reddit-post`` animates an authentic Reddit dark card with subreddit icon,
post author, title, body text, upvote group with orange reaction bounce, and action buttons.
No tween of width/height/filter/clip-path/strokeDashoffset; no textContent writes; no attr tweens.
All copy pre-baked with dual-state vote counters cross-faded via opacity.
Inter font, 9:16 vertical placement.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_RP_CATALOG = 5.0

_RP_DEFAULTS = {
    "subreddit": "r/hyperframes",
    "author": "u/developer · 3h",
    "title": "Writing HTML to render video changed everything for our pipeline",
    "body": "Zero external dependencies, pure web standards, and pixel-perfect 4K rendering in seconds. The whole workflow runs headlessly.",
    "votes": "4.2k",
    "votesActive": "4.3k",
    "comments": "328",
}

_RP_MAX = {
    "sub": 32,
    "author": 32,
    "title": 140,
    "body": 280,
    "metric": 12,
}


def _rp_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _rp_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = ("title", "body", "subreddit", "text", "snippet", "author", "domain", "name")
    return any(str(params.get(k) or "").strip() for k in keys)


def _rp_copy(params: dict[str, Any]) -> dict[str, Any]:
    raw_sub = (
        params.get("subreddit")
        or params.get("name")
        or _RP_DEFAULTS["subreddit"]
    )
    sub_str = str(raw_sub).strip()
    if sub_str and not sub_str.startswith("r/"):
        sub_str = f"r/{sub_str}"

    raw_author = params.get("author") or params.get("domain") or _RP_DEFAULTS["author"]
    author_str = str(raw_author).strip()
    if author_str and not author_str.startswith("u/") and not author_str.startswith("r/"):
        author_str = f"u/{author_str}"

    title_text = params.get("title") or _RP_DEFAULTS["title"]
    body_text = (
        params.get("body")
        or params.get("text")
        or params.get("snippet")
        or _RP_DEFAULTS["body"]
    )

    votes_init = params.get("votes") or _RP_DEFAULTS["votes"]
    votes_act = params.get("votesActive") or _RP_DEFAULTS["votesActive"]

    return {
        "subreddit": _rp_clip(sub_str, _RP_DEFAULTS["subreddit"], _RP_MAX["sub"]),
        "author": _rp_clip(author_str, _RP_DEFAULTS["author"], _RP_MAX["author"]),
        "title": _rp_clip(title_text, _RP_DEFAULTS["title"], _RP_MAX["title"]),
        "body": _rp_clip(body_text, _RP_DEFAULTS["body"], _RP_MAX["body"]),
        "votes": _rp_clip(votes_init, _RP_DEFAULTS["votes"], _RP_MAX["metric"]),
        "votesActive": _rp_clip(votes_act, _RP_DEFAULTS["votesActive"], _RP_MAX["metric"]),
        "comments": _rp_clip(params.get("comments"), _RP_DEFAULTS["comments"], _RP_MAX["metric"]),
    }


def ov_reddit_post(ctx: TemplateCtx) -> Piece:
    """Reddit Post: card with upvote reaction bounce and counter swap."""
    if not _rp_has_copy(ctx.params):
        return Piece()

    copy = _rp_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 2.5)
    scale = duration / _RP_CATALOG

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

    # Upvote press-in
    t_press = start + dur(1.5)
    tweens.append(
        f'tl.to("#{node_id}-upvote-btn",{{scale:0.85,duration:{_num(dur(0.12))},ease:"power2.out"}},'
        f'{_num(t_press)});'
    )

    # Upvote release bounce
    t_release = start + dur(1.62)
    tweens.append(
        f'tl.to("#{node_id}-upvote-btn",{{scale:1,duration:{_num(dur(0.38))},ease:"back.out(1.8)"}},'
        f'{_num(t_release)});'
    )

    # Crossfade grey arrow -> orange arrow
    tweens.append(
        f'tl.to("#{node_id}-arrow-grey",{{opacity:0,duration:{_num(dur(0.08))},ease:"none"}},'
        f'{_num(t_release)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-arrow-orange",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.1))},ease:"none"}},'
        f'{_num(t_release)});'
    )

    # Crossfade vote count (initial -> active orange)
    tweens.append(
        f'tl.to("#{node_id}-vote-init",{{opacity:0,duration:{_num(dur(0.08))},ease:"none"}},'
        f'{_num(t_release)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-vote-act",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.08))},ease:"none"}},'
        f'{_num(t_release + dur(0.02))});'
    )

    # Slide card out to bottom before clip end
    t_out = max(t_release + dur(0.8), start + duration - dur(0.35))
    tweens.append(
        f'tl.to("#{node_id}-card",{{opacity:0,y:400,duration:{_num(dur(0.3))},ease:"power3.in"}},'
        f'{_num(t_out)});'
    )

    node = (
        f'<div id="{node_id}" class="clip overlay reddit-post" {_timing(ctx)}>'
        f'<div id="{node_id}-card" class="rp-card" style="opacity:0">'
        f'<div class="rp-header">'
        f'<div class="rp-subreddit-icon">'
        f'<svg viewBox="0 0 48 48" fill="none">'
        f'<circle cx="24" cy="24" r="24" fill="#FF4500"/>'
        f'<text x="24" y="31" text-anchor="middle" font-family="Inter,sans-serif" font-size="22" font-weight="800" fill="#ffffff">r/</text>'
        f'</svg>'
        f'</div>'
        f'<div class="rp-post-meta">'
        f'<span class="rp-subreddit-name">{_esc(copy["subreddit"])}</span>'
        f'<span class="rp-post-author">{_esc(copy["author"])}</span>'
        f'</div>'
        f'</div>'
        f'<div class="rp-post-title">{_esc(copy["title"])}</div>'
        f'<div class="rp-post-body">{_esc(copy["body"])}</div>'
        f'<div class="rp-action-bar">'
        f'<div class="rp-vote-group">'
        f'<div id="{node_id}-upvote-btn" class="rp-vote-btn">'
        f'<svg viewBox="0 0 24 24" fill="none">'
        f'<path id="{node_id}-arrow-grey" d="M12 4L3 14h5v6h8v-6h5L12 4z" fill="#818384"/>'
        f'<path id="{node_id}-arrow-orange" d="M12 4L3 14h5v6h8v-6h5L12 4z" fill="#FF4500" style="opacity:0"/>'
        f'</svg>'
        f'</div>'
        f'<div class="rp-vote-wrap">'
        f'<span id="{node_id}-vote-init" class="rp-vote-count rp-vote-init">{_esc(copy["votes"])}</span>'
        f'<span id="{node_id}-vote-act" class="rp-vote-count rp-vote-act" style="opacity:0">{_esc(copy["votesActive"])}</span>'
        f'</div>'
        f'<div class="rp-vote-btn">'
        f'<svg viewBox="0 0 24 24" fill="none">'
        f'<path d="M12 20l9-10h-5V4H8v6H3l9 10z" fill="#818384"/>'
        f'</svg>'
        f'</div>'
        f'</div>'
        f'<div class="rp-action-btn">'
        f'<svg viewBox="0 0 24 24" fill="none" stroke="#818384" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>'
        f'</svg>'
        f'<span>{_esc(copy["comments"])}</span>'
        f'</div>'
        f'<div class="rp-action-btn">'
        f'<svg viewBox="0 0 24 24" fill="none" stroke="#818384" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8"/>'
        f'<polyline points="16 6 12 2 8 6"/>'
        f'<line x1="12" y1="2" x2="12" y2="15"/>'
        f'</svg>'
        f'<span>Share</span>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def rp_overlay_css() -> str:
    """CSS for Reddit Post template."""
    return (
        ".reddit-post{position:absolute;inset:0;width:1080px;height:1920px;"
        "pointer-events:none;font-family:Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}"
        ".reddit-post .rp-card{position:absolute;top:620px;left:80px;"
        "width:920px;background:#1a1a2e;"
        "border-radius:28px;padding:38px;box-shadow:0 16px 60px rgba(0,0,0,0.65);"
        "box-sizing:border-box;will-change:transform,opacity}"
        ".reddit-post .rp-header{display:flex;align-items:center;gap:16px;margin-bottom:24px}"
        ".reddit-post .rp-subreddit-icon{width:56px;height:56px;flex-shrink:0}"
        ".reddit-post .rp-subreddit-icon svg{width:56px;height:56px;display:block}"
        ".reddit-post .rp-post-meta{display:flex;flex-direction:column;gap:3px}"
        ".reddit-post .rp-subreddit-name{font-size:30px;font-weight:700;color:#d7dadc;line-height:1.2}"
        ".reddit-post .rp-post-author{font-size:25px;font-weight:400;color:#818384;line-height:1.2}"
        ".reddit-post .rp-post-title{font-size:38px;font-weight:700;color:#d7dadc;line-height:1.35;margin-bottom:18px}"
        ".reddit-post .rp-post-body{font-size:28px;font-weight:400;color:#818384;line-height:1.45;margin-bottom:30px}"
        ".reddit-post .rp-action-bar{display:flex;align-items:center;gap:24px;padding-top:22px;border-top:1px solid #343536}"
        ".reddit-post .rp-vote-group{display:flex;align-items:center;gap:12px;background:#272729;border-radius:28px;padding:10px 20px}"
        ".reddit-post .rp-vote-btn{width:36px;height:36px;display:flex;align-items:center;justify-content:center;will-change:transform}"
        ".reddit-post .rp-vote-btn svg{width:32px;height:32px;display:block}"
        ".reddit-post .rp-vote-wrap{position:relative;min-width:60px;display:flex;align-items:center;justify-content:center}"
        ".reddit-post .rp-vote-count{font-size:28px;font-weight:700;line-height:1;text-align:center}"
        ".reddit-post .rp-vote-init{color:#d7dadc}"
        ".reddit-post .rp-vote-act{position:absolute;color:#FF4500}"
        ".reddit-post .rp-action-btn{display:flex;align-items:center;gap:10px;background:#272729;border-radius:28px;padding:12px 24px}"
        ".reddit-post .rp-action-btn svg{width:28px;height:28px;display:block}"
        ".reddit-post .rp-action-btn span{font-size:25px;font-weight:500;color:#818384}"
    )
