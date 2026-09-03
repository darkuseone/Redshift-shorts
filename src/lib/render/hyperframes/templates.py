"""Каталог шаблонов (§15) в терминах HTML/CSS/GSAP.

112 шаблонов каталога — это не 112 реализаций, а набор рендереров с параметрами.
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
import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
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


def _timing(ctx: "TemplateCtx") -> str:
    return (f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
            f'data-track-index="{ctx.track}"')


def _mark_accent(text: str, accent: str) -> str:
    """Красным одно слово, не строка (§3.3.2)."""
    if not accent or accent.upper() not in text.upper():
        return _esc(text)
    idx = text.upper().index(accent.upper())
    return (_esc(text[:idx])
            + f'<span class="accent">{_esc(text[idx:idx + len(accent)])}</span>'
            + _esc(text[idx + len(accent):]))


def _content_of(ctx: "TemplateCtx") -> tuple[str, str, bool]:
    content = str(ctx.params.get("content") or "").strip()
    accent = str(ctx.params.get("accent_word") or "").strip()
    invert = bool(ctx.params.get("invert"))
    return content, accent, invert


def _enter_at(ctx: "TemplateCtx") -> float:
    """Старт движения: клип уже виден, вход ждёт конца перехода кадра."""
    return ctx.start + float(ctx.params.get("enter_delay") or 0)


def _hold(ctx: "TemplateCtx") -> float:
    return max(0.2, ctx.duration - float(ctx.params.get("enter_delay") or 0))


# Ширина строки нужна, чтобы кегль подбирался под кадр, а не под догадку. Здесь
# стояла оценка «0.52 кегля на знак», и «ЕДИНСТВЕННЫЙ» из-за неё вылезал за
# кадр: у Oswald Bold прописная кириллица занимает 0.546…0.604 кегля, то есть
# оценка врала на 12 %. Меряем настоящей гарнитурой.
#
# Запасное значение — верх измеренного диапазона: без ассетов лучше ужать
# лишнего, чем обрезать слово.
_FALLBACK_EM_PER_CHAR = 0.62


@lru_cache(maxsize=4)
def _display_font(size: int):
    """Гарнитура заголовков из проверенного набора (§3.4). None — если её нет."""
    try:
        from PIL import ImageFont

        manifest = json.loads(
            (Path("assets/fonts") / "fonts_manifest.json").read_text(encoding="utf-8"))
        entry = next(f for f in manifest["fonts"] if f.get("role") == "display")
        return ImageFont.truetype(str(Path("assets/fonts") / entry["file"]), size)
    except Exception:                                        # noqa: BLE001
        return None


def text_width(text: str, size: int) -> float:
    """Ширина строки в пикселях при данном кегле."""
    font = _display_font(100)
    if font is None:
        return len(text) * size * _FALLBACK_EM_PER_CHAR
    box = font.getbbox(text)
    return (box[2] - box[0]) * size / 100.0


def fit_size(text: str, available_px: float, max_size: int) -> int:
    """Наибольший кегль, при котором строка укладывается в ширину."""
    if not text:
        return max_size
    at_max = text_width(text, max_size)
    if at_max <= available_px:
        return max_size
    return max(24, int(max_size * available_px / at_max))


# --- словарь появления --------------------------------------------------------
#
# Ничего в кадре не «включается» — всё **приближается**. Это единственное
# правило, из которого выведены числа ниже, и оно взято с референсов: элемент
# приходит из чуть большего или чуть меньшего масштаба и садится на место.
#
# Почему числа именно такие:
#
# * **Масштаб малый — 0.86…1.14.** Крупный наезд читается как зум видеоряда и
#   спорит с Ken Burns; малый читается как «предмет подали ближе».
# * **Кривая затухающая — ``power3.out`` и ``expo.out``.** Движение начинается
#   быстро и долго успокаивается. Равномерная кривая выглядит машинной,
#   ускоряющаяся — как срыв.
# * **Прозрачность едет тем же твином, что и масштаб.** Отдельная кривая для
#   неё выиграла бы доли кадра и заняла второе окно на том же элементе — риск
#   наложения твинов не стоит того.
# * **Стаггер плотный — 40…70 мс.** Строки должны читаться очередью, а не
#   списком, который выкладывают по одной.
#
# Прозрачность **нельзя** тянуть на самом клипе: видимостью клипа распоряжается
# движок, и твин на ней застревает при перемотке (``gsap_exit_missing_hard_kill``).
# Трансформы на клипе разрешены — на них держится Ken Burns. Поэтому у
# ``entrance_tweens`` есть переключатель ``fade``: на клипе он выключен, и вход
# остаётся чистым приближением.

ENTRANCES: dict[str, dict[str, float | str]] = {
    # Приближение: элемент приходит «издалека» и садится. База для всего.
    "zoom-in": {"scale": 1.14, "y": 0, "duration": 0.55, "ease": "power3.out"},
    # Подача вперёд: элемент выходит из глубины. Для круглых рамок и плашек —
    # там приближение из большего масштаба обрезало бы края.
    "zoom-out": {"scale": 0.86, "y": 0, "duration": 0.50, "ease": "back.out(1.4)"},
    # Всплытие: подъём со смещением. Для строк текста и подписей.
    "rise": {"scale": 1.05, "y": 64, "duration": 0.52, "ease": "power3.out"},
    # Оседание: короткий приход сверху. Для заголовков над головой.
    "settle": {"scale": 1.04, "y": -46, "duration": 0.48, "ease": "expo.out"},
    # Единственное исключение из «ничего не включается»: полнокадровая
    # заслонка. Она не предмет, который приносят, а смена света — двигать её
    # нечем, любой масштаб обнажит края кадра.
    "dim": {"scale": 1.0, "y": 0, "duration": 0.42, "ease": "power2.out"},
}

# Дрейф на удержании: пока элемент висит, он еле заметно едет. Без этого кадр
# после входа замирает, и монтаж рассыпается на статичные карточки. Величина
# намеренно ниже порога осознанного замечания — работает боковым зрением.
DRIFT_SCALE = 1.035
DRIFT_MIN_SEC = 1.2


def entrance_tweens(target: str, start: float, *, name: str = "zoom-in",
                    fade: bool = True, delay: float = 0.0,
                    scale_to: float = 1.0) -> list[str]:
    """Твины появления элемента.

    ``fade=False`` для клипов: прозрачность у них за движком.
    ``scale_to`` — конечный масштаб, если элемент обязан остаться увеличенным.
    """
    spec = ENTRANCES.get(name) or ENTRANCES["zoom-in"]
    at = start + delay
    duration = float(spec["duration"])
    scale_from, shift = float(spec["scale"]), float(spec["y"])

    # Без проявления вход обязан **расти**, а не уменьшаться. Проверено кадром:
    # панель, приходящая из 1.14 без прозрачности, читается не как появление, а
    # как «она уже была здесь и отъезжает» — первый кадр застаёт её крупной и
    # непрозрачной. Из меньшего масштаба тот же путь читается как «появилась и
    # встала на место». С проявлением работают оба направления, и там мы
    # оставляем то, что задал словарь.
    if not fade and scale_from > 1.0:
        scale_from = round(2.0 - scale_from, 3)

    from_state = [f"scale:{scale_from}"]
    to_state = [f"scale:{scale_to}"]
    if shift:
        from_state.append(f"y:{shift:g}")
        to_state.append("y:0")
    if fade:
        from_state.append("opacity:0")
        to_state.append("opacity:1")

    return [f'tl.fromTo("{target}",{{{",".join(from_state)}}},'
            f'{{{",".join(to_state)},duration:{_num(duration)},'
            f'ease:"{spec["ease"]}"}},{_num(at)});']


def drift_tween(target: str, start: float, duration: float, *,
                to_scale: float = DRIFT_SCALE, from_scale: float = 1.0) -> list[str]:
    """Медленный дрейф на удержании — кадр не замирает после входа.

    Пустой список, если удержание короче ``DRIFT_MIN_SEC``: на секунде дрейф
    незаметен, а твин занимает то же свойство, что и вход, и движок считает
    наложение ошибкой.
    """
    if duration < DRIFT_MIN_SEC:
        return []
    return [f'tl.fromTo("{target}",{{scale:{from_scale}}},'
            f'{{scale:{to_scale},duration:{_num(duration)},ease:"none"}},'
            f'{_num(start)});']


def enter_and_drift(target: str, start: float, duration: float, *,
                    name: str = "zoom-in", fade: bool = True,
                    delay: float = 0.0) -> list[str]:
    """Вход, а следом дрейф до конца окна.

    Дрейф начинается там, где кончается вход: оба тянут ``scale`` одного
    элемента, а наложение двух твинов на одном свойстве движок считает ошибкой —
    порядок перезаписи в GSAP зависит от очерёдности и может смениться между
    рендерами.
    """
    spec = ENTRANCES.get(name) or ENTRANCES["zoom-in"]
    enter_sec = float(spec["duration"]) + delay
    tweens = entrance_tweens(target, start, name=name, fade=fade, delay=delay)
    tweens += drift_tween(target, start + enter_sec,
                          max(0.0, duration - enter_sec))
    return tweens


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


def tr_zoom_through(ctx: "TemplateCtx") -> Piece:
    """Наезд в деталь на склейке — жест zoom-through из SpaceX explainer.

    Тот же ``zoom_punch``, но сильнее: кадр входит из 1.22, будто камера
    проваливается в следующий план. Динамический, со SFX, не чаще 1/6 сек.
    """
    merged = dict(ctx.params)
    merged.setdefault("from_scale", 1.22)
    return tr_zoom_punch(TemplateCtx(
        index=ctx.index, start=ctx.start, duration=ctx.duration,
        target=ctx.target, track=ctx.track, params=merged))


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
    "zoom_through": tr_zoom_through,
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

    def alt_track(self, n: int = 1) -> int:
        """Дополнительный трек приёму, который собирает больше одного клипа.

        Клипы одного приёма живут в одном окне, а движок запрещает пересечение
        клипов на общем треке (``overlapping_clips_same_track``). Шаг в два, а
        не в один: соседние шоты уже разведены по чётности, и ``track + 1``
        попал бы в полосу соседа.
        """
        return self.track + 2 * n

    @property
    def track_alt(self) -> int:
        return self.alt_track(1)


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


def dv_stat_card(ctx: "TemplateCtx") -> Piece:
    """Набегающая метрика на карточке — жест SpaceX result card.

    Ступени выписаны заранее, как у ``dv_counter``: рендер сэмплирует кадры
    не по порядку, и таймер дал бы разные значения на одном таймкоде.
    """
    label = str(ctx.params.get("label") or "").strip()
    node_id = f"sc-{ctx.index:02d}"
    # Счётчик из dv_counter несёт свой id и трек. Пересобираем карточку
    # вокруг тех же span-ступеней, чтобы вход шёл на обёртку, а не на клип.
    target = float(ctx.params.get("value", 0))
    steps = max(2, int(ctx.params.get("steps", 12)))
    suffix = str(ctx.params.get("suffix", ""))
    spans, tweens = [], []
    per = ctx.duration * 0.7 / steps
    for i in range(steps + 1):
        value = target * (i / steps)
        text = (f"{value:,.0f}".replace(",", " ") if abs(target) >= 1000
                else f"{value:.0f}")
        spans.append(f'<span>{_esc(text + suffix)}</span>')
        at = ctx.start + per * i
        tweens.append(f'tl.set("#{node_id} .sc-num span:nth-child({i + 1})",'
                      f'{{opacity:1}},{_num(at)});')
        if i < steps:
            tweens.append(
                f'tl.set("#{node_id} .sc-num span:nth-child({i + 1})",'
                f'{{opacity:0}},{_num(at + per)});')
    kicker = f'<span class="sc-label">{_esc(label)}</span>' if label else ""
    tweens = entrance_tweens(f"#{node_id} .sc-in", ctx.start, name="zoom-out") + tweens
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay stat-card" {_timing(ctx)}>'
               f'<div class="sc-in">{kicker}'
               f'<span class="sc-num">{"".join(spans)}</span></div></div>'],
        tweens=tweens)


DATAVIZ: dict[str, Callable[["TemplateCtx"], Piece]] = {
    "bar-race-mini": dv_bars,
    "compare-bars": dv_bars,
    "line-rise": dv_bars,          # линия строится теми же значениями
    "counter-roll": dv_counter,
    "donut-fill": dv_donut,
    "timeline-dots": dv_dots,
    "stat-countup-card": dv_stat_card,
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
        "background:var(--color-accent-soft);transform-origin:left center}"
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
        ".stat-card{left:var(--safe-x-min);"
        "width:calc(var(--safe-x-max) - var(--safe-x-min));top:240px}"
        ".stat-card .sc-in{display:block;padding:48px 40px 40px;border-radius:32px;"
        "background:var(--color-bg-light);color:var(--color-ink);"
        "box-shadow:0 22px 60px rgba(0,0,0,0.22);text-align:center;"
        "will-change:transform}"
        ".stat-card .sc-label{display:block;font-family:var(--font-subtitle);"
        "font-weight:800;font-size:34px;letter-spacing:0.14em;"
        "text-transform:uppercase;color:var(--color-muted);margin-bottom:12px}"
        ".stat-card .sc-num{position:relative;display:block;height:1.05em;"
        "font-family:var(--font-display);font-size:168px;line-height:1.05;"
        "color:var(--color-ink)}"
        ".stat-card .sc-num span{position:absolute;left:0;right:0;opacity:0}"
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
            f'{{scaleY:1,duration:0.46,ease:"expo.out"}},'
            f'{_num(ctx.start + 0.035 * i)});')

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
    # Кегль подбирается измерением: заголовок идёт в одну строку через весь
    # кадр, и длинное слово при фиксированном кегле обрезалось бы краем.
    size = fit_size(word, 1080 - 2 * 50, int(ctx.params.get("size", 168)))

    kicker_html = (f'<span class="hh-kicker">{_esc(kicker)}</span>' if kicker else "")
    # Слово оседает сверху и потом еле заметно едет: после входа кадр не имеет
    # права замереть.
    tweens = enter_and_drift(f"#{node_id} .hh-word", ctx.start, ctx.duration,
                             name="settle")
    tweens.append(
        f'tl.fromTo("#{node_id} .hh-rule",{{scaleX:0}},'
        f'{{scaleX:1,duration:0.38,ease:"expo.out"}},{_num(ctx.start + 0.26)});')
    if kicker:
        # Твин по несобранной разметке — молчаливый no-op, и он же прячет
        # опечатку в селекторе: анимируем только то, что нарисовали.
        tweens += entrance_tweens(f"#{node_id} .hh-kicker", ctx.start,
                                  name="rise", delay=0.10)

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-headline" style="top:{top}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{kicker_html}'
               f'<span class="hh-word" style="font-size:{size}px">{_esc(word)}</span>'
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
    enter = 0.52
    back = max(ctx.start + enter, ctx.start + ctx.duration - 0.34)
    tweens = [
        # Едет обёртка, а не сам клип: прозрачность клипа за движком, и твин на
        # ней оставляет застрявшее состояние при перемотке.
        f'tl.fromTo("#{node_id}-in",{{x:620}},'
        f'{{x:0,duration:{_num(enter)},ease:"expo.out"}},{_num(ctx.start)});',
        # Ведущий одновременно уходит влево и приближается: сдвиг без укрупнения
        # читается как «его подвинули», а вместе — как смена плана.
        f'tl.fromTo("#{ctx.target}",{{x:0,scale:1}},'
        f'{{x:{shift},scale:{zoom},duration:{_num(enter)},ease:"expo.out"}},'
        f'{_num(ctx.start)});',
        f'tl.to("#{ctx.target}",'
        f'{{x:0,scale:1,duration:0.34,ease:"power2.inOut"}},{_num(back)});',
    ]
    for i in range(len(word)):
        # Буквы очередью, шаг плотный: выложенные по одной, они читаются
        # медленнее, чем слово произносится.
        tweens += entrance_tweens(
            f"#{node_id} .hs-word span:nth-child({i + 1})", ctx.start,
            name="settle", delay=0.22 + 0.045 * i)
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
    # Заливка по умолчанию тёмная, а не акцентная: §3.3.1 держит акцент в
    # 10–12 % площади кадра, а этот приём закрывает весь кадр целиком. Чёрный —
    # такой же цвет бренда, и ведущий, проступающий сквозь буквы со светлого
    # фона, на нём читается контрастнее.
    fill = str(ctx.params.get("fill", "ink")).replace("_", "-")
    lines = word.split()
    # Кегль ужимается под самую длинную строку, измеренную настоящей
    # гарнитурой: оценка «столько-то кегля на знак» врёт на десяток процентов,
    # и слово обрезается краем кадра — проверено на «ЕДИНСТВЕННЫЙ».
    margin = int(ctx.params.get("margin", 60))
    longest = max(lines, key=len, default="")
    size = fit_size(longest, 1080 - 2 * margin, int(ctx.params.get("size", 300)))
    step = int(size * 0.92)
    # Блок садится на лицо, а не в середину кадра. Буквы здесь — дырки, и видно
    # сквозь них то, что за ними: на уровне торса это тёмная одежда, которая от
    # тёмной заливки не отличается, и слово пропадало серединой. Лицо —
    # единственная область кадра, гарантированно светлее заливки.
    centre = int(ctx.params.get("face_cy", 960))
    centre = max(320, min(1500, centre))
    top = centre - (step * len(lines)) // 2 + int(size * 0.34)

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
               f'fill="var(--color-{fill})"/></svg></div>'],
        tweens=enter_and_drift(f"#{node_id} svg", ctx.start, ctx.duration,
                               name="zoom-in"))


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
    застывает первым фреймом (lint: ``video_nested_in_timed_element``).

    Вход у приёма всё же есть, и это приближение: на клипе запрещена только
    прозрачность, трансформы разрешены — на них держится Ken Burns. Проверено
    линтом: ``scale`` на медиа-клипе проходит без ошибок.

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
               f'data-track-index="{ctx.track}" muted playsinline></video>'],
        tweens=enter_and_drift(f"#{node_id}", ctx.start, ctx.duration,
                               name="zoom-in", fade=False))


def hero_text_column(ctx: "TemplateCtx") -> Piece:
    """Строки колонкой слева, ведущий справа.

    Референс: реплика разложена на короткие строки, они встают очередью снизу
    вверх, а одна-две подсвечены акцентом. Колонка занимает левую половину и
    поднимается от нижней трети — там, где у ведущего плечо, а не лицо.

    Акцент задаётся индексами строк, а не разметкой в тексте: строки приходят
    из плана, и звёздочки в них пришлось бы экранировать и парсить в двух
    местах.
    """
    lines = [str(l).strip() for l in (ctx.params.get("lines") or []) if str(l).strip()]
    if not lines:
        return Piece()
    accents = {int(i) for i in (ctx.params.get("accent_lines") or [])}
    node_id = f"tc-{ctx.index:02d}"
    # Колонка садится ниже лица — на уровень плеча и торса. На 560 она резала
    # голову пополам: аватар HeyGen стоит по центру кадра, а не справа, как на
    # референсе, и левая колонка неизбежно пересекает лицо выше плеч.
    top = int(ctx.params.get("top", 700))

    spans, tweens = [], []
    for i, line in enumerate(lines[:5]):
        css = "tc-line accent" if i in accents else "tc-line"
        spans.append(f'<span class="{css}">{_esc(line)}</span>')
        tweens += entrance_tweens(f"#{node_id} .tc-line:nth-child({i + 1})",
                                  ctx.start, name="rise", delay=0.07 * i)

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-text-column" '
               f'style="top:{top}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{"".join(spans)}</div>'],
        tweens=tweens)


def hero_bubble_card(ctx: "TemplateCtx") -> Piece:
    """Ведущий в круге, реплика карточкой под ним.

    Референс: человека **обрезают в кружок** на тёмном поле, под ним белая
    карточка с фразой. Кольцо поверх кадра этого не даёт — тело остаётся видно
    вокруг, и приём читается как рамка, а не как смена плана.

    Круг вырезается SVG-маской в тёмном поле, и сквозь дырку виден сам аватар.
    Второе видео с ``border-radius:50%`` не годится: продюсер рисует кадры в
    коробку элемента, **игнорируя скругление и рамку** — проверено зумом,
    получался квадрат. Маской вырезает надёжно, тем же приёмом, что и выбивка.

    «Резко помещают в круг» — ровно то, чего быть не должно: поле проявляется,
    а сам ведущий в это время приближается, и переход читается сменой плана.
    """
    lines = [str(l).strip() for l in (ctx.params.get("lines") or []) if str(l).strip()]
    if not lines:
        return Piece()
    node_id = f"bc-{ctx.index:02d}"
    accent_last = bool(ctx.params.get("accent_last", True))
    # Круг ставится по реальному лицу: у сегмента аватара есть face_bbox, и
    # догадка «четверть высоты кадра» промахивалась мимо головы на сотню
    # пикселей. Без bbox остаётся прежняя оценка.
    ring = int(ctx.params.get("ring", 460))
    face_x = int(ctx.params.get("face_cx", 540))
    face_y = int(ctx.params.get("face_cy", 0.24 * 1920 + ring // 2))
    radius = ring // 2

    body = "".join(
        f'<span class="bc-line{" accent" if accent_last and i == len(lines) - 1 else ""}">'
        f'{_esc(line)}</span>'
        for i, line in enumerate(lines[:4]))
    card_top = face_y + radius + 46

    svg = (f'<svg class="bc-field" viewBox="0 0 1080 1920" preserveAspectRatio="none">'
           f'<defs>'
           f'<radialGradient id="{node_id}-g" cx="50%" cy="30%" r="80%">'
           f'<stop offset="0%" stop-color="#2A2320"/>'
           f'<stop offset="58%" stop-color="#141416"/>'
           f'<stop offset="100%" stop-color="#08090B"/>'
           f'</radialGradient>'
           f'<mask id="{node_id}-m">'
           f'<rect width="1080" height="1920" fill="white"/>'
           f'<circle cx="{face_x}" cy="{face_y}" r="{radius}" fill="black"/>'
           f'</mask>'
           f'</defs>'
           f'<rect width="1080" height="1920" mask="url(#{node_id}-m)" '
           f'fill="url(#{node_id}-g)"/>'
           f'<circle cx="{face_x}" cy="{face_y}" r="{radius + 5}" fill="none" '
           f'stroke="#FFFFFF" stroke-width="10"/>'
           f'</svg>')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-bubble-card" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{svg}'
               f'<span class="bc-card" style="top:{card_top}px">{body}</span></div>'],
        tweens=(
            entrance_tweens(f"#{node_id} .bc-field", ctx.start, name="dim")
            + entrance_tweens(f"#{node_id} .bc-card", ctx.start,
                              name="zoom-out", delay=0.10)
            # Ведущий приближается внутри дырки: без этого «помещение в круг»
            # выглядит как включённая заслонка, а не как смена плана.
            #
            # Только вход, без дрейфа. Клип аватара общий и может покрывать
            # несколько слотов, а дрейф оставил бы на нём остаточный масштаб
            # после конца приёма — та же утечка, ради которой у сплита стоит
            # обратный твин. Замереть ведущий при этом не может: он живое
            # видео и говорит.
            + entrance_tweens(f"#{ctx.target}", ctx.start,
                              name="zoom-in", fade=False)
        ))


def hero_brand_pill(ctx: "TemplateCtx") -> Piece:
    """Пилюля с логотипом бренда сбоку от ведущего.

    Референс: чёрная скруглённая плашка с иконкой и названием компании
    появляется у плеча. Иконка берётся из библиотеки брендов (§14) — путь
    приходит параметром, потому что искать её здесь нечем.

    Пилюля выходит из глубины и слегка отъезжает: сторона считается от индекса
    шота, а не случайно.
    """
    label = str(ctx.params.get("label") or "").strip()
    if not label:
        return Piece()
    node_id = f"bp-{ctx.index:02d}"
    icon = str(ctx.params.get("icon") or "")
    side = "right" if ctx.index % 2 else "left"
    top = int(ctx.params.get("top", 1180))

    icon_html = (f'<img class="bp-icon" src="{_esc(icon)}" alt="" />' if icon else "")
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-brand-pill {side}" '
               f'style="top:{top}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">'
               f'<span class="bp-inner">{icon_html}'
               f'<span class="bp-label">{_esc(label)}</span></span></div>'],
        tweens=entrance_tweens(f"#{node_id} .bp-inner", ctx.start, name="zoom-out"))


def hero_card_stack(ctx: "TemplateCtx") -> Piece:
    """Карточка с заголовком и картинкой сверху, ведущий снизу.

    Референс: кадр поделён по горизонтали — сверху белая плашка с крупным
    заголовком и иллюстрацией, снизу говорящий. Отличие от сплита: там панель
    сбоку и ведущий сдвигается, здесь он остаётся на месте, а сверху ложится
    отдельный слой.

    Картинка — самостоятельный клип: ``<video>`` внутри элемента с
    ``data-start`` движок не проигрывает, кадр застывает первым фреймом.
    """
    title = str(ctx.params.get("title") or "").strip()
    if not title:
        return Piece()
    node_id = f"cs-{ctx.index:02d}"
    src = str(ctx.params.get("src") or "")
    height = int(ctx.params.get("height", 860))

    nodes = [f'<div id="{node_id}" class="clip hero-card-stack" '
             f'style="height:{height}px" '
             f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
             f'data-track-index="{ctx.track}">'
             f'<span class="cs-title">{_esc(title)}</span></div>']
    tweens = entrance_tweens(f"#{node_id} .cs-title", ctx.start, name="settle")

    if src:
        # Картинка живёт внутри карточки: высота считается от её нижнего края,
        # а не от полной высоты приёма — иначе кадр торчит из-под скругления.
        media_top = 120 + int(height * 0.34)
        media_height = max(120, height - media_top - 56)
        nodes.append(
            f'<video id="{node_id}-m" class="clip cs-media" src="{_esc(src)}" '
            f'style="top:{media_top}px;height:{media_height}px" '
            f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
            f'data-track-index="{ctx.track_alt}" muted playsinline></video>')
        tweens += enter_and_drift(f"#{node_id}-m", ctx.start, ctx.duration,
                                  name="zoom-in", fade=False)
    return Piece(nodes=nodes, tweens=tweens)


def hero_phone_mock(ctx: "TemplateCtx") -> Piece:
    """Экран телефона поверх размытого кадра.

    Референс: интерфейс приложения висит в центре, фон уходит в расфокус.
    Строки набираются очередью — это и есть «переписка», а не скриншот.

    Размытие статическое: ``filter`` вне разрешённого списка движка, и его
    анимация ломает перемотку. Расфокус даёт полупрозрачная подложка.
    """
    lines = [str(l).strip() for l in (ctx.params.get("lines") or []) if str(l).strip()]
    if not lines:
        return Piece()
    node_id = f"pm-{ctx.index:02d}"
    app = str(ctx.params.get("app") or "")

    rows, tweens = [], []
    for i, line in enumerate(lines[:4]):
        side = "out" if i % 2 else "in"
        rows.append(f'<span class="pm-row {side}">{_esc(line)}</span>')
        tweens += entrance_tweens(f"#{node_id} .pm-row:nth-child({i + 1})",
                                  ctx.start, name="rise", delay=0.16 + 0.13 * i)

    head = f'<span class="pm-app">{_esc(app)}</span>' if app else ""
    tweens = entrance_tweens(f"#{node_id} .pm-body", ctx.start,
                             name="zoom-out") + tweens
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-phone-mock" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">'
               f'<span class="pm-body">{head}'
               f'<span class="pm-rows">{"".join(rows)}</span></span></div>'],
        tweens=tweens)


def hero_type_slab(ctx: "TemplateCtx") -> Piece:
    """Плита типа слева от ведущего — жест Srinika × Mercury.

    Два-три слова Oswald на всю высоту рабочей зоны. Субтитр на этом окне
    гасится: те же слова по центру — дубль.
    """
    lines = [str(l).strip() for l in (ctx.params.get("lines") or []) if str(l).strip()]
    if not lines:
        return Piece()
    accents = {int(i) for i in (ctx.params.get("accent_lines") or [])}
    node_id = f"ts-{ctx.index:02d}"
    available = 1080 * 0.48
    longest = max(lines, key=len)
    size = fit_size(longest.upper(), available, int(ctx.params.get("size", 148)))
    rows, tweens = [], []
    for i, line in enumerate(lines[:4]):
        cls = "accent" if i in accents else ""
        rows.append(f'<span class="ts-line {cls}" style="font-size:{size}px">'
                    f'{_esc(line.upper())}</span>')
        tweens += entrance_tweens(f"#{node_id} .ts-line:nth-child({i + 1})",
                                  ctx.start, name="settle", delay=0.05 * i)
    top = int(ctx.params.get("top", 420))
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-type-slab" style="top:{top}px" '
               f'{_timing(ctx)}>{"".join(rows)}</div>'],
        tweens=tweens)


def hero_plate_pop(ctx: "TemplateCtx") -> Piece:
    """Футаж в рамке въезжает поверх кадра — UI-окно как у Stripe-launch.

    Видео само является клипом: вложенное в timed-элемент застывает первым
    кадром. Рамка ``bg_pure``, вход ``zoom-out`` без прозрачности.
    """
    src = str(ctx.params.get("src") or "")
    if not src:
        return Piece()
    node_id = f"pp-{ctx.index:02d}"
    width = int(ctx.params.get("width", 920))
    height = int(ctx.params.get("height", 580))
    left = (1080 - width) // 2
    top = int(ctx.params.get("top", 210))
    return Piece(
        nodes=[f'<video id="{node_id}" class="clip hero-plate-pop" src="{_esc(src)}" '
               f'style="left:{left}px;top:{top}px;width:{width}px;height:{height}px" '
               f'{_timing(ctx)} muted playsinline></video>'],
        tweens=enter_and_drift(f"#{node_id}", ctx.start, ctx.duration,
                               name="zoom-out", fade=False))


HERO: dict[str, Callable[["TemplateCtx"], Piece]] = {
    "hero-burst": hero_burst,
    "hero-headline": hero_headline,
    "hero-plate": hero_plate,
    "hero-split": hero_split,
    "hero-knockout": hero_knockout,
    "hero-text-column": hero_text_column,
    "hero-bubble-card": hero_bubble_card,
    "hero-brand-pill": hero_brand_pill,
    "hero-card-stack": hero_card_stack,
    "hero-phone-mock": hero_phone_mock,
    "hero-type-slab": hero_type_slab,
    "hero-plate-pop": hero_plate_pop,
}


def render_hero(name: str, ctx: "TemplateCtx") -> Piece:
    fn = HERO.get(name.rsplit("/", 1)[-1])
    return fn(ctx) if fn else Piece()


# --- полноэкранный текст: params шаблона наконец читаются ---------------------

def _fs_ceiling(ctx: "TemplateCtx") -> int:
    raw = ctx.params.get("size_px")
    if isinstance(raw, (list, tuple)) and raw:
        return int(raw[-1])
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return int(raw)
        except ValueError:
            return 420
    return 420


def _fs_size(ctx: "TemplateCtx", text: str) -> int:
    ceiling = _fs_ceiling(ctx)
    available = float(ctx.params.get("available_px") or 900)
    longest = max(text.upper().split() or [text], key=len, default="")
    return fit_size(longest, available, ceiling)


def fs_plain(ctx: "TemplateCtx") -> Piece:
    """Базовый полноэкранный кадр: одно поле, вход приближением."""
    content, accent, invert = _content_of(ctx)
    if not content:
        return Piece()
    node_id = ctx.target
    size = _fs_size(ctx, content)
    cls = "clip fullscreen-text" + (" invert" if invert else "")
    if ctx.params.get("underline"):
        cls += " fs-underline"
    if ctx.params.get("quotes"):
        cls += " fs-quote"
    markup = _mark_accent(content, accent)
    if ctx.params.get("quotes"):
        markup = f'<span class="fs-q">«</span>{markup}<span class="fs-q">»</span>'
    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span id="{node_id}-inner" style="font-size:{size}px">'
               f'{markup}</span></div>'],
        tweens=enter_and_drift(f"#{node_id}-inner", _enter_at(ctx), _hold(ctx),
                               name="zoom-in"))


# Каталог blur-out-up: ось, дальность, сила размытия. Движок не тянет filter,
# поэтому пиксели считаются здесь и кладутся в статичный CSS у призрака.
_BOU_AXES = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}
_BOU_REACH = {"close": 0.5, "standard": 1.0, "far": 1.85}
_BOU_BLUR = {"soft": 0.45, "standard": 1.0, "heavy": 2.2}
_BOU_BASE_PX = 22.0
_BOU_BASE_BLUR = 5.0
_BOU_REF_SIZE = 56.0  # кегль демо-каталога; ход масштабируем к Oswald
_BOU_ENTER = 0.3
_BOU_EXIT = 0.28
_BOU_SCALE_FROM = 0.92


def _bou_motion(params: dict[str, Any], size: int) -> tuple[float, float, int]:
    """Смещение входа и радиус призрака из переменных каталога."""
    direction = str(params.get("direction") or "up").lower()
    if direction not in _BOU_AXES:
        direction = "up"
    axis_x, axis_y = _BOU_AXES[direction]
    reach = _BOU_REACH.get(str(params.get("distance") or "standard"), 1.0)
    blur_scale = _BOU_BLUR.get(str(params.get("blur") or "standard"), 1.0)
    # 22 px при 56 px в каталоге. На 9:16 кегль ~200–420, иначе ход не читается.
    em = max(24, size) / _BOU_REF_SIZE
    dist = _BOU_BASE_PX * reach * em
    return axis_x * dist, axis_y * dist, max(1, int(round(_BOU_BASE_BLUR * blur_scale)))


def fs_kinetic_stack(ctx: "TemplateCtx") -> Piece:
    """Слова входят очередью — Texture launch / OBLIST, не весь блок сразу."""
    content, accent, invert = _content_of(ctx)
    if not content:
        return Piece()
    node_id = ctx.target
    words = content.split()
    size = _fs_size(ctx, content)
    cls = "clip fullscreen-text fs-kinetic" + (" invert" if invert else "")
    spans, tweens = [], []
    stagger = float(ctx.params.get("stagger_ms", 55)) / 1000.0
    at = _enter_at(ctx)
    for i, word in enumerate(words):
        marked = " accent" if accent and accent.lower() in word.lower() else ""
        spans.append(f'<span class="ks-word{marked}">{_esc(word)}</span>')
        tweens += entrance_tweens(
            f"#{node_id} .ks-word:nth-child({i + 1})", at,
            name="rise", delay=stagger * i)
    hold_start = at + 0.55
    hold = ctx.start + ctx.duration - hold_start
    if hold > DRIFT_MIN_SEC:
        tweens += drift_tween(f"#{node_id}-inner", hold_start, hold)
    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span id="{node_id}-inner" class="ks-stack" '
               f'style="font-size:{size}px">{"".join(spans)}</span></div>'],
        tweens=tweens)


def fs_blur_out_up(ctx: "TemplateCtx") -> Piece:
    """Слова выходят из размытия и уходят дальше по оси — blur-out-up.

    Каталог HyperFrames анимирует CSS ``filter``. Движок этого не умеет,
    поэтому у каждого слова два слоя: острый и призрак со статическим
    ``filter: blur()``. Проявляется сменой прозрачности, подъём — ``y``/``x``
    и ``scale`` на обёртке, не на клипе. Жёлтый/изумруд каталога → ``accent``
    на одном слове. Выход продолжает ту же ось: вверх для ``direction=up``.
    """
    content, accent, invert = _content_of(ctx)
    if not content:
        return Piece()
    node_id = ctx.target
    words = content.split()
    size = _fs_size(ctx, content)
    enter_x, enter_y, blur_px = _bou_motion(ctx.params, size)
    stagger = float(ctx.params.get("stagger_ms", 55)) / 1000.0
    at = _enter_at(ctx)
    end = ctx.start + ctx.duration
    n = len(words)
    last_enter_end = at + _BOU_ENTER + stagger * max(0, n - 1)
    exit_dur = _BOU_EXIT
    exit_at = end - exit_dur
    do_exit = last_enter_end + 0.05 <= exit_at
    if not do_exit and last_enter_end + 0.16 < end:
        exit_at = last_enter_end + 0.05
        exit_dur = end - exit_at
        do_exit = True

    cls = "clip fullscreen-text fs-blur-up" + (" invert" if invert else "")
    spans: list[str] = []
    tweens: list[str] = []
    accented = False
    enter_from = [f"scale:{_num(_BOU_SCALE_FROM)}"]
    enter_to = ["scale:1"]
    exit_from = ["scale:1"]
    exit_to = ["scale:0.96"]
    if enter_x:
        enter_from.append(f"x:{_num(enter_x)}")
        enter_to.append("x:0")
        exit_from.append("x:0")
        exit_to.append(f"x:{_num(-enter_x)}")
    if enter_y:
        enter_from.append(f"y:{_num(enter_y)}")
        enter_to.append("y:0")
        exit_from.append("y:0")
        exit_to.append(f"y:{_num(-enter_y)}")
    enter_from_s, enter_to_s = ",".join(enter_from), ",".join(enter_to)
    exit_from_s, exit_to_s = ",".join(exit_from), ",".join(exit_to)

    for i, word in enumerate(words):
        marked = ""
        if accent and not accented and accent.lower() in word.lower():
            marked = " accent"
            accented = True
        wid = f"{node_id}-w{i}"
        spans.append(
            f'<span id="{wid}" class="bou-word{marked}">'
            f'<span id="{wid}-s" class="bou-sharp">{_esc(word)}</span>'
            f'<span id="{wid}-g" class="bou-ghost" style="filter:blur({blur_px}px)">'
            f'{_esc(word)}</span></span>'
        )
        word_at = at + stagger * i
        tweens.append(
            f'tl.fromTo("#{wid}",{{{enter_from_s}}},{{{enter_to_s},'
            f'duration:{_num(_BOU_ENTER)},ease:"power3.out"}},{_num(word_at)});'
        )
        tweens.append(
            f'tl.fromTo("#{wid}-s",{{opacity:0}},{{opacity:1,'
            f'duration:{_num(_BOU_ENTER)},ease:"power3.out"}},{_num(word_at)});'
        )
        tweens.append(
            f'tl.fromTo("#{wid}-g",{{opacity:0.85}},{{opacity:0,'
            f'duration:{_num(_BOU_ENTER)},ease:"power3.out"}},{_num(word_at)});'
        )
        if do_exit:
            # Выход без стаггера: иначе последнее слово вылезает за окно клипа.
            tweens.append(
                f'tl.fromTo("#{wid}",{{{exit_from_s}}},{{{exit_to_s},'
                f'duration:{_num(exit_dur)},ease:"power3.in"}},{_num(exit_at)});'
            )
            tweens.append(
                f'tl.fromTo("#{wid}-s",{{opacity:1}},{{opacity:0,'
                f'duration:{_num(exit_dur)},ease:"power3.in"}},{_num(exit_at)});'
            )
            tweens.append(
                f'tl.fromTo("#{wid}-g",{{opacity:0}},{{opacity:0.8,'
                f'duration:{_num(exit_dur)},ease:"power3.in"}},{_num(exit_at)});'
            )
        tweens.append(f'tl.set("#{wid}-s",{{opacity:0}},{_num(end)});')
        tweens.append(f'tl.set("#{wid}-g",{{opacity:0}},{_num(end)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span id="{node_id}-inner" class="bou-stack" '
               f'style="font-size:{size}px">{"".join(spans)}</span></div>'],
        tweens=tweens)


# Per-Word Crossfade: каталог твинит CSS-var и filter. Вход тот же, что у
# blur-out-up, но без ухода: HOLD стоит. drift/blur — те же шкалы, что distance.
_PWC_ENTER = 0.3
_PWC_STAGGER = 0.055
_PWC_SCALE_FROM = 0.92
_PWC_EXIT_Y = 76


def fs_per_word_crossfade(ctx: "TemplateCtx") -> Piece:
    """Слова входят из лёгкого блюра с коротким подъёмом — per-word-crossfade.

    Каталог тянет ``--hf-word-y`` / ``--hf-word-blur`` и ``filter``. Здесь ход
    в px, призрак со статическим ``filter:blur()``, ``scale`` 0.92→1.
    Inter / ``#18181b`` / зелёный ``--brand`` → Oswald, ``ink`` на ``bg_pure``,
    одно слово ``accent``. Твины на словах, не на ``.clip``. HOLD без дрейфа.
    """
    content, accent, invert = _content_of(ctx)
    if str(ctx.params.get("tone") or "").lower() == "paper":
        invert = True
    if not content:
        return Piece()
    node_id = ctx.target
    words = content.split()
    if not words:
        return Piece()
    size = _fs_size(ctx, content)
    motion = dict(ctx.params)
    motion["direction"] = "up"
    motion["distance"] = str(motion.get("drift") or motion.get("distance") or "standard")
    _ex, enter_y, blur_px = _bou_motion(motion, size)
    stagger = float(ctx.params.get("stagger_ms") or _PWC_STAGGER * 1000) / 1000.0
    at = _enter_at(ctx)
    end = ctx.start + ctx.duration
    n = len(words)
    last_end = at + _PWC_ENTER + stagger * max(0, n - 1)
    if n > 1 and last_end > end - 0.04:
        stagger = max(0.02, (end - 0.04 - at - _PWC_ENTER) / (n - 1))
    exit_mode = str(ctx.params.get("exit") or "none").lower()
    if exit_mode not in ("none", "fade", "up"):
        exit_mode = "none"
    out = 0.0 if exit_mode == "none" else 0.28
    out_at = end - out if out else end

    cls = "clip fullscreen-text fs-pwc" + (" invert" if invert else "")
    spans: list[str] = []
    tweens: list[str] = []
    accented = False
    for i, word in enumerate(words):
        marked = ""
        if accent and not accented and accent.lower() in word.lower():
            marked = " accent"
            accented = True
        wid = f"{node_id}-w{i}"
        spans.append(
            f'<span id="{wid}" class="pwc-word{marked}">'
            f'<span id="{wid}-s" class="pwc-sharp">{_esc(word)}</span>'
            f'<span id="{wid}-g" class="pwc-ghost" style="filter:blur({blur_px}px)">'
            f'{_esc(word)}</span></span>'
        )
        word_at = at + stagger * i
        tweens.append(
            f'tl.fromTo("#{wid}",{{scale:{_num(_PWC_SCALE_FROM)},'
            f'y:{_num(enter_y)}}},{{scale:1,y:0,duration:{_num(_PWC_ENTER)},'
            f'ease:"power3.out"}},{_num(word_at)});'
        )
        tweens.append(
            f'tl.fromTo("#{wid}-s",{{opacity:0}},{{opacity:1,'
            f'duration:{_num(_PWC_ENTER)},ease:"power3.out",'
            f'immediateRender:false}},{_num(word_at)});'
        )
        tweens.append(
            f'tl.fromTo("#{wid}-g",{{opacity:0.85}},{{opacity:0,'
            f'duration:{_num(_PWC_ENTER)},ease:"power3.out",'
            f'immediateRender:false}},{_num(word_at)});'
        )

    if exit_mode == "fade" and out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-inner",{{opacity:1}},{{opacity:0,'
            f'duration:{_num(out)},ease:"power2.in",immediateRender:false}},'
            f'{_num(out_at)});')
    elif exit_mode == "up" and out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-inner",{{opacity:1,y:0}},'
            f'{{opacity:0,y:{_num(-_PWC_EXIT_Y)},duration:{_num(out)},'
            f'ease:"power2.in",immediateRender:false}},{_num(out_at)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span id="{node_id}-inner" class="pwc-stack" '
               f'style="font-size:{size}px">{"".join(spans)}</span></div>'],
        tweens=tweens)


_BUL_TRAVEL = {"close": 0.45, "standard": 0.85, "far": 1.5}
_BUL_ENTER = 0.48
_BUL_EASE = "back.out(1.7)"


def fs_bottom_up_letters(ctx: "TemplateCtx") -> Piece:
    """Буквы поднимаются с нижней линии — bottom-up-letters.

    Каталог ставит стартовый ``translate`` в CSS и тянет ``tl.to``. Движок
    требует ``fromTo`` без CSS-transform на том же узле. Кремовый Inter на
    тёмном → Oswald, ``ink`` на ``bg_pure``, одно слово ``accent``. Стаггер
    25 мс по глифу; ``unit=word`` поднимает целые слова тем же жестом.
    """
    content, accent, invert = _content_of(ctx)
    if not content:
        return Piece()
    node_id = ctx.target
    words = content.split()
    size = _fs_size(ctx, content)
    unit = str(ctx.params.get("unit") or "letter").lower()
    if unit not in ("letter", "word"):
        unit = "letter"
    direction = str(ctx.params.get("direction") or "up").lower()
    sign = -1.0 if direction == "down" else 1.0
    travel_em = _BUL_TRAVEL.get(str(ctx.params.get("travel") or "standard"), 0.85)
    travel_px = sign * travel_em * size
    stagger = float(ctx.params.get("stagger_ms", 25)) / 1000.0
    at = _enter_at(ctx)
    end = ctx.start + ctx.duration
    n = len(words) if unit == "word" else sum(len(word) for word in words)
    last_end = at + _BUL_ENTER + stagger * max(0, n - 1)
    if n > 1 and last_end > end - 0.04:
        stagger = max(0.012, (end - 0.04 - at - _BUL_ENTER) / (n - 1))

    cls = "clip fullscreen-text fs-letters" + (" invert" if invert else "")
    word_html: list[str] = []
    tweens: list[str] = []
    accented = False
    step = 0

    def _rise(target: str, when: float) -> str:
        return (
            f'tl.fromTo("{target}",{{opacity:0,y:{_num(travel_px)}}},'
            f'{{opacity:1,y:0,duration:{_num(_BUL_ENTER)},'
            f'ease:"{_BUL_EASE}"}},{_num(when)});'
        )

    for word in words:
        marked = ""
        if accent and not accented and accent.lower() in word.lower():
            marked = " accent"
            accented = True
        if unit == "word":
            cid = f"{node_id}-c{step}"
            word_html.append(
                f'<span id="{cid}" class="bul-word bul-unit{marked}">'
                f'{_esc(word)}</span>'
            )
            tweens.append(_rise(f"#{cid}", at + stagger * step))
            step += 1
            continue
        chars = []
        for ch in word:
            cid = f"{node_id}-c{step}"
            chars.append(f'<span id="{cid}" class="bul-ch">{_esc(ch)}</span>')
            tweens.append(_rise(f"#{cid}", at + stagger * step))
            step += 1
        word_html.append(f'<span class="bul-word{marked}">{"".join(chars)}</span>')

    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span id="{node_id}-inner" class="bul-stack" '
               f'style="font-size:{size}px">{"".join(word_html)}</span></div>'],
        tweens=tweens)


def fs_number_slam(ctx: "TemplateCtx") -> Piece:
    """Цифра-удар на карточке — K3 promo. Число отдельно, подпись ниже."""
    content, accent, invert = _content_of(ctx)
    if not content:
        return Piece()
    parts = content.split()
    if parts and re.match(r"^[\d$€£%.,+\-×xX]+", parts[0]):
        number, caption = parts[0], " ".join(parts[1:])
    else:
        number, caption = content, ""
    node_id = ctx.target
    size = _fs_size(ctx, number)
    cls = "clip fullscreen-text fs-slam" + (" invert" if invert else "")
    cap = (f'<span class="fs-cap">{_esc(caption)}</span>' if caption else "")
    tweens = entrance_tweens(f"#{node_id}-inner", _enter_at(ctx), name="zoom-in")
    if caption:
        tweens += entrance_tweens(f"#{node_id} .fs-cap", _enter_at(ctx),
                                  name="rise", delay=0.12)
    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span class="fs-slam-card">'
               f'<span id="{node_id}-inner" class="fs-num" '
               f'style="font-size:{size}px">{_mark_accent(number, accent or number)}'
               f'</span>{cap}</span></div>'],
        tweens=tweens)


# Line-by-Line Slide: каталог твинит CSS-переменные x/y/blur. 36/18/6 px
# при 52 px Inter → 0.692/0.346/0.115 em. Стаггер 80 мс, вход 0.34s.
_LBLS_SIZE = {"compact": 0.76, "standard": 1.0, "display": 1.18}
_LBLS_GAP_EM = {"fine": 4 / 52, "standard": 10 / 52, "coarse": 20 / 52}
_LBLS_X_EM = 36 / 52
_LBLS_Y_EM = 18 / 52
_LBLS_BLUR_EM = 6 / 52
_LBLS_ENTER = 0.34
_LBLS_EXIT = 0.28
_LBLS_STAGGER = 0.08


def _lbls_lines(content: str, params: dict[str, Any]) -> list[str]:
    """Строки слота: явный список, пайп, перевод строки — иначе пачка как лесенка."""
    raw = params.get("lines")
    if isinstance(raw, (list, tuple)) and raw:
        return [str(part).strip() for part in raw if str(part).strip()]
    text = str(content or "").strip()
    if not text:
        return []
    if "|" in text:
        return [part.strip() for part in text.split("|") if part.strip()]
    if "\n" in text:
        return [part.strip() for part in text.splitlines() if part.strip()]
    words = text.split()
    max_lines = max(1, int(params.get("max_lines") or 3))
    per = max(1, (len(words) + max_lines - 1) // max_lines)
    return [" ".join(words[i:i + per]) for i in range(0, len(words), per)][:max_lines]


def fs_line_by_line_slide(ctx: "TemplateCtx") -> Piece:
    """Строки заезжают слева со стаггером и уезжают вправо — line-by-line-slide.

    Каталог твинит ``--hf-line-x/y/blur`` и CSS ``filter``. Движок этого не
    умеет: ход в пикселях, размытие — призрак со статическим ``filter:blur()``.
    Inter 52 px / изумруд → Oswald, ``ink`` на ``bg_pure``, одно слово accent.
    ``tone=paper`` переворачивает кадр. На ``.clip`` прозрачность не трогаем.
    """
    content, accent, invert = _content_of(ctx)
    lines = _lbls_lines(content, ctx.params)
    if not lines:
        return Piece()
    tone = str(ctx.params.get("tone") or "ink").lower()
    if tone == "paper":
        invert = True
    direction = str(ctx.params.get("direction") or "left").lower()
    if direction not in ("left", "right"):
        direction = "left"
    density = str(ctx.params.get("density") or "standard").lower()
    gap_em = _LBLS_GAP_EM.get(density, _LBLS_GAP_EM["standard"])
    size_key = str(ctx.params.get("size") or "standard").lower()
    factor = _LBLS_SIZE.get(size_key, 1.0)

    node_id = ctx.target
    available = float(ctx.params.get("available_px") or 900)
    longest = max(lines, key=len)
    ceiling = max(24, int(_fs_ceiling(ctx) * factor))
    size = fit_size(longest, available, ceiling)
    gap = max(2, int(round(gap_em * size)))
    travel_x = round(_LBLS_X_EM * size, 2)
    travel_y = round(_LBLS_Y_EM * size, 2)
    blur_px = max(1, int(round(_LBLS_BLUR_EM * size)))
    enter_x = -travel_x if direction == "left" else travel_x
    exit_x = travel_x if direction == "left" else -travel_x

    stagger = float(ctx.params.get("stagger_ms", _LBLS_STAGGER * 1000)) / 1000.0
    at = _enter_at(ctx)
    end = ctx.start + ctx.duration
    n = len(lines)
    last_enter_end = at + _LBLS_ENTER + stagger * max(0, n - 1)
    exit_dur = _LBLS_EXIT
    exit_at = end - exit_dur
    do_exit = last_enter_end + 0.05 <= exit_at
    if not do_exit and last_enter_end + 0.16 < end:
        exit_at = last_enter_end + 0.05
        exit_dur = end - exit_at
        do_exit = True

    cls = "clip fullscreen-text fs-lbls" + (" invert" if invert else "")
    rows: list[str] = []
    tweens: list[str] = []
    for i, line in enumerate(lines):
        lid = f"{node_id}-l{i}"
        marked = _mark_accent(line, accent)
        rows.append(
            f'<span id="{lid}" class="lbls-line">'
            f'<span id="{lid}-s" class="lbls-sharp">{marked}</span>'
            f'<span id="{lid}-g" class="lbls-ghost" style="filter:blur({blur_px}px)">'
            f'{marked}</span></span>'
        )
        line_at = at + stagger * i
        tweens.append(
            f'tl.fromTo("#{lid}",{{x:{_num(enter_x)},y:{_num(travel_y)}}},'
            f'{{x:0,y:0,duration:{_num(_LBLS_ENTER)},ease:"power3.out",'
            f'immediateRender:false}},{_num(line_at)});'
        )
        tweens.append(
            f'tl.fromTo("#{lid}-s",{{opacity:0}},{{opacity:1,'
            f'duration:{_num(_LBLS_ENTER)},ease:"power3.out",'
            f'immediateRender:false}},{_num(line_at)});'
        )
        tweens.append(
            f'tl.fromTo("#{lid}-g",{{opacity:0.85}},{{opacity:0,'
            f'duration:{_num(_LBLS_ENTER)},ease:"power3.out",'
            f'immediateRender:false}},{_num(line_at)});'
        )
        if do_exit:
            tweens.append(
                f'tl.fromTo("#{lid}",{{x:0,y:0}},{{x:{_num(exit_x)},'
                f'duration:{_num(exit_dur)},ease:"power3.in",'
                f'immediateRender:false}},{_num(exit_at)});'
            )
            tweens.append(
                f'tl.fromTo("#{lid}-s",{{opacity:1}},{{opacity:0,'
                f'duration:{_num(exit_dur)},ease:"power3.in",'
                f'immediateRender:false}},{_num(exit_at)});'
            )
            tweens.append(
                f'tl.fromTo("#{lid}-g",{{opacity:0}},{{opacity:0.8,'
                f'duration:{_num(exit_dur)},ease:"power3.in",'
                f'immediateRender:false}},{_num(exit_at)});'
            )
        tweens.append(f'tl.set("#{lid}-s",{{opacity:0}},{_num(end)});')
        tweens.append(f'tl.set("#{lid}-g",{{opacity:0}},{_num(end)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<div id="{node_id}-inner" class="lbls-stack" '
               f'style="font-size:{size}px;gap:{gap}px">{"".join(rows)}</div></div>'],
        tweens=tweens)


def fs_stack_lines(ctx: "TemplateCtx") -> Piece:
    """Три строки лесенкой: слова пакуются в max_lines и входят rise."""
    content, accent, invert = _content_of(ctx)
    if not content:
        return Piece()
    words = content.split()
    max_lines = max(1, int(ctx.params.get("max_lines") or 3))
    per = max(1, (len(words) + max_lines - 1) // max_lines)
    lines = [" ".join(words[i:i + per]) for i in range(0, len(words), per)][:max_lines]
    node_id = ctx.target
    size = _fs_size(ctx, max(lines, key=len))
    cls = "clip fullscreen-text fs-stack" + (" invert" if invert else "")
    rows, tweens = [], []
    for i, line in enumerate(lines):
        rows.append(f'<span class="fs-line">{_mark_accent(line, accent)}</span>')
        tweens += entrance_tweens(f"#{node_id} .fs-line:nth-child({i + 1})",
                                  _enter_at(ctx), name="rise", delay=0.07 * i)
    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span id="{node_id}-inner" class="fs-lines" '
               f'style="font-size:{size}px">{"".join(rows)}</span></div>'],
        tweens=tweens)


def fs_vs_compare(ctx: "TemplateCtx") -> Piece:
    content, accent, invert = _content_of(ctx)
    parts = re.split(r"\s+(?:VS|vs|Vs)\s+", content)
    if len(parts) != 2:
        parts = content.split(None, 1)
    if len(parts) != 2:
        return fs_plain(ctx)
    node_id = ctx.target
    size = _fs_size(ctx, max(parts, key=len))
    cls = "clip fullscreen-text fs-vs" + (" invert" if invert else "")
    tweens = entrance_tweens(f"#{node_id} .fs-vs-a", _enter_at(ctx), name="rise")
    tweens += entrance_tweens(f"#{node_id} .fs-vs-b", _enter_at(ctx), name="rise",
                              delay=0.1)
    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span id="{node_id}-inner" class="fs-vs-row" '
               f'style="font-size:{size}px">'
               f'<span class="fs-vs-a">{_mark_accent(parts[0], accent)}</span>'
               f'<span class="fs-vs-mid">VS</span>'
               f'<span class="fs-vs-b">{_mark_accent(parts[1], accent)}</span>'
               f'</span></div>'],
        tweens=tweens)


def fs_strip(ctx: "TemplateCtx") -> Piece:
    content, accent, invert = _content_of(ctx)
    if not content:
        return Piece()
    node_id = ctx.target
    size = min(_fs_size(ctx, content), 180)
    height = int(ctx.params.get("strip_height") or 220)
    cls = "clip fullscreen-text fs-strip" + (" invert" if invert else "")
    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span id="{node_id}-inner" class="fs-band" '
               f'style="height:{height}px;font-size:{size}px">'
               f'{_mark_accent(content, accent)}</span></div>'],
        tweens=enter_and_drift(f"#{node_id}-inner", _enter_at(ctx), _hold(ctx),
                               name="rise"))


# Kinetic Type Swap: префикс и суффикс стоят, в маске катится слот.
# Каталог тянет yPercent/cqw; здесь px и fit_size. IN 2.25 сжимается вместе
# с OUT, если кадр короче базы. HOLD — остаток. Слот шириной в самое длинное
# слово, покадровая перекладка предложения запрещена.
_KTS_IN_BASE = 2.25
_KTS_OUT_BASE = 0.45
_KTS_ARRIVAL = 0.3
_KTS_SWAP_START = 0.48
_KTS_ROLL = 0.46
_KTS_SETTLE = 0.18
_KTS_TRAVEL_EM = 1.12
_KTS_GAP_EM = 0.26
_KTS_EXIT_Y = 58


def _kts_sentence(params: dict[str, Any]) -> tuple[str, list[str], str]:
    """Префикс, варианты слота, суффикс. Явные params важнее content.

    Пайп: ``ПИШИ|КОД|HTML|CSS`` — первое слово стоит, остальные катятся.
    ``ПИШИ|КОД,HTML,CSS|сейчас`` — суффикс после списка через запятую.
    Без пайпа все слова катятся в слоте: так P11 не ломает обычную фразу.
    """
    prefix = str(params.get("prefix") or "").strip()
    suffix = str(params.get("suffix") or "").strip()
    raw = params.get("options")
    options: list[str] = []
    if isinstance(raw, (list, tuple)):
        options = [str(part).strip() for part in raw if str(part).strip()]
    elif raw is not None and str(raw).strip():
        options = [part.strip() for part in str(raw).split(",") if part.strip()]

    content = str(params.get("content") or "").strip()
    if options:
        return prefix, options, suffix
    if not content:
        return prefix, [], suffix

    if "|" in content:
        chunks = [part.strip() for part in content.split("|")]
        rest = chunks
        if not prefix:
            prefix = chunks[0]
            rest = chunks[1:]
        if len(rest) == 2 and "," in rest[0]:
            options = [part.strip() for part in rest[0].split(",") if part.strip()]
            if not suffix:
                suffix = rest[1]
        elif len(rest) == 1 and "," in rest[0]:
            options = [part.strip() for part in rest[0].split(",") if part.strip()]
        else:
            options = [part for part in rest if part]
        return prefix, options, suffix

    if "," in content:
        return prefix, [part.strip() for part in content.split(",") if part.strip()], suffix
    return prefix, content.split(), suffix


def _kts_cues(params: dict[str, Any]) -> list[float]:
    raw = params.get("cues")
    tokens: list[str]
    if isinstance(raw, (list, tuple)):
        tokens = [str(item).strip() for item in raw]
    else:
        tokens = str(raw or "").split(",")
    cues: list[float] = []
    for token in tokens:
        if not token:
            continue
        try:
            seconds = float(token)
        except (TypeError, ValueError):
            continue
        if seconds >= 0 and seconds == seconds:  # not NaN
            cues.append(seconds)
    cues.sort()
    return cues


def _kts_fit(prefix: str, options: list[str], suffix: str,
             available: float, ceiling: int) -> tuple[int, int]:
    """Кегль и ширина слота: слот = самое широкое слово, предложение не живёт."""

    def measure(size: int) -> tuple[float, int]:
        widest = max(text_width(word, size) for word in options)
        gap = _KTS_GAP_EM * size
        total = widest
        if prefix:
            total += text_width(prefix, size) + gap
        if suffix:
            total += text_width(suffix, size) + gap
        return total, max(1, int(round(widest)))

    width, slot = measure(ceiling)
    if width <= available:
        return ceiling, slot
    size = max(24, int(ceiling * available / width))
    _, slot = measure(size)
    return size, slot


def fs_kinetic_type_swap(ctx: "TemplateCtx") -> Piece:
    """Держится фраза, в маске катится слово — kinetic-type-swap.

    Каталог: ``yPercent``, ``cqw`` и ``color-mix``. Движок этого не умеет:
    ход в пикселях (1.12 кегля), кегль через ``fit_size``, слот — статическая
    маска ``overflow:hidden`` шириной в самое длинное слово. Зелёный/синий/
    фиолетовый слота → ``accent``. Префикс и суффикс — ``ink``. Жёлтого нет.
    Твины на сцене и словах, не на ``.clip``.
    """
    prefix, options, suffix = _kts_sentence(ctx.params)
    if not options:
        return fs_plain(ctx) if str(ctx.params.get("content") or "").strip() else Piece()
    invert = bool(ctx.params.get("invert"))
    exit_mode = str(ctx.params.get("exit") or "none").lower()
    if exit_mode not in ("none", "fade", "up"):
        exit_mode = "none"
    node_id = ctx.target
    available = float(ctx.params.get("available_px") or 900)
    size, slot_w = _kts_fit(prefix, options, suffix, available, _fs_ceiling(ctx))
    travel = round(_KTS_TRAVEL_EM * size, 2)
    t0 = _enter_at(ctx)
    end = ctx.start + ctx.duration
    duration = max(0.001, end - t0)
    out_base = 0.0 if exit_mode == "none" else _KTS_OUT_BASE
    total_base = max(0.001, _KTS_IN_BASE + out_base)
    scale = duration / total_base if duration < total_base else 1.0
    arrival = _KTS_ARRIVAL * scale
    inn = _KTS_IN_BASE * scale
    out = out_base * scale
    swap_start = _KTS_SWAP_START * scale
    roll = _KTS_ROLL * scale
    settle = _KTS_SETTLE * scale
    enter_delay = float(ctx.params.get("enter_delay") or 0)
    cues = [max(0.0, cue - enter_delay) for cue in _kts_cues(ctx.params)]

    swap_count = len(options) - 1
    swap_times: list[float] = []
    roll_duration = roll
    if swap_count > 0:
        if cues:
            last_cue = cues[-1]
            cue_gap = (max(0.05, (last_cue - cues[0]) / (len(cues) - 1))
                       if len(cues) >= 2 else roll)
            latest_swap = max(0.0, duration - out - roll - settle)
            for index in range(swap_count):
                cue_at = (cues[index] if index < len(cues)
                          else last_cue + (index - (len(cues) - 1)) * cue_gap)
                swap_times.append(min(latest_swap, max(0.0, cue_at)))
            gaps = [swap_times[i] - swap_times[i - 1]
                    for i in range(1, len(swap_times))]
            if gaps:
                roll_duration = min(roll, max(0.04, min(gaps) * 0.72))
        else:
            last_swap_start = max(swap_start, inn - settle - roll)
            swap_step = (0.0 if swap_count == 1
                         else (last_swap_start - swap_start) / (swap_count - 1))
            roll_duration = (roll if swap_count <= 2
                             else min(roll, max(0.04, swap_step * 0.72)))
            for index in range(1, swap_count + 1):
                swap_times.append(
                    last_swap_start if swap_count == 1
                    else swap_start + (index - 1) * swap_step)
    swaps_end = (swap_times[-1] + roll_duration + settle if swap_times else inn)
    hold_start = min(max(0.0, duration - out), max(inn, swaps_end))
    hold = max(0.0, duration - (hold_start + out))
    out_at = t0 + hold_start + hold

    cls = "clip fullscreen-text fs-kts" + (" invert" if invert else "")
    prefix_html = f'<span class="kts-prefix">{_esc(prefix)}</span>'
    suffix_html = f'<span class="kts-suffix">{_esc(suffix)}</span>'
    words_html: list[str] = []
    tweens: list[str] = [
        f'tl.fromTo("#{node_id}-stage",{{opacity:0}},{{opacity:1,'
        f'duration:{_num(arrival)},ease:"power2.out"}},{_num(t0)});'
    ]
    for index, option in enumerate(options):
        wid = f"{node_id}-w{index}"
        words_html.append(
            f'<span id="{wid}" class="kts-word">{_esc(option)}</span>')
        if index == 0:
            tweens.append(
                f'tl.set("#{wid}",{{y:0,opacity:1}},{_num(t0)});')
        else:
            tweens.append(
                f'tl.set("#{wid}",{{y:{_num(travel)},opacity:0}},{_num(t0)});')

    for swap_index, local_at in enumerate(swap_times):
        outgoing = f"{node_id}-w{swap_index}"
        incoming = f"{node_id}-w{swap_index + 1}"
        word_index = swap_index + 1
        incoming_ease = "back.out(1.7)" if word_index == len(options) - 1 else "power4.out"
        out_dur = roll_duration * 0.55
        in_dur = roll_duration * 0.55
        swap_at = t0 + local_at
        in_start = swap_at + roll_duration - in_dur
        tweens.append(
            f'tl.fromTo("#{outgoing}",{{y:0}},{{y:{_num(-travel)},'
            f'duration:{_num(out_dur)},ease:"power4.in",immediateRender:false}},'
            f'{_num(swap_at)});')
        tweens.append(
            f'tl.set("#{outgoing}",{{opacity:0}},{_num(swap_at + out_dur)});')
        tweens.append(
            f'tl.fromTo("#{incoming}",{{y:{_num(travel)},opacity:0}},'
            f'{{y:0,opacity:1,duration:{_num(in_dur)},ease:"{incoming_ease}",'
            f'immediateRender:false}},{_num(in_start)});')

    if exit_mode == "fade" and out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-stage",{{opacity:1}},{{opacity:0,'
            f'duration:{_num(out)},ease:"power2.in",immediateRender:false}},'
            f'{_num(out_at)});')
    elif exit_mode == "up" and out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-stage",{{opacity:1,y:0}},'
            f'{{opacity:0,y:{_num(-_KTS_EXIT_Y)},duration:{_num(out)},'
            f'ease:"power2.in",immediateRender:false}},{_num(out_at)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<div id="{node_id}-stage" class="kts-stage">'
               f'<div class="kts-sentence" style="font-size:{size}px">'
               f'{prefix_html}'
               f'<span class="kts-slot" style="width:{slot_w}px;height:{size}px">'
               f'{"".join(words_html)}</span>'
               f'{suffix_html}'
               f'</div></div></div>'],
        tweens=tweens)


def fs_word_swap(ctx: "TemplateCtx") -> Piece:
    """Слова сменяются на месте заранее выписанными кадрами, не таймером."""
    content, accent, invert = _content_of(ctx)
    words = content.split()
    if len(words) < 2:
        return fs_plain(ctx)
    node_id = ctx.target
    size = _fs_size(ctx, max(words, key=len))
    cls = "clip fullscreen-text fs-swap" + (" invert" if invert else "")
    per = _hold(ctx) * 0.82 / len(words)
    spans, tweens = [], []
    at0 = _enter_at(ctx)
    for i, word in enumerate(words):
        spans.append(f'<span class="fs-swap-word">'
                     f'{_mark_accent(word, accent)}</span>')
        at = at0 + per * i
        tweens.append(
            f'tl.set("#{node_id} .fs-swap-word:nth-child({i + 1})",'
            f'{{opacity:1}},{_num(at)});')
        if i < len(words) - 1:
            tweens.append(
                f'tl.set("#{node_id} .fs-swap-word:nth-child({i + 1})",'
                f'{{opacity:0}},{_num(at + per)});')
    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span id="{node_id}-inner" class="fs-swap-box" '
               f'style="font-size:{size}px">{"".join(spans)}</span></div>'],
        tweens=tweens)


def fs_fact_card(ctx: "TemplateCtx") -> Piece:
    content, accent, invert = _content_of(ctx)
    if not content:
        return Piece()
    node_id = ctx.target
    size = min(_fs_size(ctx, content), 160)
    cls = "clip fullscreen-text fs-card" + (" invert" if invert else "")
    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<span id="{node_id}-inner" class="fs-fact" '
               f'style="font-size:{size}px">{_mark_accent(content, accent)}'
               f'</span></div>'],
        tweens=enter_and_drift(f"#{node_id}-inner", _enter_at(ctx), _hold(ctx),
                               name="zoom-out"))


# Logo Brand Close: вордмарк каскадом, акцентная точка, слоган и URL.
# Каталог мерит getBoundingClientRect и твинит cqw/em; здесь px и fit_size.
# HOLD без дрейфа. Точка — единственный accent. Это не кнопка подписки.
_LBC_IN_BASE = 2.6
_LBC_OUT_BASE = 0.5
_LBC_LETTER = 1.15
_LBC_STAGGER_AMOUNT = 0.7
_LBC_MARK_SCALE = 2.4
_LBC_PERIOD_AT = 0.95
_LBC_PERIOD_DUR = 0.9
_LBC_TAG_AT = 1.35
_LBC_TAG_DUR = 0.9
_LBC_URL_AT = 1.7
_LBC_URL_DUR = 0.85
_LBC_LETTER_Y_EM = 0.62
_LBC_PERIOD_Y_EM = 0.08
_LBC_TAG_Y_EM = 0.9
_LBC_URL_SCALEX = 1.06
_LBC_MARK_FROM = 1.04
_LBC_CEILING = 768
_LBC_WIDTH = 760
_LBC_EXIT_Y = 48
_LBC_DEFAULT_MARK = "РЕДШИФТ"
_LBC_DEFAULT_TAG = "Пиши код. Шли на орбиту."
_LBC_DEFAULT_URL = "redshift.shorts"


def _lbc_copy(params: dict[str, Any]) -> tuple[str, str, str]:
    """Вордмарк, слоган, URL. Явный пустой слоган/адрес прячет строку."""
    content = str(params.get("content") or "").strip()
    chunks = [part.strip() for part in content.split("|")] if content else []

    def _field(name: str, fallback: str, index: int) -> str:
        if name in params:
            return str(params.get(name) or "").strip()
        if index < len(chunks):
            return chunks[index]
        return fallback

    wordmark = _field("wordmark", "", 0)
    if not wordmark:
        wordmark = _LBC_DEFAULT_MARK
    # Одна колонка без пайпа — это вордмарк, слоган и адрес остаются дефолтом.
    if content and "|" not in content:
        tagline = (_field("tagline", _LBC_DEFAULT_TAG, 1)
                   if "tagline" in params else _LBC_DEFAULT_TAG)
        url = (_field("url", _LBC_DEFAULT_URL, 2)
               if "url" in params else _LBC_DEFAULT_URL)
        return wordmark, tagline, url
    tagline = _field("tagline", _LBC_DEFAULT_TAG if not chunks else "", 1)
    url = _field("url", _LBC_DEFAULT_URL if not chunks else "", 2)
    return wordmark, tagline, url


def _lbc_body_and_dot(wordmark: str) -> tuple[str, str]:
    text = str(wordmark or "").strip() or _LBC_DEFAULT_MARK
    if text.endswith("."):
        return text[:-1], "."
    return text, "."


def fs_logo_brand_close(ctx: "TemplateCtx") -> Piece:
    """Вордмарк каскадом, точка accent, слоган и URL — logo-brand-close.

    Каталог: ``cqw``/``em`` в твинах и ``getBoundingClientRect`` под кегль.
    Движок этого не умеет: ход в пикселях, кегль через ``fit_size``.
    Inter/крем/зелёная точка → Oswald, ``ink`` на ``bg_pure``, точка ``accent``.
    HOLD стоит. Твины на сцене, не на ``.clip``. Это не CTA-кнопка.
    """
    wordmark, tagline, url = _lbc_copy(ctx.params)
    invert = bool(ctx.params.get("invert"))
    if str(ctx.params.get("tone") or "").lower() == "paper":
        invert = True
    exit_mode = str(ctx.params.get("exit") or "none").lower()
    if exit_mode not in ("none", "fade", "up"):
        exit_mode = "none"
    body, dot = _lbc_body_and_dot(wordmark)
    node_id = ctx.target
    available = float(ctx.params.get("available_px") or _LBC_WIDTH)
    size = fit_size(body + dot, available, _LBC_CEILING)
    letter_y = round(_LBC_LETTER_Y_EM * size, 2)
    period_y = round(_LBC_PERIOD_Y_EM * size, 2)
    tag_size = max(28, min(48, int(round(size * 0.22))))
    url_size = max(18, min(26, int(round(size * 0.11))))
    if url:
        tracking = 0.28 * max(0, len(url) - 1) * url_size
        url_w = text_width(url, url_size) + tracking
        if url_w > available:
            url_size = max(16, int(url_size * available / url_w))
    tag_y = round(_LBC_TAG_Y_EM * tag_size, 2)
    gap = max(16, int(round(0.18 * size)))

    t0 = _enter_at(ctx)
    end = ctx.start + ctx.duration
    duration = max(0.001, end - t0)
    out_base = 0.0 if exit_mode == "none" else _LBC_OUT_BASE
    total_base = max(0.001, _LBC_IN_BASE + out_base)
    scale = duration / total_base if duration < total_base else 1.0
    letter_dur = _LBC_LETTER * scale
    stagger_amount = _LBC_STAGGER_AMOUNT * scale
    mark_dur = _LBC_MARK_SCALE * scale
    period_at = t0 + _LBC_PERIOD_AT * scale
    period_dur = _LBC_PERIOD_DUR * scale
    tag_at = t0 + _LBC_TAG_AT * scale
    tag_dur = _LBC_TAG_DUR * scale
    url_at = t0 + _LBC_URL_AT * scale
    url_dur = _LBC_URL_DUR * scale
    inn = _LBC_IN_BASE * scale
    out = out_base * scale
    out_at = t0 + max(inn, duration - out)

    glyphs = list(body)
    n_letters = sum(1 for ch in glyphs if not ch.isspace())
    letter_delay = stagger_amount / max(1, n_letters - 1) if n_letters > 1 else 0.0

    cls = "clip fullscreen-text fs-lbc" + (" invert" if invert else "")
    chars: list[str] = []
    tweens: list[str] = [
        f'tl.fromTo("#{node_id}-mark",{{scale:{_num(_LBC_MARK_FROM)}}},'
        f'{{scale:1,duration:{_num(mark_dur)},ease:"expo.out"}},{_num(t0)});'
    ]
    step = 0
    for i, ch in enumerate(glyphs):
        if ch.isspace():
            chars.append(f'<span class="lbc-space" aria-hidden="true"></span>')
            continue
        cid = f"{node_id}-c{i}"
        chars.append(f'<span id="{cid}" class="lbc-ch">{_esc(ch)}</span>')
        letter_at = t0 + letter_delay * step
        tweens.append(
            f'tl.fromTo("#{cid}",{{opacity:0,y:{_num(letter_y)}}},'
            f'{{opacity:1,y:0,duration:{_num(letter_dur)},ease:"expo.out"}},{_num(letter_at)});'
        )
        step += 1
    chars.append(f'<span id="{node_id}-dot" class="lbc-dot">{_esc(dot)}</span>')
    tweens.append(
        f'tl.fromTo("#{node_id}-dot",{{opacity:0,scale:0.2,y:{_num(period_y)}}},'
        f'{{opacity:1,scale:1,y:0,duration:{_num(period_dur)},'
        f'ease:"back.out(1.8)"}},{_num(period_at)});'
    )

    extras: list[str] = []
    if tagline:
        extras.append(
            f'<span id="{node_id}-tag" class="lbc-tag" '
            f'style="font-size:{tag_size}px">{_esc(tagline)}</span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-tag",{{opacity:0,y:{_num(tag_y)}}},'
            f'{{opacity:1,y:0,duration:{_num(tag_dur)},ease:"power3.out"}},'
            f'{_num(tag_at)});'
        )
    if url:
        extras.append(
            f'<span id="{node_id}-url" class="lbc-url" '
            f'style="font-size:{url_size}px">{_esc(url)}</span>')
        tweens.append(
            f'tl.fromTo("#{node_id}-url",{{opacity:0,scaleX:{_num(_LBC_URL_SCALEX)}}},'
            f'{{opacity:1,scaleX:1,duration:{_num(url_dur)},ease:"power2.out"}},'
            f'{_num(url_at)});'
        )

    if exit_mode == "fade" and out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-lock",{{opacity:1}},{{opacity:0,'
            f'duration:{_num(out)},ease:"power2.in",immediateRender:false}},'
            f'{_num(out_at)});')
    elif exit_mode == "up" and out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-lock",{{opacity:1,y:0}},'
            f'{{opacity:0,y:{_num(-_LBC_EXIT_Y)},duration:{_num(out)},'
            f'ease:"power2.in",immediateRender:false}},{_num(out_at)});')

    extras_html = "".join(extras)
    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<div id="{node_id}-lock" class="lbc-lock" style="gap:{gap}px">'
               f'<div id="{node_id}-mark" class="lbc-mark" '
               f'style="font-size:{size}px">{"".join(chars)}</div>'
               f'{extras_html}</div></div>'],
        tweens=tweens)


# Particle Text Dissolve: каталог семплирует bitmap на canvas и твинит
# clip-path + onUpdate. Движок этого не умеет: wipe — SVG-mask, scaleX на
# rect (как caption-clip-wipe), пыль — span с x/y. LCG в Python.
# Зелёный/синий/фиолетовый → ink, одно слово accent. HOLD без дрейфа.
_PTD_IN_BASE = 2.8
_PTD_OUT_BASE = 0.45
_PTD_CEILING = 576
_PTD_FRAME_W = 1080
_PTD_FRAME_H = 1920
_PTD_EXIT_Y = 76
_PTD_SEED = 0x9D1550F7
_PTD_DUST = {"low": 1, "med": 2, "high": 3}
_PTD_DUST_CAP = {"low": 24, "med": 36, "high": 48}


class _PtdRng:
    """LCG каталога (seed 0x9d1550f7): один прогон — одна таблица пыли."""

    __slots__ = ("state",)

    def __init__(self, seed: int = _PTD_SEED) -> None:
        self.state = seed & 0xFFFFFFFF

    def __call__(self) -> float:
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        return self.state / 4294967296.0


def fs_particle_text_dissolve(ctx: "TemplateCtx") -> Piece:
    """Строка собирается из облака пыли (или растворяется в него).

    Каталог: ``getImageData``, ``onUpdate`` на canvas, твин ``clip-path``.
    Здесь фронт — SVG-mask, ``scaleX`` на rect, пыль — span с заранее
    посчитанным ``x``/``y``. Inter/зелёный → Oswald, ``ink`` на ``bg_pure``,
    одно слово ``accent``. Твины на сцене, не на ``.clip``. HOLD стоит.
    """
    content = str(ctx.params.get("text") or ctx.params.get("content") or "").strip()
    accent = str(ctx.params.get("accent_word") or "").strip()
    invert = bool(ctx.params.get("invert"))
    if str(ctx.params.get("tone") or "").lower() == "paper":
        invert = True
    if not content:
        return Piece()
    direction = str(ctx.params.get("direction") or "in").lower()
    if direction not in ("in", "out"):
        direction = "in"
    density = str(ctx.params.get("density") or "med").lower()
    if density not in _PTD_DUST:
        density = "med"
    exit_mode = str(ctx.params.get("exit") or "none").lower()
    if exit_mode not in ("none", "fade", "up"):
        exit_mode = "none"

    visual = content.upper()
    node_id = ctx.target
    available = float(ctx.params.get("available_px") or 900)
    size = fit_size(visual, available, _PTD_CEILING)
    frame_w = int(ctx.params.get("frame_w") or _PTD_FRAME_W)
    frame_h = int(ctx.params.get("frame_h") or _PTD_FRAME_H)
    line_w = text_width(visual, size)
    x0 = (frame_w - line_w) / 2.0
    cy = frame_h / 2.0

    accent_range: tuple[int, int] | None = None
    if accent and accent.upper() in visual:
        start = visual.index(accent.upper())
        accent_range = (start, start + len(accent))

    t0 = _enter_at(ctx)
    end = ctx.start + ctx.duration
    duration = max(0.001, end - t0)
    out_base = 0.0 if exit_mode == "none" else _PTD_OUT_BASE
    total_base = max(0.001, _PTD_IN_BASE + out_base)
    scale = duration / total_base if duration < total_base else 1.0
    inn = _PTD_IN_BASE * scale
    out = out_base * scale
    out_at = t0 + max(inn, duration - out)
    wipe_at = t0 + inn * 0.18
    wipe_dur = inn * 0.76

    letters: list[str] = []
    dust: list[str] = []
    tweens: list[str] = []
    rng = _PtdRng()
    glyphs = [(i, ch) for i, ch in enumerate(visual) if not ch.isspace()]
    n_glyphs = len(glyphs)
    per = _PTD_DUST[density]
    cap = _PTD_DUST_CAP[density]
    if n_glyphs * per > cap:
        per = max(1, cap // max(1, n_glyphs))

    prefix = 0.0
    glyph_i = 0
    for i, ch in enumerate(visual):
        wide = text_width(ch if not ch.isspace() else " ", size)
        if ch.isspace():
            letters.append(f'<tspan class="ptd-space">{_esc(ch)}</tspan>')
            prefix += wide or 0.28 * size
            continue
        marked = ""
        if accent_range and accent_range[0] <= i < accent_range[1]:
            marked = " accent"
        letters.append(f'<tspan class="ptd-ch{marked}">{_esc(ch)}</tspan>')
        cx = x0 + prefix + wide / 2.0
        prefix += wide
        key = glyph_i / max(1, n_glyphs - 1)
        glyph_i += 1
        for d in range(per):
            at = min(0.9, 0.2 + 0.62 * key + 0.05 * rng())
            travel = 0.18 + 0.1 * rng()
            fade = 0.05 + 0.04 * rng()
            angle = rng() * math.pi * 2
            offset = (0.1 + 0.22 * rng()) * min(frame_w, frame_h)
            ox = math.cos(angle)
            oy = math.sin(angle)
            radius = max(3, int(round((0.26 + 0.5 * rng()) * 8)))
            did = f"{node_id}-d{i}-{d}"
            acc = " accent" if marked else ""
            dust.append(
                f'<span id="{did}" class="ptd-dot{acc}" style="'
                f'left:{_num(cx - radius)}px;top:{_num(cy - radius)}px;'
                f'width:{radius * 2}px;height:{radius * 2}px"></span>'
            )
            scatter_x = round(ox * offset, 2)
            scatter_y = round(oy * offset, 2)
            birth_p = max(0.0, at - travel)
            birth = t0 + birth_p * inn
            settle = t0 + at * inn
            move_s = max(0.001, settle - birth)
            fade_s = max(0.04, fade * inn)
            if direction == "in":
                tweens.append(
                    f'tl.fromTo("#{did}",{{x:{_num(scatter_x)},y:{_num(scatter_y)},'
                    f'opacity:0}},{{x:0,y:0,opacity:0.82,duration:{_num(move_s)},'
                    f'ease:"power3.out"}},{_num(birth)});'
                )
                # Стык в одной точке lint считает перекрытием opacity.
                tweens.append(
                    f'tl.fromTo("#{did}",{{opacity:0.82}},{{opacity:0,'
                    f'duration:{_num(fade_s)},ease:"power2.in",'
                    f'immediateRender:false}},{_num(settle + 0.001)});'
                )
            else:
                tweens.append(
                    f'tl.fromTo("#{did}",{{x:0,y:0,opacity:0.82}},'
                    f'{{x:{_num(scatter_x)},y:{_num(scatter_y)},opacity:0,'
                    f'duration:{_num(max(0.04, travel * inn))},ease:"power3.in",'
                    f'immediateRender:false}},{_num(settle)});'
                )

    going_in = direction == "in"
    wipe_from, wipe_to = ("0", "1") if going_in else ("1", "0")
    tweens.append(
        f'tl.fromTo("#{node_id}-wipe",{{scaleX:{wipe_from}}},{{scaleX:{wipe_to},'
        f'duration:{_num(wipe_dur)},ease:"power1.inOut"}},{_num(wipe_at)});'
    )

    if exit_mode == "fade" and out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-stage",{{opacity:1}},{{opacity:0,'
            f'duration:{_num(out)},ease:"power2.in",immediateRender:false}},'
            f'{_num(out_at)});')
    elif exit_mode == "up" and out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-stage",{{opacity:1,y:0}},'
            f'{{opacity:0,y:{_num(-_PTD_EXIT_Y)},duration:{_num(out)},'
            f'ease:"power2.in",immediateRender:false}},{_num(out_at)});')

    cls = ("clip fullscreen-text fs-ptd ptd-" + direction
           + (" invert" if invert else ""))
    box_h = max(8, int(round(size * 1.12)))
    svg_w = max(8, int(math.ceil(line_w)))
    baseline = size * 0.82
    return Piece(
        nodes=[f'<div id="{node_id}" class="{cls}" {_timing(ctx)}>'
               f'<div id="{node_id}-stage" class="ptd-stage">'
               f'<div class="ptd-dust">{"".join(dust)}</div>'
               f'<div id="{node_id}-line" class="ptd-line">'
               f'<svg class="ptd-svg" width="{svg_w}" height="{box_h}" '
               f'viewBox="0 0 {svg_w} {box_h}" aria-hidden="true">'
               f'<defs><mask id="{node_id}-m" maskUnits="userSpaceOnUse" '
               f'maskContentUnits="userSpaceOnUse">'
               f'<rect id="{node_id}-wipe" class="ptd-wipe" x="0" y="0" '
               f'width="{svg_w}" height="{box_h}" fill="#fff"/></mask></defs>'
               f'<text id="{node_id}-ink" class="ptd-ink" mask="url(#{node_id}-m)" '
               f'x="0" y="{_num(baseline)}" font-size="{_num(size)}px" '
               f'xml:space="preserve">{"".join(letters)}</text></svg>'
               f'</div></div></div>'],
        tweens=tweens)


# Scan Band: каталог твинит --sb-band-position и clip-path. Движок этого не
# умеет — полоса с overflow:hidden едет x, мир внутри на -x.
# Inter, #0b0c0e/#f7f8fa и RGB-сдвиг #ff3158/#36efff как в каталоге:
# это сам жест, не чужой бренд-токен.
_SB_IN_BASE = 0.45
_SB_OUT_BASE = 0.45
_SB_SWEEP_BASE = 1.65
_SB_HALF_PCT = 6.0
_SB_POS0_PCT = -60.0
_SB_POS1_PCT = 160.0
_SB_FRAME_W = 1080
_SB_FRAME_H = 1920
_SB_ANGLE_DEFAULT = 12.0


def fs_scan_band(ctx: "TemplateCtx") -> Piece:
    """Диагональная полоса один раз проходит по вордмарку — scan-band.

    Внутри полосы три клипа: красный и циан со сдвигом, ядро чуть правее.
    Снаружи слово чистое. Каталог тянет CSS-var на ``clip-path``; здесь
    окно ``overflow:hidden`` и ``x``, наклон — статический ``skewX`` на
    обёртке, которую твин не трогает. Цвета и Inter каталога не трогаются.
    """
    content, _accent, _invert = _content_of(ctx)
    if not content:
        return Piece()
    node_id = ctx.target
    try:
        angle = float(ctx.params.get("band_angle", _SB_ANGLE_DEFAULT))
    except (TypeError, ValueError):
        angle = _SB_ANGLE_DEFAULT
    if not math.isfinite(angle):
        angle = _SB_ANGLE_DEFAULT
    angle = max(-30.0, min(30.0, angle))
    frame_w = int(ctx.params.get("frame_w") or _SB_FRAME_W)
    frame_h = int(ctx.params.get("frame_h") or _SB_FRAME_H)
    band_w = round(_SB_HALF_PCT / 50.0 * frame_w)
    # Полоса должна иметь paint-box на старте, иначе продюсер её выкидывает.
    x0 = 0
    x1 = frame_w
    size = max(28, min(150, round(0.13 * frame_w)))
    red_x = round(-0.008 * frame_w, 2)
    cyan_x = round(0.017 * frame_w, 2)
    core_x = round(0.0065 * frame_w, 2)

    at = _enter_at(ctx)
    end = ctx.start + ctx.duration
    dur = max(0.001, end - at)
    fixed = _SB_IN_BASE + _SB_OUT_BASE
    scale = dur / fixed if dur < fixed else 1.0
    inn = _SB_IN_BASE * scale
    out = _SB_OUT_BASE * scale
    hold = max(0.0, dur - inn - out)
    sweep = min(_SB_SWEEP_BASE, hold)
    out_at = at + inn + hold
    if out > 0 and out_at <= at + inn:
        out_at = at + inn + 0.001

    label = _esc(content)
    tweens = [
        f'tl.fromTo("#{node_id}-stage",{{opacity:0}},{{opacity:1,'
        f'duration:{_num(inn)},ease:"power2.out"}},{_num(at)});'
    ]
    if sweep > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-band",{{x:{_num(x0)}}},{{x:{_num(x1)},'
            f'duration:{_num(sweep)},ease:"power2.out"}},{_num(at + inn)});'
        )
        tweens.append(
            f'tl.fromTo("#{node_id}-inner",{{x:{_num(-x0)}}},{{x:{_num(-x1)},'
            f'duration:{_num(sweep)},ease:"power2.out"}},{_num(at + inn)});'
        )
    if out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-stage",{{opacity:1}},{{opacity:0,'
            f'duration:{_num(out)},ease:"power2.in",immediateRender:false}},'
            f'{_num(out_at)});'
        )
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text fs-scan-band" '
               f'{_timing(ctx)}>'
               f'<div id="{node_id}-stage" class="sb-stage" role="img" '
               f'aria-label="{label}">'
               f'<span class="sb-wordmark" style="font-size:{size}px">{label}</span>'
               f'<div class="sb-skew" style="transform:skewX({_num(-angle)}deg);'
               f'transform-origin:0 0">'
               f'<div id="{node_id}-band" class="sb-band" '
               f'style="width:{band_w}px;height:{frame_h}px" '
               f'data-band-angle="{_num(angle)}" data-layout-allow-overflow="true">'
               f'<div class="sb-unskew" style="transform:skewX({_num(angle)}deg);'
               f'transform-origin:0 0;width:{frame_w}px;height:{frame_h}px">'
               f'<div id="{node_id}-inner" class="sb-inner" '
               f'style="width:{frame_w}px;height:{frame_h}px">'
               f'<span class="sb-clone sb-clone-red" style="font-size:{size}px;'
               f'transform:translateX({_num(red_x)}px)">{label}</span>'
               f'<span class="sb-clone sb-clone-cyan" style="font-size:{size}px;'
               f'transform:translateX({_num(cyan_x)}px)">{label}</span>'
               f'<span class="sb-clone sb-clone-core" style="font-size:{size}px;'
               f'transform:translateX({_num(core_x)}px)">{label}</span>'
               f'</div></div></div></div></div></div>'],
        tweens=tweens)


# Scramble Reveal: каталог пишет textContent из LCG-таблицы на каждом кадре.
# Движок не твинит textContent — таблица считается в Python (seed 0x27c0ffee),
# строки заранее в DOM, показ — opacity. cqw/cqh → px. Зелёный/синий/фиолет
# каталога остаются: это терминальный жест, не палитра канала.
_SR_IN_BASE = 1.65
_SR_OUT_BASE = 0.45
_SR_ARRIVAL_BASE = 0.42
_SR_LOCK_TAIL_BASE = 0.15
_SR_STILLNESS = 0.3
_SR_FPS = 30
_SR_FRAME_W = 1080
_SR_FRAME_H = 1920
_SR_SEED = 0x27C0FFEE
_SR_GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#$%&*+?<>"
_SR_ACCENTS = ("green", "blue", "violet")


def _js_round(value: float) -> int:
    """Math.round для неотрицательных: 0.5 вверх, не банковское Python."""
    return int(math.floor(float(value) + 0.5))


def _sr_frame_table(text: str, last_frame: int, scale: float = 1.0) -> list[str]:
    """Кадры каталога: LCG 0x27c0ffee, лок слева направо."""
    characters = list(text)
    last_frame = max(1, int(last_frame))
    first_lock = min(last_frame, max(1, _js_round(0.2 * _SR_FPS * scale)))
    n = len(characters)
    lock_at: list[int] = []
    for i, ch in enumerate(characters):
        if ch.isspace():
            lock_at.append(0)
            continue
        position = 1.0 if n <= 1 else i / (n - 1)
        lock_at.append(_js_round(first_lock + position * (last_frame - first_lock)))
    state = _SR_SEED & 0xFFFFFFFF
    glen = len(_SR_GLYPHS)
    rows: list[str] = []
    for frame in range(last_frame + 1):
        out: list[str] = []
        for i, ch in enumerate(characters):
            if ch.isspace() or frame >= lock_at[i]:
                out.append(ch)
                continue
            state = (1664525 * state + 1013904223) & 0xFFFFFFFF
            glyph_index = state % glen
            glyph = _SR_GLYPHS[glyph_index]
            if glyph == ch:
                glyph = _SR_GLYPHS[(glyph_index + 1) % glen]
            out.append(glyph)
        rows.append("".join(out))
    return rows


def fs_scramble_reveal(ctx: "TemplateCtx") -> Piece:
    """Строка собирается из детерминированного шума слева направо.

    Каталог ставит ``textContent`` на каждом кадре. Здесь таблица LCG
    выписана span-ами, показ — ``opacity``. Приход сцены — ``x``/``y``/
    ``opacity`` в px, не ``cqw``. Твины на сцене, не на ``.clip``.
    """
    content = str(ctx.params.get("text") or ctx.params.get("content") or "").strip()
    if not content:
        return Piece()
    accent = str(ctx.params.get("accent") or "green").lower()
    if accent not in _SR_ACCENTS:
        accent = "green"
    style = str(ctx.params.get("style") or "terminal").lower()
    if style != "clean":
        style = "terminal"
    exit_mode = str(ctx.params.get("exit") or "none").lower()
    if exit_mode not in ("none", "fade", "up"):
        exit_mode = "none"

    node_id = ctx.target
    frame_w = int(ctx.params.get("frame_w") or _SR_FRAME_W)
    frame_h = int(ctx.params.get("frame_h") or _SR_FRAME_H)
    fitted = min(11.0, 118.0 / max(1, len(content)))
    size = max(28, min(round(fitted / 100.0 * frame_w), round(0.24 * frame_h)))
    x0 = round(-0.04 * frame_w, 2)
    y0 = round(0.024 * frame_h, 2)
    drift_y = round(-0.0055 * frame_h, 2)
    exit_x = round(0.05 * frame_w, 2)
    exit_y = round(-0.035 * frame_h, 2)

    at = _enter_at(ctx)
    end = ctx.start + ctx.duration
    dur = max(0.001, end - at)
    out_base = 0.0 if exit_mode == "none" else _SR_OUT_BASE
    total_base = max(0.001, _SR_IN_BASE + out_base)
    scale = dur / total_base if dur < total_base else 1.0
    inn = _SR_IN_BASE * scale
    out = out_base * scale
    arrival = _SR_ARRIVAL_BASE * scale
    lock_tail = _SR_LOCK_TAIL_BASE * scale
    hold = max(0.0, dur - inn - out)
    hold_start = at + inn
    out_at = at + inn + hold
    reveal = max(0.0, inn - lock_tail)
    last_frame = max(1, _js_round(reveal * _SR_FPS))
    table = _sr_frame_table(content, last_frame, scale)

    runs: list[tuple[str, int]] = []
    for i, row in enumerate(table):
        if not runs or runs[-1][0] != row:
            runs.append((row, i))

    tweens = [
        f'tl.fromTo("#{node_id}-stage",{{opacity:0}},{{opacity:1,'
        f'duration:{_num(arrival)},ease:"power2.out"}},{_num(at)});',
        f'tl.fromTo("#{node_id}-stage",{{x:{_num(x0)}}},{{x:0,'
        f'duration:{_num(arrival)},ease:"power3.out"}},{_num(at)});',
        f'tl.fromTo("#{node_id}-stage",{{y:{_num(y0)}}},{{y:0,'
        f'duration:{_num(arrival)},ease:"sine.inOut"}},{_num(at)});',
    ]
    prev_id = ""
    for i, (row, frame) in enumerate(runs):
        rid = f"{node_id}-r{i}"
        t = at + frame / _SR_FPS
        tweens.append(f'tl.set("#{rid}",{{opacity:1}},{_num(t)});')
        if prev_id:
            tweens.append(f'tl.set("#{prev_id}",{{opacity:0}},{_num(t)});')
        prev_id = rid

    drift_half = max(0.0, hold - _SR_STILLNESS) / 2.0
    if drift_half > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-stage",{{y:0}},{{y:{_num(drift_y)},'
            f'duration:{_num(drift_half)},ease:"sine.inOut",yoyo:true,'
            f'repeat:1,immediateRender:false}},{_num(hold_start)});'
        )
    if exit_mode == "up" and out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-stage",{{x:0}},{{x:{_num(exit_x)},'
            f'duration:{_num(out)},ease:"power2.in",immediateRender:false}},'
            f'{_num(out_at)});'
        )
        tweens.append(
            f'tl.fromTo("#{node_id}-stage",{{y:0}},{{y:{_num(exit_y)},'
            f'duration:{_num(out)},ease:"sine.inOut",immediateRender:false}},'
            f'{_num(out_at)});'
        )
        tweens.append(
            f'tl.fromTo("#{node_id}-stage",{{opacity:1}},{{opacity:0,'
            f'duration:{_num(out)},ease:"power2.in",immediateRender:false}},'
            f'{_num(out_at)});'
        )
    elif exit_mode == "fade" and out > 0:
        tweens.append(
            f'tl.fromTo("#{node_id}-stage",{{opacity:1}},{{opacity:0,'
            f'duration:{_num(out)},ease:"power2.in",immediateRender:false}},'
            f'{_num(out_at)});'
        )

    label = _esc(content)
    rows_html = []
    for i, (row, _frame) in enumerate(runs):
        on = " sr-row-on" if i == 0 else ""
        rows_html.append(
            f'<span id="{node_id}-r{i}" class="sr-row{on}">{_esc(row)}</span>'
        )
    clean_cls = " sr-clean" if style == "clean" else ""
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip fullscreen-text fs-scramble-reveal '
               f'sr-{accent}{clean_cls}" {_timing(ctx)} '
               f'data-sr-accent="{accent}" data-sr-style="{style}">'
               f'<div id="{node_id}-stage" class="sr-stage" role="img" '
               f'aria-label="{label}">'
               f'<div class="sr-shell">'
               f'<span class="sr-prefix" aria-hidden="true">{_esc(">_")}</span>'
               f'<div class="sr-text" style="font-size:{size}px">'
               f'<span class="sr-sizer">{label}</span>'
               f'{"".join(rows_html)}</div></div></div></div>'],
        tweens=tweens)


# Shared Axis Z: каталог твинит --hf-word-scale и кладёт глубину в CSS-var.
# Движок CSS-var не тянет — стартовый scale считается здесь.
# visual = 1 + (word_scale - 1) * (sign * reach); word_scale едет 0.72 → 1.
_SAZ_SCALE_FROM = 0.72
_SAZ_REACH = {"shallow": 0.5, "standard": 1.0, "deep": 1.85}
_SAZ_SIGN = {"in": 1.0, "out": -1.0}
_SAZ_TONES = ("ink", "paper", "accent")
_SAZ_ENTER = 0.34
_SAZ_STAGGER = 0.06
_SAZ_REF_SIZE = 56.0
_SAZ_GAP_PX = 12.0


def _saz_start_scale(direction: str, depth: str) -> float:
    """Старт scale: 1 + (0.72 - 1) * sign * reach. На покое всегда 1."""
    sign = _SAZ_SIGN.get(direction, 1.0)
    reach = _SAZ_REACH.get(depth, 1.0)
    return 1.0 + (_SAZ_SCALE_FROM - 1.0) * (sign * reach)


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


def fs_shared_axis_z(ctx: "TemplateCtx") -> Piece:
    """Слова набухают по оси Z — shared-axis-z.

    Каталог твинит ``--hf-word-scale`` и пишет глубину в CSS-var. Здесь
    стартовый ``scale`` заранее: ``1 + (0.72-1) * sign * reach``.
    Inter 900 и ``#18181b`` как в каталоге; ``tone=accent`` → ``#C8453D``,
    не изумруд ``#34d399``. Стаггер 60 мс разложен в Python. HOLD без ухода.
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


