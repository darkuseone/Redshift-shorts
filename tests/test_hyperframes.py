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
    """CSS-transform плюс твин того же свойства запрещены контрактом."""
    tween = next(l for l in markup.splitlines()
                 if 'fromTo("#shot-00"' in l)
    assert "scale:1.0" in tween and "scale:1.08" in tween
    assert 'ease:"none"' in tween          # Ken Burns идёт равномерно


def test_cta_pulse_is_finite(markup):
    """repeat: -1 запрещён — рендер обязан быть детерминированным."""
    pulse = re.search(r'tl\.to\("#ovl-02-pill".*?\)', markup, re.S).group(0)
    assert "repeat:-1" not in pulse.replace(" ", "")
    assert re.search(r"repeat:\d+", pulse.replace(" ", ""))


def test_subtitle_gradient_fill_animates_inner_word(markup):
    """Видимостью клипа управляет движок — bounce и заливка на вложенном слове."""
    assert 'class="clip caption-grad"' in markup
    assert 'fromTo("#gf-00"' not in markup
    assert 'tl.set("#gf-00-w' in markup
    assert "backgroundPosition" not in markup
    assert "clip-path" not in markup
    assert 'id="w-0000"' not in markup


def test_emphasis_word_gets_blood_gradient(markup):
    assert "gf-accent" in markup
    assert "#C8453D" in markup
    assert "#E4726A" in markup
    assert "#FFD700" not in markup
    assert "#fe9f1b" not in markup.lower()


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
    assert "КУ&lt;И&gt;&amp;Я" in out


# --- CSS ----------------------------------------------------------------------

def test_css_takes_colors_from_brandbook(brandbook):
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert f"--color-accent: {brandbook['colors']['accent']};" in css
    assert "@font-face" in css and "fonts/Nunito-ExtraBold.ttf" in css


def test_subtitle_group_is_centered_on_the_work_area(brandbook):
    """Фраза центрируется в рабочей зоне, не в оптическом центре кадра."""
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    rule = re.search(r"\.gf-group\{([^}]*)\}", css).group(1)
    assert "justify-content:center" in rule


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

def test_subtitle_word_is_cleaned_and_uppercased(plan, assets, brandbook):
    """До переноса правило жило внутри отрисовки, и HTML-движок его не видел."""
    plan["subtitles"] = [
        {"display": "Падение", "start": 0.0, "end": 0.5, "emphasis": False},
        {"display": "счётчик.", "start": 0.5, "end": 1.0, "emphasis": False},
        {"display": "ОТО", "start": 1.0, "end": 1.5, "emphasis": False},
    ]
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert ">ПАДЕНИЕ<" in out
    assert ">СЧЁТЧИК<" in out and "счётчик." not in out
    assert ">ОТО<" in out


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


def test_transition_on_avatar_shot_targets_the_avatar(plan, assets, brandbook):
    """Переход обязан двигать ведущего, а не подложку под ним.

    Раньше твин целился в #shot-NN, а для непрозрачного аватара такого узла
    нет вовсе — переход пропадал молча.
    """
    plan["shots"][2]["transition"] = {"renderer": "zoom_punch", "duration": 0.32,
                                      "params": {"from_scale": 1.18}}
    for alpha in (True, False):
        plan["avatar"][0]["has_alpha"] = alpha
        out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
        tween = next(l for l in out.splitlines() if "scale:1.18" in l)
        assert '"#avatar-00"' in tween, f"has_alpha={alpha}: {tween}"


