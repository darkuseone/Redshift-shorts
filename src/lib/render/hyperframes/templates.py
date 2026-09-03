"""Каталог шаблонов (§15) в терминах HTML/CSS/GSAP.

150 шаблон каталога — это не 150 реализация, а набор рендереров с параметрами.
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

from .spm_shapes import SPM_SHAPES, SPM_VB
from .umf_shapes import UMF_CITIES, UMF_FLOWS, UMF_SHAPES, UMF_VB
from .umh_shapes import (
    UMH_TOP5, UMH_TITLE, UMH_SUBTITLE, UMH_SOURCE,
    UMH_LEG_LOW, UMH_LEG_HIGH, umh_build_hexes, umh_color, umh_is_light_text,
    UMH_INCOME,
)
from .usm_shapes import USM_SHAPES, USM_VB
from .wmp_shapes import (
    WMP_GRATICULE, WMP_SHAPES, WMP_TOP5, WMP_TITLE, WMP_SUBTITLE, WMP_SOURCE,
    WMP_VB,
)

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
    Цвета ``#3d348b`` / ``#f7b801`` — жест SCENE A/B каталога, не палитра
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
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut"}},{_num(start)});',
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


def _gw_times(duration: float) -> dict[str, float]:
    """Окно gravitational-lens: каталог держит 2 с шейдера внутри 4 с демо."""
    return _cz_times(duration)


def tr_gravitational_lens(ctx: "TemplateCtx") -> Piece:
    """Gravitational lens: from затягивает к центру, горизонт, chroma.

    Каталог рисует WebGL ``onUpdate``: warp к колодцу, chromatic aberration,
    event horizon. Здесь входящий кадр выходит из tight, фиолетовая вуаль
    ``#10002b`` схлопывается к центру, магента ``#f20089`` выходит из well,
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
        f'{{scale:1,duration:{_num(d)},ease:"power2.inOut"}},{_num(start)});',
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
    flare. Здесь вуали ``#001524``/``#fb8b24``, пятно и полоса screen.
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


def _si_times(duration: float) -> dict[str, float]:
    """Окно sdf-iris: каталог держит 2 с шейдера внутри 4 с демо."""
    return _cz_times(duration)


def tr_sdf_iris(ctx: "TemplateCtx") -> Piece:
    """SDF iris: круг из центра, три кольца glow.

    Каталог рисует WebGL ``onUpdate``: aspect-corrected SDF, onion rings.
    Здесь золотой диск ``#ffc300`` растёт ``scale``, три кольца и вуаль
    ``#003049``. Без canvas и без ``clip-path``. Цвета SCENE A/B каталога —
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
    Здесь вуали ``#3d405b``/``#e07a5f``, пятно снизу и полосы, ``y`` вверх.
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


def _wp_times(duration: float) -> dict[str, float]:
    """Окно whip-pan шейдера: каталог держит 2 с внутри 4 с демо."""
    return _cz_times(duration)


def tr_whip_pan_shader(ctx: "TemplateCtx") -> Piece:
    """Whip pan: оба кадра едут вбок с направленным смазом.

    Каталог рисует WebGL ``onUpdate``: 10 семплов, fromOff/toOff.
    Здесь вуали ``#0b132b``/``#48bfe3``, стальной слой и полосы смаза, ``x``.
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


_CW_CATALOG_SEC = 2.4
_CW_FRAME_W = 1080
_CW_FRAME_H = 1920
_CW_CARD_SCALE = 0.38


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
    и не на входящем кадре. Чернила ``#1d1d1f`` и бумага ``#ffffff`` как в
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
    на сценах. Здесь ``scaleX``/``opacity``, грани ``#1b263b``/``#e07a5f``.
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
    1080 px без CSS ``transform``, вуали ``#f72585``/``#7209b7``. Твины
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


_TLT_CATALOG_SEC = 2.4
_TLT_L1_IN_X = 169
_TLT_L1_OUT_X = 338
_TLT_L2_IN_X = 112
_TLT_L2_OUT_X = 225


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


_TDS_CATALOG_SEC = 2.4
_TDS_HOLE_FROM = 1.0
_TDS_HOLE_TO = 0.04
_TDS_A_TO = _TDS_HOLE_FROM / _TDS_HOLE_TO
_TDS_RINGS = ((1.02, 0.041), (1.08, 0.043), (1.16, 0.046))


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


_GS_COLS = 8
_GS_ROWS = 12
_GS_SCANS = 12


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
    и вуали ``#293241``/``#ee6c4d``. Без canvas и без ``Math.random``.
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
    "cinematic_zoom": tr_cinematic_zoom,
    "gravitational_lens": tr_gravitational_lens,
    "light_leak": tr_light_leak,
    "sdf_iris": tr_sdf_iris,
    "thermal_distortion": tr_thermal_distortion,
    "whip_pan_shader": tr_whip_pan_shader,
    "mk_clone_wall": tr_mk_clone_wall,
    "transitions_3d": tr_transitions_3d,
    "transitions_blur": tr_transitions_blur,
    "transitions_cover": tr_transitions_cover,
    "transitions_light": tr_transitions_light,
    "transitions_other": tr_transitions_other,
    "transitions_destruction": tr_transitions_destruction,
    "blur_dip": tr_blur_dip,
    "whip_pan": tr_whip_pan,
    "paper_slide": tr_paper_slide,
    "mask_wipe": tr_mask_wipe,
    "light_sweep": tr_light_sweep,
    "glitch": tr_glitch,
    "glitch_shader": tr_glitch_shader,
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
        f".tr-cinematic-zoom{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-cinematic-zoom .cz-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-cinematic-zoom .cz-blur,.tr-cinematic-zoom .cz-from,"
        ".tr-cinematic-zoom .cz-to,.tr-cinematic-zoom .cz-r,"
        ".tr-cinematic-zoom .cz-b,.tr-cinematic-zoom .cz-ghost{"
        "position:absolute;inset:0;display:block;opacity:0;"
        "transform-origin:50% 50%}"
        ".tr-cinematic-zoom .cz-blur{backdrop-filter:blur(16px)}"
        ".tr-cinematic-zoom .cz-from{background:#3d348b;mix-blend-mode:overlay}"
        ".tr-cinematic-zoom .cz-to{background:#f7b801;mix-blend-mode:overlay}"
        ".tr-cinematic-zoom .cz-r{inset:-18%;border-radius:50%;"
        "background:radial-gradient(circle,rgba(255,77,58,0.72) 0%,transparent 58%);"
        "mix-blend-mode:screen}"
        ".tr-cinematic-zoom .cz-b{inset:-14%;border-radius:50%;"
        "background:radial-gradient(circle,rgba(61,198,255,0.65) 0%,transparent 58%);"
        "mix-blend-mode:screen}"
        ".tr-cinematic-zoom .cz-ghost{"
        "background:radial-gradient(circle,rgba(255,255,255,0.22) 0%,transparent 70%);"
        "mix-blend-mode:screen}"
        f".tr-glitch-shader{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-glitch-shader .gs-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-glitch-shader .gs-from,.tr-glitch-shader .gs-to,"
        ".tr-glitch-shader .gs-lines,.tr-glitch-shader .gs-flick,"
        ".tr-glitch-shader .gs-r,.tr-glitch-shader .gs-b{"
        "position:absolute;inset:0;display:block;opacity:0;"
        "transform-origin:50% 50%}"
        ".tr-glitch-shader .gs-from{background:#293241;mix-blend-mode:overlay}"
        ".tr-glitch-shader .gs-to{background:#ee6c4d;mix-blend-mode:overlay}"
        ".tr-glitch-shader .gs-lines{background:repeating-linear-gradient("
        "to bottom,transparent 0px,transparent 1px,rgba(0,0,0,0.22) 1px,"
        "rgba(0,0,0,0.22) 2px);mix-blend-mode:multiply}"
        ".tr-glitch-shader .gs-flick{background:#ffffff;mix-blend-mode:overlay}"
        ".tr-glitch-shader .gs-r{background:#ee6c4d;mix-blend-mode:screen}"
        ".tr-glitch-shader .gs-b{background:#98c1d9;mix-blend-mode:screen}"
        ".tr-glitch-shader .gs-scan{position:absolute;left:-12%;width:124%;"
        "display:block;opacity:0;background:rgba(238,108,77,0.5);"
        "mix-blend-mode:overlay}"
        ".tr-glitch-shader .gs-block{position:absolute;display:block;opacity:0;"
        "background:rgba(152,193,217,0.35);mix-blend-mode:screen}"
        f".tr-gravitational-lens{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-gravitational-lens .gw-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-gravitational-lens .gw-blur,.tr-gravitational-lens .gw-from,"
        ".tr-gravitational-lens .gw-to,.tr-gravitational-lens .gw-well,"
        ".tr-gravitational-lens .gw-r,.tr-gravitational-lens .gw-b,"
        ".tr-gravitational-lens .gw-ghost{"
        "position:absolute;inset:0;display:block;opacity:0;"
        "transform-origin:50% 50%}"
        ".tr-gravitational-lens .gw-blur{backdrop-filter:blur(14px)}"
        ".tr-gravitational-lens .gw-from{background:#10002b;mix-blend-mode:overlay}"
        ".tr-gravitational-lens .gw-to{background:#f20089;mix-blend-mode:overlay}"
        ".tr-gravitational-lens .gw-well{inset:-28%;border-radius:50%;"
        "background:radial-gradient(circle,#000000 0%,transparent 62%);"
        "mix-blend-mode:multiply}"
        ".tr-gravitational-lens .gw-r{inset:-16%;border-radius:50%;"
        "background:radial-gradient(circle,rgba(242,0,137,0.78) 0%,transparent 58%);"
        "mix-blend-mode:screen}"
        ".tr-gravitational-lens .gw-b{inset:-12%;border-radius:50%;"
        "background:radial-gradient(circle,rgba(160,128,160,0.62) 0%,transparent 58%);"
        "mix-blend-mode:screen}"
        ".tr-gravitational-lens .gw-ghost{"
        "background:radial-gradient(circle,rgba(242,0,137,0.2) 0%,transparent 70%);"
        "mix-blend-mode:screen}"
        f".tr-light-leak{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-light-leak .ll-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-light-leak .ll-from,.tr-light-leak .ll-to,"
        ".tr-light-leak .ll-sage,.tr-light-leak .ll-blob,"
        ".tr-light-leak .ll-hot,.tr-light-leak .ll-orb{"
        "position:absolute;inset:0;display:block;opacity:0;"
        "transform-origin:50% 50%}"
        ".tr-light-leak .ll-from{background:#001524;mix-blend-mode:overlay}"
        ".tr-light-leak .ll-to{background:#fb8b24;mix-blend-mode:overlay}"
        ".tr-light-leak .ll-sage{background:#708d81;mix-blend-mode:overlay}"
        ".tr-light-leak .ll-blob{inset:-48% -38% 18% 12%;border-radius:50%;"
        "background:radial-gradient(circle at 78% 22%,"
        "rgba(255,230,191,0.95) 0%,rgba(255,128,24,0.78) 34%,"
        "rgba(251,139,36,0.28) 58%,transparent 74%);"
        "mix-blend-mode:screen}"
        ".tr-light-leak .ll-hot{inset:-18% -12% 62% 48%;border-radius:50%;"
        "background:radial-gradient(circle,rgba(255,204,128,0.9) 0%,transparent 62%);"
        "mix-blend-mode:screen}"
        ".tr-light-leak .ll-flare{position:absolute;display:block;opacity:0;"
        "left:-28%;top:2%;width:156%;height:24%;"
        "background:linear-gradient(108deg,transparent 22%,"
        "rgba(255,204,128,0) 38%,rgba(255,204,128,0.88) 50%,"
        "rgba(251,139,36,0.5) 58%,transparent 78%);"
        "mix-blend-mode:screen;transform-origin:50% 50%}"
        ".tr-light-leak .ll-o0{inset:-36% -18% 48% 28%;border-radius:50%;"
        "background:radial-gradient(circle,rgba(255,128,24,0.4) 0%,transparent 70%);"
        "mix-blend-mode:screen}"
        ".tr-light-leak .ll-o1{inset:-22% -8% 38% 8%;border-radius:50%;"
        "background:radial-gradient(circle,rgba(255,230,191,0.32) 0%,transparent 70%);"
        "mix-blend-mode:screen}"
        f".tr-sdf-iris{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-sdf-iris .si-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-sdf-iris .si-from,.tr-sdf-iris .si-steel{"
        "position:absolute;inset:0;display:block;opacity:0;"
        "transform-origin:50% 50%}"
        ".tr-sdf-iris .si-from{background:#003049;mix-blend-mode:overlay}"
        ".tr-sdf-iris .si-steel{background:#7a9ab0;mix-blend-mode:overlay}"
        ".tr-sdf-iris .si-iris,.tr-sdf-iris .si-ring{"
        "position:absolute;left:50%;top:50%;width:2400px;height:2400px;"
        "margin:-1200px 0 0 -1200px;border-radius:50%;display:block;opacity:0;"
        "transform-origin:50% 50%}"
        ".tr-sdf-iris .si-iris{background:#ffc300;mix-blend-mode:overlay}"
        ".tr-sdf-iris .si-ring{"
        "background:radial-gradient(circle,transparent 46%,"
        "rgba(255,217,153,0.92) 50%,transparent 54%);"
        "mix-blend-mode:screen}"
        f".tr-thermal-distortion{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-thermal-distortion .td-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-thermal-distortion .td-from,.tr-thermal-distortion .td-to,"
        ".tr-thermal-distortion .td-mist,.tr-thermal-distortion .td-blur{"
        "position:absolute;inset:0;display:block;opacity:0;"
        "transform-origin:50% 50%}"
        ".tr-thermal-distortion .td-from{background:#3d405b;mix-blend-mode:overlay}"
        ".tr-thermal-distortion .td-to{background:#e07a5f;mix-blend-mode:overlay}"
        ".tr-thermal-distortion .td-mist{background:#a0a0b0;mix-blend-mode:overlay}"
        ".tr-thermal-distortion .td-blur{backdrop-filter:blur(10px)}"
        ".tr-thermal-distortion .td-haze,.tr-thermal-distortion .td-hot{"
        "position:absolute;display:block;opacity:0;border-radius:50%;"
        "transform-origin:50% 50%}"
        ".tr-thermal-distortion .td-haze{inset:32% -24% -28% -24%;"
        "background:radial-gradient(circle at 50% 78%,"
        "rgba(255,230,179,0.92) 0%,rgba(224,122,95,0.55) 42%,transparent 70%);"
        "mix-blend-mode:screen}"
        ".tr-thermal-distortion .td-hot{inset:58% -8% -22% -8%;"
        "background:radial-gradient(circle,rgba(255,230,179,0.9) 0%,transparent 62%);"
        "mix-blend-mode:screen}"
        ".tr-thermal-distortion .td-band{position:absolute;left:-12%;width:124%;"
        "height:120px;display:block;opacity:0;"
        "background:linear-gradient(180deg,transparent 0%,"
        "rgba(255,230,179,0.7) 50%,transparent 100%);"
        "mix-blend-mode:screen;transform-origin:50% 50%}"
        ".tr-thermal-distortion .td-b0{top:1080px}"
        ".tr-thermal-distortion .td-b1{top:1240px}"
        ".tr-thermal-distortion .td-b2{top:1400px}"
        ".tr-thermal-distortion .td-b3{top:1560px}"
        ".tr-thermal-distortion .td-b4{top:1720px}"
        f".tr-whip-pan{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-whip-pan .wp-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-whip-pan .wp-from,.tr-whip-pan .wp-to,"
        ".tr-whip-pan .wp-steel,.tr-whip-pan .wp-blur{"
        "position:absolute;inset:0;display:block;opacity:0;"
        "transform-origin:50% 50%}"
        ".tr-whip-pan .wp-from{background:#0b132b;mix-blend-mode:overlay}"
        ".tr-whip-pan .wp-to{background:#48bfe3;mix-blend-mode:overlay}"
        ".tr-whip-pan .wp-steel{background:#7a9ab0;mix-blend-mode:overlay}"
        ".tr-whip-pan .wp-blur{backdrop-filter:blur(10px)}"
        ".tr-whip-pan .wp-streak{position:absolute;left:-18%;width:136%;"
        "height:88px;display:block;opacity:0;"
        "background:linear-gradient(90deg,transparent 0%,"
        "rgba(72,191,227,0) 12%,rgba(72,191,227,0.88) 48%,"
        "rgba(11,19,43,0.45) 78%,transparent 100%);"
        "mix-blend-mode:screen;transform-origin:50% 50%}"
        ".tr-whip-pan .wp-s0{top:80px}"
        ".tr-whip-pan .wp-s1{top:380px}"
        ".tr-whip-pan .wp-s2{top:680px}"
        ".tr-whip-pan .wp-s3{top:980px}"
        ".tr-whip-pan .wp-s4{top:1280px}"
        ".tr-whip-pan .wp-s5{top:1580px}"
        f".tr-mk-clone-wall{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-mk-clone-wall .cw-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-mk-clone-wall .cw-wall,.tr-mk-clone-wall .cw-tiles{"
        "position:absolute;inset:0;display:block;transform-origin:50% 50%}"
        ".tr-mk-clone-wall .cw-wall{background:#ffffff;isolation:isolate}"
        ".tr-mk-clone-wall .cw-row{position:absolute;white-space:nowrap;"
        "font-family:Inter,system-ui,sans-serif;font-weight:600;"
        "letter-spacing:-0.02em;color:#1d1d1f;line-height:1}"
        ".tr-mk-clone-wall .cw-tile{display:inline-block}"
        ".tr-mk-clone-wall .cw-invert{position:absolute;inset:0;display:block;"
        "transform-origin:50% 50%;background:#ffffff;"
        "mix-blend-mode:difference}"
        ".tr-mk-clone-wall .cw-card{position:absolute;inset:0;display:block;"
        "transform-origin:50% 50%;border-radius:0;overflow:hidden;"
        "background:linear-gradient(120deg,#fdfbfd 0%,#ff7ac8 38%,#45d6c8 100%);"
        "box-shadow:0 30px 80px rgba(0,0,0,0.22)}"
        f".tr-transitions-3d{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-3d .t3-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-transitions-3d .t3-face{position:absolute;inset:0;display:flex;"
        "flex-direction:column;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-transitions-3d .t3-a{background:#1b263b}"
        ".tr-transitions-3d .t3-b{background:#e07a5f;opacity:0}"
        ".tr-transitions-3d .t3-big{font-family:Inter,system-ui,sans-serif;"
        "font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;"
        "user-select:none}"
        ".tr-transitions-3d .t3-a .t3-big{color:rgba(255,255,255,0.08)}"
        ".tr-transitions-3d .t3-b .t3-big{color:rgba(255,255,255,0.15)}"
        ".tr-transitions-3d .t3-label{font-family:Inter,system-ui,sans-serif;"
        "font-size:40px;font-weight:600;letter-spacing:6px;"
        "margin-top:12px}"
        ".tr-transitions-3d .t3-a .t3-label{color:#778da9}"
        ".tr-transitions-3d .t3-b .t3-label{color:#ffffff}"
        ".tr-transitions-3d .t3-edge{position:absolute;left:50%;top:0;"
        "width:8px;height:100%;margin-left:-4px;display:block;opacity:0;"
        "background:#778da9;transform-origin:50% 50%}"
        f".tr-transitions-blur{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-blur .tb-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-transitions-blur .tb-face{position:absolute;inset:0;display:flex;"
        "flex-direction:column;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-transitions-blur .tb-a{background:#1b263b}"
        ".tr-transitions-blur .tb-b{background:#e07a5f;opacity:0}"
        ".tr-transitions-blur .tb-ghost{filter:blur(15px);opacity:0}"
        ".tr-transitions-blur .tb-big{font-family:Inter,system-ui,sans-serif;"
        "font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;"
        "user-select:none}"
        ".tr-transitions-blur .tb-a .tb-big{color:rgba(255,255,255,0.08)}"
        ".tr-transitions-blur .tb-b .tb-big{color:rgba(255,255,255,0.15)}"
        ".tr-transitions-blur .tb-label{font-family:Inter,system-ui,sans-serif;"
        "font-size:40px;font-weight:600;letter-spacing:6px;"
        "margin-top:12px}"
        ".tr-transitions-blur .tb-a .tb-label{color:#778da9}"
        ".tr-transitions-blur .tb-b .tb-label{color:#ffffff}"
        f".tr-transitions-cover{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-cover .tc-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-transitions-cover .tc-face{position:absolute;inset:0;display:flex;"
        "flex-direction:column;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-transitions-cover .tc-a{background:#1b263b}"
        ".tr-transitions-cover .tc-b{background:#e07a5f;opacity:0}"
        ".tr-transitions-cover .tc-big{font-family:Inter,system-ui,sans-serif;"
        "font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;"
        "user-select:none}"
        ".tr-transitions-cover .tc-a .tc-big{color:rgba(255,255,255,0.12)}"
        ".tr-transitions-cover .tc-b .tc-big{color:rgba(0,0,0,0.12)}"
        ".tr-transitions-cover .tc-label{font-family:Inter,system-ui,sans-serif;"
        "font-size:40px;font-weight:700;letter-spacing:6px;"
        "margin-top:12px;color:#ffffff}"
        ".tr-transitions-cover .tc-wipe{position:absolute;inset:0;display:block;"
        "opacity:0}"
        ".tr-transitions-cover .tc-wb{background:#7209b7}"
        ".tr-transitions-cover .tc-wa{background:#f72585}"
        f".tr-transitions-destruction{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-destruction .tds-stage{display:block;width:100%;height:100%;"
        "position:relative;background:#000}"
        ".tr-transitions-destruction .tds-face{display:flex;"
        "flex-direction:column;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-transitions-destruction .tds-b{position:absolute;inset:0;"
        "background:#e07a5f;opacity:0}"
        f".tr-transitions-destruction .tds-hole{{position:absolute;left:50%;top:50%;"
        f"width:{diagonal}px;height:{diagonal}px;"
        f"margin:-{diagonal // 2}px 0 0 -{diagonal // 2}px;"
        "border-radius:50%;overflow:hidden;display:block;"
        "transform-origin:50% 50%}"
        f".tr-transitions-destruction .tds-hole .tds-a{{position:absolute;"
        f"left:50%;top:50%;width:{width}px;height:{height}px;"
        f"margin:-{height // 2}px 0 0 -{width // 2}px;background:#1b263b}}"
        ".tr-transitions-destruction .tds-big{font-family:Inter,system-ui,sans-serif;"
        "font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;"
        "user-select:none}"
        ".tr-transitions-destruction .tds-a .tds-big{color:rgba(255,255,255,0.08)}"
        ".tr-transitions-destruction .tds-b .tds-big{color:rgba(255,255,255,0.15)}"
        ".tr-transitions-destruction .tds-label{font-family:Inter,system-ui,sans-serif;"
        "font-size:40px;font-weight:700;letter-spacing:6px;"
        "margin-top:12px}"
        ".tr-transitions-destruction .tds-a .tds-label{color:#778da9}"
        ".tr-transitions-destruction .tds-b .tds-label{color:#ffffff}"
        f".tr-transitions-destruction .tds-ring{{position:absolute;left:50%;top:50%;"
        f"width:{diagonal}px;height:{diagonal}px;"
        f"margin:-{diagonal // 2}px 0 0 -{diagonal // 2}px;"
        "border-radius:50%;display:block;opacity:0;"
        "transform-origin:50% 50%;mix-blend-mode:screen}"
        ".tr-transitions-destruction .tds-r0{"
        "background:radial-gradient(circle,transparent 44%,"
        "rgba(255,100,0,0.9) 50%,transparent 56%)}"
        ".tr-transitions-destruction .tds-r1{"
        "background:radial-gradient(circle,transparent 40%,"
        "rgba(255,50,0,0.8) 50%,transparent 60%)}"
        ".tr-transitions-destruction .tds-r2{"
        "background:radial-gradient(circle,transparent 36%,"
        "rgba(200,30,0,0.5) 50%,transparent 64%)}"
        f".tr-transitions-light{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-light .tlt-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-transitions-light .tlt-face{position:absolute;inset:0;display:flex;"
        "flex-direction:column;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-transitions-light .tlt-a{background:#1b263b}"
        ".tr-transitions-light .tlt-b{background:#e07a5f;opacity:0}"
        ".tr-transitions-light .tlt-big{font-family:Inter,system-ui,sans-serif;"
        "font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;"
        "user-select:none}"
        ".tr-transitions-light .tlt-a .tlt-big{color:rgba(255,255,255,0.12)}"
        ".tr-transitions-light .tlt-b .tlt-big{color:rgba(0,0,0,0.12)}"
        ".tr-transitions-light .tlt-label{font-family:Inter,system-ui,sans-serif;"
        "font-size:40px;font-weight:700;letter-spacing:6px;"
        "margin-top:12px;color:#ffffff}"
        ".tr-transitions-light .tlt-warm{position:absolute;inset:0;display:block;"
        "opacity:0;pointer-events:none;"
        "background:linear-gradient(135deg,rgba(255,165,0,0.6),transparent 60%);"
        "transform-origin:50% 50%}"
        ".tr-transitions-light .tlt-blob{position:absolute;display:block;"
        "opacity:0;pointer-events:none;transform-origin:50% 50%}"
        ".tr-transitions-light .tlt-l1{top:-356px;left:-225px;"
        "width:1350px;height:2667px;"
        "background:radial-gradient(ellipse at 30% 40%,"
        "rgba(255,140,0,0.5),transparent 50%)}"
        ".tr-transitions-light .tlt-l2{top:-178px;left:-112px;"
        "width:1350px;height:2489px;"
        "background:radial-gradient(ellipse at 60% 50%,"
        "rgba(255,200,0,0.4),transparent 50%)}"
        f".tr-transitions-other{{position:absolute;inset:0;z-index:{Z_TRANSITION};"
        "overflow:hidden;pointer-events:none}"
        ".tr-transitions-other .tto-stage{display:block;width:100%;height:100%;"
        "position:relative}"
        ".tr-transitions-other .tto-face{position:absolute;inset:0;display:flex;"
        "flex-direction:column;align-items:center;justify-content:center;"
        "transform-origin:50% 50%}"
        ".tr-transitions-other .tto-a{background:#1b263b}"
        ".tr-transitions-other .tto-b{background:#e07a5f;opacity:0}"
        ".tr-transitions-other .tto-big{font-family:Inter,system-ui,sans-serif;"
        "font-size:280px;font-weight:900;line-height:1;letter-spacing:-0.04em;"
        "user-select:none}"
        ".tr-transitions-other .tto-a .tto-big{color:rgba(255,255,255,0.12)}"
        ".tr-transitions-other .tto-b .tto-big{color:rgba(0,0,0,0.12)}"
        ".tr-transitions-other .tto-label{font-family:Inter,system-ui,sans-serif;"
        "font-size:40px;font-weight:700;letter-spacing:6px;"
        "margin-top:12px;color:#ffffff}"
        ".tr-transitions-other .tto-flash{position:absolute;inset:0;display:block;"
        "opacity:0;pointer-events:none;background:#ffffff;"
        "transform-origin:50% 50%}"
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