FULLSCREEN: dict[str, Callable[["TemplateCtx"], Piece]] = {
    "fullscreen_text": fs_plain,
    "kinetic_stack": fs_kinetic_stack,
    "blur_out_up": fs_blur_out_up,
    "bottom_up_letters": fs_bottom_up_letters,
    "kinetic_type_swap": fs_kinetic_type_swap,
    "line_by_line_slide": fs_line_by_line_slide,
    "logo_brand_close": fs_logo_brand_close,
    "particle_text_dissolve": fs_particle_text_dissolve,
    "per_word_crossfade": fs_per_word_crossfade,
    "scan_band": fs_scan_band,
    "scramble_reveal": fs_scramble_reveal,
    "shared_axis_z": fs_shared_axis_z,
    "number_slam": fs_number_slam,
}


def render_fullscreen(ctx: "TemplateCtx") -> Piece:
    """Собрать полноэкранный кадр по renderer и params шаблона."""
    named = str(ctx.params.get("renderer") or "")
    if named in FULLSCREEN and named != "fullscreen_text":
        return FULLSCREEN[named](ctx)
    params = ctx.params
    if params.get("blur_out"):
        return fs_blur_out_up(ctx)
    if params.get("bottom_up"):
        return fs_bottom_up_letters(ctx)
    if params.get("kinetic_swap"):
        return fs_kinetic_type_swap(ctx)
    if params.get("line_slide"):
        return fs_line_by_line_slide(ctx)
    if params.get("logo_close"):
        return fs_logo_brand_close(ctx)
    if params.get("particle_dissolve"):
        return fs_particle_text_dissolve(ctx)
    if params.get("word_crossfade"):
        return fs_per_word_crossfade(ctx)
    if params.get("scan_band"):
        return fs_scan_band(ctx)
    if params.get("scramble_reveal"):
        return fs_scramble_reveal(ctx)
    if params.get("shared_axis_z"):
        return fs_shared_axis_z(ctx)
    if params.get("kinetic") or params.get("stagger_ms"):
        return fs_kinetic_stack(ctx)
    if params.get("slam") or params.get("scale_from"):
        return fs_number_slam(ctx)
    if params.get("split"):
        return fs_vs_compare(ctx)
    if params.get("max_lines"):
        return fs_stack_lines(ctx)
    if params.get("swap_ms"):
        return fs_word_swap(ctx)
    if params.get("strip_height"):
        return fs_strip(ctx)
    if params.get("card"):
        return fs_fact_card(ctx)
    return fs_plain(ctx)


