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
    TRACK_SUBTITLE, CompositionBuilder, _lay_out_tracks, _num,
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
    assert "КУ&lt;И&gt;&amp;Я" in out


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

def test_subtitle_word_is_cleaned_and_cased(plan, assets, brandbook):
    """До переноса правило жило внутри отрисовки, и HTML-движок его не видел.

    Регистр субтитра сменился на верхний вместе с новым начертанием: заказчик
    прислал эталонный кадр, и там слово набрано прописными.
    """
    plan["subtitles"] = [
        {"display": "Падение", "start": 0.0, "end": 0.5, "emphasis": False},
        {"display": "счётчик.", "start": 0.5, "end": 1.0, "emphasis": False},
        {"display": "ОТО", "start": 1.0, "end": 1.5, "emphasis": False},
    ]
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert ">ПАДЕНИЕ<" in out
    assert ">СЧЁТЧИК<" in out and "СЧЁТЧИК." not in out
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


def test_transition_on_the_avatar_does_not_reach_back_before_its_shot(plan, assets,
                                                                     brandbook):
    """`fromTo` применяет `from` при сборке ленты, а клип живёт весь сегмент.

    Наезд на третьем шоте откатывал ведущего в `scale:0.92` с нулевой секунды:
    первые секунды он сидел в прямоугольнике 0.92 кадра с тёмными полями по
    краям. Твин обязан нести запрет, а у клипа обязана быть опора в начале —
    иначе перемотка назад вернёт его в то же начальное состояние.
    """
    plan["shots"][2]["transition"] = {"renderer": "zoom_punch", "duration": 0.32,
                                      "params": {"from_scale": 1.18}}
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    tween = next(l for l in out.splitlines() if "scale:1.18" in l)
    assert "immediateRender:false" in tween, tween
    anchor = [l for l in out.splitlines()
              if 'tl.set("#avatar-00"' in l and "scale:1" in l]
    assert anchor, "у клипа ведущего нет опоры для перемотки"


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

# Чем приём наполняется, зависит от приёма: слово, знаки, строки. Пустой
# рендерер молча отдаёт пустой Piece, и проверка разметки прошла бы вхолостую.
_HERO_FILL = {
    "hero-icons": {"icons": [{"glyph": "chip"}, {"glyph": "clock"}]},
}


def _with_hero(plan, renderer, **params):
    plan["shots"][2]["hero"] = {
        "template": f"hero-devices/{renderer}", "renderer": renderer,
        "params": {"word": "РАЗМЕР", **_HERO_FILL.get(renderer, {}), **params},
        "file": None, "duration": None,
    }
    return plan


