"""P7: ``cut_plan.json`` → ``candidates.json``.

§7.2 «Поиск B-roll». Ключевые правила, реализованные здесь:

1. Запросы строятся **на английском** из смысла блока, а не подстрочным
   переводом русского текста: сток ищет по английским тегам, и «квантовый чип»
   переведённый буквально даёт мусор.
2. На слот — 3–5 запросов разной абстракции: конкретный → предметный →
   метафорический. Один слот, закрытый пятью вариантами формулировки, надёжнее
   пяти слотов с одной формулировкой.
3. **Сначала локальная база** (§7.2.1, §14.4): если материал уже скачан и
   оценён, повторно платить за него нельзя.
4. Приоритет источников — по типу запроса (таблица §7.2 и ``stock_sources.yaml``).
5. Лицензия проверяется **до** скачивания (§7.2.7); материалы без подтверждённой
   лицензии выбывают здесь же.
6. Скачиваний не больше 50 на ролик (§7.2.4), пул — 30–60 кандидатов (§7.2.3).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..lib.ffmpeg import extract_frames, probe
from ..lib.logging import get_logger
from ..lib.manifest import FootageIndex
from ..lib.phash import phash_image
from ..lib.providers.stock import StockCandidate, build_stock_providers
from ..lib.query import build_queries, classify_intent

_log = get_logger("p7")


def _load_routing(cfg) -> dict[str, Any]:
    path = cfg.repo_root / "config" / "stock_sources.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _sources_for(intent_kind: str, routing: dict[str, Any]) -> list[str]:
    table = routing.get("routing", {})
    return list(table.get(intent_kind) or table.get("default", ["pexels"]))


def _stage1_reject(candidate: StockCandidate, cfg, slot_duration: float) -> str | None:
    """Шаг 1 §7.3 — дешёвая отбраковка без vision. Возвращает причину или None."""
    if not candidate.license_confirmed:
        return "лицензия не подтверждена (§7.2.7)"
    max_h = int(cfg.get("stock.max_download_height", 1080))
    if candidate.height and candidate.height > max_h and candidate.width > max_h:
        return f"разрешение выше {max_h}p — по §3.6.1 не берём"
    if candidate.kind == "video":
        if candidate.duration_sec and candidate.duration_sec < min(1.2, slot_duration * 0.6):
            return f"короче слота: {candidate.duration_sec:.1f} сек"
        if candidate.duration_sec and candidate.duration_sec > 120:
            return "слишком длинный исходник (>120 сек)"
    if candidate.width and candidate.height:
        aspect = candidate.width / candidate.height
        if aspect > 2.6:
            return "сверхширокий кадр: кроп 9:16 разрушит композицию"
    lowered = f"{candidate.attribution} {' '.join(candidate.tags)}".lower()
    if any(bad in lowered for bad in ("watermark", "shutterstock", "getty", "preview")):
        return "признаки водяного знака или чужого стока"
    return None


def _cache_key(candidate: StockCandidate) -> str:
    ext = ".jpg" if candidate.kind == "photo" else ".mp4"
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", candidate.id)
    return f"{candidate.source}/{safe}{ext}"


def run_step(ctx) -> dict[str, Any]:
    plan = ctx.read("cut_plan.json")
    cfg = ctx.cfg
    routing = _load_routing(cfg)
    providers = build_stock_providers(cfg, ctx.costs)
    index = FootageIndex.load(cfg)

    queries_per_slot = int(cfg.get("stock.queries_per_slot", 4))
    per_query = int(cfg.get("stock.max_candidates_per_query", 8))
    pool_min, pool_max = cfg.get("stock.target_pool_size", [30, 60])
    max_downloads = int(cfg.get("magnific.max_downloads_per_video", 50))
    probe_positions = cfg.get("stock.video_probe_frames", [0.10, 0.50, 0.90])
    dedup_threshold = int(cfg.get("stock.dedup_hamming_max", 8))
    frozen = bool(cfg.get("libraries.footage.freeze", False))

    # Материал из последних 5 роликов не переиспользуем при наличии альтернативы.
    recent_videos = _recent_video_ids(ctx, limit=5)

    slots = [s for s in plan["slots"] if s["needs_asset"] and s["asset_role"] in ("broll", "evidence")]
    downloads = 0
    stage1_rejected: list[dict[str, Any]] = []
    candidates_out: list[dict[str, Any]] = []
    seen_hashes: list[tuple[str, list[str]]] = []
    from_cache = 0

    frames_dir = ctx.wpath("broll", "frames", ".keep").parent

    for slot in slots:
        intent_kind = classify_intent(slot.get("visual_intent", ""), slot.get("queries", []),
                                      plan.get("category", ""))
        queries = build_queries(slot, plan, count=queries_per_slot)
        source_order = _sources_for(intent_kind, routing)
        slot_candidates: list[dict[str, Any]] = []

        # --- 1. локальная база (§7.2.1) --------------------------------------
        local = index.search(_tags_for(queries), limit=3, exclude_videos=recent_videos)
        for record in local:
            slot_candidates.append({
                "slot_index": slot["index"], "origin": "local_cache",
                "asset_id": record.id, "source": record.source,
                "kind": record.type, "query": queries[0],
                "license": record.license, "license_confirmed": True,
                "width": record.width, "height": record.height,
                "duration_sec": record.duration_sec,
                "phashes": record.phashes or ([record.phash] if record.phash else []),
                "storage_key": record.file, "tags": record.tags,
                "vision_summary": record.vision_summary, "prior_score": record.score,
                "ai_generated": record.ai_generated, "mock": record.mock,
                "attribution": record.extra.get("attribution", ""),
                "page_url": record.url_origin,
            })
            from_cache += 1

        if frozen and slot_candidates:
            candidates_out.extend(slot_candidates)
            continue
        if frozen:
            ctx.warn(f"кэш футажей заморожен, слот {slot['index']} не закрыт локальной базой",
                     slot=slot["index"])
            continue

        # --- 2. внешние стоки -------------------------------------------------
        # Сначала собираем метаданные по всем запросам (это бесплатно), затем
        # ранжируем и качаем только лучших. §7.2.4 даёт 50 скачиваний на ролик:
        # если тратить их подряд, последние слоты останутся пустыми.
        found_all: list[tuple[str, Any, str]] = []      # (source, candidate, query)
        for query in queries:
            for source in source_order:
                provider = providers.get(source)
                if provider is None:
                    continue
                try:
                    for candidate in provider.search(query, kind="video", limit=per_query):
                        found_all.append((source, candidate, query))
                except Exception as exc:  # noqa: BLE001 — источник не должен ронять прогон
                    ctx.warn(f"источник {source} недоступен: {exc}", source=source, query=query)

        passed: list[tuple[str, Any, str]] = []
        for source, candidate, query in found_all:
            reason = _stage1_reject(candidate, cfg, float(slot["duration"]))
            if reason:
                stage1_rejected.append({"id": candidate.id, "source": candidate.source,
                                        "reason": reason, "query": query})
            else:
                passed.append((source, candidate, query))

        passed.sort(key=lambda item: _prefetch_rank(item[1], source_order, float(slot["duration"])))

        remaining_slots = max(1, len(slots) - slots.index(slot))
        budget = max(2, (max_downloads - downloads) // remaining_slots)
        taken = 0

        for source, candidate, query in passed:
            if taken >= min(budget, per_query) or downloads >= max_downloads:
                break
            key = _cache_key(candidate)
            local_file = ctx.wpath("broll", "raw", Path(key).name)
            if ctx.storage.exists(key):
                ctx.storage.get(key, local_file)
            else:
                try:
                    providers[source].download(candidate, local_file)
                except Exception as exc:  # noqa: BLE001
                    ctx.warn(f"скачивание не удалось: {exc}", id=candidate.id)
                    continue
                ctx.storage.put(key, local_file)
                downloads += 1

            try:
                info = probe(local_file)
            except Exception as exc:  # noqa: BLE001
                ctx.warn(f"битый файл {candidate.id}: {exc}")
                continue

            frames = extract_frames(local_file, frames_dir / candidate.id,
                                    probe_positions if info.has_video else [0.5])
            hashes = [phash_image(f) for f in frames]

            # §7.2.5: дедуп внутри ролика и против всей базы
            dup_local = _find_dup(hashes, seen_hashes, dedup_threshold)
            if dup_local:
                stage1_rejected.append({"id": candidate.id, "source": candidate.source,
                                        "reason": f"визуальный дубль {dup_local} внутри ролика",
                                        "query": query})
                continue
            dup_base = index.find_duplicate(hashes, dedup_threshold)
            if dup_base is not None:
                stage1_rejected.append({"id": candidate.id, "source": candidate.source,
                                        "reason": f"дубль материала из базы {dup_base.id}",
                                        "query": query})
                continue

            seen_hashes.append((candidate.id, hashes))
            taken += 1
            slot_candidates.append({
                "slot_index": slot["index"], "origin": "stock",
                "asset_id": candidate.id, "source": candidate.source,
                "kind": candidate.kind, "query": query,
                "license": candidate.license, "license_confirmed": True,
                "attribution": candidate.attribution, "author": candidate.author,
                "page_url": candidate.page_url,
                "width": info.width or candidate.width,
                "height": info.height or candidate.height,
                "duration_sec": info.duration_sec or candidate.duration_sec,
                "fps": info.fps,
                "local_file": str(local_file), "storage_key": key,
                "frames": [str(f) for f in frames], "phashes": hashes,
                "tags": candidate.tags, "mock": bool(candidate.meta.get("mock")),
                "ai_generated": candidate.source == "magnific",
            })

        if not slot_candidates:
            ctx.warn(f"слот {slot['index']} ({slot['block_id']}) не получил ни одного кандидата",
                     slot=slot["index"], queries=queries)
        candidates_out.extend(slot_candidates)

    doc = {
        "video_id": plan["video_id"],
        "slots_needing_asset": len(slots),
        "pool_size": len(candidates_out),
        "pool_target": [pool_min, pool_max],
        "downloads": downloads,
        "download_limit": max_downloads,
        "from_local_cache": from_cache,
        "cache_share": round(from_cache / max(len(candidates_out), 1), 4),
        "stage1_rejected": stage1_rejected,
        "stage1_reject_share": round(
            len(stage1_rejected) / max(len(stage1_rejected) + len(candidates_out), 1), 4),
        "candidates": candidates_out,
    }
    ctx.write("candidates.json", doc)

    if len(candidates_out) < pool_min:
        ctx.warn(f"пул кандидатов {len(candidates_out)} меньше рекомендованных {pool_min} (§7.2.3)",
                 pool=len(candidates_out))
    _log.info("поиск B-roll завершён", extra={
        "slots": len(slots), "pool": len(candidates_out), "downloads": downloads,
        "from_cache": from_cache, "stage1_rejected": len(stage1_rejected),
    })
    return {"pool": len(candidates_out), "downloads": downloads, "from_cache": from_cache}


def _tags_for(queries: Iterable[str]) -> list[str]:
    tags: list[str] = []
    for query in queries:
        tags.extend(w.lower() for w in re.findall(r"[a-zA-Z]{3,}", query))
    return list(dict.fromkeys(tags))


def _find_dup(hashes: list[str], pool: list[tuple[str, list[str]]], threshold: int) -> str | None:
    from ..lib.phash import video_is_duplicate

    for item_id, known in pool:
        if video_is_duplicate(hashes, known, threshold):
            return item_id
    return None


def _recent_video_ids(ctx, *, limit: int = 5) -> list[str]:
    """Последние ролики — для правила «не переиспользовать в 5 подряд» (§14.4)."""
    history_path = ctx.cfg.path("paths.cache_dir", "cache") / "run_history.json"
    from ..lib.jsonio import read_json_or

    history = read_json_or(history_path, {"runs": []})
    ids = [r.get("video_id") for r in history.get("runs", []) if r.get("video_id")]
    return ids[-limit:]


def _prefetch_rank(candidate, source_order: list[str], slot_duration: float) -> tuple:
    """Порядок скачивания: сначала то, что вероятнее закроет слот.

    Бюджет скачиваний ограничен 50 на ролик (§7.2.4), поэтому качать надо не
    «что попалось первым», а лучшее по дешёвым признакам: вертикальная
    ориентация (§3.6.5), запас длительности под слот, приоритет источника.
    """
    orientation_rank = {"portrait": 0, "square": 1, "landscape": 2, "unknown": 3}
    try:
        source_rank = source_order.index(candidate.source)
    except ValueError:
        source_rank = len(source_order)
    duration_fit = 0 if candidate.duration_sec >= slot_duration + 0.5 else 1
    return (orientation_rank.get(candidate.orientation, 3), duration_fit, source_rank,
            candidate.id)
