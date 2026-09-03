"""MK progress stat: count-up numeral, label, thin track filling to value/max.

Catalog ``mk-progress-stat`` is 1920×1080 / 7s. It writes ``textContent``
from ``onUpdate`` and hides the root with ``visibility``. Here the count
is pre-baked spans and ``opacity``; the track is ``scaleX`` (already how
the catalog grows the fill); exit is ``opacity`` / ``y``. Inter, not
``-apple-system``. Ink ``#1d1d1f``, dim ``#6e6e73``, accent ``#0071e3``,
paper ``#f5f5f7`` as in the catalog — MK gesture, not channel palette.
``stat-countup-card`` / ``apple-money-count`` stay separate.
"""

from __future__ import annotations

from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing, fit_size

_MPS_CATALOG = 7.0
_MPS_IN_AT = 0.3
_MPS_IN_DUR = 0.7
_MPS_COUNT_AT = 0.5
_MPS_COUNT_DUR = 1.6
_MPS_OUT_DUR = 0.4
_MPS_FPS = 30

_MPS_INK = "#1d1d1f"
_MPS_DIM = "#6e6e73"
_MPS_ACCENT = "#0071e3"
_MPS_PAPER = "#f5f5f7"
_MPS_TRACK = "rgba(29,29,31,0.1)"


def _mps_play(dur: float) -> float:
    return dur if dur <= 0.001 else max(0.001, dur - 0.001)


def _mps_at(catalog: float, duration: float) -> float:
    return catalog * (max(duration, 0.2) / _MPS_CATALOG)


def _mps_dur(catalog: float, duration: float) -> float:
    return _mps_play(_mps_at(catalog, duration))


def _mps_times(duration: float) -> dict[str, float]:
    out_at = max(duration - _mps_at(_MPS_OUT_DUR + 0.1, duration), 0.2)
    return {
        "in_at": _mps_at(_MPS_IN_AT, duration),
        "in_dur": _mps_dur(_MPS_IN_DUR, duration),
        "count_at": _mps_at(_MPS_COUNT_AT, duration),
        "count_dur": _mps_dur(_MPS_COUNT_DUR, duration),
        "out_at": out_at,
        "out_dur": _mps_dur(_MPS_OUT_DUR, duration),
    }


def _mps_spec(params: dict[str, Any]) -> tuple[int, int, str, str, str] | None:
    if not any(k in params and params[k] not in (None, "")
               for k in ("value", "label", "caption", "max", "suffix")):
        return None
    try:
        value = int(round(float(params.get("value", 22))))
    except (TypeError, ValueError):
        value = 22
    try:
        maximum = int(round(float(params.get("max", 30))))
    except (TypeError, ValueError):
        maximum = 30
    if maximum <= 0:
        maximum = max(value, 1)
    value = max(0, value)
    suffix = str(params.get("suffix") or "")
    label = str(params.get("label") or "Goals reached")
    caption = str(params.get("caption") or "Great job, we are getting closer!")
    return value, maximum, suffix, label, caption


def _mps_frames(value: int, suffix: str, count_sec: float) -> list[str]:
    frames = max(2, int(round(count_sec * _MPS_FPS / 2)))
    labels: list[str] = []
    prev = None
    for i in range(frames + 1):
        t = i / frames
        # Catalog eases the dummy object with power2.out; sample that curve.
        eased = 1 - (1 - t) * (1 - t)
        text = f"{int(round(value * eased))}{suffix}"
        if text != prev:
            labels.append(text)
            prev = text
    final = f"{value}{suffix}"
    if labels[-1] != final:
        labels.append(final)
    return labels


