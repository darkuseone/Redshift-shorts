"""P6: ``cut_plan.json`` + ``voice_final.wav`` → ``avatar/seg_*.mp4`` + ``avatar_meta.json``.

§7.4 «Аватар». Что обеспечивает шаг:

1. Генерация **посегментно**, только на интервалы присутствия — это прямая
   экономия кредитов: платим за 40 % хронометража вместо 100 %.
2. Каждый сегмент — цельная фраза, а не обрывок: сегменты режутся по границам
   слов из ``words.json``.
3. Липсинк строится по финальной (обрезанной) озвучке: в провайдер уходит
   вырезанный кусок ``voice_final.wav``, а не исходный текст.
4. Правило перебивок (§7.4.3) уже применено в P5; здесь оно проверяется ещё раз
   по факту — соседние сегменты не должны стыковаться без зазора.
5. Целевая доля 35–60 % проверяется и попадает в отчёт.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..lib import audio as A
from ..lib.logging import get_logger
from ..lib.providers.avatar import build_avatar_provider

_log = get_logger("p6")

AVATAR_KINDS = ("avatar", "split")


def merge_segments(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Слить смежные аватар-слоты в один сегмент генерации.

    Внутри блока сплит-слоты идут подряд и аватар в них непрерывен — генерировать
    их по отдельности значит платить дважды и получить стык на ровном месте.
    """
    merged: list[dict[str, Any]] = []
    for slot in slots:
        if slot["kind"] not in AVATAR_KINDS:
            continue
        if (merged and abs(merged[-1]["end"] - slot["start"]) < 1e-6
                and merged[-1]["block_id"] == slot["block_id"]):
            merged[-1]["end"] = slot["end"]
            merged[-1]["slot_indices"].append(slot["index"])
            continue
        merged.append({
            "start": float(slot["start"]), "end": float(slot["end"]),
            "block_id": slot["block_id"], "mode": slot["mode"],
            "kind": slot["kind"], "slot_indices": [slot["index"]],
        })
    return merged


def snap_to_phrase(segment: dict[str, Any], words: list[dict[str, Any]]) -> dict[str, Any]:
    """Расширить сегмент до целых слов (§7.4.2: сегмент — цельная фраза)."""
    inside = [w for w in words
              if float(w["end"]) > segment["start"] and float(w["start"]) < segment["end"]]
    if not inside:
        return segment
    segment = dict(segment)
    segment["text"] = " ".join(w["display"] for w in inside)
    segment["word_count"] = len(inside)
    return segment


def run_step(ctx) -> dict[str, Any]:
    plan = ctx.read("cut_plan.json")
    words_doc = ctx.read_or("words.json", {"words": []})
    cfg = ctx.cfg

    if not bool(cfg.get("features.avatar_enabled", True)):
        ctx.write("avatar_meta.json", {"video_id": plan["video_id"], "enabled": False,
                                       "segments": [], "note": "аватар выключен флагом"})
        return {"segments": 0, "enabled": False}

    voice, sr = A.load_wav(ctx.work_dir / "voice_final.wav")
    voice_mono = A.to_mono(voice)
    duration = float(plan["duration_sec"])

    segments = [snap_to_phrase(s, words_doc["words"]) for s in merge_segments(plan["slots"])]
    max_seg = float(cfg.get("heygen.max_seconds_per_video", 42))
    provider = build_avatar_provider(cfg, ctx.costs)

    total_avatar_sec = sum(s["end"] - s["start"] for s in segments)
    if total_avatar_sec > max_seg:
        ctx.warn(f"суммарная длина аватара {total_avatar_sec:.1f} сек превышает лимит "
                 f"{max_seg} сек на ролик", total_sec=total_avatar_sec)

    out_dir = ctx.wpath("avatar", ".keep").parent
    produced: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        start, end = segment["start"], segment["end"]
        i0, i1 = int(round(start * sr)), int(round(end * sr))
        chunk = voice_mono[i0:i1]
        if len(chunk) == 0:
            continue
        seg_audio = out_dir / f"seg_{index:02d}.wav"
        A.save_wav(seg_audio, chunk, sr)

        seg_path = out_dir / f"seg_{index:02d}.mp4"
        result = provider.generate(audio_path=seg_audio, out_path=seg_path,
                                   duration_sec=end - start, index=index)
        seg_path = result.path
        entry = result.to_dict()
        entry.update({
            "start": round(start, 3), "end": round(end, 3),
            "duration": round(end - start, 3),
            "block_id": segment["block_id"], "mode": segment["mode"],
            "kind": segment["kind"], "slot_indices": segment["slot_indices"],
            "text": segment.get("text", ""), "audio": str(seg_audio),
        })
        produced.append(entry)

    # §7.4.3 — проверка по факту: сегменты не должны стыковаться вплотную.
    adjacent: list[dict[str, Any]] = []
    for prev, nxt in zip(produced, produced[1:]):
        gap = nxt["start"] - prev["end"]
        if gap < 0.2:
            adjacent.append({"a": prev["index"], "b": nxt["index"], "gap_sec": round(gap, 3)})

    share = total_avatar_sec / max(duration, 1e-6)
    lo, hi = cfg.get("limits.avatar_share", [0.35, 0.60])
    meta = {
        "video_id": plan["video_id"],
        "enabled": True,
        "avatar_id": cfg.get("heygen.avatar_id"),
        "model_version": cfg.get("heygen.model_version"),
        "provider_mode": produced[0]["provider_mode"] if produced else "mock",
        "background": cfg.get("heygen.background"),
        "segments": produced,
        "segment_count": len(produced),
        "total_sec": round(total_avatar_sec, 3),
        "share": round(share, 4),
        "share_limits": [lo, hi],
        "share_ok": lo <= share <= hi,
        "adjacent_without_gap": adjacent,
        "credits_saved_pct": round((1.0 - share) * 100, 1),
    }
    ctx.write("avatar_meta.json", meta)

    if adjacent:
        ctx.warn(f"аватар-сегменты стыкуются без перебивки: {adjacent} (§7.4.3, R-3)",
                 pairs=adjacent)
    if not meta["share_ok"]:
        ctx.warn(f"доля аватара {share:.1%} вне {lo:.0%}–{hi:.0%} (§3.5)", share=share)
    if meta["provider_mode"] == "mock":
        ctx.warn("аватар сгенерирован в mock-режиме: не для публикации", step="P6")

    _log.info("аватар готов", extra={
        "segments": len(produced), "total_sec": round(total_avatar_sec, 2),
        "share": meta["share"], "mode": meta["provider_mode"],
        "credits_saved_pct": meta["credits_saved_pct"],
    })
    return {"segments": len(produced), "share": meta["share"],
            "provider_mode": meta["provider_mode"]}
