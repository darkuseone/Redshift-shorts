"""P9: пустые слоты → ``generated_assets.json``.

§7.3: «Незакрытый слот идёт в генерацию, а не заполняется слабым футажом».
Здесь и только здесь закрываются слоты, которые не смог закрыть поиск.

Ограничения, которые шаг обязан соблюсти:

* доля чисто AI-generated футажа ≤ 40 % хронометража (§7.2.6, QC-14) — если
  генерация выведет ролик за этот потолок, слот остаётся пустым, и это
  фиксируется как проблема плана, а не заметается генерацией;
* платные модели ≤ 3–7 % случаев (§7.7), приоритет бесплатным;
* сгенерированный материал попадает в локальную базу с честной пометкой
  ``ai_generated`` — иначе счётчик доли AI со временем начнёт врать.
"""

from __future__ import annotations

from typing import Any

from ..lib.ffmpeg import extract_frames, probe
from ..lib.logging import get_logger
from ..lib.manifest import FootageIndex
from ..lib.phash import phash_image
from ..lib.providers.generation import build_generation_provider
from ..lib.providers.vision import build_vision_provider
from ..lib.query import build_queries

_log = get_logger("p9")

# Сколько раз пробовать пересобрать материал, если он вышел дублем.
GENERATION_ATTEMPTS = 3
VARIATIONS = (
    "different colour temperature and camera angle",
    "different composition, subject off-centre",
    "different texture and depth of field",
)


def _find_duplicate(hashes: list[str], pool: list[tuple[str, list[str]]],
                    threshold: int) -> str | None:
    from ..lib.phash import video_is_duplicate

    for item_id, known in pool:
        if video_is_duplicate(hashes, known, threshold):
            return item_id
    return None


def _prompt_for_slot(slot: dict[str, Any], plan: dict[str, Any]) -> str:
    """Промпт из смысла блока — тот же принцип, что и у поисковых запросов."""
    queries = build_queries(slot, plan, count=3)
    intent = slot.get("visual_intent") or queries[0]
    role = slot.get("role", "")
    # Запреты в промпте — не украшение. Заказчик просил, чтобы кадр не читался
    # как AI-генерация, а узнаётся она в первую очередь по «нарисованности»:
    # 3D-рендер, иллюстрация, вылизанный глянец без единой случайной детали.
    # Поэтому кадр просится фотографический, снятый камерой, с оптикой и
    # зерном — тем, чего у иллюстрации не бывает.
    # Оптика и точка съёмки меняются от слота к слоту. Без этого модель
    # выдаёт свой любимый кадр: на 0047 три сгенерированных слота подряд стали
    # одним и тем же раскалённым камнем в пустыне с разных сторон. Выбор
    # детерминирован индексом слота — прогон обязан собираться одинаково.
    look = _LOOKS[int(slot.get("index", 0)) % len(_LOOKS)]
    style = ("documentary photograph, real location, shot on a full-frame camera, "
             f"{look}, natural available light, true-to-life colour, fine film grain, "
             "imperfect detail, vertical 9:16 framing with empty space in the lower "
             "third for a caption, muted palette with a single warm red accent, "
             "photorealistic — not an illustration, not a 3d render, not CGI, "
             "no glossy studio product look, no text, no logos, no watermark")
    return f"{intent}. {queries[0]}. Role: {role}. Style: {style}"


# Оптика, ракурс и дистанция. Список короткий и предметный: каждая строка
# меняет кадр целиком, а не добавляет прилагательное.
_LOOKS = (
    "35mm lens, eye level, subject slightly off-centre, shallow depth of field",
    "85mm lens, tight detail, compressed perspective, background falls away",
    "24mm wide lens, low angle, foreground element entering the frame",
    "50mm lens, handheld, slight motion blur, over-the-shoulder distance",
    "macro lens, extreme close detail, texture filling the frame",
    "telephoto from a distance, layered depth, haze between planes",
)


