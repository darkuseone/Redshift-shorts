"""AI Chat Reveal — iPhone mock, typed prompt, streamed answer, end card.

Catalog ``ai-chat-reveal`` writes ``textContent`` while typing, uses
``autoAlpha`` / ``visibility``, and builds the keyboard from JS. Here
characters and words are pre-baked spans, visibility is ``opacity``,
keyboard geometry is static HTML. Paper ``#fdfdfd``, ink ``#0d0d0d``,
keyboard ``#d2d5e0``, mint CTA ``#3ce6ac`` as in the catalog. Inter,
not ``-apple-system``. HyperFrames branding on the end card becomes
REDSHIFT. ``chat-thread`` stays a separate bubble window.
"""

from __future__ import annotations

import re
from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_ACR_TYPE_START = 0.8637
_ACR_KEY_UP_AT = 0.2
_ACR_KEY_DUR = 0.2667
_ACR_KEY_Y = 482
_ACR_COMP_Y = -497
_ACR_SEND_GAP = 0.1667
_ACR_CARET_STEP = 0.5333
_ACR_DOT_AT = 0.4333
_ACR_DOT_STEP = 0.0333
_ACR_DOT_OFF = 0.5667
_ACR_STREAM_AT = 0.6333
_ACR_INK_DUR = 0.2667
_ACR_STOP_GAP = 0.4667
_ACR_EC_AT = 15.8333
_ACR_EC_DUR = 0.3167
_ACR_BUBBLE_DUR = 0.1667
_ACR_STAGE_SCALE = 1.18226601
_ACR_STAGE_LEFT = 96.6502

_ACR_KEY_GAPS = (
    0.1, 0.033, 0.2, 0.133, 0.2, 0.033, 0.067, 0.033, 0.1, 0.067, 0.033, 0.067,
    0.067, 0.067, 0.133, 0.067, 0.033, 0.067, 0.1, 0.1, 0.067, 0.133, 0.1,
    0.033, 0.1, 0.033, 0.167, 0.033, 0.1, 0.1, 0.067, 0.133, 0.033, 0.067, 0.1,
    0.033, 0.1, 0.067,
)
_ACR_WORD_GAPS = (
    0.167, 0.1, 0.0, 0.367, 0.0, 0.167, 0.133, 0.1, 0.1, 0.133, 0.167, 0.133,
    0.0, 0.233, 0.167, 0.1, 0.0, 0.133, 0.133, 0.1, 0.167, 0.133, 0.1, 0.133,
    0.167, 0.1, 0.133, 0.1, 0.133,
)
_ACR_DOT_RAMP = (
    0.488, 0.53, 0.53, 0.56, 0.608, 0.687, 0.729, 0.771, 0.813, 0.867, 0.904,
    0.988, 1,
)

_ACR_GREY = "#767676"
_ACR_INK = "#141414"

_ACR_MAX = {
    "botName": 24,
    "userMessage": 60,
    "answer1": 220,
    "answer2": 120,
    "answer3": 120,
    "bullet1": 90,
    "bullet2": 90,
    "bullet3": 90,
    "ecHeadline": 60,
    "ecSub": 140,
    "ecCta": 30,
    "ecFooter": 40,
}

_ACR_DEFAULTS = {
    "botName": "Assistant",
    "userMessage": "How do I turn my HTML into real video?",
    "answer1": ("You do not need an editor. REDSHIFT renders the HTML you "
                "already write into deterministic, pixel-perfect video."),
    "answer2": "It is markup, not magic.",
    "answer3": "What you get out of the box:",
    "bullet1": "A catalog of motion primitives you install and own",
    "bullet2": "GSAP timelines that seek to any frame",
    "bullet3": "9:16 renders from a single pipeline",
    "ecHeadline": "It's not magic.|It's HTML.",
    "ecSub": "Write the script. Ship the short.",
    "ecCta": "Try REDSHIFT",
    "ecFooter": "REDSHIFT.SHORTS",
}

