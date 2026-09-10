"""Paid API на перерендере запрещены без --force-paid."""

from __future__ import annotations

import argparse

import pytest

from src.cli import PAID_SKIPPED_MSG, enforce_paid_rerun_guard
from src.errors import PaidRerunForbidden, SpeechChangedNewVideo
from src.lib.config import load_config


def _args(**kwargs):
    ns = argparse.Namespace(force_paid=False, force=False)
    for key, value in kwargs.items():
        setattr(ns, key, value)
    return ns


def _seed_voice(root, video_id: str = "vid"):
    path = root / "assets" / "voice" / video_id / "voice_final.wav"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"RIFF....")
    return path


def test_prepared_plus_voice_skips_paid_even_with_force(tmp_path):
    cfg = load_config()
    cfg.repo_root = tmp_path
    _seed_voice(tmp_path)
    cfg.set("heygen.source", "prepared")
    enforce_paid_rerun_guard(cfg, _args(force=True), video_id="vid")
    assert cfg.get("pipeline.paid_skipped") is True
    assert cfg.get("heygen.source") == "prepared"
    assert cfg.get("pipeline.force_paid") is False


def test_api_plus_voice_forbidden_without_force_paid(tmp_path):
    cfg = load_config()
    cfg.repo_root = tmp_path
    _seed_voice(tmp_path)
    cfg.set("heygen.source", "api")
    with pytest.raises(PaidRerunForbidden):
        enforce_paid_rerun_guard(cfg, _args(force=True), video_id="vid")


def test_force_paid_allows_api(tmp_path):
    cfg = load_config()
    cfg.repo_root = tmp_path
    _seed_voice(tmp_path)
    cfg.set("heygen.source", "api")
    enforce_paid_rerun_guard(cfg, _args(force_paid=True), video_id="vid")
    assert cfg.get("pipeline.force_paid") is True


def test_no_voice_seed_does_not_block(tmp_path):
    cfg = load_config()
    cfg.repo_root = tmp_path
    cfg.set("heygen.source", "api")
    enforce_paid_rerun_guard(cfg, _args(), video_id="vid")
    assert not cfg.get("pipeline.paid_skipped")


def test_speech_change_needs_new_video_id(tmp_path):
    from src.p2_tts.tts import run_step

    cfg = load_config(overrides=["providers.mode=mock"])
    cfg.repo_root = tmp_path
    prepared = tmp_path / "assets" / "voice" / "vid"
    prepared.mkdir(parents=True)
    (prepared / "voice_final.wav").write_bytes(b"RIFF")
    (prepared / "draft_plan.json").write_text(
        '{"blocks":[{"id":"b1","spoken_text":"старый текст"}]}', encoding="utf-8")

    class _Ctx:
        video_id = "vid"
        cfg = cfg
        repo_root = tmp_path
        warnings = []

        def read(self, name):
            return {"video_id": "vid", "blocks": [
                {"id": "b1", "role": "hook", "spoken_text": "новый текст"}]}

        def warn(self, *a, **k):
            pass

    with pytest.raises(SpeechChangedNewVideo):
        run_step(_Ctx())


def test_paid_skipped_message():
    assert "voice cached" in PAID_SKIPPED_MSG
    assert "avatar prepared" in PAID_SKIPPED_MSG
