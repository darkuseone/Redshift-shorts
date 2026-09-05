"""503/UNAVAILABLE capacity backoff + Gemini vision Flash fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.errors import ProviderError
from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.retry import call_with_retry, is_capacity_error
from src.lib.providers import vision as V
from src.lib.providers.vision import GeminiVision, VisionVerdict


def test_is_capacity_error_detects_gemini_503():
    exc = ProviderError(
        "Gemini вернул 503",
        status=503,
        body='{"error":{"code":503,"message":"This model is currently experiencing high demand.",'
             '"status":"UNAVAILABLE"}}',
    )
    assert is_capacity_error(exc)
    assert not is_capacity_error(ProviderError("bad request", status=400))


def test_capacity_backoff_uses_longer_delays():
    sleeps: list[float] = []
    n = {"i": 0}

    def boom():
        n["i"] += 1
        raise ProviderError("Gemini вернул 503", status=503, body="UNAVAILABLE high demand")

    with pytest.raises(ProviderError, match="исчерпаны 6"):
        call_with_retry(
            boom,
            attempts=3,
            base_delay=2.0,
            capacity_attempts=6,
            capacity_base_delay=5.0,
            what="Gemini vision",
            sleep=sleeps.append,
        )
    assert n["i"] == 6
    assert sleeps == [5.0, 10.0, 20.0, 40.0, 80.0]


def test_non_capacity_keeps_short_retries():
    sleeps: list[float] = []
    n = {"i": 0}

    def boom():
        n["i"] += 1
        raise ProviderError("Gemini вернул 400", status=400, body="bad")

    with pytest.raises(ProviderError, match="исчерпаны 3"):
        call_with_retry(
            boom,
            attempts=3,
            base_delay=2.0,
            capacity_attempts=6,
            capacity_base_delay=5.0,
            what="Gemini vision",
            sleep=sleeps.append,
        )
    assert n["i"] == 3
    assert sleeps == [2.0, 4.0]


def test_config_capacity_and_flash_fallback():
    cfg = load_config()
    assert int(cfg.get("providers.capacity_retries")) == 6
    assert float(cfg.get("providers.capacity_backoff_base_sec")) == 5.0
    assert str(cfg.get("vision.gemini_model")) == "gemini-3.8-flash"
    assert str(cfg.get("vision.gemini_model_fallback")) == "gemini-3.7-flash"


def test_vision_falls_back_to_next_flash_after_503(monkeypatch, tmp_path):
    cfg = load_config()
    provider = GeminiVision(cfg, CostLedger(video_id="t"), api_key="k")
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff\xd9")

    seen: list[str] = []

    def fake_retry(fn, **kwargs):
        # Peek model from ProviderError that _call would raise — call fn once.
        # Instead intercept requests via judge's loop: patch call_with_retry per model.
        raise ProviderError("Gemini вернул 503", status=503, body="high demand UNAVAILABLE")

    calls = {"n": 0}

    def selective_retry(fn, **kwargs):
        calls["n"] += 1
        # First model capacity-exhausted; second succeeds.
        if calls["n"] == 1:
            raise ProviderError("Gemini вернул 503", status=503, body="high demand UNAVAILABLE")
        return {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": '{"score":0.8,"reason":"ok","summary":"ok",'
                                '"has_text":false,"has_logo":false,"watermark":false,'
                                '"stocky":false,"composition_9x16":0.8,'
                                '"quality":0.8,"relevance":0.8}'
                    }]
                }
            }]
        }

    monkeypatch.setattr(V, "call_with_retry", selective_retry)
    monkeypatch.setattr(provider, "charge", lambda *a, **k: None)
    verdict = provider.judge([frame], intent="x", role="develop", query="q")
    assert isinstance(verdict, VisionVerdict)
    assert calls["n"] == 2
    assert verdict.score == 0.8
