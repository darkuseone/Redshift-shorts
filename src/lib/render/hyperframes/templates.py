"""Каталог шаблонов (§15) в терминах HTML/CSS/GSAP.

81 шаблон каталога — это не 81 реализация, а 19 рендереров с параметрами.
Здесь живут именно рендереры; какой из них и с какими числами вызвать, решает
P11 и кладёт в edit-план.

Главное ограничение движка: анимировать разрешено только визуальный список —
``opacity``, ``x``, ``y``, ``scale``, ``rotation``, цвет, ``borderRadius`` и
трансформы. ``filter: blur()`` в него не входит, поэтому размытие делается
статическим слоем, у которого гасится прозрачность: результат тот же, а кадр
остаётся детерминированным при любой перемотке.

Каждый рендерер возвращает :class:`Piece` — узлы, стили и твины на глобальном
времени. Твины пишутся на вложенные элементы, а не на сам клип: видимостью
клипа управляет фреймворк, и трогать её нельзя.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any, Callable

# Слой переходов лежит выше футажа, но ниже субтитров: перекрывать слово
# вспышкой нельзя, оно и так короткое.
Z_TRANSITION = 35
# Приёмы вокруг ведущего: одни уходят ему за спину, другие ложатся поверх.
# Значения совпадают с brand_css — там же общая карта слоёв кадра.
Z_BEHIND_HEAD = 15
Z_AVATAR = 20


@dataclass
class Piece:
    """Вклад шаблона в композицию."""

    nodes: list[str] = field(default_factory=list)
    tweens: list[str] = field(default_factory=list)
    css: list[str] = field(default_factory=list)


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _num(value: float) -> str:
    return f"{float(value):.3f}".rstrip("0").rstrip(".") or "0"


# --- переходы (§4.3) ----------------------------------------------------------
#
# Переход относится к началу шота: он показывает, как кадр входит. Поэтому все
# твины стоят на времени start входящего шота.

def tr_cut(ctx: "TemplateCtx") -> Piece:
    """Прямая склейка — ничего не рисуем. §4.3: таких ≥70 %."""
    return Piece()


def tr_white_flash(ctx: "TemplateCtx") -> Piece:
    peak = float(ctx.params.get("peak", 0.85))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    # Твины идут на вложенный span, а не на сам клип: видимостью клипа
    # управляет фреймворк, и попытка её тянуть оставляет застрявшее
    # состояние при перемотке — lint ловит это как gsap_exit_missing_hard_kill.
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-flash" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(d)}" '
               f'data-track-index="{ctx.track}"><span></span></div>'],
        tweens=[
            f'tl.fromTo("#{node_id} span",{{opacity:0}},'
            f'{{opacity:{peak},duration:{_num(d * 0.35)},ease:"power2.out"}},'
            f'{_num(ctx.start)});',
            f'tl.to("#{node_id} span",{{opacity:0,duration:{_num(d * 0.65)},'
            f'ease:"power2.in"}},{_num(ctx.start + d * 0.35)});',
            f'tl.set("#{node_id} span",{{opacity:0}},{_num(ctx.start + d)});',
        ])


def tr_zoom_punch(ctx: "TemplateCtx") -> Piece:
    """Кадр влетает масштабом. from_scale > 1 — наезд, < 1 — отъезд."""
    from_scale = float(ctx.params.get("from_scale", 1.18))
    overshoot = float(ctx.params.get("overshoot", 0.0))
    if overshoot and from_scale == 1.18:
        from_scale = 1.0 - overshoot
    ease = "back.out(1.6)" if overshoot else "power3.out"
    return Piece(tweens=[
        f'tl.fromTo("#{ctx.target}",{{scale:{from_scale}}},'
        f'{{scale:1,duration:{_num(ctx.duration)},ease:"{ease}"}},{_num(ctx.start)});'
    ])


def tr_blur_dip(ctx: "TemplateCtx") -> Piece:
    """Провал в размытие.

    ``filter`` анимировать нельзя, поэтому кладём слой с постоянным
    ``backdrop-filter`` и гасим его прозрачность. Картинка та же, а свойство —
    из разрешённого списка.
    """
    max_blur = int(ctx.params.get("max_blur", 18))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-blur">'
               f'<span style="backdrop-filter:blur({max_blur}px)"></span></div>'
               .replace('class="clip tr-blur">',
                        f'class="clip tr-blur" data-start="{_num(ctx.start)}" '
                        f'data-duration="{_num(d)}" '
                        f'data-track-index="{ctx.track}">')],
        tweens=[f'tl.fromTo("#{node_id} span",{{opacity:1}},'
                f'{{opacity:0,duration:{_num(d)},ease:"power2.out"}},{_num(ctx.start)});',
                f'tl.set("#{node_id} span",{{opacity:0}},{_num(ctx.start + d)});'])


def tr_whip_pan(ctx: "TemplateCtx") -> Piece:
    """Рывок камерой вбок: кадр въезжает, вслед идёт полоса смаза."""
    direction = int(ctx.params.get("direction", 1))
    blur = int(ctx.params.get("blur", 24))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    offset = 1080 * direction
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-blur" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(d * 0.6)}" '
               f'data-track-index="{ctx.track}">'
               f'<span style="backdrop-filter:blur({blur}px)"></span></div>'],
        tweens=[
            f'tl.fromTo("#{ctx.target}",{{x:{offset}}},'
            f'{{x:0,duration:{_num(d)},ease:"power4.out"}},{_num(ctx.start)});',
            f'tl.fromTo("#{node_id} span",{{opacity:0.9}},'
            f'{{opacity:0,duration:{_num(d * 0.6)},ease:"power2.out"}},{_num(ctx.start)});',
            f'tl.set("#{node_id} span",{{opacity:0}},{_num(ctx.start + d * 0.6)});',
        ])


def tr_paper_slide(ctx: "TemplateCtx") -> Piece:
    """Кадр наезжает листом — по оси и в направлении из параметров."""
    axis = str(ctx.params.get("axis", "x"))
    direction = int(ctx.params.get("direction", 1))
    shift = (1920 if axis == "y" else 1080) * direction
    prop = "y" if axis == "y" else "x"
    return Piece(tweens=[
        f'tl.fromTo("#{ctx.target}",{{{prop}:{shift}}},'
        f'{{{prop}:0,duration:{_num(ctx.duration)},ease:"power3.out"}},{_num(ctx.start)});'
    ])


def tr_mask_wipe(ctx: "TemplateCtx") -> Piece:
    """Раскрытие маской.

    ``clip-path`` анимировать нельзя, поэтому маска — обычный элемент с
    ``border-radius`` и ``overflow:hidden``, которому тянут ``scale``. Круг
    растёт от нуля до диагонали кадра, диагональный вариант — то же, но
    повёрнутым прямоугольником.
    """
    shape = str(ctx.params.get("shape", "circle"))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    css_class = "tr-mask-circle" if shape == "circle" else "tr-mask-diagonal"
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip {css_class}" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(d)}" '
               f'data-track-index="{ctx.track}"><span></span></div>'],
        tweens=[f'tl.fromTo("#{node_id} span",{{scale:0}},'
                f'{{scale:1,duration:{_num(d)},ease:"power3.inOut"}},{_num(ctx.start)});'])


def tr_light_sweep(ctx: "TemplateCtx") -> Piece:
    """Блик проходит по кадру."""
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-sweep" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(d)}" '
               f'data-track-index="{ctx.track}"><span></span></div>'],
        tweens=[f'tl.fromTo("#{node_id} span",{{x:-1400,rotation:18}},'
                f'{{x:1400,duration:{_num(d)},ease:"power2.inOut"}},{_num(ctx.start)});'])


def tr_glitch(ctx: "TemplateCtx") -> Piece:
    """Короткий сбой: несколько полос дёргаются по горизонтали.

    Смещения детерминированы — считаются от индекса шота, а не от
    ``Math.random``: случайность сломала бы повторяемость рендера.
    """
    bars = int(ctx.params.get("bars", 7))
    node_id = f"tr-{ctx.index:02d}"
    d = ctx.duration
    spans, tweens = [], []
    for i in range(bars):
        top = int(1920 * i / bars)
        height = int(1920 / bars)
        shift = (60 + (i * 37 + ctx.index * 13) % 120) * (1 if i % 2 else -1)
        spans.append(f'<span style="top:{top}px;height:{height}px"></span>')
        tweens.append(
            f'tl.fromTo("#{node_id} span:nth-child({i + 1})",{{x:{shift},opacity:0.9}},'
            f'{{x:0,opacity:0,duration:{_num(d)},ease:"steps(3)"}},{_num(ctx.start)});')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip tr-glitch" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(d)}" '
               f'data-track-index="{ctx.track}">{"".join(spans)}</div>'],
        tweens=tweens)


# --- движение кадра -----------------------------------------------------------

def r_kenburns(ctx: "TemplateCtx") -> Piece:
    """Медленный наезд/отъезд по кадру (§15 kenburns)."""
    params = ctx.params
    from_scale = float(params.get("from_scale", 1.0))
    to_scale = float(params.get("to_scale", 1.08))
    pan_x = float(params.get("pan_x", 0.0))
    pan_y = float(params.get("pan_y", 0.0))
    return Piece(tweens=[
        f'tl.fromTo("#{ctx.target}",{{scale:{from_scale},x:0,y:0}},'
        f'{{scale:{to_scale},x:{pan_x},y:{pan_y},'
        f'duration:{_num(ctx.duration)},ease:"none"}},{_num(ctx.start)});'
    ])


def r_parallax(ctx: "TemplateCtx") -> Piece:
    """Два слоя расходятся с разной скоростью — глубина без 3D."""
    shift_pct = float(ctx.params.get("shift_pct", 0.04))
    near = int(1920 * shift_pct)
    far = int(near * 0.35)
    return Piece(tweens=[
        f'tl.fromTo("#{ctx.target}",{{scale:1.06,y:{-far}}},'
        f'{{y:{far},duration:{_num(ctx.duration)},ease:"none"}},{_num(ctx.start)});',
        f'tl.fromTo("#behind-{ctx.index:02d}",{{y:{near}}},'
        f'{{y:{-near},duration:{_num(ctx.duration)},ease:"none"}},{_num(ctx.start)});',
    ])


TRANSITIONS: dict[str, Callable[["TemplateCtx"], Piece]] = {
    "cut": tr_cut,
    "white_flash": tr_white_flash,
    "zoom_punch": tr_zoom_punch,
    "blur_dip": tr_blur_dip,
    "whip_pan": tr_whip_pan,
    "paper_slide": tr_paper_slide,
    "mask_wipe": tr_mask_wipe,
    "light_sweep": tr_light_sweep,
    "glitch": tr_glitch,
}

MOTION: dict[str, Callable[["TemplateCtx"], Piece]] = {
    "kenburns": r_kenburns,
    "parallax": r_parallax,
}


@dataclass
class TemplateCtx:
    """Что нужно рендереру, чтобы собрать свой вклад."""

    index: int
    start: float
    duration: float
    target: str                    # id элемента, к которому применяется движение
    track: int
    params: dict[str, Any] = field(default_factory=dict)


def render_transition(name: str, ctx: TemplateCtx) -> Piece:
    """Собрать переход. Неизвестное имя — прямая склейка, а не падение."""
    fn = TRANSITIONS.get(name)
    if fn is None:
        return Piece()
    return fn(ctx)


def render_motion(name: str, ctx: TemplateCtx) -> Piece:
    fn = MOTION.get(name)
    if fn is None:
        return Piece()
    return fn(ctx)


def transition_css(brandbook: dict[str, Any]) -> str:
    """Стили слоёв переходов. Геометрия — от кадра, цвета — из брендбука."""
    height = int(brandbook["canvas"]["height"])
    width = int(brandbook["canvas"]["width"])
    diagonal = int((width ** 2 + height ** 2) ** 0.5) + 40
    return (
        f".tr-flash,.tr-blur{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "pointer-events:none}"
        ".tr-flash span{position:absolute;inset:0;display:block;"
        "background:var(--color-bg-pure);opacity:0}"
        ".tr-blur span{position:absolute;inset:0;display:block}"
        f".tr-mask-circle,.tr-mask-diagonal{{position:absolute;inset:0;"
        f"z-index:{Z_TRANSITION};overflow:hidden;pointer-events:none}}"
        f".tr-mask-circle span{{position:absolute;left:50%;top:50%;"
        f"width:{diagonal}px;height:{diagonal}px;margin:-{diagonal // 2}px 0 0 -{diagonal // 2}px;"
        "border-radius:50%;background:var(--color-bg-pure);display:block}"
        f".tr-mask-diagonal span{{position:absolute;left:-20%;top:-20%;"
        "width:140%;height:140%;background:var(--color-bg-pure);display:block;"
        "transform-origin:0 0;rotate:-24deg}"
        f".tr-sweep{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-sweep span{position:absolute;top:-30%;left:0;width:280px;height:160%;"
        "display:block;background:linear-gradient(90deg,transparent,"
        "rgba(255,255,255,0.75),transparent)}"
        f".tr-glitch{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-glitch span{position:absolute;left:0;width:100%;display:block;"
        "background:var(--color-accent-soft);opacity:0}"
    )


# --- данные в кадре (§15 data-viz) --------------------------------------------
#
# Числа приходят из сценария через edit-план: рендерер не придумывает данные и
# не берёт их из воздуха. Если значений нет, шаблон не собирается — пустая
# диаграмма врёт сильнее, чем её отсутствие.

def _values(ctx: "TemplateCtx", key: str = "values") -> list[float]:
    raw = ctx.params.get(key) or []
    return [float(v) for v in raw if isinstance(v, (int, float))]


def _labels(ctx: "TemplateCtx", count: int) -> list[str]:
    labels = [str(l) for l in (ctx.params.get("labels") or [])]
    return (labels + [""] * count)[:count]


def dv_bars(ctx: "TemplateCtx") -> Piece:
    """Столбцы: рост по scaleX от нуля.

    Тянется ``scaleX``, а не ``width``: ширина вне разрешённого списка, и
    анимация по ней вдобавок вызывает пересчёт раскладки на каждом кадре.
    Столбец обязан быть блочным и иметь ширину — у элемента нулевой ширины
    масштабирование ничего не показывает.
    """
    values = _values(ctx)
    if not values:
        return Piece()
    peak = max(values) or 1.0
    labels = _labels(ctx, len(values))
    node_id = f"dv-{ctx.index:02d}"

    rows, tweens = [], []
    for i, value in enumerate(values):
        share = max(0.04, value / peak)
        rows.append(
            f'<div class="dv-row"><span class="dv-label">{_esc(labels[i])}</span>'
            f'<span class="dv-bar" style="width:{share * 100:.1f}%"></span>'
            f'<span class="dv-value">{_esc(ctx.params.get("format", "{}").format(value))}</span>'
            f'</div>')
        tweens.append(
            f'tl.fromTo("#{node_id} .dv-row:nth-child({i + 1}) .dv-bar",{{scaleX:0}},'
            f'{{scaleX:1,duration:0.5,ease:"power3.out"}},'
            f'{_num(ctx.start + 0.12 * i)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay dv" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{"".join(rows)}</div>'],
        tweens=tweens)


def dv_counter(ctx: "TemplateCtx") -> Piece:
    """Счётчик: цифры набегают до конечного значения.

    Промежуточные значения — не результат таймера, а кадры твина по
    ``scale``/``opacity`` заранее выписанных ступеней: рендер обязан давать
    один и тот же кадр при любой перемотке.
    """
    target = float(ctx.params.get("value", 0))
    steps = max(2, int(ctx.params.get("steps", 12)))
    suffix = str(ctx.params.get("suffix", ""))
    node_id = f"dv-{ctx.index:02d}"

    spans, tweens = [], []
    per = ctx.duration * 0.7 / steps
    for i in range(steps + 1):
        value = target * (i / steps)
        text = f"{value:,.0f}".replace(",", " ") if abs(target) >= 1000 else f"{value:.0f}"
        spans.append(f'<span>{_esc(text + suffix)}</span>')
        at = ctx.start + per * i
        tweens.append(f'tl.set("#{node_id} span:nth-child({i + 1})",'
                      f'{{opacity:1}},{_num(at)});')
        if i < steps:
            tweens.append(f'tl.set("#{node_id} span:nth-child({i + 1})",'
                          f'{{opacity:0}},{_num(at + per)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay dv-counter" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{"".join(spans)}</div>'],
        tweens=tweens)


def dv_donut(ctx: "TemplateCtx") -> Piece:
    """Кольцо: заполняется поворотом полумасок — conic-gradient не анимируется."""
    percent = max(0.0, min(100.0, float(ctx.params.get("value", 0))))
    node_id = f"dv-{ctx.index:02d}"
    half = percent > 50
    first_deg = 180 if half else percent / 100 * 360
    second_deg = (percent - 50) / 100 * 360 if half else 0
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay dv-donut" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">'
               f'<span class="dv-ring"><i class="a"></i><i class="b"></i></span>'
               f'<span class="dv-pct">{percent:.0f}%</span></div>'],
        tweens=[
            f'tl.fromTo("#{node_id} .a",{{rotation:0}},'
            f'{{rotation:{first_deg:.1f},duration:{_num(ctx.duration * 0.6)},'
            f'ease:"power2.out"}},{_num(ctx.start)});',
            f'tl.fromTo("#{node_id} .b",{{rotation:0}},'
            f'{{rotation:{second_deg:.1f},duration:{_num(ctx.duration * 0.6)},'
            f'ease:"power2.out"}},{_num(ctx.start)});',
        ])


def dv_dots(ctx: "TemplateCtx") -> Piece:
    """Точки на линии времени — появляются по очереди."""
    labels = [str(l) for l in (ctx.params.get("labels") or [])]
    if not labels:
        return Piece()
    node_id = f"dv-{ctx.index:02d}"
    items, tweens = [], []
    step = ctx.duration * 0.6 / max(1, len(labels))
    for i, label in enumerate(labels):
        items.append(f'<span class="dv-dot"><i></i>{_esc(label)}</span>')
        tweens.append(
            f'tl.fromTo("#{node_id} .dv-dot:nth-child({i + 1})",'
            f'{{scale:0.4,opacity:0}},{{scale:1,opacity:1,duration:0.34,'
            f'ease:"back.out(1.7)"}},{_num(ctx.start + step * i)});')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay dv-dots" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{"".join(items)}</div>'],
        tweens=tweens)


DATAVIZ: dict[str, Callable[["TemplateCtx"], Piece]] = {
    "bar-race-mini": dv_bars,
    "compare-bars": dv_bars,
    "line-rise": dv_bars,          # линия строится теми же значениями
    "counter-roll": dv_counter,
    "donut-fill": dv_donut,
    "timeline-dots": dv_dots,
}


def render_dataviz(template_id: str, ctx: "TemplateCtx") -> Piece:
    """Собрать диаграмму по id шаблона каталога (``data-viz/<name>``)."""
    name = template_id.rsplit("/", 1)[-1]
    fn = DATAVIZ.get(name)
    if fn is None:
        return Piece()
    return fn(ctx)


def dataviz_css(brandbook: dict[str, Any]) -> str:
    safe = brandbook["safe_zones"]["work_area"]
    width = int(safe["x_max"]) - int(safe["x_min"])
    return (
        ".dv,.dv-counter,.dv-donut,.dv-dots{left:var(--safe-x-min);"
        f"width:{width}px;top:38%;font-family:var(--font-subtitle);"
        "color:var(--color-ink)}"
        ".dv-row{display:flex;align-items:center;gap:18px;margin-bottom:22px}"
        ".dv-label{width:26%;font-size:34px;font-weight:800;text-align:right}"
        # Столбец обязан быть блочным и иметь ширину: у элемента нулевой ширины
        # масштаб не покажет ничего.
        ".dv-bar{display:block;height:54px;border-radius:12px;"
        "background:var(--color-accent);transform-origin:left center}"
        ".dv-value{font-size:32px;font-weight:800;color:var(--color-muted)}"
        ".dv-counter{text-align:center;font-family:var(--font-display);"
        "font-size:190px;line-height:1}"
        ".dv-counter span{position:absolute;left:0;right:0;opacity:0}"
        ".dv-dots{display:flex;justify-content:space-between;align-items:center}"
        ".dv-dot{display:flex;flex-direction:column;align-items:center;gap:12px;"
        "font-size:28px;font-weight:700}"
        ".dv-dot i{display:block;width:34px;height:34px;border-radius:50%;"
        "background:var(--color-accent)}"
        ".dv-donut{display:flex;flex-direction:column;align-items:center;gap:24px}"
        ".dv-ring{position:relative;display:block;width:360px;height:360px;"
        "border-radius:50%;background:var(--color-accent-soft);overflow:hidden}"
        ".dv-ring i{position:absolute;left:50%;top:0;width:50%;height:100%;"
        "background:var(--color-accent);transform-origin:left center;display:block}"
        ".dv-pct{font-family:var(--font-display);font-size:96px}"
    )


# --- режим B: сплит (§3.5) ----------------------------------------------------

def r_split(ctx: "TemplateCtx") -> Piece:
    """Кадр делится: сверху футаж, снизу ведущий.

    Раскрывается сдвигом обеих половин навстречу. Геометрия задаётся классами,
    а не твинами: анимируется только ``y``, из разрешённого списка.
    """
    enter = float(ctx.params.get("enter_ms", 260)) / 1000.0
    top_id, bottom_id = f"{ctx.target}-top", f"{ctx.target}-bottom"
    return Piece(tweens=[
        f'tl.fromTo("#{top_id}",{{y:-540}},'
        f'{{y:0,duration:{_num(enter)},ease:"power3.out"}},{_num(ctx.start)});',
        f'tl.fromTo("#{bottom_id}",{{y:540}},'
        f'{{y:0,duration:{_num(enter)},ease:"power3.out"}},{_num(ctx.start)});',
    ])


MOTION["split"] = r_split


def split_css(brandbook: dict[str, Any]) -> str:
    """Половины сплита. Лицо остаётся в своей полосе (§3.5)."""
    height = int(brandbook["canvas"]["height"])
    seam = int(height * 0.52)
    return (
        f".split-top{{position:absolute;left:0;right:0;top:0;height:{seam}px;"
        "overflow:hidden;z-index:10}"
        f".split-bottom{{position:absolute;left:0;right:0;top:{seam}px;"
        f"height:{height - seam}px;overflow:hidden;z-index:10}}"
        ".split-top > video,.split-bottom > video{width:100%;height:100%;"
        "object-fit:cover;display:block}"
    )


# --- приёмы вокруг ведущего (§5.3) --------------------------------------------
#
# Пять способов положить текст и графику относительно человека в кадре. Все
# держатся на одном правиле: **ведущий остаётся читаемым**. Текст и картинка
# либо уходят за него, либо делят с ним кадр, либо пропускают его сквозь
# себя — но не закрывают лицо.

# Геометрия лучей. Длины гуляют в [RAY_LEN_MIN, RAY_LEN_MIN + RAY_LEN_SPAN),
# чтобы веер не выглядел циркулем; RAY_CAP_PAD — запас снизу под закруглённый
# торец, который при повороте опускается ниже точки вращения.
RAY_LEN_MIN = 300
RAY_LEN_SPAN = 90
RAY_CAP_PAD = 40


def hero_burst(ctx: "TemplateCtx") -> Piece:
    """Лучи за головой.

    Веер полос расходится из точки за головой ведущего и раскрывается
    поворотом. Лучи рисуются в собственном слое ниже аватара, поэтому голова
    остаётся поверх, как на референсе.

    Углы считаются от индекса шота, а не случайно: рендер сэмплирует кадры
    не по порядку.

    Габариты контейнера считаются здесь, а не в CSS, и это не украшение:
    продюсер HyperFrames **пропускает .clip с нулевой площадью вместе с его
    содержимым**. Веер, подвешенный к точке ``width:0;height:0``, в кадр не
    попадал — в браузере он рисовался, в рендере исчезал. Проверено кадром:
    тот же веер в коробке 1080×600 отрисовался целиком.
    """
    rays = int(ctx.params.get("rays", 9))
    spread = float(ctx.params.get("spread_deg", 150))
    node_id = f"hb-{ctx.index:02d}"
    center_y = int(ctx.params.get("center_y", 560))

    lengths = [RAY_LEN_MIN + ((i * 53 + ctx.index * 17) % RAY_LEN_SPAN)
               for i in range(rays)]
    reach = max(lengths) if lengths else RAY_LEN_MIN
    box_h = reach + RAY_CAP_PAD
    box_top = center_y - reach

    spans, tweens = [], []
    for i, length in enumerate(lengths):
        angle = -spread / 2 + spread * i / max(1, rays - 1)
        spans.append(f'<span style="--a:{angle:.1f}deg;--len:{length}px"></span>')
        tweens.append(
            f'tl.fromTo("#{node_id} span:nth-child({i + 1})",{{scaleY:0}},'
            f'{{scaleY:1,duration:0.42,ease:"back.out(1.4)"}},'
            f'{_num(ctx.start + 0.03 * i)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-burst" '
               f'style="top:{box_top}px;height:{box_h}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{"".join(spans)}</div>'],
        tweens=tweens)


def hero_headline(ctx: "TemplateCtx") -> Piece:
    """Заголовок над головой: мелкий кикер, крупное слово, подчёркивание.

    Подчёркивание растёт по ``scaleX`` от левого края — так его видно как
    жест, а не как статичную линию. Слово выходит снизу и садится на место:
    вход из-за головы читается как «мысль всплыла».
    """
    kicker = str(ctx.params.get("kicker") or "")
    word = str(ctx.params.get("word") or "")
    if not word:
        return Piece()
    node_id = f"hh-{ctx.index:02d}"
    top = int(ctx.params.get("top", 190))

    kicker_html = (f'<span class="hh-kicker">{_esc(kicker)}</span>' if kicker else "")
    tweens = [
        f'tl.fromTo("#{node_id} .hh-word",{{y:54,opacity:0}},'
        f'{{y:0,opacity:1,duration:0.42,ease:"power3.out"}},{_num(ctx.start)});',
        f'tl.fromTo("#{node_id} .hh-rule",{{scaleX:0}},'
        f'{{scaleX:1,duration:0.38,ease:"power3.out"}},{_num(ctx.start + 0.22)});',
    ]
    if kicker:
        # Твин по несобранной разметке — молчаливый no-op, и он же прячет
        # опечатку в селекторе: анимируем только то, что нарисовали.
        tweens.insert(1,
                      f'tl.fromTo("#{node_id} .hh-kicker",{{opacity:0}},'
                      f'{{opacity:1,duration:0.28,ease:"power2.out"}},'
                      f'{_num(ctx.start + 0.08)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-headline" style="top:{top}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{kicker_html}'
               f'<span class="hh-word">{_esc(word)}</span>'
               f'<span class="hh-rule"></span></div>'],
        tweens=tweens)


def hero_split(ctx: "TemplateCtx") -> Piece:
    """Кадр делится: ведущий слева, гигантское слово столбцом справа.

    Слово набирается по буквам сверху вниз — на вертикали это читается лучше,
    чем целиком, и даёт ритм. Панель въезжает справа, ведущий не двигается:
    двигать обоих значит потерять лицо из фокуса.
    """
    word = str(ctx.params.get("word") or "")
    if not word:
        return Piece()
    node_id = f"hs-{ctx.index:02d}"
    letters = "".join(f"<span>{_esc(ch)}</span>" for ch in word)
    # Ведущий уходит влево и укрупняется: панель занимает почти половину
    # кадра, и по центру от него осталась бы одна щека.
    shift = int(ctx.params.get("subject_shift", -210))
    zoom = float(ctx.params.get("subject_zoom", 1.14))
    # Клип аватара живёт дольше приёма, поэтому сдвиг обязан отыграть назад:
    # иначе ведущий останется прижатым к левому краю до конца сегмента.
    back = max(ctx.start + 0.44, ctx.start + ctx.duration - 0.34)
    tweens = [
        # Едет обёртка, а не сам клип: видимостью клипа распоряжается движок, и
        # твин прямо на нём оставляет застрявшее состояние при перемотке.
        f'tl.fromTo("#{node_id}-in",{{x:620}},'
        f'{{x:0,duration:0.44,ease:"power3.out"}},{_num(ctx.start)});',
        f'tl.fromTo("#{ctx.target}",{{x:0,scale:1}},'
        f'{{x:{shift},scale:{zoom},duration:0.44,ease:"power3.out"}},'
        f'{_num(ctx.start)});',
        f'tl.to("#{ctx.target}",'
        f'{{x:0,scale:1,duration:0.30,ease:"power2.inOut"}},{_num(back)});',
    ]
    for i in range(len(word)):
        tweens.append(
            f'tl.fromTo("#{node_id} .hs-word span:nth-child({i + 1})",'
            f'{{opacity:0,y:-26}},{{opacity:1,y:0,duration:0.24,ease:"power2.out"}},'
            f'{_num(ctx.start + 0.2 + 0.05 * i)});')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-split" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">'
               f'<div id="{node_id}-in" class="hs-in">'
               f'<span class="hs-word">{letters}</span></div></div>'],
        tweens=tweens)


def hero_knockout(ctx: "TemplateCtx") -> Piece:
    """Выбивка: заливка на весь кадр, буквы прозрачны, в них виден ведущий.

    Буквы вырезаются SVG-маской, а не ``mix-blend-mode``: маска даёт тот же
    результат детерминированно и не зависит от того, в каком порядке продюсер
    складывает слои. Панель наезжает масштабом — тянется ``scale``, из
    разрешённого списка, а не ``clip-path``.
    """
    word = str(ctx.params.get("word") or "")
    if not word:
        return Piece()
    node_id = f"hk-{ctx.index:02d}"
    lines = word.split()
    # Кегль ужимается под самую длинную строку. Заглавная кириллица Oswald
    # занимает примерно 0.52 кегля на знак; без этого длинное слово вылезает
    # за кадр и обрезается — проверено на «ЕДИНСТВЕННАЯ».
    margin = int(ctx.params.get("margin", 60))
    longest = max((len(l) for l in lines), default=1)
    fits = int((1080 - 2 * margin) / max(1, longest * 0.52))
    size = min(int(ctx.params.get("size", 300)), fits)
    step = int(size * 0.92)
    top = (1920 - step * len(lines)) // 2 + int(size * 0.34)

    text_nodes = "".join(
        f'<text x="540" y="{top + step * i}" text-anchor="middle">{_esc(line)}</text>'
        for i, line in enumerate(lines))

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-knockout" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">'
               f'<svg viewBox="0 0 1080 1920" preserveAspectRatio="none">'
               f'<defs><mask id="{node_id}-m">'
               f'<rect width="1080" height="1920" fill="white"/>'
               f'<g class="hk-text" font-size="{size}">{text_nodes}</g>'
               f'</mask></defs>'
               f'<rect width="1080" height="1920" mask="url(#{node_id}-m)" '
               f'class="hk-fill"/></svg></div>'],
        tweens=[
            f'tl.fromTo("#{node_id} svg",{{scale:1.12,opacity:0}},'
            f'{{scale:1,opacity:1,duration:0.36,ease:"power3.out"}},{_num(ctx.start)});'
        ])


# Панель-задник. Габариты фиксированные: приём читается как «экран на стене»,
# и плавающий размер превратил бы его в случайный прямоугольник. Смещение
# крупное и одним краем уходит за кадр: панель ровно по центру ставит лицо в
# середину картинки, и приём читается как фон, а не как кадр за плечом.
PLATE_W, PLATE_H, PLATE_TOP = 660, 560, 280
PLATE_OFFSET = 185


def hero_plate(ctx: "TemplateCtx") -> Piece:
    """Картинка за спиной ведущего.

    Главный приём референса: человек сидит за столом, а позади него появляется
    кадр — как экран на стене. Панель лежит под аватаром (``Z_BEHIND_HEAD``),
    поэтому голова и плечи всегда поверх неё, и картинка читается задником, а не
    перекрытием.

    Видео здесь — сам клип, а не вложенный элемент: ``<video>`` внутри
    элемента с ``data-start`` движок под управление не берёт, и в рендере кадр
    застывает первым фреймом (lint: ``video_nested_in_timed_element``). Из-за
    этого у приёма нет твина входа: видимостью клипа распоряжается движок, а
    тянуть его самого контракт запрещает. Картинка появляется срезом — ровно
    как на референсе.

    Сторона смещения берётся из индекса шота, а не случайно: рендер сэмплирует
    кадры не по порядку, и ``Math.random`` дал бы разные кадры одного шота.
    """
    src = str(ctx.params.get("src") or "")
    if not src:
        return Piece()
    node_id = f"hp-{ctx.index:02d}"
    side = 1 if ctx.index % 2 else -1
    left = (1080 - PLATE_W) // 2 + side * PLATE_OFFSET
    top = int(ctx.params.get("top", PLATE_TOP))

    return Piece(
        nodes=[f'<video id="{node_id}" class="clip hero-plate" src="{_esc(src)}" '
               f'style="left:{left}px;top:{top}px;'
               f'width:{PLATE_W}px;height:{PLATE_H}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}" muted playsinline></video>'])


HERO: dict[str, Callable[["TemplateCtx"], Piece]] = {
    "hero-burst": hero_burst,
    "hero-headline": hero_headline,
    "hero-plate": hero_plate,
    "hero-split": hero_split,
    "hero-knockout": hero_knockout,
}


def render_hero(name: str, ctx: "TemplateCtx") -> Piece:
    fn = HERO.get(name.rsplit("/", 1)[-1])
    return fn(ctx) if fn else Piece()


def hero_css(brandbook: dict[str, Any]) -> str:
    """Стили приёмов вокруг ведущего.

    Слои сидят между фоном и аватаром (лучи, заголовок) либо поверх него
    (сплит, выбивка) — это задаётся z-index, а не порядком в разметке.
    """
    height = int(brandbook["canvas"]["height"])
    # Колонка лайк/коммент/шер съедает правое поле кадра (§3.2). Панель сплита
    # доходит до края — так и на референсе, — но буквы внутри неё обязаны
    # остаться левее: под иконками их не прочитать.
    ui_column = int(brandbook["canvas"]["width"]) - int(
        brandbook["safe_zones"]["work_area"]["x_max"])
    return (
        # --- лучи за головой ---
        # Коробка полноразмерная, а высоту и верх ставит шаблон: у .clip с
        # нулевой площадью продюсер не рисует ни саму рамку, ни детей.
        ".hero-burst{position:absolute;left:0;width:var(--frame-w);"
        f"z-index:{Z_BEHIND_HEAD};pointer-events:none}}"
        # Стартовый scaleY задаёт GSAP через fromTo. Тот же transform в CSS
        # конфликтует с твином, и лучи остаются свёрнутыми: проверено кадром.
        # rotate — отдельное свойство, оно с transform не спорит.
        f".hero-burst span{{position:absolute;left:calc(50% - 26px);"
        f"bottom:{RAY_CAP_PAD}px;display:block;"
        "width:52px;height:var(--len);border-radius:26px;"
        "background:var(--color-accent-soft);transform-origin:50% 100%;"
        "rotate:var(--a)}"
        # --- картинка за спиной ---
        # Габариты ставит шаблон; рамка живёт на самом видео, потому что видео
        # здесь и есть клип: вложенное медиа движок не проигрывает.
        f".hero-plate{{position:absolute;display:block;z-index:{Z_BEHIND_HEAD};"
        "object-fit:cover;border-radius:36px;"
        "border:10px solid var(--color-bg-pure);background:var(--color-bg-pure);"
        "box-shadow:0 26px 70px rgba(0,0,0,0.28);pointer-events:none}"
        # --- заголовок над головой ---
        ".hero-headline{position:absolute;left:0;right:0;text-align:center;"
        f"z-index:{Z_BEHIND_HEAD};pointer-events:none}}"
        ".hero-headline .hh-kicker{display:block;font-family:var(--font-subtitle);"
        "font-weight:800;font-size:34px;letter-spacing:0.22em;"
        "text-transform:uppercase;color:var(--color-ink);opacity:0.75}"
        ".hero-headline .hh-word{display:block;font-family:var(--font-display);"
        "font-size:168px;line-height:0.94;text-transform:uppercase;"
        "color:var(--color-accent);margin-top:10px}"
        ".hero-headline .hh-rule{display:block;width:420px;height:9px;"
        "margin:18px auto 0;border-radius:6px;background:var(--color-accent);"
        "transform-origin:left center}"
        # --- сплит с панелью ---
        ".hero-split{position:absolute;right:0;top:0;width:46%;"
        f"height:{height}px;z-index:{Z_AVATAR + 1};"
        "overflow:hidden;pointer-events:none}"
        ".hero-split .hs-in{position:absolute;inset:0;"
        "background:var(--color-accent-soft);display:flex;align-items:center;"
        f"justify-content:center;padding-right:{ui_column}px;"
        "will-change:transform}"
        ".hero-split .hs-word{display:flex;flex-direction:column;"
        "align-items:center;font-family:var(--font-display);font-size:172px;"
        "line-height:0.86;text-transform:uppercase;color:var(--color-ink)}"
        ".hero-split .hs-word span{display:block}"
        # --- выбивка ---
        ".hero-knockout{position:absolute;inset:0;"
        f"z-index:{Z_AVATAR + 1};pointer-events:none}}"
        ".hero-knockout svg{width:100%;height:100%;display:block}"
        ".hero-knockout .hk-fill{fill:var(--color-accent-soft)}"
        # Чёрный в маске = дырка: сквозь буквы виден ведущий.
        ".hero-knockout .hk-text{fill:#000;font-family:var(--font-display);"
        "font-weight:700;letter-spacing:-0.01em}"
    )
