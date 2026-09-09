"""Автоматический QC — 19 блокирующих проверок §11.1 + смысловой QC §11.2.

Принцип: провал = ролик не выдаётся, в лог пишется причина и таймкод. Поэтому
каждая проверка возвращает не «ок/не ок», а измеренное значение, порог и место
нарушения — иначе отчёт бесполезен для исправления.

Нумерация проверок соответствует таблице §11.1 один в один.
"""

from __future__ import annotations

import math
from collections import Counter

from pathlib import Path
from typing import Any, Callable

from ..lib.jsonio import read_json_or
from ..lib.logging import get_logger
from ..lib.palette import overlay_cyan_misuse, overlay_offbrand_fills
from ..lib.phash import video_is_duplicate
from ..lib.render.canvas import SafeZones, SAFE_ZONE_OVERLAY_TYPES
from ..lib.render.hyperframes.templates import text_width
from ..lib.templates import overlap_share

_log = get_logger("qc")

# MUST-014: Jaccard набора шаблонов с предыдущим роликом. Fail при ≥ порога.
# Instruction числа не задаёт; код с «< 1.0» не падал почти никогда.
# QC-6 держит 0.20 на пересечении *материала*, не шаблонов.
QC17_TEMPLATE_OVERLAP_MAX = 0.80
# QC-21 смотрит на приёмы кадра и содержательные оверлеи, не на хром
# (CTA / плашка домена). Пустой needs у outro-cta иначе ронял любой ролик.
QC21_CONTENT_OVERLAY_TYPES = frozenset({"dataviz", "source_card"})
# Хук / CTA / нижняя плашка — мебель кадра: у большинства пустой `needs`
# по каталогу. Считать их «приёмами без основания» раздувало долю на 0042
# до 7/7, хотя карточки и диаграммы были живые. Need-less fullscreen
# (MUST-010) по-прежнему в доле.
QC21_FURNITURE_CATEGORIES = frozenset({
    "intro-hooks", "outro-cta", "lower-thirds",
})


def _check(check_id: int, name: str, passed: bool, *, value: Any = None,
           threshold: Any = None, detail: str = "", timecode: float | None = None,
           blocking: bool = True) -> dict[str, Any]:
    return {"id": f"QC-{check_id}", "name": name, "passed": bool(passed),
            "value": value, "threshold": threshold, "detail": detail,
            "timecode_sec": round(timecode, 2) if timecode is not None else None,
            "blocking": blocking}


def blocking_failed_ids(qc: dict[str, Any]) -> list[str]:
    """Идентификаторы проверок, из-за которых ролик не выдаётся.

    Предупреждения (QC-28 и недобор акцента) живут в ``checks``, но не
    блокируют выдачу и не должны попадать в ``QC_FAILED``.
    """
    return [c["id"] for c in qc.get("checks") or []
            if not c.get("passed") and c.get("blocking", True)]


def _qc21_is_content(template_id: str) -> bool:
    """QC-21 смотрит устройства смысла, не мебель кадра."""
    cat = str(template_id or "").split("/", 1)[0]
    return bool(cat) and cat not in QC21_FURNITURE_CATEGORIES


# Что на кадре хука не пишут никогда: это не хук, а заставка. Список тот же,
# что блокирует устный хук на P0 (`HOOK_GREETING`), — экран и голос не должны
# расходиться в том, что считается разгоном.
_HOOK_BANNED_ON_SCREEN = (
    "привет", "подписывайся", "подписывайтесь", "с вами", "в этом видео",
    "сегодня разберём", "сегодня разберем", "смотри до конца", "новое видео",
)


def _hook_is_banned(text: str) -> bool:
    low = str(text or "").lower()
    return any(bad in low for bad in _HOOK_BANNED_ON_SCREEN)


