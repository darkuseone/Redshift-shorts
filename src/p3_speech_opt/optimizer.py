"""P3: ``voice_raw.wav`` → ``voice_final.wav`` + ``speech_map.json``.

Реализует §4.2 «Обработка речи»:

1. Паузы длиннее 150 мс режутся до 80–120 мс. Полное схлопывание запрещено —
   без остатка паузы речь «задыхается» и на стыках появляются артефакты.
2. Вдохи, щелчки и цоканье TTS вырезаются: внутри паузы сохраняется не начало
   (где обычно вдох), а **самое тихое окно** нужной длины, приглушённое на 6 дБ.
   Так остаётся комнатный тон, но исчезает вдох.
3. Целевая длина достигается подбором длительности паузы внутри разрешённого
   коридора 80–120 мс, а не произвольным резом.
4. Если после оптимизации ролик короче 35 сек — возвращается ``SCRIPT_TOO_SHORT``
   с расчётом недостающих секунд (§4.2.4), а не короткий ролик.

Побочный продукт — карта времени ``speech_map.json``: она позволяет точно
перенести тайминги слов из сырого таймкода в финальный (нужно P4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..errors import DurationOutOfRange, ScriptTooShort
from ..lib.audio import (
    apply_gain_db, crossfade_concat, limit_true_peak, load_wav, measure_loudness_buffer,
    measure_loudness_file, normalize_to_lufs, rms_envelope, save_wav, trailing_silence_ms,
)
from ..lib.logging import get_logger

_log = get_logger("p3")

LEAD_SILENCE_SEC = 0.10       # сколько тишины оставить перед первым словом
TAIL_SILENCE_SEC = 0.15       # QC-13: в конце ≤ 300 мс
BREATH_ATTENUATION_DB = -6.0


@dataclass
class Gap:
    start: float
    end: float
    kind: str          # lead | pause | tail

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Segment:
    src_start: float
    src_end: float
    dst_start: float
    attenuate_db: float = 0.0

    @property
    def duration(self) -> float:
        return self.src_end - self.src_start

    @property
    def dst_end(self) -> float:
        return self.dst_start + self.duration


def collect_gaps(words: list[dict[str, Any]], total_sec: float) -> list[Gap]:
    """Паузы между словами плюс лид и хвост."""
    gaps: list[Gap] = []
    if not words:
        return [Gap(0.0, total_sec, "tail")]
    first = float(words[0]["start"])
    if first > 0.005:
        gaps.append(Gap(0.0, first, "lead"))
    for prev, nxt in zip(words, words[1:]):
        start, end = float(prev["end"]), float(nxt["start"])
        if end - start > 0.005:
            gaps.append(Gap(start, end, "pause"))
    last = float(words[-1]["end"])
    if total_sec - last > 0.005:
        gaps.append(Gap(last, total_sec, "tail"))
    return gaps


def pause_target_sec(gap_sec: float, pause_ms_range: tuple[float, float], ratio: float) -> float:
    """Целевая длина паузы: длинные паузы оставляют чуть больше воздуха."""
    lo, hi = pause_ms_range
    base = lo + (hi - lo) * ratio
    # Пауза длиной 1 с ощущается как смысловая — ей достаём до верхней границы.
    stretch = min(1.0, max(0.0, (gap_sec - 0.15) / 0.85))
    target_ms = base + (hi - base) * stretch * 0.5
    return min(max(target_ms, lo), hi) / 1000.0


def _quietest_window(env: np.ndarray, sr: int, start: float, end: float,
                     length: float) -> float:
    """Начало самого тихого окна длиной ``length`` внутри [start, end]."""
    i0, i1 = int(start * sr), int(end * sr)
    win = max(1, int(length * sr))
    if i1 - i0 <= win:
        return start
    region = env[i0:i1]
    cum = np.concatenate(([0.0], np.cumsum(region)))
    n = len(region) - win
    sums = cum[win:win + n + 1] - cum[:n + 1]
    return start + int(np.argmin(sums)) / sr


def plan_segments(audio: np.ndarray, sr: int, words: list[dict[str, Any]],
                  *, threshold_ms: float, pause_ms_range: tuple[float, float],
                  ratio: float, env: np.ndarray | None = None,
                  ) -> tuple[list[Segment], list[dict[str, Any]]]:
    """Разложить дорожку на сохраняемые сегменты, вырезав лишние паузы.

    ``env`` (огибающая RMS) можно передать снаружи: подбор длины паузы гоняет
    планировщик несколько раз по одной и той же дорожке, и пересчитывать
    огибающую каждый раз — чистая трата времени раннера.
    """
    total = len(audio) / sr
    if env is None:
        env = rms_envelope(audio, sr, window_ms=10.0)
    gaps = collect_gaps(words, total)
    threshold = threshold_ms / 1000.0

    segments: list[Segment] = []
    cuts: list[dict[str, Any]] = []
    cursor_src = 0.0
    cursor_dst = 0.0

    for gap in gaps:
        if gap.kind == "lead":
            keep = min(LEAD_SILENCE_SEC, gap.duration)
            keep_start = max(gap.end - keep, gap.start)
            if keep_start > cursor_src:
                cuts.append({"kind": "lead", "src_start": round(cursor_src, 4),
                             "src_end": round(keep_start, 4),
                             "removed_sec": round(keep_start - cursor_src, 4)})
            cursor_src = keep_start
            continue

        if gap.kind == "tail":
            keep = min(TAIL_SILENCE_SEC, gap.duration)
            seg_end = gap.start + keep
            if seg_end > cursor_src:
                segments.append(Segment(cursor_src, seg_end, cursor_dst))
                cursor_dst += seg_end - cursor_src
            if gap.end > seg_end:
                cuts.append({"kind": "tail", "src_start": round(seg_end, 4),
                             "src_end": round(gap.end, 4),
                             "removed_sec": round(gap.end - seg_end, 4)})
            cursor_src = gap.end
            continue

        if gap.duration <= threshold:
            continue      # короткая пауза — не трогаем, она держит ритм

        target = pause_target_sec(gap.duration, pause_ms_range, ratio)
        target = min(target, gap.duration)
        keep_start = _quietest_window(env, sr, gap.start, gap.end, target)
        keep_end = min(keep_start + target, gap.end)

        # Речь до паузы.
        segments.append(Segment(cursor_src, gap.start, cursor_dst))
        cursor_dst += gap.start - cursor_src
        # Сохранённый кусочек тишины — приглушённый, чтобы убрать остатки вдоха.
        segments.append(Segment(keep_start, keep_end, cursor_dst, BREATH_ATTENUATION_DB))
        cursor_dst += keep_end - keep_start

        removed = gap.duration - (keep_end - keep_start)
        cuts.append({
            "kind": "breath" if keep_start > gap.start + 0.02 else "pause",
            "src_start": round(gap.start, 4), "src_end": round(gap.end, 4),
            "kept_sec": round(keep_end - keep_start, 4), "removed_sec": round(removed, 4),
        })
        cursor_src = gap.end

    if cursor_src < total:
        segments.append(Segment(cursor_src, total, cursor_dst))
    return segments, cuts


def render_segments(audio: np.ndarray, sr: int, segments: list[Segment]) -> np.ndarray:
    chunks: list[np.ndarray] = []
    for seg in segments:
        i0, i1 = int(round(seg.src_start * sr)), int(round(seg.src_end * sr))
        piece = audio[max(0, i0):max(0, i1)]
        if seg.attenuate_db:
            piece = apply_gain_db(piece, seg.attenuate_db)
        if len(piece):
            chunks.append(piece)
    return crossfade_concat(chunks, sr, fade_ms=6.0)


def remap_time(t: float, segments: list[Segment]) -> float:
    """Время из сырого таймкода в финальный."""
    for seg in segments:
        if seg.src_start - 1e-6 <= t <= seg.src_end + 1e-6:
            return seg.dst_start + (t - seg.src_start)
    # Точка попала в вырезанный кусок — прижимаем к ближайшей границе.
    best = min(segments, key=lambda s: min(abs(s.src_start - t), abs(s.src_end - t)))
    return best.dst_start if t < best.src_start else best.dst_end


def _total_after(audio_len_sec: float, cuts: list[dict[str, Any]]) -> float:
    return audio_len_sec - sum(c["removed_sec"] for c in cuts)


def run_step(ctx) -> dict[str, Any]:
    meta = ctx.read("tts_meta.json")
    sr = int(meta["sample_rate"])
    audio, file_sr = load_wav(ctx.work_dir / "voice_raw.wav")
    if file_sr != sr:  # pragma: no cover
        sr = file_sr
    audio = audio[:, 0] if audio.ndim == 2 else audio

    words: list[dict[str, Any]] = []
    for block in meta["blocks"]:
        words.extend(block["words"])
    words.sort(key=lambda w: w["start"])

    threshold_ms = float(ctx.cfg.get("speech.pause_threshold_ms", 150))
    pause_range = tuple(ctx.cfg.get("speech.pause_target_ms", [80, 120]))
    lo_dur, hi_dur = ctx.cfg.get("limits.duration_sec", [35, 70])
    target = float(ctx.read("draft_plan.json")["target_duration_sec"])
    target = min(max(target, lo_dur), hi_dur)
    source_sec = len(audio) / sr

    # Подбираем длину паузы внутри разрешённого коридора так, чтобы попасть
    # ближе к целевому хронометражу. ratio=0 → 80 мс, ratio=1 → 120 мс.
    envelope = rms_envelope(audio, sr, window_ms=10.0)
    best: tuple[float, list[Segment], list[dict[str, Any]], float] | None = None
    for ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
        segs, cuts = plan_segments(audio, sr, words, threshold_ms=threshold_ms,
                                   pause_ms_range=pause_range, ratio=ratio, env=envelope)
        duration = _total_after(source_sec, cuts)
        score = abs(duration - target)
        if best is None or score < best[0]:
            best = (score, segs, cuts, ratio)
    assert best is not None
    _score, segments, cuts, ratio = best

    voice = render_segments(audio, sr, segments)
    final_sec = len(voice) / sr

    if final_sec < lo_dur:
        deficit = round(lo_dur - final_sec, 2)
        raise ScriptTooShort(
            f"после оптимизации речи ролик {final_sec:.1f} сек — короче минимума {lo_dur} сек. "
            f"Добавьте примерно {deficit} сек текста (~{math.ceil(deficit * 2.3)} слов)",
            final_sec=round(final_sec, 2), min_sec=lo_dur, deficit_sec=deficit,
            deficit_words=math.ceil(deficit * 2.3),
        )
    if final_sec > hi_dur:
        raise DurationOutOfRange(
            f"после оптимизации речи ролик {final_sec:.1f} сек — длиннее максимума {hi_dur} сек. "
            f"Паузы уже срезаны до минимума: сократите текст примерно на "
            f"{round(final_sec - hi_dur, 1)} сек",
            final_sec=round(final_sec, 2), max_sec=hi_dur,
        )

    # Громкость голосового слоя: −14 LUFS, True Peak ≤ −1 dBTP (§4.4).
    target_lufs = float(ctx.cfg.get("audio.voice_lufs", -14))
    tp_max = float(ctx.cfg.get("audio.true_peak_max", -1))
    measured_before = measure_loudness_buffer(voice, sr).integrated_lufs
    voice, gain_db = normalize_to_lufs(voice, target_lufs, sr, measured=measured_before)
    voice = limit_true_peak(voice, tp_max)
    save_wav(ctx.wpath("voice_final.wav"), voice, sr)
    final_loudness = measure_loudness_file(ctx.work_dir / "voice_final.wav")

    # Перенос таймингов и границ блоков в новый таймкод.
    blocks_out: list[dict[str, Any]] = []
    for block in meta["blocks"]:
        mapped_words = [
            {"word": w["word"],
             "start": round(remap_time(float(w["start"]), segments), 4),
             "end": round(remap_time(float(w["end"]), segments), 4)}
            for w in block["words"]
        ]
        blocks_out.append({
            "id": block["id"],
            "role": block["role"],
            "start": round(mapped_words[0]["start"] if mapped_words
                           else remap_time(float(block["start"]), segments), 4),
            "end": round(mapped_words[-1]["end"] if mapped_words
                         else remap_time(float(block["end"]), segments), 4),
            "words": mapped_words,
        })

    speech_map = {
        "video_id": meta["video_id"],
        "sample_rate": sr,
        "source_duration_sec": round(source_sec, 3),
        "duration_sec": round(final_sec, 3),
        "removed_sec": round(source_sec - final_sec, 3),
        "target_duration_sec": target,
        "pause_threshold_ms": threshold_ms,
        "pause_target_ms_range": list(pause_range),
        "pause_ratio": ratio,
        "gain_applied_db": round(gain_db, 2),
        "loudness": {
            "integrated_lufs": round(final_loudness.integrated_lufs, 2),
            "true_peak_dbtp": round(final_loudness.true_peak_dbtp, 2),
            "trailing_silence_ms": round(trailing_silence_ms(voice, sr), 1),
        },
        "cuts": cuts,
        "segments": [
            {"src_start": round(s.src_start, 4), "src_end": round(s.src_end, 4),
             "dst_start": round(s.dst_start, 4), "dst_end": round(s.dst_end, 4),
             "attenuate_db": s.attenuate_db}
            for s in segments
        ],
        "blocks": blocks_out,
        "provider_mode": meta.get("provider_mode", "mock"),
    }
    ctx.write("speech_map.json", speech_map)

    breaths = sum(1 for c in cuts if c["kind"] == "breath")
    _log.info("речь оптимизирована", extra={
        "source_sec": round(source_sec, 2), "final_sec": round(final_sec, 2),
        "removed_sec": round(source_sec - final_sec, 2),
        "pauses_cut": sum(1 for c in cuts if c["kind"] in ("pause", "breath")),
        "breaths_removed": breaths,
        "lufs": speech_map["loudness"]["integrated_lufs"],
        "tail_ms": speech_map["loudness"]["trailing_silence_ms"],
    })
    return {"duration_sec": round(final_sec, 2), "removed_sec": round(source_sec - final_sec, 2),
            "lufs": speech_map["loudness"]["integrated_lufs"]}
