"""Claude Exchange — iPhone mock, Claude typing, tool search, streamed answer, citations.

Catalog ``claude-exchange`` writes ``textContent``, animates element heights,
and tweens width/filter. Here characters and words are pre-baked spans,
visibility is ``opacity`` / ``scale`` / ``y`` / ``scaleX`` / ``rotation``, layout is static HTML/SVG.
Claude dark theme (#20201f, #1c1c1b, #131313, #d97757). Inter font with serif typography.
"""

from __future__ import annotations

import re
from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_CLE_CATALOG = 21.4
_CLE_STAGE_SCALE = 2.1968  # 1920 / 874

_CLE_DEFAULTS = {
    "prompt": "What's the best tool for ai avatars?",
    "thinking": "Weighing accuracy against current market…",
    "lead": "I'll search for the current state of this space since AI avatar tools move fast.",
    "search": "best AI avatar video generator 2026",
    "answer1": "It depends on what you're making, but the field has consolidated fast and one platform now covers most of it.",
    "answer2": "**HeyGen** is where most teams land. Independent testing, not just vendor blogs, puts **Avatar IV** highest for talking-head realism, with facial micro-expressions and gesture control that hold up at a full-screen crop {HeyGen}. It also has the deepest enterprise adoption of the group, including a large share of the Fortune 100, which matters if you need the same presenter on brand across a year of campaigns.",
    "answer3": "By use case, the pieces shake out roughly like this:",
    "answer4": "**Marketing / hyper-realistic talking heads** → Avatar IV",
    "answer5": "**Enterprise training** → Video Translate for every locale",
    "answer6": "**UGC-style performance ads** → Instant Avatar from one selfie, then batch the variants",
    "answer7": "**Real-time conversational / interactive** → Interactive Avatar",
    "answer8": "**Custom digital twin from a selfie** → Instant Avatar in about five minutes",
    "answer9": "One distinction worth keeping in mind: a dedicated avatar platform optimizes the whole presenter workflow — script, voice, lip sync, translation, brand kit — whereas a general video model gives you cinematic scenes but takes far more skill to land the same person on camera twice.",
    "answer10": "Given your day job you probably have a sharper read than these roundups on where HeyGen actually leads versus where the reviews are being generous. Is this for a specific project, or comparing for positioning?",
}

_CLE_MAX = {
    "prompt": 80,
    "thinking": 60,
    "lead": 120,
    "search": 60,
    "answer": 350,
}


def _cle_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _cle_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = (
        "prompt", "thinking", "lead", "search", "answer1", "answer2",
        "userMessage", "title", "snippet", "domain",
    )
    return any(str(params.get(k) or "").strip() for k in keys)


def _cle_copy(params: dict[str, Any]) -> dict[str, Any]:
    prompt = params.get("prompt") or params.get("userMessage") or params.get("title") or _CLE_DEFAULTS["prompt"]
    ans2 = params.get("answer2") or _CLE_DEFAULTS["answer2"]
    if params.get("domain") and "{HeyGen}" in ans2:
        ans2 = ans2.replace("HeyGen", str(params.get("domain")))
    return {
        "prompt": _cle_clip(prompt, _CLE_DEFAULTS["prompt"], _CLE_MAX["prompt"]),
        "thinking": _cle_clip(params.get("thinking"), _CLE_DEFAULTS["thinking"], _CLE_MAX["thinking"]),
        "lead": _cle_clip(params.get("lead"), _CLE_DEFAULTS["lead"], _CLE_MAX["lead"]),
        "search": _cle_clip(params.get("search"), _CLE_DEFAULTS["search"], _CLE_MAX["search"]),
        "answer1": _cle_clip(params.get("answer1"), _CLE_DEFAULTS["answer1"], _CLE_MAX["answer"]),
        "answer2": _cle_clip(ans2, _CLE_DEFAULTS["answer2"], _CLE_MAX["answer"]),
        "answer3": _cle_clip(params.get("answer3"), _CLE_DEFAULTS["answer3"], _CLE_MAX["answer"]),
        "answer4": _cle_clip(params.get("answer4"), _CLE_DEFAULTS["answer4"], _CLE_MAX["answer"]),
        "answer5": _cle_clip(params.get("answer5"), _CLE_DEFAULTS["answer5"], _CLE_MAX["answer"]),
        "answer6": _cle_clip(params.get("answer6"), _CLE_DEFAULTS["answer6"], _CLE_MAX["answer"]),
        "answer7": _cle_clip(params.get("answer7"), _CLE_DEFAULTS["answer7"], _CLE_MAX["answer"]),
        "answer8": _cle_clip(params.get("answer8"), _CLE_DEFAULTS["answer8"], _CLE_MAX["answer"]),
        "answer9": _cle_clip(params.get("answer9"), _CLE_DEFAULTS["answer9"], _CLE_MAX["answer"]),
        "answer10": _cle_clip(params.get("answer10"), _CLE_DEFAULTS["answer10"], _CLE_MAX["answer"]),
    }


def _cle_burst(size: int, color: str) -> str:
    rays = "".join(
        f'<rect x="10.85" y="1.1" width="2.3" height="21.8" rx="1.15" fill="{color}" transform="rotate({i * 30} 12 12)"/>'
        for i in range(12)
    )
    return f'<svg viewBox="0 0 24 24" width="{size}" height="{size}">{rays}</svg>'


