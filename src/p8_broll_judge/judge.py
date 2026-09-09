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

from ..lib.footage_seed import SEED_SCORE
from ..lib.logging import get_logger
from ..lib.manifest import AssetRecord, FootageIndex, new_id, tag_url_coherence
from ..lib.palette import frame_light, palette_verdict
from ..lib.providers.vision import VisionVerdict, build_vision_provider
from ..lib.query import (
    classify_intent, thematic_reject_reason, topical_match_score,
)
from ..p7_broll_search.search import (
    _footage_pin_entry, _load_footage_pins, footage_pool_count,
    judge_blocks_stage1_dead, pin_id_denied, surplus_report,
)

COHERENCE_MIN = 0.15

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


def watermark_reject_reason(verdict: dict[str, Any] | None,
                            candidate: dict[str, Any] | None = None) -> str:
    """Вшитая в кадр чужая подпись — жёсткий отказ, даже пину (§9.3).

    `watermark` и `has_text` зрение возвращало с самого начала
    (`vision.py:79-80`) и в отборе они не использовались **никак**. На 0042 в
    кадре 0 стоял клип с вшитым `PEXELS / GOOGLE DEEPMIND` — он лежал в
    hard-prefer пинах, поэтому движок его не трогал, и подпись чужого стока
    уехала в готовый ролик.

    Пин — это «возьми вот этот кадр», а не «возьми его любой ценой»: право
    выбирать материал у заказчика есть, право протащить чужой логотип в кадр
    канала — нет. Причина пишется в отчёт, чтобы было видно, какой пин отклонён.
    """
    verdict = verdict or {}
    if bool(verdict.get("watermark")):
        return ("в кадр вшита чужая подпись или логотип стока: "
                "показывать её в ролике канала нельзя")
    # Кандидат мог принести признак из индекса, минуя свежий вердикт.
    if candidate and bool((candidate.get("vision") or {}).get("watermark")):
        return "в индексе у кадра отмечена вшитая подпись стока"
    return ""


def _prefer_rank(asset_id: str, pin_prefer: list[str]) -> int | None:
    """Index in the pin prefer list, or None if the id is not pinned."""
    aid = str(asset_id or "")
    if not aid:
        return None
    try:
        return pin_prefer.index(aid)
    except ValueError:
        return None


def _engine_gate_reason(candidate: dict[str, Any], *, pin_deny: set[str],
                        index: FootageIndex) -> str | None:
    """Blocking gates that do not need a live judge."""
    asset_id = str(candidate.get("asset_id") or "")
    if pin_id_denied(asset_id, pin_deny):
        return f"pin_deny: {asset_id}"
    indexed = index.by_id(asset_id) if asset_id else None
    if candidate.get("quarantined") or (indexed is not None and indexed.quarantined):
        return f"quarantined: {asset_id}"
    rec: dict[str, Any] | AssetRecord | None
    if candidate.get("tags") or candidate.get("url_origin") or candidate.get("vision_summary"):
        rec = candidate
    else:
        rec = indexed
    if rec is not None:
        coherence = tag_url_coherence(rec)
        if coherence < COHERENCE_MIN:
            return f"tag_url_coherence {coherence:.2f} < {COHERENCE_MIN:.2f}"
    return None


def skip_live_verdict(candidate: dict[str, Any], intent: str) -> dict[str, Any]:
    """Honest skip_live score: never invent 0.72 above accept_threshold."""
    prior = candidate.get("prior_score")
    if prior is not None:
        score = float(prior)
        judge = "skip_live"
        reason = "skip_live: переиспользована оценка без live API"
    else:
        score = float(SEED_SCORE)
        judge = "skip_live_unverified"
        reason = "skip_live: нет live-оценки, honest-borderline SEED_SCORE"
    prior_intent = str(candidate.get("prior_intent") or "")
    if prior_intent and not _same_intent(prior_intent, intent):
        score = max(0.0, score - 0.15)
        reason += "; prior_intent mismatch −0.15"
    return {
        "score": score,
        "reason": reason,
        "summary": candidate.get("vision_summary", ""),
        "judge": judge,
        "frames": 0,
    }


