"""Phrase-anchored slot lock. Chat authors it; Actions only obeys.

A lock line is {block, on, asset, plaque?, template?, avatar?}.
``on`` matches overlapping speech (not wall-clock seconds).
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Callable

from .pin_match import ctx_words, overlapping_speech

_log = logging.getLogger("redshift.slots_lock")

# Spare lower-thirds for QC-25 (no template id more than twice). dark-card
# stays off this list so a third plaque cannot reuse the overflowing id.
_QC25_LT_POOL = (
    "lower-thirds/clean-bar",
    "lower-thirds/accent-underline",
    "lower-thirds/note-pin",
    "lower-thirds/metric-badge",
    "lower-thirds/name-title",
    "lower-thirds/timestamp-marker",
    "lower-thirds/progress-step",
    "lower-thirds/tag-chips",
    "lower-thirds/warning-strip",
    "lower-thirds/source-domain",
)


def load_slots_lock(cfg: Any, video_id: str,
                    plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    raw: list[Any] = []
    try:
        from ..p7_broll_search.search import _footage_pin_entry
        entry = _footage_pin_entry(cfg, str(video_id or ""))
        raw = list(entry.get("slots_lock") or [])
    except Exception:
        raw = []
    if not raw and plan:
        raw = list(plan.get("slots_lock") or [])
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        asset = str(item.get("asset") or "").strip()
        on = str(item.get("on") or "").strip()
        if not asset or not on:
            continue
        out.append({
            "block": str(item.get("block") or "").strip(),
            "on": on,
            "asset": asset,
            "plaque": (str(item["plaque"]).strip() if item.get("plaque") else ""),
            "template": str(item.get("template") or "").strip(),
            "avatar": bool(item.get("avatar")),
            "reuse": bool(item.get("reuse")),
        })
    return out


def lock_targets(spec: dict[str, Any], slots: list[dict[str, Any]],
                 words: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    needle = spec["on"].lower()
    bid = spec.get("block") or ""
    hits: list[dict[str, Any]] = []
    for slot in slots:
        if bid and str(slot.get("block_id") or "") != bid:
            continue
        speech = overlapping_speech(slot, words).lower()
        if needle and needle in speech:
            hits.append(slot)
    if hits:
        return hits
    tokens = [t for t in needle.split() if len(t) > 3]
    if not tokens:
        return []
    for slot in slots:
        if bid and str(slot.get("block_id") or "") != bid:
            continue
        speech = overlapping_speech(slot, words).lower()
        reason = str(slot.get("reason") or "").lower()
        if any(t in speech for t in tokens) or (
                "gap fill" in reason and any(t in speech for t in tokens)):
            hits.append(slot)
    return hits


def plaque_span_for_content(
        *, content: str, block_slots: list[dict[str, Any]],
        all_slots: list[dict[str, Any]], words: list[dict[str, Any]] | None,
        lock: list[dict[str, Any]], default_span, max_sec: float = 3.5):
    label = str(content or "").strip()
    spec = next((s for s in lock if s.get("plaque")
                 and s["plaque"].strip().upper() == label.upper()), None)
    if spec is None:
        return default_span()
    hits = lock_targets(spec, block_slots, words)
    footage = [s for s in hits if str(s.get("kind") or "") not in {"avatar", "split", "talking_head"}]
    use = footage or hits
    if not use:
        return default_span()
    start = float(use[0]["start"])
    end = min(start + max_sec, float(use[-1]["end"]))
    if end - start < 0.35:
        end = min(start + max_sec, float(use[-1]["end"]))
    return round(start, 3), round(end, 3)


def _accepted_map(doc: dict[str, Any]) -> dict[int, dict[str, Any]]:
    raw = (doc or {}).get("accepted") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for key, val in raw.items():
        try:
            out[int(key)] = val
        except (TypeError, ValueError):
            continue
    return out


_MEDIA_KEYS = ("storage_key", "local_file", "file", "dst", "path", "local_path")


def _donor_has_media(donor: dict[str, Any]) -> bool:
    """Есть ли у донора ссылка на файл.

    P7 кладёт в кандидата ``storage_key`` (материал из базы) и ``local_file``
    (скачанный сток); P8 пересобирает запись как ``{**candidate, ...}`` и
    других ключей не добавляет. Проверка же спрашивала про ``file``/``dst`` —
    таких ключей в ``accepted_assets.json`` нет ни у одной записи, поэтому
    ``apply_lock_after_p8`` молча выходил на каждой строке замка. Девять
    раундов замок стоял в заявке и не двигал ни одного слота.
    """
    return any(donor.get(k) for k in _MEDIA_KEYS)


def _index_donor(ctx: Any, pid: str) -> dict[str, Any] | None:
    """Донор из базы футажей, когда P8 не принял материал ни на один слот.

    Замок называет материал поимённо: раз его нет среди принятых, поиск до
    него не дошёл (у ``magnific_0050_stamp`` теги «rubberstamp declined» не
    совпали ни с одним запросом b6). Брать файл с диска здесь законно —
    материал уже лежит в репозитории и в индексе, платить за него второй раз
    не нужно.
    """
    storage = getattr(ctx, "storage", None)
    cfg = getattr(ctx, "cfg", None)
    if storage is None or cfg is None or not pid:
        return None
    try:
        from .manifest import FootageIndex
        from .hydrate_footage import hydrate_repo_footage
        from ..p7_broll_search.search import _local_cache_row
    except Exception:  # noqa: BLE001
        return None
    try:
        index = FootageIndex.load(cfg)
        record = index.by_id(pid)
        if record is None or not record.file:
            return None
        if not storage.exists(record.file):
            hydrate_repo_footage(ctx, index)
        if not storage.exists(record.file):
            return None
        row = _local_cache_row(-1, record, f"slots_lock:{pid}")
    except Exception as exc:  # noqa: BLE001
        _log.warning("slots_lock: донор %s не поднялся из базы: %s", pid, exc)
        return None
    row["verdict"] = {
        "score": float(record.score or 0.0),
        "reason": "slots_lock: материал назван заявкой",
        "summary": record.vision_summary or "",
        "judge": "slots_lock", "frames": 0,
    }
    row["score"] = float(record.score or 0.0)
    row["decision"] = "accept_lock"
    return row


def apply_lock_after_p8(ctx: Any) -> int:
    try:
        plan = ctx.read("cut_plan.json")
        doc = ctx.read("accepted_assets.json")
    except Exception:
        return 0
    lock = load_slots_lock(getattr(ctx, "cfg", None), str(plan.get("video_id") or ""), plan)
    if not lock:
        return 0
    words = ctx_words(ctx)
    accepted = _accepted_map(doc)
    by_id: dict[str, dict[str, Any]] = {}
    for entry in accepted.values():
        if isinstance(entry, dict) and entry.get("asset_id") and _donor_has_media(entry):
            by_id[str(entry["asset_id"])] = entry
    fill_roles = ("broll", "evidence", "meme", "interstitial")
    slots = [s for s in (plan.get("slots") or [])
             if s.get("needs_asset") and s.get("asset_role") in fill_roles]
    moved = 0
    for spec in lock:
        pid = spec["asset"]
        targets = lock_targets(spec, slots, words)
        if not targets:
            continue
        donor = by_id.get(pid)
        if donor is None or not _donor_has_media(donor):
            donor = _index_donor(ctx, pid)
        if donor is None or not _donor_has_media(donor):
            _log.warning("slots_lock: нет донора для %s («%s») — слот не заперт",
                         pid, spec["on"])
            continue
        target_idx = int(targets[0]["index"])
        cur = accepted.get(target_idx) or {}
        if str(cur.get("asset_id") or "") == pid:
            continue
        if not spec.get("reuse"):
            # Замок переставляет материал, а не выбивает дыру. Если материал
            # уже лежит на другом слоте, туда переезжает прежний житель цели:
            # иначе слот-донор остаётся пустым, P11 закрывает его лестницей
            # (карточка поверх чужого клипа) — ровно так и родилось
            # «НЕ БЕРЁТ. ЭТО» поверх кадра Lean.
            for other_idx, entry in list(accepted.items()):
                if int(other_idx) == target_idx:
                    continue
                if str((entry or {}).get("asset_id") or "") != pid:
                    continue
                if cur.get("asset_id") and _donor_has_media(cur):
                    accepted[int(other_idx)] = {
                        **cur, "slot_index": int(other_idx),
                        "fallback_reason": f"slots_lock swap: уступил {pid}",
                    }
                else:
                    del accepted[int(other_idx)]
        accepted[target_idx] = {
            **donor,
            "slot_index": target_idx,
            "speech_locked": True,
            "fallback_reason": f"slots_lock:{spec['on']}",
        }
        _log.info("slots_lock: %s → слот %s (%s «%s»), было %s",
                  pid, target_idx, spec.get("block") or "-", spec["on"],
                  str(cur.get("asset_id") or "пусто"))
        moved += 1
    if not moved:
        return 0
    _log.info("slots_lock: закреплено слотов: %s из %s строк", moved, len(lock))
    doc = dict(doc)
    doc["accepted"] = {str(k): v for k, v in accepted.items()}
    ctx.write("accepted_assets.json", doc)
    return moved


def retarget_plaques_after_p11(ctx: Any) -> int:
    try:
        plan = ctx.read("edit_plan_A.json")
        cut = ctx.read("cut_plan.json")
    except Exception:
        return 0
    lock = load_slots_lock(getattr(ctx, "cfg", None),
                           str((plan or cut).get("video_id") or ""), cut or plan)
    if not lock:
        return 0
    words = ctx_words(ctx)
    slots = list((plan or {}).get("slots") or (cut or {}).get("slots") or [])
    overlays = list((plan or {}).get("overlays") or [])
    if not overlays:
        return 0
    changed = 0
    for ovl in overlays:
        if not isinstance(ovl, dict):
            continue
        content = str((ovl.get("params") or {}).get("content") or ovl.get("content") or "").strip()
        if not content:
            continue
        spec = next((s for s in lock if s.get("plaque") and s["plaque"].upper() == content.upper()), None)
        if spec is None:
            continue
        start, end = plaque_span_for_content(
            content=content,
            block_slots=[s for s in slots if str(s.get("block_id") or "") == spec["block"]] or slots,
            all_slots=slots, words=words, lock=lock,
            default_span=lambda: (float(ovl.get("start") or 0), float(ovl.get("end") or 0)),
        )
        if abs(float(ovl.get("start") or 0) - start) < 0.05 and abs(float(ovl.get("end") or 0) - end) < 0.05:
            continue
        ovl["start"] = start
        ovl["end"] = end
        changed += 1
    if changed:
        plan = dict(plan)
        plan["overlays"] = overlays
        ctx.write("edit_plan_A.json", plan)
    return changed


def cap_plan_templates_qc25(plan: dict[str, Any], catalog: Any = None) -> int:
    """Rewrite 3rd+ overlay template ids so QC-25 (max 2) passes.

    Shot templates stay put (footage lock). Latin plaque params keep
    dark_card chrome; only the counted id / renderer change.
    """
    shots = list(plan.get("shots") or [])
    overlays = list(plan.get("overlays") or [])
    seen: Counter[str] = Counter()
    for shot in shots:
        tid = str(shot.get("template") or "").strip()
        if tid:
            seen[tid] += 1
    if not overlays:
        return 0
    changed = 0
    used_list = list(plan.get("templates_used") or [])
    for ovl in overlays:
        if not isinstance(ovl, dict):
            continue
        tid = str(ovl.get("template") or "").strip()
        if not tid:
            continue
        seen[tid] += 1
        if seen[tid] <= 2:
            continue
        replacement = next((p for p in _QC25_LT_POOL if seen[p] < 2 and p != tid), None)
        if not replacement:
            continue
        ovl["template"] = replacement
        tmpl = catalog.by_id(replacement) if catalog is not None else None
        if tmpl is not None:
            renderer = getattr(tmpl, "renderer", None)
            if renderer and renderer != "plaque":
                ovl["renderer"] = renderer
            elif ovl.get("type") == "plaque":
                ovl.pop("renderer", None)
        seen[tid] -= 1
        seen[replacement] += 1
        if replacement not in used_list:
            used_list.append(replacement)
        changed += 1
    if changed:
        plan["overlays"] = overlays
        plan["templates_used"] = used_list
    return changed


def cap_overlay_templates_qc25(ctx: Any) -> int:
    try:
        plan = ctx.read("edit_plan_A.json")
    except Exception:
        return 0
    catalog = None
    try:
        from .templates import TemplateCatalog
        catalog = TemplateCatalog.load(getattr(ctx, "cfg", None))
    except Exception:
        catalog = None
    changed = cap_plan_templates_qc25(plan, catalog)
    if changed:
        ctx.write("edit_plan_A.json", plan)
    return changed


def wrap_p8(run_p8: Callable) -> Callable:
    def _wrapped(ctx):
        out = run_p8(ctx)
        apply_lock_after_p8(ctx)
        return out
    return _wrapped


def wrap_p11(run_p11: Callable) -> Callable:
    def _wrapped(ctx):
        out = run_p11(ctx)
        retarget_plaques_after_p11(ctx)
        cap_overlay_templates_qc25(ctx)
        return out
    return _wrapped
