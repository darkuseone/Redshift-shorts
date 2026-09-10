"""P8: ``candidates.json`` → ``accepted_assets.json``.

Трёхступенчатая оценка §7.3:

* **Шаг 1 — дешёвая отбраковка без LLM.** Metadata / negatives / theme.
  Цель — убить ≥50 % входящего пула до зрения (MUST-019).
* **Шаг 2 — mid-critic GLM.** Прошедшие cheap; для видео — 3 кадра.
  Score 0.0–1.0. Без ключа — mock/empty, не exception.
* **Шаг 3 — Grok Vision только серая зона** score ∈ [0.45, 0.70].
  Не чаще 1 раза на клип, лимит ≤3 вызовов на ролик. Evidence/twist сами
  по себе сюда не входят (MUST-020 снимет оставшийся helper).

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
from ..lib.pin_match import ctx_words, pin_slot_prefer_key
from ..lib.providers.vision import VisionVerdict, build_vision_provider
from ..lib.query import (
    classify_intent, negative_reject_reason, slot_negatives,
    thematic_reject_reason, topical_match_score,
)
from ..p7_broll_search.search import (
    _footage_pin_entry, _load_footage_pins, _local_cache_row, footage_pool_count,
    judge_blocks_stage1_dead, pin_id_denied, stage1_dead_ids, surplus_report,
)

COHERENCE_MIN = 0.15

_log = get_logger("p8")


def in_grey_zone(score: float, cfg) -> bool:
    """Grok/второй уровень только при score ∈ [reject, accept] (MUST-019)."""
    lo = float(cfg.get("vision.reject_threshold", 0.45))
    hi = float(cfg.get("vision.accept_threshold", 0.70))
    return lo <= float(score) <= hi


def _candidate_hay(candidate: dict[str, Any]) -> str:
    meta = candidate.get("meta") or {}
    return " ".join([
        str(candidate.get("page_url") or ""),
        str(candidate.get("url_origin") or ""),
        str(candidate.get("attribution") or ""),
        str(candidate.get("query") or ""),
        " ".join(candidate.get("tags") or []),
        str(candidate.get("vision_summary") or ""),
        str(candidate.get("asset_id") or ""),
        str(candidate.get("prior_intent") or ""),
        str(meta.get("title") or ""),
        str(meta.get("alt") or ""),
    ])


def cheap_reject_reason(candidate: dict[str, Any], *, cfg,
                        slot_duration: float = 3.0,
                        negatives: list[str] | None = None,
                        category: str = "", intent_kind: str = "",
                        video_id: str = "") -> str | None:
    """Шаг 1 без LLM: theme, negatives, watermark-строки, ultrawide, duration."""
    hay = _candidate_hay(candidate)
    theme = thematic_reject_reason(
        hay, category=category, intent_kind=intent_kind, video_id=video_id)
    if theme:
        return theme
    denied = negative_reject_reason(hay, negatives)
    if denied:
        return denied
    lowered = hay.lower()
    if any(bad in lowered for bad in ("watermark", "shutterstock", "getty", "preview")):
        return "признаки водяного знака или чужого стока"
    try:
        width, height = int(candidate.get("width") or 0), int(candidate.get("height") or 0)
    except (TypeError, ValueError):
        width, height = 0, 0
    if width and height and (width / height) > 2.6:
        return "сверхширокий кадр: кроп 9:16 разрушит композицию"
    kind = str(candidate.get("kind") or "video")
    try:
        duration = float(candidate.get("duration_sec") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if kind == "video" and duration and duration < min(1.2, max(slot_duration, 0.1) * 0.6):
        return f"короче слота: {duration:.1f} сек"
    return None


def _needs_arbitration(verdict: VisionVerdict, role: str, cfg) -> str | None:
    """Триггеры шага 3 (§7.3). Возвращает причину или None."""
    lo = float(cfg.get("vision.reject_threshold", 0.45))
    hi = float(cfg.get("vision.accept_threshold", 0.70))
    disagree = float(cfg.get("vision.frame_disagreement_threshold", 0.30))
    if lo <= verdict.score <= hi:
        return f"score {verdict.score:.2f} в спорной зоне [{lo}, {hi}]"
    if verdict.frame_disagreement > disagree:
        return f"кадры расходятся на {verdict.frame_disagreement:.2f} > {disagree}"
    # MUST-020: evidence/twist не auto-arbitrate — те же пороги, что у обычного слота.
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


def _tally_vision(name: str, counters: dict[str, int]) -> None:
    blob = str(name or "").lower()
    if "grok" in blob:
        counters["grok"] += 1
    elif "glm" in blob:
        counters["glm"] += 1
    elif "gemini" in blob:
        counters["gemini"] += 1


CRITIC_METRIC_KEYS = (
    "candidates_per_slot",
    "killed_stage1",
    "killed_cheap",
    "killed_glm",
    "grok_calls",
    "gemini_calls",
    "magnific_calls",
    "gen_share",
    "critic_cost",
)


def _service_call_count(costs, *names: str) -> int:
    if costs is None:
        return 0
    wanted = {n.lower() for n in names}
    entries = getattr(costs, "entries", None)
    if entries is not None:
        return sum(1 for e in entries
                   if str(getattr(e, "service", "") or "").lower() in wanted)
    data = costs.to_dict() if hasattr(costs, "to_dict") else {}
    return sum(1 for e in (data.get("entries") or [])
               if str(e.get("service") or "").lower() in wanted)


def _critic_cost_usd(costs) -> float:
    if costs is None:
        return 0.0
    if hasattr(costs, "by_service"):
        by = costs.by_service()
    else:
        by = (costs.to_dict() if hasattr(costs, "to_dict") else {}).get("by_service") or {}
    return round(sum(float(by.get(k, 0) or 0) for k in ("glm", "grok", "gemini")), 6)


def _killed_glm_count(judged: list[dict[str, Any]], reject_threshold: float) -> int:
    n = 0
    for entry in judged:
        verdict = entry.get("verdict") or {}
        if "glm" not in str(verdict.get("judge") or "").lower():
            continue
        try:
            score = float(verdict.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        decision = str(entry.get("decision") or "")
        if score < reject_threshold or decision.startswith("reject"):
            n += 1
    return n


def critic_metrics_payload(accepted: dict[str, Any] | None = None, *,
                           generated: dict[str, Any] | None = None,
                           costs=None,
                           candidates: dict[str, Any] | None = None) -> dict[str, Any]:
    """Стабильные ключи MUST-020 для build_report и cost_report."""
    accepted = accepted or {}
    generated = generated or {}
    candidates = candidates or {}
    per_slot = accepted.get("candidates_per_slot")
    if not isinstance(per_slot, dict):
        counts: dict[str, int] = {}
        for row in candidates.get("candidates") or []:
            key = str(row.get("slot_index", ""))
            counts[key] = counts.get(key, 0) + 1
        per_slot = counts
    killed_stage1 = accepted.get("killed_stage1", accepted.get("skipped_stage1", 0))
    if killed_stage1 is None:
        killed_stage1 = len(candidates.get("stage1_rejected") or [])
    gen_share = generated.get("ai_footage_share")
    if gen_share is None:
        gen_share = accepted.get("gen_share", 0.0)
    magnific = accepted.get("magnific_calls")
    if costs is not None:
        magnific = _service_call_count(costs, "magnific")
        critic_cost = _critic_cost_usd(costs)
    else:
        magnific = int(magnific or 0)
        critic_cost = float(accepted.get("critic_cost") or 0.0)
    return {
        "candidates_per_slot": {str(k): int(v) for k, v in dict(per_slot).items()},
        "killed_stage1": int(killed_stage1 or 0),
        "killed_cheap": int(accepted.get("killed_cheap") or 0),
        "killed_glm": int(accepted.get("killed_glm") or 0),
        "grok_calls": int(accepted.get("grok_calls") or 0),
        "gemini_calls": int(accepted.get("gemini_calls") or 0),
        "magnific_calls": int(magnific or 0),
        "gen_share": round(float(gen_share or 0.0), 4),
        "critic_cost": round(float(critic_cost or 0.0), 6),
    }


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


def _slot_duration(slot: dict[str, Any]) -> float:
    try:
        dur = float(slot.get("end") or 0) - float(slot.get("start") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    return dur if dur > 0 else 3.0


def _leftover_prefer_key(asset_id: str, slot: dict[str, Any],
                         pin_prefer: list[str],
                         words: list[dict[str, Any]] | None = None,
                         ) -> tuple[int, int]:
    """Prefer leftover pins that match this slot's spoken window, else list order."""
    return pin_slot_prefer_key(asset_id, slot, pin_prefer, words=words)