_ABC_CATALOG_SEC = 5.0
_ABC_BARS_PX = 210
_ABC_MAX_BARS = 7


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


_BCR_CATALOG_SEC = 12.0
_BCR_RACE_SEC = 10.0
_BCR_PERIOD_SEC = 2.0
_BCR_K = 5
_BCR_MAX_SERIES = 8
_BCR_BAR_COUNT = 6
_BCR_TRACK_X = 248
_BCR_TRACK_W = 600
_BCR_PLOT_TOP = 280
_BCR_PLOT_H = 1404
_BCR_TICK_POOL = 5
_BCR_TICK_LABEL_W = 80
_BCR_INK = "#1f1d1b"
_BCR_ACCENT = "#c8452d"
_BCR_DEMO_PERIODS = ["2019", "2020", "2021", "2022", "2023", "2024"]
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


def _bcr_clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _bcr_fmt(value: float, prefix: str, suffix: str, decimals: int = 0) -> str:
    if decimals <= 0:
        body = f"{int(round(value)):,}"
    else:
        body = f"{value:,.{decimals}f}"
    return f"{prefix}{body}{suffix}"


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


def _bcr_parse_periods(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(part).strip() for part in raw if str(part).strip()]
    return []


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


def dv_bar_chart_race(ctx: "TemplateCtx") -> Piece:
    """Гонка столбиков: ряды меняются местами, лидер красный.

    Каталог DEMO 1 твинит ``width`` и пишет ``textContent`` из ``onUpdate``.
    Здесь GSAP ``scaleX`` / ``x`` / ``y`` / ``opacity``, числа заранее
    span-ами. Цвета бумаги ``#f5f3ef``, чернил ``#1f1d1b`` и акцента
    ``#c8452d`` как в каталоге — жест, не палитра канала. Inter как в
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


_CST_IN_BASE = 3.3
_CST_STILLNESS = 0.3
_CST_MAX = 8
_CST_LEFT = 100
_CST_RIGHT = 980
_CST_BASE = 1280
_CST_TOP = 460
_CST_ENTER_Y = 46
_CST_DRIFT_Y = -10
_CST_INK = "#f8fafc"
_CST_MUTED = "#c6ceda"
_CST_BORDER = "#475569"
_CST_SERIES = "#767a80"
_CST_BG = "#0a0a0a"
_CST_CALLOUT_FG = "#05070b"
_CST_ACCENTS = {
    "green": "#71f5a7",
    "blue": "#61a8ff",
    "violet": "#c5a3ff",
}


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


def _cst_token(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _cst_parse_csv(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(part).strip() for part in raw if str(part).strip()]
    return []


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


def _cst_power2_out(t: float) -> float:
    u = 1.0 - t
    return 1.0 - u * u


def _cst_clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def dv_chart_story(ctx: "TemplateCtx") -> Piece:
    """Столбики растут снизу по очереди, коллаут на акценте.

    Каталог DEMO 1 твинит ``attr.height`` / ``y`` и пишет ``textContent``
    из покадрового набора. Здесь GSAP ``scaleY`` / ``scaleX`` / ``y`` /
    ``opacity`` / ``scale``, числа заранее span-ами. Сцена ``#0a0a0a``,
    чернила ``#f8fafc``, акцент ``#71f5a7`` как в каталоге — жест, не
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


_CPR_IN_BASE = 1.4
_CPR_OUT_BASE = 0.5
_CPR_DISC = 734
_CPR_LEFT = 173
_CPR_TOP = 593
_CPR_FONT = 194
_CPR_BRAND = "#35d6a0"
_CPR_SURFACE = "#1b2938"
_CPR_FG = "#f4f7fb"
_CPR_BG = "#0a0a0a"
_CPR_THICK_LO = 4.0
_CPR_THICK_HI = 30.0
_CPR_THICK_DEFAULT = 12.0
_CPR_FPS = 30.0


def _cpr_clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _cpr_power2_out(t: float) -> float:
    u = 1.0 - _cpr_clamp(t, 0.0, 1.0)
    return 1.0 - u * u


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


def _cpr_angles(fill: float) -> tuple[float, float]:
    """Правая половина −180→0, левая 0→180. Заполнение с 12 часов по часовой."""
    p = _cpr_clamp(fill, 0.0, 100.0)
    right = -180.0 + (min(p, 50.0) / 50.0) * 180.0
    left = (max(p - 50.0, 0.0) / 50.0) * 180.0
    return right, left


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


def dv_conic_progress_ring(ctx: "TemplateCtx") -> Piece:
    """Кольцо заполняется от 12 часов, центр считает в такт.

    Каталог DEMO 1 твинит ``--ring-progress`` на conic-gradient и пишет
    ``textContent`` из ``onUpdate``. Здесь GSAP ``rotation`` двух половинок
    и заранее span-ы. Сцена ``#0a0a0a``, бренд ``#35d6a0``, дорожка
    ``#1b2938``, чернила ``#f4f7fb`` как в каталоге — жест, не палитра
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


_DCL_IN_BASE = 0.55
_DCL_OUT_BASE = 0.45
_DCL_DEFAULT_START = 82.0
_DCL_DEFAULT_END = 34.0
_DCL_DEFAULT_LABEL = "Retention"
_DCL_PATH = (
    "M 8 24 C 28 28, 44 43, 61 56 S 93 76, 112 92 "
    "S 144 111, 163 134 S 193 159, 213 186 S 239 211, 252 222")
_DCL_LINE = "#fb7185"
_DCL_END = "#fecdd3"
_DCL_FG = "#f8fafc"
_DCL_GLOOM = "#030507"
_DCL_ENTER_Y = 48
_DCL_FPS = 30.0
_DCL_GLOOM_PEAK = 0.46
_DCL_EP_AT = 0.94
_DCL_PAD_X = 97
_DCL_PAD_TOP = 173
_DCL_HEADER_H = 118
_DCL_LABEL_SIZE = 38
_DCL_VALUE_SIZE = 118
_DCL_VALUE_W = 280
_DCL_PLOT_LEFT = 97
_DCL_PLOT_TOP = 387
_DCL_PLOT_W = 886
_DCL_PLOT_H = 1379
_DCL_EP_D = 30
_DCL_VB_W = 260.0
_DCL_VB_H = 240.0
_DCL_EP_X = 252.0
_DCL_EP_Y = 222.0


def _dcl_clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _dcl_power2_out(t: float) -> float:
    u = 1.0 - _dcl_clamp(t, 0.0, 1.0)
    return 1.0 - u * u


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


def _dcl_num(raw: Any, default: float | None = None) -> float | None:
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


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


def dv_decline_chart(ctx: "TemplateCtx") -> Piece:
    """Линия рисуется вниз, число считает вниз, фон темнеет.

    Каталог DEMO 1 твинит ``strokeDashoffset``, ``filter`` и пишет
    ``textContent`` из ``onUpdate``. Здесь SVG-mask с ``scaleX`` на rect,
    gloom ``opacity``, заранее span-ы. Сцена градиент ``#152f3c`` /
    ``#101a25`` / ``#0c1118``, линия ``#fb7185``, точка ``#fecdd3``,
    чернила ``#f8fafc`` как в каталоге — жест, не палитра канала. Inter.
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
               f'width="260" height="240" fill="#fff"/></mask></defs>'
               f'<line class="dcl-grid" x1="8" y1="55" x2="252" y2="55"></line>'
               f'<line class="dcl-grid" x1="8" y1="120" x2="252" y2="120"></line>'
               f'<line class="dcl-grid" x1="8" y1="185" x2="252" y2="185"></line>'
               f'<path class="dcl-line" mask="url(#{mid})" '
               f'd="{_DCL_PATH}"></path></svg></div>'
               f'<div id="{eid}" class="dcl-ep" data-layout-allow-overlap="" '
               f'style="left:{ep_cx - ep_r:.1f}px;top:{ep_cy - ep_r:.1f}px">'
               f'</div></div></div>'],
        tweens=tweens)


_MLG_CATALOG_DUR = 7.0
_MLG_DRAW = 1.3
_MLG_AXIS_AT = 0.2
_MLG_AXIS_DUR = 0.5
_MLG_XL_AT = 0.25
_MLG_XL_STAGGER = 0.05
_MLG_XL_DUR = 0.4
_MLG_SERIES0_AT = 0.5
_MLG_SERIES_STAGGER = 0.35
_MLG_DOT_DUR = 0.35
_MLG_VAL_DELAY = 0.06
_MLG_VAL_DUR = 0.35
_MLG_LEGEND_AT = 2.3
_MLG_LEGEND_DUR = 0.5
_MLG_OUT_LEAD = 0.5
_MLG_OUT_DUR = 0.4
_MLG_OUT_Y = -36
_MLG_XL_Y = 18
_MLG_VAL_Y = 14
_MLG_ACCENT = "#0071e3"
_MLG_BLOB = "#45d6c8"
_MLG_COLORS = (_MLG_ACCENT, _MLG_BLOB)
_MLG_NAMES = ("Renders", "Projects")
_MLG_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MLG_PLOT_LEFT = 90
_MLG_PLOT_W = 740
_MLG_PLOT_TOP = 427
_MLG_PLOT_H = 889
_MLG_AXIS_PAD = 15
_MLG_DOT = 22
_MLG_VAL_W = 100
_MLG_VAL_H = 46
_MLG_XL_W = 100
_MLG_GAP = 28
_MLG_XL_BELOW = 36
_MLG_LEGEND_BELOW = 90
_MLG_MASK_PAD_X = 6
_MLG_MASK_PAD_Y = 20


def _mlg_play(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


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


def _mlg_token(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


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


def dv_mk_line_graph(ctx: "TemplateCtx") -> Piece:
    """Две линии рисуются слева направо, точки и числа садятся на фронт.

    Каталог DEMO 1 твинит ``strokeDashoffset`` и ``scale`` кругов. Здесь
    SVG-mask с ``scaleX`` на rect и HTML-точки. Бумага ``#ffffff``, чернила
    ``#1d1d1f``, акцент ``#0071e3``, вторая серия ``#45d6c8`` как в каталоге
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
            f'height="{_num(mask_h)}" fill="#fff"/></mask>')
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


_SPM_CATALOG_DUR = 12.0
_SPM_HL_DUR = 1.0
_SPM_SUB_AT = 0.4
_SPM_SUB_DUR = 0.6
_SPM_REG_AT = 1.0
_SPM_REG_DUR = 0.4
_SPM_REG_STAGGER = 0.08
_SPM_LAB_AT = 4.0
_SPM_LAB_DUR = 0.3
_SPM_LAB_STAGGER = 0.05
_SPM_LEG_AT = 5.5
_SPM_LEG_DUR = 0.6
_SPM_LEG_Y = 12
_SPM_SRC_AT = 6.0
_SPM_SRC_DUR = 0.5
_SPM_HI_AT = 6.5
_SPM_HI_GAP = 0.8
_SPM_HI_DUR = 0.5
_SPM_OUT_LEAD = 0.5
_SPM_OUT_DUR = 0.4
_SPM_OUT_Y = -20
_SPM_HIGHLIGHTS = ("MAD", "PVA", "NAV")
_SPM_TITLE = "PIB per cápita por Comunidad Autónoma"
_SPM_SUBTITLE = "Producto Interior Bruto per cápita, estimación 2024"
_SPM_SOURCE = "Fuente: Instituto Nacional de Estadística"
_SPM_LOW = "#7f1d1d"
_SPM_MID = "#dc2626"
_SPM_HIGH = "#fbbf24"
_SPM_MAP_LEFT = 90
_SPM_MAP_TOP = 340
_SPM_MAP_W = 740
_SPM_MAP_H = 610
_SPM_LAB_W = 88
_SPM_LAB_H = 32
_SPM_TINY = 8.0
_SPM_DOT_R = 14.0


def _spm_play(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


def _spm_times(duration: float) -> dict[str, float]:
    """Окно spain-map: каталог 12 с, короче — те же доли."""
    d = max(0.05, float(duration))
    s = d / _SPM_CATALOG_DUR if d < _SPM_CATALOG_DUR else 1.0
    out_dur = _SPM_OUT_DUR * s
    out_lead = _SPM_OUT_LEAD * s
    out_start = max(0.0, d - out_lead)
    if out_start + out_dur + 0.001 > d:
        out_dur = max(0.001, d - out_start - 0.001)
    return {
        "scale": s,
        "hl_dur": max(0.001, _SPM_HL_DUR * s),
        "sub_at": _SPM_SUB_AT * s,
        "sub_dur": max(0.001, _SPM_SUB_DUR * s),
        "reg_at": _SPM_REG_AT * s,
        "reg_dur": max(0.05, _SPM_REG_DUR * s),
        "reg_stagger": _SPM_REG_STAGGER * s,
        "lab_at": _SPM_LAB_AT * s,
        "lab_dur": max(0.001, _SPM_LAB_DUR * s),
        "lab_stagger": _SPM_LAB_STAGGER * s,
        "leg_at": _SPM_LEG_AT * s,
        "leg_dur": max(0.001, _SPM_LEG_DUR * s),
        "src_at": _SPM_SRC_AT * s,
        "src_dur": max(0.001, _SPM_SRC_DUR * s),
        "hi_at": _SPM_HI_AT * s,
        "hi_gap": _SPM_HI_GAP * s,
        "hi_dur": max(0.05, _SPM_HI_DUR * s),
        "out_start": out_start,
        "out_dur": out_dur,
        "kill_at": d,
    }


def _spm_num(raw: Any, default: float | None = None) -> float | None:
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _spm_floats(raw: Any) -> list[float]:
    values: list[float] = []
    if not isinstance(raw, (list, tuple)):
        return values
    for item in raw:
        parsed = _spm_num(item.get("value") if isinstance(item, dict) else item)
        if parsed is not None:
            values.append(parsed)
    return values


def _spm_lerp_hex(start: str, end: str, t: float) -> str:
    def rgb(token: str) -> tuple[int, int, int]:
        h = token.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    ar, ag, ab = rgb(start)
    br, bg, bb = rgb(end)
    t = min(max(t, 0.0), 1.0)
    return (f"#{round(ar + (br - ar) * t):02x}"
            f"{round(ag + (bg - ag) * t):02x}"
            f"{round(ab + (bb - ab) * t):02x}")


def _spm_color(value: float, lo: float, hi: float) -> str:
    span = hi - lo if hi > lo else 1.0
    t = min(max((value - lo) / span, 0.0), 1.0)
    if t < 0.5:
        return _spm_lerp_hex(_SPM_LOW, _SPM_MID, t / 0.5)
    return _spm_lerp_hex(_SPM_MID, _SPM_HIGH, (t - 0.5) / 0.5)


def _spm_xy(cx: float, cy: float) -> tuple[float, float]:
    vb_x, vb_y, vb_w, vb_h = SPM_VB
    x = _SPM_MAP_LEFT + (cx - vb_x) * _SPM_MAP_W / vb_w
    y = _SPM_MAP_TOP + (cy - vb_y) * _SPM_MAP_H / vb_h
    return x, y


def _spm_spec(params: dict[str, Any]
              ) -> tuple[list[tuple[dict[str, Any], float]], str, str, str,
                         list[str]] | None:
    """Регионы (shape, value), заголовок, подзаголовок, источник, highlight."""
    if not any(k in params and params[k] not in (None, "", [], ())
               for k in ("regions", "values", "labels", "title",
                         "headline", "subtitle")):
        return None
    by_abbr = {str(item["abbr"]): item for item in SPM_SHAPES}
    items: list[tuple[dict[str, Any], float]] = []
    raw = params.get("regions")
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if not isinstance(item, dict):
                continue
            abbr = str(item.get("abbr") or item.get("id") or "").upper()
            shape = by_abbr.get(abbr)
            if shape is None:
                name = str(item.get("name") or "").lower()
                for cand in SPM_SHAPES:
                    cname = str(cand["name"]).lower()
                    if name and (name in cname or cname in name):
                        shape = cand
                        break
            if shape is None:
                continue
            value = _spm_num(item.get("value", item.get("gdp")),
                             float(shape["gdp"]))
            if value is None:
                continue
            items.append((shape, value))
    if not items:
        values = _spm_floats(params.get("values"))
        for index, shape in enumerate(SPM_SHAPES):
            value = values[index] if index < len(values) else float(shape["gdp"])
            items.append((shape, value))
    if not items:
        return None
    items.sort(key=lambda pair: pair[1])
    title = str(params.get("title") or params.get("headline") or _SPM_TITLE)
    subtitle = str(params.get("subtitle") or _SPM_SUBTITLE)
    source = str(params.get("source") or _SPM_SOURCE)
    raw_hi = params.get("highlight") or params.get("highlights")
    highlights: list[str] = []
    if isinstance(raw_hi, (list, tuple)):
        highlights = [str(item).upper() for item in raw_hi if str(item).strip()]
    if not highlights:
        highlights = list(_SPM_HIGHLIGHTS)
    return items, title, subtitle, source, highlights


def dv_spain_map(ctx: "TemplateCtx") -> Piece:
    """Хороплет Испании: регионы вспыхивают от центра, MAD/PVA/NAV подсветка.

    Каталог DEMO 1 тянет topojson с CDN, твинит ``clipPath`` заголовка и
    ``filter`` подсветки. Здесь контуры запечены, вайп заголовка ``scaleX``,
    подсветка белым оверлеем. Градиент ``#0f172a``/``#1e293b``, шкала
    ``#7f1d1d``/``#dc2626``/``#fbbf24`` как в каталоге — жест карты, не
    палитра канала. Inter. ``-apple-system`` не ставим. ``mk-line-graph`` /
    ``.dv-bar`` / ``chart-story`` не трогаем.
    """
    spec = _spm_spec(ctx.params)
    if spec is None:
        return Piece()
    items, title, subtitle, source, highlights = spec
    node_id = f"spm-{ctx.index:02d}"
    times = _spm_times(ctx.duration)
    start = ctx.start
    sid = f"{node_id}-stage"
    wid = f"{node_id}-wipe"
    hid = f"{node_id}-hl"
    uid = f"{node_id}-sub"
    lid = f"{node_id}-leg"
    xid = f"{node_id}-src"
    lo = min(value for _shape, value in items)
    hi = max(value for _shape, value in items)
    count = len(items)
    mid = (count - 1) / 2.0 if count else 0.0
    tweens: list[str] = []
    paths: list[str] = []
    labels: list[str] = []
    region_ids: list[str] = []
    label_ids: list[str] = []
    hi_ids: list[str] = []
    hi_targets: dict[str, str] = {}
    vb_x, vb_y, vb_w, vb_h = SPM_VB

    for index, (shape, value) in enumerate(items):
        abbr = str(shape["abbr"])
        color = _spm_color(value, lo, hi)
        rid = f"{node_id}-r{index}"
        region_ids.append(rid)
        cx = float(shape["cx"])
        cy = float(shape["cy"])
        tiny = float(shape["w"]) < _SPM_TINY or float(shape["h"]) < _SPM_TINY
        if tiny:
            geom = (f'<circle id="{rid}" class="spm-region" '
                    f'cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(_SPM_DOT_R)}" '
                    f'fill="{_esc(color)}"></circle>')
            hi_geom = (
                f'<circle class="spm-hi" cx="{_num(cx)}" cy="{_num(cy)}" '
                f'r="{_num(_SPM_DOT_R)}" fill="#f8fafc"></circle>')
        else:
            geom = (f'<path id="{rid}" class="spm-region" '
                    f'd="{_esc(shape["d"])}" fill="{_esc(color)}"></path>')
            hi_geom = (f'<path class="spm-hi" d="{_esc(shape["d"])}" '
                       f'fill="#f8fafc"></path>')
        paths.append(geom)
        if abbr in highlights:
            hid_r = f"{node_id}-h{index}"
            hi_ids.append(hid_r)
            hi_targets[abbr] = hid_r
            paths.append(hi_geom.replace('class="spm-hi"',
                                         f'id="{hid_r}" class="spm-hi"', 1))
        lx, ly = _spm_xy(cx, cy)
        if tiny:
            lx += 28
        lab_id = f"{node_id}-l{index}"
        label_ids.append(lab_id)
        labels.append(
            f'<div id="{lab_id}" class="spm-lab" data-layout-allow-overlap="" '
            f'style="left:{lx - _SPM_LAB_W / 2:.1f}px;'
            f'top:{ly - _SPM_LAB_H / 2:.1f}px">{_esc(abbr)}</div>')
        delay = abs(index - mid) * times["reg_stagger"]
        tweens.append(
            f'tl.fromTo("#{rid}",{{opacity:0,scale:0}},'
            f'{{opacity:1,scale:1,duration:{_num(_spm_play(times["reg_dur"]))},'
            f'ease:"back.out(1.4)",immediateRender:false}},'
            f'{_num(start + times["reg_at"] + delay)});')
        lab_delay = abs(index - mid) * times["lab_stagger"]
        tweens.append(
            f'tl.fromTo("#{lab_id}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(_spm_play(times["lab_dur"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + times["lab_at"] + lab_delay)});')

    tweens.insert(0,
        f'tl.fromTo("#{wid}",{{scaleX:1}},'
        f'{{scaleX:0,duration:{_num(_spm_play(times["hl_dur"]))},'
        f'ease:"power2.inOut",immediateRender:false}},'
        f'{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{uid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_spm_play(times["sub_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["sub_at"])});')
    tweens.append(
        f'tl.fromTo("#{lid}",{{opacity:0,y:{_SPM_LEG_Y}}},'
        f'{{opacity:1,y:0,duration:{_num(_spm_play(times["leg_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["leg_at"])});')
    tweens.append(
        f'tl.fromTo("#{xid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_spm_play(times["src_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["src_at"])});')

    for hi_i, abbr in enumerate(highlights):
        hid_r = hi_targets.get(abbr)
        if not hid_r:
            continue
        t0 = times["hi_at"] + hi_i * times["hi_gap"]
        tweens.append(
            f'tl.fromTo("#{hid_r}",{{opacity:0}},'
            f'{{opacity:0.45,duration:{_num(_spm_play(times["hi_dur"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + t0)});')
        tweens.append(
            f'tl.fromTo("#{hid_r}",{{opacity:0.45}},'
            f'{{opacity:0,duration:{_num(_spm_play(times["hi_dur"]))},'
            f'ease:"power2.in",immediateRender:false}},'
            f'{_num(start + t0 + times["hi_dur"])});')
        # scale the matching region slightly during the pulse
        for index, (shape, _value) in enumerate(items):
            if str(shape["abbr"]) != abbr:
                continue
            rid = f"{node_id}-r{index}"
            tweens.append(
                f'tl.fromTo("#{rid}",{{scale:1}},'
                f'{{scale:1.08,duration:{_num(_spm_play(times["hi_dur"]))},'
                f'ease:"power2.out",immediateRender:false}},'
                f'{_num(start + t0)});')
            tweens.append(
                f'tl.fromTo("#{rid}",{{scale:1.08}},'
                f'{{scale:1,duration:{_num(_spm_play(times["hi_dur"]))},'
                f'ease:"power2.in",immediateRender:false}},'
                f'{_num(start + t0 + times["hi_dur"])});')
            break

    tweens.append(
        f'tl.fromTo("#{sid}",{{opacity:1,y:0}},'
        f'{{opacity:0,y:{_SPM_OUT_Y},duration:{_num(_spm_play(times["out_dur"]))},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["out_start"])});')

    kill_at = start + times["kill_at"]
    tweens.append(f'tl.set("#{sid}",{{y:0,opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{wid}",{{scaleX:1}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{uid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{lid}",{{opacity:0,y:{_SPM_LEG_Y}}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{xid}",{{opacity:0}},{_num(kill_at)});')
    for rid in region_ids:
        tweens.append(
            f'tl.set("#{rid}",{{opacity:0,scale:0}},{_num(kill_at)});')
    for lab_id in label_ids:
        tweens.append(f'tl.set("#{lab_id}",{{opacity:0}},{_num(kill_at)});')
    for hid_r in hi_ids:
        tweens.append(f'tl.set("#{hid_r}",{{opacity:0}},{_num(kill_at)});')

    view = f"{_num(vb_x)} {_num(vb_y)} {_num(vb_w)} {_num(vb_h)}"
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay spm-chart" {_timing(ctx)}>'
               f'<div class="spm-bg"></div>'
               f'<div id="{sid}" class="spm-stage">'
               f'<div class="spm-hl-clip" data-layout-allow-overlap="">'
               f'<div id="{hid}" class="spm-hl">{_esc(title)}</div>'
               f'<div id="{wid}" class="spm-wipe"></div></div>'
               f'<div id="{uid}" class="spm-sub" data-layout-allow-overlap="">'
               f'{_esc(subtitle)}</div>'
               f'<svg class="spm-svg" viewBox="{view}" '
               f'preserveAspectRatio="xMidYMid meet" aria-hidden="true">'
               f'{"".join(paths)}</svg>'
               f'{"".join(labels)}'
               f'<div id="{lid}" class="spm-legend" data-layout-allow-overlap="">'
               f'<span class="spm-legend-lab">Bajo</span>'
               f'<div class="spm-legend-bar"></div>'
               f'<span class="spm-legend-lab">Alto</span></div>'
               f'<div id="{xid}" class="spm-src" data-layout-allow-overlap="">'
               f'{_esc(source)}</div></div></div>'],
        tweens=tweens)


_SRF_IN_BASE = 1.5
_SRF_OUT_BASE = 0.4
_SRF_FILL_START_BASE = 0.2
_SRF_FILL_DURATION_BASE = 1.1
_SRF_POP_DURATION_BASE = 0.2
_SRF_FPS = 30.0
_SRF_DEFAULT_RATING = 4.8
_SRF_DEFAULT_COUNT = 5
_SRF_CARD_LEFT = 40
_SRF_CARD_W = 1000
_SRF_CARD_TOP = 750
_SRF_CARD_H = 420
_SRF_PAD = 32.0
_SRF_GAP = 28.0
_SRF_VALUE_W = 210.0
_SRF_VALUE_SIZE = 92.0
_SRF_STAR_MAX = 148.0
_SRF_MUTED = "#626d7e"
_SRF_BRAND = "#ffc83d"
_SRF_PATH = (
    "M50 0 61.8 36.2 100 36.2 69.1 58.6 80.9 95 50 72.4 "
    "19.1 95 30.9 58.6 0 36.2 38.2 36.2Z"
)


def _srf_clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _srf_power2_out(t: float) -> float:
    u = 1.0 - _srf_clamp(t, 0.0, 1.0)
    return 1.0 - u * u


def _srf_play(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


def _srf_num(raw: Any, default: float | None = None) -> float | None:
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


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


def dv_star_rating_fill(ctx: "TemplateCtx") -> Piece:
    """Золотые звёзды заливаются слева направо, число считает в такт.

    Каталог DEMO 1 твинит ``clip-path`` на слое заливки и пишет
    ``textContent`` из ``onUpdate``. Здесь SVG-mask с ``scaleX`` на rect,
    попа ``scale`` 1→1.06→1, заранее span-ы. Сцена ``#090d16``, карточка
    ``#1a2230``, бренд ``#ffc83d``, чернила ``#f4f7fb`` как в каталоге —
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
               f'fill="#fff"/></mask></defs>'
               f'<g mask="url(#{mid})">{"".join(fill_html)}</g></svg></div>'
               f'{value_html}</div></div>'],
        tweens=tweens)