# --- оверлеи источника, чата, статьи -----------------------------------------

def ov_source_card(ctx: "TemplateCtx") -> Piece:
    domain = str(ctx.params.get("domain") or "")
    title = str(ctx.params.get("title") or "")
    snippet = str(ctx.params.get("snippet") or "")
    highlight = str(ctx.params.get("highlight_line") or "")
    node_id = ctx.target
    body = _esc(snippet)
    if highlight and highlight.lower() in snippet.lower():
        idx = snippet.lower().index(highlight.lower())
        body = (_esc(snippet[:idx])
                + f'<span class="hl">{_esc(snippet[idx:idx + len(highlight)])}</span>'
                + _esc(snippet[idx + len(highlight):]))
    tweens = entrance_tweens(f"#{node_id} .bar", ctx.start, name="rise")
    tweens += entrance_tweens(f"#{node_id} .title", ctx.start, name="rise", delay=0.05)
    if snippet:
        tweens += entrance_tweens(f"#{node_id} .snippet", ctx.start,
                                  name="rise", delay=0.10)
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay source-card" {_timing(ctx)}>'
               f'<div class="bar"><span class="dot"></span><span class="dot"></span>'
               f'<span class="dot"></span><span class="domain">{_esc(domain)}</span></div>'
               f'<div class="title">{_esc(title)}</div>'
               f'<div class="snippet">{body}</div></div>'],
        tweens=tweens)


