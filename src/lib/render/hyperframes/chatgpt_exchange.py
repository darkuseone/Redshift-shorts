"""ChatGPT Exchange — iPhone mock, suggestions, typed prompt, streamed answer, comparison table.

Catalog ``chatgpt-exchange`` writes ``textContent``, animates element heights,
and tweens width/filter. Here characters and words are pre-baked spans,
visibility is ``opacity`` / ``scale`` / ``y`` / ``scaleX``, layout is static HTML/SVG.
Dark theme OLED (#000, #212121, #141414, #48aaff). Inter font,
not OpenAI Sans / -apple-system.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_CGE_CATALOG = 14.9
_CGE_STAGE_SCALE = 2.1968  # 1920 / 874

_CGE_DEFAULTS = {
    "prompt": "Hey what's the best tool for ai avatars",
    "intro1": (
        "It really depends on what you're trying to do, because “AI avatars” "
        "has split into a few different categories."
    ),
    "intro2": "For **most creators and marketers**, here's how I'd rank them today:",
    "tableHeadUse": "Use case",
    "tableHeadTool": "Best tool",
    "tableHeadWhy": "Why",
    "row1Use": "Overall realism",
    "row1Tool": "HeyGen",
    "row1Why": (
        "Most natural facial expressions, lip sync, gestures, voice cloning "
        "and localization. Benchmark for talking head videos."
    ),
    "row1Chip": "Official A.I Ranking",
    "row2Use": "Enterprise/training",
    "row2Tool": "Synthesia",
    "row2Why": (
        "Better collaboration, SCORM, compliance, team workflows; "
        "less creator-focused."
    ),
    "row2Chip": "Official A.I Ranking",
    "row3Use": "Mobile UGC",
    "row3Tool": "Captions",
    "row3Why": (
        "Extremely fast mobile workflow and social editing. "
        "Great for Reels creators."
    ),
    "row3Chip": "Creator Stack",
    "row4Use": "Real-time conversations",
    "row4Tool": "Tavus",
    "row4Why": "Interactive avatars that can hold live conversations.",
    "row4Chip": "Creator Stack",
}

_CGE_MAX = {
    "prompt": 80,
    "intro1": 240,
    "intro2": 160,
    "tableHeadUse": 24,
    "tableHeadTool": 24,
    "tableHeadWhy": 24,
    "rowUse": 32,
    "rowTool": 28,
    "rowWhy": 200,
    "rowChip": 28,
}

_CGE_BELL = (
    '<svg viewBox="0 0 20 20" width="18" height="18" fill="none">'
    '<path d="M4.2 15h11.6M10 3.2a4.3 4.3 0 0 1 4.3 4.3c0 3.4 1 5 1.5 5.6H4.2'
    'C4.7 12.5 5.7 10.9 5.7 7.5A4.3 4.3 0 0 1 10 3.2Z" stroke="#fff" '
    'stroke-width="1.5" stroke-linejoin="round"/>'
    '<path d="M8.3 16.6a1.9 1.9 0 0 0 3.4 0" stroke="#fff" stroke-width="1.5"/>'
    '<path d="M3 17L17 3" stroke="#fff" stroke-width="1.6"/></svg>'
)
_CGE_BARS = (
    '<svg viewBox="0 0 20 20" width="19" height="19" fill="none">'
    '<rect x="1" y="12.5" width="3" height="4.5" rx="1" fill="#fff"/>'
    '<rect x="6" y="9.5" width="3" height="7.5" rx="1" fill="#fff"/>'
    '<rect x="11" y="6.5" width="3" height="10.5" rx="1" fill="#fff"/>'
    '<rect x="16" y="3.5" width="3" height="13.5" rx="1" fill="rgba(255,255,255,.32)"/>'
    '</svg>'
)
_CGE_BURGER = (
    '<svg viewBox="0 0 24 24" width="24" height="24" fill="none">'
    '<path d="M5 9.5h14M5 15h9" stroke="#fff" stroke-width="2.1" stroke-linecap="round"/>'
    '</svg>'
)
_CGE_VOICE_CIRCLE = (
    '<svg viewBox="0 0 24 24" width="23" height="23" fill="none">'
    '<path d="M15.4 3.9a8.6 8.6 0 1 1-9.1 14.6" stroke="#fff" stroke-width="1.9" stroke-linecap="round"/>'
    '<path d="M6.3 18.5 4 21.2l3.4.5" stroke="#fff" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M13.6 8.4a4.1 4.1 0 1 0-3.3 6.9" stroke="#fff" stroke-width="1.9" stroke-linecap="round"/>'
    '</svg>'
)
_CGE_COMPOSE = (
    '<svg viewBox="0 0 24 24" width="21" height="21" fill="none">'
    '<path d="M4.5 15.5 15.2 4.8a2 2 0 0 1 2.9 2.9L7.4 18.4l-4 1 1-3.9Z" '
    'stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/></svg>'
)
_CGE_DOTS = (
    '<svg viewBox="0 0 24 24" width="21" height="21" fill="none">'
    '<circle cx="5" cy="12" r="1.9" fill="#fff"/>'
    '<circle cx="12" cy="12" r="1.9" fill="#fff"/>'
    '<circle cx="19" cy="12" r="1.9" fill="#fff"/></svg>'
)
_CGE_PLUS = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none">'
    '<path d="M12 4.5v15M4.5 12h15" stroke="#fff" stroke-width="2.1" stroke-linecap="round"/>'
    '</svg>'
)
_CGE_MIC = (
    '<svg viewBox="0 0 24 24" width="17" height="17" fill="none">'
    '<rect x="9" y="2.6" width="6" height="11.4" rx="3" stroke="#fff" stroke-width="1.8"/>'
    '<path d="M5.5 11.4a6.5 6.5 0 0 0 13 0M12 18v3.2" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>'
    '</svg>'
)
_CGE_WAVE = (
    '<svg viewBox="0 0 24 24" width="19" height="19" fill="none">'
    '<rect x="4" y="9.5" width="2.4" height="5" rx="1.2" fill="#fff"/>'
    '<rect x="8.6" y="6" width="2.4" height="12" rx="1.2" fill="#fff"/>'
    '<rect x="13.2" y="8" width="2.4" height="8" rx="1.2" fill="#fff"/>'
    '<rect x="17.8" y="10.5" width="2.4" height="3" rx="1.2" fill="#fff"/>'
    '</svg>'
)
_CGE_ARROW_UP = (
    '<svg viewBox="0 0 24 24" width="19" height="19" fill="none">'
    '<path d="M12 19V5.6M5.8 11.8 12 5.4l6.2 6.4" stroke="#000" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)
_CGE_STOP = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none">'
    '<rect x="7" y="7" width="10" height="10" rx="2" fill="#000"/>'
    '</svg>'
)
_CGE_CHEV_DOWN = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none">'
    '<path d="M12 5v13M6.2 12.2 12 18.2l5.8-6" stroke="#fff" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)
_CGE_SHIFT = (
    '<svg viewBox="0 0 24 24" width="19" height="19" fill="none">'
    '<path d="M12 4 4.5 12h4v7h7v-7h4L12 4Z" stroke="#fff" stroke-width="1.7" stroke-linejoin="round" fill="#fff"/>'
    '</svg>'
)
_CGE_DEL = (
    '<svg viewBox="0 0 24 24" width="22" height="22" fill="none">'
    '<path d="M8.4 5h11a1.6 1.6 0 0 1 1.6 1.6v10.8A1.6 1.6 0 0 1 19.4 19h-11L2.6 12 8.4 5Z" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/>'
    '<path d="M11.4 9.6l5.2 4.8M16.6 9.6l-5.2 4.8" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>'
    '</svg>'
)
_CGE_RET = (
    '<svg viewBox="0 0 24 24" width="21" height="21" fill="none">'
    '<path d="M20 6v6.4H5.4M9.6 8.4 5 12.8l4.6 4.4" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)
_CGE_EMOJI_KEY = (
    '<svg viewBox="0 0 24 24" width="25" height="25" fill="none">'
    '<circle cx="12" cy="12" r="9" stroke="#fff" stroke-width="1.7"/>'
    '<circle cx="9" cy="10" r="1.2" fill="#fff"/>'
    '<circle cx="15" cy="10" r="1.2" fill="#fff"/>'
    '<path d="M8 14.6a5 5 0 0 0 8 0" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/>'
    '</svg>'
)
_CGE_SLACK = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none">'
    '<path d="M6.2 14.4a2 2 0 1 1-2 2v-2h2Z" fill="#e01e5a"/>'
    '<path d="M7.3 14.4a2 2 0 0 1 4 0v5a2 2 0 1 1-4 0v-5Z" fill="#e01e5a"/>'
    '<path d="M9.6 6.2a2 2 0 1 1 2-2v2h-2Z" fill="#36c5f0"/>'
    '<path d="M9.6 7.3a2 2 0 0 1 0 4h-5a2 2 0 1 1 0-4h5Z" fill="#36c5f0"/>'
    '<path d="M17.8 9.6a2 2 0 1 1 2 2h-2v-2Z" fill="#2eb67d"/>'
    '<path d="M16.7 9.6a2 2 0 0 1-4 0v-5a2 2 0 1 1 4 0v5Z" fill="#2eb67d"/>'
    '<path d="M14.4 17.8a2 2 0 1 1-2 2v-2h2Z" fill="#ecb22e"/>'
    '<path d="M14.4 16.7a2 2 0 0 1 0-4h5a2 2 0 1 1 0 4h-5Z" fill="#ecb22e"/>'
    '</svg>'
)
_CGE_GMAIL = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none">'
    '<path d="M3 6.6 12 13l9-6.4V18a1 1 0 0 1-1 1h-3V11l-5 3.6L7 11v8H4a1 1 0 0 1-1-1V6.6Z" fill="#ea4335"/>'
    '<path d="M17 11v8h3a1 1 0 0 0 1-1V6.6L17 9.5V11Z" fill="#34a853"/>'
    '<path d="M3 6.6 7 9.5V19H4a1 1 0 0 1-1-1V6.6Z" fill="#4285f4"/>'
    '<path d="M3 5.6A1.6 1.6 0 0 1 5.4 4.3L12 9l6.6-4.7A1.6 1.6 0 0 1 21 5.6v1L12 13 3 6.6v-.8Z" fill="#fbbc04"/>'
    '</svg>'
)
_CGE_CAL = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none">'
    '<rect x="3" y="4" width="18" height="17" rx="3" fill="#1a73e8"/>'
    '<rect x="3" y="4" width="18" height="4.5" rx="3" fill="#1967d2"/>'
    '<text x="12" y="17.6" font-size="9" font-weight="700" fill="#fff" text-anchor="middle" font-family="Helvetica,sans-serif">31</text>'
    '</svg>'
)


def _cge_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _cge_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = (
        "prompt", "intro1", "intro2", "userMessage", "title", "snippet",
        "domain", "tableHeadUse", "row1Tool", "row1Use", "row1Why",
    )
    return any(str(params.get(k) or "").strip() for k in keys)


def _cge_copy(params: dict[str, Any]) -> dict[str, Any]:
    prompt = params.get("prompt") or params.get("userMessage") or params.get("title") or _CGE_DEFAULTS["prompt"]
    return {
        "prompt": _cge_clip(prompt, _CGE_DEFAULTS["prompt"], _CGE_MAX["prompt"]),
        "intro1": _cge_clip(params.get("intro1"), _CGE_DEFAULTS["intro1"], _CGE_MAX["intro1"]),
        "intro2": _cge_clip(params.get("intro2"), _CGE_DEFAULTS["intro2"], _CGE_MAX["intro2"]),
        "tableHeadUse": _cge_clip(params.get("tableHeadUse"), _CGE_DEFAULTS["tableHeadUse"], _CGE_MAX["tableHeadUse"]),
        "tableHeadTool": _cge_clip(params.get("tableHeadTool"), _CGE_DEFAULTS["tableHeadTool"], _CGE_MAX["tableHeadTool"]),
        "tableHeadWhy": _cge_clip(params.get("tableHeadWhy"), _CGE_DEFAULTS["tableHeadWhy"], _CGE_MAX["tableHeadWhy"]),
        "rows": [
            {
                "emoji": "🥇",
                "use": _cge_clip(params.get("row1Use"), _CGE_DEFAULTS["row1Use"], _CGE_MAX["rowUse"]),
                "tool": _cge_clip(params.get("row1Tool") or params.get("domain"), _CGE_DEFAULTS["row1Tool"], _CGE_MAX["rowTool"]),
                "why": _cge_clip(params.get("row1Why"), _CGE_DEFAULTS["row1Why"], _CGE_MAX["rowWhy"]),
                "chip": _cge_clip(params.get("row1Chip"), _CGE_DEFAULTS["row1Chip"], _CGE_MAX["rowChip"]),
            },
            {
                "emoji": "🏢",
                "use": _cge_clip(params.get("row2Use"), _CGE_DEFAULTS["row2Use"], _CGE_MAX["rowUse"]),
                "tool": _cge_clip(params.get("row2Tool"), _CGE_DEFAULTS["row2Tool"], _CGE_MAX["rowTool"]),
                "why": _cge_clip(params.get("row2Why"), _CGE_DEFAULTS["row2Why"], _CGE_MAX["rowWhy"]),
                "chip": _cge_clip(params.get("row2Chip"), _CGE_DEFAULTS["row2Chip"], _CGE_MAX["rowChip"]),
            },
            {
                "emoji": "📱",
                "use": _cge_clip(params.get("row3Use"), _CGE_DEFAULTS["row3Use"], _CGE_MAX["rowUse"]),
                "tool": _cge_clip(params.get("row3Tool"), _CGE_DEFAULTS["row3Tool"], _CGE_MAX["rowTool"]),
                "why": _cge_clip(params.get("row3Why"), _CGE_DEFAULTS["row3Why"], _CGE_MAX["rowWhy"]),
                "chip": _cge_clip(params.get("row3Chip"), _CGE_DEFAULTS["row3Chip"], _CGE_MAX["rowChip"]),
            },
            {
                "emoji": "💬",
                "use": _cge_clip(params.get("row4Use"), _CGE_DEFAULTS["row4Use"], _CGE_MAX["rowUse"]),
                "tool": _cge_clip(params.get("row4Tool"), _CGE_DEFAULTS["row4Tool"], _CGE_MAX["rowTool"]),
                "why": _cge_clip(params.get("row4Why"), _CGE_DEFAULTS["row4Why"], _CGE_MAX["rowWhy"]),
                "chip": _cge_clip(params.get("row4Chip"), _CGE_DEFAULTS["row4Chip"], _CGE_MAX["rowChip"]),
            },
        ],
    }


def _cge_keys_html(node_id: str) -> tuple[str, dict[str, str]]:
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
        parts.append(f'<div class="cge-krow" style="top:{top}px">')
        for i, ch in enumerate(letters):
            x = x0 + i * (kb_w + kb_gap)
            kid = f"{node_id}-k-{ch}"
            key_targets[ch] = kid
            parts.append(
                f'<div id="{kid}" class="cge-key" style="left:{x:.2f}px;width:{kb_w:.2f}px">'
                f'{_esc(ch)}</div>'
            )
        if top == 160:
            parts.append(
                f'<div class="cge-key cge-kdark" style="left:{kb_inset}px;width:45.33px">{_CGE_SHIFT}</div>'
                f'<div class="cge-key cge-kdark" style="left:350px;width:45.67px">{_CGE_DEL}</div>'
            )
        parts.append('</div>')

    space_id = f"{node_id}-k-space"
    key_targets[" "] = space_id
    parts.append(
        '<div class="cge-krow" style="top:214px">'
        f'<div class="cge-key cge-kdark cge-ksmall" style="left:{kb_inset}px;width:92.67px">123</div>'
        f'<div id="{space_id}" class="cge-key" style="left:105.33px;width:191.33px"></div>'
        f'<div class="cge-key cge-kdark" style="left:302.67px;width:93px">{_CGE_RET}</div>'
        '</div>'
        f'<div class="cge-kb-bottom"><div>{_CGE_EMOJI_KEY}</div><div>{_CGE_MIC}</div></div>'
    )
    return "".join(parts), key_targets


def ov_chatgpt_exchange(ctx: TemplateCtx) -> Piece:
    """ChatGPT Exchange: prompt typing, send bubble, streamed response and table."""
    if not _cge_has_copy(ctx.params):
        return Piece()

    copy = _cge_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 3.0)
    scale = duration / _CGE_CATALOG

    def at(catalog_sec: float) -> float:
        return catalog_sec * scale

    def dur(catalog_sec: float) -> float:
        return max(0.001, catalog_sec * scale)

    prompt_text = copy["prompt"]
    tweens: list[str] = []

    # 1. Suggestions cascade in
    sug_times = [at(0.0), at(0.09), at(0.18)]
    for i, stime in enumerate(sug_times):
        tweens.append(
            f'tl.fromTo("#{node_id}-sug-{i}",{{opacity:0,y:14}},'
            f'{{opacity:1,y:0,duration:{_num(dur(0.42))},ease:"power3.out"}},'
            f'{_num(start + stime)});'
        )

    # 2. Typing start
    t0 = at(0.86)
    # Suggestions clear on first keystroke
    for i in range(3):
        tweens.append(
            f'tl.to("#{node_id}-sug-{i}",{{opacity:0,y:10,duration:{_num(dur(0.2))},ease:"power2.in"}},'
            f'{_num(start + t0 - dur(0.02) + i * dur(0.04))});'
        )
    # Placeholder fades out
    tweens.append(
        f'tl.to("#{node_id}-comp-ph",{{opacity:0,duration:{_num(dur(0.12))}}},'
        f'{_num(start + t0 - dur(0.02))});'
    )
    # Cursor 0 appears
    tweens.append(
        f'tl.set("#{node_id}-cur-0",{{opacity:1}},{_num(start + t0 - dur(0.02))});'
    )
    # Wave icon -> send arrow
    tweens.append(
        f'tl.to("#{node_id}-face-wave",{{opacity:0,scale:0.6,duration:{_num(dur(0.14))}}},'
        f'{_num(start + t0)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-face-send",{{opacity:0,scale:0.6}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.24))},ease:"back.out(1.6)"}},'
        f'{_num(start + t0 + dur(0.04))});'
    )

    # Keystrokes timeline
    char_base = dur(0.05)
    space_hold = dur(0.11)
    char_t: list[float] = []
    curr_t = t0
    for ch in prompt_text:
        char_t.append(curr_t)
        curr_t += (char_base + space_hold) if ch == " " else char_base
    type_end = curr_t

    keys_markup, key_targets = _cge_keys_html(node_id)

    shift_amount = 0.0
    for i, ch in enumerate(prompt_text):
        ct = start + char_t[i]
        tweens.append(f'tl.set("#{node_id}-ch-{i}",{{opacity:1}},{_num(ct)});')
        tweens.append(f'tl.set("#{node_id}-cur-{i}",{{opacity:0}},{_num(ct)});')
        tweens.append(f'tl.set("#{node_id}-cur-{i + 1}",{{opacity:1}},{_num(ct)});')

        # Caret scroll if prompt is long
        if i > 20:
            shift_amount += 7.5
            tweens.append(
                f'tl.to("#{node_id}-typed",{{x:-{shift_amount:.1f},duration:{_num(dur(0.08))},ease:"none"}},{_num(ct)});'
            )

        # Flash key on keyboard
        target_key = key_targets.get(ch.upper() if ch != " " else " ")
        if target_key:
            tweens.append(
                f'tl.to("#{target_key}",{{backgroundColor:"#5f5f5f",duration:{_num(dur(0.04))}}},'
                f'{_num(ct - dur(0.03))});'
            )
            tweens.append(
                f'tl.to("#{target_key}",{{backgroundColor:"#3c3c3c",duration:{_num(dur(0.09))}}},'
                f'{_num(ct + dur(0.02))});'
            )

    # Caret blink after typing
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
        f'tl.to("#{node_id}-blue-btn",{{scale:0.88,duration:{_num(dur(0.06))},ease:"power2.in"}},{_num(t_send)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-blue-btn",{{scale:1,duration:{_num(dur(0.14))},ease:"back.out(2)"}},'
        f'{_num(t_send + dur(0.06))});'
    )
    tweens.append(
        f'tl.to("#{node_id}-face-send",{{opacity:0,scale:0.6,duration:{_num(dur(0.1))}}},'
        f'{_num(t_send + dur(0.04))});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-face-stop",{{opacity:0,scale:0.6}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.18))},ease:"back.out(2)"}},'
        f'{_num(t_send + dur(0.08))});'
    )

    t_go = t_send + dur(0.03)
    # Keyboard drops down, composer drops down
    tweens.append(
        f'tl.fromTo("#{node_id}-keyboard",{{y:0}},'
        f'{{y:335,duration:{_num(dur(0.34))},ease:"power2.in"}},{_num(t_go)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-composer",{{y:-309}},'
        f'{{y:0,duration:{_num(dur(0.34))},ease:"power2.in"}},{_num(t_go)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-typed",{{opacity:0,x:0,duration:{_num(dur(0.08))}}},'
        f'{_num(t_go)});'
    )
    tweens.append(
        f'tl.to("#{node_id}-comp-ph",{{opacity:1,duration:{_num(dur(0.16))}}},'
        f'{_num(t_go + dur(0.12))});'
    )

    # Header transition
    tweens.append(
        f'tl.to("#{node_id}-seg",{{opacity:0,scale:0.9,duration:{_num(dur(0.22))},ease:"power2.in"}},'
        f'{_num(t_go)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-hdr-actions",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(dur(0.18))}}},'
        f'{_num(t_go + dur(0.16))});'
    )

    # Bubble lands in thread
    tweens.append(
        f'tl.fromTo("#{node_id}-bubble",{{opacity:0,y:220,scale:0.94}},'
        f'{{opacity:1,y:0,scale:1,duration:{_num(dur(0.34))},ease:"power3.out"}},'
        f'{_num(t_go + dur(0.02))});'
    )

    # 4. Stream response paragraphs
    tw = t_go + dur(0.34) + dur(0.6)
    word_step = dur(0.15)

    p1_words = copy["intro1"].split()
    for wid, w in enumerate(p1_words):
        tweens.append(
            f'tl.fromTo("#{node_id}-p1-w{wid}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(dur(0.1))}}},'
            f'{_num(tw)});'
        )
        tw += word_step

    # Scroll thread up for paragraph 2
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-50,duration:{_num(dur(0.6))},ease:"power2.out"}},'
        f'{_num(tw)});'
    )
    tw += dur(0.12)

    p2_words = copy["intro2"].replace("**", "").split()
    for wid, w in enumerate(p2_words):
        tweens.append(
            f'tl.fromTo("#{node_id}-p2-w{wid}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(dur(0.1))}}},'
            f'{_num(tw)});'
        )
        tw += word_step

    # 5. Table reveals row by row
    tw += dur(0.2)
    tweens.append(
        f'tl.fromTo("#{node_id}-head-row",{{opacity:0,y:6}},'
        f'{{opacity:1,y:0,duration:{_num(dur(0.2))},ease:"power2.out"}},'
        f'{_num(tw)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-head-rule",{{opacity:0,scaleX:0}},'
        f'{{opacity:1,scaleX:1,duration:{_num(dur(0.2))},ease:"power2.out"}},'
        f'{_num(tw)});'
    )
    tw += dur(0.34)

    row_step = dur(0.7)
    for r_idx, row_data in enumerate(copy["rows"]):
        tweens.append(
            f'tl.fromTo("#{node_id}-row-{r_idx}",{{opacity:0,y:10}},'
            f'{{opacity:1,y:0,duration:{_num(dur(0.22))},ease:"power2.out"}},'
            f'{_num(tw)});'
        )
        tweens.append(
            f'tl.fromTo("#{node_id}-emo-{r_idx}",{{opacity:0,scale:0.5}},'
            f'{{opacity:1,scale:1,duration:{_num(dur(0.14))},ease:"back.out(1.5)"}},'
            f'{_num(tw + dur(0.04))});'
        )
        why_words = row_data["why"].split()
        for wid, w in enumerate(why_words):
            tweens.append(
                f'tl.fromTo("#{node_id}-rw-{r_idx}-{wid}",{{opacity:0}},'
                f'{{opacity:1,duration:{_num(dur(0.09))}}},'
                f'{_num(tw + dur(0.08) + wid * dur(0.028))});'
            )
        tweens.append(
            f'tl.fromTo("#{node_id}-chip-{r_idx}",{{opacity:0,scale:0.8}},'
            f'{{opacity:1,scale:1,duration:{_num(dur(0.2))},ease:"power2.out"}},'
            f'{_num(tw + dur(0.42))});'
        )
        tweens.append(
            f'tl.fromTo("#{node_id}-rule-{r_idx}",{{opacity:0,scaleX:0}},'
            f'{{opacity:1,scaleX:1,duration:{_num(dur(0.12))}}},'
            f'{_num(tw + dur(0.2))});'
        )
        scroll_y = -90 - r_idx * 65
        tweens.append(
            f'tl.to("#{node_id}-thread",{{y:{scroll_y},duration:{_num(dur(0.72))},ease:"power2.out"}},'
            f'{_num(tw + dur(0.1))});'
        )
        tw += row_step

    # 6. Stream ends & read-back scroll
    tweens.append(
        f'tl.to("#{node_id}-face-stop",{{opacity:0,duration:{_num(dur(0.14))}}},'
        f'{_num(tw)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-face-wave",{{opacity:0,scale:0.6}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.22))},ease:"power2.out"}},'
        f'{_num(tw + dur(0.06))});'
    )

    t_read = tw + dur(0.24)
    # Minute & battery rollover
    tweens.append(
        f'tl.set("#{node_id}-clock-early",{{opacity:0}},{_num(t_read - dur(0.5))});'
    )
    tweens.append(
        f'tl.set("#{node_id}-clock-late",{{opacity:1}},{_num(t_read - dur(0.5))});'
    )
    tweens.append(
        f'tl.set("#{node_id}-batt-early",{{opacity:0}},{_num(t_read - dur(0.5))});'
    )
    tweens.append(
        f'tl.set("#{node_id}-batt-late",{{opacity:1}},{_num(t_read - dur(0.5))});'
    )

    # Readback scroll to hero position
    tweens.append(
        f'tl.to("#{node_id}-thread",{{y:-70,duration:{_num(dur(1.1))},ease:"power2.inOut"}},'
        f'{_num(t_read)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-sbar",{{opacity:0,y:50}},'
        f'{{opacity:1,y:0,duration:{_num(dur(1.1))},ease:"power2.inOut"}},'
        f'{_num(t_read)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-chev",{{opacity:0,y:10,scale:0.7}},'
        f'{{opacity:1,y:0,scale:1,duration:{_num(dur(0.3))},ease:"back.out(1.5)"}},'
        f'{_num(t_read + dur(0.75))});'
    )

    # Build HTML Markup
    typed_spans = []
    for i, ch in enumerate(prompt_text):
        shown = "\u00a0" if ch == " " else _esc(ch)
        typed_spans.append(f'<span id="{node_id}-cur-{i}" class="cge-cur"><i></i></span>')
        typed_spans.append(f'<span id="{node_id}-ch-{i}" class="cge-ch">{shown}</span>')
    typed_spans.append(f'<span id="{node_id}-cur-{len(prompt_text)}" class="cge-cur"><i></i></span>')

    p1_markup = " ".join(
        f'<span id="{node_id}-p1-w{i}" class="cge-w">{_esc(w)}</span>'
        for i, w in enumerate(p1_words)
    )

    # P2 with bold markers
    p2_raw_tokens = copy["intro2"].split()
    p2_spans = []
    w_counter = 0
    in_bold = False
    for tok in p2_raw_tokens:
        clean = tok
        if clean.startswith("**"):
            in_bold = True
            clean = clean[2:]
        has_end = clean.endswith("**")
        if has_end:
            clean = clean[:-2]
        extra_cls = " cge-bold" if in_bold else ""
        p2_spans.append(
            f'<span id="{node_id}-p2-w{w_counter}" class="cge-w{extra_cls}">{_esc(clean)}</span>'
        )
        w_counter += 1
        if has_end:
            in_bold = False
    p2_markup = " ".join(p2_spans)

    rows_markup = []
    for r_idx, row_data in enumerate(copy["rows"]):
        why_spans = " ".join(
            f'<span id="{node_id}-rw-{r_idx}-{wid}" class="cge-w">{_esc(w)}</span>'
            for wid, w in enumerate(row_data["why"].split())
        )
        rows_markup.append(
            f'<div id="{node_id}-row-{r_idx}" class="cge-tr">'
            f'<div class="cge-td cge-c1"><div class="cge-use">'
            f'<span id="{node_id}-emo-{r_idx}" class="cge-emo">{row_data["emoji"]}</span>'
            f'<span class="cge-w">{_esc(row_data["use"])}</span></div></div>'
            f'<div class="cge-td cge-c2"><span class="cge-w">{_esc(row_data["tool"])}</span></div>'
            f'<div class="cge-td cge-c3">{why_spans}'
            f'<div id="{node_id}-chip-{r_idx}" class="cge-chip">'
            f'<span class="cge-chip-dot">AI</span>{_esc(row_data["chip"])}</div></div>'
            f'</div>'
            f'<div id="{node_id}-rule-{r_idx}" class="cge-rule-row"></div>'
        )

    sug_icons = [_CGE_SLACK, _CGE_GMAIL, _CGE_CAL]
    sug_labels = ["Summarize my to-dos", "Draft follow-up emails", "Prep me for upcoming meetings"]
    sug_markup = "".join(
        f'<div id="{node_id}-sug-{i}" class="cge-sug">'
        f'<div class="cge-sug-ico">{sug_icons[i]}</div>'
        f'<div>{sug_labels[i]}</div></div>'
        for i in range(3)
    )

    node = (
        f'<div id="{node_id}" class="clip overlay chatgpt-exchange" {_timing(ctx)}>'
        f'<div class="cge-stage">'
        f'<div class="cge-screen" id="{node_id}-screen">'
        # Status Bar
        f'<div class="cge-statusbar">'
        f'<div class="cge-sb-left"><div class="cge-sb-clock cge-sb-clock-box">'
        f'<span id="{node_id}-clock-early">1:29</span>'
        f'<span id="{node_id}-clock-late">1:30</span></div>{_CGE_BELL}</div>'
        f'<div class="cge-sb-right">{_CGE_BARS}<div class="cge-sb-net">5G+</div>'
        f'<div class="cge-sb-batt"><span id="{node_id}-batt-early">89</span>'
        f'<span id="{node_id}-batt-late">88</span></div>'
        f'<div class="cge-sb-batt-cap"></div></div></div>'
        # Header Scrim & Status Plate
        f'<div class="cge-status-plate"></div>'
        f'<div class="cge-hdr-scrim"></div>'
        # Header
        f'<div class="cge-header">'
        f'<div class="cge-circle-btn cge-hdr-left">{_CGE_BURGER}</div>'
        f'<div class="cge-seg" id="{node_id}-seg"><div class="cge-seg-item on">Chat</div><div class="cge-seg-item">Work</div></div>'
        f'<div class="cge-hdr-right" id="{node_id}-hdr-right">'
        f'<div class="cge-hdr-right-face cge-hdr-voice">{_CGE_VOICE_CIRCLE}</div>'
        f'<div class="cge-hdr-right-face" id="{node_id}-hdr-actions">{_CGE_COMPOSE}{_CGE_DOTS}</div>'
        f'</div></div>'
        # Scrollport & Thread
        f'<div class="cge-scrollport">'
        f'<div class="cge-thread" id="{node_id}-thread">'
        f'<div class="cge-bubble" id="{node_id}-bubble">{_esc(prompt_text)}?</div>'
        f'<div class="cge-answer" id="{node_id}-answer">'
        f'<div class="cge-para"><div class="cge-para-inner">{p1_markup}</div></div>'
        f'<div class="cge-para"><div class="cge-para-inner">{p2_markup}</div></div>'
        f'<div class="cge-tbl" id="{node_id}-tbl">'
        f'<div class="cge-tr" id="{node_id}-head-row">'
        f'<div class="cge-td cge-th cge-c1">{_esc(copy["tableHeadUse"])}</div>'
        f'<div class="cge-td cge-th cge-c2">{_esc(copy["tableHeadTool"])}</div>'
        f'<div class="cge-td cge-th cge-c3">{_esc(copy["tableHeadWhy"])}</div>'
        f'</div>'
        f'<div class="cge-rule-head" id="{node_id}-head-rule"></div>'
        f'{"".join(rows_markup)}'
        f'</div></div></div></div>'
        # Scrollbar & Chevron
        f'<div class="cge-scrollbar" id="{node_id}-sbar"></div>'
        f'<div class="cge-chev-wrap"><div class="cge-chev" id="{node_id}-chev">{_CGE_CHEV_DOWN}</div></div>'
        # Suggestions
        f'<div class="cge-suggests" id="{node_id}-suggests">{sug_markup}</div>'
        # Comp Scrim
        f'<div class="cge-comp-scrim"></div>'
        # Composer (initially shifted -309px up)
        f'<div class="cge-composer" id="{node_id}-composer">'
        f'<div class="cge-comp-text"><span class="cge-typed" id="{node_id}-typed">{"".join(typed_spans)}</span></div>'
        f'<div class="cge-comp-ph" id="{node_id}-comp-ph">Ask ChatGPT</div>'
        f'<div class="cge-comp-ctrls"><div class="cge-comp-plus">{_CGE_PLUS}</div>'
        f'<div class="cge-comp-mic">{_CGE_MIC}</div>'
        f'<div class="cge-blue-btn" id="{node_id}-blue-btn">'
        f'<div class="cge-blue-face" id="{node_id}-face-wave">{_CGE_WAVE}</div>'
        f'<div class="cge-blue-face" id="{node_id}-face-send">{_CGE_ARROW_UP}</div>'
        f'<div class="cge-blue-face" id="{node_id}-face-stop">{_CGE_STOP}</div>'
        f'</div></div></div>'
        # Keyboard (initially y: 0)
        f'<div class="cge-keyboard" id="{node_id}-keyboard">'
        f'<div class="cge-predict">'
        f'<div class="cge-pd"><div class="cge-pdw">I</div></div>'
        f'<div class="cge-pd"><div class="cge-pdw">The</div></div>'
        f'<div class="cge-pd"><div class="cge-pdw">I\'m</div></div>'
        f'</div>'
        f'{keys_markup}'
        f'</div>'
        f'</div></div></div>'
    )

    return Piece(nodes=[node], tweens=tweens)


def cge_overlay_css() -> str:
    """ChatGPT Exchange iPhone mock CSS. Scaled to 1080x1920."""
    return (
        ".chatgpt-exchange{left:0;top:0;width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden;font-family:Inter,var(--font-subtitle),sans-serif;"
        "background:#000;color:#fcfcfc}"
        ".chatgpt-exchange .cge-stage{position:absolute;inset:0;background:#000}"
        ".chatgpt-exchange .cge-screen{position:absolute;top:0;left:50%;width:402px;height:874px;"
        f"margin-left:-201px;background:#000;overflow:hidden;transform-origin:top center;"
        f"transform:scale({_CGE_STAGE_SCALE});-webkit-font-smoothing:antialiased}}"
        # Status Bar
        ".chatgpt-exchange .cge-statusbar{position:absolute;top:0;left:0;right:0;height:65px;"
        "display:flex;align-items:center;z-index:40;padding:0 34px 0 16px;color:#fff}"
        ".chatgpt-exchange .cge-sb-left{display:flex;align-items:center;gap:6px;margin-left:31.7px}"
        ".chatgpt-exchange .cge-sb-clock{font-size:17.2px;font-weight:600;letter-spacing:1.3px}"
        ".chatgpt-exchange .cge-sb-clock-box{position:relative;width:38px;height:22px}"
        ".chatgpt-exchange .cge-sb-clock-box span{position:absolute;left:0;top:0;white-space:nowrap}"
        ".chatgpt-exchange .cge-sb-clock-box span:nth-child(2){opacity:0}"
        ".chatgpt-exchange .cge-sb-right{display:flex;align-items:center;gap:5px;margin-left:auto}"
        ".chatgpt-exchange .cge-sb-net{font-size:15px;font-weight:500;letter-spacing:-0.2px}"
        ".chatgpt-exchange .cge-sb-batt{width:30px;height:15px;border-radius:4.5px;background:#fff;"
        "color:#000;font-size:11px;font-weight:600;display:flex;align-items:center;"
        "justify-content:center;letter-spacing:-0.2px;position:relative}"
        ".chatgpt-exchange .cge-sb-batt span{position:absolute}"
        ".chatgpt-exchange .cge-sb-batt span:nth-child(2){opacity:0}"
        ".chatgpt-exchange .cge-sb-batt-cap{width:2px;height:6px;background:rgba(255,255,255,0.45);"
        "border-radius:0 2px 2px 0;margin-left:-4px}"
        # Header & Plates
        ".chatgpt-exchange .cge-status-plate{position:absolute;top:0;left:0;right:0;height:54.7px;"
        "z-index:34;background:#000}"
        ".chatgpt-exchange .cge-hdr-scrim{position:absolute;top:0;left:0;right:0;height:118px;"
        "z-index:30;background:rgba(0,0,0,0.3)}"
        ".chatgpt-exchange .cge-header{position:absolute;top:62px;left:0;right:0;height:44px;z-index:40}"
        ".chatgpt-exchange .cge-circle-btn{position:absolute;top:0;width:44px;height:44px;"
        "border-radius:22px;background:#1c1c1e;display:flex;align-items:center;justify-content:center}"
        ".chatgpt-exchange .cge-hdr-left{left:16px}"
        ".chatgpt-exchange .cge-hdr-right{position:absolute;top:0;right:16px;width:44px;height:44px;"
        "border-radius:22px;background:#1c1c1e;overflow:hidden}"
        ".chatgpt-exchange .cge-hdr-right-face{position:absolute;inset:0;display:flex;align-items:center;"
        "justify-content:center;gap:18px}"
        ".chatgpt-exchange #cge-hdr-actions{opacity:0}"
        ".chatgpt-exchange .cge-seg{position:absolute;top:-1.7px;left:121.7px;width:158px;height:48px;"
        "border-radius:24px;background:#181818;display:flex;align-items:center;padding:4px}"
        ".chatgpt-exchange .cge-seg-item{flex:1;height:40px;border-radius:20px;display:flex;"
        "align-items:center;justify-content:center;font-size:16px;font-weight:500;color:#fff}"
        ".chatgpt-exchange .cge-seg-item.on{background:#3a3a3a}"
        # Thread & Bubble
        ".chatgpt-exchange .cge-scrollport{position:absolute;inset:0;overflow:hidden;z-index:10}"
        ".chatgpt-exchange .cge-thread{position:relative;padding:128px 16px 190px;will-change:transform}"
        ".chatgpt-exchange .cge-bubble{position:relative;margin-left:auto;width:245.7px;"
        "background:#212121;border-radius:24px;padding:10px 16px;color:#fcfcfc;font-size:16px;"
        "line-height:25.667px;opacity:0}"
        ".chatgpt-exchange .cge-answer{margin-top:36px;width:360px;color:#fcfcfc;font-size:16px;"
        "line-height:25.667px}"
        ".chatgpt-exchange .cge-para{overflow:hidden}"
        ".chatgpt-exchange .cge-para+.cge-para{margin-top:24px}"
        ".chatgpt-exchange .cge-w{display:inline-block;opacity:0;will-change:opacity}"
        ".chatgpt-exchange .cge-bold{font-weight:600}"
        # Table
        ".chatgpt-exchange .cge-tbl{margin:19px 0 0 -5.7px;width:480px;overflow:hidden}"
        ".chatgpt-exchange .cge-tr{display:flex;overflow:hidden}"
        ".chatgpt-exchange .cge-td{padding:8px 12px 8px 0;font-size:14.5px;line-height:23px;color:#fcfcfc}"
        ".chatgpt-exchange .cge-c1{width:168px}"
        ".chatgpt-exchange .cge-c2{width:120px;font-weight:600}"
        ".chatgpt-exchange .cge-c3{width:173px}"
        ".chatgpt-exchange .cge-th{font-size:14.5px;line-height:23px;font-weight:600;padding-bottom:6px}"
        ".chatgpt-exchange .cge-rule-head{height:2px;background:#202020;transform-origin:0% 50%}"
        ".chatgpt-exchange .cge-rule-row{height:2px;background:#131313;transform-origin:0% 50%}"
        ".chatgpt-exchange .cge-use{display:flex;gap:8px;align-items:baseline}"
        ".chatgpt-exchange .cge-emo{font-size:14px;display:inline-block}"
        ".chatgpt-exchange .cge-chip{display:flex;width:fit-content;align-items:center;gap:6px;"
        "height:24px;margin-top:6px;padding:0 8px;border-radius:12px;background:#0b0b0c;"
        "border:1px solid #2b2b2d;font-size:10px;color:#b9b9bd;white-space:nowrap;opacity:0}"
        ".chatgpt-exchange .cge-chip-dot{width:12.5px;height:12.5px;border-radius:6.25px;"
        "background:#2e2e30;display:flex;align-items:center;justify-content:center;font-size:6px;"
        "font-weight:700;color:#d8d8da}"
        # Scroll Chrome & Suggestions
        ".chatgpt-exchange .cge-scrollbar{position:absolute;right:3.3px;top:145px;width:2.7px;"
        "height:250px;border-radius:1.4px;background:rgba(235,235,245,0.32);z-index:20;opacity:0}"
        ".chatgpt-exchange .cge-chev-wrap{position:absolute;left:0;right:0;top:738.7px;z-index:25;"
        "display:flex;justify-content:center}"
        ".chatgpt-exchange .cge-chev{width:36px;height:36px;border-radius:18px;background:#1c1c1e;"
        "border:1px solid #2c2c2e;display:flex;align-items:center;justify-content:center;opacity:0}"
        ".chatgpt-exchange .cge-suggests{position:absolute;left:0;right:0;bottom:407.7px;z-index:15}"
        ".chatgpt-exchange .cge-sug{height:47px;display:flex;align-items:center;gap:16px;"
        "padding-left:27.7px;color:#fcfcfc;font-size:16px;opacity:0}"
        ".chatgpt-exchange .cge-sug-ico{width:15.7px;height:15.7px;display:flex;align-items:center}"
        # Composer & Keyboard
        ".chatgpt-exchange .cge-comp-scrim{position:absolute;left:0;right:0;bottom:0;height:120px;"
        "z-index:18;background:linear-gradient(to top,#000 12%,rgba(0,0,0,0) 100%)}"
        ".chatgpt-exchange .cge-composer{position:absolute;left:12px;bottom:38.3px;width:378px;"
        "height:48px;border-radius:24px;background:rgba(255,255,255,0.055);z-index:20;overflow:hidden;"
        "transform:translateY(-309px)}"
        ".chatgpt-exchange .cge-comp-text{position:absolute;top:0;left:16px;right:16px;height:44px;"
        "display:flex;align-items:center;color:#fcfcfc;font-size:16px;line-height:22px;white-space:pre}"
        ".chatgpt-exchange .cge-comp-ph{position:absolute;top:0;left:48px;height:48px;display:flex;"
        "align-items:center;color:#9a9a9e;font-size:16px}"
        ".chatgpt-exchange .cge-typed{white-space:pre;display:inline-block}"
        ".chatgpt-exchange .cge-ch{opacity:0}"
        ".chatgpt-exchange .cge-cur{position:relative;display:inline-block;width:0;height:22px;"
        "vertical-align:-4px;opacity:0}"
        ".chatgpt-exchange .cge-cur i{position:absolute;left:1px;top:0;width:2px;height:22px;background:#48aaff}"
        ".chatgpt-exchange .cge-comp-ctrls{position:absolute;left:0;right:0;bottom:0;height:48px}"
        ".chatgpt-exchange .cge-comp-ctrls>*{position:absolute;top:50%;transform:translateY(-50%);"
        "display:flex;align-items:center;justify-content:center}"
        ".chatgpt-exchange .cge-comp-plus{left:15px}"
        ".chatgpt-exchange .cge-comp-mic{right:60px}"
        ".chatgpt-exchange .cge-blue-btn{right:8px;width:32px;height:32px;border-radius:16px;background:#48aaff}"
        ".chatgpt-exchange .cge-blue-face{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}"
        ".chatgpt-exchange #cge-face-send,.chatgpt-exchange #cge-face-stop{opacity:0}"
        # Keyboard
        ".chatgpt-exchange .cge-keyboard{position:absolute;left:0;right:0;top:539px;height:335px;"
        "background:#141414;z-index:22}"
        ".chatgpt-exchange .cge-predict{position:relative;height:52px;display:flex;align-items:center}"
        ".chatgpt-exchange .cge-pd{flex:1;position:relative;align-self:stretch;font-size:17px;color:#e8e8ea;"
        "border-right:1px solid rgba(235,235,245,0.16)}"
        ".chatgpt-exchange .cge-pdw{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}"
        ".chatgpt-exchange .cge-pd:last-child{border-right:none}"
        ".chatgpt-exchange .cge-krow{position:absolute;left:0;right:0;height:43px}"
        ".chatgpt-exchange .cge-key{position:absolute;top:0;height:43px;border-radius:5px;background:#3c3c3c;"
        "display:flex;align-items:center;justify-content:center;color:#fff;font-size:22.2px;font-weight:400}"
        ".chatgpt-exchange .cge-kdark{background:#2b2b2d}"
        ".chatgpt-exchange .cge-ksmall{font-size:16px}"
        ".chatgpt-exchange .cge-kb-bottom{position:absolute;left:0;right:0;top:279.7px;height:55px;"
        "display:flex;align-items:center;justify-content:space-between;padding:0 29px}"
    )
