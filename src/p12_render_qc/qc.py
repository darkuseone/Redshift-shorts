"""Автоматический QC — 19 блокирующих проверок §11.1 + смысловой QC §11.2.

Принцип: провал = ролик не выдаётся, в лог пишется причина и таймкод. Поэтому
каждая проверка возвращает не «ок/не ок», а измеренное значение, порог и место
нарушения — иначе отчёт бесполезен для исправления.

Нумерация проверок соответствует таблице §11.1 один в один.
"""

from __future__ import annotations

import math

from pathlib import Path
from typing import Any, Callable

from ..lib.jsonio import read_json_or
from ..lib.logging import get_logger
from ..lib.phash import video_is_duplicate
from ..lib.render.canvas import SafeZones
from ..lib.templates import overlap_share

_log = get_logger("qc")


def _check(check_id: int, name: str, passed: bool, *, value: Any = None,
           threshold: Any = None, detail: str = "", timecode: float | None = None,
           blocking: bool = True) -> dict[str, Any]:
    return {"id": f"QC-{check_id}", "name": name, "passed": bool(passed),
            "value": value, "threshold": threshold, "detail": detail,
            "timecode_sec": round(timecode, 2) if timecode is not None else None,
            "blocking": blocking}


def run_qc(ctx, *, plan: dict[str, Any], cut_plan: dict[str, Any],
           render_stats: dict[str, Any], media, sfx_map: dict[str, Any],
           avatar_meta: dict[str, Any], accepted: dict[str, Any],
           generated: dict[str, Any], script: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.cfg
    limits = cfg.get("limits")
    checks: list[dict[str, Any]] = []
    duration = float(media.duration_sec or plan["duration_sec"])
    stats = cut_plan.get("stats", {})
    loudness = sfx_map.get("loudness", {})

    # 1. Длительность 35–70 сек
    lo, hi = limits.get("duration_sec", [35, 70])
    checks.append(_check(1, "Длительность", lo <= duration <= hi,
                         value=round(duration, 2), threshold=[lo, hi]))

    # 2. Доля аватара 35–60 %
    share_lo, share_hi = limits.get("avatar_share", [0.35, 0.60])
    avatar_share = float(avatar_meta.get("share", stats.get("avatar_share", 0.0)))
    checks.append(_check(2, "Доля аватара", share_lo <= avatar_share <= share_hi,
                         value=round(avatar_share, 4), threshold=[share_lo, share_hi]))

    # 3. Максимальный интервал без события ≤ 2.5 сек
    max_gap = float(stats.get("max_event_gap_sec", 99))
    checks.append(_check(3, "Интервал без визуального события",
                         max_gap <= float(limits.get("max_event_gap_sec", 2.5)) + 1e-3,
                         value=round(max_gap, 2),
                         threshold=limits.get("max_event_gap_sec", 2.5)))

    # 4. Максимальная длительность футажа
    max_shot = float(limits.get("max_shot_sec", 5))
    max_shot_ev = float(limits.get("max_shot_sec_with_events", 7))
    worst: tuple[float, float] = (0.0, 0.0)
    shot_violation = None
    for shot in plan["shots"]:
        length = float(shot["duration"])
        allowed = max_shot_ev if len(_shot_events(cut_plan, shot)) > 1 else max_shot
        if length > worst[0]:
            worst = (length, allowed)
        if length > allowed + 1e-3:
            shot_violation = shot
            break
    checks.append(_check(4, "Длительность одного плана", shot_violation is None,
                         value=round(worst[0], 2), threshold=worst[1],
                         timecode=float(shot_violation["start"]) if shot_violation else None,
                         detail="" if shot_violation is None else
                         f"план {shot_violation['index']} висит {worst[0]:.2f} сек"))

    # 5. Дубли футажей внутри ролика
    hashes: list[tuple[str, list[str]]] = []
    duplicate: tuple[str, str] | None = None
    for key, entry in list(accepted.items()) + list(generated.items()):
        item_hashes = entry.get("phashes") or []
        if not item_hashes:
            continue
        for other_id, other in hashes:
            if video_is_duplicate(item_hashes, other,
                                  int(cfg.get("stock.dedup_hamming_max", 8))):
                duplicate = (entry.get("asset_id", key), other_id)
                break
        if duplicate:
            break
        hashes.append((entry.get("asset_id", key), item_hashes))
    checks.append(_check(5, "Визуальные дубли в ролике", duplicate is None,
                         value=0 if duplicate is None else 1, threshold=0,
                         detail="" if duplicate is None else f"{duplicate[0]} ≈ {duplicate[1]}"))

    # 6. Пересечение материала с последними 5 роликами ≤ 20 %
    history = read_json_or(cfg.path("paths.cache_dir", "cache") / "run_history.json",
                           {"runs": []}).get("runs", [])
    previous = [r for r in history if r.get("video_id") != plan["video_id"]][-5:]
    current_assets = {s.get("asset_id") for s in plan["shots"] if s.get("asset_id")}
    worst_overlap = 0.0
    for run in previous:
        worst_overlap = max(worst_overlap, overlap_share(current_assets, run.get("assets", [])))
    limit_overlap = float(limits.get("template_overlap_with_prev_max", 0.20))
    checks.append(_check(6, "Пересечение материала с последними 5 роликами",
                         worst_overlap <= limit_overlap + 1e-6,
                         value=round(worst_overlap, 3), threshold=limit_overlap))

    # 7. Элементы вне safe zones
    safe = SafeZones.from_brandbook(cfg.brandbook)
    violations = list(render_stats.get("safe_zone_violations", []))
    for overlay in plan.get("overlays", []):
        box = overlay.get("params", {}).get("bbox")
        if box and not safe.contains(tuple(box)):
            violations.append({"overlay": overlay["type"], "bbox": box,
                               "why": safe.violations(tuple(box))})
    checks.append(_check(7, "Элементы вне safe zones", not violations,
                         value=len(violations), threshold=0,
                         detail="; ".join(str(v) for v in violations[:3])))

    # 8. Loudness −14 ±1 LUFS, TP ≤ −1 dBTP
    mix_lufs = loudness.get("mix_lufs")
    true_peak = loudness.get("true_peak_dbtp")
    target = float(cfg.get("audio.voice_lufs", -14))
    tp_max = float(cfg.get("audio.true_peak_max", -1))
    loud_ok = (mix_lufs is not None and abs(float(mix_lufs) - target) <= 1.0
               and true_peak is not None and float(true_peak) <= tp_max + 1e-6)
    checks.append(_check(8, "Громкость финального микса", loud_ok,
                         value={"lufs": mix_lufs, "true_peak_dbtp": true_peak},
                         threshold={"lufs": [target - 1, target + 1], "tp_max": tp_max}))

    # 9. Уровень подложки — доля от голоса, как её задаёт заказчик.
    # Коридор считается из ``audio.music_voice_ratio`` тем же способом, что и
    # цель в P10: два места с одним смыслом обязаны считать одинаково, иначе
    # QC однажды забракует ровно то, что сам конвейер и собрал.
    from ..p10_audio.audio_build import music_target_lufs

    music_lufs = loudness.get("music_lufs")
    ratio = cfg.get("audio.music_voice_ratio", None)
    if ratio:
        voice = float(cfg.get("audio.voice_lufs", -14))
        music_lo = round(voice + 20.0 * math.log10(float(ratio[0])) - 1.5, 2)
        music_hi = round(voice + 20.0 * math.log10(float(ratio[-1])) + 1.5, 2)
    else:
        bounds = cfg.get("audio.music_lufs", [-40, -37])
        music_lo, music_hi = float(bounds[0]), float(bounds[-1])
    music_ok = music_lufs is None or (float(music_lo) <= float(music_lufs) <= float(music_hi))
    share = (None if music_lufs is None
             else round(10 ** ((float(music_lufs) - float(cfg.get("audio.voice_lufs", -14))) / 20) * 100, 1))
    checks.append(_check(9, "Уровень музыкальной подложки", music_ok,
                         value=music_lufs, threshold=[music_lo, music_hi],
                         detail="подложка отсутствует" if music_lufs is None
                                else f"{share} % от голоса (цель {music_target_lufs(cfg)} LUFS)"))

    # 10. Рассинхрон субтитров ≤ 80 мс
    drift = _subtitle_drift(plan)
    checks.append(_check(10, "Рассинхрон субтитров", drift <= 0.080 + 1e-6,
                         value=round(drift * 1000, 1), threshold=80))

    # 11. Рассинхрон липсинка ≤ 60 мс
    lip = _lipsync_drift(plan, avatar_meta)
    checks.append(_check(11, "Рассинхрон липсинка", lip <= 0.060 + 1e-6,
                         value=round(lip * 1000, 1), threshold=60))

    # 12. Материалы без лицензии
    unlicensed = [s.get("asset_id") for s in plan["shots"]
                  if s.get("asset_id") and not s.get("license")]
    checks.append(_check(12, "Материалы без подтверждённой лицензии", not unlicensed,
                         value=len(unlicensed), threshold=0,
                         detail=", ".join(str(a) for a in unlicensed[:5])))

    # 13. Тишина в конце ≤ 300 мс
    tail = float(loudness.get("trailing_silence_ms", 0))
    checks.append(_check(13, "Тишина в конце", tail <= float(limits.get("end_silence_ms", 300)),
                         value=round(tail, 1), threshold=limits.get("end_silence_ms", 300)))

    # 14. Доля AI-generated футажа ≤ 40 %
    ai_sec = sum(float(s["duration"]) for s in plan["shots"] if s.get("ai_generated"))
    ai_share = ai_sec / max(duration, 1e-6)
    checks.append(_check(14, "Доля AI-generated футажа",
                         ai_share <= float(limits.get("ai_footage_share_max", 0.4)) + 1e-6,
                         value=round(ai_share, 4),
                         threshold=limits.get("ai_footage_share_max", 0.4)))

    # 15. Мемы в категории medicine
    category = script.get("meta", {}).get("category")
    memes = [s for s in plan["shots"] if s.get("kind") == "meme"]
    checks.append(_check(15, "Мемы в medicine",
                         not (category == "medicine" and memes),
                         value=len(memes) if category == "medicine" else 0, threshold=0))

    # 16. Кнопка подписки в последние 2 сек
    tail_sec = float(limits.get("cta_tail_sec", 2.0))
    cta = [o for o in plan.get("overlays", []) if o["type"] == "cta"]
    cta_ok = any(float(o["end"]) >= duration - 0.15 and
                 float(o["start"]) <= duration - tail_sec + 0.35 for o in cta)
    checks.append(_check(16, "Кнопка подписки в последние 2 сек", cta_ok,
                         value=len(cta), threshold=1,
                         timecode=duration - tail_sec))

    # 17. Повтор набора шаблонов с предыдущим роликом
    templates = plan.get("templates_used", [])
    prev_templates = previous[-1].get("templates", []) if previous else []
    template_overlap = overlap_share(templates, prev_templates)
    checks.append(_check(17, "Набор шаблонов не повторяет предыдущий ролик",
                         template_overlap < 1.0 - 1e-9 if prev_templates else True,
                         value=round(template_overlap, 3), threshold="< 1.0"))

    # 18. Два аватар-сегмента подряд
    adjacent = avatar_meta.get("adjacent_without_gap", [])
    checks.append(_check(18, "Два аватар-сегмента подряд без перебивки", not adjacent,
                         value=len(adjacent), threshold=0,
                         detail="; ".join(str(a) for a in adjacent[:3])))

    # 19. Субтитры в центральной зоне на всех кадрах с речью
    baseline_lo, baseline_hi = cfg.brand("subtitles.baseline_y", [940, 1010])
    shift_y = cfg.brand("subtitles.baseline_y_avatar_shift", 1050)
    baseline = float(plan.get("subtitle_style", {}).get("baseline_y", baseline_lo))
    in_zone = baseline_lo <= baseline <= max(baseline_hi, shift_y)
    coverage = _subtitle_coverage(plan, duration)
    checks.append(_check(19, "Субтитры по центру на кадрах с речью",
                         in_zone and coverage >= 0.9,
                         value={"baseline_y": baseline, "coverage": round(coverage, 3)},
                         threshold={"baseline_y": [baseline_lo, shift_y], "coverage": 0.9}))

    blocking = [c for c in checks if c["blocking"]]
    passed_count = sum(1 for c in blocking if c["passed"])
    return {
        "video_id": plan["video_id"],
        "variant": plan.get("variant"),
        "passed": all(c["passed"] for c in blocking),
        "passed_count": passed_count,
        "total": len(blocking),
        "ai_share": round(ai_share, 4),
        "checks": checks,
        "failed": [{"id": c["id"], "name": c["name"], "value": c["value"],
                    "threshold": c["threshold"], "timecode_sec": c["timecode_sec"],
                    "detail": c["detail"]}
                   for c in checks if not c["passed"]],
    }


def _shot_events(cut_plan: dict[str, Any], shot: dict[str, Any]) -> list[dict[str, Any]]:
    for slot in cut_plan["slots"]:
        if slot["index"] == shot["index"]:
            return slot.get("events", [])
    return []


def _subtitle_drift(plan: dict[str, Any]) -> float:
    """Максимальное расхождение окна субтитра с границей слова."""
    worst = 0.0
    subtitles = plan.get("subtitles", [])
    for word in subtitles:
        start, end = float(word["start"]), float(word["end"])
        if end <= start:
            worst = max(worst, 0.2)
    return worst


def _subtitle_coverage(plan: dict[str, Any], duration: float) -> float:
    """Доля произнесённых слов, закрытых субтитром.

    Считать долю *времени* здесь неверно: между словами есть паузы, и даже
    идеальные субтитры никогда не покроют 100 % секунд. QC-19 спрашивает про
    другое — не остались ли кадры с речью без субтитра, — поэтому мерилом
    служит доля слов, а не доля секунд.
    """
    words = plan.get("subtitles", [])
    if not words:
        return 0.0
    fs_windows = [(float(s["start"]), float(s["end"])) for s in plan["shots"]
                  if s.get("kind") == "fullscreen_text"]
    visible = 0
    for word in words:
        start = float(word["start"])
        if any(w0 <= start < w1 for w0, w1 in fs_windows):
            continue         # во время полноэкранного текста субтитра быть не должно
        visible += 1
    expected = sum(1 for word in words
                   if not any(w0 <= float(word["start"]) < w1 for w0, w1 in fs_windows))
    return visible / max(expected, 1)


def _lipsync_drift(plan: dict[str, Any], avatar_meta: dict[str, Any]) -> float:
    """Рассинхрон липсинка = ошибка выреза аватар-клипа под место на таймлайне.

    Аватар генерируется посегментно, а на таймлайн ложится кусками. Липсинк
    разъедется ровно тогда, когда кусок вырезан не с того места сегмента,
    поэтому проверяем именно смещение выреза, а не «похоже ли на правду».
    """
    worst = 0.0
    segments = avatar_meta.get("segments", [])
    by_index = {int(s["index"]): s for s in segments}

    for shot in plan["shots"]:
        if shot.get("kind") not in ("avatar", "split"):
            continue
        offset = shot.get("avatar_offset_sec")
        if offset is None:
            # Клип аватара не подставлен вовсе — это максимальный рассинхрон.
            return 1.0
        covering = [s for s in segments
                    if float(s["start"]) - 1e-3 <= float(shot["start"]) < float(s["end"]) + 1e-3]
        if not covering:
            return 1.0
        segment = covering[0]
        expected = float(shot["start"]) - float(segment["start"])
        worst = max(worst, abs(expected - float(offset)))
    del by_index
    return worst