def ov_chat_thread(ctx: "TemplateCtx") -> Piece:
    """Окно чата: запрос, затем ответ очередью. SpaceX chat-response."""
    prompt = str(ctx.params.get("prompt") or ctx.params.get("title") or "").strip()
    snippet = str(ctx.params.get("snippet") or ctx.params.get("reply") or "").strip()
    lines = [str(l).strip() for l in (ctx.params.get("lines") or []) if str(l).strip()]
    if not lines and snippet:
        lines = [s.strip() for s in re.split(r"(?<=[.!?])\s+", snippet) if s.strip()][:3]
    if not prompt and not lines:
        return Piece()
    node_id = ctx.target
    app = str(ctx.params.get("app") or "Chat")
    rows: list[str] = []
    if prompt:
        rows.append(f'<span class="ct-row in">{_esc(prompt)}</span>')
    for line in lines:
        rows.append(f'<span class="ct-row out">{_esc(line)}</span>')
    tweens = entrance_tweens(f"#{node_id} .ct-body", ctx.start, name="zoom-out")
    for i in range(len(rows)):
        tweens += entrance_tweens(
            f"#{node_id} .ct-rows .ct-row:nth-child({i + 1})",
            ctx.start, name="rise", delay=0.14 + 0.12 * i)
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay chat-thread" {_timing(ctx)}>'
               f'<div class="ct-body"><span class="ct-app">{_esc(app)}</span>'
               f'<span class="ct-rows">{"".join(rows)}</span></div></div>'],
        tweens=tweens)


