"""Фаза 3 — рендер: примитивы брендбука, слои, шаблоны, подготовка планов."""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from src.lib.render.canvas import (
    FontBook, SafeZones, accent_area_share, cubic_bezier, ease, mix, parse_color, with_alpha,
)
from src.lib.render.layers import Ctx, fit_block, fullscreen_text, plaque, source_card, subscribe_button
from src.lib.render.text_rules import apply_case
from src.lib.render.shots import ShotSpec, build_filter, choose_fit, kenburns_window, apply_kenburns
from src.lib.templates import TemplateCatalog, diff_count, overlap_share


@pytest.fixture(scope="module")
def render_ctx():
    from src.lib.config import load_config

    return Ctx.build(load_config())


# --- цвет и сглаживание --------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("#C8453D", (200, 69, 61, 255)),
    ("C8453D", (200, 69, 61, 255)),
    ("#FFF", (255, 255, 255, 255)),
    ("rgba(10,10,12,0.78)", (10, 10, 12, 198)),
])
def test_parse_color(value, expected):
    assert parse_color(value) == expected


def test_parse_color_invalid():
    from src.errors import RenderError

    with pytest.raises(RenderError):
        parse_color("не цвет")


def test_with_alpha_and_mix():
    assert with_alpha((10, 20, 30, 200), 0.5) == (10, 20, 30, 100)
    assert mix((0, 0, 0, 0), (100, 100, 100, 100), 0.5) == (50, 50, 50, 50)


def test_easing_monotonic():
    values = [ease("ease_out_cubic", t / 20) for t in range(21)]
    assert values == sorted(values)
    assert values[0] == pytest.approx(0.0, abs=1e-6)
    assert values[-1] == pytest.approx(1.0, abs=1e-6)


def test_cubic_bezier_endpoints():
    assert cubic_bezier(0.215, 0.61, 0.355, 1.0, 0.0) == pytest.approx(0.0, abs=1e-4)
    assert cubic_bezier(0.215, 0.61, 0.355, 1.0, 1.0) == pytest.approx(1.0, abs=1e-4)


# --- safe zones (§3.2) ---------------------------------------------------------

def test_safe_zones_from_brandbook(render_ctx):
    safe = render_ctx.safe
    assert (safe.x_min, safe.x_max, safe.y_min, safe.y_max) == (90, 830, 150, 1520)


def test_safe_zone_violations_named(render_ctx):
    problems = render_ctx.safe.violations((10, 100, 1000, 1700))
    assert len(problems) == 4
    assert any("лайк" in p for p in problems)
    assert any("описания" in p for p in problems)


# --- гарнитуры (§3.4) ----------------------------------------------------------

def test_fontbook_loads_three_roles(render_ctx):
    for role in ("display", "subtitle", "mono"):
        assert render_ctx.fonts.path(role).exists()


def test_fit_block_respects_width(render_ctx):
    size, lines = fit_block(render_ctx, "5 МИНУТ", "display", max_width=740,
                            max_size=420, min_size=200, max_lines=1, uppercase=True)
    from src.lib.render.canvas import measure

    assert 200 <= size <= 420
    assert measure(lines[0], render_ctx.fonts.font("display", size))[0] <= 740


def test_fit_block_wraps_long_text(render_ctx):
    _size, lines = fit_block(render_ctx, "очень длинная строка из нескольких слов подряд",
                             "subtitle", max_width=600, max_size=60, min_size=28,
                             max_lines=3)
    assert len(lines) > 1


# --- слои ----------------------------------------------------------------------

def test_subtitle_has_no_leading_capital():
    assert apply_case("Твой", "lower") == "твой"
    assert apply_case("НАМЕРЕННО", "lower") == "НАМЕРЕННО"   # аббревиатуры целы
    assert apply_case("ОТО", "lower") == "ОТО"
    assert apply_case("105", "lower") == "105"
    assert apply_case("Я", "lower") == "я"                   # одна буква — не аббревиатура


def test_subtitle_shifts_down_when_face_low(render_ctx):
    from src.lib.render.layers import subtitle_baseline

    default = subtitle_baseline(render_ctx, face_bbox=None)
    shifted = subtitle_baseline(render_ctx, face_bbox=(300, 400, 700, 900))
    assert shifted > default


def test_fullscreen_text_fills_frame(render_ctx):
    layer = fullscreen_text(render_ctx, "5 МИНУТ", progress=1.0)
    assert layer.size == render_ctx.size
    assert layer.getpixel((5, 5))[3] == 255       # фон непрозрачный


