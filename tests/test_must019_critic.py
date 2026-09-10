"""MUST-019: cheap ≥50% kill; GLM-5.3-free mid; Grok only in grey [0.45, 0.80)."""

from __future__ import annotations

from src.errors import ProviderError
from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.providers.vision import GLMVision, VisionVerdict
from src.p8_broll_judge.judge import cheap_reject_reason, in_grey_zone, run_step


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
    def __init__(self, score: float, name: str):
        self.score = score
        self.name = name
        self.calls = 0
        self.queries: list[str] = []

    def judge(self, frames, **kwargs):
        self.calls += 1
        self.queries.append(str(kwargs.get("query") or ""))
        return VisionVerdict(score=self.score, reason="spy", judge=self.name)


def _slot() -> dict:
    return {
        "index": 0, "kind": "footage", "role": "develop",
        "asset_role": "broll", "needs_asset": True, "block_id": "b0",
        "visual_intent": "quantum laboratory cryostat",
        "start": 0.0, "end": 2.0,
    }


def _good(n: int) -> dict:
    return {
        "slot_index": 0,
        "asset_id": f"good_{n}",
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


JUNK_TAGS = [
    ["talking head"],
    ["talking-head"],
    ["watermark"],
    ["shutterstock preview"],
    ["getty images"],
    ["ui screenshot"],
    ["app screenshot"],
    ["desktop screenshot"],
    ["clickbait thumbnail"],
    ["clickbait"],
    ["youtube thumbnail"],
    ["stock smile lab"],
    ["stock smile"],
    ["smiling scientist"],
    ["smiling doctor"],
    ["happy lab team"],
    ["talkinghead"],
    ["getty"],
    ["watermark overlay"],
]


def _junk(n: int, tags: list[str], **over) -> dict:
    token = tags[0].replace(" ", "-")
    row = {
        "slot_index": 0,
        "asset_id": f"junk_{n}",
        "origin": "stock",
        "source": "pexels",
        "kind": "video",
        "query": token,
        "tags": tags,
        "url_origin": f"https://example.com/{token}",
        "page_url": f"https://example.com/{token}",
        "attribution": " ".join(tags),
        "width": 1080, "height": 1920, "duration_sec": 5.0,
        "frames": [],
    }
    row.update(over)
    return row


def _plan(video_id: str = "must019"):
    return {
        "video_id": video_id, "category": "ai",
        "slots": [_slot()], "blocks": [],
    }


def _surplus(n: int) -> dict:
    return {
        "ok": True, "ratio": 1.3, "candidates": n, "target": 2,
        "slots_needing_footage": 1, "status": "ok",
    }


def test_config_glm_mid_grok_grey_budget(cfg):
    assert str(cfg.get("vision.primary")).lower() == "glm"
    assert str(cfg.get("vision.arbiter")).lower() == "grok"
    assert str(cfg.get("vision.fallback")).lower() == "glm"
    assert int(cfg.get("vision.arbiter_max_calls")) <= 3
    model = str(cfg.get("vision.glm_model")).lower()
    assert "5.3" in model
    assert "4.6v-flash" not in model
    assert "5.3" in str(cfg.get("vision.glm_model_fallback", "")).lower()
    grok = str(cfg.get("vision.grok_model")).lower()
    assert grok == "grok-4.6"
    assert "grok-4-fast" not in grok
    assert "grok-2-vision" not in grok
    base = str(cfg.get("vision.glm_api_base")).lower()
    assert "open.bigmodel.cn" not in base
    assert "api.z.ai" in base or "tokenrouter" in base


def test_grey_zone_bounds(cfg):
    assert in_grey_zone(0.45, cfg)
    assert in_grey_zone(0.55, cfg)
    assert in_grey_zone(0.70, cfg)
    assert in_grey_zone(0.79, cfg)
    assert not in_grey_zone(0.80, cfg)
    assert not in_grey_zone(0.40, cfg)
    assert not in_grey_zone(0.81, cfg)


def test_cheap_kills_at_least_half_of_junk_pool(cfg):
    negatives = [
        "talking head", "watermark", "UI screenshot",
        "clickbait thumbnail", "stock smile lab",
    ]
    junk = [_junk(i, JUNK_TAGS[i]) for i in range(19)]
    junk.append(_junk(19, ["ultrawide"], width=3000, height=1000))
    good = [_good(i) for i in range(4)]
    killed = sum(
        1 for row in junk
        if cheap_reject_reason(
            row, cfg=cfg, slot_duration=2.0, negatives=negatives,
            category="ai", intent_kind="lab", video_id="redshift_0042")
    )
    kept_good = sum(
        1 for row in good
        if cheap_reject_reason(
            row, cfg=cfg, slot_duration=2.0, negatives=negatives,
            category="ai", intent_kind="lab", video_id="redshift_0042") is None
    )
    assert killed >= 10, killed
    assert killed >= 0.5 * (len(junk) + len(good)) or killed >= 10
    assert kept_good == 4


def _run(monkeypatch, candidates, *, glm: _Spy, grok: _Spy, mode: str = "mock"):
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", False)
    cfg.set("providers.mode", mode)
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))

    def _build(_cfg, _costs, *, role="primary"):
        return grok if role == "arbiter" else glm

    monkeypatch.setattr(J, "build_vision_provider", _build)
    ctx = _Ctx(
        cfg,
        {"video_id": "must019", "candidates": candidates,
         "surplus": _surplus(len(candidates))},
        _plan(),
    )
    run_step(ctx)
    return ctx.written["accepted_assets.json"]