_CLE_BELL = (
    '<svg viewBox="0 0 20 20" width="18" height="18" fill="none">'
    '<path d="M4.2 15h11.6M10 3.2a4.3 4.3 0 0 1 4.3 4.3c0 3.4 1 5 1.5 5.6H4.2'
    'C4.7 12.5 5.7 10.9 5.7 7.5A4.3 4.3 0 0 1 10 3.2Z" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/>'
    '<path d="M8.3 16.6a1.9 1.9 0 0 0 3.4 0" stroke="#fff" stroke-width="1.5"/>'
    '<path d="M3 17L17 3" stroke="#fff" stroke-width="1.6"/>'
    '</svg>'
)
_CLE_BARS = (
    '<svg viewBox="0 0 20 20" width="16" height="16" fill="none">'
    '<rect x="1" y="12.5" width="3" height="4.5" rx="1" fill="#fff"/>'
    '<rect x="6" y="9.5" width="3" height="7.5" rx="1" fill="#fff"/>'
    '<rect x="11" y="6.5" width="3" height="10.5" rx="1" fill="#fff"/>'
    '<rect x="16" y="3.5" width="3" height="13.5" rx="1" fill="rgba(255,255,255,.32)"/>'
    '</svg>'
)
_CLE_BURGER = (
    '<svg viewBox="0 0 24 24" width="22" height="22" fill="none">'
    '<path d="M5 9.5h14M5 15h9" stroke="#e8e8e0" stroke-width="2.1" stroke-linecap="round"/>'
    '</svg>'
)
_CLE_GHOST = (
    '<svg viewBox="0 0 24 24" width="24" height="24" fill="none">'
    '<path d="M5 20.4V11a7 7 0 0 1 14 0v9.4l-2.3-1.6-2.3 1.6-2.4-1.6-2.3 1.6-2.4-1.6L5 20.4Z" stroke="#e8e8e0" stroke-width="1.7" stroke-linejoin="round"/>'
    '<circle cx="9.4" cy="11.2" r="1.15" fill="#e8e8e0"/><circle cx="14.6" cy="11.2" r="1.15" fill="#e8e8e0"/>'
    '</svg>'
)
_CLE_DOTS = (
    '<svg viewBox="0 0 24 24" width="21" height="21" fill="none">'
    '<circle cx="5" cy="12" r="1.9" fill="#e8e8e0"/><circle cx="12" cy="12" r="1.9" fill="#e8e8e0"/><circle cx="19" cy="12" r="1.9" fill="#e8e8e0"/>'
    '</svg>'
)
_CLE_PLUS = (
    '<svg viewBox="0 0 24 24" width="17" height="17" fill="none">'
    '<path d="M12 4.8v14.4M4.8 12h14.4" stroke="#f0f0e8" stroke-width="2" stroke-linecap="round"/>'
    '</svg>'
)
_CLE_MIC = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none">'
    '<rect x="9.2" y="2.8" width="5.6" height="11" rx="2.8" stroke="#e8e8e0" stroke-width="1.8"/>'
    '<path d="M5.8 11.2a6.2 6.2 0 0 0 12.4 0M12 17.6v3.2" stroke="#e8e8e0" stroke-width="1.8" stroke-linecap="round"/>'
    '</svg>'
)
_CLE_ARROW_UP = (
    '<svg viewBox="0 0 24 24" width="19" height="19" fill="none">'
    '<path d="M12 19V5.6M5.8 11.8 12 5.4l6.2 6.4" stroke="#20201f" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)
_CLE_STOP = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none">'
    '<rect x="7" y="7" width="10" height="10" rx="2" fill="#20201f"/>'
    '</svg>'
)
_CLE_CHEV_DOWN = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none">'
    '<path d="M12 5v13M6.2 12.2 12 18.2l5.8-6" stroke="#fff" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)