def ov_article_scroll(ctx: "TemplateCtx") -> Piece:
    """Браузер со скроллом сниппета и подсветкой строки. Website → video."""
    domain = str(ctx.params.get("domain") or "")
    title = str(ctx.params.get("title") or "")
    snippet = str(ctx.params.get("snippet") or "")
    highlight = str(ctx.params.get("highlight_line") or "")
    node_id = ctx.target
    body = _esc(snippet)
    if highlight and snippet:
        lowered, needle = snippet.lower(), highlight.lower()
        if needle in lowered:
            idx = lowered.index(needle)
            body = (_esc(snippet[:idx])
                    + f'<span class="hl">{_esc(snippet[idx:idx + len(highlight)])}</span>'
                    + _esc(snippet[idx + len(highlight):]))
        elif highlight:
            body = f'{body} <span class="hl">{_esc(highlight)}</span>'
    shift = min(80, max(36, int(len(snippet) * 0.4)))
    tweens = entrance_tweens(f"#{node_id} .as-frame", ctx.start, name="rise")
    hold = max(0.0, ctx.duration - 0.55)
    if hold >= 0.6:
        tweens.append(
            f'tl.fromTo("#{node_id} .as-body",{{y:0}},'
            f'{{y:{-shift},duration:{_num(hold)},ease:"none"}},'
            f'{_num(ctx.start + 0.5)});')
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay article-scroll" {_timing(ctx)}>'
               f'<div class="as-frame">'
               f'<div class="bar"><span class="dot"></span><span class="dot"></span>'
               f'<span class="dot"></span><span class="domain">{_esc(domain)}</span></div>'
               f'<div class="as-clip"><div class="as-body">'
               f'<div class="title">{_esc(title)}</div>'
               f'<div class="snippet">{body}</div></div></div></div></div>'],
        tweens=tweens)


