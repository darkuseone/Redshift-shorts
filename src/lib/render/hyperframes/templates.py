"""Каталог шаблонов (§15) в терминах HTML/CSS/GSAP.

92 шаблона каталога — это не 92 реализации, а 30 рендереров с параметрами.
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
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

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


# Ширина строки нужна, чтобы кегль подбирался под кадр, а не под догадку. Здесь
# стояла оценка «0.52 кегля на знак», и «ЕДИНСТВЕННЫЙ» из-за неё вылезал за
# кадр: у Oswald Bold прописная кириллица занимает 0.546…0.604 кегля, то есть
# оценка врала на 12 %. Меряем настоящей гарнитурой.
#
# Запасное значение — верх измеренного диапазона: без ассетов лучше ужать
# лишнего, чем обрезать слово.
_FALLBACK_EM_PER_CHAR = 0.62

# Толщина обводки строк «реплики от руки»: одно число на CSS и на подбор кегля.
SS_STROKE = 14


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


def widest(lines: Iterable[str]) -> str:
    """Самая широкая строка, а не самая длинная.

    «МОЛЧА? НАПИШИ» и «ГАЗ ИЛИ ПАДАЛ» — по 13 знаков, но первая шире второй на
    11 %: ширина знака в Oswald гуляет вдвое. Подбор кегля по длиннейшей строке
    поэтому обрезал самую широкую краем кадра — проверено кадром.
    """
    return max(lines, key=lambda line: text_width(str(line).upper(), 100),
               default="")


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
    longest = widest(lines)
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


def hero_script_stack(ctx: "TemplateCtx") -> Piece:
    """Реплика выкладывается строками поверх кадра, каждая — своим наездом.

    Референс: фраза разбита на две-три короткие строки, они встают одна под
    другой по ходу речи и остаются висеть. Каждая строка обведена толстым
    контуром — на любом футаже она читается, не завися от того, что под ней.

    Гарнитура референса рукописная, у нас её нет и завести её нельзя: шрифт
    проходит проверку на кириллицу и лицензию (§14). Поэтому берётся приём, а
    не начертание — обводка, наклон и выкладка строками, — на своём дисплейном
    шрифте. Небольшой наклон строк в разные стороны и держит «подпись от руки».
    """
    lines = [str(l).strip() for l in (ctx.params.get("lines") or []) if str(l).strip()]
    if not lines:
        return Piece()
    node_id = f"ss-{ctx.index:02d}"
    top = int(ctx.params.get("top", 150))
    # Строки идут через весь кадр, поэтому кегль подбирается по самой длинной:
    # фиксированный обрезал бы её краем.
    # Поле — по левой границе рабочей области (§3.2). Уходить в самый край, как
    # на референсе, нельзя: справа висит колонка лайков и комментариев, и под
    # ней букв не прочитать.
    safe = 2 * 90
    # Обводка рисуется наружу от глифа и добавляет по её ширине с каждой
    # стороны строки — в бюджет кегля она обязана входить.
    size = fit_size(widest(lines[:3]).upper(), 1080 - safe - 2 * SS_STROKE,
                    int(ctx.params.get("size", 132)))

    rows, tweens = [], []
    for i, line in enumerate(lines[:3]):
        tilt = (-1.6, 1.2, -0.9)[i % 3]
        rows.append(f'<span class="ss-line" style="font-size:{size}px;'
                    f'rotate:{tilt}deg">{_esc(line.upper())}</span>')
        # Строка приходит вслед за речью, а не всей пачкой: задержка растёт.
        tweens += enter_and_drift(f"#{node_id} .ss-line:nth-child({i + 1})",
                                  ctx.start, ctx.duration,
                                  name="zoom-in", delay=0.10 + 0.30 * i)

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-script-stack" '
               f'style="top:{top}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{"".join(rows)}</div>'],
        tweens=tweens)


def hero_chat_typing(ctx: "TemplateCtx") -> Piece:
    """Переписка: реплика набирается словами, ответ приходит скелетоном.

    Референс: запрос печатается в поле, отправляется, и на месте ответа сперва
    пульсируют серые плашки, а уже потом встаёт текст. Приём держится на этой
    паузе — она и читается как «машина думает».

    Печать посимвольно тут не годится: перемотка обязана давать тот же кадр,
    что и проигрывание, а посимвольная анимация текста этого не гарантирует.
    Слово за словом даёт ту же скорость чтения и остаётся перемотке по зубам.
    """
    ask = [w for w in str(ctx.params.get("ask") or "").split() if w]
    if not ask:
        return Piece()
    node_id = f"ct-{ctx.index:02d}"
    answer = str(ctx.params.get("answer") or "")
    app = str(ctx.params.get("app") or "")

    words, tweens = [], []
    for i, word in enumerate(ask[:8]):
        words.append(f'<span class="ct-w">{_esc(word)}</span>')
        tweens += entrance_tweens(f"#{node_id} .ct-w:nth-child({i + 1})",
                                  ctx.start, name="rise", delay=0.14 + 0.09 * i)

    typed_for = 0.14 + 0.09 * min(len(ask), 8)
    # Скелетон живёт ровно между отправкой и ответом; он не «мигает», а
    # выкладывается полосами — перемотка отдаёт то же самое.
    bars = "".join(f'<span class="ct-bar" style="width:{w}%"></span>'
                   for w in (92, 78, 54))
    for i in range(3):
        tweens += entrance_tweens(f"#{node_id} .ct-bar:nth-child({i + 1})",
                                  ctx.start, name="dim",
                                  delay=typed_for + 0.10 + 0.12 * i)

    answer_html = ""
    if answer:
        answer_html = f'<span class="ct-answer">{_esc(answer)}</span>'
        tweens += entrance_tweens(f"#{node_id} .ct-answer", ctx.start,
                                  name="zoom-in", delay=typed_for + 0.62)

    head = f'<span class="ct-app">{_esc(app)}</span>' if app else ""
    tweens = entrance_tweens(f"#{node_id} .ct-body", ctx.start,
                             name="zoom-out") + tweens
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-chat-typing" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">'
               f'<span class="ct-body">{head}'
               f'<span class="ct-ask">{"".join(words)}</span>'
               f'<span class="ct-skeleton">{bars}</span>'
               f'{answer_html}</span></div>'],
        tweens=tweens)


def hero_title_behind(ctx: "TemplateCtx") -> Piece:
    """Двухстрочный заголовок за головой: вторая строка — акцентом.

    Референс: тема ролика стоит крупно за ведущим и держится весь блок, пока
    внизу идут субтитры. Голова перекрывает низ второй строки — именно это
    даёт глубину и отличает приём от плашки поверх кадра.

    Вторая строка берёт акцентный цвет. В референсе он золотой, в каталог это
    не переносится: палитра своя (§3.3), акцент — приглушённый красный.
    """
    head = str(ctx.params.get("head") or "")
    tail = str(ctx.params.get("tail") or "")
    if not head or not tail:
        return Piece()
    node_id = f"tb-{ctx.index:02d}"
    # Голова обязана перекрывать низ второй строки — иначе это плашка над
    # головой, а не тема за спиной: центр головы в кадре ≈ 590 px.
    top = int(ctx.params.get("top", 300))
    safe = 2 * 90
    size = fit_size(widest((head, tail)).upper(), 1080 - safe,
                    int(ctx.params.get("size", 150)))

    tweens = enter_and_drift(f"#{node_id} .tb-head", ctx.start, ctx.duration,
                             name="zoom-in")
    tweens += entrance_tweens(f"#{node_id} .tb-tail", ctx.start,
                              name="zoom-in", delay=0.16)
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-title-behind" '
               f'style="top:{top}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">'
               f'<span class="tb-head" style="font-size:{size}px">'
               f'{_esc(head.upper())}</span>'
               f'<span class="tb-tail" style="font-size:{size}px">'
               f'{_esc(tail.upper())}</span></div>'],
        tweens=tweens)


# Экспонат: габариты подписаны здесь, потому что по ним же считается, куда
# отъезжает ведущий. Разъехавшись, они спрячут ему голову за карточку.
EX_PLATE_H = 1040
EX_PIC = (150, 150, 780, 620)      # left, top, width, height
EX_SHIFT_Y, EX_SHIFT_SCALE = 580, 0.78


def hero_exhibit(ctx: "TemplateCtx") -> Piece:
    """Экспонат: материал в раме и музейная подпись под ним.

    Референс: картина стоит карточкой на светлом поле, под ней три строки —
    имя крупно, уточнение мельче, кредит совсем мелко. Кредит тут не
    украшение: §1 требует источник на экране, и это лучшее для него место —
    он не спорит ни с субтитром, ни с кадром.

    Ведущий не прячется за карточку, а отъезжает вниз и уменьшается: карточка
    занимает верхние 54 % кадра, и без сдвига она закрыла бы ему голову.
    """
    name = str(ctx.params.get("title") or "").strip()
    src = str(ctx.params.get("src") or "")
    if not name or not src:
        return Piece()
    node_id = f"ex-{ctx.index:02d}"
    detail = str(ctx.params.get("detail") or "")
    credit = str(ctx.params.get("credit") or "")
    left, top, pic_w, pic_h = EX_PIC
    size = fit_size(name.upper(), pic_w, int(ctx.params.get("size", 88)))

    label = (f'<span class="ex-name" style="font-size:{size}px">{_esc(name.upper())}</span>')
    if detail:
        label += f'<span class="ex-detail">{_esc(detail)}</span>'
    if credit:
        label += f'<span class="ex-credit">{_esc(credit)}</span>'

    # Рамка рисуется отдельным прямоугольником под материалом: тень и скругление
    # на самом видео продюсер при сборке кадра не рисует (проверено кадром), а
    # на обычном блоке — рисует.
    frame = (f'<span class="ex-frame" style="left:{left - 14}px;top:{top - 14}px;'
             f'width:{pic_w + 28}px;height:{pic_h + 28}px"></span>')

    enter, leave = 0.46, 0.34
    back = max(ctx.start + enter, ctx.start + ctx.duration - leave)
    hold = max(0.3, back - ctx.start - enter)
    tweens = [
        # Карточка приезжает сверху: прозрачность клипу запрещена, поэтому вход
        # — движение, а не проявление.
        f'tl.fromTo("#{node_id}",{{y:-72}},'
        f'{{y:0,duration:{_num(enter)},ease:"expo.out"}},{_num(ctx.start)});',
        # Уходит она туда же, откуда пришла, и ровно тогда, когда ведущий
        # возвращается: иначе последние доли секунды его голова стоит за
        # карточкой.
        f'tl.to("#{node_id}",{{y:-{EX_PLATE_H + 80},duration:{_num(leave)},'
        f'ease:"power2.in"}},{_num(back)});',
        f'tl.fromTo("#{ctx.target}",{{y:0,scale:1}},'
        f'{{y:{EX_SHIFT_Y},scale:{EX_SHIFT_SCALE},duration:{_num(enter)},'
        f'ease:"expo.out"}},{_num(ctx.start)});',
        f'tl.to("#{ctx.target}",{{y:0,scale:1,duration:{_num(leave)},'
        f'ease:"power2.inOut"}},{_num(back)});',
        # Материал в раме медленно наезжает — карточка не имеет права замереть.
        # Наезд кончается там, где начинается уход: два твина на одном клипе
        # пересекаться не должны.
        f'tl.fromTo("#{node_id}-m",{{scale:1.0}},'
        f'{{scale:1.05,duration:{_num(hold)},ease:"none"}},'
        f'{_num(ctx.start + enter)});',
        f'tl.to("#{node_id}-m",{{y:-{EX_PLATE_H + 80},duration:{_num(leave)},'
        f'ease:"power2.in"}},{_num(back)});',
    ]
    tweens += entrance_tweens(f"#{node_id} .ex-name", ctx.start, name="rise", delay=0.22)
    if detail:
        tweens += entrance_tweens(f"#{node_id} .ex-detail", ctx.start, name="rise",
                                  delay=0.32)
    if credit:
        tweens += entrance_tweens(f"#{node_id} .ex-credit", ctx.start, name="dim",
                                  delay=0.44)

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-exhibit" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{frame}{label}</div>',
               f'<video id="{node_id}-m" class="clip ex-media" src="{_esc(src)}" '
               f'style="left:{left}px;top:{top}px;width:{pic_w}px;height:{pic_h}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track_alt}" muted playsinline></video>'],
        tweens=tweens)


def hero_slam(ctx: "TemplateCtx") -> Piece:
    """Удар цветом: кадр забирает плашка с фразой и уходит, вырастая.

    Референс: на реплике кадр целиком закрывается плоской заливкой, на ней в
    две строки стоит сама фраза, и через секунду плашка уезжает на зрителя,
    вырастая за края. Цвет референса — жёлтый; у нас заливка чёрная: §3.3.1
    держит акцент в 10–12 % площади кадра, а этот приём закрывает кадр
    целиком. Красным остаётся вторая строка — то самое одно слово смысла.
    """
    lines = [str(l).strip() for l in (ctx.params.get("punch") or []) if str(l).strip()]
    lines = lines[:2]
    if not lines:
        return Piece()
    node_id = f"sl-{ctx.index:02d}"
    size = fit_size(widest(lines).upper(), 1080 - 2 * 80,
                    int(ctx.params.get("size", 186)))

    rows = "".join(
        f'<span class="sl-line{" accent" if i and len(lines) > 1 else ""}">'
        f'{_esc(line.upper())}</span>' for i, line in enumerate(lines))

    # Наезд и уход тянут один и тот же scale: контракт запрещает наложение, но
    # не последовательность — второй твин начинается там, где кончился первый.
    exit_sec = 0.42
    enter = 0.30
    leave = max(ctx.start + enter, ctx.start + ctx.duration - exit_sec)
    tweens = [
        f'tl.fromTo("#{node_id}",{{scale:1.08}},'
        f'{{scale:1,duration:{_num(enter)},ease:"expo.out"}},{_num(ctx.start)});',
        f'tl.to("#{node_id}",{{scale:1.9,duration:{_num(exit_sec)},ease:"power2.in"}},'
        f'{_num(leave)});',
    ]
    for i in range(len(lines)):
        tweens += entrance_tweens(f"#{node_id} .sl-line:nth-child({i + 1})",
                                  ctx.start, name="settle", delay=0.08 + 0.10 * i)

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-slam" '
               f'style="font-size:{size}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{rows}</div>'],
        tweens=tweens)


def hero_log(ctx: "TemplateCtx") -> Piece:
    """Список фраз копится слева по ходу речи и остаётся висеть.

    Референс: реплика выкладывается не строкой, а кусками — каждый приходит
    ровно тогда, когда его произносят, и предыдущие не исчезают. К концу блока
    на экране стоит вся мысль целиком, и её можно дочитать глазами.

    Куски приходят по своим отметкам, а не через равные паузы: приём и держится
    на совпадении с речью, ровный шаг читается как бегущая строка.
    """
    entries = [e for e in (ctx.params.get("entries") or [])
               if str((e or {}).get("text") or "").strip()]
    if not entries:
        return Piece()
    node_id = f"lg-{ctx.index:02d}"
    top = int(ctx.params.get("top", 150))
    size = int(ctx.params.get("size", 56))

    rows, tweens = [], []
    for i, entry in enumerate(entries[:5]):
        rows.append(f'<span class="lg-row">{_esc(str(entry["text"]).upper())}</span>')
        at = max(0.0, min(float(entry.get("at", 0.0)), max(0.0, ctx.duration - 0.35)))
        tweens += entrance_tweens(f"#{node_id} .lg-row:nth-child({i + 1})",
                                  ctx.start, name="rise", delay=at)

    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-log" '
               f'style="top:{top}px;font-size:{size}px" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">{"".join(rows)}</div>'],
        tweens=tweens)


def hero_oversize(ctx: "TemplateCtx") -> Piece:
    """Слово крупнее кадра: края обрезаны, буквы медленно едут.

    Референс: слово набрано так, что не помещается по ширине, и кадр показывает
    его серединой. Читается всё равно — потому что оно одно и его же в этот
    момент произносят, — а обрезанные края и дают ощущение масштаба.

    Кегль считается от того, при котором слово **влезло** бы, и умножается:
    так вылет одинаков и у короткого слова, и у длинного, а не зависит от того,
    сколько в нём знаков.
    """
    word = str(ctx.params.get("word") or "").strip()
    if not word:
        return Piece()
    node_id = f"ov-{ctx.index:02d}"
    over = float(ctx.params.get("overflow", 1.3))
    size = int(fit_size(word.upper(), 1080 - 2 * 90, 460) * over)

    # Слово едет вбок и чуть приближается: остановившись, оно превращается в
    # заставку, а кадр §4.1 обязан жить.
    tweens = [
        f'tl.fromTo("#{node_id} .ov-word",{{scale:1.1,x:36}},'
        f'{{scale:1,x:0,duration:0.52,ease:"expo.out"}},{_num(ctx.start)});',
        f'tl.fromTo("#{node_id} .ov-word",{{x:0,scale:1}},'
        f'{{x:-46,scale:1.04,duration:{_num(max(0.6, ctx.duration - 0.52))},'
        f'ease:"none"}},{_num(ctx.start + 0.52)});',
    ]
    return Piece(
        nodes=[f'<div id="{node_id}" class="clip hero-oversize" '
               f'data-start="{_num(ctx.start)}" data-duration="{_num(ctx.duration)}" '
               f'data-track-index="{ctx.track}">'
               f'<span class="ov-word" style="font-size:{size}px">'
               f'{_esc(word.upper())}</span></div>'],
        tweens=tweens)


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
    "hero-script-stack": hero_script_stack,
    "hero-chat-typing": hero_chat_typing,
    "hero-title-behind": hero_title_behind,
    "hero-exhibit": hero_exhibit,
    "hero-slam": hero_slam,
    "hero-log": hero_log,
    "hero-oversize": hero_oversize,
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
        "color:var(--color-ink);will-change:transform;"
        # Под аватаром с альфой фон светлый (§7.7, .vfx), поэтому строки
        # тёмные, а ореол — светлый: белым по светлому читалась каша.
        "text-shadow:0 4px 20px rgba(247,245,243,0.9),0 2px 6px rgba(247,245,243,0.9)}"
        # Золото референсов переведено в акцент бренда: выцветший красный.
        ".hero-text-column .tc-line.accent{color:var(--color-accent)}"
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
        ".hero-phone-mock .pm-row.in{align-self:flex-start;background:#F0EEEB}"
        ".hero-phone-mock .pm-row.out{align-self:flex-end;"
        "background:var(--color-accent-soft);color:var(--color-bg-pure)}"
        # --- наборный заголовок строками (референс: подпись от руки) ---
        # Обводка через -webkit-text-stroke съедает внутренности буквы: контур
        # рисуется поверх заливки. paint-order кладёт его под неё, и буква
        # остаётся читаемой при толстом штрихе.
        f".hero-script-stack{{position:absolute;left:0;width:var(--frame-w);"
        f"display:flex;flex-direction:column;align-items:center;gap:10px;"
        f"z-index:{Z_AVATAR + 1};pointer-events:none}}"
        ".hero-script-stack .ss-line{display:block;font-family:var(--font-display);"
        # Перенос строки ломает выкладку: кегль уже подобран измерением под
        # ширину кадра, и вторая половина фразы должна остаться на своей строке.
        "white-space:nowrap;"
        "font-weight:700;font-style:italic;letter-spacing:.01em;line-height:1.02;"
        f"color:var(--color-ink);-webkit-text-stroke:{SS_STROKE}px var(--color-bg-pure);"
        "paint-order:stroke fill;text-transform:uppercase}"
        # --- переписка с печатью ---
        f".hero-chat-typing{{position:absolute;inset:0;z-index:{Z_AVATAR + 1};"
        "display:flex;align-items:center;justify-content:center;"
        "pointer-events:none}"
        f".hero-chat-typing .ct-body{{width:{int(width * 0.70)}px;"
        "background:var(--color-bg-pure);border-radius:44px;padding:38px 34px 44px;"
        "box-shadow:0 40px 90px rgba(10,10,12,.34);display:flex;"
        "flex-direction:column;gap:22px}"
        ".hero-chat-typing .ct-app{display:block;font-family:var(--font-mono);"
        "font-size:30px;letter-spacing:.16em;text-transform:uppercase;"
        "color:var(--color-muted)}"
        # Запрос стоит справа, как отправленный: так читается направление.
        ".hero-chat-typing .ct-ask{align-self:flex-end;max-width:84%;"
        "padding:24px 30px;border-radius:30px 30px 8px 30px;"
        "background:var(--color-ink);color:var(--color-bg-pure);"
        "font-family:var(--font-subtitle);font-size:40px;line-height:1.24;"
        "display:flex;flex-wrap:wrap;gap:.32em;justify-content:flex-end}"
        ".hero-chat-typing .ct-w{display:inline-block}"
        ".hero-chat-typing .ct-skeleton{align-self:flex-start;width:84%;"
        "display:flex;flex-direction:column;gap:16px;padding:26px 30px;"
        "border-radius:30px 30px 30px 8px;background:#F0EEEB}"
        ".hero-chat-typing .ct-bar{display:block;height:22px;border-radius:11px;"
        "background:rgba(17,18,20,.14)}"
        ".hero-chat-typing .ct-answer{align-self:flex-start;max-width:84%;"
        "padding:24px 30px;border-radius:30px 30px 30px 8px;background:#F0EEEB;"
        "color:var(--color-ink);font-family:var(--font-subtitle);font-size:40px;"
        "line-height:1.24}"
        # --- двухстрочный заголовок за головой ---
        # Слой уходит за аватара: голова обязана перекрывать низ второй строки,
        # иначе это обычная плашка поверх кадра, а не глубина.
        f".hero-title-behind{{position:absolute;left:0;width:var(--frame-w);"
        f"display:flex;flex-direction:column;align-items:center;gap:2px;"
        f"z-index:{Z_BEHIND_HEAD};pointer-events:none}}"
        ".hero-title-behind .tb-head,.hero-title-behind .tb-tail{display:block;"
        "white-space:nowrap;"
        "font-family:var(--font-display);font-weight:700;line-height:.98;"
        "letter-spacing:-.01em;text-transform:uppercase}"
        ".hero-title-behind .tb-head{color:var(--color-ink)}"
        ".hero-title-behind .tb-tail{color:var(--color-accent)}"
        ".hero-title-behind .tb-head,.hero-title-behind .tb-tail{text-shadow:0 4px 20px rgba(247,245,243,0.9)}"
        # --- экспонат ---
        # Карточка стоит на светлом поле поверх фона, но под субтитрами: имя
        # экспоната и слово субтитра — разные слои смысла и спорить не должны.
        f".hero-exhibit{{position:absolute;left:0;top:0;width:var(--frame-w);"
        f"height:{EX_PLATE_H}px;z-index:{Z_AVATAR + 1};"
        "background:var(--color-bg-pure);display:flex;flex-direction:column;"
        "align-items:center;justify-content:flex-end;"
        "padding:0 90px 46px;text-align:center;pointer-events:none}"
        # Паспарту: тень и скругление живут на обычном блоке, потому что на
        # самом видео продюсер их при сборке кадра не рисует.
        ".hero-exhibit .ex-frame{position:absolute;display:block;"
        "background:var(--color-bg-pure);border-radius:22px;"
        "box-shadow:0 30px 72px rgba(10,10,12,0.30)}"
        ".hero-exhibit .ex-name{display:block;font-family:var(--font-display);"
        "text-transform:uppercase;line-height:0.94;letter-spacing:-0.01em;"
        "color:var(--color-ink)}"
        ".hero-exhibit .ex-detail{display:block;margin-top:14px;"
        "font-family:var(--font-subtitle);font-weight:700;font-size:38px;"
        "color:#4A4D52}"
        ".hero-exhibit .ex-credit{display:block;margin-top:14px;"
        "font-family:var(--font-mono);font-size:24px;letter-spacing:0.10em;"
        "text-transform:uppercase;color:var(--color-muted)}"
        f".ex-media{{position:absolute;display:block;z-index:{Z_AVATAR + 2};"
        "object-fit:cover;pointer-events:none}"
        # --- удар цветом ---
        # Заливка чёрная, а не акцентная: §3.3.1 держит красный в 10–12 %
        # площади, а приём закрывает кадр целиком.
        f".hero-slam{{position:absolute;inset:0;z-index:{Z_AVATAR + 3};"
        "background:var(--color-ink);display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;gap:6px;"
        "font-family:var(--font-display);text-transform:uppercase;"
        "line-height:0.92;letter-spacing:-0.01em;pointer-events:none}"
        ".hero-slam .sl-line{display:block;color:var(--color-bg-pure)}"
        ".hero-slam .sl-line.accent{color:var(--color-accent-soft)}"
        # --- список копится слева ---
        # Колонка занимает левые две трети: правое поле кадра съедает колонка
        # лайк/коммент/шер (§3.2), и под ней куски не прочитать.
        f".hero-log{{position:absolute;left:var(--safe-x-min);"
        f"width:{int(width * 0.56)}px;z-index:{Z_AVATAR + 1};"
        "display:flex;flex-direction:column;align-items:flex-start;gap:30px;"
        "font-family:var(--font-display);text-transform:uppercase;"
        "line-height:1.02;letter-spacing:-0.005em;pointer-events:none}"
        # Тёмная строка со светлым ореолом: под аватаром с альфой фон светлый.
        ".hero-log .lg-row{display:block;color:var(--color-ink);"
        "will-change:transform;"
        "text-shadow:0 4px 20px rgba(247,245,243,0.9),"
        "0 2px 6px rgba(247,245,243,0.9)}"
        # --- слово крупнее кадра ---
        f".hero-oversize{{position:absolute;inset:0;z-index:{Z_AVATAR + 3};"
        "background:var(--color-ink);display:flex;align-items:center;"
        "justify-content:center;overflow:visible;pointer-events:none}"
        ".hero-oversize .ov-word{display:block;white-space:nowrap;"
        "font-family:var(--font-display);text-transform:uppercase;"
        "line-height:0.9;letter-spacing:-0.02em;color:var(--color-bg-pure);"
        "will-change:transform}"
        # --- выбивка ---
        ".hero-knockout{position:absolute;inset:0;"
        f"z-index:{Z_AVATAR + 1};pointer-events:none}}"
        ".hero-knockout svg{width:100%;height:100%;display:block}"
        # Чёрный в маске = дырка: сквозь буквы виден ведущий.
        ".hero-knockout .hk-text{fill:#000;font-family:var(--font-display);"
        "font-weight:700;letter-spacing:-0.01em}"
    )
