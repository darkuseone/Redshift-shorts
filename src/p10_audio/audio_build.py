"""P10: ``cut_plan.json`` + ``voice_final.wav`` → ``sfx_map.json``, ``music_bed.wav``, ``mix.wav``.

§4.4 «Звук». Уровни не «на слух», а измеряются:

* голос −14 LUFS, True Peak ≤ −1 dBTP;
* музыкальная подложка −30…−34 LUFS — «на грани слышимости»: она заполняет
  тишину и держит напряжение, но не конкурирует с голосом;
* ducking −6…−9 dB под речью;
* SFX по смыслу, не на каждый стык, плотность ≤ 1 раза в 2 сек;
* финальный микс −14 ±1 LUFS.

SFX берутся **только** из курируемой библиотеки (§14.1): живые записи
заказчика, выбор по смыслу кадра (теги) и по роли из сценария. Нет звука —
шаг не выдумывает, а честно фиксирует пропуск.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from ..lib import audio as A
from ..lib.logging import get_logger
from ..lib.manifest import open_library
from ..lib.sfx_library import (
    INTENTS, WHOOSH_INTENTS, intent_for_role, pick_sfx,
)

_log = get_logger("p10")

AVATAR_KINDS = ("avatar", "split")
WHOOSH_SCRIPT_ROLES = frozenset({
    "whoosh_in", "whoosh_out", "swipe", "riser", "none", "",
})


def choose_bed(cfg, plan: dict[str, Any]):
    """Какая подложка играет под этот ролик. ``None`` — библиотека пуста.

    Отдельной функцией, а не строками внутри сборки микса: это стык между
    планом и библиотекой, и проверить его иначе нельзя — поднимать ради трёх
    условий весь P10 с голосом, SFX и ffmpeg значит не проверять его вовсе.
    Ровно на таком непроверенном стыке конвейер уже падал: строка жила под
    условием, которого не бывает в мок-режиме, и вылезла только на живом
    прогоне через полчаса работы раннера.

    Порядок: имя настроения из сценария (ручное решение автора важнее любой
    автоматики), затем теги, затем что есть.
    """
    from ..lib.music_library import pick_bed

    music_lib = open_library(cfg, "music")
    mood = plan.get("music_mood") or ""
    tags = plan.get("music_tags") or []
    record = music_lib.by_mood(mood) if mood else None
    if record is None and tags:
        record = pick_bed(cfg, want=tags, video_id=plan.get("video_id", ""))
    if record is None:
        record = music_lib.items[0] if music_lib.items else None
    return record


def _event(t: float, intent: str, why: str, *, priority: int = 1,
           role: str = "") -> dict[str, Any]:
    return {"t": float(t), "intent": intent, "role": role, "why": why,
            "priority": int(priority)}


def _script_sfx_by_block(plan: dict[str, Any]) -> dict[str, str]:
    return {
        block["id"]: str(block.get("sfx") or "")
        for block in plan.get("blocks", [])
    }


def _plan_sfx(plan: dict[str, Any], cfg) -> list[dict[str, Any]]:
    """Расставить SFX по смыслу кадра, плотность ≤ 1 / 2 сек.

    Картинка появилась — вжух. Плашка — клик. Переход — вжух. Это не чек-лист
    ролей, а реакция на то, что зритель видит. Два вжуха в одну миллисекунду
    сливаются в один: воздух не удваивается от того, что слот ещё и dynamic.
    """
    slots = plan["slots"]
    duration = float(plan["duration_sec"])
    min_gap = float(cfg.get("limits.sfx_min_gap_sec", 2.0))
    script_sfx = _script_sfx_by_block(plan)
    events: list[dict[str, Any]] = []

    for index, slot in enumerate(slots):
        prev = slots[index - 1] if index else None
        kind = slot["kind"]
        t = float(slot["start"])
        block_sfx = script_sfx.get(slot.get("block_id", ""), "")

        if kind == "fullscreen_text":
            events.append(_event(t, "fullscreen", "появление full-screen text (§5.2)",
                                 role="reveal"))
        elif kind == "meme":
            events.append(_event(t, "meme", "мем-вставка (§5.8)", role="meme_stinger"))
        elif kind in AVATAR_KINDS and (prev is None or prev["kind"] not in AVATAR_KINDS):
            events.append(_event(t, "avatar_in", "вход аватара (§4.4.2)",
                                 role="whoosh_in"))
        elif prev is not None and prev["kind"] in AVATAR_KINDS and kind not in AVATAR_KINDS:
            events.append(_event(t, "avatar_out", "выход аватара (§4.4.2)",
                                 role="whoosh_out"))

        # Появилась картинка — вжух. Не ставим, если автор уже дал блоку
        # другой акцент (удар, искра): два звука в один кадр — каша.
        picture_arrives = (
            kind == "footage"
            or (kind == "split" and (prev is None or prev["kind"] != "split"))
        )
        if picture_arrives and block_sfx in WHOOSH_SCRIPT_ROLES:
            events.append(_event(t, "picture_in", "появилась картинка",
                                 role="whoosh_in"))

        if slot.get("transition_in") == "dynamic":
            events.append(_event(t, "transition",
                                 "динамический переход обязан звучать (§4.3)",
                                 role="swipe"))

    for block in plan.get("blocks", []):
        overlay = block.get("overlay") or {}
        if overlay.get("type") != "lower_third":
            continue
        block_slots = [s for s in slots if s["block_id"] == block["id"]]
        if block_slots:
            events.append(_event(float(block_slots[0]["start"]) + 0.4, "plaque",
                                 f"плашка блока {block['id']}", role="pop"))

    for block in plan.get("blocks", []):
        role = block.get("sfx")
        if not role or role == "none":
            continue
        block_slots = [s for s in slots if s["block_id"] == block["id"]]
        if block_slots:
            events.append(_event(float(block_slots[0]["start"]),
                                 intent_for_role(str(role)) or "impact",
                                 f"указано в сценарии для блока {block['id']}",
                                 priority=2, role=str(role)))

    cta_start = float(plan.get("cta_window", [duration - 2, duration])[0])
    events.append(_event(cta_start, "cta", "кнопка подписки (§6, QC-16)",
                         role="subscribe_ping"))

    events = _collapse_whooshes(events)
    events.sort(key=lambda e: (e["t"], e["priority"]))
    placed: list[dict[str, Any]] = []
    for event in events:
        if placed and event["t"] - placed[-1]["t"] < min_gap:
            if event["priority"] > placed[-1]["priority"]:
                continue
            if event["priority"] == placed[-1]["priority"] and event["t"] - placed[-1]["t"] < 0.35:
                continue
            if event["t"] - placed[-1]["t"] < min_gap * 0.5:
                continue
        placed.append(event)
    return placed


def _collapse_whooshes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Один вжух на один момент: вход аватара и картинка — одно движение воздуха."""
    prefer = ("avatar_in", "avatar_out", "transition", "picture_in", "picture_out")
    grouped: dict[float, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(round(float(event["t"]), 3), []).append(event)
    collapsed: list[dict[str, Any]] = []
    for _t, group in grouped.items():
        whooshes = [e for e in group if e.get("intent") in WHOOSH_INTENTS]
        others = [e for e in group if e.get("intent") not in WHOOSH_INTENTS]
        if whooshes:
            others.append(min(whooshes, key=lambda e: (
                prefer.index(e["intent"]) if e["intent"] in prefer else 99)))
        collapsed.extend(others)
    return collapsed


def _resolve_sfx(cfg, event: dict[str, Any], *, video_id: str,
                 avoid_ids: Sequence[str]):
    """Роль из сценария, если есть в базе; иначе теги смысла кадра."""
    sfx_lib = open_library(cfg, "sfx")
    role = event.get("role") or ""
    if role:
        record = sfx_lib.by_role(role)
        if record is not None and record.id not in set(avoid_ids):
            return record
    intent = event.get("intent") or intent_for_role(role)
    want = INTENTS.get(intent, ())
    record = pick_sfx(cfg, want=want, video_id=video_id, avoid_ids=avoid_ids)
    if record is None and role:
        return sfx_lib.by_role(role)
    return record


def sfx_peak_corridor(cfg) -> tuple[float, float]:
    """Коридор пиков SFX из конфига (§4.4)."""
    lo, hi = cfg.get("audio.sfx_peak_dbfs", [-16, -12])
    return float(lo), float(hi)


def sfx_peak_target(cfg) -> float:
    """На какой пик ставится акцент. Тихий край коридора, а не громкий.

    Заказчик просил звук, который «еле слышно, но слышно, что дорого»: акцент
    работает подачей, а не громкостью. Переработка ударов добавила им около
    пятнадцати децибел в полосе, которую отдаёт динамик телефона, — на прежнем
    пике −12 они стали бы кричать поверх речи. Четыре децибела вниз возвращают
    их под голос, а слышимость держит уже сам звук.
    """
    return sfx_peak_corridor(cfg)[0]


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
    sfx_peak_lo, sfx_peak_hi = sfx_peak_corridor(cfg)
    sfx_bus = np.zeros((length, 2), dtype=np.float32)
    placed: list[dict[str, Any]] = []
    missing_roles: list[str] = []
    used_ids: list[str] = []

    for event in events:
        record = _resolve_sfx(cfg, event, video_id=plan.get("video_id", ""),
                              avoid_ids=used_ids)
        if record is None:
            missing_roles.append(event.get("role") or event.get("intent") or "?")
            placed.append({**event, "status": "missing_in_library"})
            continue
        path = sfx_lib.file_path(record)
        if not path.exists():
            missing_roles.append(record.role or record.id)
            placed.append({**event, "status": "file_missing", "file": str(path)})
            continue
        clip, clip_sr = A.load_audio_any(path, sr)
        if clip_sr != sr:
            clip = A.resample(clip, clip_sr, sr)
        clip = A.normalize_peak(clip, sfx_peak_target(cfg))
        A.place(sfx_bus, clip, float(event["t"]), sr)
        sfx_lib.mark_used(record.id, plan["video_id"])
        used_ids.append(record.id)
        placed.append({**event, "status": "placed", "asset_id": record.id,
                       "file": record.file, "picked_role": record.role,
                       "tags": list(record.tags)})
    sfx_lib.save()

    # --- музыкальная подложка (§14.2, §4.4) -------------------------------
    music_lib = open_library(cfg, "music")
    record = choose_bed(cfg, plan)
    tags = plan.get("music_tags") or []
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
                                      "tags": list(record.tags),
                                      "wanted_tags": list(tags),
                                      "target_lufs": music_target,
                                      "ducking_db": ducking_db}
    else:
        bed = np.zeros((length, 2), dtype=np.float32)
        music_info = {"asset_id": None, "mood": plan.get("music_mood") or "",
                      "note": "библиотека музыки пуста — подложка не добавлена "
                              "(python -m src.cli add-music, §14.2)"}
        ctx.warn("музыкальная подложка отсутствует: библиотека пуста (§14.2)",
                 mood=plan.get("music_mood") or "")

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
        "sfx_peak_dbfs": float(sfx_peak_lo),
        "sfx_peak_corridor": [float(sfx_peak_lo), float(sfx_peak_hi)],
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