@pytest.mark.parametrize("renderer", ["hero-icons", "hero-headline",
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


# --- тайминг: округление не имеет права создавать наезд ------------------------

def _clips(markup: str) -> list[tuple[int, float, float]]:
    """(трек, начало, конец) по тем числам, которые прочитает движок."""
    out = []
    for start, duration, track in re.findall(
            r'data-start="([\d.]+)" data-duration="([\d.]+)" data-track-index="(\d+)"',
            markup):
        out.append((int(track), float(start), float(start) + float(duration)))
    return out


def test_no_two_clips_on_a_track_overlap(markup):
    """Инвариант вёрстки: на треке клипы идут встык или с зазором, но не внахлёст."""
    by_track: dict[int, list[tuple[float, float]]] = {}
    for track, start, end in _clips(markup):
        by_track.setdefault(track, []).append((start, end))
    for track, spans in by_track.items():
        spans.sort()
        for (_, end), (start, _) in zip(spans, spans[1:]):
            assert end <= start + 1e-9, (
                f"трек {track}: клип кончается в {end}, следующий начинается в {start}")


def test_rounding_never_pushes_a_word_onto_its_neighbour(plan, assets, brandbook):
    """Границы округляются один раз, до вычитания, — иначе миллисекунда наезда.

    Числа не выдуманы: на них упал живой прогон 0047. Начало 49.3568 печатается
    как 49.357, длительность 0.4996 — как 0.5, сумма 49.857 при соседе с 49.856.
    Порознь округлённые начало и длительность обе уехали вверх.
    """
    plan["duration_sec"] = 60.0
    plan["subtitles"] = [
        {"display": "первое", "start": 49.3568, "end": 49.8564, "emphasis": False},
        {"display": "второе", "start": 49.8564, "end": 50.3, "emphasis": False},
    ]
    markup = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    words = [c for c in _clips(markup) if c[0] == TRACK_SUBTITLE]
    assert len(words) == 2
    assert words[0][2] <= words[1][1] + 1e-9, "наезд субтитра на соседа"


def test_short_word_is_stretched_but_not_into_its_neighbour(plan, assets, brandbook):
    """Пол в 50 мс уступает соседу: растянуть слово ценой падения рендера нельзя."""
    plan["subtitles"] = [
        {"display": "и", "start": 1.0, "end": 1.01, "emphasis": False},
        {"display": "вот", "start": 1.02, "end": 1.4, "emphasis": False},
    ]
    markup = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    words = sorted(c for c in _clips(markup) if c[0] == TRACK_SUBTITLE)
    assert words[0][2] == pytest.approx(1.02, abs=1e-9), "слово растянуто до соседа"
    assert words[0][2] <= words[1][1] + 1e-9


# --- настоящий lint движка ----------------------------------------------------

def test_composition_passes_the_engine_lint():
    """Композиция со всеми переходами и приёмами обязана проходить lint.

    Правила lint ловят то, чего не видит ни один наш тест: наезд клипов на
    треке, затухание без гашения, видео внутри тайминга. Раньше узнать про них
    можно было только из упавшего прогона Actions — четверть часа и деньги на
    поиск футажа, а падение в самом конце. Три захода на 0047 ушли так.

    Тест пропускается, если движка нет в окружении: он не должен превращать
    отсутствие npm-пакета в красный прогон.
    """
    import shutil
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    if not shutil.which("hyperframes"):
        pytest.skip("hyperframes не установлен: npm install -g hyperframes")

    tool = Path(__file__).resolve().parents[1] / "tools" / "lint_composition.py"
    with tempfile.TemporaryDirectory() as td:
        proc = subprocess.run([sys.executable, str(tool), "--keep", td],
                              capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("word,fits_at_max", [
    ("ДВЕНАДЦАТЬ", False),   # 1498 px при 260 — почти в полтора кадра
    ("ВОСЕМЬДЕСЯТ", False),  # 1609 px при 260
    ("ТЕЧЁТ", True),         # 621 px — кегль трогать незачем
])
def test_word_behind_head_never_leaves_the_frame(plan, assets, brandbook,
                                                 word, fits_at_max):
    """Обрезок слова читается как поломка, а не как приём.

    На 0047 «ДВЕНАДЦАТЬ» стояло константным кеглем 260 px и уходило за оба
    края: в кадре было «ДВ…АДЦ».
    """
    import re as _re

    from src.lib.render.hyperframes.templates import text_width

    plan["_blocks"] = [{"id": "b2", "emphasis_word": word}]
    markup = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    found = _re.search(r'class="clip behind-head" style="font-size:(\d+)px"', markup)
    assert found, "слова за головой нет в разметке"

    size = int(found.group(1))
    margin = brandbook["safe_zones"]["work_area"]["x_min"]
    available = brandbook["canvas"]["width"] - 2 * margin
    assert text_width(word.upper(), size) <= available + 1
    top = brandbook["text_behind_head"]["size_px"][1]
    assert (size == top) is fits_at_max, "кегль обязан падать только когда нужно"


def test_word_behind_head_is_glass_not_a_dark_slab(brandbook):
    """Тёмное по тёмному не читается, сплошное белое спорит с ведущим.

    Слово набиралось цветом ink с прозрачностью 0.55. Кадры канала тёмные, и
    на них его просто не было видно. Стекло решает обе задачи: заливка почти
    прозрачна, форму держит светлый контур по краю.
    """
    css = build_css(brandbook, {})
    block = css.split(".behind-head{", 1)[1].split("}", 1)[0]
    assert "color:transparent" in block, "заливка обязана быть прозрачной"
    assert "background-clip:text" in block, "градиент обязан обрезаться буквами"
    assert "-webkit-text-stroke" in block, "без контура стекло не читается"
    assert "drop-shadow" in block, (
        "тень нужна по буквам: text-shadow у прозрачного текста рисует "
        "прямоугольник")
    assert "color:var(--color-ink)" not in block


def test_fullscreen_text_puts_its_footage_on_a_separate_track(plan, assets, brandbook):
    """Фон под текстом — отдельный клип, а не вложенное видео.

    Видео внутри клипа с таймингом застывает первым кадром (lint:
    video_nested_in_timed_element), а трек шота уже занят самим текстом.
    Соседний трек тоже занят: там встык стоят соседние шоты.
    """
    import re as _re

    from src.lib.render.hyperframes.composition import TRACK_FS_BG

    plan["shots"][1]["file"] = "/w/shots/a.mp4"
    markup = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")

    found = _re.search(r'<video id="shot-01-bg"[^>]*data-track-index="(\d+)"', markup)
    assert found, "фон под полноэкранным текстом не собрался"
    assert int(found.group(1)) == TRACK_FS_BG
    assert 'class="clip fullscreen-text over-media"' in markup, (
        "текст обязан знать, что под ним материал: иначе заливка перекроет его")


def test_fullscreen_text_without_footage_falls_back_to_the_scene(plan, assets, brandbook):
    """Материала нет — под фразой сцена ролика, а не пустая заливка.

    На 0047 материал под этот кадр не нашёлся, и «180 ГРАДУСОВ» встало чёрными
    буквами по белому листу посреди тёмного ролика — на полторы секунды кадр
    гас в пустоту. Заказчик это уже называл: «сзади фон должен быть какой-нибудь
    тоже либо сгенерированный, либо футаж». Сцена по теме ролика тёмная, она уже
    собрана для кадров с альфой, и терять её незачем.
    """
    from src.lib.render.hyperframes.composition import TRACK_FS_BG

    plan["shots"][1].pop("file", None)
    markup = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert f'<div id="shot-01-bg" class="clip shot-bg" data-start="3"' in markup
    assert f'data-track-index="{TRACK_FS_BG}"><div class="vfx scene-' in markup
    # Затемнение остаётся: буквы лежат на картинке, а не на плоском цвете.
    assert 'class="clip fullscreen-text over-media"' in markup


def test_the_whole_line_never_burns_red(plan, assets, brandbook):
    """§3.3.2: красным горит слово, а не строка.

    P11 акцент для фразы из одного слова не назначает вовсе, но правило живёт в
    брендбуке, а не в одном шаге: план приходит и из кэша, и с прошлой версии
    конвейера, и рендер обязан отказать сам.
    """
    plan["shots"][1]["content"] = "ПЕРЕЖИВЁШЬ"
    plan["shots"][1]["accent_word"] = "ПЕРЕЖИВЁШЬ"
    markup = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert 'class="accent"' not in markup


def test_the_subtitle_glows_red_and_never_black(brandbook):
    """Заказчик прислал эталонный кадр и правило: вместо чёрной тени — тонкий
    красный градиент с размытием.

    Проверяется не «красиво», а состав: чёрного в субтитре нет вообще, ободок
    и зарево собраны из акцентных цветов брендбука, а самое широкое кольцо
    зарева и правда размыто широко — иначе это снова обводка, а не градиент.
    """
    from src.lib.render.hyperframes.brand_css import build_css

    css = build_css(brandbook, {})
    rule = re.search(r"\.word\{[^}]*text-shadow:([^;}]*)\}", css).group(1)
    assert "rgba(0,0,0" not in rule and "#000" not in rule, "чёрная тень вернулась"

    accent = brandbook["colors"]["accent"].lstrip("#")
    rgb = ",".join(str(int(accent[i:i + 2], 16)) for i in (0, 2, 4))
    assert f"rgba({rgb}," in rule, "ободок не из акцента брендбука"
    blurs = [int(m) for m in re.findall(r"0 0 (\d+)px", rule)]
    assert max(blurs) >= 60, f"зарево слишком узкое: {blurs}"

    # Акцентное слово отличается не только заливкой: у него своё гало, иначе
    # красное по красному потеряло бы край.
    emphasis = re.search(r"\.word\.emphasis\{[^}]*text-shadow:([^;}]*)\}", css).group(1)
    assert emphasis != rule
    # На светлой сцене светлый ободок пропадает вместе с фоном.
    light = re.search(r"\.stage-light \.word\.emphasis\{[^}]*\}", css)
    assert light, "у акцента нет правила для светлой сцены"


class TestOverlaysCarryTheirText:
    """Плашка обязана показывать то, что в неё положил P11.

    Читались ключи `content` и `kicker`, а план пишет `text` и `subtitle` —
    таких в нём нет ни одного. Плашка выходила пустой: в кадре готового
    ролика белая полоса без единой буквы, и так дважды за ролик. Ни lint, ни
    разметка, ни QC этого не видят — только кадр.
    """

    def _body(self, ovl):
        from src.lib.render.hyperframes.composition import CompositionBuilder

        return CompositionBuilder._overlay_body(
            object.__new__(CompositionBuilder), "ovl-01", ovl) or ""

    def test_a_plaque_shows_the_text_the_plan_gave_it(self):
        body = self._body({"type": "plaque",
                           "params": {"text": "Проверить нечем", "position": "middle"}})
        assert "Проверить нечем" in body

    def test_a_plaque_shows_its_kicker(self):
        body = self._body({"type": "plaque",
                           "params": {"text": "nature.com", "subtitle": "источник"}})
        assert "nature.com" in body and "источник" in body

    def test_the_button_shows_the_requested_word(self):
        """Без ключа кнопка молча показывала запасное «Подпишись»."""
        body = self._body({"type": "cta", "params": {"text": "ПОДПИСАТЬСЯ"}})
        assert "ПОДПИСАТЬСЯ" in body

    def test_an_overlay_never_renders_empty(self):
        """Пустая плашка — белая полоса в кадре; лучше не рисовать вовсе."""
        for ovl in ({"type": "plaque", "params": {"text": "Слово"}},
                    {"type": "cta", "params": {"text": "ЖМИ"}}):
            body = self._body(ovl)
            inner = body.split("__TIMING__>", 1)[-1]
            assert inner.strip("</div> \n"), f"пустая плашка: {ovl}"


class TestAnEmptySlotNeverShowsAHole:
    """Слот без материала обязан быть закрыт, а не показывать подложку сцены.

    На пересборке 0047 три кадра вышли чистым белым полотном с одиноким
    субтитром посреди тёмного ролика: «ГРАНИТ» дважды и «ТУНДРЫ». Дыра
    оказалась не чёрной, а светлой — ``.stage-bg`` заливает кадр
    ``--color-bg-light`` (#F7F5F3), и слот без медиа показывал именно её.

    Пустой слот при этом законен: генерация вывела бы долю AI-футажа за 35 %,
    и P9 честно отказался — четыре слота остались без материала. Отказ от
    генерации не повод показывать зрителю пустой лист.
    """

    def _markup(self, plan, assets, brandbook, kind):
        plan = {**plan, "shots": [dict(s) for s in plan["shots"]]}
        plan["shots"][0].update({"kind": kind, "file": None})
        return CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")

    @pytest.mark.parametrize("kind", ["footage", "meme"])
    def test_the_slot_still_gets_a_clip(self, plan, assets, brandbook, kind):
        markup = self._markup(plan, assets, brandbook, kind)
        assert 'id="shot-00"' in markup, f"{kind}: слот без файла не дал ни одного элемента"

    @pytest.mark.parametrize("kind", ["footage", "meme"])
    def test_the_clip_covers_the_whole_slot(self, plan, assets, brandbook, kind):
        """Полдыры — та же дыра: окно запасного фона совпадает со слотом."""
        markup = self._markup(plan, assets, brandbook, kind)
        node = re.search(r'<div id="shot-00"[^>]*>', markup)
        assert node, f"{kind}: элемента слота нет"
        assert 'data-start="0"' in node.group(0), node.group(0)
        assert 'data-duration="3"' in node.group(0), node.group(0)

    @pytest.mark.parametrize("kind", ["footage", "meme"])
    def test_the_backdrop_is_the_scene_not_the_light_stage(self, plan, assets, brandbook, kind):
        """Фон берётся тот же, что за ведущим: по теме и тёмный."""
        markup = self._markup(plan, assets, brandbook, kind)
        node = re.search(r'<div id="shot-00"[^>]*>(.*?)</div></div>', markup, re.S)
        assert node and "scene-" in node.group(1), \
            f"{kind}: запасной фон не несёт сцену ролика"

    def test_a_slot_with_a_file_is_untouched(self, plan, assets, brandbook):
        """Запасной фон не имеет права подменять нормальный материал."""
        markup = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
        assert "assets/m000_a.mp4" in markup
        node = re.search(r'<[^>]*id="shot-00"[^>]*>', markup)
        assert node and "shot-bg" not in node.group(0), node.group(0)
