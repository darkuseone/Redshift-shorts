"""North Korea locked-down: map zoom, scribble circle, LOCKED DOWN.

Catalog ``north-korea-locked-down`` is 1920×1080 / 7s. It tweens
``filter`` on the camera and ``strokeDashoffset`` on the scribble.
Here the camera is ``scale`` / ``x`` / ``y``; the circle is revealed
with an SVG-mask ``scaleX``; the label, wash and corners are
``opacity`` / ``scale``. Paper ``#eef3f4``, ink ``#151515``, scribble
``#e21d2f``, wash ``#ff3b30`` as in the catalog — editorial lock
gesture, not channel palette. Inter, not ``-apple-system``.
``world-map`` / ``us-map`` stay separate.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing
from .wmp_shapes import WMP_SHAPES

_NKL_CATALOG = 7.0
_NKL_CAM1 = 3.18
_NKL_CAM2_AT = 3.18
_NKL_CAM2 = 0.42
_NKL_CORNER_AT = 0.42
_NKL_CORNER_DUR = 0.28
_NKL_CORNER_STAGGER = 0.035
_NKL_CORNER2_AT = 1.2
_NKL_CORNER2_DUR = 0.18
_NKL_ANN_AT = 3.12
_NKL_ANN_DUR = 0.16
_NKL_CIRC_A_AT = 3.24
_NKL_CIRC_A_DUR = 0.62
_NKL_CIRC_B_AT = 3.46
_NKL_CIRC_B_DUR = 0.44
_NKL_LABEL_AT = 3.78
_NKL_LABEL_DUR = 0.28
_NKL_WASH_AT = 3.82
_NKL_WASH_DUR = 0.24
_NKL_SCAN_AT = 3.86
_NKL_SCAN_DUR = 0.18
_NKL_PULSE_AT = 4.1
_NKL_PULSE_DUR = 0.14
_NKL_CAM3_AT = 4.2
_NKL_CAM3 = 2.35
_NKL_CORNER3_AT = 5.82
_NKL_CORNER3_DUR = 0.72
_NKL_LABEL_Y_AT = 5.94
_NKL_LABEL_Y_DUR = 0.4

_NKL_PAPER = "#eef3f4"
_NKL_SEA = "#dfe6ea"
_NKL_LAND = "#f3f1ee"
_NKL_NK = "#efecea"
_NKL_STROKE = "#d7cfc8"
_NKL_INK = "#151515"
_NKL_SCRIBBLE = "#e21d2f"
_NKL_WASH = "#ff3b30"
_NKL_LABEL_BG = "#111111"

# Crop of Natural Earth around the peninsula (WMP viewBox units).
_NKL_VB = (1038.0, 36.0, 180.0, 280.0)
_NKL_LAND_CODES = ("156", "408", "410", "392", "496")
_NKL_CIRC_A = (
    "M 74 211 C 42 119 118 42 254 36 C 410 30 524 111 508 222 "
    "C 494 320 350 377 208 346 C 94 322 37 278 74 211"
)
_NKL_CIRC_B = (
    "M 92 231 C 33 150 105 55 243 44 C 408 31 529 126 501 244 "
    "C 480 334 335 370 197 342 C 83 319 47 269 92 231"
)
_NKL_LABELS = (
    ("NORTH KOREA", 1126.0, 172.0, 4.2),
    ("PYONGYANG", 1124.0, 178.5, 2.6),
    ("SEOUL", 1136.0, 194.0, 2.6),
    ("SOUTH KOREA", 1136.0, 201.0, 3.4),
    ("JAPAN", 1174.0, 188.0, 4.0),
    ("BEIJING", 1088.0, 168.0, 3.2),
)


def _nkl_play(dur: float) -> float:
    return dur if dur <= 0.001 else max(0.001, dur - 0.001)


def _nkl_at(catalog: float, duration: float) -> float:
    return catalog * (max(duration, 0.2) / _NKL_CATALOG)


def _nkl_dur(catalog: float, duration: float) -> float:
    return _nkl_play(_nkl_at(catalog, duration))


def _nkl_times(duration: float) -> dict[str, float]:
    return {
        "cam1": _nkl_dur(_NKL_CAM1, duration),
        "cam2_at": _nkl_at(_NKL_CAM2_AT, duration),
        "cam2": _nkl_dur(_NKL_CAM2, duration),
        "corner_at": _nkl_at(_NKL_CORNER_AT, duration),
        "corner_dur": _nkl_dur(_NKL_CORNER_DUR, duration),
        "corner_stagger": _nkl_at(_NKL_CORNER_STAGGER, duration),
        "corner2_at": _nkl_at(_NKL_CORNER2_AT, duration),
        "corner2_dur": _nkl_dur(_NKL_CORNER2_DUR, duration),
        "ann_at": _nkl_at(_NKL_ANN_AT, duration),
        "ann_dur": _nkl_dur(_NKL_ANN_DUR, duration),
        "circ_a_at": _nkl_at(_NKL_CIRC_A_AT, duration),
        "circ_a_dur": _nkl_dur(_NKL_CIRC_A_DUR, duration),
        "circ_b_at": _nkl_at(_NKL_CIRC_B_AT, duration),
        "circ_b_dur": _nkl_dur(_NKL_CIRC_B_DUR, duration),
        "label_at": _nkl_at(_NKL_LABEL_AT, duration),
        "label_dur": _nkl_dur(_NKL_LABEL_DUR, duration),
        "wash_at": _nkl_at(_NKL_WASH_AT, duration),
        "wash_dur": _nkl_dur(_NKL_WASH_DUR, duration),
        "scan_at": _nkl_at(_NKL_SCAN_AT, duration),
        "scan_dur": _nkl_dur(_NKL_SCAN_DUR, duration),
        "pulse_at": _nkl_at(_NKL_PULSE_AT, duration),
        "pulse_dur": _nkl_dur(_NKL_PULSE_DUR, duration),
        "cam3_at": _nkl_at(_NKL_CAM3_AT, duration),
        "cam3": _nkl_dur(_NKL_CAM3, duration),
        "corner3_at": _nkl_at(_NKL_CORNER3_AT, duration),
        "corner3_dur": _nkl_dur(_NKL_CORNER3_DUR, duration),
        "label_y_at": _nkl_at(_NKL_LABEL_Y_AT, duration),
        "label_y_dur": _nkl_dur(_NKL_LABEL_Y_DUR, duration),
    }


def _nkl_label_html(text: str) -> str:
    raw = str(text or "LOCKED DOWN").replace("<br/>", "\n").replace("<br>", "\n")
    parts = [p.strip() for p in raw.replace("/", " ").split() if p.strip()]
    if len(parts) >= 2:
        mid = max(1, len(parts) // 2)
        return f"{_esc(' '.join(parts[:mid]))}<br />{_esc(' '.join(parts[mid:]))}"
    return _esc(parts[0] if parts else "LOCKED DOWN")


def _nkl_spec(params: dict[str, Any]) -> str | None:
    raw = params.get("label", params.get("title", params.get("headline")))
    if raw in (None, ""):
        if not params:
            return None
        return "LOCKED DOWN"
    text = str(raw).strip()
    return text or "LOCKED DOWN"


def _nkl_lands() -> list[dict[str, Any]]:
    wanted = set(_NKL_LAND_CODES)
    return [item for item in WMP_SHAPES if str(item["code"]) in wanted]


def dv_north_korea_locked_down(ctx: "TemplateCtx") -> Piece:
    """Zoom into NK, scribble via SVG-mask, LOCKED DOWN. No filter/dash."""
    label = _nkl_spec(ctx.params)
    if label is None:
        return Piece()
    times = _nkl_times(ctx.duration)
    node_id = f"nkl-{ctx.index:02d}"
    start = ctx.start
    lands = _nkl_lands()
    vb = " ".join(_num(v) for v in _NKL_VB)

    paths: list[str] = []
    for item in lands:
        code = str(item["code"])
        klass = "nkl-nk" if code == "408" else "nkl-land"
        paths.append(
            f'<path class="{klass}" d="{_esc(item["d"])}"></path>'
        )
    labels: list[str] = []
    for name, x, y, size in _NKL_LABELS:
        labels.append(
            f'<text class="nkl-city" x="{_num(x)}" y="{_num(y)}" '
            f'font-size="{_num(size)}">{_esc(name)}</text>'
        )

    tweens: list[str] = [
        f'tl.fromTo("#{node_id}-cam",{{scale:0.92,x:0,y:36}},'
        f'{{scale:2.12,x:8,y:-28,duration:{_num(times["cam1"])},'
        f'ease:"expo.inOut"}},{_num(start)});',
        f'tl.to("#{node_id}-cam",{{scale:2.22,x:14,y:-40,'
        f'duration:{_num(times["cam2"])},ease:"back.out(1.5)",'
        f'immediateRender:false}},{_num(start + times["cam2_at"])});',
    ]
    for i in range(4):
        at = start + times["corner_at"] + i * times["corner_stagger"]
        tweens.append(
            f'tl.fromTo("#{node_id}-c{i}",{{opacity:0,scale:0.72}},'
            f'{{opacity:1,scale:1,duration:{_num(times["corner_dur"])},'
            f'ease:"power3.out"}},{_num(at)});')
    tweens.extend([
        f'tl.to("#{node_id}-c0",{{opacity:0.72,duration:{_num(times["corner2_dur"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["corner2_at"])});',
        f'tl.to("#{node_id}-c1",{{opacity:0.72,duration:{_num(times["corner2_dur"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["corner2_at"])});',
        f'tl.to("#{node_id}-c2",{{opacity:0.72,duration:{_num(times["corner2_dur"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["corner2_at"])});',
        f'tl.to("#{node_id}-c3",{{opacity:0.72,duration:{_num(times["corner2_dur"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["corner2_at"])});',
        f'tl.fromTo("#{node_id}-ann",{{opacity:0,scale:0.92,x:4,y:-4}},'
        f'{{opacity:1,scale:1,x:0,y:0,duration:{_num(times["ann_dur"])},'
        f'ease:"power2.out"}},{_num(start + times["ann_at"])});',
        f'tl.fromTo("#{node_id}-ra",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(times["circ_a_dur"])},ease:"power2.out"}},'
        f'{_num(start + times["circ_a_at"])});',
        f'tl.fromTo("#{node_id}-rb",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(times["circ_b_dur"])},ease:"power3.out"}},'
        f'{_num(start + times["circ_b_at"])});',
        f'tl.fromTo("#{node_id}-lab",{{opacity:0,scale:0.82}},'
        f'{{opacity:1,scale:1,duration:{_num(times["label_dur"])},'
        f'ease:"back.out(2.1)"}},{_num(start + times["label_at"])});',
        f'tl.fromTo("#{node_id}-wash",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(times["wash_dur"])},ease:"power2.out"}},'
        f'{_num(start + times["wash_at"])});',
        f'tl.fromTo("#{node_id}-scan",{{opacity:0}},'
        f'{{opacity:0.44,duration:{_num(times["scan_dur"])},ease:"none"}},'
        f'{_num(start + times["scan_at"])});',
        f'tl.to("#{node_id}-ann",{{scale:1.045,duration:{_num(times["pulse_dur"])},'
        f'yoyo:true,repeat:1,ease:"sine.inOut",immediateRender:false}},'
        f'{_num(start + times["pulse_at"])});',
        f'tl.to("#{node_id}-cam",{{scale:2.06,x:-10,y:-16,'
        f'duration:{_num(times["cam3"])},ease:"sine.inOut",'
        f'immediateRender:false}},{_num(start + times["cam3_at"])});',
        f'tl.to("#{node_id}-wash",{{opacity:0.82,duration:{_num(times["cam3"])},'
        f'ease:"sine.inOut",immediateRender:false}},'
        f'{_num(start + times["cam3_at"])});',
    ])
    for i in range(4):
        tweens.append(
            f'tl.to("#{node_id}-c{i}",{{opacity:0.38,'
            f'duration:{_num(times["corner3_dur"])},ease:"sine.inOut",'
            f'immediateRender:false}},{_num(start + times["corner3_at"])});')
    tweens.append(
        f'tl.to("#{node_id}-lab",{{y:-6,duration:{_num(times["label_y_dur"])},'
        f'yoyo:true,repeat:1,ease:"sine.inOut",immediateRender:false}},'
        f'{_num(start + times["label_y_at"])});')

    kill_at = start + max(ctx.duration - 0.001, 0.001)
    tweens.append(f'tl.set("#{node_id}-cam",{{opacity:1}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{node_id}-ann",{{opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{node_id}-wash",{{opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{node_id}-scan",{{opacity:0}},{_num(kill_at)});')
    for i in range(4):
        tweens.append(
            f'tl.set("#{node_id}-c{i}",{{opacity:0}},{_num(kill_at)});')

    corners = "".join(
        f'<div id="{node_id}-c{i}" class="nkl-corner {pos}"></div>'
        for i, pos in enumerate(("tl", "tr", "bl", "br"))
    )
    node = (
        f'<div id="{node_id}" class="clip overlay nkl-chart" {_timing(ctx)}>'
        f'<div id="{node_id}-cam" class="nkl-cam">'
        f'<svg class="nkl-svg" viewBox="{vb}" '
        f'preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
        f'<rect class="nkl-sea" x="{_num(_NKL_VB[0])}" y="{_num(_NKL_VB[1])}" '
        f'width="{_num(_NKL_VB[2])}" height="{_num(_NKL_VB[3])}"></rect>'
        f'{"".join(paths)}{"".join(labels)}</svg>'
        f'<div class="nkl-paper"></div></div>'
        f'<div id="{node_id}-ann" class="nkl-ann">'
        f'<div id="{node_id}-lab" class="nkl-lab">{_nkl_label_html(label)}</div>'
        f'<svg class="nkl-scribble" viewBox="0 0 560 392" aria-hidden="true">'
        f'<defs>'
        f'<mask id="{node_id}-ma">'
        f'<rect id="{node_id}-ra" class="nkl-wipe" x="0" y="0" width="560" '
        f'height="392" fill="#fff"></rect></mask>'
        f'<mask id="{node_id}-mb">'
        f'<rect id="{node_id}-rb" class="nkl-wipe" x="0" y="0" width="560" '
        f'height="392" fill="#fff"></rect></mask>'
        f'</defs>'
        f'<path class="nkl-circ nkl-circ-a" d="{_NKL_CIRC_A}" '
        f'mask="url(#{node_id}-ma)"></path>'
        f'<path class="nkl-circ nkl-circ-b" d="{_NKL_CIRC_B}" '
        f'mask="url(#{node_id}-mb)"></path>'
        f'</svg></div>'
        f'<div id="{node_id}-wash" class="nkl-wash"></div>'
        f'<div id="{node_id}-scan" class="nkl-scan"></div>'
        f'{corners}'
        f'<div class="nkl-attr">Natural Earth</div>'
        f'</div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def nkl_css() -> str:
    """Full-bleed editorial lock. Catalog paper/ink/scribble, Inter."""
    return (
        ".nkl-chart{left:0;top:0;width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden;font-family:Inter,var(--font-subtitle),sans-serif;"
        f"color:{_NKL_INK};background:{_NKL_PAPER}}}"
        ".nkl-cam{position:absolute;inset:0;z-index:0;"
        "transform-origin:50% 48%;will-change:transform}"
        ".nkl-svg{position:absolute;inset:0;width:100%;height:100%}"
        f".nkl-sea{{fill:{_NKL_SEA}}}"
        f".nkl-land{{fill:{_NKL_LAND};stroke:{_NKL_STROKE};stroke-width:0.35;"
        "vector-effect:non-scaling-stroke}"
        f".nkl-nk{{fill:{_NKL_NK};stroke:#c9bdb6;stroke-width:0.45;"
        "vector-effect:non-scaling-stroke}"
        ".nkl-city{fill:#6b7280;font-weight:650;font-family:Inter,sans-serif;"
        "letter-spacing:0.04em}"
        ".nkl-paper{position:absolute;inset:0;pointer-events:none;"
        "background:radial-gradient(circle at 52% 48%,rgba(255,255,255,0.1),"
        "transparent 30%),linear-gradient(180deg,rgba(255,255,255,0.1),"
        "rgba(10,20,24,0.08))}"
        ".nkl-ann{position:absolute;left:180px;top:700px;z-index:4;"
        "width:720px;height:504px;opacity:0;"
        "transform-origin:50% 50%;will-change:transform,opacity}"
        ".nkl-scribble{position:absolute;inset:0;width:720px;height:504px;"
        "overflow:visible}"
        ".nkl-circ{fill:none;stroke-linecap:round;stroke-linejoin:round}"
        f".nkl-circ-a{{stroke:{_NKL_SCRIBBLE};stroke-width:12}}"
        f".nkl-circ-b{{stroke:{_NKL_SCRIBBLE};stroke-width:6;opacity:0.82}}"
        ".nkl-wipe{transform-origin:0px 196px}"
        ".nkl-lab{position:absolute;left:0;right:0;top:-150px;"
        "margin:0 auto;width:max-content;transform-origin:50% 100%;"
        "min-width:420px;padding:20px 28px 22px;border-radius:18px;"
        f"color:#fff;background:{_NKL_LABEL_BG};"
        "box-shadow:0 22px 54px rgba(25,4,7,0.24),"
        "inset 0 0 0 1px rgba(255,255,255,0.12);"
        "font-size:64px;line-height:0.9;font-weight:900;letter-spacing:0;"
        "text-align:center;text-transform:uppercase;opacity:0}"
        ".nkl-lab::after{content:'';position:absolute;left:50%;bottom:-16px;"
        f"width:32px;height:32px;margin-left:-16px;background:{_NKL_LABEL_BG};"
        "rotate:45deg}"
        ".nkl-wash{position:absolute;inset:0;z-index:2;opacity:0;"
        "pointer-events:none;"
        f"background:radial-gradient(circle at 50% 48%,{_NKL_WASH}33,"
        f"{_NKL_WASH}0f 42%,rgba(79,0,8,0.22) 100%),"
        f"linear-gradient(90deg,rgba(99,0,12,0.12),{_NKL_WASH}33)}}"
        ".nkl-scan{position:absolute;inset:0;z-index:3;opacity:0;"
        "pointer-events:none;"
        "background:repeating-linear-gradient(0deg,rgba(65,0,0,0.12) 0,"
        "rgba(65,0,0,0.12) 1px,transparent 1px,transparent 7px)}"
        ".nkl-corner{position:absolute;z-index:6;width:72px;height:72px;"
        "border-color:rgba(17,17,17,0.62);opacity:0;"
        "transform-origin:50% 50%}"
        ".nkl-corner.tl{left:56px;top:120px;border-top:5px solid;"
        "border-left:5px solid}"
        ".nkl-corner.tr{right:56px;top:120px;border-top:5px solid;"
        "border-right:5px solid}"
        ".nkl-corner.bl{left:56px;bottom:80px;border-bottom:5px solid;"
        "border-left:5px solid}"
        ".nkl-corner.br{right:56px;bottom:80px;border-bottom:5px solid;"
        "border-right:5px solid}"
        ".nkl-attr{position:absolute;right:28px;bottom:28px;z-index:7;"
        "color:rgba(17,17,17,0.44);font-size:16px;font-weight:650}"
    )
