"""Генератор композиции HyperFrames.

Проверяется контракт движка (skill ``hyperframes-core``): каждое нарушение из
этих тестов ломает рендер молча — пустым кадром, зависшим ожиданием таймлайна
или элементом, который висит весь ролик вместо своего окна.
"""

from __future__ import annotations

import re

import pytest

from src.lib.render.hyperframes.brand_css import build_css
from src.lib.render.hyperframes.composition import (
    CompositionBuilder, _lay_out_tracks, _num,
)


@pytest.fixture
def plan():
    return {
        "video_id": "redshift_0001",
        "variant": "A",
        "fps": 30,
        "resolution": [1080, 1920],
        "duration_sec": 10.0,
        "shots": [
            {"index": 0, "start": 0.0, "end": 3.0, "duration": 3.0, "kind": "footage",
             "block_id": "b1", "file": "/w/shots/a.mp4",
             "kenburns": {"from_scale": 1.0, "to_scale": 1.08}},
            {"index": 1, "start": 3.0, "end": 4.2, "duration": 1.2,
             "kind": "fullscreen_text", "block_id": "b1",
             "content": "ПЕРЕЖИВЁШЬ", "accent_word": "ПЕРЕЖИВЁШЬ", "invert": False},
            {"index": 2, "start": 4.2, "end": 10.0, "duration": 5.8, "kind": "avatar",
             "block_id": "b2", "file": "/w/shots/av.mp4", "text_behind_head": True},
        ],
        "avatar": [
            {"index": 0, "start": 4.2, "end": 10.0, "duration": 5.8, "block_id": "b2",
             "file": "/w/avatar/seg_00.mov", "slot_indices": [2], "has_alpha": True},
        ],
        "overlays": [
            {"type": "source_card", "start": 1.0, "end": 3.0,
             "params": {"domain": "arxiv.org", "title": "Заголовок",
                        "snippet": "Выдержка"}},
            {"type": "plaque", "start": 2.0, "end": 4.0,
             "params": {"content": "Плашка"}},
            {"type": "cta", "start": 8.0, "end": 10.0, "params": {"content": "Подпишись"}},
        ],
        "subtitles": [
            {"display": "Падение", "start": 0.1, "end": 0.55, "emphasis": False},
            {"display": "в", "start": 0.6, "end": 0.9, "emphasis": True},
        ],
        "subtitle_style": {"mode": "stroke", "baseline_y": 975},
        "_blocks": [{"id": "b2", "emphasis_word": "размер"}],
    }


@pytest.fixture
def assets():
    return {
        "/w/shots/a.mp4": "assets/m000_a.mp4",
        "/w/shots/av.mp4": "assets/m001_av.mp4",
        "/w/avatar/seg_00.mov": "assets/m002_seg_00.mov",
    }


@pytest.fixture
def markup(plan, assets, brandbook):
    return CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")


@pytest.fixture
def brandbook():
    from src.lib.config import load_config
    return load_config().brandbook


# --- контракт корня -----------------------------------------------------------

def test_root_carries_required_attributes(markup):
    root = re.search(r'<div\s+id="root"(.*?)>', markup, re.S).group(1)
    for attr in ('data-composition-id="redshift"', 'data-start="0"',
                 'data-duration="10"', 'data-width="1080"', 'data-height="1920"'):
        assert attr in root, attr


def test_single_paused_timeline_is_registered(markup):
    # Ровно один таймлайн, созданный paused и положенный под ключ корня.
    assert markup.count("gsap.timeline(") == 1
    assert "paused: true" in markup
    assert 'window.__timelines["redshift"] = tl;' in markup


def test_stage_fill_is_not_on_the_root(markup, brandbook):
    """Заливка на корне теряется продюсером — кадр уходит в чёрное."""
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    root_rule = re.search(r"#root\{([^}]*)\}", css).group(1)
    assert "background" not in root_rule
    assert '<div id="stage-bg" class="clip stage-bg"' in markup


# --- треки и клипы ------------------------------------------------------------

def test_adjacent_shots_land_on_different_tracks(markup):
    """Окно клипа включает оба конца: встык на одном треке = пересечение."""
    tracks = re.findall(r'id="shot-(\d+)"[^>]*data-track-index="(\d+)"', markup)
    assert [t for _, t in tracks] == ["1", "2", "1"]


def test_overlapping_overlays_get_separate_tracks():
    items = [{"start": 0.0, "end": 3.0}, {"start": 2.0, "end": 4.0},
             {"start": 5.0, "end": 6.0}]
    assert _lay_out_tracks(items, 5) == [5, 6, 5]


def test_every_id_is_unique(markup):
    ids = re.findall(r'\sid="([^"]+)"', markup)
    assert len(ids) == len(set(ids)), "дубль id: у <video> это даёт пустой кадр"


def test_visual_clips_are_direct_children_of_root(markup):
    """Клип внутри обёртки теряет тайминг и висит весь ролик."""
    body = markup.split('data-fps="30"\n    >', 1)[1].split("</div>\n    <script>")[0]
    for line in body.strip().splitlines():
        line = line.strip()
        if 'class="clip' in line:
            assert line.startswith("<div") or line.startswith("<video"), line


# --- медиа --------------------------------------------------------------------

def test_videos_are_muted_and_inline(markup):
    for tag in re.findall(r"<video[^>]*>", markup):
        assert "muted" in tag and "playsinline" in tag, tag


def test_audio_is_a_separate_element(markup):
    # Звук ролика идёт одной сведённой дорожкой, иначе он сложится дважды.
    assert markup.count("<audio") == 1
    assert 'src="assets/mix.wav"' in markup


