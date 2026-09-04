"""Code Morph — FLIP morph between code states with token translation.

Catalog ``code-morph`` demonstrates refactoring from imperative loops
to functional chains or before/after state transition with smooth token
repositioning (FLIP) and entering/exiting fade.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
scale settle entrance, token-level x/y translation for matching symbols,
fade-in for new statements, fade-out for removed code, and glow field background.
No forbidden GSAP properties (strictly opacity, scale, x, y).
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
    _cd_parse_pair,
    _cs_metrics,
    _CS_FRAME_W,
    _CS_FRAME_H,
    _CS_PAD_TOP,
    _CS_PAD_X,
    _CS_GUTTER,
    _C3D_MONO_EM,
)

_DEFAULT_BEFORE = (
    'function activeNames(users) {\n'
    '  const out = []\n'
    '  for (const u of users) {\n'
    '    if (u.active) {\n'
    '      out.push(u.name)\n'
    '    }\n'
    '  }\n'
    '  return out\n'
    '}'
)

_DEFAULT_AFTER = (
    'function activeNames(users) {\n'
    '  return users\n'
    '    .filter((u) => u.active)\n'
    '    .map((u) => u.name)\n'
    '}'
)


def _cm_times(duration: float) -> dict[str, float]:
    d = max(1.0, float(duration))
    enter_dur = round(min(0.5, d * 0.12), 4)
    fade_dur = round(min(0.4, d * 0.10), 4)
    hold_before = round(max(0.4, d * 0.22), 4)
    morph_dur = round(min(1.2, d * 0.28), 4)
    morph_at = round(enter_dur + hold_before, 4)
    enter_delay = round(morph_dur * 0.35, 4)
    fade_out_dur = round(morph_dur * 0.5, 4)
    fade_in_dur = round(morph_dur * 0.55, 4)
    return {
        "enter_dur": enter_dur,
        "fade_dur": fade_dur,
        "fade_at": round(enter_dur * 0.5, 4),
        "morph_at": morph_at,
        "morph_dur": morph_dur,
        "enter_delay": enter_delay,
        "fade_out_dur": fade_out_dur,
        "fade_in_dur": fade_in_dur,
    }


def fs_code_morph(ctx: TemplateCtx) -> Piece:
    """Code morph: FLIP morph between two code states."""
    params = ctx.params
    before_rows = _cd_rows_from_tokens(params.get("tokens_before"))
    after_rows = _cd_rows_from_tokens(params.get("tokens_after"))
    before, after = _cd_parse_pair(params)

    # Empty content check
    if "content" in params and not str(params.get("content") or "").strip() and not before.strip() and not after.strip():
        return Piece()

    if before_rows is not None:
        a_lines = before_rows
    elif before.strip():
        a_lines = _c3d_highlight(before)
    else:
        a_lines = _c3d_highlight(_DEFAULT_BEFORE)

    if after_rows is not None:
        b_lines = after_rows
    elif after.strip():
        b_lines = _c3d_highlight(after)
    else:
        b_lines = _c3d_highlight(_DEFAULT_AFTER)

    if not a_lines and not b_lines:
        return Piece()

    raws_a = ["".join(text for text, _color in line) for line in a_lines]
    raws_b = ["".join(text for text, _color in line) for line in b_lines]
    all_raws = (raws_a + raws_b) or [""]
    node_id = ctx.target
    frame_w = int(params.get("frame_w") or _CS_FRAME_W)
    frame_h = int(params.get("frame_h") or _CS_FRAME_H)
    vis = max(len(a_lines), len(b_lines), 6)
    size, lh, editor_w, editor_h, surface_h = _cs_metrics(all_raws, frame_w, frame_h, vis)
    char_w = round(size * _C3D_MONO_EM, 3)

    t = _cm_times(ctx.duration)
    at = _enter_at(ctx)
    filename = str(params.get("filename") or "refactor.js")
    accent_title = f'<span class="cm-file">{_esc(filename)}</span> — Code Morph'

    # Extract tokens for State A
    tokens_a: list[dict[str, Any]] = []
    for r, line in enumerate(a_lines):
        col = 0
        for idx, (text, color) in enumerate(line):
            if not text:
                continue
            tokens_a.append({
                "id": f"a_{r}_{idx}",
                "text": text,
                "color": color,
                "line": r,
                "col": col,
                "len": len(text),
                "is_space": not text.strip(),
            })
            col += len(text)

    # Extract tokens for State B
    tokens_b: list[dict[str, Any]] = []
    for r, line in enumerate(b_lines):
        col = 0
        for idx, (text, color) in enumerate(line):
            if not text:
                continue
            tokens_b.append({
                "id": f"b_{r}_{idx}",
                "text": text,
                "color": color,
                "line": r,
                "col": col,
                "len": len(text),
                "is_space": not text.strip(),
            })
            col += len(text)

    # Token matching
    buckets_exact: dict[tuple[str, str], list[dict[str, Any]]] = {}
    buckets_text: dict[str, list[dict[str, Any]]] = {}
    for ta in tokens_a:
        if ta["is_space"]:
            continue
        key_exact = (ta["text"], ta["color"])
        buckets_exact.setdefault(key_exact, []).append(ta)
        buckets_text.setdefault(ta["text"], []).append(ta)

    matched_b: dict[str, dict[str, Any]] = {}
    matched_a_ids: set[str] = set()

    for tb in tokens_b:
        if tb["is_space"]:
            continue
        key_exact = (tb["text"], tb["color"])
        cand_list = [c for c in buckets_exact.get(key_exact, []) if c["id"] not in matched_a_ids]
        if not cand_list:
            cand_list = [c for c in buckets_text.get(tb["text"], []) if c["id"] not in matched_a_ids]
        if cand_list:
            cand_list.sort(key=lambda c: abs(c["line"] - tb["line"]) * 100 + abs(c["col"] - tb["col"]))
            chosen = cand_list[0]
            matched_b[tb["id"]] = chosen
            matched_a_ids.add(chosen["id"])

    tweens = [
        f'tl.fromTo("#{node_id}-editor",'
        f'{{opacity:0,scale:0.985}},'
        f'{{opacity:1,scale:1,duration:{_num(t["enter_dur"])},ease:"power2.out"}},{_num(at)});',
        f'tl.fromTo("#{node_id}-surface",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(t["fade_dur"])},ease:"power1.out"}},{_num(at + t["fade_at"])});',
        f'tl.fromTo("#{node_id}-scene-a",{{opacity:1}},'
        f'{{opacity:0,duration:{_num(t["fade_out_dur"])},ease:"power1.in"}},{_num(at + t["morph_at"])});',
        f'tl.fromTo("#{node_id}-gutter-a",{{opacity:1}},'
        f'{{opacity:0,duration:{_num(t["fade_out_dur"])},ease:"power1.in"}},{_num(at + t["morph_at"])});',
        f'tl.fromTo("#{node_id}-gutter-b",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(t["fade_in_dur"])},ease:"power1.out"}},{_num(at + t["morph_at"] + t["enter_delay"])});',
    ]

    for tb in tokens_b:
        tid = f"{node_id}-tok-{tb['id']}"
        if tb["id"] in matched_b:
            ta = matched_b[tb["id"]]
            dx = round((ta["col"] - tb["col"]) * char_w, 2)
            dy = round((ta["line"] - tb["line"]) * lh, 2)
            if dx != 0.0 or dy != 0.0:
                tweens.append(
                    f'tl.fromTo("#{tid}",'
                    f'{{x:{_num(dx)},y:{_num(dy)}}},'
                    f'{{x:0,y:0,duration:{_num(t["morph_dur"])},ease:"power2.inOut"}},'
                    f'{_num(at + t["morph_at"])});'
                )
        elif not tb["is_space"]:
            tweens.append(
                f'tl.fromTo("#{tid}",'
                f'{{opacity:0,scale:0.95}},'
                f'{{opacity:1,scale:1,duration:{_num(t["fade_in_dur"])},ease:"power1.out"}},'
                f'{_num(at + t["morph_at"] + t["enter_delay"])});'
            )

    gutter_a_html = "".join(
        f'<span class="cm-gn" style="height:{lh}px;line-height:{lh}px">{i}</span>'
        for i in range(1, len(a_lines) + 1)
    )
    gutter_b_html = "".join(
        f'<span class="cm-gn" style="height:{lh}px;line-height:{lh}px">{i}</span>'
        for i in range(1, len(b_lines) + 1)
    )

    lines_a_html: list[str] = []
    for r, line in enumerate(a_lines):
        line_spans: list[str] = []
        for idx, (text, color) in enumerate(line):
            tok_a_id = f"a_{r}_{idx}"
            if tok_a_id in matched_a_ids:
                line_spans.append(f'<span class="cm-tok" style="opacity:0">{_esc(text)}</span>')
            else:
                line_spans.append(f'<span class="cm-tok" style="color:{color}">{_esc(text)}</span>')
        lines_a_html.append(
            f'<div class="cm-line" style="height:{lh}px;line-height:{lh}px">{"".join(line_spans)}</div>'
        )

    lines_b_html: list[str] = []
    for r, line in enumerate(b_lines):
        line_spans: list[str] = []
        for idx, (text, color) in enumerate(line):
            tok_b_id = f"b_{r}_{idx}"
            if tok_b_id in matched_b:
                line_spans.append(
                    f'<span id="{node_id}-tok-{tok_b_id}" class="cm-tok" style="color:{color}">{_esc(text)}</span>'
                )
            elif not text.strip():
                line_spans.append(f'<span class="cm-tok">{_esc(text)}</span>')
            else:
                line_spans.append(
                    f'<span id="{node_id}-tok-{tok_b_id}" class="cm-tok cm-new" style="color:{color};opacity:0">{_esc(text)}</span>'
                )
        lines_b_html.append(
            f'<div class="cm-line" style="height:{lh}px;line-height:{lh}px">{"".join(line_spans)}</div>'
        )

    node = (
        f'<div id="{node_id}" class="clip fullscreen-text fs-code-morph" {_timing(ctx)}>'
        f'<div class="cm-stage">'
        f'<div class="cm-grid"></div>'
        f'<div class="cm-glow cm-glow-a"></div>'
        f'<div class="cm-glow cm-glow-b"></div>'
        f'<div id="{node_id}-editor" class="cm-editor" style="width:{editor_w}px;height:{editor_h}px">'
        f'<div class="cm-titlebar">'
        f'<div class="cm-dots">'
        f'<span class="cm-dot cm-dot-r"></span>'
        f'<span class="cm-dot cm-dot-y"></span>'
        f'<span class="cm-dot cm-dot-g"></span>'
        f'</div>'
        f'<span class="cm-filename">{accent_title}</span>'
        f'</div>'
        f'<div id="{node_id}-surface" class="cm-surface" style="width:{editor_w}px;height:{surface_h}px">'
        f'<div id="{node_id}-gutter-a" class="cm-gutter cm-gutter-a" style="width:{_CS_GUTTER}px;padding-top:{_CS_PAD_TOP}px;font-size:{size}px">{gutter_a_html}</div>'
        f'<div id="{node_id}-gutter-b" class="cm-gutter cm-gutter-b" style="width:{_CS_GUTTER}px;padding-top:{_CS_PAD_TOP}px;font-size:{size}px;opacity:0">{gutter_b_html}</div>'
        f'<div id="{node_id}-scene-a" class="cm-scene cm-scene-a">'
        f'<div class="cm-code" style="padding-left:{_CS_GUTTER + _CS_PAD_X}px;padding-top:{_CS_PAD_TOP}px;font-size:{size}px">{"".join(lines_a_html)}</div>'
        f'</div>'
        f'<div id="{node_id}-scene-b" class="cm-scene cm-scene-b">'
        f'<div class="cm-code" style="padding-left:{_CS_GUTTER + _CS_PAD_X}px;padding-top:{_CS_PAD_TOP}px;font-size:{size}px">{"".join(lines_b_html)}</div>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def cm_fullscreen_css() -> str:
    """CSS for Code Morph fullscreen text."""
    return (
        ".fullscreen-text.fs-code-morph{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;display:flex;"
        "align-items:center;justify-content:center;"
        "background:radial-gradient(120% 70% at 50% 18%,#0e1726 0%,#05070b 72%);"
        "font-family:'JetBrains Mono',var(--font-mono),monospace;font-weight:500;"
        "text-transform:none;letter-spacing:0;color:#e6edf3}"
        ".fullscreen-text.fs-code-morph .cm-stage{position:absolute;inset:0;"
        "display:flex;align-items:center;justify-content:center}"
        ".fullscreen-text.fs-code-morph .cm-grid{position:absolute;inset:0;z-index:0;"
        "pointer-events:none;background-image:linear-gradient("
        "rgba(88,166,255,0.05) 1px,transparent 1px),linear-gradient("
        "90deg,rgba(88,166,255,0.05) 1px,transparent 1px);background-size:48px 48px}"
        ".fullscreen-text.fs-code-morph .cm-glow{position:absolute;width:520px;height:520px;"
        "border-radius:50%;filter:blur(90px);opacity:0.5;pointer-events:none;z-index:0}"
        ".fullscreen-text.fs-code-morph .cm-glow-a{background:#1f6feb55;left:-80px;top:-120px}"
        ".fullscreen-text.fs-code-morph .cm-glow-b{background:#2ea04355;right:-100px;bottom:-160px}"
        ".fullscreen-text.fs-code-morph .cm-editor{position:relative;z-index:1;display:flex;"
        "flex-direction:column;box-sizing:border-box;background:#0b0f17;"
        "border:1px solid #1d2733;border-radius:16px;"
        "box-shadow:0 40px 120px rgba(0,0,0,0.6),0 2px 0 rgba(255,255,255,0.03) inset;"
        "overflow:hidden;will-change:transform,opacity}"
        ".fullscreen-text.fs-code-morph .cm-titlebar{display:flex;align-items:center;gap:14px;"
        "flex:0 0 48px;height:48px;padding:0 18px;"
        "background:linear-gradient(#11161f,#0c111a);border-bottom:1px solid #1b2430}"
        ".fullscreen-text.fs-code-morph .cm-dots{display:flex;gap:8px}"
        ".fullscreen-text.fs-code-morph .cm-dot{display:block;width:12px;height:12px;"
        "border-radius:50%}"
        ".fullscreen-text.fs-code-morph .cm-dot-r{background:#ff5f57}"
        ".fullscreen-text.fs-code-morph .cm-dot-y{background:#febc2e}"
        ".fullscreen-text.fs-code-morph .cm-dot-g{background:#28c840}"
        ".fullscreen-text.fs-code-morph .cm-filename{font-size:15px;color:#8b98a9;"
        "letter-spacing:0.2px;text-transform:none}"
        ".fullscreen-text.fs-code-morph .cm-file{color:#d6e2f0}"
        ".fullscreen-text.fs-code-morph .cm-surface{position:relative;flex:0 0 auto;"
        "overflow:hidden}"
        ".fullscreen-text.fs-code-morph .cm-scene{position:absolute;inset:0}"
        ".fullscreen-text.fs-code-morph .cm-gutter{position:absolute;left:0;z-index:1;"
        "text-align:right;color:#828c9b;user-select:none;font-variant-ligatures:none}"
        ".fullscreen-text.fs-code-morph .cm-gn{display:block}"
        ".fullscreen-text.fs-code-morph .cm-code{position:relative;display:block;width:100%;"
        "box-sizing:border-box;font-variant-ligatures:none;tab-size:2;"
        "text-align:left;text-transform:none}"
        ".fullscreen-text.fs-code-morph .cm-line{display:block;white-space:pre;position:relative;"
        "z-index:1;text-transform:none;font-weight:500}"
        ".fullscreen-text.fs-code-morph .cm-tok{display:inline-block;white-space:pre;"
        "font-weight:500;will-change:transform,opacity}"
    )