def _rebalance_prefers_onto_speech(
        *, accepted: dict[int, dict[str, Any]],
        pin_prefer: list[str], slots_by_index: dict[int, dict[str, Any]],
        words: list[dict[str, Any]] | None) -> int:
    """Swap already-accepted prefer pins onto the slot whose speech they match.

    Exclusive P7 assignment can park the Nature figure on a later evidence
    split and the ticker on «работа опубликована в Nature». Swapping does not
    change AI screen time: both slots stay the same length.
    """
    if len(accepted) < 2 or not pin_prefer:
        return 0
    swaps = 0
    prefer_set = set(pin_prefer)
    indices = [idx for idx in accepted
               if str(accepted[idx].get("asset_id") or "") in prefer_set]
    improved = True
    while improved:
        improved = False
        for i, idx_a in enumerate(indices):
            for idx_b in indices[i + 1:]:
                slot_a = slots_by_index.get(int(idx_a), {})
                slot_b = slots_by_index.get(int(idx_b), {})
                aid_a = str(accepted[idx_a].get("asset_id") or "")
                aid_b = str(accepted[idx_b].get("asset_id") or "")
                before = (
                    _leftover_prefer_key(aid_a, slot_a, pin_prefer, words)[0]
                    + _leftover_prefer_key(aid_b, slot_b, pin_prefer, words)[0]
                )
                after = (
                    _leftover_prefer_key(aid_a, slot_b, pin_prefer, words)[0]
                    + _leftover_prefer_key(aid_b, slot_a, pin_prefer, words)[0]
                )
                if after >= before:
                    continue
                if _hook_mismatch(aid_a, slot_b, pin_prefer, words) or \
                        _hook_mismatch(aid_b, slot_a, pin_prefer, words):
                    continue
                accepted[idx_a], accepted[idx_b] = accepted[idx_b], accepted[idx_a]
                accepted[idx_a]["slot_index"] = int(idx_a)
                accepted[idx_b]["slot_index"] = int(idx_b)
                swaps += 1
                improved = True
    return swaps


