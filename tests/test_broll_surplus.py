"""MUST-017: +30% surplus кандидатов до Gemini/Grok/Magnific."""

from __future__ import annotations

from src.lib.config import load_config
from src.lib.providers.vision import VisionVerdict
from src.p7_broll_search.search import surplus_report, surplus_target
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
        self.calls = 0

    def judge(self, frames, **kwargs):
        self.calls += 1
        return VisionVerdict(score=0.91, reason="spy", judge="spy")


def _slot(i: int) -> dict:
    return {
        "index": i, "kind": "footage", "role": "develop",
        "asset_role": "broll", "needs_asset": True, "block_id": f"b{i}",
        "visual_intent": "quantum laboratory cryostat",
        "start": float(i * 2), "end": float(i * 2 + 2),
    }


def _cand(slot_index: int, n: int) -> dict:
    return {
        "slot_index": slot_index,
        "asset_id": f"stock_{slot_index}_{n}",
        "origin": "stock",
        "source": "pexels",
        "query": "quantum processor macro",
        "tags": ["quantum", "processor", "laboratory"],
        "url_origin": "https://example.com/quantum-processor-laboratory",
        "page_url": "https://example.com/quantum-processor-laboratory",
        "attribution": "pexels / lab",
        "frames": [],
    }


def _plan_and_pool(n_slots: int, n_cands: int):
    slots = [_slot(i) for i in range(n_slots)]
    candidates = []
    for i in range(n_cands):
        candidates.append(_cand(i % n_slots, i))
    return slots, candidates


def test_surplus_target_ten_slots_is_thirteen():
    assert surplus_target(10, 1.3) == 13
    assert surplus_report(12, 10, 1.3)["status"] == "underfilled"
    assert surplus_report(12, 10, 1.3)["ok"] is False
    assert surplus_report(13, 10, 1.3)["ok"] is True
    assert surplus_report(13, 10, 1.3)["status"] == "ok"
    assert surplus_report(13, 10, 1.3)["slots_judgable"] == 10


def test_empty_slots_do_not_inflate_surplus_target():
    """Дыры b4/b5 не должны блокировать критика на слотах, где пул есть."""
    filled = surplus_report(22, 17, 1.3, slots_judgable=13)
    assert filled["target"] == 17
    assert filled["ok"] is True
    assert filled["slots_needing_footage"] == 17
    assert filled["slots_judgable"] == 13
    thin = surplus_report(22, 17, 1.3, slots_judgable=17)
    assert thin["target"] == 23
    assert thin["ok"] is False


def test_config_surplus_ratio_is_1_3(cfg):
    assert cfg.get("stock.candidate_surplus") == 1.3
    live = load_config()
    assert int(live.get("stock.local_candidates_per_slot")) == 24
    assert int(live.get("stock.local_keep_per_slot")) == 2


def _run(monkeypatch, n_slots: int, n_cands: int, spy: _Spy):
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", False)
    cfg.set("providers.mode", "mock")
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))
    monkeypatch.setattr(J, "build_vision_provider", lambda *a, **k: spy)
    slots, candidates = _plan_and_pool(n_slots, n_cands)
    surplus = surplus_report(n_cands, n_slots, 1.3)
    ctx = _Ctx(
        cfg,
        {"video_id": "surplus_test", "candidates": candidates, "surplus": surplus},
        {"video_id": "surplus_test", "category": "ai", "slots": slots, "blocks": []},
    )
    run_step(ctx)
    return ctx.written["accepted_assets.json"]


def test_underfilled_pool_does_not_call_paid_critic(monkeypatch):
    spy = _Spy()
    result = _run(monkeypatch, 10, 12, spy)
    assert spy.calls == 0
    assert result["surplus"]["status"] == "underfilled"
    assert result["surplus"]["target"] == 13
    decisions = {row.get("decision") for row in result["judged"]}
    assert "underfilled" in decisions
    assert result["accepted_count"] == 0
    assert result["surplus_blocks_generation"] is True
    assert result["unfilled_slots"] == []
    assert result["ladder_slots"] == list(range(10))