_USM_CATALOG_DUR = 12.0
_USM_HL_DUR = 1.0
_USM_SUB_AT = 0.4
_USM_SUB_DUR = 0.6
_USM_REG_AT = 1.0
_USM_REG_DUR = 0.4
_USM_REG_STAGGER = 0.06
_USM_LAB_AT = 3.5
_USM_LAB_DUR = 0.3
_USM_LAB_STAGGER = 0.04
_USM_LEG_AT = 5.0
_USM_LEG_DUR = 0.6
_USM_LEG_Y = 12
_USM_SRC_AT = 5.5
_USM_SRC_DUR = 0.5
_USM_HI_AT = 6.5
_USM_HI_GAP = 0.8
_USM_HI_DUR = 0.5
_USM_OUT_LEAD = 0.5
_USM_OUT_DUR = 0.4
_USM_OUT_Y = -20
_USM_HIGHLIGHTS = ("CA", "NY", "TX", "FL", "NJ")
_USM_TITLE = "Population Density by State"
_USM_SUBTITLE = "Residents per square mile, 2024 Census estimates"
_USM_SOURCE = "Source: U.S. Census Bureau"
_USM_C0 = "#1e3a5f"
_USM_C1 = "#2563eb"
_USM_C2 = "#7c3aed"
_USM_C3 = "#ec4899"
_USM_MAX = 500.0
_USM_MAP_LEFT = 40
_USM_MAP_TOP = 310
_USM_MAP_W = 1000
_USM_MAP_H = 586
_USM_LAB_W = 52
_USM_LAB_H = 24
_USM_TINY = 8.0
_USM_DOT_R = 10.0


def _usm_play(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


def _usm_times(duration: float) -> dict[str, float]:
    """Окно us-map: каталог 12 с, короче — те же доли."""
    d = max(0.05, float(duration))
    s = d / _USM_CATALOG_DUR if d < _USM_CATALOG_DUR else 1.0
    out_dur = _USM_OUT_DUR * s
    out_lead = _USM_OUT_LEAD * s
    out_start = max(0.0, d - out_lead)
    if out_start + out_dur + 0.001 > d:
        out_dur = max(0.001, d - out_start - 0.001)
    return {
        "scale": s,
        "hl_dur": max(0.001, _USM_HL_DUR * s),
        "sub_at": _USM_SUB_AT * s,
        "sub_dur": max(0.001, _USM_SUB_DUR * s),
        "reg_at": _USM_REG_AT * s,
        "reg_dur": max(0.05, _USM_REG_DUR * s),
        "reg_stagger": _USM_REG_STAGGER * s,
        "lab_at": _USM_LAB_AT * s,
        "lab_dur": max(0.001, _USM_LAB_DUR * s),
        "lab_stagger": _USM_LAB_STAGGER * s,
        "leg_at": _USM_LEG_AT * s,
        "leg_dur": max(0.001, _USM_LEG_DUR * s),
        "src_at": _USM_SRC_AT * s,
        "src_dur": max(0.001, _USM_SRC_DUR * s),
        "hi_at": _USM_HI_AT * s,
        "hi_gap": _USM_HI_GAP * s,
        "hi_dur": max(0.05, _USM_HI_DUR * s),
        "out_start": out_start,
        "out_dur": out_dur,
        "kill_at": d,
    }


def _usm_num(raw: Any, default: float | None = None) -> float | None:
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _usm_floats(raw: Any) -> list[float]:
    values: list[float] = []
    if not isinstance(raw, (list, tuple)):
        return values
    for item in raw:
        parsed = _usm_num(item.get("value") if isinstance(item, dict) else item)
        if parsed is not None:
            values.append(parsed)
    return values


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


def _usm_color(value: float) -> str:
    t = min(max(value / _USM_MAX, 0.0), 1.0)
    if t < 0.33:
        return _usm_lerp_hex(_USM_C0, _USM_C1, t / 0.33)
    if t < 0.66:
        return _usm_lerp_hex(_USM_C1, _USM_C2, (t - 0.33) / 0.33)
    return _usm_lerp_hex(_USM_C2, _USM_C3, (t - 0.66) / 0.34)


def _usm_xy(cx: float, cy: float) -> tuple[float, float]:
    vb_x, vb_y, vb_w, vb_h = USM_VB
    x = _USM_MAP_LEFT + (cx - vb_x) * _USM_MAP_W / vb_w
    y = _USM_MAP_TOP + (cy - vb_y) * _USM_MAP_H / vb_h
    return x, y


def _usm_spec(params: dict[str, Any]
              ) -> tuple[list[tuple[dict[str, Any], float]], str, str, str,
                         list[str]] | None:
    """Штаты (shape, density), заголовок, подзаголовок, источник, highlight."""
    if not any(k in params and params[k] not in (None, "", [], ())
               for k in ("regions", "states", "values", "labels", "title",
                         "headline", "subtitle")):
        return None
    by_abbr = {str(item["abbr"]): item for item in USM_SHAPES}
    by_name = {str(item["name"]).lower(): item for item in USM_SHAPES}
    items: list[tuple[dict[str, Any], float]] = []
    raw = params.get("regions", params.get("states"))
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if not isinstance(item, dict):
                continue
            abbr = str(item.get("abbr") or item.get("id") or "").upper()
            shape = by_abbr.get(abbr)
            if shape is None:
                name = str(item.get("name") or "").lower()
                shape = by_name.get(name)
                if shape is None:
                    for cand in USM_SHAPES:
                        cname = str(cand["name"]).lower()
                        if name and (name in cname or cname in name):
                            shape = cand
                            break
            if shape is None:
                continue
            value = _usm_num(item.get("value", item.get("density")),
                             float(shape["density"]))
            if value is None:
                continue
            items.append((shape, value))
    if not items:
        values = _usm_floats(params.get("values"))
        for index, shape in enumerate(USM_SHAPES):
            value = (values[index] if index < len(values)
                     else float(shape["density"]))
            items.append((shape, value))
    if not items:
        return None
    items.sort(key=lambda pair: pair[1])
    title = str(params.get("title") or params.get("headline") or _USM_TITLE)
    subtitle = str(params.get("subtitle") or _USM_SUBTITLE)
    source = str(params.get("source") or _USM_SOURCE)
    raw_hi = params.get("highlight") or params.get("highlights")
    highlights: list[str] = []
    if isinstance(raw_hi, (list, tuple)):
        highlights = [str(item).upper() for item in raw_hi if str(item).strip()]
    if not highlights:
        highlights = list(_USM_HIGHLIGHTS)
    return items, title, subtitle, source, highlights


def dv_us_map(ctx: "TemplateCtx") -> Piece:
    """Хороплет США: штаты вспыхивают от центра, CA/NY/TX/FL/NJ подсветка.

    Каталог DEMO 1 тянет topojson с CDN, твинит ``clipPath`` заголовка и
    ``filter`` подсветки. Здесь контуры запечены, вайп заголовка ``scaleX``,
    подсветка белым оверлеем. Градиент ``#0f172a``/``#1e293b``, шкала
    ``#1e3a5f``/``#2563eb``/``#7c3aed``/``#ec4899`` как в каталоге — жест
    карты, не палитра канала. Inter. ``-apple-system`` не ставим.
    ``spain-map`` / ``.dv-bar`` / ``star-rating-fill`` не трогаем.
    """
    spec = _usm_spec(ctx.params)
    if spec is None:
        return Piece()
    items, title, subtitle, source, highlights = spec
    node_id = f"usm-{ctx.index:02d}"
    times = _usm_times(ctx.duration)
    start = ctx.start
    sid = f"{node_id}-stage"
    wid = f"{node_id}-wipe"
    hid = f"{node_id}-hl"
    uid = f"{node_id}-sub"
    lid = f"{node_id}-leg"
    xid = f"{node_id}-src"
    count = len(items)
    mid = (count - 1) / 2.0 if count else 0.0
    tweens: list[str] = []
    paths: list[str] = []
    labels: list[str] = []
    region_ids: list[str] = []
    label_ids: list[str] = []
    hi_ids: list[str] = []
    hi_targets: dict[str, str] = {}
    vb_x, vb_y, vb_w, vb_h = USM_VB

    for index, (shape, value) in enumerate(items):
        abbr = str(shape["abbr"])
        color = _usm_color(value)
        rid = f"{node_id}-r{index}"
        region_ids.append(rid)
        cx = float(shape["cx"])
        cy = float(shape["cy"])
        tiny = float(shape["w"]) < _USM_TINY or float(shape["h"]) < _USM_TINY
        if tiny:
            geom = (f'<circle id="{rid}" class="usm-region" '
                    f'cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(_USM_DOT_R)}" '
                    f'fill="{_esc(color)}"></circle>')
            hi_geom = (
                f'<circle class="usm-hi" cx="{_num(cx)}" cy="{_num(cy)}" '
                f'r="{_num(_USM_DOT_R)}" fill="#f8fafc"></circle>')
        else:
            geom = (f'<path id="{rid}" class="usm-region" '
                    f'd="{_esc(shape["d"])}" fill="{_esc(color)}"></path>')
            hi_geom = (f'<path class="usm-hi" d="{_esc(shape["d"])}" '
                       f'fill="#f8fafc"></path>')
        paths.append(geom)
        if abbr in highlights:
            hid_r = f"{node_id}-h{index}"
            hi_ids.append(hid_r)
            hi_targets[abbr] = hid_r
            paths.append(hi_geom.replace('class="usm-hi"',
                                         f'id="{hid_r}" class="usm-hi"', 1))
        lx, ly = _usm_xy(cx, cy)
        if tiny:
            lx += 22
        lab_id = f"{node_id}-l{index}"
        label_ids.append(lab_id)
        labels.append(
            f'<div id="{lab_id}" class="usm-lab" data-layout-allow-overlap="" '
            f'style="left:{lx - _USM_LAB_W / 2:.1f}px;'
            f'top:{ly - _USM_LAB_H / 2:.1f}px">{_esc(abbr)}</div>')
        delay = abs(index - mid) * times["reg_stagger"]
        tweens.append(
            f'tl.fromTo("#{rid}",{{opacity:0,scale:0}},'
            f'{{opacity:1,scale:1,duration:{_num(_usm_play(times["reg_dur"]))},'
            f'ease:"back.out(1.4)",immediateRender:false}},'
            f'{_num(start + times["reg_at"] + delay)});')
        lab_delay = abs(index - mid) * times["lab_stagger"]
        tweens.append(
            f'tl.fromTo("#{lab_id}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(_usm_play(times["lab_dur"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + times["lab_at"] + lab_delay)});')

    tweens.insert(0,
        f'tl.fromTo("#{wid}",{{scaleX:1}},'
        f'{{scaleX:0,duration:{_num(_usm_play(times["hl_dur"]))},'
        f'ease:"power2.inOut",immediateRender:false}},'
        f'{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{uid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_usm_play(times["sub_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["sub_at"])});')
    tweens.append(
        f'tl.fromTo("#{lid}",{{opacity:0,y:{_USM_LEG_Y}}},'
        f'{{opacity:1,y:0,duration:{_num(_usm_play(times["leg_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["leg_at"])});')
    tweens.append(
        f'tl.fromTo("#{xid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_usm_play(times["src_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["src_at"])});')

    for hi_i, abbr in enumerate(highlights):
        hid_r = hi_targets.get(abbr)
        if not hid_r:
            continue
        t0 = times["hi_at"] + hi_i * times["hi_gap"]
        tweens.append(
            f'tl.fromTo("#{hid_r}",{{opacity:0}},'
            f'{{opacity:0.45,duration:{_num(_usm_play(times["hi_dur"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + t0)});')
        tweens.append(
            f'tl.fromTo("#{hid_r}",{{opacity:0.45}},'
            f'{{opacity:0,duration:{_num(_usm_play(times["hi_dur"]))},'
            f'ease:"power2.in",immediateRender:false}},'
            f'{_num(start + t0 + times["hi_dur"])});')
        for index, (shape, _value) in enumerate(items):
            if str(shape["abbr"]) != abbr:
                continue
            rid = f"{node_id}-r{index}"
            tweens.append(
                f'tl.fromTo("#{rid}",{{scale:1}},'
                f'{{scale:1.08,duration:{_num(_usm_play(times["hi_dur"]))},'
                f'ease:"power2.out",immediateRender:false}},'
                f'{_num(start + t0)});')
            tweens.append(
                f'tl.fromTo("#{rid}",{{scale:1.08}},'
                f'{{scale:1,duration:{_num(_usm_play(times["hi_dur"]))},'
                f'ease:"power2.in",immediateRender:false}},'
                f'{_num(start + t0 + times["hi_dur"])});')
            break

    tweens.append(
        f'tl.fromTo("#{sid}",{{opacity:1,y:0}},'
        f'{{opacity:0,y:{_USM_OUT_Y},duration:{_num(_usm_play(times["out_dur"]))},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["out_start"])});')

    kill_at = start + times["kill_at"]
    tweens.append(f'tl.set("#{sid}",{{y:0,opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{wid}",{{scaleX:1}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{uid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(
        f'tl.set("#{lid}",{{opacity:0,y:{_USM_LEG_Y}}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{xid}",{{opacity:0}},{_num(kill_at)});')
    for rid in region_ids:
        tweens.append(
            f'tl.set("#{rid}",{{opacity:0,scale:0}},{_num(kill_at)});')
    for lab_id in label_ids:
        tweens.append(f'tl.set("#{lab_id}",{{opacity:0}},{_num(kill_at)});')
    for hid_r in hi_ids:
        tweens.append(f'tl.set("#{hid_r}",{{opacity:0}},{_num(kill_at)});')

    view = f"{_num(vb_x)} {_num(vb_y)} {_num(vb_w)} {_num(vb_h)}"
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay usm-chart" {_timing(ctx)}>'
               f'<div class="usm-bg"></div>'
               f'<div id="{sid}" class="usm-stage">'
               f'<div class="usm-hl-clip" data-layout-allow-overlap="">'
               f'<div id="{hid}" class="usm-hl">{_esc(title)}</div>'
               f'<div id="{wid}" class="usm-wipe"></div></div>'
               f'<div id="{uid}" class="usm-sub" data-layout-allow-overlap="">'
               f'{_esc(subtitle)}</div>'
               f'<svg class="usm-svg" viewBox="{view}" '
               f'preserveAspectRatio="xMidYMid meet" aria-hidden="true">'
               f'{"".join(paths)}</svg>'
               f'{"".join(labels)}'
               f'<div id="{lid}" class="usm-legend" data-layout-allow-overlap="">'
               f'<span class="usm-legend-lab">Low</span>'
               f'<div class="usm-legend-bar"></div>'
               f'<span class="usm-legend-lab">High</span></div>'
               f'<div id="{xid}" class="usm-src" data-layout-allow-overlap="">'
               f'{_esc(source)}</div></div></div>'],
        tweens=tweens)


