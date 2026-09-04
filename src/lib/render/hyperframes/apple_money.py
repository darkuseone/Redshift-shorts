"""Apple money count: $0 → $10,000, then bills and coins burst.

Catalog ``apple-money-count`` is 1920×1080 / 5s. It writes ``textContent``
from ``onUpdate``, tweens ``textShadow`` / ``filter`` / ``color``. Here the
count is pre-baked spans and ``opacity``; the hit is a second green layer
(``opacity`` / ``scale``); the burst is ``x`` / ``y`` / ``rotation`` /
``scale`` / ``opacity``. Paper ``#fdfefe``, ink ``#111315``, green
``#30d158``, coin gold ``#ffd54f`` / ``#d9a514`` as in the catalog — Apple
money gesture, not channel palette. Inter, not ``-apple-system``.
``stat-countup-card`` / ``counter-roll`` / ``number-slam-card`` stay separate.
"""

from __future__ import annotations

import math
from typing import Any

from .templates import Piece, TemplateCtx, _esc, _num, _timing, fit_size

_AMC_CATALOG = 5.0
_AMC_COUNT = 3.16
_AMC_ENTER = 0.45
_AMC_HIT = 3.16
_AMC_POP = 0.16
_AMC_SETTLE = 0.23
_AMC_FLASH_IN = 0.08
_AMC_FLASH_HOLD = 0.76
_AMC_FLASH_OUT = 0.16
_AMC_BURST_AT = 3.28
_AMC_FADE_AT = 4.18
_AMC_FADE_DUR = 0.38
_AMC_OUT_AT = 4.36
_AMC_OUT_DUR = 0.28
_AMC_ICONS = 62
_AMC_FPS = 30
_AMC_DEFAULT_END = 10000.0

_AMC_PAPER = "#fdfefe"
_AMC_INK = "#111315"
_AMC_GREEN = "#30d158"
_AMC_BRAND = "#07541f"
_AMC_COIN_HI = "#fff7a6"
_AMC_COIN = "#ffd54f"
_AMC_COIN_LO = "#d9a514"
_AMC_COIN_INK = "#6f4c00"


def _amc_play(dur: float) -> float:
    return dur if dur <= 0.001 else max(0.001, dur - 0.001)


def _amc_at(catalog: float, duration: float) -> float:
    return catalog * (max(duration, 0.2) / _AMC_CATALOG)


def _amc_dur(catalog: float, duration: float) -> float:
    return _amc_play(_amc_at(catalog, duration))


def _amc_times(duration: float) -> dict[str, float]:
    return {
        "enter": _amc_dur(_AMC_ENTER, duration),
        "count": _amc_dur(_AMC_COUNT, duration),
        "hit": _amc_at(_AMC_HIT, duration),
        "pop": _amc_dur(_AMC_POP, duration),
        "settle": _amc_dur(_AMC_SETTLE, duration),
        "flash_in": _amc_dur(_AMC_FLASH_IN, duration),
        "flash_hold": _amc_dur(_AMC_FLASH_HOLD, duration),
        "flash_out": _amc_dur(_AMC_FLASH_OUT, duration),
        "burst_at": _amc_at(_AMC_BURST_AT, duration),
        "fade_at": _amc_at(_AMC_FADE_AT, duration),
        "fade_dur": _amc_dur(_AMC_FADE_DUR, duration),
        "out_at": _amc_at(_AMC_OUT_AT, duration),
        "out_dur": _amc_dur(_AMC_OUT_DUR, duration),
    }


def _amc_money(value: float, prefix: str) -> str:
    bounded = max(0, min(10_000_000, int(round(value))))
    body = f"{bounded:,}"
    return f"{prefix}{body}" if prefix else body


def _amc_spec(params: dict[str, Any]) -> tuple[float, float, str] | None:
    raw = params.get("end_value", params.get("value", params.get("end")))
    if raw in (None, ""):
        end = _AMC_DEFAULT_END
    else:
        try:
            end = float(raw)
        except (TypeError, ValueError):
            return None
    if not (end > 0):
        return None
    start_raw = params.get("start_value", params.get("start", 0))
    try:
        start = float(start_raw or 0)
    except (TypeError, ValueError):
        start = 0.0
    prefix = str(params.get("prefix", "$") or "")
    return start, end, prefix


def _amc_frames(start: float, end: float, prefix: str, count_sec: float) -> list[str]:
    frames = max(2, int(round(count_sec * _AMC_FPS / 2)))
    labels: list[str] = []
    prev = None
    for i in range(frames + 1):
        t = i / frames
        value = start + (end - start) * t
        text = _amc_money(value, prefix)
        if text != prev:
            labels.append(text)
            prev = text
    final = _amc_money(end, prefix)
    if labels[-1] != final:
        labels.append(final)
    return labels


