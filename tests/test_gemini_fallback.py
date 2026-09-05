"""TEMP: Gemini primary when XAI credits fail; Grok remains fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.errors import ProviderError
from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.providers import generation as G
from src.lib.providers import vision as V
from src.lib.providers.generation import (
    FallbackGeneration, GeminiImageGeneration, GrokImageGeneration, MockGeneration,
    build_generation_provider,
)
from src.lib.providers.vision import (
    FallbackVision, GeminiVision, GrokVision, MockVision, build_vision_provider,
)


@pytest.fixture
def cfg():
    return load_config()


def test_config_prefers_gemini_temporarily(cfg):
    assert str(cfg.get("vision.primary")).lower() == "gemini"
    assert str(cfg.get("vision.fallback")).lower() == "grok"
    assert str(cfg.get("generation.source")).lower() == "gemini"
    assert str(cfg.get("generation.fallback")).lower() == "grok"
    assert str(cfg.get("render.thumbnail_mode")).lower() == "auto"


def test_vision_uses_gemini_when_key_present(cfg, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg.set("providers.mode", "auto")
    provider = build_vision_provider(cfg, CostLedger(video_id="t"), role="primary")
    assert isinstance(provider, GeminiVision)


def test_vision_falls_back_to_grok_without_gemini(cfg, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_AI_API_KEY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    cfg.set("providers.mode", "auto")
    provider = build_vision_provider(cfg, CostLedger(video_id="t"), role="primary")
    # preferred gemini missing → live grok (possibly wrapped alone)
    leaf = getattr(provider, "primary", provider)
    assert isinstance(leaf, GrokVision) or isinstance(provider, GrokVision)


def test_vision_fallback_on_403(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    cfg.set("providers.mode", "auto")
    provider = build_vision_provider(cfg, CostLedger(video_id="t"), role="primary")
    assert isinstance(provider, FallbackVision)

    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff\xd9")

    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise ProviderError("Grok credits", status=403, body="spending limit")

    def ok(*a, **k):
        from src.lib.providers.vision import VisionVerdict
        return VisionVerdict(score=0.8, reason="ok", judge="grok")

    monkeypatch.setattr(provider.primary, "judge", boom)
    monkeypatch.setattr(provider.secondary, "judge", ok)
    verdict = provider.judge([frame], intent="x", role="develop", query="q")
    assert verdict.judge == "grok"
    assert calls["n"] == 1


def test_generation_prefers_gemini_key(cfg, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg.set("providers.mode", "auto")
    provider = build_generation_provider(cfg, CostLedger(video_id="t"))
    leaf = getattr(provider, "primary", provider)
    assert isinstance(leaf, GeminiImageGeneration) or isinstance(provider, GeminiImageGeneration)


def test_generation_fallback_on_403(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    cfg.set("providers.mode", "auto")
    provider = build_generation_provider(cfg, CostLedger(video_id="t"))
    assert isinstance(provider, FallbackGeneration)

    from src.lib.providers.generation import GeneratedAsset

    def boom(*a, **k):
        raise ProviderError("Gemini quota", status=403)

    def ok(prompt, dst, *, kind="video", duration_sec=4.0, prefer_free=True):
        Path(dst).write_bytes(b"ok")
        return GeneratedAsset(
            id="g1", path=Path(dst), kind=kind, prompt=prompt,
            model="grok-imagine-image", duration_sec=duration_sec,
            meta={"still_from": "grok"},
        )

    monkeypatch.setattr(provider.primary, "generate", boom)
    monkeypatch.setattr(provider.secondary, "generate", ok)
    asset = provider.generate("prompt", tmp_path / "out.png", kind="photo")
    assert asset.meta.get("still_from") == "grok"


def test_credits_helper():
    assert V._credits_or_auth_failure(ProviderError("x", status=403))
    assert G._credits_or_auth_failure(ProviderError("out of credits", status=200))
    assert not V._credits_or_auth_failure(ProviderError("timeout", status=500))
