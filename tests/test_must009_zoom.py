"""MUST-009: compose_zoom vs face_band/captions; gaze copy not a noun regex."""

from __future__ import annotations

import inspect

from src.lib.render.avatar_compose import (
    collision_rects, face_in_band, fit_compose_zoom, project_face, rect_iou,
    target_face_rect,
)
from src.lib.render.canvas import caption_layout_bbox
from src.lib.render.hyperframes.composition import CompositionBuilder
from src.p11_assemble.assemble import _gaze_plaque_copy
from src.p12_render_qc.qc import run_qc


class _Media:
    duration_sec = 48.0
    fps = 30
    width = 1080
    height = 1920


def _run_qc(cfg, plan, render_stats):
    class _Ctx:
        warnings: list = []

    _Ctx.cfg = cfg
    stats = {"accent_share_max": 0.06, "accent_by_family": {},
             "safe_zone_violations": []}
    stats.update(render_stats)
    return run_qc(
        _Ctx(), plan=plan,
        cut_plan={"video_id": plan["video_id"], "slots": [], "stats": {}},
        render_stats=stats,
        media=_Media(), sfx_map={"events": [], "loudness": {}},
        avatar_meta={"segments": [], "share": 0.2},
        accepted={}, generated={}, script={"blocks": []})


def _check(report, cid):
    return next(c for c in report["checks"] if c["id"] == cid)


def test_fitted_face_stays_in_band_caption_iou_zero(cfg):
    brand = cfg.brandbook
    # Small mid-frame face: 2.7 would blow past captions; fit must land in band.
    bbox = (420, 520, 660, 720)
    fit = fit_compose_zoom(bbox, 2.7, brandbook=brand, width=1080, height=1920)
    assert fit.zoom <= 2.7
    assert face_in_band(fit.face, brand, mode="A")
    for _name, rect in collision_rects(brand, width=1080, height=1920):
        assert rect_iou(fit.face, rect) == 0.0
    cap = caption_layout_bbox(brand, for_avatar=True)
    assert rect_iou(fit.face, cap) == 0.0
    # Talking head sits in the lower third, not the upper centre.
    assert fit.face[1] >= 1000


def test_unclamped_css_zoom_hits_caption_fitted_does_not(cfg):
    brand = cfg.brandbook
    bbox = (300, 700, 780, 1280)
    z = 2.7
    cx = (bbox[0] + bbox[2]) / 2 / 1080
    cy = (bbox[1] + bbox[3]) / 2 / 1920
    left = 1080 * (1 - z) * cx
    top = 1920 * (1 - z) * cy
    raw = project_face(bbox, z, left, top)
    cap = caption_layout_bbox(brand, for_avatar=True)
    bottom = (0.0, 1520.0, 1080.0, 1920.0)
    assert rect_iou(raw, cap) > 0 or rect_iou(raw, bottom) > 0
    fit = fit_compose_zoom(bbox, 2.7, brandbook=brand)
    assert rect_iou(fit.face, cap) == 0.0
    assert rect_iou(fit.face, bottom) == 0.0
    assert fit.zoom < 2.7


def test_mode_b_face_not_under_caption_or_bottom_safe(cfg):
    brand = cfg.brandbook
    bbox = (360, 400, 720, 760)
    fit = fit_compose_zoom(bbox, 2.7, brandbook=brand, mode="B")
    cap = caption_layout_bbox(brand, for_avatar=True)
    bottom = (0.0, 1520.0, 1080.0, 1920.0)
    assert rect_iou(fit.face, cap) == 0.0
    assert rect_iou(fit.face, bottom) == 0.0
    target = target_face_rect(brand, width=1080, height=1920, mode="B")
    assert fit.face[1] >= target[1] - 1
    assert fit.face[3] <= target[3] + 1


class TestNaturalPlacementR63:
    """``heygen.compose_zoom <= 1.0`` → crop-and-pin, never CSS-upscale.

    The owner: «растягивать видео из HeyGen не надо, как раньше, только
    обрезай по начало микрофона … и ставь вниз» — they measured a reference
    crop in a photo editor and sent it back. This is the calibration:
    `avatar.head_top_frac` (0.42) is where the *measured* head top
    (`src.lib.ffmpeg.head_box`, real alpha) should land, at zoom 1.0.
    """

    BOX = (360.0, 342.0, 690.0, 786.0)  # measured seg_00 @ t=1.0s

    def test_zoom_is_pinned_to_one(self, cfg):
        fit = fit_compose_zoom(self.BOX, 1.0, brandbook=cfg.brandbook)
        assert fit.zoom == 1.0

    def test_the_head_lands_on_the_configured_fraction(self, cfg):
        fit = fit_compose_zoom(self.BOX, 1.0, brandbook=cfg.brandbook,
                               width=1080, height=1920)
        head_top_frac = cfg.brandbook["avatar"]["head_top_frac"]
        landed = (self.BOX[1] + fit.top) / 1920
        assert abs(landed - head_top_frac) < 1e-6

    def test_no_horizontal_shift_even_off_centre(self, cfg):
        # A head turn mid-sentence moves the measured box left/right by
        # 60-80 px frame to frame — that is not a framing error to correct.
        off_centre = (180.0, 342.0, 510.0, 786.0)
        fit = fit_compose_zoom(off_centre, 1.0, brandbook=cfg.brandbook)
        assert fit.left == 0.0

    def test_falsy_requested_zoom_also_means_natural(self, cfg):
        # None/0 has always meant "no zoom was asked for" — that reads as
        # natural placement now, the same as an explicit 1.0.
        fit_none = fit_compose_zoom(self.BOX, None, brandbook=cfg.brandbook)
        fit_zero = fit_compose_zoom(self.BOX, 0.0, brandbook=cfg.brandbook)
        assert fit_none.zoom == fit_zero.zoom == 1.0

    def test_it_never_creeps_up_under_the_caption_band(self, cfg):
        # A tighter alpha read (smaller measured head) must not pull the
        # translate up past the caption floor — captions sit above the head
        # by construction at head_top_frac; this is the belt-and-suspenders.
        tiny_high_box = (500.0, 40.0, 580.0, 148.0)
        fit = fit_compose_zoom(tiny_high_box, 1.0, brandbook=cfg.brandbook,
                               width=1080, height=1920)
        cap_bottom = caption_layout_bbox(cfg.brandbook, for_avatar=True)[3]
        assert fit.top + tiny_high_box[1] >= cap_bottom - 1e-6

    def test_an_explicit_zoom_above_one_still_takes_the_old_band_fit(self, cfg):
        fit = fit_compose_zoom(self.BOX, 1.3, brandbook=cfg.brandbook)
        assert fit.zoom == 1.3