def dv_mk_progress_stat(ctx: "TemplateCtx") -> Piece:
    """Count-up + scaleX track. No textContent, no visibility tween."""
    spec = _mps_spec(ctx.params)
    if spec is None:
        return Piece()
    value, maximum, suffix, label, caption = spec
    times = _mps_times(ctx.duration)
    node_id = f"mps-{ctx.index:02d}"
    start = ctx.start
    labels = _mps_frames(value, suffix, times["count_dur"])
    longest = max(labels, key=len)
    size = fit_size(longest, 900, 220)
    fill = min(1.0, value / float(maximum))
    spans = [
        f'<span id="{node_id}-v{i}" class="mps-val">{_esc(text)}</span>'
        for i, text in enumerate(labels)
    ]
    tweens = [
        f'tl.fromTo("#{node_id}-card",{{y:28,opacity:0}},'
        f'{{y:0,opacity:1,duration:{_num(times["in_dur"])},'
        f'ease:"power3.out"}},{_num(start + times["in_at"])});',
        f'tl.set("#{node_id}-v0",{{opacity:1}},'
        f'{_num(start + times["in_at"])});',
    ]
    nlab = max(1, len(labels) - 1)
    prev = 0
    for i in range(1, len(labels)):
        at = start + times["count_at"] + times["count_dur"] * (i / nlab)
        tweens.append(
            f'tl.set("#{node_id}-v{prev}",{{opacity:0}},{_num(at)});')
        tweens.append(
            f'tl.set("#{node_id}-v{i}",{{opacity:1}},{_num(at)});')
        prev = i
    tweens.append(
        f'tl.fromTo("#{node_id}-fill",{{scaleX:0}},'
        f'{{scaleX:{_num(fill)},duration:{_num(times["count_dur"])},'
        f'ease:"power2.out"}},{_num(start + times["count_at"])});')
    tweens.extend([
        f'tl.to("#{node_id}-card",{{y:-20,opacity:0,'
        f'duration:{_num(times["out_dur"])},ease:"power2.in",'
        f'immediateRender:false}},{_num(start + times["out_at"])});',
        f'tl.set("#{node_id}-card",{{opacity:0}},'
        f'{_num(start + times["out_at"] + times["out_dur"])});',
    ])
    node = (
        f'<div id="{node_id}" class="clip overlay mps-chart" {_timing(ctx)}>'
        f'<div id="{node_id}-card" class="mps-card">'
        f'<div class="mps-num" style="font-size:{size}px">{"".join(spans)}</div>'
        f'<div class="mps-label">{_esc(label)}</div>'
        f'<div class="mps-track"><div id="{node_id}-fill" class="mps-fill">'
        f'</div></div>'
        f'<div class="mps-cap">{_esc(caption)}</div>'
        f'</div></div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def mps_css() -> str:
    """Centered MK progress card. Catalog ink/accent, Inter."""
    return (
        ".mps-chart{left:0;top:0;width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden;font-family:Inter,var(--font-subtitle),sans-serif;"
        f"color:{_MPS_INK};background:{_MPS_PAPER}}}"
        ".mps-card{position:absolute;left:80px;right:80px;top:520px;"
        "display:flex;flex-direction:column;align-items:flex-start;"
        "opacity:0;will-change:transform,opacity}"
        ".mps-num{position:relative;height:240px;width:100%;"
        "font-weight:600;line-height:1;letter-spacing:-0.03em;"
        "font-variant-numeric:tabular-nums}"
        ".mps-num .mps-val{position:absolute;left:0;top:0;opacity:0}"
        ".mps-label{margin-top:12px;font-weight:500;font-size:42px;"
        "letter-spacing:-0.01em}"
        ".mps-track{position:relative;margin-top:28px;width:720px;height:6px;"
        f"border-radius:3px;background:{_MPS_TRACK};overflow:hidden}}"
        ".mps-fill{position:absolute;inset:0;border-radius:3px;"
        f"background:{_MPS_ACCENT};transform-origin:0% 50%;transform:scaleX(0)}}"
        f".mps-cap{{margin-top:22px;font-weight:400;font-size:30px;"
        f"color:{_MPS_DIM}}}"
    )
