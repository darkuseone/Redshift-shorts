"""P8: same asset must not close every adjacent slot."""

from __future__ import annotations

from src.lib.config import load_config
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


def _candidate(slot_index: int, asset_id: str, *, score: float = 0.92) -> dict:
    return {
        "slot_index": slot_index,
        "asset_id": asset_id,
        "prior_score": score,
        "prior_intent": "quantum laboratory cryostat",
        "origin": "local_cache",
        "tags": ["quantum", "laboratory"],
        "url_origin": "https://example.com/quantum-laboratory-cryostat",
        "vision_summary": "quantum laboratory cryostat",
        "frames": [],
    }


def test_default_same_asset_max_slots_is_one():
    cfg = load_config()
    assert int(cfg.get("stock.same_asset_max_slots", 2)) == 1


def test_same_asset_capped_at_one_slot(monkeypatch):
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", True)
    cfg.set("stock.same_asset_max_slots", 1)
    cfg.set("stock.repeat_score_penalty", 0.12)

    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))

    slots = []
    candidates = []
    for i in range(5):
        slots.append({
            "index": i, "kind": "footage", "role": "develop",
            "asset_role": "broll", "needs_asset": True,
            "visual_intent": "quantum laboratory cryostat",
            "start": float(i * 2), "end": float(i * 2 + 2),
        })
        candidates.append(_candidate(i, "sparkle_clip", score=0.95))
        candidates.append(_candidate(i, f"other_{i}", score=0.80))

    ctx = _Ctx(
        cfg,
        {"video_id": "repeat_cap_test", "candidates": candidates},
        {"video_id": "repeat_cap_test", "category": "ai", "slots": slots},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    accepted_ids = [entry["asset_id"] for entry in result["accepted"].values()]
    assert accepted_ids.count("sparkle_clip") <= 1


def test_same_asset_capped_at_two_slots(monkeypatch):
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", True)
    cfg.set("stock.same_asset_max_slots", 2)
    cfg.set("stock.repeat_score_penalty", 0.12)

    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))

    slots = []
    candidates = []
    for i in range(5):
        slots.append({
            "index": i, "kind": "footage", "role": "develop",
            "asset_role": "broll", "needs_asset": True,
            "visual_intent": "quantum laboratory cryostat",
            "start": float(i * 2), "end": float(i * 2 + 2),
        })
        candidates.append(_candidate(i, "pexels_v35288383", score=0.95))

    ctx = _Ctx(
        cfg,
        {"video_id": "repeat_cap_test", "candidates": candidates},
        {"video_id": "repeat_cap_test", "category": "ai", "slots": slots},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    accepted_ids = [
        entry["asset_id"] for entry in result["accepted"].values()
    ]
    assert accepted_ids.count("pexels_v35288383") <= 2
    assert len(result["unfilled_slots"]) >= 3


def test_pin_prefer_wins_over_higher_scored_other(monkeypatch):
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", True)
    cfg.set("stock.same_asset_max_slots", 1)
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))

    slots = [{
        "index": 0, "kind": "footage", "role": "develop",
        "asset_role": "broll", "needs_asset": True,
        "visual_intent": "quantum laboratory cryostat",
        "start": 0.0, "end": 2.0,
    }]
    candidates = [
        _candidate(0, "random_high_score", score=0.99),
        _candidate(0, "pexels_v25935014", score=0.62),
    ]
    ctx = _Ctx(
        cfg,
        {"video_id": "redshift_0042", "candidates": candidates},
        {"video_id": "redshift_0042", "category": "ai", "slots": slots},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    accepted = result["accepted"]["0"]
    assert accepted["asset_id"] == "pexels_v25935014"
    assert accepted["decision"] == "accept_prefer"


def test_volcano_candidate_rejected_for_0042(monkeypatch):
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", True)
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))

    slots = [{
        "index": 0, "kind": "footage", "role": "develop",
        "asset_role": "broll", "needs_asset": True,
        "visual_intent": "quantum laboratory cryostat",
        "start": 0.0, "end": 2.0,
    }]
    volcano = _candidate(0, "pixabay_v144678", score=0.95)
    volcano["tags"] = ["volcano", "lava", "magma"]
    volcano["vision_summary"] = "Close-up of bright lava streams"
    volcano["url_origin"] = "https://pixabay.com/videos/id-144678/"
    prefer = _candidate(0, "pexels_v18069803", score=0.70)
    ctx = _Ctx(
        cfg,
        {"video_id": "redshift_0042", "candidates": [volcano, prefer]},
        {"video_id": "redshift_0042", "category": "ai", "slots": slots},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    judged = result["judged"]
    volcano_row = next(j for j in judged if j["asset_id"] == "pixabay_v144678")
    assert volcano_row["decision"] in ("reject_theme", "reject_gate")
    assert result["accepted"]["0"]["asset_id"] == "pexels_v18069803"


def test_repeat_cap_falls_through_to_other_asset(monkeypatch):
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", True)
    cfg.set("stock.same_asset_max_slots", 2)

    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))

    slots = []
    candidates = []
    for i in range(5):
        slots.append({
            "index": i, "kind": "footage", "role": "develop",
            "asset_role": "broll", "needs_asset": True,
            "visual_intent": "quantum laboratory cryostat",
            "start": float(i * 2), "end": float(i * 2 + 2),
        })
        candidates.append(_candidate(i, "sparkle_clip", score=0.95))
        candidates.append(_candidate(i, f"other_{i}", score=0.80))

    ctx = _Ctx(
        cfg,
        {"video_id": "repeat_cap_test", "candidates": candidates},
        {"video_id": "repeat_cap_test", "category": "ai", "slots": slots},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    accepted_ids = [entry["asset_id"] for entry in result["accepted"].values()]
    assert accepted_ids.count("sparkle_clip") <= 2
    assert any(aid.startswith("other_") for aid in accepted_ids)
    assert len(result["accepted"]) == 5
