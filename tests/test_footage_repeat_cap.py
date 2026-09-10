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
                "pexels_v18069803": AssetRecord(
                    id="pexels_v18069803", type="video", source="pexels",
                    license="Pexels License",
                    url_origin="https://www.pexels.com/video/quantum-chip-18069803/",
                    tags=["quantum", "chip"],
                    vision_summary="quantum processor chip macro",
                    score=0.90, duration_sec=8.0, width=1080, height=1920,
                    file="pexels/pexels_v18069803.mp4"),
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
            "index": 0, "kind": "footage", "role": "hook",
            "asset_role": "broll", "needs_asset": True,
            "visual_intent": "Холодный кадр квантового процессора в криостате, крупно",
            "start": 0.0, "end": 3.08, "block_id": "b1",
        },
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
    candidates = []
    for idx in (0, 3, 5):
        candidates.extend([
            _candidate(idx, "pexels_v38431825", score=0.92),
            _candidate(idx, "press_21bc8e2d72", score=0.80),
            _candidate(idx, "pexels_v18069803", score=0.90),
        ])
    for row in candidates:
        if row["asset_id"].startswith("press_"):
            row["tags"] = ["nature", "quantum", "figure"]
            row["url_origin"] = "https://www.nature.com/articles/s41586-024-08449-y"
            row["vision_summary"] = "Nature figure: Willow error-correction charts"
        elif "38431825" in row["asset_id"]:
            row["tags"] = ["ticker", "finance"]
            row["url_origin"] = "https://www.pexels.com/video/stock-market-ticker-38431825/"
            row["vision_summary"] = "stock market ticker numbers"
        else:
            row["tags"] = ["quantum", "chip"]
            row["url_origin"] = "https://www.pexels.com/video/quantum-chip-18069803/"
            row["vision_summary"] = "quantum processor chip macro"
    words = {"words": [
        {"display": "невозможно", "start": 0.4, "end": 0.9},
        {"display": "опубликована", "start": 8.4, "end": 8.9},
        {"display": "Nature", "start": 9.12, "end": 9.57},
        {"display": "внутри", "start": 13.2, "end": 13.6},
        {"display": "деньги", "start": 42.6, "end": 43.0},
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
    assert result["accepted"]["0"]["asset_id"] != "pexels_v38431825"


def test_ticker_does_not_empty_the_lattice_interstitial(monkeypatch):
    """Rebalance must not swap ticker onto the twist cut, then drop it.

    Evidence +12 → interstitial +8 looks like an improvement. After the drop
    pass the interstitial was empty and became a red fullscreen (QC-21/30).
    Lattice stays on the cut; ticker waits for «деньги».
    """
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
                "pexels_v35003022": AssetRecord(
                    id="pexels_v35003022", type="video", source="pexels",
                    license="Pexels License",
                    url_origin="https://www.pexels.com/video/gold-lattice-35003022/",
                    tags=["lattice", "quantum"],
                    vision_summary="gold quantum lattice",
                    score=0.88, duration_sec=8.0, width=1080, height=1920,
                    file="pexels/pexels_v35003022.mp4"),
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
            "index": 2, "kind": "footage", "role": "setup",
            "asset_role": "interstitial", "needs_asset": True,
            "visual_intent": "Ведущий представляет тему",
            "start": 6.6, "end": 8.0, "block_id": "b2",
            "reason": "перебивка между аватар-сегментами (§7.4.3, R-3)",
        },
        {
            "index": 3, "kind": "split", "role": "evidence",
            "asset_role": "evidence", "needs_asset": True,
            "visual_intent": "Скриншот статьи в браузере, подсветка ключевой строки",
            "start": 8.0, "end": 10.52, "block_id": "b3",
        },
        {
            "index": 4, "kind": "split", "role": "evidence",
            "asset_role": "evidence", "needs_asset": True,
            "visual_intent": "Скриншот статьи в браузере, подсветка ключевой строки",
            "start": 10.52, "end": 13.04, "block_id": "b3",
        },
        {
            "index": 15, "kind": "footage", "role": "cta",
            "asset_role": "broll", "needs_asset": True,
            "visual_intent": "Финальный кадр, кнопка подписки",
            "start": 40.79, "end": 44.51, "block_id": "b6",
        },
    ]
    candidates = [
        _candidate(2, "pexels_v35003022", score=0.88),
        _candidate(2, "pexels_v38431825", score=0.92),
        _candidate(3, "press_21bc8e2d72", score=0.80),
        _candidate(3, "pexels_v38431825", score=0.92),
        _candidate(4, "pexels_v38431825", score=0.92),
    ]
    for row in candidates:
        if row["asset_id"].startswith("press_"):
            row["tags"] = ["nature", "quantum", "figure"]
            row["url_origin"] = "https://www.nature.com/articles/s41586-024-08449-y"
            row["vision_summary"] = "Nature figure"
        elif "38431825" in row["asset_id"]:
            row["tags"] = ["ticker", "finance"]
            row["url_origin"] = "https://www.pexels.com/video/stock-market-ticker-38431825/"
            row["vision_summary"] = "stock market ticker numbers"
        else:
            row["tags"] = ["lattice", "quantum"]
            row["url_origin"] = "https://www.pexels.com/video/gold-lattice-35003022/"
            row["vision_summary"] = "gold quantum lattice"
    ctx = _Ctx(
        cfg,
        {"video_id": "redshift_0042", "candidates": candidates},
        {"video_id": "redshift_0042", "category": "ai", "duration_sec": 44.5,
         "slots": slots},
        words={"words": [
            {"display": "квантовый", "start": 6.8, "end": 7.3},
            {"display": "опубликована", "start": 8.4, "end": 8.9},
            {"display": "Nature", "start": 9.12, "end": 9.57},
            {"display": "внутри", "start": 11.0, "end": 11.4},
            {"display": "деньги", "start": 42.6, "end": 43.0},
        ]},
    )
    run_step(ctx)
    accepted = ctx.written["accepted_assets.json"]["accepted"]
    assert accepted["2"]["asset_id"] == "pexels_v35003022"
    assert accepted["3"]["asset_id"] == "press_21bc8e2d72"
    assert accepted["15"]["asset_id"] == "pexels_v38431825"
    assert accepted.get("4", {}).get("asset_id") != "pexels_v38431825"
    assert accepted["2"]["asset_id"] != "pexels_v38431825"