def _hook_mismatch(asset_id: str, slot: dict[str, Any], pin_prefer: list[str],
                   words: list[dict[str, Any]] | None) -> bool:
    """True when moving this pin onto the hook would be off-theme."""
    try:
        start = float(slot.get("start") or 0.0)
    except (TypeError, ValueError):
        start = 0.0
    if str(slot.get("role") or "") != "hook" and start >= 3.0:
        return False
    return _leftover_prefer_key(asset_id, slot, pin_prefer, words)[0] >= 0


def _drop_mismatched_prefers(
        *, accepted: dict[int, dict[str, Any]], accepted_counts: dict[str, int],
        pin_prefer: list[str], slots_by_index: dict[int, dict[str, Any]],
        words: list[dict[str, Any]] | None) -> int:
    """Unaccept prefer pins that still sit on a penalized slot after swaps."""
    dropped = 0
    for idx in list(accepted):
        aid = str(accepted[idx].get("asset_id") or "")
        if aid not in set(pin_prefer):
            continue
        slot = slots_by_index.get(int(idx), {})
        if _leftover_prefer_key(aid, slot, pin_prefer, words)[0] <= 0:
            continue
        accepted_counts[aid] = max(0, int(accepted_counts.get(aid, 1)) - 1)
        del accepted[idx]
        dropped += 1
    return dropped