def ov_paper_reveal(ctx: "TemplateCtx") -> Piece:
    """Строки статьи проявляются, одна вспыхивает. Жест PR-to-video → arxiv."""
    domain = str(ctx.params.get("domain") or "")
    title = str(ctx.params.get("title") or "")
    snippet = str(ctx.params.get("snippet") or "")
    highlight = str(ctx.params.get("highlight_line") or "")
    lines = [str(l).strip() for l in (ctx.params.get("lines") or []) if str(l).strip()]
    if not lines and snippet:
        lines = [s.strip() for s in re.split(r"(?<=[.!?])\s+", snippet) if s.strip()][:4]
    if not lines and title:
        lines = [title]
    if not lines:
        return Piece()
    node_id = ctx.target
    accent_at = -1
    if highlight:
        for i, line in enumerate(lines):
            if highlight.lower() in line.lower():
                accent_at = i
                break
        if accent_at < 0:
            lines.append(highlight)
            accent_at = len(lines) - 1
    rows, tweens = [], []
    tweens += entrance_tweens(f"#{node_id} .pr-card", ctx.start, name="zoom-out")
    for i, line in enumerate(lines[:5]):
        cls = " accent" if i == accent_at else ""
        rows.append(f'<span class="pr-line{cls}">{_esc(line)}</span>')
        tweens += entrance_tweens(f"#{node_id} .pr-line:nth-child({i + 1})",
                                  ctx.start, name="rise", delay=0.14 + 0.11 * i)
    kicker = f'<span class="pr-domain">{_esc(domain)}</span>' if domain else ""
    head = f'<span class="pr-title">{_esc(title)}</span>' if title else ""
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay paper-reveal" {_timing(ctx)}>'
               f'<div class="pr-card">{kicker}{head}'
               f'<span class="pr-lines">{"".join(rows)}</span></div></div>'],
        tweens=tweens)