def run_step(ctx) -> dict[str, Any]:
    doc = ctx.read("candidates.json")
    plan = ctx.read("cut_plan.json")
    cfg = ctx.cfg

    accept_threshold = float(cfg.get("vision.accept_threshold", 0.70))
    reject_threshold = float(cfg.get("vision.reject_threshold", 0.45))
    arbiter_budget = int(cfg.get("vision.arbiter_max_calls", 8))

    skip_live = bool(cfg.get("vision.skip_live", False))
    surplus_ratio = float(cfg.get("stock.candidate_surplus", 1.3))
    footage_slots = [
        s for s in plan.get("slots", [])
        if s.get("needs_asset") and s.get("asset_role") in ("broll", "evidence", "interstitial")
    ]
    surplus = doc.get("surplus") or surplus_report(
        footage_pool_count(doc.get("candidates") or []),
        len(footage_slots), surplus_ratio)
    paid_ok = bool(surplus.get("ok"))
    primary = None if skip_live or not paid_ok else build_vision_provider(
        cfg, ctx.costs, role="primary")
    arbiter = None if skip_live or not paid_ok else build_vision_provider(
        cfg, ctx.costs, role="arbiter")
    if skip_live:
        _log.warning("vision.skip_live: без live API — движковые гейты блокирующие")
    elif not paid_ok:
        _log.warning("surplus underfilled — paid critic (Gemini/Grok) не вызывается",
                     extra=surplus)
    index = FootageIndex.load(cfg)
    video_id = str(plan.get("video_id") or "")
    pin_deny, pin_prefer = _load_footage_pins(cfg, video_id)
    pin_entry = _footage_pin_entry(cfg, video_id)

    slots_by_index = {s["index"]: s for s in plan["slots"]}
    dead_ids = {str(row.get("id") or "") for row in (doc.get("stage1_rejected") or [])
                if row.get("id")}
    max_h = int(cfg.get("stock.max_download_height", 1080))
    by_slot: dict[int, list[dict[str, Any]]] = {}
    skipped_stage1 = 0
    for candidate in doc["candidates"]:
        blocked = judge_blocks_stage1_dead(
            candidate, dead_ids=dead_ids, max_h=max_h)
        if blocked:
            skipped_stage1 += 1
            continue
        by_slot.setdefault(candidate["slot_index"], []).append(candidate)

    palette_rules = dict(cfg.brandbook.get("color_rules", {}).get("footage_palette", {}))

    judged: list[dict[str, Any]] = []
    accepted: dict[int, dict[str, Any]] = {}
    accepted_counts: dict[str, int] = {}
    repeat_max = int(cfg.get("stock.same_asset_max_slots", 1))
    if pin_entry.get("same_asset_max_slots") is not None:
        repeat_max = int(pin_entry["same_asset_max_slots"])
    repeat_penalty = float(cfg.get("stock.repeat_score_penalty", 0.12))
    arbiter_calls = 0
    reused_scores = 0
    rejected_by_palette = 0
    rejected_by_dark = 0
    rejected_by_watermark = 0
    # Порог светлоты перебивки. Замер по базе: медиана 55 % видимого, у клипа,
    # давшего чёрную перебивку в 0047, — 16 %.
    visible_min = float(ctx.cfg.get("stock.interstitial_visible_min", 0.20))

    for slot_index in sorted(by_slot):
        slot = slots_by_index.get(slot_index, {})
        slot_block = next((b for b in plan.get("blocks", [])
                           if b.get("id") == slot.get("block_id")), {})
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
            meme_id = str(entry.get("asset_id") or "")
            if meme_id:
                accepted_counts[meme_id] = accepted_counts.get(meme_id, 0) + 1
            continue

        scored: list[tuple[float, dict[str, Any]]] = []
        intent_kind = classify_intent(
            intent, [candidate.get("query", "") for candidate in by_slot[slot_index]],
            str(plan.get("category") or ""))
        category = str(plan.get("category") or "")
        gated: list[dict[str, Any]] = []
        for candidate in by_slot[slot_index]:
            theme = thematic_reject_reason(
                " ".join([
                    str(candidate.get("page_url") or ""),
                    str(candidate.get("attribution") or ""),
                    str(candidate.get("query") or ""),
                    " ".join(candidate.get("tags") or []),
                    str(candidate.get("vision_summary") or ""),
                    str(candidate.get("asset_id") or ""),
                    str(candidate.get("prior_intent") or ""),
                ]),
                category=category, intent_kind=intent_kind, video_id=video_id)
            if theme:
                entry = {**candidate, "score": 0.0, "decision": "reject_theme",
                         "reject_reason": theme,
                         "verdict": {"score": 0.0, "judge": "theme_guard",
                                     "reason": theme, "summary": "", "frames": 0}}
                judged.append(entry)
                continue
            gate = _engine_gate_reason(candidate, pin_deny=pin_deny, index=index)
            if gate:
                entry = {**candidate, "score": 0.0, "decision": "reject_gate",
                         "reject_reason": gate,
                         "verdict": {"score": 0.0, "judge": "engine_gate",
                                     "reason": gate, "summary": "", "frames": 0}}
                judged.append(entry)
                continue
            gated.append(candidate)

        def _under_repeat_cap(entry: dict[str, Any]) -> bool:
            aid = str(entry.get("asset_id") or "")
            if not aid:
                return True
            return accepted_counts.get(aid, 0) < repeat_max

        prefer_gated = sorted(
            (c for c in gated
             if _prefer_rank(c.get("asset_id"), pin_prefer) is not None),
            key=lambda c: int(_prefer_rank(c.get("asset_id"), pin_prefer) or 0),
        )
        best: dict[str, Any] | None = None
        for candidate in prefer_gated:
            if not _under_repeat_cap(candidate):
                continue
            palette = palette_verdict(
                [Path(f) for f in candidate.get("frames", [])], palette_rules)
            light = (frame_light([Path(f) for f in candidate.get("frames", [])])
                     if slot.get("asset_role") == "interstitial" else None)
            if skip_live or candidate.get("prior_score") is not None:
                verdict_dict = skip_live_verdict(candidate, intent)
                reused_scores += 1
            else:
                verdict_dict = {
                    "score": float(SEED_SCORE),
                    "reason": "pin_prefer: принят без vision",
                    "summary": candidate.get("vision_summary", ""),
                    "judge": "pin_prefer", "frames": 0,
                }
            entry = {**candidate, "verdict": verdict_dict, "intent": intent,
                     "score": float(verdict_dict["score"]), "palette": palette}
            if light is not None:
                entry["light"] = light
            if light is not None and light["visible_share"] < visible_min:
                entry["decision"] = "reject_dark"
                entry["reject_reason"] = (
                    f"перебивке видно {light['visible_share']:.0%} кадра при пороге "
                    f"{visible_min:.0%}: зритель увидит субтитр на пустоте")
                rejected_by_dark += 1
                judged.append(entry)
                continue
            if not palette["passed"]:
                entry["decision"] = "reject_palette"
                entry["reject_reason"] = palette["reason"]
                rejected_by_palette += 1
                judged.append(entry)
                continue
            mark = watermark_reject_reason(verdict_dict, candidate)
            if mark:
                entry["decision"] = "reject_watermark"
                entry["reject_reason"] = mark
                rejected_by_watermark += 1
                _log.warning("пин отклонён: вшитая подпись", extra={
                    "asset_id": candidate.get("asset_id"),
                    "slot": slot_index, "reason": mark})
                judged.append(entry)
                continue
            entry["decision"] = "accept_prefer"
            entry["fallback_reason"] = "pin_prefer: hard-prefer before scoring"
            judged.append(entry)
            best = entry
            break

        if best is None:
          for candidate in gated:
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
            # skip_live: материал уже судился раньше / есть в кэше — без API.
            if skip_live:
                verdict_dict = skip_live_verdict(candidate, intent)
                reused_scores += 1
            elif candidate.get("origin") == "local_cache" and reusable:
                verdict_dict = {
                    "score": float(candidate["prior_score"]),
                    "reason": "оценка переиспользована из локальной базы",
                    "summary": candidate.get("vision_summary", ""),
                    "judge": "cache", "frames": 0,
                }
                reused_scores += 1
            elif not paid_ok:
                entry = {
                    **candidate, "intent": intent, "score": 0.0,
                    "decision": "underfilled",
                    "reject_reason": (
                        f"surplus {surplus['candidates']}/{surplus['target']} "
                        f"< {surplus['ratio']:.1f}×; paid critic skipped"),
                    "verdict": {
                        "score": 0.0, "judge": "surplus_gate", "frames": 0,
                        "reason": "underfilled: no Gemini/Grok/Magnific",
                    },
                }
                judged.append(entry)
                continue
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
            mark = watermark_reject_reason(entry.get("verdict"), candidate)
            if mark and entry["decision"] not in ("reject_palette", "reject_dark"):
                entry["decision"] = "reject_watermark"
                entry["reject_reason"] = mark
                rejected_by_watermark += 1
                _log.info("кандидат отклонён по вшитой подписи", extra={
                    "slot": slot_index, "asset": candidate.get("asset_id")})
            judged.append(entry)
            if entry["decision"] not in ("reject_palette", "reject_watermark"):
                scored.append((entry["score"], entry))

          def _repeat_key(pair: tuple[float, dict[str, Any]]) -> float:
            score, entry = pair
            aid = str(entry.get("asset_id") or "")
            return score - repeat_penalty * accepted_counts.get(aid, 0)

          scored.sort(key=_repeat_key, reverse=True)
          best = next((entry for score, entry in scored
                       if score >= accept_threshold and _under_repeat_cap(entry)), None)
          if best is None and scored:
            top_score, top_entry = scored[0]
            if skip_live:
                # Unverified seed/rank must not close a slot when anything
                # with a real prior exists; accept_skip_live only for gated
                # candidates that are not skip_live_unverified.
                verified = [
                    entry for _score, entry in scored
                    if str((entry.get("verdict") or {}).get("judge") or "")
                    != "skip_live_unverified" and _under_repeat_cap(entry)
                ]
                if verified:
                    best = verified[0]
                    best["decision"] = "accept_skip_live"
                    best["fallback_reason"] = (
                        "vision.skip_live: принят лучший прошедший гейты")
            # Спорный кандидат берём только если арбитраж уже был исчерпан:
            # иначе §7.3 требует отправить слот в генерацию.
            elif top_score >= reject_threshold and arbiter_calls >= arbiter_budget:
                best = next((entry for _score, entry in scored
                             if _under_repeat_cap(entry)), None)
                if best is not None:
                    best["decision"] = "accept_fallback"
                    best["fallback_reason"] = (
                        "лимит арбитража исчерпан, принят лучший из спорных")
        if best is not None:
            accepted[slot_index] = best
            aid = str(best.get("asset_id") or "")
            if aid:
                accepted_counts[aid] = accepted_counts.get(aid, 0) + 1

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
        "rejected_by_watermark": rejected_by_watermark,
        "rejected_by_dark": rejected_by_dark,
        "judged_count": len(judged),
        "accepted_count": len(accepted),
        "slots_total": len(asset_slots),
        "slots_filled": len(accepted),
        "fill_rate": round(len(accepted) / max(len(asset_slots), 1), 4),
        "unfilled_slots": unfilled,
        "added_to_index": added_to_index,
        "surplus": surplus,
        "skipped_stage1": skipped_stage1,
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
    if rejected_by_watermark:
        ctx.warn(f"{rejected_by_watermark} кандидатов отклонены за вшитую подпись "
                 f"стока — в кадре канала чужой логотип недопустим (§9.3)")
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