_CLE_CHEV_RIGHT = (
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none">'
    '<path d="M9 5l7 7-7 7" stroke="#94948c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)
_CLE_SEARCH = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none">'
    '<circle cx="11" cy="11" r="7" stroke="#94948c" stroke-width="2"/>'
    '<path d="M20 20l-4-4" stroke="#94948c" stroke-width="2" stroke-linecap="round"/>'
    '</svg>'
)
_CLE_SPARKLE = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none">'
    '<path d="M12 2l2.4 6.8L21 11.2l-6.6 2.4L12 20.4l-2.4-6.8L3 11.2l6.6-2.4L12 2Z" stroke="#94948c" stroke-width="1.8" stroke-linejoin="round"/>'
    '</svg>'
)
_CLE_COPY = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none">'
    '<rect x="9" y="9" width="11" height="11" rx="2" stroke="#94948c" stroke-width="1.8"/>'
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" stroke="#94948c" stroke-width="1.8"/>'
    '</svg>'
)
_CLE_THUMB_UP = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none">'
    '<path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11a2 2 0 0 0 2-1.7l1.3-8.5A2 2 0 0 0 19.3 9H14Z" stroke="#94948c" stroke-width="1.8" stroke-linejoin="round"/>'
    '<path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" stroke="#94948c" stroke-width="1.8"/>'
    '</svg>'
)
_CLE_SHIFT = (
    '<svg viewBox="0 0 24 24" width="19" height="19" fill="none">'
    '<path d="M12 4 4.5 12h4v7h7v-7h4L12 4Z" stroke="#fff" stroke-width="1.7" stroke-linejoin="round" fill="#fff"/>'
    '</svg>'
)
_CLE_DEL = (
    '<svg viewBox="0 0 24 24" width="22" height="22" fill="none">'
    '<path d="M8.4 5h11a1.6 1.6 0 0 1 1.6 1.6v10.8A1.6 1.6 0 0 1 19.4 19h-11L2.6 12 8.4 5Z" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/>'
    '<path d="M11.4 9.6l5.2 4.8M16.6 9.6l-5.2 4.8" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>'
    '</svg>'
)
_CLE_RET = (
    '<svg viewBox="0 0 24 24" width="21" height="21" fill="none">'
    '<path d="M20 6v6.4H5.4M9.6 8.4 5 12.8l4.6 4.4" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)
_CLE_EMOJI_KEY = (
    '<svg viewBox="0 0 24 24" width="25" height="25" fill="none">'
    '<circle cx="12" cy="12" r="9" stroke="#fff" stroke-width="1.7"/>'
    '<circle cx="9" cy="10" r="1.2" fill="#fff"/>'
    '<circle cx="15" cy="10" r="1.2" fill="#fff"/>'
    '<path d="M8 14.6a5 5 0 0 0 8 0" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/>'
    '</svg>'
)


def _cle_keys_html(node_id: str) -> tuple[str, dict[str, str]]:
    kb_w = 33.44
    kb_gap = 6.03
    kb_inset = 6.67
    parts: list[str] = []
    key_targets: dict[str, str] = {}

    rows_def = [
        (52, "QWERTYUIOP", kb_inset),
        (106, "ASDFGHJKL", 26.33),
        (160, "ZXCVBNM", 65.67),
    ]
    for top, letters, x0 in rows_def:
        parts.append(f'<div class="cle-krow" style="top:{top}px">')
        for i, ch in enumerate(letters):
            x = x0 + i * (kb_w + kb_gap)
            kid = f"{node_id}-k-{ch}"
            key_targets[ch] = kid
            parts.append(
                f'<div id="{kid}" class="cle-key" style="left:{x:.2f}px;width:{kb_w:.2f}px">'
                f'{_esc(ch)}</div>'
            )
        if top == 160:
            parts.append(
                f'<div class="cle-key cle-kdark" style="left:{kb_inset}px;width:45.33px">{_CLE_SHIFT}</div>'
                f'<div class="cle-key cle-kdark" style="left:350px;width:45.67px">{_CLE_DEL}</div>'
            )
        parts.append('</div>')

    space_id = f"{node_id}-k-space"
    key_targets[" "] = space_id
    parts.append(
        '<div class="cle-krow" style="top:214px">'
        f'<div class="cle-key cle-kdark cle-ksmall" style="left:{kb_inset}px;width:92.67px">123</div>'
        f'<div id="{space_id}" class="cle-key" style="left:105.33px;width:191.33px"></div>'
        f'<div class="cle-key cle-kdark" style="left:302.67px;width:93px">{_CLE_RET}</div>'
        '</div>'
        f'<div class="cle-kb-bottom"><div>{_CLE_EMOJI_KEY}</div><div>{_CLE_MIC}</div></div>'
    )
    return "".join(parts), key_targets


def ov_claude_exchange(ctx: TemplateCtx) -> Piece:
    """Claude Exchange: prompt typing, send bubble, reasoning, streamed answer and footer."""
    if not _cle_has_copy(ctx.params):
        return Piece()

    copy = _cle_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 3.0)
    scale = duration / _CLE_CATALOG

    def dur(catalog_sec: float) -> float:
        return max(0.001, catalog_sec * scale)

    prompt_text = copy["prompt"]
    tweens: list[str] = []

    # 1. Empty state arrives
    tweens.append(
        f'tl.fromTo("#{node_id}-empty-mark",{{opacity:0,scale:0.72}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.5))},ease:"power3.out"}},'
        f'{_num(start)});'
    )
    for i in range(5):
        tweens.append(
            f'tl.fromTo("#{node_id}-ehw-{i}",{{opacity:0,y:12}},'
            f'{{opacity:1,y:0,duration:{_num(dur(0.42))},ease:"power3.out"}},'
            f'{_num(start + dur(0.12 + i * 0.055))});'
        )

    # 2. Typing start
    t0 = dur(0.86)
    tweens.append(
        f'tl.to("#{node_id}-comp-ph",{{opacity:0,duration:{_num(dur(0.12))}}},'
        f'{_num(start + t0 - dur(0.02))});'
    )
    tweens.append(
        f'tl.set("#{node_id}-cur-0",{{opacity:1}},{_num(start + t0 - dur(0.02))});'
    )
    tweens.append(
        f'tl.to("#{node_id}-voice-btn",{{opacity:0,scale:0.6,duration:{_num(dur(0.14))}}},'
        f'{_num(start + t0)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-send-btn",{{opacity:0,scale:0.6}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.24))},ease:"back.out(1.6)"}},'
        f'{_num(start + t0 + dur(0.04))});'
    )

    # Keystrokes
    char_base = dur(0.05)
    space_hold = dur(0.11)
    char_t: list[float] = []
    curr_t = t0
    for ch in prompt_text:
        char_t.append(curr_t)
        curr_t += (char_base + space_hold) if ch == " " else char_base
    type_end = curr_t

    keys_markup, key_targets = _cle_keys_html(node_id)

    shift_amount = 0.0
    for i, ch in enumerate(prompt_text):
        ct = start + char_t[i]
        tweens.append(f'tl.set("#{node_id}-ch-{i}",{{opacity:1}},{_num(ct)});')
        tweens.append(f'tl.set("#{node_id}-cur-{i}",{{opacity:0}},{_num(ct)});')
        tweens.append(f'tl.set("#{node_id}-cur-{i + 1}",{{opacity:1}},{_num(ct)});')

        if i > 22:
            shift_amount += 7.2
            tweens.append(
                f'tl.to("#{node_id}-typed",{{x:-{shift_amount:.1f},duration:{_num(dur(0.08))},ease:"none"}},{_num(ct)});'
            )

        target_key = key_targets.get(ch.upper() if ch != " " else " ")
        if target_key:
            tweens.append(
                f'tl.to("#{target_key}",{{backgroundColor:"#5f5f5f",duration:{_num(dur(0.04))}}},'
                f'{_num(ct - dur(0.03))});'
            )
            tweens.append(
                f'tl.to("#{target_key}",{{backgroundColor:"#404040",duration:{_num(dur(0.09))}}},'
                f'{_num(ct + dur(0.02))});'
            )

    # Caret blink
    t_blink = start + type_end + dur(0.1)
    t_send = start + type_end + dur(0.3)
    blink_idx = 0
    while t_blink < t_send:
        tweens.append(
            f'tl.set("#{node_id}-cur-{len(prompt_text)}",{{opacity:{0 if blink_idx % 2 == 0 else 1}}},'
            f'{_num(t_blink)});'
        )
        t_blink += dur(0.35)
        blink_idx += 1

    # 3. Send action
    tweens.append(
        f'tl.set("#{node_id}-cur-{len(prompt_text)}",{{opacity:0}},{_num(t_send)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-send-btn",{{scale:0.86,duration:{_num(dur(0.06))},ease:"power2.out"}},{_num(t_send)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-send-btn",{{scale:1,duration:{_num(dur(0.18))},ease:"power2.out"}},{_num(t_send + dur(0.06))});'
    )

    t_go = t_send + dur(0.03)
    tweens.append(
        f'tl.fromTo("#{node_id}-keyboard",{{y:0}},'
        f'{{y:340,duration:{_num(dur(0.3))},ease:"power2.out"}},{_num(t_go)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-composer",{{y:-309}},'
        f'{{y:0,duration:{_num(dur(0.3))},ease:"power2.out"}},{_num(t_go)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-typed",{{opacity:0,x:0,duration:{_num(dur(0.08))}}},'
        f'{_num(t_go)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-comp-ph2",{{opacity:1,duration:{_num(dur(0.2))}}},'
        f'{_num(t_go + dur(0.14))});'
    )
    tweens.append(
        f'tl.to("#{node_id}-send-btn",{{opacity:0,duration:{_num(dur(0.12))}}},'
        f'{_num(t_go + dur(0.24))});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-stop-btn",{{opacity:0,scale:0.6}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.2))},ease:"power2.out"}},'
        f'{_num(t_go + dur(0.3))});'
    )

    # Empty state leaves
    tweens.append(
        f'tl.to("#{node_id}-empty-mark",{{opacity:0,scale:0.8,duration:{_num(dur(0.22))},ease:"power2.in"}},'
        f'{_num(t_go)});'
    )
    for i in range(5):
        tweens.append(
            f'tl.to("#{node_id}-ehw-{i}",{{opacity:0,y:-10,duration:{_num(dur(0.2))},ease:"power2.in"}},'
            f'{_num(t_go + dur(i * 0.02))});'
        )

    # Header incognito to action dots
    tweens.append(
        f'tl.to("#{node_id}-hdr-ghost",{{opacity:0,duration:{_num(dur(0.12))}}},'
        f'{_num(t_go + dur(0.02))});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-hdr-actions",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.18))}}},'
        f'{_num(t_go + dur(0.16))});'
    )

    # Bubble pops into thread
    tweens.append(
        f'tl.fromTo("#{node_id}-bubble",{{opacity:0,y:260,scale:0.94}},'
        f'{{opacity:1,y:0,scale:1,duration:{_num(dur(0.34))},ease:"power3.out"}},'
        f'{_num(t_go + dur(0.02))});'
    )

    # 4. Claude Reasoning & tools
    tw = t_go + dur(0.34 + 0.45)
    tweens.append(
        f'tl.fromTo("#{node_id}-spin-wrap",{{opacity:0,scale:0.6}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.26))},ease:"power3.out"}},'
        f'{_num(tw)});'
    )

    # Spinner turns
    for turn in range(12):
        t_spin = tw + dur(turn * 0.5)
        rot = (turn + 1) * 30
        sc = 1.0 if turn % 2 == 0 else 0.8
        tweens.append(
            f'tl.to("#{node_id}-spinner",{{rotation:{rot},scale:{sc},duration:{_num(dur(0.5))},ease:"sine.inOut"}},'
            f'{_num(t_spin)});'
        )

    # Tool step: thinking
    tw += dur(0.4)
    tweens.append(
        f'tl.fromTo("#{node_id}-box-think",{{opacity:0,y:8}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.26))},ease:"power2.out"}},'
        f'{_num(tw)});'
    )
    tw += dur(0.4)

    # Lead words
    lead_words = copy["lead"].split()
    for wid, w in enumerate(lead_words):
        tweens.append(
            f'tl.fromTo("#{node_id}-lw-{wid}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(dur(0.09))}}},'
            f'{_num(tw + wid * dur(0.06))});'
        )
    tw += dur(len(lead_words) * 0.06 + 0.2)

    # Tool step: search
    tweens.append(
        f'tl.fromTo("#{node_id}-box-search",{{opacity:0,y:8}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.26))},ease:"power2.out"}},'
        f'{_num(tw)});'
    )
    tw += dur(0.6)

    # Collapse tool steps into "2 steps"
    tweens.append(
        f'tl.to("#{node_id}-tools-full",{{opacity:0,y:-8,duration:{_num(dur(0.2))},ease:"power2.in"}},'
        f'{_num(tw)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-box-collapsed",{{opacity:0,y:6}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.26))},ease:"power2.out"}},'
        f'{_num(tw + dur(0.14))});'
    )
    tw += dur(0.4)

    # Notice fades out
    tweens.append(
        f'tl.to("#{node_id}-notice",{{opacity:0,duration:{_num(dur(0.16))}}},'
        f'{_num(tw)});'
    )
    tw += dur(0.25)

    # 5. Answer stream
    word_step = dur(0.06)

    # Section 1: answer1
    p1_words = copy["answer1"].split()
    for wid, w in enumerate(p1_words):
        tweens.append(
            f'tl.fromTo("#{node_id}-ans1-w{wid}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(dur(0.08))}}},'
            f'{_num(tw)});'
        )
        tw += word_step

    tw += dur(0.12)
    # Scroll thread slightly
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-45,duration:{_num(dur(0.55))},ease:"power2.out"}},'
        f'{_num(tw)});'
    )

    # Section 2: answer2 (HeyGen focus)
    p2_raw_words = copy["answer2"].split()
    for wid, w in enumerate(p2_raw_words):
        tweens.append(
            f'tl.fromTo("#{node_id}-ans2-w{wid}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(dur(0.08))}}},'
            f'{_num(tw)});'
        )
        tw += word_step

    # Section 3: answer3 + bullets 4..8
    tw += dur(0.15)
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-110,duration:{_num(dur(0.65))},ease:"power2.out"}},'
        f'{_num(tw)});'
    )
    p3_words = copy["answer3"].split()
    for wid, w in enumerate(p3_words):
        tweens.append(
            f'tl.fromTo("#{node_id}-ans3-w{wid}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(dur(0.08))}}},'
            f'{_num(tw)});'
        )
        tw += word_step

    bullets = [copy["answer4"], copy["answer5"], copy["answer6"], copy["answer7"], copy["answer8"]]
    for b_idx, bul in enumerate(bullets):
        tw += dur(0.08)
        tweens.append(
            f'tl.fromTo("#{node_id}-bul-{b_idx}",{{opacity:0,y:6}},'
            f'{{opacity:1,y:0,duration:{_num(dur(0.16))},ease:"power2.out"}},'
            f'{_num(tw)});'
        )
        bul_words = bul.split()
        for wid, w in enumerate(bul_words):
            tweens.append(
                f'tl.fromTo("#{node_id}-bulw-{b_idx}-{wid}",{{opacity:0}},'
                f'{{opacity:1,duration:{_num(dur(0.08))}}},'
                f'{_num(tw)});'
            )
            tw += word_step

    # Section 4: answer9 & answer10
    tw += dur(0.12)
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-175,duration:{_num(dur(0.65))},ease:"power2.out"}},'
        f'{_num(tw)});'
    )
    p9_words = copy["answer9"].split()
    for wid, w in enumerate(p9_words[:16]):  # stream first portion
        tweens.append(
            f'tl.fromTo("#{node_id}-ans9-w{wid}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(dur(0.08))}}},'
            f'{_num(tw)});'
        )
        tw += word_step

    # 6. Stream completes, controls revert, footer arrives
    tw += dur(0.3)
    tweens.append(
        f'tl.to("#{node_id}-stop-btn",{{opacity:0,duration:{_num(dur(0.14))}}},'
        f'{_num(tw)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-voice-btn",{{opacity:0,scale:0.6}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.22))},ease:"power2.out"}},'
        f'{_num(tw + dur(0.06))});'
    )
    tweens.append(
        f'tl.to("#{node_id}-spin-wrap",{{opacity:0,scale:0.7,duration:{_num(dur(0.2))},ease:"power2.in"}},'
        f'{_num(tw)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-actions-box",{{opacity:0,y:8}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.3))},ease:"power2.out"}},'
        f'{_num(tw + dur(0.18))});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-disclaim-box",{{opacity:0,y:8}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.3))},ease:"power2.out"}},'
        f'{_num(tw + dur(0.35))});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-chev-btn",{{opacity:0,y:10,scale:0.7}},'
        f'{{opacity:1,y:0,scale:1,duration:{_num(dur(0.3))},ease:"back.out(1.5)"}},'
        f'{_num(tw + dur(0.45))});'
    )

    # Rollover minute
    t_clock = start + dur(8.4)
    tweens.append(
        f'tl.set("#{node_id}-clock-early",{{opacity:0}},{_num(t_clock)});'
    )
    tweens.append(
        f'tl.set("#{node_id}-clock-late",{{opacity:1}},{_num(t_clock)});'
    )

    # HTML Structure
    typed_spans = []
    for i, ch in enumerate(prompt_text):
        shown = " " if ch == " " else _esc(ch)
        typed_spans.append(f'<span id="{node_id}-cur-{i}" class="cle-cur"><i></i></span>')
        typed_spans.append(f'<span id="{node_id}-ch-{i}" class="cle-ch">{shown}</span>')
    typed_spans.append(f'<span id="{node_id}-cur-{len(prompt_text)}" class="cle-cur"><i></i></span>')

    lead_spans = " ".join(
        f'<span id="{node_id}-lw-{i}" class="cle-w">{_esc(w)}</span>'
        for i, w in enumerate(lead_words)
    )

    def _render_bold_tokens(text: str, prefix: str) -> str:
        tokens = text.split()
        spans = []
        in_b = False
        for wid, tok in enumerate(tokens):
            clean = tok
            if clean.startswith("**"):
                in_b = True
                clean = clean[2:]
            has_e = clean.endswith("**")
            if has_e:
                clean = clean[:-2]
            extra = " cle-bold" if in_b else ""
            if "{HeyGen}" in clean:
                clean = clean.replace("{HeyGen}", '<span class="cle-cite">HeyGen</span>')
            else:
                clean = _esc(clean)
            spans.append(f'<span id="{node_id}-{prefix}-w{wid}" class="cle-w{extra}">{clean}</span>')
            if has_e:
                in_b = False
        return " ".join(spans)

    ans1_spans = _render_bold_tokens(copy["answer1"], "ans1")
    ans2_spans = _render_bold_tokens(copy["answer2"], "ans2")
    ans3_spans = _render_bold_tokens(copy["answer3"], "ans3")
    ans9_spans = _render_bold_tokens(" ".join(copy["answer9"].split()[:16]) + "…", "ans9")

    bullets_markup = []
    for b_idx, bul in enumerate(bullets):
        b_spans = _render_bold_tokens(bul, f"bulw-{b_idx}")
        bullets_markup.append(
            f'<div id="{node_id}-bul-{b_idx}" class="cle-bul">{b_spans}</div>'
        )

    empty_words = ["What", "can", "we", "tackle", "together?"]
    empty_markup = " ".join(
        f'<span id="{node_id}-ehw-{i}" class="cle-ehw">{w}</span>'
        for i, w in enumerate(empty_words)
    )

    node = (
        f'<div id="{node_id}" class="clip overlay claude-exchange" {_timing(ctx)}>'
        f'<div class="cle-stage">'
        f'<div class="cle-screen" id="{node_id}-screen">'
        # Status Bar
        f'<div class="cle-statusbar">'
        f'<div class="cle-sb-left">'
        f'<div class="cle-sb-clock">'
        f'<span id="{node_id}-clock-early">2:36</span>'
        f'<span id="{node_id}-clock-late" style="opacity:0">2:37</span>'
        f'</div></div>'
        f'<div class="cle-sb-right">'
        f'<div class="cle-sb-net">{_CLE_BARS}</div>'
        f'<div class="cle-sb-batt">87</div>'
        f'<div class="cle-sb-batt-cap"></div>'
        f'</div></div>'
        # Header Scrim & Bar
        f'<div class="cle-hdr-scrim"></div>'
        f'<div class="cle-header">'
        f'<div class="cle-circle-btn cle-hdr-left">{_CLE_BURGER}</div>'
        f'<div id="{node_id}-hdr-right" class="cle-hdr-right">'
        f'<div id="{node_id}-hdr-ghost" class="cle-hdr-face">{_CLE_GHOST}</div>'
        f'<div id="{node_id}-hdr-actions" class="cle-hdr-face" style="opacity:0">{_CLE_DOTS}</div>'
        f'</div></div>'
        # Scrollable Thread Area
        f'<div class="cle-scrollport">'
        f'<div id="{node_id}-thread" class="cle-thread">'
        # Empty State
        f'<div class="cle-empty">'
        f'<div id="{node_id}-empty-mark" class="cle-empty-mark">{_cle_burst(36, "#d97757")}</div>'
        f'<div class="cle-empty-head">{empty_markup}</div>'
        f'</div>'
        # User Message Bubble
        f'<div id="{node_id}-bubble" class="cle-bubble" style="opacity:0">'
        f'{_esc(prompt_text)}'
        f'</div>'
        # Claude Working / Tool Rows
        f'<div class="cle-claude-reply">'
        f'<div id="{node_id}-spin-wrap" class="cle-spin-wrap" style="opacity:0">'
        f'<div id="{node_id}-spinner" class="cle-spinner">{_cle_burst(24, "#d97757")}</div>'
        f'</div>'
        f'<div id="{node_id}-tools-full" class="cle-tools-full">'
        f'<div id="{node_id}-box-think" class="cle-tool-row" style="opacity:0">'
        f'<div class="cle-tool-ico">{_CLE_SPARKLE}</div>'
        f'<div>{_esc(copy["thinking"])}</div>'
        f'<div class="cle-chev">{_CLE_CHEV_RIGHT}</div>'
        f'</div>'
        f'<div class="cle-lead-para">{lead_spans}</div>'
        f'<div id="{node_id}-box-search" class="cle-tool-row" style="opacity:0">'
        f'<div class="cle-tool-ico">{_CLE_SEARCH}</div>'
        f'<div>{_esc(copy["search"])}</div>'
        f'<div class="cle-chev">{_CLE_CHEV_RIGHT}</div>'
        f'</div>'
        f'</div>'
        f'<div id="{node_id}-box-collapsed" class="cle-tool-row cle-collapsed" style="opacity:0">'
        f'<div class="cle-tool-ico">{_CLE_SPARKLE}</div>'
        f'<div>2 steps</div>'
        f'<div class="cle-chev">{_CLE_CHEV_RIGHT}</div>'
        f'</div>'
        # Streamed Answer
        f'<div class="cle-answer">'
        f'<div class="cle-para">{ans1_spans}</div>'
        f'<div class="cle-para">{ans2_spans}</div>'
        f'<div class="cle-para">{ans3_spans}</div>'
        f'{" ".join(bullets_markup)}'
        f'<div class="cle-para">{ans9_spans}</div>'
        f'</div>'
        # End Actions & Disclaimer
        f'<div id="{node_id}-actions-box" class="cle-actions" style="opacity:0">'
        f'<div class="cle-act-ico">{_CLE_COPY}</div>'
        f'<div class="cle-act-ico">{_CLE_THUMB_UP}</div>'
        f'<div class="cle-src-stack">'
        f'<div class="cle-src-dot" style="background:#1b6ac9">H</div>'
        f'<div class="cle-src-dot" style="background:#2b7fff">G</div>'
        f'<div class="cle-src-dot" style="background:#0f4fa8">F</div>'
        f'</div>'
        f'<div class="cle-src-label">7 sources</div>'
        f'</div>'
        f'<div id="{node_id}-disclaim-box" class="cle-disclaim" style="opacity:0">'
        f'<div class="cle-disclaim-mark">{_cle_burst(26, "#94948c")}</div>'
        f'<div class="cle-disclaim-text">Claude is AI and can make mistakes.<br/>Please double-check responses.</div>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</div>'
        # Floating Scroll Down Chevron
        f'<div class="cle-chev-wrap">'
        f'<div id="{node_id}-chev-btn" class="cle-chev-btn" style="opacity:0">{_CLE_CHEV_DOWN}</div>'
        f'</div>'
        # Composer
        f'<div class="cle-comp-scrim"></div>'
        f'<div id="{node_id}-composer" class="cle-composer">'
        f'<div id="{node_id}-notice" class="cle-notice">'
        f'<div class="cle-notice-dot"></div>'
        f'<div>Opus consumes usage limits faster than other models</div>'
        f'</div>'
        f'<div class="cle-model-pill">'
        f'<div class="cle-model-star">{_cle_burst(14, "#d97757")}</div>'
        f'<div class="cle-model-name">Opus 4.8</div>'
        f'<div class="cle-model-effort">High</div>'
        f'</div>'
        f'<div class="cle-comp-input-row">'
        f'<div class="cle-comp-plus">{_CLE_PLUS}</div>'
        f'<div class="cle-comp-field">'
        f'<div id="{node_id}-comp-ph" class="cle-comp-ph">Chat with Claude</div>'
        f'<div id="{node_id}-comp-ph2" class="cle-comp-ph" style="opacity:0">Reply to Claude</div>'
        f'<div id="{node_id}-typed" class="cle-comp-typed">{" ".join(typed_spans)}</div>'
        f'</div>'
        f'<div id="{node_id}-voice-btn" class="cle-comp-circle-btn">{_CLE_MIC}</div>'
        f'<div id="{node_id}-send-btn" class="cle-comp-send-btn" style="opacity:0">{_CLE_ARROW_UP}</div>'
        f'<div id="{node_id}-stop-btn" class="cle-comp-stop-btn" style="opacity:0">{_CLE_STOP}</div>'
        f'</div>'
        f'</div>'
        # iOS Keyboard
        f'<div id="{node_id}-keyboard" class="cle-keyboard">{keys_markup}</div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def cle_overlay_css() -> str:
    """CSS styles for Claude Exchange mobile interface."""
    return (
        ".claude-exchange{position:absolute;inset:0;width:1080px;height:1920px;"
        "overflow:hidden;background:#20201f;font-family:Inter,system-ui,sans-serif;"
        "-webkit-font-smoothing:antialiased;color:#f8f8f4}"
        ".claude-exchange .cle-stage{position:absolute;inset:0;background:#20201f}"
        ".claude-exchange .cle-screen{position:absolute;top:0;left:50%;width:402px;height:874px;"
        "margin-left:-201px;background:#20201f;overflow:hidden;transform-origin:top center;"
        f"transform:scale({_CLE_STAGE_SCALE})"
        ".claude-exchange .cle-statusbar{position:absolute;top:0;left:0;right:0;height:65px;"
        "z-index:40;display:flex;align-items:center;padding:0 34px 0 16px;color:#fff}"
        ".claude-exchange .cle-sb-left{display:flex;align-items:center;margin-left:32px}"
        ".claude-exchange .cle-sb-clock{font-size:17.2px;font-weight:600;letter-spacing:1.3px;"
        "position:relative;width:42px;height:22px}"
        ".claude-exchange .cle-sb-clock span{position:absolute;left:0;top:0;white-space:nowrap}"
        ".claude-exchange .cle-sb-right{display:flex;align-items:center;gap:5px;margin-left:auto}"
        ".claude-exchange .cle-sb-batt{width:30px;height:15px;border-radius:4.5px;background:#fff;"
        "color:#000;font-size:11px;font-weight:600;display:flex;align-items:center;"
        "justify-content:center;letter-spacing:-0.2px}"
        ".claude-exchange .cle-sb-batt-cap{width:2px;height:6px;background:rgba(255,255,255,0.45);"
        "border-radius:0 2px 2px 0;margin-left:-4px}"
        ".claude-exchange .cle-hdr-scrim{position:absolute;top:0;left:0;right:0;height:112px;"
        "z-index:30;background:linear-gradient(to bottom,rgba(32,32,31,0.92) 46%,rgba(32,32,31,0) 100%)}"
        ".claude-exchange .cle-header{position:absolute;top:62px;left:0;right:0;height:44px;z-index:40}"
        ".claude-exchange .cle-circle-btn{position:absolute;top:0;width:44px;height:44px;border-radius:22px;"
        "background:rgba(255,255,255,0.035);border:1px solid rgba(255,255,255,0.11);"
        "display:flex;align-items:center;justify-content:center}"
        ".claude-exchange .cle-hdr-left{left:16px}"
        ".claude-exchange .cle-hdr-right{position:absolute;top:0;right:16px;width:44px;height:44px;"
        "border-radius:22px;background:#272726;border:1px solid rgba(255,255,255,0.07);overflow:hidden}"
        ".claude-exchange .cle-hdr-face{position:absolute;inset:0;display:flex;align-items:center;"
        "justify-content:center}"
        ".claude-exchange .cle-scrollport{position:absolute;inset:0;overflow:hidden;z-index:10}"
        ".claude-exchange .cle-thread{position:relative;padding:124px 14px 180px 16px;will-change:transform}"
        ".claude-exchange .cle-empty{display:flex;flex-direction:column;align-items:center;padding-top:70px}"
        ".claude-exchange .cle-empty-mark{width:36px;height:36px}"
        ".claude-exchange .cle-empty-head{margin-top:20px;font-family:Georgia,serif;font-size:23px;"
        "color:#e8e8de;display:flex;gap:6px}"
        ".claude-exchange .cle-ehw{display:inline-block}"
        ".claude-exchange .cle-bubble{width:fit-content;max-width:322px;margin-left:auto;"
        "background:#131313;border-radius:24px;padding:14px 16px;color:#f8f8f4;font-size:17.5px;"
        "line-height:24px}"
        ".claude-exchange .cle-claude-reply{position:relative;margin-top:20px}"
        ".claude-exchange .cle-spin-wrap{position:relative;width:32px;height:32px;display:flex;"
        "align-items:center;justify-content:center;margin-bottom:12px}"
        ".claude-exchange .cle-spinner{width:24px;height:24px;display:flex;align-items:center;justify-content:center}"
        ".claude-exchange .cle-tool-row{display:flex;align-items:center;gap:12px;min-height:30px;"
        "color:#94948c;font-size:14.5px;padding:4px 0}"
        ".claude-exchange .cle-tool-row .cle-chev{margin-left:auto}"
        ".claude-exchange .cle-tool-ico{width:16px;height:16px;flex:none;display:flex;align-items:center}"
        ".claude-exchange .cle-lead-para{padding:4px 0 6px 28px;font-size:14.5px;line-height:20px;color:#c0c0b4}"
        ".claude-exchange .cle-collapsed{margin-top:4px}"
        ".claude-exchange .cle-answer{margin-top:16px;font-family:Georgia,serif;font-size:18px;"
        "line-height:27.5px;color:#f8f8f4}"
        ".claude-exchange .cle-para{margin-bottom:14px}"
        ".claude-exchange .cle-w{opacity:0;display:inline-block}"
        ".claude-exchange .cle-bold{font-weight:700;color:#fff}"
        ".claude-exchange .cle-bul{position:relative;padding-left:22px;margin-bottom:8px}"
        ".claude-exchange .cle-bul::before{content:'•';position:absolute;left:8px;top:0;color:#94948c}"
        ".claude-exchange .cle-cite{display:inline-block;padding:1px 7px;margin:0 2px;border-radius:6px;"
        "background:rgba(255,255,255,0.08);font-family:Inter,sans-serif;font-size:13px;vertical-align:2px;"
        "color:#ded9d0}"
        ".claude-exchange .cle-actions{display:flex;align-items:center;gap:16px;min-height:24px;"
        "padding-top:20px}"
        ".claude-exchange .cle-act-ico{width:16px;height:16px;opacity:0.65}"
        ".claude-exchange .cle-src-stack{display:flex;margin-left:6px}"
        ".claude-exchange .cle-src-dot{width:16px;height:16px;border-radius:8px;margin-left:-5px;"
        "border:1.2px solid #20201f;display:flex;align-items:center;justify-content:center;"
        "font-size:6px;font-weight:700;color:#fff}"
        ".claude-exchange .cle-src-label{font-size:13.5px;color:#94948c;margin-left:5px}"
        ".claude-exchange .cle-disclaim{display:flex;align-items:flex-start;padding-top:24px}"
        ".claude-exchange .cle-disclaim-mark{width:26px;height:26px;flex:none}"
        ".claude-exchange .cle-disclaim-text{margin-left:auto;text-align:right;font-size:12.5px;"
        "line-height:18px;color:#94948c}"
        ".claude-exchange .cle-chev-wrap{position:absolute;left:0;right:0;top:720px;z-index:25;"
        "display:flex;justify-content:center}"
        ".claude-exchange .cle-chev-btn{width:36px;height:36px;border-radius:18px;background:#2a2a28;"
        "border:1px solid rgba(255,255,255,0.1);display:flex;align-items:center;justify-content:center}"
        ".claude-exchange .cle-comp-scrim{position:absolute;left:0;right:0;bottom:0;height:118px;"
        "z-index:18;background:linear-gradient(to top,#20201f 16%,rgba(32,32,31,0) 100%)}"
        ".claude-exchange .cle-composer{position:absolute;left:8px;bottom:34px;width:386px;height:172px;"
        "border-radius:26px;background:#1c1c1b;border:1px solid #424240;z-index:20;overflow:hidden}"
        ".claude-exchange .cle-notice{position:absolute;top:10px;left:14px;right:14px;display:flex;"
        "align-items:center;gap:7px;font-size:12.5px;color:#94948c}"
        ".claude-exchange .cle-notice-dot{width:6px;height:6px;border-radius:3px;background:#d97757;flex:none}"
        ".claude-exchange .cle-model-pill{position:absolute;left:14px;top:44px;display:flex;align-items:center;"
        "gap:6px;padding:3px 8px;border-radius:12px;background:#272726;border:1px solid rgba(255,255,255,0.06)}"
        ".claude-exchange .cle-model-star{width:14px;height:14px;display:flex;align-items:center}"
        ".claude-exchange .cle-model-name{font-size:13px;font-weight:600;color:#f8f8f4}"
        ".claude-exchange .cle-model-effort{font-size:11.5px;color:#94948c;margin-left:4px}"
        ".claude-exchange .cle-comp-input-row{position:absolute;left:12px;right:12px;bottom:14px;"
        "height:44px;display:flex;align-items:center;gap:8px}"
        ".claude-exchange .cle-comp-plus{width:36px;height:36px;border-radius:18px;background:#282826;"
        "display:flex;align-items:center;justify-content:center;color:#e8e8e0;flex:none}"
        ".claude-exchange .cle-comp-field{position:relative;flex:1;height:36px;display:flex;"
        "align-items:center;overflow:hidden}"
        ".claude-exchange .cle-comp-ph{position:absolute;left:4px;font-size:17.5px;color:#94948c;"
        "white-space:nowrap}"
        ".claude-exchange .cle-comp-typed{position:absolute;left:4px;display:flex;align-items:center;"
        "white-space:pre;font-size:17.5px;color:#f8f8f4}"
        ".claude-exchange .cle-ch{opacity:0;display:inline-block}"
        ".claude-exchange .cle-cur{display:inline-block;width:2px;height:22px;margin:0 1px;opacity:0}"
        ".claude-exchange .cle-cur i{display:block;width:2px;height:22px;background:#d97757;border-radius:1px}"
        ".claude-exchange .cle-comp-circle-btn{width:36px;height:36px;border-radius:18px;background:#282826;"
        "display:flex;align-items:center;justify-content:center;color:#e8e8e0;flex:none}"
        ".claude-exchange .cle-comp-send-btn{width:36px;height:36px;border-radius:18px;background:#d97757;"
        "display:flex;align-items:center;justify-content:center;color:#20201f;flex:none}"
        ".claude-exchange .cle-comp-stop-btn{width:36px;height:36px;border-radius:18px;background:#ded9d0;"
        "display:flex;align-items:center;justify-content:center;color:#20201f;flex:none}"
        ".claude-exchange .cle-keyboard{position:absolute;left:0;right:0;bottom:0;height:309px;"
        "background:#1b1b1c;z-index:22}"
        ".claude-exchange .cle-krow{position:absolute;left:0;right:0;height:42px}"
        ".claude-exchange .cle-key{position:absolute;height:42px;background:#404040;border-radius:5px;"
        "display:flex;align-items:center;justify-content:center;font-size:22px;color:#fff;"
        "box-shadow:0 1px 0 rgba(0,0,0,0.35)}"
        ".claude-exchange .cle-kdark{background:#2a2a2b}"
        ".claude-exchange .cle-ksmall{font-size:16px}"
        ".claude-exchange .cle-kb-bottom{position:absolute;left:18px;right:18px;bottom:14px;"
        "display:flex;justify-content:space-between;align-items:center}"
    )