def _amc_icons() -> list[dict[str, float | bool]]:
    """Catalog golden-angle burst, scaled 1920×1080 → 1080×1920."""
    sx, sy = 1080 / 1920, 1920 / 1080
    specs: list[dict[str, float | bool]] = []
    for i in range(_AMC_ICONS):
        coin = i % 3 == 0
        angle = i * 2.399963229728653
        ring = i % 5
        radius_x = (260 + ring * 145 + (i % 7) * 12) * sx
        radius_y = (160 + ring * 78 + (i % 6) * 12) * sy
        offset_x = ((i % 4) * 24 - 36) * sx
        offset_y = ((i % 5) * 18 - 36) * sy
        x = max(-486, min(486, math.cos(angle) * radius_x + offset_x))
        y = max(-827, min(827, math.sin(angle * 1.13) * radius_y + offset_y))
        specs.append({
            "x": x,
            "y": y,
            "delay": (i % 8) * 0.025,
            "duration": 0.74 + (i % 5) * 0.045,
            "fade_delay": (i % 5) * 0.05,
            "rotation": ((i * 43) % 160) - 80,
            "scale": (0.72 + (i % 4) * 0.08) if coin else (0.68 + (i % 5) * 0.07),
            "coin": coin,
        })
    return specs


def dv_apple_money_count(ctx: "TemplateCtx") -> Piece:
    """Count $0→end, then bills/coins burst. No textContent, no filter tween."""
    spec = _amc_spec(ctx.params)
    if spec is None:
        return Piece()
    start_v, end_v, prefix = spec
    times = _amc_times(ctx.duration)
    node_id = f"amc-{ctx.index:02d}"
    start = ctx.start
    labels = _amc_frames(start_v, end_v, prefix, times["count"])
    longest = max(labels, key=len)
    size = fit_size(longest, 900, 220)
    final = labels[-1]
    icons = _amc_icons()

    spans = [
        f'<span id="{node_id}-v{i}" class="amc-val">{_esc(text)}</span>'
        for i, text in enumerate(labels)
    ]
    burst: list[str] = []
    tweens: list[str] = [
        f'tl.fromTo("#{node_id}-stage",{{y:26,opacity:0,scale:0.985}},'
        f'{{y:0,opacity:1,scale:1,duration:{_num(times["enter"])},'
        f'ease:"power2.out"}},{_num(start)});',
        f'tl.set("#{node_id}-v0",{{opacity:1}},{_num(start)});',
    ]
    count_sec = times["count"]
    nlab = max(1, len(labels) - 1)
    prev = 0
    for i in range(1, len(labels)):
        at = start + count_sec * (i / nlab)
        tweens.append(
            f'tl.set("#{node_id}-v{prev}",{{opacity:0}},{_num(at)});')
        tweens.append(
            f'tl.set("#{node_id}-v{i}",{{opacity:1}},{_num(at)});')
        prev = i

    hit = start + times["hit"]
    tweens.extend([
        f'tl.set("#{node_id}-v{prev}",{{opacity:0}},{_num(hit)});',
        f'tl.fromTo("#{node_id}-hit",{{opacity:0,scale:1}},'
        f'{{opacity:1,scale:1.06,duration:{_num(times["pop"])},'
        f'ease:"back.out(2.2)"}},{_num(hit)});',
        f'tl.to("#{node_id}-hit",{{scale:1,duration:{_num(times["settle"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(hit + times["pop"])});',
        f'tl.fromTo("#{node_id}-flash",{{opacity:0}},'
        f'{{opacity:0.34,duration:{_num(times["flash_in"])},ease:"none"}},'
        f'{_num(hit)});',
        f'tl.to("#{node_id}-flash",{{opacity:0.22,duration:{_num(times["flash_hold"])},'
        f'ease:"none",immediateRender:false}},'
        f'{_num(hit + times["flash_in"])});',
        f'tl.to("#{node_id}-flash",{{opacity:0,duration:{_num(times["flash_out"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(hit + times["flash_in"] + times["flash_hold"])});',
    ])

    for i, spec_i in enumerate(icons):
        iid = f"{node_id}-i{i:02d}"
        kind = "coin" if spec_i["coin"] else "bill"
        burst.append(
            f'<div id="{iid}" class="amc-icon {kind}">'
            f'<span class="amc-mark">$</span></div>'
        )
        delay = _amc_at(float(spec_i["delay"]), ctx.duration)
        fade_delay = _amc_at(float(spec_i["fade_delay"]), ctx.duration)
        burst_at = start + times["burst_at"] + delay
        fade_at = start + times["fade_at"] + fade_delay
        dur = _amc_dur(float(spec_i["duration"]), ctx.duration)
        if burst_at + dur > fade_at:
            dur = max(0.001, fade_at - burst_at - 0.001)
        tweens.append(
            f'tl.fromTo("#{iid}",{{x:0,y:0,rotation:0,scale:0.18,opacity:0}},'
            f'{{x:{_num(float(spec_i["x"]))},y:{_num(float(spec_i["y"]))},'
            f'rotation:{_num(float(spec_i["rotation"]))},'
            f'scale:{_num(float(spec_i["scale"]))},opacity:1,'
            f'duration:{_num(dur)},ease:"power4.out"}},'
            f'{_num(burst_at)});')
        fade_y = float(spec_i["y"]) + (-58 if float(spec_i["y"]) < 0 else 58)
        tweens.append(
            f'tl.to("#{iid}",{{y:{_num(fade_y)},'
            f'scale:{_num(float(spec_i["scale"]) * 0.54)},opacity:0,'
            f'duration:{_num(times["fade_dur"])},ease:"power2.in",'
            f'immediateRender:false}},'
            f'{_num(start + times["fade_at"] + fade_delay)});')
        tweens.append(
            f'tl.set("#{iid}",{{opacity:0}},'
            f'{_num(start + times["fade_at"] + fade_delay + times["fade_dur"])});')

    out_at = start + times["out_at"]
    tweens.extend([
        f'tl.to("#{node_id}-hit",{{opacity:0,scale:0.985,'
        f'duration:{_num(times["out_dur"])},ease:"power2.in",'
        f'immediateRender:false}},{_num(out_at)});',
        f'tl.set("#{node_id}-stage",{{opacity:0}},'
        f'{_num(out_at + times["out_dur"])});',
    ])

    node = (
        f'<div id="{node_id}" class="clip overlay amc-chart" {_timing(ctx)}>'
        f'<div id="{node_id}-stage" class="amc-stage" '
        f'style="font-size:{size}px">'
        f'<div id="{node_id}-flash" class="amc-flash"></div>'
        f'<div id="{node_id}-amount" class="amc-amount">{"".join(spans)}</div>'
        f'<div id="{node_id}-hit" class="amc-hit">{_esc(final)}</div>'
        f'<div id="{node_id}-burst" class="amc-burst">{"".join(burst)}</div>'
        f'</div></div>'
    )
    return Piece(nodes=[node], tweens=tweens)


