"""Message Thread Reveal — iPhone iMessage thread, typing bubbles, link card, end card.

Catalog ``message-thread-reveal`` uses visibility/jumping coordinates.
Here bubbles pop with opacity and scale, the thread smoothly translates with ``y``,
typed characters are pre-baked spans, and the end card transitions with opacity and scale.
No tween of width/height/filter/clip-path/strokeDashoffset; no textContent writes.
Brandbook accent (#C8453D / #E4726A) for CTA and highlights, Inter font.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_MTR_CATALOG = 25.7667

_MTR_DEFAULTS = {
    "contactName": "Rachel",
    "questionMessage": "what r u using for the launch video??",
    "teaserMessage": "wait look 👀",
    "cardTitle": "HyperFrames | Write HTML, render pixel-perfect video",
    "cardDomain": "hyperframes.heygen.com",
    "reactionMessage": "OMG IT'S HTML",
    "reactionEmoji": "🤯🤯🤯",
    "benefitMessage": "renders in 4K. no editor",
    "discoveryMessage": "where did u find this",
    "sourceMessage": "on heygen",
    "workflowMessage": "u just write plain html tags",
    "ownershipMessage": "the code is yours forever",
    "installMessage": "installing rn",
    "thanksMessage": "ty bestie 💚",
    "ecProof": "12,000+ creators",
    "ecFeature1": "Write|plain HTML",
    "ecFeature2": "Render|pixel-perfect",
    "ecFeature3": "Own|every line",
    "ecCta": "Start rendering free",
}

_MTR_MAX = {
    "contactName": 24,
    "questionMessage": 100,
    "teaserMessage": 50,
    "cardTitle": 80,
    "cardDomain": 40,
    "reactionMessage": 60,
    "benefitMessage": 60,
    "discoveryMessage": 60,
    "sourceMessage": 50,
    "workflowMessage": 60,
    "ownershipMessage": 60,
    "installMessage": 50,
    "thanksMessage": 50,
    "ecProof": 40,
    "ecCta": 32,
}


def _mtr_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _mtr_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = (
        "contactName", "questionMessage", "teaserMessage", "cardTitle",
        "cardDomain", "reactionMessage", "benefitMessage", "title", "snippet",
    )
    return any(str(params.get(k) or "").strip() for k in keys)


def _mtr_copy(params: dict[str, Any]) -> dict[str, Any]:
    card_title = params.get("cardTitle") or params.get("title") or _MTR_DEFAULTS["cardTitle"]
    card_domain = params.get("cardDomain") or params.get("domain") or _MTR_DEFAULTS["cardDomain"]
    q_msg = params.get("questionMessage") or params.get("snippet") or _MTR_DEFAULTS["questionMessage"]
    return {
        "contactName": _mtr_clip(params.get("contactName"), _MTR_DEFAULTS["contactName"], _MTR_MAX["contactName"]),
        "questionMessage": _mtr_clip(q_msg, _MTR_DEFAULTS["questionMessage"], _MTR_MAX["questionMessage"]),
        "teaserMessage": _mtr_clip(params.get("teaserMessage"), _MTR_DEFAULTS["teaserMessage"], _MTR_MAX["teaserMessage"]),
        "cardTitle": _mtr_clip(card_title, _MTR_DEFAULTS["cardTitle"], _MTR_MAX["cardTitle"]),
        "cardDomain": _mtr_clip(card_domain, _MTR_DEFAULTS["cardDomain"], _MTR_MAX["cardDomain"]),
        "reactionMessage": _mtr_clip(params.get("reactionMessage"), _MTR_DEFAULTS["reactionMessage"], _MTR_MAX["reactionMessage"]),
        "reactionEmoji": str(params.get("reactionEmoji") or _MTR_DEFAULTS["reactionEmoji"]).strip(),
        "benefitMessage": _mtr_clip(params.get("benefitMessage"), _MTR_DEFAULTS["benefitMessage"], _MTR_MAX["benefitMessage"]),
        "discoveryMessage": _mtr_clip(params.get("discoveryMessage"), _MTR_DEFAULTS["discoveryMessage"], _MTR_MAX["discoveryMessage"]),
        "sourceMessage": _mtr_clip(params.get("sourceMessage"), _MTR_DEFAULTS["sourceMessage"], _MTR_MAX["sourceMessage"]),
        "workflowMessage": _mtr_clip(params.get("workflowMessage"), _MTR_DEFAULTS["workflowMessage"], _MTR_MAX["workflowMessage"]),
        "ownershipMessage": _mtr_clip(params.get("ownershipMessage"), _MTR_DEFAULTS["ownershipMessage"], _MTR_MAX["ownershipMessage"]),
        "installMessage": _mtr_clip(params.get("installMessage"), _MTR_DEFAULTS["installMessage"], _MTR_MAX["installMessage"]),
        "thanksMessage": _mtr_clip(params.get("thanksMessage"), _MTR_DEFAULTS["thanksMessage"], _MTR_MAX["thanksMessage"]),
        "ecProof": _mtr_clip(params.get("ecProof"), _MTR_DEFAULTS["ecProof"], _MTR_MAX["ecProof"]),
        "ecFeature1": str(params.get("ecFeature1") or _MTR_DEFAULTS["ecFeature1"]),
        "ecFeature2": str(params.get("ecFeature2") or _MTR_DEFAULTS["ecFeature2"]),
        "ecFeature3": str(params.get("ecFeature3") or _MTR_DEFAULTS["ecFeature3"]),
        "ecCta": _mtr_clip(params.get("ecCta"), _MTR_DEFAULTS["ecCta"], _MTR_MAX["ecCta"]),
    }


def ov_message_thread_reveal(ctx: TemplateCtx) -> Piece:
    """Message Thread Reveal overlay: iMessage conversation, link preview card, end card."""
    if not _mtr_has_copy(ctx.params):
        return Piece()

    copy = _mtr_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 3.0)
    scale = duration / _MTR_CATALOG

    def dur(catalog_sec: float) -> float:
        return max(0.001, catalog_sec * scale)

    tweens: list[str] = []

    # 1. First incoming message pops in
    tweens.append(
        f'tl.fromTo("#{node_id}-m1",{{opacity:0,scale:0.75}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.2))},ease:"power2.out"}},'
        f'{_num(start)});'
    )

    # 2. Typing indicator appears
    t_dots = start + dur(0.77)
    tweens.append(
        f'tl.fromTo("#{node_id}-dots",{{opacity:0,scale:0.6}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.2))},ease:"power2.out"}},'
        f'{_num(t_dots)});'
    )

    # 3. Message 2 (teaser outgoing)
    t_m2 = start + dur(2.97)
    tweens.append(
        f'tl.to("#{node_id}-dots",{{opacity:0,duration:{_num(dur(0.1))}}},'
        f'{_num(t_m2 - dur(0.1))});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-m2",{{opacity:0,scale:0.75}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.16))},ease:"power2.out"}},'
        f'{_num(t_m2)});'
    )

    # 4. Message 3 (link preview card outgoing)
    t_m3 = start + dur(3.7)
    tweens.append(
        f'tl.fromTo("#{node_id}-m3",{{opacity:0,scale:0.9,y:15}},'
        f'{{opacity:1,scale:1,y:0,duration:{_num(dur(0.25))},ease:"power3.out"}},'
        f'{_num(t_m3)});'
    )

    # 5. Message 4 (Rachel reaction)
    t_m4 = start + dur(7.3)
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-60,duration:{_num(dur(0.35))},ease:"power2.out"}},'
        f'{_num(t_m4)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-m4",{{opacity:0,scale:0.75}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.16))},ease:"power2.out"}},'
        f'{_num(t_m4)});'
    )

    # 6. Message 5 (Emoji reaction)
    t_m5 = start + dur(8.03)
    tweens.append(
        f'tl.fromTo("#{node_id}-m5",{{opacity:0,scale:0.5}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.2))},ease:"back.out(1.8)"}},'
        f'{_num(t_m5)});'
    )

    # 7. Message 6 (benefit outgoing)
    t_m6 = start + dur(10.6)
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-140,duration:{_num(dur(0.35))},ease:"power2.out"}},'
        f'{_num(t_m6)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-m6",{{opacity:0,scale:0.75}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.16))},ease:"power2.out"}},'
        f'{_num(t_m6)});'
    )

    # 8. Message 7 (where did u find this incoming)
    t_m7 = start + dur(12.37)
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-220,duration:{_num(dur(0.35))},ease:"power2.out"}},'
        f'{_num(t_m7)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-m7",{{opacity:0,scale:0.75}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.16))},ease:"power2.out"}},'
        f'{_num(t_m7)});'
    )

    # 9. Message 8 (on heygen)
    t_m8 = start + dur(14.07)
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-290,duration:{_num(dur(0.35))},ease:"power2.out"}},'
        f'{_num(t_m8)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-m8",{{opacity:0,scale:0.75}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.16))},ease:"power2.out"}},'
        f'{_num(t_m8)});'
    )

    # 10. Message 9 (plain html tags)
    t_m9 = start + dur(17.1)
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-360,duration:{_num(dur(0.35))},ease:"power2.out"}},'
        f'{_num(t_m9)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-m9",{{opacity:0,scale:0.75}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.16))},ease:"power2.out"}},'
        f'{_num(t_m9)});'
    )

    # 11. Message 10 (code is yours)
    t_m10 = start + dur(19.9)
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-440,duration:{_num(dur(0.35))},ease:"power2.out"}},'
        f'{_num(t_m10)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-m10",{{opacity:0,scale:0.75}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.16))},ease:"power2.out"}},'
        f'{_num(t_m10)});'
    )

    # 12. Message 11 & 12 (installing rn & ty bestie)
    t_m11 = start + dur(20.67)
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-510,duration:{_num(dur(0.35))},ease:"power2.out"}},'
        f'{_num(t_m11)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-m11",{{opacity:0,scale:0.75}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.16))},ease:"power2.out"}},'
        f'{_num(t_m11)});'
    )

    t_m12 = start + dur(21.43)
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-580,duration:{_num(dur(0.35))},ease:"power2.out"}},'
        f'{_num(t_m12)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-m12",{{opacity:0,scale:0.75}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.16))},ease:"power2.out"}},'
        f'{_num(t_m12)});'
    )

    # 13. End card reveal
    t_ec = start + dur(23.27)
    tweens.append(
        f'tl.fromTo("#{node_id}-endcard",{{opacity:0,scale:0.95}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.35))},ease:"power2.out"}},'
        f'{_num(t_ec)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-cta",{{opacity:0,scale:0.85}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.25))},ease:"back.out(1.5)"}},'
        f'{_num(t_ec + dur(0.2))});'
    )

    contact_initial = (copy["contactName"][:1] or "R").upper()

    def _render_feat(feat_text: str) -> str:
        parts = feat_text.split("|", 1)
        top = _esc(parts[0])
        bot = _esc(parts[1]) if len(parts) > 1 else ""
        return f'<div class="mtr-feat"><div class="mtr-feat-top">{top}</div><div class="mtr-feat-bot">{bot}</div></div>'

    feats_html = "".join(_render_feat(copy[k]) for k in ("ecFeature1", "ecFeature2", "ecFeature3"))

    stars_svg = "".join(
        '<svg viewBox="0 0 24 24" width="28" height="28" fill="#ffd54f"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>'
        for _ in range(5)
    )

    node = (
        f'<div id="{node_id}" class="clip overlay message-thread-reveal" {_timing(ctx)}>'
        f'<div class="mtr-plate"></div>'
        f'<div class="mtr-phonebody">'
        f'<div class="mtr-screen">'
        # Status Bar
        f'<div class="mtr-statusbar">'
        f'<div class="mtr-sb-time">9:41</div>'
        f'<div class="mtr-sb-icons">'
        f'<svg width="28" height="18" viewBox="0 0 28 18" fill="#fff"><rect x="1" y="11" width="4" height="6" rx="1"/><rect x="7" y="8" width="4" height="9" rx="1"/><rect x="13" y="4" width="4" height="13" rx="1"/><rect x="19" y="0" width="4" height="17" rx="1"/></svg>'
        f'<svg width="32" height="16" viewBox="0 0 32 16" fill="none"><rect x="1" y="1" width="26" height="14" rx="4" stroke="#fff" stroke-width="2"/><rect x="3" y="3" width="18" height="10" rx="2" fill="#fff"/><path d="M29 6v4" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>'
        f'</div></div>'
        # Header
        f'<div class="mtr-header">'
        f'<div class="mtr-hdr-back"><svg width="24" height="34" viewBox="0 0 24 34" fill="none"><path d="M20 4L4 17l16 13" stroke="#0a80f8" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg><span class="mtr-hdr-badge">32</span></div>'
        f'<div class="mtr-hdr-contact">'
        f'<div class="mtr-hdr-avatar">{_esc(contact_initial)}</div>'
        f'<div class="mtr-hdr-name">{_esc(copy["contactName"])} <span class="mtr-chev">›</span></div>'
        f'</div>'
        f'<div class="mtr-hdr-cam"><svg width="36" height="28" viewBox="0 0 36 28" fill="#0a80f8"><rect x="2" y="2" width="24" height="24" rx="6"/><path d="M28 8l6-5v22l-6-5V8Z"/></svg></div>'
        f'</div>'
        # Chat Viewport
        f'<div class="mtr-chatview">'
        f'<div id="{node_id}-thread" class="mtr-thread">'
        # m1 (recv)
        f'<div id="{node_id}-m1" class="mtr-msg mtr-recv"><div class="mtr-bubble mtr-b-recv">{_esc(copy["questionMessage"])}</div></div>'
        # dots
        f'<div id="{node_id}-dots" class="mtr-msg mtr-recv" style="opacity:0"><div class="mtr-dots"><span class="mtr-dot"></span><span class="mtr-dot"></span><span class="mtr-dot"></span></div></div>'
        # m2 (sent)
        f'<div id="{node_id}-m2" class="mtr-msg mtr-sent" style="opacity:0"><div class="mtr-bubble mtr-b-sent">{_esc(copy["teaserMessage"])}</div></div>'
        # m3 (sent card)
        f'<div id="{node_id}-m3" class="mtr-msg mtr-sent" style="opacity:0">'
        f'<div class="mtr-card">'
        f'<div class="mtr-card-thumb"><svg width="48" height="48" viewBox="0 0 24 24" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" stroke="#fff" stroke-width="2"/><circle cx="8" cy="10" r="2" fill="#fff"/><path d="M21 15l-5-5-8 7" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg></div>'
        f'<div class="mtr-card-info">'
        f'<div class="mtr-card-title">{_esc(copy["cardTitle"])}</div>'
        f'<div class="mtr-card-domain">{_esc(copy["cardDomain"])}</div>'
        f'</div></div></div>'
        # m4 (recv reaction)
        f'<div id="{node_id}-m4" class="mtr-msg mtr-recv" style="opacity:0"><div class="mtr-bubble mtr-b-recv">{_esc(copy["reactionMessage"])}</div></div>'
        # m5 (recv emoji)
        f'<div id="{node_id}-m5" class="mtr-msg mtr-recv" style="opacity:0"><div class="mtr-emoji">{_esc(copy["reactionEmoji"])}</div></div>'
        # m6 (sent benefit)
        f'<div id="{node_id}-m6" class="mtr-msg mtr-sent" style="opacity:0"><div class="mtr-bubble mtr-b-sent">{_esc(copy["benefitMessage"])}</div></div>'
        # m7 (recv discovery)
        f'<div id="{node_id}-m7" class="mtr-msg mtr-recv" style="opacity:0"><div class="mtr-bubble mtr-b-recv">{_esc(copy["discoveryMessage"])}</div></div>'
        # m8 (sent source)
        f'<div id="{node_id}-m8" class="mtr-msg mtr-sent" style="opacity:0"><div class="mtr-bubble mtr-b-sent">{_esc(copy["sourceMessage"])}</div></div>'
        # m9 (sent workflow)
        f'<div id="{node_id}-m9" class="mtr-msg mtr-sent" style="opacity:0"><div class="mtr-bubble mtr-b-sent">{_esc(copy["workflowMessage"])}</div></div>'
        # m10 (sent ownership)
        f'<div id="{node_id}-m10" class="mtr-msg mtr-sent" style="opacity:0"><div class="mtr-bubble mtr-b-sent">{_esc(copy["ownershipMessage"])}</div></div>'
        # m11 (recv install)
        f'<div id="{node_id}-m11" class="mtr-msg mtr-recv" style="opacity:0"><div class="mtr-bubble mtr-b-recv">{_esc(copy["installMessage"])}</div></div>'
        # m12 (recv thanks)
        f'<div id="{node_id}-m12" class="mtr-msg mtr-recv" style="opacity:0"><div class="mtr-bubble mtr-b-recv">{_esc(copy["thanksMessage"])}</div></div>'
        f'</div>'  # end thread
        f'</div>'  # end chatview
        # Composer at bottom
        f'<div class="mtr-composer">'
        f'<div class="mtr-comp-plus"><svg width="24" height="24" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="11" fill="#8e8e93"/><path d="M12 7v10M7 12h10" stroke="#1c1c1e" stroke-width="2.5" stroke-linecap="round"/></svg></div>'
        f'<div class="mtr-comp-input"><span class="mtr-comp-ph">iMessage</span></div>'
        f'<div class="mtr-comp-mic"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><rect x="9" y="2" width="6" height="12" rx="3" fill="#8e8e93"/><path d="M5 10a7 7 0 0 0 14 0M12 17v4" stroke="#8e8e93" stroke-width="2.5" stroke-linecap="round"/></svg></div>'
        f'</div>'
        # End Card overlay
        f'<div id="{node_id}-endcard" class="mtr-endcard" style="opacity:0">'
        f'<div class="mtr-ec-logo"><span class="mtr-ec-logotext">{_esc(copy["contactName"])}</span></div>'
        f'<div class="mtr-ec-stars">{stars_svg}</div>'
        f'<div class="mtr-ec-proof">{_esc(copy["ecProof"])}</div>'
        f'<div class="mtr-ec-feats">{feats_html}</div>'
        f'<div id="{node_id}-cta" class="mtr-ec-cta">{_esc(copy["ecCta"])}</div>'
        f'</div>'
        f'</div>'  # end screen
        f'</div>'  # end phonebody
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def mtr_overlay_css() -> str:
    """CSS for Message Thread Reveal."""
    return (
        ".message-thread-reveal{position:absolute;inset:0;width:1080px;height:1920px;"
        "overflow:hidden;background:#000;font-family:Inter,system-ui,sans-serif;"
        "-webkit-font-smoothing:antialiased;color:#fff}"
        ".message-thread-reveal .mtr-plate{position:absolute;inset:0;"
        "background:radial-gradient(ellipse 90% 60% at 30% 20%,rgba(200,69,61,0.15) 0%,rgba(200,69,61,0) 60%),"
        "linear-gradient(168deg,#111214 0%,#0a0a0c 100%)}"
        ".message-thread-reveal .mtr-phonebody{position:absolute;left:124px;top:64px;width:832px;height:1797px;"
        "border-radius:112px;background:#3a3d42;box-shadow:inset 0 2px 3px rgba(255,255,255,0.25),0 40px 90px rgba(0,0,0,0.6)}"
        ".message-thread-reveal .mtr-screen{position:absolute;left:16px;top:16px;width:800px;height:1765px;"
        "border-radius:100px;background:#000;overflow:hidden}"
        ".message-thread-reveal .mtr-statusbar{position:absolute;top:0;left:0;right:0;height:110px;"
        "display:flex;align-items:center;justify-content:space-between;padding:0 60px;z-index:30}"
        ".message-thread-reveal .mtr-sb-time{font-size:34px;font-weight:600;color:#fff}"
        ".message-thread-reveal .mtr-sb-icons{display:flex;gap:14px;align-items:center}"
        ".message-thread-reveal .mtr-header{position:absolute;top:110px;left:0;right:0;height:140px;"
        "display:flex;align-items:center;justify-content:space-between;padding:0 44px;z-index:30;"
        "border-bottom:1px solid rgba(255,255,255,0.08)}"
        ".message-thread-reveal .mtr-hdr-back{display:flex;align-items:center;gap:10px}"
        ".message-thread-reveal .mtr-hdr-badge{padding:2px 14px;background:#262628;border-radius:16px;font-size:24px;color:#fff}"
        ".message-thread-reveal .mtr-hdr-contact{display:flex;flex-direction:column;align-items:center;gap:6px}"
        ".message-thread-reveal .mtr-hdr-avatar{width:72px;height:72px;border-radius:36px;background:#9ce474;"
        "color:#12300c;font-size:36px;font-weight:700;display:flex;align-items:center;justify-content:center}"
        ".message-thread-reveal .mtr-hdr-name{padding:4px 18px;background:#232325;border-radius:20px;font-size:24px;"
        "color:#fff;display:flex;align-items:center;gap:6px}"
        ".message-thread-reveal .mtr-chev{color:#8e8e93;font-size:20px}"
        ".message-thread-reveal .mtr-hdr-cam{width:48px;height:48px;display:flex;align-items:center;justify-content:center}"
        ".message-thread-reveal .mtr-chatview{position:absolute;left:0;top:260px;width:800px;height:1360px;overflow:hidden}"
        ".message-thread-reveal .mtr-thread{position:relative;padding:24px 36px 140px;display:flex;"
        "flex-direction:column;gap:20px;will-change:transform}"
        ".message-thread-reveal .mtr-msg{display:flex;width:100%}"
        ".message-thread-reveal .mtr-recv{justify-content:flex-start}"
        ".message-thread-reveal .mtr-sent{justify-content:flex-end}"
        ".message-thread-reveal .mtr-bubble{max-width:580px;padding:18px 26px;border-radius:32px;font-size:29px;"
        "line-height:38px;will-change:transform,opacity}"
        ".message-thread-reveal .mtr-b-recv{background:#242428;color:#fff;border-bottom-left-radius:8px}"
        ".message-thread-reveal .mtr-b-sent{background:#0a80f8;color:#fff;border-bottom-right-radius:8px}"
        ".message-thread-reveal .mtr-dots{background:#242428;padding:18px 24px;border-radius:28px;display:flex;gap:8px;align-items:center}"
        ".message-thread-reveal .mtr-dot{width:14px;height:14px;border-radius:7px;background:#8e8e93}"
        ".message-thread-reveal .mtr-card{max-width:580px;background:#1c1c1e;border:1px solid #333;"
        "border-radius:26px;overflow:hidden;display:flex;flex-direction:column}"
        ".message-thread-reveal .mtr-card-thumb{height:180px;background:#2a2b30;display:flex;align-items:center;justify-content:center}"
        ".message-thread-reveal .mtr-card-info{padding:18px 22px}"
        ".message-thread-reveal .mtr-card-title{font-size:24px;font-weight:600;color:#fff;line-height:30px}"
        ".message-thread-reveal .mtr-card-domain{font-size:18px;color:#8e8e93;margin-top:6px}"
        ".message-thread-reveal .mtr-emoji{font-size:72px;line-height:80px}"
        ".message-thread-reveal .mtr-composer{position:absolute;left:0;right:0;bottom:30px;height:90px;"
        "display:flex;align-items:center;gap:14px;padding:0 30px;z-index:30}"
        ".message-thread-reveal .mtr-comp-plus{width:44px;height:44px;display:flex;align-items:center;justify-content:center}"
        ".message-thread-reveal .mtr-comp-input{flex:1;height:56px;background:#1c1c1e;border:1px solid #3a3a3c;"
        "border-radius:28px;display:flex;align-items:center;padding:0 22px}"
        ".message-thread-reveal .mtr-comp-ph{font-size:26px;color:#8e8e93}"
        ".message-thread-reveal .mtr-comp-mic{width:44px;height:44px;display:flex;align-items:center;justify-content:center}"
        ".message-thread-reveal .mtr-endcard{position:absolute;inset:0;background:#111214;z-index:50;"
        "display:flex;flex-direction:column;align-items:center;justify-content:center;padding:60px 50px}"
        ".message-thread-reveal .mtr-ec-logo{margin-bottom:30px}"
        ".message-thread-reveal .mtr-ec-logotext{font-size:48px;font-weight:800;color:#fff;letter-spacing:-0.5px}"
        ".message-thread-reveal .mtr-ec-stars{display:flex;gap:10px;margin-bottom:16px}"
        ".message-thread-reveal .mtr-ec-proof{font-size:28px;color:#7A7D82;margin-bottom:50px}"
        ".message-thread-reveal .mtr-ec-feats{display:flex;gap:16px;margin-bottom:60px}"
        ".message-thread-reveal .mtr-feat{background:#1c1c1e;border:1px solid #2c2c2e;border-radius:20px;"
        "padding:20px 24px;text-align:center;min-width:180px}"
        ".message-thread-reveal .mtr-feat-top{font-size:24px;font-weight:700;color:#fff}"
        ".message-thread-reveal .mtr-feat-bot{font-size:20px;color:#7A7D82;margin-top:6px}"
        ".message-thread-reveal .mtr-ec-cta{width:100%;max-width:540px;height:84px;border-radius:42px;"
        "background:#C8453D;color:#fff;font-size:32px;font-weight:700;display:flex;align-items:center;"
        "justify-content:center;box-shadow:0 12px 30px rgba(200,69,61,0.45)}"
    )