_ACR_SHIFT = (
    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" '
    'stroke="#000" stroke-width="1.6" stroke-linejoin="round">'
    '<path d="M12 4 L4.5 12 H8.5 V17 H15.5 V12 H19.5 Z"/></svg>'
)
_ACR_DEL = (
    '<svg width="31" height="24" viewBox="0 0 28 20" fill="none" '
    'stroke="#000" stroke-width="1.6" stroke-linejoin="round" '
    'stroke-linecap="round"><path d="M9 2 H26 V18 H9 L1.5 10 Z"/>'
    '<path d="M13 6.5 L20 13.5 M20 6.5 L13 13.5"/></svg>'
)
_ACR_EMOJI = (
    '<svg width="27" height="27" viewBox="0 0 24 24" fill="none" '
    'stroke="#000" stroke-width="1.4" stroke-linecap="round">'
    '<circle cx="12" cy="12" r="9"/>'
    '<circle cx="9" cy="10" r="0.6" fill="#000"/>'
    '<circle cx="15" cy="10" r="0.6" fill="#000"/>'
    '<path d="M8 14.5 C9.5 16.5 14.5 16.5 16 14.5"/></svg>'
)
_ACR_RETURN = (
    '<svg width="27" height="27" viewBox="0 0 24 24" fill="none" '
    'stroke="#000" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="M19 5 V11 H6"/>'
    '<path d="M9.5 7.5 L6 11 L9.5 14.5"/></svg>'
)
_ACR_SIGNAL = (
    '<svg width="30" height="20" viewBox="0 0 20 12" fill="#0d0d0d">'
    '<rect x="0" y="7" width="3" height="4" rx="1"/>'
    '<rect x="5" y="5" width="3" height="6" rx="1"/>'
    '<rect x="10" y="2.6" width="3" height="8.4" rx="1"/>'
    '<rect x="15" y="0.5" width="3" height="10.5" rx="1"/></svg>'
)
_ACR_WIFI = (
    '<svg width="30" height="21" viewBox="0 0 22 15" fill="none" '
    'stroke="#0d0d0d" stroke-width="2.2" stroke-linecap="round">'
    '<path d="M2 5 C7 -0.5 15 -0.5 20 5" fill="none"/>'
    '<path d="M5.5 8.6 C9 5 13 5 16.5 8.6"/>'
    '<path d="M9.2 12 C10.4 11 11.6 11 12.8 12"/></svg>'
)
_ACR_BATTERY = (
    '<svg width="46" height="22" viewBox="0 0 30 14" fill="none">'
    '<rect x="0.8" y="0.8" width="25" height="12.4" rx="3.6" '
    'stroke="#0d0d0d" stroke-opacity="0.32" stroke-width="1.2"/>'
    '<rect x="2.4" y="2.4" width="22.4" height="9.2" rx="2.4" fill="#0d0d0d"/>'
    '<path d="M28 4.6 v4.8 a2.4 2.4 0 0 0 0 -4.8" fill="#0d0d0d" '
    'fill-opacity="0.45"/></svg>'
)
_ACR_MENU = (
    '<svg width="29" height="29" viewBox="0 0 24 24" fill="none" '
    'stroke="#0d0d0d" stroke-width="1.9" stroke-linecap="round">'
    '<path d="M4 8 H20 M4 15 H12"/></svg>'
)
_ACR_HICONS_A = (
    '<svg width="28" height="28" viewBox="0 0 26 24" fill="none" '
    'stroke="#0d0d0d" stroke-width="1.7" stroke-linecap="round">'
    '<circle cx="10" cy="8" r="4"/>'
    '<path d="M3 21 C3 16 6.5 14 10 14 C13.5 14 17 16 17 21"/>'
    '<path d="M20 6 V12 M17 9 H23"/></svg>'
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" '
    'stroke="#0d0d0d" stroke-width="1.7" stroke-linecap="round" '
    'stroke-dasharray="2.4 3.4"><circle cx="12" cy="12" r="9"/></svg>'
)
_ACR_HICONS_B = (
    '<svg width="23" height="23" viewBox="0 0 24 24" fill="none" '
    'stroke="#0d0d0d" stroke-width="1.7" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="M4 20 L5 15.5 L16.5 4 C17.6 2.9 '
    '19.4 2.9 20.5 4 C21.6 5.1 21.6 6.9 20.5 8 L9 19.5 L4 20 Z"/></svg>'
    '<svg width="34" height="34" viewBox="0 0 24 24" fill="#0d0d0d">'
    '<circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/>'
    '<circle cx="19" cy="12" r="1.7"/></svg>'
)
_ACR_PLUS = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" '
    'stroke="#0d0d0d" stroke-width="1.9" stroke-linecap="round">'
    '<path d="M12 5 V19 M5 12 H19"/></svg>'
)
_ACR_MIC = (
    '<svg width="15" height="22" viewBox="0 0 24 34" fill="none" '
    'stroke="#0d0d0d" stroke-width="2" stroke-linecap="round">'
    '<rect x="8" y="2" width="8" height="16" rx="4" fill="#0d0d0d" '
    'stroke="none"/><path d="M4 14 a8 8 0 0 0 16 0 M12 22 V28 M7 31 H17" '
    'stroke-width="2.2"/></svg>'
)
_ACR_SEND_GREY = (
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" '
    'stroke="#b6b6b6" stroke-width="2.6" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<path d="M12 19 V6 M6.5 11 L12 5.5 L17.5 11"/></svg>'
)
_ACR_SEND_WHITE = (
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" '
    'stroke="#fff" stroke-width="2.6" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<path d="M12 19 V6 M6.5 11 L12 5.5 L17.5 11"/></svg>'
)
_ACR_GLOBE = (
    '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" '
    'stroke="#000" stroke-width="2.6"><circle cx="12" cy="12" r="9.6"/>'
    '<path d="M2.4 12 H21.6 M12 2.4 C7.8 6.8 7.8 17.2 12 21.6 C16.2 17.2 '
    '16.2 6.8 12 2.4 M4 7 H20 M4 17 H20" stroke-width="2.2"/></svg>'
)
_ACR_KB_MIC = (
    '<svg width="16" height="25" viewBox="0 0 24 34" preserveAspectRatio="none" '
    'fill="none" stroke="#0d0d0d" stroke-width="3.9" stroke-linecap="round">'
    '<rect x="5.5" y="1" width="13" height="17.5" rx="6.5" fill="#0d0d0d" '
    'stroke="none"/>'
    '<path d="M2.5 14 a9.5 9.5 0 0 0 19 0 M12 23.5 V28.5 M5.5 32 H18.5"/></svg>'
)
_ACR_STAR = (
    '<svg class="acr-ecstar" width="80" height="80" viewBox="0 0 80 80">'
    '<g stroke="#2f6b57" stroke-width="8.5" stroke-linecap="round">'
    '<line x1="47" y1="40" x2="77" y2="40"/>'
    '<line x1="46.5" y1="42.7" x2="74.2" y2="54.2"/>'
    '<line x1="44.9" y1="44.9" x2="66.2" y2="66.2"/>'
    '<line x1="42.7" y1="46.5" x2="54.2" y2="74.2"/>'
    '<line x1="40" y1="47" x2="40" y2="77"/>'
    '<line x1="37.3" y1="46.5" x2="25.8" y2="74.2"/>'
    '<line x1="35.1" y1="44.9" x2="13.8" y2="66.2"/>'
    '<line x1="33.5" y1="42.7" x2="5.8" y2="54.2"/>'
    '<line x1="33" y1="40" x2="3" y2="40"/>'
    '<line x1="33.5" y1="37.3" x2="5.8" y2="25.8"/>'
    '<line x1="35.1" y1="35.1" x2="13.8" y2="13.8"/>'
    '<line x1="37.3" y1="33.5" x2="25.8" y2="5.8"/>'
    '<line x1="40" y1="33" x2="40" y2="3"/>'
    '<line x1="42.7" y1="33.5" x2="54.2" y2="5.8"/>'
    '<line x1="44.9" y1="35.1" x2="66.2" y2="13.8"/>'
    '<line x1="46.5" y1="37.3" x2="74.2" y2="25.8"/></g></svg>'
)
_ACR_PLAY = (
    '<svg width="40" height="46" viewBox="0 0 44 48" fill="none">'
    '<path d="M40.5 20.6 C43.2 22.1 43.2 25.9 40.5 27.4 L6.2 46.6 '
    'C3.5 48.1 0.2 46.2 0.2 43.2 L0.2 4.8 C0.2 1.8 3.5 -0.1 6.2 1.4 Z" '
    'fill="#0d0d0d"/></svg>'
)
_ACR_ARROW = (
    '<svg width="30" height="34" viewBox="0 0 16 24" fill="none" '
    'stroke="#0d0d0d" stroke-width="2.6" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="M2 2 L14 12 L2 22"/></svg>'
)


