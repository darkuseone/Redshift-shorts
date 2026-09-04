"""Приёмы, перенесённые из ветки шаблонов (см. tools/port_templates.py).

Отдельный файл, а не вперемешку с нашими: перенос — механический, и
граница обязана быть видна. Чинится и снимается он тоже отдельно.

Источник: origin/cursor/hyperframes-sci-templates-647c

Правила движка те же, что и у наших приёмов: кадр — чистая функция
времени, прозрачность клипа трогать нельзя, два твина на одно свойство
одного элемента запрещены. Перенесённое проходит те же тесты.
"""

from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from .wmp_shapes import WMP_GRATICULE, WMP_SHAPES, WMP_SOURCE, WMP_SUBTITLE, WMP_TITLE, WMP_TOP5, WMP_VB
from .templates import (
    Piece, _enter_at, _esc, _fs_ceiling, _labels, _num, _timing, _values, fit_size, text_width,
)

TemplateCtx = Any  # подсказка типа: настоящий класс — в templates.py

_ABC_CATALOG_SEC = 5.0


def _abc_times(duration: float) -> dict[str, float]:
    """Окно animated bar chart: каталог 0.5 с пауза, 1.2 с рост power3.out.

    На шорте это ``ctx.duration`` (2–4 с). Доли 5 с окна сохраняем, стык +1 мс.
    """
    d = max(0.05, float(duration))
    s = d / _ABC_CATALOG_SEC

    def t(catalog: float) -> float:
        return max(0.0, min(d, catalog * s))

    grow_at = t(0.5)
    grow_end = t(1.7)
    if grow_at + 0.001 > grow_end:
        grow_end = min(d, grow_at + 0.001)
    if grow_at + 0.001 > grow_end:
        grow_at = max(0.0, grow_end - 0.001)
    if grow_end + 0.001 > d:
        grow_end = max(0.001, d - 0.001)
        if grow_at + 0.001 > grow_end:
            grow_at = max(0.0, grow_end - 0.001)
    grow_dur = max(0.001, grow_end - grow_at)
    return {"grow_at": grow_at, "grow_dur": grow_dur, "kill_at": d}


_ABC_MAX_BARS = 7


_ABC_BARS_PX = 210


def dv_animated_bar_chart(ctx: "TemplateCtx") -> Piece:
    """Карточка: столбики растут снизу (scaleY), KPI +42%.

    Каталог твинит CSS-var ``--hf-grow`` / ``--hf-dash``. Здесь GSAP
    ``scaleY`` от нижней кромки, без ``height``/``width`` и без dash.
    Твины на столбиках, не на ``.clip``. Цвета карточки каталога —
    жест, не палитра канала. ``-apple-system`` не ставим. Inter как
    в каталоге. ``bar-race-mini`` / ``compare-bars`` не трогаем.
    """
    values = _values(ctx)
    if not values:
        return Piece()
    values = values[:_ABC_MAX_BARS]
    peak = max(values) or 1.0
    # Каталог задаёт высоту столбика в процентах контейнера (max 95 %).
    # Крупные числа из сценария нормируем к максимуму.
    if peak <= 100.0:
        fracs = [max(0.04, v / 100.0) for v in values]
    else:
        fracs = [max(0.04, v / peak) for v in values]
    labels = _labels(ctx, len(values))
    title = str(ctx.params.get("title") or "Animated Bar Chart").strip()
    subtitle = str(ctx.params.get("subtitle") or (
        "A compact data card with deterministic bar growth "
        "and value callouts.")).strip()
    kpi = str(ctx.params.get("kpi") or ctx.params.get("callout") or "").strip()
    node_id = f"abc-{ctx.index:02d}"
    times = _abc_times(ctx.duration)
    start = ctx.start
    cols: list[str] = []
    tweens: list[str] = []
    for i, frac in enumerate(fracs):
        h_px = frac * _ABC_BARS_PX
        bid = f"{node_id}-b{i}"
        cols.append(
            f'<div class="abc-col">'
            f'<div class="abc-slot" style="height:{h_px:.1f}px">'
            f'<span id="{bid}" class="abc-grow">'
            f'<span class="abc-fill"></span></span></div>'
            f'<span class="abc-lbl">{_esc(labels[i])}</span></div>')
        if times["grow_at"] >= 0.001:
            tweens.append(
                f'tl.set("#{bid}",{{scaleY:0,opacity:1}},{_num(start)});')
        tweens.append(
            f'tl.fromTo("#{bid}",{{scaleY:0,opacity:1}},'
            f'{{scaleY:1,opacity:1,duration:{_num(times["grow_dur"])},'
            f'ease:"power3.out",immediateRender:false}},'
            f'{_num(start + times["grow_at"])});')
        tweens.append(
            f'tl.set("#{bid}",{{scaleY:0,opacity:0}},'
            f'{_num(start + times["kill_at"])});')
    kpi_html = (f'<strong class="abc-kpi">{_esc(kpi)}</strong>' if kpi else "")
    n = len(values)
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay abc-chart" {_timing(ctx)}>'
               f'<div class="abc-card">'
               f'<div class="abc-head">'
               f'<h3 class="abc-title">{_esc(title)}</h3>'
               f'<p class="abc-sub">{_esc(subtitle)}</p>'
               f'{kpi_html}</div>'
               f'<div class="abc-bars" style="grid-template-columns:repeat({n},1fr)">'
               f'{"".join(cols)}</div></div></div>'],
        tweens=tweens)


def _bcr_parse_periods(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(part).strip() for part in raw if str(part).strip()]
    return []


_BCR_MAX_SERIES = 8


def _bcr_pad_values(values: list[float], count: int) -> list[float]:
    if not values:
        return [0.0] * count
    out = list(values)
    while len(out) < count:
        out.append(out[-1])
    return out[:count]


def _bcr_parse_series(raw: Any, period_count: int) -> list[tuple[str, list[float]]]:
    out: list[tuple[str, list[float]]] = []
    rows: list[Any]
    if isinstance(raw, str):
        rows = [line.strip() for line in re.split(r"[\n;]+", raw) if line.strip()]
    elif isinstance(raw, (list, tuple)):
        rows = list(raw)
    else:
        return []
    for item in rows:
        label = ""
        values: list[float] = []
        if isinstance(item, str):
            split = item.find(":")
            if split < 0:
                continue
            label = item[:split].strip()
            values = []
            for part in item[split + 1:].split(","):
                try:
                    values.append(float(part.strip()))
                except ValueError:
                    continue
        elif isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            raw_vals = item.get("values") or []
            values = [float(v) for v in raw_vals if isinstance(v, (int, float))]
        if not label or not values:
            continue
        out.append((label, _bcr_pad_values(values, period_count)))
        if len(out) >= _BCR_MAX_SERIES:
            break
    return out


_BCR_DEMO_PERIODS = ["2019", "2020", "2021", "2022", "2023", "2024"]


def _bcr_synthesize(values: list[float], labels: list[str],
                    periods: list[str]) -> list[tuple[str, list[float]]]:
    t_count = max(2, len(periods))
    series: list[tuple[str, list[float]]] = []
    for i, value in enumerate(values[:_BCR_MAX_SERIES]):
        power = 0.65 + 0.12 * ((i * 3) % 5)
        start = 0.22 + 0.07 * ((i * 2) % 6)
        row: list[float] = []
        for step in range(t_count):
            u = step / (t_count - 1) if t_count > 1 else 1.0
            row.append(max(0.0, float(value) * (start + (1.0 - start) * (u ** power))))
        series.append((labels[i] or f"S{i + 1}", row))
    return series


_BCR_DEMO_SERIES: tuple[tuple[str, tuple[float, ...]], ...] = (
    ("Northwind", (42, 58, 71, 96, 118, 131)),
    ("Cobalt", (30, 46, 68, 92, 126, 168)),
    ("Ferry", (55, 62, 66, 70, 74, 79)),
    ("Marlow", (18, 33, 52, 61, 88, 104)),
    ("Aster", (25, 28, 44, 58, 63, 72)),
    ("Pell", (12, 20, 39, 47, 55, 90)),
    ("Quill", (8, 11, 15, 24, 40, 66)),
    ("Dunmore", (35, 37, 38, 40, 42, 44)),
)


def _bcr_table(ctx: "TemplateCtx") -> tuple[list[str], list[tuple[str, list[float]]]] | None:
    """Таблица гонки: явный series, иначе 1D values, иначе DEMO 1 каталога."""
    periods = _bcr_parse_periods(ctx.params.get("periods"))
    n_periods = max(1, len(periods) or len(_BCR_DEMO_PERIODS))
    series = _bcr_parse_series(ctx.params.get("series"), n_periods)
    if series:
        n_periods = len(series[0][1])
        if not periods:
            periods = [str(2019 + i) for i in range(n_periods)]
        periods = (periods + [str(i + 1) for i in range(n_periods)])[:n_periods]
        return periods, [(lab, _bcr_pad_values(vals, n_periods)) for lab, vals in series]
    values = _values(ctx)
    if values:
        t_count = max(2, len(periods) or 6)
        if not periods:
            periods = [str(2019 + i) for i in range(t_count)]
        periods = (periods + [str(i + 1) for i in range(t_count)])[:t_count]
        labels = _labels(ctx, len(values))
        return periods, _bcr_synthesize(values, labels, periods)
    if ctx.params.get("demo") is False:
        return None
    # DEMO 1 каталога: без данных в плане всё равно показываем namesake-жест.
    if not ctx.params:
        return None
    return list(_BCR_DEMO_PERIODS), [(n, list(v)) for n, v in _BCR_DEMO_SERIES]


_BCR_CATALOG_SEC = 12.0


_BCR_RACE_SEC = 10.0


_BCR_PERIOD_SEC = 2.0


def _bcr_times(duration: float) -> dict[str, float]:
    """Окно bar chart race: каталог 12 с, гонка 10 с, период 2 с.

    На шорте это ``ctx.duration``. Доли 12 с окна сохраняем, стык +1 мс.
    """
    d = max(0.05, float(duration))
    s = d / _BCR_CATALOG_SEC
    race_end = min(d, _BCR_RACE_SEC * s)
    if race_end + 0.001 > d:
        race_end = max(0.001, d - 0.001)
    period = max(0.001, _BCR_PERIOD_SEC * s)
    return {"scale": s, "race_end": race_end, "kill_at": d, "period": period}


_BCR_PLOT_H = 1404


_BCR_K = 5


_BCR_TICK_POOL = 5


def _bcr_clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _bcr_value_at(t: float, values: list[float], period_dur: float) -> float:
    t_count = len(values)
    if t_count < 2:
        return values[0]
    u = t / period_dur
    i = int(_bcr_clamp(math.floor(u), 0, t_count - 2))
    frac = _bcr_clamp(u - i, 0.0, 1.0)
    return values[i] + (values[i + 1] - values[i]) * frac


def _bcr_rank_pos(t: float, index: int, ranks: list[list[int]], kf_dur: float) -> float:
    if len(ranks) < 2:
        return float(ranks[0][index])
    m = t / kf_dur
    m0 = int(_bcr_clamp(math.floor(m), 0, len(ranks) - 2))
    x = _bcr_clamp(m - m0, 0.0, 1.0)
    ease = x * x * (3.0 - 2.0 * x)
    a = ranks[m0][index]
    b = ranks[m0 + 1][index]
    return a + (b - a) * ease


def _bcr_frame(t: float, series: list[tuple[str, list[float]]],
               ranks: list[list[int]], kf_dur: float, bar_count: int
               ) -> tuple[list[float], list[float], list[float], int, float]:
    values = [_bcr_value_at(t, row[1], _BCR_PERIOD_SEC) for row in series]
    leader = min(range(len(values)), key=lambda j: (-values[j], j))
    scale_max = max(values[leader] * 1.06, 1e-6)
    ys = [_bcr_rank_pos(t, j, ranks, kf_dur) for j in range(len(series))]
    opacities = [_bcr_clamp(bar_count - y, 0.0, 1.0) for y in ys]
    return values, ys, opacities, leader, scale_max


_BCR_TRACK_W = 600


_BCR_ACCENT = "#E63946"


_BCR_INK = "#111214"


def _bcr_nice_step(x: float) -> float:
    x = max(float(x), 1e-9)
    exp = 10 ** math.floor(math.log10(x))
    frac = x / exp
    if frac <= 1:
        nice = 1
    elif frac <= 2:
        nice = 2
    elif frac <= 5:
        nice = 5
    else:
        nice = 10
    return exp * nice


_BCR_TRACK_X = 248


def _bcr_fmt(value: float, prefix: str, suffix: str, decimals: int = 0) -> str:
    if decimals <= 0:
        body = f"{int(round(value)):,}"
    else:
        body = f"{value:,.{decimals}f}"
    return f"{prefix}{body}{suffix}"


_BCR_BAR_COUNT = 6


_BCR_TICK_LABEL_W = 80


def dv_bar_chart_race(ctx: "TemplateCtx") -> Piece:
    """Гонка столбиков: ряды меняются местами, лидер красный.

    Каталог DEMO 1 твинит ``width`` и пишет ``textContent`` из ``onUpdate``.
    Здесь GSAP ``scaleX`` / ``x`` / ``y`` / ``opacity``, числа заранее
    span-ами. Цвета бумаги ``var(--color-accent-soft)``, чернил ``var(--color-ink)`` и акцента
    ``var(--color-accent)`` как в каталоге — жест, не палитра канала. Inter как в
    каталоге. ``-apple-system`` не ставим. ``bar-race-mini`` /
    ``animated-bar-chart`` / ``.dv-bar`` не трогаем.
    """
    table = _bcr_table(ctx)
    if table is None:
        return Piece()
    periods, series = table
    t_count = len(periods)
    n_series = len(series)
    if t_count < 1 or n_series < 1:
        return Piece()
    bar_count = int(round(float(ctx.params.get("bar_count",
                    ctx.params.get("barCount", _BCR_BAR_COUNT)))))
    bar_count = int(_bcr_clamp(bar_count, 3, 12))
    prefix = str(ctx.params.get("value_prefix",
                 ctx.params.get("valuePrefix", "$")))
    suffix = str(ctx.params.get("value_suffix",
                 ctx.params.get("valueSuffix", "M")))
    decimals = int(round(float(ctx.params.get("value_decimals",
                   ctx.params.get("valueDecimals", 0)))))
    decimals = int(_bcr_clamp(decimals, 0, 3))
    title = str(ctx.params.get("title") or "Streaming Subscribers by Service").strip()
    subtitle = str(ctx.params.get("subtitle") or "Ranked by reported subscribers").strip()
    source = str(ctx.params.get("source") or "Placeholder data").strip()
    node_id = f"bcr-{ctx.index:02d}"
    times = _bcr_times(ctx.duration)
    start = ctx.start
    pitch = _BCR_PLOT_H / bar_count
    bar_h = max(12.0, pitch * 0.62)
    bar_top = (pitch - bar_h) / 2.0
    kf_dur = _BCR_PERIOD_SEC / _BCR_K
    kf_count = (t_count - 1) * _BCR_K + 1 if t_count > 1 else 1
    ranks: list[list[int]] = []
    for m in range(kf_count):
        tm = m * kf_dur
        order = sorted(range(n_series),
                       key=lambda j: (-_bcr_value_at(tm, series[j][1], _BCR_PERIOD_SEC), j))
        row = [0] * n_series
        for rank, j in enumerate(order):
            row[j] = rank
        ranks.append(row)

    frames: list[tuple[float, list[float], list[float], list[float], int, float]] = []
    for m in range(kf_count):
        catalog_t = m * kf_dur
        packed_t = min(times["kill_at"], catalog_t * times["scale"])
        values, ys, opacities, leader, scale_max = _bcr_frame(
            catalog_t, series, ranks, kf_dur, bar_count)
        frames.append((packed_t, values, ys, opacities, leader, scale_max))

    rows_html: list[str] = []
    tweens: list[str] = []
    _, val0, y0, o0, lead0, scale0 = frames[0]
    for j, (label, values) in enumerate(series):
        rid, bid, vid = f"{node_id}-r{j}", f"{node_id}-b{j}", f"{node_id}-v{j}"
        spans = []
        for p, period_val in enumerate(values):
            spans.append(
                f'<span id="{vid}-p{p}">{_esc(_bcr_fmt(period_val, prefix, suffix, decimals))}</span>')
        rows_html.append(
            f'<div id="{rid}" class="bcr-row" style="height:{pitch:.2f}px">'
            f'<div class="bcr-name" data-layout-allow-overlap="">{_esc(label)}</div>'
            f'<div id="{bid}" class="bcr-bar" style="height:{bar_h:.2f}px;'
            f'top:{bar_top:.2f}px;width:{_BCR_TRACK_W}px"></div>'
            f'<div id="{vid}" class="bcr-value" data-layout-allow-overlap="">'
            f'{"".join(spans)}</div></div>')
        sx0 = _bcr_clamp(val0[j] / scale0, 0.0, 1.0)
        x0 = sx0 * _BCR_TRACK_W
        y_px = y0[j] * pitch
        color0 = _BCR_ACCENT if j == lead0 else _BCR_INK
        if o0[j] >= 0.001:
            tweens.append(
                f'tl.set("#{rid}",{{y:{_num(y_px)},opacity:{_num(o0[j])}}},'
                f'{_num(start)});')
        else:
            tweens.append(
                f'tl.set("#{rid}",{{y:{_num(y_px)}}},{_num(start)});')
        tweens.append(
            f'tl.set("#{bid}",{{scaleX:{_num(sx0)},opacity:1,'
            f'backgroundColor:"{color0}"}},{_num(start)});')
        tweens.append(
            f'tl.set("#{vid}",{{x:{_num(x0)}}},{_num(start)});')
        tweens.append(
            f'tl.set("#{vid}-p0",{{opacity:1}},{_num(start)});')

    ticks_html: list[str] = []
    for k in range(_BCR_TICK_POOL):
        zero = " bcr-tick-zero" if k == 0 else ""
        kid, lid = f"{node_id}-k{k}", f"{node_id}-l{k}"
        lab_spans = []
        for p in range(t_count):
            t_p = min(_BCR_RACE_SEC, p * _BCR_PERIOD_SEC)
            _vals, _ys, _op, _lead, scale_p = _bcr_frame(
                t_p, series, ranks, kf_dur, bar_count)
            step = _bcr_nice_step(scale_p / 4)
            tv = k * step
            text = _bcr_fmt(tv, prefix, suffix, decimals) if tv <= scale_p + 1e-6 else ""
            lab_spans.append(f'<span id="{lid}-p{p}">{_esc(text)}</span>')
        ticks_html.append(
            f'<div id="{kid}" class="bcr-tick-line{zero}"></div>'
            f'<div id="{lid}" class="bcr-tick-label">{"".join(lab_spans)}</div>')

    def _tick_state(scale_max: float) -> list[tuple[float, float, float]]:
        step = _bcr_nice_step(scale_max / 4)
        out: list[tuple[float, float, float]] = []
        for k in range(_BCR_TICK_POOL):
            tv = k * step
            visible = 1.0 if tv <= scale_max + 1e-6 else 0.0
            tx = _BCR_TRACK_X + (tv / scale_max) * _BCR_TRACK_W
            out.append((tx, tx - _BCR_TICK_LABEL_W / 2, visible))
        return out

    tick0 = _tick_state(frames[0][5])
    for k in range(_BCR_TICK_POOL):
        tx, lx, vis = tick0[k]
        if vis >= 0.5:
            tweens.append(
                f'tl.set("#{node_id}-k{k}",{{x:{_num(tx)},opacity:1}},'
                f'{_num(start)});')
            tweens.append(
                f'tl.set("#{node_id}-l{k}",{{x:{_num(lx)},opacity:1}},'
                f'{_num(start)});')
        else:
            tweens.append(
                f'tl.set("#{node_id}-k{k}",{{x:{_num(tx)}}},{_num(start)});')
            tweens.append(
                f'tl.set("#{node_id}-l{k}",{{x:{_num(lx)}}},{_num(start)});')
        tweens.append(
            f'tl.set("#{node_id}-l{k}-p0",{{opacity:1}},{_num(start)});')

    period_spans = []
    for p, label in enumerate(periods):
        period_spans.append(f'<span id="{node_id}-p{p}">{_esc(label)}</span>')
    tweens.append(f'tl.set("#{node_id}-p0",{{opacity:1}},{_num(start)});')

    prev_lead = lead0
    prev_period = 0
    for m in range(1, kf_count):
        t_at, vals, ys, ops, leader, scale_max = frames[m]
        t_prev, pvals, pys, pops, _plead, pscale = frames[m - 1]
        dur = max(0.001, t_at - t_prev)
        play = dur if dur <= 0.001 else max(0.001, dur - 0.001)
        at = start + t_prev
        for j in range(n_series):
            rid, bid, vid = f"{node_id}-r{j}", f"{node_id}-b{j}", f"{node_id}-v{j}"
            sx_a = _bcr_clamp(pvals[j] / pscale, 0.0, 1.0)
            sx_b = _bcr_clamp(vals[j] / scale_max, 0.0, 1.0)
            tweens.append(
                f'tl.fromTo("#{rid}",{{y:{_num(pys[j] * pitch)},'
                f'opacity:{_num(pops[j])}}},{{y:{_num(ys[j] * pitch)},'
                f'opacity:{_num(ops[j])},duration:{_num(play)},ease:"none",'
                f'immediateRender:false}},{_num(at)});')
            tweens.append(
                f'tl.fromTo("#{bid}",{{scaleX:{_num(sx_a)},opacity:1}},'
                f'{{scaleX:{_num(sx_b)},opacity:1,duration:{_num(play)},'
                f'ease:"none",immediateRender:false}},{_num(at)});')
            tweens.append(
                f'tl.fromTo("#{vid}",{{x:{_num(sx_a * _BCR_TRACK_W)}}},'
                f'{{x:{_num(sx_b * _BCR_TRACK_W)},duration:{_num(play)},'
                f'ease:"none",immediateRender:false}},{_num(at)});')
        ticks_a = _tick_state(pscale)
        ticks_b = _tick_state(scale_max)
        for k in range(_BCR_TICK_POOL):
            ax, alx, av = ticks_a[k]
            bx, blx, bv = ticks_b[k]
            tweens.append(
                f'tl.fromTo("#{node_id}-k{k}",{{x:{_num(ax)},opacity:{_num(av)}}},'
                f'{{x:{_num(bx)},opacity:{_num(bv)},duration:{_num(play)},'
                f'ease:"none",immediateRender:false}},{_num(at)});')
            tweens.append(
                f'tl.fromTo("#{node_id}-l{k}",{{x:{_num(alx)},opacity:{_num(av)}}},'
                f'{{x:{_num(blx)},opacity:{_num(bv)},duration:{_num(play)},'
                f'ease:"none",immediateRender:false}},{_num(at)});')
        catalog_t = m * kf_dur
        period_i = int(_bcr_clamp(math.floor(catalog_t / _BCR_PERIOD_SEC), 0, t_count - 1))
        if period_i != prev_period:
            swap_at = start + t_at
            tweens.append(
                f'tl.set("#{node_id}-p{prev_period}",{{opacity:0}},{_num(swap_at)});')
            tweens.append(
                f'tl.set("#{node_id}-p{period_i}",{{opacity:1}},{_num(swap_at)});')
            for j in range(n_series):
                tweens.append(
                    f'tl.set("#{node_id}-v{j}-p{prev_period}",{{opacity:0}},'
                    f'{_num(swap_at)});')
                tweens.append(
                    f'tl.set("#{node_id}-v{j}-p{period_i}",{{opacity:1}},'
                    f'{_num(swap_at)});')
            for k in range(_BCR_TICK_POOL):
                tweens.append(
                    f'tl.set("#{node_id}-l{k}-p{prev_period}",{{opacity:0}},'
                    f'{_num(swap_at)});')
                tweens.append(
                    f'tl.set("#{node_id}-l{k}-p{period_i}",{{opacity:1}},'
                    f'{_num(swap_at)});')
            prev_period = period_i
        if leader != prev_lead:
            swap_at = start + t_at
            tweens.append(
                f'tl.set("#{node_id}-b{prev_lead}",{{backgroundColor:"{_BCR_INK}"}},'
                f'{_num(swap_at)});')
            tweens.append(
                f'tl.set("#{node_id}-b{leader}",{{backgroundColor:"{_BCR_ACCENT}"}},'
                f'{_num(swap_at)});')
            prev_lead = leader

    kill_at = start + times["kill_at"]
    for j in range(n_series):
        tweens.append(
            f'tl.set("#{node_id}-r{j}",{{y:0,opacity:0}},{_num(kill_at)});')
        tweens.append(
            f'tl.set("#{node_id}-b{j}",{{scaleX:0,opacity:0}},{_num(kill_at)});')
        tweens.append(
            f'tl.set("#{node_id}-v{j}",{{x:0,opacity:0}},{_num(kill_at)});')
    for k in range(_BCR_TICK_POOL):
        tweens.append(
            f'tl.set("#{node_id}-k{k}",{{x:0,opacity:0}},{_num(kill_at)});')
        tweens.append(
            f'tl.set("#{node_id}-l{k}",{{x:0,opacity:0}},{_num(kill_at)});')
    for p in range(t_count):
        tweens.append(
            f'tl.set("#{node_id}-p{p}",{{opacity:0}},{_num(kill_at)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay bcr-chart" {_timing(ctx)}>'
               f'<div class="bcr-bg"></div>'
               f'<div class="bcr-head">'
               f'<div class="bcr-head-left">'
               f'<h1 class="bcr-title">{_esc(title)}</h1>'
               f'<p class="bcr-subtitle">{_esc(subtitle)}</p></div>'
               f'<div class="bcr-head-right">'
               f'<span class="bcr-period-caption">Period</span>'
               f'<span class="bcr-period">{"".join(period_spans)}</span></div></div>'
               f'<div class="bcr-plot">{"".join(rows_html)}</div>'
               f'<div class="bcr-axis">{"".join(ticks_html)}</div>'
               f'<p class="bcr-source">{_esc(source)}</p></div>'],
        tweens=tweens)


def _cst_parse_csv(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(part).strip() for part in raw if str(part).strip()]
    return []


_CST_MAX = 8


def _cst_token(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _cst_table(ctx: "TemplateCtx") -> tuple[list[float], list[str], list[str]] | None:
    """Числа и подписи DEMO 1: 12, 28, 45, 64 / Q1–Q4. Без данных — пусто."""
    values = _values(ctx)
    tokens: list[str]
    if values:
        tokens = [_cst_token(v) for v in values]
    else:
        values = []
        tokens = []
        for token in _cst_parse_csv(ctx.params.get("data")):
            try:
                values.append(float(token))
                tokens.append(token)
            except ValueError:
                continue
    if not values:
        return None
    values = values[:_CST_MAX]
    tokens = tokens[:_CST_MAX]
    n = len(values)
    labels = _cst_parse_csv(ctx.params.get("labels"))
    if not labels:
        labels = _labels(ctx, n)
    if not any(labels):
        labels = [f"Q{i + 1}" for i in range(n)]
    labels = (labels + [""] * n)[:n]
    return values, tokens, labels


_CST_ACCENTS = {
    "green": "#E63946",
    "blue": "#7A7D82",
    "violet": "#ED747D",
}


_CST_IN_BASE = 3.3


def _cst_times(duration: float) -> dict[str, float]:
    """Окно chart-story: каталог IN 3.3 с на 5 с, exit none.

    На шорте это ``ctx.duration``. Короче 3.3 с — IN сжимается, стык +1 мс.
    """
    d = max(0.05, float(duration))
    s = d / _CST_IN_BASE if d < _CST_IN_BASE else 1.0
    inn = _CST_IN_BASE * s
    if inn + 0.001 > d:
        inn = max(0.001, d - 0.001)
        s = inn / _CST_IN_BASE
    hold = max(0.0, d - inn)
    callout_at = min(max(0.0, 2.35 * s), max(0.0, d - 0.002))
    return {
        "s": s,
        "kill_at": d,
        "enter_dur": max(0.001, 0.5 * s),
        "axis_at": 0.15 * s,
        "axis_dur": max(0.001, 0.5 * s),
        "build_at": 0.55 * s,
        "build_dur": 1.6 * s,
        "bar_dur": max(0.001, 0.85 * s),
        "labels_at": 0.85 * s,
        "label_stagger": 0.12 * s,
        "fade_dur": max(0.001, 0.4 * s),
        "value_lag": 0.65 * s,
        "callout_at": callout_at,
        "pop_dur": max(0.001, 0.45 * s),
        "roll_dur": max(0.001, 0.7 * s),
        "hold_start": inn,
        "hold": hold,
    }


_CST_LEFT = 100


def _cst_clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


_CST_STILLNESS = 0.3


_CST_RIGHT = 980


_CST_BASE = 1280


_CST_TOP = 460


_CST_SERIES = "#7A7D82"


_CST_ENTER_Y = 46


_CST_DRIFT_Y = -10


def _cst_power2_out(t: float) -> float:
    u = 1.0 - t
    return 1.0 - u * u


def dv_chart_story(ctx: "TemplateCtx") -> Piece:
    """Столбики растут снизу по очереди, коллаут на акценте.

    Каталог DEMO 1 твинит ``attr.height`` / ``y`` и пишет ``textContent``
    из покадрового набора. Здесь GSAP ``scaleY`` / ``scaleX`` / ``y`` /
    ``opacity`` / ``scale``, числа заранее span-ами. Сцена ``var(--color-ink)``,
    чернила ``var(--color-text-soft)``, акцент ``var(--color-accent)`` как в каталоге — жест, не
    палитра канала. Inter / JetBrains Mono. ``-apple-system`` не ставим.
    ``bar-race-mini`` / ``animated-bar-chart`` / ``bar-chart-race`` /
    ``.dv-bar`` не трогаем.
    """
    table = _cst_table(ctx)
    if table is None:
        return Piece()
    values, tokens, labels = table
    n = len(values)
    peak = max(values) or 1.0
    unit = str(ctx.params["unit"]) if "unit" in ctx.params else "%"
    raw_emp = ctx.params.get("emphasize")
    if raw_emp is None or raw_emp == "":
        emp = n - 1
    else:
        try:
            emp = int(round(float(raw_emp)))
        except (TypeError, ValueError):
            emp = n - 1
    emp = int(_cst_clamp(emp, 0, n - 1))
    accent_key = str(ctx.params.get("accent") or "green").strip().lower()
    accent = _CST_ACCENTS.get(accent_key, _CST_ACCENTS["green"])
    node_id = f"cst-{ctx.index:02d}"
    times = _cst_times(ctx.duration)
    start = ctx.start
    plot_w = float(_CST_RIGHT - _CST_LEFT)
    plot_h = float(_CST_BASE - _CST_TOP)
    band = plot_w / n
    bar_w = min(band * 0.62, 157.0)
    scale = plot_w / 840.0
    stagger = ((times["build_dur"] - times["bar_dur"]) / (n - 1)
               if n > 1 else 0.0)
    sid = f"{node_id}-stage"
    aid = f"{node_id}-axis"
    cid = f"{node_id}-call"
    vid = f"{node_id}-cv"
    tweens: list[str] = []
    parts: list[str] = [
        f'<div id="{aid}" class="cst-axis" style="left:{_CST_LEFT}px;'
        f'top:{_CST_BASE}px;width:{plot_w:.1f}px"></div>']
    tweens.append(
        f'tl.set("#{aid}",{{scaleX:0,opacity:1}},{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{aid}",{{scaleX:0,opacity:1}},'
        f'{{scaleX:1,opacity:1,duration:{_num(times["axis_dur"])},'
        f'ease:"power2.inOut",immediateRender:false}},'
        f'{_num(start + times["axis_at"])});')

    emp_h = max((values[emp] / peak) * plot_h, 3.0)
    for i, value in enumerate(values):
        height = max((value / peak) * plot_h, 3.0)
        cx = _CST_LEFT + band * (i + 0.5)
        x = cx - bar_w / 2.0
        y = _CST_BASE - height
        color = accent if i == emp else _CST_SERIES
        rx = min(10.0, bar_w * 0.18, height / 2.0)
        bid = f"{node_id}-b{i}"
        lid = f"{node_id}-al{i}"
        parts.append(
            f'<div id="{bid}" class="cst-bar" style="left:{x:.1f}px;top:{y:.1f}px;'
            f'width:{bar_w:.1f}px;height:{height:.1f}px;background:{color};'
            f'border-radius:{rx:.1f}px"></div>')
        parts.append(
            f'<div id="{lid}" class="cst-al" data-layout-allow-overlap="" '
            f'style="left:{cx - 90:.1f}px;top:{_CST_BASE + 18}px">'
            f'{_esc(labels[i])}</div>')
        at = times["build_at"] + stagger * i
        if at >= 0.001:
            tweens.append(
                f'tl.set("#{bid}",{{scaleY:0,opacity:1}},{_num(start)});')
        tweens.append(
            f'tl.fromTo("#{bid}",{{scaleY:0,opacity:1}},'
            f'{{scaleY:1,opacity:1,duration:{_num(times["bar_dur"])},'
            f'ease:"power3.out",immediateRender:false}},'
            f'{_num(start + at)});')
        label_at = times["labels_at"] + times["label_stagger"] * i
        tweens.append(
            f'tl.fromTo("#{lid}",{{opacity:0,y:8}},'
            f'{{opacity:1,y:0,duration:{_num(times["fade_dur"])},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + label_at)});')
        if i != emp:
            display = f"{tokens[i]}{unit}"
            nid = f"{node_id}-vl{i}"
            parts.append(
                f'<div id="{nid}" class="cst-vl" data-layout-allow-overlap="" '
                f'style="left:{cx - 90:.1f}px;top:{y - 40:.1f}px">'
                f'{_esc(display)}</div>')
            value_at = at + times["value_lag"]
            tweens.append(
                f'tl.fromTo("#{nid}",{{opacity:0,y:8}},'
                f'{{opacity:1,y:0,duration:{_num(times["fade_dur"])},'
                f'ease:"power2.out",immediateRender:false}},'
                f'{_num(start + value_at)});')

    display_emp = f"{tokens[emp]}{unit}"
    chip_w = max(96.0 * scale, len(display_emp) * 17.0 * scale + 44.0 * scale)
    chip_h = 52.0 * scale
    emp_cx = _CST_LEFT + band * (emp + 0.5)
    chip_cx = _cst_clamp(emp_cx, chip_w / 2 + 8, 1080 - chip_w / 2 - 8)
    chip_bottom = _CST_BASE - emp_h - 20.0 * scale
    chip_top = chip_bottom - chip_h
    chip_left = chip_cx - chip_w / 2
    dec = len(tokens[emp].split(".", 1)[1]) if "." in tokens[emp] else 0
    frames = max(1, int(round(times["roll_dur"] * 30)))
    spans: list[str] = []
    for frame in range(frames + 1):
        if frame == frames:
            text = display_emp
        else:
            t = frame / frames
            text = f"{values[emp] * _cst_power2_out(t):.{dec}f}{unit}"
        spans.append(f'<span id="{vid}-{frame}">{_esc(text)}</span>')
    parts.append(
        f'<div id="{cid}" class="cst-call" data-layout-allow-overlap="" '
        f'style="left:{chip_left:.1f}px;top:{chip_top:.1f}px;'
        f'width:{chip_w:.1f}px;height:{chip_h:.1f}px;background:{accent}">'
        f'<div id="{vid}" class="cst-cv">{"".join(spans)}</div></div>')

    tweens.append(
        f'tl.fromTo("#{sid}",{{opacity:0,y:{_CST_ENTER_Y}}},'
        f'{{opacity:1,y:0,duration:{_num(times["enter_dur"])},'
        f'ease:"power3.out",immediateRender:false}},{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{cid}",{{opacity:0,scale:0.6}},'
        f'{{opacity:1,scale:1,duration:{_num(times["pop_dur"])},'
        f'ease:"back.out(1.7)",immediateRender:false}},'
        f'{_num(start + times["callout_at"])});')
    for frame in range(frames + 1):
        at = start + times["callout_at"] + times["roll_dur"] * (frame / frames)
        if frame:
            tweens.append(
                f'tl.set("#{vid}-{frame - 1}",{{opacity:0}},{_num(at)});')
        tweens.append(
            f'tl.set("#{vid}-{frame}",{{opacity:1}},{_num(at)});')

    drift = times["hold"] - _CST_STILLNESS
    if drift > 0.1:
        half = drift / 2.0
        play = half if half <= 0.001 else max(0.001, half - 0.001)
        hold_at = start + times["hold_start"]
        tweens.append(
            f'tl.fromTo("#{sid}",{{y:0,opacity:1}},'
            f'{{y:{_CST_DRIFT_Y},opacity:1,duration:{_num(play)},'
            f'ease:"sine.inOut",immediateRender:false}},{_num(hold_at)});')
        tweens.append(
            f'tl.fromTo("#{sid}",{{y:{_CST_DRIFT_Y},opacity:1}},'
            f'{{y:0,opacity:1,duration:{_num(play)},'
            f'ease:"sine.inOut",immediateRender:false}},'
            f'{_num(hold_at + half)});')

    kill_at = start + times["kill_at"]
    tweens.append(
        f'tl.set("#{sid}",{{y:0,opacity:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{aid}",{{scaleX:0,opacity:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{cid}",{{scale:1,opacity:0}},{_num(kill_at)});')
    for i in range(n):
        tweens.append(
            f'tl.set("#{node_id}-b{i}",{{scaleY:0,opacity:0}},{_num(kill_at)});')
        tweens.append(
            f'tl.set("#{node_id}-al{i}",{{y:0,opacity:0}},{_num(kill_at)});')
        if i != emp:
            tweens.append(
                f'tl.set("#{node_id}-vl{i}",{{y:0,opacity:0}},{_num(kill_at)});')
    for frame in range(frames + 1):
        tweens.append(
            f'tl.set("#{vid}-{frame}",{{opacity:0}},{_num(kill_at)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay cst-chart" {_timing(ctx)}>'
               f'<div class="cst-bg"></div>'
               f'<div id="{sid}" class="cst-stage">{"".join(parts)}</div></div>'],
        tweens=tweens)


def _cpr_clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


_CPR_THICK_DEFAULT = 12.0


_CPR_THICK_LO = 4.0


_CPR_THICK_HI = 30.0


def _cpr_spec(params: dict[str, Any]) -> tuple[float, str, float | None, str, float] | None:
    """progress, label_text, numeric target, suffix, thickness. Пусто → None."""
    if not any(k in params and params[k] not in (None, "", [], ())
               for k in ("progress", "value", "label", "values")):
        return None
    raw_progress = params.get("progress", params.get("value"))
    if raw_progress in (None, "") and params.get("values"):
        raw_progress = params["values"][0]
    if raw_progress in (None, ""):
        progress = 100.0
    else:
        try:
            progress = float(raw_progress)
        except (TypeError, ValueError):
            progress = 100.0
        if not (0.0 <= progress <= 100.0) and "progress" not in params:
            progress = 100.0
    progress = _cpr_clamp(progress, 0.0, 100.0)
    raw_label = params.get("label")
    if raw_label is None or str(raw_label) == "":
        if "value" in params and params["value"] not in (None, ""):
            try:
                val = float(params["value"])
            except (TypeError, ValueError):
                val = progress
            suffix = str(params.get("suffix") or "")
            token = str(int(round(val))) if abs(val - round(val)) < 1e-9 else f"{val:g}"
            raw_label = f"{token}{suffix}"
        else:
            raw_label = f"{int(round(progress))}"
    label_text = str(raw_label)
    match = re.match(r"^\s*(-?\d+(?:\.\d+)?)(.*)$", label_text)
    label_target = float(match.group(1)) if match else None
    suffix = match.group(2) if match else ""
    raw_thick = params.get("thickness", _CPR_THICK_DEFAULT)
    try:
        thickness = float(raw_thick)
    except (TypeError, ValueError):
        thickness = _CPR_THICK_DEFAULT
    thickness = _cpr_clamp(thickness, _CPR_THICK_LO, _CPR_THICK_HI)
    return progress, label_text, label_target, suffix, thickness


_CPR_IN_BASE = 1.4


_CPR_OUT_BASE = 0.5


def _cpr_times(duration: float) -> dict[str, float]:
    """Окно conic-progress-ring: IN 1.4 с, OUT 0.5 с, HOLD остаток.

    Короче 1.9 с — IN и OUT сжимаются вместе. HOLD не трогаем.
    """
    d = max(0.05, float(duration))
    min_io = _CPR_IN_BASE + _CPR_OUT_BASE
    s = d / min_io if d < min_io else 1.0
    inn = _CPR_IN_BASE * s
    out = _CPR_OUT_BASE * s
    if inn + out + 0.001 > d:
        s = max(0.001, d - 0.001) / min_io
        inn = _CPR_IN_BASE * s
        out = max(0.001, d - inn - 0.001)
    hold = max(0.0, d - inn - out)
    out_start = inn + hold
    return {
        "in": inn,
        "out": out,
        "hold": hold,
        "out_start": out_start,
        "kill_at": d,
    }


_CPR_DISC = 734


_CPR_LEFT = 173


_CPR_TOP = 593


def _cpr_angles(fill: float) -> tuple[float, float]:
    """Правая половина −180→0, левая 0→180. Заполнение с 12 часов по часовой."""
    p = _cpr_clamp(fill, 0.0, 100.0)
    right = -180.0 + (min(p, 50.0) / 50.0) * 180.0
    left = (max(p - 50.0, 0.0) / 50.0) * 180.0
    return right, left


def _cpr_power2_out(t: float) -> float:
    u = 1.0 - _cpr_clamp(t, 0.0, 1.0)
    return 1.0 - u * u


_CPR_FPS = 30.0


def dv_conic_progress_ring(ctx: "TemplateCtx") -> Piece:
    """Кольцо заполняется от 12 часов, центр считает в такт.

    Каталог DEMO 1 твинит ``--ring-progress`` на conic-gradient и пишет
    ``textContent`` из ``onUpdate``. Здесь GSAP ``rotation`` двух половинок
    и заранее span-ы. Сцена ``var(--color-ink)``, бренд ``var(--color-accent)``, дорожка
    ``var(--color-space-deep)``, чернила ``var(--color-text-soft)`` как в каталоге — жест, не палитра
    канала. Inter. ``-apple-system`` не ставим. ``donut-fill`` / ``.dv-donut``
    / ``chart-story`` / ``animated-bar-chart`` / ``bar-chart-race`` не трогаем.
    """
    spec = _cpr_spec(ctx.params)
    if spec is None:
        return Piece()
    progress, label_text, label_target, suffix, thickness = spec
    node_id = f"cpr-{ctx.index:02d}"
    times = _cpr_times(ctx.duration)
    start = ctx.start
    inn = times["in"]
    sid = f"{node_id}-stage"
    aid = f"{node_id}-a"
    bid = f"{node_id}-b"
    vid = f"{node_id}-cv"
    hole_d = _CPR_DISC * (1.0 - thickness / 100.0)
    hole_x = _CPR_LEFT + (_CPR_DISC - hole_d) / 2.0
    hole_y = _CPR_TOP + (_CPR_DISC - hole_d) / 2.0
    frames = max(1, int(round(inn * _CPR_FPS)))
    tweens: list[str] = []
    spans: list[str] = []
    texts: list[str] = []
    for frame in range(frames + 1):
        if label_target is None:
            text = label_text
        elif frame == frames:
            text = label_text
        else:
            t = frame / frames
            fill = progress * _cpr_power2_out(t)
            ratio = fill / progress if progress > 0 else 1.0
            text = f"{int(round(label_target * ratio))}{suffix}"
        texts.append(text)
        spans.append(f'<span id="{vid}-{frame}">{_esc(text)}</span>')

    r0, l0 = _cpr_angles(0.0)
    tweens.append(
        f'tl.set("#{aid}",{{rotation:{_num(r0)}}},{_num(start)});')
    tweens.append(
        f'tl.set("#{bid}",{{rotation:{_num(l0)}}},{_num(start)});')
    prev_r, prev_l = r0, l0
    prev_t = 0.0
    for frame in range(1, frames + 1):
        t = frame / frames
        fill = progress * _cpr_power2_out(t)
        right, left = _cpr_angles(fill)
        at = start + inn * prev_t
        dt = inn * (t - prev_t)
        play = dt if dt <= 0.001 else max(0.001, dt - 0.001)
        tweens.append(
            f'tl.fromTo("#{aid}",{{rotation:{_num(prev_r)}}},'
            f'{{rotation:{_num(right)},duration:{_num(play)},'
            f'ease:"none",immediateRender:false}},{_num(at)});')
        tweens.append(
            f'tl.fromTo("#{bid}",{{rotation:{_num(prev_l)}}},'
            f'{{rotation:{_num(left)},duration:{_num(play)},'
            f'ease:"none",immediateRender:false}},{_num(at)});')
        prev_r, prev_l, prev_t = right, left, t

    tweens.append(
        f'tl.set("#{vid}-0",{{opacity:1}},{_num(start)});')
    prev_shown = 0
    for frame in range(1, frames + 1):
        if texts[frame] == texts[prev_shown]:
            continue
        at = start + inn * (frame / frames)
        tweens.append(
            f'tl.set("#{vid}-{prev_shown}",{{opacity:0}},{_num(at)});')
        tweens.append(
            f'tl.set("#{vid}-{frame}",{{opacity:1}},{_num(at)});')
        prev_shown = frame

    out_dur = times["out"]
    out_play = out_dur if out_dur <= 0.001 else max(0.001, out_dur - 0.001)
    tweens.append(
        f'tl.fromTo("#{sid}",{{opacity:1}},'
        f'{{opacity:0,duration:{_num(out_play)},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["out_start"])});')

    kill_at = start + times["kill_at"]
    tweens.append(
        f'tl.set("#{sid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{aid}",{{rotation:{_num(r0)}}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{bid}",{{rotation:{_num(l0)}}},{_num(kill_at)});')
    for frame in range(frames + 1):
        tweens.append(
            f'tl.set("#{vid}-{frame}",{{opacity:0}},{_num(kill_at)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay cpr-chart" {_timing(ctx)}>'
               f'<div class="cpr-bg"></div>'
               f'<div id="{sid}" class="cpr-stage">'
               f'<div class="cpr-disc">'
               f'<div class="cpr-right"><div id="{aid}" class="cpr-rot">'
               f'<div class="cpr-paint"></div></div></div>'
               f'<div class="cpr-left"><div id="{bid}" class="cpr-rot">'
               f'<div class="cpr-paint"></div></div></div></div>'
               f'<div class="cpr-hole" data-layout-allow-overlap="" '
               f'style="left:{hole_x:.1f}px;top:{hole_y:.1f}px;'
               f'width:{hole_d:.1f}px;height:{hole_d:.1f}px"></div>'
               f'<div id="{vid}" class="cpr-cv" data-layout-allow-overlap="">'
               f'{"".join(spans)}</div></div></div>'],
        tweens=tweens)


def _dcl_num(raw: Any, default: float | None = None) -> float | None:
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


_DCL_DEFAULT_START = 82.0


_DCL_DEFAULT_END = 34.0


_DCL_DEFAULT_LABEL = "Retention"


def _dcl_spec(params: dict[str, Any]) -> tuple[float, float, str] | None:
    """start, end, label. Пусто → None."""
    if not any(k in params and params[k] not in (None, "", [], ())
               for k in ("start_value", "end_value", "values", "value", "label")):
        return None
    values: list[float] = []
    raw_values = params.get("values")
    if isinstance(raw_values, (list, tuple)):
        for item in raw_values:
            parsed = _dcl_num(item)
            if parsed is not None:
                values.append(parsed)
    start = _dcl_num(params.get("start_value"))
    end = _dcl_num(params.get("end_value"))
    if start is None and values:
        start = values[0]
    if end is None and len(values) >= 2:
        end = values[-1]
    if start is None:
        start = _dcl_num(params.get("value"), _DCL_DEFAULT_START)
    if start is None:
        start = _DCL_DEFAULT_START
    if end is None:
        end = _DCL_DEFAULT_END
    raw_label = params.get("label")
    if raw_label is None or str(raw_label) == "":
        label = _DCL_DEFAULT_LABEL
    else:
        label = str(raw_label)
    return start, end, label


_DCL_IN_BASE = 0.55


_DCL_OUT_BASE = 0.45


def _dcl_times(duration: float) -> dict[str, float]:
    """Окно decline-chart: IN 0.55 с, OUT 0.45 с, HOLD остаток.

    Короче 1.0 с — IN и OUT сжимаются вместе. HOLD не трогаем.
    """
    d = max(0.05, float(duration))
    min_io = _DCL_IN_BASE + _DCL_OUT_BASE
    s = d / min_io if d < min_io else 1.0
    inn = _DCL_IN_BASE * s
    out = _DCL_OUT_BASE * s
    if inn + out + 0.001 > d:
        s = max(0.001, d - 0.001) / min_io
        inn = _DCL_IN_BASE * s
        out = max(0.001, d - inn - 0.001)
    hold = max(0.0, d - inn - out)
    out_start = inn + hold
    return {
        "in": inn,
        "out": out,
        "hold": hold,
        "out_start": out_start,
        "kill_at": d,
    }


_DCL_PLOT_LEFT = 97


_DCL_PLOT_TOP = 387


_DCL_EP_D = 30


_DCL_VALUE_W = 280


_DCL_LABEL_SIZE = 38


_DCL_PLOT_W = 886


_DCL_PLOT_H = 1379


_DCL_PAD_X = 97


_DCL_PAD_TOP = 173


_DCL_HEADER_H = 118


_DCL_EP_X = 252.0


_DCL_VB_W = 260.0


_DCL_EP_Y = 222.0


_DCL_VB_H = 240.0


def _dcl_clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _dcl_power2_out(t: float) -> float:
    u = 1.0 - _dcl_clamp(t, 0.0, 1.0)
    return 1.0 - u * u


_DCL_ENTER_Y = 48


_DCL_FPS = 30.0


_DCL_GLOOM_PEAK = 0.46


_DCL_EP_AT = 0.94


_DCL_PATH = (
    "M 8 24 C 28 28, 44 43, 61 56 S 93 76, 112 92 "
    "S 144 111, 163 134 S 193 159, 213 186 S 239 211, 252 222")


def dv_decline_chart(ctx: "TemplateCtx") -> Piece:
    """Линия рисуется вниз, число считает вниз, фон темнеет.

    Каталог DEMO 1 твинит ``strokeDashoffset``, ``filter`` и пишет
    ``textContent`` из ``onUpdate``. Здесь SVG-mask с ``scaleX`` на rect,
    gloom ``opacity``, заранее span-ы. Сцена градиент ``var(--color-space-deep)`` /
    ``var(--color-space-deep)`` / ``var(--color-space-deep)``, линия ``var(--color-accent)``, точка ``var(--color-accent-soft)``,
    чернила ``var(--color-text-soft)`` как в каталоге — жест, не палитра канала. Inter.
    ``-apple-system`` не ставим. ``line-rise`` / ``.dv-bar`` /
    ``chart-story`` / ``conic-progress-ring`` / ``mk-line-graph`` не трогаем.
    """
    spec = _dcl_spec(ctx.params)
    if spec is None:
        return Piece()
    start_value, end_value, label = spec
    node_id = f"dcl-{ctx.index:02d}"
    times = _dcl_times(ctx.duration)
    start = ctx.start
    inn = times["in"]
    hold = times["hold"]
    out = times["out"]
    out_start = times["out_start"]
    sid = f"{node_id}-stage"
    gid = f"{node_id}-gloom"
    wid = f"{node_id}-wipe"
    eid = f"{node_id}-ep"
    vid = f"{node_id}-cv"
    mid = f"{node_id}-m"
    ep_cx = _DCL_PLOT_LEFT + (_DCL_EP_X / _DCL_VB_W) * _DCL_PLOT_W
    ep_cy = _DCL_PLOT_TOP + (_DCL_EP_Y / _DCL_VB_H) * _DCL_PLOT_H
    ep_r = _DCL_EP_D / 2.0
    tweens: list[str] = []
    spans: list[str] = []
    texts: list[str] = []
    frames = max(1, int(round(hold * _DCL_FPS))) if hold > 0 else 0
    if frames:
        for frame in range(frames + 1):
            t = frame / frames
            progress = _dcl_power2_out(t)
            value = int(round(start_value + (end_value - start_value) * progress))
            text = str(value)
            texts.append(text)
            spans.append(f'<span id="{vid}-{frame}">{_esc(text)}</span>')
    else:
        texts.append(str(int(round(start_value))))
        spans.append(f'<span id="{vid}-0">{_esc(texts[0])}</span>')
        texts.append(str(int(round(end_value))))
        spans.append(f'<span id="{vid}-1">{_esc(texts[1])}</span>')

    tweens.append(
        f'tl.fromTo("#{sid}",{{opacity:0,y:{_DCL_ENTER_Y}}},'
        f'{{opacity:1,y:0,duration:{_num(inn)},'
        f'ease:"power2.out",immediateRender:false}},{_num(start)});')
    tweens.append(
        f'tl.set("#{wid}",{{scaleX:0}},{_num(start)});')
    tweens.append(
        f'tl.set("#{eid}",{{scale:0.72,opacity:0}},{_num(start)});')
    tweens.append(
        f'tl.set("#{vid}-0",{{opacity:1}},{_num(start)});')

    hold_at = start + inn
    if hold > 0:
        hold_play = hold if hold <= 0.001 else max(0.001, hold - 0.001)
        tweens.append(
            f'tl.fromTo("#{wid}",{{scaleX:0}},'
            f'{{scaleX:1,duration:{_num(hold_play)},'
            f'ease:"power2.out",immediateRender:false}},{_num(hold_at)});')
        tweens.append(
            f'tl.fromTo("#{gid}",{{opacity:0}},'
            f'{{opacity:{_num(_DCL_GLOOM_PEAK)},duration:{_num(hold_play)},'
            f'ease:"power2.out",immediateRender:false}},{_num(hold_at)});')
        prev_shown = 0
        for frame in range(1, frames + 1):
            if texts[frame] == texts[prev_shown]:
                continue
            at = hold_at + hold * (frame / frames)
            tweens.append(
                f'tl.set("#{vid}-{prev_shown}",{{opacity:0}},{_num(at)});')
            tweens.append(
                f'tl.set("#{vid}-{frame}",{{opacity:1}},{_num(at)});')
            prev_shown = frame
        fade_t = 1.0 - math.sqrt(max(0.0, 1.0 - _DCL_EP_AT))
        fade_at = hold_at + hold * fade_t
        fade_dur = max(0.001, start + out_start - fade_at)
        fade_play = fade_dur if fade_dur <= 0.001 else max(0.001, fade_dur - 0.001)
        tweens.append(
            f'tl.fromTo("#{eid}",{{opacity:0,scale:0.72}},'
            f'{{opacity:1,scale:0.72,duration:{_num(fade_play)},'
            f'ease:"power2.out",immediateRender:false}},{_num(fade_at)});')
    else:
        tweens.append(
            f'tl.set("#{wid}",{{scaleX:1}},{_num(hold_at)});')
        tweens.append(
            f'tl.set("#{gid}",{{opacity:{_num(_DCL_GLOOM_PEAK)}}},'
            f'{_num(hold_at)});')
        tweens.append(
            f'tl.set("#{vid}-0",{{opacity:0}},{_num(hold_at)});')
        tweens.append(
            f'tl.set("#{vid}-1",{{opacity:1}},{_num(hold_at)});')

    out_play = out if out <= 0.001 else max(0.001, out - 0.001)
    tweens.append(
        f'tl.fromTo("#{eid}",{{scale:0.72,opacity:1}},'
        f'{{scale:1,opacity:1,duration:{_num(out_play)},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + out_start)});')

    kill_at = start + times["kill_at"]
    tweens.append(
        f'tl.set("#{sid}",{{y:0,opacity:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{gid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{wid}",{{scaleX:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{eid}",{{scale:0.72,opacity:0}},{_num(kill_at)});')
    span_n = frames + 1 if frames else 2
    for frame in range(span_n):
        tweens.append(
            f'tl.set("#{vid}-{frame}",{{opacity:0}},{_num(kill_at)});')

    value_left = 1080 - _DCL_PAD_X - _DCL_VALUE_W
    label_top = _DCL_PAD_TOP + _DCL_HEADER_H - _DCL_LABEL_SIZE
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay dcl-chart" {_timing(ctx)}>'
               f'<div class="dcl-bg"></div>'
               f'<div id="{gid}" class="dcl-gloom"></div>'
               f'<div id="{sid}" class="dcl-stage">'
               f'<div class="dcl-label" data-layout-allow-overlap="" '
               f'style="left:{_DCL_PAD_X}px;top:{label_top}px">'
               f'{_esc(label)}</div>'
               f'<div id="{vid}" class="dcl-cv" data-layout-allow-overlap="" '
               f'style="left:{value_left}px;top:{_DCL_PAD_TOP}px">'
               f'{"".join(spans)}</div>'
               f'<div class="dcl-plot">'
               f'<svg viewBox="0 0 260 240" preserveAspectRatio="none" '
               f'aria-hidden="true">'
               f'<defs><mask id="{mid}" maskUnits="userSpaceOnUse" '
               f'maskContentUnits="userSpaceOnUse">'
               f'<rect id="{wid}" class="dcl-wipe" x="0" y="0" '
               f'width="260" height="240" fill="#FFFFFF"/></mask></defs>'
               f'<line class="dcl-grid" x1="8" y1="55" x2="252" y2="55"></line>'
               f'<line class="dcl-grid" x1="8" y1="120" x2="252" y2="120"></line>'
               f'<line class="dcl-grid" x1="8" y1="185" x2="252" y2="185"></line>'
               f'<path class="dcl-line" mask="url(#{mid})" '
               f'd="{_DCL_PATH}"></path></svg></div>'
               f'<div id="{eid}" class="dcl-ep" data-layout-allow-overlap="" '
               f'style="left:{ep_cx - ep_r:.1f}px;top:{ep_cy - ep_r:.1f}px">'
               f'</div></div></div>'],
        tweens=tweens)


def _mlg_num(raw: Any, default: float | None = None) -> float | None:
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _mlg_floats(raw: Any) -> list[float]:
    values: list[float] = []
    if not isinstance(raw, (list, tuple)):
        return values
    for item in raw:
        parsed = _mlg_num(item.get("value") if isinstance(item, dict) else item)
        if parsed is not None:
            values.append(parsed)
    return values


_MLG_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


_MLG_NAMES = ("Renders", "Projects")


_MLG_ACCENT = "#1A1F2E"


_MLG_BLOB = "#E63946"


_MLG_COLORS = (_MLG_ACCENT, _MLG_BLOB)


def _mlg_color(raw: Any, index: int) -> str:
    text = str(raw or "").strip()
    if text.startswith("#") and len(text) in (4, 7):
        return text
    return _MLG_COLORS[index % len(_MLG_COLORS)]


def _mlg_spec(params: dict[str, Any]
              ) -> tuple[list[tuple[str, list[float], str]], list[str], bool] | None:
    """series (name, values, color), x-labels, showValues. Пусто → None."""
    if not any(k in params and params[k] not in (None, "", [], ())
               for k in ("series", "values", "xLabels", "labels")):
        return None
    series: list[tuple[str, list[float], str]] = []
    raw_series = params.get("series")
    if isinstance(raw_series, (list, tuple)):
        for index, item in enumerate(raw_series):
            if not isinstance(item, dict):
                vals = _mlg_floats([item])
                if len(vals) >= 2:
                    series.append((_MLG_NAMES[index % 2], vals,
                                   _MLG_COLORS[index % 2]))
                continue
            vals = _mlg_floats(item.get("values") or item.get("data"))
            if len(vals) < 2:
                continue
            name = str(item.get("name") or item.get("label")
                       or _MLG_NAMES[index % 2])
            series.append((name, vals, _mlg_color(item.get("color"), index)))
    if not series:
        vals = _mlg_floats(params.get("values"))
        extra = _mlg_floats(params.get("values_b"))
        if len(vals) >= 2:
            name = str(params.get("label") or params.get("name") or _MLG_NAMES[0])
            series.append((name, vals, _mlg_color(params.get("color"), 0)))
        if len(extra) >= 2:
            series.append((_MLG_NAMES[1], extra, _mlg_color(params.get("color_b"), 1)))
    if not series:
        return None
    count = min(len(item[1]) for item in series)
    if count < 2:
        return None
    series = [(name, values[:count], color) for name, values, color in series]
    raw_labels = params.get("xLabels", params.get("labels"))
    labels: list[str] = []
    if isinstance(raw_labels, (list, tuple)):
        labels = [str(item) for item in raw_labels[:count]]
    while len(labels) < count:
        labels.append(_MLG_MONTHS[len(labels) % 12])
    show_values = params.get("showValues")
    if show_values is None:
        show_values = True
    return series, labels, bool(show_values)


_MLG_OUT_DUR = 0.4


_MLG_OUT_LEAD = 0.5


_MLG_CATALOG_DUR = 7.0


_MLG_AXIS_AT = 0.2


_MLG_XL_AT = 0.25


_MLG_XL_STAGGER = 0.05


_MLG_SERIES0_AT = 0.5


_MLG_SERIES_STAGGER = 0.35


_MLG_VAL_DELAY = 0.06


_MLG_LEGEND_AT = 2.3


_MLG_AXIS_DUR = 0.5


_MLG_XL_DUR = 0.4


_MLG_DRAW = 1.3


_MLG_DOT_DUR = 0.35


_MLG_VAL_DUR = 0.35


_MLG_LEGEND_DUR = 0.5


def _mlg_times(duration: float) -> dict[str, float]:
    """Окно mk-line-graph: каталог 7 с, короче — те же доли."""
    d = max(0.05, float(duration))
    s = d / _MLG_CATALOG_DUR if d < _MLG_CATALOG_DUR else 1.0
    out_dur = _MLG_OUT_DUR * s
    out_lead = _MLG_OUT_LEAD * s
    out_start = max(0.0, d - out_lead)
    if out_start + out_dur + 0.001 > d:
        out_dur = max(0.001, d - out_start - 0.001)
    return {
        "scale": s,
        "axis_at": _MLG_AXIS_AT * s,
        "axis_dur": max(0.001, _MLG_AXIS_DUR * s),
        "xl_at": _MLG_XL_AT * s,
        "xl_stagger": _MLG_XL_STAGGER * s,
        "xl_dur": max(0.001, _MLG_XL_DUR * s),
        "series0_at": _MLG_SERIES0_AT * s,
        "series_stagger": _MLG_SERIES_STAGGER * s,
        "draw": max(0.001, _MLG_DRAW * s),
        "dot_dur": max(0.05, _MLG_DOT_DUR * s),
        "val_delay": _MLG_VAL_DELAY * s,
        "val_dur": max(0.05, _MLG_VAL_DUR * s),
        "legend_at": _MLG_LEGEND_AT * s,
        "legend_dur": max(0.001, _MLG_LEGEND_DUR * s),
        "out_start": out_start,
        "out_dur": out_dur,
        "kill_at": d,
    }


_MLG_PLOT_TOP = 427


_MLG_PLOT_H = 889


_MLG_PLOT_LEFT = 90


_MLG_MASK_PAD_X = 6


_MLG_MASK_PAD_Y = 20


_MLG_PLOT_W = 740


_MLG_OUT_Y = -36


_MLG_AXIS_PAD = 15


_MLG_XL_Y = 18


_MLG_VAL_Y = 14


_MLG_GAP = 28


_MLG_VAL_H = 46


_MLG_XL_BELOW = 36


def _mlg_play(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


_MLG_XL_W = 100


_MLG_LEGEND_BELOW = 90


_MLG_DOT = 22


_MLG_VAL_W = 100


def _mlg_token(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


def dv_mk_line_graph(ctx: "TemplateCtx") -> Piece:
    """Две линии рисуются слева направо, точки и числа садятся на фронт.

    Каталог DEMO 1 твинит ``strokeDashoffset`` и ``scale`` кругов. Здесь
    SVG-mask с ``scaleX`` на rect и HTML-точки. Бумага ``var(--color-bg-pure)``, чернила
    ``var(--color-ink)``, акцент ``var(--color-panel)``, вторая серия ``var(--color-accent)`` как в каталоге
    — жест MK, не палитра канала. Inter. ``-apple-system`` не ставим.
    ``line-rise`` / ``.dv-bar`` / ``decline-chart`` / ``chart-story`` не
    трогаем.
    """
    spec = _mlg_spec(ctx.params)
    if spec is None:
        return Piece()
    series, xlabels, show_values = spec
    node_id = f"mlg-{ctx.index:02d}"
    times = _mlg_times(ctx.duration)
    start = ctx.start
    sid = f"{node_id}-stage"
    aid = f"{node_id}-axis"
    lid = f"{node_id}-leg"
    count = len(series[0][1])
    peak = max(value for _name, values, _color in series for value in values)
    peak = peak * 1.15 if peak > 0 else 1.0
    plot_bottom = _MLG_PLOT_TOP + _MLG_PLOT_H

    def px(index: int) -> float:
        return _MLG_PLOT_LEFT + (index / (count - 1)) * _MLG_PLOT_W

    def py(value: float) -> float:
        return _MLG_PLOT_TOP + _MLG_PLOT_H - (value / peak) * _MLG_PLOT_H

    tweens: list[str] = []
    defs: list[str] = []
    paths: list[str] = []
    dots: list[str] = []
    values_html: list[str] = []
    xl_html: list[str] = []
    legend_html: list[str] = []
    wipe_ids: list[str] = []
    dot_ids: list[str] = []
    val_ids: list[str] = []
    xl_ids: list[str] = []

    mask_x = _MLG_PLOT_LEFT - _MLG_MASK_PAD_X
    mask_y = _MLG_PLOT_TOP - _MLG_MASK_PAD_Y
    mask_w = _MLG_PLOT_W + _MLG_MASK_PAD_X * 2
    mask_h = _MLG_PLOT_H + _MLG_MASK_PAD_Y * 2

    for si, (name, values, color) in enumerate(series):
        parts = []
        for index, value in enumerate(values):
            cmd = "M" if index == 0 else "L"
            parts.append(f"{cmd}{_num(px(index))} {_num(py(value))}")
        d_attr = " ".join(parts)
        mid = f"{node_id}-m{si}"
        wid = f"{node_id}-w{si}"
        pid = f"{node_id}-p{si}"
        wipe_ids.append(wid)
        defs.append(
            f'<mask id="{mid}" maskUnits="userSpaceOnUse" '
            f'maskContentUnits="userSpaceOnUse">'
            f'<rect id="{wid}" class="mlg-wipe" x="{_num(mask_x)}" '
            f'y="{_num(mask_y)}" width="{_num(mask_w)}" '
            f'height="{_num(mask_h)}" fill="#FFFFFF"/></mask>')
        paths.append(
            f'<path id="{pid}" class="mlg-line" mask="url(#{mid})" '
            f'd="{d_attr}" stroke="{_esc(color)}"></path>')
        below = si > 0
        legend_html.append(
            f'<div class="mlg-legend-item">'
            f'<span class="mlg-legend-dot" style="background:{_esc(color)}">'
            f'</span>{_esc(name)}</div>')
        for index, value in enumerate(values):
            x = px(index)
            y = py(value)
            did = f"{node_id}-d{si}-{index}"
            dot_ids.append(did)
            dots.append(
                f'<div id="{did}" class="mlg-dot" data-layout-allow-overlap="" '
                f'style="left:{x - _MLG_DOT / 2:.1f}px;'
                f'top:{y - _MLG_DOT / 2:.1f}px;border-color:{_esc(color)}">'
                f'</div>')
            if show_values:
                vid = f"{node_id}-v{si}-{index}"
                val_ids.append(vid)
                top = y + _MLG_GAP if below else y - _MLG_GAP - _MLG_VAL_H
                values_html.append(
                    f'<div id="{vid}" class="mlg-val" '
                    f'data-layout-allow-overlap="" '
                    f'style="left:{x - _MLG_VAL_W / 2:.1f}px;top:{top:.1f}px">'
                    f'{_esc(_mlg_token(value))}</div>')

    for index, label in enumerate(xlabels):
        xid = f"{node_id}-x{index}"
        xl_ids.append(xid)
        xl_html.append(
            f'<div id="{xid}" class="mlg-xl" data-layout-allow-overlap="" '
            f'style="left:{px(index) - _MLG_XL_W / 2:.1f}px;'
            f'top:{plot_bottom + _MLG_XL_BELOW:.1f}px">{_esc(label)}</div>')

    axis_y = plot_bottom
    axis = (
        f'<line id="{aid}" class="mlg-axis" '
        f'x1="{_num(_MLG_PLOT_LEFT - _MLG_AXIS_PAD)}" y1="{_num(axis_y)}" '
        f'x2="{_num(_MLG_PLOT_LEFT + _MLG_PLOT_W + _MLG_AXIS_PAD)}" '
        f'y2="{_num(axis_y)}"></line>')

    tweens.append(
        f'tl.fromTo("#{aid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_mlg_play(times["axis_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["axis_at"])});')
    for index, xid in enumerate(xl_ids):
        tweens.append(
            f'tl.fromTo("#{xid}",{{opacity:0,y:{_MLG_XL_Y}}},'
            f'{{opacity:1,y:0,duration:{_num(_mlg_play(times["xl_dur"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + times["xl_at"] + index * times["xl_stagger"])});')
    for wid in wipe_ids:
        tweens.append(
            f'tl.set("#{wid}",{{scaleX:0}},{_num(start)});')
    for did in dot_ids:
        tweens.append(
            f'tl.set("#{did}",{{scale:0}},{_num(start)});')
    for si, (_name, values, _color) in enumerate(series):
        t0 = times["series0_at"] + si * times["series_stagger"]
        wid = wipe_ids[si]
        tweens.append(
            f'tl.fromTo("#{wid}",{{scaleX:0}},'
            f'{{scaleX:1,duration:{_num(_mlg_play(times["draw"]))},'
            f'ease:"power2.inOut",immediateRender:false}},'
            f'{_num(start + t0)});')
        span = times["draw"] * 0.92
        for index in range(count):
            td = t0 + (index / (count - 1)) * span
            did = f"{node_id}-d{si}-{index}"
            tweens.append(
                f'tl.fromTo("#{did}",{{scale:0}},'
                f'{{scale:1,duration:{_num(_mlg_play(times["dot_dur"]))},'
                f'ease:"back.out(1.2)",immediateRender:false}},'
                f'{_num(start + td)});')
            if show_values:
                vid = f"{node_id}-v{si}-{index}"
                tweens.append(
                    f'tl.fromTo("#{vid}",{{opacity:0,y:{_MLG_VAL_Y}}},'
                    f'{{opacity:1,y:0,duration:{_num(_mlg_play(times["val_dur"]))},'
                    f'ease:"power2.out",immediateRender:false}},'
                    f'{_num(start + td + times["val_delay"])});')
    tweens.append(
        f'tl.fromTo("#{lid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_mlg_play(times["legend_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["legend_at"])});')
    tweens.append(
        f'tl.fromTo("#{sid}",{{opacity:1,y:0}},'
        f'{{opacity:0,y:{_MLG_OUT_Y},duration:{_num(_mlg_play(times["out_dur"]))},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["out_start"])});')

    kill_at = start + times["kill_at"]
    tweens.append(
        f'tl.set("#{sid}",{{y:0,opacity:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{aid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{lid}",{{opacity:0}},{_num(kill_at)});')
    for wid in wipe_ids:
        tweens.append(
            f'tl.set("#{wid}",{{scaleX:0}},{_num(kill_at)});')
    for did in dot_ids:
        tweens.append(
            f'tl.set("#{did}",{{scale:0}},{_num(kill_at)});')
    for vid in val_ids:
        tweens.append(
            f'tl.set("#{vid}",{{opacity:0,y:{_MLG_VAL_Y}}},{_num(kill_at)});')
    for xid in xl_ids:
        tweens.append(
            f'tl.set("#{xid}",{{opacity:0,y:{_MLG_XL_Y}}},{_num(kill_at)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay mlg-chart" {_timing(ctx)}>'
               f'<div class="mlg-bg"></div>'
               f'<div id="{sid}" class="mlg-stage">'
               f'<svg class="mlg-svg" viewBox="0 0 1080 1920" '
               f'preserveAspectRatio="none" aria-hidden="true">'
               f'<defs>{"".join(defs)}</defs>{axis}{"".join(paths)}</svg>'
               f'{"".join(dots)}{"".join(values_html)}{"".join(xl_html)}'
               f'<div id="{lid}" class="mlg-legend" data-layout-allow-overlap="" '
               f'style="left:{_MLG_PLOT_LEFT}px;'
               f'top:{plot_bottom + _MLG_LEGEND_BELOW}px">'
               f'{"".join(legend_html)}</div></div></div>'],
        tweens=tweens)


def _srf_num(raw: Any, default: float | None = None) -> float | None:
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


_SRF_DEFAULT_RATING = 4.8


def _srf_clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


_SRF_DEFAULT_COUNT = 5


def _srf_spec(params: dict[str, Any]) -> tuple[float, int, bool] | None:
    """rating, star_count, show_value. Пусто → None."""
    keys = ("rating", "starCount", "star_count", "stars",
            "showValue", "show_value", "value")
    if not any(k in params and params[k] not in (None, "", [], ())
               for k in keys):
        return None
    rating = _srf_num(params.get("rating"))
    if rating is None:
        rating = _srf_num(params.get("value"), _SRF_DEFAULT_RATING)
    if rating is None:
        rating = _SRF_DEFAULT_RATING
    count = _srf_num(params.get("starCount"))
    if count is None:
        count = _srf_num(params.get("star_count"))
    if count is None:
        count = _srf_num(params.get("stars"), float(_SRF_DEFAULT_COUNT))
    if count is None:
        count = float(_SRF_DEFAULT_COUNT)
    star_count = int(round(count))
    star_count = max(1, min(10, star_count))
    rating = _srf_clamp(rating, 0.0, 5.0)
    rating = min(rating, float(star_count))
    raw_show = params.get("showValue", params.get("show_value", "yes"))
    if isinstance(raw_show, bool):
        show_value = raw_show
    else:
        show_value = str(raw_show).strip().lower() not in ("no", "false", "0")
    return rating, star_count, show_value


_SRF_IN_BASE = 1.5


_SRF_OUT_BASE = 0.4


_SRF_FILL_START_BASE = 0.2


_SRF_FILL_DURATION_BASE = 1.1


_SRF_POP_DURATION_BASE = 0.2


def _srf_times(duration: float) -> dict[str, float]:
    """Окно star-rating-fill: IN 1.50 с, OUT 0.40 с, HOLD остаток.

    Короче 1.90 с — IN и OUT сжимаются вместе. HOLD не трогаем.
    """
    d = max(0.05, float(duration))
    min_io = _SRF_IN_BASE + _SRF_OUT_BASE
    s = d / min_io if d < min_io else 1.0
    inn = _SRF_IN_BASE * s
    out = _SRF_OUT_BASE * s
    if inn + out + 0.001 > d:
        s = max(0.001, d - 0.001) / min_io
        inn = _SRF_IN_BASE * s
        out = max(0.001, d - inn - 0.001)
    hold = max(0.0, d - inn - out)
    out_start = inn + hold
    return {
        "in": inn,
        "out": out,
        "hold": hold,
        "out_start": out_start,
        "kill_at": d,
        "fill_start": _SRF_FILL_START_BASE * s,
        "fill_dur": max(0.001, _SRF_FILL_DURATION_BASE * s),
        "pop_dur": max(0.05, _SRF_POP_DURATION_BASE * s),
    }


_SRF_VALUE_W = 210.0


_SRF_GAP = 28.0


_SRF_STAR_MAX = 148.0


_SRF_CARD_LEFT = 40


_SRF_CARD_TOP = 750


_SRF_CARD_W = 1000


_SRF_CARD_H = 420


_SRF_VALUE_SIZE = 92.0


_SRF_PAD = 32.0


_SRF_FPS = 30.0


_SRF_PATH = (
    "M50 0 61.8 36.2 100 36.2 69.1 58.6 80.9 95 50 72.4 "
    "19.1 95 30.9 58.6 0 36.2 38.2 36.2Z"
)


_SRF_MUTED = "#7A7D82"


_SRF_BRAND = "#E63946"


def _srf_play(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


def _srf_power2_out(t: float) -> float:
    u = 1.0 - _srf_clamp(t, 0.0, 1.0)
    return 1.0 - u * u


def dv_star_rating_fill(ctx: "TemplateCtx") -> Piece:
    """Золотые звёзды заливаются слева направо, число считает в такт.

    Каталог DEMO 1 твинит ``clip-path`` на слое заливки и пишет
    ``textContent`` из ``onUpdate``. Здесь SVG-mask с ``scaleX`` на rect,
    попа ``scale`` 1→1.06→1, заранее span-ы. Сцена ``var(--color-space-deep)``, карточка
    ``var(--color-space-deep)``, бренд ``var(--color-accent)``, чернила ``var(--color-text-soft)`` как в каталоге —
    жест рейтинга, не палитра канала. Inter. ``-apple-system`` не ставим.
    ``donut-fill`` / ``.dv-bar`` / ``conic-progress-ring`` / ``spain-map`` /
    ``us-map`` не трогаем.
    """
    spec = _srf_spec(ctx.params)
    if spec is None:
        return Piece()
    rating, star_count, show_value = spec
    node_id = f"srf-{ctx.index:02d}"
    times = _srf_times(ctx.duration)
    start = ctx.start
    sid = f"{node_id}-stage"
    wid = f"{node_id}-wipe"
    mid = f"{node_id}-m"
    vid = f"{node_id}-cv"
    fill_ratio = rating / float(star_count) if star_count else 0.0
    show_w = _SRF_VALUE_W if show_value else 0.0
    gap = _SRF_GAP if show_value else 0.0
    avail = _SRF_CARD_W - _SRF_PAD * 2.0 - show_w - gap
    star = min(_SRF_STAR_MAX, avail / float(star_count))
    stars_w = star * star_count
    row_w = stars_w + gap + show_w
    row_left = _SRF_CARD_LEFT + (_SRF_CARD_W - row_w) / 2.0
    stars_top = _SRF_CARD_TOP + (_SRF_CARD_H - star) / 2.0
    value_top = stars_top + (star - _SRF_VALUE_SIZE) / 2.0
    value_left = row_left + stars_w + gap
    scale = star / 100.0
    fill_start = times["fill_start"]
    fill_dur = times["fill_dur"]
    pop_dur = times["pop_dur"]
    frames = max(1, int(round(fill_dur * _SRF_FPS)))
    tweens: list[str] = []
    base_html: list[str] = []
    fill_html: list[str] = []
    base_ids: list[str] = []
    fill_ids: list[str] = []
    spans: list[str] = []
    texts: list[str] = []

    for index in range(star_count):
        bid = f"{node_id}-b{index}"
        fid = f"{node_id}-f{index}"
        base_ids.append(bid)
        fill_ids.append(fid)
        left = index * star
        base_html.append(
            f'<svg id="{bid}" class="srf-cell" data-layout-allow-overlap="" '
            f'style="left:{left:.1f}px;width:{star:.1f}px;height:{star:.1f}px" '
            f'viewBox="0 0 100 100" aria-hidden="true">'
            f'<path d="{_SRF_PATH}" fill="{_SRF_MUTED}"></path></svg>')
        fill_html.append(
            f'<g id="{fid}" class="srf-fill-star">'
            f'<g transform="translate({_num(left)} 0) scale({_num(scale)})">'
            f'<path d="{_SRF_PATH}" fill="{_SRF_BRAND}"></path></g></g>')

    if show_value:
        for frame in range(frames + 1):
            if frame == frames:
                text = f"{rating:.1f}"
            else:
                t = frame / frames
                text = f"{rating * _srf_power2_out(t):.1f}"
            texts.append(text)
            spans.append(f'<span id="{vid}-{frame}">{_esc(text)}</span>')

    tweens.append(f'tl.set("#{wid}",{{scaleX:0}},{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{wid}",{{scaleX:0}},'
        f'{{scaleX:{_num(fill_ratio)},duration:{_num(_srf_play(fill_dur))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + fill_start)});')

    if show_value:
        tweens.append(
            f'tl.set("#{vid}-0",{{opacity:1}},{_num(start)});')
        prev_shown = 0
        for frame in range(1, frames + 1):
            if texts[frame] == texts[prev_shown]:
                continue
            at = start + fill_start + fill_dur * (frame / frames)
            tweens.append(
                f'tl.set("#{vid}-{prev_shown}",{{opacity:0}},{_num(at)});')
            tweens.append(
                f'tl.set("#{vid}-{frame}",{{opacity:1}},{_num(at)});')
            prev_shown = frame

    pop_count = math.ceil(rating)
    denom = max(1.0, rating)
    pop_up = pop_dur * 0.45
    pop_down = pop_dur * 0.55
    for pop_index in range(pop_count):
        if pop_index >= star_count:
            break
        pop_at = fill_start + fill_dur * (pop_index / denom) * 0.82
        for tid in (base_ids[pop_index], fill_ids[pop_index]):
            tweens.append(
                f'tl.fromTo("#{tid}",{{scale:1}},'
                f'{{scale:1.06,duration:{_num(_srf_play(pop_up))},'
                f'ease:"power2.out",immediateRender:false}},'
                f'{_num(start + pop_at)});')
            tweens.append(
                f'tl.fromTo("#{tid}",{{scale:1.06}},'
                f'{{scale:1,duration:{_num(_srf_play(pop_down))},'
                f'ease:"power2.out",immediateRender:false}},'
                f'{_num(start + pop_at + pop_up)});')

    tweens.append(
        f'tl.fromTo("#{sid}",{{opacity:1}},'
        f'{{opacity:0,duration:{_num(_srf_play(times["out"]))},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["out_start"])});')

    kill_at = start + times["kill_at"]
    tweens.append(f'tl.set("#{sid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{wid}",{{scaleX:0}},{_num(kill_at)});')
    for bid in base_ids:
        tweens.append(f'tl.set("#{bid}",{{scale:1}},{_num(kill_at)});')
    for fid in fill_ids:
        tweens.append(f'tl.set("#{fid}",{{scale:1}},{_num(kill_at)});')
    if show_value:
        for frame in range(frames + 1):
            tweens.append(
                f'tl.set("#{vid}-{frame}",{{opacity:0}},{_num(kill_at)});')

    value_html = ""
    if show_value:
        value_html = (
            f'<div id="{vid}" class="srf-cv" data-layout-allow-overlap="" '
            f'style="left:{value_left:.1f}px;top:{value_top:.1f}px;'
            f'width:{_SRF_VALUE_W:.1f}px;height:{_SRF_VALUE_SIZE:.1f}px;'
            f'font-size:{_SRF_VALUE_SIZE:.1f}px">'
            f'{"".join(spans)}</div>')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay srf-chart" {_timing(ctx)}>'
               f'<div class="srf-bg"></div>'
               f'<div id="{sid}" class="srf-stage">'
               f'<div class="srf-card" data-layout-allow-overlap=""></div>'
               f'<div class="srf-stars" data-layout-allow-overlap="" '
               f'style="left:{row_left:.1f}px;top:{stars_top:.1f}px;'
               f'width:{stars_w:.1f}px;height:{star:.1f}px">'
               f'{"".join(base_html)}'
               f'<svg class="srf-fill-svg" viewBox="0 0 {_num(stars_w)} {_num(star)}" '
               f'width="{_num(stars_w)}" height="{_num(star)}" '
               f'preserveAspectRatio="none" aria-hidden="true">'
               f'<defs><mask id="{mid}" maskUnits="userSpaceOnUse" '
               f'maskContentUnits="userSpaceOnUse">'
               f'<rect id="{wid}" class="srf-wipe" x="0" y="0" '
               f'width="{_num(stars_w)}" height="{_num(star)}" '
               f'fill="#FFFFFF"/></mask></defs>'
               f'<g mask="url(#{mid})">{"".join(fill_html)}</g></svg></div>'
               f'{value_html}</div></div>'],
        tweens=tweens)


def _wmp_num(raw: Any, fallback: float | None) -> float | None:
    if raw is None or raw == "":
        return fallback
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def _wmp_spec(params: dict[str, Any]
              ) -> tuple[list[tuple[dict[str, Any], float | None]], str, str,
                         str, list[str]] | None:
    if not any(k in params and params[k] not in (None, "", [], ())
               for k in ("regions", "countries", "values", "labels", "title",
                         "headline", "subtitle")):
        return None
    by_code = {str(item["code"]): item for item in WMP_SHAPES}
    by_name = {str(item["name"]).lower(): item for item in WMP_SHAPES}
    overrides: dict[str, float] = {}
    raw = params.get("regions", params.get("countries"))
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or item.get("id") or "").zfill(3)
            shape = by_code.get(code)
            if shape is None:
                name = str(item.get("name") or "").lower()
                shape = by_name.get(name)
            if shape is None:
                continue
            value = _wmp_num(item.get("value", item.get("gdp")),
                             float(shape["gdp"]) if shape["gdp"] is not None
                             else None)
            if value is not None:
                overrides[str(shape["code"])] = value
    items: list[tuple[dict[str, Any], float | None]] = []
    for shape in WMP_SHAPES:
        code = str(shape["code"])
        if code in overrides:
            items.append((shape, overrides[code]))
        elif shape["gdp"] is not None:
            items.append((shape, float(shape["gdp"])))
        else:
            items.append((shape, None))
    title = str(params.get("title") or params.get("headline") or WMP_TITLE)
    subtitle = str(params.get("subtitle") or WMP_SUBTITLE)
    source = str(params.get("source") or WMP_SOURCE)
    raw_hi = params.get("highlight") or params.get("highlights")
    highlights: list[str] = []
    if isinstance(raw_hi, (list, tuple)):
        highlights = [str(item).zfill(3) for item in raw_hi if str(item).strip()]
    if not highlights:
        highlights = list(WMP_TOP5)
    return items, title, subtitle, source, highlights


_WMP_CATALOG_DUR = 14.0


_WMP_SUB_AT = 0.4


_WMP_REG_AT = 1.0


_WMP_REG_STAGGER = 0.02


_WMP_LEG_AT = 4.0


_WMP_SRC_AT = 4.5


_WMP_HI_AT = 5.0


_WMP_HI_GAP = 0.15


_WMP_HL_DUR = 1.0


_WMP_SUB_DUR = 0.6


_WMP_REG_DUR = 0.3


_WMP_LEG_DUR = 0.6


_WMP_SRC_DUR = 0.5


_WMP_HI_DUR = 0.4


_WMP_HI_BACK = 0.6


def _wmp_times(duration: float) -> dict[str, float]:
    """Window world-map: catalog 14 s, shorter — same ratios."""
    d = max(0.05, float(duration))
    s = d / _WMP_CATALOG_DUR if d < _WMP_CATALOG_DUR else 1.0
    return {
        "scale": s,
        "hl_dur": max(0.001, _WMP_HL_DUR * s),
        "sub_at": _WMP_SUB_AT * s,
        "sub_dur": max(0.001, _WMP_SUB_DUR * s),
        "reg_at": _WMP_REG_AT * s,
        "reg_dur": max(0.001, _WMP_REG_DUR * s),
        "reg_stagger": _WMP_REG_STAGGER * s,
        "leg_at": _WMP_LEG_AT * s,
        "leg_dur": max(0.001, _WMP_LEG_DUR * s),
        "src_at": _WMP_SRC_AT * s,
        "src_dur": max(0.001, _WMP_SRC_DUR * s),
        "hi_at": _WMP_HI_AT * s,
        "hi_dur": max(0.001, _WMP_HI_DUR * s),
        "hi_back": max(0.001, _WMP_HI_BACK * s),
        "hi_gap": _WMP_HI_GAP * s,
        "out_start": max(0.001, d - 0.8),
        "out_dur": max(0.001, 0.6 * s),
        "kill_at": max(0.001, d - 0.05),
    }


_WMP_DEFAULT = "#0B132B"


def _usm_lerp_hex(start: str, end: str, t: float) -> str:
    def rgb(token: str) -> tuple[int, int, int]:
        h = token.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    ar, ag, ab = rgb(start)
    br, bg, bb = rgb(end)
    t = min(max(t, 0.0), 1.0)
    return (f"#{round(ar + (br - ar) * t):02x}"
            f"{round(ag + (bg - ag) * t):02x}"
            f"{round(ab + (bb - ab) * t):02x}")


_WMP_STOPS = ("#9F1A24", "#9F1A24", "#E63946", "#ED747D")


def _wmp_color(value: float, lo: float, hi: float) -> str:
    span = hi - lo if hi > lo else 1.0
    t = min(max((value - lo) / span, 0.0), 1.0)
    scaled = t * (len(_WMP_STOPS) - 1)
    idx = min(int(scaled), len(_WMP_STOPS) - 2)
    return _usm_lerp_hex(_WMP_STOPS[idx], _WMP_STOPS[idx + 1], scaled - idx)


_WMP_OUT_Y = 60


def _wmp_play(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


def dv_world_map(ctx: "TemplateCtx") -> Piece:
    """World choropleth: countries fade from center, top-5 pulse.

    Catalog DEMO 1 fetches world-atlas topojson and tweens ``clipPath`` /
    ``filter:brightness``. Here paths are pre-baked Natural Earth,
    wipe is ``scaleX``, highlights use white overlay ``opacity``.
    Gradient ``var(--color-space-deep)``/``var(--color-space-deep)``, scale ``var(--color-accent-deep)``→``var(--color-accent-deep)``→
    ``var(--color-accent)``→``var(--color-accent-soft)``. Inter.
    """
    spec = _wmp_spec(ctx.params)
    if spec is None:
        return Piece()
    items, title, subtitle, source, highlights = spec
    numbered = [value for _shape, value in items if value is not None]
    lo = min(numbered) if numbered else 0.0
    hi = max(numbered) if numbered else 1.0
    node_id = f"wmp-{ctx.index:02d}"
    times = _wmp_times(ctx.duration)
    start = ctx.start
    sid = f"{node_id}-stage"
    wid = f"{node_id}-wipe"
    uid = f"{node_id}-sub"
    lid = f"{node_id}-leg"
    xid = f"{node_id}-src"
    tweens: list[str] = []
    paths: list[str] = []
    region_ids: list[str] = []
    hi_ids: list[str] = []
    hi_targets: dict[str, str] = {}
    vb_x, vb_y, vb_w, vb_h = WMP_VB

    for index, (shape, value) in enumerate(items):
        code = str(shape["code"])
        color = (_wmp_color(value, lo, hi) if value is not None
                 else _WMP_DEFAULT)
        rid = f"{node_id}-r{index}"
        region_ids.append(rid)
        paths.append(
            f'<path id="{rid}" class="wmp-region" '
            f'd="{_esc(shape["d"])}" fill="{_esc(color)}"></path>')
        if code in highlights:
            hid_r = f"{node_id}-h{index}"
            hi_ids.append(hid_r)
            hi_targets[code] = hid_r
            paths.append(
                f'<path id="{hid_r}" class="wmp-hi" '
                f'd="{_esc(shape["d"])}" fill="#C7C9D1"></path>')
        delay = index * times["reg_stagger"]
        tweens.append(
            f'tl.fromTo("#{rid}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(_wmp_play(times["reg_dur"]))},'
            f'ease:"power1.out",immediateRender:false}},'
            f'{_num(start + times["reg_at"] + delay)});')

    tweens.insert(0,
        f'tl.fromTo("#{wid}",{{scaleX:1}},'
        f'{{scaleX:0,duration:{_num(_wmp_play(times["hl_dur"]))},'
        f'ease:"power3.inOut",immediateRender:false}},'
        f'{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{uid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_wmp_play(times["sub_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["sub_at"])});')
    tweens.append(
        f'tl.fromTo("#{lid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_wmp_play(times["leg_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["leg_at"])});')
    tweens.append(
        f'tl.fromTo("#{xid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_wmp_play(times["src_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["src_at"])});')

    for hi_i, code in enumerate(highlights):
        hid_r = hi_targets.get(code)
        if not hid_r:
            continue
        t0 = times["hi_at"] + hi_i * times["hi_gap"]
        tweens.append(
            f'tl.fromTo("#{hid_r}",{{opacity:0}},'
            f'{{opacity:0.4,duration:{_num(_wmp_play(times["hi_dur"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + t0)});')
        tweens.append(
            f'tl.fromTo("#{hid_r}",{{opacity:0.4}},'
            f'{{opacity:0,duration:{_num(_wmp_play(times["hi_back"]))},'
            f'ease:"power2.inOut",immediateRender:false}},'
            f'{_num(start + t0 + times["hi_dur"])});')

    tweens.append(
        f'tl.fromTo("#{sid}",{{opacity:1,y:0}},'
        f'{{opacity:0,y:{_WMP_OUT_Y},duration:{_num(_wmp_play(times["out_dur"]))},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["out_start"])});')

    kill_at = start + times["kill_at"]
    tweens.append(f'tl.set("#{sid}",{{y:0,opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{wid}",{{scaleX:1}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{uid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{lid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{xid}",{{opacity:0}},{_num(kill_at)});')
    for rid in region_ids:
        tweens.append(f'tl.set("#{rid}",{{opacity:0}},{_num(kill_at)});')
    for hid_r in hi_ids:
        tweens.append(f'tl.set("#{hid_r}",{{opacity:0}},{_num(kill_at)});')

    view = f"{_num(vb_x)} {_num(vb_y)} {_num(vb_w)} {_num(vb_h)}"
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay wmp-chart" {_timing(ctx)}>'
               f'<div class="wmp-bg"></div>'
               f'<div id="{sid}" class="wmp-stage">'
               f'<div class="wmp-hl-clip" data-layout-allow-overlap="">'
               f'<div class="wmp-hl">{_esc(title)}</div>'
               f'<div id="{wid}" class="wmp-wipe"></div></div>'
               f'<div id="{uid}" class="wmp-sub" data-layout-allow-overlap="">'
               f'{_esc(subtitle)}</div>'
               f'<svg class="wmp-svg" viewBox="{view}" '
               f'preserveAspectRatio="xMidYMid meet" aria-hidden="true">'
               f'<path class="wmp-grat" d="{_esc(WMP_GRATICULE)}"></path>'
               f'{"".join(paths)}</svg>'
               f'<div id="{lid}" class="wmp-legend" data-layout-allow-overlap="">'
               f'<div class="wmp-legend-bar"></div>'
               f'<div class="wmp-legend-labs">'
               f'<span>Low</span><span>High</span></div></div>'
               f'<div id="{xid}" class="wmp-src" data-layout-allow-overlap="">'
               f'{_esc(source)}</div></div></div>'],
        tweens=tweens)


_ATCD_DEFAULT_CMD = "npm audit"


_ATCD_DEFAULT_PROMPT = "user@Mac ~ % "


_ATCD_DEFAULT_TITLE = "bash — 80×24"


_ATCD_OUTPUT: tuple[tuple[str, str], ...] = (
    ("Last login: Mon Jun 2 09:14:22 on ttys002", "dim"),
    ("Scanning dependencies...", ""),
    ("Found 3 vulnerabilities (1 moderate, 2 low)", ""),
    (" package: lodash@4.17.20", "dim"),
    (" severity: moderate", "dim"),
    (" fix: lodash@4.17.21", "dim"),
    (" package: minimist@1.2.5", "dim"),
    (" severity: low", "dim"),
    (" fix: minimist@1.2.6", "dim"),
    ("Run `npm audit fix` to fix them.", "bold"),
)


def _atcd_session(params: dict[str, Any], code: str
                  ) -> tuple[str, str, str, list[tuple[str, str]]]:
    command = str(params.get("command") or "").strip()
    prompt = str(params.get("prompt") or _ATCD_DEFAULT_PROMPT)
    title = str(params.get("title") or _ATCD_DEFAULT_TITLE)
    raw_out = params.get("output") if "output" in params else params.get("lines")
    rows: list[str] = []
    if isinstance(raw_out, str):
        rows = raw_out.replace("\r\n", "\n").split("\n")
    elif isinstance(raw_out, (list, tuple)):
        rows = [str(item) for item in raw_out]
    if not command:
        text = code.strip()
        if text:
            parts = text.replace("\r\n", "\n").split("\n")
            first = parts[0].strip()
            if first.startswith("$"):
                first = first[1:].strip()
            command = first
            if not rows:
                rows = parts[1:]
    if not command:
        command = _ATCD_DEFAULT_CMD
    if not any(line.strip() for line in rows):
        return command, prompt, title, [tuple(item) for item in _ATCD_OUTPUT]
    styled: list[tuple[str, str]] = []
    for line in rows:
        kind = ""
        if line.startswith(" "):
            kind = "dim"
        if line.startswith("Run ") or line.startswith("error:") or line.startswith("fatal:"):
            kind = "bold"
        styled.append((line, kind))
    return command, prompt, title, styled


_ATCD_SIZE_CEILING = 22


_ATCD_TITLE_H = 42


_ATCD_PAD_Y = 18


_ATCD_SIZE_FLOOR = 16


_ATCD_LH_EM = 1.60


_ATCD_RADIUS = 10


def _atcd_metrics(n_out: int, frame_w: int, frame_h: int) -> dict[str, int]:
    window_w = min(int(round(frame_w * 0.90)), 980)
    max_h = int(round(frame_h * 0.62))
    size = _ATCD_SIZE_CEILING
    rows = max(3, int(n_out) + 2)
    lh = max(22, int(round(size * _ATCD_LH_EM)))
    canvas_h = rows * lh + _ATCD_PAD_Y * 2
    window_h = _ATCD_TITLE_H + canvas_h
    while window_h > max_h and size > _ATCD_SIZE_FLOOR:
        size -= 1
        lh = max(22, int(round(size * _ATCD_LH_EM)))
        canvas_h = rows * lh + _ATCD_PAD_Y * 2
        window_h = _ATCD_TITLE_H + canvas_h
    if window_h > max_h:
        canvas_h = max(120, max_h - _ATCD_TITLE_H)
        window_h = _ATCD_TITLE_H + canvas_h
    caret_w = max(6, int(round(size * 9 / 14)))
    caret_h = max(12, int(round(size * 16 / 14)))
    return {
        "window_w": window_w,
        "window_h": window_h,
        "canvas_h": canvas_h,
        "size": size,
        "lh": lh,
        "caret_w": caret_w,
        "caret_h": caret_h,
        "radius": max(8, int(round(_ATCD_RADIUS * window_w / 1400))),
    }


_ATCD_TYPE_AT = 0.50


_ATCD_TYPE_SPAN = 1.50


_ATCD_CURSOR_OFF = 2.20


_ATCD_FIRST_OUT = 2.30


_ATCD_CLEAR_AT = 2.50


_ATCD_OUT_BASE = 2.80


_ATCD_OUT_STAGGER = 0.10


_ATCD_PROMPT2 = 4.20


_ATCD_BLINK0 = 4.40


_ATCD_BLINK_GAP = 0.40


_ATCD_BLINK_DUR = 0.05


_ATCD_HOLD = 6.80


_ATCD_CHAR_FADE = 0.04


def _atcd_times(duration: float, n_chars: int) -> dict[str, float]:
    """Каталог на ~7 с: набор с 0.50, вывод с 2.3, новый промпт с 4.2."""
    d = max(2.0, float(duration))
    type_at = _ATCD_TYPE_AT
    type_span = _ATCD_TYPE_SPAN
    cursor_off = _ATCD_CURSOR_OFF
    first_out = _ATCD_FIRST_OUT
    clear_at = _ATCD_CLEAR_AT
    out_base = _ATCD_OUT_BASE
    out_stagger = _ATCD_OUT_STAGGER
    prompt2 = _ATCD_PROMPT2
    blink0 = _ATCD_BLINK0
    blink_gap = _ATCD_BLINK_GAP
    blink_dur = _ATCD_BLINK_DUR
    hold = _ATCD_HOLD
    packed = hold
    if packed > d - 0.04:
        fit = (d - 0.04) / packed
        type_at *= fit
        type_span *= fit
        cursor_off *= fit
        first_out *= fit
        clear_at *= fit
        out_base *= fit
        out_stagger *= fit
        prompt2 *= fit
        blink0 *= fit
        blink_gap *= fit
        hold *= fit
    n = max(1, int(n_chars))
    per = type_span / n
    blink_dur = min(blink_dur, max(0.02, blink_gap - 0.002))
    return {
        "type_at": round(type_at, 4),
        "per": round(per, 5),
        "char_fade": round(min(_ATCD_CHAR_FADE, max(0.02, per * 0.4)), 4),
        "cursor_off": round(cursor_off, 4),
        "first_out": round(first_out, 4),
        "clear_at": round(clear_at, 4),
        "out_base": round(out_base, 4),
        "out_stagger": round(out_stagger, 4),
        "prompt2": round(prompt2, 4),
        "blink0": round(blink0, 4),
        "blink_gap": round(blink_gap, 4),
        "blink_dur": round(blink_dur, 4),
        "hold": round(hold, 4),
    }


_ATCD_N_BLINKS = 6


_ATCD_FRAME_W = 1080


_ATCD_FRAME_H = 1920


_ATCD_PAD_X = 20


def fs_apple_terminal_clear_dark(ctx: "TemplateCtx") -> Piece:
    """Terminal.app Clear Dark: каталог пишет textContent и innerHTML.

    Здесь глифы команды и второй промпт заранее, показ — ``opacity``.
    Сланец ``var(--color-ink)``, белый текст и серый промпт ``var(--color-muted)`` как в
    каталоге — профиль Clear Dark, не палитра канала.
    """
    params = ctx.params
    code = str(params.get("code") or params.get("content") or params.get("text")
               or "").replace("\r\n", "\n").replace("\t", "  ")
    command, prompt, title, output = _atcd_session(params, code)
    if not command:
        return Piece()
    glyphs = list(command)
    node_id = ctx.target
    frame_w = int(params.get("frame_w") or _ATCD_FRAME_W)
    frame_h = int(params.get("frame_h") or _ATCD_FRAME_H)
    m = _atcd_metrics(len(output), frame_w, frame_h)
    t = _atcd_times(ctx.duration, len(glyphs))
    at = _enter_at(ctx)
    invert = " invert" if params.get("invert") else ""
    tweens: list[str] = []
    for i, _ch in enumerate(glyphs):
        start = at + t["type_at"] + i * t["per"]
        tweens.append(
            f'tl.fromTo("#{node_id}-c{i}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(t["char_fade"])},ease:"none"}},'
            f'{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{node_id}-cur1",{{opacity:1}},'
        f'{{opacity:0,duration:{_num(t["blink_dur"])},ease:"none"}},'
        f'{_num(at + t["cursor_off"])});')
    tweens.append(
        f'tl.fromTo("#{node_id}-cmd",{{opacity:1}},'
        f'{{opacity:0,duration:{_num(t["blink_dur"])},ease:"none",'
        f'immediateRender:false}},{_num(at + t["clear_at"])});')
    for i, (_line, _kind) in enumerate(output):
        if i == 0:
            when = at + t["first_out"]
        else:
            when = at + t["out_base"] + i * t["out_stagger"]
        tweens.append(
            f'tl.fromTo("#{node_id}-o{i}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(t["blink_dur"])},ease:"none"}},'
            f'{_num(when)});')
    tweens.append(
        f'tl.fromTo("#{node_id}-in1",{{opacity:1}},'
        f'{{opacity:0,duration:{_num(t["blink_dur"])},ease:"none",'
        f'immediateRender:false}},{_num(at + t["prompt2"])});')
    tweens.append(
        f'tl.fromTo("#{node_id}-in2",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(t["blink_dur"])},ease:"none"}},'
        f'{_num(at + t["prompt2"])});')
    for i in range(_ATCD_N_BLINKS):
        start = at + t["blink0"] + i * t["blink_gap"]
        going_off = i % 2 == 0
        fr, to = (1, 0) if going_off else (0, 1)
        extra = ",immediateRender:false" if i else ""
        tweens.append(
            f'tl.fromTo("#{node_id}-cur2",{{opacity:{fr}}},'
            f'{{opacity:{to},duration:{_num(t["blink_dur"])},ease:"none"'
            f'{extra}}},{_num(start)});')
    # То же правило, что и у `beat-freeze-cut`: каждый выход в ноль гасится
    # жёстко. Курсор терминала мигает туда-сюда, и гашение в конце «погасания»
    # безопасно — следующее «зажигание» стоит позже по ленте.
    for done in list(tweens):
        made = re.search(r'tl\.fromTo\("([^"]+)",\{[^}]*\},\{([^}]*)\},([0-9.]+)\);', done)
        if not made or not re.search(r"opacity:0(?![.0-9])", made.group(2)):
            continue
        span = re.search(r"duration:([0-9.]+)", made.group(2))
        tweens.append(
            f'tl.set("{made.group(1)}",{{opacity:0}},'
            f'{_num(float(made.group(3)) + float(span.group(1)))});')
    chars_html = "".join(
        f'<span id="{node_id}-c{i}" class="atcd-ch">{_esc(ch)}</span>'
        for i, ch in enumerate(glyphs)
    )
    out_html = "".join(
        f'<span id="{node_id}-o{i}" class="atcd-line'
        f'{" atcd-dim" if kind == "dim" else ""}'
        f'{" atcd-bold" if kind == "bold" else ""}"'
        f' style="min-height:{m["lh"]}px;line-height:{m["lh"]}px">'
        f'{_esc(line) if line else " "}</span>'
        for i, (line, kind) in enumerate(output)
    )
    prompt_html = f'<span class="atcd-prompt">{_esc(prompt)}</span>'
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text '
               f'fs-apple-terminal-clear-dark{invert}" {_timing(ctx)}>'
               f'<span class="atcd-stage">'
               f'<span class="atcd-window" style="width:{m["window_w"]}px;'
               f'height:{m["window_h"]}px;border-radius:{m["radius"]}px">'
               f'<span class="atcd-bar">'
               f'<span class="atcd-lights">'
               f'<span class="atcd-dot atcd-close"></span>'
               f'<span class="atcd-dot atcd-min"></span>'
               f'<span class="atcd-dot atcd-full"></span></span>'
               f'<span class="atcd-title">{_esc(title)}</span></span>'
               f'<span class="atcd-canvas" style="height:{m["canvas_h"]}px;'
               f'font-size:{m["size"]}px;padding:{_ATCD_PAD_Y}px {_ATCD_PAD_X}px">'
               f'<span class="atcd-out">{out_html}</span>'
               f'<span class="atcd-slot" style="min-height:{m["lh"]}px">'
               f'<span id="{node_id}-in1" class="atcd-input" '
               f'style="min-height:{m["lh"]}px;line-height:{m["lh"]}px">'
               f'{prompt_html}'
               f'<span id="{node_id}-cmd" class="atcd-cmd">{chars_html}</span>'
               f'<span id="{node_id}-cur1" class="atcd-cursor" '
               f'style="width:{m["caret_w"]}px;height:{m["caret_h"]}px">'
               f'</span></span>'
               f'<span id="{node_id}-in2" class="atcd-input atcd-input-next" '
               f'style="min-height:{m["lh"]}px;line-height:{m["lh"]}px">'
               f'{prompt_html}'
               f'<span id="{node_id}-cur2" class="atcd-cursor" '
               f'style="width:{m["caret_w"]}px;height:{m["caret_h"]}px">'
               f'</span></span></span>'
               f'</span></span></span></div>'],
        tweens=tweens)


_BFC_CATALOG_END = 5.55


def _bfc_times(duration: float) -> dict[str, float]:
    """Каталог на 6 с: beat 0.7, freeze 2.2, cut 3.0, hold 5.2."""
    d = max(2.0, float(duration))
    fit = 1.0
    if _BFC_CATALOG_END > d - 0.04:
        fit = (d - 0.04) / _BFC_CATALOG_END

    def pack(value: float) -> float:
        return round(value * fit, 4)

    freeze = pack(2.2)
    ramp = pack(1.35)
    return {
        "card_dur": pack(0.55),
        "zoom0_dur": pack(0.69),
        "intro_at": pack(0.12),
        "intro_in": pack(0.28),
        "intro_out_at": pack(0.52),
        "intro_out": pack(0.18),
        "bar_in_at": pack(0.12),
        "bar_in_stagger": pack(0.02),
        "bar_in_dur": pack(0.42),
        "beat1": pack(0.70),
        "crop1_dur": pack(0.22),
        "zoom1_dur": pack(0.28),
        "bar_beat_stagger": pack(0.01),
        "bar_beat_dur": pack(0.16),
        "ramp": ramp,
        "ramp_dur": round(max(0.12, freeze - ramp), 4),
        "freeze": freeze,
        "flash_dur": pack(0.28),
        "hit_in": pack(0.05),
        "hit_out_at": pack(2.75),
        "hit_out": pack(0.20),
        "settle_at": pack(2.55),
        "settle_dur": pack(0.35),
        "cut": pack(3.0),
        "smear_in": pack(0.12),
        "switch": pack(3.14),
        "zoom_rec": pack(0.18),
        "smear_out_at": pack(3.16),
        "smear_out": pack(0.16),
        "bleft_dur": pack(0.40),
        "bcard_dur": pack(0.38),
        "bcard_stagger": pack(0.06),
        "zoom_b_at": pack(3.33),
        "zoom_b_dur": pack(1.17),
        "beat3": pack(4.7),
        "zoom3_dur": pack(0.14),
        "bc_punch": pack(0.12),
        "bc_back_at": pack(4.84),
        "bc_back": pack(0.22),
        "hold": pack(5.2),
        "hold_dur": pack(0.35),
        "bar_ramp_stagger": pack(0.01),
        "bar_ramp_dur": pack(0.70),
    }


def _bfc_place(prev_end: float, want: float) -> float:
    if want >= prev_end + 0.001:
        return want
    return round(prev_end + 0.001, 4)


_BFC_PATTERN = (0.55, 1.15, 0.7, 1.35, 0.9, 1.4, 0.65, 1.1, 0.5, 1.25, 0.8, 1.45)


def _bfc_n(value: float) -> str:
    if abs(float(value)) < 1e-9:
        return "0"
    return _num(value)


_BFC_WAVE_FILL = (
    "M0,160 C40,150 60,90 100,100 C140,110 160,40 200,55 C240,70 260,150 300,140 "
    "C340,130 360,30 400,45 C440,60 460,130 500,120 C540,110 560,70 592,80 "
    "L592,220 L0,220 Z")


_BFC_WAVE_PATH = (
    "M0,160 C40,150 60,90 100,100 C140,110 160,40 200,55 C240,70 260,150 300,140 "
    "C340,130 360,30 400,45 C440,60 460,130 500,120 C540,110 560,70 592,80")


def fs_beat_freeze_cut(ctx: "TemplateCtx") -> Piece:
    """Music-promo: рамп → freeze DROP → hard-cut. Каталог твинит filter.

    Здесь scale/x/y/opacity и статичный backdrop-filter. Твины на карточке,
    кропе, барах и слоях freeze/cut, не на ``.clip``. Мята каталога ``var(--color-accent)``
    спорит со скриншотами — акцент ``var(--color-accent)``, сцена ``var(--color-space-deep)``, панели
    ``var(--color-space-deep)``. Циан ``var(--color-accent)`` не берём.
    """
    params = ctx.params
    raw = str(params.get("content") or params.get("text") or "").strip()
    line = raw.split("\n")[0].strip() if raw else ""
    primary = line if 1 <= len(line) <= 16 else "DROP"
    secondary = str(params.get("secondary") or "ON THE BEAT").strip() or "ON THE BEAT"
    node_id = ctx.target
    invert = " invert" if params.get("invert") else ""
    t = _bfc_times(ctx.duration)
    at = _enter_at(ctx)

    def ft(sel: str, frm: str, too: str, dur: float, ease: str, start: float,
           *, ir: bool = False) -> str:
        flag = ",immediateRender:false" if ir else ""
        tween = (
            f'tl.fromTo("{sel}",{{{frm}}},{{{too},duration:{_bfc_n(dur)},'
            f'ease:"{ease}"{flag}}},{_bfc_n(start)});')
        # Ноль, а не `opacity:0.85`: гасится только настоящий выход.
        if re.search(r"opacity:0(?![.0-9])", too):
            tween += f'tl.set("{sel}",{{opacity:0}},{_bfc_n(start + dur)});'
        return tween

    zoom = f"#{node_id}-zoom"
    crop = f"#{node_id}-crop"
    card = f"#{node_id}-card"
    shot_a = f"#{node_id}-a"
    shot_b = f"#{node_id}-b"
    intro = f"#{node_id}-intro"
    hit = f"#{node_id}-hit"
    flash = f"#{node_id}-flash"
    outline = f"#{node_id}-outline"
    contour = f"#{node_id}-contour"
    badge = f"#{node_id}-badge"
    smear = f"#{node_id}-smear"
    blur = f"#{node_id}-blur"
    bleft = f"#{node_id}-bleft"
    tweens = [
        ft(card, "scale:0.9,y:20", "scale:1,y:0", t["card_dur"], "power3.out", at),
        ft(zoom, "scale:1", "scale:1.04", t["zoom0_dur"], "power1.out", at),
        ft(intro, "opacity:0,y:-12", "opacity:1,y:0",
           t["intro_in"], "power2.out", at + t["intro_at"]),
        ft(intro, "opacity:1,y:0", "opacity:0,y:-8",
           t["intro_out"], "power2.in", at + t["intro_out_at"], ir=True),
    ]
    zoom_end = at + t["zoom0_dur"]
    z1_at = _bfc_place(zoom_end, at + t["beat1"])
    tweens.append(ft(zoom, "scale:1.04", "scale:1.08",
                     t["zoom1_dur"], "expo.out", z1_at, ir=True))
    zoom_end = z1_at + t["zoom1_dur"]
    tweens.append(ft(crop, "scale:1,x:0,y:0", "scale:1.18,x:-80,y:24",
                     t["crop1_dur"], "power4.out", at + t["beat1"]))
    crop_end = at + t["beat1"] + t["crop1_dur"]
    ramp_at = _bfc_place(crop_end, at + t["ramp"])
    z_ramp = _bfc_place(zoom_end, at + t["ramp"])
    tweens.append(ft(crop, "scale:1.18,x:-80,y:24", "scale:1.28,x:28,y:-12",
                     t["ramp_dur"], "power3.in", ramp_at, ir=True))
    tweens.append(ft(zoom, "scale:1.08", "scale:1.12",
                     t["ramp_dur"], "power2.in", z_ramp, ir=True))
    zoom_end = z_ramp + t["ramp_dur"]
    for i, peak in enumerate(_BFC_PATTERN):
        bar = f"#{node_id}-bar{i}"
        in_at = at + t["bar_in_at"] + i * t["bar_in_stagger"]
        tweens.append(ft(bar, "scaleY:0.55", "scaleY:1",
                         t["bar_in_dur"], "power2.out", in_at))
        in_end = in_at + t["bar_in_dur"]
        beat_at = _bfc_place(in_end, at + t["beat1"] + i * t["bar_beat_stagger"])
        tweens.append(ft(bar, "scaleY:1", f"scaleY:{_bfc_n(peak)}",
                         t["bar_beat_dur"], "power3.out", beat_at, ir=True))
        beat_end = beat_at + t["bar_beat_dur"]
        ramp_bar = _bfc_place(
            beat_end, at + t["ramp"] + i * t["bar_ramp_stagger"])
        tweens.append(ft(bar, f"scaleY:{_bfc_n(peak)}", "scaleY:1.55",
                         t["bar_ramp_dur"], "power2.in", ramp_bar, ir=True))
    freeze_at = at + t["freeze"]
    tweens.extend([
        ft(flash, "opacity:0.55", "opacity:0",
           t["flash_dur"], "power2.out", freeze_at),
        ft(outline, "opacity:0", "opacity:1",
           t["hit_in"], "power4.out", freeze_at),
        ft(contour, "opacity:0", "opacity:0.85",
           t["hit_in"], "power4.out", freeze_at),
        ft(badge, "opacity:0", "opacity:1",
           t["hit_in"], "power4.out", freeze_at),
        ft(hit, "opacity:0,scale:1.15", "opacity:1,scale:1",
           t["hit_in"], "power4.out", freeze_at),
        ft(hit, "opacity:1,scale:1", "opacity:0,scale:0.96",
           t["hit_out"], "power2.in", at + t["hit_out_at"], ir=True),
        ft(outline, "opacity:1", "opacity:0.75",
           t["settle_dur"], "sine.out", at + t["settle_at"], ir=True),
        ft(contour, "opacity:0.85", "opacity:0.75",
           t["settle_dur"], "sine.out", at + t["settle_at"], ir=True),
        ft(badge, "opacity:1", "opacity:0.75",
           t["settle_dur"], "sine.out", at + t["settle_at"], ir=True),
    ])
    cut_at = at + t["cut"]
    switch_at = at + t["switch"]
    tweens.extend([
        ft(smear, "opacity:0,scaleX:0.35,x:-280", "opacity:0.95,scaleX:1.6,x:120",
           t["smear_in"], "power4.in", cut_at),
        ft(blur, "opacity:0", "opacity:0.85",
           t["smear_in"], "power3.in", cut_at),
        ft(smear, "opacity:0.95,x:120", "opacity:0,x:360",
           t["smear_out"], "power2.out", at + t["smear_out_at"], ir=True),
        ft(blur, "opacity:0.85", "opacity:0",
           t["zoom_rec"], "power3.out", switch_at, ir=True),
        ft(shot_a, "opacity:1", "opacity:0", 0.001, "none", switch_at),
        ft(shot_b, "opacity:0", "opacity:1", 0.001, "none", switch_at),
        ft(outline, "opacity:0.75", "opacity:0", 0.001, "none", switch_at, ir=True),
        ft(contour, "opacity:0.75", "opacity:0", 0.001, "none", switch_at, ir=True),
        ft(badge, "opacity:0.75", "opacity:0", 0.001, "none", switch_at, ir=True),
        ft(bleft, "opacity:0,x:-24", "opacity:1,x:0",
           t["bleft_dur"], "power3.out", switch_at),
    ])
    for i in range(3):
        card_at = switch_at + i * t["bcard_stagger"]
        tweens.append(ft(f"#{node_id}-bc{i}", "opacity:0,x:24", "opacity:1,x:0",
                         t["bcard_dur"], "power3.out", card_at))
    rec_at = _bfc_place(zoom_end, switch_at)
    tweens.append(ft(zoom, "scale:1.12", "scale:1",
                     t["zoom_rec"], "power3.out", rec_at, ir=True))
    zoom_end = rec_at + t["zoom_rec"]
    zb_at = _bfc_place(zoom_end, at + t["zoom_b_at"])
    tweens.append(ft(zoom, "scale:1", "scale:1.02",
                     t["zoom_b_dur"], "sine.out", zb_at, ir=True))
    zoom_end = zb_at + t["zoom_b_dur"]
    z3_at = _bfc_place(zoom_end, at + t["beat3"])
    tweens.append(ft(zoom, "scale:1.02", "scale:1.08",
                     t["zoom3_dur"], "power4.out", z3_at, ir=True))
    zoom_end = z3_at + t["zoom3_dur"]
    hold_at = _bfc_place(zoom_end, at + t["hold"])
    tweens.append(ft(zoom, "scale:1.08", "scale:1.03",
                     t["hold_dur"], "power2.out", hold_at, ir=True))
    bc1 = f"#{node_id}-bc1"
    tweens.append(ft(bc1, "scale:1", "scale:1.04",
                     t["bc_punch"], "power3.out", at + t["beat3"]))
    tweens.append(ft(bc1, "scale:1.04", "scale:1",
                     t["bc_back"], "power2.out", at + t["bc_back_at"], ir=True))
    bars_html = "".join(
        f'<span id="{node_id}-bar{i}" class="bfc-bar"></span>'
        for i in range(12))
    b_cards = (
        ('Ramp', '1.35→2.2', False),
        ('Freeze', '0.8s', True),
        ('Cut', '3.00', False),
    )
    cards_html = "".join(
        f'<span id="{node_id}-bc{i}" class="bfc-b-card">'
        f'<span class="bfc-b-label">{_esc(label)}</span>'
        f'<span class="bfc-b-value{" accent" if accent else ""}">'
        f'{_esc(value)}</span></span>'
        for i, (label, value, accent) in enumerate(b_cards))
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text '
               f'fs-beat-freeze-cut{invert}" {_timing(ctx)}>'
               f'<span class="bfc-stage">'
               f'<span class="bfc-bg"></span><span class="bfc-grid"></span>'
               f'<span id="{node_id}-zoom" class="bfc-zoom">'
               f'<span id="{node_id}-a" class="bfc-shot-a">'
               f'<span id="{node_id}-crop" class="bfc-crop">'
               f'<span id="{node_id}-card" class="bfc-card">'
               f'<span class="bfc-glow"></span>'
               f'<span class="bfc-wave"><svg viewBox="0 0 592 220" '
               f'preserveAspectRatio="none" aria-hidden="true">'
               f'<path class="bfc-wave-fill" d="{_BFC_WAVE_FILL}"/>'
               f'<path class="bfc-wave-path" d="{_BFC_WAVE_PATH}"/>'
               f'</svg></span>'
               f'<span class="bfc-bars">{bars_html}</span>'
               f'<span class="bfc-meta"><span class="bfc-kicker">MUSIC PROMO</span>'
               f'<span class="bfc-pill">LIVE</span></span>'
               f'</span></span></span>'
               f'<span id="{node_id}-b" class="bfc-shot-b">'
               f'<span id="{node_id}-bleft" class="bfc-b-copy">'
               f'<span class="bfc-eyebrow">Next shot</span>'
               f'<span class="bfc-title"><span>HARD</span><span>CUT</span></span>'
               f'<span class="bfc-accent-bar"></span>'
               f'<span class="bfc-sub">Beat-locked freeze, then cut. '
               f'Built for music-led promos and montages.</span></span>'
               f'<span class="bfc-b-list">{cards_html}</span>'
               f'</span></span>'
               f'<span id="{node_id}-intro" class="bfc-intro">'
               f'<span class="bfc-intro-label">{_esc(secondary)}</span></span>'
               f'<span id="{node_id}-hit" class="bfc-hit">{_esc(primary)}</span>'
               f'<span id="{node_id}-outline" class="bfc-outline"></span>'
               f'<span id="{node_id}-flash" class="bfc-flash"></span>'
               f'<span id="{node_id}-contour" class="bfc-contour"></span>'
               f'<span id="{node_id}-badge" class="bfc-badge">FREEZE</span>'
               f'<span id="{node_id}-smear" class="bfc-smear"></span>'
               f'<span id="{node_id}-blur" class="bfc-blur"></span>'
               f'<span class="bfc-vignette"></span>'
               f'</span></div>'],
        tweens=tweens)


_C3D_SIZE_CEILING = 34


_C3D_SIZE_FLOOR = 18


_C3D_PAD_X = 32


_C3D_MONO_EM = 0.62


def _c3d_fit(lines: list[list[tuple[str, str]]], available: float) -> int:
    longest = max((sum(len(t[0]) for t in line) for line in lines), default=1)
    text_avail = max(80.0, available - 2 * _C3D_PAD_X)
    size = _C3D_SIZE_CEILING
    while size > _C3D_SIZE_FLOOR and longest * size * _C3D_MONO_EM > text_avail:
        size -= 1
    return size


_C3D_SETTLE_FRAC = 0.6


def _c3d_times(duration: float) -> dict[str, float]:
    """Посадка 60 % длительности, как camZ в каталоге; дрейф после стыка +1 мс."""
    settle_dur = max(0.2, duration * _C3D_SETTLE_FRAC)
    if settle_dur > duration - 0.05:
        settle_dur = max(0.2, duration - 0.05)
    drift_at = settle_dur + 0.001
    drift_dur = max(0.0, duration - drift_at)
    return {"settle_dur": settle_dur, "drift_at": drift_at, "drift_dur": drift_dur}


_C3D_LEX = re.compile(
    r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)'
    r"|(/\*[^*]*\*+(?:[^/*][^*]*\*+)*/|//[^\n]*)"
    r"|(\b\d+(?:\.\d+)?\b)"
    r"|(\b[A-Za-z_]\w*\b)"
    r"|(\s+)"
    r"|([^\sA-Za-z0-9_]+)"
)


_C3D_FN_COLOR = "#ED747D"


_C3D_VAR_COLOR = "#7A7D82"


_C3D_FG_COLOR = "#F7F5F3"


_C3D_STR_COLOR = "#C7C9D1"


_C3D_CMT_COLOR = "#7A7D82"


_C3D_PARAM_COLOR = "#E63946"


_C3D_KW_COLOR = "#E63946"


_C3D_KW = frozenset({
    "async", "await", "function", "const", "let", "var", "return", "if", "else",
    "for", "while", "class", "new", "import", "from", "export", "default",
    "true", "false", "null", "undefined", "def", "and", "or", "not", "in",
    "try", "catch", "throw", "this", "typeof", "void", "yield", "of",
})


def _c3d_highlight(code: str) -> list[list[tuple[str, str]]]:
    """Github-dark токены без Shiki: ключевые, функции, строки, параметры."""
    rows: list[list[tuple[str, str]]] = []
    for line in code.split("\n"):
        raw: list[tuple[str, str]] = []
        for match in _C3D_LEX.finditer(line):
            string, comment, number, ident, space, punct = match.groups()
            if string:
                raw.append((string, _C3D_STR_COLOR))
            elif comment:
                raw.append((comment, _C3D_CMT_COLOR))
            elif number:
                raw.append((number, _C3D_VAR_COLOR))
            elif ident:
                color = _C3D_KW_COLOR if ident in _C3D_KW else _C3D_VAR_COLOR
                raw.append((ident, color))
            elif space:
                raw.append((space, _C3D_FG_COLOR))
            elif punct:
                raw.append((punct, _C3D_FG_COLOR))
        if not raw and line == "":
            rows.append([("", _C3D_FG_COLOR)])
            continue
        colored: list[tuple[str, str]] = []
        i = 0
        while i < len(raw):
            text, color = raw[i]
            nxt = ""
            for j in range(i + 1, len(raw)):
                if raw[j][0].strip():
                    nxt = raw[j][0]
                    break
            if (color == _C3D_VAR_COLOR and text.isidentifier()
                    and nxt.startswith("(")):
                colored.append((text, _C3D_FN_COLOR))
            else:
                colored.append((text, color))
            i += 1
        i = 0
        while i < len(colored):
            text, color = colored[i]
            if color == _C3D_FN_COLOR:
                depth = 0
                j = i + 1
                while j < len(colored):
                    chunk = colored[j][0]
                    if "(" in chunk:
                        depth += chunk.count("(")
                    if colored[j][1] == _C3D_VAR_COLOR and colored[j][0].isidentifier() and depth > 0:
                        colored[j] = (colored[j][0], _C3D_PARAM_COLOR)
                    if ")" in chunk:
                        depth -= chunk.count(")")
                        if depth <= 0:
                            break
                    j += 1
            i += 1
        rows.append(colored or [("", _C3D_FG_COLOR)])
    if rows and rows[-1] == [("", _C3D_FG_COLOR)]:
        rows.pop()
    return rows


_C3D_FROM_X = 48


_C3D_FROM_Y = 36


_C3D_FROM_ROT = -9


_C3D_SCALE_FROM = 0.72


_C3D_DRIFT_X = 6


_C3D_DRIFT_Y = -3


_C3D_DRIFT_ROT = 2


_C3D_DRIFT_SCALE = 1.02


_C3D_LH = 1.47


def fs_code_3d_extrude(ctx: "TemplateCtx") -> Piece:
    """Код на скошенной плите: каталог — Three.js ExtrudeGeometry.

    Движок WebGL и ``onUpdate`` не умеет. Посадка — ``scale``/``x``/``y``/
    ``rotation`` на плите, скос — статичный слой ``var(--color-space-deep)``. Github-dark и
    JetBrains Mono как в каталоге — это сам жест, не палитра канала. Твины
    на ``#…-slab``, не на ``.clip``.
    """
    params = ctx.params
    code = str(params.get("code") or params.get("content") or params.get("text")
               or "").replace("\r\n", "\n").strip("\n")
    if not code.strip():
        return Piece()
    raw_tokens = params.get("tokens")
    if isinstance(raw_tokens, list) and raw_tokens:
        rows: list[list[tuple[str, str]]] = [[]]
        for tok in raw_tokens:
            if not isinstance(tok, dict):
                continue
            piece = str(tok.get("content") or "")
            color = str(tok.get("color") or _C3D_FG_COLOR)
            if piece == "\n":
                rows.append([])
                continue
            rows[-1].append((piece, color))
        while rows and not rows[-1]:
            rows.pop()
        lines = rows or _c3d_highlight(code)
    else:
        lines = _c3d_highlight(code)
    node_id = ctx.target
    available = float(params.get("available_px") or 740)
    size = _c3d_fit(lines, available)
    t = _c3d_times(ctx.duration)
    at = _enter_at(ctx)
    tweens = [
        f'tl.fromTo("#{node_id}-slab",'
        f'{{scale:{_num(_C3D_SCALE_FROM)},x:{_C3D_FROM_X},y:{_C3D_FROM_Y},'
        f'rotation:{_C3D_FROM_ROT}}},'
        f'{{scale:1,x:0,y:0,rotation:0,duration:{_num(t["settle_dur"])},'
        f'ease:"power3.out"}},{_num(at)});',
    ]
    if t["drift_dur"] >= 0.05:
        tweens.append(
            f'tl.fromTo("#{node_id}-slab",'
            f'{{scale:1,x:0,y:0,rotation:0}},'
            f'{{scale:{_num(_C3D_DRIFT_SCALE)},x:{_C3D_DRIFT_X},y:{_C3D_DRIFT_Y},'
            f'rotation:{_C3D_DRIFT_ROT},duration:{_num(t["drift_dur"])},'
            f'ease:"sine.inOut",immediateRender:false}},'
            f'{_num(at + t["drift_at"])});')
    line_html: list[str] = []
    for li, line in enumerate(lines):
        toks = "".join(
            f'<span class="c3d-tok" style="color:{html.escape(color, quote=True)}">'
            f'{_esc(text)}</span>'
            for text, color in line
        )
        line_html.append(f'<span class="c3d-line" data-i="{li}">{toks}</span>')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text fs-code-3d" '
               f'{_timing(ctx)}>'
               f'<span id="{node_id}-stage" class="c3d-stage">'
               f'<span id="{node_id}-slab" class="c3d-slab">'
               f'<span class="c3d-edge" aria-hidden="true"></span>'
               f'<span class="c3d-face" style="font-size:{size}px;'
               f'line-height:{_num(_C3D_LH)}">'
               f'{"".join(line_html)}</span></span></span></div>'],
        tweens=tweens)


_CD_TOP = 24


def _cd_rows_from_tokens(raw_tokens: Any) -> list[list[tuple[str, str]]] | None:
    if not isinstance(raw_tokens, list) or not raw_tokens:
        return None
    rows: list[list[tuple[str, str]]] = [[]]
    for tok in raw_tokens:
        if not isinstance(tok, dict):
            continue
        piece = str(tok.get("content") or "")
        color = str(tok.get("color") or _C3D_FG_COLOR)
        if piece == "\n":
            rows.append([])
            continue
        rows[-1].append((piece, color))
    while rows and not rows[-1]:
        rows.pop()
    return rows or None


def _cd_parse_pair(params: dict[str, Any]) -> tuple[str, str]:
    """before/after, разделитель ---, unified diff, иначе один сниппет дважды."""
    before = str(params.get("code_before") or params.get("before") or "")
    after = str(params.get("code_after") or params.get("after") or "")
    before = before.replace("\r\n", "\n").strip("\n")
    after = after.replace("\r\n", "\n").strip("\n")
    if before.strip() or after.strip():
        return before, after or before
    content = str(params.get("code") or params.get("content") or params.get("text")
                  or "").replace("\r\n", "\n").strip("\n")
    if not content.strip():
        return "", ""
    parts = re.split(r"\n---+\n", content, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip("\n"), parts[1].strip("\n")
    raw = content.split("\n")
    plus = any(ln.startswith("+") and not ln.startswith("+++") for ln in raw)
    minus = any(ln.startswith("-") and not ln.startswith("---") for ln in raw)
    if plus and minus:
        old: list[str] = []
        new: list[str] = []
        for ln in raw:
            if ln.startswith("+++") or ln.startswith("---") or ln.startswith("@@"):
                continue
            if ln.startswith("+"):
                new.append(ln[1:])
            elif ln.startswith("-"):
                old.append(ln[1:])
            else:
                body = ln[1:] if ln.startswith(" ") else ln
                old.append(body)
                new.append(body)
        return "\n".join(old), "\n".join(new)
    return content, content


def _cd_line_diff(a: list[str], b: list[str]) -> list[tuple[str, str]]:
    """LCS как в каталоге: same / del / add."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    ops: list[tuple[str, str]] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            ops.append(("same", b[j]))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            ops.append(("del", a[i]))
            i += 1
        else:
            ops.append(("add", b[j]))
            j += 1
    while i < n:
        ops.append(("del", a[i]))
        i += 1
    while j < m:
        ops.append(("add", b[j]))
        j += 1
    return ops


_CD_SIZE_CEILING = 28


def _cd_times(duration: float, n_del: int, n_add: int) -> dict[str, float]:
    """Каталог на 6 с: editor 0.5, fade 0.45, del 0.55, add 0.6. Стык +1 мс не нужен:
    scaleY и y на одной строке — разные свойства."""
    s = duration / 6.0
    editor_dur = max(0.18, 0.5 * s)
    fade_dur = max(0.12, 0.45 * s)
    fade_at = min(0.45 * s, editor_dur)
    hold = max(0.06, 0.3 * s)
    del_dur = max(0.16, 0.55 * s)
    add_dur = max(0.18, 0.6 * s)
    gap = max(0.04, 0.15 * s)
    st_del = 0.08 * s
    st_add = 0.12 * s
    at_del = fade_at + fade_dur + hold
    # Каталог: atAdd = atDel + DEL + 0.15 — после длительности первого минуса,
    # не после всего стаггера. Хвост последнего минуса пересекается с плюсом.
    at_add = at_del + (del_dur if n_del else 0.0) + (gap if n_add else 0.0)
    add_span = (add_dur + max(0, n_add - 1) * st_add) if n_add else 0.0
    end = max(at_add + add_span,
              at_del + ((del_dur + max(0, n_del - 1) * st_del) if n_del else 0.0))
    if end > duration - 0.04 and end > 1e-9:
        fit = max(0.35, (duration - 0.04) / end)
        editor_dur *= fit
        fade_dur *= fit
        fade_at *= fit
        hold *= fit
        del_dur *= fit
        add_dur *= fit
        gap *= fit
        st_del *= fit
        st_add *= fit
        at_del = fade_at + fade_dur + hold
        at_add = at_del + (del_dur if n_del else 0.0) + (gap if n_add else 0.0)
        add_span = (add_dur + max(0, n_add - 1) * st_add) if n_add else 0.0
    pack_end = max(
        at_add + add_span,
        at_del + ((del_dur + max(0, n_del - 1) * st_del) if n_del else 0.0),
    )
    pack_dur = max(0.05, pack_end - at_del) if (n_del or n_add) else 0.0
    return {
        "editor_dur": editor_dur,
        "fade_at": fade_at,
        "fade_dur": fade_dur,
        "at_del": at_del,
        "del_dur": del_dur,
        "st_del": st_del,
        "at_add": at_add,
        "add_dur": add_dur,
        "st_add": st_add,
        "pack_at": at_del,
        "pack_dur": pack_dur,
    }


def _cd_text_from_rows(rows: list[list[tuple[str, str]]]) -> str:
    return "\n".join("".join(text for text, _color in line) for line in rows)


_CD_PAD_X = 28


_CD_LH_EM = 1.53


_CD_EDITOR_SCALE = 0.985


def _cd_toks(line: list[tuple[str, str]]) -> str:
    return "".join(
        f'<span class="cd-tok" style="color:{html.escape(color, quote=True)}">'
        f'{_esc(text)}</span>'
        for text, color in line
    )


def fs_code_diff(ctx: "TemplateCtx") -> Piece:
    """Правка как цветной diff: каталог твинит height.

    Здесь минус схлопывается ``scaleY``, плюс раскрывается, пакет строк
    едет заранее посчитанным ``y``. Твины на ``#…-editor`` / строках, не
    на ``.clip``. JetBrains Mono и github-dark как в каталоге.
    """
    params = ctx.params
    before_rows = _cd_rows_from_tokens(params.get("tokens_before"))
    after_rows = _cd_rows_from_tokens(params.get("tokens_after"))
    before, after = _cd_parse_pair(params)
    if before_rows is not None:
        before = _cd_text_from_rows(before_rows)
    if after_rows is not None:
        after = _cd_text_from_rows(after_rows)
    if not before.strip() and not after.strip():
        return Piece()
    a_text = before.split("\n") if before.strip() else []
    b_text = after.split("\n") if after.strip() else []
    if not a_text and not b_text:
        return Piece()
    ops = _cd_line_diff(a_text, b_text)
    if not ops:
        return Piece()
    a_hi = before_rows if before_rows is not None else _c3d_highlight(before)
    b_hi = after_rows if after_rows is not None else _c3d_highlight(after)

    def _cd_index(rows: list[list[tuple[str, str]]]) -> dict[str, list]:
        out: dict[str, list] = {}
        for row in rows:
            key = "".join(piece for piece, _color in row)
            out.setdefault(key, []).append(row)
        return out

    a_map = _cd_index(a_hi)
    b_map = _cd_index(b_hi)
    highlighted: list[list[tuple[str, str]]] = []
    for kind, text in ops:
        src = b_map if kind != "del" else a_map
        bucket = src.get(text)
        if bucket:
            highlighted.append(bucket.pop(0))
        else:
            fallback = _c3d_highlight(text)
            highlighted.append(fallback[0] if fallback else [("", _C3D_FG_COLOR)])
    node_id = ctx.target
    available = max(float(params.get("available_px") or 740), 820.0)
    size = min(_CD_SIZE_CEILING, _c3d_fit(highlighted, available - _CD_PAD_X))
    size = max(_C3D_SIZE_FLOOR, size)
    lh = int(round(size * _CD_LH_EM))
    n_del = sum(1 for kind, _t in ops if kind == "del")
    n_add = sum(1 for kind, _t in ops if kind == "add")
    t = _cd_times(ctx.duration, n_del, n_add)
    at = _enter_at(ctx)
    y_start: list[int] = []
    cursor = _CD_TOP
    for kind, _text in ops:
        y_start.append(cursor)
        if kind != "add":
            cursor += lh
    y_end: list[int] = []
    cursor = _CD_TOP
    for kind, _text in ops:
        y_end.append(cursor)
        if kind != "del":
            cursor += lh
    code_h = max(y_start[-1], y_end[-1]) + lh + 16
    filename = str(params.get("filename") or "greet.js")
    invert = " invert" if params.get("invert") else ""
    tweens = [
        f'tl.fromTo("#{node_id}-editor",'
        f'{{opacity:0,scale:{_num(_CD_EDITOR_SCALE)}}},'
        f'{{opacity:1,scale:1,duration:{_num(t["editor_dur"])},'
        f'ease:"power2.out"}},{_num(at)});',
        f'tl.fromTo("#{node_id}-code",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(t["fade_dur"])},ease:"power1.out"}},'
        f'{_num(at + t["fade_at"])});',
    ]
    del_i = 0
    add_i = 0
    for i, (kind, _text) in enumerate(ops):
        lid = f"{node_id}-ln{i}"
        ys, ye = y_start[i], y_end[i]
        if ys != ye:
            tweens.append(
                f'tl.fromTo("#{lid}",{{y:{ys}}},{{y:{ye},'
                f'duration:{_num(t["pack_dur"])},ease:"power2.inOut"}},'
                f'{_num(at + t["pack_at"])});')
        else:
            tweens.append(f'tl.set("#{lid}",{{y:{ys}}},{_num(at)});')
        if kind == "del":
            when = at + t["at_del"] + del_i * t["st_del"]
            tweens.append(
                f'tl.fromTo("#{lid}",{{scaleY:1,opacity:1}},'
                f'{{scaleY:0,opacity:0,duration:{_num(t["del_dur"])},'
                f'ease:"power2.inOut"}},{_num(when)});')
            del_i += 1
        elif kind == "add":
            when = at + t["at_add"] + add_i * t["st_add"]
            tweens.append(
                f'tl.fromTo("#{lid}",{{scaleY:0,opacity:0}},'
                f'{{scaleY:1,opacity:1,duration:{_num(t["add_dur"])},'
                f'ease:"power2.out"}},{_num(when)});')
            add_i += 1
    lines_html: list[str] = []
    for i, (kind, _text) in enumerate(ops):
        sign = "-" if kind == "del" else "+" if kind == "add" else "\u00a0"
        lines_html.append(
            f'<span id="{node_id}-ln{i}" class="cd-line cd-{kind}" '
            f'style="height:{lh}px;font-size:{size}px;line-height:{lh}px">'
            f'<span class="cd-sign">{sign}</span>{_cd_toks(highlighted[i])}'
            f'</span>')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text fs-code-diff'
               f'{invert}" {_timing(ctx)}>'
               f'<span id="{node_id}-stage" class="cd-stage">'
               f'<span id="{node_id}-editor" class="cd-editor">'
               f'<span class="cd-titlebar">'
               f'<span class="cd-dots" aria-hidden="true">'
               f'<i class="cd-dot cd-dot-r"></i>'
               f'<i class="cd-dot cd-dot-y"></i>'
               f'<i class="cd-dot cd-dot-g"></i></span>'
               f'<span class="cd-filename"><span class="cd-file">'
               f'{_esc(filename)}</span> — Code Diff</span></span>'
               f'<span id="{node_id}-surface" class="cd-surface">'
               f'<span id="{node_id}-code" class="cd-code" '
               f'style="height:{code_h}px">'
               f'{"".join(lines_html)}</span></span></span></span></div>'],
        tweens=tweens)


_CPA_SIZE_CEILING = 56


_CPA_SIZE_FLOOR = 22


_CPA_FONT_PX_CAT = 46


_CPA_LINE_H_CAT = 70


_CPA_PAD_X_CAT = 70


_CPA_PAD_Y_CAT = 64


def _cpa_metrics(lines: list[list[tuple[str, str]]], available: float,
                 frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    longest = max((sum(len(piece[0]) for piece in line) for line in lines), default=1)

    def dims(s: int) -> tuple[int, int, int]:
        lh = max(1, int(round(s * _CPA_LINE_H_CAT / _CPA_FONT_PX_CAT)))
        px = max(8, int(round(s * _CPA_PAD_X_CAT / _CPA_FONT_PX_CAT)))
        py = max(8, int(round(s * _CPA_PAD_Y_CAT / _CPA_FONT_PX_CAT)))
        return lh, px, py

    size = _CPA_SIZE_CEILING
    lh, px, py = dims(size)
    text_avail = max(80.0, min(available, frame_w * 0.88) - 2 * px)
    while size > _CPA_SIZE_FLOOR:
        tall = len(lines) * lh + 2 * py
        wide = longest * size * _C3D_MONO_EM + 2 * px
        if (tall <= frame_h * 0.72 and wide <= frame_w * 0.90
                and longest * size * _C3D_MONO_EM <= text_avail):
            break
        size -= 1
        lh, px, py = dims(size)
    return size, lh, px, py


@lru_cache(maxsize=8)
def _cpa_mono_font(size: int):
    """JetBrains Mono Bold из проверенного набора. None — если файла нет."""
    try:
        from PIL import ImageFont

        manifest = json.loads(
            (Path("assets/fonts") / "fonts_manifest.json").read_text(encoding="utf-8"))
        entry = next(f for f in manifest["fonts"] if f.get("role") == "mono")
        return ImageFont.truetype(str(Path("assets/fonts") / entry["file"]), size)
    except Exception:                                        # noqa: BLE001
        return None


_CPA_BG_RGB = (11, 15, 23)


def _cpa_token_boxes(lines: list[list[tuple[str, str]]], font, pad_x: int,
                     pad_y: int, line_h: int) -> list[tuple[float, float, int, int, str]]:
    boxes: list[tuple[float, float, int, int, str]] = []
    for li, line in enumerate(lines):
        x = float(pad_x)
        y0 = pad_y + li * line_h
        y1 = y0 + line_h
        for text, color in line:
            if not text:
                continue
            wide = font.getlength(text) if font is not None else len(text) * 16.0
            if text.strip():
                boxes.append((x, x + wide, y0, y1, color))
            x += wide
    return boxes


def _cpa_glyph_hits(lines: list[list[tuple[str, str]]], size: int, pad_x: int,
                    pad_y: int, line_h: int, cap: int, font) -> list[tuple[int, int, str]]:
    hits: list[tuple[int, int, str]] = []
    em = size * _C3D_MONO_EM
    for li, line in enumerate(lines):
        x = float(pad_x)
        y = pad_y + li * line_h + int(round(line_h * 0.38))
        for text, color in line:
            for ch in text:
                wide = font.getlength(ch) if font is not None and ch else em
                if not ch:
                    continue
                if not ch.isspace():
                    hits.append((int(x + wide / 2), int(y), color))
                x += wide
    if len(hits) <= cap:
        return hits
    n = len(hits)
    return [hits[int(round(i * (n - 1) / (cap - 1)))] for i in range(cap)]


_CPA_THRESH = 220


def _cpa_snap_color(x: int, y: int, boxes: list[tuple[float, float, int, int, str]],
                    fallback: str) -> str:
    for x0, x1, y0, y1, color in boxes:
        if x0 <= x < x1 and y0 <= y < y1:
            return color
    return fallback


def _cpa_hex_rgb(color: str) -> tuple[int, int, int]:
    raw = str(color or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) < 6:
        return 225, 228, 232
    try:
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return 225, 228, 232


def _cpa_rgb_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _cpa_sample_hits(lines: list[list[tuple[str, str]]], size: int, pad_x: int,
                     pad_y: int, line_h: int, cap: int) -> tuple[list[tuple[int, int, str]], int, int]:
    """Семпл ярких пикселей глифов, как getImageData в каталоге. Cap — DOM."""
    font = _cpa_mono_font(size)
    if font is None:
        longest = max((sum(len(piece[0]) for piece in line) for line in lines), default=1)
        cw = max(2, int(math.ceil(longest * size * _C3D_MONO_EM + 2 * pad_x)))
        ch = max(2, int(len(lines) * line_h + 2 * pad_y))
        return _cpa_glyph_hits(lines, size, pad_x, pad_y, line_h, cap, None), cw, ch
    try:
        from PIL import Image, ImageDraw
    except Exception:                                        # noqa: BLE001
        longest = max((sum(len(piece[0]) for piece in line) for line in lines), default=1)
        cw = max(2, int(math.ceil(font.getlength("".join(t[0] for t in lines[0])) + 2 * pad_x)))
        ch = max(2, int(len(lines) * line_h + 2 * pad_y))
        return _cpa_glyph_hits(lines, size, pad_x, pad_y, line_h, cap, font), cw, ch

    max_w = 0.0
    for line in lines:
        wide = 0.0
        for text, _color in line:
            if text:
                wide += font.getlength(text)
        if wide > max_w:
            max_w = wide
    cw = max(2, int(math.ceil(max_w + 2 * pad_x)))
    ch = max(2, int(math.ceil(len(lines) * line_h + 2 * pad_y)))
    img = Image.new("RGB", (cw, ch), _CPA_BG_RGB)
    draw = ImageDraw.Draw(img)
    for li, line in enumerate(lines):
        x = float(pad_x)
        y = pad_y + li * line_h
        for text, color in line:
            if not text:
                continue
            draw.text((x, y), text, font=font, fill=_cpa_hex_rgb(color), anchor="lt")
            x += font.getlength(text)
    pix = img.load()
    step = 2
    if cw * ch > 400_000:
        step = 4
    hits: list[tuple[int, int, str]] = []
    for y in range(0, ch, step):
        for x in range(0, cw, step):
            r, g, b = pix[x, y][:3]
            if r + g + b < _CPA_THRESH:
                continue
            hits.append((x, y, _cpa_rgb_hex((r, g, b))))
    boxes = _cpa_token_boxes(lines, font, pad_x, pad_y, line_h)
    if hits and boxes:
        hits = [(x, y, _cpa_snap_color(x, y, boxes, color)) for x, y, color in hits]
    if not hits:
        return _cpa_glyph_hits(lines, size, pad_x, pad_y, line_h, cap, font), cw, ch
    if len(hits) > cap:
        n = len(hits)
        hits = [hits[int(round(i * (n - 1) / (cap - 1)))] for i in range(cap)]
    return hits, cw, ch


_CPA_CAP = 160


_CPA_SPAN = 0.62


_CPA_ASSEMBLE_FRAC = 0.72


def _cpa_times(duration: float) -> dict[str, float]:
    """Сборка 72 % длительности, как uProgress в каталоге; span 0.62.

    До конца сборки кадр — пыль. Острый код проявляется к финишу, пыль
    гаснет после стыка +1 мс, иначе opacity на точке пересекается.
    """
    assemble = max(0.35, duration * _CPA_ASSEMBLE_FRAC)
    if assemble > duration - 0.04:
        assemble = max(0.35, duration - 0.04)
    move = assemble * _CPA_SPAN
    code_at = assemble * 0.78
    code_dur = max(0.16, assemble - code_at)
    fade_at = assemble + 0.001
    fade = max(0.12, min(0.40, duration - fade_at - 0.02))
    return {
        "assemble": assemble,
        "move": move,
        "code_at": code_at,
        "code_dur": code_dur,
        "fade_at": fade_at,
        "fade": fade,
    }


def _cpa_i32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def _cpa_u32(value: int) -> int:
    return value & 0xFFFFFFFF


class _CpaRng:
    """mulberry32 каталога (seed 23, mix 2654435761). Без Math.random."""

    __slots__ = ("state",)

    def __init__(self, seed: int) -> None:
        self.state = _cpa_i32(seed)

    def __call__(self) -> float:
        a = _cpa_i32(self.state + 0x6D2B79F5)
        self.state = a
        t = _cpa_i32(_cpa_i32(a ^ (_cpa_u32(a) >> 15)) * (1 | a))
        t = _cpa_i32(t + _cpa_i32(_cpa_i32(t ^ (_cpa_u32(t) >> 7)) * (61 | t))) ^ t
        t = _cpa_i32(t)
        return _cpa_u32(t ^ (_cpa_u32(t) >> 14)) / 4294967296.0


_CPA_SEED = 23


_CPA_SEED_MIX = 2654435761


def _cpa_rng(seed: int = _CPA_SEED) -> _CpaRng:
    mixed = ((seed or 1) * _CPA_SEED_MIX) & 0xFFFFFFFF
    return _CpaRng(mixed)


_CPA_DOT = 12


_CPA_FRAME_W = 1080


_CPA_FRAME_H = 1920


def _cpa_brighten(color: str) -> str:
    r, g, b = _cpa_hex_rgb(color)
    bump = int(round(0.32 * 255))
    return _cpa_rgb_hex((min(255, r + bump), min(255, g + bump), min(255, b + bump)))


def _cpa_num(value: float) -> str:
    """_num(-0.0) даёт '-0' — линт и GSAP этого не едят."""
    if abs(float(value)) < 5e-4:
        return "0"
    return _num(value)


_CPA_SCALE_FROM = 0.62


def fs_code_particle_assemble(ctx: "TemplateCtx") -> Piece:
    """Пыль собирается в глифы кода: каталог — Three.js Points.

    Движок WebGL, ``onUpdate`` и ``Math.random`` не умеет. Пыль — span с
    заранее посчитанным ``x``/``y``, PRNG — mulberry32 seed 23. Github-dark
    и JetBrains Mono как в каталоге — это сам жест, не палитра канала.
    Твины на ``#…-d*`` и ``#…-code``, не на ``.clip``.
    """
    params = ctx.params
    code = str(params.get("code") or params.get("content") or params.get("text")
               or "").replace("\r\n", "\n").strip("\n")
    raw_tokens = params.get("tokens")
    token_rows = _cd_rows_from_tokens(raw_tokens)
    if token_rows is not None:
        lines = token_rows
        if not any(piece for line in lines for piece, _color in line):
            return Piece()
    else:
        if not code.strip():
            return Piece()
        lines = _c3d_highlight(code)
    if not lines:
        return Piece()
    node_id = ctx.target
    frame_w = int(params.get("frame_w") or _CPA_FRAME_W)
    frame_h = int(params.get("frame_h") or _CPA_FRAME_H)
    available = float(params.get("available_px") or min(900, frame_w * 0.88))
    size, line_h, pad_x, pad_y = _cpa_metrics(lines, available, frame_w, frame_h)
    hits, cw, ch = _cpa_sample_hits(lines, size, pad_x, pad_y, line_h, _CPA_CAP)
    if not hits:
        return Piece()
    t = _cpa_times(ctx.duration)
    at = _enter_at(ctx)
    rng = _cpa_rng(int(params.get("seed") or _CPA_SEED))
    code_left = (frame_w - cw) / 2.0
    code_top = (frame_h - ch) / 2.0
    radius = _CPA_DOT // 2
    spread_x = frame_w * 0.46
    spread_y = frame_h * 0.40
    fade_at = at + t["fade_at"]
    dust: list[str] = []
    tweens: list[str] = []
    for i, (px, py, color) in enumerate(hits):
        sx = (rng() * 2 - 1) * spread_x
        sy = (rng() * 2 - 1) * spread_y
        sz = (rng() * 2 - 1) * 9.0 - 2.0
        delay = rng()
        origin_x = frame_w / 2.0 + sx + sz * 16.0
        origin_y = frame_h / 2.0 + sy + sz * 10.0
        scatter_x = origin_x - (code_left + px)
        scatter_y = origin_y - (code_top + py)
        start = at + delay * (1.0 - _CPA_SPAN) * t["assemble"]
        did = f"{node_id}-d{i}"
        left = int(round(code_left + px - radius))
        top = int(round(code_top + py - radius))
        token = html.escape(color, quote=True)
        dust.append(
            f'<span id="{did}" class="pa-dot" style="'
            f'left:{left}px;top:{top}px;width:{_CPA_DOT}px;height:{_CPA_DOT}px;'
            f'background:{token}"></span>')
        bright = _cpa_brighten(color)
        tweens.append(
            f'tl.fromTo("#{did}",'
            f'{{x:{_cpa_num(scatter_x)},y:{_cpa_num(scatter_y)},'
            f'opacity:0.85,scale:{_num(_CPA_SCALE_FROM)},backgroundColor:"{bright}"}},'
            f'{{x:0,y:0,opacity:1,scale:1,backgroundColor:"{token}",'
            f'duration:{_num(t["move"])},ease:"power2.out"}},'
            f'{_num(start)});')
        if fade_at + 0.05 < ctx.start + ctx.duration:
            tweens.append(
                f'tl.fromTo("#{did}",{{opacity:1}},{{opacity:0,'
                f'duration:{_num(t["fade"])},ease:"power2.in",'
                f'immediateRender:false}},{_num(fade_at)});')
    tweens.append(
        f'tl.fromTo("#{node_id}-code",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(t["code_dur"])},ease:"power1.out",'
        f'immediateRender:false}},{_num(at + t["code_at"])});')
    line_html: list[str] = []
    for li, line in enumerate(lines):
        toks = "".join(
            f'<span class="pa-tok" style="color:{html.escape(color, quote=True)}">'
            f'{_esc(text)}</span>'
            for text, color in line
        )
        line_html.append(
            f'<span class="pa-line" data-i="{li}" style="height:{line_h}px;'
            f'line-height:{line_h}px">{toks}</span>')
    invert = " invert" if params.get("invert") else ""
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text fs-code-pa'
               f'{invert}" {_timing(ctx)}>'
               f'<span id="{node_id}-stage" class="pa-stage">'
               f'<span class="pa-dust">{"".join(dust)}</span>'
               f'<span id="{node_id}-code" class="pa-code" '
               f'style="width:{cw}px;height:{ch}px;padding:{pad_y}px {pad_x}px;'
               f'font-size:{size}px">{"".join(line_html)}</span>'
               f'</span></div>'],
        tweens=tweens)


_CS_DEFAULT_LINE = 12


def _cs_pick_line(raws: list[str], params: dict[str, Any]) -> int:
    """1-indexed line / target_line, иначе подстрока focus, иначе строка 12."""
    n = len(raws)
    if n <= 0:
        return 0
    raw = params.get("line", params.get("target_line"))
    if isinstance(raw, bool):
        raw = None
    if isinstance(raw, (int, float)):
        return max(0, min(n - 1, int(raw) - 1))
    if isinstance(raw, str) and raw.strip().isdigit():
        return max(0, min(n - 1, int(raw.strip()) - 1))
    focus = str(params.get("focus") or params.get("highlight_line") or "").strip()
    if focus:
        for i, text in enumerate(raws):
            if focus in text:
                return i
    return max(0, min(n - 1, _CS_DEFAULT_LINE - 1))


_CS_SIZE_CEILING = 22


_CS_SIZE_FLOOR = 13


_CS_PAD_TOP = 12


_CS_TITLE_H = 48


_CS_GUTTER = 56


_CS_PAD_X = 16


_CS_LH_EM = 1.55


def _cs_metrics(raws: list[str], frame_w: int, frame_h: int,
                vis: int) -> tuple[int, int, int, int, int]:
    """Карточка короче файла: vis строк в окне, чтобы dy был заметным."""
    vis = max(6, min(int(vis), 16))
    editor_w = min(int(round(frame_w * 0.90)), 980)
    inner_w = max(80, editor_w - _CS_GUTTER - _CS_PAD_X * 2)
    max_chars = max((len(row) for row in raws), default=8)
    max_editor_h = int(round(frame_h * 0.58))
    max_surface = max(120, max_editor_h - _CS_TITLE_H)
    lh_cap = max(18, int((max_surface - _CS_PAD_TOP) / vis))
    font = min(
        _CS_SIZE_CEILING,
        max(_CS_SIZE_FLOOR, int(inner_w / max(max_chars * _C3D_MONO_EM, 8))),
    )
    font = min(font, max(_CS_SIZE_FLOOR, int(lh_cap / _CS_LH_EM)))
    font = max(_CS_SIZE_FLOOR, font)
    lh = max(18, int(round(font * _CS_LH_EM)))
    surface_h = vis * lh + _CS_PAD_TOP
    editor_h = _CS_TITLE_H + surface_h
    if editor_h > max_editor_h:
        extra = editor_h - max_editor_h
        drop = max(1, int(math.ceil(extra / vis)))
        lh = max(18, lh - drop)
        surface_h = vis * lh + _CS_PAD_TOP
        editor_h = _CS_TITLE_H + surface_h
    return font, lh, editor_w, editor_h, surface_h


def _cs_times(duration: float) -> dict[str, float]:
    """Каталог Code Scroll To Line на 6 с: editor 0.50, fade 0.45 с 0.45,
    пауза 0.35, scroll 1.70 с 1.25, дим/прожектор за 0.35 до прибытия.
    """
    d = max(1.5, float(duration))
    enter = 0.50
    fade = 0.45
    gap = 0.35
    scroll = 1.70
    dim_lead = 0.35
    dim_dur = 0.50
    hl_dur = 0.45
    fade_at = 0.45
    packed = fade_at + fade + gap + scroll
    if packed > d - 0.04:
        fit = (d - 0.04) / packed
        enter *= fit
        fade *= fit
        gap *= fit
        scroll *= fit
        dim_lead *= fit
        dim_dur *= fit
        hl_dur *= fit
        fade_at *= fit
    fade_at = round(fade_at, 4)
    enter = round(enter, 4)
    fade = round(fade, 4)
    gap = round(gap, 4)
    scroll = round(scroll, 4)
    dim_lead = round(dim_lead, 4)
    dim_dur = round(dim_dur, 4)
    hl_dur = round(hl_dur, 4)
    scroll_at = round(fade_at + fade + gap, 4)
    arr_at = round(scroll_at + scroll, 4)
    dim_at = round(max(fade_at + fade + 0.02, arr_at - dim_lead), 4)
    end_limit = d - 0.01
    if dim_at + dim_dur > end_limit:
        dim_dur = round(max(0.08, end_limit - dim_at), 4)
    if dim_at + hl_dur > end_limit:
        hl_dur = round(max(0.08, end_limit - dim_at), 4)
    return {
        "enter": enter,
        "fade_at": fade_at,
        "fade": fade,
        "scroll_at": scroll_at,
        "scroll": scroll,
        "arr_at": arr_at,
        "dim_at": dim_at,
        "dim_dur": dim_dur,
        "hl_dur": hl_dur,
    }


_CS_FRAME_W = 1080


_CS_FRAME_H = 1920


_CS_VIS = 14


_CS_DEFAULT_FILE = "fetchWithRetry.js"


_CS_EDITOR_SCALE = 0.985


def _cs_num(value: float) -> str:
    """_num(-0.0) даёт '-0' — линт и GSAP этого не едят."""
    if abs(float(value)) < 5e-4:
        return "0"
    return _num(value)


_CS_DIM = 0.35


def fs_code_scroll(ctx: "TemplateCtx") -> Piece:
    """Камера скроллит файл к целевой строке и подсвечивает её.

    Каталог меряет ``getBoundingClientRect`` после ``fonts.ready``. Здесь
    ``y`` заранее, окно ~14 строк, чтобы на 9:16 сдвиг был виден. Твины на
    ``#…-editor`` / ``#…-scroll`` / строках, не на ``.clip``. JetBrains Mono,
    github-dark и прожектор ``var(--color-muted)`` как в каталоге — это сам жест.
    """
    params = ctx.params
    code = str(params.get("code") or params.get("content") or params.get("text")
               or "").replace("\r\n", "\n").replace("\t", "  ").strip("\n")
    raw_tokens = params.get("tokens")
    token_rows = _cd_rows_from_tokens(raw_tokens)
    if token_rows is not None:
        lines = token_rows
        if not any(piece for line in lines for piece, _color in line):
            return Piece()
    else:
        if not code.strip():
            return Piece()
        lines = _c3d_highlight(code)
    if not lines:
        return Piece()
    raws = ["".join(text for text, _color in line) for line in lines]
    idx = _cs_pick_line(raws, params)
    node_id = ctx.target
    frame_w = int(params.get("frame_w") or _CS_FRAME_W)
    frame_h = int(params.get("frame_h") or _CS_FRAME_H)
    vis = int(params.get("visible_lines") or _CS_VIS)
    size, lh, editor_w, editor_h, surface_h = _cs_metrics(raws, frame_w, frame_h, vis)
    line_center = _CS_PAD_TOP + idx * lh + lh / 2.0
    dy = int(round(surface_h * 0.5 - line_center))
    if abs(dy) < 1:
        dy = 0
    t = _cs_times(ctx.duration)
    at = _enter_at(ctx)
    filename = str(params.get("filename") or _CS_DEFAULT_FILE)
    invert = " invert" if params.get("invert") else ""
    hl_top = _CS_PAD_TOP + idx * lh
    tweens = [
        f'tl.fromTo("#{node_id}-editor",'
        f'{{opacity:0,scale:{_num(_CS_EDITOR_SCALE)}}},'
        f'{{opacity:1,scale:1,duration:{_num(t["enter"])},'
        f'ease:"power2.out"}},{_num(at)});',
        f'tl.fromTo("#{node_id}-scroll",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(t["fade"])},ease:"power1.out"}},'
        f'{_num(at + t["fade_at"])});',
        f'tl.fromTo("#{node_id}-scroll",{{y:0}},'
        f'{{y:{_cs_num(dy)},duration:{_num(t["scroll"])},'
        f'ease:"power2.inOut",immediateRender:false}},'
        f'{_num(at + t["scroll_at"])});',
        f'tl.fromTo("#{node_id}-hl",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(t["hl_dur"])},ease:"power1.out"}},'
        f'{_num(at + t["dim_at"])});',
    ]
    for i in range(len(lines)):
        if i == idx:
            continue
        tweens.append(
            f'tl.fromTo("#{node_id}-ln{i}",{{opacity:1}},'
            f'{{opacity:{_num(_CS_DIM)},duration:{_num(t["dim_dur"])},'
            f'ease:"power1.out"}},{_num(at + t["dim_at"])});')
    gutter_html = "".join(
        f'<span class="cs-gn" style="height:{lh}px;line-height:{lh}px">{i}</span>'
        for i in range(1, len(lines) + 1)
    )
    line_html: list[str] = []
    for i, line in enumerate(lines):
        toks = "".join(
            f'<span class="cs-tok" style="color:{html.escape(color, quote=True)}">'
            f'{_esc(text)}</span>'
            for text, color in line
        )
        line_html.append(
            f'<span id="{node_id}-ln{i}" class="cs-line" '
            f'style="height:{lh}px;line-height:{lh}px">{toks}</span>')
    scroll_h = _CS_PAD_TOP + len(lines) * lh + 8
    code_pl = _CS_GUTTER + 8
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text fs-code-scroll'
               f'{invert}" {_timing(ctx)}>'
               f'<span class="cs-stage">'
               f'<span class="cs-grid"></span>'
               f'<span class="cs-glow cs-glow-a"></span>'
               f'<span class="cs-glow cs-glow-b"></span>'
               f'<span id="{node_id}-editor" class="cs-editor" '
               f'style="width:{editor_w}px;height:{editor_h}px;font-size:{size}px">'
               f'<span class="cs-titlebar"><span class="cs-dots">'
               f'<span class="cs-dot cs-dot-r"></span>'
               f'<span class="cs-dot cs-dot-y"></span>'
               f'<span class="cs-dot cs-dot-g"></span></span>'
               f'<span class="cs-filename"><span class="cs-file">'
               f'{_esc(filename)}</span> — Code Scroll To Line</span></span>'
               f'<span class="cs-surface" style="height:{surface_h}px">'
               f'<span id="{node_id}-scroll" class="cs-scroll" '
               f'style="height:{scroll_h}px">'
               f'<span class="cs-gutter" style="top:{_CS_PAD_TOP}px;'
               f'width:{_CS_GUTTER}px;font-size:{size}px;line-height:{lh}px">'
               f'{gutter_html}</span>'
               f'<span class="cs-code" style="padding:{_CS_PAD_TOP}px '
               f'{_CS_PAD_X}px 8px {code_pl}px">'
               f'<span id="{node_id}-hl" class="cs-hl" '
               f'style="top:{hl_top}px;height:{lh}px"></span>'
               f'{"".join(line_html)}</span></span></span></span></span></div>'],
        tweens=tweens)


_CT_SIZE_CEILING = 26


_CT_TITLE_H = 48


_CT_SIZE_FLOOR = 16


_CT_PAD_TOP = 16


_CT_GUTTER = 56


_CT_PAD_X = 18


_CT_LH_EM = 1.55


def _ct_metrics(raws: list[str], frame_w: int, frame_h: int
                ) -> tuple[int, int, int, int, int]:
    n = max(1, len(raws))
    editor_w = min(int(round(frame_w * 0.90)), 980)
    inner_w = max(80, editor_w - _CT_GUTTER - _CT_PAD_X * 2)
    max_chars = max((len(row) for row in raws), default=8)
    max_editor_h = int(round(frame_h * 0.62))
    max_surface = max(120, max_editor_h - _CT_TITLE_H)
    font = min(
        _CT_SIZE_CEILING,
        max(_CT_SIZE_FLOOR, int(inner_w / max(max_chars * _C3D_MONO_EM, 8))),
    )
    lh = max(22, int(round(font * _CT_LH_EM)))
    while n * lh + _CT_PAD_TOP + 8 > max_surface and font > _CT_SIZE_FLOOR:
        font -= 1
        lh = max(22, int(round(font * _CT_LH_EM)))
    surface_h = n * lh + _CT_PAD_TOP + 8
    editor_h = _CT_TITLE_H + surface_h
    return font, lh, editor_w, editor_h, surface_h


_CT_PER = 0.028


_CT_CHAR_FADE = 0.12


_CT_WS_FADE = 0.01


def _ct_times(duration: float, n_chars: int) -> dict[str, float]:
    """Каталог Code Typing на 5 с: editor 0.50, fade 0.45 с 0.45,
    затем 0.028 с на знак. Если набор не влезает — сжимаем PER.
    """
    d = max(1.5, float(duration))
    n = max(1, int(n_chars))
    enter = 0.50
    fade = 0.45
    fade_at = 0.45
    per = _CT_PER
    char_fade = _CT_CHAR_FADE
    ws_fade = _CT_WS_FADE
    packed = fade_at + fade + n * per
    if packed > d - 0.04:
        fit = (d - 0.04) / packed
        enter *= fit
        fade *= fit
        fade_at *= fit
        per *= fit
        char_fade *= fit
        ws_fade *= fit
    fade_at = round(fade_at, 4)
    enter = round(enter, 4)
    fade = round(fade, 4)
    per = round(per, 5)
    char_fade = round(max(0.04, char_fade), 4)
    ws_fade = round(max(0.008, ws_fade), 4)
    type_at = round(fade_at + fade, 4)
    last_at = type_at + max(0, n - 1) * per
    # Линт считает стык твинов overlap; каретка короче слота на 2 мс,
    # чтобы _num (3 знака) не схлопнул зазор.
    caret_dur = round(max(0.004, per - 0.002), 5)
    if caret_dur >= per - 5e-4:
        caret_dur = round(max(0.003, per * 0.85), 5)
    end_limit = d - 0.01
    if last_at + char_fade > end_limit:
        char_fade = round(max(0.04, end_limit - last_at), 4)
    if last_at + ws_fade > end_limit:
        ws_fade = round(max(0.008, end_limit - last_at), 4)
    return {
        "enter": enter,
        "fade_at": fade_at,
        "fade": fade,
        "type_at": type_at,
        "per": per,
        "caret_dur": caret_dur,
        "char_fade": char_fade,
        "ws_fade": ws_fade,
    }


_CT_FRAME_W = 1080


_CT_FRAME_H = 1920


_CT_DEFAULT_FILE = "loadConfig.js"


def _ct_advance(ch: str, font, em: float) -> float:
    if font is not None:
        try:
            wide = float(font.getlength(ch))
            if wide > 0:
                return wide
        except Exception:                                    # noqa: BLE001
            pass
    return em


_CT_EDITOR_SCALE = 0.985


def _ct_num(value: float) -> str:
    """_num(-0.0) даёт '-0' — линт и GSAP этого не едят."""
    if abs(float(value)) < 5e-4:
        return "0"
    return _num(value)


_CT_CARET_W = 3


def fs_code_typing(ctx: "TemplateCtx") -> Piece:
    """Посимвольный набор с кареткой: каталог меряет DOM.

    Здесь ширина глифа из JetBrains Mono, ``x``/``y`` каретки заранее.
    Твины на ``#…-editor`` / ``#…-scene`` / знаках / каретке, не на
    ``.clip``. github-dark и ``var(--color-muted)`` как в каталоге — это сам жест.
    """
    params = ctx.params
    code = str(params.get("code") or params.get("content") or params.get("text")
               or "").replace("\r\n", "\n").replace("\t", "  ").strip("\n")
    raw_tokens = params.get("tokens")
    token_rows = _cd_rows_from_tokens(raw_tokens)
    if token_rows is not None:
        lines = token_rows
        if not any(piece for line in lines for piece, _color in line):
            return Piece()
    else:
        if not code.strip():
            return Piece()
        lines = _c3d_highlight(code)
    if not lines:
        return Piece()
    glyphs: list[tuple[str, str, int, bool]] = []
    for li, line in enumerate(lines):
        for text, color in line:
            for ch in text:
                glyphs.append((ch, color, li, ch == " "))
    if not glyphs:
        return Piece()
    node_id = ctx.target
    frame_w = int(params.get("frame_w") or _CT_FRAME_W)
    frame_h = int(params.get("frame_h") or _CT_FRAME_H)
    raws = ["".join(text for text, _color in line) for line in lines]
    size, lh, editor_w, editor_h, surface_h = _ct_metrics(raws, frame_w, frame_h)
    pad_left = _CT_GUTTER + 8
    caret_h = max(14, int(round(size * 32 / 30)))
    caret_gap = max(0, int(round((lh - caret_h) / 2)))
    font = _cpa_mono_font(size)
    em = size * _C3D_MONO_EM
    if font is not None:
        try:
            measured = float(font.getlength("M"))
            if measured > 0:
                em = measured
        except Exception:                                    # noqa: BLE001
            pass
    t = _ct_times(ctx.duration, len(glyphs))
    at = _enter_at(ctx)
    filename = str(params.get("filename") or _CT_DEFAULT_FILE)
    invert = " invert" if params.get("invert") else ""
    xs: list[float] = []
    ys: list[float] = []
    rights: list[float] = []
    cursor_x = 0.0
    prev_line = 0
    for ch, _color, li, _ws in glyphs:
        if li != prev_line:
            cursor_x = 0.0
            prev_line = li
        wide = _ct_advance(ch, font, em)
        left = pad_left + cursor_x
        top = _CT_PAD_TOP + li * lh + caret_gap
        xs.append(left)
        ys.append(top)
        rights.append(left + wide)
        cursor_x += wide
    tweens = [
        f'tl.fromTo("#{node_id}-editor",'
        f'{{opacity:0,scale:{_num(_CT_EDITOR_SCALE)}}},'
        f'{{opacity:1,scale:1,duration:{_num(t["enter"])},'
        f'ease:"power2.out"}},{_num(at)});',
        f'tl.fromTo("#{node_id}-scene",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(t["fade"])},ease:"power1.out"}},'
        f'{_num(at + t["fade_at"])});',
    ]
    prev_x, prev_y = xs[0], ys[0]
    type_at = at + t["type_at"]
    for i, (ch, _color, _li, ws) in enumerate(glyphs):
        start = type_at + i * t["per"]
        fade = t["ws_fade"] if ws else t["char_fade"]
        tweens.append(
            f'tl.fromTo("#{node_id}-c{i}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(fade)},ease:"power1.out"}},'
            f'{_num(start)});')
        nx, ny = rights[i], ys[i]
        extra = ',immediateRender:false' if i else ""
        tweens.append(
            f'tl.fromTo("#{node_id}-caret",'
            f'{{x:{_ct_num(prev_x)},y:{_ct_num(prev_y)}}},'
            f'{{x:{_ct_num(nx)},y:{_ct_num(ny)},duration:{_num(t["caret_dur"])},'
            f'ease:"none"{extra}}},{_num(start)});')
        prev_x, prev_y = nx, ny
    gutter_html = "".join(
        f'<span class="ct-gn" style="height:{lh}px;line-height:{lh}px">{i}</span>'
        for i in range(1, len(lines) + 1)
    )
    line_html: list[str] = []
    gi = 0
    for li, line in enumerate(lines):
        pieces: list[str] = []
        n_on_line = sum(len(text) for text, _color in line)
        for _ in range(n_on_line):
            ch, color, _ln, _ws = glyphs[gi]
            pieces.append(
                f'<span id="{node_id}-c{gi}" class="ct-ch" '
                f'style="color:{html.escape(color, quote=True)}">'
                f'{_esc(ch)}</span>')
            gi += 1
        line_html.append(
            f'<span class="ct-line" style="height:{lh}px;line-height:{lh}px">'
            f'{"".join(pieces)}</span>')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text fs-code-typing'
               f'{invert}" {_timing(ctx)}>'
               f'<span class="ct-stage">'
               f'<span class="ct-grid"></span>'
               f'<span class="ct-glow ct-glow-a"></span>'
               f'<span class="ct-glow ct-glow-b"></span>'
               f'<span id="{node_id}-editor" class="ct-editor" '
               f'style="width:{editor_w}px;height:{editor_h}px;font-size:{size}px">'
               f'<span class="ct-titlebar"><span class="ct-dots">'
               f'<span class="ct-dot ct-dot-r"></span>'
               f'<span class="ct-dot ct-dot-y"></span>'
               f'<span class="ct-dot ct-dot-g"></span></span>'
               f'<span class="ct-filename"><span class="ct-file">'
               f'{_esc(filename)}</span> — Code Typing</span></span>'
               f'<span class="ct-surface" style="height:{surface_h}px">'
               f'<span id="{node_id}-scene" class="ct-scene">'
               f'<span class="ct-gutter" style="top:{_CT_PAD_TOP}px;'
               f'width:{_CT_GUTTER}px;font-size:{size}px;line-height:{lh}px">'
               f'{gutter_html}</span>'
               f'<span class="ct-code" style="padding:{_CT_PAD_TOP}px '
               f'{_CT_PAD_X}px 8px {pad_left}px">'
               f'{"".join(line_html)}'
               f'<span id="{node_id}-caret" class="ct-caret" '
               f'style="width:{_CT_CARET_W}px;height:{caret_h}px"></span>'
               f'</span></span></span></span></span></div>'],
        tweens=tweens)


_DP_DEMO: tuple[tuple[tuple[str, str], ...], ...] = (
    (("# A small functional toolkit", "comment"),),
    (("def", "keyword"), (" ", "plain"), ("pluck_deep", "function"),
     ("(", "punctuation"), ("key", "parameter"), ("):", "punctuation")),
    (("    ", "plain"), ("return", "keyword"), (" ", "plain"),
     ("lambda", "keyword"), (" ", "plain"), ("obj", "parameter"),
     (": ", "punctuation"), ("reduce", "function"), ("(", "punctuation"),
     ("lambda", "keyword"), (" ", "plain"), ("acc", "parameter"),
     (", ", "punctuation"), ("k", "parameter"), (": ", "punctuation"),
     ("acc", "variable"), ("[", "punctuation"), ("k", "variable"),
     ("]", "punctuation"), (", ", "punctuation"), ("key", "variable"),
     (".split", "function"), ("(", "punctuation"), ("'.'", "string"),
     ("), ", "punctuation"), ("obj", "variable"), (")", "punctuation")),
    (),
    (("def", "keyword"), (" ", "plain"), ("compose", "function"),
     ("(", "punctuation"), ("*", "operator"), ("fns", "parameter"),
     ("):", "punctuation")),
    (("    ", "plain"), ("return", "keyword"), (" ", "plain"),
     ("lambda", "keyword"), (" ", "plain"), ("res", "parameter"),
     (": ", "punctuation"), ("reduce", "function"), ("(", "punctuation"),
     ("lambda", "keyword"), (" ", "plain"), ("acc", "parameter"),
     (", ", "punctuation"), ("fn", "parameter"), (": ", "punctuation"),
     ("fn", "function"), ("(", "punctuation"), ("acc", "variable"),
     ("), ", "punctuation"), ("fns", "variable"), (", ", "punctuation"),
     ("res", "variable"), (")", "punctuation")),
    (),
    (("def", "keyword"), (" ", "plain"), ("unfold", "function"),
     ("(", "punctuation"), ("f", "parameter"), (", ", "punctuation"),
     ("seed", "parameter"), ("):", "punctuation")),
    (("    ", "plain"),
     ('"""Build a list by repeatedly applying f to a seed."""', "string")),
    (("    acc", "variable"), (" = ", "operator"), ("[]", "punctuation")),
    (("    while", "keyword"), (" ", "plain"), ("True", "class-name"),
     (":", "punctuation")),
    (("        result", "variable"), (" = ", "operator"), ("f", "function"),
     ("(", "punctuation"), ("seed", "variable"), (")", "punctuation")),
    (("        if", "keyword"), (" ", "plain"), ("result", "variable"),
     (" is ", "keyword"), ("None", "class-name"), (":", "punctuation")),
    (("            return", "keyword"), (" ", "plain"),
     ("acc", "variable")),
    (("        acc", "variable"), (".append", "function"),
     ("(", "punctuation"), ("result", "variable"), ("[", "punctuation"),
     ("0", "number"), ("])", "punctuation")),
    (("        seed", "variable"), (" = ", "operator"),
     ("result", "variable"), ("[", "punctuation"), ("1", "number"),
     ("]", "punctuation")),
    (),
)


_DP_FILE = "functional_toolkit.py"


def _dp_kind(text: str, color: str) -> str:
    if color == _C3D_KW_COLOR:
        return "keyword"
    if color == _C3D_FN_COLOR:
        return "function"
    if color == _C3D_STR_COLOR:
        return "string"
    if color == _C3D_CMT_COLOR:
        return "comment"
    if color == _C3D_PARAM_COLOR:
        return "parameter"
    if color == _C3D_VAR_COLOR:
        stripped = text.strip()
        if stripped[:1].isdigit():
            return "number"
        return "variable"
    stripped = text.strip()
    if stripped and not any(ch.isalnum() or ch == "_" for ch in stripped):
        return "punctuation"
    return "plain"


def _dp_lines(params: dict[str, Any], code: str
              ) -> tuple[list[list[tuple[str, str]]], str]:
    text = code.strip("\n")
    if not text.strip():
        return [list(line) for line in _DP_DEMO], str(params.get("filename") or _DP_FILE)
    rows = _c3d_highlight(text)
    lines = [[(piece, _dp_kind(piece, color)) for piece, color in row]
             for row in rows]
    return lines, str(params.get("filename") or "snippet.py")


_DP_SIZE_CEILING = 18


_DP_SIZE_FLOOR = 12


def _dp_metrics(raws: list[str], frame_w: int, frame_h: int) -> dict[str, int]:
    pad_x = 24
    pad_y = 28
    header_h = 78
    gap = 12
    wb_w = max(640, frame_w - pad_x * 2)
    wb_h = min(int(round(frame_h * 0.78)), frame_h - pad_y * 2 - header_h - gap)
    activity = 44
    sidebar = min(168, max(120, int(round(wb_w * 0.20))))
    editor_w = max(280, wb_w - activity - sidebar)
    title_h, status_h, tab_h, crumb_h, term_h = 32, 24, 32, 24, 96
    longest = max((len(row) for row in raws), default=8)
    n = max(1, len(raws))
    inner = max(80, editor_w - 56)
    size = _DP_SIZE_CEILING
    lh = max(20, int(round(size * 1.52)))
    gutter = max(40, int(round(size * 72 / 18)))
    pad_top = max(10, int(round(size * 20 / 18)))
    editor_h = wb_h - title_h - status_h - tab_h - crumb_h - term_h
    while (longest * size * _C3D_MONO_EM > inner
            or n * lh + pad_top + 8 > editor_h) and size > _DP_SIZE_FLOOR:
        size -= 1
        lh = max(18, int(round(size * 1.52)))
        gutter = max(36, int(round(size * 72 / 18)))
        pad_top = max(8, int(round(size * 20 / 18)))
    caret_h = max(12, int(round(size * 22 / 18)))
    return {
        "wb_w": wb_w, "wb_h": wb_h, "activity": activity, "sidebar": sidebar,
        "title_h": title_h, "status_h": status_h, "tab_h": tab_h,
        "crumb_h": crumb_h, "term_h": term_h, "size": size, "lh": lh,
        "gutter": gutter, "pad_top": pad_top, "caret_h": caret_h,
        "header_h": header_h, "pad_x": pad_x, "pad_y": pad_y,
    }


_DP_HDR_DUR = 0.45


_DP_WB_AT = 0.10


_DP_WB_DUR = 0.58


_DP_HL_AT = 0.74


_DP_HL_DUR = 0.22


_DP_TYPE_AT = 0.95


_DP_CHAR_PER = 0.012


_DP_LINE_MIN = 0.08


_DP_LINE_GAP = 0.045


_DP_TERM_AT = 7.55


_DP_TERM_DUR = 0.56


_DP_TB_AT = 8.05


_DP_TB_DUR = 0.24


_DP_TB_STAGGER = 0.16


_DP_TILT_AT = 9.35


_DP_TILT_DUR = 0.72


_DP_UNTILT_AT = 10.08


_DP_UNTILT_DUR = 0.62


_DP_CATALOG_END = 10.70


def _dp_times(duration: float, line_ns: list[int]) -> dict[str, Any]:
    """Каталог на 11 с: набор с 0.95, терминал 7.55, наклон 9.35."""
    d = max(2.0, float(duration))
    hdr_dur = _DP_HDR_DUR
    wb_at = _DP_WB_AT
    wb_dur = _DP_WB_DUR
    hl_at = _DP_HL_AT
    hl_dur = _DP_HL_DUR
    type_at = _DP_TYPE_AT
    char_per = _DP_CHAR_PER
    line_min = _DP_LINE_MIN
    line_gap = _DP_LINE_GAP
    term_at = _DP_TERM_AT
    term_dur = _DP_TERM_DUR
    tb_at = _DP_TB_AT
    tb_dur = _DP_TB_DUR
    tb_stagger = _DP_TB_STAGGER
    tilt_at = _DP_TILT_AT
    tilt_dur = _DP_TILT_DUR
    untilt_at = _DP_UNTILT_AT
    untilt_dur = _DP_UNTILT_DUR
    packed = _DP_CATALOG_END
    if packed > d - 0.04:
        fit = (d - 0.04) / packed
        hdr_dur *= fit
        wb_at *= fit
        wb_dur *= fit
        hl_at *= fit
        hl_dur *= fit
        type_at *= fit
        char_per *= fit
        line_min *= fit
        line_gap *= fit
        term_at *= fit
        term_dur *= fit
        tb_at *= fit
        tb_dur *= fit
        tb_stagger *= fit
        tilt_at *= fit
        tilt_dur *= fit
        untilt_at *= fit
        untilt_dur *= fit
    char_per = max(0.004, char_per)
    caret_dur = round(max(0.003, char_per - 0.002), 5)
    if caret_dur >= char_per - 5e-4:
        caret_dur = round(max(0.003, char_per * 0.7), 5)
    char_fade = round(max(0.003, min(0.01, char_per * 0.6)), 5)
    line_at: list[float] = []
    char_at: list[float] = []
    cursor = type_at
    for n in line_ns:
        line_at.append(round(cursor, 5))
        for i in range(int(n)):
            char_at.append(round(cursor + i * char_per, 5))
        cursor += max(n * char_per, line_min) + line_gap
    if untilt_at < tilt_at + tilt_dur + 0.001:
        untilt_at = tilt_at + tilt_dur + 0.001
    return {
        "hdr_dur": round(hdr_dur, 4),
        "wb_at": round(wb_at, 4),
        "wb_dur": round(wb_dur, 4),
        "hl_at": round(hl_at, 4),
        "hl_dur": round(hl_dur, 4),
        "type_at": round(type_at, 4),
        "char_per": round(char_per, 5),
        "caret_dur": caret_dur,
        "char_fade": char_fade,
        "line_at": line_at,
        "char_at": char_at,
        "term_at": round(term_at, 4),
        "term_dur": round(term_dur, 4),
        "tb_at": round(tb_at, 4),
        "tb_dur": round(tb_dur, 4),
        "tb_stagger": round(tb_stagger, 4),
        "tilt_at": round(tilt_at, 4),
        "tilt_dur": round(tilt_dur, 4),
        "untilt_at": round(untilt_at, 4),
        "untilt_dur": round(untilt_dur, 4),
    }


_DP_TERM_LINES = (
    ("functional-toolkit %", "python -m pytest"),
    ("", "collected 3 items"),
    ("", "tests/test_toolkit.py ... passed"),
)


_DP_FRAME_W = 1080


_DP_FRAME_H = 1920


_DP_TILT_X = 22


_DP_TILT_ROT = -5.5


_DP_KICKER = "Official VS Code built-in theme"


_DP_LABEL = "Dark+"


_DP_TITLE = "functional-toolkit - Visual Studio Code"


def fs_dark_plus(ctx: "TemplateCtx") -> Piece:
    """VS Code Dark+: каталог меряет DOM и крутит rotateY.

    Здесь ширина глифа из JetBrains Mono, заранее x/y каретки, наклон —
    ``rotation``/``x``. Твины на хроме / знаках / каретке, не на ``.clip``.
    Цвета Dark+ и ``var(--color-panel)`` как в каталоге — жест темы, не палитра канала.
    """
    params = ctx.params
    code = str(params.get("code") or params.get("content") or params.get("text")
               or "").replace("\r\n", "\n").replace("\t", "  ")
    lines, filename = _dp_lines(params, code)
    if not lines:
        return Piece()
    raws = ["".join(text for text, _kind in line) for line in lines]
    glyphs: list[tuple[str, str, int]] = []
    line_ns: list[int] = []
    for li, line in enumerate(lines):
        n = 0
        for text, kind in line:
            for ch in text:
                glyphs.append((ch, kind, li))
                n += 1
        line_ns.append(n)
    node_id = ctx.target
    frame_w = int(params.get("frame_w") or _DP_FRAME_W)
    frame_h = int(params.get("frame_h") or _DP_FRAME_H)
    m = _dp_metrics(raws, frame_w, frame_h)
    t = _dp_times(ctx.duration, line_ns)
    at = _enter_at(ctx)
    invert = " invert" if params.get("invert") else ""
    font = _cpa_mono_font(m["size"])
    em = m["size"] * _C3D_MONO_EM
    if font is not None:
        try:
            measured = float(font.getlength("M"))
            if measured > 0:
                em = measured
        except Exception:                                    # noqa: BLE001
            pass
    xs: list[float] = []
    ys: list[float] = []
    cursor_x = 0.0
    prev_li = 0
    for ch, _kind, li in glyphs:
        if li != prev_li:
            cursor_x = 0.0
            prev_li = li
        wide = _ct_advance(ch, font, em)
        xs.append(m["gutter"] + cursor_x + 2)
        ys.append(m["pad_top"] + li * m["lh"] + 3)
        cursor_x += wide
    origin_x = m["gutter"]
    origin_y = m["pad_top"] + 3
    tweens = [
        f'tl.fromTo("#{node_id}-hdr",{{opacity:0,y:24}},'
        f'{{opacity:1,y:0,duration:{_num(t["hdr_dur"])},'
        f'ease:"power3.out"}},{_num(at)});',
        f'tl.fromTo("#{node_id}-wb",'
        f'{{opacity:0,y:42,scale:0.986}},'
        f'{{opacity:1,y:0,scale:1,duration:{_num(t["wb_dur"])},'
        f'ease:"power3.out"}},{_num(at + t["wb_at"])});',
        f'tl.fromTo("#{node_id}-hl",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(t["hl_dur"])},ease:"power2.out"}},'
        f'{_num(at + t["hl_at"])});',
        f'tl.set("#{node_id}-caret",{{x:{_ct_num(origin_x)},'
        f'y:{_ct_num(origin_y)}}},{_num(at)});',
    ]
    prev_y = 0
    for i, when in enumerate(t["line_at"]):
        dest = i * m["lh"]
        if i == 0:
            continue
        tweens.append(
            f'tl.fromTo("#{node_id}-hl",{{y:{_ct_num(prev_y)}}},'
            f'{{y:{_ct_num(dest)},duration:0.03,ease:"none",'
            f'immediateRender:false}},{_num(at + when)});')
        prev_y = dest
    prev_x = origin_x
    prev_cy = origin_y
    prev_li = 0
    for i, ((ch, _kind, li), when) in enumerate(zip(glyphs, t["char_at"])):
        if li != prev_li:
            dest_x = origin_x
            dest_y = m["pad_top"] + li * m["lh"] + 3
            tweens.append(
                f'tl.fromTo("#{node_id}-caret",'
                f'{{x:{_ct_num(prev_x)},y:{_ct_num(prev_cy)}}},'
                f'{{x:{_ct_num(dest_x)},y:{_ct_num(dest_y)},duration:0.001,'
                f'ease:"none",immediateRender:false}},'
                f'{_num(at + t["line_at"][li])});')
            prev_x, prev_cy = dest_x, dest_y
            prev_li = li
        fade = t["char_fade"]
        tweens.append(
            f'tl.fromTo("#{node_id}-c{i}",{{opacity:0}},'
            f'{{opacity:1,duration:{_ct_num(fade)},ease:"none"}},'
            f'{_num(at + when)});')
        caret_start = at + when + 0.002
        tweens.append(
            f'tl.fromTo("#{node_id}-caret",'
            f'{{x:{_ct_num(prev_x)},y:{_ct_num(prev_cy)}}},'
            f'{{x:{_ct_num(xs[i])},y:{_ct_num(ys[i])},'
            f'duration:{_ct_num(t["caret_dur"])},ease:"none",'
            f'immediateRender:false}},{_num(caret_start)});')
        prev_x, prev_cy = xs[i], ys[i]
    last_char = (t["char_at"][-1] if t["char_at"] else t["type_at"])
    blink0 = last_char + 0.08
    blink_gap = 0.40
    blink_dur = 0.05
    hold_limit = ctx.duration - 0.04
    if at + blink0 + 5 * blink_gap + blink_dur > ctx.start + hold_limit:
        span = max(0.3, (ctx.start + hold_limit) - (at + blink0))
        blink_gap = max(0.08, span / 6)
        blink_dur = min(0.05, blink_gap - 0.002)
    for i in range(6):
        start = at + blink0 + i * blink_gap
        going_off = i % 2 == 0
        fr, to = (1, 0) if going_off else (0, 1)
        extra = ",immediateRender:false" if i else ""
        tweens.append(
            f'tl.fromTo("#{node_id}-caret",{{opacity:{fr}}},'
            f'{{opacity:{to},duration:{_ct_num(blink_dur)},ease:"none"'
            f'{extra}}},{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{node_id}-term",{{opacity:0,y:140}},'
        f'{{opacity:1,y:0,duration:{_num(t["term_dur"])},'
        f'ease:"power3.out"}},{_num(at + t["term_at"])});')
    for i in range(3):
        tweens.append(
            f'tl.fromTo("#{node_id}-tb{i}",{{opacity:0,y:8}},'
            f'{{opacity:1,y:0,duration:{_num(t["tb_dur"])},'
            f'ease:"power2.out"}},{_num(at + t["tb_at"] + i * t["tb_stagger"])});')
    tweens.append(
        f'tl.fromTo("#{node_id}-wb",{{rotation:0,x:0}},'
        f'{{rotation:{_num(_DP_TILT_ROT)},x:{_DP_TILT_X},'
        f'duration:{_num(t["tilt_dur"])},ease:"power2.inOut",'
        f'immediateRender:false}},{_num(at + t["tilt_at"])});')
    tweens.append(
        f'tl.fromTo("#{node_id}-wb",'
        f'{{rotation:{_num(_DP_TILT_ROT)},x:{_DP_TILT_X}}},'
        f'{{rotation:0,x:0,duration:{_num(t["untilt_dur"])},'
        f'ease:"power2.inOut",immediateRender:false}},'
        f'{_num(at + t["untilt_at"])});')
    idx = 0
    lines_html: list[str] = []
    for li, line in enumerate(lines):
        bits: list[str] = []
        for text, kind in line:
            cls = "" if kind in ("", "plain") else f" dp-tok-{kind}"
            for ch in text:
                bits.append(
                    f'<span id="{node_id}-c{idx}" class="dp-ch{cls}">'
                    f'{_esc(ch)}</span>')
                idx += 1
        if not bits:
            bits.append(" ")
        lines_html.append(
            f'<span class="dp-line" style="height:{m["lh"]}px;'
            f'grid-template-columns:{m["gutter"]}px 1fr">'
            f'<span class="dp-ln">{li + 1}</span>'
            f'<span class="dp-code">{"".join(bits)}</span></span>')
    source = (
        f'Typing `{_esc(filename)}` with workbench colors from '
        f'<span class="dp-src">dark_plus.json</span>.')
    term_rows = []
    for i, (prompt, rest) in enumerate(_DP_TERM_LINES):
        prompt_html = (f'<span class="dp-prompt">{_esc(prompt)}</span> '
                       if prompt else "")
        extra = ""
        if "passed" in rest:
            body, _, tail = rest.rpartition(" ")
            extra = f'{_esc(body)} <span class="dp-tok-comment">{_esc(tail)}</span>'
        else:
            extra = _esc(rest)
        term_rows.append(
            f'<span id="{node_id}-tb{i}" class="dp-tb">{prompt_html}{extra}</span>')
    icons = (
        '<svg class="dp-icon dp-icon-on" viewBox="0 0 24 24" aria-hidden="true">'
        '<path fill="currentColor" d="M4 4h7v7H4V4Zm9 0h7v7h-7V4ZM4 13h7v7H4v-7Zm9 0h7v7h-7v-7Z"/>'
        '</svg>'
        '<svg class="dp-icon" viewBox="0 0 24 24" aria-hidden="true">'
        '<path fill="none" stroke="currentColor" stroke-width="2" '
        'd="m21 21-5.2-5.2M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z"/>'
        '</svg>'
        '<svg class="dp-icon" viewBox="0 0 24 24" aria-hidden="true">'
        '<path fill="none" stroke="currentColor" stroke-width="2" '
        'd="M8 18 3 12l5-6m8 12 5-6-5-6"/>'
        '</svg>'
        '<svg class="dp-icon" viewBox="0 0 24 24" aria-hidden="true">'
        '<path fill="none" stroke="currentColor" stroke-width="2" '
        'd="M12 3v18m0-18 6 6m-6-6L6 9m6 12 6-6m-6 6-6-6"/>'
        '</svg>'
    )
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text '
               f'fs-dark-plus{invert}" {_timing(ctx)}>'
               f'<span class="dp-stage" style="padding:{m["pad_y"]}px {m["pad_x"]}px">'
               f'<span id="{node_id}-hdr" class="dp-header">'
               f'<span class="dp-head-l"><span class="dp-kicker">{_esc(_DP_KICKER)}</span>'
               f'<span class="dp-title">{_esc(_DP_LABEL)}</span></span>'
               f'<span class="dp-note">{source}</span></span>'
               f'<span id="{node_id}-wb" class="dp-wb" style="width:{m["wb_w"]}px;'
               f'height:{m["wb_h"]}px;grid-template-columns:{m["activity"]}px '
               f'{m["sidebar"]}px 1fr;grid-template-rows:{m["title_h"]}px 1fr '
               f'{m["status_h"]}px">'
               f'<span class="dp-titlebar">'
               f'<span class="dp-traffic"><span></span><span></span><span></span></span>'
               f'<span class="dp-wintitle">{_esc(_DP_TITLE)}</span>'
               f'<span class="dp-search">Search</span></span>'
               f'<span class="dp-activity">{icons}</span>'
               f'<span class="dp-sidebar"><span class="dp-side-title">Explorer</span>'
               f'<span class="dp-sec">⌄ Functional Toolkit</span>'
               f'<span class="dp-tree">'
               f'<span class="dp-row">⌄ src</span>'
               f'<span class="dp-row dp-child dp-sel">◇ {_esc(filename)}</span>'
               f'<span class="dp-row dp-child">◇ test_toolkit.py</span>'
               f'<span class="dp-row">◇ pyproject.toml</span>'
               f'<span class="dp-row">◇ README.md</span></span></span>'
               f'<span class="dp-editor-area" style="grid-template-rows:{m["tab_h"]}px '
               f'{m["crumb_h"]}px 1fr {m["term_h"]}px">'
               f'<span class="dp-tabs"><span class="dp-tab">◇ {_esc(filename)}</span>'
               f'<span class="dp-tab dp-tab-off">README.md</span></span>'
               f'<span class="dp-crumbs">functional-toolkit › src › {_esc(filename)}</span>'
               f'<span class="dp-editor" style="font-size:{m["size"]}px">'
               f'<span id="{node_id}-hl" class="dp-hl" style="top:{m["pad_top"]}px;'
               f'height:{m["lh"]}px"></span>'
               f'<span class="dp-col" style="padding:{m["pad_top"]}px 12px 8px 0">'
               f'{"".join(lines_html)}</span>'
               f'<span id="{node_id}-caret" class="dp-caret" '
               f'style="width:2px;height:{m["caret_h"]}px"></span></span>'
               f'<span id="{node_id}-term" class="dp-term">'
               f'<span class="dp-ptabs"><span class="dp-pon">Terminal</span>'
               f'<span>Problems</span><span>Output</span></span>'
               f'<span class="dp-tbody">{"".join(term_rows)}</span></span></span>'
               f'<span class="dp-status"><span class="dp-stat-l">'
               f'<span class="dp-remote">main</span><span>0 errors</span>'
               f'<span>0 warnings</span></span>'
               f'<span class="dp-stat-r"><span>Ln 17, Col 1</span>'
               f'<span>Spaces: 4</span><span>UTF-8</span></span></span>'
               f'</span></span></div>'],
        tweens=tweens)


_SAZ_STAGGER = 0.06


_SAZ_SIGN = {"in": 1.0, "out": -1.0}


_SAZ_REACH = {"shallow": 0.5, "standard": 1.0, "deep": 1.85}


_SAZ_TONES = ("ink", "paper", "accent")


_SAZ_SCALE_FROM = 0.72


def _saz_start_scale(direction: str, depth: str) -> float:
    """Старт scale: 1 + (0.72 - 1) * sign * reach. На покое всегда 1."""
    sign = _SAZ_SIGN.get(direction, 1.0)
    reach = _SAZ_REACH.get(depth, 1.0)
    return 1.0 + (_SAZ_SCALE_FROM - 1.0) * (sign * reach)


_SAZ_GAP_PX = 12.0


_SAZ_REF_SIZE = 56.0


def _saz_size_and_gap(ctx: "TemplateCtx", words: list[str]) -> tuple[int, int]:
    """Кегль и gap, чтобы слова остались в один ряд, как inline-flex каталога."""
    ceiling = _fs_ceiling(ctx)
    available = float(ctx.params.get("available_px") or 900) * 0.94
    gap_ratio = _SAZ_GAP_PX / _SAZ_REF_SIZE
    n = len(words)
    size = ceiling
    while size > 24:
        gap = gap_ratio * size
        total = sum(text_width(w, size) for w in words) + gap * max(0, n - 1)
        if total <= available:
            break
        size -= 2
    return size, max(1, int(round(gap_ratio * size)))


_SAZ_ENTER = 0.34


def fs_shared_axis_z(ctx: "TemplateCtx") -> Piece:
    """Слова набухают по оси Z — shared-axis-z.

    Каталог твинит ``--hf-word-scale`` и пишет глубину в CSS-var. Здесь
    стартовый ``scale`` заранее: ``1 + (0.72-1) * sign * reach``.
    Inter 900 и ``var(--color-ink)`` как в каталоге; ``tone=accent`` → ``var(--color-accent)``,
    не изумруд ``var(--color-accent)``. Стаггер 60 мс разложен в Python. HOLD без ухода.
    """
    content = str(ctx.params.get("text") or ctx.params.get("content") or "").strip()
    if not content:
        return Piece()
    words = content.split()
    if not words:
        return Piece()

    direction = str(ctx.params.get("direction") or "in").lower()
    if direction not in _SAZ_SIGN:
        direction = "in"
    depth = str(ctx.params.get("depth") or "standard").lower()
    if depth not in _SAZ_REACH:
        depth = "standard"
    tone = str(ctx.params.get("tone") or "ink").lower()
    if tone not in _SAZ_TONES:
        tone = "ink"

    start_scale = _saz_start_scale(direction, depth)
    node_id = ctx.target
    size, gap = _saz_size_and_gap(ctx, words)
    stagger = _SAZ_STAGGER
    at = _enter_at(ctx)
    end = ctx.start + ctx.duration
    n = len(words)
    last_end = at + _SAZ_ENTER + stagger * max(0, n - 1)
    if n > 1 and last_end > end - 0.04:
        stagger = max(0.02, (end - 0.04 - at - _SAZ_ENTER) / (n - 1))

    cls = f"clip fullscreen-text fs-shared-axis-z saz-{tone}"
    spans: list[str] = []
    tweens: list[str] = []
    for i, word in enumerate(words):
        wid = f"{node_id}-w{i}"
        spans.append(f'<span id="{wid}" class="saz-word">{_esc(word)}</span>')
        word_at = at + stagger * i
        tweens.append(
            f'tl.fromTo("#{wid}",{{opacity:0,scale:{_num(start_scale)}}},'
            f'{{opacity:1,scale:1,duration:{_num(_SAZ_ENTER)},'
            f'ease:"back.out(1.8)"}},{_num(word_at)});'
        )

    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)} '
               f'data-saz-direction="{direction}" data-saz-depth="{depth}">'
               f'<span id="{node_id}-inner" class="saz-stack" '
               f'style="font-size:{size}px;gap:{gap}px">'
               f'{"".join(spans)}</span></div>'],
        tweens=tweens)


_TS_DEFAULT_CMD = "$ hyperframes render --skill=terminal-simulator"


def _ts_command(params: dict[str, Any], code: str) -> str:
    raw = str(params.get("command") or code or "").replace("\r\n", "\n").strip()
    if not raw:
        return _TS_DEFAULT_CMD
    first = raw.split("\n", 1)[0].strip()
    if not first.startswith("$"):
        first = f"$ {first}"
    return first


_TS_DEFAULT_FILES = ("index.html", "style.css", "timeline.js")


def _ts_files(params: dict[str, Any]) -> list[str]:
    raw = params.get("files")
    names: list[str] = []
    if isinstance(raw, str):
        blob = raw.replace(",", "\n")
        names = [ln.strip() for ln in blob.split("\n") if ln.strip()]
    elif isinstance(raw, (list, tuple)):
        names = [str(item).strip() for item in raw if str(item).strip()]
    return names or list(_TS_DEFAULT_FILES)


_TS_TERM_H = 78


_TS_CHROME_H = 48


_TS_BODY_H = 340


_TS_CATALOG_W = 760


_TS_FILES_W = 210


_TS_RADIUS = 24


_TS_LINE_H = 18


_TS_LINE_GAP = 14


_TS_PAD = 22


_TS_DOT = 11


_TS_CHROME_SIZE = 14


_TS_BODY_SIZE = 15


_TS_TERM_Y = 16


def _ts_metrics(frame_w: int, frame_h: int) -> dict[str, int]:
    catalog_h = _TS_CHROME_H + _TS_BODY_H + _TS_TERM_H
    scale = min(frame_w * 0.90 / _TS_CATALOG_W, frame_h * 0.55 / catalog_h)
    scale = max(0.85, min(1.45, scale))

    def px(catalog: float) -> int:
        return max(1, int(round(catalog * scale)))

    return {
        "card_w": px(_TS_CATALOG_W),
        "chrome_h": px(_TS_CHROME_H),
        "body_h": px(_TS_BODY_H),
        "term_h": px(_TS_TERM_H),
        "files_w": px(_TS_FILES_W),
        "radius": px(_TS_RADIUS),
        "line_h": px(_TS_LINE_H),
        "line_gap": px(_TS_LINE_GAP),
        "pad": px(_TS_PAD),
        "dot": px(_TS_DOT),
        "chrome_size": px(_TS_CHROME_SIZE),
        "body_size": px(_TS_BODY_SIZE),
        "term_y": px(_TS_TERM_Y),
        "shadow_y": px(28),
        "shadow_blur": px(80),
    }


_TS_START = 0.50


_TS_LINE_DUR = 0.24


_TS_LINE_STAGGER = 0.08


_TS_TERM_DELAY = 0.48


_TS_TERM_DUR = 0.34


def _ts_times(duration: float) -> dict[str, float]:
    """Каталог: строки с 0.50, 0.24 с, стаггер 0.08; терминал с 0.98."""
    d = max(1.5, float(duration))
    start = _TS_START
    line_dur = _TS_LINE_DUR
    stagger = _TS_LINE_STAGGER
    term_delay = _TS_TERM_DELAY
    term_dur = _TS_TERM_DUR
    packed = start + term_delay + term_dur
    if packed > d - 0.04:
        fit = (d - 0.04) / packed
        start *= fit
        line_dur *= fit
        stagger *= fit
        term_delay *= fit
        term_dur *= fit
    return {
        "start": round(start, 4),
        "line_dur": round(line_dur, 4),
        "stagger": round(stagger, 4),
        "term_delay": round(term_delay, 4),
        "term_dur": round(term_dur, 4),
        "term_at": round(start + term_delay, 4),
    }


_TS_N_LINES = 5


_TS_DEFAULT_TITLE = "Terminal Simulator"


_TS_FRAME_W = 1080


_TS_FRAME_H = 1920


def _ts_num(value: float) -> str:
    """_num(-0.0) даёт '-0' — линт и GSAP этого не едят."""
    if abs(float(value)) < 5e-4:
        return "0"
    return _num(value)


_TS_LINE_WIDTHS = (92, 72, 84, 58, 78)


def fs_terminal_simulator(ctx: "TemplateCtx") -> Piece:
    """Окно IDE: скелет строк и команда. Каталог твинит CSS-var.

    Здесь ``scaleX``/``opacity`` на полосках и ``y`` терминала, не на
    ``.clip``. Сланец ``var(--color-space-deep)`` и зелёный ``var(--color-accent-soft)`` как в каталоге —
    это жест терминала, не палитра канала.
    """
    params = ctx.params
    code = str(params.get("code") or params.get("content") or params.get("text")
               or "").replace("\r\n", "\n").replace("\t", "  ").strip("\n")
    command = _ts_command(params, code)
    files = _ts_files(params)
    title = str(params.get("title") or _TS_DEFAULT_TITLE)
    node_id = ctx.target
    frame_w = int(params.get("frame_w") or _TS_FRAME_W)
    frame_h = int(params.get("frame_h") or _TS_FRAME_H)
    m = _ts_metrics(frame_w, frame_h)
    t = _ts_times(ctx.duration)
    at = _enter_at(ctx)
    invert = " invert" if params.get("invert") else ""
    tweens: list[str] = []
    for i in range(_TS_N_LINES):
        start = at + t["start"] + i * t["stagger"]
        tweens.append(
            f'tl.fromTo("#{node_id}-l{i}",{{scaleX:0,opacity:0}},'
            f'{{scaleX:1,opacity:1,duration:{_num(t["line_dur"])},'
            f'ease:"power2.out"}},{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{node_id}-term",{{opacity:0,y:{_ts_num(m["term_y"])}}},'
        f'{{opacity:1,y:0,duration:{_num(t["term_dur"])},ease:"power2.out"}},'
        f'{_num(at + t["term_at"])});')
    lines_html = "".join(
        f'<span id="{node_id}-l{i}" class="ts-line" '
        f'style="width:{_TS_LINE_WIDTHS[i]}%;height:{m["line_h"]}px"></span>'
        for i in range(_TS_N_LINES)
    )
    files_html = "<br />".join(_esc(name) for name in files)
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text '
               f'fs-terminal-simulator{invert}" {_timing(ctx)}>'
               f'<span class="ts-stage">'
               f'<span class="ts-card" style="width:{m["card_w"]}px;'
               f'border-radius:{m["radius"]}px;'
               f'box-shadow:0 {m["shadow_y"]}px {m["shadow_blur"]}px '
               f'rgba(11,19,43,0.2)">'
               f'<span class="ts-chrome" style="height:{m["chrome_h"]}px;'
               f'font-size:{m["chrome_size"]}px">'
               f'<span class="ts-dots" style="gap:{max(6, m["dot"] - 3)}px">'
               f'<span class="ts-dot ts-dot-r" style="width:{m["dot"]}px;'
               f'height:{m["dot"]}px"></span>'
               f'<span class="ts-dot ts-dot-y" style="width:{m["dot"]}px;'
               f'height:{m["dot"]}px"></span>'
               f'<span class="ts-dot ts-dot-g" style="width:{m["dot"]}px;'
               f'height:{m["dot"]}px"></span></span>'
               f'<span class="ts-title">{_esc(title)}</span></span>'
               f'<span class="ts-body" style="min-height:{m["body_h"]}px;'
               f'grid-template-columns:{m["files_w"]}px 1fr">'
               f'<span class="ts-files" style="padding:{m["pad"]}px;'
               f'font-size:{m["body_size"]}px">{files_html}</span>'
               f'<span class="ts-editor" style="padding:{m["pad"]}px;'
               f'gap:{m["line_gap"]}px">{lines_html}</span></span>'
               f'<span id="{node_id}-term" class="ts-term" '
               f'style="min-height:{m["term_h"]}px;font-size:{m["body_size"]}px;'
               f'padding:{max(12, int(round(m["pad"] * 0.82)))}px {m["pad"]}px '
               f'{m["pad"]}px">{_esc(command)}</span>'
               f'</span></span></div>'],
        tweens=tweens)


_LT_AU_NAME_CEILING = 72


_LT_AU_ROLE_SIZE = 26


def _lt_au_times(duration: float) -> dict[str, float]:
    """Вход как в каталоге; выход прижат к концу, если окно короче 4.8 с."""
    name_in_at, name_in_dur = 0.10, 0.55
    rule_in_at, rule_in_dur = 0.30, 0.50
    role_in_at, role_in_dur = 0.46, 0.50
    role_out_dur, rule_out_dur, name_out_dur = 0.30, 0.30, 0.32
    role_out_lead, rule_out_lead, name_out_lead = 0.55, 0.50, 0.45
    enter_end = role_in_at + role_in_dur
    first_out = duration - role_out_lead
    if first_out < enter_end + 0.001:
        room = max(0.35, first_out - 0.001)
        scale = room / enter_end
        name_in_at *= scale
        name_in_dur *= scale
        rule_in_at *= scale
        rule_in_dur *= scale
        role_in_at *= scale
        role_in_dur *= scale
        enter_end = role_in_at + role_in_dur
    role_out_at = max(enter_end + 0.001, duration - role_out_lead)
    rule_out_at = max(role_out_at + 0.001, duration - rule_out_lead)
    name_out_at = max(rule_out_at + 0.001, duration - name_out_lead)
    return {
        "name_in_at": name_in_at, "name_in_dur": name_in_dur,
        "rule_in_at": rule_in_at, "rule_in_dur": rule_in_dur,
        "role_in_at": role_in_at, "role_in_dur": role_in_dur,
        "role_out_at": role_out_at, "role_out_dur": role_out_dur,
        "rule_out_at": rule_out_at, "rule_out_dur": rule_out_dur,
        "name_out_at": name_out_at, "name_out_dur": name_out_dur,
    }


_LT_AU_NAME_FROM_Y = 28


_LT_AU_NAME_EXIT_Y = -16


_LT_AU_ROLE_FROM_Y = 16


def ov_lt_accent_underline(ctx: "TemplateCtx") -> Piece:
    """Нижняя треть без карточки: имя, акцентная черта left→right, роль.

    Каталог твинит ``tl.to`` после ``gsap.set`` и прячет обёртку через
    ``visibility``. Движок требует ``fromTo`` на вложенных узлах; ``visibility``
    вне списка. Мятный ``var(--color-accent)`` — чужой бренд, черта канала ``var(--color-accent)``.
    Oswald и Space Mono как в каталоге. Клип в потоке: абсолютный единственный
    ребёнок обнуляет paint-box.
    """
    params = ctx.params
    name = str(params.get("name") or params.get("content") or params.get("text")
               or "").strip()
    role = str(params.get("role") or params.get("kicker") or params.get("subtitle")
               or "").strip()
    if not name and not role:
        return Piece()
    node_id = ctx.target
    available = float(params.get("available_px") or 740)
    name_size = (fit_size(name.upper(), available, _LT_AU_NAME_CEILING)
                 if name else _LT_AU_NAME_CEILING)
    role_size = (min(_LT_AU_ROLE_SIZE, fit_size(role, available, _LT_AU_ROLE_SIZE))
                 if role else _LT_AU_ROLE_SIZE)
    name_w = text_width(name.upper(), name_size) if name else 0.0
    role_w = text_width(role, role_size) if role else 0.0
    rule_w = max(40, int(round(max(name_w, role_w))))
    t = _lt_au_times(ctx.duration)
    at = ctx.start
    parts: list[str] = []
    tweens: list[str] = []
    if name:
        parts.append(
            f'<span id="{node_id}-name" class="lt-au-name" '
            f'style="font-size:{name_size}px">{_esc(name)}</span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-name",{{y:{_LT_AU_NAME_FROM_Y},opacity:0}},'
            f'{{y:0,opacity:1,duration:{_num(t["name_in_dur"])},'
            f'ease:"power3.out"}},{_num(at + t["name_in_at"])});')
        tweens.append(
            f'tl.fromTo("#{node_id}-name",{{y:0,opacity:1}},'
            f'{{y:{_LT_AU_NAME_EXIT_Y},opacity:0,duration:{_num(t["name_out_dur"])},'
            f'ease:"power2.in",immediateRender:false}},'
            f'{_num(at + t["name_out_at"])});')
    parts.append(
        f'<span id="{node_id}-rule" class="lt-au-rule" '
        f'style="width:{rule_w}px"></span>')
    tweens.append(
        f'tl.fromTo("#{node_id}-rule",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(t["rule_in_dur"])},ease:"power4.out"}},'
        f'{_num(at + t["rule_in_at"])});')
    tweens.append(
        f'tl.fromTo("#{node_id}-rule",{{scaleX:1}},'
        f'{{scaleX:0,duration:{_num(t["rule_out_dur"])},ease:"power2.in",'
        f'immediateRender:false}},{_num(at + t["rule_out_at"])});')
    if role:
        parts.append(
            f'<span id="{node_id}-role" class="lt-au-role" '
            f'style="font-size:{role_size}px">{_esc(role)}</span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-role",{{y:{_LT_AU_ROLE_FROM_Y},opacity:0}},'
            f'{{y:0,opacity:1,duration:{_num(t["role_in_dur"])},'
            f'ease:"power3.out"}},{_num(at + t["role_in_at"])});')
        tweens.append(
            f'tl.fromTo("#{node_id}-role",{{opacity:1}},'
            f'{{opacity:0,duration:{_num(t["role_out_dur"])},ease:"power2.in",'
            f'immediateRender:false}},{_num(at + t["role_out_at"])});')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay lt-accent-underline" '
               f'{_timing(ctx)}>{"".join(parts)}</div>'],
        tweens=tweens)


_LT_CB_SLACK = 1.14


_LT_CB_NAME_CEILING = 52


_LT_CB_ROLE_SIZE = 26


_LT_CB_GAP = 7


def _lt_cb_times(duration: float) -> dict[str, float]:
    """Вход как в каталоге; выход прижат к концу, если окно короче 4.8 с."""
    wipe_in_at, wipe_in_dur = 0.10, 0.55
    tab_in_at, tab_in_dur = 0.28, 0.45
    name_in_at, name_in_dur = 0.34, 0.50
    role_in_at, role_in_dur = 0.44, 0.50
    exit_dur, exit_lead = 0.35, 0.50
    enter_end = role_in_at + role_in_dur
    first_out = duration - exit_lead
    if first_out < enter_end + 0.001:
        room = max(0.35, first_out - 0.001)
        scale = room / enter_end
        wipe_in_at *= scale
        wipe_in_dur *= scale
        tab_in_at *= scale
        tab_in_dur *= scale
        name_in_at *= scale
        name_in_dur *= scale
        role_in_at *= scale
        role_in_dur *= scale
        enter_end = role_in_at + role_in_dur
    exit_at = max(enter_end + 0.001, duration - exit_lead)
    return {
        "wipe_in_at": wipe_in_at, "wipe_in_dur": wipe_in_dur,
        "tab_in_at": tab_in_at, "tab_in_dur": tab_in_dur,
        "name_in_at": name_in_at, "name_in_dur": name_in_dur,
        "role_in_at": role_in_at, "role_in_dur": role_in_dur,
        "exit_at": exit_at, "exit_dur": exit_dur,
    }


_LT_CB_PAD_R = 40


_LT_CB_NAME_LH = 1.06


_LT_CB_ROLE_LH = 1.2


_LT_CB_PAD_L = 30


_LT_CB_TAB_W = 12


_LT_CB_EXIT_Y = 18


_LT_CB_FROM_Y = 22


_LT_CB_PAD_T = 22


_LT_CB_PAD_B = 24


def ov_lt_clean_bar(ctx: "TemplateCtx") -> Piece:
    """Белая плашка с акцентной полоской: wipe слева, tab растёт, текст ↑.

    Каталог твинит ``clip-path`` и прячет карточку через ``visibility``.
    Движок этого не умеет: wipe — SVG-mask и ``scaleX`` на rect, как у
    caption-clip-wipe. Оранжевый ``var(--color-accent)`` — чужой бренд, tab канала
    ``var(--color-accent)``. Montserrat как в каталоге. Твины на маске, tab и строках,
    не на ``.clip``.
    """
    params = ctx.params
    name = str(params.get("name") or params.get("content") or params.get("text")
               or "").strip()
    role = str(params.get("role") or params.get("kicker") or params.get("subtitle")
               or "").strip()
    if not name and not role:
        return Piece()
    node_id = ctx.target
    available = float(params.get("available_px") or 740)
    text_avail = max(80.0, available - _LT_CB_TAB_W - _LT_CB_PAD_L - _LT_CB_PAD_R)
    fit_avail = text_avail / _LT_CB_SLACK
    name_size = (fit_size(name, fit_avail, _LT_CB_NAME_CEILING)
                 if name else _LT_CB_NAME_CEILING)
    role_size = (min(_LT_CB_ROLE_SIZE, fit_size(role, fit_avail, _LT_CB_ROLE_SIZE))
                 if role else _LT_CB_ROLE_SIZE)
    name_w = text_width(name, name_size) * _LT_CB_SLACK if name else 0.0
    role_w = text_width(role, role_size) * _LT_CB_SLACK if role else 0.0
    inner_w = max(40, int(math.ceil(max(name_w, role_w))))
    card_w = _LT_CB_TAB_W + _LT_CB_PAD_L + _LT_CB_PAD_R + inner_w
    name_h = name_size * _LT_CB_NAME_LH if name else 0.0
    role_h = role_size * _LT_CB_ROLE_LH if role else 0.0
    gap = _LT_CB_GAP if name and role else 0
    card_h = int(math.ceil(_LT_CB_PAD_T + _LT_CB_PAD_B + name_h + gap + role_h))
    card_w = max(8, card_w)
    card_h = max(8, card_h)
    t = _lt_cb_times(ctx.duration)
    at = ctx.start
    rows: list[str] = []
    tweens: list[str] = [
        f'tl.fromTo("#{node_id}-wipe",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(t["wipe_in_dur"])},ease:"power3.out"}},'
        f'{_num(at + t["wipe_in_at"])});',
        f'tl.fromTo("#{node_id}-tab",{{scaleY:0}},'
        f'{{scaleY:1,duration:{_num(t["tab_in_dur"])},ease:"power2.out"}},'
        f'{_num(at + t["tab_in_at"])});',
        f'tl.fromTo("#{node_id}-stage",{{y:0,opacity:1}},'
        f'{{y:{_LT_CB_EXIT_Y},opacity:0,duration:{_num(t["exit_dur"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(at + t["exit_at"])});',
    ]
    if name:
        rows.append(
            f'<span id="{node_id}-name" class="lt-cb-name" '
            f'style="font-size:{name_size}px">{_esc(name)}</span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-name",{{y:{_LT_CB_FROM_Y},opacity:0}},'
            f'{{y:0,opacity:1,duration:{_num(t["name_in_dur"])},'
            f'ease:"power3.out"}},{_num(at + t["name_in_at"])});')
    if role:
        rows.append(
            f'<span id="{node_id}-role" class="lt-cb-role" '
            f'style="font-size:{role_size}px">{_esc(role)}</span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-role",{{y:{_LT_CB_FROM_Y},opacity:0}},'
            f'{{y:0,opacity:1,duration:{_num(t["role_in_dur"])},'
            f'ease:"power3.out"}},{_num(at + t["role_in_at"])});')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay lt-clean-bar" {_timing(ctx)}>'
               f'<span id="{node_id}-stage" class="lt-cb-stage" '
               f'style="width:{card_w}px;height:{card_h}px">'
               f'<svg class="lt-cb-svg" width="{card_w}" height="{card_h}" '
               f'viewBox="0 0 {card_w} {card_h}" aria-hidden="true">'
               f'<defs><mask id="{node_id}-m" maskUnits="userSpaceOnUse" '
               f'maskContentUnits="userSpaceOnUse">'
               f'<rect id="{node_id}-wipe" class="lt-cb-wipe" x="0" y="0" '
               f'width="{card_w}" height="{card_h}" fill="#FFFFFF"/></mask></defs>'
               f'</svg>'
               f'<span id="{node_id}-card" class="lt-cb-card" '
               f'style="-webkit-mask:url(#{node_id}-m);mask:url(#{node_id}-m)">'
               f'<span id="{node_id}-tab" class="lt-cb-tab"></span>'
               f'<span class="lt-cb-body">{"".join(rows)}</span></span></span></div>'],
        tweens=tweens)


_LT_DC_SLACK = 1.14


_LT_DC_NAME_CEILING = 48


_LT_DC_ROLE_SIZE = 25


def _lt_dc_times(duration: float) -> dict[str, float]:
    """Вход как в каталоге; выход прижат к концу, если окно короче 4.8 с."""
    card_in_at, card_in_dur = 0.10, 0.50
    name_in_at, name_in_dur = 0.26, 0.45
    rule_in_at, rule_in_dur = 0.42, 0.50
    role_in_at, role_in_dur = 0.56, 0.45
    exit_dur, exit_lead = 0.35, 0.50
    enter_end = role_in_at + role_in_dur
    first_out = duration - exit_lead
    if first_out < enter_end + 0.001:
        room = max(0.35, first_out - 0.001)
        scale = room / enter_end
        card_in_at *= scale
        card_in_dur *= scale
        name_in_at *= scale
        name_in_dur *= scale
        rule_in_at *= scale
        rule_in_dur *= scale
        role_in_at *= scale
        role_in_dur *= scale
        enter_end = role_in_at + role_in_dur
    exit_at = max(enter_end + 0.001, duration - exit_lead)
    return {
        "card_in_at": card_in_at, "card_in_dur": card_in_dur,
        "name_in_at": name_in_at, "name_in_dur": name_in_dur,
        "rule_in_at": rule_in_at, "rule_in_dur": rule_in_dur,
        "role_in_at": role_in_at, "role_in_dur": role_in_dur,
        "exit_at": exit_at, "exit_dur": exit_dur,
    }


_LT_DC_PAD_R = 38


_LT_DC_PAD_L = 32


_LT_DC_CARD_FROM_Y = 60


_LT_DC_EXIT_Y = 24


_LT_DC_NAME_FROM_Y = 14


def ov_lt_dark_card(ctx: "TemplateCtx") -> Piece:
    """Угольная карточка на светлом футаже: имя, черта left→right, роль.

    Каталог твинит ``tl.to`` после ``gsap.set`` и прячет обёртку через
    ``visibility``. Движок требует ``fromTo`` на вложенных узлах; ``visibility``
    вне списка. Золото ``var(--color-accent)`` — чужой бренд, черта канала ``var(--color-accent)``.
    Уголь ``var(--color-ink)`` и Montserrat как в каталоге — это сам жест. Твины на
    карточке, имени, черте и роли, не на ``.clip``. Клип в потоке: абсолютный
    единственный ребёнок обнуляет paint-box.
    """
    params = ctx.params
    name = str(params.get("name") or params.get("content") or params.get("text")
               or "").strip()
    role = str(params.get("role") or params.get("kicker") or params.get("subtitle")
               or "").strip()
    if not name and not role:
        return Piece()
    node_id = ctx.target
    available = float(params.get("available_px") or 740)
    text_avail = max(80.0, available - _LT_DC_PAD_L - _LT_DC_PAD_R)
    fit_avail = text_avail / _LT_DC_SLACK
    name_size = (fit_size(name, fit_avail, _LT_DC_NAME_CEILING)
                 if name else _LT_DC_NAME_CEILING)
    role_size = (min(_LT_DC_ROLE_SIZE, fit_size(role, fit_avail, _LT_DC_ROLE_SIZE))
                 if role else _LT_DC_ROLE_SIZE)
    name_w = text_width(name, name_size) * _LT_DC_SLACK if name else 0.0
    role_w = text_width(role, role_size) * _LT_DC_SLACK if role else 0.0
    rule_w = max(40, int(math.ceil(max(name_w, role_w))))
    t = _lt_dc_times(ctx.duration)
    at = ctx.start
    rows: list[str] = []
    tweens: list[str] = [
        f'tl.fromTo("#{node_id}-card",{{y:{_LT_DC_CARD_FROM_Y},opacity:0}},'
        f'{{y:0,opacity:1,duration:{_num(t["card_in_dur"])},ease:"power3.out"}},'
        f'{_num(at + t["card_in_at"])});',
        f'tl.fromTo("#{node_id}-card",{{y:0,opacity:1}},'
        f'{{y:{_LT_DC_EXIT_Y},opacity:0,duration:{_num(t["exit_dur"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(at + t["exit_at"])});',
        f'tl.fromTo("#{node_id}-rule",{{scaleX:0}},'
        f'{{scaleX:1,duration:{_num(t["rule_in_dur"])},ease:"power4.out"}},'
        f'{_num(at + t["rule_in_at"])});',
    ]
    if name:
        rows.append(
            f'<span id="{node_id}-name" class="lt-dc-name" '
            f'style="font-size:{name_size}px">{_esc(name)}</span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-name",{{y:{_LT_DC_NAME_FROM_Y},opacity:0}},'
            f'{{y:0,opacity:1,duration:{_num(t["name_in_dur"])},'
            f'ease:"power3.out"}},{_num(at + t["name_in_at"])});')
    rows.append(
        f'<span id="{node_id}-rule" class="lt-dc-rule" '
        f'style="width:{rule_w}px"></span>')
    if role:
        rows.append(
            f'<span id="{node_id}-role" class="lt-dc-role" '
            f'style="font-size:{role_size}px">{_esc(role)}</span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-role",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(t["role_in_dur"])},ease:"power2.out"}},'
            f'{_num(at + t["role_in_at"])});')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay lt-dark-card" {_timing(ctx)}>'
               f'<span id="{node_id}-card" class="lt-dc-card">'
               f'{"".join(rows)}</span></div>'],
        tweens=tweens)


def _cz_times(duration: float) -> dict[str, float]:
    """Окно cinematic-zoom: каталог держит 2 с шейдера внутри 4 с демо.

    На склейке шорта это ``ctx.duration`` (~0.3 с). Вуаль «to» вспыхивает
    к середине и гаснет; join +1 мс, чтобы opacity не наложилась.
    """
    d = max(0.05, float(duration))
    mid = d * 0.5
    to_out_at = mid + 0.001
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "to_out_at": to_out_at,
        "to_out": max(0.001, d - to_out_at - 0.001),
    }


def tr_cinematic_zoom(ctx: "TemplateCtx") -> Piece:
    """Cinematic zoom: from зумит наружу, to — внутрь из tight, RGB-сдвиг.

    Каталог рисует WebGL: 12 радиальных семплов, per-channel offset,
    ``onUpdate`` на шейдер. Здесь входящий кадр садится с ``from_scale``,
    индиго-вуаль уезжает наружу, золотая входит из tight, хроматические
    кольца и статичный ``backdrop-filter``. Без canvas и без Three.js.
    Цвета ``var(--color-panel)`` / ``var(--color-accent)`` — жест SCENE A/B каталога, не палитра
    канала.
    """
    from_scale = float(ctx.params.get("from_scale", 1.16))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _cz_times(d)
    start = ctx.start
    ghosts = []
    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{immediateRender:false,scale:1,duration:{_num(d)},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-from",{{scale:1,opacity:0.55}},'
        f'{{scale:1.14,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{scale:1.12}},'
        f'{{scale:1,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{opacity:0}},'
        f'{{opacity:0.42,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-r",{{scale:0.92,opacity:0.5}},'
        f'{{scale:1.18,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-b",{{scale:0.96,opacity:0.45}},'
        f'{{scale:1.12,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.85}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
    ]
    for i in range(3):
        g_from = 1.0 + i * 0.03
        g_to = 1.10 + i * 0.05
        g_op = 0.26 - i * 0.05
        ghosts.append(f'<span id="{node_id}-g{i}" class="cz-ghost"></span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-g{i}",{{scale:{_num(g_from)},opacity:{_num(g_op)}}},'
            f'{{scale:{_num(g_to)},opacity:0,duration:{_num(times["dur"])},'
            f'ease:"power2.inOut"}},{_num(start)});')
        tweens.append(
            f'tl.set("#{node_id}-g{i}",{{opacity:0}},{_num(start + d)});')
    tweens.extend([
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-r",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ])
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-cinematic-zoom" {_timing(ctx)}>'
               f'<span class="cz-stage">'
               f'<span id="{node_id}-blur" class="cz-blur"></span>'
               f'<span id="{node_id}-from" class="cz-from"></span>'
               f'<span id="{node_id}-to" class="cz-to"></span>'
               f'{"".join(ghosts)}'
               f'<span id="{node_id}-r" class="cz-r"></span>'
               f'<span id="{node_id}-b" class="cz-b"></span>'
               f'</span></div>'],
        tweens=tweens)


def _gs_times(duration: float) -> dict[str, float]:
    """Окно shader-glitch: каталог держит 2 с шейдера внутри 4 с демо."""
    d = max(0.05, float(duration))
    mid = d * 0.5
    to_out_at = mid + 0.001
    return {
        "dur": max(0.001, d - 0.001),
        "mid": mid,
        "to_out_at": to_out_at,
        "to_out": max(0.001, d - to_out_at - 0.001),
    }


_GS_SCANS = 12


_GS_COLS = 8


_GS_ROWS = 12


def _gs_blocks(index: int, seed: int) -> list[tuple[int, int, int, int, int, int]]:
    """Блоки scramble: ~17 % ячеек 8×12, как step(0.83) в шейдере каталога."""
    cw = 1080 // _GS_COLS
    ch = 1920 // _GS_ROWS
    out: list[tuple[int, int, int, int, int, int]] = []
    for row in range(_GS_ROWS):
        for col in range(_GS_COLS):
            h = (col * 47 + row * 91 + seed * 13 + index * 17) % 100
            if h < 83:
                continue
            dx = ((h * 37 + seed) % 70) - 35
            dy = ((h * 19 + index) % 70) - 35
            out.append((col * cw, row * ch, cw, ch, dx, dy))
            if len(out) >= 16:
                return out
    return out


def tr_glitch_shader(ctx: "TemplateCtx") -> Piece:
    """Glitch shader: scan lines, block scramble, chroma, flicker.

    Каталог рисует WebGL ``onUpdate``: 60 scan-line, 12×8 блоки, RGB-сдвиг,
    posterize. Здесь заранее полосы и клетки, ``x``/``y``/``opacity``, chroma
    и вуали ``var(--color-panel)``/``var(--color-accent)``. Без canvas и без ``Math.random``.
    ``glitch-short`` остаётся короткими полосами; это жест из каталога.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _gs_times(d)
    start = ctx.start
    seed = int(ctx.params.get("seed", ctx.index * 17 + 9))
    spans: list[str] = [
        f'<span id="{node_id}-from" class="gs-from"></span>',
        f'<span id="{node_id}-to" class="gs-to"></span>',
        f'<span id="{node_id}-lines" class="gs-lines"></span>',
        f'<span id="{node_id}-flick" class="gs-flick"></span>',
        f'<span id="{node_id}-r" class="gs-r"></span>',
        f'<span id="{node_id}-b" class="gs-b"></span>',
    ]
    tweens = [
        f'tl.fromTo("#{node_id}-from",{{opacity:0.5}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{opacity:0}},'
        f'{{opacity:0.4,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-lines",{{opacity:0}},'
        f'{{opacity:0.55,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-lines",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-flick",{{opacity:0.32}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"steps(5)"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-r",{{x:0,opacity:0}},'
        f'{{x:36,opacity:0.5,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-r",{{x:0,opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-b",{{x:0,opacity:0}},'
        f'{{x:-32,opacity:0.45,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-b",{{x:0,opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-lines",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-flick",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-r",{{opacity:0,x:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0,x:0}},{_num(start + d)});',
    ]
    for i in range(_GS_SCANS):
        top = int(1920 * i / _GS_SCANS) + (i * 7 + seed) % 18
        ht = 3 + i % 3
        shift = (80 + (i * 37 + ctx.index * 13) % 110) * (1 if i % 2 else -1)
        spans.append(
            f'<span id="{node_id}-s{i}" class="gs-scan" '
            f'style="top:{top}px;height:{ht}px"></span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-s{i}",{{x:{shift},opacity:0.75}},'
            f'{{x:0,opacity:0,duration:{_num(times["dur"])},ease:"steps(3)"}},{_num(start)});')
        tweens.append(
            f'tl.set("#{node_id}-s{i}",{{opacity:0}},{_num(start + d)});')
    for i, (left, top, w, h, dx, dy) in enumerate(_gs_blocks(ctx.index, seed)):
        spans.append(
            f'<span id="{node_id}-k{i}" class="gs-block" '
            f'style="left:{left}px;top:{top}px;width:{w}px;height:{h}px"></span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-k{i}",{{x:{dx},y:{dy},opacity:0.55}},'
            f'{{x:0,y:0,opacity:0,duration:{_num(times["dur"])},'
            f'ease:"steps(2)"}},{_num(start)});')
        tweens.append(
            f'tl.set("#{node_id}-k{i}",{{opacity:0}},{_num(start + d)});')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-glitch-shader" {_timing(ctx)}>'
               f'<span class="gs-stage">{"".join(spans)}</span></div>'],
        tweens=tweens)


def _gw_times(duration: float) -> dict[str, float]:
    """Окно gravitational-lens: каталог держит 2 с шейдера внутри 4 с демо."""
    return _cz_times(duration)


def tr_gravitational_lens(ctx: "TemplateCtx") -> Piece:
    """Gravitational lens: from затягивает к центру, горизонт, chroma.

    Каталог рисует WebGL ``onUpdate``: warp к колодцу, chromatic aberration,
    event horizon. Здесь входящий кадр выходит из tight, фиолетовая вуаль
    ``var(--color-accent-deep)`` схлопывается к центру, магента ``var(--color-accent)`` выходит из well,
    кольца и статичный ``backdrop-filter``. Без canvas. Цвета SCENE A/B
    каталога — жест шейдера, не палитра канала.
    """
    from_scale = float(ctx.params.get("from_scale", 1.14))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _gw_times(d)
    start = ctx.start
    ghosts = []
    tweens = [
        f'tl.fromTo("#{ctx.target}",{{scale:{_num(from_scale)}}},'
        f'{{immediateRender:false,scale:1,duration:{_num(d)},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-from",{{scale:1,opacity:0.58}},'
        f'{{scale:0.62,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-well",{{scale:0.22,opacity:0.9}},'
        f'{{scale:1.4,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{scale:0.48}},'
        f'{{scale:1,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{opacity:0}},'
        f'{{opacity:0.48,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-r",{{scale:0.82,opacity:0.52}},'
        f'{{scale:1.2,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-b",{{scale:0.88,opacity:0.4}},'
        f'{{scale:1.14,opacity:0,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.8}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
    ]
    for i in range(3):
        g_from = 1.18 + i * 0.08
        g_to = 0.55 + i * 0.08
        g_op = 0.28 - i * 0.06
        ghosts.append(f'<span id="{node_id}-g{i}" class="gw-ghost"></span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-g{i}",{{scale:{_num(g_from)},opacity:{_num(g_op)}}},'
            f'{{scale:{_num(g_to)},opacity:0,duration:{_num(times["dur"])},'
            f'ease:"power2.inOut"}},{_num(start)});')
        tweens.append(
            f'tl.set("#{node_id}-g{i}",{{opacity:0}},{_num(start + d)});')
    tweens.extend([
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-well",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-r",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ])
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-gravitational-lens" {_timing(ctx)}>'
               f'<span class="gw-stage">'
               f'<span id="{node_id}-blur" class="gw-blur"></span>'
               f'<span id="{node_id}-from" class="gw-from"></span>'
               f'<span id="{node_id}-to" class="gw-to"></span>'
               f'<span id="{node_id}-well" class="gw-well"></span>'
               f'{"".join(ghosts)}'
               f'<span id="{node_id}-r" class="gw-r"></span>'
               f'<span id="{node_id}-b" class="gw-b"></span>'
               f'</span></div>'],
        tweens=tweens)


def _ll_times(duration: float) -> dict[str, float]:
    """Окно light-leak: каталог держит 2 с шейдера внутри 4 с демо."""
    return _cz_times(duration)


def tr_light_leak(ctx: "TemplateCtx") -> Piece:
    """Light leak: тёплый засвет сверху-справа, flare и ACES.

    Каталог рисует WebGL ``onUpdate``: Beer-Lambert, ACES, направленный
    flare. Здесь вуали ``var(--color-space-deep)``/``var(--color-accent)``, пятно и полоса screen.
    Без canvas. Цвета SCENE A/B каталога — жест шейдера, не палитра канала.
    ``light-sweep`` остаётся диагональным бликом.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _ll_times(d)
    start = ctx.start
    tweens = [
        f'tl.fromTo("#{node_id}-from",{{opacity:0.48}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{opacity:0}},'
        f'{{opacity:0.42,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-sage",{{opacity:0.22}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blob",{{scale:0.38}},'
        f'{{scale:1.48,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blob",{{opacity:0.22}},'
        f'{{opacity:0.86,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-blob",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-hot",{{scale:0.28}},'
        f'{{scale:1.12,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-hot",{{opacity:0.18}},'
        f'{{opacity:0.72,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-hot",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-flare",{{x:240,scaleX:0.68}},'
        f'{{x:-80,scaleX:1.16,duration:{_num(times["dur"])},'
        f'ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-flare",{{opacity:0}},'
        f'{{opacity:0.7,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-flare",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
    ]
    orbs = []
    for i in range(2):
        s0 = 0.52 + i * 0.16
        s1 = 1.18 + i * 0.1
        op = 0.3 - i * 0.08
        orbs.append(f'<span id="{node_id}-o{i}" class="ll-orb ll-o{i}"></span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-o{i}",{{scale:{_num(s0)},opacity:{_num(op)}}},'
            f'{{scale:{_num(s1)},opacity:0,duration:{_num(times["dur"])},'
            f'ease:"power2.out"}},{_num(start)});')
        tweens.append(
            f'tl.set("#{node_id}-o{i}",{{opacity:0}},{_num(start + d)});')
    tweens.extend([
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-sage",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blob",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-hot",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-flare",{{opacity:0}},{_num(start + d)});',
    ])
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-light-leak" {_timing(ctx)}>'
               f'<span class="ll-stage">'
               f'<span id="{node_id}-from" class="ll-from"></span>'
               f'<span id="{node_id}-to" class="ll-to"></span>'
               f'<span id="{node_id}-sage" class="ll-sage"></span>'
               f'<span id="{node_id}-blob" class="ll-blob"></span>'
               f'<span id="{node_id}-hot" class="ll-hot"></span>'
               f'<span id="{node_id}-flare" class="ll-flare"></span>'
               f'{"".join(orbs)}'
               f'</span></div>'],
        tweens=tweens)


_CW_CARD_SCALE = 0.38


_CW_CATALOG_SEC = 2.4


def _cw_times(duration: float) -> dict[str, float]:
    """Окно clone-wall: каталог держит 2.4 с (карточка → invert → уход стенки).

    На склейке шорта это ``ctx.duration`` (~0.3 с). Доли каталога сохраняем,
    стыки +1 мс, чтобы scale карточки и opacity стенки не наложились.
    """
    d = max(0.05, float(duration))
    s = d / _CW_CATALOG_SEC

    def t(catalog: float) -> float:
        return max(0.0, min(d, catalog * s))

    card_at = t(0.2)
    card_dur = max(0.001, t(0.95) - card_at)
    card_out_at = t(1.35)
    if card_at + card_dur + 0.001 > card_out_at:
        card_dur = max(0.001, card_out_at - card_at - 0.001)
    card_out_end = t(1.75)
    card_out_dur = max(0.001, card_out_end - card_out_at)
    wall_out_at = t(1.9)
    if card_out_at + card_out_dur + 0.001 > wall_out_at:
        card_out_dur = max(0.001, wall_out_at - card_out_at - 0.001)
    wall_out_end = min(d - 0.001, t(2.35))
    wall_out_dur = max(0.001, wall_out_end - wall_out_at)
    invert_at = t(0.85)
    invert_end = t(1.5)
    invert_dur = max(0.001, invert_end - invert_at)
    drift_at = t(0.3)
    drift_end = min(wall_out_at - 0.001, t(0.3 + 1.8))
    drift_dur = max(0.001, drift_end - drift_at)
    card_kill = min(d, max(card_out_at + card_out_dur, t(1.76)))
    wall_kill = min(d, max(wall_out_at + wall_out_dur, t(2.36)))
    return {
        "card_at": card_at,
        "card_dur": card_dur,
        "card_out_at": card_out_at,
        "card_out_dur": card_out_dur,
        "card_kill": card_kill,
        "invert_at": invert_at,
        "invert_dur": invert_dur,
        "drift_at": drift_at,
        "drift_dur": drift_dur,
        "wall_out_at": wall_out_at,
        "wall_out_dur": wall_out_dur,
        "wall_kill": wall_kill,
    }


_CW_FRAME_W = 1080


_CW_FRAME_H = 1920


def _cw_wall(word: str, font_size: int, spread_x: int, spread_y: int,
             brick: bool) -> tuple[int, list[tuple[float, float]]]:
    """Ряды клонов: сколько плиток в ряду и (top, left) каждого ряда."""
    row_h = font_size + spread_y
    rows = min(16, math.ceil(_CW_FRAME_H / row_h) + 1)
    tile_w = max(1.0, len(word) * font_size * 0.58 + spread_x)
    per_row = math.ceil(_CW_FRAME_W / tile_w) + 2
    layout: list[tuple[float, float]] = []
    for r in range(rows):
        offset = -round(tile_w / 2) if brick and r % 2 else 0
        layout.append((r * row_h - font_size * 0.35, offset - tile_w))
    return per_row, layout


def tr_mk_clone_wall(ctx: "TemplateCtx") -> Piece:
    """Clone wall: плитка слов накрывает кадр, инвертируется и уходит.

    Каталог твинит ``width``/``height`` карточки, ``visibility`` и собирает
    ряды в JS. Здесь ``scale``/``x``/``opacity``/``borderRadius``, ряды заранее
    в Python. Твины на карточке / плитке / invert / стенке, не на ``.clip``
    и не на входящем кадре. Чернила ``var(--color-ink)`` и бумага ``var(--color-bg-pure)`` как в
    каталоге — жест MK, не палитра канала. ``-apple-system`` не ставим.
    """
    params = ctx.params
    word = str(params.get("word") or "HyperFrames").strip() or "HyperFrames"
    font_size = int(params.get("fontSize") or params.get("font_size") or 240)
    spread_x = int(params.get("spreadX") or params.get("spread_x") or 90)
    spread_y = int(params.get("spreadY") or params.get("spread_y") or 60)
    brick_raw = params.get("brickOffset", params.get("brick_offset", True))
    if isinstance(brick_raw, bool):
        brick = brick_raw
    else:
        brick = str(brick_raw).strip().lower() not in ("0", "false", "no")
    drift_x = int(params.get("driftX") or params.get("drift_x") or -46)
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _cw_times(d)
    start = ctx.start
    per_row, layout = _cw_wall(word, font_size, spread_x, spread_y, brick)
    tile = (f'<span class="cw-tile" style="margin-right:{spread_x}px">'
            f"{_esc(word)}</span>")
    rows = []
    for i, (top, left) in enumerate(layout):
        rows.append(
            f'<span id="{node_id}-r{i}" class="cw-row" '
            f'style="top:{_num(top)}px;left:{_num(left)}px;'
            f'font-size:{font_size}px">{tile * (per_row + 1)}</span>')
    card_to = _CW_CARD_SCALE
    card_out = round(card_to * 0.6, 3)
    tweens = [
        f'tl.set("#{node_id}-invert",{{x:{-_CW_FRAME_W}}},'
        f'{_num(start)});',
        f'tl.fromTo("#{node_id}-card",{{scale:1,borderRadius:0}},'
        f'{{scale:{_num(card_to)},borderRadius:40,'
        f'duration:{_num(times["card_dur"])},ease:"power3.inOut"}},'
        f'{_num(start + times["card_at"])});',
        f'tl.to("#{node_id}-card",{{scale:{_num(card_out)},opacity:0,'
        f'duration:{_num(times["card_out_dur"])},ease:"power2.in",'
        f'immediateRender:false}},'
        f'{_num(start + times["card_out_at"])});',
        f'tl.set("#{node_id}-card",{{opacity:0}},'
        f'{_num(start + times["card_kill"])});',
        f'tl.fromTo("#{node_id}-tiles",{{x:0}},'
        f'{{x:{drift_x},duration:{_num(times["drift_dur"])},'
        f'ease:"sine.inOut"}},{_num(start + times["drift_at"])});',
        f'tl.fromTo("#{node_id}-invert",{{x:{-_CW_FRAME_W}}},'
        f'{{x:0,duration:{_num(times["invert_dur"])},ease:"power3.inOut",'
        f'immediateRender:false}},'
        f'{_num(start + times["invert_at"])});',
        f'tl.fromTo("#{node_id}-wall",{{opacity:1}},'
        f'{{opacity:0,duration:{_num(times["wall_out_dur"])},'
        f'ease:"power2.inOut",immediateRender:false}},'
        f'{_num(start + times["wall_out_at"])});',
        f'tl.set("#{node_id}-wall",{{opacity:0}},'
        f'{_num(start + times["wall_kill"])});',
        f'tl.set("#{node_id}-invert",{{opacity:0}},'
        f'{_num(start + d)});',
        f'tl.set("#{node_id}-tiles",{{opacity:0}},'
        f'{_num(start + d)});',
    ]
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-mk-clone-wall" {_timing(ctx)}>'
               f'<span class="cw-stage">'
               f'<span id="{node_id}-wall" class="cw-wall">'
               f'<span id="{node_id}-tiles" class="cw-tiles">'
               f'{"".join(rows)}</span>'
               f'<span id="{node_id}-invert" class="cw-invert"></span>'
               f'</span>'
               f'<span id="{node_id}-card" class="cw-card"></span>'
               f'</span></div>'],
        tweens=tweens)


def _si_times(duration: float) -> dict[str, float]:
    """Окно sdf-iris: каталог держит 2 с шейдера внутри 4 с демо."""
    return _cz_times(duration)


def tr_sdf_iris(ctx: "TemplateCtx") -> Piece:
    """SDF iris: круг из центра, три кольца glow.

    Каталог рисует WebGL ``onUpdate``: aspect-corrected SDF, onion rings.
    Здесь золотой диск ``var(--color-accent)`` растёт ``scale``, три кольца и вуаль
    ``var(--color-space-deep)``. Без canvas и без ``clip-path``. Цвета SCENE A/B каталога —
    жест шейдера, не палитра канала. ``mask-wipe-circle`` остаётся белой маской.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _si_times(d)
    start = ctx.start
    tweens = [
        f'tl.fromTo("#{node_id}-from",{{opacity:0.5}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-steel",{{opacity:0.2}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-iris",{{scale:0.06}},'
        f'{{scale:1.18,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-iris",{{opacity:0}},'
        f'{{opacity:0.46,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-iris",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
    ]
    rings = []
    for i in range(3):
        s0 = 0.08 + i * 0.03
        s1 = 1.12 + i * 0.05
        op = 0.72 - i * 0.16
        rings.append(f'<span id="{node_id}-r{i}" class="si-ring"></span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-r{i}",{{scale:{_num(s0)}}},'
            f'{{scale:{_num(s1)},duration:{_num(times["dur"])},'
            f'ease:"power2.inOut"}},{_num(start)});')
        tweens.append(
            f'tl.fromTo("#{node_id}-r{i}",{{opacity:0}},'
            f'{{opacity:{_num(op)},duration:{_num(times["mid"])},'
            f'ease:"power2.out"}},{_num(start)});')
        tweens.append(
            f'tl.to("#{node_id}-r{i}",{{opacity:0,duration:{_num(times["to_out"])},'
            f'ease:"power2.in",immediateRender:false}},'
            f'{_num(start + times["to_out_at"])});')
        tweens.append(
            f'tl.set("#{node_id}-r{i}",{{opacity:0}},{_num(start + d)});')
    tweens.extend([
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-steel",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-iris",{{opacity:0}},{_num(start + d)});',
    ])
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-sdf-iris" {_timing(ctx)}>'
               f'<span class="si-stage">'
               f'<span id="{node_id}-from" class="si-from"></span>'
               f'<span id="{node_id}-steel" class="si-steel"></span>'
               f'<span id="{node_id}-iris" class="si-iris"></span>'
               f'{"".join(rings)}'
               f'</span></div>'],
        tweens=tweens)


def _td_times(duration: float) -> dict[str, float]:
    """Окно thermal-distortion: каталог держит 2 с шейдера внутри 4 с демо."""
    return _cz_times(duration)


def tr_thermal_distortion(ctx: "TemplateCtx") -> Piece:
    """Thermal distortion: heat shimmer снизу вверх и тёплый haze.

    Каталог рисует WebGL ``onUpdate``: FBM displacement, sine, haze.
    Здесь вуали ``var(--color-panel)``/``var(--color-accent)``, пятно снизу и полосы, ``y`` вверх.
    Без canvas. Цвета SCENE A/B каталога — жест шейдера, не палитра канала.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _td_times(d)
    start = ctx.start
    tweens = [
        f'tl.fromTo("#{node_id}-from",{{opacity:0.5}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{opacity:0}},'
        f'{{opacity:0.4,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-mist",{{opacity:0.22}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.7}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-haze",{{scale:0.42}},'
        f'{{scale:1.28,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-haze",{{opacity:0.2}},'
        f'{{opacity:0.82,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-haze",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-hot",{{scale:0.28}},'
        f'{{scale:1.08,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-hot",{{opacity:0.16}},'
        f'{{opacity:0.7,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-hot",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
    ]
    bands = []
    for i in range(5):
        x0 = (32 - i * 6) * (1 if i % 2 else -1)
        x1 = -x0
        rise = -220 - i * 28
        op = 0.64 - i * 0.08
        bands.append(
            f'<span id="{node_id}-b{i}" class="td-band td-b{i}"></span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-b{i}",{{y:0,x:{x0}}},'
            f'{{y:{rise},x:{x1},duration:{_num(times["dur"])},'
            f'ease:"power2.inOut"}},{_num(start)});')
        tweens.append(
            f'tl.fromTo("#{node_id}-b{i}",{{opacity:0}},'
            f'{{opacity:{_num(op)},duration:{_num(times["mid"])},'
            f'ease:"power2.out"}},{_num(start)});')
        tweens.append(
            f'tl.to("#{node_id}-b{i}",{{opacity:0,duration:{_num(times["to_out"])},'
            f'ease:"power2.in",immediateRender:false}},'
            f'{_num(start + times["to_out_at"])});')
        tweens.append(
            f'tl.set("#{node_id}-b{i}",{{opacity:0}},{_num(start + d)});')
    tweens.extend([
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-mist",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-haze",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-hot",{{opacity:0}},{_num(start + d)});',
    ])
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-thermal-distortion" {_timing(ctx)}>'
               f'<span class="td-stage">'
               f'<span id="{node_id}-blur" class="td-blur"></span>'
               f'<span id="{node_id}-from" class="td-from"></span>'
               f'<span id="{node_id}-to" class="td-to"></span>'
               f'<span id="{node_id}-mist" class="td-mist"></span>'
               f'<span id="{node_id}-haze" class="td-haze"></span>'
               f'<span id="{node_id}-hot" class="td-hot"></span>'
               f'{"".join(bands)}'
               f'</span></div>'],
        tweens=tweens)


_T3_CATALOG_SEC = 2.4


def _t3_times(duration: float) -> dict[str, float]:
    """Окно 3D card flip: каталог крутит rotationY 0.6 с внутри 11 с демо.

    На склейке шорта это ``ctx.duration`` (~0.3 с). Доли 2.4 с окна
    (удержание A → схлоп scaleX → раскрытие B) сохраняем, стыки +1 мс.
    """
    d = max(0.05, float(duration))
    s = d / _T3_CATALOG_SEC

    def t(catalog: float) -> float:
        return max(0.0, min(d, catalog * s))

    a_at = t(0.5)
    a_end = t(1.2)
    a_dur = max(0.001, a_end - a_at)
    b_at = t(1.21)
    if a_at + a_dur + 0.001 > b_at:
        a_dur = max(0.001, b_at - a_at - 0.001)
    b_end = min(d - 0.001, t(1.9))
    b_dur = max(0.001, b_end - b_at)
    a_kill = min(d, max(a_at + a_dur, b_at))
    edge_at = t(1.05)
    edge_mid = min(d - 0.002, max(edge_at + 0.001, t(1.21)))
    if edge_at + 0.001 > edge_mid:
        edge_at = max(0.0, edge_mid - 0.001)
    edge_in = max(0.001, edge_mid - edge_at)
    if edge_at + edge_in + 0.001 > edge_mid:
        edge_in = max(0.001, edge_mid - edge_at - 0.001)
    edge_end = min(d - 0.001, t(1.4))
    if edge_mid + 0.001 > edge_end:
        edge_end = min(d - 0.001, edge_mid + 0.001)
    edge_out = max(0.001, edge_end - edge_mid)
    return {
        "a_at": a_at,
        "a_dur": a_dur,
        "a_kill": a_kill,
        "b_at": b_at,
        "b_dur": b_dur,
        "edge_at": edge_at,
        "edge_in": edge_in,
        "edge_mid": edge_mid,
        "edge_out": edge_out,
    }


def tr_transitions_3d(ctx: "TemplateCtx") -> Piece:
    """3D card flip: SCENE A схлопывается, SCENE B раскрывается.

    Каталог твинит ``rotationY`` / ``filter`` / ``clipPath`` / ``zIndex``
    на сценах. Здесь ``scaleX``/``opacity``, грани ``var(--color-space-deep)``/``var(--color-accent)``.
    Твины на гранях / ребре, не на ``.clip`` и не на входящем кадре.
    Цвета SCENE A/B каталога — жест карточки, не палитра канала.
    ``-apple-system`` не ставим. Inter как запас вместо системного стека.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _t3_times(d)
    start = ctx.start
    tweens = [
        f'tl.fromTo("#{node_id}-a",{{scaleX:1}},'
        f'{{scaleX:0,duration:{_num(times["a_dur"])},ease:"power2.inOut"}},'
        f'{_num(start + times["a_at"])});',
        f'tl.set("#{node_id}-a",{{opacity:0}},'
        f'{_num(start + times["a_kill"])});',
        f'tl.fromTo("#{node_id}-b",{{scaleX:0,opacity:1}},'
        f'{{scaleX:1,duration:{_num(times["b_dur"])},ease:"power2.inOut"}},'
        f'{_num(start + times["b_at"])});',
        f'tl.fromTo("#{node_id}-edge",{{opacity:0}},'
        f'{{opacity:0.92,duration:{_num(times["edge_in"])},'
        f'ease:"power2.out"}},{_num(start + times["edge_at"])});',
        f'tl.to("#{node_id}-edge",{{opacity:0,duration:{_num(times["edge_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["edge_mid"])});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-edge",{{opacity:0}},{_num(start + d)});',
    ]
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-transitions-3d" {_timing(ctx)}>'
               f'<span class="t3-stage">'
               f'<span id="{node_id}-a" class="t3-face t3-a">'
               f'<span class="t3-big">ONE</span>'
               f'<span class="t3-label">SCENE A</span></span>'
               f'<span id="{node_id}-b" class="t3-face t3-b">'
               f'<span class="t3-big">TWO</span>'
               f'<span class="t3-label">SCENE B</span></span>'
               f'<span id="{node_id}-edge" class="t3-edge"></span>'
               f'</span></div>'],
        tweens=tweens)


_TB_CATALOG_SEC = 2.4


def _tb_times(duration: float) -> dict[str, float]:
    """Окно blur through: каталог твинит ``filter`` 0.4 с с перекрытием 0.2 с.

    На склейке шорта это ``ctx.duration`` (~0.3 с). Доли 2.4 с окна
    (удержание A → blur-out → blur-in B) сохраняем, стыки +1 мс.
    """
    d = max(0.05, float(duration))
    s = d / _TB_CATALOG_SEC

    def t(catalog: float) -> float:
        return max(0.0, min(d, catalog * s))

    a_at = t(1.0)
    a_end = t(1.4)
    a_dur = max(0.001, a_end - a_at)
    b_at = t(1.2)
    b_end = min(d - 0.001, t(1.6))
    if b_at + 0.001 > b_end:
        b_at = max(0.0, b_end - 0.001)
    b_dur = max(0.001, b_end - b_at)
    ag_at = a_at
    ag_mid = min(d - 0.002, max(ag_at + 0.001, a_at + a_dur * 0.5))
    if ag_at + 0.001 > ag_mid:
        ag_at = max(0.0, ag_mid - 0.001)
    ag_in = max(0.001, ag_mid - ag_at)
    if ag_at + ag_in + 0.001 > ag_mid:
        ag_in = max(0.001, ag_mid - ag_at - 0.001)
    ag_end = min(d - 0.001, max(ag_mid + 0.001, a_at + a_dur))
    if ag_mid + 0.001 > ag_end:
        ag_end = min(d - 0.001, ag_mid + 0.001)
    ag_out = max(0.001, ag_end - ag_mid)
    a_kill = min(d, max(a_at + a_dur, ag_end, b_at))
    return {
        "a_at": a_at,
        "a_dur": a_dur,
        "a_kill": a_kill,
        "ag_at": ag_at,
        "ag_in": ag_in,
        "ag_mid": ag_mid,
        "ag_out": ag_out,
        "b_at": b_at,
        "b_dur": b_dur,
    }


def tr_transitions_blur(ctx: "TemplateCtx") -> Piece:
    """Blur through: SCENE A уходит в размытие, SCENE B выходит из него.

    Каталог твинит ``filter`` / ``skewX`` / ``clipPath`` / ``zIndex`` на
    сценах. Здесь ``scale``/``opacity`` и призраки со статическим
    ``filter:blur(15px)``. Твины на гранях / призраках, не на ``.clip``
    и не на входящем кадре. Цвета SCENE A/B каталога — жест карточки,
    не палитра канала. ``-apple-system`` не ставим. Inter как запас
    вместо системного стека. ``blur-dip`` остаётся провалом
    ``backdrop-filter``.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _tb_times(d)
    start = ctx.start
    tweens = [
        f'tl.fromTo("#{node_id}-a",{{scale:1,opacity:1}},'
        f'{{scale:1.05,opacity:0,duration:{_num(times["a_dur"])},'
        f'ease:"power2.in"}},{_num(start + times["a_at"])});',
        f'tl.set("#{node_id}-a",{{opacity:0}},'
        f'{_num(start + times["a_kill"])});',
        f'tl.fromTo("#{node_id}-ag",{{scale:1,opacity:0}},'
        f'{{scale:1.03,opacity:0.8,duration:{_num(times["ag_in"])},'
        f'ease:"power2.in"}},{_num(start + times["ag_at"])});',
        f'tl.to("#{node_id}-ag",{{scale:1.05,opacity:0,'
        f'duration:{_num(times["ag_out"])},ease:"power2.in",'
        f'immediateRender:false}},{_num(start + times["ag_mid"])});',
        f'tl.set("#{node_id}-ag",{{opacity:0}},'
        f'{_num(start + times["a_kill"])});',
        f'tl.fromTo("#{node_id}-bg",{{scale:0.95,opacity:0.85}},'
        f'{{scale:1,opacity:0,duration:{_num(times["b_dur"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["b_at"])});',
        f'tl.fromTo("#{node_id}-b",{{scale:0.95,opacity:0}},'
        f'{{scale:1,opacity:1,duration:{_num(times["b_dur"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["b_at"])});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-ag",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-bg",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
    ]
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-transitions-blur" {_timing(ctx)}>'
               f'<span class="tb-stage">'
               f'<span id="{node_id}-a" class="tb-face tb-a">'
               f'<span class="tb-big">ONE</span>'
               f'<span class="tb-label">SCENE A</span></span>'
               f'<span id="{node_id}-ag" class="tb-face tb-a tb-ghost">'
               f'<span class="tb-big">ONE</span>'
               f'<span class="tb-label">SCENE A</span></span>'
               f'<span id="{node_id}-bg" class="tb-face tb-b tb-ghost">'
               f'<span class="tb-big">TWO</span>'
               f'<span class="tb-label">SCENE B</span></span>'
               f'<span id="{node_id}-b" class="tb-face tb-b">'
               f'<span class="tb-big">TWO</span>'
               f'<span class="tb-label">SCENE B</span></span>'
               f'</span></div>'],
        tweens=tweens)


_TC_CATALOG_SEC = 2.4


def _tc_times(duration: float) -> dict[str, float]:
    """Окно cover: каталог едет ``translateX`` 0.25 с со стаггером 0.06 с.

    На склейке шорта это ``ctx.duration`` (~0.3 с). Доли 2.4 с окна
    (удержание A → staggered wipes → удержание B) сохраняем, стыки +1 мс.
    """
    d = max(0.05, float(duration))
    s = d / _TC_CATALOG_SEC

    def t(catalog: float) -> float:
        return max(0.0, min(d, catalog * s))

    def span(start_cat: float, end_cat: float,
             after: float = 0.0) -> tuple[float, float]:
        at = max(t(start_cat), after)
        end = min(d, t(end_cat))
        if at + 0.001 > end:
            end = min(d, at + 0.001)
        if at + 0.001 > end:
            at = max(0.0, end - 0.001)
        return at, max(0.001, end - at)

    wa_in_at, wa_in_dur = span(1.00, 1.25)
    wb_in_at, wb_in_dur = span(1.06, 1.31, after=wa_in_at + 0.001)
    wa_out_at, wa_out_dur = span(
        1.28, 1.53, after=wa_in_at + wa_in_dur + 0.001)
    wb_out_at, wb_out_dur = span(
        1.34, 1.59,
        after=max(wb_in_at + wb_in_dur + 0.001, wa_out_at + 0.001))
    swap_at = min(max(t(1.20), wa_in_at + 0.001), wa_out_at)
    return {
        "wa_in_at": wa_in_at,
        "wa_in_dur": wa_in_dur,
        "wb_in_at": wb_in_at,
        "wb_in_dur": wb_in_dur,
        "swap_at": swap_at,
        "wa_out_at": wa_out_at,
        "wa_out_dur": wa_out_dur,
        "wb_out_at": wb_out_at,
        "wb_out_dur": wb_out_dur,
    }


def tr_transitions_cover(ctx: "TemplateCtx") -> Piece:
    """Cover: staggered blocks накрывают SCENE A и открывают SCENE B.

    Каталог ставит CSS ``transform: translateX(-1920px)`` и твинит ``x`` /
    ``textContent`` / ``innerHTML`` / ``zIndex``. Здесь GSAP ``x`` на
    1080 px без CSS ``transform``, вуали ``var(--color-accent)``/``var(--color-accent-deep)``. Твины
    на гранях / вайпах, не на ``.clip`` и не на входящем кадре. Цвета
    SCENE A/B и вайпов каталога — жест карточки, не палитра канала.
    ``-apple-system`` не ставим. Inter как запас вместо системного стека.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _tc_times(d)
    start = ctx.start
    tweens = [
        f'tl.fromTo("#{node_id}-wa",{{x:-1080,opacity:1}},'
        f'{{x:0,opacity:1,duration:{_num(times["wa_in_dur"])},'
        f'ease:"power3.inOut",immediateRender:false}},'
        f'{_num(start + times["wa_in_at"])});',
        f'tl.fromTo("#{node_id}-wb",{{x:-1080,opacity:1}},'
        f'{{x:0,opacity:1,duration:{_num(times["wb_in_dur"])},'
        f'ease:"power3.inOut",immediateRender:false}},'
        f'{_num(start + times["wb_in_at"])});',
        f'tl.set("#{node_id}-a",{{opacity:0}},'
        f'{_num(start + times["swap_at"])});',
        f'tl.set("#{node_id}-b",{{opacity:1}},'
        f'{_num(start + times["swap_at"])});',
        f'tl.to("#{node_id}-wa",{{x:1080,opacity:1,'
        f'duration:{_num(times["wa_out_dur"])},ease:"power3.inOut",'
        f'immediateRender:false}},{_num(start + times["wa_out_at"])});',
        f'tl.to("#{node_id}-wb",{{x:1080,opacity:1,'
        f'duration:{_num(times["wb_out_dur"])},ease:"power3.inOut",'
        f'immediateRender:false}},{_num(start + times["wb_out_at"])});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-wa",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-wb",{{opacity:0}},{_num(start + d)});',
    ]
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-transitions-cover" {_timing(ctx)}>'
               f'<span class="tc-stage">'
               f'<span id="{node_id}-a" class="tc-face tc-a">'
               f'<span class="tc-big">ONE</span>'
               f'<span class="tc-label">SCENE A</span></span>'
               f'<span id="{node_id}-b" class="tc-face tc-b">'
               f'<span class="tc-big">TWO</span>'
               f'<span class="tc-label">SCENE B</span></span>'
               f'<span id="{node_id}-wb" class="tc-wipe tc-wb"></span>'
               f'<span id="{node_id}-wa" class="tc-wipe tc-wa"></span>'
               f'</span></div>'],
        tweens=tweens)


_TDS_CATALOG_SEC = 2.4


def _tds_times(duration: float) -> dict[str, float]:
    """Окно page burn: каталог 3 с canvas ``onUpdate`` и ``clip-path``.

    На склейке шорта это ``ctx.duration`` (~0.3 с). Доли 2.4 с окна
    (удержание A → burn → удержание B) сохраняем, стыки +1 мс.
    """
    d = max(0.05, float(duration))
    s = d / _TDS_CATALOG_SEC

    def t(catalog: float) -> float:
        return max(0.0, min(d, catalog * s))

    def span(start_cat: float, end_cat: float,
             after: float = 0.0) -> tuple[float, float]:
        at = max(t(start_cat), after)
        end = min(d, t(end_cat))
        if at + 0.001 > end:
            end = min(d, at + 0.001)
        if at + 0.001 > end:
            at = max(0.0, end - 0.001)
        return at, max(0.001, end - at)

    burn_at, burn_dur = span(1.00, 2.00)
    b_at, b_dur = span(1.167, 1.833, after=burn_at + 0.001)
    kill_at = min(d, max(burn_at + burn_dur, b_at + b_dur))
    return {
        "burn_at": burn_at,
        "burn_dur": burn_dur,
        "b_at": b_at,
        "b_dur": b_dur,
        "kill_at": kill_at,
    }


_TDS_RINGS = ((1.02, 0.041), (1.08, 0.043), (1.16, 0.046))


_TDS_HOLE_FROM = 1.0


_TDS_HOLE_TO = 0.04


_TDS_A_TO = _TDS_HOLE_FROM / _TDS_HOLE_TO


def tr_transitions_destruction(ctx: "TemplateCtx") -> Piece:
    """Page burn: SCENE A сгорает кругом, SCENE B проявляется.

    Каталог рисует canvas ``onUpdate``, ``clip-path`` и ``Math.sin``-шум.
    Здесь круг ``overflow:hidden`` и ``scale``, кольца огня без canvas.
    Твины на дыре / гранях / кольцах, не на ``.clip`` и не на входящем
    кадре. Цвета SCENE A/B и огня каталога — жест карточки, не палитра
    канала. ``-apple-system`` не ставим. Inter как запас вместо
    системного стека. ``sdf-iris`` и ``mask-wipe-circle`` не трогаем.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _tds_times(d)
    start = ctx.start
    tweens = [
        f'tl.fromTo("#{node_id}-hole",{{scale:{_num(_TDS_HOLE_FROM)},opacity:1}},'
        f'{{scale:{_num(_TDS_HOLE_TO)},opacity:1,duration:{_num(times["burn_dur"])},'
        f'ease:"power1.in",immediateRender:false}},'
        f'{_num(start + times["burn_at"])});',
        f'tl.fromTo("#{node_id}-a",{{scale:1,opacity:1}},'
        f'{{scale:{_num(_TDS_A_TO)},opacity:1,duration:{_num(times["burn_dur"])},'
        f'ease:"power1.in",immediateRender:false}},'
        f'{_num(start + times["burn_at"])});',
        f'tl.fromTo("#{node_id}-b",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(times["b_dur"])},'
        f'ease:"power1.out",immediateRender:false}},'
        f'{_num(start + times["b_at"])});',
    ]
    for i, (s0, s1) in enumerate(_TDS_RINGS):
        tweens.append(
            f'tl.fromTo("#{node_id}-r{i}",{{scale:{_num(s0)},opacity:1}},'
            f'{{scale:{_num(s1)},opacity:1,duration:{_num(times["burn_dur"])},'
            f'ease:"power1.in",immediateRender:false}},'
            f'{_num(start + times["burn_at"])});')
    for suffix in ("hole", "a", "r0", "r1", "r2"):
        tweens.append(
            f'tl.set("#{node_id}-{suffix}",{{opacity:0}},'
            f'{_num(start + times["kill_at"])});')
    for suffix in ("hole", "a", "b", "r0", "r1", "r2"):
        tweens.append(
            f'tl.set("#{node_id}-{suffix}",{{opacity:0}},{_num(start + d)});')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-transitions-destruction" {_timing(ctx)}>'
               f'<span class="tds-stage">'
               f'<span id="{node_id}-b" class="tds-face tds-b">'
               f'<span class="tds-big">TWO</span>'
               f'<span class="tds-label">SCENE B</span></span>'
               f'<span id="{node_id}-hole" class="tds-hole">'
               f'<span id="{node_id}-a" class="tds-face tds-a">'
               f'<span class="tds-big">ONE</span>'
               f'<span class="tds-label">SCENE A</span></span></span>'
               f'<span id="{node_id}-r2" class="tds-ring tds-r2"></span>'
               f'<span id="{node_id}-r1" class="tds-ring tds-r1"></span>'
               f'<span id="{node_id}-r0" class="tds-ring tds-r0"></span>'
               f'</span></div>'],
        tweens=tweens)


_TLT_CATALOG_SEC = 2.4


def _tlt_times(duration: float) -> dict[str, float]:
    """Окно light leak: каталог едет ``x`` и твинит ``opacity`` бликов.

    На склейке шорта это ``ctx.duration`` (~0.3 с). Доли 2.4 с окна
    (удержание A → leak → удержание B) сохраняем, стыки +1 мс.
    """
    d = max(0.05, float(duration))
    s = d / _TLT_CATALOG_SEC

    def t(catalog: float) -> float:
        return max(0.0, min(d, catalog * s))

    def span(start_cat: float, end_cat: float,
             after: float = 0.0) -> tuple[float, float]:
        at = max(t(start_cat), after)
        end = min(d, t(end_cat))
        if at + 0.001 > end:
            end = min(d, at + 0.001)
        if at + 0.001 > end:
            at = max(0.0, end - 0.001)
        return at, max(0.001, end - at)

    warm_in_at, warm_in_dur = span(1.00, 1.30)
    l1_in_at, l1_in_dur = span(1.05, 1.55)
    l2_in_at, l2_in_dur = span(1.10, 1.70)
    warm_peak_at, warm_peak_dur = span(
        1.35, 1.50, after=warm_in_at + warm_in_dur + 0.001)
    warm_out_at, warm_out_dur = span(
        1.50, 1.90, after=warm_peak_at + warm_peak_dur + 0.001)
    l1_out_at, l1_out_dur = span(
        1.50, 1.85, after=l1_in_at + l1_in_dur + 0.001)
    l2_out_at, l2_out_dur = span(
        1.55, 1.90, after=l2_in_at + l2_in_dur + 0.001)
    swap_at = min(max(t(1.45), warm_in_at + 0.001), warm_out_at)
    return {
        "warm_in_at": warm_in_at,
        "warm_in_dur": warm_in_dur,
        "l1_in_at": l1_in_at,
        "l1_in_dur": l1_in_dur,
        "l2_in_at": l2_in_at,
        "l2_in_dur": l2_in_dur,
        "warm_peak_at": warm_peak_at,
        "warm_peak_dur": warm_peak_dur,
        "swap_at": swap_at,
        "warm_out_at": warm_out_at,
        "warm_out_dur": warm_out_dur,
        "l1_out_at": l1_out_at,
        "l1_out_dur": l1_out_dur,
        "l2_out_at": l2_out_at,
        "l2_out_dur": l2_out_dur,
    }


_TLT_L1_IN_X = 169


_TLT_L1_OUT_X = 338


_TLT_L2_IN_X = 112


_TLT_L2_OUT_X = 225


def tr_transitions_light(ctx: "TemplateCtx") -> Piece:
    """Light leak: тёплые блики едут по кадру, SCENE B проявляется.

    Каталог DEMO 1 твинит ``opacity``/``x`` трёх бликов. Здесь те же
    ``x`` на 9:16 (300→169) без CSS ``transform`` и без ``filter``.
    Твины на гранях / бликах, не на ``.clip`` и не на входящем кадре.
    Цвета SCENE A/B и оранжевых leak каталога — жест карточки, не
    палитра канала. ``-apple-system`` не ставим. Inter как запас
    вместо системного стека. ``light-leak`` и ``light-sweep`` не
    трогаем.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _tlt_times(d)
    start = ctx.start
    tweens = [
        f'tl.fromTo("#{node_id}-warm",{{opacity:0}},'
        f'{{opacity:0.4,duration:{_num(times["warm_in_dur"])},'
        f'ease:"power1.in",immediateRender:false}},'
        f'{_num(start + times["warm_in_at"])});',
        f'tl.to("#{node_id}-warm",{{opacity:0.6,'
        f'duration:{_num(times["warm_peak_dur"])},ease:"power2.in",'
        f'immediateRender:false}},{_num(start + times["warm_peak_at"])});',
        f'tl.to("#{node_id}-warm",{{opacity:0,'
        f'duration:{_num(times["warm_out_dur"])},ease:"power2.out",'
        f'immediateRender:false}},{_num(start + times["warm_out_at"])});',
        f'tl.fromTo("#{node_id}-l1",{{x:0,opacity:0.9}},'
        f'{{x:{_TLT_L1_IN_X},opacity:0.9,duration:{_num(times["l1_in_dur"])},'
        f'ease:"sine.inOut",immediateRender:false}},'
        f'{_num(start + times["l1_in_at"])});',
        f'tl.to("#{node_id}-l1",{{x:{_TLT_L1_OUT_X},opacity:0,'
        f'duration:{_num(times["l1_out_dur"])},ease:"power1.out",'
        f'immediateRender:false}},{_num(start + times["l1_out_at"])});',
        f'tl.fromTo("#{node_id}-l2",{{x:0,opacity:0.8}},'
        f'{{x:{_TLT_L2_IN_X},opacity:0.8,duration:{_num(times["l2_in_dur"])},'
        f'ease:"sine.inOut",immediateRender:false}},'
        f'{_num(start + times["l2_in_at"])});',
        f'tl.to("#{node_id}-l2",{{x:{_TLT_L2_OUT_X},opacity:0,'
        f'duration:{_num(times["l2_out_dur"])},ease:"power1.out",'
        f'immediateRender:false}},{_num(start + times["l2_out_at"])});',
        f'tl.set("#{node_id}-a",{{opacity:0}},'
        f'{_num(start + times["swap_at"])});',
        f'tl.set("#{node_id}-b",{{opacity:1}},'
        f'{_num(start + times["swap_at"])});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-warm",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-l1",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-l2",{{opacity:0}},{_num(start + d)});',
    ]
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-transitions-light" {_timing(ctx)}>'
               f'<span class="tlt-stage">'
               f'<span id="{node_id}-a" class="tlt-face tlt-a">'
               f'<span class="tlt-big">ONE</span>'
               f'<span class="tlt-label">SCENE A</span></span>'
               f'<span id="{node_id}-b" class="tlt-face tlt-b">'
               f'<span class="tlt-big">TWO</span>'
               f'<span class="tlt-label">SCENE B</span></span>'
               f'<span id="{node_id}-warm" class="tlt-warm"></span>'
               f'<span id="{node_id}-l1" class="tlt-blob tlt-l1"></span>'
               f'<span id="{node_id}-l2" class="tlt-blob tlt-l2"></span>'
               f'</span></div>'],
        tweens=tweens)


_TTO_CATALOG_SEC = 2.4


def _tto_times(duration: float) -> dict[str, float]:
    """Окно flash cut: каталог 0.03 с вспышка, 0.1 с спад.

    На склейке шорта это ``ctx.duration`` (~0.3 с). Доли 2.4 с окна
    (удержание A → flash → удержание B) сохраняем, стыки +1 мс.
    """
    d = max(0.05, float(duration))
    s = d / _TTO_CATALOG_SEC

    def t(catalog: float) -> float:
        return max(0.0, min(d, catalog * s))

    def span(start_cat: float, end_cat: float,
             after: float = 0.0) -> tuple[float, float]:
        at = max(t(start_cat), after)
        end = min(d, t(end_cat))
        if at + 0.001 > end:
            end = min(d, at + 0.001)
        if at + 0.001 > end:
            at = max(0.0, end - 0.001)
        return at, max(0.001, end - at)

    flash_in_at, flash_in_dur = span(1.00, 1.03)
    flash_out_at, flash_out_dur = span(
        1.05, 1.15, after=flash_in_at + flash_in_dur + 0.001)
    swap_at = min(max(t(1.03), flash_in_at + flash_in_dur), flash_out_at)
    return {
        "flash_in_at": flash_in_at,
        "flash_in_dur": flash_in_dur,
        "swap_at": swap_at,
        "flash_out_at": flash_out_at,
        "flash_out_dur": flash_out_dur,
    }


def tr_transitions_other(ctx: "TemplateCtx") -> Piece:
    """Flash cut: белая вспышка на склейке, SCENE B проявляется.

    Каталог DEMO 1 твинит ``opacity`` белого оверлея 0.03 с вверх и
    0.1 с вниз. Здесь те же твины без CSS ``transform`` и без ``filter``.
    Твины на гранях / вспышке, не на ``.clip`` и не на входящем кадре.
    Цвета SCENE A/B и белой вспышки каталога — жест карточки, не палитра
    канала. ``-apple-system`` не ставим. Inter как запас вместо
    системного стека. ``white_flash`` не трогаем.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _tto_times(d)
    start = ctx.start
    tweens = [
        f'tl.fromTo("#{node_id}-flash",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(times["flash_in_dur"])},'
        f'ease:"power4.out",immediateRender:false}},'
        f'{_num(start + times["flash_in_at"])});',
        f'tl.fromTo("#{node_id}-flash",{{opacity:1}},'
        f'{{opacity:0,duration:{_num(times["flash_out_dur"])},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["flash_out_at"])});',
        f'tl.fromTo("#{node_id}-a",{{opacity:1}},'
        f'{{opacity:0,duration:0.001,ease:"none",immediateRender:false}},'
        f'{_num(start + times["swap_at"])});',
        f'tl.fromTo("#{node_id}-b",{{opacity:0}},'
        f'{{opacity:1,duration:0.001,ease:"none",immediateRender:false}},'
        f'{_num(start + times["swap_at"])});',
        f'tl.set("#{node_id}-a",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-b",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-flash",{{opacity:0}},{_num(start + d)});',
    ]
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-transitions-other" {_timing(ctx)}>'
               f'<span class="tto-stage">'
               f'<span id="{node_id}-a" class="tto-face tto-a">'
               f'<span class="tto-big">ONE</span>'
               f'<span class="tto-label">SCENE A</span></span>'
               f'<span id="{node_id}-b" class="tto-face tto-b">'
               f'<span class="tto-big">TWO</span>'
               f'<span class="tto-label">SCENE B</span></span>'
               f'<span id="{node_id}-flash" class="tto-flash"></span>'
               f'</span></div>'],
        tweens=tweens)


def _wp_times(duration: float) -> dict[str, float]:
    """Окно whip-pan шейдера: каталог держит 2 с внутри 4 с демо."""
    return _cz_times(duration)


def tr_whip_pan_shader(ctx: "TemplateCtx") -> Piece:
    """Whip pan: оба кадра едут вбок с направленным смазом.

    Каталог рисует WebGL ``onUpdate``: 10 семплов, fromOff/toOff.
    Здесь вуали ``var(--color-space-deep)``/``var(--color-accent)``, стальной слой и полосы смаза, ``x``.
    Без canvas. Цвета SCENE A/B каталога — жест шейдера, не палитра канала.
    ``whip-pan-l``/``whip-pan-r`` остаются рывком кадра ``tr-blur``.
    """
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    times = _wp_times(d)
    start = ctx.start
    tweens = [
        f'tl.fromTo("#{node_id}-from",{{x:0}},'
        f'{{x:-360,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-from",{{opacity:0.5}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{x:280}},'
        f'{{x:0,duration:{_num(times["dur"])},ease:"power2.inOut"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-to",{{opacity:0}},'
        f'{{opacity:0.4,duration:{_num(times["mid"])},ease:"power2.out"}},{_num(start)});',
        f'tl.to("#{node_id}-to",{{opacity:0,duration:{_num(times["to_out"])},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["to_out_at"])});',
        f'tl.fromTo("#{node_id}-steel",{{opacity:0.22}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
        f'tl.fromTo("#{node_id}-blur",{{opacity:0.7}},'
        f'{{opacity:0,duration:{_num(times["dur"])},ease:"power2.out"}},{_num(start)});',
    ]
    streaks = []
    for i in range(6):
        x0 = 48 - i * 8
        x1 = -220 - i * 40
        op = 0.72 - i * 0.08
        streaks.append(
            f'<span id="{node_id}-s{i}" class="wp-streak wp-s{i}"></span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-s{i}",{{x:{x0}}},'
            f'{{x:{x1},duration:{_num(times["dur"])},'
            f'ease:"power2.inOut"}},{_num(start)});')
        tweens.append(
            f'tl.fromTo("#{node_id}-s{i}",{{opacity:0}},'
            f'{{opacity:{_num(op)},duration:{_num(times["mid"])},'
            f'ease:"power2.out"}},{_num(start)});')
        tweens.append(
            f'tl.to("#{node_id}-s{i}",{{opacity:0,duration:{_num(times["to_out"])},'
            f'ease:"power2.in",immediateRender:false}},'
            f'{_num(start + times["to_out_at"])});')
        tweens.append(
            f'tl.set("#{node_id}-s{i}",{{opacity:0}},{_num(start + d)});')
    tweens.extend([
        f'tl.set("#{node_id}-from",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-to",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-steel",{{opacity:0}},{_num(start + d)});',
        f'tl.set("#{node_id}-blur",{{opacity:0}},{_num(start + d)});',
    ])
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-whip-pan" {_timing(ctx)}>'
               f'<span class="wp-stage">'
               f'<span id="{node_id}-blur" class="wp-blur"></span>'
               f'<span id="{node_id}-from" class="wp-from"></span>'
               f'<span id="{node_id}-to" class="wp-to"></span>'
               f'<span id="{node_id}-steel" class="wp-steel"></span>'
               f'{"".join(streaks)}'
               f'</span></div>'],
        tweens=tweens)


def ported_css(brandbook: dict[str, Any]) -> str:
    """Стиль перенесённых приёмов.

    Считался исполнением обеих сторон на нашем брендбуке:
    взяты правила тех классов, которых у нас не было.
    Приём, живущий отдельным модулем, приносит свой стиль сам.
    """
    rules = (
        '.tr-cinematic-zoom{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-cinematic-zoom .cz-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-cinematic-zoom .cz-blur,.tr-cinematic-zoom .cz-from,.tr-cinematic-zoom .cz-to,.tr-cinematic-zoom .cz-r,.tr-cinematic-zoom .cz-b,.tr-cinematic-zoom .cz-ghost{position:absolute;inset:0;display:block;opacity:0;transform-origin:50% 50%}'
        '.tr-cinematic-zoom .cz-blur{backdrop-filter:blur(16px)}'
        '.tr-cinematic-zoom .cz-from{background:var(--color-panel);mix-blend-mode:overlay}'
        '.tr-cinematic-zoom .cz-to{background:var(--color-accent);mix-blend-mode:overlay}'
        '.tr-cinematic-zoom .cz-r{inset:-18%;border-radius:50%;background:radial-gradient(circle,rgba(230,57,70,0.72) 0%,transparent 58%);mix-blend-mode:screen}'
        '.tr-cinematic-zoom .cz-b{inset:-14%;border-radius:50%;background:radial-gradient(circle,rgba(122,125,130,0.65) 0%,transparent 58%);mix-blend-mode:screen}'
        '.tr-cinematic-zoom .cz-ghost{background:radial-gradient(circle,rgba(255,255,255,0.22) 0%,transparent 70%);mix-blend-mode:screen}'
        '.tr-glitch-shader{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-glitch-shader .gs-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-glitch-shader .gs-from,.tr-glitch-shader .gs-to,.tr-glitch-shader .gs-lines,.tr-glitch-shader .gs-flick,.tr-glitch-shader .gs-r,.tr-glitch-shader .gs-b{position:absolute;inset:0;display:block;opacity:0;transform-origin:50% 50%}'
        '.tr-glitch-shader .gs-from{background:var(--color-panel);mix-blend-mode:overlay}'
        '.tr-glitch-shader .gs-to{background:var(--color-accent);mix-blend-mode:overlay}'
        '.tr-glitch-shader .gs-lines{background:repeating-linear-gradient(to bottom,transparent 0px,transparent 1px,rgba(0,0,0,0.22) 1px,rgba(0,0,0,0.22) 2px);mix-blend-mode:multiply}'
        '.tr-glitch-shader .gs-flick{background:var(--color-bg-pure);mix-blend-mode:overlay}'
        '.tr-glitch-shader .gs-r{background:var(--color-accent);mix-blend-mode:screen}'
        '.tr-glitch-shader .gs-b{background:var(--color-muted);mix-blend-mode:screen}'
        '.tr-glitch-shader .gs-scan{position:absolute;left:-12%;width:124%;display:block;opacity:0;background:rgba(230,57,70,0.5);mix-blend-mode:overlay}'
        '.tr-glitch-shader .gs-block{position:absolute;display:block;opacity:0;background:rgba(122,125,130,0.35);mix-blend-mode:screen}'
        '.tr-gravitational-lens{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-gravitational-lens .gw-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-gravitational-lens .gw-blur,.tr-gravitational-lens .gw-from,.tr-gravitational-lens .gw-to,.tr-gravitational-lens .gw-well,.tr-gravitational-lens .gw-r,.tr-gravitational-lens .gw-b,.tr-gravitational-lens .gw-ghost{position:absolute;inset:0;display:block;opacity:0;transform-origin:50% 50%}'
        '.tr-gravitational-lens .gw-blur{backdrop-filter:blur(14px)}'
        '.tr-gravitational-lens .gw-from{background:var(--color-accent-deep);mix-blend-mode:overlay}'
        '.tr-gravitational-lens .gw-to{background:var(--color-accent);mix-blend-mode:overlay}'
        '.tr-gravitational-lens .gw-well{inset:-28%;border-radius:50%;background:radial-gradient(circle,var(--color-ink) 0%,transparent 62%);mix-blend-mode:multiply}'
        '.tr-gravitational-lens .gw-r{inset:-16%;border-radius:50%;background:radial-gradient(circle,rgba(230,57,70,0.78) 0%,transparent 58%);mix-blend-mode:screen}'
        '.tr-gravitational-lens .gw-b{inset:-12%;border-radius:50%;background:radial-gradient(circle,rgba(160,128,160,0.62) 0%,transparent 58%);mix-blend-mode:screen}'
        '.tr-gravitational-lens .gw-ghost{background:radial-gradient(circle,rgba(230,57,70,0.2) 0%,transparent 70%);mix-blend-mode:screen}'
        '.tr-light-leak{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-light-leak .ll-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-light-leak .ll-from,.tr-light-leak .ll-to,.tr-light-leak .ll-sage,.tr-light-leak .ll-blob,.tr-light-leak .ll-hot,.tr-light-leak .ll-orb{position:absolute;inset:0;display:block;opacity:0;transform-origin:50% 50%}'
        '.tr-light-leak .ll-from{background:var(--color-space-deep);mix-blend-mode:overlay}'
        '.tr-light-leak .ll-to{background:var(--color-accent);mix-blend-mode:overlay}'
        '.tr-light-leak .ll-sage{background:var(--color-muted);mix-blend-mode:overlay}'
        '.tr-light-leak .ll-blob{inset:-48% -38% 18% 12%;border-radius:50%;background:radial-gradient(circle at 78% 22%,rgba(237,116,125,0.95) 0%,rgba(230,57,70,0.78) 34%,rgba(230,57,70,0.28) 58%,transparent 74%);mix-blend-mode:screen}'
        '.tr-light-leak .ll-hot{inset:-18% -12% 62% 48%;border-radius:50%;background:radial-gradient(circle,rgba(237,116,125,0.9) 0%,transparent 62%);mix-blend-mode:screen}'
        '.tr-light-leak .ll-flare{position:absolute;display:block;opacity:0;left:-28%;top:2%;width:156%;height:24%;background:linear-gradient(108deg,transparent 22%,rgba(237,116,125,0) 38%,rgba(237,116,125,0.88) 50%,rgba(230,57,70,0.5) 58%,transparent 78%);mix-blend-mode:screen;transform-origin:50% 50%}'
        '.tr-light-leak .ll-o0{inset:-36% -18% 48% 28%;border-radius:50%;background:radial-gradient(circle,rgba(230,57,70,0.4) 0%,transparent 70%);mix-blend-mode:screen}'
        '.tr-light-leak .ll-o1{inset:-22% -8% 38% 8%;border-radius:50%;background:radial-gradient(circle,rgba(237,116,125,0.32) 0%,transparent 70%);mix-blend-mode:screen}'
        '.tr-sdf-iris{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-sdf-iris .si-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-sdf-iris .si-from,.tr-sdf-iris .si-steel{position:absolute;inset:0;display:block;opacity:0;transform-origin:50% 50%}'
        '.tr-sdf-iris .si-from{background:var(--color-space-deep);mix-blend-mode:overlay}'
        '.tr-sdf-iris .si-steel{background:var(--color-muted);mix-blend-mode:overlay}'
        '.tr-sdf-iris .si-iris,.tr-sdf-iris .si-ring{position:absolute;left:50%;top:50%;width:2400px;height:2400px;margin:-1200px 0 0 -1200px;border-radius:50%;display:block;opacity:0;transform-origin:50% 50%}'
        '.tr-sdf-iris .si-iris{background:var(--color-accent);mix-blend-mode:overlay}'
        '.tr-sdf-iris .si-ring{background:radial-gradient(circle,transparent 46%,rgba(237,116,125,0.92) 50%,transparent 54%);mix-blend-mode:screen}'
        '.tr-thermal-distortion{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-thermal-distortion .td-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-thermal-distortion .td-from,.tr-thermal-distortion .td-to,.tr-thermal-distortion .td-mist,.tr-thermal-distortion .td-blur{position:absolute;inset:0;display:block;opacity:0;transform-origin:50% 50%}'
        '.tr-thermal-distortion .td-from{background:var(--color-panel);mix-blend-mode:overlay}'
        '.tr-thermal-distortion .td-to{background:var(--color-accent);mix-blend-mode:overlay}'
        '.tr-thermal-distortion .td-mist{background:var(--color-text-soft);mix-blend-mode:overlay}'
        '.tr-thermal-distortion .td-blur{backdrop-filter:blur(10px)}'
        '.tr-thermal-distortion .td-haze,.tr-thermal-distortion .td-hot{position:absolute;display:block;opacity:0;border-radius:50%;transform-origin:50% 50%}'
        '.tr-thermal-distortion .td-haze{inset:32% -24% -28% -24%;background:radial-gradient(circle at 50% 78%,rgba(237,116,125,0.92) 0%,rgba(230,57,70,0.55) 42%,transparent 70%);mix-blend-mode:screen}'
        '.tr-thermal-distortion .td-hot{inset:58% -8% -22% -8%;background:radial-gradient(circle,rgba(237,116,125,0.9) 0%,transparent 62%);mix-blend-mode:screen}'
        '.tr-thermal-distortion .td-band{position:absolute;left:-12%;width:124%;height:120px;display:block;opacity:0;background:linear-gradient(180deg,transparent 0%,rgba(237,116,125,0.7) 50%,transparent 100%);mix-blend-mode:screen;transform-origin:50% 50%}'
        '.tr-thermal-distortion .td-b0{top:1080px}'
        '.tr-thermal-distortion .td-b1{top:1240px}'
        '.tr-thermal-distortion .td-b2{top:1400px}'
        '.tr-thermal-distortion .td-b3{top:1560px}'
        '.tr-thermal-distortion .td-b4{top:1720px}'
        '.tr-whip-pan{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-whip-pan .wp-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-whip-pan .wp-from,.tr-whip-pan .wp-to,.tr-whip-pan .wp-steel,.tr-whip-pan .wp-blur{position:absolute;inset:0;display:block;opacity:0;transform-origin:50% 50%}'
        '.tr-whip-pan .wp-from{background:var(--color-space-deep);mix-blend-mode:overlay}'
        '.tr-whip-pan .wp-to{background:var(--color-accent);mix-blend-mode:overlay}'
        '.tr-whip-pan .wp-steel{background:var(--color-muted);mix-blend-mode:overlay}'
        '.tr-whip-pan .wp-blur{backdrop-filter:blur(10px)}'
        '.tr-whip-pan .wp-streak{position:absolute;left:-18%;width:136%;height:88px;display:block;opacity:0;background:linear-gradient(90deg,transparent 0%,rgba(230,57,70,0) 12%,rgba(230,57,70,0.88) 48%,rgba(11,19,43,0.45) 78%,transparent 100%);mix-blend-mode:screen;transform-origin:50% 50%}'
        '.tr-whip-pan .wp-s0{top:80px}'
        '.tr-whip-pan .wp-s1{top:380px}'
        '.tr-whip-pan .wp-s2{top:680px}'
        '.tr-whip-pan .wp-s3{top:980px}'
        '.tr-whip-pan .wp-s4{top:1280px}'
        '.tr-whip-pan .wp-s5{top:1580px}'
        '.tr-mk-clone-wall{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-mk-clone-wall .cw-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-mk-clone-wall .cw-wall,.tr-mk-clone-wall .cw-tiles{position:absolute;inset:0;display:block;transform-origin:50% 50%}'
        '.tr-mk-clone-wall .cw-wall{background:var(--color-space-deep);isolation:isolate}'
        '.tr-mk-clone-wall .cw-row{position:absolute;white-space:nowrap;font-family:var(--font-subtitle);font-weight:600;letter-spacing:-0.02em;color:var(--color-ink);line-height:1}'
        '.tr-mk-clone-wall .cw-tile{display:inline-block}'
        '.tr-mk-clone-wall .cw-invert{position:absolute;inset:0;display:block;transform-origin:50% 50%;background:var(--color-bg-pure);mix-blend-mode:difference}'
        '.tr-mk-clone-wall .cw-card{position:absolute;inset:0;display:block;transform-origin:50% 50%;border-radius:0;overflow:hidden;background:linear-gradient(120deg,var(--color-accent-soft) 0%,var(--color-accent-soft) 38%,var(--color-accent) 100%);box-shadow:0 30px 80px rgba(0,0,0,0.22)}'
        '.tr-transitions-3d{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-transitions-3d .t3-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-transitions-3d .t3-face{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;transform-origin:50% 50%}'
        '.tr-transitions-3d .t3-a{background:var(--color-space-deep)}'
        '.tr-transitions-3d .t3-b{background:var(--color-accent);opacity:0}'
        '.tr-transitions-3d .t3-big{font-family:var(--font-subtitle);font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}'
        '.tr-transitions-3d .t3-a .t3-big{color:rgba(255,255,255,0.08)}'
        '.tr-transitions-3d .t3-b .t3-big{color:rgba(255,255,255,0.15)}'
        '.tr-transitions-3d .t3-label{font-family:var(--font-subtitle);font-size:40px;font-weight:600;letter-spacing:6px;margin-top:12px}'
        '.tr-transitions-3d .t3-a .t3-label{color:var(--color-muted)}'
        '.tr-transitions-3d .t3-b .t3-label{color:var(--color-bg-pure)}'
        '.tr-transitions-3d .t3-edge{position:absolute;left:50%;top:0;width:8px;height:100%;margin-left:-4px;display:block;opacity:0;background:var(--color-muted);transform-origin:50% 50%}'
        '.tr-transitions-blur{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-transitions-blur .tb-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-transitions-blur .tb-face{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;transform-origin:50% 50%}'
        '.tr-transitions-blur .tb-a{background:var(--color-space-deep)}'
        '.tr-transitions-blur .tb-b{background:var(--color-accent);opacity:0}'
        '.tr-transitions-blur .tb-ghost{filter:blur(15px);opacity:0}'
        '.tr-transitions-blur .tb-big{font-family:var(--font-subtitle);font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}'
        '.tr-transitions-blur .tb-a .tb-big{color:rgba(255,255,255,0.08)}'
        '.tr-transitions-blur .tb-b .tb-big{color:rgba(255,255,255,0.15)}'
        '.tr-transitions-blur .tb-label{font-family:var(--font-subtitle);font-size:40px;font-weight:600;letter-spacing:6px;margin-top:12px}'
        '.tr-transitions-blur .tb-a .tb-label{color:var(--color-muted)}'
        '.tr-transitions-blur .tb-b .tb-label{color:var(--color-bg-pure)}'
        '.tr-transitions-cover{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-transitions-cover .tc-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-transitions-cover .tc-face{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;transform-origin:50% 50%}'
        '.tr-transitions-cover .tc-a{background:var(--color-space-deep)}'
        '.tr-transitions-cover .tc-b{background:var(--color-accent);opacity:0}'
        '.tr-transitions-cover .tc-big{font-family:var(--font-subtitle);font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}'
        '.tr-transitions-cover .tc-a .tc-big{color:rgba(255,255,255,0.12)}'
        '.tr-transitions-cover .tc-b .tc-big{color:rgba(0,0,0,0.12)}'
        '.tr-transitions-cover .tc-label{font-family:var(--font-subtitle);font-size:40px;font-weight:700;letter-spacing:6px;margin-top:12px;color:var(--color-bg-pure)}'
        '.tr-transitions-cover .tc-wipe{position:absolute;inset:0;display:block;opacity:0}'
        '.tr-transitions-cover .tc-wb{background:var(--color-accent-deep)}'
        '.tr-transitions-cover .tc-wa{background:var(--color-accent)}'
        '.tr-transitions-destruction{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-transitions-destruction .tds-stage{display:block;width:100%;height:100%;position:relative;background:var(--color-ink)}'
        '.tr-transitions-destruction .tds-face{display:flex;flex-direction:column;align-items:center;justify-content:center;transform-origin:50% 50%}'
        '.tr-transitions-destruction .tds-b{position:absolute;inset:0;background:var(--color-accent);opacity:0}'
        '.tr-transitions-destruction .tds-hole{position:absolute;left:50%;top:50%;width:2242px;height:2242px;margin:-1121px 0 0 -1121px;border-radius:50%;overflow:hidden;display:block;transform-origin:50% 50%}'
        '.tr-transitions-destruction .tds-hole .tds-a{position:absolute;left:50%;top:50%;width:1080px;height:1920px;margin:-960px 0 0 -540px;background:var(--color-space-deep)}'
        '.tr-transitions-destruction .tds-big{font-family:var(--font-subtitle);font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}'
        '.tr-transitions-destruction .tds-a .tds-big{color:rgba(255,255,255,0.08)}'
        '.tr-transitions-destruction .tds-b .tds-big{color:rgba(255,255,255,0.15)}'
        '.tr-transitions-destruction .tds-label{font-family:var(--font-subtitle);font-size:40px;font-weight:700;letter-spacing:6px;margin-top:12px}'
        '.tr-transitions-destruction .tds-a .tds-label{color:var(--color-muted)}'
        '.tr-transitions-destruction .tds-b .tds-label{color:var(--color-bg-pure)}'
        '.tr-transitions-destruction .tds-ring{position:absolute;left:50%;top:50%;width:2242px;height:2242px;margin:-1121px 0 0 -1121px;border-radius:50%;display:block;opacity:0;transform-origin:50% 50%;mix-blend-mode:screen}'
        '.tr-transitions-destruction .tds-r0{background:radial-gradient(circle,transparent 44%,rgba(230,57,70,0.9) 50%,transparent 56%)}'
        '.tr-transitions-destruction .tds-r1{background:radial-gradient(circle,transparent 40%,rgba(230,57,70,0.8) 50%,transparent 60%)}'
        '.tr-transitions-destruction .tds-r2{background:radial-gradient(circle,transparent 36%,rgba(230,57,70,0.5) 50%,transparent 64%)}'
        '.tr-transitions-light{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-transitions-light .tlt-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-transitions-light .tlt-face{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;transform-origin:50% 50%}'
        '.tr-transitions-light .tlt-a{background:var(--color-space-deep)}'
        '.tr-transitions-light .tlt-b{background:var(--color-accent);opacity:0}'
        '.tr-transitions-light .tlt-big{font-family:var(--font-subtitle);font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}'
        '.tr-transitions-light .tlt-a .tlt-big{color:rgba(255,255,255,0.12)}'
        '.tr-transitions-light .tlt-b .tlt-big{color:rgba(0,0,0,0.12)}'
        '.tr-transitions-light .tlt-label{font-family:var(--font-subtitle);font-size:40px;font-weight:700;letter-spacing:6px;margin-top:12px;color:var(--color-bg-pure)}'
        '.tr-transitions-light .tlt-warm{position:absolute;inset:0;display:block;opacity:0;pointer-events:none;background:linear-gradient(135deg,rgba(230,57,70,0.6),transparent 60%);transform-origin:50% 50%}'
        '.tr-transitions-light .tlt-blob{position:absolute;display:block;opacity:0;pointer-events:none;transform-origin:50% 50%}'
        '.tr-transitions-light .tlt-l1{top:-356px;left:-225px;width:1350px;height:2667px;background:radial-gradient(ellipse at 30% 40%,rgba(230,57,70,0.5),transparent 50%)}'
        '.tr-transitions-light .tlt-l2{top:-178px;left:-112px;width:1350px;height:2489px;background:radial-gradient(ellipse at 60% 50%,rgba(230,57,70,0.4),transparent 50%)}'
        '.tr-transitions-other{position:absolute;inset:0;z-index:35;overflow:hidden;pointer-events:none}'
        '.tr-transitions-other .tto-stage{display:block;width:100%;height:100%;position:relative}'
        '.tr-transitions-other .tto-face{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;transform-origin:50% 50%}'
        '.tr-transitions-other .tto-a{background:var(--color-space-deep)}'
        '.tr-transitions-other .tto-b{background:var(--color-accent);opacity:0}'
        '.tr-transitions-other .tto-big{font-family:var(--font-subtitle);font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;user-select:none}'
        '.tr-transitions-other .tto-a .tto-big{color:rgba(255,255,255,0.12)}'
        '.tr-transitions-other .tto-b .tto-big{color:rgba(0,0,0,0.12)}'
        '.tr-transitions-other .tto-label{font-family:var(--font-subtitle);font-size:40px;font-weight:700;letter-spacing:6px;margin-top:12px;color:var(--color-bg-pure)}'
        '.tr-transitions-other .tto-flash{position:absolute;inset:0;display:block;opacity:0;pointer-events:none;background:var(--color-bg-pure);transform-origin:50% 50%}'
        '.abc-chart{left:0;top:0;width:1080px;height:1920px;background:var(--color-space-deep)}'
        '.abc-card{position:absolute;left:90px;width:740px;top:420px;padding:34px;border-radius:28px;background:var(--color-panel);box-shadow:0 28px 80px rgba(11,19,43,0.16);display:grid;gap:22px}'
        '.abc-head{display:grid;gap:8px}'
        '.abc-title{margin:0;font-family:var(--font-subtitle);font-size:34px;font-weight:700;line-height:1.1;letter-spacing:-0.04em;color:var(--color-bg-pure)}'
        '.abc-sub{margin:0;font-family:var(--font-subtitle);font-size:16px;font-weight:400;line-height:1.45;color:var(--color-muted)}'
        '.abc-kpi{display:block;font-family:var(--font-subtitle);font-size:54px;font-weight:700;line-height:1;letter-spacing:-0.06em;color:var(--color-bg-pure)}'
        '.abc-bars{display:grid;align-items:end;gap:14px;height:210px}'
        '.abc-col{display:flex;flex-direction:column;justify-content:flex-end;align-items:stretch;height:100%;gap:10px}'
        '.abc-slot{position:relative;width:100%;overflow:hidden;border-radius:14px 14px 5px 5px}'
        '.abc-grow{position:absolute;left:0;width:100%;height:200%;bottom:-100%;display:block;transform-origin:50% 50%}'
        '.abc-fill{position:absolute;left:0;top:0;width:100%;height:50%;background:var(--color-accent);border-radius:14px 14px 5px 5px}'
        '.abc-lbl{display:block;text-align:center;font-family:var(--font-subtitle);font-size:13px;font-weight:500;color:var(--color-text-soft)}'
        '.bcr-chart{left:0;top:0;width:1080px;height:1920px;background:var(--color-space-deep);font-family:var(--font-subtitle);color:var(--color-ink)}'
        '.bcr-bg{position:absolute;inset:0;background:var(--color-space-deep)}'
        '.bcr-head{position:absolute;top:56px;left:48px;width:984px;height:200px}'
        '.bcr-head-left{position:absolute;left:0;top:0;width:640px}'
        '.bcr-head-right{position:absolute;right:0;top:0;text-align:right}'
        '.bcr-title{margin:0;font-size:34px;font-weight:700;letter-spacing:-0.015em;line-height:1.1;color:var(--color-bg-pure)}'
        '.bcr-subtitle{margin:10px 0 0;font-size:16px;font-weight:400;color:var(--color-muted)}'
        '.bcr-period-caption{display:block;font-size:13px;font-weight:600;letter-spacing:0.18em;text-transform:uppercase;color:var(--color-muted)}'
        '.bcr-period{position:relative;display:block;height:56px;margin-top:4px;font-size:52px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-0.02em}'
        '.bcr-period span{position:absolute;right:0;top:0;opacity:0;white-space:nowrap}'
        '.bcr-plot{position:absolute;left:0;top:280px;width:1080px;height:1404px;overflow:hidden}'
        '.bcr-row{position:absolute;left:0;top:0;width:1080px;opacity:0}'
        '.bcr-name{position:absolute;left:32px;width:204px;top:0;height:100%;display:flex;align-items:center;justify-content:flex-end;text-align:right;font-size:20px;font-weight:600;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background-color:var(--color-accent-soft)}'
        '.bcr-bar{position:absolute;left:248px;border-radius:3px;background-color:var(--color-accent);transform-origin:left center}'
        '.bcr-value{position:absolute;left:252px;top:0;height:100%}'
        '.bcr-value span{position:absolute;left:0;top:0;height:100%;opacity:0;display:flex;align-items:center;padding:0 10px;font-size:20px;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap;background-color:var(--color-accent-soft)}'
        '.bcr-axis{position:absolute;inset:0;z-index:5000;pointer-events:none}'
        '.bcr-tick-label{position:absolute;top:248px;left:0;width:80px;font-size:15px;font-weight:500;font-variant-numeric:tabular-nums;color:var(--color-muted);opacity:0}'
        '.bcr-tick-label span{position:absolute;left:0;top:0;width:80px;text-align:center;opacity:0;white-space:nowrap}'
        '.bcr-source{position:absolute;left:48px;top:1748px;margin:0;font-size:14px;color:var(--color-muted)}'
        '.cst-chart{left:0;top:0;width:1080px;height:1920px;background:var(--color-ink);font-family:var(--font-subtitle);color:var(--color-text-soft)}'
        '.cst-bg{position:absolute;inset:0;background:var(--color-ink)}'
        '.cst-stage{position:absolute;left:0;top:0;width:1080px;height:1920px;opacity:0}'
        '.cst-axis{position:absolute;height:3px;background:var(--color-panel);border-radius:2px;transform-origin:left center}'
        '.cst-bar{position:absolute;transform-origin:50% 100%}'
        '.cst-al,.cst-vl{position:absolute;width:180px;text-align:center;font-family:var(--font-mono);letter-spacing:0.03em;opacity:0;white-space:nowrap}'
        '.cst-al{font-size:26px;font-weight:500;color:var(--color-text-soft)}'
        '.cst-vl{font-size:27px;font-weight:600;color:var(--color-text-soft)}'
        '.cst-call{position:absolute;border-radius:12px;opacity:0;transform-origin:50% 100%;overflow:hidden}'
        '.cst-cv{position:absolute;left:0;right:0;top:0;bottom:0;font-family:var(--font-mono);font-size:29px;font-weight:600;color:var(--color-space-deep);letter-spacing:0.03em}'
        '.cst-cv span{position:absolute;left:0;right:0;top:0;bottom:0;display:flex;align-items:center;justify-content:center;opacity:0}'
        '.cpr-chart{left:0;top:0;width:1080px;height:1920px;background:var(--color-ink);font-family:var(--font-subtitle);color:var(--color-text-soft)}'
        '.cpr-bg{position:absolute;inset:0;background:var(--color-ink)}'
        '.cpr-stage{position:absolute;left:0;top:0;width:1080px;height:1920px}'
        '.cpr-disc{position:absolute;left:173px;top:593px;width:734px;height:734px;border-radius:50%;overflow:hidden;background:var(--color-space-deep)}'
        '.cpr-right,.cpr-left{position:absolute;top:0;width:50%;height:100%;overflow:hidden}'
        '.cpr-right{left:50%}'
        '.cpr-left{left:0}'
        '.cpr-rot{position:absolute;top:0;left:-100%;width:200%;height:100%;transform-origin:50% 50%}'
        '.cpr-left .cpr-rot{left:0}'
        '.cpr-paint{position:absolute;left:50%;top:0;width:50%;height:100%;background:var(--color-accent)}'
        '.cpr-hole{position:absolute;border-radius:50%;background:var(--color-ink)}'
        '.cpr-cv{position:absolute;left:173px;top:593px;width:734px;height:734px;font-family:var(--font-subtitle);font-size:194px;font-weight:700;letter-spacing:-0.04em;line-height:1;color:var(--color-text-soft);font-variant-numeric:tabular-nums}'
        '.cpr-cv span{position:absolute;left:0;top:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;opacity:0}'
        '.dcl-chart{left:0;top:0;width:1080px;height:1920px;background:var(--color-space-deep);font-family:var(--font-subtitle);color:var(--color-text-soft)}'
        '.dcl-bg{position:absolute;inset:0;background:radial-gradient(circle at 24% 16%,rgba(230,57,70,0.55),transparent 46%),linear-gradient(145deg,var(--color-space-deep) 0%,var(--color-space-deep) 48%,var(--color-space-deep) 100%)}'
        '.dcl-gloom{position:absolute;inset:0;background:var(--color-space-deep);opacity:0}'
        '.dcl-stage{position:absolute;left:0;top:0;width:1080px;height:1920px}'
        '.dcl-label{position:absolute;width:580px;overflow:hidden;color:rgba(199,201,209,0.72);font-size:38px;font-weight:600;letter-spacing:0.05em;line-height:1.1;text-overflow:ellipsis;text-transform:uppercase;white-space:nowrap}'
        '.dcl-cv{position:absolute;width:280px;height:118px;color:var(--color-text-soft);font-family:var(--font-subtitle);font-size:118px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-0.07em;line-height:0.8;text-align:right}'
        '.dcl-cv span{position:absolute;left:0;top:0;right:0;bottom:0;display:flex;align-items:flex-end;justify-content:flex-end;opacity:0}'
        '.dcl-plot{position:absolute;left:97px;top:387px;width:886px;height:1379px}'
        '.dcl-plot svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}'
        '.dcl-grid{stroke:rgba(122,125,130,0.18);stroke-width:1;vector-effect:non-scaling-stroke}'
        '.dcl-line{fill:none;stroke:var(--color-accent);stroke-linecap:round;stroke-linejoin:round;stroke-width:4}'
        '.dcl-wipe{transform-origin:0px 50%;transform-box:fill-box}'
        '.dcl-ep{position:absolute;width:30px;height:30px;border-radius:50%;background:var(--color-accent-soft);opacity:0;transform-origin:50% 50%}'
        '.mlg-chart{left:0;top:0;width:1080px;height:1920px;background:var(--color-space-deep);font-family:var(--font-subtitle);color:var(--color-bg-pure)}'
        '.mlg-bg{position:absolute;inset:0;background:var(--color-space-deep)}'
        '.mlg-stage{position:absolute;left:0;top:0;width:1080px;height:1920px}'
        '.mlg-svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}'
        '.mlg-axis{stroke:rgba(199,201,209,0.35);stroke-width:2;opacity:0}'
        '.mlg-line{fill:none;stroke-width:5;stroke-linecap:round;stroke-linejoin:round}'
        '.mlg-wipe{transform-origin:0px 50%;transform-box:fill-box}'
        '.mlg-dot{position:absolute;width:22px;height:22px;border-radius:50%;background:var(--color-bg-pure);box-sizing:border-box;border-style:solid;border-width:4px;transform-origin:50% 50%}'
        '.mlg-val{position:absolute;width:100px;height:46px;font-weight:600;font-size:38px;letter-spacing:-0.01em;color:var(--color-bg-pure);font-variant-numeric:tabular-nums;line-height:46px;text-align:center;white-space:nowrap;opacity:0}'
        '.mlg-xl{position:absolute;width:100px;font-weight:400;font-size:32px;color:var(--color-muted);text-align:center;white-space:nowrap;opacity:0}'
        '.mlg-legend{position:absolute;display:flex;gap:32px;opacity:0}'
        '.mlg-legend-item{display:flex;align-items:center;gap:12px;font-weight:500;font-size:36px;color:var(--color-muted)}'
        '.mlg-legend-dot{width:14px;height:14px;border-radius:50%;flex-shrink:0}'
        '.srf-chart{left:0;top:0;width:1080px;height:1920px;background:var(--color-space-deep);font-family:var(--font-subtitle);color:var(--color-text-soft)}'
        '.srf-bg{position:absolute;inset:0;background:var(--color-space-deep)}'
        '.srf-stage{position:absolute;left:0;top:0;width:1080px;height:1920px}'
        '.srf-card{position:absolute;left:40px;top:750px;width:1000px;height:420px;border-radius:32px;background:var(--color-space-deep);border:2px solid rgba(199,201,209,0.14);box-shadow:0 43px 108px rgba(199,201,209,0.12)}'
        '.srf-stars{position:absolute}'
        '.srf-fill-svg{position:absolute;left:0;top:0;overflow:visible}'
        '.srf-cell{position:absolute;top:0;overflow:visible;transform-origin:50% 50%}'
        '.srf-fill-star{transform-origin:50% 50%;transform-box:fill-box}'
        '.srf-wipe{transform-origin:0px 50%;transform-box:fill-box}'
        '.srf-cv{position:absolute;line-height:1;text-align:right;font-weight:720;letter-spacing:-0.04em;font-variant-numeric:tabular-nums;color:var(--color-text-soft)}'
        '.srf-cv span{position:absolute;right:0;top:0;opacity:0;white-space:nowrap}'
        '.wmp-chart{left:0;top:0;width:1080px;height:1920px;background:var(--color-space-deep);font-family:var(--font-subtitle);color:var(--color-accent-soft)}'
        '.wmp-bg{position:absolute;inset:0;background:linear-gradient(145deg,var(--color-space-deep) 0%,var(--color-space-deep) 100%)}'
        '.wmp-stage{position:absolute;left:0;top:0;width:1080px;height:1920px}'
        '.wmp-hl-clip{position:absolute;left:40px;top:140px;width:1000px;overflow:hidden}'
        '.wmp-hl{font-weight:700;font-size:38px;letter-spacing:-0.02em;color:var(--color-accent-soft);line-height:1.15}'
        '.wmp-wipe{position:absolute;inset:0;background:linear-gradient(145deg,var(--color-space-deep) 0%,var(--color-space-deep) 100%);transform-origin:100% 50%}'
        '.wmp-sub{position:absolute;left:40px;top:236px;width:1000px;font-weight:300;font-size:22px;color:var(--color-muted);opacity:0}'
        '.wmp-svg{position:absolute;left:40px;top:310px;width:1000px;height:560px;overflow:visible}'
        '.wmp-grat{fill:none;stroke:var(--color-space-deep);stroke-width:0.6;stroke-opacity:0.5}'
        '.wmp-region{stroke:var(--color-space-deep);stroke-width:0.6;opacity:0;vector-effect:non-scaling-stroke}'
        '.wmp-hi{fill:var(--color-text-soft);opacity:0;pointer-events:none}'
        '.wmp-legend{position:absolute;left:40px;top:900px;width:1000px;display:flex;flex-direction:column;align-items:center;gap:8px;opacity:0}'
        '.wmp-legend-bar{width:280px;height:14px;border-radius:7px;background:linear-gradient(90deg,var(--color-accent-deep),var(--color-accent-deep),var(--color-accent),var(--color-accent-soft))}'
        '.wmp-legend-labs{display:flex;justify-content:space-between;width:280px;font-weight:500;font-size:16px;color:var(--color-muted)}'
        '.wmp-src{position:absolute;left:40px;top:968px;width:1000px;font-weight:400;font-size:16px;color:var(--color-panel);text-align:right;opacity:0}'
        '.fullscreen-text .saz-stack{display:inline-flex;flex-wrap:nowrap;justify-content:center;align-items:center;max-width:100%;line-height:1;white-space:nowrap}'
        '.fullscreen-text .saz-word{display:inline-block;will-change:transform,opacity}'
        ".fullscreen-text.fs-code-3d{width:var(--frame-w);height:var(--frame-h);padding:0;overflow:hidden;isolation:isolate;display:flex;align-items:center;justify-content:center;background:var(--color-space-deep);font-family:var(--font-mono);font-weight:600;text-transform:none;letter-spacing:0}"
        '.fullscreen-text.fs-code-3d.invert{background:var(--color-space-deep);color:var(--color-bg-light)}'
        '.fullscreen-text .c3d-stage{display:flex;align-items:center;justify-content:center;width:100%;height:100%}'
        '.fullscreen-text .c3d-slab{position:relative;display:inline-block;max-width:88%;will-change:transform}'
        '.fullscreen-text .c3d-edge{position:absolute;inset:0;border-radius:14px;background:var(--color-space-deep);transform:translate(14px,16px);z-index:0}'
        '.fullscreen-text .c3d-face{position:relative;z-index:1;display:flex;flex-direction:column;align-items:flex-start;gap:0;padding:28px 32px;border-radius:14px;background:var(--color-panel);color:var(--color-bg-light);box-shadow:0 22px 54px rgba(0,0,0,0.55),-10px -8px 28px rgba(230,57,70,0.16),12px 10px 32px rgba(199,201,209,0.14)}'
        '.fullscreen-text .c3d-line{display:block;white-space:pre;font-weight:600;letter-spacing:0}'
        '.fullscreen-text .c3d-tok{font-weight:600}'
        '.fullscreen-text .cd-stage{display:flex;align-items:center;justify-content:center;width:100%;height:100%}'
        '.fullscreen-text .cd-editor{position:relative;display:flex;flex-direction:column;width:92%;max-width:1000px;max-height:78%;background:var(--color-space-deep);border:1px solid var(--color-space-deep);border-radius:16px;box-shadow:0 40px 120px rgba(0,0,0,0.6),0 2px 0 rgba(255,255,255,0.03) inset;overflow:hidden;will-change:transform,opacity}'
        '.fullscreen-text .cd-titlebar{display:flex;align-items:center;gap:14px;flex:0 0 52px;height:52px;padding:0 20px;background:linear-gradient(var(--color-space-deep),var(--color-space-deep));border-bottom:1px solid var(--color-space-deep)}'
        '.fullscreen-text .cd-dots{display:flex;gap:8px}'
        '.fullscreen-text .cd-dot{display:block;width:12px;height:12px;border-radius:50%}'
        '.fullscreen-text .cd-dot-r{background:var(--color-accent)}'
        '.fullscreen-text .cd-dot-y{background:var(--color-accent)}'
        '.fullscreen-text .cd-dot-g{background:var(--color-accent)}'
        '.fullscreen-text .cd-filename{font-size:16px;color:var(--color-text-soft);letter-spacing:0.2px;text-transform:none}'
        '.fullscreen-text .cd-file{color:var(--color-text-soft)}'
        '.fullscreen-text .cd-surface{position:relative;flex:1 1 auto;overflow:hidden}'
        '.fullscreen-text .cd-code{position:relative;display:block;width:100%;font-variant-ligatures:none}'
        '.fullscreen-text .cd-line{position:absolute;left:0;right:0;display:block;overflow:hidden;white-space:pre;padding-left:14px;transform-origin:50% 0%;will-change:transform,opacity}'
        '.fullscreen-text .cd-sign{display:inline-block;width:1.1em;color:var(--color-panel)}'
        '.fullscreen-text .cd-del .cd-sign{color:var(--color-accent)}'
        '.fullscreen-text .cd-add .cd-sign{color:var(--color-accent)}'
        '.fullscreen-text .cd-tok{font-weight:500}'
        '.fullscreen-text .pa-stage{position:relative;display:flex;align-items:center;justify-content:center;width:100%;height:100%}'
        '.fullscreen-text .pa-dust{position:absolute;inset:0;z-index:1;pointer-events:none}'
        '.fullscreen-text .pa-dot{position:absolute;display:block;border-radius:50%;pointer-events:none;will-change:transform,opacity;box-shadow:0 0 10px rgba(225,228,232,0.4)}'
        '.fullscreen-text .pa-code{position:relative;z-index:2;display:flex;flex-direction:column;align-items:flex-start;box-sizing:border-box;opacity:0;white-space:pre;text-align:left;font-variant-ligatures:none;pointer-events:none}'
        '.fullscreen-text .pa-line{display:block;white-space:pre;font-weight:700;letter-spacing:0}'
        '.fullscreen-text .pa-tok{font-weight:700}'
        '.fullscreen-text .cs-stage{position:relative;display:flex;align-items:center;justify-content:center;width:100%;height:100%}'
        '.fullscreen-text .cs-grid{position:absolute;inset:0;z-index:0;pointer-events:none;background-image:linear-gradient(rgba(122,125,130,0.05) 1px,transparent 1px),linear-gradient(90deg,rgba(122,125,130,0.05) 1px,transparent 1px);background-size:48px 48px}'
        '.fullscreen-text .cs-glow{position:absolute;width:520px;height:520px;border-radius:50%;filter:blur(90px);opacity:0.5;pointer-events:none;z-index:0}'
        '.fullscreen-text .cs-glow-a{background:#1f6feb55;left:-80px;top:-120px}'
        '.fullscreen-text .cs-glow-b{background:#2ea04355;right:-100px;bottom:-160px}'
        '.fullscreen-text .cs-editor{position:relative;z-index:1;display:flex;flex-direction:column;box-sizing:border-box;background:var(--color-space-deep);border:1px solid var(--color-space-deep);border-radius:16px;box-shadow:0 40px 120px rgba(0,0,0,0.6),0 2px 0 rgba(255,255,255,0.03) inset;overflow:hidden;will-change:transform,opacity}'
        '.fullscreen-text .cs-titlebar{display:flex;align-items:center;gap:14px;flex:0 0 48px;height:48px;padding:0 18px;background:linear-gradient(var(--color-space-deep),var(--color-space-deep));border-bottom:1px solid var(--color-space-deep)}'
        '.fullscreen-text .cs-dots{display:flex;gap:8px}'
        '.fullscreen-text .cs-dot{display:block;width:12px;height:12px;border-radius:50%}'
        '.fullscreen-text .cs-dot-r{background:var(--color-accent)}'
        '.fullscreen-text .cs-dot-y{background:var(--color-accent)}'
        '.fullscreen-text .cs-dot-g{background:var(--color-accent)}'
        '.fullscreen-text .cs-filename{font-size:15px;color:var(--color-text-soft);letter-spacing:0.2px;text-transform:none}'
        '.fullscreen-text .cs-file{color:var(--color-text-soft)}'
        '.fullscreen-text .cs-surface{position:relative;flex:0 0 auto;overflow:hidden}'
        '.fullscreen-text .cs-scroll{position:relative;display:block;will-change:transform,opacity;opacity:0}'
        '.fullscreen-text .cs-gutter{position:absolute;left:0;z-index:1;text-align:right;color:var(--color-text-soft);user-select:none;font-variant-ligatures:none}'
        '.fullscreen-text .cs-gn{display:block}'
        '.fullscreen-text .cs-code{position:relative;display:block;width:100%;box-sizing:border-box;font-variant-ligatures:none;tab-size:2;text-align:left;text-transform:none}'
        '.fullscreen-text .cs-line{display:block;white-space:pre;position:relative;z-index:1;text-transform:none;font-weight:500}'
        '.fullscreen-text .cs-tok{font-weight:500}'
        '.fullscreen-text .cs-hl{position:absolute;left:0;right:0;z-index:0;background:rgba(122,125,130,0.16);border-left:3px solid var(--color-muted);border-radius:6px;pointer-events:none;opacity:0}'
        '.fullscreen-text .ct-stage{position:relative;display:flex;align-items:center;justify-content:center;width:100%;height:100%}'
        '.fullscreen-text .ct-grid{position:absolute;inset:0;z-index:0;pointer-events:none;background-image:linear-gradient(rgba(122,125,130,0.05) 1px,transparent 1px),linear-gradient(90deg,rgba(122,125,130,0.05) 1px,transparent 1px);background-size:48px 48px}'
        '.fullscreen-text .ct-glow{position:absolute;width:520px;height:520px;border-radius:50%;filter:blur(90px);opacity:0.5;pointer-events:none;z-index:0}'
        '.fullscreen-text .ct-glow-a{background:#1f6feb55;left:-80px;top:-120px}'
        '.fullscreen-text .ct-glow-b{background:#2ea04355;right:-100px;bottom:-160px}'
        '.fullscreen-text .ct-editor{position:relative;z-index:1;display:flex;flex-direction:column;box-sizing:border-box;background:var(--color-space-deep);border:1px solid var(--color-space-deep);border-radius:16px;box-shadow:0 40px 120px rgba(0,0,0,0.6),0 2px 0 rgba(255,255,255,0.03) inset;overflow:hidden;will-change:transform,opacity}'
        '.fullscreen-text .ct-titlebar{display:flex;align-items:center;gap:14px;flex:0 0 48px;height:48px;padding:0 18px;background:linear-gradient(var(--color-space-deep),var(--color-space-deep));border-bottom:1px solid var(--color-space-deep)}'
        '.fullscreen-text .ct-dots{display:flex;gap:8px}'
        '.fullscreen-text .ct-dot{display:block;width:12px;height:12px;border-radius:50%}'
        '.fullscreen-text .ct-dot-r{background:var(--color-accent)}'
        '.fullscreen-text .ct-dot-y{background:var(--color-accent)}'
        '.fullscreen-text .ct-dot-g{background:var(--color-accent)}'
        '.fullscreen-text .ct-filename{font-size:15px;color:var(--color-text-soft);letter-spacing:0.2px;text-transform:none}'
        '.fullscreen-text .ct-file{color:var(--color-text-soft)}'
        '.fullscreen-text .ct-surface{position:relative;flex:0 0 auto;overflow:hidden}'
        '.fullscreen-text .ct-scene{position:relative;display:block;width:100%;height:100%;opacity:0}'
        '.fullscreen-text .ct-gutter{position:absolute;left:0;z-index:1;text-align:right;color:var(--color-text-soft);user-select:none;font-variant-ligatures:none}'
        '.fullscreen-text .ct-gn{display:block}'
        '.fullscreen-text .ct-code{position:relative;display:block;width:100%;box-sizing:border-box;font-variant-ligatures:none;tab-size:2;text-align:left;text-transform:none}'
        '.fullscreen-text .ct-line{display:block;white-space:pre;position:relative;z-index:1;text-transform:none;font-weight:500}'
        '.fullscreen-text .ct-ch{display:inline-block;white-space:pre;opacity:0;font-weight:500;will-change:opacity}'
        '.fullscreen-text .ct-caret{position:absolute;left:0;top:0;z-index:3;background:var(--color-muted);border-radius:1px;pointer-events:none;will-change:transform}'
        '.fullscreen-text .ts-stage{position:relative;display:flex;align-items:center;justify-content:center;width:100%;height:100%}'
        '.fullscreen-text .ts-card{position:relative;z-index:1;display:flex;flex-direction:column;box-sizing:border-box;background:var(--color-space-deep);color:var(--color-bg-light);overflow:hidden}'
        '.fullscreen-text .ts-chrome{display:flex;align-items:center;gap:8px;flex:0 0 auto;padding:0 18px;background:var(--color-space-deep);color:var(--color-muted);text-transform:none}'
        '.fullscreen-text .ts-dots{display:flex;align-items:center}'
        '.fullscreen-text .ts-dot{display:block;border-radius:999px}'
        '.fullscreen-text .ts-dot-r{background:var(--color-accent)}'
        '.fullscreen-text .ts-dot-y{background:var(--color-accent)}'
        '.fullscreen-text .ts-dot-g{background:var(--color-accent)}'
        '.fullscreen-text .ts-title{text-transform:none;color:var(--color-muted)}'
        '.fullscreen-text .ts-body{display:grid;min-height:0}'
        '.fullscreen-text .ts-files{box-sizing:border-box;border-right:1px solid rgba(122,125,130,0.18);color:var(--color-muted);text-align:left;text-transform:none;line-height:1.8}'
        '.fullscreen-text .ts-editor{box-sizing:border-box;display:grid;align-content:start}'
        '.fullscreen-text .ts-term{box-sizing:border-box;border-top:1px solid rgba(122,125,130,0.18);color:var(--color-accent-soft);text-align:left;text-transform:none;opacity:0;will-change:transform,opacity}'
        '.fullscreen-text .atcd-stage{position:relative;display:flex;align-items:center;justify-content:center;width:100%;height:100%}'
        '.fullscreen-text .atcd-window{position:relative;z-index:1;display:flex;flex-direction:column;box-sizing:border-box;overflow:hidden;box-shadow:0 30px 80px rgba(0,0,0,0.7),0 10px 30px rgba(0,0,0,0.5)}'
        '.fullscreen-text .atcd-bar{position:relative;display:flex;align-items:center;flex:0 0 42px;height:42px;padding:0 14px;background:rgba(0,0,0,0.4);border-bottom:1px solid rgba(255,255,255,0.08)}'
        '.fullscreen-text .atcd-lights{display:flex;align-items:center;gap:8px;z-index:1}'
        '.fullscreen-text .atcd-dot{display:block;width:13px;height:13px;border-radius:50%}'
        '.fullscreen-text .atcd-close{background:var(--color-accent);border:1px solid var(--color-accent)}'
        '.fullscreen-text .atcd-min{background:var(--color-accent);border:1px solid var(--color-accent)}'
        '.fullscreen-text .atcd-full{background:var(--color-accent);border:1px solid var(--color-accent)}'
        '.fullscreen-text .atcd-title{position:absolute;left:0;right:0;text-align:center;font-family:var(--font-subtitle);font-size:13px;font-weight:500;color:var(--color-bg-pure);letter-spacing:-0.1px;text-transform:none;pointer-events:none}'
        '.fullscreen-text .atcd-canvas{flex:1;box-sizing:border-box;background:rgba(0,0,0,0.7);color:var(--color-bg-pure);text-align:left;text-transform:none;overflow:hidden;line-height:1.6}'
        '.fullscreen-text .atcd-out{display:block;margin-bottom:4px}'
        '.fullscreen-text .atcd-slot{position:relative;display:block}'
        '.fullscreen-text .atcd-input{display:flex;align-items:center;white-space:pre;text-transform:none;will-change:opacity}'
        '.fullscreen-text .atcd-input-next{position:absolute;left:0;top:0;opacity:0}'
        '.fullscreen-text .atcd-prompt{color:var(--color-muted);font-weight:700;text-transform:none}'
        '.fullscreen-text .atcd-cmd{display:inline;color:var(--color-bg-pure);will-change:opacity}'
        '.fullscreen-text .atcd-ch{display:inline;white-space:pre;opacity:0;color:var(--color-bg-pure);text-transform:none;will-change:opacity}'
        '.fullscreen-text .atcd-cursor{display:inline-block;flex:0 0 auto;background:var(--color-muted);margin-left:1px;vertical-align:text-bottom;will-change:opacity}'
        '.fullscreen-text .dp-stage{position:relative;display:flex;flex-direction:column;gap:12px;width:100%;height:100%;box-sizing:border-box}'
        '.fullscreen-text .dp-header{display:flex;align-items:flex-end;justify-content:space-between;flex:0 0 auto;will-change:transform,opacity}'
        '.fullscreen-text .dp-kicker{display:block;margin:0 0 7px;color:var(--color-muted);font-size:13px;font-weight:650;text-transform:uppercase}'
        '.fullscreen-text .dp-title{display:block;color:var(--color-bg-light);font-size:36px;line-height:1;font-weight:760;text-transform:none}'
        '.fullscreen-text .dp-note{width:42%;color:var(--color-muted);font-size:14px;line-height:1.35;text-align:right;text-transform:none}'
        '.fullscreen-text .dp-src{color:var(--color-text-soft)}'
        '.fullscreen-text .dp-wb{position:relative;display:grid;overflow:hidden;border:1px solid var(--color-panel);border-radius:8px;background:var(--color-ink);box-shadow:0 34px 90px rgba(0,0,0,0.42);transform-origin:82% 50%;will-change:transform,opacity}'
        '.fullscreen-text .dp-titlebar{grid-column:1/-1;display:grid;grid-template-columns:110px 1fr 160px;align-items:center;background:var(--color-ink);color:var(--color-bg-light);border-bottom:1px solid var(--color-panel);font-size:12px}'
        '.fullscreen-text .dp-traffic{display:flex;gap:8px;padding-left:16px}'
        '.fullscreen-text .dp-traffic span{display:block;width:12px;height:12px;border-radius:999px}'
        '.fullscreen-text .dp-traffic span:nth-child(1){background:var(--color-accent)}'
        '.fullscreen-text .dp-traffic span:nth-child(2){background:var(--color-accent)}'
        '.fullscreen-text .dp-traffic span:nth-child(3){background:var(--color-accent)}'
        '.fullscreen-text .dp-wintitle{justify-self:center;opacity:0.84;text-transform:none}'
        '.fullscreen-text .dp-search{justify-self:end;width:140px;height:20px;margin-right:12px;display:flex;align-items:center;justify-content:center;border:1px solid rgba(204,204,204,0.22);border-radius:5px;color:var(--color-text-soft)}'
        '.fullscreen-text .dp-activity{grid-row:2/3;background:var(--color-ink);border-right:1px solid var(--color-panel);display:flex;flex-direction:column;align-items:center;padding:10px 0;gap:16px}'
        '.fullscreen-text .dp-icon{display:block;width:22px;height:22px;color:var(--color-muted)}'
        '.fullscreen-text .dp-icon-on{color:var(--color-bg-light);border-left:2px solid var(--color-panel);padding-left:3px}'
        '.fullscreen-text .dp-sidebar{grid-row:2/3;background:var(--color-ink);color:var(--color-bg-light);border-right:1px solid var(--color-panel);display:flex;flex-direction:column;min-width:0;text-transform:none}'
        '.fullscreen-text .dp-side-title{height:32px;display:flex;align-items:center;padding:0 16px;font-size:11px;text-transform:uppercase;color:var(--color-text-soft)}'
        '.fullscreen-text .dp-sec{height:22px;display:flex;align-items:center;gap:6px;padding:0 12px;background:var(--color-panel);border-top:1px solid var(--color-panel);border-bottom:1px solid var(--color-panel);font-size:11px;font-weight:700}'
        '.fullscreen-text .dp-tree{padding:6px 0;font-size:12px;line-height:22px}'
        '.fullscreen-text .dp-row{display:flex;align-items:center;height:22px;padding:0 8px 0 14px;color:var(--color-bg-light);white-space:nowrap}'
        '.fullscreen-text .dp-child{padding-left:28px}'
        '.fullscreen-text .dp-sel{background:rgba(204,204,204,0.12)}'
        '.fullscreen-text .dp-editor-area{grid-row:2/3;display:grid;min-width:0;background:var(--color-ink)}'
        '.fullscreen-text .dp-tabs{display:flex;background:var(--color-ink);border-bottom:1px solid var(--color-panel)}'
        '.fullscreen-text .dp-tab{height:32px;display:flex;align-items:center;gap:8px;padding:0 12px;border-right:1px solid var(--color-panel);background:var(--color-panel);color:var(--color-bg-pure);border-top:2px solid var(--color-panel);font-size:12px;text-transform:none}'
        '.fullscreen-text .dp-tab-off{background:var(--color-ink);color:var(--color-text-soft);border-top-color:transparent}'
        '.fullscreen-text .dp-crumbs{display:flex;align-items:center;padding:0 14px;color:var(--color-muted);border-bottom:1px solid var(--color-panel);font-size:11px;text-transform:none}'
        ".fullscreen-text .dp-editor{position:relative;overflow:hidden;background:var(--color-ink);color:var(--color-bg-light);font-family:var(--font-mono);line-height:1.52;text-transform:none}"
        '.fullscreen-text .dp-hl{position:absolute;left:0;right:0;background:rgba(255,255,255,0.04);opacity:0;will-change:transform,opacity}'
        '.fullscreen-text .dp-col{position:relative;display:block}'
        '.fullscreen-text .dp-line{display:grid;grid-template-columns:48px 1fr;align-items:center}'
        ".fullscreen-text .dp-ln{padding-right:10px;color:var(--color-muted);text-align:right;font-family:var(--font-mono)}"
        '.fullscreen-text .dp-code{white-space:pre;text-align:left}'
        '.fullscreen-text .dp-tok-comment{color:var(--color-accent)}'
        '.fullscreen-text .dp-caret{position:absolute;left:0;top:0;z-index:3;display:block;background:var(--color-bg-light);pointer-events:none;will-change:transform,opacity}'
        ".fullscreen-text .dp-term{display:grid;grid-template-rows:28px 1fr;background:var(--color-ink);border-top:1px solid var(--color-panel);color:var(--color-bg-light);font-family:var(--font-mono);font-size:12px;opacity:0;text-transform:none;will-change:transform,opacity}"
        '.fullscreen-text .dp-ptabs{display:flex;align-items:center;gap:18px;padding:0 14px;border-bottom:1px solid var(--color-panel);color:var(--color-muted);font-family:var(--font-subtitle);font-size:11px;text-transform:uppercase}'
        '.fullscreen-text .dp-pon{color:var(--color-bg-light);border-bottom:1px solid var(--color-panel);height:28px;display:flex;align-items:center}'
        '.fullscreen-text .dp-tbody{padding:8px 16px;line-height:1.7}'
        '.fullscreen-text .dp-tb{display:block;opacity:0;will-change:transform,opacity}'
        '.fullscreen-text .dp-prompt{color:var(--color-accent-soft)}'
        '.fullscreen-text .dp-status{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;background:var(--color-ink);color:var(--color-bg-light);border-top:1px solid var(--color-panel);font-size:11px}'
        '.fullscreen-text .dp-stat-l,.fullscreen-text .dp-stat-r{display:flex;align-items:center;gap:14px;padding:0 10px}'
        '.fullscreen-text .dp-remote{align-self:stretch;display:flex;align-items:center;padding:0 10px;margin-left:-10px;background:var(--color-accent-deep);color:var(--color-bg-pure)}'
        '.fullscreen-text .dp-stage svg{display:block}'
        '.fullscreen-text .bfc-stage{position:relative;display:block;width:100%;height:100%}'
        '.fullscreen-text .bfc-bg{position:absolute;inset:0;background:radial-gradient(ellipse 80% 60% at 50% 40%,rgba(230,57,70,0.10) 0%,transparent 55%),radial-gradient(ellipse 50% 40% at 80% 80%,rgba(255,255,255,0.03) 0%,transparent 50%),var(--color-space-deep)}'
        '.fullscreen-text .bfc-grid{position:absolute;inset:0;opacity:0.22;background-image:linear-gradient(rgba(255,255,255,0.04) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.04) 1px,transparent 1px);background-size:80px 80px;pointer-events:none}'
        '.fullscreen-text .bfc-zoom{position:absolute;inset:0;display:block;transform-origin:50% 50%;will-change:transform}'
        '.fullscreen-text .bfc-shot-a,.fullscreen-text .bfc-shot-b,.fullscreen-text .bfc-crop{position:absolute;inset:0;display:block;overflow:hidden}'
        '.fullscreen-text .bfc-crop{display:flex;align-items:center;justify-content:center;transform-origin:50% 50%;will-change:transform}'
        '.fullscreen-text .bfc-shot-b{opacity:0;display:flex;flex-direction:column;justify-content:center;padding:72px 48px 96px;will-change:opacity}'
        '.fullscreen-text .bfc-card{position:relative;width:900px;height:1020px;border-radius:32px;overflow:hidden;background:linear-gradient(160deg,rgba(255,255,255,0.06) 0%,transparent 40%),linear-gradient(180deg,var(--color-space-deep) 0%,var(--color-space-deep) 100%);border:1px solid rgba(255,255,255,0.08);box-shadow:0 40px 120px rgba(0,0,0,0.55),0 0 0 1px rgba(230,57,70,0.12),inset 0 1px 0 rgba(255,255,255,0.06);will-change:transform,opacity}'
        '.fullscreen-text .bfc-glow{position:absolute;left:50%;top:28%;width:380px;height:380px;margin-left:-190px;margin-top:-190px;border-radius:50%;background:radial-gradient(circle,rgba(230,57,70,0.32) 0%,transparent 68%);pointer-events:none}'
        '.fullscreen-text .bfc-wave{position:absolute;left:56px;right:56px;top:110px;height:200px}'
        '.fullscreen-text .bfc-wave svg{width:100%;height:100%;display:block}'
        '.fullscreen-text .bfc-wave-path{fill:none;stroke:var(--color-accent);stroke-width:4;stroke-linecap:round;stroke-linejoin:round}'
        '.fullscreen-text .bfc-wave-fill{fill:var(--color-accent);opacity:0.12}'
        '.fullscreen-text .bfc-bars{position:absolute;left:72px;right:72px;bottom:150px;height:96px;display:flex;align-items:flex-end;gap:8px}'
        '.fullscreen-text .bfc-bar{flex:1;height:40%;border-radius:6px 6px 2px 2px;background:linear-gradient(180deg,var(--color-accent) 0%,rgba(230,57,70,0.25) 100%);transform-origin:50% 100%;will-change:transform}'
        '.fullscreen-text .bfc-meta{position:absolute;left:56px;right:56px;bottom:52px;display:flex;align-items:center;justify-content:space-between}'
        '.fullscreen-text .bfc-kicker{font-size:16px;font-weight:600;letter-spacing:0.18em;text-transform:uppercase;color:var(--color-bg-light)}'
        '.fullscreen-text .bfc-pill{font-size:14px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--color-bg-pure);background:var(--color-accent);padding:8px 16px;border-radius:999px}'
        '.fullscreen-text .bfc-b-copy{display:flex;flex-direction:column;gap:22px;will-change:transform,opacity}'
        '.fullscreen-text .bfc-eyebrow{font-size:18px;font-weight:700;letter-spacing:0.22em;text-transform:uppercase;color:var(--color-accent)}'
        '.fullscreen-text .bfc-title{display:flex;flex-direction:column;font-size:108px;font-weight:900;line-height:0.92;letter-spacing:-0.04em;text-transform:uppercase;color:var(--color-bg-pure)}'
        '.fullscreen-text .bfc-accent-bar{width:120px;height:6px;border-radius:999px;background:var(--color-accent)}'
        '.fullscreen-text .bfc-sub{font-size:24px;font-weight:500;color:var(--color-bg-light);line-height:1.35;max-width:640px;text-transform:none}'
        '.fullscreen-text .bfc-b-list{display:flex;flex-direction:column;gap:18px;margin-top:48px}'
        '.fullscreen-text .bfc-b-card{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:28px 30px;border-radius:20px;background:linear-gradient(135deg,var(--color-space-deep),var(--color-space-deep));border:1px solid rgba(255,255,255,0.08);box-shadow:0 18px 48px rgba(0,0,0,0.35);will-change:transform,opacity}'
        '.fullscreen-text .bfc-b-label{font-size:16px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:var(--color-bg-light)}'
        '.fullscreen-text .bfc-intro{position:absolute;left:0;right:0;top:72px;display:flex;justify-content:center;pointer-events:none;z-index:20;opacity:0;will-change:transform,opacity}'
        '.fullscreen-text .bfc-intro-label{font-size:16px;font-weight:700;letter-spacing:0.28em;text-transform:uppercase;color:var(--color-bg-light);padding:10px 18px;border:1px solid rgba(255,255,255,0.08);border-radius:999px;background:rgba(11,19,43,0.55);backdrop-filter:blur(8px)}'
        '.fullscreen-text .bfc-hit{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;z-index:30;opacity:0;font-size:120px;font-weight:900;letter-spacing:-0.04em;text-transform:uppercase;color:var(--color-bg-pure);text-shadow:0 0 40px rgba(230,57,70,0.45),0 8px 40px rgba(0,0,0,0.55);will-change:transform,opacity}'
        '.fullscreen-text .bfc-outline{position:absolute;inset:48px;border:3px solid var(--color-accent);border-radius:8px;box-shadow:0 0 0 1px rgba(230,57,70,0.25),inset 0 0 0 1px rgba(230,57,70,0.15),0 0 48px rgba(230,57,70,0.2);opacity:0;pointer-events:none;z-index:25;will-change:opacity}'
        '.fullscreen-text .bfc-flash{position:absolute;inset:0;background:var(--color-bg-pure);opacity:0;mix-blend-mode:screen;pointer-events:none;z-index:26;will-change:opacity}'
        '.fullscreen-text .bfc-contour{position:absolute;inset:0;background:linear-gradient(90deg,transparent 0%,rgba(230,57,70,0.08) 48%,transparent 52%),radial-gradient(ellipse 40% 55% at 50% 48%,transparent 40%,rgba(230,57,70,0.18) 100%);opacity:0;mix-blend-mode:screen;pointer-events:none;z-index:25;will-change:opacity}'
        '.fullscreen-text .bfc-badge{position:absolute;top:80px;right:48px;font-size:15px;font-weight:800;letter-spacing:0.2em;text-transform:uppercase;color:var(--color-bg-pure);background:var(--color-accent);padding:10px 18px;border-radius:6px;opacity:0;z-index:27;will-change:opacity}'
        '.fullscreen-text .bfc-smear{position:absolute;inset:-8% -20%;pointer-events:none;z-index:40;opacity:0;background:linear-gradient(90deg,transparent 0%,rgba(230,57,70,0.12) 35%,rgba(255,255,255,0.55) 50%,rgba(230,57,70,0.12) 65%,transparent 100%);filter:blur(18px);transform-origin:50% 50%;will-change:transform,opacity}'
        '.fullscreen-text .bfc-blur{position:absolute;inset:0;pointer-events:none;z-index:39;opacity:0;backdrop-filter:blur(14px);background:rgba(11,19,43,0.12);will-change:opacity}'
        '.fullscreen-text .bfc-vignette{position:absolute;inset:0;pointer-events:none;z-index:15;background:radial-gradient(ellipse 75% 70% at 50% 50%,transparent 45%,rgba(0,0,0,0.55) 100%);opacity:0.85}'
        '.lt-accent-underline{left:var(--safe-x-min);bottom:460px;max-width:calc(var(--safe-x-max) - var(--safe-x-min));display:flex;flex-direction:column;align-items:flex-start;gap:14px;background:transparent}'
        ".lt-au-name{display:block;font-family:var(--font-display);font-weight:700;color:var(--color-bg-pure);line-height:0.96;letter-spacing:0.005em;text-transform:uppercase;white-space:nowrap;text-shadow:0 2px 22px rgba(0,0,0,0.45);will-change:transform,opacity}"
        '.lt-au-rule{display:block;height:6px;border-radius:3px;background:var(--color-accent);transform-origin:0% 50%;will-change:transform}'
        ".lt-au-role{display:block;font-family:var(--font-mono);font-weight:400;color:var(--color-text-soft);line-height:1.2;letter-spacing:0.04em;white-space:nowrap;text-shadow:0 2px 16px rgba(0,0,0,0.45);will-change:transform,opacity}"
        '.lt-clean-bar{left:var(--safe-x-min);bottom:460px;max-width:calc(var(--safe-x-max) - var(--safe-x-min));background:transparent}'
        '.lt-cb-stage{display:block;position:relative;overflow:visible}'
        '.lt-cb-svg{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}'
        '.lt-cb-wipe{transform-origin:0px 50%;transform-box:fill-box}'
        '.lt-cb-card{display:flex;align-items:stretch;width:100%;height:100%;border-radius:16px;overflow:hidden;box-shadow:0 14px 44px rgba(15,17,21,0.18)}'
        '.lt-cb-tab{display:block;width:12px;flex-shrink:0;background:var(--color-accent);transform-origin:50% 0%;will-change:transform}'
        '.lt-cb-body{display:flex;flex-direction:column;gap:7px;flex:1;background:var(--color-panel);padding:22px 40px 24px 30px}'
        ".lt-cb-name{display:block;font-family:var(--font-subtitle);font-weight:700;color:var(--color-bg-pure);line-height:1.06;letter-spacing:-0.015em;white-space:nowrap;will-change:transform,opacity}"
        ".lt-cb-role{display:block;font-family:var(--font-subtitle);font-weight:400;color:var(--color-text-soft);line-height:1.2;letter-spacing:0.01em;white-space:nowrap;will-change:transform,opacity}"
        '.lt-dark-card{left:var(--safe-x-min);bottom:460px;max-width:calc(var(--safe-x-max) - var(--safe-x-min));background:transparent}'
        '.lt-dc-card{display:flex;flex-direction:column;gap:12px;background:var(--color-ink);border-radius:14px;padding:24px 38px 26px 32px;box-shadow:0 18px 50px rgba(0,0,0,0.4);will-change:transform,opacity}'
        ".lt-dc-name{display:block;font-family:var(--font-subtitle);font-weight:700;color:var(--color-bg-pure);line-height:1.02;letter-spacing:-0.015em;white-space:nowrap;will-change:transform,opacity}"
        '.lt-dc-rule{display:block;height:4px;border-radius:2px;background:var(--color-accent);transform-origin:0% 50%;will-change:transform}'
        ".lt-dc-role{display:block;font-family:var(--font-subtitle);font-weight:400;color:var(--color-text-soft);line-height:1.2;letter-spacing:0.02em;white-space:nowrap;will-change:opacity}"
    )
    return rules
