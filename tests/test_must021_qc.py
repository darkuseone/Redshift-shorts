"""MUST-021: QC чужого hue в HyperFrames, cyan=tech, VFX cap = instruction."""

from __future__ import annotations

from src.lib.palette import (
    brandbook_fill_allowlist,
    hex_in_allowlist,
    overlay_cyan_misuse,
    overlay_offbrand_fills,
)
from src.p12_render_qc.qc import run_qc


class _Media:
    duration_sec = 48.0
    fps = 30
    width = 1080
    height = 1920


def _plan(**over):
    plan = {
        "video_id": "redshift_9021", "variant": "B", "duration_sec": 48.0,
        "shots": [], "overlays": [], "subtitles": [], "templates_used": [],
        "pick_traces": [], "avatar": [],
    }
    plan.update(over)
    return plan


def _shot(index, **over):
    shot = {"index": index, "start": index * 3.0, "end": index * 3.0 + 3.0,
            "duration": 3.0, "kind": "footage", "block_id": "b1",
            "role": "body", "mode": "C", "reason": ""}
    shot.update(over)
    return shot


def _run(ctx_cfg, plan, script=None):
    class _Ctx:
        cfg = ctx_cfg
        warnings: list = []
    return run_qc(
        _Ctx(), plan=plan,
        cut_plan={"video_id": plan["video_id"], "slots": [], "stats": {}},
        render_stats={"accent_share_max": 0.06, "accent_by_family": {}},
        media=_Media(), sfx_map={"events": [], "loudness": {}},
        avatar_meta={"segments": [], "share": 0.2},
        accepted={}, generated={}, script=script or {"blocks": []})


def _check(report, cid):
    return next(c for c in report["checks"] if c["id"] == cid)


class TestQc31BlocksOffbrandOverlayFill:
    """0047-pink / leftover yellow in a plaque fill must fail delivery."""

    def test_magenta_fill_fails(self, cfg):
        plan = _plan(overlays=[{
            "type": "plaque", "start": 1.0, "end": 2.0,
            "params": {"fill": "#FF00AA", "text": "X"},
        }])
        check = _check(_run(cfg, plan), "QC-31")
        assert not check["passed"] and check["blocking"]
        assert check["value"] >= 1

    def test_yellow_leftover_fails(self, cfg):
        plan = _plan(overlays=[{
            "type": "highlight", "start": 4.0, "end": 5.0,
            "params": {"fill": "#FFD700"},
        }])
        check = _check(_run(cfg, plan), "QC-31")
        assert not check["passed"]

    def test_brand_accent_passes(self, cfg):
        plan = _plan(overlays=[{
            "type": "plaque", "start": 1.0, "end": 2.0,
            "params": {"fill": "#C8453D"},
        }])
        assert _check(_run(cfg, plan), "QC-31")["passed"]

    def test_ink_and_white_are_allowed(self, cfg):
        plan = _plan(overlays=[{
            "type": "source_card", "start": 1.0, "end": 2.0,
            "params": {"fill": "#111214", "color": "#FFFFFF"},
        }])
        assert _check(_run(cfg, plan), "QC-31")["passed"]

    def test_empty_overlays_pass(self, cfg):
        assert _check(_run(cfg, _plan()), "QC-31")["passed"]

    def test_allowlist_rejects_0047_pink(self, cfg):
        allow = brandbook_fill_allowlist(cfg.brandbook)
        assert not hex_in_allowlist("#FF00AA", allow)
        assert hex_in_allowlist("#C8453D", allow)
        assert overlay_offbrand_fills(
            [{"type": "plaque", "params": {"fill": "#FF00AA"}}],
            cfg.brandbook,
        )