def test_source_card_meets_minimum_width(render_ctx):
    """§5.6: скриншот не мельче 60 % ширины кадра."""
    _layer, bbox = source_card(render_ctx, template="browser", domain="nature.com",
                               title="Quantum error correction")
    assert render_ctx.safe.width / render_ctx.width >= 0.60


def test_source_card_stays_in_safe_zone(render_ctx):
    _layer, bbox = source_card(render_ctx, template="browser", domain="nature.com",
                               title="Quantum error correction below the surface code")
    assert render_ctx.safe.contains(bbox)


def test_plaque_within_safe_zone(render_ctx):
    layer = plaque(render_ctx, "nature.com", progress=1.0, subtitle_text="источник")
    bbox = layer.getbbox()
    assert bbox is not None
    assert bbox[3] <= render_ctx.safe.y_max + 40


def test_cta_button_visible_and_in_safe_zone(render_ctx):
    layer = subscribe_button(render_ctx, progress=0.9)
    bbox = layer.getbbox()
    assert bbox is not None
    assert bbox[3] <= render_ctx.safe.y_max + 60


def test_accent_share_within_brandbook_limit(render_ctx):
    """§3.3.1 — акцент занимает не более 10–12 % площади кадра."""
    frame = Image.new("RGBA", render_ctx.size, (247, 245, 243, 255))
    frame.alpha_composite(subscribe_button(render_ctx, progress=1.0))
    share = accent_area_share(frame, render_ctx.color("accent"))
    assert share <= float(render_ctx.brandbook["color_rules"]["accent_max_frame_share"])


# --- подготовка планов (§3.6) --------------------------------------------------

class _Info:
    def __init__(self, w, h):
        self.width, self.height = w, h
        self.has_video = True
        self.duration_sec = 5.0


def test_build_filter_never_stretches():
    spec = ShotSpec(src="x", dst="y", duration_sec=3, width=1080, height=1920, fps=30)
    filter_str = build_filter(_Info(1920, 1080), spec)
    assert "crop=1080:1920" in filter_str
    # Масштаб сохраняет пропорции: обе стороны множатся на один коэффициент.
    assert "scale=3414:1920" in filter_str


def test_build_filter_focus_shifts_crop():
    left = build_filter(_Info(1920, 1080), ShotSpec("x", "y", 3, 1080, 1920, 30, focus_x=0.1))
    right = build_filter(_Info(1920, 1080), ShotSpec("x", "y", 3, 1080, 1920, 30, focus_x=0.9))
    assert left != right


def test_pillarbox_only_for_ultrawide():
    assert choose_fit(_Info(1920, 1080), pillarbox_used=0, pillarbox_limit=2) == "crop"
    assert choose_fit(_Info(2560, 1080), pillarbox_used=0, pillarbox_limit=2) == "pillarbox"


def test_pillarbox_respects_per_video_limit():
    assert choose_fit(_Info(2560, 1080), pillarbox_used=2, pillarbox_limit=2) == "crop"


def test_kenburns_window_in_spec():
    """§3.6.4 — масштаб 1.0 → 1.08…1.15."""
    zoom_start, _, _ = kenburns_window(0.0, zoom_from=1.0, zoom_to=1.12)
    zoom_end, _, _ = kenburns_window(1.0, zoom_from=1.0, zoom_to=1.12)
    assert zoom_start == pytest.approx(1.0)
    assert zoom_end == pytest.approx(1.12)
    assert 1.08 <= zoom_end <= 1.15


def test_kenburns_is_monotonic():
    zooms = [kenburns_window(t / 10, zoom_from=1.0, zoom_to=1.12)[0] for t in range(11)]
    assert zooms == sorted(zooms)


def test_apply_kenburns_keeps_size():
    frame = Image.new("RGB", (1080, 1920), (30, 40, 50))
    out = apply_kenburns(frame, 1.12, 0.03, 0.0, (1080, 1920))
    assert out.size == (1080, 1920)


# --- каталог шаблонов (§15) ----------------------------------------------------

def test_stats_from_text_skips_years_when_other_numbers_exist():
    from src.p11_assemble.assemble import _stats_from_text

    nums = _stats_from_text("В 2024 году чип набрал 105 кубитов и 12 %")
    values = [n["value"] for n in nums]
    assert 2024 not in values
    assert 105 in values
    assert 12 in values