def _acr_clip(value: Any, fallback: str, max_len: int) -> str:
    text = str(value or "").strip() or fallback
    return text[:max_len] if len(text) > max_len else text


def _acr_has_copy(params: dict[str, Any]) -> bool:
    for key in ("userMessage", "prompt", "title", "snippet", "answer1"):
        if str(params.get(key) or "").strip():
            return True
    return False


def _acr_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _acr_copy(params: dict[str, Any]) -> dict[str, str]:
    user = (str(params.get("userMessage") or params.get("prompt")
                or params.get("title") or "").strip())
    snippet = str(params.get("snippet") or "").strip()
    if not user and snippet:
        user = snippet
        snippet = ""
    out = {
        key: _acr_clip(params.get(key), fallback, _ACR_MAX[key])
        for key, fallback in _ACR_DEFAULTS.items()
    }
    if user:
        out["userMessage"] = _acr_clip(user, out["userMessage"], _ACR_MAX["userMessage"])
    bits = _acr_sentences(snippet) if snippet else []
    if bits:
        out["answer1"] = _acr_clip(bits[0], out["answer1"], _ACR_MAX["answer1"])
        if len(bits) > 1:
            out["answer2"] = _acr_clip(bits[1], out["answer2"], _ACR_MAX["answer2"])
        if len(bits) > 2:
            out["answer3"] = _acr_clip(bits[2], out["answer3"], _ACR_MAX["answer3"])
    for key in ("answer1", "answer2", "answer3", "bullet1", "bullet2", "bullet3"):
        if str(params.get(key) or "").strip():
            out[key] = _acr_clip(params.get(key), out[key], _ACR_MAX[key])
    if str(params.get("botName") or params.get("app") or "").strip():
        out["botName"] = _acr_clip(
            params.get("botName") or params.get("app"),
            out["botName"], _ACR_MAX["botName"])
    for key in ("ecHeadline", "ecSub", "ecCta", "ecFooter"):
        if key in params and str(params.get(key) or "").strip():
            out[key] = _acr_clip(params.get(key), out[key], _ACR_MAX[key])
    return out