def test_rebalance_refuses_a_penalized_destination():
    from src.p8_broll_judge.judge import _rebalance_prefers_onto_speech

    pin_prefer = ["pexels_v35003022", "pexels_v38431825"]
    accepted = {
        2: {"asset_id": "pexels_v35003022", "slot_index": 2},
        4: {"asset_id": "pexels_v38431825", "slot_index": 4},
    }
    slots = {
        2: {"index": 2, "asset_role": "interstitial", "start": 6.6, "end": 8.0,
            "needs_asset": True},
        4: {"index": 4, "asset_role": "evidence", "start": 10.52, "end": 13.04,
            "needs_asset": True},
        15: {"index": 15, "asset_role": "broll", "start": 40.79, "end": 44.51,
             "needs_asset": True, "role": "cta"},
    }
    words = [{"display": "деньги", "start": 42.6, "end": 43.0}]
    swapped = _rebalance_prefers_onto_speech(
        accepted=accepted, pin_prefer=pin_prefer,
        slots_by_index=slots, words=words)
    assert swapped >= 1
    assert accepted[2]["asset_id"] == "pexels_v35003022"
    assert 4 not in accepted
    assert accepted[15]["asset_id"] == "pexels_v38431825"


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
    assert super_entry.get("speech_locked") is True
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
    assert out[1]["carve_remainder"] is True
    assert out[1]["inherit_from"] == 10
    assert all(float(ev["t"]) < out[0]["end"] for ev in out[0]["events"])


def test_carve_remainder_blocks_gap_fullscreen():
    from src.p11_assemble.assemble import _block_gap_fullscreen

    assert _block_gap_fullscreen({"carve_remainder": True}) is True
    assert _block_gap_fullscreen({"reason": "перебивка между аватар-сегментами"}) is False
    assert _block_gap_fullscreen({"kind": "footage"}) is False


def test_p7_exclusive_ids_do_not_consume_runner_ups():
    import inspect

    from src.p7_broll_search import search

    body = inspect.getsource(search.run_step)
    assert "exclusive_ids" in body
    assert "taken_ids = set(exclusive_ids)" in body


def test_cryostat_leftover_skips_nature_evidence():
    from src.lib.pin_match import pin_slot_prefer_key

    evidence = {
        "index": 6, "role": "evidence", "asset_role": "evidence",
        "visual_intent": "Скриншот статьи в браузере",
        "start": 15.58, "end": 18.12,
    }
    words = [
        {"display": "внутри", "start": 15.6, "end": 15.9},
        {"display": "него", "start": 15.9, "end": 16.2},
        {"display": "множило", "start": 16.5, "end": 17.0},
    ]
    bonus, _ = pin_slot_prefer_key(
        "grok_cryostat_0042", evidence, ["grok_cryostat_0042"], words=words)
    assert bonus > 0


def test_hall_inherits_onto_universe_speech():
    from src.p11_assemble.assemble import inherit_ai_plates_onto_speech

    slots = [
        {"index": 10, "start": 26.25, "end": 28.16, "block_id": "b4",
         "kind": "footage"},
        {"index": 11, "start": 28.88, "end": 31.84, "block_id": "b4",
         "kind": "footage", "needs_asset": True},
    ]
    assets = {10: {"asset_id": "grok_supercomputer_0042", "ai_generated": True}}
    words = [{"display": "вселенная", "start": 29.4, "end": 29.85}]
    out = inherit_ai_plates_onto_speech(slots, assets, words)
    assert out[1]["inherit_from"] == 10
    assert "ai_generated" not in out[1]