_UMF_CATALOG_DUR = 12.0
_UMF_HL_DUR = 1.0
_UMF_SUB_AT = 0.3
_UMF_SUB_DUR = 0.5
_UMF_ST_AT = 0.6
_UMF_ST_DUR = 0.8
_UMF_DOT_AT = 1.5
_UMF_DOT_DUR = 0.4
_UMF_DOT_STAGGER = 0.05
_UMF_LAB_AT = 2.5
_UMF_LAB_DUR = 0.3
_UMF_LAB_STAGGER = 0.05
_UMF_ARC_AT = 3.5
_UMF_ARC_DUR = 1.0
_UMF_ARC_STAGGER = 0.2
_UMF_TD_AT = 7.0
_UMF_TD_DUR = 1.5
_UMF_TD_STAGGER = 0.1
_UMF_TD_FADE = 0.3
_UMF_SRC_AT = 9.0
_UMF_SRC_DUR = 0.6
_UMF_TITLE = "Interstate Flow Connections"
_UMF_SUBTITLE = "Relative volume of major city-to-city corridors"
_UMF_SOURCE = "Source: Illustrative data"
_UMF_MAP_LEFT = 40
_UMF_MAP_TOP = 310
_UMF_MAP_W = 1000
_UMF_MAP_H = 562
_UMF_CITY_R = 10.0
_UMF_TDOT = 12.0
_UMF_MIN_W = 1.5
_UMF_MAX_W = 4.0
_UMF_MAX_VOL = 100.0
_UMF_LAB_DX = 12.0
_UMF_LAB_DY = -18.0


def _umf_play(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


def _umf_times(duration: float) -> dict[str, float]:
    """Окно us-map-flow: каталог 12 с, короче — те же доли."""
    d = max(0.05, float(duration))
    s = d / _UMF_CATALOG_DUR if d < _UMF_CATALOG_DUR else 1.0
    return {
        "scale": s,
        "hl_dur": max(0.001, _UMF_HL_DUR * s),
        "sub_at": _UMF_SUB_AT * s,
        "sub_dur": max(0.001, _UMF_SUB_DUR * s),
        "st_at": _UMF_ST_AT * s,
        "st_dur": max(0.001, _UMF_ST_DUR * s),
        "dot_at": _UMF_DOT_AT * s,
        "dot_dur": max(0.001, _UMF_DOT_DUR * s),
        "dot_stagger": _UMF_DOT_STAGGER * s,
        "lab_at": _UMF_LAB_AT * s,
        "lab_dur": max(0.001, _UMF_LAB_DUR * s),
        "lab_stagger": _UMF_LAB_STAGGER * s,
        "arc_at": _UMF_ARC_AT * s,
        "arc_dur": max(0.001, _UMF_ARC_DUR * s),
        "arc_stagger": _UMF_ARC_STAGGER * s,
        "td_at": _UMF_TD_AT * s,
        "td_dur": max(0.001, _UMF_TD_DUR * s),
        "td_stagger": _UMF_TD_STAGGER * s,
        "td_fade": max(0.001, _UMF_TD_FADE * s),
        "src_at": _UMF_SRC_AT * s,
        "src_dur": max(0.001, _UMF_SRC_DUR * s),
        "kill_at": d,
    }


def _umf_num(raw: Any, default: float | None = None) -> float | None:
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _umf_xy(x: float, y: float) -> tuple[float, float]:
    vb_x, vb_y, vb_w, vb_h = UMF_VB
    sx = _UMF_MAP_LEFT + (x - vb_x) * _UMF_MAP_W / vb_w
    sy = _UMF_MAP_TOP + (y - vb_y) * _UMF_MAP_H / vb_h
    return sx, sy


def _umf_quad(x1: float, y1: float, cx: float, cy: float,
              x2: float, y2: float, t: float) -> tuple[float, float]:
    u = 1.0 - t
    return (u * u * x1 + 2.0 * u * t * cx + t * t * x2,
            u * u * y1 + 2.0 * u * t * cy + t * t * y2)


def _umf_spec(params: dict[str, Any]
              ) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                         str, str, str] | None:
    """Города, дуги, заголовок, подзаголовок, источник."""
    if not any(k in params and params[k] not in (None, "", [], ())
               for k in ("cities", "flows", "title", "headline", "subtitle")):
        return None
    cities: list[dict[str, Any]] = []
    raw_c = params.get("cities")
    if isinstance(raw_c, (list, tuple)):
        for item in raw_c:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            x = _umf_num(item.get("x"))
            y = _umf_num(item.get("y"))
            if not name or x is None or y is None:
                continue
            cities.append({"name": name, "x": x, "y": y})
    if not cities:
        cities = [{"name": str(item["name"]), "x": float(item["x"]),
                   "y": float(item["y"])} for item in UMF_CITIES]
    by_name = {str(item["name"]): item for item in cities}
    flows: list[dict[str, Any]] = []
    raw_f = params.get("flows")
    src_flows = raw_f if isinstance(raw_f, (list, tuple)) and raw_f else UMF_FLOWS
    for item in src_flows:
        if not isinstance(item, dict):
            continue
        src = str(item.get("from") or item.get("source") or "").strip()
        dst = str(item.get("to") or item.get("target") or "").strip()
        if src not in by_name or dst not in by_name:
            continue
        vol = _umf_num(item.get("volume", item.get("value")), 50.0)
        if vol is None:
            continue
        flows.append({"from": src, "to": dst, "volume": vol})
    if not cities or not flows:
        return None
    title = str(params.get("title") or params.get("headline") or _UMF_TITLE)
    subtitle = str(params.get("subtitle") or _UMF_SUBTITLE)
    source = str(params.get("source") or _UMF_SOURCE)
    return cities, flows, title, subtitle, source


def dv_us_map_flow(ctx: "TemplateCtx") -> Piece:
    """Карта коридоров США: дуги между городами, точки бегут по дуге.

    Каталог DEMO 1 тянет topojson, твинит ``clipPath`` заголовка,
    ``strokeDashoffset`` дуг и ``onUpdate``/``getPointAtLength`` точек.
    Здесь контуры и xy запечены, вайп заголовка ``scaleX``, дуги растут
    ``scale`` от города-источника, точки едут GSAP ``x``/``y`` по квадратике.
    Градиент ``#0f172a``/``#1e293b``, дуги ``#3b82f6``, точки ``#60a5fa``
    как в каталоге — жест карты, не палитра канала. Inter.
    ``-apple-system`` не ставим. ``us-map`` / ``spain-map`` / ``.dv-bar``
    не трогаем.
    """
    spec = _umf_spec(ctx.params)
    if spec is None:
        return Piece()
    cities, flows, title, subtitle, source = spec
    node_id = f"umf-{ctx.index:02d}"
    times = _umf_times(ctx.duration)
    start = ctx.start
    sid = f"{node_id}-stage"
    wid = f"{node_id}-wipe"
    hid = f"{node_id}-hl"
    uid = f"{node_id}-sub"
    xid = f"{node_id}-src"
    tweens: list[str] = []
    paths: list[str] = []
    region_ids: list[str] = []
    city_html: list[str] = []
    city_ids: list[str] = []
    labels: list[str] = []
    label_ids: list[str] = []
    arcs: list[str] = []
    arc_ids: list[str] = []
    dots: list[str] = []
    dot_ids: list[str] = []
    vb_x, vb_y, vb_w, vb_h = UMF_VB
    by_name = {str(item["name"]): item for item in cities}

    for index, shape in enumerate(UMF_SHAPES):
        rid = f"{node_id}-r{index}"
        region_ids.append(rid)
        paths.append(
            f'<path id="{rid}" class="umf-region" d="{_esc(shape["d"])}"></path>')
        tweens.append(
            f'tl.fromTo("#{rid}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(_umf_play(times["st_dur"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + times["st_at"])});')

    for index, city in enumerate(cities):
        cid = f"{node_id}-c{index}"
        lab_id = f"{node_id}-l{index}"
        city_ids.append(cid)
        label_ids.append(lab_id)
        cx = float(city["x"])
        cy = float(city["y"])
        city_html.append(
            f'<circle id="{cid}" class="umf-city" cx="{_num(cx)}" '
            f'cy="{_num(cy)}" r="{_num(_UMF_CITY_R)}"></circle>')
        lx, ly = _umf_xy(cx, cy)
        labels.append(
            f'<div id="{lab_id}" class="umf-lab" data-layout-allow-overlap="" '
            f'style="left:{lx + _UMF_LAB_DX:.1f}px;'
            f'top:{ly + _UMF_LAB_DY:.1f}px">{_esc(city["name"])}</div>')
        delay = index * times["dot_stagger"]
        tweens.append(
            f'tl.fromTo("#{cid}",{{opacity:0,scale:0}},'
            f'{{opacity:1,scale:1,duration:{_num(_umf_play(times["dot_dur"]))},'
            f'ease:"back.out(1.7)",immediateRender:false}},'
            f'{_num(start + times["dot_at"] + delay)});')
        lab_delay = index * times["lab_stagger"]
        tweens.append(
            f'tl.fromTo("#{lab_id}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(_umf_play(times["lab_dur"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + times["lab_at"] + lab_delay)});')

    half = _UMF_TDOT / 2.0
    for index, flow in enumerate(flows):
        src = by_name[str(flow["from"])]
        dst = by_name[str(flow["to"])]
        x1 = float(src["x"])
        y1 = float(src["y"])
        x2 = float(dst["x"])
        y2 = float(dst["y"])
        mid_x = (x1 + x2) / 2.0
        mid_y = min(y1, y2) - abs(x2 - x1) * 0.15
        vol = min(max(float(flow["volume"]), 0.0), _UMF_MAX_VOL)
        t = vol / _UMF_MAX_VOL
        stroke_w = _UMF_MIN_W + t * (_UMF_MAX_W - _UMF_MIN_W)
        arc_op = 0.4 + t * 0.6
        aid = f"{node_id}-a{index}"
        did = f"{node_id}-d{index}"
        arc_ids.append(aid)
        dot_ids.append(did)
        d_attr = (f"M{_num(x1)},{_num(y1)} Q{_num(mid_x)},{_num(mid_y)} "
                  f"{_num(x2)},{_num(y2)}")
        arcs.append(
            f'<path id="{aid}" class="umf-arc" d="{_esc(d_attr)}" '
            f'stroke-width="{_num(stroke_w)}" '
            f'style="transform-origin:{_num(x1)}px {_num(y1)}px"></path>')
        sx1, sy1 = _umf_xy(x1, y1)
        sxm, sym = _umf_xy(*_umf_quad(x1, y1, mid_x, mid_y, x2, y2, 0.5))
        sx2, sy2 = _umf_xy(x2, y2)
        dots.append(
            f'<div id="{did}" class="umf-tdot" data-layout-allow-overlap="" '
            f'style="left:{sx1 - half:.1f}px;top:{sy1 - half:.1f}px"></div>')
        arc_delay = index * times["arc_stagger"]
        tweens.append(
            f'tl.fromTo("#{aid}",{{opacity:0,scale:0}},'
            f'{{opacity:{_num(arc_op)},scale:1,'
            f'duration:{_num(_umf_play(times["arc_dur"]))},'
            f'ease:"power2.inOut",immediateRender:false}},'
            f'{_num(start + times["arc_at"] + arc_delay)});')
        td_delay = index * times["td_stagger"]
        t0 = start + times["td_at"] + td_delay
        seg = times["td_dur"] / 2.0
        tweens.append(
            f'tl.fromTo("#{did}",{{opacity:0}},'
            f'{{opacity:0.9,duration:{_num(_umf_play(0.001))},'
            f'ease:"none",immediateRender:false}},'
            f'{_num(t0)});')
        tweens.append(
            f'tl.fromTo("#{did}",{{x:0,y:0}},'
            f'{{x:{_num(sxm - sx1)},y:{_num(sym - sy1)},'
            f'duration:{_num(_umf_play(seg))},'
            f'ease:"power1.in",immediateRender:false}},'
            f'{_num(t0)});')
        tweens.append(
            f'tl.fromTo("#{did}",{{x:{_num(sxm - sx1)},y:{_num(sym - sy1)}}},'
            f'{{x:{_num(sx2 - sx1)},y:{_num(sy2 - sy1)},'
            f'duration:{_num(_umf_play(seg))},'
            f'ease:"power1.out",immediateRender:false}},'
            f'{_num(t0 + seg)});')
        tweens.append(
            f'tl.fromTo("#{did}",{{opacity:0.9}},'
            f'{{opacity:0,duration:{_num(_umf_play(times["td_fade"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(t0 + times["td_dur"])});')

    tweens.insert(0,
        f'tl.fromTo("#{wid}",{{scaleX:1}},'
        f'{{scaleX:0,duration:{_num(_umf_play(times["hl_dur"]))},'
        f'ease:"power2.inOut",immediateRender:false}},'
        f'{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{uid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_umf_play(times["sub_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["sub_at"])});')
    tweens.append(
        f'tl.fromTo("#{xid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_umf_play(times["src_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["src_at"])});')

    kill_at = start + times["kill_at"]
    tweens.append(f'tl.set("#{wid}",{{scaleX:1}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{uid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{xid}",{{opacity:0}},{_num(kill_at)});')
    for rid in region_ids:
        tweens.append(f'tl.set("#{rid}",{{opacity:0}},{_num(kill_at)});')
    for cid in city_ids:
        tweens.append(
            f'tl.set("#{cid}",{{opacity:0,scale:0}},{_num(kill_at)});')
    for lab_id in label_ids:
        tweens.append(f'tl.set("#{lab_id}",{{opacity:0}},{_num(kill_at)});')
    for aid in arc_ids:
        tweens.append(
            f'tl.set("#{aid}",{{opacity:0,scale:0}},{_num(kill_at)});')
    for did in dot_ids:
        tweens.append(
            f'tl.set("#{did}",{{opacity:0,x:0,y:0}},{_num(kill_at)});')

    view = f"{_num(vb_x)} {_num(vb_y)} {_num(vb_w)} {_num(vb_h)}"
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay umf-chart" {_timing(ctx)}>'
               f'<div class="umf-bg"></div>'
               f'<div id="{sid}" class="umf-stage">'
               f'<div class="umf-hl-clip" data-layout-allow-overlap="">'
               f'<div id="{hid}" class="umf-hl">{_esc(title)}</div>'
               f'<div id="{wid}" class="umf-wipe"></div></div>'
               f'<div id="{uid}" class="umf-sub" data-layout-allow-overlap="">'
               f'{_esc(subtitle)}</div>'
               f'<svg class="umf-svg" viewBox="{view}" '
               f'preserveAspectRatio="xMidYMid meet" aria-hidden="true">'
               f'{"".join(paths)}{"".join(arcs)}{"".join(city_html)}</svg>'
               f'{"".join(labels)}{"".join(dots)}'
               f'<div id="{xid}" class="umf-src" data-layout-allow-overlap="">'
               f'{_esc(source)}</div></div></div>'],
        tweens=tweens)


# ---------- us-map-hex constants ----------
_UMH_CATALOG_DUR = 10.0
_UMH_HL_DUR = 1.0
_UMH_SUB_AT = 0.3
_UMH_SUB_DUR = 0.5
_UMH_HEX_AT = 0.8
_UMH_HEX_DUR = 0.4
_UMH_HEX_STAGGER = 0.03
_UMH_LAB_AT = 3.5
_UMH_LAB_DUR = 0.3
_UMH_LAB_STAGGER = 0.02
_UMH_LEG_AT = 5.0
_UMH_LEG_DUR = 0.6
_UMH_SRC_AT = 5.5
_UMH_SRC_DUR = 0.5
_UMH_HI_AT = 6.0
_UMH_HI_DUR = 0.4
_UMH_HI_GAP = 0.08
_UMH_HI2_AT = 6.8
_UMH_HI3_AT = 7.4
_UMH_HI4_AT = 8.0
_UMH_OUT_Y = 60
_UMH_MAP_LEFT = 40
_UMH_MAP_TOP = 140


def _umh_play(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


def _umh_times(duration: float) -> dict[str, float]:
    """Window us-map-hex: catalog 10 s, shorter — same ratios."""
    d = max(0.05, float(duration))
    s = d / _UMH_CATALOG_DUR if d < _UMH_CATALOG_DUR else 1.0
    return {
        "scale": s,
        "hl_dur": max(0.001, _UMH_HL_DUR * s),
        "sub_at": _UMH_SUB_AT * s,
        "sub_dur": max(0.001, _UMH_SUB_DUR * s),
        "hex_at": _UMH_HEX_AT * s,
        "hex_dur": max(0.001, _UMH_HEX_DUR * s),
        "hex_stagger": _UMH_HEX_STAGGER * s,
        "lab_at": _UMH_LAB_AT * s,
        "lab_dur": max(0.001, _UMH_LAB_DUR * s),
        "lab_stagger": _UMH_LAB_STAGGER * s,
        "leg_at": _UMH_LEG_AT * s,
        "leg_dur": max(0.001, _UMH_LEG_DUR * s),
        "src_at": _UMH_SRC_AT * s,
        "src_dur": max(0.001, _UMH_SRC_DUR * s),
        "hi_at": _UMH_HI_AT * s,
        "hi_dur": max(0.001, _UMH_HI_DUR * s),
        "hi_gap": _UMH_HI_GAP * s,
        "hi2_at": _UMH_HI2_AT * s,
        "hi3_at": _UMH_HI3_AT * s,
        "hi4_at": _UMH_HI4_AT * s,
        "out_start": max(0.001, d - 0.8),
        "out_dur": max(0.001, 0.6 * s),
        "kill_at": max(0.001, d - 0.05),
    }


def dv_us_map_hex(ctx: "TemplateCtx") -> Piece:
    """Hex grid map USA: hexagons scale from center, top-5 pulse.

    Catalog DEMO 1 computes hex geometry in JS, tweens ``filter:brightness``
    for highlights. Here hexes are pre-baked, wipe is ``scaleX``,
    highlights use white overlay ``opacity`` (no ``filter`` tween).
    Gradient ``#0f172a``/``#1e293b``, amber scale ``#451a03``→``#f59e0b``→
    ``#fef3c7`` as in catalog. Inter.
    """
    params = ctx.params
    if not any(k in params and params[k] not in (None, "", [], ())
               for k in ("regions", "states", "values", "labels", "title",
                         "headline", "subtitle")):
        return Piece()

    hexes = umh_build_hexes()
    title = str(params.get("title") or params.get("headline") or UMH_TITLE)
    subtitle = str(params.get("subtitle") or UMH_SUBTITLE)
    source = str(params.get("source") or UMH_SOURCE)
    leg_low = str(params.get("legend_low") or UMH_LEG_LOW)
    leg_high = str(params.get("legend_high") or UMH_LEG_HIGH)
    raw_hi = params.get("highlight") or params.get("highlights")
    highlights: list[str] = []
    if isinstance(raw_hi, (list, tuple)):
        highlights = [str(item).upper() for item in raw_hi if str(item).strip()]
    if not highlights:
        highlights = list(UMH_TOP5)

    node_id = f"umh-{ctx.index:02d}"
    times = _umh_times(ctx.duration)
    start = ctx.start
    sid = f"{node_id}-stage"
    wid = f"{node_id}-wipe"
    uid = f"{node_id}-sub"
    lid = f"{node_id}-leg"
    xid = f"{node_id}-src"

    tweens: list[str] = []
    polys: list[str] = []
    text_els: list[str] = []
    hi_ids: list[str] = []
    hex_ids: list[str] = []
    lab_ids: list[str] = []
    hi_hex_map: dict[str, str] = {}

    for i, h in enumerate(hexes):
        pid = f"{node_id}-p{i}"
        tid = f"{node_id}-t{i}"
        hex_ids.append(pid)
        lab_ids.append(tid)
        abbr = h["abbr"]
        text_cls = "umh-text umh-text-light" if h["light_text"] else "umh-text"
        polys.append(
            f'<polygon id="{pid}" class="umh-poly" '
            f'points="{h["points"]}" fill="{_esc(h["color"])}"></polygon>')
        text_els.append(
            f'<text id="{tid}" class="{text_cls}" '
            f'x="{h["cx"]:.1f}" y="{h["cy"]:.1f}">{_esc(abbr)}</text>')
        if abbr in highlights:
            hid_r = f"{node_id}-h{i}"
            hi_ids.append(hid_r)
            hi_hex_map[abbr] = hid_r
            polys.append(
                f'<polygon id="{hid_r}" class="umh-hi" '
                f'points="{h["points"]}" fill="#f8fafc"></polygon>')

        delay = i * times["hex_stagger"]
        tweens.append(
            f'tl.fromTo("#{pid}",{{opacity:0,scale:0}},'
            f'{{opacity:1,scale:1,duration:{_num(_umh_play(times["hex_dur"]))},'
            f'ease:"back.out(1.4)",immediateRender:false}},'
            f'{_num(start + times["hex_at"] + delay)});')
        lab_delay = i * times["lab_stagger"]
        tweens.append(
            f'tl.fromTo("#{tid}",{{opacity:0}},'
            f'{{opacity:1,duration:{_num(_umh_play(times["lab_dur"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + times["lab_at"] + lab_delay)});')

    tweens.insert(0,
        f'tl.fromTo("#{wid}",{{scaleX:1}},'
        f'{{scaleX:0,duration:{_num(_umh_play(times["hl_dur"]))},'
        f'ease:"power2.inOut",immediateRender:false}},'
        f'{_num(start)});')
    tweens.append(
        f'tl.fromTo("#{uid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_umh_play(times["sub_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["sub_at"])});')
    tweens.append(
        f'tl.fromTo("#{lid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_umh_play(times["leg_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["leg_at"])});')
    tweens.append(
        f'tl.fromTo("#{xid}",{{opacity:0}},'
        f'{{opacity:1,duration:{_num(_umh_play(times["src_dur"]))},'
        f'ease:"power2.out",immediateRender:false}},'
        f'{_num(start + times["src_at"])});')

    for hi_i, abbr in enumerate(highlights):
        hid_r = hi_hex_map.get(abbr)
        if not hid_r:
            continue
        d = _umh_play(times["hi_dur"])
        gap = hi_i * times["hi_gap"]
        tweens.append(
            f'tl.fromTo("#{hid_r}",{{opacity:0}},'
            f'{{opacity:0.35,duration:{_num(d)},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + times["hi_at"] + gap)});')
        tweens.append(
            f'tl.fromTo("#{hid_r}",{{opacity:0.35}},'
            f'{{opacity:0,duration:{_num(d)},'
            f'ease:"power2.in",immediateRender:false}},'
            f'{_num(start + times["hi2_at"] + gap)});')
        tweens.append(
            f'tl.fromTo("#{hid_r}",{{opacity:0}},'
            f'{{opacity:0.25,duration:{_num(_umh_play(0.3 * times["scale"]))},'
            f'ease:"power2.out",immediateRender:false}},'
            f'{_num(start + times["hi3_at"] + gap * 0.75)});')
        tweens.append(
            f'tl.fromTo("#{hid_r}",{{opacity:0.25}},'
            f'{{opacity:0,duration:{_num(_umh_play(0.5 * times["scale"]))},'
            f'ease:"power2.in",immediateRender:false}},'
            f'{_num(start + times["hi4_at"] + gap * 0.75)});')

    tweens.append(
        f'tl.fromTo("#{sid}",{{opacity:1,y:0}},'
        f'{{opacity:0,y:{_UMH_OUT_Y},duration:{_num(_umh_play(times["out_dur"]))},'
        f'ease:"power2.in",immediateRender:false}},'
        f'{_num(start + times["out_start"])});')

    kill_at = start + times["kill_at"]
    tweens.append(f'tl.set("#{sid}",{{y:0,opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{wid}",{{scaleX:1}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{uid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{lid}",{{opacity:0}},{_num(kill_at)});')
    tweens.append(f'tl.set("#{xid}",{{opacity:0}},{_num(kill_at)});')
    for pid in hex_ids:
        tweens.append(
            f'tl.set("#{pid}",{{opacity:0,scale:0}},{_num(kill_at)});')
    for tid in lab_ids:
        tweens.append(f'tl.set("#{tid}",{{opacity:0}},{_num(kill_at)});')
    for hid_r in hi_ids:
        tweens.append(f'tl.set("#{hid_r}",{{opacity:0}},{_num(kill_at)});')

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip overlay umh-chart" {_timing(ctx)}>'
               f'<div class="umh-bg"></div>'
               f'<div id="{sid}" class="umh-stage">'
               f'<div class="umh-hl-clip" data-layout-allow-overlap="">'
               f'<div class="umh-hl">{_esc(title)}</div>'
               f'<div id="{wid}" class="umh-wipe"></div></div>'
               f'<div id="{uid}" class="umh-sub" data-layout-allow-overlap="">'
               f'{_esc(subtitle)}</div>'
               f'<svg class="umh-svg" viewBox="0 0 1080 1920" '
               f'preserveAspectRatio="xMidYMid meet" aria-hidden="true">'
               f'{"".join(polys)}{"".join(text_els)}</svg>'
               f'<div id="{lid}" class="umh-legend" data-layout-allow-overlap="">'
               f'<span class="umh-legend-lab">{_esc(leg_low)}</span>'
               f'<div class="umh-legend-bar"></div>'
               f'<span class="umh-legend-lab">{_esc(leg_high)}</span></div>'
               f'<div id="{xid}" class="umh-src" data-layout-allow-overlap="">'
               f'{_esc(source)}</div></div></div>'],
        tweens=tweens)


