"""MUST-020: evidence/twist не auto-arbitrate; метрики build_report."""

from __future__ import annotations

import json

from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.providers.vision import VisionVerdict
from src.p8_broll_judge.judge import (
    CRITIC_METRIC_KEYS, _needs_arbitration, critic_metrics_payload, run_step,
)


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
    def __init__(self, cfg, candidates, plan, costs=None):
        self.cfg = cfg
        self._candidates = candidates
        self._plan = plan
        self.written = {}
        self.warnings = []
        self.costs = costs if costs is not None else CostLedger(video_id="must020")

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
    def __init__(self, score: float, name: str):
        self.score = score
        self.name = name
        self.calls = 0

    def judge(self, frames, **kwargs):
        self.calls += 1
        return VisionVerdict(score=self.score, reason="spy", judge=self.name)


def _verdict(score, disagreement=0.0):
    scores = [score, score + disagreement]
    return VisionVerdict(score=score, reason="", per_frame_scores=scores)


def _cand() -> dict:
    return {
        "slot_index": 0,
        "asset_id": "ev_1",
        "origin": "stock",
        "source": "pexels",
        "kind": "video",
        "query": "quantum processor macro",
        "tags": ["quantum", "processor", "laboratory"],
        "url_origin": "https://example.com/quantum-processor-laboratory",
        "page_url": "https://example.com/quantum-processor-laboratory",
        "attribution": "pexels / lab",
        "width": 1080, "height": 1920, "duration_sec": 5.0,
        "frames": [],
    }


def _run(monkeypatch, *, glm_score: float, grok: _Spy, role: str = "evidence"):
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", False)
    cfg.set("providers.mode", "mock")
    cfg.set("stock.candidate_surplus", 1.0)
    glm = _Spy(glm_score, "glm")
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))
    monkeypatch.setattr(
        J, "build_vision_provider",
        lambda _c, _k, *, role="primary": grok if role == "arbiter" else glm)
    slot = {
        "index": 0, "kind": "footage", "role": role,
        "asset_role": "evidence" if role == "evidence" else "broll",
        "needs_asset": True, "block_id": "b0",
        "visual_intent": "quantum laboratory cryostat",
        "start": 0.0, "end": 2.0,
    }
    ctx = _Ctx(
        cfg,
        {"video_id": "must020", "candidates": [_cand()],
         "surplus": {"ok": True, "ratio": 1.3, "candidates": 1,
                     "target": 1, "slots_needing_footage": 1, "status": "ok"}},
        {"video_id": "must020", "category": "ai", "slots": [slot], "blocks": []},
    )
    run_step(ctx)
    return ctx.written["accepted_assets.json"], glm, grok


def test_evidence_outside_grey_does_not_call_grok(monkeypatch, cfg):
    assert _needs_arbitration(_verdict(0.80), "evidence", cfg) is None
    grok = _Spy(0.99, "grok")
    result, glm, grok = _run(monkeypatch, glm_score=0.80, grok=grok, role="evidence")
    assert glm.calls == 1
    assert grok.calls == 0
    assert result["grok_calls"] == 0


def test_twist_outside_grey_does_not_call_grok(monkeypatch):
    grok = _Spy(0.99, "grok")
    result, glm, grok = _run(monkeypatch, glm_score=0.90, grok=grok, role="twist")
    assert glm.calls == 1
    assert grok.calls == 0
    assert result["grok_calls"] == 0


def test_evidence_grey_still_may_call_grok_once(monkeypatch):
    grok = _Spy(0.88, "grok")
    result, glm, grok = _run(monkeypatch, glm_score=0.55, grok=grok, role="evidence")
    assert glm.calls == 1
    assert grok.calls == 1
    assert result["grok_calls"] == 1
    assert result["arbiter_calls"] <= 3


def test_critic_metrics_schema_keys():
    payload = critic_metrics_payload(
        {
            "candidates_per_slot": {"0": 3, "1": 2},
            "killed_stage1": 4,
            "killed_cheap": 12,
            "killed_glm": 5,
            "grok_calls": 2,
            "gemini_calls": 0,
        },
        generated={"ai_footage_share": 0.04},
        costs=None,
    )
    for key in CRITIC_METRIC_KEYS:
        assert key in payload
    assert payload["candidates_per_slot"]["0"] == 3
    assert payload["killed_stage1"] == 4
    assert payload["killed_cheap"] == 12
    assert payload["killed_glm"] == 5
    assert payload["grok_calls"] == 2
    assert payload["gemini_calls"] == 0
    assert payload["magnific_calls"] == 0
    assert payload["gen_share"] == 0.04
    assert payload["critic_cost"] == 0.0


def test_p8_result_has_must020_keys(monkeypatch):
    grok = _Spy(0.99, "grok")
    result, _glm, _grok = _run(monkeypatch, glm_score=0.40, grok=grok)
    for key in CRITIC_METRIC_KEYS:
        assert key in result
    assert result["killed_glm"] >= 1
    assert result["candidates_per_slot"]["0"] == 1
    assert result["killed_stage1"] == 0


def test_build_report_keys_if_0042_present(repo_root):
    path = repo_root / "output" / "redshift_0042" / "build_report.json"
    if not path.exists():
        path = repo_root / "work" / "redshift_0042" / "build_report.json"
    if not path.exists():
        import pytest
        pytest.skip("нет mock-прогона 0042")
    doc = json.loads(path.read_text(encoding="utf-8"))
    for key in CRITIC_METRIC_KEYS:
        assert key in doc
    costs = doc.get("costs") or {}
    for key in CRITIC_METRIC_KEYS:
        assert key in costs
