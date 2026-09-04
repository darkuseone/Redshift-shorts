"""Grid transitions — rippling mosaic tile displacement and reveal.

Catalog ``transitions-grid`` demonstrates grid dissolve and mosaic block
transitions between scenes using ordered tile cascades.
Rebuilt for 9:16 vertical placement without WebGL or canvas:
dual-layer crossfade with scale settle, 3x4 rippling grid cell cascade,
and soft blur wash.
Inter font, no forbidden GSAP properties.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _num, _timing, HOLD, Z_TRANSITION

_GRID_COLORS = (
    "#C8453D",
    "#E4726A",
    "#8E2F2A",
    "#111214",
    "#7A7D82",
    "#F7F5F3",
    "#C8453D",
    "#E4726A",
    "#8E2F2A",
    "#111214",
    "#7A7D82",
    "#FFFFFF",
)

_CELL_ORDER = sorted(
    range(12),
    key=lambda idx: (((idx % 3) - 1.0) ** 2 + ((idx // 3) - 1.5) ** 2) ** 0.5,
)


def _tg_times(duration: float) -> dict[str, float]:
    d = max(0.05, float(duration))
    mid = d * 0.48
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "swap_at": mid,
        "to_out_at": mid + 0.001,
        "to_out": max(0.001, d - mid - 0.002),
    }


def tr_transitions_grid(ctx: TemplateCtx) -> Piece:
    """Grid: rippling mosaic tile cascade and scene crossfade."""
    from_scale = float(ctx.params.get("from_scale", 1.10))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _tg_times(d)
    start = ctx.start

    stag = min(0.03, (d * 0.32) / 12)
    cell_in = min(0.18, d * 0.22)
    cell_out = min(0.18, d * 0.22)

    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut",{HOLD}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-a",{{scale:1,opacity:1}},'
        f'{{scale:1.05,opacity:0,duration:{_num(times["mid"] * 0.9)},'
        f'ease:"power2.in"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-b",{{scale:0.96,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["mid"] * 0.9)},'
        f'ease:"power2.out"}},{_num(start + times["swap_at"] * 0.5)});',
        f'tl.to("#{node_id}-b",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.7}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
    ]

    for rank, cell_idx in enumerate(_CELL_ORDER):
        t_in = start + rank * stag
        t_out = start + times["swap_at"] + rank * stag
        tweens.append(
            f'tl.fromTo("#{node_id}-c{cell_idx}",{{scale:0.8,opacity:0}},'
            f'{{scale:1,opacity:0.9,duration:{_num(cell_in)},ease:"power2.out"}},{_num(t_in)});'
        )
        tweens.append(
            f'tl.to("#{node_id}-c{cell_idx}",{{scale:0.85,opacity:0,duration:{_num(cell_out)},'
            f'ease:"power2.in",immediateRender:false}},{_num(t_out)});'
        )

    tweens.append(f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});')
    tweens.append(f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});')
    tweens.append(f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});')
    for cell_idx in range(12):
        tweens.append(f'tl.set("#{node_id}-c{cell_idx}",{{opacity:0}},{_num(start + d)});')

    cells_html = "".join(
        f'<span id="{node_id}-c{i}" class="tg-cell" style="background:{_GRID_COLORS[i]}"></span>'
        for i in range(12)
    )
    node = (
        f'<div id="{node_id}" class="clip tr-transitions-grid" {_timing(ctx)}>'
        f'<span class="tg-stage">'
        f'<span id="{node_id}-blur" class="tg-blur"></span>'
        f'<span id="{node_id}-a" class="tg-face tg-a">'
        f'<span class="tg-big">ONE</span>'
        f'<span class="tg-label">SCENE A</span>'
        f'</span>'
        f'<span id="{node_id}-b" class="tg-face tg-b">'
        f'<span class="tg-big">TWO</span>'
        f'<span class="tg-label">SCENE B</span>'
        f'</span>'
        f'<span class="tg-grid">{cells_html}</span>'
        f'</span>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def tg_transition_css() -> str:
    """CSS for Transitions Grid."""
    return (
        f".tr-transitions-grid{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-grid .tg-stage{display:block;width:100%;height:100%;position:relative}"
        ".tr-transitions-grid .tg-blur,.tr-transitions-grid .tg-face{"
        "position:absolute;inset:0;display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;transform-origin:50% 50%}"
        ".tr-transitions-grid .tg-blur{backdrop-filter:blur(14px);opacity:0}"
        ".tr-transitions-grid .tg-a{background:#111214;opacity:0}"
        ".tr-transitions-grid .tg-b{background:#C8453D;opacity:0}"
        ".tr-transitions-grid .tg-big{font-family:Inter,system-ui,sans-serif;font-size:220px;"
        "font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}"
        ".tr-transitions-grid .tg-a .tg-big{color:rgba(255,255,255,0.08)}"
        ".tr-transitions-grid .tg-b .tg-big{color:rgba(255,255,255,0.15)}"
        ".tr-transitions-grid .tg-label{font-family:Inter,system-ui,sans-serif;font-size:36px;"
        "font-weight:700;letter-spacing:6px;margin-top:10px}"
        ".tr-transitions-grid .tg-a .tg-label{color:#7A7D82}"
        ".tr-transitions-grid .tg-b .tg-label{color:#ffffff}"
        ".tr-transitions-grid .tg-grid{position:absolute;inset:0;display:grid;"
        "grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(4,1fr);gap:4px;padding:4px}"
        ".tr-transitions-grid .tg-cell{display:block;width:100%;height:100%;"
        "border-radius:6px;opacity:0;transform-origin:50% 50%}"
    )