def _acr_type_end(message: str) -> float:
    t = _ACR_TYPE_START
    for n in range(2, max(2, len(message)) + 1):
        t += _ACR_KEY_GAPS[(n - 2) % len(_ACR_KEY_GAPS)]
    return t


def _acr_keys_html() -> str:
    parts: list[str] = []
    for top, left, letters in (
            (83, 13, "qwertyuiop"),
            (173, 48, "asdfghjkl"),
            (263, 123, "zxcvbnm")):
        for i, ch in enumerate(letters):
            x = left + i * 73.7
            parts.append(
                f'<div class="acr-key" style="left:{x:g}px;top:{top}px;width:62px">'
                f'{_esc(ch)}</div>')
    specials = (
        (13, 263, 97, " acr-gkey", _ACR_SHIFT),
        (640, 263, 98, " acr-gkey", _ACR_DEL),
        (13, 353, 97, " acr-gkey acr-num", "123"),
        (118, 353, 86, "", _ACR_EMOJI),
        (217, 353, 389, " acr-spc", "space"),
        (614, 353, 124, " acr-gkey", _ACR_RETURN),
    )
    for left, top, width, extra, body in specials:
        parts.append(
            f'<div class="acr-key{extra}" style="left:{left}px;top:{top}px;'
            f'width:{width}px">{body}</div>')
    return "".join(parts)


def _acr_char_spans(node_id: str, message: str) -> str:
    bits: list[str] = []
    for i, ch in enumerate(message):
        shown = "\u00a0" if ch == " " else _esc(ch)
        bits.append(f'<span id="{node_id}-ch{i}" class="acr-ch">{shown}</span>')
    return "".join(bits)


