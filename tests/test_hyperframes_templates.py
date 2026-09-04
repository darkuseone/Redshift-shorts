"""Каталог шаблонов в HTML/GSAP.

147 шаблон каталога — это рендереры с параметрами. Проверяется то, что
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
    enter_and_drift, entrance_tweens, dataviz_css, hero_css, overlay_css, render_dataviz,
    render_fullscreen, render_hero, render_motion, render_overlay,
    render_transition, transition_css,
    _fs_size, _lt_au_times, _lt_cb_times, _lt_dc_times,     _c3d_times, _c3d_highlight, _cd_times, _cd_line_diff, _cd_parse_pair,
    _cpa_times, _cpa_rng, _CPA_CAP, _cs_times, _ct_times, _ts_times,
    _atcd_times, _dp_times, _bfc_times, _cz_times, _gs_times, _gs_blocks, _GS_SCANS,
    _gw_times, _ll_times, _si_times, _td_times, _wp_times, _cw_times, _t3_times, _tb_times, _tc_times, _tds_times, _tlt_times, _tto_times, _abc_times, _bcr_times, _cst_times, _cpr_times, _dcl_times, _mlg_times, _spm_times, _srf_times, _usm_times, _umf_times, _wmp_times, _sr_frame_table,
    SS_STROKE, text_width,
)
from src.lib.render.hyperframes.apple_money import _amc_times
from src.lib.render.hyperframes.north_korea import _nkl_times
from src.lib.render.hyperframes.nyc_paris import _npf_times
from src.lib.render.hyperframes.mk_progress import _mps_times
from src.lib.render.hyperframes.flowchart_vertical import _fcv_times

# §7 контракта детерминизма: анимировать можно только это.
ALLOWED_PROPS = {
    "opacity", "x", "y", "scale", "scaleX", "scaleY", "rotation",
    "color", "backgroundColor", "borderRadius", "autoAlpha",
    "duration", "ease", "repeat", "yoyo", "stagger",
    # Не свойство, а настройка самого твина: запрет применять начальное
    # состояние сразу при сборке ленты. Твину на кадре она обязательна —
    # иначе он откатывает ведущего к своему `from` с нулевой секунды.
    "immediateRender",
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


def test_tweens_on_the_frame_itself_do_not_reach_back_in_time(ctx):
    """`fromTo` применяет своё `from` сразу при сборке ленты.

    Клип ведущего живёт весь сегмент, и наезд, поставленный на третий шот,
    откатывал его в `scale:0.92` с нулевой секунды: пять секунд ведущий сидел
    в видимом прямоугольнике с тёмными полями. Видно кадром, не тестом, —
    поэтому правило записано здесь.
    """
    from src.lib.render.hyperframes.templates import (
        MOTION, render_motion, render_transition,
    )

    checked = 0
    for name in sorted(TRANSITIONS):
        checked += _assert_target_tweens_hold(render_transition(name, ctx).tweens,
                                              ctx, name)
    for name in sorted(MOTION):
        checked += _assert_target_tweens_hold(render_motion(name, ctx).tweens,
                                              ctx, name)
    for name in sorted(HERO):
        checked += _assert_target_tweens_hold(
            render_hero(name, _hero_ctx(name)).tweens, _hero_ctx(name), name)
    assert checked, "ни один твин по самому кадру не проверен"


def _assert_target_tweens_hold(tweens, ctx, name) -> int:
    """Сколько твинов `fromTo` по кадру проверено — все обязаны нести запрет."""
    seen = 0
    for tween in tweens:
        if not tween.startswith("tl.fromTo(") or f'"#{ctx.target}"' not in tween:
            continue
        seen += 1
        assert "immediateRender:false" in tween, f"{name}: {tween}"
    return seen


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
    # На полосу приходится два твина: затухание и гашение в ноль по концу.
    assert len(first.tweens) == 14
    assert sum(t.startswith("tl.set(") for t in first.tweens) == 7


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
                ".tr-sweep", ".tr-glitch", ".tr-cinematic-zoom",
                ".tr-glitch-shader", ".tr-gravitational-lens", ".tr-light-leak",
                ".tr-sdf-iris", ".tr-thermal-distortion", ".tr-whip-pan",
                ".tr-mk-clone-wall", ".tr-transitions-3d", ".tr-transitions-blur",
                ".tr-transitions-cover", ".tr-transitions-destruction",
                ".tr-transitions-light", ".tr-transitions-other"):
        assert cls in css, cls


# --- диаграммы ----------------------------------------------------------------

@pytest.mark.parametrize("template_id,params", [
    ("data-viz/bar-race-mini", {"values": [12, 30, 7, 25], "labels": list("абвг")}),
    ("data-viz/compare-bars", {"values": [66, 28]}),
    ("data-viz/counter-roll", {"value": 27000, "suffix": " ч"}),
    ("data-viz/donut-fill", {"value": 73}),
    ("data-viz/timeline-dots", {"labels": ["1916", "1971", "2019"]}),
    ("data-viz/stat-countup-card", {"value": 105, "suffix": " кубит", "label": "105"}),
    ("data-viz/animated-bar-chart", {
        "values": [42, 72, 56, 88, 64, 95, 78],
        "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"],
        "kpi": "+42%",
    }),
    ("data-viz/bar-chart-race", {
        "periods": ["2019", "2020", "2021", "2022", "2023", "2024"],
        "series": [
            {"label": "Northwind", "values": [42, 58, 71, 96, 118, 131]},
            {"label": "Cobalt", "values": [30, 46, 68, 92, 126, 168]},
            {"label": "Ferry", "values": [55, 62, 66, 70, 74, 79]},
            {"label": "Marlow", "values": [18, 33, 52, 61, 88, 104]},
            {"label": "Aster", "values": [25, 28, 44, 58, 63, 72]},
            {"label": "Pell", "values": [12, 20, 39, 47, 55, 90]},
            {"label": "Quill", "values": [8, 11, 15, 24, 40, 66]},
            {"label": "Dunmore", "values": [35, 37, 38, 40, 42, 44]},
        ],
    }),
    ("data-viz/chart-story", {
        "values": [12, 28, 45, 64],
        "labels": ["Q1", "Q2", "Q3", "Q4"],
        "emphasize": 3,
        "unit": "%",
    }),
    ("data-viz/conic-progress-ring", {
        "progress": 100,
        "label": "100",
    }),
    ("data-viz/decline-chart", {
        "start_value": 82,
        "end_value": 34,
        "label": "Retention",
    }),
    ("data-viz/mk-line-graph", {
        "series": [
            {"name": "Renders", "values": [12, 26, 22, 38, 44, 58]},
            {"name": "Projects", "values": [8, 14, 18, 16, 28, 36]},
        ],
        "xLabels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
    }),
    ("data-viz/spain-map", {
        "title": "PIB per cápita por Comunidad Autónoma",
        "regions": [
            {"abbr": "MAD", "value": 38100},
            {"abbr": "PVA", "value": 36800},
            {"abbr": "NAV", "value": 35200},
            {"abbr": "EXT", "value": 19200},
        ],
    }),
    ("data-viz/us-map-bubble", {}),
    ("data-viz/flowchart", {}),
    ("data-viz/oscilloscope-trace", {}),
    ("data-viz/weight-wave", {}),
    ("data-viz/star-rating-fill", {
        "rating": 4.8,
        "starCount": 5,
        "showValue": True,
    }),
    ("data-viz/us-map", {
        "title": "Population Density by State",
        "highlight": ["CA", "NY", "TX", "FL", "NJ"],
    }),
    ("data-viz/us-map-flow", {
        "title": "Interstate Flow Connections",
        "subtitle": "Relative volume of major city-to-city corridors",
        "source": "Source: Illustrative data",
    }),
    ("data-viz/us-map-hex", {
        "title": "Median Household Income by State",
        "subtitle": "American Community Survey, 2024",
        "source": "Source: U.S. Census Bureau",
        "highlight": ["MD", "NJ", "MA", "CT", "HI"],
    }),
    ("data-viz/world-map", {
        "title": "Global GDP per Capita",
        "subtitle": "Nominal GDP per capita, 2024 IMF estimates",
        "source": "Source: International Monetary Fund",
        "highlight": ["756", "578", "840", "036", "752"],
    }),
    ("data-viz/apple-money-count", {
        "end_value": 10000,
        "prefix": "$",
    }),
    ("data-viz/north-korea-locked-down", {
        "label": "LOCKED DOWN",
    }),
    ("data-viz/nyc-paris-flight", {
        "origin": "New York", "dest": "Paris",
        "origin_code": "JFK / NYC", "dest_code": "CDG / FR",
        "km": "5,837",
    }),
    ("data-viz/mk-progress-stat", {
        "value": 22, "max": 30, "label": "Goals reached",
        "caption": "Great job, we are getting closer!",
    }),
    ("data-viz/flowchart-vertical", {
        "root": "Should I learn to code?",
        "branches": ["Yes", "Not sure"],
        "leaves": [
            "Start with Python", "Try no-code first",
            "Build a personal website", "Take a free intro course",
        ],
    }),
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
    assert render_dataviz("data-viz/animated-bar-chart", ctx) == Piece()
    assert render_dataviz("data-viz/bar-chart-race", ctx) == Piece()
    assert render_dataviz("data-viz/chart-story", ctx) == Piece()
    assert render_dataviz("data-viz/conic-progress-ring", ctx) == Piece()
    assert render_dataviz("data-viz/decline-chart", ctx) == Piece()
    assert render_dataviz("data-viz/mk-line-graph", ctx) == Piece()
    assert render_dataviz("data-viz/spain-map", ctx) == Piece()
    assert render_dataviz("data-viz/star-rating-fill", ctx) == Piece()
    assert render_dataviz("data-viz/us-map", ctx) == Piece()
    assert render_dataviz("data-viz/us-map-flow", ctx) == Piece()
    assert render_dataviz("data-viz/us-map-hex", ctx) == Piece()
    assert render_dataviz("data-viz/world-map", ctx) == Piece()
    assert render_dataviz("data-viz/apple-money-count",
                         TemplateCtx(index=4, start=10.0, duration=3.0,
                                     target="ovl-04", track=6,
                                     params={"end_value": 0})) == Piece()
    assert render_dataviz("data-viz/north-korea-locked-down", ctx) == Piece()
    assert render_dataviz("data-viz/nyc-paris-flight", ctx) == Piece()
    assert render_dataviz("data-viz/mk-progress-stat", ctx) == Piece()
    assert render_dataviz("data-viz/flowchart-vertical", ctx) == Piece()


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


def test_existing_bars_do_not_use_animated_bar_chart_classes():
    ctx = TemplateCtx(index=0, start=0.0, duration=3.0, target="ovl-00",
                      track=6, params={"values": [50, 100], "labels": ["A", "B"]})
    compare = render_dataviz("data-viz/compare-bars", ctx).nodes[0]
    race = render_dataviz("data-viz/bar-race-mini", ctx).nodes[0]
    assert "dv-bar" in compare and "dv-bar" in race
    assert "abc-" not in compare and "abc-" not in race
    assert "bcr-" not in compare and "bcr-" not in race
    assert "cst-" not in compare and "cst-" not in race
    assert "cpr-" not in compare and "cpr-" not in race
    assert "dcl-" not in compare and "dcl-" not in race
    assert "mlg-" not in compare and "mlg-" not in race
    assert "spm-" not in compare and "spm-" not in race
    assert "srf-" not in compare and "srf-" not in race
    assert "usm-" not in compare and "usm-" not in race
    assert "umf-" not in compare and "umf-" not in race
    assert "umh-" not in compare and "umh-" not in race
    assert "wmp-" not in compare and "wmp-" not in race
    donut = render_dataviz("data-viz/donut-fill", TemplateCtx(
        index=0, start=0.0, duration=3.0, target="ovl-00",
        track=6, params={"value": 73})).nodes[0]
    assert "dv-donut" in donut
    assert "cpr-" not in donut
    assert "cst-" not in donut
    assert "dcl-" not in donut
    assert "mlg-" not in donut
    assert "spm-" not in donut
    assert "srf-" not in donut
    assert "usm-" not in donut
    assert "umf-" not in donut
    assert "umh-" not in donut
    assert "wmp-" not in donut


def test_animated_bar_chart_grows_scaleY_without_css_transform(ctx):
    """Каталог DEMO 1 твинит --hf-grow; здесь scaleY, без height/width/dash."""
    piece = render_dataviz("data-viz/animated-bar-chart", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=5.0, target=ctx.target,
        track=6, params={
            "values": [42, 72, 56, 88, 64, 95, 78],
            "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"],
            "kpi": "+42%",
        }))
    node = piece.nodes[0]
    assert "abc-chart" in node
    assert "abc-card" in node and "abc-grow" in node and "abc-fill" in node
    assert "abc-kpi" in node and "+42%" in node
    assert "Animated Bar Chart" in node
    assert "Jan" in node and "Jul" in node
    assert "dv-bar" not in node
    assert "stat-card" not in node
    assert "--hf-grow" not in node
    assert "--hf-dash" not in node
    assert node.count(f'id="abc-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    for i in range(7):
        assert f'id="abc-{ctx.index:02d}-b{i}"' in node
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "power3.out" in body
    assert "immediateRender:false" in body
    assert "scaleY:0" in body and "scaleY:1" in body
    assert "opacity:1" in body
    assert "filter" not in body
    assert "strokeDashoffset" not in body
    assert "stroke-dashoffset" not in body
    assert "--hf-grow" not in body
    assert "--hf-dash" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "clipPath" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#abc-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _abc_times(5.0)
    assert times["grow_at"] + times["grow_dur"] + 0.001 <= times["kill_at"] + 1e-9
    assert abs(times["grow_at"] - 0.5) < 1e-9
    assert abs(times["grow_dur"] - 1.2) < 1e-9
    short = _abc_times(0.22)
    assert short["grow_at"] + short["grow_dur"] + 0.001 <= 0.22 + 1e-9


def test_bar_chart_race_uses_scalex_not_width(ctx):
    """Каталог DEMO 1 твинит width и textContent; здесь scaleX/x/y и span-ы."""
    piece = render_dataviz("data-viz/bar-chart-race", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=12.0, target=ctx.target,
        track=6, params={
            "title": "Streaming Subscribers by Service",
            "subtitle": "Ranked by reported subscribers",
            "periods": ["2019", "2020", "2021", "2022", "2023", "2024"],
            "series": [
                {"label": "Northwind", "values": [42, 58, 71, 96, 118, 131]},
                {"label": "Cobalt", "values": [30, 46, 68, 92, 126, 168]},
                {"label": "Ferry", "values": [55, 62, 66, 70, 74, 79]},
                {"label": "Marlow", "values": [18, 33, 52, 61, 88, 104]},
                {"label": "Aster", "values": [25, 28, 44, 58, 63, 72]},
                {"label": "Pell", "values": [12, 20, 39, 47, 55, 90]},
                {"label": "Quill", "values": [8, 11, 15, 24, 40, 66]},
                {"label": "Dunmore", "values": [35, 37, 38, 40, 42, 44]},
            ],
        }))
    node = piece.nodes[0]
    assert "bcr-chart" in node
    assert "bcr-bar" in node and "bcr-row" in node and "bcr-period" in node
    assert "Streaming Subscribers by Service" in node
    assert "Northwind" in node and "Cobalt" in node and "Ferry" in node
    assert "2019" in node and "2024" in node
    assert "$168M" in node and "$42M" in node
    assert "dv-bar" not in node
    assert "abc-" not in node
    assert "cst-" not in node
    assert "stat-card" not in node
    assert "textContent" not in node
    assert node.count(f'id="bcr-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    for i in range(8):
        assert f'id="bcr-{ctx.index:02d}-b{i}"' in node
        assert f'id="bcr-{ctx.index:02d}-r{i}"' in node
        assert f'id="bcr-{ctx.index:02d}-v{i}"' in node
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scaleX:" in body
    assert "ease:\"none\"" in body or "ease:\"none\"" in "".join(piece.tweens)
    assert "immediateRender:false" in body
    assert "#c8452d" in body
    assert "#1f1d1b" in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "clipPath" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#bcr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _bcr_times(12.0)
    assert abs(times["race_end"] - 10.0) < 1e-9
    assert abs(times["period"] - 2.0) < 1e-9
    short = _bcr_times(0.22)
    assert short["race_end"] + 0.001 <= 0.22 + 1e-9


def test_chart_story_grows_scaleY_not_height(ctx):
    """Каталог DEMO 1 твинит attr.height и textContent; здесь scaleY и span-ы."""
    piece = render_dataviz("data-viz/chart-story", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=5.0, target=ctx.target,
        track=6, params={
            "values": [12, 28, 45, 64],
            "labels": ["Q1", "Q2", "Q3", "Q4"],
            "emphasize": 3,
            "unit": "%",
            "accent": "green",
        }))
    node = piece.nodes[0]
    assert "cst-chart" in node
    assert "cst-bar" in node and "cst-stage" in node and "cst-call" in node
    assert "cst-bg" in node
    assert "Q1" in node and "Q4" in node
    assert "12%" in node and "28%" in node and "45%" in node and "64%" in node
    assert "#71f5a7" in node
    assert "#767a80" in node
    assert "dv-bar" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "stat-card" not in node
    assert "textContent" not in node
    assert "--hf-grow" not in node
    assert node.count(f'id="cst-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    for i in range(4):
        assert f'id="cst-{ctx.index:02d}-b{i}"' in node
        assert f'id="cst-{ctx.index:02d}-al{i}"' in node
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scaleY:0" in body and "scaleY:1" in body
    assert "scaleX:0" in body and "scaleX:1" in body
    assert "back.out(1.7)" in body
    assert "power3.out" in body
    assert "immediateRender:false" in body
    assert "opacity:1" in body
    assert "filter" not in body
    assert "strokeDashoffset" not in body
    assert "attr:" not in body
    assert "textContent" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "clipPath" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#cst-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _cst_times(5.0)
    assert abs(times["enter_dur"] - 0.5) < 1e-9
    assert abs(times["callout_at"] - 2.35) < 1e-9
    assert abs(times["hold_start"] - 3.3) < 1e-9
    short = _cst_times(0.22)
    assert short["callout_at"] + 0.001 <= 0.22 + 1e-9


def test_conic_progress_ring_rotates_halves_not_conic(ctx):
    """Каталог DEMO 1 твинит --ring-progress и textContent; здесь rotation и span-ы."""
    piece = render_dataviz("data-viz/conic-progress-ring", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=4.0, target=ctx.target,
        track=6, params={"progress": 100, "label": "100", "thickness": 12}))
    node = piece.nodes[0]
    assert "cpr-chart" in node
    assert "cpr-disc" in node and "cpr-stage" in node and "cpr-paint" in node
    assert "cpr-bg" in node
    assert "cpr-hole" in node
    assert ">100<" in node
    assert "dv-donut" not in node
    assert "dv-ring" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "cst-" not in node
    assert "dcl-" not in node
    assert "stat-card" not in node
    assert "textContent" not in node
    assert "--ring-progress" not in node
    assert "conic-gradient" not in node
    assert node.count(f'id="cpr-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    assert f'id="cpr-{ctx.index:02d}-a"' in node
    assert f'id="cpr-{ctx.index:02d}-b"' in node
    assert f'id="cpr-{ctx.index:02d}-stage"' in node
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "rotation:" in body
    assert "power2.in" in body
    assert "ease:\"none\"" in body or 'ease:"none"' in body
    assert "immediateRender:false" in body
    assert "opacity:1" in body
    assert "filter" not in body
    assert "strokeDashoffset" not in body
    assert "attr:" not in body
    assert "textContent" not in body
    assert "--ring-progress" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "clipPath" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#cpr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _cpr_times(4.0)
    assert abs(times["in"] - 1.4) < 1e-9
    assert abs(times["out"] - 0.5) < 1e-9
    assert abs(times["out_start"] - 3.5) < 1e-9
    short = _cpr_times(0.22)
    assert short["out_start"] + 0.001 <= 0.22 + 1e-9


def test_conic_progress_ring_keeps_catalog_brand_and_surface():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".cpr-chart" in css
    assert ".cpr-disc" in css
    chart = re.search(r"\.cpr-chart\{[^}]+\}", css).group(0)
    bg = re.search(r"\.cpr-bg\{[^}]+\}", css).group(0)
    disc = re.search(r"\.cpr-disc\{[^}]+\}", css).group(0)
    paint = re.search(r"\.cpr-paint\{[^}]+\}", css).group(0)
    hole = re.search(r"\.cpr-hole\{[^}]+\}", css).group(0)
    label = re.search(r"\.cpr-cv\{[^}]+\}", css).group(0)
    rot = re.search(r"\.cpr-rot\{[^}]+\}", css).group(0)
    assert "#0a0a0a" in chart
    assert "#0a0a0a" in bg
    assert "#0a0a0a" in hole
    assert "#1b2938" in disc
    assert "#35d6a0" in paint
    assert "#f4f7fb" in chart
    assert "#f4f7fb" in label
    assert "transform-origin:50% 50%" in rot
    block = css.split(".cpr-chart", 1)[1].split(".dcl-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    assert "text-transform" not in block
    stripped = (css.replace("transform-origin:left center", "")
                .replace("transform-origin:50% 50%", "")
                .replace("transform-origin:50% 100%", "")
                .replace("transform-origin:0px 50%", "")
                .replace("transform-box:fill-box", ""))
    assert "transform:" not in stripped.split(".cpr-chart", 1)[1].split(".dcl-chart", 1)[0]
    dv_bar = re.search(r"\.dv-bar\{[^}]+\}", css).group(0)
    assert "cpr-" not in dv_bar
    donut = re.search(r"\.dv-donut\{[^}]+\}", css).group(0)
    assert "cpr-" not in donut


def test_decline_chart_draws_mask_not_dash(ctx):
    """Каталог DEMO 1 твинит strokeDashoffset и textContent; здесь scaleX и span-ы."""
    piece = render_dataviz("data-viz/decline-chart", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=4.0, target=ctx.target,
        track=6, params={
            "start_value": 82,
            "end_value": 34,
            "label": "Retention",
        }))
    node = piece.nodes[0]
    assert "dcl-chart" in node
    assert "dcl-bg" in node and "dcl-stage" in node and "dcl-line" in node
    assert "dcl-gloom" in node and "dcl-wipe" in node and "dcl-ep" in node
    assert "Retention" in node
    assert ">82<" in node and ">34<" in node
    assert "dv-bar" not in node
    assert "dv-donut" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "cst-" not in node
    assert "cpr-" not in node
    assert "mlg-" not in node
    assert "stat-card" not in node
    assert "textContent" not in node
    assert "strokeDashoffset" not in node
    assert "stroke-dashoffset" not in node
    assert "conic-gradient" not in node
    assert node.count(f'id="dcl-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    assert f'id="dcl-{ctx.index:02d}-stage"' in node
    assert f'id="dcl-{ctx.index:02d}-wipe"' in node
    assert f'id="dcl-{ctx.index:02d}-ep"' in node
    assert f'id="dcl-{ctx.index:02d}-gloom"' in node
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scaleX:0" in body and "scaleX:1" in body
    assert "power2.out" in body
    assert "immediateRender:false" in body
    assert "opacity:1" in body
    assert "filter" not in body
    assert "strokeDashoffset" not in body
    assert "stroke-dashoffset" not in body
    assert "attr:" not in body
    assert "textContent" not in body
    assert "saturate" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "clipPath" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#dcl-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _dcl_times(4.0)
    assert abs(times["in"] - 0.55) < 1e-9
    assert abs(times["out"] - 0.45) < 1e-9
    assert abs(times["hold"] - 3.0) < 1e-9
    assert abs(times["out_start"] - 3.55) < 1e-9
    short = _dcl_times(0.22)
    assert short["out_start"] + 0.001 <= 0.22 + 1e-9


def test_decline_chart_keeps_catalog_line_and_ambient():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".dcl-chart" in css
    assert ".dcl-line" in css
    chart = re.search(r"\.dcl-chart\{[^}]+\}", css).group(0)
    bg = re.search(r"\.dcl-bg\{[^}]+\}", css).group(0)
    gloom = re.search(r"\.dcl-gloom\{[^}]+\}", css).group(0)
    line = re.search(r"\.dcl-line\{[^}]+\}", css).group(0)
    ep = re.search(r"\.dcl-ep\{[^}]+\}", css).group(0)
    label = re.search(r"\.dcl-label\{[^}]+\}", css).group(0)
    value = re.search(r"\.dcl-cv\{[^}]+\}", css).group(0)
    wipe = re.search(r"\.dcl-wipe\{[^}]+\}", css).group(0)
    assert "#0c1118" in chart
    assert "#152f3c" in bg and "#101a25" in bg and "#0c1118" in bg
    assert "#030507" in gloom
    assert "#fb7185" in line
    assert "#fecdd3" in ep
    assert "#f8fafc" in chart and "#f8fafc" in value
    assert "text-transform:uppercase" in label
    assert "transform-origin:0px 50%" in wipe
    assert "transform-box:fill-box" in wipe
    assert "transform-origin:50% 50%" in ep
    block = css.split(".dcl-chart", 1)[1].split(".mlg-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    stripped = (css.replace("transform-origin:left center", "")
                .replace("transform-origin:50% 50%", "")
                .replace("transform-origin:50% 100%", "")
                .replace("transform-origin:0px 50%", "")
                .replace("transform-box:fill-box", "")
                .replace("text-transform:uppercase", ""))
    assert "transform:" not in stripped.split(".dcl-chart", 1)[1].split(".mlg-chart", 1)[0]
    dv_bar = re.search(r"\.dv-bar\{[^}]+\}", css).group(0)
    assert "dcl-" not in dv_bar
    donut = re.search(r"\.dv-donut\{[^}]+\}", css).group(0)
    assert "dcl-" not in donut


def test_mk_line_graph_draws_mask_not_dash(ctx):
    """Каталог DEMO 1 твинит strokeDashoffset; здесь scaleX на SVG-mask."""
    piece = render_dataviz("data-viz/mk-line-graph", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=7.0, target=ctx.target,
        track=6, params={
            "series": [
                {"name": "Renders", "values": [12, 26, 22, 38, 44, 58]},
                {"name": "Projects", "values": [8, 14, 18, 16, 28, 36]},
            ],
            "xLabels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
        }))
    node = piece.nodes[0]
    assert "mlg-chart" in node
    assert "mlg-bg" in node and "mlg-stage" in node and "mlg-line" in node
    assert "mlg-wipe" in node and "mlg-dot" in node and "mlg-legend" in node
    assert "Renders" in node and "Projects" in node
    assert "Jan" in node and "Jun" in node
    assert ">12<" in node and ">58<" in node and ">8<" in node and ">36<" in node
    assert "#0071e3" in node and "#45d6c8" in node
    assert "dv-bar" not in node
    assert "dv-donut" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "cst-" not in node
    assert "cpr-" not in node
    assert "dcl-" not in node
    assert "stat-card" not in node
    assert "textContent" not in node
    assert "strokeDashoffset" not in node
    assert "stroke-dashoffset" not in node
    assert "mk-lg-" not in node
    assert node.count(f'id="mlg-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    assert f'id="mlg-{ctx.index:02d}-stage"' in node
    assert f'id="mlg-{ctx.index:02d}-w0"' in node
    assert f'id="mlg-{ctx.index:02d}-w1"' in node
    assert f'id="mlg-{ctx.index:02d}-d0-0"' in node
    assert f'id="mlg-{ctx.index:02d}-d1-5"' in node
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scaleX:0" in body and "scaleX:1" in body
    assert "power2.inOut" in body
    assert "back.out(1.2)" in body
    assert "immediateRender:false" in body
    assert "opacity:1" in body
    assert "filter" not in body
    assert "strokeDashoffset" not in body
    assert "stroke-dashoffset" not in body
    assert "attr:" not in body
    assert "textContent" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "clipPath" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#mlg-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _mlg_times(7.0)
    assert abs(times["axis_at"] - 0.2) < 1e-9
    assert abs(times["draw"] - 1.3) < 1e-9
    assert abs(times["legend_at"] - 2.3) < 1e-9
    assert abs(times["out_start"] - 6.5) < 1e-9
    assert abs(times["out_dur"] - 0.4) < 1e-9
    short = _mlg_times(0.22)
    assert short["out_start"] + 0.001 <= 0.22 + 1e-9


def test_mk_line_graph_keeps_catalog_mk_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".mlg-chart" in css
    assert ".mlg-line" in css
    chart = re.search(r"\.mlg-chart\{[^}]+\}", css).group(0)
    bg = re.search(r"\.mlg-bg\{[^}]+\}", css).group(0)
    axis = re.search(r"\.mlg-axis\{[^}]+\}", css).group(0)
    val = re.search(r"\.mlg-val\{[^}]+\}", css).group(0)
    xl = re.search(r"\.mlg-xl\{[^}]+\}", css).group(0)
    wipe = re.search(r"\.mlg-wipe\{[^}]+\}", css).group(0)
    dot = re.search(r"\.mlg-dot\{[^}]+\}", css).group(0)
    assert "#ffffff" in chart and "#ffffff" in bg
    assert "#1d1d1f" in chart and "#1d1d1f" in val
    assert "#6e6e73" in xl
    assert "rgba(29,29,31,0.22)" in axis
    assert "transform-origin:0px 50%" in wipe
    assert "transform-box:fill-box" in wipe
    assert "transform-origin:50% 50%" in dot
    block = css.split(".mlg-chart", 1)[1].split(".spm-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    stripped = (css.replace("transform-origin:left center", "")
                .replace("transform-origin:50% 50%", "")
                .replace("transform-origin:50% 100%", "")
                .replace("transform-origin:0px 50%", "")
                .replace("transform-origin:100% 50%", "")
                .replace("transform-box:fill-box", "")
                .replace("text-transform:uppercase", ""))
    assert "transform:" not in stripped.split(".mlg-chart", 1)[1].split(".spm-chart", 1)[0]
    dv_bar = re.search(r"\.dv-bar\{[^}]+\}", css).group(0)
    assert "mlg-" not in dv_bar
    donut = re.search(r"\.dv-donut\{[^}]+\}", css).group(0)
    assert "mlg-" not in donut
    dcl = re.search(r"\.dcl-line\{[^}]+\}", css).group(0)
    assert "mlg-" not in dcl


def test_spain_map_bakes_paths_not_fetch(ctx):
    """Каталог DEMO 1 тянет topojson и твинит clipPath/filter; здесь контуры и scaleX."""
    piece = render_dataviz("data-viz/spain-map", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=12.0, target=ctx.target,
        track=6, params={
            "title": "PIB per cápita por Comunidad Autónoma",
            "subtitle": "Producto Interior Bruto per cápita, estimación 2024",
            "source": "Fuente: Instituto Nacional de Estadística",
            "highlight": ["MAD", "PVA", "NAV"],
            "regions": [
                {"abbr": "AND", "value": 20200},
                {"abbr": "ARA", "value": 30500},
                {"abbr": "AST", "value": 24100},
                {"abbr": "BAL", "value": 28900},
                {"abbr": "CAN", "value": 21500},
                {"abbr": "CNT", "value": 25200},
                {"abbr": "CYL", "value": 25800},
                {"abbr": "CLM", "value": 21400},
                {"abbr": "CAT", "value": 33700},
                {"abbr": "VAL", "value": 23800},
                {"abbr": "EXT", "value": 19200},
                {"abbr": "GAL", "value": 24500},
                {"abbr": "MAD", "value": 38100},
                {"abbr": "MUR", "value": 22100},
                {"abbr": "NAV", "value": 35200},
                {"abbr": "PVA", "value": 36800},
                {"abbr": "RIO", "value": 29800},
                {"abbr": "CEU", "value": 21000},
                {"abbr": "MEL", "value": 19500},
            ],
        }))
    node = piece.nodes[0]
    assert "spm-chart" in node
    assert "spm-bg" in node and "spm-stage" in node and "spm-region" in node
    assert "spm-wipe" in node and "spm-legend" in node and "spm-lab" in node
    assert "PIB per c" in node
    assert "Bajo" in node and "Alto" in node
    assert "Fuente" in node
    assert "MAD" in node and "PVA" in node and "NAV" in node and "EXT" in node
    assert "#7f1d1d" in node or "#dc2626" in node or "#fbbf24" in node
    assert "dv-bar" not in node
    assert "dv-donut" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "cst-" not in node
    assert "cpr-" not in node
    assert "dcl-" not in node
    assert "mlg-" not in node
    assert "srf-" not in node
    assert "usm-" not in node
    assert "umf-" not in node
    assert "umh-" not in node
    assert "wmp-" not in node
    assert "stat-card" not in node
    assert "jsdelivr" not in node
    assert "topojson" not in node
    assert "textContent" not in node
    assert "clipPath" not in node
    assert "clip-path" not in node
    assert node.count(f'id="spm-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    assert f'id="spm-{ctx.index:02d}-stage"' in node
    assert f'id="spm-{ctx.index:02d}-wipe"' in node
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scaleX:1" in body and "scaleX:0" in body
    assert "back.out(1.4)" in body
    assert "immediateRender:false" in body
    assert "filter" not in body
    assert "clipPath" not in body
    assert "strokeWidth" not in body
    assert "textContent" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#spm-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _spm_times(12.0)
    assert abs(times["hl_dur"] - 1.0) < 1e-9
    assert abs(times["reg_at"] - 1.0) < 1e-9
    assert abs(times["lab_at"] - 4.0) < 1e-9
    assert abs(times["leg_at"] - 5.5) < 1e-9
    assert abs(times["hi_at"] - 6.5) < 1e-9
    assert abs(times["out_start"] - 11.5) < 1e-9
    short = _spm_times(0.22)
    assert short["out_start"] + 0.001 <= 0.22 + 1e-9


def test_spain_map_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".spm-chart" in css
    assert ".spm-region" in css
    chart = re.search(r"\.spm-chart\{[^}]+\}", css).group(0)
    bg = re.search(r"\.spm-bg\{[^}]+\}", css).group(0)
    hl = re.search(r"\.spm-hl\{[^}]+\}", css).group(0)
    wipe = re.search(r"\.spm-wipe\{[^}]+\}", css).group(0)
    bar = re.search(r"\.spm-legend-bar\{[^}]+\}", css).group(0)
    region = re.search(r"\.spm-region\{[^}]+\}", css).group(0)
    assert "#0f172a" in chart and "#0f172a" in bg
    assert "#1e293b" in bg
    assert "#f8fafc" in hl
    assert "#7f1d1d" in bar and "#dc2626" in bar and "#fbbf24" in bar
    assert "transform-origin:100% 50%" in wipe
    assert "transform-origin:50% 50%" in region
    assert "transform-box:fill-box" in region
    block = css.split(".spm-chart", 1)[1].split(".srf-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    stripped = (css.replace("transform-origin:left center", "")
                .replace("transform-origin:50% 50%", "")
                .replace("transform-origin:50% 100%", "")
                .replace("transform-origin:0px 50%", "")
                .replace("transform-origin:100% 50%", "")
                .replace("transform-box:fill-box", "")
                .replace("text-transform:uppercase", ""))
    assert "transform:" not in stripped.split(".spm-chart", 1)[1].split(".srf-chart", 1)[0]
    dv_bar = re.search(r"\.dv-bar\{[^}]+\}", css).group(0)
    assert "spm-" not in dv_bar
    donut = re.search(r"\.dv-donut\{[^}]+\}", css).group(0)
    assert "spm-" not in donut
    mlg = re.search(r"\.mlg-line\{[^}]+\}", css).group(0)
    assert "spm-" not in mlg


def test_star_rating_fill_wipes_mask_not_clip_path(ctx):
    """Каталог DEMO 1 твинит clip-path и textContent; здесь SVG-mask scaleX."""
    piece = render_dataviz("data-viz/star-rating-fill", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=4.0, target=ctx.target,
        track=6, params={"rating": 4.8, "starCount": 5, "showValue": True}))
    node = piece.nodes[0]
    assert "srf-chart" in node
    assert "srf-bg" in node and "srf-stage" in node and "srf-card" in node
    assert "srf-wipe" in node and "srf-cell" in node and "srf-fill-star" in node
    assert "4.8" in node
    assert "M50 0" in node
    assert "#ffc83d" in node
    assert "#626d7e" in node
    assert "dv-bar" not in node
    assert "dv-donut" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "cst-" not in node
    assert "cpr-" not in node
    assert "dcl-" not in node
    assert "mlg-" not in node
    assert "spm-" not in node
    assert "usm-" not in node
    assert "umf-" not in node
    assert "umh-" not in node
    assert "wmp-" not in node
    assert "stat-card" not in node
    assert "textContent" not in node
    assert "clipPath" not in node
    assert "clip-path" not in node
    assert "--ring-progress" not in node
    assert node.count(f'id="srf-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    assert f'id="srf-{ctx.index:02d}-stage"' in node
    assert f'id="srf-{ctx.index:02d}-wipe"' in node
    assert f'id="srf-{ctx.index:02d}-b0"' in node
    assert f'id="srf-{ctx.index:02d}-f4"' in node
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scaleX:0" in body and "scaleX:0.96" in body
    assert "scale:1.06" in body
    assert "power2.out" in body
    assert "immediateRender:false" in body
    assert "filter" not in body
    assert "clipPath" not in body
    assert "clip-path" not in body
    assert "textContent" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#srf-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _srf_times(4.0)
    assert abs(times["in"] - 1.5) < 1e-9
    assert abs(times["out"] - 0.4) < 1e-9
    assert abs(times["fill_start"] - 0.2) < 1e-9
    assert abs(times["fill_dur"] - 1.1) < 1e-9
    assert abs(times["out_start"] - 3.6) < 1e-9
    short = _srf_times(0.22)
    assert short["out_start"] + 0.001 <= 0.22 + 1e-9


def test_star_rating_fill_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".srf-chart" in css
    assert ".srf-wipe" in css
    chart = re.search(r"\.srf-chart\{[^}]+\}", css).group(0)
    bg = re.search(r"\.srf-bg\{[^}]+\}", css).group(0)
    card = re.search(r"\.srf-card\{[^}]+\}", css).group(0)
    wipe = re.search(r"\.srf-wipe\{[^}]+\}", css).group(0)
    cell = re.search(r"\.srf-cell\{[^}]+\}", css).group(0)
    fill = re.search(r"\.srf-fill-star\{[^}]+\}", css).group(0)
    cv = re.search(r"\.srf-cv\{[^}]+\}", css).group(0)
    assert "#090d16" in chart and "#090d16" in bg
    assert "#f4f7fb" in chart and "#f4f7fb" in cv
    assert "#1a2230" in card
    assert "rgba(244,247,251,0.14)" in card
    assert "transform-origin:0px 50%" in wipe
    assert "transform-box:fill-box" in wipe
    assert "transform-origin:50% 50%" in cell
    assert "transform-box:fill-box" in fill
    block = css.split(".srf-chart", 1)[1].split(".usm-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    stripped = (css.replace("transform-origin:left center", "")
                .replace("transform-origin:50% 50%", "")
                .replace("transform-origin:50% 100%", "")
                .replace("transform-origin:0px 50%", "")
                .replace("transform-origin:100% 50%", "")
                .replace("transform-box:fill-box", "")
                .replace("text-transform:uppercase", ""))
    assert "transform:" not in stripped.split(".srf-chart", 1)[1].split(".usm-chart", 1)[0]
    dv_bar = re.search(r"\.dv-bar\{[^}]+\}", css).group(0)
    assert "srf-" not in dv_bar
    donut = re.search(r"\.dv-donut\{[^}]+\}", css).group(0)
    assert "srf-" not in donut
    spm = re.search(r"\.spm-region\{[^}]+\}", css).group(0)
    assert "srf-" not in spm
    usm = re.search(r"\.usm-region\{[^}]+\}", css).group(0)
    assert "srf-" not in usm


def test_us_map_bakes_paths_not_fetch(ctx):
    """Каталог DEMO 1 тянет topojson и твинит clipPath/filter; здесь контуры и scaleX."""
    piece = render_dataviz("data-viz/us-map", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=12.0, target=ctx.target,
        track=6, params={
            "title": "Population Density by State",
            "subtitle": "Residents per square mile, 2024 Census estimates",
            "source": "Source: U.S. Census Bureau",
            "highlight": ["CA", "NY", "TX", "FL", "NJ"],
        }))
    node = piece.nodes[0]
    assert "usm-chart" in node
    assert "usm-bg" in node and "usm-stage" in node and "usm-region" in node
    assert "usm-wipe" in node and "usm-legend" in node and "usm-lab" in node
    assert "Population Density" in node
    assert "Low" in node and "High" in node
    assert "Census Bureau" in node
    assert "CA" in node and "NY" in node and "TX" in node and "FL" in node
    assert "NJ" in node and "AK" in node and "HI" in node
    assert "#1e3a5f" in node or "#2563eb" in node or "#ec4899" in node
    assert "dv-bar" not in node
    assert "dv-donut" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "cst-" not in node
    assert "cpr-" not in node
    assert "dcl-" not in node
    assert "mlg-" not in node
    assert "spm-" not in node
    assert "srf-" not in node
    assert "umf-" not in node
    assert "umh-" not in node
    assert "wmp-" not in node
    assert "stat-card" not in node
    assert "jsdelivr" not in node
    assert "topojson" not in node
    assert "textContent" not in node
    assert "clipPath" not in node
    assert "clip-path" not in node
    assert node.count(f'id="usm-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    assert f'id="usm-{ctx.index:02d}-stage"' in node
    assert f'id="usm-{ctx.index:02d}-wipe"' in node
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scaleX:1" in body and "scaleX:0" in body
    assert "back.out(1.4)" in body
    assert "immediateRender:false" in body
    assert "filter" not in body
    assert "clipPath" not in body
    assert "strokeWidth" not in body
    assert "textContent" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#usm-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _usm_times(12.0)
    assert abs(times["hl_dur"] - 1.0) < 1e-9
    assert abs(times["reg_at"] - 1.0) < 1e-9
    assert abs(times["lab_at"] - 3.5) < 1e-9
    assert abs(times["leg_at"] - 5.0) < 1e-9
    assert abs(times["hi_at"] - 6.5) < 1e-9
    assert abs(times["out_start"] - 11.5) < 1e-9
    short = _usm_times(0.22)
    assert short["out_start"] + 0.001 <= 0.22 + 1e-9


def test_us_map_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".usm-chart" in css
    assert ".usm-region" in css
    chart = re.search(r"\.usm-chart\{[^}]+\}", css).group(0)
    bg = re.search(r"\.usm-bg\{[^}]+\}", css).group(0)
    hl = re.search(r"\.usm-hl\{[^}]+\}", css).group(0)
    wipe = re.search(r"\.usm-wipe\{[^}]+\}", css).group(0)
    bar = re.search(r"\.usm-legend-bar\{[^}]+\}", css).group(0)
    region = re.search(r"\.usm-region\{[^}]+\}", css).group(0)
    assert "#0f172a" in chart and "#0f172a" in bg
    assert "#1e293b" in bg
    assert "#f8fafc" in hl
    assert "#1e3a5f" in bar and "#2563eb" in bar
    assert "#7c3aed" in bar and "#ec4899" in bar
    assert "transform-origin:100% 50%" in wipe
    assert "transform-origin:50% 50%" in region
    assert "transform-box:fill-box" in region
    block = css.split(".usm-chart", 1)[1].split(".umf-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    stripped = (css.replace("transform-origin:left center", "")
                .replace("transform-origin:50% 50%", "")
                .replace("transform-origin:50% 100%", "")
                .replace("transform-origin:0px 50%", "")
                .replace("transform-origin:100% 50%", "")
                .replace("transform-box:fill-box", "")
                .replace("transform-box:view-box", "")
                .replace("text-transform:uppercase", ""))
    assert "transform:" not in stripped.split(".usm-chart", 1)[1].split(".umf-chart", 1)[0]
    dv_bar = re.search(r"\.dv-bar\{[^}]+\}", css).group(0)
    assert "usm-" not in dv_bar
    donut = re.search(r"\.dv-donut\{[^}]+\}", css).group(0)
    assert "usm-" not in donut
    spm = re.search(r"\.spm-region\{[^}]+\}", css).group(0)
    assert "usm-" not in spm
    srf = re.search(r"\.srf-wipe\{[^}]+\}", css).group(0)
    assert "usm-" not in srf


def test_us_map_flow_bakes_paths_not_fetch(ctx):
    """Каталог DEMO 1 тянет topojson и твинит clipPath/dash/onUpdate; здесь scale и x/y."""
    piece = render_dataviz("data-viz/us-map-flow", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=12.0, target=ctx.target,
        track=6, params={
            "title": "Interstate Flow Connections",
            "subtitle": "Relative volume of major city-to-city corridors",
            "source": "Source: Illustrative data",
        }))
    node = piece.nodes[0]
    assert "umf-chart" in node
    assert "umf-bg" in node and "umf-stage" in node and "umf-region" in node
    assert "umf-wipe" in node and "umf-arc" in node and "umf-city" in node
    assert "umf-tdot" in node and "umf-lab" in node
    assert "Interstate Flow" in node
    assert "city-to-city" in node
    assert "Illustrative data" in node
    assert "San Francisco" in node and "New York" in node and "Miami" in node
    assert "Chicago" in node and "Dallas" in node
    assert node.count('class="umf-region"') == 50
    assert node.count('class="umf-arc"') == 12
    assert node.count('class="umf-city"') == 12
    assert node.count("umf-tdot") == 12
    assert "0 0 1920 1080" in node
    assert "dv-bar" not in node
    assert "dv-donut" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "cst-" not in node
    assert "cpr-" not in node
    assert "dcl-" not in node
    assert "mlg-" not in node
    assert "spm-" not in node
    assert "srf-" not in node
    assert "usm-" not in node
    assert "umh-" not in node
    assert "wmp-" not in node
    assert "stat-card" not in node
    assert "jsdelivr" not in node
    assert "topojson" not in node
    assert "textContent" not in node
    assert "clipPath" not in node
    assert "clip-path" not in node
    assert "strokeDashoffset" not in node
    assert "stroke-dashoffset" not in node
    assert "getPointAtLength" not in node
    assert "onUpdate" not in node
    assert "filter" not in node
    assert node.count(f'id="umf-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    assert f'id="umf-{ctx.index:02d}-stage"' in node
    assert f'id="umf-{ctx.index:02d}-wipe"' in node
    assert f'id="umf-{ctx.index:02d}-hl"' in node
    assert f'id="umf-{ctx.index:02d}-sub"' in node
    assert f'id="umf-{ctx.index:02d}-src"' in node
    assert f'id="umf-{ctx.index:02d}-r0"' in node
    assert f'id="umf-{ctx.index:02d}-c0"' in node
    assert f'id="umf-{ctx.index:02d}-l0"' in node
    assert f'id="umf-{ctx.index:02d}-a0"' in node
    assert f'id="umf-{ctx.index:02d}-d0"' in node
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scaleX:1" in body and "scaleX:0" in body
    assert "back.out(1.7)" in body
    assert "immediateRender:false" in body
    assert "filter" not in body
    assert "clipPath" not in body
    assert "clip-path" not in body
    assert "strokeDashoffset" not in body
    assert "onUpdate" not in body
    assert "getPointAtLength" not in body
    assert "strokeWidth" not in body
    assert "textContent" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#umf-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _umf_times(12.0)
    assert abs(times["hl_dur"] - 1.0) < 1e-9
    assert abs(times["sub_at"] - 0.3) < 1e-9
    assert abs(times["st_at"] - 0.6) < 1e-9
    assert abs(times["dot_at"] - 1.5) < 1e-9
    assert abs(times["lab_at"] - 2.5) < 1e-9
    assert abs(times["arc_at"] - 3.5) < 1e-9
    assert abs(times["td_at"] - 7.0) < 1e-9
    assert abs(times["src_at"] - 9.0) < 1e-9
    short = _umf_times(0.22)
    assert short["kill_at"] <= 0.22 + 1e-9
    assert short["src_at"] + short["src_dur"] <= short["kill_at"] + 1e-9


def test_us_map_flow_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".umf-chart" in css
    assert ".umf-arc" in css
    assert ".umf-city" in css
    chart = re.search(r"\.umf-chart\{[^}]+\}", css).group(0)
    bg = re.search(r"\.umf-bg\{[^}]+\}", css).group(0)
    hl = re.search(r"\.umf-hl\{[^}]+\}", css).group(0)
    wipe = re.search(r"\.umf-wipe\{[^}]+\}", css).group(0)
    region = re.search(r"\.umf-region\{[^}]+\}", css).group(0)
    arc = re.search(r"\.umf-arc\{[^}]+\}", css).group(0)
    city = re.search(r"\.umf-city\{[^}]+\}", css).group(0)
    tdot = re.search(r"\.umf-tdot\{[^}]+\}", css).group(0)
    lab = re.search(r"\.umf-lab\{[^}]+\}", css).group(0)
    assert "#0f172a" in chart and "#0f172a" in bg
    assert "#1e293b" in bg
    assert "#f8fafc" in hl
    assert "#1e293b" in region and "#334155" in region
    assert "#3b82f6" in arc
    assert "#ffffff" in city
    assert "#60a5fa" in tdot
    assert "#cbd5e1" in lab
    assert "transform-origin:100% 50%" in wipe
    assert "transform-origin:50% 50%" in city
    assert "transform-box:fill-box" in city
    assert "transform-box:view-box" in arc
    block = css.split(".umf-chart", 1)[1].split(".wmp-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    stripped = (block.replace("transform-origin:left center", "")
                .replace("transform-origin:50% 50%", "")
                .replace("transform-origin:50% 100%", "")
                .replace("transform-origin:0px 50%", "")
                .replace("transform-origin:100% 50%", "")
                .replace("transform-box:fill-box", "")
                .replace("transform-box:view-box", "")
                .replace("text-transform:uppercase", ""))
    assert "transform:" not in stripped
    dv_bar = re.search(r"\.dv-bar\{[^}]+\}", css).group(0)
    assert "umf-" not in dv_bar
    donut = re.search(r"\.dv-donut\{[^}]+\}", css).group(0)
    assert "umf-" not in donut
    spm = re.search(r"\.spm-region\{[^}]+\}", css).group(0)
    assert "umf-" not in spm
    srf = re.search(r"\.srf-wipe\{[^}]+\}", css).group(0)
    assert "umf-" not in srf
    usm = re.search(r"\.usm-region\{[^}]+\}", css).group(0)
    assert "umf-" not in usm


def test_us_map_hex_bakes_hexes_not_fetch(ctx):
    """Catalog computes hex geometry in JS; here hexes are pre-baked."""
    piece = render_dataviz("data-viz/us-map-hex", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=10.0, target=ctx.target,
        track=6, params={
            "title": "Median Household Income by State",
            "subtitle": "American Community Survey, 2024",
            "source": "Source: U.S. Census Bureau",
            "highlight": ["MD", "NJ", "MA", "CT", "HI"],
        }))
    node = piece.nodes[0]
    assert "umh-chart" in node
    assert "umh-bg" in node and "umh-stage" in node and "umh-poly" in node
    assert "umh-wipe" in node and "umh-text" in node
    assert "Median Household" in node
    assert "Census Bureau" in node
    assert node.count('class="umh-poly"') == 51
    assert node.count('class="umh-hi"') == 5
    assert "dv-bar" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "usm-" not in node
    assert "umf-" not in node
    assert "spm-" not in node
    assert "srf-" not in node
    assert "wmp-" not in node
    assert "stat-card" not in node
    assert "jsdelivr" not in node
    assert "topojson" not in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    assert node.count(f'id="umh-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert "scaleX:1" in body and "scaleX:0" in body
    assert "back.out(1.4)" in body
    assert "immediateRender:false" in body
    assert "filter" not in body
    assert "clipPath" not in body
    assert "brightness" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#umh-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")


def test_us_map_hex_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".umh-chart" in css
    assert ".umh-poly" in css
    assert ".umh-text" in css
    chart = re.search(r"\.umh-chart\{[^}]+\}", css).group(0)
    bg = re.search(r"\.umh-bg\{[^}]+\}", css).group(0)
    poly = re.search(r"\.umh-poly\{[^}]+\}", css).group(0)
    legend_bar = re.search(r"\.umh-legend-bar\{[^}]+\}", css).group(0)
    assert "#0f172a" in chart and "#0f172a" in bg
    assert "#1e293b" in bg
    assert "#0f172a" in poly
    assert "#451a03" in legend_bar and "#f59e0b" in legend_bar and "#fef3c7" in legend_bar
    block = css.split(".umh-chart", 1)[1].split(".wmp-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block


def test_world_map_bakes_paths_not_fetch(ctx):
    """Catalog fetches world-atlas and tweens clipPath/filter; here baked paths."""
    piece = render_dataviz("data-viz/world-map", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=14.0, target=ctx.target,
        track=6, params={
            "title": "Global GDP per Capita",
            "subtitle": "Nominal GDP per capita, 2024 IMF estimates",
            "source": "Source: International Monetary Fund",
            "highlight": ["756", "578", "840", "036", "752"],
        }))
    node = piece.nodes[0]
    assert "wmp-chart" in node
    assert "wmp-bg" in node and "wmp-stage" in node and "wmp-region" in node
    assert "wmp-wipe" in node and "wmp-grat" in node
    assert "Global GDP" in node
    assert "International Monetary Fund" in node
    assert node.count('class="wmp-region"') == 177
    assert node.count('class="wmp-hi"') == 5
    assert "dv-bar" not in node
    assert "abc-" not in node
    assert "usm-" not in node
    assert "umf-" not in node
    assert "umh-" not in node
    assert "spm-" not in node
    assert "stat-card" not in node
    assert "jsdelivr" not in node
    assert "topojson" not in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    assert node.count(f'id="wmp-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert "scaleX:1" in body and "scaleX:0" in body
    assert "power1.out" in body
    assert "immediateRender:false" in body
    assert "filter" not in body
    assert "clipPath" not in body
    assert "brightness" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#wmp-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _wmp_times(14.0)
    assert abs(times["hl_dur"] - 1.0) < 1e-9
    assert abs(times["sub_at"] - 0.4) < 1e-9
    assert abs(times["reg_at"] - 1.0) < 1e-9
    assert abs(times["leg_at"] - 4.0) < 1e-9
    assert abs(times["src_at"] - 4.5) < 1e-9
    assert abs(times["hi_at"] - 5.0) < 1e-9


def test_world_map_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".wmp-chart" in css
    assert ".wmp-region" in css
    assert ".wmp-grat" in css
    chart = re.search(r"\.wmp-chart\{[^}]+\}", css).group(0)
    bg = re.search(r"\.wmp-bg\{[^}]+\}", css).group(0)
    legend_bar = re.search(r"\.wmp-legend-bar\{[^}]+\}", css).group(0)
    assert "#0f172a" in chart and "#0f172a" in bg
    assert "#1e293b" in bg
    assert "#064e3b" in legend_bar and "#0d9488" in legend_bar
    assert "#22d3ee" in legend_bar and "#f0fdfa" in legend_bar
    block = css.split(".wmp-chart", 1)[1].split(".amc-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block


def test_apple_money_count_bakes_spans_not_textcontent(ctx):
    """Catalog writes textContent and tweens filter; here spans and opacity."""
    piece = render_dataviz("data-viz/apple-money-count", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=5.0, target=ctx.target,
        track=6, params={"end_value": 10000, "prefix": "$"}))
    node = piece.nodes[0]
    assert "amc-chart" in node
    assert "amc-stage" in node and "amc-flash" in node and "amc-hit" in node
    assert "$10,000" in node
    assert "$0" in node
    assert node.count('class="amc-icon') == 62
    assert "textContent" not in node
    assert "onUpdate" not in node
    assert "clip-path" not in node
    assert "filter:" not in "".join(piece.tweens)
    assert "textContent" not in "".join(piece.tweens)
    assert "strokeDashoffset" not in "".join(piece.tweens)
    body = " ".join(piece.tweens)
    assert "opacity:1" in body and "opacity:0" in body
    assert "power4.out" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#amc-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _amc_times(5.0)
    assert abs(times["hit"] - 3.16) < 1e-9
    assert abs(times["burst_at"] - 3.28) < 1e-9


def test_apple_money_count_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".amc-chart" in css
    assert ".amc-icon.bill" in css
    assert ".amc-icon.coin" in css
    chart = re.search(r"\.amc-chart\{[^}]+\}", css).group(0)
    flash = re.search(r"\.amc-flash\{[^}]+\}", css).group(0)
    hit = re.search(r"\.amc-hit\{[^}]+\}", css).group(0)
    assert "#fdfefe" in chart
    assert "#111315" in chart
    assert "#30d158" in flash and "#30d158" in hit
    assert "#ffd54f" in css
    block = css.split(".amc-chart", 1)[1].split(".nkl-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block


def test_north_korea_locked_down_bakes_mask_not_dash(ctx):
    """Catalog tweens filter/strokeDashoffset; here scale/x/y and SVG-mask."""
    piece = render_dataviz("data-viz/north-korea-locked-down", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=7.0, target=ctx.target,
        track=6, params={"label": "LOCKED DOWN"}))
    node = piece.nodes[0]
    assert "nkl-chart" in node
    assert "nkl-cam" in node and "nkl-ann" in node and "nkl-lab" in node
    assert "LOCKED" in node and "DOWN" in node
    assert "nkl-circ" in node and "nkl-wipe" in node
    assert "nkl-nk" in node
    assert node.count('class="nkl-land"') >= 3
    assert "korea-map.png" not in node
    assert "textContent" not in node
    assert "strokeDashoffset" not in node
    assert "clip-path" not in node
    assert "filter:" not in "".join(piece.tweens)
    assert "strokeDashoffset" not in "".join(piece.tweens)
    assert "textContent" not in "".join(piece.tweens)
    body = " ".join(piece.tweens)
    assert "scaleX:1" in body and "scaleX:0" in body
    assert "expo.inOut" in body
    assert "back.out(2.1)" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#nkl-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _nkl_times(7.0)
    assert abs(times["cam2_at"] - 3.18) < 1e-9
    assert abs(times["circ_a_at"] - 3.24) < 1e-9
    assert abs(times["label_at"] - 3.78) < 1e-9


def test_north_korea_locked_down_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".nkl-chart" in css
    assert ".nkl-circ-a" in css
    assert ".nkl-nk" in css
    chart = re.search(r"\.nkl-chart\{[^}]+\}", css).group(0)
    circ = re.search(r"\.nkl-circ-a\{[^}]+\}", css).group(0)
    lab = re.search(r"\.nkl-lab\{[^}]+\}", css).group(0)
    assert "#eef3f4" in chart
    assert "#151515" in chart
    assert "#e21d2f" in circ
    assert "#111111" in lab
    assert "#ff3b30" in css
    block = css.split(".nkl-chart", 1)[1].split(".npf-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block


def test_nyc_paris_flight_bakes_path_not_offset(ctx):
    """Catalog tweens offsetDistance/strokeDashoffset; here x/y and SVG-mask."""
    piece = render_dataviz("data-viz/nyc-paris-flight", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=6.0, target=ctx.target,
        track=6, params={
            "origin": "New York", "dest": "Paris",
            "origin_code": "JFK / NYC", "dest_code": "CDG / FR",
            "km": "5,837",
        }))
    node = piece.nodes[0]
    assert "npf-chart" in node
    assert "npf-plane" in node and "npf-pin" in node and "npf-line" in node
    assert "New York" in node and "Paris" in node
    assert "ARRIVED" in node
    assert "5,837" in node
    assert "map-nyc-paris.png" not in node
    assert "offsetDistance" not in node
    assert "offset-path" not in node
    assert "strokeDashoffset" not in node
    assert "textContent" not in node
    body = " ".join(piece.tweens)
    assert "scaleX:1" in body and "scaleX:0" in body
    assert "offsetDistance" not in body
    assert "strokeDashoffset" not in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#npf-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _npf_times(6.0)
    assert abs(times["fly_at"] - 1.17) < 1e-9
    assert abs(times["white_at"] - 5.5) < 1e-9


def test_nyc_paris_flight_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".npf-chart" in css
    assert ".npf-plane" in css
    assert ".npf-line" in css
    chart = re.search(r"\.npf-chart\{[^}]+\}", css).group(0)
    line = re.search(r"\.npf-line\{[^}]+\}", css).group(0)
    badge = re.search(r"\.npf-badge\{[^}]+\}", css).group(0)
    assert "#f5f5f7" in chart
    assert "#1d1d1f" in chart
    assert "#0071e3" in line
    assert "#d70015" in badge
    block = css.split(".npf-chart", 1)[1].split(".mps-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block


def test_mk_progress_stat_bakes_spans_not_textcontent(ctx):
    """Catalog writes textContent; here spans, track scaleX."""
    piece = render_dataviz("data-viz/mk-progress-stat", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=7.0, target=ctx.target,
        track=6, params={
            "value": 22, "max": 30, "label": "Goals reached",
            "caption": "Great job, we are getting closer!",
        }))
    node = piece.nodes[0]
    assert "mps-chart" in node
    assert "mps-fill" in node and "mps-num" in node
    assert "Goals reached" in node
    assert "22" in node
    assert "textContent" not in node
    assert "visibility" not in "".join(piece.tweens)
    assert "textContent" not in "".join(piece.tweens)
    body = " ".join(piece.tweens)
    assert "scaleX:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#mps-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _mps_times(7.0)
    assert abs(times["count_at"] - 0.5) < 1e-9


def test_mk_progress_stat_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".mps-chart" in css
    assert ".mps-fill" in css
    chart = re.search(r"\.mps-chart\{[^}]+\}", css).group(0)
    fill = re.search(r"\.mps-fill\{[^}]+\}", css).group(0)
    assert "#f5f5f7" in chart
    assert "#1d1d1f" in chart
    assert "#0071e3" in fill
    block = css.split(".mps-chart", 1)[1]
    assert "Inter" in block
    assert "-apple-system" not in block


def test_flowchart_vertical_bakes_spans_not_textcontent(ctx):
    """Catalog writes textContent; here pre-baked spans, SVG-mask."""
    piece = render_dataviz("data-viz/flowchart-vertical", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=12.0, target=ctx.target,
        track=6, params={
            "root": "Should I learn to code?",
            "branches": ["Yes", "Not sure"],
            "leaves": [
                "Start with Python", "Try no-code first",
                "Build a personal website", "Take a free intro course",
            ],
        }))
    node = piece.nodes[0]
    assert "fcv-chart" in node
    assert "Should I learn to code?" in node
    assert "Start with Python" in node
    assert "Pythom" in node
    assert "textContent" not in node
    assert "filter:" not in "".join(piece.tweens)
    assert "strokeDashoffset" not in "".join(piece.tweens)
    assert "textContent" not in "".join(piece.tweens)
    body = " ".join(piece.tweens)
    assert "scale:" in body or "scaleY:" in body
    assert "opacity:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#fcv-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _fcv_times(12.0)
    assert abs(times["root_at"] - 0.2) < 1e-9


def test_flowchart_vertical_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".fcv-chart" in css
    assert ".fcv-node" in css
    assert "#e8d44d" in css
    assert "#c2e8a0" in css
    assert "#f5c5a3" in css
    assert "#d4c5f9" in css
    assert "#9747ff" in css
    assert "#0b84f3" in css
    block = css.split(".fcv-chart", 1)[1]
    assert "Inter" in block
    assert "-apple-system" not in block


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


@pytest.mark.parametrize("name", sorted(TRANSITIONS))
def test_fade_to_nothing_is_followed_by_a_hard_kill(name, ctx):
    """Затухание в ноль обязано заканчиваться tl.set на том же селекторе.

    Перемотка назад через уже отыгранный твин возвращает элемент в начальное
    состояние: полоса, которая должна была исчезнуть, остаётся в кадре. Кадр по
    перемотке обязан совпадать с кадром по проигрыванию, и lint движка держит
    это правилом gsap_exit_missing_hard_kill. На живом прогоне 0047 оно
    остановило рендер по всем четырём полосам перехода tr-19.
    """
    piece = render_transition(name, ctx)
    kills = {re.search(r'"([^"]+)"', t).group(1)
             for t in piece.tweens if t.startswith("tl.set(")}
    for tween in piece.tweens:
        if tween.startswith("tl.set("):
            continue
        to_state = re.findall(r"\{[^{}]*\}", tween)[-1]
        if not re.search(r"opacity:0(?![.\d])", to_state):
            continue
        target = re.search(r'"([^"]+)"', tween).group(1)
        assert target in kills, f"{name}: затухание без гашения — {tween}"


# --- приёмы вокруг ведущего ---------------------------------------------------
#
# Референсы заказчика: ведущий за столом, а кадр вокруг него живёт. Проверяется
# то, что уже ломалось в реальном рендере, а не то, что легко проверить.

HERO_PARAMS = {
    "hero-icons": {"icons": [{"glyph": "chip"}, {"glyph": "atom"},
                             {"glyph": "clock"}],
                   "face_cx": 579, "face_cy": 579, "head_half": 207},
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
    "hero-script-stack": {"lines": ["если ты", "зайдёшь", "за горизонт"]},
    "hero-chat-typing": {"ask": "что будет за горизонтом событий",
                         "answer": "тело растянет в нить",
                         "app": "ChatGPT"},
    "hero-chat-generate": {"gen_prompt": "нарисуй горизонт событий вблизи",
                           "app": "ChatGPT", "src": "assets/m000_shot.mp4"},
    "hero-title-behind": {"head": "Наполеон", "tail": "проиграл машине"},
    "hero-exhibit": {"title": "Наполеон Бонапарт", "detail": "партия с турком, 1809",
                     "credit": "NASA · public domain", "src": "assets/m000_shot.mp4"},
    "hero-slam": {"punch": ["Ты сам", "не разгадал"]},
    "hero-log": {"entries": [{"text": "не по правилам,", "at": 0.0},
                             {"text": "турок вернул фигуру", "at": 0.9},
                             {"text": "сходил ещё раз,", "at": 1.8}]},
    "hero-oversize": {"word": "за фокус"},
    "hero-figure": {"figures": [{"value": "$902 626 748", "note": "получает Google"},
                                {"value": "$18 530 611", "note": "получает Google"},
                                {"value": "$0", "note": "получает Google"}]},
    "hero-verdict": {"punch": ["Себе", "ноль"]},
    "hero-bubble-typed": {"entries": [{"text": "ни одна компания", "at": 0.0},
                                      {"text": "не платит гуглу", "at": 0.9},
                                      {"text": "ни рубля", "at": 1.8}]},
    "hero-paper": {"source": "arxiv.org",
                   "quote": "maximizing survival time below the event horizon"},
}


def _clip_ids(nodes: list[str]) -> list[str]:
    """Идентификаторы клипов разметки — клипом может быть и <video>, и <div>."""
    return re.findall(r'<\w+ id="([^"]+)"[^>]*class="clip', " ".join(nodes))


def _css_rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    return match.group(1) if match else ""


def _css_rules_under(css: str, selector: str) -> list[tuple[str, str]]:
    """Правила для потомков селектора: ``.hero-icons .hi-mark``, ``.hero-plate .hp-in``."""
    pattern = re.escape(selector) + r"(?:\s|>)+([^{,]+)\{([^}]*)\}"
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(pattern, css)]


def _hero_ctx(name, **over):
    params = {**HERO_PARAMS[name], **over.pop("params", {})}
    base = dict(index=3, start=4.5, duration=2.0, target="avatar-01",
                track=13, params=params)
    base.update(over)
    return TemplateCtx(**base)


def test_script_stack_fits_the_widest_line_not_the_longest():
    """Кегль подбирается по ширине строки, а не по числу знаков.

    «ГАЗ ИЛИ ПАДАЛ» и «МОЛЧА? НАПИШИ» — по 13 знаков, но вторая шире на 11 %:
    подбор по длине обрезал её краем кадра. Обводка тоже входит в бюджет — она
    рисуется наружу от глифа.
    """
    lines = ["Ты бы жал на", "газ или падал", "молча? Напиши"]
    piece = render_hero("hero-script-stack",
                        _hero_ctx("hero-script-stack", params={"lines": lines}))
    size = int(re.search(r"font-size:(\d+)px", piece.nodes[0]).group(1))
    for line in lines:
        drawn = text_width(line.upper(), size) + 2 * SS_STROKE
        assert drawn <= 1080 - 2 * 90 + 1e-6, (line, drawn)


def test_split_column_fits_the_panel_on_any_word():
    """Столбец сплита обязан уложиться в панель и по ширине, и по высоте.

    По одной букве в строке «ЕДИНСТВЕННЫЙ» уходил кеглем за нижний край
    панели. Раскладка теперь выбирается измерением, и проверять надо оба
    поля: короткое слово не должно потерять крупный кегль, длинное — вылезти.
    """
    from src.lib.render.hyperframes.templates import (
        SPLIT_BOX, split_rows, widest)

    box_w, box_h = SPLIT_BOX
    for word in ("НЕТ", "НИЧЕГО", "ВНИМАНИЕ", "ЕДИНСТВЕННЫЙ", "НЕВОЗВРАТА"):
        rows, size = split_rows(word)
        assert "".join(rows) == word, (word, rows)
        assert text_width(widest(rows), size) <= box_w + 1e-6, (word, rows, size)
        assert len(rows) * size * 0.86 <= box_h + 1e-6, (word, rows, size)
        # Короткое слово получает и лучшую раскладку, и полный кегль.
        if len(word) <= 6:
            assert rows == list(word) and size == 172, (word, rows, size)


def test_behind_head_devices_sit_on_the_measured_crown():
    """Строка за головой садится по макушке, а не по числу из пресета.

    Голова обязана перекрывать только низ последней строки. На новом аватаре
    константа пресета пришлась слову ровно поперёк: «НЕЧЕМ» читалось как
    «НЕ⋯ЕМ» — голова закрыла середину. Проверяется само правило: где бы ни
    оказалась макушка, перекрытие остаётся долей высоты знака.
    """
    from src.lib.render.hyperframes.templates import BEHIND_HEAD_BITE

    for head_top in (300, 372, 520):
        params = {"word": "НЕЧЕМ", "kicker": "ВОПРОС", "head_top": head_top}
        node = render_hero("hero-headline",
                           _hero_ctx("hero-headline", params=params)).nodes[0]
        top = int(re.search(r'class="clip hero-headline" style="top:(\d+)px', node).group(1))
        size = int(re.search(r"font-size:(\d+)px", node).group(1))
        cap = size * 0.72
        # Низ прописных — вот сколько от них съедает голова.
        bite = (top + cap) - head_top
        assert abs(bite - cap * BEHIND_HEAD_BITE) <= 1.5, (head_top, top, bite)

    # Без измерения остаётся число пресета: догадка хуже, но лучше пустоты.
    plain = render_hero("hero-headline",
                        _hero_ctx("hero-headline",
                                  params={"word": "НЕЧЕМ", "top": 190})).nodes[0]
    assert 'style="top:190px' in plain


def test_log_marks_the_accent_word_and_never_shows_a_bare_dash():
    """Список копится чёрным, и одно слово в нём горит — акцентное.

    Заодно проверяется, чем список не имеет права быть: куском из одной
    пунктуации («—» отдельной строкой) и оборванным на предлоге хвостом.
    Тире закрывает кусок так же, как запятая, поэтому отдельным словом оно
    давало кусок из себя одного.
    """
    from src.p11_assemble.assemble import _hero_content, hero_params

    block = {"id": "b5", "emphasis_word": "выбрать",
             "text": "Выжить внутри нельзя. Можно только выбрать, "
                     "сколько ты продержишься, — и лучшая стратегия на"}
    spoken = [{"display": w, "start": 0.4 * i, "end": 0.4 * i + 0.35,
               "block_id": "b5"}
              for i, w in enumerate(block["text"].split())]
    slot = {"role": "turn", "start": 0.0, "end": 8.0}
    content = _hero_content(block, slot, None, words=spoken)
    entries = content["entries"]
    assert all(any(ch.isalnum() for ch in e["text"]) for e in entries), entries
    assert not entries[-1]["text"].endswith(" на"), entries[-1]

    params = hero_params("hero-log", {}, content, slot)
    node = render_hero("hero-log", _hero_ctx("hero-log", params=params)).nodes[0]
    assert '<b class="lg-hit">ВЫБРАТЬ,</b>' in node, node


def test_typed_card_is_centred_by_position_and_accents_its_last_chunk():
    """Карточка набирается кусками, последний приходит акцентом.

    Центровка — позицией, а не ``translateX``: вход тянет ``transform``
    целиком, и первый же твин стёр бы сдвиг на половину ширины — карточка
    уехала бы вправо на весь ролик.
    """
    from src.lib.render.hyperframes.templates import BT_CARD_W

    piece = render_hero("hero-bubble-typed", _hero_ctx("hero-bubble-typed"))
    node = piece.nodes[0]
    assert node.count('class="bt-chunk') == 3
    assert 'class="bt-chunk last"' in node
    assert f'left:{(1080 - BT_CARD_W) // 2}px' in node
    # Каждый кусок приходит на своей отметке, а не через ровный шаг.
    starts = sorted(float(m) for m in re.findall(
        r'\.bt-chunk:nth-child\(\d+\)"[^;]*?,([\d.]+)\);', " ".join(piece.tweens)))
    assert len(starts) == 3 and len(set(starts)) == 3, starts
    assert starts == sorted(starts) and starts[-1] > starts[0], starts


def test_source_page_shows_only_what_the_script_really_cites():
    """Страница первоисточника не досочиняет ни домена, ни текста статьи.

    Домен берётся из ссылки блока как есть; цитата — из ``overlay.highlight``.
    Без ссылки приёма нет вовсе: страница без домена — не источник.
    """
    from src.p11_assemble.assemble import _hero_content, hero_params

    block = {"id": "b3", "emphasis_word": "порог",
             "text": "Ошибки упали ниже порога коррекции.",
             "source_ref": "https://www.nature.com/articles/s41586-024-08449-y",
             "overlay": {"type": "highlight",
                         "content": "below the surface code threshold"}}
    slot = {"role": "develop", "start": 0.0, "end": 5.0}
    content = _hero_content(block, slot, None, (540, 700), title="Квантовый чип")
    params = hero_params("hero-paper", {}, content, slot)
    assert params["source"] == "nature.com"
    assert params["quote"] == "below the surface code threshold"

    node = render_hero("hero-paper", _hero_ctx("hero-paper", params=params)).nodes[0]
    assert "nature.com" in node
    # Цитата разложена по строкам, поэтому целиком её в разметке нет — но ни
    # одно слово потеряться не имеет права: обрывок цитаты уже не цитата.
    for word in params["quote"].split():
        assert word in node, word
    # В разметке страницы нет ни одного слова реплики: тело набрано полосами.
    assert "коррекции" not in node

    # Без ссылки на источник приём не собирается. Контекст здесь строится
    # напрямую: `_hero_ctx` подмешал бы домен из набора по умолчанию.
    bare = dict(block); bare.pop("source_ref")
    empty = hero_params("hero-paper", {}, _hero_content(bare, slot, None), slot)
    assert not empty.get("source")
    ctx = TemplateCtx(index=3, start=4.5, duration=2.0, target="avatar-01",
                      track=13, params=empty)
    assert not render_hero("hero-paper", ctx).nodes


def test_every_css_variable_is_defined():
    """Опечатка в имени переменной не падает — она красит текст в чёрное.

    Брендбук отдаёт цвета как ``--color-ink``; ``var(--ink)`` браузер считает
    невалидным и берёт унаследованное значение. Так три приёма разом потеряли
    и обводку, и акцент, и цвет пузыря — молча, в живом ролике. Здесь список
    имён проверяется целиком, а не по одному приёму.
    """
    from src.lib.config import load_config
    from src.lib.render.hyperframes.brand_css import build_css

    css = build_css(load_config().brandbook, fonts={})
    root = re.search(r":root\{(.*?)\}", css, re.S)
    assert root, "в таблице стилей нет блока :root с переменными брендбука"
    defined = {m.group(1) for m in re.finditer(r"(--[\w-]+)\s*:", root.group(1))}
    used = {m.group(1) for m in re.finditer(r"var\((--[\w-]+)", css)}
    # Эти две ставит сам шаблон в атрибуте style каждого луча.
    inline = {"--a", "--len"}
    assert not (used - defined - inline), sorted(used - defined - inline)


def test_every_hero_gets_its_content_from_the_pipeline():
    """Приём, выбранный конвейером, обязан получить и содержимое.

    Пропуск в отображении не падает и не пишет в лог: рендерер возвращает
    пустой ``Piece``, и приёма в кадре просто нет. Проверяется именно связка
    «что конвейер кладёт в params» ↔ «что рендерер оттуда читает».
    """
    from src.p11_assemble.assemble import _HERO_NEEDS, _hero_content, hero_params

    block = {"id": "b1", "emphasis_word": "переживёшь",
             # В тексте есть число: приёму со сменой значений больше нечем
             # наполниться, и без него проверка его бы не задела.
             # Число — приёму со сменой значений, «минут» и «эксперимент» —
             # знакам за головой: одного знака им мало, это очередь.
             # Вопрос в конце — приёму с перепиской: окно поиска ставится
             # только там, где блок и правда спрашивает.
             "text": "Падение в чёрную дыру ты переживёшь. Это и есть "
                     "худшая часть: 12 минут собственного времени, "
                     "и ни один эксперимент этого не проверит. "
                     "Сколько бы выдержал ты?",
             # Ссылка на источник и помеченная цитата: без них страница
             # первоисточника не собирается, и это её правило, а не пропуск.
             "source_ref": "arxiv.org",
             "overlay": {"type": "highlight",
                         "content": "maximizing survival time below the "
                                    "event horizon"}}
    # Тайминги слов конвейер отдаёт всегда: на них держится «список копится».
    spoken = [{"display": w, "start": 0.4 * i, "end": 0.4 * i + 0.35,
               "block_id": "b1"}
              for i, w in enumerate(block["text"].split())]
    content = _hero_content(block, {"role": "hook", "start": 0.0, "end": 6.0}, None,
                            (540, 700), title="Можно ли выжить внутри чёрной дыры",
                            words=spoken)
    content["brand"] = {"label": "Google", "icon": "assets/icons/google.png"}

    # Окно генерации включается предметом реплики, а не её длиной, и на блоке
    # про чёрную дыру оно обязано молчать. Значит, содержимое ему надо брать с
    # блока про генерацию — иначе проверка требовала бы от приёма ровно того,
    # чего он делать не должен.
    gen_block = {"id": "b2", "role": "develop", "emphasis_word": "четыре",
                 "text": "Нейросеть рисует такой кадр за четыре секунды, "
                         "и отличить его от съёмки уже нельзя."}
    gen_content = _hero_content(gen_block, {"role": "develop", "start": 0.0, "end": 6.0},
                                None, (540, 700), title="Кадр, которого не было",
                                words=[{"display": w, "start": 0.4 * i,
                                        "end": 0.4 * i + 0.35, "block_id": "b2"}
                                       for i, w in enumerate(gen_block["text"].split())])

    for name in sorted(HERO):
        source = gen_content if "gen_prompt" in _HERO_NEEDS.get(name, ()) else content
        params = hero_params(name, {}, source, {"role": "hook"})
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


def test_icons_stay_inside_the_work_area_and_flash_in_turn():
    """Знаки не заезжают под колонку интерфейса и вспыхивают очередью.

    Дуга несимметрична намеренно: голова стоит правее середины кадра, а правое
    поле съедает колонка лайк/коммент/шер (§3.2). Знак, заехавший под неё, в
    ролике не читается — проверяется именно это, а не красота дуги.
    """
    from src.lib.render.hyperframes.templates import ICON_SIZE, SAFE_X

    piece = render_hero("hero-icons", _hero_ctx("hero-icons"))
    node = piece.nodes[0]
    places = [(int(x), int(y)) for x, y in
              re.findall(r"left:(-?\d+)px;top:(-?\d+)px", node)]
    assert len(places) == 3
    for x, _ in places:
        assert SAFE_X[0] <= x and x + ICON_SIZE <= SAFE_X[1], (x, places)

    # Каждый знак приходит и уходит, и приходит он не одновременно с соседом.
    ins = sorted(float(m) for m in re.findall(
        r'\.hi-mark:nth-child\(\d+\)",\{scale:[\d.]+,opacity:0\}[^;]*?\},([\d.]+)\)',
        " ".join(piece.tweens)))
    assert len(set(ins)) > 1, ins
    assert any("opacity:0" in t and "tl.to(" in t for t in piece.tweens)


def test_short_shot_gets_no_frozen_icon():
    """Шот короче одной вспышки не получает знака вовсе.

    Иначе знак замер бы в кадре с недоигранным входом: это не приём, а брак.
    """
    piece = render_hero("hero-icons", _hero_ctx("hero-icons", duration=0.3))
    assert not piece.nodes and not piece.tweens


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
    # Проверяется правило, а не число: числа словаря живут в самом словаре и
    # меняются, когда меняется вкус к движению.
    start = float(re.search(r"\{scale:([\d.]+)", enter).group(1))
    assert start < 1.0, f"панель обязана расти, а не отъезжать: {enter}"
    assert "ease:\"back" not in enter, f"отскок — это игрушка: {enter}"


def test_hero_headline_without_a_kicker_tweens_only_what_it_drew():
    """Твин по несобранной разметке молчит — и прячет опечатку в селекторе."""
    piece = render_hero("hero-headline", _hero_ctx("hero-headline",
                                                   params={"kicker": ""}))
    assert "hh-kicker" not in " ".join(piece.nodes + piece.tweens)
    assert any("hh-word" in t for t in piece.tweens)


def test_hero_knockout_does_not_flood_the_frame_with_accent():
    """§3.3.1 держит акцент в 10–12 % площади, а приём закрывает кадр целиком."""
    node = render_hero("hero-knockout", _hero_ctx("hero-knockout")).nodes[0]
    assert "var(--color-knockout)" in node
    assert "accent" not in node


def test_knockout_fill_turns_over_with_the_stage():
    """Буквы — дырки: тёмная заливка на тёмной сцене даёт чёрное по чёрному."""
    from src.lib.config import load_config
    from src.lib.render.hyperframes.brand_css import build_css

    css = build_css(load_config().brandbook, fonts={})
    base = [rule for rule in css.split("}") if "--color-knockout:" in rule]
    assert base, "цвет заливки выбивки не объявлен"
    dark = [rule for rule in base if ".stage-dark" in rule]
    assert dark, "на тёмной сцене заливка не переворачивается"
    assert "bg-light" in dark[0], dark[0]


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
    """С проявлением вход идёт из значения словаря, без — из зеркального.

    Число берётся из словаря, а не переписывается сюда: словарь и есть
    источник правды о том, откуда приходит элемент.
    """
    import re
    spec = float(ENTRANCES["zoom-in"]["scale"])
    tween = entrance_tweens("#inner", 0.0, name="zoom-in", fade=True)[0]
    assert float(re.search(r"\{scale:([\d.]+)", tween).group(1)) == spec

    # Без проявления вход обязан **расти**: уменьшение без проявления читается
    # как отъезд, а не как появление.
    plain = entrance_tweens("#inner", 0.0, name="zoom-in", fade=False)[0]
    assert float(re.search(r"\{scale:([\d.]+)", plain).group(1)) < 1.0


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


def test_generation_result_arrives_after_the_prompt_and_inside_the_window():
    """Результат — отдельный клип: у него своё начало, и оно позже промпта.

    Прозрачность клипу запрещена, поэтому «картинка появилась» делается не
    проявлением, а тем, что клипа до этого момента просто нет. И лечь он обязан
    в окно, а не рядом: рамка и медиа считаются одними числами (``CG_CARD``).
    """
    from src.lib.render.hyperframes.templates import CG_CARD, _cg_media_box

    ctx = _hero_ctx("hero-chat-generate", duration=6.0)
    piece = render_hero("hero-chat-generate", ctx)
    starts = {re.search(r'id="([^"]+)"', node).group(1):
              float(re.search(r'data-start="([\d.]+)"', node).group(1))
              for node in piece.nodes}
    chrome, media = f"cg-{ctx.index:02d}", f"cg-{ctx.index:02d}-m"
    assert starts[chrome] == pytest.approx(ctx.start)
    assert starts[media] > starts[chrome] + 0.6

    mx, my, mw, mh = _cg_media_box()
    left, top, width, height = CG_CARD
    assert left <= mx and mx + mw <= left + width
    assert top <= my and my + mh <= top + height
    node = next(n for n in piece.nodes if 'id="' + media + '"' in n)
    assert f"left:{mx}px" in node and f"top:{my}px" in node


def test_generation_result_never_outlives_its_shot():
    """Короткий кадр ужимает ожидание, а не выпускает клип за границу окна."""
    ctx = _hero_ctx("hero-chat-generate", duration=2.0)
    piece = render_hero("hero-chat-generate", ctx)
    media = next(n for n in piece.nodes if n.startswith("<video"))
    start = float(re.search(r'data-start="([\d.]+)"', media).group(1))
    dur = float(re.search(r'data-duration="([\d.]+)"', media).group(1))
    assert start >= ctx.start
    assert start + dur <= ctx.start + ctx.duration + 1e-6
    assert dur >= 0.4


def test_generation_result_is_capped_by_the_material_length():
    """Материал короче кадра укорачивает картинку, но не само окно."""
    ctx = _hero_ctx("hero-chat-generate", duration=6.0,
                    params={"media_sec": 0.9})
    piece = render_hero("hero-chat-generate", ctx)
    chrome = next(n for n in piece.nodes if n.startswith("<div"))
    media = next(n for n in piece.nodes if n.startswith("<video"))
    assert float(re.search(r'data-duration="([\d.]+)"', chrome).group(1)) == ctx.duration
    assert float(re.search(r'data-duration="([\d.]+)"', media).group(1)) == pytest.approx(0.9)


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


def test_knockout_letters_stay_on_skin_not_on_hair():
    """Выше бровей за дырками букв тёмные волосы — то же тёмное по тёмному.

    Проверяется не число, а правило: нарисованная часть прописных целиком
    лежит в полосе кожи, посчитанной по измеренной коробке головы.
    """
    import re

    from src.lib.render.hyperframes.templates import face_band

    for word in ("ЕДИНСТВЕННАЯ", "ЖИВОЙ ЭФИР", "ДА"):
        params = {"head_top": 366, "head_h": 486, "word": word}
        node = render_hero("hero-knockout",
                           _hero_ctx("hero-knockout", params=params)).nodes[0]
        size = int(re.search(r'font-size="(\d+)"', node).group(1))
        rows = [int(y) for y in re.findall(r'<text x="540" y="(\d+)"', node)]
        top, bottom = face_band(params)
        assert rows, word
        assert rows[0] - 0.72 * size >= top - 1, f"{word}: буквы залезли на волосы"
        assert rows[-1] <= bottom + 1, f"{word}: буквы сползли на одежду"


def test_knockout_shrinks_to_the_face_but_not_below_readable():
    """Двухстрочное слово в лицо целиком не влезает — его мало опустить."""
    import re

    wide = _hero_ctx("hero-knockout", params={"word": "ЖИВОЙ ЭФИР"})
    tight = _hero_ctx("hero-knockout",
                      params={"word": "ЖИВОЙ ЭФИР", "head_top": 366,
                              "head_h": 486})
    free = int(re.search(r'font-size="(\d+)"',
                         render_hero("hero-knockout", wide).nodes[0]).group(1))
    fit = int(re.search(r'font-size="(\d+)"',
                        render_hero("hero-knockout", tight).nodes[0]).group(1))
    assert fit < free, "кегль не ужался под полосу лица"
    assert fit >= 150, "выбивка измельчала до подписи"


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


def test_apple_terminal_clear_dark_types_then_prints_output():
    """Каталог пишет textContent и innerHTML; здесь span-ы и opacity."""
    piece = render_fullscreen(_fs_ctx(
        content="", renderer="apple_terminal_clear_dark",
        apple_terminal_clear_dark=True, duration=8.0))
    node = piece.nodes[0]
    assert "fs-apple-terminal-clear-dark" in node
    assert "atcd-window" in node and "atcd-prompt" in node
    assert "atcd-slot" in node and "atcd-input-next" in node
    assert "bash — 80×24" in node
    assert "user@Mac ~ % " in node
    plain = re.sub(r"<[^>]+>", "", node)
    assert "npm audit" in plain
    assert "lodash" in plain
    assert "Run `npm audit fix` to fix them." in plain
    assert "NPM AUDIT" not in node
    assert "USER@MAC" not in node
    assert node.count("atcd-ch") == 9
    assert node.count("atcd-line") == 10
    assert "position:absolute" not in node.split("atcd-stage", 1)[0]
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert "text:" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "display:none" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "onUpdate" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = "#shot-01"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith("#shot-01-")
    flagged = render_fullscreen(_fs_ctx(
        content="", apple_terminal_clear_dark=True, stagger_ms=55, duration=8.0))
    assert "fs-apple-terminal-clear-dark" in flagged.nodes[0]
    assert "ks-word" not in flagged.nodes[0]
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="apple_terminal_clear_dark", duration=8.0))
    assert "npm audit" in re.sub(r"<[^>]+>", "", empty.nodes[0])
    times = _atcd_times(8.0, 9)
    assert abs(times["type_at"] - 0.50) < 1e-9
    assert abs(times["clear_at"] - 2.50) < 1e-9
    assert abs(times["prompt2"] - 4.20) < 1e-9
    short = _atcd_times(2.0, 9)
    assert short["hold"] <= 2.0 + 1e-9
    assert short["blink_dur"] < short["blink_gap"]


def test_apple_terminal_clear_dark_keeps_clear_dark_slate():
    from src.lib.config import load_config

    piece = render_fullscreen(_fs_ctx(
        content="", renderer="apple_terminal_clear_dark", duration=8.0))
    node = piece.nodes[0]
    assert "atcd-close" in node and "atcd-min" in node and "atcd-full" in node
    css = overlay_css(load_config().brandbook)
    assert ".fs-apple-terminal-clear-dark" in css
    assert "text-transform:none" in css
    assert "JetBrains Mono" in css
    assert "#1a1a1a" in css
    assert "#888888" in css
    assert "#ff5f57" in css
    prompt = re.search(r"\.atcd-prompt\{[^}]+\}", css).group(0)
    assert "#888888" in prompt
    assert "#C8453D" not in prompt
    cursor = re.search(r"\.atcd-cursor\{[^}]+\}", css).group(0)
    assert "#888888" in cursor
    assert "#C8453D" not in cursor
    title = re.search(r"\.atcd-title\{[^}]+\}", css).group(0)
    assert "transform:" not in title.replace("text-transform:none", "")
    stage = re.search(r"\.atcd-stage\{[^}]+\}", css).group(0)
    assert "position:absolute" not in stage
    invert = re.search(
        r"\.fullscreen-text\.fs-apple-terminal-clear-dark\.invert\{[^}]+\}",
        css).group(0)
    assert "#1a1a1a" in invert


def test_dark_plus_types_code_inside_vscode_chrome():
    """Каталог меряет DOM и крутит rotateY; здесь заранее x/y и 2D rotation."""
    piece = render_fullscreen(_fs_ctx(
        content="", renderer="dark_plus", dark_plus=True, duration=8.0))
    node = piece.nodes[0]
    assert "fs-dark-plus" in node
    assert "dp-wb" in node and "dp-editor" in node and "dp-caret" in node
    assert "Dark+" in node
    assert "functional_toolkit.py" in node
    plain = re.sub(r"<[^>]+>", "", node)
    assert "pluck_deep" in plain
    assert "compose" in plain
    assert "unfold" in plain
    assert "PLUCK_DEEP" not in node
    assert "python -m pytest" in node
    assert "position:absolute" not in node.split("dp-stage", 1)[0]
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    n_chars = node.count("dp-ch")
    assert n_chars > 80
    body = " ".join(piece.tweens)
    assert "rotateY" not in body
    assert "getBoundingClientRect" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "classList" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "onUpdate" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = "#shot-01"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith("#shot-01-")
    caret_xy = [tw for tw in piece.tweens
                if "#shot-01-caret" in tw and "x:" in tw]
    assert caret_xy
    flagged = render_fullscreen(_fs_ctx(
        content="", dark_plus=True, stagger_ms=55, duration=8.0))
    assert "fs-dark-plus" in flagged.nodes[0]
    assert "ks-word" not in flagged.nodes[0]
    empty = render_fullscreen(_fs_ctx(
        content="", renderer="dark_plus", duration=8.0))
    assert "pluck_deep" in re.sub(r"<[^>]+>", "", empty.nodes[0])
    times = _dp_times(11.0, [9] * 17)
    assert abs(times["type_at"] - 0.95) < 1e-9
    assert abs(times["term_at"] - 7.55) < 1e-9
    assert abs(times["tilt_at"] - 9.35) < 1e-9
    short = _dp_times(2.0, [9] * 17)
    assert short["untilt_at"] + short["untilt_dur"] <= 2.0 + 1e-6
    assert short["caret_dur"] < short["char_per"] - 5e-4


def test_dark_plus_keeps_theme_tokens():
    from src.lib.config import load_config

    piece = render_fullscreen(_fs_ctx(
        content="", renderer="dark_plus", duration=8.0))
    node = piece.nodes[0]
    assert "dp-traffic" in node and "dp-remote" in node
    css = overlay_css(load_config().brandbook)
    assert ".fs-dark-plus" in css
    assert "JetBrains Mono" in css
    assert "text-transform:none" in css
    assert "#1E1E1E" in css or "#1e1e1e" in css
    assert "#0078d4" in css
    assert "#6A9955" in css or "#6a9955" in css
    assert "#16825D" in css or "#16825d" in css
    comment = re.search(r"\.dp-tok-comment\{[^}]+\}", css).group(0)
    assert "#C8453D" not in comment
    wb = re.search(r"\.dp-wb\{[^}]+\}", css).group(0)
    assert "transform:" not in wb.replace("transform-origin:82% 50%", "").replace(
        "will-change:transform,opacity", "")
    stage = re.search(r"\.dp-stage\{[^}]+\}", css).group(0)
    assert "position:absolute" not in stage
    invert = re.search(
        r"\.fullscreen-text\.fs-dark-plus\.invert\{[^}]+\}", css).group(0)
    assert "#0a0a0a" in invert


def test_beat_freeze_cut_ramps_then_freezes_without_webgl():
    """Каталог твинит filter/visibility; здесь scale/x/y/opacity и 12 баров."""
    piece = render_fullscreen(_fs_ctx(
        content="", renderer="beat_freeze_cut", beat_freeze_cut=True,
        duration=6.0))
    node = piece.nodes[0]
    assert "fs-beat-freeze-cut" in node
    assert "bfc-card" in node and "bfc-bars" in node
    assert node.count('class="bfc-bar"') == 12
    assert "DROP" in node
    assert "FREEZE" in node
    assert "HARD" in node and "CUT" in node
    assert "ON THE BEAT" in node
    assert "MUSIC PROMO" in node
    assert "position:absolute" not in node.split("bfc-stage", 1)[0]
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert "WebGL" not in body
    assert "onUpdate" not in body
    assert "visibility" not in body
    assert "filter" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = "#shot-01"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith("#shot-01-")
    flagged = render_fullscreen(_fs_ctx(
        content="", beat_freeze_cut=True, stagger_ms=55, duration=6.0))
    assert "fs-beat-freeze-cut" in flagged.nodes[0]
    assert "ks-word" not in flagged.nodes[0]
    labeled = render_fullscreen(_fs_ctx(
        content="УДАР", renderer="beat_freeze_cut", duration=6.0))
    assert "УДАР" in labeled.nodes[0]
    assert "DROP" not in labeled.nodes[0]
    times = _bfc_times(6.0)
    assert abs(times["beat1"] - 0.7) < 1e-9
    assert abs(times["freeze"] - 2.2) < 1e-9
    assert abs(times["cut"] - 3.0) < 1e-9
    assert times["hold"] + times["hold_dur"] <= 6.0 + 1e-6
    short = _bfc_times(2.0)
    assert short["hold"] + short["hold_dur"] <= 2.0 + 1e-6
    assert short["freeze"] < times["freeze"]


def test_beat_freeze_cut_keeps_it_kosmos_palette_not_catalog_mint():
    from src.lib.config import load_config

    piece = render_fullscreen(_fs_ctx(
        content="", renderer="beat_freeze_cut", duration=6.0))
    node = piece.nodes[0]
    assert "#00E5C7" not in node and "#00e5c7" not in node
    css = overlay_css(load_config().brandbook)
    assert ".fs-beat-freeze-cut" in css
    block = css.split(".fs-beat-freeze-cut", 1)[1].split(".fs-swap-box", 1)[0]
    assert "#E63946" in block
    assert "#0B132B" in block
    assert "#1A1F2E" in block
    assert "#C7C9D1" in block
    assert "#C8453D" not in block
    assert "#111214" not in block
    assert "#F7F5F3" not in block
    assert "#7A7D82" not in block
    assert "#00E5C7" not in block and "#00e5c7" not in block
    assert "#00E5FF" not in block and "#00e5ff" not in block
    assert "-apple-system" not in block
    bar = re.search(r"\.bfc-bar\{[^}]+\}", css).group(0)
    assert "#E63946" in bar
    assert "transform-origin:50% 100%" in bar
    assert "transform:" not in bar.replace("transform-origin:50% 100%", "").replace(
        "will-change:transform", "")
    wave = re.search(r"\.bfc-wave-path\{[^}]+\}", css).group(0)
    assert "stroke:#E63946" in wave
    eyebrow = re.search(r"\.bfc-eyebrow\{[^}]+\}", css).group(0)
    assert "color:#E63946" in eyebrow
    pill = re.search(r"\.bfc-pill\{[^}]+\}", css).group(0)
    assert "background:#E63946" in pill
    assert "color:#ffffff" in pill
    stage = re.search(r"\.bfc-stage\{[^}]+\}", css).group(0)
    assert "position:absolute" not in stage
    invert = re.search(
        r"\.fullscreen-text\.fs-beat-freeze-cut\.invert\{[^}]+\}", css).group(0)
    assert "#0B132B" in invert
    assert "#111214" not in invert


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


def test_cinematic_zoom_from_out_to_in_without_webgl(ctx):
    """Каталог крутит шейдер в onUpdate; здесь scale/opacity и статичный blur."""
    piece = render_transition("cinematic_zoom", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.16}}))
    node = piece.nodes[0]
    assert "tr-cinematic-zoom" in node
    assert "cz-stage" in node
    assert "cz-from" in node and "cz-to" in node
    assert "cz-r" in node and "cz-b" in node
    assert "cz-blur" in node
    assert node.count("cz-ghost") == 3
    assert "position:absolute" not in node.split("cz-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert f'scale:1.16' in body
    assert f'"#{ctx.target}"' in body
    assert "power2.inOut" in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "text:" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    times = _cz_times(ctx.duration)
    assert times["mid"] + times["to_out"] < ctx.duration + 1e-9
    assert times["to_out_at"] > times["mid"]
    short = _cz_times(0.22)
    assert short["to_out_at"] + short["to_out"] <= 0.22 + 1e-9


def test_cinematic_zoom_keeps_catalog_indigo_and_gold():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-cinematic-zoom" in css
    frm = re.search(r"\.tr-cinematic-zoom \.cz-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-cinematic-zoom \.cz-to\{[^}]+\}", css).group(0)
    assert "#3d348b" in frm
    assert "#f7b801" in too
    assert "#C8453D" not in frm and "#C8453D" not in too
    stage = re.search(r"\.tr-cinematic-zoom \.cz-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    # GSAP owns scale — no CSS transform on tweened layers
    assert "transform:" not in stripped.split(".tr-cinematic-zoom", 1)[1]
    assert "backdrop-filter:blur(16px)" in css


def test_chromatic_radial_split_animates_without_webgl(ctx):
    """Каталог крутит WebGL в onUpdate; здесь radial color split/opacity и статичный blur."""
    piece = render_transition("chromatic_radial_split", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.14}}))
    node = piece.nodes[0]
    assert "tr-chromatic-radial-split" in node
    assert "crs-stage" in node
    assert "crs-from" in node and "crs-to" in node
    assert "crs-r" in node and "crs-b" in node
    assert "crs-blur" in node
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert "scale:1.14" in body
    assert f'"#{ctx.target}"' in body
    assert "power2.inOut" in body
    assert "webgl" not in body.lower()


def test_chromatic_radial_split_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-chromatic-radial-split" in css
    frm = re.search(r"\.tr-chromatic-radial-split \.crs-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-chromatic-radial-split \.crs-to\{[^}]+\}", css).group(0)
    assert "#22223b" in frm
    assert "#7678ed" in too
    stage = re.search(r"\.tr-chromatic-radial-split \.crs-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    assert "backdrop-filter:blur(14px)" in css


def test_cross_warp_morph_animates_without_webgl(ctx):
    """Каталог крутит WebGL в onUpdate; здесь opposing coordinate drift, dual crossfade и soft blur."""
    piece = render_transition("cross_warp_morph", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.12}}))
    node = piece.nodes[0]
    assert "tr-cross-warp-morph" in node
    assert "cwm-stage" in node
    assert "cwm-from" in node and "cwm-to" in node
    assert "cwm-warp-a" in node and "cwm-warp-b" in node
    assert "cwm-blur" in node
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert "scale:1.12" in body
    assert f'"#{ctx.target}"' in body
    assert "power2.inOut" in body
    assert "webgl" not in body.lower()


def test_cross_warp_morph_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-cross-warp-morph" in css
    frm = re.search(r"\.tr-cross-warp-morph \.cwm-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-cross-warp-morph \.cwm-to\{[^}]+\}", css).group(0)
    assert "#283618" in frm
    assert "#a7c957" in too
    stage = re.search(r"\.tr-cross-warp-morph \.cwm-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    assert "backdrop-filter:blur(14px)" in css


def test_domain_warp_dissolve_animates_without_webgl(ctx):
    """Каталог крутит WebGL в onUpdate; здесь cascaded warp crossfade, iridescent glow и blur."""
    piece = render_transition("domain_warp_dissolve", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.14}}))
    node = piece.nodes[0]
    assert "tr-domain-warp-dissolve" in node
    assert "dwd-stage" in node
    assert "dwd-from" in node and "dwd-to" in node
    assert "dwd-glow" in node
    assert "dwd-blur" in node
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert "scale:1.14" in body
    assert f'"#{ctx.target}"' in body
    assert "power2.inOut" in body
    assert "webgl" not in body.lower()


def test_domain_warp_dissolve_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-domain-warp-dissolve" in css
    frm = re.search(r"\.tr-domain-warp-dissolve \.dwd-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-domain-warp-dissolve \.dwd-to\{[^}]+\}", css).group(0)
    assert "#0d1b2a" in frm
    assert "#00f5d4" in too
    stage = re.search(r"\.tr-domain-warp-dissolve \.dwd-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    assert "backdrop-filter:blur(14px)" in css


def test_flash_through_white_animates_without_webgl(ctx):
    """Каталог крутит WebGL в onUpdate; здесь white flare midpoint, amber glow и crossfade."""
    piece = render_transition("flash_through_white", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.12}}))
    node = piece.nodes[0]
    assert "tr-flash-through-white" in node
    assert "ftw-stage" in node
    assert "ftw-from" in node and "ftw-to" in node
    assert "ftw-flash" in node and "ftw-glow" in node
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert "scale:1.12" in body
    assert f'"#{ctx.target}"' in body
    assert "power2.in" in body or "power2.out" in body
    assert "webgl" not in body.lower()


def test_flash_through_white_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-flash-through-white" in css
    frm = re.search(r"\.tr-flash-through-white \.ftw-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-flash-through-white \.ftw-to\{[^}]+\}", css).group(0)
    assert "#03071e" in frm
    assert "#ffba08" in too
    stage = re.search(r"\.tr-flash-through-white \.ftw-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    assert "#ffffff" in css


def test_ridged_burn_animates_without_webgl(ctx):
    """Каталог крутит WebGL в onUpdate; здесь fiery blackbody burn, ember sparks и crossfade."""
    piece = render_transition("ridged_burn", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.14}}))
    node = piece.nodes[0]
    assert "tr-ridged-burn" in node
    assert "rb-stage" in node
    assert "rb-from" in node and "rb-to" in node
    assert "rb-ember" in node and "rb-sparks" in node
    assert "rb-blur" in node
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert "scale:1.14" in body
    assert f'"#{ctx.target}"' in body
    assert "power2.in" in body or "power2.out" in body
    assert "webgl" not in body.lower()


def test_ridged_burn_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-ridged-burn" in css
    frm = re.search(r"\.tr-ridged-burn \.rb-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-ridged-burn \.rb-to\{[^}]+\}", css).group(0)
    assert "#0b090a" in frm
    assert "#e5383b" in too
    stage = re.search(r"\.tr-ridged-burn \.rb-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    assert "backdrop-filter:blur(14px)" in css


def test_ripple_waves_animates_without_webgl(ctx):
    """Каталог крутит WebGL в onUpdate; здесь concentric wave rings in counter-phase, ripple highlights и blur."""
    piece = render_transition("ripple_waves", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.12}}))
    node = piece.nodes[0]
    assert "tr-ripple-waves" in node
    assert "rw-stage" in node
    assert "rw-from" in node and "rw-to" in node
    assert "rw-w1" in node and "rw-w2" in node
    assert "rw-blur" in node
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert "scale:1.12" in body
    assert f'"#{ctx.target}"' in body
    assert "power2.inOut" in body or "power2.out" in body
    assert "webgl" not in body.lower()


def test_ripple_waves_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-ripple-waves" in css
    frm = re.search(r"\.tr-ripple-waves \.rw-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-ripple-waves \.rw-to\{[^}]+\}", css).group(0)
    assert "#264653" in frm
    assert "#e9c46a" in too
    stage = re.search(r"\.tr-ripple-waves \.rw-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    assert "backdrop-filter:blur(14px)" in css


def test_swirl_vortex_animates_without_webgl(ctx):
    """Каталог крутит WebGL в onUpdate; здесь counter-rotating swirl crossfade, vortex glow и blur."""
    piece = render_transition("swirl_vortex", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.12}}))
    node = piece.nodes[0]
    assert "tr-swirl-vortex" in node
    assert "sv-stage" in node
    assert "sv-from" in node and "sv-to" in node
    assert "sv-vortex" in node
    assert "sv-blur" in node
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert "scale:1.12" in body
    assert f'"#{ctx.target}"' in body
    assert "rotation:28" in body and "rotation:-28" in body
    assert "webgl" not in body.lower()


def test_swirl_vortex_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-swirl-vortex" in css
    frm = re.search(r"\.tr-swirl-vortex \.sv-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-swirl-vortex \.sv-to\{[^}]+\}", css).group(0)
    assert "#073b4c" in frm
    assert "#06d6a0" in too
    stage = re.search(r"\.tr-swirl-vortex \.sv-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    assert "backdrop-filter:blur(14px)" in css


def test_transitions_dissolve_animates_without_webgl(ctx):
    """Каталог демонстрирует dissolve переходы; здесь smooth crossfade с scale drift и blur."""
    piece = render_transition("transitions_dissolve", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.10}}))
    node = piece.nodes[0]
    assert "tr-transitions-dissolve" in node
    assert "td-stage" in node
    assert "td-a" in node and "td-b" in node
    assert "td-blur" in node
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert "scale:1.1" in body
    assert f'"#{ctx.target}"' in body
    assert "power2.inOut" in body
    assert "webgl" not in body.lower()


def test_transitions_dissolve_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-transitions-dissolve" in css
    frm = re.search(r"\.tr-transitions-dissolve \.td-a\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-transitions-dissolve \.td-b\{[^}]+\}", css).group(0)
    assert "#1b263b" in frm
    assert "#e07a5f" in too
    stage = re.search(r"\.tr-transitions-dissolve \.td-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    assert "backdrop-filter:blur(14px)" in css


def test_transitions_distortion_animates_without_webgl(ctx):
    """Каталог демонстрирует distortion переходы; здесь chromatic RGB slices и jitter."""
    piece = render_transition("transitions_distortion", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.12}}))
    node = piece.nodes[0]
    assert "tr-transitions-distortion" in node
    assert "tdist-stage" in node
    assert "tdist-a" in node and "tdist-b" in node
    assert "tdist-r" in node and "tdist-b-chroma" in node
    assert "tdist-blur" in node
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert "scale:1.12" in body
    assert f'"#{ctx.target}"' in body
    assert "x:-18" in body or "x:18" in body
    assert "webgl" not in body.lower()


def test_transitions_distortion_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-transitions-distortion" in css
    frm = re.search(r"\.tr-transitions-distortion \.tdist-a\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-transitions-distortion \.tdist-b\{[^}]+\}", css).group(0)
    assert "#1b263b" in frm
    assert "#e07a5f" in too
    stage = re.search(r"\.tr-transitions-distortion \.tdist-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    assert "rgba(229,56,59,0.35)" in css
    assert "rgba(72,191,227,0.35)" in css


def test_glitch_shader_scan_and_scramble_without_webgl(ctx):
    """Каталог крутит шейдер в onUpdate; здесь полосы, клетки и chroma."""
    seed = 9
    piece = render_transition("glitch_shader", TemplateCtx(
        **{**ctx.__dict__, "params": {"seed": seed}}))
    node = piece.nodes[0]
    assert "tr-glitch-shader" in node
    assert "gs-stage" in node
    assert "gs-from" in node and "gs-to" in node
    assert "gs-r" in node and "gs-b" in node
    assert "gs-lines" in node and "gs-flick" in node
    assert node.count("gs-scan") == _GS_SCANS
    blocks = _gs_blocks(ctx.index, seed)
    assert node.count("gs-block") == len(blocks)
    assert "position:absolute" not in node.split("gs-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    ids = re.findall(r'\sid="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "power2.inOut" in body
    assert "steps(3)" in body and "steps(2)" in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "text:" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector != f"#{ctx.target}", tween
    times = _gs_times(ctx.duration)
    assert times["mid"] + times["to_out"] < ctx.duration + 1e-9
    assert times["to_out_at"] > times["mid"]
    short = _gs_times(0.22)
    assert short["to_out_at"] + short["to_out"] <= 0.22 + 1e-9
    again = render_transition("glitch_shader", TemplateCtx(
        **{**ctx.__dict__, "params": {"seed": seed}}))
    assert again.tweens == piece.tweens
    other = render_transition("glitch_shader", TemplateCtx(
        **{**ctx.__dict__, "index": ctx.index + 1, "params": {"seed": seed}}))
    assert other.tweens != piece.tweens
    assert _gs_blocks(ctx.index, seed) == _gs_blocks(ctx.index, seed)
    assert _gs_blocks(ctx.index, seed) != _gs_blocks(ctx.index + 1, seed)


def test_glitch_shader_keeps_catalog_slate_and_coral():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-glitch-shader" in css
    frm = re.search(r"\.tr-glitch-shader \.gs-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-glitch-shader \.gs-to\{[^}]+\}", css).group(0)
    assert "#293241" in frm
    assert "#ee6c4d" in too
    assert "#C8453D" not in frm and "#C8453D" not in too
    assert "#98c1d9" in css
    stage = re.search(r"\.tr-glitch-shader \.gs-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-glitch-shader", 1)[1]
    short = render_transition("glitch", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11,
        params={"bars": 7}))
    assert "tr-glitch-shader" not in short.nodes[0]
    assert 'class="clip tr-glitch"' in short.nodes[0]


def test_gravitational_lens_warps_in_without_webgl(ctx):
    """Каталог крутит шейдер в onUpdate; здесь scale к центру и chroma."""
    piece = render_transition("gravitational_lens", TemplateCtx(
        **{**ctx.__dict__, "params": {"from_scale": 1.14}}))
    node = piece.nodes[0]
    assert "tr-gravitational-lens" in node
    assert "gw-stage" in node
    assert "gw-from" in node and "gw-to" in node
    assert "gw-well" in node
    assert "gw-r" in node and "gw-b" in node
    assert "gw-blur" in node
    assert node.count("gw-ghost") == 3
    assert "position:absolute" not in node.split("gw-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert "scale:1.14" in body
    assert f'"#{ctx.target}"' in body
    assert "scale:0.62" in body
    assert "power2.inOut" in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "text:" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    times = _gw_times(ctx.duration)
    assert times["mid"] + times["to_out"] < ctx.duration + 1e-9
    assert times["to_out_at"] > times["mid"]
    short = _gw_times(0.22)
    assert short["to_out_at"] + short["to_out"] <= 0.22 + 1e-9


def test_gravitational_lens_keeps_catalog_magenta():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-gravitational-lens" in css
    frm = re.search(r"\.tr-gravitational-lens \.gw-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-gravitational-lens \.gw-to\{[^}]+\}", css).group(0)
    assert "#10002b" in frm
    assert "#f20089" in too
    assert "#C8453D" not in frm and "#C8453D" not in too
    assert "#a080a0" in css or "160,128,160" in css
    stage = re.search(r"\.tr-gravitational-lens \.gw-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-gravitational-lens", 1)[1]
    assert "backdrop-filter:blur(14px)" in css


def test_light_leak_washes_in_without_webgl(ctx):
    """Каталог крутит шейдер в onUpdate; здесь пятно, flare и вуали."""
    piece = render_transition("light_leak", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-light-leak" in node
    assert "ll-stage" in node
    assert "ll-from" in node and "ll-to" in node
    assert "ll-blob" in node and "ll-flare" in node
    assert "ll-hot" in node and "ll-sage" in node
    assert node.count("ll-orb") == 2
    assert "position:absolute" not in node.split("ll-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scale:0.38" in body
    assert "x:240" in body
    assert "power2.inOut" in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "text:" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    times = _ll_times(ctx.duration)
    assert times["mid"] + times["to_out"] < ctx.duration + 1e-9
    assert times["to_out_at"] > times["mid"]
    short = _ll_times(0.22)
    assert short["to_out_at"] + short["to_out"] <= 0.22 + 1e-9
    sweep = render_transition("light_sweep", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11))
    assert "tr-light-leak" not in sweep.nodes[0]
    assert 'class="clip tr-sweep"' in sweep.nodes[0]


def test_light_leak_keeps_catalog_navy_and_amber():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-light-leak" in css
    frm = re.search(r"\.tr-light-leak \.ll-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-light-leak \.ll-to\{[^}]+\}", css).group(0)
    assert "#001524" in frm
    assert "#fb8b24" in too
    assert "#C8453D" not in frm and "#C8453D" not in too
    assert "#708d81" in css
    stage = re.search(r"\.tr-light-leak \.ll-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-light-leak", 1)[1]


def test_sdf_iris_opens_from_center_without_webgl(ctx):
    """Каталог крутит шейдер в onUpdate; здесь диск, три кольца и вуали."""
    piece = render_transition("sdf_iris", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-sdf-iris" in node
    assert "si-stage" in node
    assert "si-from" in node and "si-iris" in node
    assert "si-steel" in node
    assert node.count("si-ring") == 3
    assert "position:absolute" not in node.split("si-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scale:0.06" in body
    assert "power2.inOut" in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "text:" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    times = _si_times(ctx.duration)
    assert times["mid"] + times["to_out"] < ctx.duration + 1e-9
    assert times["to_out_at"] > times["mid"]
    short = _si_times(0.22)
    assert short["to_out_at"] + short["to_out"] <= 0.22 + 1e-9
    wipe = render_transition("mask_wipe", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11,
        params={"shape": "circle"}))
    assert "tr-sdf-iris" not in wipe.nodes[0]
    assert "tr-mask-circle" in wipe.nodes[0]


def test_sdf_iris_keeps_catalog_teal_and_gold():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-sdf-iris" in css
    frm = re.search(r"\.tr-sdf-iris \.si-from\{[^}]+\}", css).group(0)
    iris = re.search(r"\.tr-sdf-iris \.si-iris\{[^}]+\}", css).group(0)
    assert "#003049" in frm
    assert "#ffc300" in iris
    assert "#C8453D" not in frm and "#C8453D" not in iris
    assert "#7a9ab0" in css
    stage = re.search(r"\.tr-sdf-iris \.si-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-sdf-iris", 1)[1]


def test_thermal_distortion_rises_from_bottom_without_webgl(ctx):
    """Каталог крутит шейдер в onUpdate; здесь haze, полосы и вуали."""
    piece = render_transition("thermal_distortion", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-thermal-distortion" in node
    assert "td-stage" in node
    assert "td-from" in node and "td-to" in node
    assert "td-haze" in node and "td-hot" in node
    assert "td-mist" in node and "td-blur" in node
    assert node.count("td-band") == 5
    assert "position:absolute" not in node.split("td-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scale:0.42" in body
    assert "y:0" in body
    assert "power2.inOut" in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "text:" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    times = _td_times(ctx.duration)
    assert times["mid"] + times["to_out"] < ctx.duration + 1e-9
    assert times["to_out_at"] > times["mid"]
    short = _td_times(0.22)
    assert short["to_out_at"] + short["to_out"] <= 0.22 + 1e-9
    leak = render_transition("light_leak", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11))
    assert "tr-thermal-distortion" not in leak.nodes[0]
    assert "tr-light-leak" in leak.nodes[0]


def test_thermal_distortion_keeps_catalog_slate_and_terracotta():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-thermal-distortion" in css
    frm = re.search(r"\.tr-thermal-distortion \.td-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-thermal-distortion \.td-to\{[^}]+\}", css).group(0)
    assert "#3d405b" in frm
    assert "#e07a5f" in too
    assert "#C8453D" not in frm and "#C8453D" not in too
    assert "#a0a0b0" in css
    assert "rgba(255,230,179" in css
    stage = re.search(r"\.tr-thermal-distortion \.td-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-thermal-distortion", 1)[1]
    assert "backdrop-filter:blur(10px)" in css


def test_whip_pan_shader_slides_with_streaks_without_webgl(ctx):
    """Каталог крутит шейдер в onUpdate; здесь вуали, полосы смаза и x."""
    piece = render_transition("whip_pan_shader", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-whip-pan" in node
    assert "wp-stage" in node
    assert "wp-from" in node and "wp-to" in node
    assert "wp-steel" in node and "wp-blur" in node
    assert node.count("wp-streak") == 6
    assert "position:absolute" not in node.split("wp-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "x:0" in body
    assert "x:-360" in body
    assert "power2.inOut" in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "text:" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
    times = _wp_times(ctx.duration)
    assert times["mid"] + times["to_out"] < ctx.duration + 1e-9
    assert times["to_out_at"] > times["mid"]
    short = _wp_times(0.22)
    assert short["to_out_at"] + short["to_out"] <= 0.22 + 1e-9
    legacy = render_transition("whip_pan", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11,
        params={"direction": 1, "blur": 24}))
    assert "tr-whip-pan" not in legacy.nodes[0]
    assert "tr-blur" in legacy.nodes[0]


def test_whip_pan_shader_keeps_catalog_navy_and_cyan():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-whip-pan" in css
    frm = re.search(r"\.tr-whip-pan \.wp-from\{[^}]+\}", css).group(0)
    too = re.search(r"\.tr-whip-pan \.wp-to\{[^}]+\}", css).group(0)
    assert "#0b132b" in frm
    assert "#48bfe3" in too
    assert "#C8453D" not in frm and "#C8453D" not in too
    assert "#7a9ab0" in css
    assert "rgba(72,191,227" in css
    stage = re.search(r"\.tr-whip-pan \.wp-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-whip-pan", 1)[1]
    assert "backdrop-filter:blur(10px)" in css


def test_mk_clone_wall_tiles_then_inverts_without_webgl(ctx):
    """Каталог твинит width/height и visibility; здесь scale/x/opacity и плитка."""
    piece = render_transition("mk_clone_wall", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-mk-clone-wall" in node
    assert "cw-stage" in node
    assert "cw-wall" in node and "cw-tiles" in node
    assert "cw-invert" in node and "cw-card" in node
    assert "HyperFrames" in node
    assert "cw-row" in node and "cw-tile" in node
    assert node.count("cw-row") >= 6
    assert "position:absolute" not in node.split("cw-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scale:0.38" in body
    assert "borderRadius:40" in body
    assert "x:-1080" in body
    assert "x:0" in body
    assert "power3.inOut" in body
    assert "sine.inOut" in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _cw_times(ctx.duration)
    assert times["card_at"] + times["card_dur"] <= times["card_out_at"] + 1e-9
    assert times["wall_out_at"] + times["wall_out_dur"] <= ctx.duration + 1e-9
    assert times["card_kill"] <= ctx.duration + 1e-9
    short = _cw_times(0.22)
    assert short["wall_out_at"] + short["wall_out_dur"] <= 0.22 + 1e-9
    renamed = render_transition("mk_clone_wall", TemplateCtx(
        index=ctx.index, start=ctx.start, duration=ctx.duration,
        target=ctx.target, track=ctx.track, params={"word": "РЕДШИФТ"}))
    assert "РЕДШИФТ" in renamed.nodes[0]
    assert "HyperFrames" not in renamed.nodes[0]


def test_mk_clone_wall_keeps_catalog_ink_paper_and_blobs():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-mk-clone-wall" in css
    wall = re.search(r"\.tr-mk-clone-wall \.cw-wall\{[^}]+\}", css).group(0)
    invert = re.search(r"\.tr-mk-clone-wall \.cw-invert\{[^}]+\}", css).group(0)
    card = re.search(r"\.tr-mk-clone-wall \.cw-card\{[^}]+\}", css).group(0)
    row = re.search(r"\.tr-mk-clone-wall \.cw-row\{[^}]+\}", css).group(0)
    assert "#ffffff" in wall
    assert "isolation:isolate" in wall
    assert "#ffffff" in invert
    assert "mix-blend-mode:difference" in invert
    assert "#ff7ac8" in card and "#45d6c8" in card
    assert "#1d1d1f" in row
    assert "Inter" in row
    assert "-apple-system" not in css.split(".tr-mk-clone-wall", 1)[1]
    assert "#C8453D" not in css.split(".tr-mk-clone-wall", 1)[1].split(".fullscreen-text", 1)[0]
    assert "#00E5C7" not in css.split(".tr-mk-clone-wall", 1)[1]
    stage = re.search(r"\.tr-mk-clone-wall \.cw-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-mk-clone-wall", 1)[1]


def test_transitions_3d_flips_with_scalex_without_rotationy(ctx):
    """Каталог твинит rotationY; здесь scaleX граней и ребро."""
    piece = render_transition("transitions_3d", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-transitions-3d" in node
    assert "t3-stage" in node
    assert "t3-face" in node and "t3-a" in node and "t3-b" in node
    assert "t3-edge" in node
    assert "ONE" in node and "TWO" in node
    assert "SCENE A" in node and "SCENE B" in node
    assert "position:absolute" not in node.split("t3-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scaleX:0" in body
    assert "scaleX:1" in body
    assert "power2.inOut" in body
    assert "rotationY" not in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter" not in body
    assert "visibility" not in body
    assert "clipPath" not in body
    assert "zIndex" not in body
    assert "skewX" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _t3_times(ctx.duration)
    assert times["a_at"] + times["a_dur"] <= times["b_at"] + 1e-9
    assert times["b_at"] + times["b_dur"] <= ctx.duration + 1e-9
    assert times["edge_at"] + times["edge_in"] <= times["edge_mid"] + 1e-9
    assert times["a_kill"] <= ctx.duration + 1e-9
    short = _t3_times(0.22)
    assert short["b_at"] + short["b_dur"] <= 0.22 + 1e-9
    thermal = render_transition("thermal_distortion", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11))
    assert "tr-transitions-3d" not in thermal.nodes[0]


def test_transitions_3d_keeps_catalog_navy_and_terracotta():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-transitions-3d" in css
    face_a = re.search(r"\.tr-transitions-3d \.t3-a\{[^}]+\}", css).group(0)
    face_b = re.search(r"\.tr-transitions-3d \.t3-b\{[^}]+\}", css).group(0)
    assert "#1b263b" in face_a
    assert "#e07a5f" in face_b
    assert "#778da9" in css
    assert "Inter" in css.split(".tr-transitions-3d", 1)[1]
    assert "-apple-system" not in css.split(".tr-transitions-3d", 1)[1]
    assert "#C8453D" not in css.split(".tr-transitions-3d", 1)[1]
    assert "#00E5C7" not in css.split(".tr-transitions-3d", 1)[1]
    assert "#00E5FF" not in css.split(".tr-transitions-3d", 1)[1]
    stage = re.search(r"\.tr-transitions-3d \.t3-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-transitions-3d", 1)[1]


def test_transitions_blur_crossfades_with_scale_without_filter_tween(ctx):
    """Каталог твинит filter; здесь scale граней и призраки со статическим blur."""
    piece = render_transition("transitions_blur", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-transitions-blur" in node
    assert "tb-stage" in node
    assert "tb-face" in node and "tb-a" in node and "tb-b" in node
    assert "tb-ghost" in node
    assert "ONE" in node and "TWO" in node
    assert "SCENE A" in node and "SCENE B" in node
    assert "position:absolute" not in node.split("tb-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "scale:1.05" in body
    assert "scale:0.95" in body
    assert "power2.in" in body
    assert "power2.out" in body
    assert "immediateRender:false" in body
    assert "filter" not in body
    assert "skewX" not in body
    assert "rotationY" not in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "visibility" not in body
    assert "clipPath" not in body
    assert "zIndex" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _tb_times(ctx.duration)
    assert times["ag_at"] + times["ag_in"] <= times["ag_mid"] + 1e-9
    assert times["ag_mid"] + times["ag_out"] <= ctx.duration + 1e-9
    assert times["a_at"] + times["a_dur"] <= ctx.duration + 1e-9
    assert times["b_at"] + times["b_dur"] <= ctx.duration + 1e-9
    assert times["a_kill"] <= ctx.duration + 1e-9
    short = _tb_times(0.22)
    assert short["b_at"] + short["b_dur"] <= 0.22 + 1e-9
    dip = render_transition("blur_dip", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11))
    assert "tr-transitions-blur" not in dip.nodes[0]
    three = render_transition("transitions_3d", TemplateCtx(
        index=2, start=0.0, duration=0.2, target="shot-02", track=11))
    assert "tr-transitions-blur" not in three.nodes[0]


def test_transitions_blur_keeps_catalog_navy_and_terracotta():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-transitions-blur" in css
    face_a = re.search(r"\.tr-transitions-blur \.tb-a\{[^}]+\}", css).group(0)
    face_b = re.search(r"\.tr-transitions-blur \.tb-b\{[^}]+\}", css).group(0)
    ghost = re.search(r"\.tr-transitions-blur \.tb-ghost\{[^}]+\}", css).group(0)
    assert "#1b263b" in face_a
    assert "#e07a5f" in face_b
    assert "filter:blur(15px)" in ghost
    assert "#778da9" in css.split(".tr-transitions-blur", 1)[1]
    assert "Inter" in css.split(".tr-transitions-blur", 1)[1]
    assert "-apple-system" not in css.split(".tr-transitions-blur", 1)[1]
    assert "#C8453D" not in css.split(".tr-transitions-blur", 1)[1]
    assert "#00E5C7" not in css.split(".tr-transitions-blur", 1)[1]
    assert "#00E5FF" not in css.split(".tr-transitions-blur", 1)[1]
    stage = re.search(r"\.tr-transitions-blur \.tb-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-transitions-blur", 1)[1]


def test_transitions_cover_slides_wipes_with_x_without_css_transform(ctx):
    """Каталог ставит translateX в CSS; здесь GSAP x на 1080 px."""
    piece = render_transition("transitions_cover", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-transitions-cover" in node
    assert "tc-stage" in node
    assert "tc-face" in node and "tc-a" in node and "tc-b" in node
    assert "tc-wipe" in node and "tc-wa" in node and "tc-wb" in node
    assert "ONE" in node and "TWO" in node
    assert "SCENE A" in node and "SCENE B" in node
    assert "position:absolute" not in node.split("tc-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "x:-1080" in body
    assert "x:1080" in body
    assert "power3.inOut" in body
    assert "immediateRender:false" in body
    assert "filter" not in body
    assert "skewX" not in body
    assert "rotationY" not in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "visibility" not in body
    assert "clipPath" not in body
    assert "zIndex" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _tc_times(ctx.duration)
    assert times["wa_in_at"] + times["wa_in_dur"] + 0.001 <= times["wa_out_at"] + 1e-9
    assert times["wb_in_at"] + times["wb_in_dur"] + 0.001 <= times["wb_out_at"] + 1e-9
    assert times["wa_out_at"] + times["wa_out_dur"] <= ctx.duration + 1e-9
    assert times["wb_out_at"] + times["wb_out_dur"] <= ctx.duration + 1e-9
    assert times["swap_at"] <= times["wa_out_at"] + 1e-9
    short = _tc_times(0.22)
    assert short["wb_out_at"] + short["wb_out_dur"] <= 0.22 + 1e-9
    dip = render_transition("blur_dip", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11))
    assert "tr-transitions-cover" not in dip.nodes[0]
    three = render_transition("transitions_3d", TemplateCtx(
        index=2, start=0.0, duration=0.2, target="shot-02", track=11))
    assert "tr-transitions-cover" not in three.nodes[0]
    blur = render_transition("transitions_blur", TemplateCtx(
        index=4, start=0.0, duration=0.2, target="shot-04", track=11))
    assert "tr-transitions-cover" not in blur.nodes[0]
    paper = render_transition("paper_slide", TemplateCtx(
        index=5, start=0.0, duration=0.2, target="shot-05", track=11,
        params={"direction": 1}))
    assert paper.nodes == [] or "tr-transitions-cover" not in paper.nodes[0]


def test_transitions_cover_keeps_catalog_magenta_and_purple():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-transitions-cover" in css
    face_a = re.search(r"\.tr-transitions-cover \.tc-a\{[^}]+\}", css).group(0)
    face_b = re.search(r"\.tr-transitions-cover \.tc-b\{[^}]+\}", css).group(0)
    wipe_a = re.search(r"\.tr-transitions-cover \.tc-wa\{[^}]+\}", css).group(0)
    wipe_b = re.search(r"\.tr-transitions-cover \.tc-wb\{[^}]+\}", css).group(0)
    assert "#1b263b" in face_a
    assert "#e07a5f" in face_b
    assert "#f72585" in wipe_a
    assert "#7209b7" in wipe_b
    block = css.split(".tr-transitions-cover", 1)[1]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    assert "text-transform" not in block
    stage = re.search(r"\.tr-transitions-cover \.tc-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-transitions-cover", 1)[1]


def test_transitions_destruction_burns_a_circle_without_clip_path_or_canvas(ctx):
    """Каталог рисует canvas и clip-path; здесь scale круга overflow:hidden."""
    piece = render_transition("transitions_destruction", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-transitions-destruction" in node
    assert "tds-stage" in node
    assert "tds-face" in node and "tds-a" in node and "tds-b" in node
    assert "tds-hole" in node
    assert "tds-ring" in node and "tds-r0" in node and "tds-r1" in node and "tds-r2" in node
    assert "ONE" in node and "TWO" in node
    assert "SCENE A" in node and "SCENE B" in node
    assert "position:absolute" not in node.split("tds-stage", 1)[0]
    assert "<canvas" not in node
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "power1.in" in body
    assert "power1.out" in body
    assert "immediateRender:false" in body
    assert "scale:25" in body or "scale:25." in body
    assert "filter" not in body
    assert "skewX" not in body
    assert "rotationY" not in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "visibility" not in body
    assert "clipPath" not in body
    assert "zIndex" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _tds_times(ctx.duration)
    assert times["burn_at"] + times["burn_dur"] <= ctx.duration + 1e-9
    assert times["b_at"] + times["b_dur"] <= ctx.duration + 1e-9
    assert times["burn_at"] + 0.001 <= times["b_at"] + 1e-9
    assert times["kill_at"] <= ctx.duration + 1e-9
    short = _tds_times(0.22)
    assert short["burn_at"] + short["burn_dur"] <= 0.22 + 1e-9
    assert short["b_at"] + short["b_dur"] <= 0.22 + 1e-9
    dip = render_transition("blur_dip", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11))
    assert "tr-transitions-destruction" not in dip.nodes[0]
    three = render_transition("transitions_3d", TemplateCtx(
        index=2, start=0.0, duration=0.2, target="shot-02", track=11))
    assert "tr-transitions-destruction" not in three.nodes[0]
    blur = render_transition("transitions_blur", TemplateCtx(
        index=4, start=0.0, duration=0.2, target="shot-04", track=11))
    assert "tr-transitions-destruction" not in blur.nodes[0]
    cover = render_transition("transitions_cover", TemplateCtx(
        index=5, start=0.0, duration=0.2, target="shot-05", track=11))
    assert "tr-transitions-destruction" not in cover.nodes[0]
    iris = render_transition("sdf_iris", TemplateCtx(
        index=6, start=0.0, duration=0.2, target="shot-06", track=11))
    assert "tr-transitions-destruction" not in iris.nodes[0]
    mask = render_transition("mask_wipe", TemplateCtx(
        index=7, start=0.0, duration=0.2, target="shot-07", track=11,
        params={"shape": "circle"}))
    assert "tr-transitions-destruction" not in mask.nodes[0]


def test_transitions_destruction_keeps_catalog_navy_terra_and_fire():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-transitions-destruction" in css
    face_a = re.search(
        r"\.tr-transitions-destruction \.tds-hole \.tds-a\{[^}]+\}", css).group(0)
    face_b = re.search(r"\.tr-transitions-destruction \.tds-b\{[^}]+\}", css).group(0)
    ring0 = re.search(r"\.tr-transitions-destruction \.tds-r0\{[^}]+\}", css).group(0)
    ring1 = re.search(r"\.tr-transitions-destruction \.tds-r1\{[^}]+\}", css).group(0)
    ring2 = re.search(r"\.tr-transitions-destruction \.tds-r2\{[^}]+\}", css).group(0)
    assert "#1b263b" in face_a
    assert "#e07a5f" in face_b
    assert "255,100,0" in ring0
    assert "255,50,0" in ring1
    assert "200,30,0" in ring2
    block = css.split(".tr-transitions-destruction", 1)[1]
    assert "Inter" in block
    assert "#778da9" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    assert "#ffc300" not in block
    assert "text-transform" not in block
    stage = re.search(r"\.tr-transitions-destruction \.tds-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-transitions-destruction", 1)[1]


def test_transitions_light_slides_leaks_with_x_without_css_transform(ctx):
    """Каталог DEMO 1 едет x бликов; здесь GSAP x на 9:16, без filter."""
    piece = render_transition("transitions_light", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-transitions-light" in node
    assert "tlt-stage" in node
    assert "tlt-face" in node and "tlt-a" in node and "tlt-b" in node
    assert "tlt-warm" in node
    assert "tlt-blob" in node and "tlt-l1" in node and "tlt-l2" in node
    assert "ONE" in node and "TWO" in node
    assert "SCENE A" in node and "SCENE B" in node
    assert "position:absolute" not in node.split("tlt-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "x:169" in body
    assert "x:338" in body
    assert "x:112" in body
    assert "x:225" in body
    assert "sine.inOut" in body
    assert "power1.in" in body
    assert "power2.in" in body
    assert "power2.out" in body
    assert "power1.out" in body
    assert "immediateRender:false" in body
    assert "filter" not in body
    assert "skewX" not in body
    assert "rotationY" not in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "visibility" not in body
    assert "clipPath" not in body
    assert "zIndex" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _tlt_times(ctx.duration)
    assert times["warm_in_at"] + times["warm_in_dur"] + 0.001 <= times["warm_peak_at"] + 1e-9
    assert times["warm_peak_at"] + times["warm_peak_dur"] + 0.001 <= times["warm_out_at"] + 1e-9
    assert times["l1_in_at"] + times["l1_in_dur"] + 0.001 <= times["l1_out_at"] + 1e-9
    assert times["l2_in_at"] + times["l2_in_dur"] + 0.001 <= times["l2_out_at"] + 1e-9
    assert times["warm_out_at"] + times["warm_out_dur"] <= ctx.duration + 1e-9
    assert times["l1_out_at"] + times["l1_out_dur"] <= ctx.duration + 1e-9
    assert times["l2_out_at"] + times["l2_out_dur"] <= ctx.duration + 1e-9
    assert times["swap_at"] <= times["warm_out_at"] + 1e-9
    short = _tlt_times(0.22)
    assert short["l2_out_at"] + short["l2_out_dur"] <= 0.22 + 1e-9
    assert short["warm_out_at"] + short["warm_out_dur"] <= 0.22 + 1e-9
    leak = render_transition("light_leak", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11))
    assert "tr-transitions-light" not in leak.nodes[0]
    assert "tr-light-leak" in leak.nodes[0]
    sweep = render_transition("light_sweep", TemplateCtx(
        index=2, start=0.0, duration=0.2, target="shot-02", track=11))
    assert "tr-transitions-light" not in sweep.nodes[0]
    assert 'class="clip tr-sweep"' in sweep.nodes[0]
    flash = render_transition("white_flash", TemplateCtx(
        index=4, start=0.0, duration=0.2, target="shot-04", track=11))
    assert "tr-transitions-light" not in flash.nodes[0]
    dest = render_transition("transitions_destruction", TemplateCtx(
        index=5, start=0.0, duration=0.2, target="shot-05", track=11))
    assert "tr-transitions-light" not in dest.nodes[0]
    cover = render_transition("transitions_cover", TemplateCtx(
        index=6, start=0.0, duration=0.2, target="shot-06", track=11))
    assert "tr-transitions-light" not in cover.nodes[0]


def test_transitions_light_keeps_catalog_orange_leaks():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-transitions-light" in css
    face_a = re.search(r"\.tr-transitions-light \.tlt-a\{[^}]+\}", css).group(0)
    face_b = re.search(r"\.tr-transitions-light \.tlt-b\{[^}]+\}", css).group(0)
    warm = re.search(r"\.tr-transitions-light \.tlt-warm\{[^}]+\}", css).group(0)
    blob1 = re.search(r"\.tr-transitions-light \.tlt-l1\{[^}]+\}", css).group(0)
    blob2 = re.search(r"\.tr-transitions-light \.tlt-l2\{[^}]+\}", css).group(0)
    assert "#1b263b" in face_a
    assert "#e07a5f" in face_b
    assert "255,165,0" in warm
    assert "255,140,0" in blob1
    assert "255,200,0" in blob2
    block = css.split(".tr-transitions-light", 1)[1]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    assert "text-transform" not in block
    stage = re.search(r"\.tr-transitions-light \.tlt-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-transitions-light", 1)[1]


def test_transitions_other_flashes_white_without_css_transform(ctx):
    """Каталог DEMO 1 твинит opacity вспышки; здесь без filter и без .clip."""
    piece = render_transition("transitions_other", TemplateCtx(**ctx.__dict__))
    node = piece.nodes[0]
    assert "tr-transitions-other" in node
    assert "tto-stage" in node
    assert "tto-face" in node and "tto-a" in node and "tto-b" in node
    assert "tto-flash" in node
    assert "ONE" in node and "TWO" in node
    assert "SCENE A" in node and "SCENE B" in node
    assert "position:absolute" not in node.split("tto-stage", 1)[0]
    assert node.count(f'id="tr-{ctx.index:02d}"') == 1
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    body = " ".join(piece.tweens)
    assert f'"#{ctx.target}"' not in body
    assert "power4.out" in body
    assert "power2.out" in body
    assert "immediateRender:false" in body
    assert "opacity:1" in body
    assert "opacity:0" in body
    assert "filter" not in body
    assert "skewX" not in body
    assert "rotationY" not in body
    assert "webgl" not in body.lower()
    assert "onUpdate" not in body
    assert "textContent" not in body
    assert "innerHTML" not in body
    assert "getBoundingClientRect" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "visibility" not in body
    assert "clipPath" not in body
    assert "zIndex" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    clip = f"#tr-{ctx.index:02d}"
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != clip, tween
        assert selector.startswith(clip + "-")
    times = _tto_times(ctx.duration)
    assert times["flash_in_at"] + times["flash_in_dur"] + 0.001 <= times["flash_out_at"] + 1e-9
    assert times["flash_out_at"] + times["flash_out_dur"] <= ctx.duration + 1e-9
    assert times["swap_at"] <= times["flash_out_at"] + 1e-9
    short = _tto_times(0.22)
    assert short["flash_out_at"] + short["flash_out_dur"] <= 0.22 + 1e-9
    assert short["flash_in_at"] + short["flash_in_dur"] + 0.001 <= short["flash_out_at"] + 1e-9
    flash = render_transition("white_flash", TemplateCtx(
        index=4, start=0.0, duration=0.2, target="shot-04", track=11))
    assert "tr-transitions-other" not in flash.nodes[0]
    assert "tr-flash" in flash.nodes[0]
    leak = render_transition("light_leak", TemplateCtx(
        index=1, start=0.0, duration=0.2, target="shot-01", track=11))
    assert "tr-transitions-other" not in leak.nodes[0]
    light = render_transition("transitions_light", TemplateCtx(
        index=7, start=0.0, duration=0.2, target="shot-07", track=11))
    assert "tr-transitions-other" not in light.nodes[0]
    dest = render_transition("transitions_destruction", TemplateCtx(
        index=5, start=0.0, duration=0.2, target="shot-05", track=11))
    assert "tr-transitions-other" not in dest.nodes[0]
    cover = render_transition("transitions_cover", TemplateCtx(
        index=6, start=0.0, duration=0.2, target="shot-06", track=11))
    assert "tr-transitions-other" not in cover.nodes[0]


def test_transitions_other_keeps_catalog_navy_terra_and_white_flash():
    from src.lib.config import load_config

    css = transition_css(load_config().brandbook)
    assert ".tr-transitions-other" in css
    face_a = re.search(r"\.tr-transitions-other \.tto-a\{[^}]+\}", css).group(0)
    face_b = re.search(r"\.tr-transitions-other \.tto-b\{[^}]+\}", css).group(0)
    flash = re.search(r"\.tr-transitions-other \.tto-flash\{[^}]+\}", css).group(0)
    assert "#1b263b" in face_a
    assert "#e07a5f" in face_b
    assert "#ffffff" in flash
    block = css.split(".tr-transitions-other", 1)[1]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    assert "text-transform" not in block
    stage = re.search(r"\.tr-transitions-other \.tto-stage\{[^}]+\}", css).group(0)
    assert "position:relative" in stage
    assert "position:absolute" not in stage
    stripped = css.replace("transform-origin:50% 50%", "")
    assert "transform:" not in stripped.split(".tr-transitions-other", 1)[1]


def test_animated_bar_chart_keeps_catalog_ink_and_paper():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".abc-chart" in css
    assert ".abc-card" in css
    chart = re.search(r"\.abc-chart\{[^}]+\}", css).group(0)
    card = re.search(r"\.abc-card\{[^}]+\}", css).group(0)
    fill = re.search(r"\.abc-fill\{[^}]+\}", css).group(0)
    grow = re.search(r"\.abc-grow\{[^}]+\}", css).group(0)
    title = re.search(r"\.abc-title\{[^}]+\}", css).group(0)
    kpi = re.search(r"\.abc-kpi\{[^}]+\}", css).group(0)
    assert "#f7f7f8" in chart
    assert "#ffffff" in card
    assert "17,24,39" in fill
    assert "#111827" in title
    assert "#111827" in kpi
    assert "transform-origin:50% 50%" in grow
    block = css.split(".abc-chart", 1)[1].split(".bcr-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    assert "text-transform" not in block
    assert "--hf-grow" not in block
    assert "--hf-dash" not in block
    stripped = css.replace("transform-origin:50% 50%", "")
    abc_only = stripped.split(".abc-chart", 1)[1].split(".bcr-chart", 1)[0]
    assert "transform:" not in abc_only
    dv_bar = re.search(r"\.dv-bar\{[^}]+\}", css).group(0)
    assert "abc-" not in dv_bar
    assert "bcr-" not in dv_bar
    assert "cst-" not in dv_bar
    assert "cpr-" not in dv_bar
    assert "dcl-" not in dv_bar
    assert "transform-origin:left center" in dv_bar


def test_bar_chart_race_keeps_catalog_ink_paper_and_accent():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".bcr-chart" in css
    assert ".bcr-bar" in css
    chart = re.search(r"\.bcr-chart\{[^}]+\}", css).group(0)
    bar = re.search(r"\.bcr-bar\{[^}]+\}", css).group(0)
    bg = re.search(r"\.bcr-bg\{[^}]+\}", css).group(0)
    title = re.search(r"\.bcr-title\{[^}]+\}", css).group(0)
    caption = re.search(r"\.bcr-period-caption\{[^}]+\}", css).group(0)
    assert "#f5f3ef" in chart and "#f5f3ef" in bg
    assert "#1f1d1b" in chart and "#1f1d1b" in bar and "#1f1d1b" in title
    assert "transform-origin:left center" in bar
    assert "text-transform:uppercase" in caption
    block = css.split(".bcr-chart", 1)[1].split(".cst-chart", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    stripped = (css.replace("transform-origin:left center", "")
                .replace("transform-origin:50% 50%", "")
                .replace("text-transform:uppercase", ""))
    bcr_only = stripped.split(".bcr-chart", 1)[1].split(".cst-chart", 1)[0]
    assert "transform:" not in bcr_only
    dv_bar = re.search(r"\.dv-bar\{[^}]+\}", css).group(0)
    assert "bcr-" not in dv_bar
    assert "cst-" not in dv_bar
    assert "cpr-" not in dv_bar
    assert "dcl-" not in dv_bar


def test_chart_story_keeps_catalog_ink_paper_and_accent():
    from src.lib.config import load_config

    css = dataviz_css(load_config().brandbook)
    assert ".cst-chart" in css
    assert ".cst-bar" in css
    chart = re.search(r"\.cst-chart\{[^}]+\}", css).group(0)
    bg = re.search(r"\.cst-bg\{[^}]+\}", css).group(0)
    axis = re.search(r"\.cst-axis\{[^}]+\}", css).group(0)
    bar = re.search(r"\.cst-bar\{[^}]+\}", css).group(0)
    call = re.search(r"\.cst-call\{[^}]+\}", css).group(0)
    assert "#0a0a0a" in chart
    assert "#0a0a0a" in bg
    assert "#f8fafc" in chart
    assert "#475569" in axis
    assert "transform-origin:left center" in axis
    assert "transform-origin:50% 100%" in bar
    assert "transform-origin:50% 100%" in call
    block = css.split(".cst-chart", 1)[1].split(".cpr-chart", 1)[0]
    assert "Inter" in block
    assert "JetBrains Mono" in block
    assert "-apple-system" not in block
    assert "#C8453D" not in block
    assert "#00E5C7" not in block
    assert "#00E5FF" not in block
    assert "text-transform" not in block
    stripped = (css.replace("transform-origin:left center", "")
                .replace("transform-origin:50% 50%", "")
                .replace("transform-origin:50% 100%", ""))
    assert "transform:" not in stripped.split(".cst-chart", 1)[1].split(".cpr-chart", 1)[0]
    dv_bar = re.search(r"\.dv-bar\{[^}]+\}", css).group(0)
    assert "cst-" not in dv_bar
    assert "cpr-" not in dv_bar
    assert "dcl-" not in dv_bar


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
    "ai_chat_reveal": {
        "userMessage": "How do I turn my HTML into real video?",
        "answer1": "You do not need an editor. REDSHIFT renders HTML.",
        "answer2": "It is markup, not magic.",
        "answer3": "What you get out of the box:",
        "bullet1": "A catalog of motion primitives you install and own",
        "bullet2": "GSAP timelines that seek to any frame",
        "bullet3": "9:16 renders from a single pipeline",
        "ecHeadline": "It's not magic.|It's HTML.",
        "ecCta": "Try REDSHIFT",
        "ecFooter": "REDSHIFT.SHORTS",
    },
    "app_showcase": {
        "tagline": "Unleash Full Potential",
        "cta": "START NOW",
        "name": "James Medrano",
        "subtitle": "Premium Member",
    },
    "vpn_youtube_spot": {},
    "blue_sweater": {},
    "chatgpt_exchange": {
        "prompt": "Hey what is the best tool for ai avatars",
        "intro1": "It depends on what you do.",
        "intro2": "Here is how I rank them today:",
        "row1Tool": "HeyGen",
    },
    "claude_exchange": {
        "prompt": "What is the best tool for ai avatars",
        "thinking": "Weighing accuracy against market…",
        "lead": "I will search for the current state.",
        "search": "best AI avatar video generator 2026",
        "answer1": "It depends on what you are making.",
        "answer2": "HeyGen is where most teams land.",
    },
    "message_thread_reveal": {
        "contactName": "Rachel",
        "questionMessage": "what r u using for the launch video",
        "teaserMessage": "wait look",
        "cardTitle": "HyperFrames | Write HTML",
        "cardDomain": "hyperframes.heygen.com",
        "reactionMessage": "OMG IT IS HTML",
    },
    "notes_reveal": {
        "titleL1": "Things nobody told me",
        "titleL2": "about video",
        "noteLine1": "my videos sucked",
        "cardTop": "THE POWER",
        "brandDomain": "hyperframes.heygen.com",
    },
    "notification_cascade": {
        "notifTitle": "New render",
        "message1": "Launch video is ready.",
        "appName": "HyperFrames",
        "headlineTop": "SHIP VIDEO",
        "headlineAccent": "FROM HTML",
        "footerText": "hyperframes.heygen.com",
    },
    "instagram_follow": {
        "displayName": "HeyGen",
        "handle": "@heygen_official",
        "followers": "47.5K followers",
        "buttonText": "Follow",
        "followingText": "Following",
    },
    "tiktok_follow": {
        "displayName": "HeyGen",
        "handle": "@heygen.com",
        "followers": "1,999 followers",
        "buttonText": "Follow",
        "followingText": "Following",
    },
    "yt_lower_third": {
        "channelName": "HeyGen",
        "subscriberCount": "82.2K subscribers",
        "buttonText": "Subscribe",
        "subscribedText": "Subscribed",
    },
    "x_post": {
        "displayName": "Hyperframes",
        "handle": "@hyperframes",
        "text": "Write HTML, render pixel-perfect video. Zero external dependencies, pure web standards. #HyperFrames",
        "timestamp": "1:10 PM · Apr 7, 2026",
        "replies": "34",
        "reposts": "2.3K",
        "likes": "10.9K",
        "likesActive": "11.0K",
        "views": "150K",
    },
    "reddit_post": {
        "subreddit": "r/hyperframes",
        "author": "u/developer · 3h",
        "title": "Writing HTML to render video changed everything for our pipeline",
        "body": "Zero external dependencies, pure web standards, and pixel-perfect 4K rendering in seconds. The whole workflow runs headlessly.",
        "votes": "4.2k",
        "votesActive": "4.3k",
        "comments": "328",
    },
    "spotify_card": {
        "trackName": "HyperFrames",
        "artistName": "HeyGen",
        "brandText": "Spotify",
    },
    "macos_notification": {
        "appName": "HyperFrames",
        "time": "now",
        "title": "Build complete",
        "body": "Video rendered in 1.4s with zero frame drops.",
        "iconText": "HF",
    },
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
    assert "acr-" not in node
    assert "ai-chat-reveal" not in node


def test_ai_chat_reveal_types_spans_not_textcontent():
    """Catalog writes textContent / autoAlpha; here baked spans and opacity."""
    ctx = TemplateCtx(index=0, start=0.0, duration=19.333, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["ai_chat_reveal"])
    piece = render_overlay("ai_chat_reveal", ctx)
    node = piece.nodes[0]
    assert "ai-chat-reveal" in node
    assert "acr-keyboard" in node and "acr-composer" in node
    assert "acr-bubble" in node and "How do I turn my HTML" in node
    assert "Ask anything" in node
    assert "qwertyuiop" not in node.replace("acr-key", "")
    assert "acr-key" in node and ">q<" in node and ">p<" in node
    assert "REDSHIFT" in node and "РЕДШИФТ" in node
    assert "Try REDSHIFT" in node
    assert "not magic" in node
    assert "HTML." in node
    assert "acr-w" in node and "acr-ch" in node
    assert "ct-row" not in node
    assert "chat-thread" not in node
    assert "textContent" not in node
    assert "autoAlpha" not in node
    assert "Math.random" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    assert "-apple-system" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "autoAlpha" not in body
    assert "visibility" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    assert 'y:482' in body and "y:-497" in body
    assert 'color:"#767676"' in body and 'color:"#141414"' in body
    assert "power2.out" in body and "power1.inOut" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("ai_chat_reveal", TemplateCtx(
        index=0, start=0.0, duration=19.333, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_ai_chat_reveal_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".ai-chat-reveal" in css
    assert ".acr-keyboard" in css
    assert ".acr-endcard-inner" in css
    root = re.search(r"\.ai-chat-reveal\{[^}]+\}", css).group(0)
    kbd = re.search(r"\.ai-chat-reveal \.acr-keyboard\{[^}]+\}", css).group(0)
    cta = re.search(r"\.ai-chat-reveal \.acr-eccta\{[^}]+\}", css).group(0)
    inner = re.search(r"\.ai-chat-reveal \.acr-endcard-inner\{[^}]+\}", css).group(0)
    assert "Inter" in root
    assert "-apple-system" not in css.split(".ai-chat-reveal", 1)[1]
    assert "#d2d5e0" in kbd
    assert "#3ce6ac" in cta
    assert "#14110e" in inner and "#221b13" in inner
    block = css.split(".ai-chat-reveal", 1)[1]
    assert "HyperFrames" not in block
    chat = render_overlay("chat_thread", TemplateCtx(
        index=0, start=1.0, duration=3.0, target="ovl-00",
        track=5, params=OVERLAY_PARAMS["chat_thread"])).nodes[0]
    assert "acr-" not in chat
    assert "aps-" not in chat
    assert "app-showcase" not in chat


def test_chatgpt_exchange_bakes_spans_not_textcontent():
    """Catalog writes textContent and animates heights; here baked spans, opacity and scale."""
    ctx = TemplateCtx(index=0, start=0.0, duration=14.9, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["chatgpt_exchange"])
    piece = render_overlay("chatgpt_exchange", ctx)
    node = piece.nodes[0]
    assert "chatgpt-exchange" in node
    assert "cge-keyboard" in node and "cge-composer" in node
    assert "cge-bubble" in node and "Hey what is the best tool for ai avatars" in node
    assert "Ask ChatGPT" in node
    assert "cge-key" in node and ">Q<" in node and ">P<" in node
    assert "HeyGen" in node and "Synthesia" in node
    assert "cge-w" in node and "cge-ch" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    assert "-apple-system" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body or "scaleX:" in body
    assert "opacity:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("chatgpt_exchange", TemplateCtx(
        index=0, start=0.0, duration=14.9, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_chatgpt_exchange_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".chatgpt-exchange" in css
    assert ".cge-composer" in css
    assert ".cge-keyboard" in css
    block = css.split(".chatgpt-exchange", 1)[1].split(".sfb-board", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block


def test_claude_exchange_bakes_spans_not_textcontent():
    """Catalog writes textContent and animates heights; here baked spans, opacity and scale."""
    ctx = TemplateCtx(index=0, start=0.0, duration=21.4, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["claude_exchange"])
    piece = render_overlay("claude_exchange", ctx)
    node = piece.nodes[0]
    assert "claude-exchange" in node
    assert "cle-keyboard" in node and "cle-composer" in node
    assert "cle-bubble" in node and "What is the best tool for ai avatars" in node
    assert "Chat with Claude" in node
    assert "cle-key" in node and ">Q<" in node and ">P<" in node
    assert "HeyGen" in node
    assert "cle-w" in node and "cle-ch" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    assert "-apple-system" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body or "scaleX:" in body
    assert "opacity:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("claude_exchange", TemplateCtx(
        index=0, start=0.0, duration=21.4, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_claude_exchange_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".claude-exchange" in css
    assert ".cle-composer" in css
    assert ".cle-keyboard" in css
    block = css.split(".claude-exchange", 1)[1].split(".sfb-board", 1)[0]
    assert "Inter" in block
    assert "-apple-system" not in block


def test_message_thread_reveal_bakes_spans_not_textcontent():
    """Catalog writes textContent and animates heights; here baked spans, opacity and scale."""
    ctx = TemplateCtx(index=0, start=0.0, duration=25.8, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["message_thread_reveal"])
    piece = render_overlay("message_thread_reveal", ctx)
    node = piece.nodes[0]
    assert "message-thread-reveal" in node
    assert "mtr-chatview" in node and "mtr-composer" in node
    assert "what r u using for the launch video" in node
    assert "Rachel" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body or "scaleX:" in body
    assert "opacity:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("message_thread_reveal", TemplateCtx(
        index=0, start=0.0, duration=25.8, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_message_thread_reveal_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".message-thread-reveal" in css
    assert ".mtr-chatview" in css
    assert ".mtr-composer" in css
    block = css.split(".message-thread-reveal", 1)[1].split(".sfb-board", 1)[0]
    assert "Inter" in block


def test_notes_reveal_bakes_spans_not_textcontent():
    """Catalog writes textContent and animates heights; here baked spans, opacity and transform."""
    ctx = TemplateCtx(index=0, start=0.0, duration=24.9, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["notes_reveal"])
    piece = render_overlay("notes_reveal", ctx)
    node = piece.nodes[0]
    assert "notes-reveal" in node
    assert "nr-notescene" in node and "nr-cardscene" in node
    assert "Things nobody told me" in node
    assert ">my<" in node and ">videos<" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body or "scaleX:" in body
    assert "opacity:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("notes_reveal", TemplateCtx(
        index=0, start=0.0, duration=24.9, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_notes_reveal_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".notes-reveal" in css
    assert ".nr-notescene" in css
    assert ".nr-cardscene" in css
    block = css.split(".notes-reveal", 1)[1].split(".notification-cascade", 1)[0]
    assert "Inter" in block


def test_notification_cascade_animates_without_forbidden_properties():
    """Catalog restacks banners with expo.out; here y/scale/opacity, no forbidden props."""
    ctx = TemplateCtx(index=0, start=0.0, duration=14.0, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["notification_cascade"])
    piece = render_overlay("notification_cascade", ctx)
    node = piece.nodes[0]
    assert "notification-cascade" in node
    assert "nc-stack-inner" in node and "nc-endcard" in node
    assert "New render" in node
    assert "Launch video is ready." in node
    assert "SHIP VIDEO" in node
    assert "FROM HTML" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    assert "-apple-system" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body or "scaleX:" in body
    assert "opacity:" in body
    assert "y:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("notification_cascade", TemplateCtx(
        index=0, start=0.0, duration=14.0, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_notification_cascade_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".notification-cascade" in css
    assert ".nc-banner" in css
    assert ".nc-endcard" in css
    block = css.split(".notification-cascade", 1)[1].split(".instagram-follow", 1)[0]
    assert "Inter" in block


def test_instagram_follow_animates_without_forbidden_properties():
    """Catalog bounces button and crossfades text; here y/scale/opacity/backgroundColor, no forbidden props."""
    ctx = TemplateCtx(index=0, start=0.0, duration=4.5, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["instagram_follow"])
    piece = render_overlay("instagram_follow", ctx)
    node = piece.nodes[0]
    assert "instagram-follow" in node
    assert "if-card" in node and "if-follow-btn" in node
    assert "HeyGen" in node
    assert "@heygen_official" in node
    assert "47.5K followers" in node
    assert "Follow" in node
    assert "Following" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    assert "-apple-system" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body
    assert "opacity:" in body
    assert "y:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("instagram_follow", TemplateCtx(
        index=0, start=0.0, duration=4.5, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_instagram_follow_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".instagram-follow" in css
    assert ".if-card" in css
    assert ".if-follow-btn" in css
    block = css.split(".instagram-follow", 1)[1].split(".tiktok-follow", 1)[0]
    assert "Inter" in block


def test_tiktok_follow_animates_without_forbidden_properties():
    """Catalog bounces button and crossfades text; here y/scale/opacity/backgroundColor, no forbidden props."""
    ctx = TemplateCtx(index=0, start=0.0, duration=4.5, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["tiktok_follow"])
    piece = render_overlay("tiktok_follow", ctx)
    node = piece.nodes[0]
    assert "tiktok-follow" in node
    assert "tf-card" in node and "tf-follow-btn" in node
    assert "HeyGen" in node
    assert "@heygen.com" in node
    assert "1,999 followers" in node
    assert "Follow" in node
    assert "Following" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    assert "-apple-system" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body
    assert "opacity:" in body
    assert "y:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("tiktok_follow", TemplateCtx(
        index=0, start=0.0, duration=4.5, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_tiktok_follow_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".tiktok-follow" in css
    assert ".tf-card" in css
    assert ".tf-follow-btn" in css
    block = css.split(".tiktok-follow", 1)[1].split(".yt-lower-third", 1)[0]
    assert "Inter" in block


def test_yt_lower_third_animates_without_forbidden_properties():
    """Catalog bounces button and crossfades text; here y/scale/opacity/backgroundColor, no forbidden props."""
    ctx = TemplateCtx(index=0, start=0.0, duration=4.5, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["yt_lower_third"])
    piece = render_overlay("yt_lower_third", ctx)
    node = piece.nodes[0]
    assert "yt-lower-third" in node
    assert "ylt-card" in node and "ylt-subscribe-btn" in node
    assert "HeyGen" in node
    assert "82.2K subscribers" in node
    assert "Subscribe" in node
    assert "Subscribed" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    assert "DM Sans" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body
    assert "opacity:" in body
    assert "y:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("yt_lower_third", TemplateCtx(
        index=0, start=0.0, duration=4.5, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_yt_lower_third_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".yt-lower-third" in css
    assert ".ylt-card" in css
    assert ".ylt-subscribe-btn" in css
    block = css.split(".yt-lower-third", 1)[1].split(".x-post", 1)[0]
    assert "Inter" in block


def test_x_post_animates_without_forbidden_properties():
    """Catalog bounces heart and updates text via opacity; here y/scale/opacity, no forbidden props."""
    ctx = TemplateCtx(index=0, start=0.0, duration=5.0, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["x_post"])
    piece = render_overlay("x_post", ctx)
    node = piece.nodes[0]
    assert "x-post" in node
    assert "xp-card" in node and "xp-like-btn" in node
    assert "Hyperframes" in node
    assert "@hyperframes" in node
    assert "Write HTML" in node
    assert "10.9K" in node
    assert "11.0K" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body
    assert "opacity:" in body
    assert "y:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("x_post", TemplateCtx(
        index=0, start=0.0, duration=5.0, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_x_post_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".x-post" in css
    assert ".xp-card" in css
    assert ".xp-like-btn" in css
    block = css.split(".x-post", 1)[1].split(".reddit-post", 1)[0]
    assert "Inter" in block


def test_reddit_post_animates_without_forbidden_properties():
    """Catalog bounces arrow and updates text via opacity; here y/scale/opacity, no forbidden props."""
    ctx = TemplateCtx(index=0, start=0.0, duration=5.0, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["reddit_post"])
    piece = render_overlay("reddit_post", ctx)
    node = piece.nodes[0]
    assert "reddit-post" in node
    assert "rp-card" in node and "rp-vote-btn" in node
    assert "r/hyperframes" in node
    assert "u/developer" in node
    assert "Writing HTML" in node
    assert "4.2k" in node
    assert "4.3k" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body
    assert "opacity:" in body
    assert "y:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("reddit_post", TemplateCtx(
        index=0, start=0.0, duration=5.0, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_reddit_post_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".reddit-post" in css
    assert ".rp-card" in css
    assert ".rp-vote-btn" in css
    block = css.split(".reddit-post", 1)[1].split(".spotify-card", 1)[0]
    assert "Inter" in block


def test_spotify_card_animates_without_forbidden_properties():
    """Catalog breathes album art and staggers text; here y/scale/opacity, no forbidden props."""
    ctx = TemplateCtx(index=0, start=0.0, duration=5.0, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["spotify_card"])
    piece = render_overlay("spotify_card", ctx)
    node = piece.nodes[0]
    assert "spotify-card" in node
    assert "sc-card" in node and "sc-album-art" in node
    assert "HyperFrames" in node
    assert "HeyGen" in node
    assert "Spotify" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "scale:" in body
    assert "opacity:" in body
    assert "y:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("spotify_card", TemplateCtx(
        index=0, start=0.0, duration=5.0, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_spotify_card_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".spotify-card" in css
    assert ".sc-card" in css
    assert ".sc-album-art" in css
    block = css.split(".spotify-card", 1)[1].split(".macos-notification", 1)[0]
    assert "Inter" in block


def test_macos_notification_animates_without_forbidden_properties():
    """Catalog slides from right; here x/opacity, no forbidden props."""
    ctx = TemplateCtx(index=0, start=0.0, duration=5.0, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["macos_notification"])
    piece = render_overlay("macos_notification", ctx)
    node = piece.nodes[0]
    assert "macos-notification" in node
    assert "mn-card" in node and "mn-app-icon" in node
    assert "HyperFrames" in node
    assert "Build complete" in node
    assert "Video rendered" in node
    assert "textContent" not in node
    assert "filter:" not in node
    assert "clip-path" not in node
    body = " ".join(piece.tweens)
    assert "textContent" not in body
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "height:" not in body
    assert "filter:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "opacity:" in body
    assert "x:" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    empty = render_overlay("macos_notification", TemplateCtx(
        index=0, start=0.0, duration=5.0, target="ovl-01", track=5, params={}))
    assert empty.nodes == []


def test_macos_notification_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".macos-notification" in css
    assert ".mn-card" in css
    assert ".mn-app-icon" in css
    block = css.split(".macos-notification", 1)[1].split(".sfb-board", 1)[0]
    assert "Inter" in block






def test_app_showcase_fans_phones_without_width_or_dash():
    """Catalog tweens width / strokeDashoffset; here scaleX / rotation / mask."""
    ctx = TemplateCtx(index=0, start=0.0, duration=5.5, target="ovl-00",
                      track=5, params=OVERLAY_PARAMS["app_showcase"])
    piece = render_overlay("app_showcase", ctx)
    node = piece.nodes[0]
    assert "app-showcase" in node
    assert "aps-phone" in node and "aps-side-c" in node
    assert "Unleash Full Potential" in node
    assert "START NOW" in node
    assert "James Medrano" in node
    assert "Weekly Goal" in node and "Burned Calories" in node
    assert "Running" in node and "Cycling" in node and "Strength" in node
    assert "acr-" not in node
    assert "chat-thread" not in node
    assert "pm-body" not in node
    assert "strokeDashoffset" not in node
    assert "textContent" not in node
    assert "Math.random" not in node
    assert "-apple-system" not in node
    assert "DM Sans" not in node
    body = " ".join(piece.tweens)
    assert "strokeDashoffset" not in body
    assert "width:" not in body
    assert "visibility" not in body
    assert "clip-path" not in body
    assert "Math.random" not in body
    assert "repeat:-1" not in body.replace(" ", "")
    assert "scaleX:0" in body and "scaleX:1" in body
    assert "rotation:-180" in body
    assert "back.out(1.4)" in body and "expo.out" in body and "circ.out" in body
    extra = _tweened_props(piece.tweens) - ALLOWED_PROPS
    assert not extra
    for tween in piece.tweens:
        selector = re.search(r'tl\.(?:fromTo|to|set)\("(#[^"]+)"', tween).group(1)
        assert selector != "#ovl-00", tween
        assert selector.startswith("#ovl-00-")
    ids = re.findall(r'id="([^"]+)"', node)
    assert len(ids) == len(set(ids))
    custom = render_overlay("app_showcase", TemplateCtx(
        index=0, start=0.0, duration=5.5, target="ovl-01", track=5,
        params={"tagline": "Train every morning", "name": "Maya Chen"}))
    assert "Train every morning" in custom.nodes[0]
    assert "Maya Chen" in custom.nodes[0]
    assert "MC" in custom.nodes[0]


def test_app_showcase_keeps_catalog_tokens():
    from src.lib.config import load_config

    css = overlay_css(load_config().brandbook)
    assert ".app-showcase" in css
    assert ".aps-phone" in css
    root = re.search(r"\.app-showcase\{[^}]+\}", css).group(0)
    cta = re.search(r"\.app-showcase \.aps-cta\{[^}]+\}", css).group(0)
    bg = re.search(r"\.app-showcase \.aps-bg\{[^}]+\}", css).group(0)
    assert "Inter" in root
    assert "-apple-system" not in css.split(".app-showcase", 1)[1]
    assert "DM Sans" not in css.split(".app-showcase", 1)[1]
    assert "#e4fa72" in cta
    assert "#f1f2ec" in bg
    assert "#271f15" in css.split(".app-showcase", 1)[1]
    phone = render_overlay("source_card", TemplateCtx(
        index=0, start=1.0, duration=3.0, target="ovl-00",
        track=5, params=OVERLAY_PARAMS["source_card"])).nodes[0]
    assert "aps-" not in phone
    assert "app-showcase" not in phone
    mock = render_hero("hero-phone-mock", _hero_ctx("hero-phone-mock")).nodes[0]
    assert "aps-" not in mock
    assert "app-showcase" not in mock


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

def test_scene_follows_the_topic_of_the_video():
    """Сцена выбирается темой ролика, и короткая основа обязана совпасть.

    «Чёрная дыра» — основа «дыр», три буквы. У знаков такая основа сверяется
    словом целиком, и ролик про горизонт событий получал нейтральную комнату:
    «дыры» ≠ «дыр». У сцен правило другое (см. :func:`src.lib.backdrop._matches`),
    и проверяется здесь именно этот случай.
    """
    from src.lib.backdrop import DEFAULT_SCENE, pick_scene

    assert pick_scene("Что происходит внутри чёрной дыры") == "horizon"
    assert pick_scene("", "Кубит держится доли секунды") == "grid"
    assert pick_scene("Ракета села на баржу") == "space"
    assert pick_scene("Как они делят деньги") == "room"
    # Тема не опознана — фон нейтральный, а не случайный.
    assert pick_scene("Просто разговор ни о чём") == DEFAULT_SCENE


def test_every_scene_is_drawn_and_has_a_tone():
    """Сцена без стилей — белый прямоугольник за ведущим, молча."""
    from src.lib.backdrop import SCENES, backdrop_css, describe, tone

    css = backdrop_css()
    for name in SCENES:
        assert f".vfx.scene-{name}{{" in css, name
        assert tone(name) in ("dark", "light"), name
        assert describe(name), name


def test_text_on_a_dark_stage_does_not_stay_ink_black():
    """То, что лежит прямо на фоне, обязано менять цвет вместе с ним.

    Заголовок за головой, тема, знаки и накопительный список рисуются поверх
    сцены без подложки. На тёмной сцене чернильный цвет из брендбука пропадает
    в фоне — цвет берётся из ``--color-on-stage``, а тон сцены его переключает.
    """
    from src.lib.config import load_config
    from src.lib.render.hyperframes.brand_css import build_css

    css = build_css(load_config().brandbook, fonts={})
    assert "--color-on-stage" in css
    dark = re.search(r"(?<![#\w-])\.stage-dark\{([^}]*)\}", css)
    assert dark, "тёмная сцена не переопределяет цвет надписей на фоне"
    assert "--color-on-stage" in dark.group(1)

    on_stage = (".hero-title-behind .tb-head", ".hero-log .lg-row",
                ".hero-icons", ".hero-headline .hh-kicker")
    for selector in on_stage:
        # Правил у селектора может быть несколько: цвет достаточно задать в
        # одном из них.
        rules = [m.group(2) for m in
                 re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
                 if selector in m.group(1)]
        assert rules, selector
        assert any("var(--color-on-stage)" in body for body in rules), selector


def test_typed_chunks_do_not_run_together():
    """Пробел в `::after` внутри `inline-block` схлопывается и не рисуется.

    На кадре это читалось как «комокгаза»: два куска карточки встык. Отступ
    ставится полем блока, а не текстовым узлом внутри него.
    """
    from src.lib.config import load_config
    from src.lib.render.hyperframes.brand_css import build_css

    css = build_css(load_config().brandbook, fonts={})
    rules = [r for r in css.split("}") if ".bt-chunk" in r and "inline-block" in r]
    assert rules, "кусок карточки перестал быть блочным"
    assert "margin-right" in rules[0], rules[0]
    assert ".bt-chunk::after" not in css, "пробел снова внутри блока"


# --- экспонат (§5.4) ----------------------------------------------------------

def test_the_exhibit_label_never_rides_over_the_picture():
    """На 0047 «ФИЗИКУ» было закрыто материалом ровно наполовину.

    Подпись прижималась к низу плиты, и, переросши остаток высоты, лезла вверх
    — под картинку. Проверяется геометрией, а не глазами: подпись начинается
    ниже нижнего края материала и в плиту укладывается целиком.
    """
    from src.lib.config import load_config
    from src.lib.render.hyperframes.templates import EX_PIC, EX_PLATE_H, hero_css

    css = hero_css(load_config().brandbook)
    rule = re.search(r"\.hero-exhibit\{([^}]*)\}", css).group(1)
    pad_top = int(re.search(r"padding:(\d+)px", rule).group(1))
    assert pad_top >= EX_PIC[1] + EX_PIC[3], "подпись начинается выше картинки"
    # Имя 88 px, уточнение в две строки по 38 px и кредит 24 px с полями по 14.
    assert EX_PLATE_H - pad_top - 46 >= 88 + 14 + 2 * 46 + 14 + 24
    assert "overflow:hidden" in rule, "подписи нечем удержаться внутри плиты"


def test_the_exhibit_caption_is_a_whole_phrase():
    """Подпись обрывалась на счёте слов: «…и сегодня это»."""
    from src.p11_assemble.assemble import _caption

    text = ("Скважину закрыли в девяносто втором, и сегодня это заваренный люк "
            "посреди тундры. Мы упёрлись не в бюджет.")
    assert _caption(text) == "Скважину закрыли в девяносто втором"
    # Короткая фраза уходит целиком.
    assert _caption("Её там не оказалось. Дальше шёл гранит.") == "Её там не оказалось"
    # Нечего взять целиком — подписи не будет, выдумывать текст неоткуда.
    assert _caption("Одно длинное предложение без единого знака препинания "
                    "которое в подпись под экспонатом никак не помещается") == ""


def test_a_generated_picture_gets_no_museum_label():
    """Табличка — утверждение о материале, и под генерацией она лжёт формой.

    В кадре она вдобавок подписывала «REDSHIFT / GENERATED»: ровно то, чего
    заказчик просил в кадре не показывать.
    """
    from src.lib.templates import TemplateCatalog
    from src.p11_assemble.assemble import _hero_device

    path = Path("templates/manifest.json")
    catalog = TemplateCatalog(path, json.loads(path.read_text("utf-8")))
    content = {"word": "ФИЗИКУ", "title": "Кольская сверхглубокая",
               "caption": "Скважину закрыли в девяносто втором", "lines": ["а", "б"],
               "punch": ["а", "б"], "entries": ["а"], "figures": [], "face": (540, 570)}
    slot = {"index": 3, "role": "develop", "duration": 5.0, "start": 0.0, "end": 5.0}
    picked = set()
    for generated in (True, False):
        plate = {"file": "/w/a.mp4", "duration_sec": 5.0, "credit": "NASA",
                 "ai_generated": generated}
        for seed in range(40):
            entry = _hero_device(catalog, slot=slot, content=content,
                                 has_alpha=True, plate_src=plate,
                                 recent_videos=[], exclude=[], seed=seed)
            if entry and generated:
                assert entry["renderer"] != "hero-exhibit", entry["template"]
            if entry and not generated:
                picked.add(entry["renderer"])
    # И обратное: на настоящем материале приём из каталога не исчез.
    assert "hero-exhibit" in picked

def test_split_flap_board():
    piece = render_fullscreen(_fs_ctx(renderer="split_flap_board", word="FLIGHT"))
    assert piece.nodes
    assert "sfb-board" in piece.nodes[0]

def test_news_ticker():
    piece = render_fullscreen(_fs_ctx(renderer="news_ticker", text="BREAKING"))
    assert piece.nodes
    assert "ntk-scroll" in piece.nodes[0]