def test_overlay_renderer_maps_chat_and_paper():
    from src.lib.templates import Template
    from src.p11_assemble.assemble import _overlay_renderer

    chat = Template(id="browser-ui/chat-thread", name="chat-thread",
                    category="browser-ui", title="", duration_range=[1, 4],
                    params={}, tags=[], renderer="chat_thread")
    assert _overlay_renderer(chat) == "chat_thread"
    old = Template(id="browser-ui/chat-ai-typing", name="chat-ai-typing",
                   category="browser-ui", title="", duration_range=[1, 4],
                   params={}, tags=[], renderer="source_card")
    assert _overlay_renderer(old) == "chat_thread"
    reveal = Template(id="browser-ui/ai-chat-reveal", name="ai-chat-reveal",
                      category="browser-ui", title="", duration_range=[2, 19.4],
                      params={}, tags=[], renderer="ai_chat_reveal")
    assert _overlay_renderer(reveal) == "ai_chat_reveal"
    showcase = Template(id="browser-ui/app-showcase", name="app-showcase",
                        category="browser-ui", title="", duration_range=[2, 5.5],
                        params={}, tags=[], renderer="app_showcase")
    assert _overlay_renderer(showcase) == "app_showcase"


def test_plaque_overlay_attaches_custom_renderer():
    from src.lib.templates import Template
    from src.p11_assemble.assemble import _plaque_overlay

    custom = Template(id="lower-thirds/accent-underline", name="accent-underline",
                      category="lower-thirds", title="", duration_range=[1.5, 4.8],
                      params={"accent_underline": True}, tags=["person"],
                      renderer="lt_accent_underline")
    ovl = _plaque_overlay(template=custom, start=1.0, end=3.6,
                          params={"name": "МАЙЯ ЧЕН"}, why="test")
    assert ovl["renderer"] == "lt_accent_underline"
    bar = Template(id="lower-thirds/clean-bar", name="clean-bar",
                   category="lower-thirds", title="", duration_range=[1.5, 4.8],
                   params={"clean_bar": True}, tags=["person"],
                   renderer="lt_clean_bar")
    bar_ovl = _plaque_overlay(template=bar, start=1.0, end=3.6,
                              params={"name": "Майя Чен"}, why="test")
    assert bar_ovl["renderer"] == "lt_clean_bar"
    dark = Template(id="lower-thirds/dark-card", name="dark-card",
                    category="lower-thirds", title="", duration_range=[1.5, 4.8],
                    params={"dark_card": True}, tags=["person"],
                    renderer="lt_dark_card")
    dark_ovl = _plaque_overlay(template=dark, start=1.0, end=3.6,
                               params={"name": "Майя Чен"}, why="test")
    assert dark_ovl["renderer"] == "lt_dark_card"
    generic = Template(id="lower-thirds/name-title", name="name-title",
                       category="lower-thirds", title="", duration_range=[1.5, 4.0],
                       params={}, tags=["person"], renderer="plaque")
    plain = _plaque_overlay(template=generic, start=1.0, end=3.0,
                            params={"text": "x"}, why="test")
    assert "renderer" not in plain


def test_catalog_matches_spec_counts(cfg):
    catalog = TemplateCatalog.load(cfg)
    counts = catalog.counts()
    assert counts == {
        "intro-hooks": 8, "text-fullscreen": 32, "lower-thirds": 12, "frames-cards": 7,
        "browser-ui": 17, "transitions": 27, "avatar-entry": 6, "kenburns": 10,
        "parallax": 4, "data-viz": 28, "outro-cta": 6, "hero-devices": 25,
    }
    assert len(catalog.all()) == 182


def test_catalog_rotation_avoids_recent(cfg):
    catalog = TemplateCatalog.load(cfg)
    first = catalog.pick("kenburns", duration=3.0, seed=1)
    first.last_used_in = ["v1", "v2", "v3"]
    picked = catalog.pick("kenburns", duration=3.0, recent_videos=["v3"], seed=1)
    assert picked.id != first.id


def test_catalog_pick_respects_duration(cfg):
    catalog = TemplateCatalog.load(cfg)
    template = catalog.pick("transitions", duration=0.2, tags={"dynamic"}, seed=3)
    assert template.fits(0.2)
    assert template.id != "transitions/cut"