def test_every_tween_target_exists_in_the_markup(plan, assets, brandbook):
    """Твин по несуществующему id ничего не делает и не жалуется."""
    plan["shots"][0]["transition"] = {"renderer": "white_flash", "duration": 0.3,
                                      "params": {}}
    plan["shots"][2]["transition"] = {"renderer": "paper_slide", "duration": 0.3,
                                      "params": {"axis": "y", "direction": -1}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for tween in [l for l in out.splitlines() if l.strip().startswith("tl.")]:
        selector = re.search(r'"#([^" ]+)', tween).group(1)
        assert selector in ids, f"твин целится в несуществующий {selector}: {tween}"


def test_glitch_shader_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """Шейдер каталога не вендорится: только оверлей, без scale входящего."""
    plan["shots"][0]["transition"] = {
        "renderer": "glitch_shader", "duration": 0.4,
        "params": {"seed": 9}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-glitch-shader" in out
    assert "gs-from" in out and "gs-to" in out
    assert "gs-scan" in out and "gs-block" in out
    assert "gs-r" in out and "gs-b" in out
    assert 'class="clip tr-glitch"' not in out
    assert "scale:1.16" not in out
    assert '"#shot-00"' not in "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_cinematic_zoom_overlay_scales_the_incoming_shot(plan, assets, brandbook):
    """Шейдер каталога не вендорится: оверлей + scale входящего кадра."""
    plan["shots"][0]["transition"] = {
        "renderer": "cinematic_zoom", "duration": 0.4,
        "params": {"from_scale": 1.16}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-cinematic-zoom" in out
    assert "cz-from" in out and "cz-to" in out
    assert "cz-r" in out and "cz-b" in out
    tween = next(l for l in out.splitlines() if "scale:1.16" in l)
    assert '"#shot-00"' in tween
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and ("tr-00" in l or "scale:1.16" in l)]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_gravitational_lens_overlay_scales_the_incoming_shot(
        plan, assets, brandbook):
    """Шейдер каталога не вендорится: оверлей + scale входящего из well."""
    plan["shots"][0]["transition"] = {
        "renderer": "gravitational_lens", "duration": 0.4,
        "params": {"from_scale": 1.14}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-gravitational-lens" in out
    assert "gw-from" in out and "gw-to" in out
    assert "gw-well" in out
    assert "gw-r" in out and "gw-b" in out
    tween = next(l for l in out.splitlines() if "scale:1.14" in l)
    assert '"#shot-00"' in tween
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and ("tr-00" in l or "scale:1.14" in l)]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_light_leak_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """Шейдер каталога не вендорится: только засвет, без scale входящего."""
    plan["shots"][0]["transition"] = {
        "renderer": "light_leak", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-light-leak" in out
    assert "ll-from" in out and "ll-to" in out
    assert "ll-blob" in out and "ll-flare" in out
    assert 'class="clip tr-sweep"' not in out
    assert '"#shot-00"' not in "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_sdf_iris_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """Шейдер каталога не вендорится: только диск и кольца, без scale входящего."""
    plan["shots"][0]["transition"] = {
        "renderer": "sdf_iris", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-sdf-iris" in out
    assert "si-from" in out and "si-iris" in out
    assert "si-ring" in out
    assert "tr-mask-circle" not in out
    assert '"#shot-00"' not in "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_thermal_distortion_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """Шейдер каталога не вендорится: только haze и полосы, без scale входящего."""
    plan["shots"][0]["transition"] = {
        "renderer": "thermal_distortion", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-thermal-distortion" in out
    assert "td-from" in out and "td-to" in out
    assert "td-haze" in out and "td-band" in out
    assert 'class="clip tr-sweep"' not in out
    assert '"#shot-00"' not in "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_whip_pan_shader_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """Шейдер каталога не вендорится: только смаз и вуали, без x входящего."""
    plan["shots"][0]["transition"] = {
        "renderer": "whip_pan_shader", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-whip-pan" in out
    assert "wp-from" in out and "wp-to" in out
    assert "wp-streak" in out
    assert 'class="clip tr-blur"' not in out
    assert '"#shot-00"' not in "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_mk_clone_wall_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """Каталог не вендорится: плитка и invert, без scale входящего."""
    plan["shots"][0]["transition"] = {
        "renderer": "mk_clone_wall", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-mk-clone-wall" in out
    assert "cw-wall" in out and "cw-invert" in out
    assert "cw-card" in out and "HyperFrames" in out
    assert 'class="clip tr-blur"' not in out
    assert '"#shot-00"' not in "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    assert "visibility" not in "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl."))
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_transitions_3d_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """rotationY каталога не вендорится: грани scaleX, без входящего кадра."""
    plan["shots"][0]["transition"] = {
        "renderer": "transitions_3d", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-transitions-3d" in out
    assert "t3-a" in out and "t3-b" in out
    assert "t3-edge" in out and "ONE" in out
    assert "rotationY" not in out
    assert '"#shot-00"' not in "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_transitions_blur_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """filter каталога не вендорится: грани scale и призраки, без входящего кадра."""
    plan["shots"][0]["transition"] = {
        "renderer": "transitions_blur", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-transitions-blur" in out
    assert "tb-a" in out and "tb-b" in out
    assert "tb-ghost" in out and "ONE" in out
    assert "tr-transitions-3d" not in out
    assert 'class="clip tr-blur"' not in out
    tween_body = "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "filter" not in tween_body
    assert "skewX" not in tween_body
    assert '"#shot-00"' not in tween_body
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_transitions_cover_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """translateX каталога не вендорится: вайпы GSAP x, без входящего кадра."""
    plan["shots"][0]["transition"] = {
        "renderer": "transitions_cover", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-transitions-cover" in out
    assert "tc-a" in out and "tc-b" in out
    assert "tc-wa" in out and "tc-wb" in out and "ONE" in out
    assert "tr-transitions-blur" not in out
    assert "tr-transitions-3d" not in out
    assert 'class="clip tr-blur"' not in out
    tween_body = "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "x:-1080" in tween_body
    assert "x:1080" in tween_body
    assert "filter" not in tween_body
    assert "innerHTML" not in tween_body
    assert "textContent" not in tween_body
    assert '"#shot-00"' not in tween_body
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_transitions_destruction_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """clip-path и canvas каталога не вендорятся: круг scale, без входящего кадра."""
    plan["shots"][0]["transition"] = {
        "renderer": "transitions_destruction", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-transitions-destruction" in out
    assert "tds-a" in out and "tds-b" in out
    assert "tds-hole" in out and "tds-r0" in out and "ONE" in out
    assert "tr-transitions-cover" not in out
    assert "tr-transitions-blur" not in out
    assert "tr-transitions-3d" not in out
    assert "tr-sdf-iris" not in out
    assert 'class="clip tr-mask-circle"' not in out
    tween_body = "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "clipPath" not in tween_body
    assert "onUpdate" not in tween_body
    assert "<canvas" not in out
    assert "filter" not in tween_body
    assert "innerHTML" not in tween_body
    assert "textContent" not in tween_body
    assert '"#shot-00"' not in tween_body
    assert "webgl" not in out.lower()
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_transitions_light_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """filter и CSS transform каталога не вендорятся: GSAP x бликов, без входящего кадра."""
    plan["shots"][0]["transition"] = {
        "renderer": "transitions_light", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-transitions-light" in out
    assert "tlt-a" in out and "tlt-b" in out
    assert "tlt-warm" in out and "tlt-l1" in out and "ONE" in out
    assert "tr-light-leak" not in out
    assert 'class="clip tr-sweep"' not in out
    assert "tr-transitions-destruction" not in out
    assert "tr-transitions-cover" not in out
    tween_body = "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "x:169" in tween_body
    assert "x:338" in tween_body
    assert "filter" not in tween_body
    assert "innerHTML" not in tween_body
    assert "textContent" not in tween_body
    assert '"#shot-00"' not in tween_body
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_transitions_other_overlay_does_not_tween_the_incoming_shot(
        plan, assets, brandbook):
    """Flash cut каталога не вендорится на .clip: opacity вспышки, без входящего кадра."""
    plan["shots"][0]["transition"] = {
        "renderer": "transitions_other", "duration": 0.4, "params": {}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "tr-transitions-other" in out
    assert "tto-a" in out and "tto-b" in out
    assert "tto-flash" in out and "ONE" in out
    assert 'class="clip tr-flash"' not in out
    assert "tr-transitions-light" not in out
    assert "tr-transitions-destruction" not in out
    assert "tr-transitions-cover" not in out
    tween_body = "\n".join(
        l for l in out.splitlines() if l.strip().startswith("tl.")
        and "tr-00" in l)
    assert "power4.out" in tween_body
    assert "power2.out" in tween_body
    assert "filter" not in tween_body
    assert "innerHTML" not in tween_body
    assert "textContent" not in tween_body
    assert '"#shot-00"' not in tween_body
    assert "webgl" not in out.lower()
    assert "onUpdate" not in out
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for line in [l for l in out.splitlines() if l.strip().startswith("tl.")
                 and "tr-00" in l]:
        selector = re.search(r'"#([^" ]+)', line).group(1)
        assert selector in ids, line


def test_kenburns_starts_after_the_transition(plan, assets, brandbook):
    """Вход и медленный проезд не имеют права тянуть одно свойство разом.

    Порядок перезаписи в GSAP зависит от очерёдности твинов и может
    переключиться между рендерами — lint движка ловит это как
    overlapping_gsap_tweens.
    """
    plan["shots"][0]["transition"] = {"renderer": "zoom_punch", "duration": 0.26,
                                      "params": {"from_scale": 1.35}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")

    scale_tweens = [l for l in out.splitlines()
                    if '"#shot-00"' in l and "scale" in l]
    assert len(scale_tweens) == 2

    windows = []
    for tween in scale_tweens:
        at = float(tween.rstrip(");").rsplit(",", 1)[1])
        dur = float(re.search(r"duration:([\d.]+)", tween).group(1))
        windows.append((at, at + dur))
    windows.sort()
    assert windows[0][1] <= windows[1][0] + 1e-6, f"твины пересекаются: {windows}"


def test_cut_leaves_kenburns_at_the_shot_start(plan, assets, brandbook):
    """Прямая склейка не занимает времени — проезд начинается сразу."""
    plan["shots"][0]["transition"] = {"renderer": "cut", "duration": 0.3}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    tween = next(l for l in out.splitlines() if 'fromTo("#shot-00"' in l)
    assert tween.rstrip(");").endswith(",0")


# --- приёмы вокруг ведущего ---------------------------------------------------

def _with_hero(plan, renderer, **params):
    plan["shots"][2]["hero"] = {
        "template": f"hero-devices/{renderer}", "renderer": renderer,
        "params": {"word": "РАЗМЕР", **params}, "file": None, "duration": None,
    }
    return plan


@pytest.mark.parametrize("renderer", ["hero-burst", "hero-headline",
                                      "hero-split", "hero-knockout"])
def test_hero_device_reaches_the_markup(plan, assets, brandbook, renderer):
    out = CompositionBuilder(_with_hero(plan, renderer), brandbook,
                             assets).build("assets/mix.wav")
    assert f'class="clip {renderer}"' in out, renderer


def test_hero_tween_targets_exist_in_the_markup(plan, assets, brandbook):
    """Твин по несуществующему id молча ничего не делает.

    Сплит тянет самого ведущего, и его узел зовётся ``avatar-NN``, а не
    ``shot-NN``: на непрозрачном аватаре второго попросту нет.
    """
    out = CompositionBuilder(_with_hero(plan, "hero-split"), brandbook,
                             assets).build("assets/mix.wav")
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for tween in [l for l in out.splitlines() if l.strip().startswith("tl.")]:
        selector = re.search(r'"#([^" ]+)', tween).group(1)
        assert selector in ids, f"твин целится в несуществующий {selector}: {tween}"
    assert '"#avatar-00"' in out


def test_hero_starts_after_the_transition(plan, assets, brandbook):
    """Вход кадра и приём тянут ``x``/``scale`` одного ведущего.

    Наложение двух твинов на одном элементе движок считает ошибкой: порядок
    перезаписи в GSAP зависит от очерёдности и может смениться между рендерами.
    """
    plan["shots"][2]["transition"] = {"renderer": "zoom_punch", "duration": 0.32,
                                      "params": {"from_scale": 1.18}}
    out = CompositionBuilder(_with_hero(plan, "hero-split"), brandbook,
                             assets).build("assets/mix.wav")
    # Обе цели — сам аватар: вход кадра и приём сплита тянут его x и scale.
    # Искать по величине масштаба нельзя, 1.14 встречается и в словаре входов.
    avatar = [l for l in out.splitlines() if '"#avatar-00"' in l and "scale" in l]
    entrance = next(l for l in avatar if "scale:1.18" in l)
    device = next(l for l in avatar if "scale:1.14" in l)
    start = float(entrance.rstrip(");").rsplit(",", 1)[1])
    assert float(device.rstrip(");").rsplit(",", 1)[1]) >= start + 0.32 - 1e-6


def test_hero_plate_duration_is_capped_by_its_material(plan, assets, brandbook):
    """Кадр-задник короче аватар-плана: растянутая панель досидит его пустой."""
    plan["shots"][2]["hero"] = {
        "template": "hero-devices/plate-behind-back", "renderer": "hero-plate",
        "params": {}, "file": "/w/shots/a.mp4", "duration": 1.4,
    }
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    node = next(l for l in out.splitlines() if 'class="clip hero-plate"' in l)
    assert 'data-duration="1.4"' in node, node


def test_hero_without_a_device_adds_nothing(plan, assets, brandbook):
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "hero-" not in out


def test_hero_devices_do_not_share_a_track_with_the_shots(plan, assets, brandbook):
    """Приём и шот на одном треке пересеклись бы на стыке кадров."""
    out = CompositionBuilder(_with_hero(plan, "hero-headline"), brandbook,
                             assets).build("assets/mix.wav")
    node = next(l for l in out.splitlines() if 'class="clip hero-headline"' in l)
    track = int(re.search(r'data-track-index="(\d+)"', node).group(1))
    assert track >= 13


def test_kinetic_fullscreen_uses_word_stack(plan, assets, brandbook):
    plan["shots"][1]["content"] = "раз два три"
    plan["shots"][1]["accent_word"] = "два"
    plan["shots"][1]["params"] = {"stagger_ms": 55, "kinetic": True}
    plan["shots"][1]["renderer"] = "kinetic_stack"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "ks-word" in out
    assert "ks-stack" in out


def test_blur_out_up_fullscreen_uses_a_static_ghost(plan, assets, brandbook):
    plan["shots"][1]["content"] = "сигнал с орбиты"
    plan["shots"][1]["accent_word"] = "орбиты"
    plan["shots"][1]["params"] = {
        "stagger_ms": 55, "blur_out": True, "direction": "up",
        "distance": "standard", "blur": "standard",
    }
    plan["shots"][1]["renderer"] = "blur_out_up"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "bou-ghost" in out
    assert "filter:blur(5px)" in out
    assert "filter:" not in "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)


def test_bottom_up_letters_fullscreen_splits_glyphs(plan, assets, brandbook):
    plan["shots"][1]["content"] = "код живёт"
    plan["shots"][1]["accent_word"] = "код"
    plan["shots"][1]["params"] = {
        "stagger_ms": 25, "bottom_up": True, "unit": "letter",
        "direction": "up", "travel": "standard",
    }
    plan["shots"][1]["renderer"] = "bottom_up_letters"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "bul-ch" in out
    assert "back.out(1.7)" in out
    assert 'id="shot-01-c0"' in out


def test_kinetic_type_swap_fullscreen_masks_the_slot(plan, assets, brandbook):
    plan["shots"][1]["content"] = "ПИШИ|КОД|HTML|ОРБИТЫ"
    plan["shots"][1]["params"] = {"kinetic_swap": True, "exit": "none"}
    plan["shots"][1]["renderer"] = "kinetic_type_swap"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "kts-slot" in out
    assert "kts-word" in out
    assert 'class="kts-slot"' in out
    assert "yPercent" not in out
    assert "back.out(1.7)" in out


def test_line_by_line_slide_fullscreen_uses_a_static_ghost(plan, assets, brandbook):
    plan["shots"][1]["content"] = "ПИШИ КОД|СОБИРАЙ ОРБИТЫ|ШЛИ НА ПРОД"
    plan["shots"][1]["accent_word"] = "ОРБИТЫ"
    plan["shots"][1]["params"] = {
        "line_slide": True, "direction": "left", "size": "standard",
        "density": "standard", "tone": "ink",
    }
    plan["shots"][1]["renderer"] = "line_by_line_slide"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "lbls-ghost" in out
    assert "lbls-stack" in out
    assert "filter:blur(" in out
    assert "filter:" not in "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)


def test_particle_text_dissolve_fullscreen_has_no_canvas(plan, assets, brandbook):
    plan["shots"][1]["content"] = "СОБЕРИ ОРБИТУ"
    plan["shots"][1]["accent_word"] = "ОРБИТУ"
    plan["shots"][1]["params"] = {
        "particle_dissolve": True, "direction": "in", "density": "med",
        "exit": "none",
    }
    plan["shots"][1]["renderer"] = "particle_text_dissolve"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "ptd-wipe" in out
    assert "ptd-dot" in out
    assert "<svg" in out
    assert "<canvas" not in out
    assert "clipPath" not in out
    assert "Math.random" not in out
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert ".ptd-wipe" in css
    assert ".ptd-dot" in css


def test_per_word_crossfade_fullscreen_uses_a_static_ghost(plan, assets, brandbook):
    plan["shots"][1]["content"] = "ПИШИ КОД НА ОРБИТЕ"
    plan["shots"][1]["accent_word"] = "ОРБИТЕ"
    plan["shots"][1]["params"] = {
        "word_crossfade": True, "drift": "standard", "blur": "standard",
        "tone": "ink", "exit": "none",
    }
    plan["shots"][1]["renderer"] = "per_word_crossfade"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "pwc-ghost" in out
    assert "filter:blur(5px)" in out
    assert "--hf-word" not in out
    assert "filter:" not in "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert ".pwc-stack" in css
    assert ".pwc-ghost" in css


def test_scan_band_fullscreen_keeps_catalog_chromatic(plan, assets, brandbook):
    plan["shots"][1]["content"] = "СИГНАЛ"
    plan["shots"][1]["duration"] = 3.5
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 3.5
    plan["shots"][1]["params"] = {"scan_band": True, "band_angle": 12}
    plan["shots"][1]["renderer"] = "scan_band"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-scan-band" in out
    assert "sb-clone-red" in out and "sb-clone-cyan" in out
    assert "--sb-band" not in out
    assert "clip-path" not in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "clip-path" not in tween_src
    assert "--sb-" not in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "Inter,system-ui,sans-serif" in css
    assert "#ff3158" in css and "#36efff" in css
    assert "#0b0c0e" in css
    assert ".sb-band" in css


def test_scramble_reveal_fullscreen_keeps_catalog_terminal(plan, assets, brandbook):
    plan["shots"][1]["content"] = "СИГНАЛ"
    plan["shots"][1]["duration"] = 3.0
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 3.0
    plan["shots"][1]["params"] = {
        "scramble_reveal": True, "accent": "green", "style": "terminal",
        "exit": "none"}
    plan["shots"][1]["renderer"] = "scramble_reveal"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-scramble-reveal" in out
    assert "sr-green" in out and "sr-prefix" in out
    assert "textContent" not in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line
        or "tl.set" in line)
    assert "textContent" not in tween_src
    assert "clip-path" not in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "#71f5a7" in css
    assert ".sr-shell" in css
    assert "var(--font-mono)" in css


def test_shared_axis_z_fullscreen_keeps_catalog_inter(plan, assets, brandbook):
    plan["shots"][1]["content"] = "ПИШИ КОД"
    plan["shots"][1]["duration"] = 1.4
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 1.4
    plan["shots"][1]["params"] = {
        "shared_axis_z": True, "direction": "in", "depth": "standard",
        "tone": "ink"}
    plan["shots"][1]["renderer"] = "shared_axis_z"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-shared-axis-z" in out
    assert "saz-word" in out and "saz-ink" in out
    assert "--hf-word" not in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "--hf-" not in tween_src
    assert "filter" not in tween_src
    assert "back.out(1.8)" in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert ".saz-stack" in css and ".saz-word" in css
    assert "Inter,system-ui,sans-serif" in css
    assert "#18181b" in css
    assert ".fullscreen-text.fs-shared-axis-z.saz-accent{color:#C8453D}" in css
    assert "#fafafa" in css
    assert "#34d399" not in css


def test_code_3d_extrude_fullscreen_reaches_the_markup(plan, assets, brandbook):
    plan["shots"][1]["content"] = (
        "async function loadConfig(path) {\n"
        "  const raw = await readFile(path, \"utf8\")\n"
        "  return validate(config)\n"
        "}"
    )
    plan["shots"][1]["duration"] = 8.0
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 8.0
    plan["shots"][1]["params"] = {"code_3d_extrude": True}
    plan["shots"][1]["renderer"] = "code_3d_extrude"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-code-3d" in out
    assert "c3d-slab" in out and "c3d-edge" in out
    assert "loadConfig" in out
    assert "THREE" not in out and "<canvas" not in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "onUpdate" not in tween_src
    assert "scale:0.72" in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "JetBrains Mono" in css
    assert "#05070b" in css and "#24292e" in css
    assert ".c3d-slab" in css


def test_code_diff_fullscreen_reaches_the_markup(plan, assets, brandbook):
    plan["shots"][1]["content"] = (
        "function greet(name) {\n"
        "  console.log(\"hi \" + name)\n"
        "}\n---\n"
        "function greet(name, lang) {\n"
        "  const msg = translate(\"hi\", lang)\n"
        "  console.log(`${msg} ${name}`)\n"
        "}"
    )
    plan["shots"][1]["duration"] = 6.0
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 6.0
    plan["shots"][1]["params"] = {"code_diff": True}
    plan["shots"][1]["renderer"] = "code_diff"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-code-diff" in out
    assert "cd-editor" in out and "cd-del" in out and "cd-add" in out
    assert "translate" in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "height:" not in tween_src
    assert "scaleY:0" in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "JetBrains Mono" in css
    assert "#f85149" in css and "#3fb950" in css
    assert ".cd-editor" in css


def test_code_particle_assemble_fullscreen_reaches_the_markup(plan, assets, brandbook):
    plan["shots"][1]["content"] = (
        "const app = pipe(\n"
        "  parse,\n"
        "  optimize,\n"
        "  emit,\n"
        ")"
    )
    plan["shots"][1]["duration"] = 8.0
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 8.0
    plan["shots"][1]["params"] = {"code_particle_assemble": True}
    plan["shots"][1]["renderer"] = "code_particle_assemble"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-code-pa" in out
    assert "pa-dot" in out and "pa-code" in out
    assert "const" in out and "pipe" in out
    assert "THREE" not in out and "<canvas" not in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "onUpdate" not in tween_src
    assert "Math.random" not in tween_src
    assert "width:" not in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "JetBrains Mono" in css
    assert "#05070b" in css
    assert ".pa-dot" in css


def test_code_scroll_fullscreen_reaches_the_markup(plan, assets, brandbook):
    plan["shots"][1]["content"] = (
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
    plan["shots"][1]["duration"] = 6.0
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 6.0
    plan["shots"][1]["params"] = {"code_scroll": True, "filename": "fetchWithRetry.js",
                                  "line": 12}
    plan["shots"][1]["renderer"] = "code_scroll"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-code-scroll" in out
    assert "cs-editor" in out and "cs-hl" in out and "cs-scroll" in out
    assert "fetchWithRetry" in out and "createClient" in out
    assert "lastError" in out and "FETCHWITHRETRY" not in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "onUpdate" not in tween_src
    assert "getBoundingClientRect" not in tween_src
    assert "width:" not in tween_src
    assert "height:" not in tween_src
    assert "y:" in tween_src
    assert "opacity:0.35" in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "JetBrains Mono" in css
    assert "#58a6ff" in css
    assert ".cs-hl" in css
    assert ".cs-editor" in css


def test_code_typing_fullscreen_reaches_the_markup(plan, assets, brandbook):
    plan["shots"][1]["content"] = (
        "async function loadConfig(path) {\n"
        "  const raw = await readFile(path, \"utf8\")\n"
        "  const config = JSON.parse(raw)\n"
        "  return validate(config)\n"
        "}"
    )
    plan["shots"][1]["duration"] = 5.0
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 5.0
    plan["shots"][1]["params"] = {"code_typing": True, "filename": "loadConfig.js"}
    plan["shots"][1]["renderer"] = "code_typing"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-code-typing" in out
    assert "ct-editor" in out and "ct-caret" in out and "ct-ch" in out
    assert "loadConfig.js" in out
    plain = re.sub(r"<[^>]+>", "", out)
    assert "readFile" in plain and "loadConfig" in plain
    assert "LOADCONFIG" not in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "onUpdate" not in tween_src
    assert "getBoundingClientRect" not in tween_src
    assert "width:" not in tween_src
    assert "height:" not in tween_src
    assert "x:" in tween_src and "y:" in tween_src
    assert 'ease:"none"' in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "JetBrains Mono" in css
    assert "#58a6ff" in css
    assert ".ct-caret" in css
    assert ".ct-editor" in css


def test_terminal_simulator_fullscreen_reaches_the_markup(plan, assets, brandbook):
    plan["shots"][1]["content"] = "$ hyperframes render --skill=terminal-simulator"
    plan["shots"][1]["duration"] = 5.0
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 5.0
    plan["shots"][1]["params"] = {"terminal_simulator": True}
    plan["shots"][1]["renderer"] = "terminal_simulator"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-terminal-simulator" in out
    assert "ts-card" in out and "ts-term" in out and "ts-line" in out
    assert "Terminal Simulator" in out
    assert "index.html" in out
    assert "$ hyperframes render --skill=terminal-simulator" in out
    assert "HYPERFRAMES RENDER" not in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "--hf-line" not in tween_src
    assert "width:" not in tween_src
    assert "height:" not in tween_src
    assert "scaleX:0" in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "#86efac" in css
    assert ".ts-term" in css
    assert ".ts-card" in css


def test_apple_terminal_clear_dark_fullscreen_reaches_the_markup(
        plan, assets, brandbook):
    plan["shots"][1]["content"] = "npm audit"
    plan["shots"][1]["duration"] = 8.0
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 8.0
    plan["shots"][1]["params"] = {"apple_terminal_clear_dark": True}
    plan["shots"][1]["renderer"] = "apple_terminal_clear_dark"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-apple-terminal-clear-dark" in out
    assert "atcd-window" in out and "atcd-prompt" in out
    assert "bash — 80×24" in out
    plain = re.sub(r"<[^>]+>", "", out)
    assert "npm audit" in plain
    assert "lodash" in plain
    assert "NPM AUDIT" not in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "textContent" not in tween_src
    assert "innerHTML" not in tween_src
    assert "width:" not in tween_src
    assert "height:" not in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "#888888" in css
    assert ".atcd-cursor" in css
    assert ".atcd-window" in css


def test_dark_plus_fullscreen_reaches_the_markup(plan, assets, brandbook):
    plan["shots"][1]["content"] = ""
    plan["shots"][1]["duration"] = 8.0
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 8.0
    plan["shots"][1]["params"] = {"dark_plus": True}
    plan["shots"][1]["renderer"] = "dark_plus"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-dark-plus" in out
    assert "dp-wb" in out and "dp-caret" in out
    assert "Dark+" in out
    plain = re.sub(r"<[^>]+>", "", out)
    assert "pluck_deep" in plain
    assert "PLUCK_DEEP" not in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "rotateY" not in tween_src
    assert "getBoundingClientRect" not in tween_src
    assert "width:" not in tween_src
    assert "height:" not in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "#0078d4" in css
    assert ".dp-caret" in css
    assert ".dp-wb" in css


def test_beat_freeze_cut_fullscreen_reaches_the_markup(plan, assets, brandbook):
    plan["shots"][1]["content"] = "DROP"
    plan["shots"][1]["duration"] = 6.0
    plan["shots"][1]["end"] = plan["shots"][1]["start"] + 6.0
    plan["shots"][1]["params"] = {"beat_freeze_cut": True}
    plan["shots"][1]["renderer"] = "beat_freeze_cut"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-beat-freeze-cut" in out
    assert "bfc-card" in out and "bfc-hit" in out
    assert "DROP" in out and "FREEZE" in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line)
    assert "visibility" not in tween_src
    assert "filter" not in tween_src
    assert "width:" not in tween_src
    assert "height:" not in tween_src
    assert 'tl.fromTo("#shot-01",' not in out
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "#C8453D" in css
    assert ".bfc-card" in css
    assert ".bfc-bar" in css
    bfc = css.split(".fs-beat-freeze-cut", 1)[1].split(".fs-swap-box", 1)[0]
    assert "#E63946" in bfc
    assert "#0B132B" in bfc
    assert "#1A1F2E" in bfc
    assert "#C7C9D1" in bfc
    assert "#C8453D" not in bfc
    assert "#00E5C7" not in bfc and "#00e5c7" not in bfc
    assert "#00E5FF" not in bfc and "#00e5ff" not in bfc


def test_logo_brand_close_overlay_is_a_lockup_not_a_pill(plan, assets, brandbook):
    """Identity close занимает окно CTA: вордмарк, не пилюля подписки."""
    plan["overlays"][2] = {
        "type": "cta", "start": 8.0, "end": 10.0,
        "template": "outro-cta/logo-brand-close",
        "renderer": "logo_brand_close",
        "params": {"logo_close": True, "exit": "none", "wordmark": "РЕДШИФТ",
                   "tagline": "Пиши код. Шли на орбиту.", "url": "redshift.shorts"},
    }
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "lbc-mark" in out
    assert "lbc-dot" in out
    assert out.count("lbc-ch") == len("РЕДШИФТ")
    assert "redshift.shorts" in out
    assert 'class="pill"' not in out
    assert 'id="ovl-02-pill"' not in out
    assert "cqw" not in out
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert ".lbc-mark" in css
    assert ".lbc-dot" in css


def test_lt_accent_underline_overlay_reaches_the_markup(plan, assets, brandbook):
    plan["overlays"][1] = {
        "type": "plaque", "start": 0.2, "end": 5.0,
        "template": "lower-thirds/accent-underline",
        "params": {"name": "МАЙЯ ЧЕН", "role": "ВЕДУЩАЯ · НЕЙРОФИЗИОЛОГ",
                   "accent_underline": True},
    }
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "lt-accent-underline" in out
    assert "lt-au-rule" in out
    assert "МАЙЯ ЧЕН" in out
    assert "#ovl-01-name" in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line
        or "tl.set" in line)
    assert "visibility" not in tween_src
    assert "scaleX:0" in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "Space Mono" in css
    assert "#C8453D" in css
    assert "#46e5b7" not in css
    assert "Oswald" in css


def test_lt_clean_bar_overlay_reaches_the_markup(plan, assets, brandbook):
    plan["overlays"][1] = {
        "type": "plaque", "start": 0.2, "end": 5.0,
        "template": "lower-thirds/clean-bar",
        "params": {"name": "Майя Чен", "role": "Ведущая · нейрофизиолог",
                   "clean_bar": True},
    }
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "lt-clean-bar" in out
    assert "lt-cb-tab" in out and "lt-cb-wipe" in out
    assert "Майя Чен" in out
    assert "#ovl-01-wipe" in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line
        or "tl.set" in line)
    assert "visibility" not in tween_src
    assert "clip-path" not in tween_src and "clipPath" not in tween_src
    assert "scaleX:0" in tween_src and "scaleY:0" in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "Montserrat" in css
    assert "#C8453D" in css
    assert "#ff5a36" not in css


def test_lt_dark_card_overlay_reaches_the_markup(plan, assets, brandbook):
    plan["overlays"][1] = {
        "type": "plaque", "start": 0.2, "end": 5.0,
        "template": "lower-thirds/dark-card",
        "params": {"name": "Майя Чен", "role": "Ведущая · нейрофизиолог",
                   "dark_card": True},
    }
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "lt-dark-card" in out
    assert "lt-dc-rule" in out
    assert "Майя Чен" in out
    assert "#ovl-01-card" in out
    tween_src = "".join(
        line for line in out.splitlines() if "tl.fromTo" in line or "tl.to" in line
        or "tl.set" in line)
    assert "visibility" not in tween_src
    assert "scaleX:0" in tween_src
    css = build_css(brandbook, {"subtitle": "Nunito-ExtraBold.ttf"})
    assert "Montserrat" in css
    assert "#C8453D" in css
    assert "#f5b942" not in css
    assert "#16181d" in css


def test_source_card_overlay_uses_the_renderer(plan, assets, brandbook):
    plan["overlays"][0]["renderer"] = "chat_thread"
    plan["overlays"][0]["params"] = {
        "prompt": "что внутри", "snippet": "Квантовый чип. Сто кубит.",
    }
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "chat-thread" in out
    assert "ct-row" in out


def test_dataviz_overlay_reaches_the_markup(plan, assets, brandbook):
    plan["overlays"].insert(0, {
        "type": "dataviz", "start": 0.2, "end": 2.4,
        "template": "data-viz/compare-bars",
        "params": {"values": [66, 28], "labels": ["A", "B"]},
    })
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "dv-bar" in out


def test_animated_bar_chart_overlay_reaches_the_markup(plan, assets, brandbook):
    plan["overlays"].insert(0, {
        "type": "dataviz", "start": 0.2, "end": 2.4,
        "template": "data-viz/animated-bar-chart",
        "params": {
            "values": [42, 72, 56, 88, 64, 95, 78],
            "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"],
            "kpi": "+42%",
        },
    })
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "abc-chart" in out
    assert "abc-grow" in out
    assert "+42%" in out
    node = next(line for line in out.splitlines() if "abc-chart" in line)
    assert "dv-bar" not in node
    assert "stat-card" not in node


def test_bar_chart_race_overlay_reaches_the_markup(plan, assets, brandbook):
    plan["overlays"].insert(0, {
        "type": "dataviz", "start": 0.2, "end": 6.0,
        "template": "data-viz/bar-chart-race",
        "params": {
            "title": "Streaming Subscribers by Service",
            "periods": ["2019", "2020", "2021", "2022", "2023", "2024"],
            "series": [
                {"label": "Northwind", "values": [42, 58, 71, 96, 118, 131]},
                {"label": "Cobalt", "values": [30, 46, 68, 92, 126, 168]},
                {"label": "Ferry", "values": [55, 62, 66, 70, 74, 79]},
            ],
        },
    })
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "bcr-chart" in out
    assert "Northwind" in out and "Cobalt" in out
    node = next(line for line in out.splitlines() if "bcr-chart" in line)
    assert "dv-bar" not in node
    assert "abc-" not in node


def test_chart_story_overlay_reaches_the_markup(plan, assets, brandbook):
    plan["overlays"].insert(0, {
        "type": "dataviz", "start": 0.2, "end": 5.0,
        "template": "data-viz/chart-story",
        "params": {
            "values": [12, 28, 45, 64],
            "labels": ["Q1", "Q2", "Q3", "Q4"],
            "emphasize": 3,
            "unit": "%",
        },
    })
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "cst-chart" in out
    assert "cst-bg" in out
    assert "Q1" in out and "64%" in out
    node = next(line for line in out.splitlines() if "cst-chart" in line)
    assert "dv-bar" not in node
    assert "abc-" not in node
    assert "bcr-" not in node


def test_conic_progress_ring_overlay_reaches_the_markup(plan, assets, brandbook):
    plan["overlays"].insert(0, {
        "type": "dataviz", "start": 0.2, "end": 4.2,
        "template": "data-viz/conic-progress-ring",
        "params": {"progress": 100, "label": "100", "thickness": 12},
    })
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "cpr-chart" in out
    assert "cpr-bg" in out
    assert "cpr-paint" in out
    node = next(line for line in out.splitlines() if "cpr-chart" in line)
    assert "dv-donut" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "cst-" not in node
    assert "dcl-" not in node


def test_mk_line_graph_overlay_reaches_the_markup(plan, assets, brandbook):
    plan["overlays"].insert(0, {
        "type": "dataviz", "start": 0.2, "end": 7.2,
        "template": "data-viz/mk-line-graph",
        "params": {
            "series": [
                {"name": "Renders", "values": [12, 26, 22, 38, 44, 58]},
                {"name": "Projects", "values": [8, 14, 18, 16, 28, 36]},
            ],
            "xLabels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
        },
    })
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "mlg-chart" in out
    assert "mlg-bg" in out
    assert "mlg-line" in out
    assert "Renders" in out and "Projects" in out
    node = next(line for line in out.splitlines() if "mlg-chart" in line)
    assert "dv-bar" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "cst-" not in node
    assert "cpr-" not in node
    assert "dcl-" not in node
    assert "mk-lg-" not in node


def test_decline_chart_overlay_reaches_the_markup(plan, assets, brandbook):
    plan["overlays"].insert(0, {
        "type": "dataviz", "start": 0.2, "end": 4.2,
        "template": "data-viz/decline-chart",
        "params": {"start_value": 82, "end_value": 34, "label": "Retention"},
    })
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "dcl-chart" in out
    assert "dcl-bg" in out
    assert "dcl-line" in out
    assert "Retention" in out
    node = next(line for line in out.splitlines() if "dcl-chart" in line)
    assert "dv-bar" not in node
    assert "abc-" not in node
    assert "bcr-" not in node
    assert "cst-" not in node
    assert "cpr-" not in node
    assert "mlg-" not in node
    """С фиксированным кеглем «ПЕРЕЖИВЁШЬ» занимало 2400 px при кадре 1080.

    Поймано кадром готового MP4, а не разметкой: QC-7 меряет safe zones по
    оверлеям, а полноэкранный текст оверлеем не является и через проверку
    проходил.
    """
    from src.lib.render.hyperframes.templates import text_width

    safe_x = int(brandbook["safe_zones"]["work_area"]["x_min"])
    available = 1080 - 2 * safe_x
    for word in ("ПЕРЕЖИВЁШЬ", "НЕПРЕДСКАЗУЕМОСТЬ", "ХУЖЕ", "ДА"):
        plan["shots"][1]["content"] = word
        out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
        node = next(l for l in out.splitlines() if "fullscreen-text" in l)
        size = int(re.search(r"font-size:(\d+)px", node).group(1))
        assert text_width(word, size) <= available + 1e-6, f"{word} при кегле {size}"


def test_short_fullscreen_word_keeps_the_brandbook_ceiling(plan, assets, brandbook):
    """Подгонка не должна мельчить то, что и так влезает."""
    plan["shots"][1]["content"] = "ДА"
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    node = next(l for l in out.splitlines() if "fullscreen-text" in l)
    ceiling = int(brandbook["fullscreen_text"]["size_px"][1])
    assert int(re.search(r"font-size:(\d+)px", node).group(1)) == ceiling


def test_hero_media_paths_are_rewritten_to_the_project(plan, assets, brandbook):
    """HyperFrames резолвит медиа от каталога проекта.

    Незаменённый абсолютный путь — не ошибка сборки, а пустой прямоугольник в
    кадре, который заметен только на рендере.
    """
    assets["/w/icons/google.png"] = "assets/m009_google.png"
    plan["shots"][2]["hero"] = {
        "template": "hero-devices/brand-pill", "renderer": "hero-brand-pill",
        "params": {"label": "Google", "icon": "/w/icons/google.png"},
        "file": None, "duration": None, "carries_line": False,
    }
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "/w/icons/google.png" not in out
    assert "assets/m009_google.png" in out


def test_hero_media_path_outside_the_project_is_dropped(plan, assets, brandbook):
    """Лучше приём без картинки, чем ссылка в никуда."""
    plan["shots"][2]["hero"] = {
        "template": "hero-devices/brand-pill", "renderer": "hero-brand-pill",
        "params": {"label": "Google", "icon": "/нет/такого.png"},
        "file": None, "duration": None, "carries_line": False,
    }
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "/нет/такого.png" not in out
    assert "hero-brand-pill" in out, "приём обязан остаться, потеряв только иконку"


def test_bubble_cuts_the_circle_with_a_mask_not_a_radius(plan, assets, brandbook):
    """Продюсер рисует кадры видео в коробку, игнорируя border-radius.

    Проверено зумом: второе видео со скруглением давало квадрат. Круг режется
    SVG-маской, и сквозь дырку виден сам аватар — второе видео не нужно.
    """
    plan["shots"][2]["hero"] = {
        "template": "hero-devices/bubble-card", "renderer": "hero-bubble-card",
        "params": {"lines": ["ни одна компания"], "face_cx": 540, "face_cy": 550},
        "file": None, "duration": None, "carries_line": True,
    }
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "<mask" in out and "<circle" in out
    assert out.count('class="clip hero-bubble-card"') == 1
    # Ведущий приближается внутри дырки — иначе это заслонка, а не смена плана.
    assert any('"#avatar-00"' in l and "scale" in l for l in out.splitlines())