def _fill_unfilled_from_leftover_prefers(
        *, ctx, cfg, plan: dict[str, Any], slots_by_index: dict[int, dict[str, Any]],
        accepted: dict[int, dict[str, Any]], accepted_counts: dict[str, int],
        judged: list[dict[str, Any]], pin_prefer: list[str], pin_deny: set[str],
        index: FootageIndex, repeat_max: int, skip_live: bool,
        palette_rules: dict[str, Any], visible_min: float,
        words: list[dict[str, Any]] | None = None) -> int:
    """Hard-prefer pins parked as P7 runner-ups onto later empty slots.

    keep_per_slot used to mark unused prefers taken, so 0042 never showed the
    cryostat still. This is the same pin_prefer accept, not a weak-stock fill.
    """
    if not pin_prefer:
        return 0
    asset_slots = [
        s for s in plan.get("slots") or []
        if s.get("needs_asset")
        and s.get("asset_role") in ("broll", "evidence", "meme", "interstitial")
    ]
    unfilled = [s for s in asset_slots if int(s["index"]) not in accepted]
    if not unfilled:
        return 0
    duration = float(plan.get("duration_sec") or 0.0) or sum(
        _slot_duration(s) for s in plan.get("slots") or [])
    ai_max = float(cfg.get("limits.ai_footage_share_max", 0.10)) * max(duration, 1e-6)
    ai_used = 0.0
    for idx, entry in accepted.items():
        if entry.get("ai_generated"):
            ai_used += _slot_duration(slots_by_index.get(int(idx), {}))
    storage = getattr(ctx, "storage", None)
    filled = 0
    leftover = [
        pid for pid in pin_prefer
        if accepted_counts.get(pid, 0) < repeat_max and not pin_id_denied(pid, pin_deny)
    ]
    for slot in unfilled:
        slot_index = int(slot["index"])
        if leftover:
            leftover.sort(key=lambda pid: _leftover_prefer_key(
                pid, slot, pin_prefer, words))
        slot_dur = _slot_duration(slot)
        intent = slot.get("visual_intent", "") or slot.get("reason", "")
        picked_id = None
        for pid in leftover:
            rec = index.by_id(pid)
            if rec is None or getattr(rec, "quarantined", False):
                continue
            if not rec.file:
                continue
            if storage is not None and not storage.exists(rec.file):
                continue
            bonus = _leftover_prefer_key(pid, slot, pin_prefer, words)[0]
            if bonus > 0:
                continue
            carve_sec: float | None = None
            if rec.ai_generated:
                remain = ai_max - ai_used
                if slot_dur > remain + 1e-6:
                    # Spoken match + leftover AI that cannot cover the whole
                    # slot: keep a short window so QC-14 stays under 10 %.
                    if bonus >= 0 or remain < 1.2:
                        continue
                    carve_sec = remain
            candidate = _local_cache_row(slot_index, rec, intent or pid)
            gate = _engine_gate_reason(candidate, pin_deny=pin_deny, index=index)
            if gate:
                continue
            cheap = cheap_reject_reason(
                candidate, cfg=cfg, slot_duration=slot_dur,
                negatives=slot_negatives(slot, plan),
                category=str(plan.get("category") or ""),
                intent_kind=classify_intent(
                    intent, [candidate.get("query", "")],
                    str(plan.get("category") or "")),
                video_id=str(plan.get("video_id") or ""))
            if cheap:
                continue
            palette = palette_verdict([], palette_rules)
            if skip_live or candidate.get("prior_score") is not None:
                verdict_dict = skip_live_verdict(candidate, intent)
            else:
                verdict_dict = {
                    "score": float(SEED_SCORE),
                    "reason": "pin_prefer leftover: принят без vision",
                    "summary": candidate.get("vision_summary", ""),
                    "judge": "pin_prefer", "frames": 0,
                }
            entry = {**candidate, "verdict": verdict_dict, "intent": intent,
                     "score": float(verdict_dict["score"]), "palette": palette,
                     "decision": "accept_prefer",
                     "fallback_reason": "pin_prefer leftover: unused prefer onto empty slot"}
            if bonus < 0:
                entry["speech_locked"] = True
            if carve_sec is not None:
                entry["carve_sec"] = round(float(carve_sec), 3)
                entry["speech_locked"] = True
                entry["fallback_reason"] = (
                    "pin_prefer leftover: carved AI window onto spoken slot")
            judged.append(entry)
            accepted[slot_index] = entry
            accepted_counts[pid] = accepted_counts.get(pid, 0) + 1
            if rec.ai_generated:
                ai_used += float(carve_sec) if carve_sec is not None else slot_dur
            picked_id = pid
            filled += 1
            break
        if picked_id is not None:
            leftover = [pid for pid in leftover if pid != picked_id]
    return filled