def amc_css() -> str:
    """Full-bleed Apple money count. Catalog paper/ink/green, Inter."""
    return (
        ".amc-chart{left:0;top:0;width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden;font-family:Inter,var(--font-subtitle),sans-serif;"
        f"color:{_AMC_INK};background:{_AMC_PAPER}}}"
        ".amc-stage{position:absolute;inset:0;transform-origin:50% 50%;"
        "will-change:transform,opacity}"
        ".amc-flash{position:absolute;inset:0;z-index:1;opacity:0;"
        f"background:{_AMC_GREEN}}}"
        ".amc-amount{position:absolute;inset:0;z-index:5;"
        "display:flex;align-items:center;justify-content:center;"
        "font-weight:900;line-height:0.9;letter-spacing:0;"
        "font-variant-numeric:tabular-nums;white-space:nowrap;"
        f"color:{_AMC_INK};"
        "text-shadow:0 3px 0 rgba(253,254,254,0.58),"
        "0 18px 36px rgba(17,19,21,0.14),0 42px 92px rgba(17,19,21,0.1)}"
        ".amc-amount .amc-val{position:absolute;opacity:0}"
        ".amc-hit{position:absolute;inset:0;z-index:6;"
        "display:flex;align-items:center;justify-content:center;"
        "font-weight:900;line-height:0.9;letter-spacing:0;"
        "font-variant-numeric:tabular-nums;white-space:nowrap;opacity:0;"
        f"color:{_AMC_GREEN};"
        "text-shadow:0 3px 0 rgba(253,254,254,0.52),"
        "0 18px 40px rgba(48,209,88,0.3),0 46px 96px rgba(7,84,31,0.2)}"
        ".amc-burst{position:absolute;inset:0;z-index:8;pointer-events:none;"
        "overflow:visible}"
        ".amc-icon{position:absolute;left:50%;top:50%;display:flex;"
        "align-items:center;justify-content:center;opacity:0;"
        "transform-origin:50% 50%;will-change:transform,opacity;"
        "margin-left:-48px;margin-top:-26px}"
        ".amc-icon.bill{width:96px;height:52px;border-radius:10px;"
        f"background:{_AMC_GREEN};"
        "box-shadow:inset 0 0 0 3px rgba(7,84,31,0.2),"
        "inset 0 -10px 18px rgba(7,84,31,0.1),"
        "0 16px 26px rgba(7,84,31,0.2)}"
        ".amc-icon.coin{width:64px;height:64px;margin-left:-32px;margin-top:-32px;"
        "border-radius:50%;"
        f"background:radial-gradient(circle at 34% 30%,{_AMC_COIN_HI} 0%,"
        f"{_AMC_COIN} 40%,{_AMC_COIN_LO} 100%);"
        "box-shadow:inset 0 0 0 4px rgba(111,76,0,0.12),"
        "inset 0 -8px 14px rgba(111,76,0,0.1),"
        "0 16px 30px rgba(111,76,0,0.18)}"
        f".amc-icon .amc-mark{{position:relative;z-index:1;color:{_AMC_BRAND};"
        "font-size:30px;font-weight:900;line-height:1}"
        f".amc-icon.coin .amc-mark{{color:{_AMC_COIN_INK};font-size:28px}}"
    )
