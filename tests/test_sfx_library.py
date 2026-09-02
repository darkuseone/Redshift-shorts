"""Курируемые короткие звуки: приём, теги, выбор по смыслу кадра."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.lib.config import load_config
from src.lib.sfx_library import (
    INTENTS, add_clip, intent_for_role, pick_sfx,
)
from src.p10_audio.audio_build import _plan_sfx


def _tone(path: Path, *, seconds: float = 0.4, freq: int = 1200) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:duration={seconds}",
         "-af", "volume=-6dB", "-ar", "48000", "-ac", "2", str(path)],
        check=True)
    return path


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg.set("paths.assets_dir", str(tmp_path / "assets"))
    return cfg


def test_a_good_clip_is_accepted_and_named(cfg, tmp_path):
    report = add_clip(cfg, source=_tone(tmp_path / "air.wav"),
                      clip_id="whoosh_test", tags=["whoosh", "sharp"],
                      role="whoosh_in", title="тест")
    assert report["warnings"] == []
    assert report["file"] == "whoosh_test.wav"
    assert report["measured"]["duration_sec"] <= 2.0


def test_unknown_tag_is_refused(cfg, tmp_path):
    from src.errors import RedshiftError

    with pytest.raises(RedshiftError, match="не из словаря"):
        add_clip(cfg, source=_tone(tmp_path / "x.wav"), clip_id="x",
                 tags=["trombone"])


def test_picture_in_does_not_pick_the_inaudible_rumble(cfg, tmp_path):
    add_clip(cfg, source=_tone(tmp_path / "air.wav", freq=2000),
             clip_id="whoosh_ok", tags=["whoosh", "sharp"], role="whoosh_in")
    add_clip(cfg, source=_tone(tmp_path / "sub.wav", freq=40),
             clip_id="rumble", tags=["rumble", "sub", "air"])
    picked = pick_sfx(cfg, want=INTENTS["picture_in"], video_id="redshift_0047")
    assert picked.id == "sfx_whoosh_ok"
    assert "rumble" not in picked.tags


def test_old_script_roles_still_resolve():
    assert intent_for_role("whoosh_in") == "picture_in"
    assert intent_for_role("ui_click") == "ui"
    assert intent_for_role("subscribe_ping") == "cta"
    assert intent_for_role("data_beep") == "data"


def test_a_new_picture_gets_a_whoosh(cfg):
    plan = {
        "duration_sec": 12.0,
        "cta_window": [10.0, 12.0],
        "blocks": [{"id": "b1", "sfx": "none"}, {"id": "b2", "sfx": "none"}],
        "slots": [
            {"index": 0, "start": 0.0, "end": 4.0, "kind": "footage", "block_id": "b1",
             "transition_in": "cut"},
            {"index": 1, "start": 4.0, "end": 8.0, "kind": "footage", "block_id": "b2",
             "transition_in": "cut"},
            {"index": 2, "start": 8.0, "end": 12.0, "kind": "avatar", "block_id": "b2",
             "transition_in": "cut"},
        ],
    }
    events = _plan_sfx(plan, cfg)
    intents = [(round(e["t"], 2), e["intent"]) for e in events]
    assert (0.0, "picture_in") in intents
    assert (4.0, "picture_in") in intents
    assert any(i == "cta" for _, i in intents)


def test_a_scripted_hit_replaces_the_whoosh_on_that_picture(cfg):
    """Автор поставил удар на блок — второй вжух сверху не нужен."""
    plan = {
        "duration_sec": 8.0,
        "cta_window": [6.0, 8.0],
        "blocks": [{"id": "b1", "sfx": "hit_impact"}],
        "slots": [
            {"index": 0, "start": 0.0, "end": 6.0, "kind": "footage", "block_id": "b1",
             "transition_in": "cut"},
        ],
    }
    events = _plan_sfx(plan, cfg)
    at_zero = [e for e in events if abs(e["t"]) < 1e-6]
    assert any(e["intent"] == "impact" for e in at_zero)
    assert not any(e["intent"] == "picture_in" for e in at_zero)


def test_fill_still_does_not_synthesise(cfg):
    from src.lib.library_filler import fill_sfx

    result = fill_sfx(cfg)
    assert result["added"] == []
    assert result["curated"] is True
    assert "add-sfx" in result["note"]
