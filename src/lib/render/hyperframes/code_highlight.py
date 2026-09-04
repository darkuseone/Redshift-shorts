"""Code Highlight — syntax-highlighted code block with sweep highlight box.

Catalog ``code-highlight`` demonstrates code editor display with
syntax highlighting, line numbers, and a sweep highlight box that focuses
on a target line while dimming surrounding code.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
scale settle entrance, scaleX sweep highlight on target line, line dimming,
and glow field background.
No forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import (
    Piece,
    TemplateCtx,
    _num,
    _timing,
    _enter_at,
    _esc,
    _c3d_highlight,
    _cd_rows_from_tokens,
    _cs_pick_line,
    _cs_metrics,
    _CS_FRAME_W,
    _CS_FRAME_H,
    _CS_PAD_TOP,
    _CS_PAD_X,
    _CS_GUTTER,
)


def _ch_times(duration: float) -> dict[str, float]:
    d = max(0.8, float(duration))
    enter = round(min(0.5, d * 0.15), 4)
    fade = round(min(0.4, d * 0.12), 4)
    sweep_dur = round(min(0.8, d * 0.25), 4)
    sweep_at = round(enter + fade + 0.1, 4)
    return {
        "enter": enter,
        "fade": fade,
        "fade_at": round(enter * 0.5, 4),
        "sweep_at": sweep_at,
        "sweep_dur": sweep_dur,
    }


def fs_code_highlight(ctx: TemplateCtx) -> Piece:
    """Code highlight: syntax-highlighted code with sweep highlight box."""
    params = ctx.params
    code = str(params.get("code") or params.get("content") or params.get("text")
               or "").replace("\r\n", "\n").replace("\t", "  ").strip("\n")
    if not code.strip():
        code = (
            'async function loadConfig(path) {\n'
            '  const raw = await readFile(path, "utf8")\n'
            '  const config = JSON.parse(raw)\n'
            '  return validate(config)\n'
            '}'
        )
    raw_tokens = params.get("tokens")
    token_rows = _cd_rows_from_tokens(raw_tokens)
    if token_rows is not None:
        lines = token_rows
    else:
        lines = _c3d_highlight(code)
    if not lines:
        return Piece()

    raws = ["".join(text for text, _color in line) for line in lines]
    idx = _cs_pick_line(raws, params)
    node_id = ctx.target
    frame_w = int(params.get("frame_w") or _CS_FRAME_W)
    frame_h = int(params.get("frame_h") or _CS_FRAME_H)
    vis = len(lines)
    size, lh, editor_w, editor_h, surface_h = _cs_metrics(raws, frame_w, frame_h, vis)
    hl_top = _CS_PAD_TOP + idx * lh
    t = _ch_times(ctx.duration)
    at = _enter_at(ctx)
    filename = str(params.get("filename") or "loadConfig.js")
    accent_title = f'<span class="cs-file">{_esc(filename)}</span> — Code Highlight Sweep'

    tweens = [
        f'tl.fromTo("#{node_id}-editor",'
        f'{{opacity:0,scale:0.985}},'
        f'{{opacity:1,scale:1,duration:{_num(t["enter"])},ease:"power2.out"}},{_num(at)});',
        f'tl.fromTo("#{node_id}-surface",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(t["fade"])},ease:"power1.out"}},{_num(at + t["fade_at"])});',
        f'tl.fromTo("#{node_id}-hl",{{scaleX:0,opacity:0}},'
        f'{{scaleX:1,opacity:1,duration:{_num(t["sweep_dur"])},ease:"power2.inOut"}},'
        f'{_num(at + t["sweep_at"])});',
    ]

    for i in range(len(lines)):
        if i == idx:
            continue
        tweens.append(
            f'tl.fromTo("#{node_id}-ln{i}",{{opacity:1}},'
            f'{{opacity:0.42,duration:{_num(t["sweep_dur"])},ease:"power2.inOut"}},'
            f'{_num(at + t["sweep_at"])});'
        )

    gutter_html = "".join(
        f'<span class="cs-gn" style="height:{lh}px;line-height:{lh}px">{i}</span>'
        for i in range(1, len(lines) + 1)
    )
    line_html: list[str] = []
    for i, line in enumerate(lines):
        inner = "".join(
            f'<span class="cs-tok" style="color:{color}">{_esc(text)}</span>'
            for text, color in line
        )
        line_html.append(
            f'<div id="{node_id}-ln{i}" class="cs-line" style="height:{lh}px;line-height:{lh}px">{inner}</div>'
        )

    node = (
        f'<div id="{node_id}" class="clip fullscreen-text fs-code-highlight" {_timing(ctx)}>'
        f'<div class="cs-stage">'
        f'<div class="cs-grid"></div>'
        f'<div class="cs-glow cs-glow-a"></div>'
        f'<div class="cs-glow cs-glow-b"></div>'
        f'<div id="{node_id}-editor" class="cs-editor" style="width:{editor_w}px;height:{editor_h}px">'
        f'<div class="cs-titlebar">'
        f'<div class="cs-dots">'
        f'<span class="cs-dot cs-dot-r"></span>'
        f'<span class="cs-dot cs-dot-y"></span>'
        f'<span class="cs-dot cs-dot-g"></span>'
        f'</div>'
        f'<span class="cs-filename">{accent_title}</span>'
        f'</div>'
        f'<div id="{node_id}-surface" class="cs-surface" style="width:{editor_w}px;height:{surface_h}px">'
        f'<div id="{node_id}-hl" class="cs-hl" style="top:{hl_top}px;height:{lh}px;transform-origin:left center"></div>'
        f'<div class="cs-gutter" style="width:{_CS_GUTTER}px;padding-top:{_CS_PAD_TOP}px;font-size:{size}px">{gutter_html}</div>'
        f'<div class="cs-code" style="padding-left:{_CS_GUTTER + _CS_PAD_X}px;padding-top:{_CS_PAD_TOP}px;font-size:{size}px">{"".join(line_html)}</div>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def ch_fullscreen_css() -> str:
    """CSS for Code Highlight fullscreen text."""
    return (
        ".fullscreen-text.fs-code-highlight{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;display:flex;"
        "align-items:center;justify-content:center;"
        "background:radial-gradient(120% 70% at 50% 18%,#0e1726 0%,#05070b 72%);"
        "font-family:'JetBrains Mono',var(--font-mono),monospace;font-weight:500;"
        "text-transform:none;letter-spacing:0;color:#e6edf3}"
        ".fullscreen-text.fs-code-highlight .cs-hl{"
        "background:rgba(88,166,255,0.18);border-left:3px solid #58a6ff;"
        "border-radius:6px;box-shadow:0 0 20px rgba(88,166,255,0.25)}"
    )