def test_avatar_uses_alpha_source_not_flattened_shot(markup):
    """Смысл переезда: слои собираются в браузере, а не берутся сплющенными."""
    assert 'id="avatar-00" class="avatar" src="assets/m002_seg_00.mov"' in markup
    # Под аватаром — сгенерированный фон, а не файл сплющенного кадра.
    assert '<div id="shot-02" class="clip shot-bg"' in markup
    assert "assets/m001_av.mp4" not in markup


# --- анимация -----------------------------------------------------------------

def test_kenburns_uses_fromto_not_css_transform(markup):
    """CSS-transform плюс твин той же свойства запрещены контрактом."""
    assert 'tl.fromTo("#shot-00",{scale:1.0},{scale:1.08' in markup


def test_cta_pulse_is_finite(markup):
    """repeat: -1 запрещён — рендер обязан быть детерминированным."""
    pulse = re.search(r'tl\.to\("#ovl-02-pill".*?\)', markup, re.S).group(0)
    assert "repeat:-1" not in pulse.replace(" ", "")
    assert re.search(r"repeat:\d+", pulse.replace(" ", ""))


def test_subtitle_popin_animates_inner_span(markup):
    """Видимостью клипа управляет фреймворк — анимируем вложенный span."""
    assert 'tl.fromTo("#w-0000-t"' in markup
    assert 'tl.fromTo("#w-0000"' not in markup


def test_emphasis_word_marked_in_markup(markup):
    assert 'id="w-0001" class="clip word emphasis"' in markup


def test_text_behind_head_taken_from_block(markup):
    assert '<div id="behind-02" class="clip behind-head"' in markup
    assert ">размер</div>" in markup


# --- мелочи, которые ломают атрибуты -----------------------------------------

@pytest.mark.parametrize("value,expected", [
    (0, "0"), (2.212, "2.212"), (10.0, "10"), (53.9610, "53.961"), (0.4, "0.4"),
])
def test_seconds_are_written_compactly(value, expected):
    assert _num(value) == expected


def test_text_is_escaped(plan, assets, brandbook):
    # Кавычки и скобки по краям срезает правило §5.1, поэтому спецсимволы
    # для проверки экранирования ставим внутрь слова.
    plan["subtitles"][0]["display"] = "ку<и>&я"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "ку&lt;и&gt;&amp;я" in out


# --- CSS ----------------------------------------------------------------------

def test_css_takes_colors_from_brandbook(brandbook):
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert f"--color-accent: {brandbook['colors']['accent']};" in css
    assert "@font-face" in css and "fonts/Nunito-ExtraBold.ttf" in css


def test_subtitle_is_centered_on_the_frame(brandbook):
    """Центр кадра, а не середина рабочей зоны (правое поле ужато под UI)."""
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    rule = re.search(r"\.word\{([^}]*)\}", css).group(1)
    assert "left:0" in rule and "right:0" in rule and "text-align:center" in rule


# --- статистика для отчёта ----------------------------------------------------

def test_subtitle_coverage_merges_touching_windows():
    """Слова примыкают встык — простая сумма завысила бы покрытие."""
    from src.lib.render.hyperframes.compositor import _subtitle_coverage_sec

    plan = {"subtitles": [
        {"display": "а", "start": 0.0, "end": 1.0},
        {"display": "б", "start": 1.0, "end": 2.0},   # встык
        {"display": "в", "start": 1.5, "end": 2.5},   # с наложением
        {"display": "г", "start": 5.0, "end": 6.0},   # с разрывом
        {"display": "", "start": 8.0, "end": 9.0},    # пустое не считается
    ]}
    assert _subtitle_coverage_sec(plan) == pytest.approx(3.5)


def test_subtitle_coverage_of_empty_plan_is_zero():
    from src.lib.render.hyperframes.compositor import _subtitle_coverage_sec

    assert _subtitle_coverage_sec({"subtitles": []}) == 0.0


# --- правило текста доезжает до обоих движков ---------------------------------

def test_subtitle_word_is_cleaned_and_lowercased(plan, assets, brandbook):
    """До переноса правило жило внутри отрисовки, и HTML-движок его не видел."""
    plan["subtitles"] = [
        {"display": "Падение", "start": 0.0, "end": 0.5, "emphasis": False},
        {"display": "счётчик.", "start": 0.5, "end": 1.0, "emphasis": False},
        {"display": "ОТО", "start": 1.0, "end": 1.5, "emphasis": False},
    ]
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert ">падение<" in out
    assert ">счётчик<" in out and "счётчик." not in out
    assert ">ОТО<" in out          # аббревиатуру не трогаем


def test_source_card_clears_the_subtitle_band(brandbook):
    """Карточка наезжала на слово: высота у неё content-driven."""
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    rule = re.search(r"\.source-card\{([^}]*)\}", css).group(1)
    bottom = int(re.search(r"bottom:(\d+)px", rule).group(1))
    subs = brandbook["subtitles"]
    height = int(brandbook["canvas"]["height"])
    card_bottom_y = height - bottom
    assert card_bottom_y <= subs["baseline_y_default"] - subs["size_px"][1] // 2


# --- аватар без альфы ---------------------------------------------------------

def test_opaque_avatar_gets_no_background_layer(plan, assets, brandbook):
    """Фото-аватар HeyGen приходит со вшитым фоном: подкладывать нечего."""
    plan["avatar"][0]["has_alpha"] = False
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert 'id="shot-02"' not in out          # фон под аватаром не рисуем
    assert 'class="vfx"' not in out
    assert 'id="avatar-00" class="avatar"' in out


def test_word_behind_head_needs_alpha(plan, assets, brandbook):
    """Без альфы слово оказалось бы за непрозрачным видео — его не видно."""
    plan["avatar"][0]["has_alpha"] = False
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "behind-head" not in out

    plan["avatar"][0]["has_alpha"] = True
    with_alpha = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "behind-head" in with_alpha
