"""QC-пакет агента: сетка кадров, не 2–3 скрина."""

from __future__ import annotations

from src.p12_render_qc.qc_pack import pack_timestamps, write_scorecard


def test_pack_is_dense_not_two_frames():
    plan = {
        "duration_sec": 40.0,
        "shots": [
            {"kind": "footage", "start": 0.0, "end": 4.0},
            {"kind": "avatar", "start": 4.0, "end": 10.0},
            {"kind": "footage", "start": 10.0, "end": 40.0},
        ],
    }
    stamps = pack_timestamps(plan, 40.0)
    assert len(stamps) >= 12
    assert stamps[0] < 0.2
    assert stamps[-1] > 39.0
    # стык аватара
    assert any(abs(t - 4.0) < 0.15 for t in stamps)
    assert any(abs(t - 10.0) < 0.15 for t in stamps)


def test_scorecard_axes_not_frozen(tmp_path, monkeypatch):
    card = write_scorecard(tmp_path, video_id="x")
    ids = [a["id"] for a in card["axes"]]
    assert "hook" in ids
    assert "audio_mix" in ids
    assert "scam_risk" in ids
    assert card["frozen"] is False
    assert (tmp_path / "qc_agent_scorecard.json").is_file()
