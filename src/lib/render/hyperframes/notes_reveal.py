"""Notes Reveal — Apple Notes typing reveal, paper scroll, and marker closing card.

Catalog ``notes-reveal`` measures character bounds dynamically.
Here character spans are pre-baked with opacity reveals, smooth scroll via transform y,
and clean crossfade into the closing card.
No tween of width/height/filter/clip-path/strokeDashoffset; no textContent writes.
Brandbook ink #111214, accent #C8453D / #E4726A, Inter font.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_NR_CATALOG = 24.85

_NR_DEFAULTS = {
    "titleL1": "Things nobody told me",
    "titleL2": "about video.",
    "noteLine1": "my videos sucked",
    "noteLine2": "my tools cost 675299675299",
    "noteLine3": "and re-edits never end.",
    "noteLine4": "then i tried writing html only",
    "noteLine5": "started HyperFrames three weeks ago",
    "noteLine6": "the grind is gone, but more than that —",
    "noteLine7": "I ship videos weekly.",
    "cardTop": "THE POWER",
    "cardMid": "OF",
    "cardBottom": "ONE FILE",
    "check1Label": "WRITE",
    "check1Value": "HTML",
    "check2Label": "RENDER",
    "check2Value": "IN 4K",
    "check3Label": "SHIP",
    "check3Value": "TODAY",
    "brandDomain": "hyperframes.heygen.com",
}

_NR_MAX = {
    "title": 60,
    "line": 80,
    "card": 32,
    "check": 24,
    "domain": 40,
}


def _nr_clip(val: Any, default: str, max_len: int) -> str:
    text = str(val if val is not None else default).strip()
    return text[:max_len] if len(text) > max_len else text


def _nr_has_copy(params: dict[str, Any]) -> bool:
    if not params:
        return False
    keys = (
        "titleL1", "titleL2", "noteLine1", "noteLine4", "noteLine5",
        "cardTop", "title", "snippet", "prompt",
    )
    return any(str(params.get(k) or "").strip() for k in keys)


def _nr_copy(params: dict[str, Any]) -> dict[str, Any]:
    t1 = params.get("titleL1") or params.get("title") or _NR_DEFAULTS["titleL1"]
    l4 = params.get("noteLine4") or params.get("snippet") or _NR_DEFAULTS["noteLine4"]
    domain = params.get("brandDomain") or params.get("domain") or _NR_DEFAULTS["brandDomain"]
    return {
        "titleL1": _nr_clip(t1, _NR_DEFAULTS["titleL1"], _NR_MAX["title"]),
        "titleL2": _nr_clip(params.get("titleL2"), _NR_DEFAULTS["titleL2"], _NR_MAX["title"]),
        "noteLine1": _nr_clip(params.get("noteLine1"), _NR_DEFAULTS["noteLine1"], _NR_MAX["line"]),
        "noteLine2": _nr_clip(params.get("noteLine2"), _NR_DEFAULTS["noteLine2"], _NR_MAX["line"]),
        "noteLine3": _nr_clip(params.get("noteLine3"), _NR_DEFAULTS["noteLine3"], _NR_MAX["line"]),
        "noteLine4": _nr_clip(l4, _NR_DEFAULTS["noteLine4"], _NR_MAX["line"]),
        "noteLine5": _nr_clip(params.get("noteLine5"), _NR_DEFAULTS["noteLine5"], _NR_MAX["line"]),
        "noteLine6": _nr_clip(params.get("noteLine6"), _NR_DEFAULTS["noteLine6"], _NR_MAX["line"]),
        "noteLine7": _nr_clip(params.get("noteLine7"), _NR_DEFAULTS["noteLine7"], _NR_MAX["line"]),
        "cardTop": _nr_clip(params.get("cardTop"), _NR_DEFAULTS["cardTop"], _NR_MAX["card"]),
        "cardMid": _nr_clip(params.get("cardMid"), _NR_DEFAULTS["cardMid"], _NR_MAX["card"]),
        "cardBottom": _nr_clip(params.get("cardBottom"), _NR_DEFAULTS["cardBottom"], _NR_MAX["card"]),
        "check1Label": _nr_clip(params.get("check1Label"), _NR_DEFAULTS["check1Label"], _NR_MAX["check"]),
        "check1Value": _nr_clip(params.get("check1Value"), _NR_DEFAULTS["check1Value"], _NR_MAX["check"]),
        "check2Label": _nr_clip(params.get("check2Label"), _NR_DEFAULTS["check2Label"], _NR_MAX["check"]),
        "check2Value": _nr_clip(params.get("check2Value"), _NR_DEFAULTS["check2Value"], _NR_MAX["check"]),
        "check3Label": _nr_clip(params.get("check3Label"), _NR_DEFAULTS["check3Label"], _NR_MAX["check"]),
        "check3Value": _nr_clip(params.get("check3Value"), _NR_DEFAULTS["check3Value"], _NR_MAX["check"]),
        "brandDomain": _nr_clip(domain, _NR_DEFAULTS["brandDomain"], _NR_MAX["domain"]),
    }


def ov_notes_reveal(ctx: TemplateCtx) -> Piece:
    """Notes Reveal: Apple Notes typing animation and closing paper card."""
    if not _nr_has_copy(ctx.params):
        return Piece()

    copy = _nr_copy(ctx.params)
    node_id = ctx.target
    start = ctx.start
    duration = max(float(ctx.duration), 3.0)
    scale = duration / _NR_CATALOG

    def dur(catalog_sec: float) -> float:
        return max(0.001, catalog_sec * scale)

    tweens: list[str] = []

    lines = [
        copy["noteLine1"],
        copy["noteLine2"],
        copy["noteLine3"],
        copy["noteLine4"],
        copy["noteLine5"],
        copy["noteLine6"],
        copy["noteLine7"],
    ]

    # Line typing times across ~20s
    line_starts = [0.8, 3.2, 5.8, 8.8, 12.0, 15.2, 18.0]
    scroll_times = [(12.0, -120), (15.2, -260), (18.0, -380)]

    for l_idx, (line_text, l_start_cat) in enumerate(zip(lines, line_starts)):
        t_line = start + dur(l_start_cat)
        words = line_text.split()
        w_step = dur(1.8) / max(1, len(words))
        for w_idx, w in enumerate(words):
            tw_time = t_line + w_idx * w_step
            tweens.append(
                f'tl.fromTo("#{node_id}-w-{l_idx}-{w_idx}",{{opacity:0}},'
                f'{{opacity:1,duration:{_num(dur(0.08))}}},'
                f'{_num(tw_time)});'
            )

    # Scrolling the notes body
    for st, y_offset in scroll_times:
        tweens.append(
            f'tl.to("#{node_id}-notebody",{{y:{y_offset},duration:{_num(dur(0.6))},ease:"power2.out"}},'
            f'{_num(start + dur(st))});'
        )

    # Crossfade into Card Scene at ~21.3s
    t_fade = start + dur(21.3)
    tweens.append(
        f'tl.to("#{node_id}-notescene",{{opacity:0,duration:{_num(dur(0.4))},ease:"none"}},'
        f'{_num(t_fade)});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-cardscene",{{opacity:0,scale:0.96}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.45))},ease:"power2.out"}},'
        f'{_num(t_fade + dur(0.1))});'
    )

    # Card highlights / underlines reveal
    tweens.append(
        f'tl.fromTo("#{node_id}-card-line",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(dur(0.35))},ease:"power2.out"}},'
        f'{_num(t_fade + dur(0.4))});'
    )
    tweens.append(
        f'tl.fromTo("#{node_id}-card-ring",{{opacity:0,scale:0.8}},'
        f'{{opacity:1,scale:1,duration:{_num(dur(0.3))},ease:"back.out(1.5)"}},'
        f'{_num(t_fade + dur(0.6))});'
    )

    # Build HTML
    lines_markup = []
    for l_idx, line_text in enumerate(lines):
        spans = [
            f'<span id="{node_id}-w-{l_idx}-{w_idx}" class="nr-w">{_esc(w)}</span>'
            for w_idx, w in enumerate(line_text.split())
        ]
        lines_markup.append(
            f'<div class="nr-line">{" ".join(spans)}</div>'
        )

    node = (
        f'<div id="{node_id}" class="clip overlay notes-reveal" {_timing(ctx)}>'
        # Card Scene (underneath)
        f'<div id="{node_id}-cardscene" class="nr-cardscene" style="opacity:0">'
        f'<div class="nr-card-dots"></div>'
        f'<div class="nr-card-paper">'
        f'<div class="nr-card-hl1">{_esc(copy["cardTop"])}</div>'
        f'<div id="{node_id}-card-line" class="nr-card-underline"></div>'
        f'<div class="nr-card-mid">{_esc(copy["cardMid"])}</div>'
        f'<div class="nr-card-hl2"><span id="{node_id}-card-ring" class="nr-card-ring"></span>{_esc(copy["cardBottom"])}</div>'
        f'<div class="nr-card-checklist">'
        f'<div class="nr-check-row"><span class="nr-chk-lbl">{_esc(copy["check1Label"])}</span><span class="nr-chk-val">{_esc(copy["check1Value"])}</span></div>'
        f'<div class="nr-check-row"><span class="nr-chk-lbl">{_esc(copy["check2Label"])}</span><span class="nr-chk-val">{_esc(copy["check2Value"])}</span></div>'
        f'<div class="nr-check-row"><span class="nr-chk-lbl">{_esc(copy["check3Label"])}</span><span class="nr-chk-val">{_esc(copy["check3Value"])}</span></div>'
        f'</div>'
        f'<div class="nr-card-footer">'
        f'<div class="nr-card-domain">{_esc(copy["brandDomain"])}</div>'
        f'</div>'
        f'</div></div>'
        # Notes Scene (top)
        f'<div id="{node_id}-notescene" class="nr-notescene">'
        f'<div class="nr-statusbar">'
        f'<div class="nr-sb-time">9:41</div>'
        f'<div class="nr-sb-icons"><svg width="24" height="16" viewBox="0 0 24 16" fill="#111214"><rect x="1" y="1" width="18" height="14" rx="3" stroke="#111214" stroke-width="1.5" fill="none"/><rect x="3" y="3" width="12" height="10" rx="1.5" fill="#111214"/><path d="M21 5v6" stroke="#111214" stroke-width="2" stroke-linecap="round"/></svg></div>'
        f'</div>'
        f'<div class="nr-header">'
        f'<div class="nr-hdr-back">‹ Notes</div>'
        f'<div class="nr-hdr-tools"><svg width="26" height="26" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="#e4a824" stroke-width="2"/><path d="M12 8v8M8 12h8" stroke="#e4a824" stroke-width="2" stroke-linecap="round"/></svg></div>'
        f'</div>'
        f'<div class="nr-note-view">'
        f'<div id="{node_id}-notebody" class="nr-notebody">'
        f'<div class="nr-title-l1">{_esc(copy["titleL1"])}</div>'
        f'<div class="nr-title-l2">{_esc(copy["titleL2"])}</div>'
        f'<div class="nr-date-header">Today at 9:41 AM</div>'
        f'<div class="nr-lines">'
        f'{" ".join(lines_markup)}'
        f'</div>'
        f'</div></div>'
        f'</div>'  # end notescene
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def nr_overlay_css() -> str:
    """CSS for Notes Reveal template."""
    return (
        ".notes-reveal{position:absolute;inset:0;width:1080px;height:1920px;"
        "overflow:hidden;background:#000;font-family:Inter,system-ui,sans-serif;"
        "-webkit-font-smoothing:antialiased;color:#111214}"
        ".notes-reveal .nr-notescene{position:absolute;inset:0;background:#fcfbf8;"
        "display:flex;flex-direction:column;z-index:2}"
        ".notes-reveal .nr-statusbar{height:80px;display:flex;align-items:center;"
        "justify-content:space-between;padding:0 50px;font-size:28px;font-weight:600}"
        ".notes-reveal .nr-header{height:90px;display:flex;align-items:center;"
        "justify-content:space-between;padding:0 40px;border-bottom:1px solid rgba(0,0,0,0.06)}"
        ".notes-reveal .nr-hdr-back{font-size:32px;font-weight:500;color:#e4a824}"
        ".notes-reveal .nr-note-view{position:relative;flex:1;overflow:hidden;padding:0 50px}"
        ".notes-reveal .nr-notebody{position:relative;padding-top:40px;will-change:transform}"
        ".notes-reveal .nr-title-l1{font-size:60px;font-weight:800;color:#111214;line-height:1.15}"
        ".notes-reveal .nr-title-l2{font-size:60px;font-weight:800;color:#111214;line-height:1.15;margin-bottom:16px}"
        ".notes-reveal .nr-date-header{font-size:24px;font-weight:500;color:#8e8e93;margin-bottom:44px}"
        ".notes-reveal .nr-lines{display:flex;flex-direction:column;gap:28px}"
        ".notes-reveal .nr-line{font-size:42px;line-height:56px;color:#1d1d1f;font-weight:400}"
        ".notes-reveal .nr-w{opacity:0;display:inline-block}"
        ".notes-reveal .nr-cardscene{position:absolute;inset:0;background:#ece1d5;"
        "display:flex;align-items:center;justify-content:center;z-index:1;padding:60px 40px}"
        ".notes-reveal .nr-card-dots{position:absolute;inset:0;"
        "background-image:radial-gradient(circle,rgba(178,150,138,0.22) 2px,transparent 2.6px);"
        "background-size:36px 36px}"
        ".notes-reveal .nr-card-paper{position:relative;width:100%;max-width:880px;background:#fcfcfc;"
        "border-radius:28px;padding:70px 60px;box-shadow:0 24px 60px rgba(90,60,40,0.14);"
        "display:flex;flex-direction:column;align-items:center;transform:rotate(-2.5deg)}"
        ".notes-reveal .nr-card-hl1{font-size:80px;font-weight:900;color:#C8453D;letter-spacing:1px;"
        "text-transform:uppercase;line-height:1}"
        ".notes-reveal .nr-card-underline{width:360px;height:8px;border-radius:4px;background:#C8453D;"
        "margin:10px 0 20px;transform-origin:left center;will-change:transform}"
        ".notes-reveal .nr-card-mid{font-size:52px;font-weight:800;color:#111214;margin-bottom:14px}"
        ".notes-reveal .nr-card-hl2{position:relative;font-size:74px;font-weight:900;color:#111214;"
        "letter-spacing:1px;text-transform:uppercase;line-height:1;margin-bottom:50px}"
        ".notes-reveal .nr-card-ring{position:absolute;left:-16px;top:-10px;right:-16px;bottom:-10px;"
        "border:4px solid #C8453D;border-radius:24px;will-change:transform,opacity}"
        ".notes-reveal .nr-card-checklist{display:flex;flex-direction:column;gap:20px;width:100%;"
        "margin-bottom:60px}"
        ".notes-reveal .nr-check-row{display:flex;align-items:center;justify-content:space-between;"
        "padding:16px 24px;background:#f4f0eb;border-radius:18px}"
        ".notes-reveal .nr-chk-lbl{font-size:30px;font-weight:700;color:#6b6b70;letter-spacing:1px}"
        ".notes-reveal .nr-chk-val{font-size:32px;font-weight:900;color:#111214}"
        ".notes-reveal .nr-card-footer{display:flex;align-items:center;justify-content:center}"
        ".notes-reveal .nr-card-domain{font-size:28px;font-weight:700;color:#C8453D}"
    )