def test_empty_slots_do_not_block_critic_on_the_rest(monkeypatch):
    """22 кандидата на 13 слотах при 17 дырах: critic зовётся, P9 не сжигает квоту."""
    spy = _Spy()
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", False)
    cfg.set("providers.mode", "mock")
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))
    monkeypatch.setattr(J, "build_vision_provider", lambda *a, **k: spy)
    slots = [_slot(i) for i in range(17)]
    candidates = [_cand(i % 13, i) for i in range(22)]
    ctx = _Ctx(
        cfg,
        {"video_id": "surplus_holes", "candidates": candidates},
        {"video_id": "surplus_holes", "category": "ai", "slots": slots, "blocks": []},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    assert spy.calls >= 1
    assert result["surplus"]["ok"] is True
    assert result["surplus"]["slots_judgable"] == 13
    assert result["surplus"]["target"] == 17
    assert result["surplus_blocks_generation"] is False


def test_surplus_met_allows_paid_critic(monkeypatch):
    spy = _Spy()
    result = _run(monkeypatch, 10, 13, spy)
    assert spy.calls >= 1
    assert result["surplus"]["ok"] is True
    assert result["surplus"]["status"] == "ok"


def test_underfilled_local_cache_reuses_prior_score(monkeypatch):
    """MUST-017: paid critic для нового стока; кэш с prior_score принимают без него."""
    spy = _Spy()
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", False)
    cfg.set("providers.mode", "mock")
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))
    monkeypatch.setattr(J, "build_vision_provider", lambda *a, **k: spy)
    slots = [_slot(i) for i in range(10)]
    candidates = []
    for i in range(12):
        row = _cand(i % 10, i)
        row["origin"] = "local_cache"
        row["prior_score"] = 0.91
        row["url_origin"] = row["page_url"]
        candidates.append(row)
    surplus = surplus_report(12, 10, 1.3)
    ctx = _Ctx(
        cfg,
        {"video_id": "surplus_cache", "candidates": candidates, "surplus": surplus},
        {"video_id": "surplus_cache", "category": "ai", "slots": slots, "blocks": []},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    assert spy.calls == 0
    assert result["surplus"]["status"] == "underfilled"
    assert result["accepted_count"] >= 10
    decisions = {row.get("decision") for row in result["judged"]
                 if row.get("origin") == "local_cache"}
    assert "underfilled" not in decisions


class _LowSpy:
    def __init__(self):
        self.calls = 0

    def judge(self, frames, **kwargs):
        self.calls += 1
        return VisionVerdict(score=0.22, reason="low", judge="grok")


def test_critic_reject_leftover_fills_from_downloaded_files(monkeypatch, tmp_path):
    """Grok < 0.70, арбитраж не исчерпан — слоты закрывает уже скачанный клип."""
    from PIL import Image

    from src.p8_broll_judge import judge as J

    spy = _LowSpy()
    cfg = load_config()
    cfg.set("vision.skip_live", False)
    cfg.set("providers.mode", "mock")
    cfg.set("stock.same_asset_max_slots", 1)
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))
    monkeypatch.setattr(J, "build_vision_provider", lambda *a, **k: spy)

    n_slots = 6
    slots = [_slot(i) for i in range(n_slots)]
    candidates = []
    # 8 клипов на 4 слота: surplus ок, два пустых слота закрывает leftover.
    for i in range(8):
        row = _cand(i % 4, i)
        media = tmp_path / f"{row['asset_id']}.jpg"
        Image.new("RGB", (32, 32), (18, 18, 18)).save(media, format="JPEG")
        row["local_file"] = str(media)
        row["storage_key"] = f"stock/{row['asset_id']}.mp4"
        row["frames"] = [str(media)]
        candidates.append(row)
    ctx = _Ctx(
        cfg,
        {"video_id": "leftover_stock", "candidates": candidates},
        {"video_id": "leftover_stock", "category": "ai", "slots": slots, "blocks": []},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    assert spy.calls >= 1
    assert result["surplus"]["ok"] is True
    assert result["accepted_count"] == n_slots
    leftover = [
        entry for entry in result["accepted"].values()
        if entry.get("decision") == "accept_stock_leftover"
    ]
    assert leftover
    assert all(entry.get("local_file") for entry in result["accepted"].values())
    assert len({entry["asset_id"] for entry in result["accepted"].values()}) == n_slots
    assert result["unfilled_slots"] == []
    assert result["surplus_blocks_generation"] is False
    assert all("leftover_from_slot" in entry for entry in leftover)


def test_leftover_does_not_park_cross_topic_stock(monkeypatch, tmp_path):
    """Datacenter leftover must not fill a fluids slot."""
    from PIL import Image

    from src.p8_broll_judge import judge as J

    spy = _LowSpy()
    cfg = load_config()
    cfg.set("vision.skip_live", False)
    cfg.set("providers.mode", "mock")
    cfg.set("stock.same_asset_max_slots", 1)
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))
    monkeypatch.setattr(J, "build_vision_provider", lambda *a, **k: spy)

    slots = [
        {**_slot(0), "visual_intent": "quantum laboratory cryostat",
         "queries": ["quantum processor macro chip"], "block_id": "b3"},
        {**_slot(1), "visual_intent": "weather radar airplane wing blood",
         "queries": ["weather radar storm satellite"], "block_id": "b4"},
    ]
    candidates = []
    for i in range(4):
        row = _cand(0, i)
        media = tmp_path / f"{row['asset_id']}.jpg"
        Image.new("RGB", (32, 32), (18, 18, 18)).save(media, format="JPEG")
        row["local_file"] = str(media)
        row["storage_key"] = f"stock/{row['asset_id']}.mp4"
        row["frames"] = [str(media)]
        candidates.append(row)
    ctx = _Ctx(
        cfg,
        {"video_id": "leftover_topic", "candidates": candidates},
        {"video_id": "leftover_topic", "category": "ai", "slots": slots,
         "blocks": [
             {"id": "b3", "text": "OpenAI выкладывает работу про Астру."},
             {"id": "b4", "text": "Погода, крыло самолёта, ток крови."},
         ]},
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    leftover = [
        entry for entry in result["accepted"].values()
        if entry.get("decision") == "accept_stock_leftover"
    ]
    assert 0 in {int(k) for k in result["accepted"]} or leftover
    assert 1 not in {int(k) for k in result["accepted"]}
    assert 1 in result["unfilled_slots"]


def test_critic_reject_without_files_does_not_leftover_fill(monkeypatch):
    """Без скачанного файла leftover не подменяет генерацию / лестницу."""
    spy = _LowSpy()
    result = _run(monkeypatch, 10, 13, spy)
    assert spy.calls >= 1
    assert result["surplus"]["ok"] is True
    assert result["accepted_count"] == 0
    decisions = {row.get("decision") for row in result["judged"]}
    assert "accept_stock_leftover" not in decisions
    assert result["unfilled_slots"] == list(range(10))

