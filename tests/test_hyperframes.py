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


def test_fullscreen_word_never_leaves_the_frame(plan, assets, brandbook):
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