def ov_ai_chat_reveal(ctx: "TemplateCtx") -> Piece:
    """iPhone chat: keyboard rises, prompt types, answer streams, end card."""
    if not _acr_has_copy(ctx.params):
        return Piece()
    copy = _acr_copy(ctx.params)
    message = copy["userMessage"]
    if len(message) < 2:
        message = _ACR_DEFAULTS["userMessage"]
        copy["userMessage"] = message
    node_id = ctx.target
    start = ctx.start
    type_end = _acr_type_end(message)
    send = type_end + _ACR_SEND_GAP
    kid = f"{node_id}-kbd"
    cid = f"{node_id}-comp"
    tid = f"{node_id}-ctext"
    pid = f"{node_id}-ph"
    care = f"{node_id}-caret"
    bid = f"{node_id}-bubble"
    did = f"{node_id}-dot"
    ha, hb = f"{node_id}-ha", f"{node_id}-hb"
    sg, sb, st = f"{node_id}-sg", f"{node_id}-sb", f"{node_id}-st"
    ecid = f"{node_id}-ecin"

    tweens = [
        f'tl.fromTo("#{kid}",{{y:{_ACR_KEY_Y}}},'
        f'{{y:0,duration:{_num(_ACR_KEY_DUR)},ease:"power2.out"}},'
        f'{_num(start + _ACR_KEY_UP_AT)});',
        f'tl.fromTo("#{cid}",{{y:0}},'
        f'{{y:{_ACR_COMP_Y},duration:{_num(_ACR_KEY_DUR)},ease:"power2.out"}},'
        f'{_num(start + _ACR_KEY_UP_AT)});',
        f'tl.set("#{pid}",{{opacity:0}},{_num(start + _ACR_TYPE_START)});',
        f'tl.set("#{sg}",{{opacity:0}},{_num(start + _ACR_TYPE_START)});',
        f'tl.set("#{sb}",{{opacity:1}},{_num(start + _ACR_TYPE_START)});',
    ]
    t = _ACR_TYPE_START
    tweens.append(
        f'tl.set("#{node_id}-ch0",{{opacity:1}},{_num(start + t)});')
    tweens.append(
        f'tl.set("#{node_id}-ch1",{{opacity:1}},{_num(start + t)});')
    t += _ACR_KEY_GAPS[0]
    for n in range(3, len(message) + 1):
        tweens.append(
            f'tl.set("#{node_id}-ch{n - 1}",{{opacity:1}},{_num(start + t)});')
        t += _ACR_KEY_GAPS[(n - 2) % len(_ACR_KEY_GAPS)]
    caret_t = start + _ACR_TYPE_START
    on = True
    type_end_abs = start + type_end
    while caret_t < type_end_abs:
        tweens.append(
            f'tl.set("#{care}",{{opacity:{1 if on else 0}}},'
            f'{_num(caret_t)});')
        caret_t += _ACR_CARET_STEP
        on = not on
    send_abs = start + send
    tweens += [
        f'tl.set("#{care}",{{opacity:0}},{_num(send_abs)});',
        f'tl.set("#{tid}",{{opacity:0}},{_num(send_abs)});',
        f'tl.set("#{pid}",{{opacity:1}},{_num(send_abs)});',
        f'tl.set("#{sb}",{{opacity:0}},{_num(send_abs)});',
        f'tl.set("#{st}",{{opacity:1}},{_num(send_abs)});',
        f'tl.fromTo("#{bid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_ACR_BUBBLE_DUR)},ease:"power1.out"}},'
        f'{_num(send_abs - 0.03)});',
        f'tl.set("#{ha}",{{opacity:0}},{_num(send_abs)});',
        f'tl.set("#{hb}",{{opacity:1}},{_num(send_abs)});',
        f'tl.fromTo("#{kid}",{{y:0}},'
        f'{{y:{_ACR_KEY_Y},duration:{_num(_ACR_KEY_DUR)},ease:"power1.inOut",'
        f'immediateRender:false}},{_num(send_abs - 0.03)});',
        f'tl.fromTo("#{cid}",{{y:{_ACR_COMP_Y}}},'
        f'{{y:0,duration:{_num(_ACR_KEY_DUR)},ease:"power1.inOut",'
        f'immediateRender:false}},{_num(send_abs - 0.03)});',
    ]
    dot_start = send + _ACR_DOT_AT
    for i, alpha in enumerate(_ACR_DOT_RAMP):
        tweens.append(
            f'tl.set("#{did}",{{opacity:{_num(alpha)}}},'
            f'{_num(start + dot_start + i * _ACR_DOT_STEP)});')
    tweens.append(
        f'tl.set("#{did}",{{opacity:0}},'
        f'{_num(start + dot_start + _ACR_DOT_OFF)});')

    word_ids: list[str] = []

    def add_word(text: str, extra: str = "") -> str:
        wid = f"{node_id}-w{len(word_ids)}"
        word_ids.append(wid)
        cls = "acr-w" + (f" {extra}" if extra else "")
        return f'<span id="{wid}" class="{cls}">{_esc(text)}</span>'

    def para_html(text: str) -> str:
        bits = [add_word(w) for w in text.split()]
        return f'<p class="acr-ap">{" ".join(bits)}</p>'

    def bullet_html(text: str) -> str:
        mark = add_word("•", "acr-mark")
        bits = [add_word(w) for w in text.split()]
        return (f'<div class="acr-ali">{mark}'
                f'<div class="acr-alitext">{" ".join(bits)}</div></div>')

    answer = (
        para_html(copy["answer1"])
        + para_html(copy["answer2"])
        + para_html(copy["answer3"])
        + bullet_html(copy["bullet1"])
        + bullet_html(copy["bullet2"])
        + bullet_html(copy["bullet3"])
    )
    w = dot_start + _ACR_STREAM_AT
    for i, wid in enumerate(word_ids):
        if i:
            w += _ACR_WORD_GAPS[i % len(_ACR_WORD_GAPS)]
        tweens.append(f'tl.set("#{wid}",{{opacity:1}},{_num(start + w)});')
        tweens.append(
            f'tl.fromTo("#{wid}",{{color:"{_ACR_GREY}"}},'
            f'{{color:"{_ACR_INK}",duration:{_num(_ACR_INK_DUR)},ease:"none"}},'
            f'{_num(start + w)});')
    stop_at = start + w + _ACR_STOP_GAP
    tweens += [
        f'tl.set("#{st}",{{opacity:0}},{_num(stop_at)});',
        f'tl.set("#{sb}",{{opacity:1}},{_num(stop_at)});',
        f'tl.fromTo("#{ecid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_ACR_EC_DUR)},ease:"none"}},'
        f'{_num(start + _ACR_EC_AT)});',
    ]

    head_lines = "<br/>".join(
        _esc(line) for line in copy["ecHeadline"].split("|") if line)
    chars = _acr_char_spans(node_id, message)
    keys = _acr_keys_html()
    node = (
        f'<div id="{node_id}" class="clip overlay ai-chat-reveal" {_timing(ctx)}>'
        f'<div class="acr-chat"><div class="acr-stage">'
        f'<div class="acr-chat-bg"></div>'
        f'<div class="acr-statusbar"><div class="acr-clock">11:42</div>'
        f'<div class="acr-sicons">{_ACR_SIGNAL}{_ACR_WIFI}{_ACR_BATTERY}</div></div>'
        f'<div class="acr-header"><div class="acr-hleft">{_ACR_MENU}</div>'
        f'<div class="acr-htitle">{_esc(copy["botName"])}</div>'
        f'<div id="{ha}" class="acr-hicons acr-hicons-a">{_ACR_HICONS_A}</div>'
        f'<div id="{hb}" class="acr-hicons acr-hicons-b">{_ACR_HICONS_B}</div></div>'
        f'<div id="{bid}" class="acr-bubble">{_esc(message)}</div>'
        f'<div id="{did}" class="acr-dot"></div>'
        f'<div class="acr-answer">{answer}</div>'
        f'<div id="{cid}" class="acr-composer"><div class="acr-pill">'
        f'<div class="acr-plusi">{_ACR_PLUS}</div>'
        f'<div id="{pid}" class="acr-ph">Ask anything</div>'
        f'<div class="acr-ctextwrap"><span id="{tid}" class="acr-ctext">{chars}</span>'
        f'<span id="{care}" class="acr-caret"></span></div>'
        f'<div class="acr-cmic">{_ACR_MIC}</div>'
        f'<div id="{sg}" class="acr-cbtn acr-btn-grey">{_ACR_SEND_GREY}</div>'
        f'<div id="{sb}" class="acr-cbtn acr-btn-black">{_ACR_SEND_WHITE}</div>'
        f'<div id="{st}" class="acr-cbtn acr-btn-stop"><div class="acr-sq"></div></div>'
        f'</div></div>'
        f'<div id="{kid}" class="acr-keyboard">'
        f'<div class="acr-suggest"><div class="acr-sug">How</div>'
        f'<div class="acr-sug">Can</div><div class="acr-sug">My</div></div>'
        f'<div class="acr-keys">{keys}</div>'
        f'<div class="acr-kbstrip"><span class="acr-kglobe">{_ACR_GLOBE}</span>'
        f'<span class="acr-kmic">{_ACR_KB_MIC}</span></div></div>'
        f'</div></div>'
        f'<div class="acr-endcard"><div id="{ecid}" class="acr-endcard-inner">'
        f'<div class="acr-stage">'
        f'<div class="acr-eclogo">РЕДШИФТ</div>{_ACR_STAR}'
        f'<div class="acr-ecvideo"><div class="acr-play">{_ACR_PLAY}</div></div>'
        f'<div class="acr-echead">{head_lines}</div>'
        f'<div class="acr-ecsub">{_esc(copy["ecSub"])}</div>'
        f'<div class="acr-eccta"><span class="acr-lbl">{_esc(copy["ecCta"])}</span>'
        f'{_ACR_ARROW}</div>'
        f'<div class="acr-ecfoot">{_esc(copy["ecFooter"])}</div>'
        f'</div></div></div></div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def acr_overlay_css() -> str:
    """Full-bleed iPhone mock. Stage 750×1624 scaled into 1080×1920."""
    scale = f"{_ACR_STAGE_SCALE:.8f}".rstrip("0").rstrip(".")
    left = f"{_ACR_STAGE_LEFT:g}"
    return (
        ".ai-chat-reveal{left:0;top:0;width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden;font-family:Inter,var(--font-subtitle),sans-serif;"
        "color:#0d0d0d}"
        ".ai-chat-reveal .acr-chat,.ai-chat-reveal .acr-endcard"
        "{position:absolute;inset:0}"
        ".ai-chat-reveal .acr-chat{background:#fdfdfd}"
        ".ai-chat-reveal .acr-stage{position:absolute;"
        "left:__ACR_LEFT__px;top:0;width:750px;height:1624px;"
        "transform:scale(__ACR_SCALE__);transform-origin:top left}"
        ".ai-chat-reveal .acr-chat-bg{position:absolute;inset:0;background:#fdfdfd}"
        ".ai-chat-reveal .acr-statusbar{position:absolute;top:14px;left:0;right:0;"
        "height:44px}"
        ".ai-chat-reveal .acr-clock{position:absolute;left:39px;top:9px;"
        "font-size:22px;font-weight:600;letter-spacing:2.4px;"
        "font-variant-numeric:tabular-nums;color:#0d0d0d}"
        ".ai-chat-reveal .acr-sicons{position:absolute;right:26px;top:8px;"
        "display:flex;gap:9px;align-items:center}"
        ".ai-chat-reveal .acr-header{position:absolute;top:64px;left:0;right:0;"
        "height:52px}"
        ".ai-chat-reveal .acr-hleft{position:absolute;left:28px;top:12px}"
        ".ai-chat-reveal .acr-htitle{position:absolute;left:0;right:48px;"
        "text-align:center;top:13px;font-size:22px;font-weight:600;color:#0d0d0d}"
        ".ai-chat-reveal .acr-hicons{position:absolute;right:28px;top:14px;"
        "display:flex;gap:26px;align-items:center}"
        ".ai-chat-reveal .acr-hicons-b{opacity:0}"
        ".ai-chat-reveal .acr-bubble{position:absolute;top:129px;right:32px;"
        "max-width:544px;background:#f3f3f3;border-radius:34px;"
        "padding:20px 30px;font-size:27px;line-height:38.6px;color:#111;"
        "letter-spacing:1.25px;opacity:0}"
        ".ai-chat-reveal .acr-answer{position:absolute;top:267px;left:33px;"
        "width:662px;font-size:27px;line-height:38.6px;color:#141414;"
        "letter-spacing:1.25px}"
        ".ai-chat-reveal .acr-ap{margin:0 0 15.5px}"
        ".ai-chat-reveal .acr-ali{display:flex;margin:0 0 6.5px}"
        ".ai-chat-reveal .acr-mark{width:30px;flex:0 0 30px;text-align:center;"
        "font-size:18px;line-height:38.6px}"
        ".ai-chat-reveal .acr-alitext{flex:1}"
        ".ai-chat-reveal .acr-w{opacity:0;color:#767676}"
        ".ai-chat-reveal .acr-dot{position:absolute;left:32px;top:279px;"
        "width:15px;height:15px;border-radius:50%;background:#646464;opacity:0}"
        ".ai-chat-reveal .acr-composer{position:absolute;left:30px;right:30px;"
        "bottom:31px;will-change:transform}"
        ".ai-chat-reveal .acr-pill{position:relative;width:100%;min-height:81px;"
        "background:#fff;border:2px solid #ececec;border-radius:41px;"
        "box-shadow:0 4px 14px rgba(0,0,0,0.04);display:flex;align-items:center;"
        "padding:13px 160px 13px 78px}"
        ".ai-chat-reveal .acr-plusi{position:absolute;left:30px;top:50%;"
        "margin-top:-11px}"
        ".ai-chat-reveal .acr-ph{position:absolute;left:78px;top:50%;"
        "margin-top:-16px;color:#767676;font-size:28px;letter-spacing:1.25px}"
        ".ai-chat-reveal .acr-ctextwrap{width:100%;min-height:38px;"
        "white-space:pre}"
        ".ai-chat-reveal .acr-ctext{font-size:29px;line-height:38px;color:#0d0d0d;"
        "letter-spacing:1.25px}"
        ".ai-chat-reveal .acr-ch{opacity:0}"
        ".ai-chat-reveal .acr-caret{display:inline-block;width:3px;height:30px;"
        "margin-left:2px;border-radius:1.5px;background:#0d0d0d;"
        "vertical-align:-4px;opacity:0}"
        ".ai-chat-reveal .acr-cmic{position:absolute;right:80px;top:50%;"
        "margin-top:-11px}"
        ".ai-chat-reveal .acr-cbtn{position:absolute;right:14px;top:50%;"
        "margin-top:-26px;width:52px;height:52px;border-radius:50%;"
        "display:grid;place-items:center}"
        ".ai-chat-reveal .acr-btn-grey{background:#ececec}"
        ".ai-chat-reveal .acr-btn-black{background:#0d0d0d;opacity:0}"
        ".ai-chat-reveal .acr-btn-stop{background:#0d0d0d;opacity:0}"
        ".ai-chat-reveal .acr-sq{width:19px;height:19px;border-radius:5px;"
        "background:#fff}"
        ".ai-chat-reveal .acr-keyboard{position:absolute;left:0;bottom:0;"
        "width:750px;height:482px;background:#d2d5e0;will-change:transform}"
        ".ai-chat-reveal .acr-suggest{position:absolute;top:0;left:0;right:0;"
        "height:74px;display:flex}"
        ".ai-chat-reveal .acr-sug{flex:1;display:grid;place-items:center;"
        "font-size:29px;color:#0d0d0d;position:relative}"
        ".ai-chat-reveal .acr-sug+.acr-sug::before{content:'';position:absolute;"
        "left:0;top:16px;bottom:16px;width:1.5px;background:#bcbabf}"
        ".ai-chat-reveal .acr-key{position:absolute;height:74px;background:#fdfdfd;"
        "border-radius:10px;box-shadow:0 2px 0 #8b8a8f;display:grid;"
        "place-items:center;font-size:32px;color:#000}"
        ".ai-chat-reveal .acr-gkey{background:#aeacaf}"
        ".ai-chat-reveal .acr-num,.ai-chat-reveal .acr-spc{font-size:27px}"
        ".ai-chat-reveal .acr-kbstrip{position:absolute;bottom:10px;left:0;right:0;"
        "height:52px}"
        ".ai-chat-reveal .acr-kglobe{position:absolute;left:48px;top:21px}"
        ".ai-chat-reveal .acr-kmic{position:absolute;right:52px;top:23px}"
        ".ai-chat-reveal .acr-endcard-inner{position:absolute;inset:0;"
        "background:linear-gradient(180deg,#111214 0%,#0a0a0c 100%);opacity:0}"
        ".ai-chat-reveal .acr-eclogo{position:absolute;left:255px;top:112px;"
        "font-weight:800;font-size:42px;letter-spacing:0.12em;color:#F7F5F3}"
        ".ai-chat-reveal .acr-ecstar{position:absolute;left:610px;top:230px}"
        ".ai-chat-reveal .acr-ecvideo{position:absolute;left:222px;top:336px;"
        "width:283px;height:454px;border-radius:36px;"
        "background:linear-gradient(165deg,#8E2F2A 0%,#C8453D 78%,#E4726A 100%);"
        "box-shadow:0 24px 60px rgba(0,0,0,0.45)}"
        ".ai-chat-reveal .acr-play{position:absolute;left:50%;top:50%;"
        "width:108px;height:108px;margin-left:-54px;margin-top:-54px;"
        "border-radius:50%;background:rgba(253,253,253,0.94);display:grid;"
        "place-items:center}"
        ".ai-chat-reveal .acr-echead{position:absolute;top:946px;left:0;right:0;"
        "text-align:center;font-weight:700;font-size:57px;line-height:58px;"
        "color:#F7F5F3;letter-spacing:0.5px}"
        ".ai-chat-reveal .acr-ecsub{position:absolute;top:1084px;left:65px;"
        "right:65px;text-align:center;font-weight:500;font-size:31px;"
        "line-height:40px;color:#7A7D82}"
        ".ai-chat-reveal .acr-eccta{position:absolute;left:160px;top:1406px;"
        "width:429px;height:87px;background:#C8453D;border-radius:44px;"
        "display:flex;align-items:center;justify-content:center;gap:22px}"
        ".ai-chat-reveal .acr-lbl{color:#ffffff;font-weight:700;font-size:33px;"
        "letter-spacing:0.3px}"
        ".ai-chat-reveal .acr-ecfoot{position:absolute;top:1536px;left:0;right:0;"
        "text-align:center;font-weight:700;font-size:25px;letter-spacing:4px;"
        "color:#E4726A}"
    ).replace("__ACR_LEFT__", left).replace("__ACR_SCALE__", scale)
