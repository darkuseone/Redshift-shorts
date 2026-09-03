"""P8: ``candidates.json`` → ``accepted_assets.json``.

Трёхступенчатая оценка §7.3. Шаг 1 (дешёвая отбраковка без vision) уже отработал
в P7 — там он экономит не только вызовы модели, но и скачивания. Здесь работают
шаги 2 и 3:

* **Шаг 2 — критик со зрением.** Все прошедшие кандидаты, для видео — 3 кадра.
  Исполнитель Gemini (дешевле). Возвращает score 0.0–1.0 и причину.
* **Шаг 3 — арбитраж Grok.** Только спорные: score в [0.45, 0.70], либо
  расхождение оценок кадров одного видео > 0.3, либо роль блока
  ``evidence``/``twist``. Жёсткий лимит — 8 вызовов на ролик. Решение финальное.

Пороги: ≥0.70 принять, <0.45 отклонить. Незакрытый слот уходит в генерацию (P9),
а **не** заполняется слабым футажом — это прямое требование §7.3.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..lib.logging import get_logger
from ..lib.manifest import AssetRecord, FootageIndex, new_id
from ..lib.palette import frame_light, palette_verdict
from ..lib.providers.vision import VisionVerdict, build_vision_provider

_log = get_logger("p8")


def _needs_arbitration(verdict: VisionVerdict, role: str, cfg) -> str | None:
    """Триггеры шага 3 (§7.3). Возвращает причину или None."""
    lo = float(cfg.get("vision.reject_threshold", 0.45))
    hi = float(cfg.get("vision.accept_threshold", 0.70))
    disagree = float(cfg.get("vision.frame_disagreement_threshold", 0.30))
    if lo <= verdict.score <= hi:
        return f"score {verdict.score:.2f} в спорной зоне [{lo}, {hi}]"
    if verdict.frame_disagreement > disagree:
        return f"кадры расходятся на {verdict.frame_disagreement:.2f} > {disagree}"
    if role in ("evidence", "twist"):
        return f"роль блока {role} — цена ошибки выше обычной"
    return None


def belongs_to_its_source(entry: dict[str, Any]) -> bool:
    """Материал, который нельзя переиспользовать в другом ролике (§14.4).

    Кадр со страницы статьи принадлежит своей статье: в общей базе он стал бы
    доступен любому сюжету — и вместе с ним исчезло бы единственное основание
    его показывать, та самая страница рядом в кадре.
    """
    return str(entry.get("origin") or "") == "press"


def _same_intent(left: str, right: str) -> bool:
    """Тот же ли это по сути слот, для которого оценка ставилась.

    Сравнение по словам, а не побуквенно: реплики разных роликов формулируют
    один и тот же кадр по-разному («трещиноватый гранит крупным планом» и
    «крупный план гранита»), и требовать точного совпадения значило бы
    пересуживать один и тот же кадр каждый прогон. Половина общих слов —
    порог, при котором слоты ещё про одно и то же.
    """
    def words(text: str) -> set[str]:
        # Сравниваются основы, а не слова целиком: по-русски один и тот же
        # кадр называют «трещиноватый гранит крупным планом» и «крупный план
        # трещиноватого гранита» — общих слов ноль, смысл один.
        return {w[:4] for w in re.findall(r"\w{4,}", str(text).lower())}

    a, b = words(left), words(right)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.5


def run_step(ctx) -> dict[str, Any]:
    doc = ctx.read("candidates.json")
    plan = ctx.read("cut_plan.json")
    cfg = ctx.cfg

    accept_threshold = float(cfg.get("vision.accept_threshold", 0.70))
    reject_threshold = float(cfg.get("vision.reject_threshold", 0.45))
    arbiter_budget = int(cfg.get("vision.arbiter_max_calls", 8))

    primary = build_vision_provider(cfg, ctx.costs, role="primary")
    arbiter = build_vision_provider(cfg, ctx.costs, role="arbiter")
    index = FootageIndex.load(cfg)

    slots_by_index = {s["index"]: s for s in plan["slots"]}
    by_slot: dict[int, list[dict[str, Any]]] = {}
    for candidate in doc["candidates"]:
        by_slot.setdefault(candidate["slot_index"], []).append(candidate)

    palette_rules = dict(cfg.brandbook.get("color_rules", {}).get("footage_palette", {}))

    judged: list[dict[str, Any]] = []
    accepted: dict[int, dict[str, Any]] = {}
    arbiter_calls = 0
    reused_scores = 0
    rejected_by_palette = 0
    rejected_by_dark = 0
    # Порог светлоты перебивки. Замер по базе: медиана 55 % видимого, у клипа,
    # давшего чёрную перебивку в 0047, — 16 %.
    visible_min = float(ctx.cfg.get("stock.interstitial_visible_min", 0.20))

    for slot_index in sorted(by_slot):
        slot = slots_by_index.get(slot_index, {})
        role = slot.get("role", "")
        intent = slot.get("visual_intent", "") or slot.get("reason", "")

        # Мем из собственной базы vision не судит: он отобран вручную (§14.3),
        # кадров для оценки у него нет, а «смысловое соответствие» у мема —
        # это ирония реплики, а не совпадение с visual_intent.
        library_memes = [c for c in by_slot[slot_index] if c.get("origin") == "meme_library"]
        if library_memes:
            entry = {**library_memes[0], "score": 1.0,
                     "decision": "accept_library",
                     "verdict": {"score": 1.0, "judge": "library",
                                 "reason": "карточка из курированной базы мемов (§14.3)",
                                 "summary": "", "frames": 0}}
            accepted[slot_index] = entry
            judged.append(entry)
            continue

        scored: list[tuple[float, dict[str, Any]]] = []
        for candidate in by_slot[slot_index]:
            # Материал из локальной базы уже оценивался — платить второй раз
            # за тот же кадр нельзя (§7.2.1, идемпотентность §7.6). Но оценка
            # принадлежит паре «кадр + смысл слота», а не кадру: судья отвечал
            # на вопрос «подходит ли снимок вот этой реплике». Перенести её на
            # другой слот значит утверждать то, чего никто не проверял —
            # снимок галактики получил бы 0.9 в кадре про буровую, потому что
            # у слотов совпал тег «space».
            #
            # Вечнозелёная база вскрыла это ребром: её записи не судились ни
            # разу, у них стоит ровный SEED_SCORE 0.62 при пороге приёма 0.70,
            # и по этому пути весь засев навсегда оставался «borderline».
            reusable = (candidate.get("prior_score")
                        and candidate.get("prior_intent")
                        and _same_intent(candidate.get("prior_intent", ""), intent))
            if candidate.get("origin") == "local_cache" and reusable:
                verdict_dict = {
                    "score": float(candidate["prior_score"]),
                    "reason": "оценка переиспользована из локальной базы",
                    "summary": candidate.get("vision_summary", ""),
                    "judge": "cache", "frames": 0,
                }
                reused_scores += 1
            else:
                frames = [Path(f) for f in candidate.get("frames", [])]
                verdict = primary.judge(frames, intent=intent, role=role,
                                        query=candidate.get("query", ""))
                verdict_dict = verdict.to_dict()

                reason = _needs_arbitration(verdict, role, cfg)
                if reason and arbiter_calls < arbiter_budget:
                    arbiter_calls += 1
                    final = arbiter.judge(frames, intent=intent, role=role,
                                          query=candidate.get("query", ""))
                    verdict_dict = final.to_dict()
                    verdict_dict["arbitrated"] = True
                    verdict_dict["arbitration_reason"] = reason
                    verdict_dict["primary_score"] = round(verdict.score, 4)
                elif reason:
                    verdict_dict["arbitration_skipped"] = (
                        f"{reason}; лимит арбитража {arbiter_budget} исчерпан")

            # Цвет судится отдельно от смысла и бесплатно: кадры кандидата
            # уже лежат на диске. Судья со зрением оценивает соответствие
            # речи и про палитру канала не знает — на 0047 он принял стену из
            # ярко-розовых кубов по запросу «dark red gradient».
            palette = palette_verdict(
                [Path(f) for f in candidate.get("frames", [])], palette_rules)

            # Светлота судится только у перебивки. Общий порог зарезал бы
            # ночную эстетику канала: в базе восемь клипов из сорока четырёх
            # темнее 15 % видимого, и в длинном кадре под речь они законны.
            # Перебивка — другое: 1.4 секунды, ради того чтобы в кадре что-то
            # произошло. В 0047 на 40.5 и 50.0 сек там оказался субтитр на
            # пустоте, средняя яркость 17.7 и 20.1 из 255.
            light = (frame_light([Path(f) for f in candidate.get("frames", [])])
                     if slot.get("asset_role") == "interstitial" else None)

            entry = {**candidate, "verdict": verdict_dict, "intent": intent,
                     "score": float(verdict_dict["score"]), "palette": palette}
            if light is not None:
                entry["light"] = light
            entry["decision"] = (
                "accept" if entry["score"] >= accept_threshold
                else "reject" if entry["score"] < reject_threshold
                else "borderline")
            if light is not None and light["visible_share"] < visible_min:
                # Перебивка в черноту — не перебивка. Отказ, а не штраф:
                # §7.3 велит незакрытый слот отправлять в генерацию, а не
                # затыкать материалом, который в кадре ничего не показывает.
                entry["decision"] = "reject_dark"
                entry["reject_reason"] = (
                    f"перебивке видно {light['visible_share']:.0%} кадра при пороге "
                    f"{visible_min:.0%}: зритель увидит субтитр на пустоте")
                rejected_by_dark += 1
                _log.info("кандидат отклонён по темноте", extra={
                    "slot": slot_index, "asset": candidate.get("asset_id"),
                    "visible_share": light["visible_share"]})
                judged.append(entry)
                continue
            if not palette["passed"]:
                # Отказ, а не штраф к оценке: §7.3 велит незакрытый слот
                # отправлять в генерацию, а не затыкать слабым материалом.
                # Кадр не той палитры — ровно такой слабый материал.
                entry["decision"] = "reject_palette"
                entry["reject_reason"] = palette["reason"]
                rejected_by_palette += 1
                _log.info("кандидат отклонён по палитре", extra={
                    "slot": slot_index, "asset": candidate.get("asset_id"),
                    "off_share": palette["off_share"]})
            judged.append(entry)
            if entry["decision"] != "reject_palette":
                scored.append((entry["score"], entry))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        best = next((entry for score, entry in scored if score >= accept_threshold), None)
        if best is None and scored:
            top_score, top_entry = scored[0]
            # Спорный кандидат берём только если арбитраж уже был исчерпан:
            # иначе §7.3 требует отправить слот в генерацию.
            if top_score >= reject_threshold and arbiter_calls >= arbiter_budget:
                best = top_entry
                best["decision"] = "accept_fallback"
                best["fallback_reason"] = (
                    "лимит арбитража исчерпан, принят лучший из спорных")
        if best is not None:
            accepted[slot_index] = best

    # --- пополнение локальной базы (§14.4, §14.6) ----------------------------
    added_to_index = 0
    memes_used: list[str] = []
    for entry in accepted.values():
        if entry.get("origin") == "meme_library":
            # Мемы живут в своей библиотеке с лимитом 100 (§14.3), в индексе
            # футажей им делать нечего.
            memes_used.append(entry["asset_id"])
            continue
        if belongs_to_its_source(entry):
            continue
        if entry.get("origin") == "local_cache":
            index.mark_used(entry["asset_id"], doc["video_id"])
            continue
        if index.by_id(entry["asset_id"]) is not None:
            index.mark_used(entry["asset_id"], doc["video_id"])
            continue
        index.add(AssetRecord(
            id=entry["asset_id"] or new_id(),
            type=entry.get("kind", "video"),
            source=entry.get("source", "unknown"),
            license=entry.get("license", ""),
            url_origin=entry.get("page_url", ""),
            phash=(entry.get("phashes") or [""])[0],
            phashes=entry.get("phashes", []),
            tags=entry.get("tags", []),
            vision_summary=entry.get("verdict", {}).get("summary", ""),
            score=entry.get("score", 0.0),
            duration_sec=entry.get("duration_sec", 0.0),
            width=entry.get("width", 0), height=entry.get("height", 0),
            file=entry.get("storage_key", ""),
            used_in=[doc["video_id"]],
            ai_generated=bool(entry.get("ai_generated")),
            mock=bool(entry.get("mock")),
            extra={"attribution": entry.get("attribution", ""),
                   "author": entry.get("author", ""),
                   # Смысл слота, за который оценка получена: без него она
                   # не переиспользуема — см. _same_intent.
                   "judged_intent": entry.get("intent", "")},
        ))
        added_to_index += 1
    index.save()

    if memes_used:
        from ..lib.manifest import open_library

        library = open_library(cfg, "memes")
        for meme_id in memes_used:
            library.mark_used(meme_id, doc["video_id"])
        library.save()

    asset_slots = [s["index"] for s in plan["slots"]
                   if s["needs_asset"]
                   and s["asset_role"] in ("broll", "evidence", "meme", "interstitial")]
    unfilled = [i for i in asset_slots if i not in accepted]

    result = {
        "video_id": doc["video_id"],
        "accept_threshold": accept_threshold,
        "reject_threshold": reject_threshold,
        "arbiter_calls": arbiter_calls,
        "arbiter_budget": arbiter_budget,
        "reused_scores": reused_scores,
        "rejected_by_palette": rejected_by_palette,
        "rejected_by_dark": rejected_by_dark,
        "judged_count": len(judged),
        "accepted_count": len(accepted),
        "slots_total": len(asset_slots),
        "slots_filled": len(accepted),
        "fill_rate": round(len(accepted) / max(len(asset_slots), 1), 4),
        "unfilled_slots": unfilled,
        "added_to_index": added_to_index,
        "accepted": {str(k): v for k, v in sorted(accepted.items())},
        "judged": judged,
    }
    ctx.write("accepted_assets.json", result)

    if unfilled:
        ctx.warn(f"{len(unfilled)} слотов не закрыты футажом — уйдут в генерацию P9 (§7.3)",
                 slots=unfilled)
    if rejected_by_dark:
        ctx.warn(f"{rejected_by_dark} кандидатов отклонены как слишком тёмные для "
                 f"перебивки (порог {visible_min:.0%} видимого кадра)")
    if rejected_by_palette:
        ctx.warn(f"{rejected_by_palette} кандидатов отклонены по палитре канала "
                 f"(§3.1): посторонний цвет занимал больше "
                 f"{float(palette_rules.get('off_share_max', 0.15)):.0%} кадра")
    _log.info("оценка футажей завершена", extra={
        "judged": len(judged), "accepted": len(accepted),
        "fill_rate": result["fill_rate"], "arbiter_calls": arbiter_calls,
        "reused": reused_scores, "unfilled": len(unfilled),
        "rejected_by_palette": rejected_by_palette,
        "rejected_by_dark": rejected_by_dark,
    })
    return {"accepted": len(accepted), "fill_rate": result["fill_rate"],
            "arbiter_calls": arbiter_calls}