def test_empty_slot_splits_at_authored_five_minutes():
    from src.p11_assemble.assemble import split_empty_at_authored_punch

    plan = {
        "blocks": [{
            "id": "b4",
            "text": "Задача решена за пять минут.",
            "overlay": {"type": "fullscreen_text", "content": "5 МИНУТ"},
        }],
    }
    slots = [{
        "index": 11, "start": 28.88, "end": 31.84, "duration": 2.96,
        "block_id": "b4", "kind": "footage", "needs_asset": True,
        "inherit_from": 10,
    }]
    words = [
        {"display": "вселенная", "start": 29.4, "end": 29.85, "block_id": "b4"},
        {"display": "пять", "start": 31.032, "end": 31.227, "block_id": "b4"},
        {"display": "минут", "start": 31.227, "end": 31.677, "block_id": "b4"},
    ]
    out = split_empty_at_authored_punch(slots, plan, {}, words)
    assert len(out) == 2
    assert out[0]["inherit_from"] == 10
    assert out[1]["authored_punch"] is True
    assert out[1]["inherit_from"] == 10
    assert float(out[1]["start"]) > 29.85
    assert float(out[1]["end"]) - float(out[1]["start"]) >= 1.14
    assert out[0]["end"] == out[1]["start"]


def test_punch_split_does_not_carve_earlier_empty_slots():
    """Spoken «пять минут» lives in the last empty C — not in every b4 gap."""
    from src.p11_assemble.assemble import split_empty_at_authored_punch

    plan = {
        "blocks": [{
            "id": "b4",
            "text": "Задача решена за пять минут.",
            "overlay": {"type": "fullscreen_text", "content": "5 МИНУТ",
                        "template_hint": "text-fullscreen/impact-01"},
        }],
    }
    slots = [
        {"index": 7, "start": 18.12, "end": 20.84, "duration": 2.72,
         "block_id": "b4", "kind": "footage", "needs_asset": True},
        {"index": 11, "start": 28.88, "end": 31.84, "duration": 2.96,
         "block_id": "b4", "kind": "footage", "needs_asset": True,
         "inherit_from": 10},
    ]
    words = [
        {"display": "вселенная", "start": 29.4, "end": 29.85, "block_id": "b4"},
        {"display": "пять", "start": 31.032, "end": 31.227, "block_id": "b4"},
        {"display": "минут", "start": 31.227, "end": 31.677, "block_id": "b4"},
    ]
    out = split_empty_at_authored_punch(slots, plan, {}, words)
    early = next(s for s in out if int(s["index"]) == 7)
    assert float(early["end"]) == 20.84
    assert not early.get("authored_punch")
    tails = [s for s in out if s.get("authored_punch")]
    assert len(tails) == 1
    assert float(tails[0]["start"]) >= 28.88
    assert tails[0].get("template_hint") == "text-fullscreen/impact-01"


def test_authored_punch_splits_filled_slot():
    """Cached leftover on the punch beat must not skip the authored overlay."""
    from src.p11_assemble.assemble import split_empty_at_authored_punch

    plan = {
        "blocks": [{
            "id": "b4",
            "text": "За конечное время — сингулярность. Вихрь как спагетти.",
            "emphasis_word": "сингулярность",
            "overlay": {"type": "fullscreen_text", "content": "СИНГУЛЯРНОСТЬ"},
        }],
    }
    slots = [{
        "index": 19, "start": 42.866, "end": 45.151, "duration": 2.285,
        "block_id": "b4", "kind": "footage", "needs_asset": True,
    }]
    words = [
        {"display": "энергия.", "start": 42.87, "end": 43.32, "block_id": "b4"},
        {"display": "сингулярность.", "start": 44.70, "end": 45.15, "block_id": "b4"},
    ]
    assets = {19: {"asset_id": "fp_rock_surface"}}
    out = split_empty_at_authored_punch(slots, plan, assets, words)
    tails = [s for s in out if s.get("authored_punch")]
    assert len(tails) == 1
    assert tails[0]["inherit_from"] == 19
    assert float(tails[0]["start"]) >= 43.4
    assert float(tails[0]["end"]) == 45.151


def test_inherited_hall_skips_the_emphasis_card():
    """Hall plate is the shot; «ВДВОЕ» over it was the 0042 defect."""
    from src.p11_assemble.assemble import VisualBudget, _close_empty_slot

    rung, hero, overlay = _close_empty_slot(
        {"index": 11, "start": 28.88, "end": 31.23, "duration": 2.35,
         "inherit_from": 10, "block_id": "b4", "beat": ""},
        {"id": "b4",
         "text": "ошибка падает вдвое. решена за пять минут.",
         "emphasis_word": "вдвое"},
        budget=VisualBudget(),
        picker=None,
        catalog=None,
        plan={"duration_sec": 44, "title": "", "sources": []},
        variant="A", seed=1, recent_videos=[], used_templates=[],
        brand_icons=None, words=[], plate_src=None,
        traits={"number", "comparison"}, bg_file="/tmp/hall.mp4")
    assert rung == "inherit"
    assert hero is None
    assert overlay is None
