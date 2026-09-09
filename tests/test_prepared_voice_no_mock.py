"""Боевая сборка не подменяет prepared-голос mock TTS (QC-10)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.errors import MockTtsForbidden
from src.lib import audio as A
from src.lib.cache import StepCache
from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.jsonio import write_json
from src.lib.storage import build_storage
from src.p2_tts.tts import run_step as p2
from src.p3_speech_opt.optimizer import run_step as p3
from src.pipeline import RunContext


def _ctx(tmp_path, cfg, video_id="redshift_9042"):
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "out").mkdir()
    return RunContext(
        video_id=video_id, cfg=cfg, work_dir=work,
        output_dir=tmp_path / "out", script_path=tmp_path / "s.json",
        cache=StepCache(tmp_path / "cache"),
        costs=CostLedger(video_id=video_id),
        storage=build_storage(cfg),
    )


def _draft(spoken: str) -> dict:
    return {
        "video_id": "redshift_9042",
        "tts_target_sec": 40.0,
        "target_duration_sec": 40.0,
        "blocks": [{
            "id": "b1", "role": "hook",
            "text": spoken, "spoken_text": spoken,
        }],
    }


def _seed_prepared(root, spoken: str) -> None:
    voice_dir = root / "assets" / "voice" / "redshift_9042"
    voice_dir.mkdir(parents=True)
    sr = 48000
    A.save_wav(voice_dir / "voice_final.wav",
               np.zeros(sr, dtype=np.float32), sr)
    write_json(voice_dir / "draft_plan.json", _draft(spoken))
    write_json(voice_dir / "speech_map.json", {
        "video_id": "redshift_9042", "sample_rate": sr,
        "duration_sec": 1.0,
        "loudness": {"integrated_lufs": -14.0, "true_peak_dbtp": -3.0},
        "blocks": [{
            "id": "b1", "role": "hook", "start": 0.0, "end": 1.0,
            "words": [{"word": "этот", "start": 0.0, "end": 1.0}],
        }],
    })


def test_combat_build_reuses_matching_prepared_voice(tmp_path):
    cfg = load_config(overrides=["providers.mode=auto", "heygen.source=prepared"])
    cfg.repo_root = tmp_path
    spoken = "Этот ответ невозможно проверить. Ничем."
    _seed_prepared(tmp_path, spoken)
    ctx = _ctx(tmp_path, cfg)
    write_json(ctx.work_dir / "draft_plan.json", _draft(spoken))
    result = p2(ctx)
    assert result["provider_mode"] == "prepared"
    meta = json.loads((ctx.work_dir / "tts_meta.json").read_text(encoding="utf-8"))
    assert meta["provider_mode"] == "prepared"
    reused = p3(ctx)
    assert reused.get("reused") is True


def test_combat_build_rejects_stale_prepared_voice(tmp_path):
    cfg = load_config(overrides=["providers.mode=auto", "heygen.source=prepared"])
    cfg.repo_root = tmp_path
    _seed_prepared(tmp_path, "Этот ответ невозможно проверить. Вообще ничем.")
    ctx = _ctx(tmp_path, cfg)
    write_json(ctx.work_dir / "draft_plan.json",
               _draft("Этот ответ невозможно проверить. Ничем."))
    with pytest.raises(MockTtsForbidden):
        p2(ctx)


def test_explicit_mock_still_synthesizes(tmp_path):
    cfg = load_config(overrides=["providers.mode=mock"])
    cfg.repo_root = tmp_path
    spoken = "Этот ответ невозможно проверить. Ничем."
    _seed_prepared(tmp_path, spoken)
    ctx = _ctx(tmp_path, cfg)
    write_json(ctx.work_dir / "draft_plan.json", _draft(spoken))
    result = p2(ctx)
    assert result["provider_mode"] == "mock"