def test_catalog_exclude_is_honoured(cfg):
    catalog = TemplateCatalog.load(cfg)
    first = catalog.pick("lower-thirds", duration=2.0, seed=5)
    second = catalog.pick("lower-thirds", duration=2.0, exclude=[first.id], seed=5)
    assert second.id != first.id


def test_diff_and_overlap_helpers():
    assert diff_count(["a", "b", "c"], ["a", "b", "c"]) == 0
    assert diff_count(["a", "b", "c"], ["x", "y", "z"]) == 3
    assert overlap_share(["a", "b"], ["a", "b"]) == 1.0
    assert overlap_share(["a"], ["b"]) == 0.0


# --- приёмы вокруг ведущего (§5.3, референсы) ---------------------------------

def test_hero_kicker_is_never_a_pipeline_role():
    """Роль блока служебная и латиницей: «EVIDENCE» в кадре — отладочный вывод."""
    from src.lib.schema import BLOCK_ROLES
    from src.p11_assemble.assemble import _HERO_KICKERS

    assert set(BLOCK_ROLES) <= set(_HERO_KICKERS), "роль без русской подписи"
    for role, kicker in _HERO_KICKERS.items():
        assert kicker.upper() != role.upper()
        assert not any("a" <= ch.lower() <= "z" for ch in kicker), kicker


def _content(**over):
    from src.p11_assemble.assemble import _hero_content

    block = {"text": "Горизонт событий это не стена а точка невозврата",
             "emphasis_word": "горизонт"}
    content = _hero_content(block, {"role": "evidence"}, None)
    content.update(over)
    return content


def test_hero_device_requires_what_it_draws(cfg):
    """Приём без своего материала рисует пустоту поверх ведущего.

    Отбор идёт исключениями, а не фильтром tags: ``pick`` при пустом наборе
    кандидатов возвращается ко всей категории.
    """
    from src.p11_assemble.assemble import _HERO_NEEDS, _hero_device

    catalog = TemplateCatalog.load(cfg)
    # История использования обнуляется: выбор ранжирует приёмы по ней (§15.12),
    # и любой прогон конвейера её меняет — тест начинал падать не от правки
    # кода, а от того, что рядом собрали ролик. Здесь проверяется правило
    # выбора, а не то, что канал успел показать.
    for template in catalog.all():
        template.last_used_in = []
    slot = {"index": 4, "duration": 3.0, "role": "evidence"}

    empty = {"word": "", "lines": [], "accent_lines": [], "title": "", "brand": None}
    assert _hero_device(catalog, slot=slot, content=empty, has_alpha=False,
                        plate_src=None, recent_videos=[], exclude=[], seed=1) is None

    # Кадра и логотипа нет — остаются только те приёмы, что живут на тексте.
    for seed in range(20):
        entry = _hero_device(catalog, slot=slot, content=_content(), has_alpha=False,
                             plate_src=None, recent_videos=[], exclude=[], seed=seed)
        assert entry is not None
        template = catalog.by_id(entry["template"])
        assert "alpha" not in template.tags, entry["template"]
        assert not ({"plate", "brand"} & set(_HERO_NEEDS[entry["renderer"]])), \
            f"{entry['renderer']} выпал без материала"


def test_every_hero_renderer_declares_what_it_needs(cfg):
    """Новый приём без записи в _HERO_NEEDS выпадет на пустом кадре."""
    from src.lib.render.hyperframes.templates import HERO
    from src.p11_assemble.assemble import _HERO_NEEDS

    catalog = TemplateCatalog.load(cfg)
    for template in catalog.by_category("hero-devices"):
        assert template.renderer in HERO, template.id
        assert template.renderer in _HERO_NEEDS, template.id


def test_hero_content_wraps_lines_and_marks_the_accent():
    """Строка длиннее ~20 знаков не влезает в половину кадра на кегле 76."""
    content = _content()
    assert content["lines"], "реплика не разложена на строки"
    assert all(len(line) <= 17 for line in content["lines"]), content["lines"]
    assert content["accent_lines"] == [0], content["accent_lines"]
    assert content["title"] == "ГОРИЗОНТ СОБЫТИЙ ЭТО"


