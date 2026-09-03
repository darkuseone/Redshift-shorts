"""P2: ``draft_plan.json`` → ``voice_raw.wav`` + ``tts_meta.json``.

Озвучка идёт **поблочно**: так границы блоков известны точно (а не угадываются
по паузам), можно переозвучить один блок, не трогая остальные, и посегментная
генерация аватара в P6 получает готовые интервалы фраз.

§4.2.4 требует запаса длины +18…25 %. Запас — не украшение: если после срезки
пауз ролик окажется короче 35 сек, система обязана вернуть ``SCRIPT_TOO_SHORT``,
а не выдать короткий ролик. Поэтому P2 не просто «просит подлиннее», а
контролирует фактическую длину и при необходимости делает одну корректирующую
переозвучку с пересчитанной скоростью.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..lib.audio import SAMPLE_RATE, crossfade_concat, load_wav, save_wav
from ..lib.logging import get_logger
from ..lib.providers.tts import TTSResult, build_tts_provider

_log = get_logger("p2")

# Допустимое отклонение фактической длины от заказанной, при котором
# корректирующая переозвучка не нужна.
LENGTH_TOLERANCE = 0.12
BLOCK_GAP_SEC = 0.22          # пауза между блоками; P3 подрежет её до 80–120 мс


def _synthesize_block(provider, text: str, out_path: Path, *, speed: float) -> TTSResult:
    return provider.synthesize(text, out_path, speed=speed)


def run_step(ctx) -> dict[str, Any]:
    draft = ctx.read("draft_plan.json")
    provider = build_tts_provider(ctx.cfg, ctx.costs)
    sr = int(ctx.cfg.get("elevenlabs.sample_rate", SAMPLE_RATE))
    # Темп речи ведущего. Поднять один только множитель скорости недостаточно:
    # коррекция длины тут же замедлит озвучку обратно, лишь бы попасть в
    # плановую длительность. Поэтому вместе со скоростью сдвигается и сама цель
    # — на ту же долю. Речь становится быстрее, а ролик соразмерно короче.
    pace = max(0.7, min(1.4, float(ctx.cfg.get("elevenlabs.pace", 1.0))))
    desired_sec = float(draft["tts_target_sec"]) / pace
    correct_length = bool(ctx.cfg.get("elevenlabs.length_correction", True))

    blocks_dir = ctx.wpath("tts_blocks", ".keep").parent

    def synth_all(speed: float) -> tuple[list[TTSResult], float]:
        results: list[TTSResult] = []
        total = 0.0
        for block in draft["blocks"]:
            out = blocks_dir / f"{block['id']}.wav"
            res = _synthesize_block(provider, block["spoken_text"], out, speed=speed)
            results.append(res)
            total += res.duration_sec
        total += BLOCK_GAP_SEC * max(0, len(draft["blocks"]) - 1)
        return results, total

    speed = pace
    results, raw_total = synth_all(speed)
    correction: dict[str, Any] | None = None

    if correct_length and raw_total > 0 and abs(raw_total - desired_sec) / desired_sec > LENGTH_TOLERANCE:
        # Скорость обратна длительности: чтобы удлинить, замедляем.
        # Потолок коррекции тоже едет за темпом: при pace=1.1 прежний предел
        # 1.35 срезал бы саму прибавку, ради которой темп и задан.
        new_speed = max(0.65 * pace, min(1.35 * pace, speed * raw_total / desired_sec))
        _log.info("корректирующая переозвучка ради запаса длины",
                  extra={"raw_sec": round(raw_total, 2), "desired_sec": round(desired_sec, 2),
                         "speed": round(new_speed, 3)})
        corrected, corrected_total = synth_all(new_speed)
        correction = {"from_sec": round(raw_total, 3), "to_sec": round(corrected_total, 3),
                      "speed": round(new_speed, 3)}
        results, raw_total, speed = corrected, corrected_total, new_speed

    # Склейка блоков в одну дорожку с межблочными паузами.
    segments: list[np.ndarray] = []
    block_meta: list[dict[str, Any]] = []
    cursor = 0.0
    gap = np.zeros(int(BLOCK_GAP_SEC * sr), dtype=np.float32)

    for idx, (block, res) in enumerate(zip(draft["blocks"], results)):
        data, block_sr = load_wav(res.audio_path)
        if block_sr != sr:  # pragma: no cover — провайдер обязан отдавать нужную частоту
            raise ValueError(f"частота блока {block['id']} = {block_sr}, ожидалась {sr}")
        mono = data[:, 0] if data.ndim == 2 else data
        segments.append(mono)
        block_meta.append({
            "id": block["id"],
            "role": block["role"],
            "start": round(cursor, 4),
            "end": round(cursor + res.duration_sec, 4),
            "spoken_text": block["spoken_text"],
            "chars": res.chars,
            "words": [
                {"word": w.word, "start": round(w.start + cursor, 4), "end": round(w.end + cursor, 4)}
                for w in res.words
            ],
        })
        cursor += res.duration_sec
        if idx < len(results) - 1:
            segments.append(gap)
            cursor += BLOCK_GAP_SEC

    voice = np.concatenate(segments) if segments else np.zeros(sr, dtype=np.float32)
    save_wav(ctx.wpath("voice_raw.wav"), voice, sr)

    meta = {
        "video_id": draft["video_id"],
        "sample_rate": sr,
        "duration_sec": round(len(voice) / sr, 3),
        "desired_sec": round(desired_sec, 3),
        "speed": round(speed, 3),
        "length_correction": correction,
        "model": results[0].model if results else "",
        "provider_mode": results[0].provider_mode if results else "mock",
        "voice_id": results[0].voice_id if results else "",
        "block_gap_sec": BLOCK_GAP_SEC,
        "has_provider_word_timings": bool(results and results[0].words),
        "blocks": block_meta,
        "total_chars": sum(r.chars for r in results),
    }
    ctx.write("tts_meta.json", meta)

    if meta["provider_mode"] == "mock":
        ctx.warn("озвучка синтезирована в mock-режиме: голос не пригоден для публикации",
                 step="P2")

    _log.info("озвучка готова", extra={
        "duration_sec": meta["duration_sec"], "desired_sec": meta["desired_sec"],
        "mode": meta["provider_mode"], "model": meta["model"],
        "words": sum(len(b["words"]) for b in block_meta),
    })
    return {"duration_sec": meta["duration_sec"], "provider_mode": meta["provider_mode"],
            "corrected": bool(correction)}
