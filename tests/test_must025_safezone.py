"""MUST-025: HyperFrames пишет bbox; QC-7 ловит сдвиг и пустой замер."""

from __future__ import annotations

from src.lib.render.canvas import SafeZones
from src.lib.render.hyperframes.composition import CompositionBuilder
from src.p12_render_qc.qc import run_qc


class _Media:
    duration_sec = 48.0
    fps = 30
    width = 1080
    height = 1920


def _plan(**over):
    plan = {
        "video_id": "redshift_9025", "variant": "B", "duration_sec": 48.0,
        "shots": [], "overlays": [], "subtitles": [], "templates_used": [],
        "pick_traces": [], "avatar": [],
    }
    plan.update(over)
    return plan


def _run(ctx_cfg, plan, render_stats=None):
    class _Ctx:
        cfg = ctx_cfg
        warnings: list = []
    stats = {"accent_share_max": 0.06, "accent_by_family": {},
             "safe_zone_violations": []}
    if render_stats:
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


class TestQc7FailClosedWhenUnmeasured:
    def test_plaque_without_bbox_fails_as_unmeasured(self, cfg):
        plan = _plan(overlays=[{
            "type": "plaque", "start": 1.0, "end": 2.0,
            "params": {"text": "X"},
        }])
        check = _check(_run(cfg, plan), "QC-7")
        assert not check["passed"] and check["blocking"]
        assert "не мерили" in check["detail"]

    def test_empty_plan_has_nothing_to_measure(self, cfg):
        assert _check(_run(cfg, _plan()), "QC-7")["passed"]

    def test_work_area_bbox_passes(self, cfg):
        plan = _plan(overlays=[{
            "type": "plaque", "start": 1.0, "end": 2.0,
            "params": {"text": "X", "bbox": [90, 150, 830, 1520]},
        }])
        check = _check(_run(cfg, plan), "QC-7")
        assert check["passed"]
        assert check["value"]["measured"] >= 1

    def test_shift_into_bottom_400_fails(self, cfg):
        plan = _plan(overlays=[{
            "type": "plaque", "start": 1.0, "end": 2.0,
            "params": {"text": "X", "bbox": [100, 1600, 700, 1850]},
        }])
        check = _check(_run(cfg, plan), "QC-7")
        assert not check["passed"]
        assert "не мерили" not in (check["detail"] or "")


class TestCompositionEmitsBbox:
    def test_plaque_and_captions_write_checks(self, cfg):
        plan = {
            "video_id": "redshift_9025", "variant": "A", "fps": 30,
            "resolution": [1080, 1920], "duration_sec": 10.0,
            "shots": [{
                "index": 0, "start": 0.0, "end": 10.0, "duration": 10.0,
                "kind": "footage", "block_id": "b1", "file": "/w/shots/a.mp4",
            }],
            "avatar": [],
            "overlays": [
                {"type": "source_card", "start": 1.0, "end": 3.0,
                 "params": {"domain": "arxiv.org", "title": "Заголовок",
                            "snippet": "Выдержка", "text": "X"}},
                {"type": "plaque", "start": 2.0, "end": 4.0,
                 "params": {"text": "Плашка"}},
                {"type": "cta", "start": 8.0, "end": 10.0,
                 "params": {"text": "Подпишись"}},
            ],
            "subtitles": [
                {"display": "Падение", "start": 0.1, "end": 0.55},
            ],
        }
        assets = {"/w/shots/a.mp4": "assets/m000_a.mp4"}
        brandbook = cfg.brandbook
        builder = CompositionBuilder(plan, brandbook, assets)
        builder.build("assets/mix.wav")
        checks = builder.stats["safe_zone_checks"]
        assert len(checks) >= 1
        kinds = {ov["type"] for ov in plan["overlays"]
                 if (ov.get("params") or {}).get("bbox")}
        assert "plaque" in kinds
        assert "source_card" in kinds
        assert "cta" in kinds
        assert any(c.get("overlay") == "captions" for c in checks)
        safe = SafeZones.from_brandbook(brandbook)
        for ov in plan["overlays"]:
            box = (ov.get("params") or {}).get("bbox")
            if not box:
                continue
            if ov["type"] != "cta":
                assert safe.contains(tuple(box)), (ov["type"], box)
