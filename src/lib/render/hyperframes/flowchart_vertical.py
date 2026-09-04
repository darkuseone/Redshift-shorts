"""Flowchart vertical: branching decision tree, connector lines, cursor typing fix.

Catalog ``flowchart-vertical`` is 1440×2560 / 12s. Translated to 1080×1920 9:16 portrait.
Connectors use SVG-mask scaleY (no strokeDashoffset); typo correction uses pre-baked
spans and opacity (no innerHTML/textContent modification); cursor and emoji use x/y/scale.
Inter, not ``-apple-system``. Colors match HyperFrames catalog: #ffffff canvas,
nodes #e8d44d / #c2e8a0 / #f5c5a3 / #d4c5f9 / #a8d8f0 / #f8b4c8, ink #111214.
``flowchart`` stays separate.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing

_FCV_CATALOG = 12.0

# Catalog colors
_FCV_CANVAS = "#ffffff"
_FCV_INK = "#111214"
_FCV_YELLOW = "#e8d44d"
_FCV_GREEN = "#c2e8a0"
_FCV_PEACH = "#f5c5a3"
_FCV_LAVENDER = "#d4c5f9"
_FCV_BLUE = "#a8d8f0"
_FCV_PINK = "#f8b4c8"
_FCV_TAG_PURPLE = "#9747ff"
_FCV_BORDER_BLUE = "#0b84f3"
_FCV_SQUIGGLE_RED = "#e53935"
_FCV_HIGHLIGHT = "#d0e4ff"


def _fcv_play(dur: float) -> float:
    return dur if dur <= 0.001 else max(0.001, dur - 0.001)


def _fcv_at(catalog: float, duration: float) -> float:
    return catalog * (max(duration, 0.4) / _FCV_CATALOG)


def _fcv_dur(catalog: float, duration: float) -> float:
    return _fcv_play(_fcv_at(catalog, duration))


def _fcv_times(duration: float) -> dict[str, float]:
    d = max(duration, 0.4)
    out_at = max(d - _fcv_at(0.6, d), 0.5)
    return {
        "root_at": _fcv_at(0.2, d),
        "root_dur": _fcv_dur(0.4, d),
        "c1_at": _fcv_at(0.8, d),
        "c1_dur": _fcv_dur(0.5, d),
        "lbl_at": _fcv_at(1.05, d),
        "lbl_dur": _fcv_dur(0.2, d),
        "l2_at": _fcv_at(1.4, d),
        "l2_dur": _fcv_dur(0.4, d),
        "c2_at": _fcv_at(2.4, d),
        "c2_dur": _fcv_dur(0.5, d),
        "l3_at": _fcv_at(2.8, d),
        "l3_dur": _fcv_dur(0.4, d),
        "sq_at": _fcv_at(3.0, d),
        "cur_at": _fcv_at(4.2, d),
        "cur_dur": _fcv_dur(1.0, d),
        "clk1_at": _fcv_at(5.3, d),
        "clk2_at": _fcv_at(5.8, d),
        "fix_at": _fcv_at(6.4, d),
        "fix_dur": _fcv_dur(0.25, d),
        "desel_at": _fcv_at(7.2, d),
        "emoji_at": _fcv_at(7.7, d),
        "emoji_dur": _fcv_dur(0.3, d),
        "out_at": out_at,
        "out_dur": _fcv_dur(0.5, d),
    }


def _fcv_spec(params: dict[str, Any]) -> dict[str, Any] | None:
    if not params or not any(k in params for k in ("root", "nodes", "branches", "leaves", "title", "label")):
        return None
    root = str(params.get("root") or params.get("title") or "Should I learn to code?").strip()
    branches = list(params.get("branches") or ["Yes", "Not sure"])[:2]
    if len(branches) < 2:
        branches = ["Yes", "Not sure"]
    leaves = list(params.get("leaves") or [
        "Start with Python", "Try no-code first",
        "Build a personal website", "Take a free intro course",
    ])[:4]
    while len(leaves) < 4:
        leaves.append("Option")
    return {"root": root, "branches": branches, "leaves": leaves}


def dv_flowchart_vertical(ctx: "TemplateCtx") -> Piece:
    """Vertical flowchart: question root, 2 branches, 4 leaves, cursor typo fix."""
    spec = _fcv_spec(ctx.params)
    if spec is None:
        return Piece()

    node_id = f"fcv-{ctx.index:02d}"
    start = ctx.start
    duration = max(float(ctx.duration), 0.4)
    times = _fcv_times(duration)

    root_text = spec["root"]
    branch_l, branch_r = spec["branches"][0], spec["branches"][1]
    leaf_py, leaf_nocode, leaf_web, leaf_course = spec["leaves"]

    tweens: list[str] = [
        # Level 1 root appears
        f'tl.fromTo("#{node_id}-root",{{scale:0,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["root_dur"])},ease:"power2.out"}},'
        f'{_num(start + times["root_at"])});',

        # Connectors Level 1 draw via mask scaleY
        f'tl.fromTo("#{node_id}-m1-rect",{{scaleY:0}},'
        f'{{scaleY:1,duration:{_num(times["c1_dur"])},ease:"power2.inOut"}},'
        f'{_num(start + times["c1_at"])});',

        # Branch labels fade in
        f'tl.fromTo("#{node_id}-lbl-l",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(times["lbl_dur"])},ease:"power1.out"}},'
        f'{_num(start + times["lbl_at"])});',
        f'tl.fromTo("#{node_id}-lbl-r",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(times["lbl_dur"])},ease:"power1.out"}},'
        f'{_num(start + times["lbl_at"] + _fcv_dur(0.08, duration))});',

        # Level 2 nodes appear
        f'tl.fromTo("#{node_id}-n-yes",{{scale:0,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["l2_dur"])},ease:"back.out(1.7)"}},'
        f'{_num(start + times["l2_at"])});',
        f'tl.fromTo("#{node_id}-n-not-sure",{{scale:0,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["l2_dur"])},ease:"back.out(1.7)"}},'
        f'{_num(start + times["l2_at"] + _fcv_dur(0.15, duration))});',

        # Connectors Level 2 draw via mask scaleY
        f'tl.fromTo("#{node_id}-m2-rect",{{scaleY:0}},'
        f'{{scaleY:1,duration:{_num(times["c2_dur"])},ease:"power2.inOut"}},'
        f'{_num(start + times["c2_at"])});',

        # Level 3 leaf nodes appear
        f'tl.fromTo("#{node_id}-n-py",{{scale:0,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["l3_dur"])},ease:"back.out(1.7)"}},'
        f'{_num(start + times["l3_at"])});',
        f'tl.fromTo("#{node_id}-n-nocode",{{scale:0,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["l3_dur"])},ease:"back.out(1.7)"}},'
        f'{_num(start + times["l3_at"] + _fcv_dur(0.12, duration))});',
        f'tl.fromTo("#{node_id}-n-web",{{scale:0,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["l3_dur"])},ease:"back.out(1.7)"}},'
        f'{_num(start + times["l3_at"] + _fcv_dur(0.24, duration))});',
        f'tl.fromTo("#{node_id}-n-course",{{scale:0,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["l3_dur"])},ease:"back.out(1.7)"}},'
        f'{_num(start + times["l3_at"] + _fcv_dur(0.36, duration))});',

        # Red squiggle under typo
        f'tl.fromTo("#{node_id}-squiggle",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_fcv_dur(0.15, duration))},ease:"power1.out"}},'
        f'{_num(start + times["sq_at"])});',

        # Cursor drifts in
        f'tl.fromTo("#{node_id}-cur",{{x:200,y:350,opacity:0}},'
        f'{{x:0,y:0,opacity:1,duration:{_num(times["cur_dur"])},ease:"power1.inOut"}},'
        f'{_num(start + times["cur_at"])});',

        # Single click: selection border pops
        f'tl.to("#{node_id}-border",{{opacity:1,duration:{_num(_fcv_dur(0.08, duration))},ease:"power1.out",immediateRender:false}},'
        f'{_num(start + times["clk1_at"])});',
        f'tl.to("#{node_id}-cur",{{scale:0.85,duration:{_num(_fcv_dur(0.06, duration))},yoyo:true,repeat:1,ease:"power1.inOut",immediateRender:false}},'
        f'{_num(start + times["clk1_at"])});',

        # Double click: highlight appears
        f'tl.to("#{node_id}-cur",{{scale:0.85,duration:{_num(_fcv_dur(0.06, duration))},yoyo:true,repeat:3,ease:"power1.inOut",immediateRender:false}},'
        f'{_num(start + times["clk2_at"])});',
        f'tl.to("#{node_id}-py-hl",{{opacity:1,duration:{_num(_fcv_dur(0.08, duration))},ease:"power1.out",immediateRender:false}},'
        f'{_num(start + times["clk2_at"] + _fcv_dur(0.1, duration))});',

        # Fix typo: fade typo layer to 0, fade fix layer to 1, squiggle fades out
        f'tl.to("#{node_id}-py-typo",{{opacity:0,duration:{_num(times["fix_dur"])},ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["fix_at"])});',
        f'tl.to("#{node_id}-py-fix",{{opacity:1,duration:{_num(times["fix_dur"])},ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["fix_at"])});',
        f'tl.to("#{node_id}-squiggle",{{opacity:0,duration:{_num(_fcv_dur(0.12, duration))},ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["fix_at"])});',
        f'tl.set("#{node_id}-squiggle",{{opacity:0}},{_num(start + times["fix_at"] + _fcv_dur(0.12, duration))});',

        # Deselect: cursor moves away, border fades out
        f'tl.to("#{node_id}-cur",{{x:60,y:40,duration:{_num(_fcv_dur(0.3, duration))},ease:"power1.out",immediateRender:false}},'
        f'{_num(start + times["desel_at"])});',
        f'tl.to("#{node_id}-border",{{opacity:0,duration:{_num(_fcv_dur(0.12, duration))},ease:"power1.out",immediateRender:false}},'
        f'{_num(start + times["desel_at"])});',

        # Thumbs up emoji pops
        f'tl.fromTo("#{node_id}-thumb",{{scale:0}},'
        f'{{scale:1,duration:{_num(times["emoji_dur"])},ease:"back.out(2)"}},'
        f'{_num(start + times["emoji_at"])});',

        # Fade out
        f'tl.to("#{node_id}-stage",{{opacity:0,duration:{_num(times["out_dur"])},ease:"power2.inOut",immediateRender:false}},'
        f'{_num(start + times["out_at"])});',
    ]

    # SVG Connectors layout (9:16 portrait coordinates)
    # Level 1 lines: from (540, 545) down to (330, 765) and (750, 765)
    # Level 2 lines: from (330, 835) to (210, 1060) & (450, 1060); from (750, 835) to (630, 1060) & (870, 1060)
    svg_connectors = (
        f'<svg class="fcv-connectors" viewBox="0 0 1080 1920" aria-hidden="true">'
        f'<defs>'
        f'<mask id="{node_id}-m1">'
        f'<rect id="{node_id}-m1-rect" x="0" y="530" width="1080" height="260" fill="#fff" '
        f'style="transform-origin:540px 535px;"></rect>'
        f'</mask>'
        f'<mask id="{node_id}-m2">'
        f'<rect id="{node_id}-m2-rect" x="0" y="820" width="1080" height="260" fill="#fff" '
        f'style="transform-origin:540px 825px;"></rect>'
        f'</mask>'
        f'</defs>'
        f'<g mask="url(#{node_id}-m1)">'
        f'<path class="fcv-conn-line" d="M 540 545 L 540 650 L 330 650 L 330 765"></path>'
        f'<path class="fcv-conn-line" d="M 540 545 L 540 650 L 750 650 L 750 765"></path>'
        f'</g>'
        f'<g mask="url(#{node_id}-m2)">'
        f'<path class="fcv-conn-line" d="M 330 835 L 330 950 L 210 950 L 210 1060"></path>'
        f'<path class="fcv-conn-line" d="M 330 835 L 330 950 L 450 950 L 450 1060"></path>'
        f'<path class="fcv-conn-line" d="M 750 835 L 750 950 L 630 950 L 630 1060"></path>'
        f'<path class="fcv-conn-line" d="M 750 835 L 750 950 L 870 950 L 870 1060"></path>'
        f'</g>'
        f'</svg>'
    )

    node = (
        f'<div id="{node_id}" class="clip overlay fcv-chart" {_timing(ctx)}>'
        f'<div id="{node_id}-stage" class="fcv-stage">'
        f'{svg_connectors}'
        f'<div id="{node_id}-lbl-l" class="fcv-label" style="left:435px;top:695px;">{_esc(branch_l)}</div>'
        f'<div id="{node_id}-lbl-r" class="fcv-label" style="left:645px;top:695px;">{_esc(branch_r)}</div>'
        f'<div id="{node_id}-root" class="fcv-node fcv-yellow" style="left:540px;top:515px;width:380px;">'
        f'{_esc(root_text)}</div>'
        f'<div id="{node_id}-n-yes" class="fcv-node fcv-green" style="left:330px;top:800px;width:130px;">'
        f'{_esc(branch_l)}</div>'
        f'<div id="{node_id}-n-not-sure" class="fcv-node fcv-peach" style="left:750px;top:800px;width:170px;">'
        f'{_esc(branch_r)}</div>'
        f'<div id="{node_id}-n-py" class="fcv-node fcv-lavender" style="left:210px;top:1100px;width:180px;">'
        f'<div class="fcv-py-box">'
        f'<span id="{node_id}-py-typo" class="fcv-py-text">Start with '
        f'<span id="{node_id}-py-wrong" class="fcv-typo">Pythom'
        f'<span id="{node_id}-py-hl" class="fcv-hl"></span></span></span>'
        f'<span id="{node_id}-py-fix" class="fcv-py-text fcv-fix">{_esc(leaf_py)}</span>'
        f'<svg id="{node_id}-squiggle" class="fcv-squiggle" width="48" height="6" viewBox="0 0 64 6">'
        f'<path d="M 0 3 Q 2 0 4 3 T 8 3 T 12 3 T 16 3 T 20 3 T 24 3 T 28 3 T 32 3 T 36 3 T 40 3 T 44 3 T 48 3 T 52 3 T 56 3 T 60 3 T 64 3" '
        f'fill="none" stroke="{_FCV_SQUIGGLE_RED}" stroke-width="2.5"></path>'
        f'</svg>'
        f'</div>'
        f'<div id="{node_id}-border" class="fcv-selection-border"></div>'
        f'</div>'
        f'<div id="{node_id}-n-nocode" class="fcv-node fcv-blue" style="left:450px;top:1100px;width:180px;">'
        f'{_esc(leaf_nocode)}</div>'
        f'<div id="{node_id}-n-web" class="fcv-node fcv-pink" style="left:630px;top:1100px;width:180px;">'
        f'{_esc(leaf_web)}</div>'
        f'<div id="{node_id}-n-course" class="fcv-node fcv-yellow" style="left:870px;top:1100px;width:180px;">'
        f'{_esc(leaf_course)}</div>'
        f'<div id="{node_id}-cur" class="fcv-cursor" style="left:210px;top:1100px;">'
        f'<svg width="24" height="24" viewBox="0 0 24 24" fill="none">'
        f'<path d="M5.65376 12.3673H5.46026L5.31717 12.4976L0.500002 16.8829L0.500002 1.19841L11.7841 12.3673H5.65376Z" '
        f'fill="#ffffff" stroke="{_FCV_INK}" stroke-width="1.5"></path>'
        f'</svg>'
        f'<div class="fcv-tag">You</div>'
        f'</div>'
        f'<div id="{node_id}-thumb" class="fcv-emoji" style="left:290px;top:1030px;">👍</div>'
        f'</div></div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def fcv_css() -> str:
    """Full-bleed vertical flowchart. Catalog colors, Inter."""
    return (
        ".fcv-chart{position:absolute;left:0;top:0;width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden;font-family:Inter,var(--font-subtitle),sans-serif;"
        f"color:{_FCV_INK};background-color:{_FCV_CANVAS};"
        "background-image:radial-gradient(#e5e5e5 1.5px, transparent 1.5px);"
        "background-size:24px 24px}"
        ".fcv-stage{position:absolute;inset:0;transform-origin:50% 50%;will-change:transform,opacity}"
        ".fcv-connectors{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:5}"
        f".fcv-conn-line{{fill:none;stroke:{_FCV_INK};stroke-width:4;stroke-linecap:round;stroke-linejoin:round}}"
        f".fcv-label{{position:absolute;font-size:18px;font-weight:600;color:{_FCV_INK};background:{_FCV_CANVAS};"
        "padding:4px 10px;border-radius:6px;border:1px solid #e5e7eb;opacity:0;z-index:8;"
        "transform:translate(-50%, -50%)}"
        f".fcv-node{{position:absolute;transform:translate(-50%, -50%) scale(0);padding:16px 18px;"
        f"border-radius:14px;font-size:18px;font-weight:600;line-height:1.25;color:{_FCV_INK};box-shadow:0 6px 16px rgba(0,0,0,0.08);"
        "display:flex;align-items:center;justify-content:center;text-align:center;z-index:10;box-sizing:border-box}"
        f".fcv-yellow{{background-color:{_FCV_YELLOW}}}"
        f".fcv-green{{background-color:{_FCV_GREEN}}}"
        f".fcv-peach{{background-color:{_FCV_PEACH}}}"
        f".fcv-lavender{{background-color:{_FCV_LAVENDER}}}"
        f".fcv-blue{{background-color:{_FCV_BLUE}}}"
        f".fcv-pink{{background-color:{_FCV_PINK}}}"
        ".fcv-py-box{position:relative;display:inline-block}"
        ".fcv-py-text{display:inline-block;white-space:normal}"
        ".fcv-py-text.fcv-fix{position:absolute;left:0;top:0;opacity:0;width:100%}"
        ".fcv-typo{position:relative;display:inline-block;padding:0 2px}"
        f".fcv-hl{{position:absolute;inset:0;background-color:{_FCV_HIGHLIGHT};border-radius:3px;opacity:0;z-index:-1}}"
        ".fcv-squiggle{position:absolute;right:0;bottom:-4px;opacity:0}"
        f".fcv-selection-border{{position:absolute;top:-4px;left:-4px;right:-4px;bottom:-4px;"
        f"border:2.5px solid {_FCV_BORDER_BLUE};border-radius:16px;pointer-events:none;opacity:0}}"
        ".fcv-cursor{position:absolute;z-index:100;pointer-events:none;display:flex;align-items:flex-start;opacity:0}"
        f".fcv-tag{{background-color:{_FCV_TAG_PURPLE};color:#ffffff;padding:2px 8px;border-radius:4px;"
        "font-size:14px;font-weight:600;margin-left:4px;margin-top:10px}"
        ".fcv-emoji{position:absolute;font-size:36px;transform:translate(-50%, -50%) scale(0);z-index:30}"
    )
