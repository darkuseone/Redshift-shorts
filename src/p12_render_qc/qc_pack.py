"""Плотный QC-пакет для агента: сетка кадров, вырезки звука, метрики микса.

Машинные гейты §11.1 остаются в qc.py. Этот пакет — глаза и уши Cursor:
не 2–3 кадра, а стыки, аватар in/out, safe-zone и хук/середина/финал по звуку.
Vision по этой сетке не вызывается — кредиты бережём.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..lib.ffmpeg import extract_audio_clip, extract_frames_at, probe
from ..lib.jsonio import write_json
from ..lib.logging import get_logger

_log = get_logger("qc_pack")

RUBRIC_PATH = Path("config/qc_agent_rubric.json")


def _clamp(ts: float, duration: float) -> float:
    if duration <= 0.05:
        return 0.0
    return max(0.0, min(float(ts), duration - 0.04))


def pack_timestamps(plan: dict[str, Any], duration: float) -> list[float]:
    """Старт, шаг 3.5 с, каждый стык, аватар in/out, финал, три safe-zone."""
    times: set[float] = {0.04, _clamp(duration - 0.08, duration)}
    step = 3.5
    t = 0.0
    while t < duration:
        times.add(_clamp(t, duration))
        t += step
    for shot in plan.get("shots") or []:
        start = float(shot.get("start") or 0.0)
        end = float(shot.get("end") or (start + float(shot.get("duration") or 0.0)))
        times.add(_clamp(start + 0.04, duration))
        times.add(_clamp(end - 0.04, duration))
        kind = str(shot.get("kind") or "")
        if kind in ("avatar", "split"):
            times.add(_clamp(start + 0.08, duration))
            times.add(_clamp(end - 0.08, duration))
    # Safe-zone: верх кадра (0.15), низ/сабы (0.82), лицо vs сабы на первом аватаре.
    times.add(_clamp(duration * 0.15, duration))
    times.add(_clamp(duration * 0.82, duration))
    avatar = next(
        (s for s in (plan.get("shots") or [])
         if str(s.get("kind") or "") in ("avatar", "split")),
        None,
    )
    if avatar is not None:
        mid = (float(avatar.get("start") or 0.0)
               + float(avatar.get("end") or 0.0)) / 2.0
        times.add(_clamp(mid, duration))
    ordered = sorted({round(x, 3) for x in times if x >= 0.0})
    return ordered


def _audio_windows(duration: float) -> list[tuple[str, float, float]]:
    hook_end = min(3.0, max(1.2, duration * 0.08))
    mid = max(duration / 2.0 - 1.5, hook_end + 0.2)
    finale = max(duration - 3.2, mid + 1.5)
    return [
        ("hook", 0.0, hook_end),
        ("mid", mid, min(mid + 3.0, duration)),
        ("finale", finale, duration),
    ]


def write_scorecard(out_dir: Path, *, video_id: str) -> dict[str, Any]:
    rubric = {}
    path = RUBRIC_PATH
    if path.is_file():
        rubric = json.loads(path.read_text(encoding="utf-8"))
    axes = []
    for axis in rubric.get("axes") or []:
        row = dict(axis)
        row["score"] = None
        row["notes"] = ""
        axes.append(row)
    card = {
        "video_id": video_id,
        "frozen": bool(rubric.get("frozen", False)),
        "release_rule": rubric.get("release_rule"),
        "axes": axes,
        "audio_mix_checks": list(rubric.get("audio_mix_checks") or []),
        "verdict": None,
    }
    write_json(out_dir / "qc_agent_scorecard.json", card)
    return card


def build_qc_pack(ctx, *, video_path: Path, plan: dict[str, Any],
                  mix_path: Path | None, loudness: dict[str, Any],
                  variant: str) -> dict[str, Any]:
    """Сетка кадров + wav-вырезки + ebur128 в output/<id>/qc_pack/."""
    info = probe(video_path)
    duration = float(info.duration_sec or plan.get("duration_sec") or 0.0)
    out_dir = ctx.opath("qc_pack", variant)
    frames_dir = out_dir / "frames"
    audio_dir = out_dir / "audio"
    stamps = pack_timestamps(plan, duration)
    frames = extract_frames_at(video_path, frames_dir, stamps, width=540)
    clips: list[dict[str, Any]] = []
    src_audio = mix_path if mix_path and Path(mix_path).is_file() else video_path
    for name, start, end in _audio_windows(duration):
        dest = audio_dir / f"{name}.wav"
        try:
            extract_audio_clip(src_audio, dest, start_sec=start, duration_sec=max(0.4, end - start))
            clips.append({"name": name, "start": round(start, 3),
                          "end": round(end, 3), "file": str(dest.name)})
        except Exception as exc:  # noqa: BLE001
            _log.warning("вырезка звука QC-пакета не собралась", extra={
                "name": name, "err": str(exc)[:200]})
    metrics = {
        "ebur128_lufs": loudness.get("mix_lufs"),
        "true_peak_dbtp": loudness.get("true_peak_dbtp"),
        "music_lufs": loudness.get("music_lufs"),
        "trailing_silence_ms": loudness.get("trailing_silence_ms"),
        "duration_sec": duration,
    }
    write_json(out_dir / "audio_metrics.json", metrics)
    write_scorecard(out_dir, video_id=str(plan.get("video_id") or ctx.video_id))
    manifest = {
        "variant": variant,
        "video_id": plan.get("video_id"),
        "frame_count": len(frames),
        "timestamps_sec": stamps,
        "frames": [p.name for p in frames],
        "audio_clips": clips,
        "metrics": metrics,
        "safe_zone_notes": [
            "frame near 15% — верх кадра",
            "frame near 82% — низ / субтитры",
            "avatar mid — лицо vs сабы",
        ],
    }
    write_json(out_dir / "manifest.json", manifest)
    _log.info("QC-пакет собран", extra={
        "variant": variant, "frames": len(frames), "clips": len(clips)})
    return manifest