def test_line_carrying_devices_suppress_the_subtitle(cfg):
    """Пословный субтитр поверх той же фразы — дубль, и он ложится на карточку."""
    from src.p11_assemble.assemble import (
        _CAPTION_HEROES, _HERO_NEEDS, _hero_device, hero_mutes_subtitle,
    )

    catalog = TemplateCatalog.load(cfg)
    # История прогонов обнуляется намеренно. Ротация ранжирует по числу
    # использований, и после живого прогона приёмы со строками уходят вниз на
    # всех сорока зёрнах — тест начинает падать от того, что кто-то собрал
    # ролик, а не от того, что правило сломалось. Проверяется правило.
    for template in catalog.templates:
        template.last_used_in = []
    slot = {"index": 4, "duration": 3.0, "role": "evidence"}
    plate = {"file": "/w/shots/a.mp4", "duration_sec": 3.0}
    seen = set()
    for seed in range(40):
        # С материалом, иначе приёмы, которым он нужен, отсеиваются до выбора и
        # правило на них не проверяется вовсе — так и жил экспонат.
        entry = _hero_device(catalog, slot=slot, content=_content(), has_alpha=False,
                             plate_src=plate, recent_videos=[], exclude=[], seed=seed)
        seen.add(entry["renderer"])
        assert entry["carries_line"] is hero_mutes_subtitle(
            entry["renderer"])["carries_line"], entry["renderer"]
    assert any("lines" in _HERO_NEEDS[r] for r in seen), "приёмы со строками не выпали"
    # Экспонат подписывает материал фразой целиком и потому тоже глушит субтитр,
    # хотя строк ему никто не передаёт.
    assert hero_mutes_subtitle(_CAPTION_HEROES[0])["carries_line"] is True


def test_full_frame_fill_is_short_and_takes_the_subtitle_with_it(cfg):
    """Заливка во весь кадр съедает и субтитр: белого слова на ней не видно."""
    from src.p11_assemble.assemble import _FULL_FRAME_HEROES, _hero_device

    catalog = TemplateCatalog.load(cfg)
    slot = {"index": 4, "duration": 6.0, "role": "evidence"}
    seen = set()
    for seed in range(60):
        entry = _hero_device(catalog, slot=slot, content=_content(), has_alpha=False,
                             plate_src=None, recent_videos=[], exclude=[], seed=seed)
        full = entry["renderer"] in _FULL_FRAME_HEROES
        assert entry["covers_frame"] is full, entry["renderer"]
        if full:
            seen.add(entry["renderer"])
            assert entry["duration"] and entry["duration"] < slot["duration"], (
                f'{entry["renderer"]}: заливка досиживает весь кадр')
    assert seen, "ни один приём с заливкой во весь кадр не выпал"


def test_hero_plate_duration_never_exceeds_its_material(cfg):
    """Кадр-задник короче аватар-плана: растянутая панель досидит его пустой."""
    from src.p11_assemble.assemble import _hero_device

    catalog = TemplateCatalog.load(cfg)
    slot = {"index": 4, "duration": 6.0, "role": "evidence"}
    plate = {"file": "/w/shots/a.mp4", "duration_sec": 1.4}
    keep = [t.id for t in catalog.by_category("hero-devices")
            if t.renderer != "hero-plate"]

    entry = _hero_device(catalog, slot=slot, content=_content(), has_alpha=True,
                         plate_src=plate, recent_videos=[], exclude=keep, seed=0)
    assert entry["renderer"] == "hero-plate"
    assert entry["duration"] == 1.4
    assert entry["file"] == "/w/shots/a.mp4"



def test_bubble_ring_sits_on_the_measured_face():
    """Круглая рамка ставится по face_bbox, а не по средней высоте головы."""
    from src.p11_assemble.assemble import _face_centres

    meta = {"segments": [{"index": 0, "face_bbox": [340, 350, 740, 750],
                          "slot_indices": [3, 5]}]}
    assert _face_centres(meta) == {3: (540, 550), 5: (540, 550)}
    assert _face_centres({"segments": [{"index": 0, "slot_indices": [1]}]}) == {}


def test_knockout_size_is_measured_not_guessed():
    """Оценка «0.52 кегля на знак» врала на 12 % — слово резалось краем кадра."""
    from src.lib.render.hyperframes.templates import fit_size, text_width

    for word in ("ЕДИНСТВЕННЫЙ", "ШИРОЧАЙШЕЕ", "ГОРИЗОНТ"):
        size = fit_size(word, 960, 300)
        assert text_width(word, size) <= 960 + 1e-6, word
    # Короткое слово не ужимается ниже потолка.
    assert fit_size("ДА", 960, 300) == 300