def test_config_default_is_natural_placement_since_r63(cfg):
    # r63: the channel's current look is shot vertically and already fills
    # the frame — CSS-scaling it further was the "stretched, poor quality"
    # complaint the owner sent back. 1.0 routes fit_compose_zoom to the
    # natural-placement branch (no scale, ever) instead of the band-fit
    # below. A value above 1.0 is still an explicit, deliberate request —
    # for a future look that genuinely sits small in its own frame.
    assert float(cfg.get("heygen.compose_zoom")) == 1.0


def test_an_explicit_zoom_above_one_is_still_a_ceiling_not_blind(cfg):
    # Band-fit stays reachable for a look that needs it; 2.7 here is a
    # deliberate request passed straight to the function, not read off the
    # channel's current (natural, 1.0) default.
    brand = cfg.brandbook
    small = fit_compose_zoom((430, 480, 650, 640), 2.7, brandbook=brand)
    large = fit_compose_zoom((280, 360, 800, 1100), 2.7, brandbook=brand)
    assert small.zoom != large.zoom
    assert large.zoom < small.zoom
    assert large.zoom <= 2.7 and small.zoom <= 2.7


def test_instruction_and_qc_use_brandbook_caption_baseline(cfg):
    lo, hi = cfg.brand("subtitles.baseline_y")
    assert [lo, hi] == [620, 1280]
    text = (cfg.repo_root / "instruction.md").read_text(encoding="utf-8")
    assert "620–1280" in text or "620-1280" in text
    assert "940–1010" not in text and "940-1010" not in text
    from src.p12_render_qc import qc as qc_mod
    src = inspect.getsource(qc_mod.run_qc)
    assert "[620, 1280]" in src
    assert "[940, 1010]" not in src


def test_qc7_fails_when_face_enters_bottom_safe(cfg):
    plan = {
        "video_id": "redshift_9009", "variant": "A", "duration_sec": 48.0,
        "shots": [], "overlays": [], "subtitles": [], "templates_used": [],
        "pick_traces": [], "avatar": [],
        "subtitle_style": {"baseline_y": 1180},
    }
    stats = {
        "safe_zone_violations": [{
            "overlay": "avatar_face",
            "bbox": [200, 1600, 800, 1880],
            "ok": False, "why": ["bottom_safe"],
        }],
        "safe_zone_checks": [{"overlay": "avatar_face"}],
        "safe_zone_measured": True,
    }
    check = _check(_run_qc(cfg, plan, stats), "QC-7")
    assert not check["passed"]


def test_composition_records_fitted_face_without_caption_hit(cfg):
    plan = {
        "video_id": "redshift_9009", "variant": "A", "duration_sec": 12.0,
        "fps": 30, "resolution": [1080, 1920],
        "shots": [], "overlays": [], "subtitles": [{"text": "ONE", "start": 0, "end": 1}],
        "avatar_compose_zoom": 2.7,
        "avatar": [{"index": 0, "start": 0, "duration": 4,
                    "face_bbox": [420, 520, 660, 720], "file": "x.webm"}],
    }
    builder = CompositionBuilder(plan, cfg.brandbook, assets={})
    builder._record_face_safe_zone()
    faces = [c for c in builder.stats["safe_zone_checks"]
             if c.get("overlay") == "avatar_face"]
    assert faces
    assert all(c.get("ok") for c in faces)
    assert not any(c.get("overlay") == "avatar_face"
                   for c in builder.stats["safe_zone_violations"])


def test_gaze_copy_from_hook_on_screen_not_noun_regex():
    plan = {
        "hook": {"on_screen": "невозможно проверить"},
        "blocks": [{"role": "hook", "text": "сто пять кубитов в криостате",
                    "overlay": {"content": "НЕЧЕМ"}}],
        "sources": [{"highlight_line": "ниже порога"}],
    }
    assert _gaze_plaque_copy(plan) == "НЕВОЗМОЖНО ПРОВЕРИТЬ"
    src = inspect.getsource(_gaze_plaque_copy)
    assert "кубит" not in src
    assert "qubit" not in src


def test_gaze_copy_without_on_screen_uses_overlay_not_body_scan():
    plan = {
        "hook": {},
        "blocks": [{"role": "hook", "text": "105 единиц внутри чипа",
                    "overlay": {"content": "удар"}}],
    }
    assert _gaze_plaque_copy(plan) == "УДАР"
