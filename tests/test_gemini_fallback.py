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
    FallbackVision, GeminiVision, GLMVision, GrokVision, MockVision,
    build_vision_provider,
)


@pytest.fixture
def cfg():
    return load_config()


def _provider_blob(provider) -> str:
    parts = [getattr(provider, "name", ""), type(provider).__name__]
    for attr in ("primary", "secondary"):
        child = getattr(provider, attr, None)
        if child is not None:
            parts.append(_provider_blob(child))
    return " ".join(parts).lower()


def test_config_prefers_gemini_without_xai(cfg):
    # Vision mid-critic is GLM; image generation stays Gemini-only, no xAI.
    assert str(cfg.get("vision.primary")).lower() == "glm"
    assert str(cfg.get("vision.arbiter")).lower() == "grok"
    assert str(cfg.get("vision.fallback") or "").lower() == "glm"
    assert str(cfg.get("generation.source")).lower() == "gemini"
    assert str(cfg.get("generation.fallback") or "") == ""
    assert cfg.get("providers.allow_xai") is False
    assert str(cfg.get("render.thumbnail_mode")).lower() == "auto"


def test_vision_uses_glm_when_key_present(cfg, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "glm-test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_AI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg.set("providers.mode", "auto")
    provider = build_vision_provider(cfg, CostLedger(video_id="t"), role="primary")
    assert isinstance(provider, GLMVision)


def test_vision_uses_gemini_when_key_present(cfg, monkeypatch):
    """Нет GLM-ключа — Gemini остаётся запасом primary, не arbiter-на-всё."""
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("TOKENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg.set("providers.mode", "auto")
    provider = build_vision_provider(cfg, CostLedger(video_id="t"), role="primary")
    assert isinstance(provider, GeminiVision)
    assert "grok" not in _provider_blob(provider)


def test_vision_does_not_use_grok_when_allow_xai_is_false(cfg, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("TOKENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    cfg.set("providers.mode", "auto")
    cfg.set("providers.allow_xai", False)
    provider = build_vision_provider(cfg, CostLedger(video_id="t"), role="primary")
    assert "grok" not in _provider_blob(provider)
    assert not isinstance(provider, FallbackVision)
    assert isinstance(provider, GeminiVision)


def test_vision_without_gemini_stays_mock_when_xai_forbidden(cfg, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_AI_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("TOKENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    cfg.set("providers.mode", "auto")
    cfg.set("providers.allow_xai", False)
    provider = build_vision_provider(cfg, CostLedger(video_id="t"), role="primary")
    assert isinstance(provider, MockVision)
    assert "grok" not in _provider_blob(provider)


def test_vision_fallback_on_403(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("GLM_API_KEY", "glm-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg.set("providers.mode", "auto")
    cfg.set("vision.fallback", "gemini")
    provider = build_vision_provider(cfg, CostLedger(video_id="t"), role="primary")
    assert isinstance(provider, FallbackVision)
    assert "grok" not in _provider_blob(provider)

    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff\xd9")

    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise ProviderError("GLM credits", status=403, body="spending limit")

    def ok(*a, **k):
        from src.lib.providers.vision import VisionVerdict
        return VisionVerdict(score=0.8, reason="ok", judge="gemini")

    monkeypatch.setattr(provider.primary, "judge", boom)
    monkeypatch.setattr(provider.secondary, "judge", ok)
    verdict = provider.judge([frame], intent="x", role="develop", query="q")
    assert verdict.judge == "gemini"
    assert calls["n"] == 1


def test_primary_never_uses_grok_even_if_allow_xai(cfg, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "glm-test-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    cfg.set("providers.mode", "auto")
    cfg.set("providers.allow_xai", True)
    provider = build_vision_provider(cfg, CostLedger(video_id="t"), role="primary")
    assert "grok" not in _provider_blob(provider)


def test_arbiter_can_use_grok_without_global_allow_xai(cfg, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "glm-test-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    cfg.set("providers.mode", "auto")
    cfg.set("providers.allow_xai", False)
    provider = build_vision_provider(cfg, CostLedger(video_id="t"), role="arbiter")
    assert "grok" in _provider_blob(provider)
    assert isinstance(provider, (GrokVision, FallbackVision))


def test_generation_prefers_gemini_key(cfg, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg.set("providers.mode", "auto")
    provider = build_generation_provider(cfg, CostLedger(video_id="t"))
    leaf = getattr(provider, "primary", provider)
    assert isinstance(leaf, GeminiImageGeneration) or isinstance(provider, GeminiImageGeneration)


def test_generation_does_not_use_grok_when_allow_xai_is_false(cfg, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    cfg.set("providers.mode", "auto")
    cfg.set("providers.allow_xai", False)
    provider = build_generation_provider(cfg, CostLedger(video_id="t"))
    assert "grok" not in _provider_blob(provider)
    assert not isinstance(provider, FallbackGeneration)


def test_generation_fallback_on_403(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    cfg.set("providers.mode", "auto")
    cfg.set("providers.allow_xai", True)
    cfg.set("generation.fallback", "grok")
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


def test_skip_live_does_not_invent_a_passing_score():
    from src.lib.footage_seed import SEED_SCORE
    from src.p8_broll_judge.judge import skip_live_verdict

    unverified = skip_live_verdict({"score": 0.72, "asset_id": "pexels_v20757503"},
                                   "процессор крупно")
    assert unverified["judge"] == "skip_live_unverified"
    assert unverified["score"] == SEED_SCORE
    assert unverified["score"] < 0.70

    reused = skip_live_verdict(
        {"prior_score": 0.88, "prior_intent": "логический кубит в статье",
         "vision_summary": "paper"},
        "логический кубит в журнале")
    assert reused["judge"] == "skip_live"
    assert reused["score"] == 0.88

    mismatched = skip_live_verdict(
        {"prior_score": 0.88, "prior_intent": "швейная машинка крупно"},
        "логический кубит в статье")
    assert mismatched["score"] == pytest.approx(0.73)
