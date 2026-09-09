"""MUST-018: stage1-мёртвые не на vision; download ≤1080p по короткой стороне."""

from __future__ import annotations

from src.lib.config import load_config
from src.lib.ffmpeg import probe, run
from src.lib.providers.stock import StockCandidate
from src.lib.providers.vision import VisionVerdict
from src.lib.render.shots import slim_video
from src.p7_broll_search.search import (
    _stage1_reject, judge_blocks_stage1_dead, short_side_over_cap,
    stage1_dead_ids,
)
from src.p8_broll_judge.judge import run_step


class _Index:
    def by_id(self, asset_id):
        return None

    def mark_used(self, *a, **k):
        return None

    def add(self, record):
        return record

    def save(self):
        return None


class _Ctx:
    def __init__(self, cfg, candidates, plan):
        self.cfg = cfg
        self._candidates = candidates
        self._plan = plan
        self.written = {}
        self.warnings = []
        self.costs = None

    def read(self, name):
        if name == "candidates.json":
            return self._candidates
        if name == "cut_plan.json":
            return self._plan
        raise KeyError(name)

    def write(self, name, data):
        self.written[name] = data
        return name

    def warn(self, message, **fields):
        self.warnings.append(message)


class _Spy:
    def __init__(self):
        self.ids: list[str] = []

    def judge(self, frames, **kwargs):
        self.ids.append(str(kwargs.get("query") or ""))
        return VisionVerdict(score=0.91, reason="spy", judge="spy")


def _cand(**kwargs) -> StockCandidate:
    base = dict(id="x", source="pexels", kind="video", query="q", width=1080, height=1920,
                duration_sec=5.0, license="Pexels License", license_confirmed=True)
    base.update(kwargs)
    return StockCandidate(**base)


def test_max_download_height_is_1080(cfg):
    assert int(cfg.get("stock.max_download_height")) == 1080


def test_short_side_over_cap_is_min_side():
    assert short_side_over_cap(3840, 2160, 1080)
    assert short_side_over_cap(2160, 3840, 1080)
    assert not short_side_over_cap(1080, 1920, 1080)
    assert not short_side_over_cap(1920, 1080, 1080)
    assert not short_side_over_cap(1080, 2160, 1080)


def test_stage1_rejects_4k_keeps_1080p_portrait(cfg):
    assert _stage1_reject(_cand(width=3840, height=2160), cfg, 3.0)
    assert _stage1_reject(_cand(width=2160, height=3840), cfg, 3.0)
    assert _stage1_reject(_cand(width=1080, height=1920), cfg, 3.0) is None
    assert _stage1_reject(_cand(width=1080, height=2160), cfg, 3.0) is None


