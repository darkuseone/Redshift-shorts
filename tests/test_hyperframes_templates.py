"""Каталог шаблонов в HTML/GSAP.

120 шаблонов каталога — это рендереры с параметрами. Проверяется то, что
движок карает молча: анимация свойства вне разрешённого списка, случайность в
рендере и бесконечные повторы.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.lib.render.hyperframes.templates import (
    DATAVIZ, DRIFT_SCALE, ENTRANCES, FULLSCREEN, HERO, MOTION, OVERLAYS,
    TRANSITIONS, Piece, TemplateCtx,
    enter_and_drift, entrance_tweens, hero_css, overlay_css, render_dataviz,
    render_fullscreen, render_hero, render_motion, render_overlay,
    render_transition, transition_css,
    _fs_size, _lt_au_times, _lt_cb_times, _lt_dc_times,     _c3d_times, _c3d_highlight, _cd_times, _cd_line_diff, _cd_parse_pair,
    _cpa_times, _cpa_rng, _CPA_CAP, _cs_times, _ct_times, _ts_times,
    _sr_frame_table,
)

# §7 контракта детерминизма: анимировать можно только это.
ALLOWED_PROPS = {
    "opacity", "x", "y", "scale", "scaleX", "scaleY", "rotation",
    "color", "backgroundColor", "borderRadius", "autoAlpha",
    "duration", "ease", "repeat", "yoyo", "stagger", "immediateRender",
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
    implemented = (set(TRANSITIONS) | set(MOTION) | set(HERO) | set(OVERLAYS)
                   | set(FULLSCREEN) | built_in | {"dataviz"})
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
    ("data-viz/stat-countup-card", {"value": 105, "suffix": " кубит", "label": "105"}),
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
    "hero-type-slab": {"lines": ["ГОРИЗОНТ", "СОБЫТИЙ"], "accent_lines": [0]},
    "hero-plate-pop": {"src": "assets/m000_shot.mp4"},
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


def _fs_ctx(**params):
    duration = float(params.pop("duration", 1.4))
    return TemplateCtx(index=1, start=3.0, duration=duration, target="shot-01",
                       track=1, params={"available_px": 900, "size_px": 420,
                                        **params})


def test_kinetic_stack_staggers_words():
    piece = render_fullscreen(_fs_ctx(content="раз два три", accent_word="два",
                                     stagger_ms=55, kinetic=True))
    assert "ks-word" in piece.nodes[0]
    assert piece.nodes[0].count("ks-word") == 3
    assert " accent" in piece.nodes[0]
    assert len(piece.tweens) >= 3
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra


def test_blur_out_up_staggers_words_from_a_static_ghost():
    """Каталог тянет filter; здесь призрак со статическим blur и смена opacity."""
    piece = render_fullscreen(_fs_ctx(
        content="сигнал с орбиты", accent_word="орбиты",
        renderer="blur_out_up", blur_out=True, stagger_ms=55,
        direction="up", duration=1.8))
    node = piece.nodes[0]
    assert "bou-word" in node
    assert node.count("bou-word") == 3
    assert node.count("bou-ghost") == 3
    assert "filter:blur(5px)" in node
    assert " accent" in node
    body = " ".join(piece.tweens)
    assert "filter" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#{_fs_ctx().target}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    w0 = [float(t.rstrip(");").rsplit(",", 1)[1])
          for t in piece.tweens if "fromTo" in t and '-w0"' in t][:1]
    w1 = [float(t.rstrip(");").rsplit(",", 1)[1])
          for t in piece.tweens if "fromTo" in t and '-w1"' in t][:1]
    assert w0 and w1 and w1[0] - w0[0] == pytest.approx(0.055)
    assert re.search(r"scale:0.92,y:[0-9.]+", body)
    assert re.search(r"y:-[0-9.]+", body)
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))


def test_blur_out_up_direction_flips_the_axis():
    left = render_fullscreen(_fs_ctx(
        content="код", renderer="blur_out_up", direction="left", duration=1.8))
    body = " ".join(left.tweens)
    assert re.search(r"scale:0.92,x:-", body)
    assert re.search(r"scale:0.96,x:[0-9.]+", body)
    assert "{y:" not in body and ",y:" not in body
    std = render_fullscreen(_fs_ctx(
        content="код", renderer="blur_out_up", duration=1.8))
    far = render_fullscreen(_fs_ctx(
        content="код", renderer="blur_out_up", direction="up",
        distance="far", blur="heavy", duration=1.8))
    assert "filter:blur(11px)" in far.nodes[0]

    def enter_y(piece):
        return float(re.search(r"scale:0.92,y:([0-9.]+)", " ".join(piece.tweens)).group(1))

    assert enter_y(far) == pytest.approx(enter_y(std) * 1.85)


def test_bottom_up_letters_staggers_glyphs():
    """Каталог: буква из 0.85em ниже, back.out, стаггер 25 мс. Не CSS-transform."""
    piece = render_fullscreen(_fs_ctx(
        content="код живёт", accent_word="код",
        renderer="bottom_up_letters", bottom_up=True, unit="letter",
        direction="up", travel="standard", stagger_ms=25, duration=1.8))
    node = piece.nodes[0]
    assert node.count("bul-ch") == 8
    assert node.count("bul-word") == 2
    assert " accent" in node
    body = " ".join(piece.tweens)
    assert "back.out(1.7)" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#{_fs_ctx().target}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    t0 = [float(t.rstrip(");").rsplit(",", 1)[1])
          for t in piece.tweens if '-c0"' in t][0]
    t1 = [float(t.rstrip(");").rsplit(",", 1)[1])
          for t in piece.tweens if '-c1"' in t][0]
    assert t1 - t0 == pytest.approx(0.025)
    assert "opacity:0" in body and "y:0" in body
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))


def test_bottom_up_letters_direction_and_unit():
    down = render_fullscreen(_fs_ctx(
        content="код", renderer="bottom_up_letters", direction="down",
        duration=1.8))
    assert re.search(r"opacity:0,y:-", " ".join(down.tweens))
    words = render_fullscreen(_fs_ctx(
        content="код живёт", renderer="bottom_up_letters", unit="word",
        duration=1.8))
    assert words.nodes[0].count("bul-ch") == 0
    assert words.nodes[0].count("bul-unit") == 2
    std = render_fullscreen(_fs_ctx(
        content="код", renderer="bottom_up_letters", travel="standard",
        duration=1.8))
    far = render_fullscreen(_fs_ctx(
        content="код", renderer="bottom_up_letters", travel="far",
        duration=1.8))

    def enter_y(piece):
        return abs(float(re.search(r"opacity:0,y:(-?[0-9.]+)",
                                   " ".join(piece.tweens)).group(1)))

    assert enter_y(far) == pytest.approx(enter_y(std) * 1.5 / 0.85)


def test_kinetic_type_swap_rolls_the_slot_without_reflow():
    """Каталог: yPercent/cqw. Здесь px, слот = самое широкое слово, не .clip."""
    piece = render_fullscreen(_fs_ctx(
        content="ПИШИ|КОД|HTML|ОРБИТЫ", renderer="kinetic_type_swap",
        kinetic_swap=True, exit="none", duration=4.0))
    node = piece.nodes[0]
    assert "kts-slot" in node
    assert "kts-prefix" in node and "ПИШИ" in node
    assert node.count("kts-word") == 3
    assert "КОД" in node and "HTML" in node and "ОРБИТЫ" in node
    body = " ".join(piece.tweens)
    assert "yPercent" not in body
    assert "cqw" not in node and "cqh" not in node
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#{_fs_ctx().target}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    assert "back.out(1.7)" in body
    assert "power4.in" in body
    assert "immediateRender:false" in body
    assert re.search(r'style="width:\d+px;height:\d+px"', node)
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    from src.lib.render.hyperframes.templates import _kts_sentence
    prefix, options, suffix = _kts_sentence({"content": "ПИШИ|КОД|HTML|ОРБИТЫ"})
    assert (prefix, options, suffix) == ("ПИШИ", ["КОД", "HTML", "ОРБИТЫ"], "")


def test_kinetic_type_swap_exit_and_cues():
    fade = render_fullscreen(_fs_ctx(
        content="КОД,HTML", renderer="kinetic_type_swap",
        kinetic_swap=True, exit="fade", duration=4.0))
    assert 'fromTo("#shot-01-stage",{opacity:1}' in " ".join(fade.tweens)
    up = render_fullscreen(_fs_ctx(
        content="КОД,HTML", renderer="kinetic_type_swap",
        kinetic_swap=True, exit="up", duration=4.0))
    assert re.search(r"opacity:0,y:-", " ".join(up.tweens))
    cued = render_fullscreen(_fs_ctx(
        content="А|Б|В", renderer="kinetic_type_swap",
        kinetic_swap=True, cues="0.4,1.2", duration=4.0))
    starts = [float(t.rstrip(");").rsplit(",", 1)[1])
              for t in cued.tweens if "fromTo" in t and '-w0"' in t]
    assert starts and any(abs(at - 3.4) < 1e-6 or abs(at - 0.4) < 1e-6
                          for at in starts)
    comma = render_fullscreen(_fs_ctx(
        prefix="ПИШИ", options="КОД,HTML", suffix="СЕЙЧАС",
        renderer="kinetic_type_swap", duration=4.0))
    assert "ПИШИ" in comma.nodes[0] and "СЕЙЧАС" in comma.nodes[0]


def test_line_by_line_slide_staggers_from_the_left():
    """Каталог твинит CSS-var и filter; здесь px + призрак со статическим blur."""
    piece = render_fullscreen(_fs_ctx(
        content="ПИШИ КОД|СОБИРАЙ ОРБИТЫ|ШЛИ НА ПРОД",
        accent_word="ОРБИТЫ", renderer="line_by_line_slide",
        line_slide=True, direction="left", duration=1.8))
    node = piece.nodes[0]
    assert node.count("lbls-line") == 3
    assert node.count("lbls-ghost") == 3
    assert "filter:blur(" in node
    assert "accent" in node
    body = " ".join(piece.tweens)
    assert "filter" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#{_fs_ctx().target}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    t0 = [float(t.rstrip(");").rsplit(",", 1)[1])
          for t in piece.tweens if "fromTo" in t and '-l0"' in t][:1]
    t1 = [float(t.rstrip(");").rsplit(",", 1)[1])
          for t in piece.tweens if "fromTo" in t and '-l1"' in t][:1]
    assert t0 and t1 and t1[0] - t0[0] == pytest.approx(0.08)
    assert re.search(r"x:-[0-9.]+,y:[0-9.]+", body)
    assert "power3.out" in body
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    from src.lib.render.hyperframes.templates import _lbls_lines
    assert _lbls_lines("А|Б|В", {}) == ["А", "Б", "В"]


def test_line_by_line_slide_direction_and_tone():
    right = render_fullscreen(_fs_ctx(
        content="КОД|HTML", renderer="line_by_line_slide",
        line_slide=True, direction="right", duration=1.8))
    body = " ".join(right.tweens)
    assert re.search(r"x:[0-9.]+,y:[0-9.]+", body)
    paper = render_fullscreen(_fs_ctx(
        content="КОД|HTML", renderer="line_by_line_slide",
        line_slide=True, tone="paper", duration=1.8))
    assert "invert" in paper.nodes[0]
    packed = render_fullscreen(_fs_ctx(
        content="один два три четыре пять шесть",
        renderer="line_by_line_slide", line_slide=True, duration=1.8))
    assert packed.nodes[0].count("lbls-line") == 3


def test_logo_brand_close_cascades_letters_and_keeps_the_period_accent():
    """Каталог: cqw/em и measure. Здесь px, точка accent, HOLD без дрейфа."""
    piece = render_fullscreen(_fs_ctx(
        wordmark="РЕДШИФТ", tagline="Пиши код. Шли на орбиту.",
        url="redshift.shorts", renderer="logo_brand_close",
        logo_close=True, exit="none", duration=4.0))
    node = piece.nodes[0]
    assert "lbc-mark" in node
    assert "lbc-dot" in node
    assert "lbc-tag" in node and "Пиши код" in node
    assert "lbc-url" in node and "redshift.shorts" in node
    assert node.count("lbc-ch") == len("РЕДШИФТ")
    assert "lbc-dot" in node
    body = " ".join(piece.tweens)
    assert "cqw" not in node and "cqh" not in node
    assert "yPercent" not in body
    assert "letterSpacing" not in body
    assert "0.62em" not in body and "0.08em" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#{_fs_ctx().target}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    assert "back.out(1.8)" in body
    assert "expo.out" in body
    assert "scaleX:1.06" in body
    assert "DRIFT" not in body and "1.035" not in body
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    from src.lib.render.hyperframes.templates import _lbc_copy, _lbc_body_and_dot
    assert _lbc_copy({})[0] == "РЕДШИФТ"
    assert _lbc_body_and_dot("РЕДШИФТ.") == ("РЕДШИФТ", ".")
    doubled = render_fullscreen(_fs_ctx(
        wordmark="РЕДШИФТ.", renderer="logo_brand_close", duration=4.0))
    assert doubled.nodes[0].count("lbc-dot") == 1
    assert doubled.nodes[0].count("lbc-ch") == len("РЕДШИФТ")


def test_logo_brand_close_exit_and_hidden_lines():
    fade = render_fullscreen(_fs_ctx(
        wordmark="КОД", renderer="logo_brand_close",
        logo_close=True, exit="fade", duration=4.0))
    assert 'fromTo("#shot-01-lock",{opacity:1}' in " ".join(fade.tweens)
    up = render_fullscreen(_fs_ctx(
        wordmark="КОД", renderer="logo_brand_close",
        logo_close=True, exit="up", duration=4.0))
    assert re.search(r"opacity:0,y:-", " ".join(up.tweens))
    hidden = render_fullscreen(_fs_ctx(
        wordmark="КОД", tagline="", url="",
        renderer="logo_brand_close", duration=4.0))
    assert "lbc-tag" not in hidden.nodes[0]
    assert "lbc-url" not in hidden.nodes[0]
    short = render_fullscreen(_fs_ctx(
        wordmark="КОД", renderer="logo_brand_close", duration=2.0))
    starts = [float(t.rstrip(");").rsplit(",", 1)[1])
              for t in short.tweens if "-dot\"" in t and "fromTo" in t]
    assert starts and starts[0] < 3.0 + 0.95 - 0.01
    piped = render_fullscreen(_fs_ctx(
        content="ОРБИТА|Пиши HTML.|orbit.lab",
        renderer="logo_brand_close", duration=4.0))
    assert piped.nodes[0].count("lbc-ch") == len("ОРБИТА")
    assert "Пиши HTML." in piped.nodes[0]
    assert "orbit.lab" in piped.nodes[0]
    paper = render_fullscreen(_fs_ctx(
        wordmark="КОД", renderer="logo_brand_close", tone="paper", duration=4.0))
    assert "invert" in paper.nodes[0]


def test_particle_text_dissolve_wipes_with_scale_and_precomputed_dust():
    """Каталог: canvas onUpdate и clip-path. Здесь scaleX и span с x/y, LCG."""
    piece = render_fullscreen(_fs_ctx(
        content="СОБЕРИ ОРБИТУ", accent_word="ОРБИТУ",
        renderer="particle_text_dissolve", particle_dissolve=True,
        direction="in", density="med", exit="none", duration=4.0))
    node = piece.nodes[0]
    assert "ptd-wipe" in node
    assert "ptd-dot" in node
    assert "ptd-ch" in node
    assert " accent" in node
    assert "<svg" in node
    assert "mask=" in node
    assert "<canvas" not in node
    body = " ".join(piece.tweens)
    assert "clipPath" not in body and "clip-path" not in body
    assert "Math.random" not in body
    assert "onUpdate" not in body
    assert "cqh" not in body and "yPercent" not in body
    assert "scaleX:0" in body and "scaleX:1" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#{_fs_ctx().target}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    again = render_fullscreen(_fs_ctx(
        content="СОБЕРИ ОРБИТУ", accent_word="ОРБИТУ",
        renderer="particle_text_dissolve", particle_dissolve=True,
        direction="in", density="med", duration=4.0))
    assert piece.tweens == again.tweens
    from src.lib.render.hyperframes.templates import _PtdRng
    rng = _PtdRng()
    assert rng() == _PtdRng()()


def test_particle_text_dissolve_direction_density_and_exit():
    outgoing = render_fullscreen(_fs_ctx(
        content="КОД", renderer="particle_text_dissolve",
        particle_dissolve=True, direction="out", duration=4.0))
    assert "ptd-out" in outgoing.nodes[0]
    assert "scaleX:1" in " ".join(outgoing.tweens)
    low = render_fullscreen(_fs_ctx(
        content="КОД", renderer="particle_text_dissolve", density="low",
        duration=4.0))
    high = render_fullscreen(_fs_ctx(
        content="КОД", renderer="particle_text_dissolve", density="high",
        duration=4.0))
    assert low.nodes[0].count("ptd-dot") < high.nodes[0].count("ptd-dot")
    fade = render_fullscreen(_fs_ctx(
        content="КОД", renderer="particle_text_dissolve",
        exit="fade", duration=4.0))
    assert 'fromTo("#shot-01-stage",{opacity:1}' in " ".join(fade.tweens)
    up = render_fullscreen(_fs_ctx(
        content="КОД", renderer="particle_text_dissolve",
        exit="up", duration=4.0))
    assert re.search(r"opacity:0,y:-", " ".join(up.tweens))
    paper = render_fullscreen(_fs_ctx(
        content="КОД", renderer="particle_text_dissolve",
        tone="paper", duration=4.0))
    assert "invert" in paper.nodes[0]
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="particle_text_dissolve", duration=4.0))
    assert empty.nodes == []


def test_per_word_crossfade_rises_from_a_static_ghost():
    """Каталог твинит CSS-var и filter. Здесь y/scale и призрак, HOLD без ухода."""
    piece = render_fullscreen(_fs_ctx(
        content="ПИШИ КОД НА ОРБИТЕ", accent_word="ОРБИТЕ",
        renderer="per_word_crossfade", word_crossfade=True,
        drift="standard", blur="standard", tone="ink", exit="none",
        duration=2.0))
    node = piece.nodes[0]
    assert "pwc-word" in node
    assert node.count("pwc-word") == 4
    assert node.count("pwc-ghost") == 4
    assert "filter:blur(5px)" in node
    assert " accent" in node
    body = " ".join(piece.tweens)
    assert "filter" not in body
    assert "--hf-word" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#{_fs_ctx().target}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    w0 = [float(t.rstrip(");").rsplit(",", 1)[1])
          for t in piece.tweens if "fromTo" in t and '-w0"' in t][:1]
    w1 = [float(t.rstrip(");").rsplit(",", 1)[1])
          for t in piece.tweens if "fromTo" in t and '-w1"' in t][:1]
    assert w0 and w1 and w1[0] - w0[0] == pytest.approx(0.055)
    assert re.search(r"scale:0.92,y:[0-9.]+", body)
    assert "y:-" not in body
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    flagged = render_fullscreen(_fs_ctx(
        content="ПИШИ КОД", word_crossfade=True, duration=2.0))
    assert "pwc-word" in flagged.nodes[0]


def test_per_word_crossfade_drift_tone_and_exit():
    close = render_fullscreen(_fs_ctx(
        content="КОД", renderer="per_word_crossfade", drift="close",
        duration=2.0))
    far = render_fullscreen(_fs_ctx(
        content="КОД", renderer="per_word_crossfade", drift="far",
        duration=2.0))
    cy = float(re.search(r"scale:0.92,y:([0-9.]+)", " ".join(close.tweens)).group(1))
    fy = float(re.search(r"scale:0.92,y:([0-9.]+)", " ".join(far.tweens)).group(1))
    assert fy > cy
    heavy = render_fullscreen(_fs_ctx(
        content="КОД", renderer="per_word_crossfade", blur="heavy",
        duration=2.0))
    assert "filter:blur(11px)" in heavy.nodes[0]
    paper = render_fullscreen(_fs_ctx(
        content="КОД", renderer="per_word_crossfade", tone="paper",
        duration=2.0))
    assert "invert" in paper.nodes[0]
    fade = render_fullscreen(_fs_ctx(
        content="КОД", renderer="per_word_crossfade", exit="fade",
        duration=2.0))
    assert 'fromTo("#shot-01-inner",{opacity:1}' in " ".join(fade.tweens)
    up = render_fullscreen(_fs_ctx(
        content="КОД", renderer="per_word_crossfade", exit="up",
        duration=2.0))
    assert re.search(r"opacity:0,y:-", " ".join(up.tweens))
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="per_word_crossfade", duration=2.0))
    assert empty.nodes == []


def test_scan_band_sweeps_a_static_clip_on_x():
    """Каталог твинит CSS-var и clip-path. Здесь overflow-окно и x / -x."""
    piece = render_fullscreen(_fs_ctx(
        content="СИГНАЛ", renderer="scan_band", scan_band=True,
        band_angle=12, duration=3.5))
    node = piece.nodes[0]
    assert "fs-scan-band" in node
    assert "sb-wordmark" in node
    assert node.count('class="sb-clone') == 3
    assert "sb-clone-red" in node and "sb-clone-cyan" in node
    assert "СИГНАЛ" in node
    assert "clip-path" not in node
    assert "skewX(-12deg)" in node and "skewX(12deg)" in node
    assert "transform-origin:0 0" in node
    assert "overflow" not in " ".join(piece.tweens)
    body = " ".join(piece.tweens)
    assert "--sb-band" not in body
    assert "clip-path" not in body
    assert "filter" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    assert "Math.random" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#{_fs_ctx().target}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    assert f'fromTo("{clip}-band",{{x:0}}' in body
    assert f'fromTo("{clip}-inner",{{x:0}}' in body
    assert "x:1080" in body
    assert "x:-1080" in body
    assert f'fromTo("{clip}-stage",{{opacity:0}}' in body
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    flagged = render_fullscreen(_fs_ctx(
        content="СИГНАЛ", scan_band=True, duration=3.5))
    assert "fs-scan-band" in flagged.nodes[0]


def test_scan_band_angle_envelope_and_empty():
    steep = render_fullscreen(_fs_ctx(
        content="КОД", renderer="scan_band", band_angle=30, duration=3.5))
    flat = render_fullscreen(_fs_ctx(
        content="КОД", renderer="scan_band", band_angle=0, duration=3.5))
    assert 'data-band-angle="30"' in steep.nodes[0]
    assert 'data-band-angle="0"' in flat.nodes[0]
    assert "skewX(-30deg)" in steep.nodes[0]
    short = render_fullscreen(_fs_ctx(
        content="КОД", renderer="scan_band", duration=0.8))
    assert "-band" not in " ".join(short.tweens)
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="scan_band", duration=3.5))
    assert empty.nodes == []


def test_scramble_reveal_locks_left_to_right():
    """Каталог пишет textContent. Здесь LCG-таблица и opacity по кадрам."""
    table = _sr_frame_table("ABCD", last_frame=20, scale=1.0)
    assert table[-1] == "ABCD"
    assert table[0] != "ABCD"
    locked = [False] * 4
    for row in table:
        for col, ch in enumerate("ABCD"):
            if locked[col]:
                assert row[col] == ch
            if row[col] == ch:
                locked[col] = True
    assert all(locked)
    piece = render_fullscreen(_fs_ctx(
        content="СИГНАЛ", renderer="scramble_reveal", scramble_reveal=True,
        accent="green", style="terminal", exit="none", duration=3.0))
    node = piece.nodes[0]
    assert "fs-scramble-reveal" in node
    assert "sr-green" in node
    assert "sr-prefix" in node
    assert "СИГНАЛ" in node
    assert node.count('class="sr-row') >= 2
    assert "textContent" not in " ".join(piece.tweens)
    assert "clip-path" not in node
    body = " ".join(piece.tweens)
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#{_fs_ctx().target}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    assert f'fromTo("{clip}-stage",{{opacity:0}}' in body
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    flagged = render_fullscreen(_fs_ctx(
        content="СИГНАЛ", scramble_reveal=True, duration=3.0))
    assert "fs-scramble-reveal" in flagged.nodes[0]


def test_scramble_reveal_envelope_style_and_empty():
    clean = render_fullscreen(_fs_ctx(
        content="КОД", renderer="scramble_reveal", style="clean",
        accent="blue", duration=3.0))
    assert "sr-clean" in clean.nodes[0]
    assert 'data-sr-accent="blue"' in clean.nodes[0]
    fade = render_fullscreen(_fs_ctx(
        content="КОД", renderer="scramble_reveal", exit="fade", duration=3.0))
    up = render_fullscreen(_fs_ctx(
        content="КОД", renderer="scramble_reveal", exit="up", duration=3.0))
    none = render_fullscreen(_fs_ctx(
        content="КОД", renderer="scramble_reveal", exit="none", duration=3.0))
    fade_body = " ".join(fade.tweens)
    up_body = " ".join(up.tweens)
    none_body = " ".join(none.tweens)
    assert 'ease:"power2.in"' in fade_body
    assert "x:" in up_body and "y:" in up_body
    assert none_body.count("power2.in") == 0
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="scramble_reveal", duration=3.0))
    assert empty.nodes == []


def test_shared_axis_z_swells_words_on_scale():
    """Каталог твинит CSS-var; здесь заранее посчитанный scale и opacity."""
    piece = render_fullscreen(_fs_ctx(
        content="ПИШИ КОД", renderer="shared_axis_z", shared_axis_z=True,
        direction="in", depth="standard", tone="ink", duration=1.4))
    node = piece.nodes[0]
    assert "fs-shared-axis-z" in node
    assert "saz-ink" in node
    assert node.count("saz-word") == 2
    assert "ПИШИ" in node and "КОД" in node
    size = int(re.search(r'font-size:(\d+)px', node).group(1))
    one = _fs_size(_fs_ctx(content="ПИШИ КОД"), "ПИШИ")
    assert size < one, "два слова в один ряд, не кегль самого длинного"
    assert "--hf-" not in node
    assert "filter:" not in node
    body = " ".join(piece.tweens)
    assert "--hf-" not in body
    assert "filter" not in body
    assert "back.out(1.8)" in body
    assert "scale:0.72" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#{_fs_ctx().target}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    w0 = [float(t.rstrip(");").rsplit(",", 1)[1])
          for t in piece.tweens if "fromTo" in t and '-w0"' in t]
    w1 = [float(t.rstrip(");").rsplit(",", 1)[1])
          for t in piece.tweens if "fromTo" in t and '-w1"' in t]
    assert w0 and w1 and w1[0] - w0[0] == pytest.approx(0.06)
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    flagged = render_fullscreen(_fs_ctx(
        content="ПИШИ КОД", shared_axis_z=True, duration=1.4))
    assert "fs-shared-axis-z" in flagged.nodes[0]
    assert "ks-word" not in flagged.nodes[0]


def test_shared_axis_z_depth_direction_tone_and_empty():
    cases = {
        ("in", "standard"): "0.72",
        ("in", "shallow"): "0.86",
        ("in", "deep"): "0.482",
        ("out", "standard"): "1.28",
        ("out", "shallow"): "1.14",
        ("out", "deep"): "1.518",
    }
    for (direction, depth), scale in cases.items():
        piece = render_fullscreen(_fs_ctx(
            content="А Б", renderer="shared_axis_z",
            direction=direction, depth=depth, duration=1.4))
        body = " ".join(piece.tweens)
        assert f"scale:{scale}" in body, (direction, depth, body)
    paper = render_fullscreen(_fs_ctx(
        content="КОД", renderer="shared_axis_z", tone="paper", duration=1.4))
    assert "saz-paper" in paper.nodes[0]
    accent = render_fullscreen(_fs_ctx(
        content="КОД", renderer="shared_axis_z", tone="accent", duration=1.4))
    assert "saz-accent" in accent.nodes[0]
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="shared_axis_z", duration=1.4))
    assert empty.nodes == []
    unknown = render_fullscreen(_fs_ctx(
        content="КОД", renderer="shared_axis_z",
        direction="sideways", depth="extreme", tone="neon", duration=1.4))
    assert "saz-ink" in unknown.nodes[0]
    assert "scale:0.72" in " ".join(unknown.tweens)


_C3D_DEMO = (
    "async function loadConfig(path) {\n"
    "  const raw = await readFile(path, \"utf8\")\n"
    "  const config = JSON.parse(raw)\n"
    "  return validate(config)\n"
    "}"
)


def test_code_3d_extrude_settles_a_slab_without_webgl():
    """Каталог крутит Three.js; здесь 2D-посадка scale/x/y/rotation."""
    piece = render_fullscreen(_fs_ctx(
        content=_C3D_DEMO, renderer="code_3d_extrude", code_3d_extrude=True,
        duration=8.0))
    node = piece.nodes[0]
    assert "fs-code-3d" in node
    assert "c3d-slab" in node and "c3d-edge" in node and "c3d-face" in node
    assert "loadConfig" in node and "utf8" in node
    assert "THREE" not in node and "WebGL" not in node and "<canvas" not in node
    assert "position:absolute" not in node.split("c3d-edge", 1)[0]
    assert node.count('id="shot-01"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert "scale:0.72" in body and "rotation:-9" in body
    assert "power3.out" in body and "sine.inOut" in body
    assert "THREE" not in body and "onUpdate" not in body
    assert "Math.random" not in body
    assert "visibility" not in body
    assert "width:" not in body
    assert "filter" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = "#shot-01"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector == "#shot-01-slab"
    exits = [t for t in piece.tweens if "immediateRender:false" in t]
    assert len(exits) == 1
    times = _c3d_times(8.0)
    assert abs(times["settle_dur"] - 4.8) < 1e-9
    assert abs(times["drift_at"] - 4.801) < 1e-9
    flagged = render_fullscreen(_fs_ctx(
        content=_C3D_DEMO, code_3d_extrude=True, duration=8.0))
    assert "fs-code-3d" in flagged.nodes[0]
    assert "ks-word" not in flagged.nodes[0]


def test_code_3d_extrude_highlights_github_dark_and_skips_empty():
    tokens = {(text, color) for line in _c3d_highlight(_C3D_DEMO) for text, color in line}
    assert ("async", "#F97583") in tokens
    assert ("function", "#F97583") in tokens
    assert ("loadConfig", "#B392F0") in tokens
    assert ('"utf8"', "#9ECBFF") in tokens
    assert ("path", "#FFAB70") in tokens
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="code_3d_extrude", duration=8.0))
    assert empty.nodes == []
    short = _c3d_times(1.5)
    assert short["settle_dur"] + 0.001 <= short["drift_at"] + 1e-9
    assert short["settle_dur"] < short["drift_at"] + short["drift_dur"]


def test_code_3d_extrude_css_keeps_github_dark_and_mono():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert "JetBrains Mono" in css
    assert "#05070b" in css and "#24292e" in css and "#141d2b" in css
    assert "#F97583" not in css
    edge = re.search(r"\.c3d-edge\{[^}]+\}", css).group(0)
    assert "background:#141d2b" in edge
    assert "transform:translate(14px,16px)" in edge
    assert "text-transform:none" in css
    slab = re.search(r"\.c3d-slab\{[^}]+\}", css).group(0)
    assert "transform:" not in slab.replace("will-change:transform", "")
    assert "THREE" not in css


_CD_BEFORE = (
    "function greet(name) {\n"
    "  console.log(\"hi \" + name)\n"
    "}"
)
_CD_AFTER = (
    "function greet(name, lang) {\n"
    "  const msg = translate(\"hi\", lang)\n"
    "  console.log(`${msg} ${name}`)\n"
    "}"
)


def test_code_diff_collapses_minus_and_expands_plus_without_height():
    """Каталог твинит height; здесь scaleY и заранее посчитанный y."""
    piece = render_fullscreen(_fs_ctx(
        before=_CD_BEFORE, after=_CD_AFTER, renderer="code_diff",
        code_diff=True, duration=6.0, filename="greet.js"))
    node = piece.nodes[0]
    assert "fs-code-diff" in node
    assert "cd-editor" in node and "cd-del" in node and "cd-add" in node
    assert "greet.js" in node and "loadConfig" not in node
    assert "translate" in node and "console" in node
    assert "height:" not in " ".join(piece.tweens)
    assert "width:" not in " ".join(piece.tweens)
    assert "filter" not in " ".join(piece.tweens)
    assert "visibility" not in " ".join(piece.tweens)
    assert "onUpdate" not in " ".join(piece.tweens)
    assert "Math.random" not in " ".join(piece.tweens)
    assert "THREE" not in node
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    body = " ".join(piece.tweens)
    assert "scaleY:0" in body and "scaleY:1" in body
    assert "power2.inOut" in body and "power2.out" in body
    clip = "#shot-01"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    ops = _cd_line_diff(_CD_BEFORE.split("\n"), _CD_AFTER.split("\n"))
    assert [kind for kind, _text in ops] == [
        "del", "del", "add", "add", "add", "same"]
    flagged = render_fullscreen(_fs_ctx(
        before=_CD_BEFORE, after=_CD_AFTER, code_diff=True, stagger_ms=55,
        duration=6.0))
    assert "fs-code-diff" in flagged.nodes[0]
    assert "ks-word" not in flagged.nodes[0]
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="code_diff", duration=6.0))
    assert empty.nodes == []
    split = render_fullscreen(_fs_ctx(
        content=_CD_BEFORE + "\n---\n" + _CD_AFTER, code_diff=True,
        duration=6.0))
    assert "cd-del" in split.nodes[0] and "cd-add" in split.nodes[0]
    times = _cd_times(6.0, 2, 3)
    assert times["at_del"] + times["del_dur"] <= times["at_add"] + 1e-9
    short = _cd_times(1.5, 2, 3)
    assert short["at_add"] + short["add_dur"] <= 1.5 + 1e-9
    parsed = _cd_parse_pair({"content": "-old\n+new"})
    assert parsed == ("old", "new")


def test_code_diff_css_keeps_github_diff_and_mono():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert "JetBrains Mono" in css
    assert "#f85149" in css and "#3fb950" in css
    assert "#C8453D" not in re.search(r"\.cd-del\{[^}]+\}", css).group(0)
    assert "#C8453D" not in re.search(r"\.cd-add\{[^}]+\}", css).group(0)
    editor = re.search(r"\.cd-editor\{[^}]+\}", css).group(0)
    assert "transform:" not in editor.replace("will-change:transform,opacity", "")
    line = re.search(r"\.cd-line\{[^}]+\}", css).group(0)
    assert "transform-origin:50% 0%" in line
    assert "transform:" not in line.replace("transform-origin:50% 0%", "").replace(
        "will-change:transform,opacity", "")
    assert "text-transform:none" in css
    assert ".fs-code-diff" in css


_CPA_DEMO = (
    "const app = pipe(\n"
    "  parse,\n"
    "  optimize,\n"
    "  emit,\n"
    ")"
)


def test_code_particle_assemble_flies_capped_dust_without_webgl():
    """Каталог рисует GPU Points; здесь span с заранее x/y и mulberry32."""
    piece = render_fullscreen(_fs_ctx(
        content=_CPA_DEMO, renderer="code_particle_assemble",
        code_particle_assemble=True, duration=8.0))
    node = piece.nodes[0]
    assert "fs-code-pa" in node
    assert "pa-dust" in node and "pa-dot" in node and "pa-code" in node
    assert "const" in node and "pipe" in node and "optimize" in node
    assert "CONST" not in node
    assert "THREE" not in node and "WebGL" not in node and "<canvas" not in node
    assert "position:absolute" not in node.split("pa-dust", 1)[0]
    assert node.count('id="shot-01"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    n_dots = node.count("pa-dot")
    assert 80 <= n_dots <= _CPA_CAP
    body = " ".join(piece.tweens)
    assert "power2.out" in body
    assert "scale:0.62" in body
    assert "THREE" not in body and "onUpdate" not in body
    assert "Math.random" not in body
    assert "visibility" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = "#shot-01"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith("#shot-01-")
    flagged = render_fullscreen(_fs_ctx(
        content=_CPA_DEMO, code_particle_assemble=True, stagger_ms=55,
        duration=8.0))
    assert "fs-code-pa" in flagged.nodes[0]
    assert "ks-word" not in flagged.nodes[0]
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="code_particle_assemble", duration=8.0))
    assert empty.nodes == []
    again = render_fullscreen(_fs_ctx(
        content=_CPA_DEMO, renderer="code_particle_assemble",
        code_particle_assemble=True, duration=8.0))
    assert piece.tweens == again.tweens
    rng = _cpa_rng()
    assert rng() == _cpa_rng()()
    times = _cpa_times(8.0)
    assert abs(times["assemble"] - 5.76) < 1e-9
    assert times["code_at"] + times["code_dur"] <= times["assemble"] + 1e-9
    assert times["fade_at"] > times["assemble"]
    assert times["code_at"] + times["code_dur"] <= 8.0 + 1e-9
    short = _cpa_times(1.5)
    assert short["code_at"] + short["code_dur"] <= 1.5 + 1e-9
    assert short["fade_at"] + short["fade"] <= 1.5 + 1e-9


def test_code_particle_assemble_keeps_github_dark_and_mono():
    from src.lib.config import load_config

    piece = render_fullscreen(_fs_ctx(
        content=_CPA_DEMO, renderer="code_particle_assemble", duration=8.0))
    node = piece.nodes[0]
    assert "#F97583" in node and "#B392F0" in node and "#79B8FF" in node
    css = overlay_css(load_config().brandbook)
    assert "JetBrains Mono" in css
    assert "#05070b" in css
    assert ".fs-code-pa" in css
    assert "text-transform:none" in css
    dot = re.search(r"\.pa-dot\{[^}]+\}", css).group(0)
    assert "transform:" not in dot.replace("will-change:transform,opacity", "")
    stage = re.search(r"\.pa-stage\{[^}]+\}", css).group(0)
    assert "position:absolute" not in stage
    invert = re.search(r"\.fullscreen-text\.fs-code-pa\.invert\{[^}]+\}", css).group(0)
    assert "background:#05070b" in invert
    assert "#C8453D" not in dot


_CS_DEMO = (
    'import { createClient } from "./client"\n'
    'import { logger } from "./logger"\n'
    "\n"
    "const RETRIES = 3\n"
    "\n"
    "export async function fetchWithRetry(url, opts = {}) {\n"
    "  const client = createClient(opts)\n"
    "  let lastError = null\n"
    "\n"
    "  for (let attempt = 1; attempt <= RETRIES; attempt++) {\n"
    "    try {\n"
    "      const res = await client.get(url)\n"
    "      if (res.ok) return res.body\n"
    "      lastError = new Error(\"bad status \" + res.status)\n"
    "    } catch (err) {\n"
    "      lastError = err\n"
    "      logger.warn(\"attempt \" + attempt + \" failed\")\n"
    "    }\n"
    "    await sleep(attempt * 250)\n"
    "  }\n"
    "\n"
    "  throw lastError\n"
    "}"
)


def test_code_scroll_centers_the_target_line_without_dom_measure():
    """Каталог меряет getBoundingClientRect; здесь заранее y и vis=14."""
    piece = render_fullscreen(_fs_ctx(
        content=_CS_DEMO, renderer="code_scroll", code_scroll=True,
        duration=6.0, filename="fetchWithRetry.js", line=12))
    node = piece.nodes[0]
    assert "fs-code-scroll" in node
    assert "cs-editor" in node and "cs-scroll" in node and "cs-hl" in node
    assert "cs-gutter" in node and "fetchWithRetry.js" in node
    assert "createClient" in node and "lastError" in node and "await" in node
    assert "CONST" not in node
    assert "FETCHWITHRETRY" not in node
    assert "position:absolute" not in node.split("cs-stage", 1)[0]
    assert node.count('id="shot-01"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert "power2.inOut" in body and "power2.out" in body
    assert "opacity:0.35" in body
    assert "y:" in body
    y_vals = [float(v) for v in re.findall(
        r'tl\.fromTo\("#shot-01-scroll",\{y:0\},\{y:(-?[0-9.]+)', body)]
    assert y_vals and y_vals[0] < -80
    assert "height:" not in body
    assert "width:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "onUpdate" not in body
    assert "Math.random" not in body
    assert "getBoundingClientRect" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = "#shot-01"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith("#shot-01-")
    flagged = render_fullscreen(_fs_ctx(
        content=_CS_DEMO, code_scroll=True, stagger_ms=55, duration=6.0))
    assert "fs-code-scroll" in flagged.nodes[0]
    assert "ks-word" not in flagged.nodes[0]
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="code_scroll", duration=6.0))
    assert empty.nodes == []
    times = _cs_times(6.0)
    assert times["fade_at"] + times["fade"] <= times["scroll_at"] + 1e-9
    assert abs(times["scroll_at"] - 1.25) < 1e-9
    assert abs(times["arr_at"] - 2.95) < 1e-9
    assert times["dim_at"] + times["dim_dur"] <= 6.0 + 1e-9
    short = _cs_times(1.5)
    assert short["fade_at"] + short["fade"] <= short["scroll_at"] + 1e-9
    assert short["arr_at"] <= 1.5 + 1e-9
    assert short["dim_at"] + short["dim_dur"] <= 1.5 + 1e-9
    focused = render_fullscreen(_fs_ctx(
        content=_CS_DEMO, renderer="code_scroll", duration=6.0,
        focus="throw lastError"))
    focused_body = " ".join(focused.tweens)
    assert 'tl.fromTo("#shot-01-ln21",{opacity:1}' not in focused_body
    assert 'tl.fromTo("#shot-01-ln11",{opacity:1}' in focused_body


def test_code_scroll_keeps_github_dark_spotlight_and_mono():
    from src.lib.config import load_config

    piece = render_fullscreen(_fs_ctx(
        content=_CS_DEMO, renderer="code_scroll", duration=6.0))
    node = piece.nodes[0]
    assert "#F97583" in node and "#B392F0" in node and "#79B8FF" in node
    css = overlay_css(load_config().brandbook)
    assert "JetBrains Mono" in css
    assert "#05070b" in css
    assert ".fs-code-scroll" in css
    assert "text-transform:none" in css
    hl = re.search(r"\.cs-hl\{[^}]+\}", css).group(0)
    assert "#58a6ff" in hl
    assert "#C8453D" not in hl
    editor = re.search(r"\.cs-editor\{[^}]+\}", css).group(0)
    assert "transform:" not in editor.replace("will-change:transform,opacity", "")
    scroll = re.search(r"\.cs-scroll\{[^}]+\}", css).group(0)
    assert "transform:" not in scroll.replace("will-change:transform,opacity", "")
    stage = re.search(r"\.cs-stage\{[^}]+\}", css).group(0)
    assert "position:absolute" not in stage
    invert = re.search(r"\.fullscreen-text\.fs-code-scroll\.invert\{[^}]+\}", css).group(0)
    assert "background:#05070b" in invert


_CT_DEMO = (
    "async function loadConfig(path) {\n"
    "  const raw = await readFile(path, \"utf8\")\n"
    "  const config = JSON.parse(raw)\n"
    "  return validate(config)\n"
    "}"
)


def test_code_typing_reveals_glyphs_with_a_precomputed_caret():
    """Каталог меряет getBoundingClientRect; здесь заранее x/y каретки."""
    piece = render_fullscreen(_fs_ctx(
        content=_CT_DEMO, renderer="code_typing", code_typing=True,
        duration=5.0, filename="loadConfig.js"))
    node = piece.nodes[0]
    assert "fs-code-typing" in node
    assert "ct-editor" in node and "ct-caret" in node and "ct-ch" in node
    assert "loadConfig.js" in node
    plain = re.sub(r"<[^>]+>", "", node)
    assert "readFile" in plain and "loadConfig" in plain
    assert "LOADCONFIG" not in node
    assert "position:absolute" not in node.split("ct-stage", 1)[0]
    assert node.count('id="shot-01"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    n_chars = sum(1 for ch in _CT_DEMO if ch != "\n")
    assert node.count("ct-ch") == n_chars
    body = " ".join(piece.tweens)
    assert "power2.out" in body and 'ease:"none"' in body
    assert "getBoundingClientRect" not in body
    assert "height:" not in body
    assert "width:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "onUpdate" not in body
    assert "Math.random" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    caret_tweens = [tw for tw in piece.tweens if "#shot-01-caret" in tw]
    assert len(caret_tweens) == n_chars
    assert all("x:" in tw and "y:" in tw for tw in caret_tweens)
    prev_end = None
    for tw in caret_tweens:
        dur = float(re.search(r"duration:([\d.]+)", tw).group(1))
        start = float(re.search(r"\},([\d.]+)\);$", tw).group(1))
        if prev_end is not None:
            assert start > prev_end + 1e-9, tw
        prev_end = start + dur
    clip = "#shot-01"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith("#shot-01-")
    flagged = render_fullscreen(_fs_ctx(
        content=_CT_DEMO, code_typing=True, stagger_ms=55, duration=5.0))
    assert "fs-code-typing" in flagged.nodes[0]
    assert "ks-word" not in flagged.nodes[0]
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="code_typing", duration=5.0))
    assert empty.nodes == []
    times = _ct_times(5.0, n_chars)
    assert abs(times["per"] - 0.028) < 1e-9
    assert times["caret_dur"] < times["per"] - 5e-4
    assert times["fade_at"] + times["fade"] <= times["type_at"] + 1e-9
    assert times["type_at"] + n_chars * times["per"] <= 5.0 + 1e-9
    short = _ct_times(1.5, n_chars)
    assert short["caret_dur"] < short["per"] - 5e-4
    assert short["fade_at"] + short["fade"] <= short["type_at"] + 1e-9
    assert short["type_at"] + n_chars * short["per"] <= 1.5 + 1e-9


def test_code_typing_keeps_github_dark_caret_and_mono():
    from src.lib.config import load_config

    piece = render_fullscreen(_fs_ctx(
        content=_CT_DEMO, renderer="code_typing", duration=5.0))
    node = piece.nodes[0]
    assert "#F97583" in node and "#B392F0" in node and "#79B8FF" in node
    css = overlay_css(load_config().brandbook)
    assert "JetBrains Mono" in css
    assert "#05070b" in css
    assert ".fs-code-typing" in css
    assert "text-transform:none" in css
    caret = re.search(r"\.ct-caret\{[^}]+\}", css).group(0)
    assert "#58a6ff" in caret
    assert "#C8453D" not in caret
    assert "transform:" not in caret.replace("will-change:transform", "")
    editor = re.search(r"\.ct-editor\{[^}]+\}", css).group(0)
    assert "transform:" not in editor.replace("will-change:transform,opacity", "")
    stage = re.search(r"\.ct-stage\{[^}]+\}", css).group(0)
    assert "position:absolute" not in stage
    invert = re.search(r"\.fullscreen-text\.fs-code-typing\.invert\{[^}]+\}", css).group(0)
    assert "background:#05070b" in invert


_TS_DEMO = "$ hyperframes render --skill=terminal-simulator"


def test_terminal_simulator_grows_skeleton_lines_then_the_command():
    """Каталог твинит CSS-var; здесь scaleX полосок и y терминала."""
    piece = render_fullscreen(_fs_ctx(
        content=_TS_DEMO, renderer="terminal_simulator",
        terminal_simulator=True, duration=5.0))
    node = piece.nodes[0]
    assert "fs-terminal-simulator" in node
    assert "ts-card" in node and "ts-term" in node and "ts-line" in node
    assert "Terminal Simulator" in node
    assert "index.html" in node and "style.css" in node and "timeline.js" in node
    assert _TS_DEMO in node
    assert "HYPERFRAMES RENDER" not in node
    assert "position:absolute" not in node.split("ts-stage", 1)[0]
    assert node.count('id="shot-01"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    assert node.count("ts-line") == 5
    body = " ".join(piece.tweens)
    assert "scaleX:0" in body and "scaleX:1" in body
    assert "power2.out" in body
    assert "--hf-line" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = "#shot-01"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith("#shot-01-")
    assert sum(1 for tw in piece.tweens if "-l" in tw) == 5
    assert sum(1 for tw in piece.tweens if "-term" in tw) == 1
    flagged = render_fullscreen(_fs_ctx(
        content=_TS_DEMO, terminal_simulator=True, stagger_ms=55, duration=5.0))
    assert "fs-terminal-simulator" in flagged.nodes[0]
    assert "ks-word" not in flagged.nodes[0]
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="terminal_simulator", duration=5.0))
    assert _TS_DEMO in empty.nodes[0]
    custom = render_fullscreen(_fs_ctx(
        content="npx hyperframes render", renderer="terminal_simulator",
        duration=5.0))
    assert "$ npx hyperframes render" in custom.nodes[0]
    times = _ts_times(5.0)
    assert abs(times["start"] - 0.50) < 1e-9
    assert abs(times["stagger"] - 0.08) < 1e-9
    assert abs(times["term_at"] - 0.98) < 1e-9
    short = _ts_times(1.5)
    assert short["term_at"] + short["term_dur"] <= 1.5 + 1e-9


def test_terminal_simulator_keeps_catalog_slate_and_green():
    from src.lib.config import load_config

    piece = render_fullscreen(_fs_ctx(
        content=_TS_DEMO, renderer="terminal_simulator", duration=5.0))
    node = piece.nodes[0]
    assert "ts-dot-r" in node and "ts-dot-y" in node and "ts-dot-g" in node
    css = overlay_css(load_config().brandbook)
    assert ".fs-terminal-simulator" in css
    assert "text-transform:none" in css
    assert "JetBrains Mono" in css
    assert "#0f172a" in css
    assert "#f7f7f8" in css
    term = re.search(r"\.ts-term\{[^}]+\}", css).group(0)
    assert "#86efac" in term
    assert "#C8453D" not in term
    line = re.search(r"\.ts-line\{[^}]+\}", css).group(0)
    assert "transform-origin:left center" in line
    assert "transform:" not in line.replace("will-change:transform,opacity", "").replace(
        "transform-origin:left center", "")
    card = re.search(r"\.ts-card\{[^}]+\}", css).group(0)
    assert "transform:" not in card
    stage = re.search(r"\.ts-stage\{[^}]+\}", css).group(0)
    assert "position:absolute" not in stage
    invert = re.search(
        r"\.fullscreen-text\.fs-terminal-simulator\.invert\{[^}]+\}", css).group(0)
    assert "background:#f7f7f8" in invert


def test_number_slam_splits_the_caption():
    piece = render_fullscreen(_fs_ctx(content="105 кубитов", slam=True))
    assert "fs-num" in piece.nodes[0]
    assert "fs-cap" in piece.nodes[0]
    assert "105" in piece.nodes[0] and "кубитов" in piece.nodes[0]


def test_stack_lines_read_max_lines_param():
    piece = render_fullscreen(_fs_ctx(content="один два три четыре", max_lines=2))
    assert "fs-line" in piece.nodes[0]
    assert piece.nodes[0].count('class="fs-line"') == 2


def test_zoom_through_enters_from_a_stronger_scale(ctx):
    piece = render_transition("zoom_through", ctx)
    assert "scale:1.22" in piece.tweens[0]


OVERLAY_PARAMS = {
    "source_card": {"domain": "arxiv.org", "title": "Paper",
                    "snippet": "Hello world", "highlight_line": "Hello"},
    "chat_thread": {"prompt": "что внутри", "snippet": "Квантовый чип. Сто кубит."},
    "article_scroll": {"domain": "nature.com", "title": "Title",
                       "snippet": "long quoted line here", "highlight_line": "quoted"},
    "paper_reveal": {"domain": "arxiv.org", "title": "Nature",
                     "snippet": "One. Two. Three.", "highlight_line": "Two"},
    "lt_accent_underline": {"name": "МАЙЯ ЧЕН",
                            "role": "ВЕДУЩАЯ · НЕЙРОФИЗИОЛОГ"},
    "lt_clean_bar": {"name": "Майя Чен",
                     "role": "Ведущая · нейрофизиолог"},
    "lt_dark_card": {"name": "Майя Чен",
                     "role": "Ведущая · нейрофизиолог"},
}


@pytest.mark.parametrize("name", sorted(OVERLAYS))
def test_overlay_animates_only_allowed_properties(name):
    ctx = TemplateCtx(index=0, start=1.0, duration=3.0, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS[name])
    piece = render_overlay(name, ctx)
    assert piece.nodes, name
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra, f"{name}: {extra}"
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", f"{name} тянет сам клип: {tween}"


def test_lt_accent_underline_draws_the_rule_with_scalex():
    ctx = TemplateCtx(index=0, start=0.0, duration=4.8, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["lt_accent_underline"])
    piece = render_overlay("lt_accent_underline", ctx)
    node = piece.nodes[0]
    assert "lt-accent-underline" in node
    assert 'id="ovl-00-name"' in node and "МАЙЯ ЧЕН" in node
    assert 'id="ovl-00-rule"' in node
    assert 'id="ovl-00-role"' in node and "НЕЙРОФИЗИОЛОГ" in node
    assert node.count('id="ovl-00"') == 1
    assert "position:absolute" not in node
    body = " ".join(piece.tweens)
    assert "scaleX:0" in body and "scaleX:1" in body
    assert "power4.out" in body and "power3.out" in body
    assert "visibility" not in body
    assert "width:" not in body
    assert "#46e5b7" not in node and "#46e5b7" not in body
    exits = [t for t in piece.tweens if "power2.in" in t]
    assert len(exits) == 3
    for tween in exits:
        assert "immediateRender:false" in tween
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
    times = _lt_au_times(4.8)
    assert abs(times["name_in_at"] - 0.10) < 1e-9
    assert abs(times["role_out_at"] - 4.25) < 1e-9


def test_lt_accent_underline_short_window_keeps_enter_before_exit():
    times = _lt_au_times(2.6)
    assert times["role_in_at"] + times["role_in_dur"] < times["role_out_at"]
    assert times["rule_in_at"] + times["rule_in_dur"] < times["rule_out_at"]
    assert times["name_in_at"] + times["name_in_dur"] < times["name_out_at"]
    squeezed = _lt_au_times(1.5)
    assert squeezed["role_in_at"] + squeezed["role_in_dur"] < squeezed["role_out_at"]


def test_lt_accent_underline_reads_text_and_skips_empty():
    ctx = TemplateCtx(index=0, start=0.0, duration=2.6, target="ovl-01",
                      track=5, params={"text": "МАЙЯ ЧЕН"})
    piece = render_overlay("lt_accent_underline", ctx)
    assert "МАЙЯ ЧЕН" in piece.nodes[0]
    assert "ovl-01-role" not in piece.nodes[0]
    empty = render_overlay("lt_accent_underline", TemplateCtx(
        index=0, start=0.0, duration=2.6, target="ovl-02", track=5, params={}))
    assert empty.nodes == []


def test_lt_accent_underline_css_keeps_oswald_and_remaps_mint():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert "#46e5b7" not in css
    assert ".lt-au-rule{display:block;height:6px;border-radius:3px;background:#C8453D;" in css
    rule = re.search(r"\.lt-au-rule\{[^}]+\}", css).group(0)
    assert "transform-origin:0% 50%" in rule
    assert "transform:" not in rule.replace("transform-origin:0% 50%", "")
    assert "Oswald" in css
    assert "Space Mono" in css
    assert "#ffffff" in css and "#e7eaf0" in css


def test_lt_clean_bar_wipes_with_scalex_mask_not_clip_path():
    ctx = TemplateCtx(index=0, start=0.0, duration=4.8, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["lt_clean_bar"])
    piece = render_overlay("lt_clean_bar", ctx)
    node = piece.nodes[0]
    assert "lt-clean-bar" in node
    assert 'id="ovl-00-wipe"' in node and 'id="ovl-00-tab"' in node
    assert "Майя Чен" in node and "нейрофизиолог" in node
    assert "maskUnits" in node
    assert "clip-path" not in node.lower() and "clipPath" not in node
    assert "position:absolute" not in node.split("lt-cb-svg", 1)[0]
    body = " ".join(piece.tweens)
    assert "scaleX:0" in body and "scaleY:0" in body
    assert "clip-path" not in body and "clipPath" not in body
    assert "visibility" not in body
    assert "width:" not in body
    assert "#ff5a36" not in node and "#ff5a36" not in body
    exits = [t for t in piece.tweens if "power2.in" in t]
    assert len(exits) == 1
    assert "immediateRender:false" in exits[0]
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
    times = _lt_cb_times(4.8)
    assert abs(times["wipe_in_at"] - 0.10) < 1e-9
    assert abs(times["exit_at"] - 4.3) < 1e-9


def test_lt_clean_bar_short_window_keeps_enter_before_exit():
    times = _lt_cb_times(2.6)
    assert times["role_in_at"] + times["role_in_dur"] < times["exit_at"]
    squeezed = _lt_cb_times(1.5)
    assert squeezed["role_in_at"] + squeezed["role_in_dur"] < squeezed["exit_at"]


def test_lt_clean_bar_reads_text_and_skips_empty():
    ctx = TemplateCtx(index=0, start=0.0, duration=2.6, target="ovl-01",
                      track=5, params={"text": "Майя Чен"})
    piece = render_overlay("lt_clean_bar", ctx)
    assert "Майя Чен" in piece.nodes[0]
    assert "ovl-01-role" not in piece.nodes[0]
    empty = render_overlay("lt_clean_bar", TemplateCtx(
        index=0, start=0.0, duration=2.6, target="ovl-02", track=5, params={}))
    assert empty.nodes == []


def test_lt_clean_bar_css_keeps_montserrat_and_remaps_orange():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert "#ff5a36" not in css
    assert "clip-path" not in css
    tab = re.search(r"\.lt-cb-tab\{[^}]+\}", css).group(0)
    assert "background:#C8453D" in tab
    assert "transform-origin:50% 0%" in tab
    assert "transform:" not in tab.replace("transform-origin:50% 0%", "")
    wipe = re.search(r"\.lt-cb-wipe\{[^}]+\}", css).group(0)
    assert "transform-origin:0px 50%" in wipe
    assert "Montserrat" in css
    assert "#0f1115" in css and "#5a6170" in css


def test_lt_dark_card_draws_the_rule_with_scalex():
    ctx = TemplateCtx(index=0, start=0.0, duration=4.8, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["lt_dark_card"])
    piece = render_overlay("lt_dark_card", ctx)
    node = piece.nodes[0]
    assert "lt-dark-card" in node
    assert 'id="ovl-00-card"' in node
    assert 'id="ovl-00-name"' in node and "Майя Чен" in node
    assert 'id="ovl-00-rule"' in node
    assert 'id="ovl-00-role"' in node and "нейрофизиолог" in node
    assert node.count('id="ovl-00"') == 1
    assert "position:absolute" not in node
    body = " ".join(piece.tweens)
    assert "scaleX:0" in body and "scaleX:1" in body
    assert "power4.out" in body and "power3.out" in body and "power2.out" in body
    assert "visibility" not in body
    assert "width:" not in body
    assert "#f5b942" not in node and "#f5b942" not in body
    assert "y:60" in body and "y:14" in body and "y:24" in body
    exits = [t for t in piece.tweens if "power2.in" in t]
    assert len(exits) == 1
    assert "immediateRender:false" in exits[0]
    assert "#ovl-00-card" in exits[0]
    for tween in piece.tweens:
        selector = re.search(r'"(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
    times = _lt_dc_times(4.8)
    assert abs(times["card_in_at"] - 0.10) < 1e-9
    assert abs(times["exit_at"] - 4.3) < 1e-9


def test_lt_dark_card_short_window_keeps_enter_before_exit():
    times = _lt_dc_times(2.6)
    assert times["role_in_at"] + times["role_in_dur"] < times["exit_at"]
    assert times["card_in_at"] + times["card_in_dur"] < times["exit_at"]
    squeezed = _lt_dc_times(1.5)
    assert squeezed["role_in_at"] + squeezed["role_in_dur"] < squeezed["exit_at"]


def test_lt_dark_card_reads_text_and_skips_empty():
    ctx = TemplateCtx(index=0, start=0.0, duration=2.6, target="ovl-01",
                      track=5, params={"text": "Майя Чен"})
    piece = render_overlay("lt_dark_card", ctx)
    assert "Майя Чен" in piece.nodes[0]
    assert "ovl-01-role" not in piece.nodes[0]
    empty = render_overlay("lt_dark_card", TemplateCtx(
        index=0, start=0.0, duration=2.6, target="ovl-02", track=5, params={}))
    assert empty.nodes == []


def test_lt_dark_card_css_keeps_charcoal_montserrat_and_remaps_gold():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert "#f5b942" not in css
    assert "#16181d" in css
    rule = re.search(r"\.lt-dc-rule\{[^}]+\}", css).group(0)
    assert "background:#C8453D" in rule
    assert "transform-origin:0% 50%" in rule
    assert "transform:" not in rule.replace("transform-origin:0% 50%", "")
    assert "Montserrat" in css
    assert "#ffffff" in css and "#aeb6c2" in css


def test_chat_thread_puts_the_user_on_the_left():
    ctx = TemplateCtx(index=0, start=1.0, duration=3.0, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["chat_thread"])
    node = render_overlay("chat_thread", ctx).nodes[0]
    assert 'ct-row in' in node
    assert node.index("ct-row in") < node.index("ct-row out")


def test_hero_plate_pop_media_is_the_clip_itself():
    piece = render_hero("hero-plate-pop", _hero_ctx("hero-plate-pop"))
    assert piece.nodes[0].startswith("<video "), piece.nodes[0][:80]
    assert "opacity" not in piece.tweens[0]


def test_new_catalog_ids_carry_example_video():
    manifest = json.loads(Path("templates/manifest.json").read_text(encoding="utf-8"))
    needed = {
        "text-fullscreen/kinetic-stack", "text-fullscreen/number-slam-card",
        "browser-ui/chat-thread", "browser-ui/article-highlight",
        "frames-cards/paper-reveal", "data-viz/stat-countup-card",
        "hero-devices/type-slab", "hero-devices/footage-plate-pop",
        "transitions/zoom-through",
    }
    by_id = {t["id"]: t for t in manifest["templates"]}
    for tid in needed:
        assert by_id[tid].get("example_video"), tid