def test_cheap_filter_runs_before_vision_on_junk_pool(monkeypatch):
    junk = [_junk(i, JUNK_TAGS[i]) for i in range(19)]
    junk.append(_junk(19, ["ultrawide"], width=3000, height=1000))
    good = [_good(i) for i in range(4)]
    glm, grok = _Spy(0.91, "glm"), _Spy(0.91, "grok")
    result = _run(monkeypatch, junk + good, glm=glm, grok=grok)
    assert result["killed_cheap"] >= 10
    assert result["cheap_kill_rate"] >= 0.5
    judged_good = {row["asset_id"] for row in result["judged"]
                   if str(row.get("asset_id") or "").startswith("good_")}
    assert judged_good == {f"good_{i}" for i in range(4)}
    assert glm.calls == 4
    assert grok.calls == 0
    assert result["grok_calls"] == 0


def test_score_outside_grey_does_not_call_grok(monkeypatch):
    glm40, grok40 = _Spy(0.40, "glm"), _Spy(0.99, "grok")
    result40 = _run(monkeypatch, [_good(0)], glm=glm40, grok=grok40)
    assert glm40.calls == 1
    assert grok40.calls == 0
    assert result40["grok_calls"] == 0

    glm80, grok80 = _Spy(0.80, "glm"), _Spy(0.99, "grok")
    result80 = _run(monkeypatch, [_good(1)], glm=glm80, grok=grok80)
    assert glm80.calls == 1
    assert grok80.calls == 0
    assert result80["grok_calls"] == 0


def test_grey_score_calls_second_level_at_most_once_per_clip(monkeypatch):
    glm, grok = _Spy(0.55, "glm"), _Spy(0.88, "grok")
    result = _run(monkeypatch, [_good(0), _good(1)], glm=glm, grok=grok)
    assert glm.calls == 2
    assert grok.calls == 2
    assert grok.calls <= glm.calls
    by_clip = {}
    for row in result["judged"]:
        if row.get("verdict", {}).get("arbitrated"):
            aid = row["asset_id"]
            by_clip[aid] = by_clip.get(aid, 0) + 1
    assert by_clip.get("good_0") == 1
    assert by_clip.get("good_1") == 1
    assert result["arbiter_calls"] <= result["arbiter_budget"] <= 3


def test_missing_glm_key_does_not_crash(monkeypatch):
    from src.p8_broll_judge import judge as J

    cfg = load_config()
    cfg.set("vision.skip_live", False)
    cfg.set("providers.mode", "auto")
    for env_name in (
        "GLM_API_KEY", "GLM_API", "TOKENROUTER_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY",
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AI_API_KEY", "XAI_API_KEY", "XAI_API",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(J.FootageIndex, "load", classmethod(lambda cls, cfg: _Index()))
    ctx = _Ctx(
        cfg,
        {"video_id": "must019_nokey", "candidates": [_good(0)],
         "surplus": _surplus(1)},
        _plan("must019_nokey"),
    )
    run_step(ctx)
    result = ctx.written["accepted_assets.json"]
    assert "judged" in result
    assert result["grok_calls"] == 0


def test_glm_payload_has_no_json_object_response_format(cfg, monkeypatch, tmp_path):
    from PIL import Image

    frame = tmp_path / "f.jpg"
    Image.new("RGB", (32, 32), (40, 80, 160)).save(frame, format="JPEG")
    captured: dict[str, object] = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {
                "content": 'preamble {"score": 0.81, "reason": "ok", '
                           '"summary": "lab", "relevance": 0.8, "quality": 0.8, '
                           '"composition_9x16": 0.7, "has_text": false, '
                           '"has_logo": false, "watermark": false, "stocky": false}'
            }}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setenv("GLM_API_KEY", "glm-test-key")
    cfg.set("providers.mode", "live")
    import src.lib.providers.vision as V
    monkeypatch.setattr(V, "call_with_retry", lambda fn, **k: fn())
    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    judge = GLMVision(cfg, CostLedger(video_id="t"), api_key="glm-test-key")
    verdict = judge.judge([frame], intent="chip", role="develop", query="willow")
    assert verdict.score == 0.81
    assert verdict.judge == "glm"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert "response_format" not in payload
    assert "json_object" not in str(payload).lower()
    assert "json_schema" not in str(payload).lower()
    assert payload["model"] == cfg.get("vision.glm_model")
    assert "open.bigmodel.cn" not in str(captured["url"])
    content = payload["messages"][0]["content"]
    assert any(part.get("type") == "image_url" for part in content)


def test_glm_rejects_flash_model(cfg, tmp_path):
    cfg.set("vision.glm_model", "GLM-4.6V-Flash")
    judge = GLMVision(cfg, CostLedger(video_id="t"), api_key="k")
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff\xd9")
    try:
        judge.judge([frame], intent="x", role="develop", query="q")
    except ProviderError as exc:
        assert "4.6V-Flash" in str(exc) or "5.3-free" in str(exc)
    else:
        raise AssertionError("Flash model must be rejected")