# ---------- world-map constants ----------
_WMP_CATALOG_DUR = 14.0
_WMP_HL_DUR = 1.0
_WMP_SUB_AT = 0.4
_WMP_SUB_DUR = 0.6
_WMP_REG_AT = 1.0
_WMP_REG_DUR = 0.3
_WMP_REG_STAGGER = 0.02
_WMP_LEG_AT = 4.0
_WMP_LEG_DUR = 0.6
_WMP_SRC_AT = 4.5
_WMP_SRC_DUR = 0.5
_WMP_HI_AT = 5.0
_WMP_HI_DUR = 0.4
_WMP_HI_BACK = 0.6
_WMP_HI_GAP = 0.15
_WMP_OUT_Y = 60
_WMP_DEFAULT = "#1e293b"
_WMP_STOPS = ("#064e3b", "#0d9488", "#22d3ee", "#f0fdfa")


def _wmp_play(duration: float) -> float:
    return duration if duration <= 0.001 else max(0.001, duration - 0.001)


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


def _wmp_color(value: float, lo: float, hi: float) -> str:
    span = hi - lo if hi > lo else 1.0
    t = min(max((value - lo) / span, 0.0), 1.0)
    scaled = t * (len(_WMP_STOPS) - 1)
    idx = min(int(scaled), len(_WMP_STOPS) - 2)
    return _usm_lerp_hex(_WMP_STOPS[idx], _WMP_STOPS[idx + 1], scaled - idx)


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


def dv_world_map(ctx: "TemplateCtx") -> Piece:
    """World choropleth: countries fade from center, top-5 pulse.

    Catalog DEMO 1 fetches world-atlas topojson and tweens ``clipPath`` /
    ``filter:brightness``. Here paths are pre-baked Natural Earth,
    wipe is ``scaleX``, highlights use white overlay ``opacity``.
    Gradient ``#0f172a``/``#1e293b``, scale ``#064e3b``→``#0d9488``→
    ``#22d3ee``→``#f0fdfa``. Inter.
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
                f'd="{_esc(shape["d"])}" fill="#f8fafc"></path>')
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


DATAVIZ: dict[str, Callable[["TemplateCtx"], Piece]] = {
    "bar-race-mini": dv_bars,
    "compare-bars": dv_bars,
    "line-rise": dv_bars,          # линия строится теми же значениями
    "counter-roll": dv_counter,
    "donut-fill": dv_donut,
    "timeline-dots": dv_dots,
    "stat-countup-card": dv_stat_card,
    "animated-bar-chart": dv_animated_bar_chart,
    "bar-chart-race": dv_bar_chart_race,
    "chart-story": dv_chart_story,
    "conic-progress-ring": dv_conic_progress_ring,
    "decline-chart": dv_decline_chart,
    "mk-line-graph": dv_mk_line_graph,
    "spain-map": dv_spain_map,
    "star-rating-fill": dv_star_rating_fill,
    "us-map": dv_us_map,
    "us-map-flow": dv_us_map_flow,
    "us-map-hex": dv_us_map_hex,
    "world-map": dv_world_map,
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
    left = int(safe["x_min"])
    width = int(safe["x_max"]) - left
    canvas_w = int(brandbook["canvas"]["width"])
    canvas_h = int(brandbook["canvas"]["height"])
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
        ".abc-chart{left:0;top:0;"
        f"width:{canvas_w}px;height:{canvas_h}px;"
        "background:#f7f7f8}"
        ".abc-card{position:absolute;"
        f"left:{left}px;width:{width}px;top:420px;"
        "padding:34px;border-radius:28px;background:#ffffff;"
        "box-shadow:0 28px 80px rgba(15,23,42,0.16);"
        "display:grid;gap:22px}"
        ".abc-head{display:grid;gap:8px}"
        ".abc-title{margin:0;font-family:Inter,system-ui,sans-serif;"
        "font-size:34px;font-weight:700;line-height:1.1;letter-spacing:-0.04em;"
        "color:#111827}"
        ".abc-sub{margin:0;font-family:Inter,system-ui,sans-serif;"
        "font-size:16px;font-weight:400;line-height:1.45;color:#6b7280}"
        ".abc-kpi{display:block;font-family:Inter,system-ui,sans-serif;"
        "font-size:54px;font-weight:700;line-height:1;letter-spacing:-0.06em;"
        "color:#111827}"
        ".abc-bars{display:grid;align-items:end;gap:14px;height:210px}"
        ".abc-col{display:flex;flex-direction:column;justify-content:flex-end;"
        "align-items:stretch;height:100%;gap:10px}"
        ".abc-slot{position:relative;width:100%;overflow:hidden;"
        "border-radius:14px 14px 5px 5px}"
        ".abc-grow{position:absolute;left:0;width:100%;height:200%;bottom:-100%;"
        "display:block;transform-origin:50% 50%}"
        ".abc-fill{position:absolute;left:0;top:0;width:100%;height:50%;"
        "background:rgba(17,24,39,0.72);border-radius:14px 14px 5px 5px}"
        ".abc-lbl{display:block;text-align:center;"
        "font-family:Inter,system-ui,sans-serif;font-size:13px;font-weight:500;"
        "color:#9ca3af}"
        ".bcr-chart{left:0;top:0;"
        f"width:{canvas_w}px;height:{canvas_h}px;"
        "background:#f5f3ef;font-family:Inter,sans-serif;color:#1f1d1b}"
        ".bcr-bg{position:absolute;inset:0;background:#f5f3ef}"
        ".bcr-head{position:absolute;top:56px;left:48px;"
        f"width:{canvas_w - 96}px;"
        "height:200px}"
        ".bcr-head-left{position:absolute;left:0;top:0;width:640px}"
        ".bcr-head-right{position:absolute;right:0;top:0;text-align:right}"
        ".bcr-title{margin:0;font-size:34px;font-weight:700;"
        "letter-spacing:-0.015em;line-height:1.1;color:#1f1d1b}"
        ".bcr-subtitle{margin:10px 0 0;font-size:16px;font-weight:400;"
        "color:#6b6560}"
        ".bcr-period-caption{display:block;font-size:13px;font-weight:600;"
        "letter-spacing:0.18em;text-transform:uppercase;color:#6b6560}"
        ".bcr-period{position:relative;display:block;height:56px;margin-top:4px;"
        "font-size:52px;font-weight:700;line-height:1;"
        "font-variant-numeric:tabular-nums;letter-spacing:-0.02em}"
        ".bcr-period span{position:absolute;right:0;top:0;opacity:0;"
        "white-space:nowrap}"
        f".bcr-plot{{position:absolute;left:0;top:{_BCR_PLOT_TOP}px;"
        f"width:{canvas_w}px;height:{_BCR_PLOT_H}px;overflow:hidden}}"
        f".bcr-row{{position:absolute;left:0;top:0;width:{canvas_w}px;opacity:0}}"
        ".bcr-name{position:absolute;left:32px;width:204px;top:0;height:100%;"
        "display:flex;align-items:center;justify-content:flex-end;"
        "text-align:right;font-size:20px;font-weight:600;line-height:1.2;"
        "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"
        "background-color:#f5f3ef}"
        f".bcr-bar{{position:absolute;left:{_BCR_TRACK_X}px;"
        "border-radius:3px;background-color:#1f1d1b;"
        "transform-origin:left center}"
        f".bcr-value{{position:absolute;left:{_BCR_TRACK_X + 4}px;top:0;height:100%}}"
        ".bcr-value span{position:absolute;left:0;top:0;height:100%;opacity:0;"
        "display:flex;align-items:center;padding:0 10px;font-size:20px;"
        "font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap;"
        "background-color:#f5f3ef}"
        ".bcr-axis{position:absolute;inset:0;z-index:5000;pointer-events:none}"
        f".bcr-tick-line{{position:absolute;top:{_BCR_PLOT_TOP}px;left:0;width:1px;"
        f"height:{_BCR_PLOT_H}px;background-color:rgba(31,29,27,0.11);opacity:0}}"
        ".bcr-tick-line.bcr-tick-zero{background-color:rgba(31,29,27,0.5)}"
        f".bcr-tick-label{{position:absolute;top:{_BCR_PLOT_TOP - 32}px;left:0;"
        f"width:{_BCR_TICK_LABEL_W}px;font-size:15px;font-weight:500;"
        "font-variant-numeric:tabular-nums;color:#6b6560;opacity:0}"
        f".bcr-tick-label span{{position:absolute;left:0;top:0;width:{_BCR_TICK_LABEL_W}px;"
        "text-align:center;opacity:0;white-space:nowrap}"
        ".bcr-source{position:absolute;left:48px;top:1748px;margin:0;"
        "font-size:14px;color:#6b6560}"
        ".cst-chart{left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "background:#0a0a0a;font-family:Inter,system-ui,sans-serif;"
        "color:#f8fafc}"
        ".cst-bg{position:absolute;inset:0;background:#0a0a0a}"
        ".cst-stage{position:absolute;left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "opacity:0}"
        ".cst-axis{position:absolute;height:3px;background:#475569;"
        "border-radius:2px;transform-origin:left center}"
        ".cst-bar{position:absolute;transform-origin:50% 100%}"
        ".cst-al,.cst-vl{position:absolute;width:180px;text-align:center;"
        'font-family:"JetBrains Mono",ui-monospace,monospace;'
        "letter-spacing:0.03em;opacity:0;white-space:nowrap}"
        ".cst-al{font-size:26px;font-weight:500;color:#c6ceda}"
        ".cst-vl{font-size:27px;font-weight:600;color:#f8fafc}"
        ".cst-call{position:absolute;border-radius:12px;opacity:0;"
        "transform-origin:50% 100%;overflow:hidden}"
        ".cst-cv{position:absolute;left:0;right:0;top:0;bottom:0;"
        'font-family:"JetBrains Mono",ui-monospace,monospace;'
        "font-size:29px;font-weight:600;color:#05070b;"
        "letter-spacing:0.03em}"
        ".cst-cv span{position:absolute;left:0;right:0;top:0;bottom:0;"
        "display:flex;align-items:center;justify-content:center;opacity:0}"
        ".cpr-chart{left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "background:#0a0a0a;font-family:Inter,system-ui,sans-serif;"
        "color:#f4f7fb}"
        ".cpr-bg{position:absolute;inset:0;background:#0a0a0a}"
        ".cpr-stage{position:absolute;left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px"
        "}"
        f".cpr-disc{{position:absolute;left:{_CPR_LEFT}px;top:{_CPR_TOP}px;"
        f"width:{_CPR_DISC}px;height:{_CPR_DISC}px;"
        "border-radius:50%;overflow:hidden;background:#1b2938}"
        ".cpr-right,.cpr-left{position:absolute;top:0;width:50%;height:100%;"
        "overflow:hidden}"
        ".cpr-right{left:50%}"
        ".cpr-left{left:0}"
        ".cpr-rot{position:absolute;top:0;left:-100%;width:200%;height:100%;"
        "transform-origin:50% 50%}"
        ".cpr-left .cpr-rot{left:0}"
        ".cpr-paint{position:absolute;left:50%;top:0;width:50%;height:100%;"
        "background:#35d6a0}"
        ".cpr-hole{position:absolute;border-radius:50%;background:#0a0a0a}"
        f".cpr-cv{{position:absolute;left:{_CPR_LEFT}px;top:{_CPR_TOP}px;"
        f"width:{_CPR_DISC}px;height:{_CPR_DISC}px;"
        "font-family:Inter,system-ui,sans-serif;"
        f"font-size:{_CPR_FONT}px;font-weight:700;letter-spacing:-0.04em;"
        "line-height:1;color:#f4f7fb;font-variant-numeric:tabular-nums}"
        ".cpr-cv span{position:absolute;left:0;top:0;right:0;bottom:0;"
        "display:flex;align-items:center;justify-content:center;opacity:0}"
        ".dcl-chart{left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "background:#0c1118;font-family:Inter,system-ui,sans-serif;"
        "color:#f8fafc}"
        ".dcl-bg{position:absolute;inset:0;background:"
        "radial-gradient(circle at 24% 16%,rgba(47,129,150,0.55),transparent 46%),"
        "linear-gradient(145deg,#152f3c 0%,#101a25 48%,#0c1118 100%)}"
        ".dcl-gloom{position:absolute;inset:0;background:#030507;opacity:0}"
        ".dcl-stage{position:absolute;left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px"
        "}"
        ".dcl-label{position:absolute;width:580px;overflow:hidden;"
        "color:rgba(226,232,240,0.72);font-size:38px;font-weight:600;"
        "letter-spacing:0.05em;line-height:1.1;text-overflow:ellipsis;"
        "text-transform:uppercase;white-space:nowrap}"
        f".dcl-cv{{position:absolute;width:{_DCL_VALUE_W}px;"
        f"height:{_DCL_HEADER_H}px;"
        "color:#f8fafc;font-family:Inter,system-ui,sans-serif;"
        f"font-size:{_DCL_VALUE_SIZE}px;font-weight:700;"
        "font-variant-numeric:tabular-nums;letter-spacing:-0.07em;"
        "line-height:0.8;text-align:right}"
        ".dcl-cv span{position:absolute;left:0;top:0;right:0;bottom:0;"
        "display:flex;align-items:flex-end;justify-content:flex-end;opacity:0}"
        f".dcl-plot{{position:absolute;left:{_DCL_PLOT_LEFT}px;"
        f"top:{_DCL_PLOT_TOP}px;width:{_DCL_PLOT_W}px;"
        f"height:{_DCL_PLOT_H}px"
        "}"
        ".dcl-plot svg{position:absolute;inset:0;width:100%;height:100%;"
        "overflow:visible}"
        ".dcl-grid{stroke:rgba(148,163,184,0.18);stroke-width:1;"
        "vector-effect:non-scaling-stroke}"
        ".dcl-line{fill:none;stroke:#fb7185;stroke-linecap:round;"
        "stroke-linejoin:round;stroke-width:4}"
        ".dcl-wipe{transform-origin:0px 50%;transform-box:fill-box}"
        f".dcl-ep{{position:absolute;width:{_DCL_EP_D}px;"
        f"height:{_DCL_EP_D}px;"
        "border-radius:50%;background:#fecdd3;opacity:0;"
        "transform-origin:50% 50%}"
        ".mlg-chart{left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "background:#ffffff;font-family:Inter,system-ui,sans-serif;"
        "color:#1d1d1f}"
        ".mlg-bg{position:absolute;inset:0;background:#ffffff}"
        ".mlg-stage{position:absolute;left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px"
        "}"
        ".mlg-svg{position:absolute;inset:0;width:100%;height:100%;"
        "overflow:visible}"
        ".mlg-axis{stroke:rgba(29,29,31,0.22);stroke-width:2;opacity:0}"
        ".mlg-line{fill:none;stroke-width:5;stroke-linecap:round;"
        "stroke-linejoin:round}"
        ".mlg-wipe{transform-origin:0px 50%;transform-box:fill-box}"
        f".mlg-dot{{position:absolute;width:{_MLG_DOT}px;"
        f"height:{_MLG_DOT}px;"
        "border-radius:50%;background:#ffffff;box-sizing:border-box;"
        "border-style:solid;border-width:4px;transform-origin:50% 50%}"
        f".mlg-val{{position:absolute;width:{_MLG_VAL_W}px;"
        f"height:{_MLG_VAL_H}px;"
        "font-weight:600;font-size:38px;letter-spacing:-0.01em;"
        "color:#1d1d1f;font-variant-numeric:tabular-nums;line-height:46px;"
        "text-align:center;white-space:nowrap;opacity:0}"
        f".mlg-xl{{position:absolute;width:{_MLG_XL_W}px;"
        "font-weight:400;font-size:32px;color:#6e6e73;text-align:center;"
        "white-space:nowrap;opacity:0}"
        ".mlg-legend{position:absolute;display:flex;gap:32px;opacity:0}"
        ".mlg-legend-item{display:flex;align-items:center;gap:12px;"
        "font-weight:500;font-size:36px;color:#6e6e73}"
        ".mlg-legend-dot{width:14px;height:14px;border-radius:50%;"
        "flex-shrink:0}"
        ".spm-chart{left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "background:#0f172a;font-family:Inter,system-ui,sans-serif;"
        "color:#e2e8f0}"
        ".spm-bg{position:absolute;inset:0;"
        "background:linear-gradient(145deg,#0f172a 0%,#1e293b 100%)}"
        ".spm-stage{position:absolute;left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px"
        "}"
        ".spm-hl-clip{position:absolute;left:90px;top:168px;width:740px;"
        "overflow:hidden}"
        ".spm-hl{font-weight:700;font-size:36px;letter-spacing:-0.02em;"
        "color:#f8fafc;text-align:center;line-height:1.15}"
        ".spm-wipe{position:absolute;inset:0;"
        "background:linear-gradient(145deg,#0f172a 0%,#1e293b 100%);"
        "transform-origin:100% 50%}"
        ".spm-sub{position:absolute;left:90px;top:268px;width:740px;"
        "font-weight:300;font-size:22px;color:#94a3b8;text-align:center;"
        "opacity:0}"
        ".spm-svg{position:absolute;left:90px;top:340px;width:740px;"
        "height:610px;overflow:visible}"
        ".spm-region{stroke:#1e293b;stroke-width:1.2;opacity:0;"
        "transform-origin:50% 50%;transform-box:fill-box;"
        "vector-effect:non-scaling-stroke}"
        ".spm-hi{fill:#f8fafc;opacity:0;pointer-events:none;"
        "transform-origin:50% 50%;transform-box:fill-box}"
        f".spm-lab{{position:absolute;width:{_SPM_LAB_W}px;"
        f"height:{_SPM_LAB_H}px;"
        "font-weight:500;font-size:20px;color:#f8fafc;text-align:center;"
        "line-height:32px;white-space:nowrap;opacity:0}"
        ".spm-legend{position:absolute;left:90px;top:972px;width:740px;"
        "display:flex;justify-content:center;align-items:center;gap:14px;"
        "opacity:0}"
        ".spm-legend-bar{width:280px;height:14px;border-radius:7px;"
        "background:linear-gradient(90deg,#7f1d1d,#dc2626,#fbbf24)}"
        ".spm-legend-lab{font-weight:500;font-size:22px;color:#94a3b8}"
        ".spm-src{position:absolute;left:90px;top:1048px;width:740px;"
        "font-weight:400;font-size:18px;color:#475569;text-align:right;"
        "opacity:0}"
        ".srf-chart{left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "background:#090d16;font-family:Inter,system-ui,sans-serif;"
        "color:#f4f7fb}"
        ".srf-bg{position:absolute;inset:0;background:#090d16}"
        ".srf-stage{position:absolute;left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px"
        "}"
        f".srf-card{{position:absolute;left:{_SRF_CARD_LEFT}px;"
        f"top:{_SRF_CARD_TOP}px;width:{_SRF_CARD_W}px;"
        f"height:{_SRF_CARD_H}px;"
        "border-radius:32px;background:#1a2230;"
        "border:2px solid rgba(244,247,251,0.14);"
        "box-shadow:0 43px 108px rgba(244,247,251,0.12)}"
        ".srf-stars{position:absolute}"
        ".srf-fill-svg{position:absolute;left:0;top:0;overflow:visible}"
        ".srf-cell{position:absolute;top:0;overflow:visible;"
        "transform-origin:50% 50%}"
        ".srf-fill-star{transform-origin:50% 50%;transform-box:fill-box}"
        ".srf-wipe{transform-origin:0px 50%;transform-box:fill-box}"
        ".srf-cv{position:absolute;line-height:1;text-align:right;"
        "font-weight:720;letter-spacing:-0.04em;"
        "font-variant-numeric:tabular-nums;color:#f4f7fb}"
        ".srf-cv span{position:absolute;right:0;top:0;opacity:0;"
        "white-space:nowrap}"
        ".usm-chart{left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "background:#0f172a;font-family:Inter,system-ui,sans-serif;"
        "color:#e2e8f0}"
        ".usm-bg{position:absolute;inset:0;"
        "background:linear-gradient(145deg,#0f172a 0%,#1e293b 100%)}"
        ".usm-stage{position:absolute;left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px"
        "}"
        ".usm-hl-clip{position:absolute;left:40px;top:140px;width:1000px;"
        "overflow:hidden}"
        ".usm-hl{font-weight:700;font-size:38px;letter-spacing:-0.02em;"
        "color:#f8fafc;text-align:center;line-height:1.15}"
        ".usm-wipe{position:absolute;inset:0;"
        "background:linear-gradient(145deg,#0f172a 0%,#1e293b 100%);"
        "transform-origin:100% 50%}"
        ".usm-sub{position:absolute;left:40px;top:236px;width:1000px;"
        "font-weight:300;font-size:22px;color:#94a3b8;text-align:center;"
        "opacity:0}"
        ".usm-svg{position:absolute;left:40px;top:310px;width:1000px;"
        "height:586px;overflow:visible}"
        ".usm-region{stroke:#1e293b;stroke-width:1.2;opacity:0;"
        "transform-origin:50% 50%;transform-box:fill-box;"
        "vector-effect:non-scaling-stroke}"
        ".usm-hi{fill:#f8fafc;opacity:0;pointer-events:none;"
        "transform-origin:50% 50%;transform-box:fill-box}"
        f".usm-lab{{position:absolute;width:{_USM_LAB_W}px;"
        f"height:{_USM_LAB_H}px;"
        "font-weight:500;font-size:15px;color:#f8fafc;text-align:center;"
        "line-height:24px;white-space:nowrap;opacity:0}"
        ".usm-legend{position:absolute;left:40px;top:912px;width:1000px;"
        "display:flex;justify-content:center;align-items:center;gap:14px;"
        "opacity:0}"
        ".usm-legend-bar{width:300px;height:14px;border-radius:7px;"
        "background:linear-gradient(90deg,#1e3a5f,#2563eb,#7c3aed,#ec4899)}"
        ".usm-legend-lab{font-weight:500;font-size:22px;color:#94a3b8}"
        ".usm-src{position:absolute;left:40px;top:968px;width:1000px;"
        "font-weight:400;font-size:18px;color:#475569;text-align:right;"
        "opacity:0}"
        ".umf-chart{left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "background:#0f172a;font-family:Inter,system-ui,sans-serif;"
        "color:#e2e8f0}"
        ".umf-bg{position:absolute;inset:0;"
        "background:linear-gradient(145deg,#0f172a 0%,#1e293b 100%)}"
        ".umf-stage{position:absolute;left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px"
        "}"
        ".umf-hl-clip{position:absolute;left:40px;top:140px;width:1000px;"
        "overflow:hidden;z-index:4}"
        ".umf-hl{font-weight:700;font-size:38px;letter-spacing:-0.02em;"
        "color:#f8fafc;text-align:left;line-height:1.15}"
        ".umf-wipe{position:absolute;inset:0;"
        "background:linear-gradient(145deg,#0f172a 0%,#1e293b 100%);"
        "transform-origin:100% 50%}"
        ".umf-sub{position:absolute;left:40px;top:236px;width:1000px;"
        "font-weight:300;font-size:22px;color:#94a3b8;text-align:left;"
        "opacity:0;z-index:4}"
        ".umf-svg{position:absolute;left:40px;top:310px;width:1000px;"
        "height:562px;overflow:visible}"
        ".umf-region{fill:#1e293b;stroke:#334155;stroke-width:0.5;"
        "opacity:0;vector-effect:non-scaling-stroke}"
        ".umf-arc{fill:none;stroke:#3b82f6;stroke-linecap:round;opacity:0;"
        "transform-box:view-box;vector-effect:non-scaling-stroke}"
        ".umf-city{fill:#ffffff;opacity:0;transform-origin:50% 50%;"
        "transform-box:fill-box}"
        ".umf-lab{position:absolute;font-weight:500;font-size:16px;"
        "color:#cbd5e1;white-space:nowrap;opacity:0;z-index:2;"
        "pointer-events:none}"
        ".umf-tdot{position:absolute;width:12px;height:12px;"
        "border-radius:50%;background:#60a5fa;opacity:0;z-index:3;"
        "pointer-events:none}"
        ".umf-src{position:absolute;left:40px;top:968px;width:1000px;"
        "font-weight:400;font-size:18px;color:#475569;text-align:right;"
        "opacity:0;z-index:4}"
        ".umh-chart{left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "background:#0f172a;font-family:Inter,system-ui,sans-serif;"
        "color:#e2e8f0}"
        ".umh-bg{position:absolute;inset:0;"
        "background:linear-gradient(145deg,#0f172a 0%,#1e293b 100%)}"
        ".umh-stage{position:absolute;left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px"
        "}"
        ".umh-hl-clip{position:absolute;left:40px;top:140px;width:1000px;"
        "overflow:hidden}"
        ".umh-hl{font-weight:700;font-size:38px;letter-spacing:-0.02em;"
        "color:#f8fafc;line-height:1.15}"
        ".umh-wipe{position:absolute;inset:0;"
        "background:linear-gradient(145deg,#0f172a 0%,#1e293b 100%);"
        "transform-origin:100% 50%}"
        ".umh-sub{position:absolute;left:40px;top:236px;width:1000px;"
        "font-weight:300;font-size:22px;color:#94a3b8;opacity:0}"
        ".umh-svg{position:absolute;left:40px;top:280px;width:1000px;"
        "height:620px;overflow:visible}"
        ".umh-poly{stroke:#0f172a;stroke-width:2;opacity:0;"
        "transform-origin:50% 50%;transform-box:fill-box;"
        "vector-effect:non-scaling-stroke}"
        ".umh-text{font-family:Inter,system-ui,sans-serif;font-size:14px;"
        "font-weight:600;fill:#0f172a;text-anchor:middle;"
        "dominant-baseline:central;opacity:0}"
        ".umh-text-light{fill:#fef3c7}"
        ".umh-hi{fill:#f8fafc;opacity:0;pointer-events:none}"
        ".umh-legend{position:absolute;left:40px;top:920px;width:1000px;"
        "display:flex;justify-content:center;align-items:center;gap:12px;"
        "opacity:0}"
        ".umh-legend-bar{width:240px;height:14px;border-radius:4px;"
        "background:linear-gradient(90deg,#451a03,#f59e0b,#fef3c7)}"
        ".umh-legend-lab{font-weight:500;font-size:18px;color:#94a3b8}"
        ".umh-src{position:absolute;left:40px;top:968px;width:1000px;"
        "font-weight:400;font-size:16px;color:#475569;text-align:right;"
        "opacity:0}"
        ".wmp-chart{left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px;"
        "background:#0f172a;font-family:Inter,system-ui,sans-serif;"
        "color:#f0fdfa}"
        ".wmp-bg{position:absolute;inset:0;"
        "background:linear-gradient(145deg,#0f172a 0%,#1e293b 100%)}"
        ".wmp-stage{position:absolute;left:0;top:0;"
        f"width:{canvas_w}px;"
        f"height:{canvas_h}px"
        "}"
        ".wmp-hl-clip{position:absolute;left:40px;top:140px;width:1000px;"
        "overflow:hidden}"
        ".wmp-hl{font-weight:700;font-size:38px;letter-spacing:-0.02em;"
        "color:#f0fdfa;line-height:1.15}"
        ".wmp-wipe{position:absolute;inset:0;"
        "background:linear-gradient(145deg,#0f172a 0%,#1e293b 100%);"
        "transform-origin:100% 50%}"
        ".wmp-sub{position:absolute;left:40px;top:236px;width:1000px;"
        "font-weight:300;font-size:22px;color:#94a3b8;opacity:0}"
        ".wmp-svg{position:absolute;left:40px;top:310px;width:1000px;"
        "height:560px;overflow:visible}"
        ".wmp-grat{fill:none;stroke:#1e293b;stroke-width:0.6;stroke-opacity:0.5}"
        ".wmp-region{stroke:#1e293b;stroke-width:0.6;opacity:0;"
        "vector-effect:non-scaling-stroke}"
        ".wmp-hi{fill:#f8fafc;opacity:0;pointer-events:none}"
        ".wmp-legend{position:absolute;left:40px;top:900px;width:1000px;"
        "display:flex;flex-direction:column;align-items:center;gap:8px;"
        "opacity:0}"
        ".wmp-legend-bar{width:280px;height:14px;border-radius:7px;"
        "background:linear-gradient(90deg,#064e3b,#0d9488,#22d3ee,#f0fdfa)}"
        ".wmp-legend-labs{display:flex;justify-content:space-between;"
        "width:280px;font-weight:500;font-size:16px;color:#94a3b8}"
        ".wmp-src{position:absolute;left:40px;top:968px;width:1000px;"
        "font-weight:400;font-size:16px;color:#475569;text-align:right;"
        "opacity:0}"
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


# Каталог code-3d-extrude: WebGL-плита, rotY/rotX/camZ, canvas onUpdate.
# Движок Three.js и onUpdate не умеет — 2D-посадка scale/x/y/rotation.
_C3D_KW = frozenset({
    "async", "await", "function", "const", "let", "var", "return", "if", "else",
    "for", "while", "class", "new", "import", "from", "export", "default",
    "true", "false", "null", "undefined", "def", "and", "or", "not", "in",
    "try", "catch", "throw", "this", "typeof", "void", "yield", "of",
})
_C3D_KW_COLOR = "#F97583"
_C3D_FN_COLOR = "#B392F0"
_C3D_VAR_COLOR = "#79B8FF"
_C3D_PARAM_COLOR = "#FFAB70"
_C3D_STR_COLOR = "#9ECBFF"
_C3D_FG_COLOR = "#E1E4E8"
_C3D_CMT_COLOR = "#6A737D"
_C3D_LEX = re.compile(
    r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)'
    r"|(/\*[^*]*\*+(?:[^/*][^*]*\*+)*/|//[^\n]*)"
    r"|(\b\d+(?:\.\d+)?\b)"
    r"|(\b[A-Za-z_]\w*\b)"
    r"|(\s+)"
    r"|([^\sA-Za-z0-9_]+)"
)
_C3D_SCALE_FROM = 0.72
_C3D_FROM_X = 48
_C3D_FROM_Y = 36
_C3D_FROM_ROT = -9
_C3D_DRIFT_SCALE = 1.02
_C3D_DRIFT_X = 6
_C3D_DRIFT_Y = -3
_C3D_DRIFT_ROT = 2
_C3D_SETTLE_FRAC = 0.6
_C3D_PAD_X = 32
_C3D_PAD_Y = 28
_C3D_SIZE_CEILING = 34
_C3D_SIZE_FLOOR = 18
_C3D_MONO_EM = 0.62
_C3D_LH = 1.47


def _c3d_times(duration: float) -> dict[str, float]:
    """Посадка 60 % длительности, как camZ в каталоге; дрейф после стыка +1 мс."""
    settle_dur = max(0.2, duration * _C3D_SETTLE_FRAC)
    if settle_dur > duration - 0.05:
        settle_dur = max(0.2, duration - 0.05)
    drift_at = settle_dur + 0.001
    drift_dur = max(0.0, duration - drift_at)
    return {"settle_dur": settle_dur, "drift_at": drift_at, "drift_dur": drift_dur}


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


def _c3d_fit(lines: list[list[tuple[str, str]]], available: float) -> int:
    longest = max((sum(len(t[0]) for t in line) for line in lines), default=1)
    text_avail = max(80.0, available - 2 * _C3D_PAD_X)
    size = _C3D_SIZE_CEILING
    while size > _C3D_SIZE_FLOOR and longest * size * _C3D_MONO_EM > text_avail:
        size -= 1
    return size


def fs_code_3d_extrude(ctx: "TemplateCtx") -> Piece:
    """Код на скошенной плите: каталог — Three.js ExtrudeGeometry.

    Движок WebGL и ``onUpdate`` не умеет. Посадка — ``scale``/``x``/``y``/
    ``rotation`` на плите, скос — статичный слой ``#141d2b``. Github-dark и
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