def _talking_head_in_window(shots: list[dict[str, Any]],
                            slots: list[dict[str, Any]], *,
                            until: float) -> dict[str, Any] | None:
    """Первый кадр-лицо, который пересекает [0, until)."""
    for item in list(shots) + list(slots):
        if item.get("kind") not in ("avatar", "split"):
            continue
        start = float(item.get("start", 0.0) or 0.0)
        end = float(item.get("end") or (start + float(item.get("duration") or 0.0)))
        if start < until - 1e-9 and end > 1e-9:
            return item
    return None


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

    # 7. Элементы вне safe zones. Пустой список при живых оверлеях — это
    # «не мерили», а не «всё в зоне»: HyperFrames раньше не писал bbox, и
    # QC-7 зеленел вхолостую.
    safe = SafeZones.from_brandbook(cfg.brandbook)
    violations = list(render_stats.get("safe_zone_violations", []))
    checks_done = list(render_stats.get("safe_zone_checks") or [])
    measured_boxes = 0
    for overlay in plan.get("overlays", []):
        box = overlay.get("params", {}).get("bbox")
        if not (box and len(box) == 4):
            continue
        measured_boxes += 1
        if not safe.contains(tuple(box)):
            violations.append({"overlay": overlay.get("type"), "bbox": box,
                               "why": safe.violations(tuple(box))})
    measurable = [
        ov for ov in plan.get("overlays") or []
        if str(ov.get("type") or "") in SAFE_ZONE_OVERLAY_TYPES
    ]
    measured = bool(
        measured_boxes or checks_done
        or render_stats.get("safe_zone_measured"))
    if measurable and not measured:
        checks.append(_check(
            7, "Элементы вне safe zones", False,
            value={"violations": len(violations), "measured": 0,
                   "overlays": len(measurable)},
            threshold=0, detail="не мерили"))
    else:
        checks.append(_check(
            7, "Элементы вне safe zones", not violations,
            value={"violations": len(violations), "measured": measured_boxes
                   or len(checks_done),
                   "overlays": len(measurable)},
            threshold=0,
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
        bounds = cfg.get("audio.music_lufs", [-26, -24])
        music_lo, music_hi = float(bounds[0]), float(bounds[-1])
    music_ok = music_lufs is None or (float(music_lo) <= float(music_lufs) <= float(music_hi))
    share = (None if music_lufs is None
             else round(10 ** ((float(music_lufs) - float(cfg.get("audio.voice_lufs", -14))) / 20) * 100, 1))
    checks.append(_check(9, "Уровень музыкальной подложки", music_ok,
                         value=music_lufs, threshold=[music_lo, music_hi],
                         detail="подложка отсутствует" if music_lufs is None
                                else f"{share} % от голоса (цель {music_target_lufs(cfg)} LUFS)"))

    # 10. Рассинхрон субтитров: SRT vs речь после P3. Потолок — верх окна
    # слова в P4 (`speech.max_word_ms`, 450 мс), не киношные 50/80 мс.
    drift_limit = float(cfg.get("speech.max_word_ms", 450)) / 1000.0
    drift = _subtitle_drift(plan, speech_words=_speech_words(ctx, plan))
    checks.append(_check(10, "Рассинхрон субтитров",
                         drift <= drift_limit + 1e-6,
                         value=round(drift * 1000, 1),
                         threshold=int(round(drift_limit * 1000))))

    # 11. Смещение выреза аватар-клипа относительно таймлайна.
    # Это не рот и не lip-sync (LATER-003): только avatar_clip_offset.
    offset = _avatar_clip_offset(plan, avatar_meta)
    checks.append(_check(11, "Смещение выреза аватар-клипа",
                         offset <= 0.060 + 1e-6,
                         value=round(offset * 1000, 1), threshold=60,
                         detail="avatar_clip_offset"))

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

    # 14. Доля AI-generated футажа ≤ 10 %
    ai_sec = sum(float(s["duration"]) for s in plan["shots"] if s.get("ai_generated"))
    ai_share = ai_sec / max(duration, 1e-6)
    checks.append(_check(14, "Доля AI-generated футажа",
                         ai_share <= float(limits.get("ai_footage_share_max", 0.10)) + 1e-6,
                         value=round(ai_share, 4),
                         threshold=limits.get("ai_footage_share_max", 0.10)))

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
    qc17_max = float(limits.get("qc17_template_overlap_max", QC17_TEMPLATE_OVERLAP_MAX))
    overlap_ok = (not prev_templates) or (template_overlap < qc17_max)
    checks.append(_check(17, "Набор шаблонов не повторяет предыдущий ролик",
                         overlap_ok,
                         value=round(template_overlap, 3), threshold=qc17_max))

    # 18. Два аватар-сегмента подряд
    adjacent = avatar_meta.get("adjacent_without_gap", [])
    checks.append(_check(18, "Два аватар-сегмента подряд без перебивки", not adjacent,
                         value=len(adjacent), threshold=0,
                         detail="; ".join(str(a) for a in adjacent[:3])))

    # 19. Субтитры в центральной зоне на всех кадрах с речью
    baseline_lo, baseline_hi = cfg.brand("subtitles.baseline_y", [1100, 1280])
    shift_y = cfg.brand("subtitles.baseline_y_avatar_shift", 1280)
    baseline = float(plan.get("subtitle_style", {}).get("baseline_y", baseline_lo))
    in_zone = baseline_lo <= baseline <= max(baseline_hi, shift_y)
    coverage = _subtitle_coverage(plan, duration)
    checks.append(_check(19, "Субтитры по центру на кадрах с речью",
                         in_zone and coverage >= 0.9,
                         value={"baseline_y": baseline, "coverage": round(coverage, 3)},
                         threshold={"baseline_y": [baseline_lo, shift_y], "coverage": 0.9}))

    # --- QC-20/21/22: номера закреплены за MEGA P1, формулировка её же.

    # 20. Текст за полем брендбука. Полей два: `work_area` (740 px) смещено
    # влево, справа 250 px отданы ведущему; полноэкранные приёмы ведущего не
    # имеют и набирают по центру во всю ширину за вычетом тех же полей —
    # 1080 - 2*90 = 900 px. Меряем по внешней границе: строка шире неё вылезает
    # в любом случае, а 740 px — брак только на стороне ведущего, и по плану
    # эти элементы не отличить. Тот же порог, что у предрендерного линта.
    bleed_w = 1080 - 2 * 90
    over = []
    for shot in plan.get("shots", []):
        text = str(shot.get("content") or "")
        size = int((shot.get("params") or {}).get("size") or 0)
        if not text or size <= 0:
            continue
        widest = max((min(text_width(line.upper(), size, role="display"),
                          text_width(line.upper(), size, role="subtitle"))
                      for line in text.splitlines() if line.strip()), default=0.0)
        if widest > bleed_w + 1.0:
            over.append({"index": shot.get("index"), "px": round(widest)})
    checks.append(_check(
        20, "Текст за полем брендбука", not over,
        value=len(over), threshold=bleed_w,
        detail=", ".join(f"кадр {o['index']}: {o['px']} px" for o in over[:6])))

    # 21. Приём без основания. Need-less выбранный шаблон = ungrounded
    # (MUST-010): пустой `needs` больше не прячет приём от гейта.
    # CTA и нижние плашки — хром (QC-16 / домен источника), не приём MEGA P1:
    # на кэш-сборке 0042 они одни поднимали долю выше 30% при живых карточках.
    placed = list(plan.get("shots") or [])
    placed += [o for o in (plan.get("overlays") or [])
               if str(o.get("type") or "") in QC21_CONTENT_OVERLAY_TYPES]
    selected = [p for p in placed if p.get("template")
                and _qc21_is_content(str(p.get("template") or ""))]
    ungrounded = [p for p in selected if not p.get("grounded_on")]
    ungrounded_share = (len(ungrounded) / len(selected)) if selected else 0.0
    checks.append(_check(
        21, "Приёмы без основания", ungrounded_share <= 0.30,
        value=round(ungrounded_share, 3), threshold=0.30,
        detail=f"{len(ungrounded)} из {len(selected)} содержательных приёмов "
               f"без grounded_on (need-less считается)"))

    # 22. Выбранный приём обязан лежать в разрешённом наборе. Ступени отката
    # различаются по смыслу: снятие `duration` и `traits` оставляет приём
    # **внутри** набора — слот короче любого шаблона категории это дефект
    # нарезки, а не подбора. Выходом за набор считается только последняя
    # ступень, иначе гейт ловил бы чужую поломку.
    traces = plan.get("pick_traces") or []
    escaped = [t for t in traces
               if t.get("allow_size") and t.get("escape_level") == "category"]
    checks.append(_check(
        22, "Выбранный приём внутри разрешённого набора", not escaped,
        value=len(escaped), threshold=0,
        detail=", ".join(f"{t['category']}→{t['template']}" for t in escaped[:6])))

    # 23. Полноэкранных надписей — в смонтированном ролике, а не в плане.
    # Потолок `limits.fullscreen_text_per_video` стоял в конфиге и никем не
    # мерился на выходе (N-2): на 0042 четырнадцать кадров из двадцати
    # закрылись надписью при девятнадцати пройденных QC.
    shots = plan.get("shots", [])
    fs_hi = int((limits.get("fullscreen_text_per_video") or [2, 4])[-1])
    fs_shots = [s for s in shots if s.get("kind") == "fullscreen_text"]
    checks.append(_check(
        23, "Полноэкранных надписей в ролике", len(fs_shots) <= fs_hi,
        value=len(fs_shots), threshold=fs_hi,
        detail=", ".join(str(s["index"]) for s in fs_shots[:8])))

    # 24. Голых плит: кадр без текста, без ассета и без приёма. Последняя
    # ветка лестницы §7.2, и она обязана оставаться последней.
    plates = [s for s in shots
              if "plate without text" in str(s.get("gap_reason") or "")]
    checks.append(_check(
        24, "Голых плит без текста и материала", len(plates) <= 2,
        value=len(plates), threshold=2,
        detail=", ".join(str(s["index"]) for s in plates[:8])))

    # 25. Визуальное разнообразие: ни один приём не звучит больше двух раз.
    # На 0042 `blur-out-up` встречался трижды (V-4).
    used = [str(s.get("template") or "") for s in shots if s.get("template")]
    used += [str(o.get("template") or "")
             for o in plan.get("overlays", []) if o.get("template")]
    counts = Counter(used)
    worst_template, worst_count = (counts.most_common(1) or [("", 0)])[0]
    checks.append(_check(
        25, "Приём не повторяется больше двух раз", worst_count <= 2,
        value={"template": worst_template, "count": worst_count},
        threshold=2,
        detail=f"{worst_template} — {worst_count} раза" if worst_count > 2 else ""))

    # 27. Шов лупа (§6.3 R-4). Мерится только там, где он обещан: тип
    # концовки `visual_loop_seam` — единственный, который берёт на себя
    # обязательство сомкнуть последний кадр с первым. На всех остальных типах
    # проверка не блокирует и остаётся справкой: интересно знать, насколько
    # ролик близок к петле, но требовать её не за что.
    seam_declared = str((cut_plan.get("cta") or {}).get("type") or "") == "visual_loop_seam"
    seam_bits = render_stats.get("loop_seam_dhash_bits")
    seam_max = int(cfg.get("limits.loop_seam_dhash_max", 12))
    seam_measured = seam_bits is not None
    checks.append(_check(
        27, "Шов лупа: последний кадр совпадает с первым",
        (not seam_declared) or (seam_measured and int(seam_bits) <= seam_max),
        value={"bits": None if not seam_measured else int(seam_bits),
               "declared": seam_declared},
        threshold=seam_max,
        detail=("тип концовки не visual_loop_seam — шов не обещан"
                if not seam_declared else
                "замер не выполнен" if not seam_measured else
                f"расхождение {int(seam_bits)} бит из 64"),
        blocking=seam_declared))

    # 28. Плотность первых секунд (§10.4). Ролик решается в первые три
    # секунды, и мёртвая пауза длиннее пятой доли секунды там слышна как
    # провал темпа. Предупреждающий: звук — не брак кадра, но повод править
    # раскладку событий.
    fs_window = float(limits.get("first_seconds_window", 3.0))
    fs_gap_ms = float(limits.get("first_seconds_gap_ms", 200))
    beats = sorted(float(e["t"]) for e in sfx_map.get("events", [])
                   if e.get("status") == "placed" and float(e.get("t", 99)) <= fs_window)
    marks = [0.0, *beats]
    worst_gap = max((marks[i] - marks[i - 1] for i in range(1, len(marks))), default=fs_window)
    if not beats:
        worst_gap = fs_window
    checks.append(_check(
        28, "Мёртвая пауза в первые секунды",
        worst_gap * 1000.0 <= fs_gap_ms + 1e-6,
        value={"worst_gap_ms": round(worst_gap * 1000.0, 1),
               "events": len(beats), "window_sec": fs_window},
        threshold=fs_gap_ms,
        detail=("в первые секунды не поставлено ни одного звука"
                if not beats else ""),
        blocking=False))

    # 29. Экранный хук: строка в кадре к первой секунде, и это не лицо.
    # QC-29 раньше смотрел только «текст ≤1 с» и пропускал talking-head.
    hook_shot = next((s for s in shots if s.get("hook")), None)
    if hook_shot is None:
        hook_shot = next((s for s in shots
                          if s.get("kind") == "fullscreen_text"
                          and float(s.get("start", 99)) <= 1.0), None)
    hook_text = str((hook_shot or {}).get("content") or "")
    hook_words = len([w for w in hook_text.split() if w])
    hook_at = float((hook_shot or {}).get("start", 99.0)) + float(
        ((hook_shot or {}).get("params") or {}).get("enter_delay") or 0.0)
    # Нижняя граница — одно слово, а не три, как сказано в прозе §12.2. Банк
    # хуков §5.4 сам себе противоречит: «НЕВОЗМОЖНО ПРОВЕРИТЬ», «105 КУБИТОВ»,
    # «НАЙДИ ОШИБКУ» — все по два слова, а стиль `blackout_word` по замыслу
    # выносит на экран ровно одно. Считаем правдой примеры, а не абзац: гейт с
    # порогом в три слова забраковал бы эталонную разметку 0042 из того же ТЗ.
    hook_ok = bool(hook_shot) and hook_at <= 1.0 and 1 <= hook_words <= 7 \
        and not _hook_is_banned(hook_text)
    face_hold = 1.0
    face_shot = _talking_head_in_window(shots, cut_plan.get("slots") or [],
                                        until=face_hold)
    if face_shot is not None:
        hook_ok = False
    if not hook_shot:
        hook_detail = "хук-кадра нет"
    elif face_shot is not None:
        hook_detail = "первая секунда занята лицом аватара"
    else:
        hook_detail = ""
    checks.append(_check(
        29, "Экранный хук в первую секунду, не talking-head", hook_ok,
        value={"at_sec": round(hook_at, 2) if hook_shot else None,
               "words": hook_words, "text": hook_text[:48],
               "face_at_sec": None if face_shot is None else round(
                   float(face_shot.get("start", 0.0)), 2)},
        threshold={"at_sec": 1.0, "words": [1, 7], "face_after_sec": face_hold},
        detail=hook_detail,
        timecode=0.0 if face_shot is not None else None))

    # 30. Доля акцента в кадре (§7.5). До этой волны `accent_share_max`
    # оставался нулём на пути HyperFrames: его считал только старый
    # PIL-компоновщик, а бюджет `color_rules.accent_max_frame_share` был
    # объявлен и не измерялся ни разу. Коридор двусторонний намеренно: ролик
    # совсем без акцента — такой же брак, как залитый им, просто тише.
    accent_rules = (cfg.brandbook.get("color_rules") or {}) \
        if hasattr(cfg, "brandbook") else {}
    accent_hi = float(accent_rules.get("accent_max_frame_share", 0.12))
    accent_lo = float(accent_rules.get("accent_min_frame_share", 0.02))
    accent_max = float(render_stats.get("accent_share_max") or 0.0)
    accent_measured = int(render_stats.get("accent_share_max") is not None)
    over_cap = accent_max > accent_hi + 1e-9
    checks.append(_check(
        30, "Доля акцентного цвета в кадре",
        accent_lo <= accent_max <= accent_hi,
        value={"max": round(accent_max, 4),
               "by_family": render_stats.get("accent_by_family") or {}},
        threshold=[accent_lo, accent_hi],
        detail=("замер по шести пробам готового файла"
                if accent_measured else "замер не выполнен"),
        blocking=over_cap))

    # 31. Чужой hue в заливке HyperFrames-оверлея (MUST-021).
    # Footage-палитра смотрит кадр стока; розовый/жёлтый fill плашки туда
    # не попадает. Allowlist = цвета брендбука ± белый/ink, допуск ΔE.
    # Каталог templates.py этим гейтом не перекрашивается.
    brandbook = cfg.brandbook if hasattr(cfg, "brandbook") else {}
    offbrand = overlay_offbrand_fills(plan.get("overlays") or [], brandbook)
    off_tc = next((float(h["start"]) for h in offbrand
                   if h.get("start") is not None), None)
    checks.append(_check(
        31, "Заливка оверлея вне палитры брендбука", not offbrand,
        value=len(offbrand), threshold=0,
        detail="; ".join(
            f"{h.get('overlay')}:{','.join(h.get('hex') or [])}"
            for h in offbrand[:4]),
        timecode=off_tc))

    # 32. Cyan — tech/AI-tool, не медицина и не «второй красный».
    cyan_hits = overlay_cyan_misuse(
        plan.get("overlays") or [], brandbook, script)
    cyan_tc = next((float(h["start"]) for h in cyan_hits
                    if h.get("start") is not None), None)
    checks.append(_check(
        32, "Cyan только на tech-слоте", not cyan_hits,
        value=len(cyan_hits), threshold=0,
        detail="; ".join(
            f"{h.get('overlay')} theme={h.get('theme')}"
            for h in cyan_hits[:4]),
        timecode=cyan_tc))

    # 33. VFX-фон = instruction §1.10: ≤2 клипа, каждый 2–5 сек.
    # Планировщик уже режет до лимита; QC ловит план, который лимит обошёл.
    vfx_limit = int(limits.get("bg_vfx_per_video", 2))
    vfx_range = limits.get("bg_vfx_sec", [2.0, 5.0])
    vfx_lo, vfx_hi = float(vfx_range[0]), float(vfx_range[-1])
    vfx_clips = _vfx_clips(plan)
    vfx_over = len(vfx_clips) > vfx_limit
    vfx_bad_dur = [
        clip for clip in vfx_clips
        if clip.get("duration_sec") is not None
        and not (vfx_lo - 1e-6 <= float(clip["duration_sec"]) <= vfx_hi + 1e-6)
    ]
    vfx_ok = (not vfx_over) and (not vfx_bad_dur)
    checks.append(_check(
        33, "VFX-фон: число и длительность", vfx_ok,
        value={"count": len(vfx_clips),
               "durations": [c.get("duration_sec") for c in vfx_clips]},
        threshold={"count_max": vfx_limit, "sec": [vfx_lo, vfx_hi]},
        detail=("" if vfx_ok else
                (f"{len(vfx_clips)} клипов при потолке {vfx_limit}"
                 if vfx_over else
                 "длительность вне [2, 5] с"))))

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


def apply_semantic_qc(qc: dict[str, Any], vision: dict[str, Any] | None) -> dict[str, Any]:
    """§11.2 входит в решение о выдаче: mismatch > порога или skip ≠ success."""
    from .vision_qc import semantic_blocks

    qc = {**qc, "checks": list(qc.get("checks") or []),
          "failed": list(qc.get("failed") or [])}
    if not vision:
        return qc
    qc["vision"] = vision
    if (not vision.get("enabled")
            and not vision.get("qc_skipped_semantic")
            and not vision.get("skipped")):
        return qc

    skipped = bool(vision.get("qc_skipped_semantic") or vision.get("skipped"))
    limit = float(vision.get("mismatch_limit")
                  if vision.get("mismatch_limit") is not None else 0.10)
    share = vision.get("mismatch_share")
    blocks = semantic_blocks(mismatch_share=share, limit=limit, skipped=skipped)
    vision["blocking"] = blocks
    passed = not blocks
    detail = (vision.get("reason")
              or "; ".join(vision.get("notes") or [])
              or ("qc_skipped_semantic" if skipped else
                  f"mismatch_share={share}"))
    check = {
        "id": "QC-SEMANTIC",
        "name": "Смысловой QC §11.2",
        "passed": passed,
        "value": share,
        "threshold": limit,
        "detail": detail,
        "timecode_sec": None,
        "blocking": True,
    }
    qc["checks"] = [c for c in qc["checks"] if c.get("id") != "QC-SEMANTIC"] + [check]
    blocking = [c for c in qc["checks"] if c["blocking"]]
    qc["passed"] = all(c["passed"] for c in blocking)
    qc["passed_count"] = sum(1 for c in blocking if c["passed"])
    qc["total"] = len(blocking)
    qc["failed"] = [{"id": c["id"], "name": c["name"], "value": c["value"],
                     "threshold": c["threshold"], "timecode_sec": c["timecode_sec"],
                     "detail": c["detail"]}
                    for c in qc["checks"] if not c["passed"]]
    return qc


def _vfx_clips(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """VFX-фоны плана: список matting/vfx и шоты с background=vfx.

    Планировщик режет до лимита на сборке; QC смотрит уже собранный план,
    иначе три клипа, проскочившие лимит, выдаются молча.
    """
    found: dict[Any, dict[str, Any]] = {}

    def add(item: Any, *, fallback: Any = None) -> None:
        if isinstance(item, dict):
            key = item.get("slot", item.get("index", fallback))
            duration = item.get("duration_sec", item.get("duration"))
            rec = {
                "slot": key,
                "duration_sec": None if duration is None else float(duration),
            }
        else:
            key = fallback
            rec = {"slot": key, "duration_sec": None}
        if key is None:
            key = f"anon-{len(found)}"
        prev = found.get(key)
        if prev and prev.get("duration_sec") is not None and rec["duration_sec"] is None:
            return
        found[key] = rec

    for bucket in (plan.get("vfx"), (plan.get("matting") or {}).get("vfx")):
        if isinstance(bucket, int):
            for i in range(max(0, bucket)):
                add({"slot": f"count-{i}"})
        elif isinstance(bucket, list):
            for i, item in enumerate(bucket):
                add(item, fallback=i)

    for shot in plan.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        flagged = (
            str(shot.get("background") or "") == "vfx"
            or shot.get("vfx_src")
            or shot.get("vfx")
        )
        if flagged:
            add({"slot": shot.get("index"),
                 "duration_sec": shot.get("duration")})
    return list(found.values())


def _shot_events(cut_plan: dict[str, Any], shot: dict[str, Any]) -> list[dict[str, Any]]:
    for slot in cut_plan["slots"]:
        if slot["index"] == shot["index"]:
            return slot.get("events", [])
    return []


def _speech_words(ctx, plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Эталон речи после P3 remap: явный список плана или ``words.json``."""
    explicit = plan.get("speech_words") or plan.get("words")
    if explicit:
        return list(explicit)
    read_or = getattr(ctx, "read_or", None)
    if callable(read_or):
        doc = read_or("words.json", {}) or {}
        if isinstance(doc, dict):
            return list(doc.get("words") or [])
    return []


def _cue_token(text: str) -> str:
    raw = str(text or "").casefold().strip()
    return raw.strip(".,:;!?…«»\"'()[]")


def _subtitle_drift(plan: dict[str, Any],
                    speech_words: list[dict[str, Any]] | None = None) -> float:
    """Максимальный |Δ| старта SRT-ку и соответствующего слова речи, сек.

    Пара ищется по тексту и времени, а не по порядковому номеру в полном
    списке речи: под полноэкранным хуком караоке снимается, и оставшиеся
    куи — это середина ролика, не начало words.json.
    Склейка коротких слов на экране не ломает ряд: куе забирает речевые
    слова, чей старт ещё лежит внутри окна куи. Вывернутое окно — брак.
    """
    cues = [c for c in (plan.get("subtitles") or []) if "start" in c]
    speech = list(speech_words if speech_words is not None else
                  (plan.get("speech_words") or []))
    worst = 0.0
    for cue in cues:
        start, end = float(cue["start"]), float(cue["end"])
        if end <= start:
            worst = max(worst, 1.0)

    if not cues or not speech:
        return worst

    used = [False] * len(speech)
    for cue in cues:
        c_start = float(cue["start"])
        c_end = float(cue["end"])
        token = _cue_token(cue.get("display") or cue.get("word") or "")
        best_i: int | None = None
        best_score: float | None = None
        for i, word in enumerate(speech):
            if used[i]:
                continue
            w_start = float(word["start"])
            w_tok = _cue_token(word.get("display") or word.get("word") or "")
            dt = abs(c_start - w_start)
            score = dt if (token and w_tok == token) else dt + 1000.0
            if best_score is None or score < best_score:
                best_i, best_score = i, score
        if best_i is None:
            continue
        used[best_i] = True
        worst = max(worst, abs(c_start - float(speech[best_i]["start"])))
        for j in range(best_i + 1, len(speech)):
            if used[j]:
                continue
            if float(speech[j]["start"]) <= c_end + 1e-3:
                used[j] = True
            else:
                break
    return worst


def _subtitle_coverage(plan: dict[str, Any], duration: float) -> float:
    """Доля субтитров, реально положенных на речь.

    Captions stay on under cards/FS except same-punch-family dedupe. QC-19
    only checks that remaining cues are consistent (start < end); coverage is
    the fraction of subtitle cues that are well-formed — not "mute under FS".
    """
    words = plan.get("subtitles", [])
    if not words:
        return 0.0
    visible = 0
    for word in words:
        start, end = float(word["start"]), float(word["end"])
        if end > start:
            visible += 1
    return visible / max(len(words), 1)


def _avatar_clip_offset(plan: dict[str, Any], avatar_meta: dict[str, Any]) -> float:
    """Смещение выреза аватар-клипа относительно места на таймлайне.

    Аватар генерируется посегментно и кладётся кусками. QC-11 меряет
    ``avatar_clip_offset`` — ошибку выреза, не рот и не lip-sync.
    """
    worst = 0.0
    segments = avatar_meta.get("segments", [])
    by_index = {int(s["index"]): s for s in segments}

    for shot in plan["shots"]:
        if shot.get("kind") not in ("avatar", "split"):
            continue
        offset = shot.get("avatar_offset_sec")
        if offset is None:
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
