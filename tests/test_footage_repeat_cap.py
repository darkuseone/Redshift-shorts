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
    def __init__(self, cfg, candidates, plan, words=None):
        self.cfg = cfg
        self._candidates = candidates
        self._plan = plan
        self._words = words if words is not None else {"words": []}
        self.written = {}
        self.warnings = []

    def read(self, name):
        if name == "candidates.json":
            return self._candidates
        if name == "cut_plan.json":
            return self._plan
        if name == "words.json":
            return self._words
        raise KeyError(name)

    def read_or(self, name, default):
        try:
            return self.read(name)
        except KeyError:
            return default

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


def test_leftover_prefer_fills_empty_later_slot(monkeypatch):
    """Runner-up prefer of slot 0 must still close a later empty slot."""
    from src.lib.manifest import AssetRecord
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", True)
    cfg.set("stock.same_asset_max_slots", 1)

    class _PinIndex:
        def __init__(self):
            self._items = {
                "pexels_v25935014": AssetRecord(
                    id="pexels_v25935014", type="video", source="pexels",
                    license="Pexels License",
                    url_origin="https://example.com/quantum-laboratory-cryostat",
                    tags=["quantum", "laboratory"],
                    vision_summary="quantum laboratory cryostat",
                    score=0.86, duration_sec=3.0, width=1080, height=1920,
                    file="pexels/pexels_v25935014.mp4"),
                "grok_cryostat_0042": AssetRecord(
                    id="grok_cryostat_0042", type="video", source="generated",
                    license="generated-owned",
                    url_origin="cursor://generate-image/grok_quantum_cryostat",
                    tags=["quantum", "cryostat", "processor"],
                    vision_summary="gold dilution refrigerator quantum processor",
                    score=0.86, duration_sec=3.0, width=1080, height=1920,
                    file="generated/grok_cryostat_0042.mp4",
                    ai_generated=True),
            }

        def by_id(self, asset_id):
            return self._items.get(asset_id)

        def mark_used(self, *a, **k):
            return None

        def add(self, record):
            return record

        def save(self):
            return None

    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _PinIndex()))

    slots = [
        {
            "index": 0, "kind": "footage", "role": "hook",
            "asset_role": "broll", "needs_asset": True,
            "visual_intent": "quantum chip cryostat",
            "start": 0.0, "end": 2.0,
        },
        {
            "index": 1, "kind": "footage", "role": "develop",
            "asset_role": "broll", "needs_asset": True,
            "visual_intent": "Холодный кадр квантового процессора в криостате",
            "start": 2.0, "end": 3.4,
        },
    ]
    candidates = [_candidate(0, "pexels_v25935014", score=0.86)]
    ctx = _Ctx(
        cfg,
        {"video_id": "redshift_0042", "candidates": candidates},
        {"video_id": "redshift_0042", "category": "ai", "duration_sec": 44.5,
         "slots": slots},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    assert result["accepted"]["0"]["asset_id"] == "pexels_v25935014"
    assert result["accepted"]["1"]["asset_id"] == "grok_cryostat_0042"
    assert result["accepted"]["1"]["decision"] == "accept_prefer"
    assert "1" not in {str(i) for i in result["unfilled_slots"]}


def test_press_beats_ticker_on_nature_speech(monkeypatch):
    """Nature figure sits on the Nature utterance, not a stock ticker."""
    from src.lib.manifest import AssetRecord
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", True)
    cfg.set("stock.same_asset_max_slots", 1)

    class _PinIndex:
        def __init__(self):
            self._items = {
                "press_21bc8e2d72": AssetRecord(
                    id="press_21bc8e2d72", type="image", source="press",
                    license="fair-use-quote",
                    url_origin="https://www.nature.com/articles/s41586-024-08449-y",
                    tags=["nature", "quantum", "figure"],
                    vision_summary="Nature figure: Willow error-correction charts",
                    score=0.86, duration_sec=0.0, width=685, height=271,
                    file="press/press_21bc8e2d72.jpg"),
                "pexels_v38431825": AssetRecord(
                    id="pexels_v38431825", type="video", source="pexels",
                    license="Pexels License",
                    url_origin="https://www.pexels.com/video/stock-market-ticker-38431825/",
                    tags=["ticker", "finance"],
                    vision_summary="stock market ticker numbers",
                    score=0.92, duration_sec=8.0, width=1080, height=1920,
                    file="pexels/pexels_v38431825.mp4"),
            }

        def by_id(self, asset_id):
            return self._items.get(asset_id)

        def mark_used(self, *a, **k):
            return None

        def add(self, record):
            return record

        def save(self):
            return None

    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _PinIndex()))

    slots = [
        {
            "index": 3, "kind": "split", "role": "evidence",
            "asset_role": "evidence", "needs_asset": True,
            "visual_intent": "Скриншот статьи в браузере, подсветка ключевой строки",
            "start": 8.0, "end": 10.52, "block_id": "b3",
        },
        {
            "index": 5, "kind": "split", "role": "evidence",
            "asset_role": "evidence", "needs_asset": True,
            "visual_intent": "Скриншот статьи в браузере, подсветка ключевой строки",
            "start": 13.04, "end": 15.58, "block_id": "b3",
        },
    ]
    candidates = [
        _candidate(3, "pexels_v38431825", score=0.92),
        _candidate(3, "press_21bc8e2d72", score=0.80),
        _candidate(5, "pexels_v38431825", score=0.92),
        _candidate(5, "press_21bc8e2d72", score=0.80),
    ]
    for row in candidates:
        if row["asset_id"].startswith("press_"):
            row["tags"] = ["nature", "quantum", "figure"]
            row["url_origin"] = "https://www.nature.com/articles/s41586-024-08449-y"
            row["vision_summary"] = "Nature figure: Willow error-correction charts"
        else:
            row["tags"] = ["ticker", "finance"]
            row["url_origin"] = "https://www.pexels.com/video/stock-market-ticker-38431825/"
            row["vision_summary"] = "stock market ticker numbers"
    words = {"words": [
        {"display": "опубликована", "start": 8.4, "end": 8.9},
        {"display": "Nature", "start": 9.12, "end": 9.57},
        {"display": "внутри", "start": 13.2, "end": 13.6},
    ]}
    ctx = _Ctx(
        cfg,
        {"video_id": "redshift_0042", "candidates": candidates},
        {"video_id": "redshift_0042", "category": "ai", "duration_sec": 44.5,
         "slots": slots},
        words=words,
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    assert result["accepted"]["3"]["asset_id"] == "press_21bc8e2d72"
    assert result["accepted"]["3"]["asset_id"] != "pexels_v38431825"


def test_supercomputer_carves_onto_spoken_slot(monkeypatch):
    """Hall clip covers «суперкомпьютеру» without blowing the 10 % AI cap."""
    from src.lib.manifest import AssetRecord
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", True)
    cfg.set("stock.same_asset_max_slots", 1)
    cfg.set("limits.ai_footage_share_max", 0.10)

    class _PinIndex:
        def __init__(self):
            self._items = {
                "grok_cryostat_0042": AssetRecord(
                    id="grok_cryostat_0042", type="video", source="generated",
                    license="generated-owned",
                    url_origin="cursor://generate-image/grok_quantum_cryostat",
                    tags=["quantum", "cryostat"],
                    vision_summary="gold dilution refrigerator",
                    score=0.86, duration_sec=3.0, width=1080, height=1920,
                    file="generated/grok_cryostat_0042.mp4",
                    ai_generated=True),
                "grok_supercomputer_0042": AssetRecord(
                    id="grok_supercomputer_0042", type="video", source="generated",
                    license="generated-owned",
                    url_origin="cursor://generate-image/grok_supercomputer_hall",
                    tags=["supercomputer", "hall"],
                    vision_summary="supercomputer hall",
                    score=0.86, duration_sec=3.0, width=1080, height=1920,
                    file="generated/grok_supercomputer_0042.mp4",
                    ai_generated=True),
            }

        def by_id(self, asset_id):
            return self._items.get(asset_id)

        def mark_used(self, *a, **k):
            return None

        def add(self, record):
            return record

        def save(self):
            return None

    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _PinIndex()))

    slots = [
        {
            "index": 7, "kind": "footage", "role": "develop",
            "asset_role": "broll", "needs_asset": True,
            "visual_intent": "График падения ошибки, абстрактная визуализация данных",
            "start": 18.12, "end": 20.84, "block_id": "b4",
        },
        {
            "index": 10, "kind": "footage", "role": "develop",
            "asset_role": "broll", "needs_asset": True,
            "visual_intent": "График падения ошибки, абстрактная визуализация данных",
            "start": 26.25, "end": 28.88, "block_id": "b4",
        },
    ]
    cryo = _candidate(7, "grok_cryostat_0042", score=0.86)
    cryo["ai_generated"] = True
    cryo["tags"] = ["quantum", "cryostat"]
    cryo["url_origin"] = "cursor://generate-image/grok_quantum_cryostat"
    cryo["vision_summary"] = "gold dilution refrigerator"
    ctx = _Ctx(
        cfg,
        {"video_id": "redshift_0042", "candidates": [cryo]},
        {"video_id": "redshift_0042", "category": "ai", "duration_sec": 44.5,
         "slots": slots},
        words={"words": [
            {"display": "ошибка", "start": 18.5, "end": 19.0},
            {"display": "суперкомпьютеру", "start": 26.74, "end": 27.19},
        ]},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    assert result["accepted"]["7"]["asset_id"] == "grok_cryostat_0042"
    super_entry = result["accepted"]["10"]
    assert super_entry["asset_id"] == "grok_supercomputer_0042"
    assert float(super_entry["carve_sec"]) < 2.63
    assert float(super_entry["carve_sec"]) >= 1.2
    used = 2.72 + float(super_entry["carve_sec"])
    assert used <= 44.5 * 0.10 + 1e-6


def test_apply_ai_carves_splits_the_spoken_window():
    from src.p11_assemble.assemble import apply_ai_carves

    slots = [{
        "index": 10, "start": 26.25, "end": 28.88, "duration": 2.63,
        "kind": "footage", "needs_asset": True, "reason": "режим C",
        "events": [{"t": 26.25, "kind": "shot_change"},
                   {"t": 27.5, "kind": "kenburns_restart"}],
    }]
    assets = {10: {"asset_id": "grok_supercomputer_0042", "carve_sec": 1.65,
                   "ai_generated": True}}
    out = apply_ai_carves(slots, assets)
    assert len(out) == 2
    assert out[0]["index"] == 10
    assert abs(out[0]["duration"] - 1.65) < 1e-6
    assert out[1]["start"] == out[0]["end"]
    assert out[1]["end"] == 28.88
    assert out[1]["index"] != 10
    assert all(float(ev["t"]) < out[0]["end"] for ev in out[0]["events"])


def test_p7_exclusive_ids_do_not_consume_runner_ups():
    import inspect

    from src.p7_broll_search import search

    body = inspect.getsource(search.run_step)
    assert "exclusive_ids" in body
    assert "taken_ids = set(exclusive_ids)" in body