# Каталог lt-accent-underline: 4.8 с, имя ↑, черта scaleX, роль ↑, затем уход.
_LT_AU_NAME_CEILING = 72
_LT_AU_ROLE_SIZE = 26
_LT_AU_NAME_FROM_Y = 28
_LT_AU_ROLE_FROM_Y = 16
_LT_AU_NAME_EXIT_Y = -16


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


def ov_lt_accent_underline(ctx: "TemplateCtx") -> Piece:
    """Нижняя треть без карточки: имя, акцентная черта left→right, роль.

    Каталог твинит ``tl.to`` после ``gsap.set`` и прячет обёртку через
    ``visibility``. Движок требует ``fromTo`` на вложенных узлах; ``visibility``
    вне списка. Мятный ``#46e5b7`` — чужой бренд, черта канала ``#C8453D``.
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


OVERLAYS: dict[str, Callable[["TemplateCtx"], Piece]] = {
    "source_card": ov_source_card,
    "chat_thread": ov_chat_thread,
    "article_scroll": ov_article_scroll,
    "paper_reveal": ov_paper_reveal,
    "lt_accent_underline": ov_lt_accent_underline,
}


def render_overlay(name: str, ctx: "TemplateCtx") -> Piece:
    fn = OVERLAYS.get(name.rsplit("/", 1)[-1])
    return fn(ctx) if fn else Piece()


def overlay_css(brandbook: dict[str, Any]) -> str:
    """Стили окон чата, статьи, paper-reveal и нижней трети."""
    height = int(brandbook["canvas"]["height"])
    safe = brandbook["safe_zones"]["work_area"]
    subs = brandbook["subtitles"]
    subtitle_top = int(subs["baseline_y_default"]) - int(subs["size_px"][1]) // 2 - 30
    return (
        ".fullscreen-text .ks-stack{display:flex;flex-wrap:wrap;justify-content:center;"
        "gap:0.18em 0.28em;max-width:100%}"
        ".fullscreen-text .ks-word{display:inline-block;will-change:transform}"
        ".fullscreen-text .bou-stack{display:flex;flex-wrap:wrap;justify-content:center;"
        "align-items:center;gap:0.18em 0.28em;max-width:100%;letter-spacing:-0.04em}"
        ".fullscreen-text .bou-word{position:relative;display:inline-block;"
        "will-change:transform}"
        ".fullscreen-text .bou-sharp{position:relative;display:block}"
        ".fullscreen-text .bou-ghost{position:absolute;left:0;top:0;"
        "white-space:nowrap;pointer-events:none}"
        ".fullscreen-text .pwc-stack{display:flex;flex-wrap:wrap;justify-content:center;"
        "align-items:center;gap:0.21em 0.21em;max-width:100%;letter-spacing:-0.04em;"
        "line-height:1}"
        ".fullscreen-text .pwc-word{position:relative;display:inline-block;"
        "will-change:transform}"
        ".fullscreen-text .pwc-sharp{position:relative;display:block;opacity:0}"
        ".fullscreen-text .pwc-ghost{position:absolute;left:0;top:0;"
        "white-space:nowrap;pointer-events:none;opacity:0}"
        ".fullscreen-text .bul-stack{display:flex;flex-wrap:wrap;justify-content:center;"
        "align-items:center;gap:0.12em 0.22em;max-width:100%;letter-spacing:-0.02em;"
        "line-height:1}"
        ".fullscreen-text .bul-word{display:inline-flex;white-space:nowrap}"
        ".fullscreen-text .bul-ch,.fullscreen-text .bul-unit{display:inline-block;"
        "opacity:0;will-change:transform}"
        ".fullscreen-text .fs-slam-card{display:flex;flex-direction:column;"
        "align-items:center;gap:18px;padding:48px 40px;border-radius:36px;"
        "background:var(--color-bg-pure)}"
        ".fullscreen-text.invert .fs-slam-card{background:var(--color-ink)}"
        ".fullscreen-text .fs-num{display:block;line-height:0.9}"
        ".fullscreen-text .fs-cap{display:block;font-family:var(--font-subtitle);"
        "font-size:48px;font-weight:800;text-transform:none;color:var(--color-muted);"
        "will-change:transform}"
        ".fullscreen-text .fs-lines{display:flex;flex-direction:column;"
        "align-items:flex-start;gap:0.12em;text-align:left}"
        ".fullscreen-text .fs-line{display:block;will-change:transform}"
        ".fullscreen-text .lbls-stack{display:flex;flex-direction:column;"
        "align-items:flex-start;overflow:hidden;letter-spacing:-0.04em;"
        "line-height:1;text-align:left;max-width:100%}"
        ".fullscreen-text .lbls-line{position:relative;display:block;"
        "white-space:nowrap;will-change:transform}"
        ".fullscreen-text .lbls-sharp{position:relative;display:block;opacity:0}"
        ".fullscreen-text .lbls-ghost{position:absolute;left:0;top:0;"
        "white-space:nowrap;pointer-events:none;opacity:0}"
        ".fullscreen-text.fs-vs{}"
        ".fullscreen-text .fs-vs-row{display:flex;align-items:center;"
        "justify-content:center;gap:28px}"
        ".fullscreen-text .fs-vs-mid{font-size:0.38em;color:var(--color-accent);"
        "letter-spacing:0.08em}"
        ".fullscreen-text .fs-vs-a,.fullscreen-text .fs-vs-b"
        "{display:block;will-change:transform}"
        ".fullscreen-text .fs-band{display:flex;align-items:center;"
        "justify-content:center;width:100%;background:var(--color-accent);"
        "color:var(--color-bg-pure);will-change:transform}"
        ".fullscreen-text.fs-strip{background:var(--color-bg-light)}"
        ".fullscreen-text .kts-stage{display:flex;align-items:center;"
        "justify-content:center;width:100%;height:100%;will-change:opacity}"
        ".fullscreen-text .kts-sentence{display:flex;align-items:baseline;"
        "justify-content:center;gap:0.26em;max-width:100%;white-space:nowrap;"
        "letter-spacing:-0.045em;line-height:1.08}"
        ".fullscreen-text .kts-prefix,.fullscreen-text .kts-suffix{flex:0 0 auto}"
        ".fullscreen-text .kts-prefix:empty,.fullscreen-text .kts-suffix:empty"
        "{display:none}"
        ".fullscreen-text .kts-slot{position:relative;display:block;flex:0 0 auto;"
        "overflow:hidden;color:var(--color-accent)}"
        ".fullscreen-text .kts-word{position:absolute;left:0;right:0;top:0;"
        "color:var(--color-accent);text-align:center;white-space:nowrap;"
        "line-height:1;will-change:opacity}"
        ".fullscreen-text.fs-lbc{z-index:45;width:var(--frame-w);"
        "height:var(--frame-h)}"
        ".fullscreen-text .lbc-lock{display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;width:100%;"
        "will-change:transform}"
        ".fullscreen-text .lbc-mark{display:flex;align-items:baseline;"
        "justify-content:center;flex-wrap:wrap;letter-spacing:-0.045em;"
        "line-height:0.9;transform-origin:50% 100%;will-change:transform}"
        ".fullscreen-text .lbc-ch,.fullscreen-text .lbc-dot{display:inline-block;"
        "opacity:0;will-change:transform}"
        ".fullscreen-text .lbc-dot{color:var(--color-accent);"
        "transform-origin:50% 65%}"
        ".fullscreen-text .lbc-space{display:inline-block;width:0.34em}"
        ".fullscreen-text .lbc-tag{display:block;font-family:var(--font-subtitle);"
        "font-weight:800;text-transform:none;color:var(--color-ink);"
        "line-height:1.15;max-width:100%;opacity:0;will-change:transform}"
        ".fullscreen-text.invert .lbc-tag{color:var(--color-bg-pure)}"
        ".fullscreen-text .lbc-url{display:block;font-family:var(--font-mono);"
        "text-transform:none;letter-spacing:0.28em;color:var(--color-muted);"
        "opacity:0;will-change:transform}"
        ".fullscreen-text.fs-ptd{width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden}"
        ".fullscreen-text .ptd-stage{position:absolute;inset:0;"
        "will-change:transform}"
        ".fullscreen-text .ptd-dust{position:absolute;inset:0;pointer-events:none}"
        ".fullscreen-text .ptd-dot{position:absolute;display:block;opacity:0;"
        "border-radius:50%;background:var(--color-ink);will-change:transform}"
        ".fullscreen-text.invert .ptd-dot{background:var(--color-bg-pure)}"
        ".fullscreen-text .ptd-dot.accent{background:var(--color-accent)}"
        ".fullscreen-text .ptd-line{position:absolute;inset:0;display:flex;"
        "align-items:center;justify-content:center}"
        ".fullscreen-text .ptd-svg{display:block;overflow:visible}"
        ".fullscreen-text .ptd-wipe{transform-origin:0px 50%;transform-box:fill-box}"
        ".fullscreen-text.ptd-out .ptd-wipe{transform-origin:100% 50%}"
        ".fullscreen-text .ptd-ink{fill:currentColor;"
        "font-family:var(--font-display);font-weight:700;letter-spacing:-0.02em}"
        ".fullscreen-text .ptd-ink .accent{fill:var(--color-accent)}"
        ".fullscreen-text.fs-scan-band{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;"
        "background:#0b0c0e;color:#f7f8fa;"
        "font-family:Inter,system-ui,sans-serif;font-weight:850;"
        "letter-spacing:-0.065em}"
        ".fullscreen-text .sb-stage{position:absolute;inset:0;opacity:0;"
        "will-change:opacity}"
        ".fullscreen-text .sb-wordmark,.fullscreen-text .sb-clone"
        "{position:absolute;inset:0;display:grid;place-items:center;"
        "font-weight:850;line-height:0.86;letter-spacing:-0.065em;"
        "white-space:nowrap}"
        ".fullscreen-text .sb-wordmark{color:#f7f8fa;"
        "text-shadow:0 23px 77px rgba(0,0,0,0.45)}"
        ".fullscreen-text .sb-skew{position:absolute;inset:0;"
        "transform-origin:0 0}"
        ".fullscreen-text .sb-band{position:absolute;top:0;left:0;"
        "overflow:hidden;will-change:transform;z-index:1}"
        ".fullscreen-text .sb-unskew{position:absolute;top:0;left:0;"
        "transform-origin:0 0}"
        ".fullscreen-text .sb-inner{position:absolute;top:0;left:0;"
        "will-change:transform}"
        ".fullscreen-text .sb-clone{text-shadow:none}"
        ".fullscreen-text .sb-clone-red{color:#ff3158;opacity:0.9}"
        ".fullscreen-text .sb-clone-cyan{color:#36efff;opacity:0.9}"
        ".fullscreen-text .sb-clone-core{color:#f7f8fa}"
        ".fullscreen-text.fs-scramble-reveal{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;display:grid;place-items:center;"
        "background:#0b1016;color:#f8fafc;"
        "font-family:var(--font-mono);font-weight:780}"
        ".fullscreen-text .sr-stage{display:block;width:950px;max-width:88%;"
        "will-change:transform,opacity}"
        ".fullscreen-text .sr-shell{display:flex;align-items:center;"
        "justify-content:center;width:100%;min-height:653px;padding:96px 54px;"
        "overflow:hidden;border:2px solid #5fb28d;border-radius:26px;"
        "background:#132222;box-shadow:0 67px 192px rgba(0,0,0,0.42),"
        "inset 0 0 77px rgba(113,245,167,0.07)}"
        ".fullscreen-text .sr-prefix{flex:0 0 auto;margin-right:19px;"
        "color:#90f7ba;font-size:0.74em;font-weight:700;line-height:1;opacity:0.78}"
        ".fullscreen-text .sr-text{position:relative;display:block;min-width:0;"
        "overflow:hidden;color:#71f5a7;font-weight:780;line-height:1;"
        "letter-spacing:0.055em;text-align:center;white-space:pre;"
        "text-shadow:0 0 54px rgba(113,245,167,0.34)}"
        ".fullscreen-text .sr-sizer{visibility:hidden;display:block;white-space:pre}"
        ".fullscreen-text .sr-row{position:absolute;inset:0;display:flex;"
        "align-items:center;justify-content:center;opacity:0;white-space:pre;"
        "color:inherit;text-shadow:inherit}"
        ".fullscreen-text .sr-row.sr-row-on{opacity:1}"
        ".fullscreen-text.sr-clean .sr-shell{min-height:499px;padding:58px 22px;"
        "border-color:transparent;background:transparent;box-shadow:none}"
        ".fullscreen-text.sr-clean .sr-prefix{display:none}"
        ".fullscreen-text.sr-blue .sr-shell{border-color:#5685c0;background:#121c29;"
        "box-shadow:0 67px 192px rgba(0,0,0,0.42),inset 0 0 77px rgba(97,168,255,0.07)}"
        ".fullscreen-text.sr-blue .sr-prefix{color:#84bbff}"
        ".fullscreen-text.sr-blue .sr-text{color:#61a8ff;"
        "text-shadow:0 0 54px rgba(97,168,255,0.34)}"
        ".fullscreen-text.sr-violet .sr-shell{border-color:#9082c0;background:#1a1c29;"
        "box-shadow:0 67px 192px rgba(0,0,0,0.42),inset 0 0 77px rgba(197,163,255,0.07)}"
        ".fullscreen-text.sr-violet .sr-prefix{color:#d2b7ff}"
        ".fullscreen-text.sr-violet .sr-text{color:#c5a3ff;"
        "text-shadow:0 0 54px rgba(197,163,255,0.34)}"
        ".fullscreen-text.fs-shared-axis-z{width:var(--frame-w);height:var(--frame-h);"
        "overflow:hidden;isolation:isolate;display:flex;align-items:center;"
        "justify-content:center;background:#FFFFFF;color:#18181b;"
        "font-family:Inter,system-ui,sans-serif;font-weight:900;"
        "letter-spacing:-0.04em;line-height:1}"
        ".fullscreen-text.fs-shared-axis-z.saz-paper{background:#18181b;color:#fafafa}"
        ".fullscreen-text.fs-shared-axis-z.saz-accent{color:#C8453D}"
        ".fullscreen-text .saz-stack{display:inline-flex;flex-wrap:nowrap;"
        "justify-content:center;align-items:center;max-width:100%;line-height:1;"
        "white-space:nowrap}"
        ".fullscreen-text .saz-word{display:inline-block;"
        "will-change:transform,opacity}"
        ".fullscreen-text .fs-swap-box{position:relative;display:block;"
        "min-height:1.1em}"
        ".fullscreen-text .fs-swap-word{position:absolute;left:0;right:0;opacity:0}"
        ".fullscreen-text .fs-fact{display:block;padding:52px 44px;border-radius:36px;"
        "background:var(--color-bg-light);max-width:100%;will-change:transform}"
        ".fullscreen-text.fs-underline .accent"
        "{box-shadow:inset 0 -0.12em 0 var(--color-accent)}"
        ".fullscreen-text .fs-q{color:var(--color-accent);font-size:0.55em}"
        f".chat-thread{{left:var(--safe-x-min);"
        "width:calc(var(--safe-x-max) - var(--safe-x-min));"
        f"top:{int(safe['y_min']) + 40}px}}"
        ".chat-thread .ct-body{display:flex;flex-direction:column;gap:22px;"
        "padding:36px 30px;border-radius:40px;background:var(--color-bg-pure);"
        "box-shadow:0 24px 70px rgba(0,0,0,0.24);will-change:transform}"
        ".chat-thread .ct-app{display:block;font-family:var(--font-mono);"
        "font-size:28px;color:var(--color-muted);text-align:center}"
        ".chat-thread .ct-rows{display:flex;flex-direction:column;gap:16px}"
        ".chat-thread .ct-row{display:block;max-width:86%;padding:22px 28px;"
        "border-radius:28px;font-family:var(--font-subtitle);font-weight:700;"
        "font-size:38px;line-height:1.22;will-change:transform}"
        ".chat-thread .ct-row.in{align-self:flex-start;background:var(--color-bg-light);"
        "color:var(--color-ink)}"
        ".chat-thread .ct-row.out{align-self:flex-end;"
        "background:var(--color-accent-soft);color:var(--color-bg-pure)}"
        f".article-scroll{{left:var(--safe-x-min);"
        "width:calc(var(--safe-x-max) - var(--safe-x-min));"
        f"bottom:{height - subtitle_top}px}}"
        ".article-scroll .as-frame{border-radius:22px;overflow:hidden;"
        "background:var(--color-bg-pure);color:var(--color-ink);"
        "box-shadow:0 18px 48px rgba(0,0,0,0.22);will-change:transform}"
        ".article-scroll .bar{display:flex;align-items:center;gap:10px;"
        "padding:18px 22px;background:var(--color-bg-light)}"
        ".article-scroll .dot{width:14px;height:14px;border-radius:50%;"
        "background:var(--color-muted)}"
        ".article-scroll .domain{margin-left:10px;font-family:var(--font-mono);"
        "font-size:26px;color:var(--color-muted)}"
        ".article-scroll .title{padding:22px 26px 6px;font-family:var(--font-display);"
        "font-size:52px;line-height:1.04}"
        ".article-scroll .snippet{padding:6px 26px 26px;font-size:30px;"
        "line-height:1.3;color:var(--color-muted)}"
        ".article-scroll .hl{background:var(--color-accent-soft);"
        "box-shadow:0 0 0 6px var(--color-accent-soft)}"
        ".article-scroll .as-clip{overflow:hidden;max-height:420px}"
        ".article-scroll .as-body{will-change:transform}"
        f".paper-reveal{{left:var(--safe-x-min);"
        "width:calc(var(--safe-x-max) - var(--safe-x-min));"
        f"top:{int(safe['y_min']) + 80}px}}"
        ".paper-reveal .pr-card{display:block;padding:40px 36px 36px;"
        "border-radius:28px;background:var(--color-bg-pure);color:var(--color-ink);"
        "box-shadow:0 22px 56px rgba(0,0,0,0.2);will-change:transform}"
        ".paper-reveal .pr-domain{display:block;font-family:var(--font-mono);"
        "font-size:26px;color:var(--color-muted);margin-bottom:10px}"
        ".paper-reveal .pr-title{display:block;font-family:var(--font-display);"
        "font-size:56px;line-height:1.02;margin-bottom:22px}"
        ".paper-reveal .pr-lines{display:flex;flex-direction:column;gap:14px}"
        ".paper-reveal .pr-line{display:block;font-family:var(--font-subtitle);"
        "font-size:34px;line-height:1.28;color:var(--color-muted);will-change:transform}"
        ".paper-reveal .pr-line.accent{color:var(--color-ink);"
        "background:var(--color-accent-soft);box-shadow:0 0 0 8px var(--color-accent-soft);"
        "border-radius:8px}"
        f".lt-accent-underline{{left:var(--safe-x-min);"
        f"bottom:{height - int(safe['y_max']) + 60}px;"
        "max-width:calc(var(--safe-x-max) - var(--safe-x-min));"
        "display:flex;flex-direction:column;align-items:flex-start;gap:14px;"
        "background:transparent}"
        ".lt-au-name{display:block;font-family:'Oswald',var(--font-display),sans-serif;"
        "font-weight:700;color:#ffffff;line-height:0.96;letter-spacing:0.005em;"
        "text-transform:uppercase;white-space:nowrap;"
        "text-shadow:0 2px 22px rgba(0,0,0,0.45);will-change:transform,opacity}"
        ".lt-au-rule{display:block;height:6px;border-radius:3px;background:#C8453D;"
        "transform-origin:0% 50%;will-change:transform}"
        ".lt-au-role{display:block;font-family:'Space Mono',var(--font-mono),monospace;"
        "font-weight:400;color:#e7eaf0;line-height:1.2;letter-spacing:0.04em;"
        "white-space:nowrap;text-shadow:0 2px 16px rgba(0,0,0,0.45);"
        "will-change:transform,opacity}"
    )


def hero_css(brandbook: dict[str, Any]) -> str:
    """Стили приёмов вокруг ведущего.

    Слои сидят между фоном и аватаром (лучи, заголовок) либо поверх него
    (сплит, выбивка) — это задаётся z-index, а не порядком в разметке.
    """
    height = int(brandbook["canvas"]["height"])
    width = int(brandbook["canvas"]["width"])
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
        # --- строки колонкой слева ---
        # Колонка занимает левую половину: правая половина под ведущим, а
        # правое поле кадра съедает колонка лайк/коммент/шер.
        f".hero-text-column{{position:absolute;left:var(--safe-x-min);"
        f"width:{int(width * 0.42)}px;z-index:{Z_AVATAR + 1};"
        "display:flex;flex-direction:column;align-items:flex-start;gap:18px;"
        "pointer-events:none}"
        ".hero-text-column .tc-line{display:block;font-family:var(--font-display);"
        "text-transform:uppercase;font-size:66px;line-height:0.98;"
        "color:var(--color-bg-pure);will-change:transform;"
        "text-shadow:0 4px 22px rgba(0,0,0,0.55),0 2px 5px rgba(0,0,0,0.45)}"
        # Золото референсов переведено в акцент бренда: выцветший красный.
        ".hero-text-column .tc-line.accent{color:var(--color-accent-soft)}"
        # --- круглая рамка и карточка ---
        f".hero-bubble-card{{position:absolute;inset:0;z-index:{Z_AVATAR + 1};"
        "pointer-events:none}"
        # Кольцо обводит лицо, не закрывая его: заливки нет, только рамка.
        # Тёмное поле с круглой дыркой: ведущий остаётся виден только в круге.
        # Градиент, а не filter — размытие вне разрешённого списка движка.
        ".hero-bubble-card .bc-field{position:absolute;inset:0;display:block;"
        "width:100%;height:100%;will-change:transform}"
        ".hero-bubble-card .bc-card{position:absolute;left:var(--safe-x-min);"
        "right:var(--safe-x-min);display:flex;flex-direction:column;"
        "gap:10px;padding:56px 46px 44px;border-radius:44px;"
        "background:var(--color-bg-pure);color:var(--color-ink);"
        "box-shadow:0 26px 70px rgba(0,0,0,0.28);text-align:center;"
        "will-change:transform}"
        ".hero-bubble-card .bc-line{display:block;font-family:var(--font-subtitle);"
        "font-weight:700;font-size:62px;line-height:1.16}"
        ".hero-bubble-card .bc-line.accent{font-weight:800;"
        "color:var(--color-accent)}"
        # --- пилюля бренда ---
        f".hero-brand-pill{{position:absolute;z-index:{Z_AVATAR + 1};"
        "pointer-events:none}"
        ".hero-brand-pill.left{left:var(--safe-x-min)}"
        ".hero-brand-pill.right{right:calc(var(--frame-w) - var(--safe-x-max))}"
        ".hero-brand-pill .bp-inner{display:inline-flex;align-items:center;"
        "gap:20px;padding:20px 38px;border-radius:999px;"
        "background:var(--color-ink);color:var(--color-bg-pure);"
        "box-shadow:0 16px 44px rgba(0,0,0,0.34);will-change:transform}"
        ".hero-brand-pill .bp-icon{display:block;width:64px;height:64px;"
        "object-fit:contain}"
        ".hero-brand-pill .bp-label{font-family:var(--font-subtitle);"
        "font-weight:800;font-size:52px;line-height:1}"
        # --- карточка сверху, ведущий снизу ---
        f".hero-card-stack{{position:absolute;left:0;right:0;top:0;"
        f"z-index:{Z_AVATAR + 1};border-radius:0 0 44px 44px;overflow:hidden;"
        "background:var(--color-bg-pure);display:flex;justify-content:center;"
        "padding:110px 60px 0;pointer-events:none}"
        ".hero-card-stack .cs-title{display:block;text-align:center;"
        "font-family:var(--font-display);text-transform:uppercase;"
        "font-size:104px;line-height:0.96;color:var(--color-ink);"
        "will-change:transform}"
        f".cs-media{{position:absolute;left:60px;width:{width - 120}px;"
        f"z-index:{Z_AVATAR + 2};object-fit:cover;border-radius:28px;"
        "display:block}"
        # --- экран телефона ---
        f".hero-phone-mock{{position:absolute;inset:0;z-index:{Z_AVATAR + 1};"
        "display:flex;align-items:center;justify-content:center;"
        # Расфокус фона — полупрозрачная подложка, а не filter: blur вне
        # разрешённого списка движка, и его анимация ломает перемотку.
        "background:rgba(10,10,12,0.42);pointer-events:none}"
        f".hero-phone-mock .pm-body{{width:{int(width * 0.72)}px;"
        f"max-height:{int(height * 0.62)}px;display:flex;flex-direction:column;"
        "gap:24px;padding:44px 34px;border-radius:56px;"
        "background:var(--color-bg-pure);color:var(--color-ink);"
        "box-shadow:0 34px 90px rgba(0,0,0,0.45);will-change:transform}"
        ".hero-phone-mock .pm-app{display:block;font-family:var(--font-mono);"
        "font-size:30px;color:var(--color-muted);text-align:center}"
        ".hero-phone-mock .pm-rows{display:flex;flex-direction:column;gap:20px}"
        ".hero-phone-mock .pm-row{display:block;max-width:82%;padding:26px 32px;"
        "border-radius:34px;font-family:var(--font-subtitle);font-weight:700;"
        "font-size:44px;line-height:1.2;will-change:transform}"
        ".hero-phone-mock .pm-row.in{align-self:flex-start;background:var(--color-bg-light)}"
        ".hero-phone-mock .pm-row.out{align-self:flex-end;"
        "background:var(--color-accent-soft);color:var(--color-bg-pure)}"
        # --- плита типа слева ---
        f".hero-type-slab{{position:absolute;left:var(--safe-x-min);"
        f"width:{int(width * 0.52)}px;z-index:{Z_AVATAR + 1};"
        "display:flex;flex-direction:column;align-items:flex-start;gap:8px;"
        "pointer-events:none}"
        ".hero-type-slab .ts-line{display:block;font-family:var(--font-display);"
        "text-transform:uppercase;line-height:0.9;color:var(--color-ink);"
        "will-change:transform;"
        "text-shadow:0 4px 22px rgba(247,245,243,0.9)}"
        ".hero-type-slab .ts-line.accent{color:var(--color-accent)}"
        # --- футаж-окно поверх ---
        f".hero-plate-pop{{position:absolute;display:block;z-index:{Z_AVATAR + 1};"
        "object-fit:cover;border-radius:28px;"
        "border:10px solid var(--color-bg-pure);background:var(--color-bg-pure);"
        "box-shadow:0 28px 80px rgba(0,0,0,0.34);pointer-events:none}"
        # --- выбивка ---
        ".hero-knockout{position:absolute;inset:0;"
        f"z-index:{Z_AVATAR + 1};pointer-events:none}}"
        ".hero-knockout svg{width:100%;height:100%;display:block}"
        # Чёрный в маске = дырка: сквозь буквы виден ведущий.
        ".hero-knockout .hk-text{fill:#000;font-family:var(--font-display);"
        "font-weight:700;letter-spacing:-0.01em}"
    )
