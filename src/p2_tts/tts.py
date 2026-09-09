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

import re
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from ..errors import MockTtsForbidden
from ..lib.audio import SAMPLE_RATE, crossfade_concat, load_wav, save_wav
from ..lib.jsonio import read_json_or
from ..lib.logging import get_logger
from ..lib.providers.tts import TTSResult, build_tts_provider

_log = get_logger("p2")

# Допустимое отклонение фактической длины от заказанной, при котором
# корректирующая переозвучка не нужна.
LENGTH_TOLERANCE = 0.12
BLOCK_GAP_SEC = 0.22          # пауза между блоками; P3 подрежет её до 80–120 мс
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _spoken_key(blocks: list[dict[str, Any]]) -> tuple[tuple[str, str], ...]:
    """Нормализованная речь блоков — сравнение сценария с prepared-голосом."""
    out: list[tuple[str, str]] = []
    for block in blocks:
        text = str(block.get("spoken_text") or block.get("text") or "")
        words = " ".join(_WORD_RE.findall(text.lower()))
        out.append((str(block.get("id") or ""), words))
    return tuple(out)


def prepared_voice_dir(ctx) -> Path | None:
    path = Path(ctx.repo_root) / "assets" / "voice" / ctx.video_id
    if (path / "voice_final.wav").is_file():
        return path
    return None


def combat_voice_lock(ctx) -> bool:
    """Боевая сборка: не mock CLI, и есть prepared-аватар или prepared-голос."""
    if str(ctx.cfg.get("providers.mode", "auto")).lower() == "mock":
        return False
    heygen = str(ctx.cfg.get("heygen.source", "auto")).lower()
    return heygen == "prepared" or prepared_voice_dir(ctx) is not None


def adopt_prepared_voice(ctx, prepared: Path, draft: dict[str, Any]) -> dict[str, Any]:
    """Скопировать кэш голоса в work/ и не звать mock TTS."""
    speech_map = read_json_or(prepared / "speech_map.json", {}) or {}
    voice_src = prepared / "voice_final.wav"
    shutil.copy2(voice_src, ctx.wpath("voice_final.wav"))
    shutil.copy2(voice_src, ctx.wpath("voice_raw.wav"))
    if (prepared / "speech_map.json").is_file():
        shutil.copy2(prepared / "speech_map.json", ctx.wpath("speech_map.json"))
    sm_blocks = {str(b.get("id")): b for b in speech_map.get("blocks") or []}
    blocks_meta: list[dict[str, Any]] = []
    for block in draft["blocks"]:
        sm_block = sm_blocks.get(str(block["id"]), {})
        words = list(sm_block.get("words") or [])
        spoken = str(block.get("spoken_text") or "")
        blocks_meta.append({
            "id": block["id"],
            "role": block.get("role"),
            "start": sm_block.get("start", 0.0),
            "end": sm_block.get("end", 0.0),
            "spoken_text": spoken,
            "chars": len(spoken),
            "words": words,
        })
    sr = int(speech_map.get("sample_rate")
             or ctx.cfg.get("elevenlabs.sample_rate", SAMPLE_RATE))
    meta = {
        "video_id": draft["video_id"],
        "sample_rate": sr,
        "duration_sec": float(speech_map.get("duration_sec") or 0.0),
        "desired_sec": float(draft.get("tts_target_sec") or 0.0),
        "speed": 1.0,
        "length_correction": None,
        "model": "prepared",
        "provider_mode": "prepared",
        "voice_id": "prepared",
        "block_gap_sec": BLOCK_GAP_SEC,
        "has_provider_word_timings": bool(blocks_meta and blocks_meta[0]["words"]),
        "blocks": blocks_meta,
        "total_chars": sum(b["chars"] for b in blocks_meta),
        "prepared_from": str(prepared),
    }
    ctx.write("tts_meta.json", meta)
    ctx.warn("озвучка взята из prepared-кэша: mock TTS не вызывался", step="P2")
    _log.info("prepared-голос подставлен вместо mock TTS", extra={
        "duration_sec": meta["duration_sec"], "from": str(prepared),
    })
    return {"duration_sec": meta["duration_sec"], "provider_mode": "prepared",
            "corrected": False}


def _synthesize_block(provider, text: str, out_path: Path, *, speed: float) -> TTSResult:
    return provider.synthesize(text, out_path, speed=speed)


def run_step(ctx) -> dict[str, Any]:
    draft = ctx.read("draft_plan.json")
    provider = build_tts_provider(ctx.cfg, ctx.costs)
    if provider.is_mock and combat_voice_lock(ctx):
        prepared = prepared_voice_dir(ctx)
        prepared_draft = (
            read_json_or(prepared / "draft_plan.json", {}) if prepared else {}
        )
        current = _spoken_key(draft.get("blocks") or [])
        cached = _spoken_key((prepared_draft or {}).get("blocks") or [])
        if prepared is None or current != cached:
            raise MockTtsForbidden(
                "боевая сборка: mock TTS запрещён — prepared-голос отсутствует "
                "или не совпадает со сценарием (иначе QC-10 и липсинк)",
                video_id=ctx.video_id,
                have_prepared=bool(prepared),
                speech_match=bool(prepared) and current == cached,
            )
        return adopt_prepared_voice(ctx, prepared, draft)

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