# Каталог code-diff: unified view, height 46→0 на минусах и 0→46 на плюсах.
# Движок height не твинит — scaleY и заранее посчитанный y, как у столбцов
# data-viz (scaleX вместо width). Красный/зелёный github — сам жест.
_CD_EDITOR_SCALE = 0.985
_CD_LH_EM = 1.53
_CD_SIZE_CEILING = 28
_CD_TOP = 24
_CD_PAD_X = 28
_CD_TITLE_H = 52
_CD_DEL_COLOR = "#f85149"
_CD_ADD_COLOR = "#3fb950"


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


def _cd_text_from_rows(rows: list[list[tuple[str, str]]]) -> str:
    return "\n".join("".join(text for text, _color in line) for line in rows)


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


# Каталог code-particle-assemble: Three.js Points, шейдер uProgress, canvas
# getImageData. Движок WebGL, onUpdate и Math.random не умеет — capped span-ы
# с заранее посчитанным x/y, mulberry32 seed 23, как в каталоге.
_CPA_SEED = 23
_CPA_SEED_MIX = 2654435761
_CPA_CAP = 160
_CPA_DOT = 12
_CPA_ASSEMBLE_FRAC = 0.72
_CPA_SPAN = 0.62
_CPA_SIZE_CEILING = 56
_CPA_SIZE_FLOOR = 22
_CPA_FONT_PX_CAT = 46
_CPA_LINE_H_CAT = 70
_CPA_PAD_X_CAT = 70
_CPA_PAD_Y_CAT = 64
_CPA_THRESH = 220
_CPA_BG_RGB = (11, 15, 23)
_CPA_FRAME_W = 1080
_CPA_FRAME_H = 1920
_CPA_SCALE_FROM = 0.62


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


def _cpa_rng(seed: int = _CPA_SEED) -> _CpaRng:
    mixed = ((seed or 1) * _CPA_SEED_MIX) & 0xFFFFFFFF
    return _CpaRng(mixed)


def _cpa_num(value: float) -> str:
    """_num(-0.0) даёт '-0' — линт и GSAP этого не едят."""
    if abs(float(value)) < 5e-4:
        return "0"
    return _num(value)


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


def _cpa_brighten(color: str) -> str:
    r, g, b = _cpa_hex_rgb(color)
    bump = int(round(0.32 * 255))
    return _cpa_rgb_hex((min(255, r + bump), min(255, g + bump), min(255, b + bump)))


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


def _cpa_snap_color(x: int, y: int, boxes: list[tuple[float, float, int, int, str]],
                    fallback: str) -> str:
    for x0, x1, y0, y1, color in boxes:
        if x0 <= x < x1 and y0 <= y < y1:
            return color
    return fallback


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


# Каталог code-scroll: камера скроллит файл к целевой строке и подсвечивает
# её. document.fonts.ready + getBoundingClientRect здесь нельзя — dy
# заранее в Python. CSS-transform на editor/scroll запрещён: жест — scale/y.
_CS_VIS = 14
_CS_GUTTER = 56
_CS_TITLE_H = 48
_CS_PAD_TOP = 12
_CS_PAD_X = 16
_CS_LH_EM = 1.55
_CS_SIZE_FLOOR = 13
_CS_SIZE_CEILING = 22
_CS_EDITOR_SCALE = 0.985
_CS_DIM = 0.35
_CS_FRAME_W = 1080
_CS_FRAME_H = 1920
_CS_DEFAULT_LINE = 12
_CS_DEFAULT_FILE = "fetchWithRetry.js"


def _cs_num(value: float) -> str:
    """_num(-0.0) даёт '-0' — линт и GSAP этого не едят."""
    if abs(float(value)) < 5e-4:
        return "0"
    return _num(value)


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


def fs_code_scroll(ctx: "TemplateCtx") -> Piece:
    """Камера скроллит файл к целевой строке и подсвечивает её.

    Каталог меряет ``getBoundingClientRect`` после ``fonts.ready``. Здесь
    ``y`` заранее, окно ~14 строк, чтобы на 9:16 сдвиг был виден. Твины на
    ``#…-editor`` / ``#…-scroll`` / строках, не на ``.clip``. JetBrains Mono,
    github-dark и прожектор ``#58a6ff`` как в каталоге — это сам жест.
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


# Каталог code-typing: посимвольный набор с кареткой. getBoundingClientRect
# после fonts.ready здесь нельзя — x/y каретки заранее. CSS-transform на
# editor/caret запрещён. Каретка #58a6ff — жест, не акцент канала.
_CT_GUTTER = 56
_CT_TITLE_H = 48
_CT_PAD_TOP = 16
_CT_PAD_X = 18
_CT_LH_EM = 1.55
_CT_SIZE_FLOOR = 16
_CT_SIZE_CEILING = 26
_CT_EDITOR_SCALE = 0.985
_CT_PER = 0.028
_CT_CHAR_FADE = 0.12
_CT_WS_FADE = 0.01
_CT_CARET_W = 3
_CT_FRAME_W = 1080
_CT_FRAME_H = 1920
_CT_DEFAULT_FILE = "loadConfig.js"


def _ct_num(value: float) -> str:
    """_num(-0.0) даёт '-0' — линт и GSAP этого не едят."""
    if abs(float(value)) < 5e-4:
        return "0"
    return _num(value)


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


def _ct_advance(ch: str, font, em: float) -> float:
    if font is not None:
        try:
            wide = float(font.getlength(ch))
            if wide > 0:
                return wide
        except Exception:                                    # noqa: BLE001
            pass
    return em


def fs_code_typing(ctx: "TemplateCtx") -> Piece:
    """Посимвольный набор с кареткой: каталог меряет DOM.

    Здесь ширина глифа из JetBrains Mono, ``x``/``y`` каретки заранее.
    Твины на ``#…-editor`` / ``#…-scene`` / знаках / каретке, не на
    ``.clip``. github-dark и ``#58a6ff`` как в каталоге — это сам жест.
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


# Каталог terminal-simulator: скелет строк через CSS-var --hf-line и
# команда снизу. Движок CSS-var не твинит — scaleX и opacity, y терминала.
_TS_CATALOG_W = 760
_TS_CHROME_H = 48
_TS_BODY_H = 340
_TS_TERM_H = 78
_TS_FILES_W = 210
_TS_RADIUS = 24
_TS_LINE_H = 18
_TS_LINE_GAP = 14
_TS_PAD = 22
_TS_DOT = 11
_TS_CHROME_SIZE = 14
_TS_BODY_SIZE = 15
_TS_START = 0.50
_TS_LINE_DUR = 0.24
_TS_LINE_STAGGER = 0.08
_TS_TERM_DELAY = 0.48
_TS_TERM_DUR = 0.34
_TS_TERM_Y = 16
_TS_LINE_WIDTHS = (92, 72, 84, 58, 78)
_TS_DEFAULT_TITLE = "Terminal Simulator"
_TS_DEFAULT_CMD = "$ hyperframes render --skill=terminal-simulator"
_TS_DEFAULT_FILES = ("index.html", "style.css", "timeline.js")
_TS_FRAME_W = 1080
_TS_FRAME_H = 1920
_TS_N_LINES = 5


def _ts_num(value: float) -> str:
    """_num(-0.0) даёт '-0' — линт и GSAP этого не едят."""
    if abs(float(value)) < 5e-4:
        return "0"
    return _num(value)


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


def _ts_command(params: dict[str, Any], code: str) -> str:
    raw = str(params.get("command") or code or "").replace("\r\n", "\n").strip()
    if not raw:
        return _TS_DEFAULT_CMD
    first = raw.split("\n", 1)[0].strip()
    if not first.startswith("$"):
        first = f"$ {first}"
    return first


def _ts_files(params: dict[str, Any]) -> list[str]:
    raw = params.get("files")
    names: list[str] = []
    if isinstance(raw, str):
        blob = raw.replace(",", "\n")
        names = [ln.strip() for ln in blob.split("\n") if ln.strip()]
    elif isinstance(raw, (list, tuple)):
        names = [str(item).strip() for item in raw if str(item).strip()]
    return names or list(_TS_DEFAULT_FILES)


def fs_terminal_simulator(ctx: "TemplateCtx") -> Piece:
    """Окно IDE: скелет строк и команда. Каталог твинит CSS-var.

    Здесь ``scaleX``/``opacity`` на полосках и ``y`` терминала, не на
    ``.clip``. Сланец ``#0f172a`` и зелёный ``#86efac`` как в каталоге —
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
               f'rgba(15,23,42,0.2)">'
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


# Каталог Apple Terminal Clear Dark: textContent, innerHTML и мигание
# каретки через колбэки. Здесь заранее span-ы, opacity, без DOM-мутаций.
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
_ATCD_N_BLINKS = 6
_ATCD_HOLD = 6.80
_ATCD_BLINK_DUR = 0.05
_ATCD_CHAR_FADE = 0.04
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
_ATCD_FRAME_W = 1080
_ATCD_FRAME_H = 1920
_ATCD_SIZE_FLOOR = 16
_ATCD_SIZE_CEILING = 22
_ATCD_LH_EM = 1.60
_ATCD_TITLE_H = 42
_ATCD_PAD_Y = 18
_ATCD_PAD_X = 20
_ATCD_RADIUS = 10


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


def fs_apple_terminal_clear_dark(ctx: "TemplateCtx") -> Piece:
    """Terminal.app Clear Dark: каталог пишет textContent и innerHTML.

    Здесь глифы команды и второй промпт заранее, показ — ``opacity``.
    Сланец ``#1a1a1a``, белый текст и серый промпт ``#888888`` как в
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


# Каталог Dark+: VS Code workbench, getBoundingClientRect, rotateY/z,
# classList и repeat:25 на каретке. Здесь заранее x/y, 2D rotation/x,
# span-ы и конечные blink. Цвета Dark+ — жест темы, не палитра канала.
_DP_TYPE_AT = 0.95
_DP_CHAR_PER = 0.012
_DP_LINE_MIN = 0.08
_DP_LINE_GAP = 0.045
_DP_HDR_DUR = 0.45
_DP_WB_AT = 0.10
_DP_WB_DUR = 0.58
_DP_HL_AT = 0.74
_DP_HL_DUR = 0.22
_DP_TERM_AT = 7.55
_DP_TERM_DUR = 0.56
_DP_TB_AT = 8.05
_DP_TB_DUR = 0.24
_DP_TB_STAGGER = 0.16
_DP_TILT_AT = 9.35
_DP_TILT_DUR = 0.72
_DP_UNTILT_AT = 10.08
_DP_UNTILT_DUR = 0.62
_DP_TILT_ROT = -5.5
_DP_TILT_X = 22
_DP_CATALOG_END = 10.70
_DP_FRAME_W = 1080
_DP_FRAME_H = 1920
_DP_SIZE_FLOOR = 12
_DP_SIZE_CEILING = 18
_DP_LABEL = "Dark+"
_DP_FILE = "functional_toolkit.py"
_DP_KICKER = "Official VS Code built-in theme"
_DP_TITLE = "functional-toolkit - Visual Studio Code"
_DP_TERM_LINES = (
    ("functional-toolkit %", "python -m pytest"),
    ("", "collected 3 items"),
    ("", "tests/test_toolkit.py ... passed"),
)
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