class TestQc32CyanIsTechOnly:
    """Cyan #36EFFF is the tech accent, not a medicine card fill."""

    def test_tech_card_cyan_passes(self, cfg):
        plan = _plan(overlays=[{
            "type": "plaque", "start": 2.0, "end": 3.0,
            "params": {"fill": "#36EFFF", "theme": "tech"},
        }])
        report = _run(cfg, plan)
        assert _check(report, "QC-31")["passed"]
        assert _check(report, "QC-32")["passed"]

    def test_ai_tool_theme_cyan_passes(self, cfg):
        plan = _plan(overlays=[{
            "type": "source_card", "start": 2.0, "end": 3.0,
            "params": {"fill": "#36EFFF", "theme": "ai-tool"},
        }])
        assert _check(_run(cfg, plan), "QC-32")["passed"]

    def test_medicine_card_cyan_fails(self, cfg):
        plan = _plan(overlays=[{
            "type": "plaque", "start": 6.0, "end": 8.0,
            "params": {"fill": "#36EFFF", "theme": "medicine"},
        }])
        check = _check(_run(cfg, plan), "QC-32")
        assert not check["passed"] and check["blocking"]

    def test_medicine_via_block_emphasis_fails(self, cfg):
        plan = _plan(overlays=[{
            "type": "plaque", "start": 6.0, "end": 8.0,
            "block_id": "b_med",
            "params": {"accent_family": "cyan"},
        }])
        script = {"blocks": [{
            "id": "b_med",
            "emphasis_family": "tech",
            "overlay": {"theme": "medicine"},
        }]}
        check = _check(_run(cfg, plan, script=script), "QC-32")
        assert not check["passed"]

    def test_unmarked_cyan_does_not_false_positive(self, cfg):
        """Number/source cyan from MEGA D-9 has no medicine theme — not this gate."""
        plan = _plan(overlays=[{
            "type": "plaque", "start": 2.0, "end": 3.0,
            "params": {"fill": "#36EFFF"},
        }])
        assert _check(_run(cfg, plan), "QC-32")["passed"]
        assert not overlay_cyan_misuse(
            [{"type": "plaque", "params": {"fill": "#36EFFF"}}],
            cfg.brandbook, {"blocks": []})


class TestQc33VfxCapMatchesInstruction:
    """Instruction §1.10: ≤2 VFX clips, each 2–5 s. Plan with 3 must fail."""

    def test_three_vfx_fail(self, cfg):
        plan = _plan(shots=[
            _shot(0, background="vfx"),
            _shot(1, background="vfx"),
            _shot(2, background="vfx"),
        ])
        check = _check(_run(cfg, plan), "QC-33")
        assert not check["passed"] and check["blocking"]
        assert check["value"]["count"] == 3
        assert check["threshold"]["count_max"] == 2

    def test_two_vfx_in_window_pass(self, cfg):
        plan = _plan(shots=[
            _shot(0, background="vfx", duration=3.0),
            _shot(1, background="vfx", duration=4.0),
        ])
        assert _check(_run(cfg, plan), "QC-33")["passed"]

    def test_vfx_too_short_fails(self, cfg):
        plan = _plan(shots=[_shot(0, background="vfx", duration=1.5,
                                 end=1.5)])
        check = _check(_run(cfg, plan), "QC-33")
        assert not check["passed"]

    def test_vfx_too_long_fails(self, cfg):
        plan = _plan(shots=[_shot(0, background="vfx", duration=8.0,
                                 end=8.0)])
        check = _check(_run(cfg, plan), "QC-33")
        assert not check["passed"]

    def test_matting_vfx_list_counts(self, cfg):
        plan = _plan(matting={"vfx": [
            {"slot": 0, "duration_sec": 3.0},
            {"slot": 1, "duration_sec": 3.0},
            {"slot": 2, "duration_sec": 3.0},
        ]})
        check = _check(_run(cfg, plan), "QC-33")
        assert not check["passed"]
        assert check["value"]["count"] == 3

    def test_no_vfx_passes(self, cfg):
        assert _check(_run(cfg, _plan()), "QC-33")["passed"]

    def test_threshold_is_instruction_number(self, cfg):
        check = _check(_run(cfg, _plan()), "QC-33")
        assert check["threshold"]["count_max"] == cfg.get("limits.bg_vfx_per_video")
        assert check["threshold"]["sec"] == list(cfg.get("limits.bg_vfx_sec"))
