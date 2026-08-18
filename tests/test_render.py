"""Фаза 3 — рендер: примитивы брендбука, слои, шаблоны, подготовка планов."""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from src.lib.render.canvas import (
    FontBook, SafeZones, accent_area_share, cubic_bezier, ease, mix, parse_color, with_alpha,
)
from src.lib.render.layers import Ctx, fit_block, fullscreen_text, plaque, source_card, subtitle, subscribe_button
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

def test_subtitle_is_centered_and_in_safe_zone(render_ctx):
    layer = subtitle(render_ctx, "кубитов", progress=1.0)
    bbox = layer.getbbox()
    assert bbox is not None
    center_x = (bbox[0] + bbox[2]) / 2
    assert abs(center_x - render_ctx.safe.center_x) < 12       # §5.1: по центру
    assert render_ctx.safe.y_min <= bbox[1] and bbox[3] <= render_ctx.safe.y_max


def test_subtitle_baseline_is_in_center_band(render_ctx):
    layer = subtitle(render_ctx, "слово", progress=1.0)
    bbox = layer.getbbox()
    center_y = (bbox[1] + bbox[3]) / 2
    lo, hi = render_ctx.brandbook["subtitles"]["baseline_y"]
    assert lo - 60 <= center_y <= hi + 60


def test_subtitle_shifts_down_when_face_low(render_ctx):
    from src.lib.render.layers import subtitle_baseline

    default = subtitle_baseline(render_ctx, face_bbox=None)
    shifted = subtitle_baseline(render_ctx, face_bbox=(300, 400, 700, 900))
    assert shifted > default


def test_subtitle_emphasis_uses_accent(render_ctx):
    plain = subtitle(render_ctx, "слово", progress=1.0)
    accent = subtitle(render_ctx, "слово", progress=1.0, emphasis=True)
    assert list(plain.getdata()) != list(accent.getdata())


def test_subtitle_empty_word_is_noop(render_ctx):
    assert subtitle(render_ctx, "  ,  ", progress=1.0).getbbox() is None


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
    frame.alpha_composite(subtitle(render_ctx, "невозможно", progress=1.0, emphasis=True))
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

def test_catalog_matches_spec_counts(cfg):
    catalog = TemplateCatalog.load(cfg)
    counts = catalog.counts()
    assert counts == {
        "intro-hooks": 8, "text-fullscreen": 10, "lower-thirds": 8, "frames-cards": 6,
        "browser-ui": 6, "transitions": 12, "avatar-entry": 6, "kenburns": 10,
        "parallax": 4, "data-viz": 6, "outro-cta": 5,
    }
    assert len(catalog.all()) == 81


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
