"""Каталог шаблонов в HTML/GSAP.

92 шаблона каталога — это 30 рендереров с параметрами. Проверяется то, что
движок карает молча: анимация свойства вне разрешённого списка, случайность в
рендере и бесконечные повторы.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.lib.render.hyperframes.templates import (
    DATAVIZ, DRIFT_SCALE, ENTRANCES, HERO, MOTION, TRANSITIONS, Piece, TemplateCtx,
    enter_and_drift, entrance_tweens, hero_css, render_dataviz, render_hero,
    render_motion, render_transition, transition_css,
)

# §7 контракта детерминизма: анимировать можно только это.
ALLOWED_PROPS = {
    "opacity", "x", "y", "scale", "scaleX", "scaleY", "rotation",
    "color", "backgroundColor", "borderRadius", "autoAlpha",
    "duration", "ease", "repeat", "yoyo", "stagger",
}


@pytest.fixture
def ctx():
    return TemplateCtx(index=3, start=4.5, duration=0.32, target="shot-03",
                       track=11, params={})


def _tweened_props(tweens: list[str]) -> set[str]:
    props: set[str] = set()
    for tween in tweens:
        for body in re.findall(r"\{([^{}]*)\}", tween):
            for pair in body.split(","):
                if ":" in pair:
                    props.add(pair.split(":", 1)[0].strip())
    return props


# --- контракт детерминизма ----------------------------------------------------

@pytest.mark.parametrize("name", sorted(TRANSITIONS))
def test_transition_animates_only_allowed_properties(name, ctx):
    """filter/clip-path вне списка: их анимация ломает перемотку."""
    piece = render_transition(name, ctx)
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra, f"{name} тянет запрещённые свойства: {extra}"


@pytest.mark.parametrize("name", sorted(MOTION))
def test_motion_animates_only_allowed_properties(name, ctx):
    piece = render_motion(name, ctx)
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra, f"{name} тянет запрещённые свойства: {extra}"


@pytest.mark.parametrize("name", sorted(TRANSITIONS) + sorted(MOTION))
def test_no_randomness_and_no_endless_repeat(name, ctx):
    piece = (render_transition(name, ctx) if name in TRANSITIONS
             else render_motion(name, ctx))
    body = " ".join(piece.tweens)
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")


@pytest.mark.parametrize("name", sorted(TRANSITIONS))
def test_every_tween_is_placed_at_shot_start(name, ctx):
    """Переход относится к началу шота — иначе он сыграет мимо склейки."""
    piece = render_transition(name, ctx)
    for tween in piece.tweens:
        at = float(tween.rstrip(");").rsplit(",", 1)[1])
        assert ctx.start - 1e-6 <= at <= ctx.start + ctx.duration + 1e-6, tween


# --- поведение отдельных переходов -------------------------------------------

def test_cut_draws_nothing():
    """§4.3: прямых склеек ≥70 %, и они не должны ничего стоить."""
    piece = render_transition("cut", TemplateCtx(0, 0.0, 0.3, "shot-00", 11))
    assert piece.nodes == [] and piece.tweens == []


def test_unknown_transition_degrades_to_cut(ctx):
    """Незнакомое имя не роняет рендер — ролик собирается прямой склейкой."""
    assert render_transition("небывалый", ctx) == Piece()


def test_blur_is_static_layer_not_animated_filter(ctx):
    """Размытие тянут прозрачностью слоя, а не свойством filter."""
    piece = render_transition("blur_dip", TemplateCtx(**{**ctx.__dict__,
                                                        "params": {"max_blur": 18}}))
    assert "backdrop-filter:blur(18px)" in piece.nodes[0]
    assert "blur" not in " ".join(piece.tweens)


def test_zoom_punch_direction_follows_param(ctx):
    zoom_in = render_transition("zoom_punch", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.35}}))
    zoom_out = render_transition("zoom_punch", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 0.72}}))
    assert "scale:1.35" in zoom_in.tweens[0]
    assert "scale:0.72" in zoom_out.tweens[0]


def test_paper_slide_respects_axis_and_direction(ctx):
    up = render_transition("paper_slide", TemplateCtx(
        **{**ctx.__dict__, "params": {"axis": "y", "direction": -1}}))
    assert "y:-1920" in up.tweens[0]
    right = render_transition("paper_slide", TemplateCtx(
        **{**ctx.__dict__, "params": {"direction": 1}}))
    assert "x:1080" in right.tweens[0]


def test_glitch_offsets_are_deterministic(ctx):
    """Дважды собранный кадр обязан совпасть с точностью до пикселя."""
    params = {"bars": 7}
    first = render_transition("glitch", TemplateCtx(**{**ctx.__dict__, "params": params}))
    second = render_transition("glitch", TemplateCtx(**{**ctx.__dict__, "params": params}))
    assert first.tweens == second.tweens
    assert len(first.tweens) == 7


def test_glitch_bars_differ_between_shots(ctx):
    """Одинаковый сбой на каждой склейке читался бы как заставка."""
    a = render_transition("glitch", TemplateCtx(**{**ctx.__dict__, "index": 1,
                                                  "params": {"bars": 5}}))
    b = render_transition("glitch", TemplateCtx(**{**ctx.__dict__, "index": 2,
                                                  "params": {"bars": 5}}))
    assert a.tweens != b.tweens


# --- покрытие каталога --------------------------------------------------------

def test_every_renderer_of_the_catalog_is_implemented():
    """Каталог §15 и модуль не должны расходиться."""
    manifest = json.loads(Path("templates/manifest.json").read_text(encoding="utf-8"))
    renderers = {t["renderer"] for t in manifest["templates"]}
    # Эти собирает генератор композиции напрямую — по одному узлу на шот или
    # оверлей, без параметров каталога.
    built_in = {"fullscreen_text", "source_card", "plaque", "footage", "avatar",
                "cta_button"}
    implemented = set(TRANSITIONS) | set(MOTION) | set(HERO) | built_in | {"dataviz"}
    missing = renderers - implemented
    assert not missing, f"рендереры каталога без реализации: {sorted(missing)}"


def test_css_covers_every_layer_the_transitions_use():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    for cls in (".tr-flash", ".tr-blur", ".tr-mask-circle", ".tr-mask-diagonal",
                ".tr-sweep", ".tr-glitch"):
        assert cls in css, cls


# --- диаграммы ----------------------------------------------------------------

@pytest.mark.parametrize("template_id,params", [
    ("data-viz/bar-race-mini", {"values": [12, 30, 7, 25], "labels": list("абвг")}),
    ("data-viz/compare-bars", {"values": [66, 28]}),
    ("data-viz/counter-roll", {"value": 27000, "suffix": " ч"}),
    ("data-viz/donut-fill", {"value": 73}),
    ("data-viz/timeline-dots", {"labels": ["1916", "1971", "2019"]}),
])
def test_dataviz_animates_only_allowed_properties(template_id, params):
    ctx = TemplateCtx(index=4, start=10.0, duration=3.0, target="ovl-04",
                      track=6, params=params)
    piece = render_dataviz(template_id, ctx)
    assert piece.nodes, f"{template_id} не собрал разметку"
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra, f"{template_id} тянет запрещённые свойства: {extra}"


def test_dataviz_without_data_draws_nothing():
    """Пустая диаграмма врёт сильнее, чем её отсутствие."""
    ctx = TemplateCtx(index=4, start=10.0, duration=3.0, target="ovl-04",
                      track=6, params={})
    assert render_dataviz("data-viz/bar-race-mini", ctx) == Piece()
    assert render_dataviz("data-viz/timeline-dots", ctx) == Piece()


def test_bars_scale_relative_to_the_largest_value():
    """Столбцы соотносятся с максимумом, иначе диаграмма искажает данные."""
    ctx = TemplateCtx(index=0, start=0.0, duration=3.0, target="ovl-00",
                      track=6, params={"values": [50, 100]})
    node = render_dataviz("data-viz/compare-bars", ctx).nodes[0]
    widths = [float(w) for w in re.findall(r"width:([\d.]+)%", node)]
    assert widths == pytest.approx([50.0, 100.0])


def test_counter_steps_are_frames_not_a_timer():
    """Значения выписаны заранее: рендер сэмплирует кадры не по порядку."""
    ctx = TemplateCtx(index=0, start=0.0, duration=2.0, target="ovl-00",
                      track=6, params={"value": 100, "steps": 4})
    piece = render_dataviz("data-viz/counter-roll", ctx)
    assert "setTimeout" not in " ".join(piece.tweens)
    assert piece.nodes[0].count("<span>") == 5      # 0..100 включительно
    assert ">100<" in piece.nodes[0]


def test_split_moves_both_halves_towards_the_seam():
    ctx = TemplateCtx(index=2, start=1.0, duration=1.0, target="shot-02",
                      track=1, params={"enter_ms": 260})
    piece = render_motion("split", ctx)
    body = " ".join(piece.tweens)
    assert "y:-540" in body and "y:540" in body


@pytest.mark.parametrize("name", sorted(TRANSITIONS))
def test_no_tween_targets_a_clip_element(name, ctx):
    """Видимостью клипа управляет фреймворк.

    Твин прямо на клипе оставляет застрявшее состояние при перемотке — lint
    движка ловит это как gsap_exit_missing_hard_kill. Анимируем вложенный
    элемент, а не сам клип.
    """
    piece = render_transition(name, ctx)
    clip_ids = re.findall(r'<div id="([^"]+)" class="clip', " ".join(piece.nodes))
    for tween in piece.tweens:
        target = re.search(r'"(#[^"]+)"', tween).group(1)
        for clip_id in clip_ids:
            assert target != f"#{clip_id}", f"{name} тянет сам клип: {tween}"


# --- приёмы вокруг ведущего ---------------------------------------------------
#
# Референсы заказчика: ведущий за столом, а кадр вокруг него живёт. Проверяется
# то, что уже ломалось в реальном рендере, а не то, что легко проверить.

HERO_PARAMS = {
    "hero-burst": {},
    "hero-headline": {"word": "ГОРИЗОНТ", "kicker": "ОДНА ТЕОРИЯ"},
    "hero-plate": {"src": "assets/m000_shot.mp4"},
    "hero-split": {"word": "ВНИМАНИЕ"},
    "hero-knockout": {"word": "ЕДИНСТВЕННАЯ"},
    "hero-text-column": {"lines": ["И ГОРИЗОНТ", "КОТОРЫЙ РАНЬШЕ",
                                   "КАЗАЛСЯ СТЕНОЙ"],
                         "accent_lines": [0]},
    "hero-bubble-card": {"lines": ["ни один прибор", "не увидит границу"]},
    "hero-brand-pill": {"label": "Google", "icon": "assets/icons/google.png"},
    "hero-card-stack": {"title": "СВЕТИЛ ВНУТРЬ", "src": "assets/m000_shot.mp4"},
    "hero-phone-mock": {"lines": ["что там внутри", "никто не знает"],
                        "app": "ChatGPT"},
    "hero-script-stack": {"lines": ["если ты", "зайдёшь", "за горизонт"]},
    "hero-chat-typing": {"ask": "что будет за горизонтом событий",
                         "answer": "тело растянет в нить",
                         "app": "ChatGPT"},
    "hero-title-behind": {"head": "Наполеон", "tail": "проиграл машине"},
}


def _clip_ids(nodes: list[str]) -> list[str]:
    """Идентификаторы клипов разметки — клипом может быть и <video>, и <div>."""
    return re.findall(r'<\w+ id="([^"]+)"[^>]*class="clip', " ".join(nodes))


def _css_rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    return match.group(1) if match else ""


def _css_rules_under(css: str, selector: str) -> list[tuple[str, str]]:
    """Правила для потомков селектора: ``.hero-burst span``, ``.hero-plate .hp-in``."""
    pattern = re.escape(selector) + r"(?:\s|>)+([^{,]+)\{([^}]*)\}"
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(pattern, css)]


def _hero_ctx(name, **over):
    params = {**HERO_PARAMS[name], **over.pop("params", {})}
    base = dict(index=3, start=4.5, duration=2.0, target="avatar-01",
                track=13, params=params)
    base.update(over)
    return TemplateCtx(**base)


def test_every_hero_gets_its_content_from_the_pipeline():
    """Приём, выбранный конвейером, обязан получить и содержимое.

    Пропуск в отображении не падает и не пишет в лог: рендерер возвращает
    пустой ``Piece``, и приёма в кадре просто нет. Проверяется именно связка
    «что конвейер кладёт в params» ↔ «что рендерер оттуда читает».
    """
    from src.p11_assemble.assemble import _HERO_NEEDS, _hero_content, hero_params

    block = {"id": "b1", "emphasis_word": "переживёшь",
             "text": "Падение в чёрную дыру ты переживёшь. Это и есть худшая часть."}
    content = _hero_content(block, {"role": "hook"}, None, (540, 700),
                            title="Можно ли выжить внутри чёрной дыры")
    content["brand"] = {"label": "Google", "icon": "assets/icons/google.png"}

    for name in sorted(HERO):
        params = hero_params(name, {}, content, {"role": "hook"})
        if "plate" in _HERO_NEEDS.get(name, ()):
            # Материал приходит не из текста блока, а из соседнего кадра.
            params["src"] = "assets/m000_shot.mp4"
        ctx = TemplateCtx(index=3, start=4.5, duration=3.0, target="avatar-01",
                          track=13, params=params)
        assert render_hero(name, ctx).nodes, f"{name} остался без содержимого"


@pytest.mark.parametrize("name", sorted(HERO))
def test_hero_animates_only_allowed_properties(name):
    piece = render_hero(name, _hero_ctx(name))
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra, f"{name} тянет запрещённые свойства: {extra}"


@pytest.mark.parametrize("name", sorted(HERO))
def test_hero_is_deterministic(name):
    """Рендер сэмплирует кадры не по порядку — случайности быть не может."""
    first = render_hero(name, _hero_ctx(name))
    second = render_hero(name, _hero_ctx(name))
    assert first == second
    assert "Math.random" not in " ".join(first.tweens + first.nodes)


@pytest.mark.parametrize("name", sorted(HERO))
def test_hero_clip_has_a_paintable_box(name):
    """Клип нулевой площади продюсер выбрасывает вместе с содержимым.

    Так пропали лучи hero-burst: в браузере веер рисовался, а из рендера
    исчезал целиком — проверено кадром, тот же веер в коробке 1080×600
    отрисовался. Клип, у которого все дети выведены из потока, обязан задать
    габариты сам: содержимое их ему не даст.
    """
    from src.lib.config import load_config

    piece = render_hero(name, _hero_ctx(name))
    css = hero_css(load_config().brandbook)
    node = piece.nodes[0]
    # У клипа может быть и второй класс-модификатор (``clip hero-brand-pill
    # left``) — берём первый после clip, именно он несёт геометрию.
    css_class = re.search(r'class="clip ([\w-]+)', node).group(1)
    inline = re.search(r'style="([^"]*)"', node)
    box = (inline.group(1) if inline else "") + ";" + _css_rule(css, f".{css_class}")

    # Габариты обязан задать сам клип, если высоту ему дать некому: детей нет
    # вовсе (медиа-клип) либо все они выведены из потока.
    rules = _css_rules_under(css, f".{css_class}")
    if rules and not all("position:absolute" in body for _, body in rules):
        return      # высоту даёт содержимое — коробку задавать нечем и незачем

    for side, spans in (("width", ("width:", "inset:")),
                        ("height", ("height:", "inset:"))):
        assert any(m in box for m in spans), f"{name}: не задан {side}: {box}"
        assert f"{side}:0;" not in box + ";", f"{name}: нулевой {side}: {box}"


@pytest.mark.parametrize("name", sorted(HERO))
def test_hero_never_tweens_opacity_of_its_own_clip(name):
    """Видимостью клипа распоряжается движок — прозрачность на нём застревает.

    Трансформы на клипе, наоборот, разрешены: на них держится Ken Burns, и
    линт пропускает их без замечаний — проверено на реальной композиции. Раньше
    здесь стоял запрет на любой твин по клипу, и из-за него панель за спиной
    появлялась срезом вместо приближения.

    Селектор потомка (``#hs-03 .hs-word``) разрешён всегда: он целится внутрь
    клипа, а не в него самого.
    """
    piece = render_hero(name, _hero_ctx(name))
    clip_ids = _clip_ids(piece.nodes)
    assert clip_ids, f"{name} не собрал ни одного клипа"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1).strip()
        if selector.lstrip("#") not in clip_ids:
            continue
        for forbidden in ("opacity", "autoAlpha", "visibility"):
            assert forbidden not in tween, \
                f"{name} тянет {forbidden} на самом клипе: {tween}"


@pytest.mark.parametrize("name", ["hero-headline", "hero-split", "hero-knockout"])
def test_hero_without_text_draws_nothing(name):
    """Приём без слова — пустая плашка поверх ведущего, а не приём."""
    assert render_hero(name, _hero_ctx(name, params={"word": ""})) == Piece()


def test_hero_plate_without_media_draws_nothing():
    assert render_hero("hero-plate", _hero_ctx("hero-plate", params={"src": ""})) == Piece()


def test_hero_burst_box_covers_the_longest_ray():
    """Коробка обязана накрыть веер: на неё смотрит продюсер, а не на лучи."""
    piece = render_hero("hero-burst", _hero_ctx("hero-burst"))
    node = piece.nodes[0]
    reach = max(int(n) for n in re.findall(r"--len:(\d+)px", node))
    height = int(re.search(r"height:(\d+)px", node).group(1))
    assert height >= reach


def test_hero_split_returns_the_subject_to_the_centre():
    """Клип аватара живёт дольше приёма: несброшенный сдвиг утечёт в кадры."""
    piece = render_hero("hero-split", _hero_ctx("hero-split"))
    back = [t for t in piece.tweens if '"#avatar-01"' in t and "tl.to(" in t]
    assert back, "ведущий остаётся сдвинутым до конца сегмента"
    assert "x:0" in back[0] and "scale:1," in back[0]


def test_hero_knockout_shrinks_the_font_to_fit_the_frame():
    """«ЕДИНСТВЕННАЯ» кеглем 300 не влезает — проверено кадром."""
    piece = render_hero("hero-knockout", _hero_ctx("hero-knockout"))
    size = int(re.search(r'font-size="(\d+)"', piece.nodes[0]).group(1))
    assert size < 300
    assert size * 0.52 * len("ЕДИНСТВЕННАЯ") <= 1080 - 2 * 60


def test_hero_plate_media_is_the_clip_itself():
    """Вложенное в тайминг видео движок не проигрывает — кадр застывает.

    Ровно это и поймал lint: ``video_nested_in_timed_element``. Панель за
    спиной обязана быть самим клипом, а не ``<video>`` внутри ``<div>``.
    """
    piece = render_hero("hero-plate", _hero_ctx("hero-plate"))
    node = piece.nodes[0]
    assert node.startswith("<video "), node[:60]
    assert 'class="clip hero-plate"' in node
    assert node.count("<video") == 1
    assert "data-start=" in node and "data-duration=" in node


def test_hero_plate_enters_by_approaching():
    """«Резко помещают» — не про этот монтаж: панель обязана приближаться.

    Другого узла, кроме самого медиа-клипа, у панели нет, поэтому вход идёт
    трансформой без прозрачности.
    """
    piece = render_hero("hero-plate", _hero_ctx("hero-plate"))
    assert piece.tweens, "панель появляется срезом"
    enter = piece.tweens[0]
    assert "opacity" not in enter, enter
    assert "{scale:0.86}" in enter, f"панель обязана расти, а не отъезжать: {enter}"


def test_hero_headline_without_a_kicker_tweens_only_what_it_drew():
    """Твин по несобранной разметке молчит — и прячет опечатку в селекторе."""
    piece = render_hero("hero-headline", _hero_ctx("hero-headline",
                                                   params={"kicker": ""}))
    assert "hh-kicker" not in " ".join(piece.nodes + piece.tweens)
    assert any("hh-word" in t for t in piece.tweens)


def test_hero_knockout_does_not_flood_the_frame_with_accent():
    """§3.3.1 держит акцент в 10–12 % площади, а приём закрывает кадр целиком."""
    node = render_hero("hero-knockout", _hero_ctx("hero-knockout")).nodes[0]
    assert "var(--color-ink)" in node
    assert "accent" not in node


def test_hero_knockout_fill_is_a_brandbook_token():
    node = render_hero("hero-knockout",
                       _hero_ctx("hero-knockout",
                                 params={"fill": "accent_deep"})).nodes[0]
    assert "var(--color-accent-deep)" in node


# --- словарь появления --------------------------------------------------------

def test_every_hero_device_enters_by_moving():
    """Референс: «должно выглядеть как увеличение либо приближение».

    Приём, который просто проявляется прозрачностью, этому не отвечает: у входа
    обязана быть трансформа.
    """
    for name in sorted(HERO):
        piece = render_hero(name, _hero_ctx(name))
        assert piece.tweens, f"{name} появляется срезом"
        moving = [t for t in piece.tweens
                  if any(prop in t for prop in ("scale:", "y:", "x:", "scaleY:"))]
        assert moving, f"{name} только проявляется, но не движется"


@pytest.mark.parametrize("name", sorted(ENTRANCES))
def test_entrance_decelerates(name):
    """Кривая затухающая: равномерная выглядит машинной, ускоряющаяся — срывом."""
    assert str(ENTRANCES[name]["ease"]).split("(")[0].endswith(".out")


@pytest.mark.parametrize("name", sorted(ENTRANCES))
def test_entrance_scale_stays_subtle(name):
    """Крупный наезд читается как зум видеоряда и спорит с Ken Burns."""
    assert 0.8 <= float(ENTRANCES[name]["scale"]) <= 1.2


def test_entrance_on_a_clip_carries_no_opacity():
    tween = entrance_tweens("#hp-03", 1.0, fade=False)[0]
    assert "opacity" not in tween
    assert "scale:" in tween


def test_entrance_without_a_fade_grows_instead_of_shrinking():
    """Проверено кадром: приход из 1.14 без проявления читается как отъезд.

    Первый кадр застаёт элемент крупным и непрозрачным — будто он тут и был.
    Из меньшего масштаба тот же путь читается как появление.
    """
    import re
    for name in sorted(ENTRANCES):
        tween = entrance_tweens("#clip", 0.0, name=name, fade=False)[0]
        scale_from = float(re.search(r"\{scale:([\d.]+)", tween).group(1))
        assert scale_from <= 1.0, f"{name}: вход без проявления уменьшается"


def test_entrance_with_a_fade_keeps_the_dictionary_value():
    import re
    tween = entrance_tweens("#inner", 0.0, name="zoom-in", fade=True)[0]
    assert float(re.search(r"\{scale:([\d.]+)", tween).group(1)) == 1.14


def test_drift_never_overlaps_the_entrance():
    """Вход и дрейф тянут ``scale`` одного элемента — наложение движок карает."""
    tweens = enter_and_drift("#hp-03", 5.0, 4.0, name="zoom-in", fade=False)
    assert len(tweens) == 2
    starts = [float(t.rstrip(");").rsplit(",", 1)[1]) for t in tweens]
    enter_end = starts[0] + float(ENTRANCES["zoom-in"]["duration"])
    assert starts[1] >= enter_end - 1e-6


def test_short_hold_gets_no_drift():
    """На секунде дрейф незаметен, а окно на ``scale`` занимает."""
    assert len(enter_and_drift("#x", 0.0, 0.6, fade=False)) == 1


def test_drift_is_imperceptible():
    """Дрейф работает боковым зрением: заметный превращается в отдельный жест."""
    assert 1.0 < DRIFT_SCALE <= 1.06


@pytest.mark.parametrize("name", sorted(HERO))
def test_hero_clips_of_one_device_never_share_a_track(name):
    """Пересечение клипов на общем треке движок считает ошибкой.

    Карточка с картинкой собирает два клипа в одном окне, и на общем треке
    линт валит сборку с ``overlapping_clips_same_track`` — поймано на реальной
    композиции, не в теории.
    """
    piece = render_hero(name, _hero_ctx(name))
    tracks = [re.search(r'data-track-index="(\d+)"', node).group(1)
              for node in piece.nodes if "data-track-index" in node]
    assert len(tracks) == len(set(tracks)), f"{name}: клипы делят трек {tracks}"


def test_knockout_sits_on_the_face_not_the_torso():
    """Буквы выбивки — дырки: на уровне торса сквозь них видна тёмная одежда,
    неотличимая от тёмной заливки, и слово пропадает серединой."""
    import re

    high = render_hero("hero-knockout",
                       _hero_ctx("hero-knockout", params={"face_cy": 550})).nodes[0]
    low = render_hero("hero-knockout",
                      _hero_ctx("hero-knockout", params={"face_cy": 1200})).nodes[0]
    y_high = int(re.search(r'y="(\d+)"', high).group(1))
    y_low = int(re.search(r'y="(\d+)"', low).group(1))
    assert y_high < y_low, "выбивка не следует за лицом"
    # Без данных о лице остаётся середина кадра.
    mid = render_hero("hero-knockout", _hero_ctx("hero-knockout")).nodes[0]
    assert 700 < int(re.search(r'y="(\d+)"', mid).group(1)) < 1200


def test_headline_size_is_measured_too():
    """Заголовок идёт строкой через кадр — при фиксированном кегле обрежется."""
    import re

    long_word = render_hero("hero-headline",
                            _hero_ctx("hero-headline",
                                      params={"word": "НЕПРЕДСКАЗУЕМОСТЬ",
                                              "size": 232})).nodes[0]
    size = int(re.search(r"font-size:(\d+)px", long_word).group(1))
    from src.lib.render.hyperframes.templates import text_width
    assert text_width("НЕПРЕДСКАЗУЕМОСТЬ", size) <= 980 + 1e-6


def test_bubble_leaves_no_residual_scale_on_the_shared_avatar():
    """Клип аватара общий и может покрывать несколько слотов.

    Дрейф оставил бы на нём остаточный масштаб после конца приёма — ту же
    утечку, ради которой у сплита стоит обратный твин.
    """
    piece = render_hero("hero-bubble-card",
                        _hero_ctx("hero-bubble-card", duration=6.0))
    avatar = [t for t in piece.tweens if '"#avatar-01"' in t]
    assert len(avatar) == 1, f"на аватаре больше одного твина: {avatar}"
    to_state = re.search(r"\},\{([^}]*)\}", avatar[0]).group(1)
    assert "scale:1.0," in to_state + ",", f"приём оставляет масштаб: {to_state}"