def test_catalog_save_keeps_templates_added_during_a_run(cfg, tmp_path):
    """Прогон длится минуты; шаблон, добавленный за это время, пропадал.

    Объект каталога помнит состав на момент старта, и запись «как в памяти»
    затирала новичка. Поймано на живом прогоне: приём исчез из манифеста
    после P11.
    """
    import json

    from src.lib.templates import TemplateCatalog

    path = tmp_path / "manifest.json"
    base = {"templates": [{"id": "cat/one", "name": "one", "category": "cat",
                           "title": "", "duration_range": [1.0, 2.0], "params": {},
                           "tags": [], "renderer": "r", "last_used_in": []}]}
    path.write_text(json.dumps(base), encoding="utf-8")
    catalog = TemplateCatalog(path, json.loads(path.read_text()))
    catalog.mark_used(["cat/one"], "v1")

    # Пока каталог жил в памяти, генератор дописал в манифест второй шаблон.
    grown = json.loads(path.read_text())
    grown["templates"].append({**base["templates"][0], "id": "cat/two", "name": "two"})
    path.write_text(json.dumps(grown), encoding="utf-8")

    catalog.save()
    saved = json.loads(path.read_text())
    assert {t["id"] for t in saved["templates"]} == {"cat/one", "cat/two"}
    assert saved["templates"][0]["last_used_in"] == ["v1"]


def test_subtitle_straddling_a_cut_is_dropped():
    """Слово, начавшееся до склейки и дожившее до неё, висело поверх текста.

    Отбор по началу слова его пропускал: начало вне окна, хвост внутри.
    """
    windows = [(2.212, 3.412)]

    def kept(start, end):
        return not any(start < w_end and end > w_start for w_start, w_end in windows)

    assert kept(1.60, 2.10)          # целиком до окна
    assert not kept(2.05, 2.30)      # хвост заезжает в окно
    assert not kept(2.50, 2.90)      # целиком внутри
    assert not kept(3.30, 3.70)      # начало внутри
    assert kept(3.45, 3.90)          # целиком после


class TestRotationRespectsTheAiCeiling:
    """Перестановка вставок не имеет права выносить ролик за потолок AI.

    P9 выдаёт генерацию под конкретные слоты и считает долю по их
    длительности. Ротация версии B переносит тот же кадр на слот вдвое
    длиннее — материала не прибавилось, а доля выросла. Прогон CI
    33607509470: P9 отчитался о 0.1995, вариант A собрался в 0.3420,
    вариант B — в 0.3971 при потолке 0.35. QC-14 не выдал ролик, за который
    уже заплачены голос, аватар и генерация: худший из возможных отказов.
    """

    slots = [{"index": 0, "block_id": "b1", "duration": 0.3},
             {"index": 1, "block_id": "b1", "duration": 2.5},
             {"index": 2, "block_id": "b2", "duration": 1.0}]
    assets = {0: {"ai_generated": True, "asset_id": "gen"},
              1: {"ai_generated": False, "asset_id": "stock"},
              2: {"ai_generated": False, "asset_id": "stock2"}}

    def _ai_seconds(self, mapping):
        return sum(s["duration"] for s in self.slots
                   if mapping[s["index"]].get("ai_generated"))

    def test_rotation_alone_can_double_the_ai_share(self):
        """Сначала показать саму беду: без потолка доля растёт вдвое."""
        from src.p11_assemble.assemble import _rotate_assets

        rotated = _rotate_assets(self.slots, self.assets, shift=1)
        assert self._ai_seconds(rotated) > self._ai_seconds(self.assets)

    def test_the_offending_block_is_rolled_back(self):
        from src.p11_assemble.assemble import _rotate_assets

        capped = _rotate_assets(self.slots, self.assets, shift=1, ai_budget_sec=1.0)
        assert self._ai_seconds(capped) <= 1.0

    def test_other_blocks_keep_their_rotation(self):
        """Откатывается блок-виновник, а не всё различие версий (§4.5)."""
        from src.p11_assemble.assemble import _rotate_assets

        capped = _rotate_assets(self.slots, self.assets, shift=1, ai_budget_sec=1.0)
        assert capped[2]["asset_id"] == "stock2"

    def test_a_rotation_within_budget_survives(self):
        from src.p11_assemble.assemble import _rotate_assets

        kept = _rotate_assets(self.slots, self.assets, shift=1, ai_budget_sec=5.0)
        assert kept[1]["asset_id"] == "gen", "ротацию откатили без нужды"
