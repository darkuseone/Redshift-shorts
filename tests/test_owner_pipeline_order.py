"""Заказчик: порядок пайплайна, Никита, Grok, 8/10, аватар только на присутствии."""

from __future__ import annotations

from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.duration import duration_limits
from src.lib.providers.tts import pick_voice, voice_label
from src.lib.providers.vision import MockVision, build_vision_provider
from src.p5_replan.replanner import (
    Slot, _avatar_runs, _raise_appearance_count,
)
from src.p6_avatar.avatar import merge_segments


def test_duration_limits_preferred_and_hard():
    cfg = load_config()
    lo, preferred, hard = duration_limits(cfg)
    assert lo == 35
    assert preferred == 75
    assert hard == 90


def test_brandbook_appearances_are_three_to_seven():
    cfg = load_config()
    lo, hi = cfg.brand("avatar.appearances")
    assert lo == 3 and hi == 7


def test_voice_is_nikita_clone():
    cfg = load_config()
    vid = pick_voice(cfg, "redshift_0050")
    assert vid in cfg.get("elevenlabs.voice_pool")
    assert voice_label(cfg, vid) in ("Никита 1", "Никита 2")
    assert pick_voice(cfg, "redshift_0050") == vid


def test_gemini_key_does_not_become_vision_judge(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API", raising=False)
    monkeypatch.delenv("TOKENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg = load_config()
    cfg.set("providers.mode", "auto")
    primary = build_vision_provider(cfg, CostLedger(video_id="t"), role="primary")
    qc = build_vision_provider(cfg, CostLedger(video_id="t"), role="qc")
    assert isinstance(primary, MockVision)
    assert "gemini" not in type(primary).__name__.lower()
    assert "gemini" not in type(qc).__name__.lower()


def test_merge_segments_skips_footage_off_avatar():
    slots = [
        {"index": 0, "start": 0.0, "end": 3.0, "kind": "footage",
         "block_id": "b0", "mode": "C"},
        {"index": 1, "start": 3.0, "end": 7.0, "kind": "avatar",
         "block_id": "b1", "mode": "A"},
        {"index": 2, "start": 7.0, "end": 10.0, "kind": "footage",
         "block_id": "b2", "mode": "C"},
        {"index": 3, "start": 10.0, "end": 14.0, "kind": "split",
         "block_id": "b3", "mode": "B"},
    ]
    merged = merge_segments(slots)
    assert [s["kind"] for s in merged] == ["avatar", "split"]
    assert merged[0]["start"] == 3.0 and merged[0]["end"] == 7.0
    total = sum(s["end"] - s["start"] for s in merged)
    assert total == 8.0


def _slot(index, start, end, kind="footage", block="b1", mode="C"):
    return Slot(index=index, start=start, end=end, kind=kind, block_id=block,
                role="develop", mode=mode)


def test_appearance_count_is_raised_to_three():
    slots = [
        _slot(0, 0, 4, kind="avatar", block="b1", mode="A"),
        _slot(1, 4, 8, block="b2"),
        _slot(2, 8, 12, block="b3"),
        _slot(3, 12, 16, block="b4"),
        _slot(4, 16, 20, block="b5"),
    ]
    blocks = [{"id": f"b{i}", "role": "develop"} for i in range(1, 6)]
    notes: list[str] = []
    _raise_appearance_count(slots, blocks, 20.0, 0.60, 3.0, 12.0, 3, 7, notes)
    assert len(_avatar_runs(slots)) >= 3