def fs_dark_plus(ctx: "TemplateCtx") -> Piece:
    """VS Code Dark+: каталог меряет DOM и крутит rotateY.

    Здесь ширина глифа из JetBrains Mono, заранее x/y каретки, наклон —
    ``rotation``/``x``. Твины на хроме / знаках / каретке, не на ``.clip``.
    Цвета Dark+ и ``#0078d4`` как в каталоге — жест темы, не палитра канала.
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


_BFC_CATALOG_END = 5.55
_BFC_PATTERN = (0.55, 1.15, 0.7, 1.35, 0.9, 1.4, 0.65, 1.1, 0.5, 1.25, 0.8, 1.45)
_BFC_WAVE_FILL = (
    "M0,160 C40,150 60,90 100,100 C140,110 160,40 200,55 C240,70 260,150 300,140 "
    "C340,130 360,30 400,45 C440,60 460,130 500,120 C540,110 560,70 592,80 "
    "L592,220 L0,220 Z")
_BFC_WAVE_PATH = (
    "M0,160 C40,150 60,90 100,100 C140,110 160,40 200,55 C240,70 260,150 300,140 "
    "C340,130 360,30 400,45 C440,60 460,130 500,120 C540,110 560,70 592,80")


def _bfc_n(value: float) -> str:
    if abs(float(value)) < 1e-9:
        return "0"
    return _num(value)


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


def fs_beat_freeze_cut(ctx: "TemplateCtx") -> Piece:
    """Music-promo: рамп → freeze DROP → hard-cut. Каталог твинит filter.

    Здесь scale/x/y/opacity и статичный backdrop-filter. Твины на карточке,
    кропе, барах и слоях freeze/cut, не на ``.clip``. Мята каталога ``#00E5C7``
    спорит со скриншотами — акцент ``#E63946``, сцена ``#0B132B``, панели
    ``#1A1F2E``. Циан ``#00E5FF`` не берём.
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
        return (
            f'tl.fromTo("{sel}",{{{frm}}},{{{too},duration:{_bfc_n(dur)},'
            f'ease:"{ease}"{flag}}},{_bfc_n(start)});')

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
    "code_3d_extrude": fs_code_3d_extrude,
    "code_diff": fs_code_diff,
    "code_particle_assemble": fs_code_particle_assemble,
    "code_scroll": fs_code_scroll,
    "code_typing": fs_code_typing,
    "terminal_simulator": fs_terminal_simulator,
    "apple_terminal_clear_dark": fs_apple_terminal_clear_dark,
    "dark_plus": fs_dark_plus,
    "beat_freeze_cut": fs_beat_freeze_cut,
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
    if params.get("code_3d_extrude"):
        return fs_code_3d_extrude(ctx)
    if params.get("code_diff"):
        return fs_code_diff(ctx)
    if params.get("code_particle_assemble"):
        return fs_code_particle_assemble(ctx)
    if params.get("code_scroll"):
        return fs_code_scroll(ctx)
    if params.get("code_typing"):
        return fs_code_typing(ctx)
    if params.get("terminal_simulator"):
        return fs_terminal_simulator(ctx)
    if params.get("apple_terminal_clear_dark"):
        return fs_apple_terminal_clear_dark(ctx)
    if params.get("dark_plus"):
        return fs_dark_plus(ctx)
    if params.get("beat_freeze_cut"):
        return fs_beat_freeze_cut(ctx)
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


# Каталог lt-clean-bar: 4.8 с, clip-path wipe, tab scaleY, имя/роль ↑.
_LT_CB_TAB_W = 12
_LT_CB_PAD_L = 30
_LT_CB_PAD_R = 40
_LT_CB_PAD_T = 22
_LT_CB_PAD_B = 24
_LT_CB_GAP = 7
_LT_CB_NAME_CEILING = 52
_LT_CB_ROLE_SIZE = 26
_LT_CB_NAME_LH = 1.06
_LT_CB_ROLE_LH = 1.2
_LT_CB_SLACK = 1.14
_LT_CB_FROM_Y = 22
_LT_CB_EXIT_Y = 18


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


def ov_lt_clean_bar(ctx: "TemplateCtx") -> Piece:
    """Белая плашка с акцентной полоской: wipe слева, tab растёт, текст ↑.

    Каталог твинит ``clip-path`` и прячет карточку через ``visibility``.
    Движок этого не умеет: wipe — SVG-mask и ``scaleX`` на rect, как у
    caption-clip-wipe. Оранжевый ``#ff5a36`` — чужой бренд, tab канала
    ``#C8453D``. Montserrat как в каталоге. Твины на маске, tab и строках,
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
               f'width="{card_w}" height="{card_h}" fill="#fff"/></mask></defs>'
               f'</svg>'
               f'<span id="{node_id}-card" class="lt-cb-card" '
               f'style="-webkit-mask:url(#{node_id}-m);mask:url(#{node_id}-m)">'
               f'<span id="{node_id}-tab" class="lt-cb-tab"></span>'
               f'<span class="lt-cb-body">{"".join(rows)}</span></span></span></div>'],
        tweens=tweens)


# Каталог lt-dark-card: 4.8 с, угольная карточка, имя, черта scaleX, роль.
_LT_DC_PAD_L = 32
_LT_DC_PAD_R = 38
_LT_DC_NAME_CEILING = 48
_LT_DC_ROLE_SIZE = 25
_LT_DC_SLACK = 1.14
_LT_DC_CARD_FROM_Y = 60
_LT_DC_NAME_FROM_Y = 14
_LT_DC_EXIT_Y = 24


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


def ov_lt_dark_card(ctx: "TemplateCtx") -> Piece:
    """Угольная карточка на светлом футаже: имя, черта left→right, роль.

    Каталог твинит ``tl.to`` после ``gsap.set`` и прячет обёртку через
    ``visibility``. Движок требует ``fromTo`` на вложенных узлах; ``visibility``
    вне списка. Золото ``#f5b942`` — чужой бренд, черта канала ``#C8453D``.
    Уголь ``#16181d`` и Montserrat как в каталоге — это сам жест. Твины на
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


from .acr_chat import acr_overlay_css, ov_ai_chat_reveal


