"""P10: ``cut_plan.json`` + ``voice_final.wav`` → ``sfx_map.json``, ``music_bed.wav``, ``mix.wav``.

§4.4 «Звук». Уровни не «на слух», а измеряются:

* голос −14 LUFS, True Peak ≤ −1 dBTP;
* музыкальная подложка −30…−34 LUFS — «на грани слышимости»: она заполняет
  тишину и держит напряжение, но не конкурирует с голосом;
* ducking −6…−9 dB под речью;
* SFX по смыслу, не на каждый стык, плотность ≤ 1 раза в 2 сек;
* финальный микс −14 ±1 LUFS.

SFX берутся **только** из библиотеки (§4.4.3–4): после её заполнения до 20
файлов генерация заблокирована, и повторная генерация уже имеющегося звука
считается ошибкой процесса. Если нужной роли в библиотеке нет, шаг не выдумывает
звук, а честно фиксирует пропуск.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..lib import audio as A
from ..lib.logging import get_logger
from ..lib.manifest import open_library

_log = get_logger("p10")

# Обязательные точки SFX (§4.4.2)
MANDATORY_SFX = {
    "avatar_in": "whoosh_in",
    "avatar_out": "whoosh_out",
    "fullscreen_text": "reveal",
    "plaque": "pop",
    "meme": "meme_stinger",
    "cta": "subscribe_ping",
}
AVATAR_KINDS = ("avatar", "split")


def _plan_sfx(plan: dict[str, Any], cfg) -> list[dict[str, Any]]:
    """Расставить SFX по смыслу, соблюдая плотность ≤ 1 / 2 сек."""
    slots = plan["slots"]
    duration = float(plan["duration_sec"])
    min_gap = float(cfg.get("limits.sfx_min_gap_sec", 2.0))
    events: list[dict[str, Any]] = []

    for index, slot in enumerate(slots):
        prev = slots[index - 1] if index else None
        kind = slot["kind"]

        if kind == "fullscreen_text":
            events.append({"t": slot["start"], "role": MANDATORY_SFX["fullscreen_text"],
                           "why": "появление full-screen text (§5.2)", "priority": 1})
        elif kind == "meme":
            events.append({"t": slot["start"], "role": MANDATORY_SFX["meme"],
                           "why": "мем-вставка (§5.8)", "priority": 1})
        elif kind in AVATAR_KINDS and (prev is None or prev["kind"] not in AVATAR_KINDS):
            events.append({"t": slot["start"], "role": MANDATORY_SFX["avatar_in"],
                           "why": "вход аватара (§4.4.2)", "priority": 1})
        elif prev is not None and prev["kind"] in AVATAR_KINDS and kind not in AVATAR_KINDS:
            events.append({"t": slot["start"], "role": MANDATORY_SFX["avatar_out"],
                           "why": "выход аватара (§4.4.2)", "priority": 1})

        if slot.get("transition_in") == "dynamic":
            # §4.3: каждый динамический переход обязан сопровождаться SFX.
            events.append({"t": slot["start"], "role": "swipe",
                           "why": "динамический переход обязан звучать (§4.3)",
                           "priority": 1})

    # Пожелания сценария по блокам — приоритет ниже обязательных точек.
    for block in plan.get("blocks", []):
        role = block.get("sfx")
        if not role or role == "none":
            continue
        block_slots = [s for s in slots if s["block_id"] == block["id"]]
        if block_slots:
            events.append({"t": block_slots[0]["start"], "role": role,
                           "why": f"указано в сценарии для блока {block['id']}",
                           "priority": 2})

    cta_start = float(plan.get("cta_window", [duration - 2, duration])[0])
    events.append({"t": cta_start, "role": MANDATORY_SFX["cta"],
                   "why": "кнопка подписки (§6, QC-16)", "priority": 1})

    events.sort(key=lambda e: (e["t"], e["priority"]))
    placed: list[dict[str, Any]] = []
    for event in events:
        if placed and event["t"] - placed[-1]["t"] < min_gap:
            # Плотность §4.4.1: обязательную точку пропускаем, только если рядом
            # уже стоит другая обязательная.
            if event["priority"] > placed[-1]["priority"]:
                continue
            if event["priority"] == placed[-1]["priority"] and event["t"] - placed[-1]["t"] < 0.35:
                continue
            if event["t"] - placed[-1]["t"] < min_gap * 0.5:
                continue
        placed.append(event)
    return placed


def run_step(ctx) -> dict[str, Any]:
    plan = ctx.read("cut_plan.json")
    cfg = ctx.cfg
    sr = int(cfg.get("audio.sample_rate", A.SAMPLE_RATE))

    voice, voice_sr = A.load_wav(ctx.work_dir / "voice_final.wav")
    if voice_sr != sr:
        voice = A.resample(voice, voice_sr, sr)
    voice_mono = A.to_mono(voice)
    duration = float(plan["duration_sec"])
    length = int(round(duration * sr))
    voice_stereo = A.to_stereo(voice)[:length]
    if len(voice_stereo) < length:
        voice_stereo = np.pad(voice_stereo, ((0, length - len(voice_stereo)), (0, 0)))
    # BS.1770 суммирует мощность каналов, поэтому дублирование моно в стерео
    # даёт +3 LU: голос, нормализованный в P3 до −14 LUFS как моно, в стерео
    # измеряется как −11. Приводим слой к целевому уровню уже в стерео.
    voice_target = float(cfg.get("audio.voice_lufs", -14))
    voice_stereo, _voice_gain = A.normalize_to_lufs(
        voice_stereo, voice_target, sr,
        measured=A.measure_loudness_buffer(voice_stereo, sr).integrated_lufs)

    # --- SFX из библиотеки (§14.1) ---------------------------------------
    sfx_lib = open_library(cfg, "sfx")
    events = _plan_sfx(plan, cfg)
    sfx_peak_lo, sfx_peak_hi = cfg.get("audio.sfx_peak_dbfs", [-16, -12])
    sfx_bus = np.zeros((length, 2), dtype=np.float32)
    placed: list[dict[str, Any]] = []
    missing_roles: list[str] = []

    for event in events:
        record = sfx_lib.by_role(event["role"])
        if record is None:
            missing_roles.append(event["role"])
            placed.append({**event, "status": "missing_in_library"})
            continue
        path = sfx_lib.file_path(record)
        if not path.exists():
            missing_roles.append(event["role"])
            placed.append({**event, "status": "file_missing", "file": str(path)})
            continue
        clip, clip_sr = A.load_audio_any(path, sr)
        if clip_sr != sr:
            clip = A.resample(clip, clip_sr, sr)
        clip = A.normalize_peak(clip, float(sfx_peak_hi))
        A.place(sfx_bus, clip, float(event["t"]), sr)
        sfx_lib.mark_used(record.id, plan["video_id"])
        placed.append({**event, "status": "placed", "asset_id": record.id,
                       "file": record.file})
    sfx_lib.save()

    # --- музыкальная подложка (§14.2, §4.4) -------------------------------
    music_lib = open_library(cfg, "music")
    mood = plan.get("music_mood", "neutral_drive")
    record = music_lib.by_mood(mood) or (music_lib.items[0] if music_lib.items else None)
    music_lufs_lo, music_lufs_hi = cfg.get("audio.music_lufs", [-34, -30])
    music_target = (float(music_lufs_lo) + float(music_lufs_hi)) / 2
    ducking_db = float(cfg.get("audio.ducking_db", -7))

    if record is not None and music_lib.file_path(record).exists():
        bed, bed_sr = A.load_audio_any(music_lib.file_path(record), sr)
        if bed_sr != sr:
            bed = A.resample(bed, bed_sr, sr)
        bed = A.to_stereo(bed)
        bed = A.loop_to_length(bed, length, sr=sr)
        bed = A.duck(bed, voice_mono, sr, depth_db=ducking_db)
        # Уровень подложки задаётся ПОСЛЕ ducking: QC-9 проверяет то, что
        # слышно в готовом миксе, а не то, каким бед был до приглушения.
        bed, _bed_gain = A.normalize_to_lufs(
            bed, music_target, sr,
            measured=A.measure_loudness_buffer(bed, sr).integrated_lufs)
        music_lib.mark_used(record.id, plan["video_id"])
        music_lib.save()
        music_info: dict[str, Any] = {"asset_id": record.id, "mood": record.mood,
                                      "file": record.file,
                                      "target_lufs": music_target,
                                      "ducking_db": ducking_db}
    else:
        bed = np.zeros((length, 2), dtype=np.float32)
        music_info = {"asset_id": None, "mood": mood,
                      "note": "библиотека музыки пуста — подложка не добавлена "
                              "(наполните через fill-libraries, §14.2)"}
        ctx.warn("музыкальная подложка отсутствует: библиотека пуста (§14.2)", mood=mood)

    A.save_wav(ctx.wpath("music_bed.wav"), bed, sr)

    # --- финальный микс ----------------------------------------------------
    # Финальная нормализация микса сдвигает и подложку. Чтобы она осталась в
    # коридоре −30…−34 LUFS уже в готовом файле, компенсируем этот сдвиг в беде.
    target_lufs = float(cfg.get("audio.voice_lufs", -14))
    provisional = A.mix([(voice_stereo, 0.0), (bed, 0.0), (sfx_bus, 0.0)], length, channels=2)
    mix_gain = target_lufs - A.measure_loudness_buffer(provisional, sr).integrated_lufs
    if record is not None and abs(mix_gain) > 0.05:
        bed = A.apply_gain_db(bed, -mix_gain)

    mix = A.mix([(voice_stereo, 0.0), (bed, 0.0), (sfx_bus, 0.0)], length, channels=2)
    measured = A.measure_loudness_buffer(mix, sr).integrated_lufs
    mix, gain_db = A.normalize_to_lufs(mix, target_lufs, sr, measured=measured)
    mix = A.limit_true_peak(mix, float(cfg.get("audio.true_peak_max", -1)))
    A.save_wav(ctx.wpath("mix.wav"), mix, sr)
    final = A.measure_loudness_file(ctx.work_dir / "mix.wav")

    bed_in_mix = A.apply_gain_db(bed, gain_db) if record is not None else None
    bed_lufs = (A.measure_loudness_buffer(bed_in_mix, sr).integrated_lufs
                if bed_in_mix is not None else None)
    sfx_map = {
        "video_id": plan["video_id"],
        "duration_sec": round(duration, 3),
        "sample_rate": sr,
        "events": placed,
        "placed_count": sum(1 for e in placed if e.get("status") == "placed"),
        "missing_roles": sorted(set(missing_roles)),
        "min_gap_sec": float(cfg.get("limits.sfx_min_gap_sec", 2.0)),
        "music": music_info,
        "loudness": {
            "voice_lufs": round(A.measure_loudness_buffer(voice_stereo, sr).integrated_lufs, 2),
            "music_lufs": round(bed_lufs, 2) if bed_lufs is not None else None,
            "mix_lufs": round(final.integrated_lufs, 2),
            "true_peak_dbtp": round(final.true_peak_dbtp, 2),
            "gain_applied_db": round(gain_db, 2),
            "trailing_silence_ms": round(A.trailing_silence_ms(mix, sr), 1),
        },
    }
    ctx.write("sfx_map.json", sfx_map)

    if missing_roles:
        ctx.warn(f"нет SFX для ролей {sorted(set(missing_roles))}: библиотека не заполнена "
                 f"(§14.1) — звук не выдумывается", roles=sorted(set(missing_roles)))
    _log.info("аудио собрано", extra={
        "sfx_placed": sfx_map["placed_count"], "sfx_missing": len(set(missing_roles)),
        "mix_lufs": sfx_map["loudness"]["mix_lufs"],
        "tp": sfx_map["loudness"]["true_peak_dbtp"],
        "music": music_info.get("asset_id"),
    })
    return {"sfx_placed": sfx_map["placed_count"], "mix_lufs": sfx_map["loudness"]["mix_lufs"]}