def test_stage1_dead_and_4k_never_reach_judge(monkeypatch):
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", False)
    cfg.set("stock.candidate_surplus", 1.0)
    spy = _Spy()
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))
    monkeypatch.setattr(J, "build_vision_provider", lambda *a, **k: spy)

    dead = {
        "slot_index": 0, "asset_id": "fourk_clip", "id": "fourk_clip",
        "origin": "stock", "width": 3840, "height": 2160,
        "query": "fourk_clip", "tags": ["quantum", "chip"],
        "url_origin": "https://example.com/quantum-chip",
        "page_url": "https://example.com/quantum-chip",
        "frames": [],
    }
    listed = {
        "slot_index": 0, "asset_id": "ok_clip", "origin": "stock",
        "width": 1080, "height": 1920, "query": "ok_clip",
        "tags": ["quantum", "chip"],
        "url_origin": "https://example.com/quantum-chip-ok",
        "page_url": "https://example.com/quantum-chip-ok",
        "frames": [],
    }
    sneak = {
        "slot_index": 0, "asset_id": "sneak_4k", "origin": "stock",
        "width": 2160, "height": 3840, "query": "sneak_4k",
        "tags": ["quantum", "chip"],
        "url_origin": "https://example.com/quantum-chip-sneak",
        "page_url": "https://example.com/quantum-chip-sneak",
        "frames": [],
    }
    slots = [{
        "index": 0, "kind": "footage", "role": "develop",
        "asset_role": "broll", "needs_asset": True, "block_id": "b0",
        "visual_intent": "quantum laboratory cryostat",
        "start": 0.0, "end": 2.0,
    }]
    ctx = _Ctx(
        cfg,
        {
            "video_id": "stage1_dead",
            "candidates": [dead, listed, sneak],
            "stage1_rejected": [{"id": "fourk_clip", "reason": "разрешение выше 1080p"}],
            "surplus": {"ok": True, "ratio": 1.0, "candidates": 3,
                        "target": 1, "slots_needing_footage": 1, "status": "ok"},
        },
        {"video_id": "stage1_dead", "category": "ai", "slots": slots, "blocks": []},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    judged_ids = {row.get("asset_id") for row in result["judged"]}
    assert "fourk_clip" not in judged_ids
    assert "sneak_4k" not in judged_ids
    assert result["skipped_stage1"] >= 2
    assert "fourk_clip" not in spy.ids
    assert "sneak_4k" not in spy.ids
    assert judge_blocks_stage1_dead(
        dead, dead_ids={"fourk_clip"}, max_h=1080)
    assert judge_blocks_stage1_dead(
        sneak, dead_ids=set(), max_h=1080)


def test_stage1_dup_reject_does_not_kill_first_slot_hit(monkeypatch):
    """«Дубль» на хвосте слотов не делает клип мёртвым для слота, где он кандидат."""
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", True)
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))

    hit = {
        "slot_index": 0, "asset_id": "pexels_v18069803", "origin": "local_cache",
        "width": 1080, "height": 1920, "query": "quantum processor",
        "tags": ["quantum", "laboratory"], "prior_score": 0.92,
        "prior_intent": "quantum laboratory cryostat",
        "url_origin": "https://example.com/quantum-laboratory-cryostat",
        "page_url": "https://example.com/quantum-laboratory-cryostat",
        "vision_summary": "quantum laboratory cryostat",
        "frames": [],
    }
    slots = [{
        "index": 0, "kind": "footage", "role": "hook",
        "asset_role": "broll", "needs_asset": True, "block_id": "b1",
        "visual_intent": "quantum laboratory cryostat",
        "start": 0.0, "end": 2.0,
    }]
    ctx = _Ctx(
        cfg,
        {
            "video_id": "redshift_0042",
            "candidates": [hit],
            "stage1_rejected": [
                {"id": "pexels_v18069803",
                 "reason": "дубль pexels_v18069803 (материал из базы)"},
            ],
            "surplus": {"ok": False, "ratio": 1.3, "candidates": 1,
                        "target": 2, "slots_needing_footage": 1,
                        "status": "underfilled"},
        },
        {"video_id": "redshift_0042", "category": "ai", "slots": slots,
         "blocks": [{"id": "b1", "text": "квантовый чип в лаборатории"}]},
    )
    assert "pexels_v18069803" not in stage1_dead_ids(
        [{"id": "pexels_v18069803",
          "reason": "дубль pexels_v18069803 (материал из базы)"}])
    run_step(ctx)
    accepted = ctx.written["accepted_assets.json"]["accepted"]
    assert accepted["0"]["asset_id"] == "pexels_v18069803"


def test_slim_video_does_not_keep_short_side_above_1080(tmp_path):
    src = tmp_path / "fourk.mp4"
    run(["-y", "-f", "lavfi", "-i", "testsrc2=s=2160x2160:d=0.4:r=24",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         str(src)], what="4k fixture")
    assert min(probe(src).width, probe(src).height) == 2160
    slim_video(src, max_sec=20.0, max_short_side=1080)
    info = probe(src)
    assert min(info.width, info.height) <= 1080, (info.width, info.height)
    assert src.exists()