OVERLAYS: dict[str, Callable[["TemplateCtx"], Piece]] = {
    "source_card": ov_source_card,
    "chat_thread": ov_chat_thread,
    "article_scroll": ov_article_scroll,
    "paper_reveal": ov_paper_reveal,
    "lt_accent_underline": ov_lt_accent_underline,
    "lt_clean_bar": ov_lt_clean_bar,
    "lt_dark_card": ov_lt_dark_card,
    "ai_chat_reveal": ov_ai_chat_reveal,
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
        ".fullscreen-text.fs-code-3d{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;display:flex;"
        "align-items:center;justify-content:center;background:#05070b;"
        "font-family:'JetBrains Mono',var(--font-mono),monospace;font-weight:600;"
        "text-transform:none;letter-spacing:0}"
        ".fullscreen-text.fs-code-3d.invert{background:#05070b;color:#e1e4e8}"
        ".fullscreen-text .c3d-stage{display:flex;align-items:center;"
        "justify-content:center;width:100%;height:100%}"
        ".fullscreen-text .c3d-slab{position:relative;display:inline-block;"
        "max-width:88%;will-change:transform}"
        ".fullscreen-text .c3d-edge{position:absolute;inset:0;border-radius:14px;"
        "background:#141d2b;transform:translate(14px,16px);z-index:0}"
        ".fullscreen-text .c3d-face{position:relative;z-index:1;display:flex;"
        "flex-direction:column;align-items:flex-start;gap:0;"
        "padding:28px 32px;border-radius:14px;background:#24292e;color:#e1e4e8;"
        "box-shadow:0 22px 54px rgba(0,0,0,0.55),-10px -8px 28px rgba(79,255,160,0.16),"
        "12px 10px 32px rgba(188,212,255,0.14)}"
        ".fullscreen-text .c3d-line{display:block;white-space:pre;font-weight:600;"
        "letter-spacing:0}"
        ".fullscreen-text .c3d-tok{font-weight:600}"
        ".fullscreen-text.fs-code-diff{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;display:flex;"
        "align-items:center;justify-content:center;"
        "background:radial-gradient(120% 70% at 50% 18%,#0e1726 0%,#05070b 72%);"
        "font-family:'JetBrains Mono',var(--font-mono),monospace;font-weight:500;"
        "text-transform:none;letter-spacing:0;color:#e6edf3}"
        ".fullscreen-text.fs-code-diff.invert{background:#05070b;color:#e6edf3}"
        ".fullscreen-text .cd-stage{display:flex;align-items:center;"
        "justify-content:center;width:100%;height:100%}"
        ".fullscreen-text .cd-editor{position:relative;display:flex;"
        "flex-direction:column;width:92%;max-width:1000px;max-height:78%;"
        "background:#0b0f17;border:1px solid #1d2733;border-radius:16px;"
        "box-shadow:0 40px 120px rgba(0,0,0,0.6),0 2px 0 rgba(255,255,255,0.03) inset;"
        "overflow:hidden;will-change:transform,opacity}"
        ".fullscreen-text .cd-titlebar{display:flex;align-items:center;gap:14px;"
        "flex:0 0 52px;height:52px;padding:0 20px;"
        "background:linear-gradient(#11161f,#0c111a);border-bottom:1px solid #1b2430}"
        ".fullscreen-text .cd-dots{display:flex;gap:8px}"
        ".fullscreen-text .cd-dot{display:block;width:12px;height:12px;"
        "border-radius:50%}"
        ".fullscreen-text .cd-dot-r{background:#ff5f57}"
        ".fullscreen-text .cd-dot-y{background:#febc2e}"
        ".fullscreen-text .cd-dot-g{background:#28c840}"
        ".fullscreen-text .cd-filename{font-size:16px;color:#8b98a9;"
        "letter-spacing:0.2px;text-transform:none}"
        ".fullscreen-text .cd-file{color:#d6e2f0}"
        ".fullscreen-text .cd-surface{position:relative;flex:1 1 auto;"
        "overflow:hidden}"
        ".fullscreen-text .cd-code{position:relative;display:block;width:100%;"
        "font-variant-ligatures:none}"
        ".fullscreen-text .cd-line{position:absolute;left:0;right:0;"
        "display:block;overflow:hidden;white-space:pre;padding-left:14px;"
        "transform-origin:50% 0%;will-change:transform,opacity}"
        ".fullscreen-text .cd-sign{display:inline-block;width:1.1em;"
        "color:#415062}"
        ".fullscreen-text .cd-del{background:rgba(248,81,73,0.12);"
        "box-shadow:inset 3px 0 #f85149}"
        ".fullscreen-text .cd-add{background:rgba(63,185,80,0.12);"
        "box-shadow:inset 3px 0 #3fb950}"
        ".fullscreen-text .cd-del .cd-sign{color:#f85149}"
        ".fullscreen-text .cd-add .cd-sign{color:#3fb950}"
        ".fullscreen-text .cd-tok{font-weight:500}"
        ".fullscreen-text.fs-code-pa{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;display:flex;"
        "align-items:center;justify-content:center;background:#05070b;"
        "font-family:'JetBrains Mono',var(--font-mono),monospace;font-weight:700;"
        "text-transform:none;letter-spacing:0;color:#e1e4e8}"
        ".fullscreen-text.fs-code-pa.invert{background:#05070b;color:#e1e4e8}"
        ".fullscreen-text .pa-stage{position:relative;display:flex;"
        "align-items:center;justify-content:center;width:100%;height:100%}"
        ".fullscreen-text .pa-dust{position:absolute;inset:0;z-index:1;"
        "pointer-events:none}"
        ".fullscreen-text .pa-dot{position:absolute;display:block;"
        "border-radius:50%;pointer-events:none;will-change:transform,opacity;"
        "box-shadow:0 0 10px rgba(225,228,232,0.4)}"
        ".fullscreen-text .pa-code{position:relative;z-index:2;display:flex;"
        "flex-direction:column;align-items:flex-start;box-sizing:border-box;"
        "opacity:0;white-space:pre;text-align:left;font-variant-ligatures:none;"
        "pointer-events:none}"
        ".fullscreen-text .pa-line{display:block;white-space:pre;font-weight:700;"
        "letter-spacing:0}"
        ".fullscreen-text .pa-tok{font-weight:700}"
        ".fullscreen-text.fs-code-scroll{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;display:flex;"
        "align-items:center;justify-content:center;"
        "background:radial-gradient(120% 70% at 50% 18%,#0e1726 0%,#05070b 72%);"
        "font-family:'JetBrains Mono',var(--font-mono),monospace;font-weight:500;"
        "text-transform:none;letter-spacing:0;color:#e6edf3}"
        ".fullscreen-text.fs-code-scroll.invert{background:#05070b;color:#e6edf3}"
        ".fullscreen-text .cs-stage{position:relative;display:flex;"
        "align-items:center;justify-content:center;width:100%;height:100%}"
        ".fullscreen-text .cs-grid{position:absolute;inset:0;z-index:0;"
        "pointer-events:none;background-image:linear-gradient("
        "rgba(88,166,255,0.05) 1px,transparent 1px),linear-gradient("
        "90deg,rgba(88,166,255,0.05) 1px,transparent 1px);background-size:48px 48px}"
        ".fullscreen-text .cs-glow{position:absolute;width:520px;height:520px;"
        "border-radius:50%;filter:blur(90px);opacity:0.5;pointer-events:none;"
        "z-index:0}"
        ".fullscreen-text .cs-glow-a{background:#1f6feb55;left:-80px;top:-120px}"
        ".fullscreen-text .cs-glow-b{background:#2ea04355;right:-100px;bottom:-160px}"
        ".fullscreen-text .cs-editor{position:relative;z-index:1;display:flex;"
        "flex-direction:column;box-sizing:border-box;background:#0b0f17;"
        "border:1px solid #1d2733;border-radius:16px;"
        "box-shadow:0 40px 120px rgba(0,0,0,0.6),0 2px 0 rgba(255,255,255,0.03) inset;"
        "overflow:hidden;will-change:transform,opacity}"
        ".fullscreen-text .cs-titlebar{display:flex;align-items:center;gap:14px;"
        "flex:0 0 48px;height:48px;padding:0 18px;"
        "background:linear-gradient(#11161f,#0c111a);border-bottom:1px solid #1b2430}"
        ".fullscreen-text .cs-dots{display:flex;gap:8px}"
        ".fullscreen-text .cs-dot{display:block;width:12px;height:12px;"
        "border-radius:50%}"
        ".fullscreen-text .cs-dot-r{background:#ff5f57}"
        ".fullscreen-text .cs-dot-y{background:#febc2e}"
        ".fullscreen-text .cs-dot-g{background:#28c840}"
        ".fullscreen-text .cs-filename{font-size:15px;color:#8b98a9;"
        "letter-spacing:0.2px;text-transform:none}"
        ".fullscreen-text .cs-file{color:#d6e2f0}"
        ".fullscreen-text .cs-surface{position:relative;flex:0 0 auto;"
        "overflow:hidden}"
        ".fullscreen-text .cs-scroll{position:relative;display:block;"
        "will-change:transform,opacity;opacity:0}"
        ".fullscreen-text .cs-gutter{position:absolute;left:0;z-index:1;"
        "text-align:right;color:#828c9b;user-select:none;"
        "font-variant-ligatures:none}"
        ".fullscreen-text .cs-gn{display:block}"
        ".fullscreen-text .cs-code{position:relative;display:block;width:100%;"
        "box-sizing:border-box;font-variant-ligatures:none;tab-size:2;"
        "text-align:left;text-transform:none}"
        ".fullscreen-text .cs-line{display:block;white-space:pre;position:relative;"
        "z-index:1;text-transform:none;font-weight:500}"
        ".fullscreen-text .cs-tok{font-weight:500}"
        ".fullscreen-text .cs-hl{position:absolute;left:0;right:0;z-index:0;"
        "background:rgba(88,166,255,0.16);border-left:3px solid #58a6ff;"
        "border-radius:6px;pointer-events:none;opacity:0}"
        ".fullscreen-text.fs-code-typing{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;display:flex;"
        "align-items:center;justify-content:center;"
        "background:radial-gradient(120% 70% at 50% 18%,#0e1726 0%,#05070b 72%);"
        "font-family:'JetBrains Mono',var(--font-mono),monospace;font-weight:500;"
        "text-transform:none;letter-spacing:0;color:#e6edf3}"
        ".fullscreen-text.fs-code-typing.invert{background:#05070b;color:#e6edf3}"
        ".fullscreen-text .ct-stage{position:relative;display:flex;"
        "align-items:center;justify-content:center;width:100%;height:100%}"
        ".fullscreen-text .ct-grid{position:absolute;inset:0;z-index:0;"
        "pointer-events:none;background-image:linear-gradient("
        "rgba(88,166,255,0.05) 1px,transparent 1px),linear-gradient("
        "90deg,rgba(88,166,255,0.05) 1px,transparent 1px);background-size:48px 48px}"
        ".fullscreen-text .ct-glow{position:absolute;width:520px;height:520px;"
        "border-radius:50%;filter:blur(90px);opacity:0.5;pointer-events:none;"
        "z-index:0}"
        ".fullscreen-text .ct-glow-a{background:#1f6feb55;left:-80px;top:-120px}"
        ".fullscreen-text .ct-glow-b{background:#2ea04355;right:-100px;bottom:-160px}"
        ".fullscreen-text .ct-editor{position:relative;z-index:1;display:flex;"
        "flex-direction:column;box-sizing:border-box;background:#0b0f17;"
        "border:1px solid #1d2733;border-radius:16px;"
        "box-shadow:0 40px 120px rgba(0,0,0,0.6),0 2px 0 rgba(255,255,255,0.03) inset;"
        "overflow:hidden;will-change:transform,opacity}"
        ".fullscreen-text .ct-titlebar{display:flex;align-items:center;gap:14px;"
        "flex:0 0 48px;height:48px;padding:0 18px;"
        "background:linear-gradient(#11161f,#0c111a);border-bottom:1px solid #1b2430}"
        ".fullscreen-text .ct-dots{display:flex;gap:8px}"
        ".fullscreen-text .ct-dot{display:block;width:12px;height:12px;"
        "border-radius:50%}"
        ".fullscreen-text .ct-dot-r{background:#ff5f57}"
        ".fullscreen-text .ct-dot-y{background:#febc2e}"
        ".fullscreen-text .ct-dot-g{background:#28c840}"
        ".fullscreen-text .ct-filename{font-size:15px;color:#8b98a9;"
        "letter-spacing:0.2px;text-transform:none}"
        ".fullscreen-text .ct-file{color:#d6e2f0}"
        ".fullscreen-text .ct-surface{position:relative;flex:0 0 auto;"
        "overflow:hidden}"
        ".fullscreen-text .ct-scene{position:relative;display:block;width:100%;"
        "height:100%;opacity:0}"
        ".fullscreen-text .ct-gutter{position:absolute;left:0;z-index:1;"
        "text-align:right;color:#828c9b;user-select:none;"
        "font-variant-ligatures:none}"
        ".fullscreen-text .ct-gn{display:block}"
        ".fullscreen-text .ct-code{position:relative;display:block;width:100%;"
        "box-sizing:border-box;font-variant-ligatures:none;tab-size:2;"
        "text-align:left;text-transform:none}"
        ".fullscreen-text .ct-line{display:block;white-space:pre;position:relative;"
        "z-index:1;text-transform:none;font-weight:500}"
        ".fullscreen-text .ct-ch{display:inline-block;white-space:pre;opacity:0;"
        "font-weight:500;will-change:opacity}"
        ".fullscreen-text .ct-caret{position:absolute;left:0;top:0;z-index:3;"
        "background:#58a6ff;border-radius:1px;pointer-events:none;"
        "will-change:transform}"
        ".fullscreen-text.fs-terminal-simulator{width:var(--frame-w);"
        "height:var(--frame-h);padding:0;overflow:hidden;isolation:isolate;"
        "display:flex;align-items:center;justify-content:center;"
        "background:#f7f7f8;color:#e4e4e7;"
        "font-family:'JetBrains Mono',var(--font-mono),monospace;"
        "font-weight:500;text-transform:none;letter-spacing:0}"
        ".fullscreen-text.fs-terminal-simulator.invert{background:#f7f7f8;"
        "color:#e4e4e7}"
        ".fullscreen-text .ts-stage{position:relative;display:flex;"
        "align-items:center;justify-content:center;width:100%;height:100%}"
        ".fullscreen-text .ts-card{position:relative;z-index:1;display:flex;"
        "flex-direction:column;box-sizing:border-box;background:#0f172a;"
        "color:#e4e4e7;overflow:hidden}"
        ".fullscreen-text .ts-chrome{display:flex;align-items:center;gap:8px;"
        "flex:0 0 auto;padding:0 18px;background:#111827;color:#94a3b8;"
        "text-transform:none}"
        ".fullscreen-text .ts-dots{display:flex;align-items:center}"
        ".fullscreen-text .ts-dot{display:block;border-radius:999px}"
        ".fullscreen-text .ts-dot-r{background:#ef4444}"
        ".fullscreen-text .ts-dot-y{background:#f59e0b}"
        ".fullscreen-text .ts-dot-g{background:#22c55e}"
        ".fullscreen-text .ts-title{text-transform:none;color:#94a3b8}"
        ".fullscreen-text .ts-body{display:grid;min-height:0}"
        ".fullscreen-text .ts-files{box-sizing:border-box;"
        "border-right:1px solid rgba(148,163,184,0.18);color:#94a3b8;"
        "text-align:left;text-transform:none;line-height:1.8}"
        ".fullscreen-text .ts-editor{box-sizing:border-box;display:grid;"
        "align-content:start}"
        ".fullscreen-text .ts-line{display:block;border-radius:999px;"
        "background:rgba(228,228,231,0.18);transform-origin:left center;"
        "opacity:0;will-change:transform,opacity}"
        ".fullscreen-text .ts-term{box-sizing:border-box;"
        "border-top:1px solid rgba(148,163,184,0.18);color:#86efac;"
        "text-align:left;text-transform:none;opacity:0;"
        "will-change:transform,opacity}"
        ".fullscreen-text.fs-apple-terminal-clear-dark{width:var(--frame-w);"
        "height:var(--frame-h);padding:0;overflow:hidden;isolation:isolate;"
        "display:flex;align-items:center;justify-content:center;"
        "background:linear-gradient(135deg,#1a1a1a 0%,#111111 100%);"
        "color:#ffffff;font-family:'JetBrains Mono',var(--font-mono),monospace;"
        "font-weight:400;text-transform:none;letter-spacing:0}"
        ".fullscreen-text.fs-apple-terminal-clear-dark.invert{"
        "background:linear-gradient(135deg,#1a1a1a 0%,#111111 100%);color:#ffffff}"
        ".fullscreen-text .atcd-stage{position:relative;display:flex;"
        "align-items:center;justify-content:center;width:100%;height:100%}"
        ".fullscreen-text .atcd-window{position:relative;z-index:1;display:flex;"
        "flex-direction:column;box-sizing:border-box;overflow:hidden;"
        "box-shadow:0 30px 80px rgba(0,0,0,0.7),0 10px 30px rgba(0,0,0,0.5)}"
        ".fullscreen-text .atcd-bar{position:relative;display:flex;"
        "align-items:center;flex:0 0 42px;height:42px;padding:0 14px;"
        "background:rgba(0,0,0,0.4);border-bottom:1px solid rgba(255,255,255,0.08)}"
        ".fullscreen-text .atcd-lights{display:flex;align-items:center;gap:8px;"
        "z-index:1}"
        ".fullscreen-text .atcd-dot{display:block;width:13px;height:13px;"
        "border-radius:50%}"
        ".fullscreen-text .atcd-close{background:#ff5f57;border:1px solid #e0443e}"
        ".fullscreen-text .atcd-min{background:#ffbd2e;border:1px solid #dfa123}"
        ".fullscreen-text .atcd-full{background:#28c840;border:1px solid #1aab29}"
        ".fullscreen-text .atcd-title{position:absolute;left:0;right:0;"
        "text-align:center;font-family:Inter,system-ui,sans-serif;font-size:13px;"
        "font-weight:500;color:#ffffff;letter-spacing:-0.1px;"
        "text-transform:none;pointer-events:none}"
        ".fullscreen-text .atcd-canvas{flex:1;box-sizing:border-box;"
        "background:rgba(0,0,0,0.7);color:#ffffff;text-align:left;"
        "text-transform:none;overflow:hidden;line-height:1.6}"
        ".fullscreen-text .atcd-out{display:block;margin-bottom:4px}"
        ".fullscreen-text .atcd-line{display:block;white-space:pre;opacity:0;"
        "color:#ffffff;text-transform:none;will-change:opacity}"
        ".fullscreen-text .atcd-dim{color:rgba(255,255,255,0.6)}"
        ".fullscreen-text .atcd-bold{font-weight:700;color:#ffffff}"
        ".fullscreen-text .atcd-slot{position:relative;display:block}"
        ".fullscreen-text .atcd-input{display:flex;align-items:center;"
        "white-space:pre;text-transform:none;will-change:opacity}"
        ".fullscreen-text .atcd-input-next{position:absolute;left:0;top:0;"
        "opacity:0}"
        ".fullscreen-text .atcd-prompt{color:#888888;font-weight:700;"
        "text-transform:none}"
        ".fullscreen-text .atcd-cmd{display:inline;color:#ffffff;"
        "will-change:opacity}"
        ".fullscreen-text .atcd-ch{display:inline;white-space:pre;opacity:0;"
        "color:#ffffff;text-transform:none;will-change:opacity}"
        ".fullscreen-text .atcd-cursor{display:inline-block;flex:0 0 auto;"
        "background:#888888;margin-left:1px;vertical-align:text-bottom;"
        "will-change:opacity}"
        ".fullscreen-text.fs-dark-plus{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;display:flex;"
        "align-items:stretch;justify-content:center;"
        "background:linear-gradient(180deg,rgba(0,0,0,0.16),rgba(0,0,0,0.32)),#0a0a0a;"
        "color:#d4d4d4;font-family:Inter,system-ui,sans-serif;font-weight:400;"
        "text-transform:none;letter-spacing:0}"
        ".fullscreen-text.fs-dark-plus.invert{"
        "background:linear-gradient(180deg,rgba(0,0,0,0.16),rgba(0,0,0,0.32)),#0a0a0a;"
        "color:#d4d4d4}"
        ".fullscreen-text .dp-stage{position:relative;display:flex;"
        "flex-direction:column;gap:12px;width:100%;height:100%;box-sizing:border-box}"
        ".fullscreen-text .dp-header{display:flex;align-items:flex-end;"
        "justify-content:space-between;flex:0 0 auto;will-change:transform,opacity}"
        ".fullscreen-text .dp-kicker{display:block;margin:0 0 7px;color:#6e7681;"
        "font-size:13px;font-weight:650;text-transform:uppercase}"
        ".fullscreen-text .dp-title{display:block;color:#cccccc;font-size:36px;"
        "line-height:1;font-weight:760;text-transform:none}"
        ".fullscreen-text .dp-note{width:42%;color:#6e7681;font-size:14px;"
        "line-height:1.35;text-align:right;text-transform:none}"
        ".fullscreen-text .dp-src{color:#9d9d9d}"
        ".fullscreen-text .dp-wb{position:relative;display:grid;overflow:hidden;"
        "border:1px solid #2b2b2b;border-radius:8px;background:#1e1e1e;"
        "box-shadow:0 34px 90px rgba(0,0,0,0.42);transform-origin:82% 50%;"
        "will-change:transform,opacity}"
        ".fullscreen-text .dp-titlebar{grid-column:1/-1;display:grid;"
        "grid-template-columns:110px 1fr 160px;align-items:center;"
        "background:#181818;color:#cccccc;border-bottom:1px solid #2b2b2b;"
        "font-size:12px}"
        ".fullscreen-text .dp-traffic{display:flex;gap:8px;padding-left:16px}"
        ".fullscreen-text .dp-traffic span{display:block;width:12px;height:12px;"
        "border-radius:999px}"
        ".fullscreen-text .dp-traffic span:nth-child(1){background:#ff5f57}"
        ".fullscreen-text .dp-traffic span:nth-child(2){background:#ffbd2e}"
        ".fullscreen-text .dp-traffic span:nth-child(3){background:#28c840}"
        ".fullscreen-text .dp-wintitle{justify-self:center;opacity:0.84;"
        "text-transform:none}"
        ".fullscreen-text .dp-search{justify-self:end;width:140px;height:20px;"
        "margin-right:12px;display:flex;align-items:center;justify-content:center;"
        "border:1px solid rgba(204,204,204,0.22);border-radius:5px;color:#9d9d9d}"
        ".fullscreen-text .dp-activity{grid-row:2/3;background:#181818;"
        "border-right:1px solid #2b2b2b;display:flex;flex-direction:column;"
        "align-items:center;padding:10px 0;gap:16px}"
        ".fullscreen-text .dp-icon{display:block;width:22px;height:22px;"
        "color:#868686}"
        ".fullscreen-text .dp-icon-on{color:#d7d7d7;border-left:2px solid #0078d4;"
        "padding-left:3px}"
        ".fullscreen-text .dp-sidebar{grid-row:2/3;background:#181818;color:#cccccc;"
        "border-right:1px solid #2b2b2b;display:flex;flex-direction:column;"
        "min-width:0;text-transform:none}"
        ".fullscreen-text .dp-side-title{height:32px;display:flex;align-items:center;"
        "padding:0 16px;font-size:11px;text-transform:uppercase;color:#bbbbbb}"
        ".fullscreen-text .dp-sec{height:22px;display:flex;align-items:center;"
        "gap:6px;padding:0 12px;background:#1f1f1f;border-top:1px solid #2b2b2b;"
        "border-bottom:1px solid #2b2b2b;font-size:11px;font-weight:700}"
        ".fullscreen-text .dp-tree{padding:6px 0;font-size:12px;line-height:22px}"
        ".fullscreen-text .dp-row{display:flex;align-items:center;height:22px;"
        "padding:0 8px 0 14px;color:#cccccc;white-space:nowrap}"
        ".fullscreen-text .dp-child{padding-left:28px}"
        ".fullscreen-text .dp-sel{background:rgba(204,204,204,0.12)}"
        ".fullscreen-text .dp-editor-area{grid-row:2/3;display:grid;min-width:0;"
        "background:#1e1e1e}"
        ".fullscreen-text .dp-tabs{display:flex;background:#181818;"
        "border-bottom:1px solid #2b2b2b}"
        ".fullscreen-text .dp-tab{height:32px;display:flex;align-items:center;"
        "gap:8px;padding:0 12px;border-right:1px solid #2b2b2b;background:#1f1f1f;"
        "color:#ffffff;border-top:2px solid #0078d4;font-size:12px;"
        "text-transform:none}"
        ".fullscreen-text .dp-tab-off{background:#181818;color:#9d9d9d;"
        "border-top-color:transparent}"
        ".fullscreen-text .dp-crumbs{display:flex;align-items:center;padding:0 14px;"
        "color:#6e7681;border-bottom:1px solid #2b2b2b;font-size:11px;"
        "text-transform:none}"
        ".fullscreen-text .dp-editor{position:relative;overflow:hidden;"
        "background:#1e1e1e;color:#d4d4d4;"
        "font-family:'JetBrains Mono',var(--font-mono),monospace;"
        "line-height:1.52;text-transform:none}"
        ".fullscreen-text .dp-hl{position:absolute;left:0;right:0;"
        "background:rgba(255,255,255,0.04);opacity:0;will-change:transform,opacity}"
        ".fullscreen-text .dp-col{position:relative;display:block}"
        ".fullscreen-text .dp-line{display:grid;grid-template-columns:48px 1fr;"
        "align-items:center}"
        ".fullscreen-text .dp-ln{padding-right:10px;color:#6e7681;text-align:right;"
        "font-family:'JetBrains Mono',var(--font-mono),monospace}"
        ".fullscreen-text .dp-code{white-space:pre;text-align:left}"
        ".fullscreen-text .dp-ch{display:inline;white-space:pre;opacity:0;"
        "text-transform:none;will-change:opacity}"
        ".fullscreen-text .dp-tok-comment{color:#6A9955}"
        ".fullscreen-text .dp-tok-keyword{color:#d7ba7d}"
        ".fullscreen-text .dp-tok-function{color:#DCDCAA}"
        ".fullscreen-text .dp-tok-string{color:#d16969}"
        ".fullscreen-text .dp-tok-number{color:#b5cea8}"
        ".fullscreen-text .dp-tok-variable{color:#4FC1FF}"
        ".fullscreen-text .dp-tok-parameter{color:#9CDCFE}"
        ".fullscreen-text .dp-tok-operator{color:#d7ba7d}"
        ".fullscreen-text .dp-tok-punctuation{color:#CE9178}"
        ".fullscreen-text .dp-tok-class-name{color:#4EC9B0}"
        ".fullscreen-text .dp-caret{position:absolute;left:0;top:0;z-index:3;"
        "display:block;background:#d4d4d4;pointer-events:none;"
        "will-change:transform,opacity}"
        ".fullscreen-text .dp-term{display:grid;grid-template-rows:28px 1fr;"
        "background:#181818;border-top:1px solid #2b2b2b;color:#d4d4d4;"
        "font-family:'JetBrains Mono',var(--font-mono),monospace;font-size:12px;"
        "opacity:0;text-transform:none;will-change:transform,opacity}"
        ".fullscreen-text .dp-ptabs{display:flex;align-items:center;gap:18px;"
        "padding:0 14px;border-bottom:1px solid #2b2b2b;color:#6e7681;"
        "font-family:Inter,system-ui,sans-serif;font-size:11px;"
        "text-transform:uppercase}"
        ".fullscreen-text .dp-pon{color:#d4d4d4;border-bottom:1px solid #0078d4;"
        "height:28px;display:flex;align-items:center}"
        ".fullscreen-text .dp-tbody{padding:8px 16px;line-height:1.7}"
        ".fullscreen-text .dp-tb{display:block;opacity:0;will-change:transform,opacity}"
        ".fullscreen-text .dp-prompt{color:#DCDCAA}"
        ".fullscreen-text .dp-status{grid-column:1/-1;display:flex;align-items:center;"
        "justify-content:space-between;background:#181818;color:#cccccc;"
        "border-top:1px solid #2b2b2b;font-size:11px}"
        ".fullscreen-text .dp-stat-l,.fullscreen-text .dp-stat-r{display:flex;"
        "align-items:center;gap:14px;padding:0 10px}"
        ".fullscreen-text .dp-remote{align-self:stretch;display:flex;"
        "align-items:center;padding:0 10px;margin-left:-10px;background:#16825D;"
        "color:#ffffff}"
        ".fullscreen-text .dp-stage svg{display:block}"
        ".fullscreen-text.fs-beat-freeze-cut{width:var(--frame-w);height:var(--frame-h);"
        "padding:0;overflow:hidden;isolation:isolate;display:flex;"
        "align-items:stretch;justify-content:center;background:#0B132B;"
        "color:#ffffff;font-family:Inter,system-ui,sans-serif;font-weight:700;"
        "text-transform:none;letter-spacing:0}"
        ".fullscreen-text.fs-beat-freeze-cut.invert{background:#0B132B;color:#ffffff}"
        ".fullscreen-text .bfc-stage{position:relative;display:block;width:100%;"
        "height:100%}"
        ".fullscreen-text .bfc-bg{position:absolute;inset:0;background:"
        "radial-gradient(ellipse 80% 60% at 50% 40%,rgba(230,57,70,0.10) 0%,"
        "transparent 55%),radial-gradient(ellipse 50% 40% at 80% 80%,"
        "rgba(255,255,255,0.03) 0%,transparent 50%),#0B132B}"
        ".fullscreen-text .bfc-grid{position:absolute;inset:0;opacity:0.22;"
        "background-image:linear-gradient(rgba(255,255,255,0.04) 1px,transparent 1px),"
        "linear-gradient(90deg,rgba(255,255,255,0.04) 1px,transparent 1px);"
        "background-size:80px 80px;pointer-events:none}"
        ".fullscreen-text .bfc-zoom{position:absolute;inset:0;display:block;"
        "transform-origin:50% 50%;will-change:transform}"
        ".fullscreen-text .bfc-shot-a,.fullscreen-text .bfc-shot-b,"
        ".fullscreen-text .bfc-crop{position:absolute;inset:0;display:block;"
        "overflow:hidden}"
        ".fullscreen-text .bfc-crop{display:flex;align-items:center;"
        "justify-content:center;transform-origin:50% 50%;will-change:transform}"
        ".fullscreen-text .bfc-shot-b{opacity:0;display:flex;flex-direction:column;"
        "justify-content:center;padding:72px 48px 96px;will-change:opacity}"
        ".fullscreen-text .bfc-card{position:relative;width:900px;height:1020px;"
        "border-radius:32px;overflow:hidden;"
        "background:linear-gradient(160deg,rgba(255,255,255,0.06) 0%,transparent 40%),"
        "linear-gradient(180deg,#1A1F2E 0%,#0B132B 100%);"
        "border:1px solid rgba(255,255,255,0.08);"
        "box-shadow:0 40px 120px rgba(0,0,0,0.55),0 0 0 1px rgba(230,57,70,0.12),"
        "inset 0 1px 0 rgba(255,255,255,0.06);will-change:transform,opacity}"
        ".fullscreen-text .bfc-glow{position:absolute;left:50%;top:28%;width:380px;"
        "height:380px;margin-left:-190px;margin-top:-190px;border-radius:50%;"
        "background:radial-gradient(circle,rgba(230,57,70,0.32) 0%,transparent 68%);"
        "pointer-events:none}"
        ".fullscreen-text .bfc-wave{position:absolute;left:56px;right:56px;top:110px;"
        "height:200px}"
        ".fullscreen-text .bfc-wave svg{width:100%;height:100%;display:block}"
        ".fullscreen-text .bfc-wave-path{fill:none;stroke:#E63946;stroke-width:4;"
        "stroke-linecap:round;stroke-linejoin:round}"
        ".fullscreen-text .bfc-wave-fill{fill:#E63946;opacity:0.12}"
        ".fullscreen-text .bfc-bars{position:absolute;left:72px;right:72px;"
        "bottom:150px;height:96px;display:flex;align-items:flex-end;gap:8px}"
        ".fullscreen-text .bfc-bar{flex:1;height:40%;border-radius:6px 6px 2px 2px;"
        "background:linear-gradient(180deg,#E63946 0%,rgba(230,57,70,0.25) 100%);"
        "transform-origin:50% 100%;will-change:transform}"
        ".fullscreen-text .bfc-meta{position:absolute;left:56px;right:56px;"
        "bottom:52px;display:flex;align-items:center;justify-content:space-between}"
        ".fullscreen-text .bfc-kicker{font-size:16px;font-weight:600;"
        "letter-spacing:0.18em;text-transform:uppercase;color:#C7C9D1}"
        ".fullscreen-text .bfc-pill{font-size:14px;font-weight:700;"
        "letter-spacing:0.08em;text-transform:uppercase;color:#ffffff;"
        "background:#E63946;padding:8px 16px;border-radius:999px}"
        ".fullscreen-text .bfc-b-copy{display:flex;flex-direction:column;gap:22px;"
        "will-change:transform,opacity}"
        ".fullscreen-text .bfc-eyebrow{font-size:18px;font-weight:700;"
        "letter-spacing:0.22em;text-transform:uppercase;color:#E63946}"
        ".fullscreen-text .bfc-title{display:flex;flex-direction:column;"
        "font-size:108px;font-weight:900;line-height:0.92;letter-spacing:-0.04em;"
        "text-transform:uppercase;color:#ffffff}"
        ".fullscreen-text .bfc-accent-bar{width:120px;height:6px;border-radius:999px;"
        "background:#E63946}"
        ".fullscreen-text .bfc-sub{font-size:24px;font-weight:500;color:#C7C9D1;"
        "line-height:1.35;max-width:640px;text-transform:none}"
        ".fullscreen-text .bfc-b-list{display:flex;flex-direction:column;gap:18px;"
        "margin-top:48px}"
        ".fullscreen-text .bfc-b-card{display:flex;align-items:center;"
        "justify-content:space-between;gap:20px;padding:28px 30px;border-radius:20px;"
        "background:linear-gradient(135deg,#1A1F2E,#0B132B);"
        "border:1px solid rgba(255,255,255,0.08);"
        "box-shadow:0 18px 48px rgba(0,0,0,0.35);will-change:transform,opacity}"
        ".fullscreen-text .bfc-b-label{font-size:16px;font-weight:600;"
        "letter-spacing:0.12em;text-transform:uppercase;color:#C7C9D1}"
        ".fullscreen-text .bfc-b-value{font-size:32px;font-weight:800;"
        "letter-spacing:-0.03em;color:#ffffff;text-transform:none}"
        ".fullscreen-text .bfc-b-value.accent{color:#E63946}"
        ".fullscreen-text .bfc-intro{position:absolute;left:0;right:0;top:72px;"
        "display:flex;justify-content:center;pointer-events:none;z-index:20;"
        "opacity:0;will-change:transform,opacity}"
        ".fullscreen-text .bfc-intro-label{font-size:16px;font-weight:700;"
        "letter-spacing:0.28em;text-transform:uppercase;color:#C7C9D1;"
        "padding:10px 18px;border:1px solid rgba(255,255,255,0.08);"
        "border-radius:999px;background:rgba(11,19,43,0.55);"
        "backdrop-filter:blur(8px)}"
        ".fullscreen-text .bfc-hit{position:absolute;inset:0;display:flex;"
        "align-items:center;justify-content:center;pointer-events:none;z-index:30;"
        "opacity:0;font-size:120px;font-weight:900;letter-spacing:-0.04em;"
        "text-transform:uppercase;color:#ffffff;"
        "text-shadow:0 0 40px rgba(230,57,70,0.45),0 8px 40px rgba(0,0,0,0.55);"
        "will-change:transform,opacity}"
        ".fullscreen-text .bfc-outline{position:absolute;inset:48px;border:3px solid "
        "#E63946;border-radius:8px;box-shadow:0 0 0 1px rgba(230,57,70,0.25),"
        "inset 0 0 0 1px rgba(230,57,70,0.15),0 0 48px rgba(230,57,70,0.2);"
        "opacity:0;pointer-events:none;z-index:25;will-change:opacity}"
        ".fullscreen-text .bfc-flash{position:absolute;inset:0;background:#ffffff;"
        "opacity:0;mix-blend-mode:screen;pointer-events:none;z-index:26;"
        "will-change:opacity}"
        ".fullscreen-text .bfc-contour{position:absolute;inset:0;background:"
        "linear-gradient(90deg,transparent 0%,rgba(230,57,70,0.08) 48%,"
        "transparent 52%),radial-gradient(ellipse 40% 55% at 50% 48%,"
        "transparent 40%,rgba(230,57,70,0.18) 100%);opacity:0;"
        "mix-blend-mode:screen;pointer-events:none;z-index:25;will-change:opacity}"
        ".fullscreen-text .bfc-badge{position:absolute;top:80px;right:48px;"
        "font-size:15px;font-weight:800;letter-spacing:0.2em;text-transform:uppercase;"
        "color:#ffffff;background:#E63946;padding:10px 18px;border-radius:6px;"
        "opacity:0;z-index:27;will-change:opacity}"
        ".fullscreen-text .bfc-smear{position:absolute;inset:-8% -20%;"
        "pointer-events:none;z-index:40;opacity:0;background:linear-gradient(90deg,"
        "transparent 0%,rgba(230,57,70,0.12) 35%,rgba(255,255,255,0.55) 50%,"
        "rgba(230,57,70,0.12) 65%,transparent 100%);filter:blur(18px);"
        "transform-origin:50% 50%;will-change:transform,opacity}"
        ".fullscreen-text .bfc-blur{position:absolute;inset:0;pointer-events:none;"
        "z-index:39;opacity:0;backdrop-filter:blur(14px);"
        "background:rgba(11,19,43,0.12);will-change:opacity}"
        ".fullscreen-text .bfc-vignette{position:absolute;inset:0;pointer-events:none;"
        "z-index:15;background:radial-gradient(ellipse 75% 70% at 50% 50%,"
        "transparent 45%,rgba(0,0,0,0.55) 100%);opacity:0.85}"
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
        f".lt-clean-bar{{left:var(--safe-x-min);"
        f"bottom:{height - int(safe['y_max']) + 60}px;"
        "max-width:calc(var(--safe-x-max) - var(--safe-x-min));"
        "background:transparent}"
        ".lt-cb-stage{display:block;position:relative;overflow:visible}"
        ".lt-cb-svg{position:absolute;left:0;top:0;width:100%;height:100%;"
        "pointer-events:none}"
        ".lt-cb-wipe{transform-origin:0px 50%;transform-box:fill-box}"
        ".lt-cb-card{display:flex;align-items:stretch;width:100%;height:100%;"
        "border-radius:16px;overflow:hidden;"
        "box-shadow:0 14px 44px rgba(15,17,21,0.18)}"
        ".lt-cb-tab{display:block;width:12px;flex-shrink:0;background:#C8453D;"
        "transform-origin:50% 0%;will-change:transform}"
        ".lt-cb-body{display:flex;flex-direction:column;gap:7px;flex:1;"
        "background:#ffffff;padding:22px 40px 24px 30px}"
        ".lt-cb-name{display:block;font-family:'Montserrat',var(--font-subtitle),sans-serif;"
        "font-weight:700;color:#0f1115;line-height:1.06;letter-spacing:-0.015em;"
        "white-space:nowrap;will-change:transform,opacity}"
        ".lt-cb-role{display:block;font-family:'Montserrat',var(--font-subtitle),sans-serif;"
        "font-weight:400;color:#5a6170;line-height:1.2;letter-spacing:0.01em;"
        "white-space:nowrap;will-change:transform,opacity}"
        f".lt-dark-card{{left:var(--safe-x-min);"
        f"bottom:{height - int(safe['y_max']) + 60}px;"
        "max-width:calc(var(--safe-x-max) - var(--safe-x-min));"
        "background:transparent}"
        ".lt-dc-card{display:flex;flex-direction:column;gap:12px;"
        "background:#16181d;border-radius:14px;padding:24px 38px 26px 32px;"
        "box-shadow:0 18px 50px rgba(0,0,0,0.4);will-change:transform,opacity}"
        ".lt-dc-name{display:block;font-family:'Montserrat',var(--font-subtitle),sans-serif;"
        "font-weight:700;color:#ffffff;line-height:1.02;letter-spacing:-0.015em;"
        "white-space:nowrap;will-change:transform,opacity}"
        ".lt-dc-rule{display:block;height:4px;border-radius:2px;background:#C8453D;"
        "transform-origin:0% 50%;will-change:transform}"
        ".lt-dc-role{display:block;font-family:'Montserrat',var(--font-subtitle),sans-serif;"
        "font-weight:400;color:#aeb6c2;line-height:1.2;letter-spacing:0.02em;"
        "white-space:nowrap;will-change:opacity}"
        + acr_overlay_css()
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