def run_step(ctx) -> dict[str, Any]:
    plan = ctx.read("cut_plan.json")
    accepted_doc = ctx.read("accepted_assets.json")
    cfg = ctx.cfg

    slots_by_index = {s["index"]: s for s in plan["slots"]}
    unfilled = list(accepted_doc.get("unfilled_slots", []))
    duration = float(plan["duration_sec"])
    ai_share_max = float(cfg.get("limits.ai_footage_share_max", 0.40))
    paid_share_limit = float(cfg.get("magnific.paid_model_share_limit", 0.07))
    prefer_free = bool(cfg.get("magnific.prefer_free_models", True))

    # Сколько AI-материала уже в ролике: генерация добавляется поверх него.
    ai_sec = sum(
        float(slots_by_index.get(int(k), {}).get("duration", 0.0))
        for k, entry in accepted_doc.get("accepted", {}).items()
        if entry.get("ai_generated")
    )
    ai_budget_sec = max(0.0, ai_share_max * duration - ai_sec)

    provider = build_generation_provider(cfg, ctx.costs)
    # Сгенерированный кадр судится тем же судьёй, что и сток. До сих пор он
    # проверялся только на дубль по pHash — то есть на «не такой, как соседи», а
    # не на «годится ли вообще». В ролике 0047 так и вышло: на 21 и 24 секунде
    # встал «раскалённый камень в пустыне», который судья §11.2 потом честно
    # назвал стоковым и не про гранит. Заказчик просил использовать генерацию
    # только там, где она выходит качественно, — а решить это можно, только
    # посмотрев на результат.
    critic = build_vision_provider(cfg, ctx.costs, role="primary")
    # Порог мягче, чем у стока: сгенерированный кадр — запасной путь, и
    # требовать от него оценки принятия значит оставить слоты пустыми. Но ниже
    # порога отбраковки он в монтаж не идёт: там начинается тот самый вид,
    # ради которого всё это и затевалось.
    min_score = float(cfg.get("vision.generated_min_score",
                              cfg.get("vision.reject_threshold", 0.45)))
    index = FootageIndex.load(cfg)
    dedup_threshold = int(cfg.get("stock.dedup_hamming_max", 8))

    # Сравниваем и с принятым материалом, и с уже сгенерированным в этом прогоне.
    seen_hashes: list[tuple[str, list[str]]] = [
        (entry.get("asset_id", key), entry.get("phashes") or [])
        for key, entry in accepted_doc.get("accepted", {}).items()
        if entry.get("phashes")
    ]

    generated: dict[str, Any] = {}
    skipped: list[dict[str, Any]] = []
    paid_used = 0

    for slot_index in unfilled:
        slot = slots_by_index.get(slot_index)
        if slot is None:
            continue
        if slot.get("asset_role") == "meme":
            # §14.3: мем не генерируется. Пустой мем-слот — это сигнал наполнить
            # библиотеку, а не повод синтезировать «что-то смешное».
            skipped.append({
                "slot": slot_index,
                "reason": "мем не генерируется (§14.3): наполните библиотеку — "
                          "python -m src.cli fill-libraries --kind memes",
            })
            continue
        slot_duration = float(slot["duration"])
        if slot_duration > ai_budget_sec:
            skipped.append({
                "slot": slot_index,
                "reason": (f"генерация вывела бы долю AI-футажа за {ai_share_max:.0%} "
                           f"(§7.2.6): остаток бюджета {ai_budget_sec:.1f} сек, "
                           f"нужно {slot_duration:.1f} сек"),
            })
            continue

        base_prompt = _prompt_for_slot(slot, plan)
        asset_verdict = None
        # Платные модели — редкое исключение (§7.7), считаем их долю честно.
        use_free = prefer_free or (paid_used + 1) / max(len(unfilled), 1) > paid_share_limit
        out = ctx.wpath("broll", "generated", f"slot_{slot_index:02d}.mp4")

        # Абстрактный сгенерированный B-roll легко получается похожим сам на
        # себя. QC-5 запрещает визуальные дубли в ролике, поэтому проверяем
        # результат тем же pHash и при совпадении пересобираем с другим
        # акцентом в промпте, а не отдаём дубль в монтаж.
        asset = None
        hashes: list[str] = []
        info = None
        rejected_attempts: list[str] = []
        for attempt in range(GENERATION_ATTEMPTS):
            prompt = base_prompt if attempt == 0 else f"{base_prompt}. Variation {attempt}: {VARIATIONS[attempt % len(VARIATIONS)]}"
            candidate = provider.generate(prompt, out, kind="video",
                                          duration_sec=max(slot_duration + 0.6, 2.0),
                                          prefer_free=use_free)
            candidate_info = probe(candidate.path)
            candidate_frames = extract_frames(
                candidate.path, ctx.wpath("broll", "frames", candidate.id, ".keep").parent,
                cfg.get("stock.video_probe_frames", [0.1, 0.5, 0.9]))
            candidate_hashes = [phash_image(f) for f in candidate_frames]

            duplicate = _find_duplicate(candidate_hashes, seen_hashes, dedup_threshold)
            if duplicate is not None:
                rejected_attempts.append(f"похож на {duplicate}")
                continue

            verdict = critic.judge(
                candidate_frames,
                intent=str(slot.get("visual_intent") or slot.get("reason") or ""),
                role=str(slot.get("role") or ""), query=prompt)
            if verdict.score < min_score:
                rejected_attempts.append(
                    f"судья {verdict.score:.2f} < {min_score:.2f}: {verdict.reason[:120]}")
                continue

            asset, info, hashes = candidate, candidate_info, candidate_hashes
            frames = candidate_frames
            asset_verdict = verdict
            break

        if asset is None:
            # Пустой слот честнее плохого кадра: его видно в отчёте, а слабую
            # генерацию видно только зрителю.
            skipped.append({
                "slot": slot_index,
                "reason": (f"генерация не дала годного кадра "
                           f"({'; '.join(rejected_attempts)}) — слот оставлен пустым"),
            })
            continue

        if asset.paid_model:
            paid_used += 1
        seen_hashes.append((asset.id, hashes))

        entry = {
            **asset.to_dict(),
            "slot_index": slot_index, "origin": "generated",
            "asset_id": asset.id, "source": "magnific",
            "local_file": str(asset.path), "frames": [str(f) for f in frames],
            "phashes": hashes, "license_confirmed": True,
            "duration_sec": info.duration_sec or asset.duration_sec,
            "width": info.width or asset.width, "height": info.height or asset.height,
            "tags": ["generated", slot.get("role", ""), "abstract"],
            "attribution": "REDSHIFT / generated",
            # Оценка — от судьи, а не единица по умолчанию. «Материал сделан под
            # слот, релевантность гарантирована» — ровно то предположение, из-за
            # которого в 0047 встал раскалённый камень вместо гранита: модель
            # рисует по промпту, а не по смыслу блока, и проверить это можно
            # только взглядом.
            "score": round(float(asset_verdict.score), 4) if asset_verdict else 0.5,
            "vision_summary": asset_verdict.summary if asset_verdict else "",
            "verdict": asset_verdict.to_dict() if asset_verdict else {},
        }
        generated[str(slot_index)] = entry
        ai_budget_sec -= slot_duration

        # В общую библиотеку сгенерированный кадр не кладётся. Библиотека
        # живёт в репозитории и просматривается раньше внешних стоков — накопив
        # там AI, конвейер начал бы предпочитать его настоящему кадру, ровно
        # вопреки правилу «преимущество всегда за реальным материалом».
        # Повторить генерацию дёшево, а место в истории git не возвращается
        # никогда. Паспорт кадра остаётся в отчёте прогона.
        _log.info("сгенерированный кадр в библиотеку не попадает",
                  extra={"slot": slot_index, "asset_id": asset.id})

    index.save()

    total_ai_sec = ai_sec + sum(
        float(slots_by_index[int(k)]["duration"]) for k in generated)
    doc = {
        "video_id": plan["video_id"],
        "generated_count": len(generated),
        "skipped": skipped,
        "paid_model_used": paid_used,
        "ai_footage_sec": round(total_ai_sec, 3),
        "ai_footage_share": round(total_ai_sec / max(duration, 1e-6), 4),
        "ai_share_limit": ai_share_max,
        "generated": generated,
    }
    ctx.write("generated_assets.json", doc)

    for item in skipped:
        ctx.warn(f"слот {item['slot']} остался пустым: {item['reason']}", slot=item["slot"])
    if doc["ai_footage_share"] > ai_share_max + 1e-6:
        ctx.warn(f"доля AI-футажа {doc['ai_footage_share']:.0%} превышает {ai_share_max:.0%} (QC-14)")

    _log.info("генерация завершена", extra={
        "generated": len(generated), "skipped": len(skipped),
        "ai_share": doc["ai_footage_share"], "paid_models": paid_used,
    })
    return {"generated": len(generated), "ai_share": doc["ai_footage_share"]}