def run_step(ctx) -> dict[str, Any]:
    doc = ctx.read("candidates.json")
    plan = ctx.read("cut_plan.json")
    cfg = ctx.cfg

    accept_threshold = float(cfg.get("vision.accept_threshold", 0.70))
    reject_threshold = float(cfg.get("vision.reject_threshold", 0.45))
    arbiter_budget = int(cfg.get("vision.arbiter_max_calls", 3))

    skip_live = bool(cfg.get("vision.skip_live", False))
    surplus_ratio = float(cfg.get("stock.candidate_surplus", 1.3))
    words = ctx_words(ctx)
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
        _log.warning("surplus underfilled — paid critic (GLM/Grok/Magnific) не вызывается",
                     extra=surplus)
    index = FootageIndex.load(cfg)
    video_id = str(plan.get("video_id") or "")
    pin_deny, pin_prefer = _load_footage_pins(cfg, video_id)
    pin_entry = _footage_pin_entry(cfg, video_id)

    slots_by_index = {s["index"]: s for s in plan["slots"]}
    dead_ids = stage1_dead_ids(doc.get("stage1_rejected") or [])
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
    vision_counts = {"grok": 0, "glm": 0, "gemini": 0}
    killed_cheap = 0
    cheap_seen = 0
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
        negatives = slot_negatives(slot, plan)
        try:
            slot_duration = float(slot.get("end") or 0) - float(slot.get("start") or 0)
        except (TypeError, ValueError):
            slot_duration = 0.0
        if slot_duration <= 0:
            slot_duration = 3.0
        gated: list[dict[str, Any]] = []
        for candidate in by_slot[slot_index]:
            cheap_seen += 1
            cheap = cheap_reject_reason(
                candidate, cfg=cfg, slot_duration=slot_duration,
                negatives=negatives, category=category,
                intent_kind=intent_kind, video_id=video_id)
            if cheap:
                killed_cheap += 1
                decision = "reject_theme" if (
                    cheap.startswith("тематический") or cheap.startswith("sci off-theme")
                ) else "reject_cheap"
                entry = {**candidate, "score": 0.0, "decision": decision,
                         "reject_reason": cheap,
                         "verdict": {"score": 0.0, "judge": "cheap_filter",
                                     "reason": cheap, "summary": "", "frames": 0}}
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
            key=lambda c: _leftover_prefer_key(
                str(c.get("asset_id") or ""), slot, pin_prefer, words),
        )
        best: dict[str, Any] | None = None
        for candidate in prefer_gated:
            if not _under_repeat_cap(candidate):
                continue
            if _leftover_prefer_key(
                    str(candidate.get("asset_id") or ""), slot,
                    pin_prefer, words)[0] > 0:
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
            reusable = (candidate.get("prior_score") is not None
                        and candidate.get("origin") == "local_cache")
            # skip_live: материал уже судился раньше / есть в кэше — без API.
            if skip_live:
                verdict_dict = skip_live_verdict(candidate, intent)
                reused_scores += 1
            elif reusable:
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
                _tally_vision(
                    f"{getattr(primary, 'name', '')} {verdict_dict.get('judge', '')}",
                    vision_counts)

                # MUST-019: второй уровень / Grok только серая зона score.
                if (in_grey_zone(verdict.score, cfg)
                        and arbiter is not None
                        and arbiter_calls < arbiter_budget):
                    aid = str(candidate.get("asset_id") or "")
                    already = bool(verdict_dict.get("arbitrated"))
                    if not already:
                        arbiter_calls += 1
                        final = arbiter.judge(frames, intent=intent, role=role,
                                              query=candidate.get("query", ""))
                        primary_score = round(verdict.score, 4)
                        verdict_dict = final.to_dict()
                        verdict_dict["arbitrated"] = True
                        verdict_dict["arbitration_reason"] = (
                            f"score {primary_score:.2f} в серой зоне "
                            f"[{reject_threshold:.2f}, {accept_threshold:.2f}]")
                        verdict_dict["primary_score"] = primary_score
                        verdict_dict["clip_id"] = aid
                        _tally_vision(
                            f"{getattr(arbiter, 'name', '')} {verdict_dict.get('judge', '')}",
                            vision_counts)
                elif in_grey_zone(verdict.score, cfg) and arbiter_calls >= arbiter_budget:
                    verdict_dict["arbitration_skipped"] = (
                        f"серая зона; лимит арбитража {arbiter_budget} исчерпан")

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

    leftover_filled = _fill_unfilled_from_leftover_prefers(
        ctx=ctx, cfg=cfg, plan=plan, slots_by_index=slots_by_index,
        accepted=accepted, accepted_counts=accepted_counts, judged=judged,
        pin_prefer=pin_prefer, pin_deny=pin_deny, index=index,
        repeat_max=repeat_max, skip_live=skip_live,
        palette_rules=palette_rules, visible_min=visible_min, words=words)
    if leftover_filled:
        _log.info("leftover prefer pins closed %s empty slot(s)", leftover_filled)
    swapped = _rebalance_prefers_onto_speech(
        accepted=accepted, pin_prefer=pin_prefer,
        slots_by_index=slots_by_index, words=words)
    if swapped:
        _log.info("rebalanced %s prefer pin pair(s) onto spoken slots", swapped)
    dropped = _drop_mismatched_prefers(
        accepted=accepted, accepted_counts=accepted_counts,
        pin_prefer=pin_prefer, slots_by_index=slots_by_index, words=words)
    if dropped:
        leftover_filled += _fill_unfilled_from_leftover_prefers(
            ctx=ctx, cfg=cfg, plan=plan, slots_by_index=slots_by_index,
            accepted=accepted, accepted_counts=accepted_counts, judged=judged,
            pin_prefer=pin_prefer, pin_deny=pin_deny, index=index,
            repeat_max=repeat_max, skip_live=skip_live,
            palette_rules=palette_rules, visible_min=visible_min, words=words)

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
    candidates_per_slot = {str(i): 0 for i in asset_slots}
    for slot_index, rows in by_slot.items():
        candidates_per_slot[str(slot_index)] = len(rows)
    killed_glm = _killed_glm_count(judged, reject_threshold)
    costs = getattr(ctx, "costs", None)
    critic = critic_metrics_payload(
        {
            "candidates_per_slot": candidates_per_slot,
            "killed_stage1": skipped_stage1,
            "killed_cheap": killed_cheap,
            "killed_glm": killed_glm,
            "grok_calls": vision_counts["grok"],
            "gemini_calls": vision_counts["gemini"],
            "magnific_calls": _service_call_count(costs, "magnific"),
            "gen_share": 0.0,
            "critic_cost": _critic_cost_usd(costs),
        },
        costs=costs,
    )

    result = {
        "video_id": doc["video_id"],
        "accept_threshold": accept_threshold,
        "reject_threshold": reject_threshold,
        "arbiter_calls": arbiter_calls,
        "arbiter_budget": arbiter_budget,
        "grok_calls": vision_counts["grok"],
        "glm_calls": vision_counts["glm"],
        "gemini_calls": vision_counts["gemini"],
        "killed_cheap": killed_cheap,
        "killed_glm": killed_glm,
        "killed_stage1": skipped_stage1,
        "cheap_seen": cheap_seen,
        "cheap_kill_rate": round(killed_cheap / max(cheap_seen, 1), 4),
        "candidates_per_slot": candidates_per_slot,
        "magnific_calls": critic["magnific_calls"],
        "gen_share": critic["gen_share"],
        "critic_cost": critic["critic_cost"],
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
            "arbiter_calls": arbiter_calls,
            "grok_calls": vision_counts["grok"],
            "killed_cheap": killed_cheap}
