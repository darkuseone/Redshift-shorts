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

from ..lib.ffmpeg import extract_frames, grade_to_palette, probe
from ..lib.logging import get_logger
from ..lib.manifest import FootageIndex, open_library
from ..lib.palette import palette_verdict
from ..lib.phash import phash_image
from ..lib.providers.press import build_press_provider
from ..lib.providers.stock import StockCandidate, build_stock_providers
from ..lib.query import build_queries, classify_intent
from ..lib.render.shots import slim_video

_log = get_logger("p7")


def _load_routing(cfg) -> dict[str, Any]:
    path = cfg.repo_root / "config" / "stock_sources.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _sources_for(intent_kind: str, routing: dict[str, Any]) -> list[str]:
    table = routing.get("routing", {})
    return list(table.get(intent_kind) or table.get("default", ["pexels"]))


def _license_mode(source: str, routing: dict[str, Any]) -> str:
    """Как источник подтверждает лицензию: ``per_item``, ``source_default`` или
    ``owner_decision`` — последнее принимает владелец канала, а не конвейер."""
    spec = ((routing or {}).get("sources") or {}).get(source) or {}
    return str(spec.get("license_check") or "per_item")


def _stage1_reject(candidate: StockCandidate, cfg, slot_duration: float, *,
                   routing: dict[str, Any] | None = None) -> str | None:
    """Шаг 1 §7.3 — дешёвая отбраковка без vision. Возвращает причину или None."""
    if (not candidate.license_confirmed
            and _license_mode(candidate.source, routing or {}) != "owner_decision"):
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


def _article_for(slot: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any] | None:
    """Статья, на которую ссылается блок этого слота, — или ``None``.

    Связь идёт через ``source_ref`` блока, а не через «первый источник ролика»:
    кадр обязан иллюстрировать ту самую статью, которую в этот момент цитируют,
    иначе это уже не реальный материал, а картинка по теме.
    """
    if slot.get("asset_role") != "evidence":
        return None
    block = next((b for b in plan.get("blocks", [])
                  if b.get("id") == slot.get("block_id")), None)
    ref = str((block or {}).get("source_ref") or "").strip().lower()
    if not ref:
        return None
    for source in plan.get("sources", []) or []:
        domain = str(source.get("domain") or "").lower()
        url = str(source.get("url") or "")
        if not url:
            continue
        if ref in (domain, url.lower()) or (domain and domain in ref):
            return {"url": url, "domain": domain,
                    "title": source.get("title", "")}
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

    slots = [s for s in plan["slots"]
             if s["needs_asset"] and s["asset_role"] in ("broll", "evidence", "interstitial")]
    downloads = 0
    researched = 0
    press_used = 0
    press = build_press_provider(cfg, ctx.costs, sources=routing)
    palette_rules = dict(cfg.brandbook.get("color_rules", {}).get("footage_palette", {}))
    # Пресс-кадру палитра канала прощается шире: это цитата в рамке источника, а
    # не фон кадра, и по общему порогу он не проходил бы почти никогда.
    press_palette_max = float(palette_rules.get("press_off_share_max", 0.35))
    grade_rules = {k: float(v) for k, v in
                   (palette_rules.get("press_grade") or {}).items()
                   if k in ("saturation", "red_lift", "contrast")}
    # Вес принимаемого материала. Хранилище живёт в репозитории, и клип на
    # 45 МБ остаётся в истории git навсегда — ужимать надо на приёме.
    slim_max_sec = float(cfg.get("stock.keep_sec", 20.0))
    slim_crf = int(cfg.get("stock.intake_crf", 23))
    max_short_side = int(cfg.get("stock.max_download_height", 1080))

    stage1_rejected: list[dict[str, Any]] = []
    candidates_out: list[dict[str, Any]] = []
    seen_hashes: list[tuple[str, list[str]]] = []
    from_cache = 0
    missing_in_storage: list[str] = []

    frames_dir = ctx.wpath("broll", "frames", ".keep").parent

    for slot in slots:
        intent_kind = classify_intent(slot.get("visual_intent", ""), slot.get("queries", []),
                                      plan.get("category", ""))
        queries = build_queries(slot, plan, count=queries_per_slot)
        source_order = _sources_for(intent_kind, routing)
        slot_candidates: list[dict[str, Any]] = []

        # --- 1. локальная база (§7.2.1) --------------------------------------
        local = index.search(_tags_for(queries), limit=3, exclude_videos=recent_videos,
                             allow_recent=frozen)
        for record in local:
            # Индекс живёт в git, а файлы — во внешнем storage (§14.5). На свежем
            # клоне записи есть, а payload'а нет: предлагать такой материал нельзя,
            # иначе слот «закроется» пустотой и сборка упадёт на подготовке плана.
            if not record.file or not ctx.storage.exists(record.file):
                missing_in_storage.append(record.id)
                continue
            # Кандидат из базы обязан проходить тот же дедуп, что и скачанный:
            # без этого один и тот же кадр попадал в разные слоты и валил QC-5.
            record_hashes = record.phashes or ([record.phash] if record.phash else [])
            if record_hashes:
                dup = _find_dup(record_hashes, seen_hashes, dedup_threshold)
                if dup:
                    stage1_rejected.append({"id": record.id, "source": record.source,
                                            "reason": f"дубль {dup} (материал из базы)",
                                            "query": queries[0]})
                    continue
                seen_hashes.append((record.id, record_hashes))
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
                # Смысл, за который оценка записи получена. Пусто у засева и у
                # старых записей — такой материал судится заново.
                "prior_intent": record.extra.get("judged_intent", ""),
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

        def accept(provider: Any, candidate: Any, query: str, *,
                   origin: str = "stock", palette_max: float | None = None,
                   grade: bool = False) -> bool:
            """Скачать кандидата, промерить и положить в слот. False — не взяли.

            Отдельной функцией, а не телом цикла: тем же путём идёт кадр со
            страницы статьи, и разъехавшись, он потерял бы дедуп, палитру и
            учёт скачиваний — то есть всё, ради чего этот путь и написан.
            """
            nonlocal downloads

            key = _cache_key(candidate)
            local_file = ctx.wpath("broll", "raw", Path(key).name)
            store_after_checks = False
            if ctx.storage.exists(key):
                ctx.storage.get(key, local_file)
            else:
                try:
                    provider.download(candidate, local_file)
                except Exception as exc:  # noqa: BLE001
                    ctx.warn(f"скачивание не удалось: {exc}", id=candidate.id)
                    return False
                if grade:
                    # Грейд ложится в storage вместо исходника, а не рядом с
                    # ним. Иначе возобновлённый прогон, у которого нет рабочего
                    # каталога, вытянет по ключу неотгрейженный кадр — и в
                    # ролик поедет цвет, который отбор уже отклонял.
                    try:
                        graded = local_file.with_name(
                            f"{local_file.stem}_graded{local_file.suffix}")
                        grade_to_palette(local_file, graded, **grade_rules)
                        graded.replace(local_file)
                    except Exception as exc:  # noqa: BLE001 — грейд не роняет прогон
                        ctx.warn(f"грейд не удался, кадр берётся как есть: {exc}",
                                 id=candidate.id)
                # Синтетика мок-режима в общую базу не кладётся — ни записью,
                # ни файлом. Запись индекс отклоняет с прошлой находки, а файл
                # оставался: мок-прогон намывал в assets/footage десятки клипов,
                # и `git add -A` уносил их в репозиторий. Девятнадцать мегабайт
                # за один прогон CI, который гоняется на каждом коммите.
                # В хранилище файл кладётся не здесь, а ниже — после того,
                # как пройдёт палитру и дедуп. Прежде клали сразу после
                # скачивания, и отбракованный кадр всё равно оседал в
                # репозитории навсегда: десять розовых клипов, вычищенных
                # руками, вернулись первым же прогоном, потому что поиск
                # находит их снова, а гейт палитры срабатывал уже после.
                store_after_checks = not candidate.meta.get("mock")
                downloads += 1

            try:
                info = probe(local_file)
            except Exception as exc:  # noqa: BLE001
                ctx.warn(f"битый файл {candidate.id}: {exc}")
                return False

            frames = extract_frames(local_file, frames_dir / candidate.id,
                                    probe_positions if info.has_video else [0.5])
            hashes = [phash_image(f) for f in frames]

            # Палитра канала (§3.1). Судится здесь, а не только у критика:
            # кадр не той палитры отбраковывается до оплаты зрения, а слот
            # успевает уйти на второй заход поиска, а не сразу в генерацию.
            rules = dict(palette_rules)
            if palette_max is not None:
                rules["off_share_max"] = palette_max
            verdict = palette_verdict(frames, rules)
            if not verdict["passed"]:
                stage1_rejected.append({"id": candidate.id, "source": candidate.source,
                                        "reason": verdict["reason"], "query": query})
                return False

            # §7.2.5: дедуп внутри ролика и против всей базы
            dup_local = _find_dup(hashes, seen_hashes, dedup_threshold)
            if dup_local:
                stage1_rejected.append({"id": candidate.id, "source": candidate.source,
                                        "reason": f"визуальный дубль {dup_local} внутри ролика",
                                        "query": query})
                return False
            dup_base = index.find_duplicate(hashes, dedup_threshold)
            if dup_base is not None:
                stage1_rejected.append({"id": candidate.id, "source": candidate.source,
                                        "reason": f"дубль материала из базы {dup_base.id}",
                                        "query": query})
                return False

            # Кандидат прошёл все заслоны — вот теперь его можно хранить.
            # Ужимаем тоже здесь: перекодировка стоит секунд, и тратить их на
            # кадр, который сейчас отбракуют, незачем.
            if store_after_checks:
                slim = slim_video(local_file, max_sec=slim_max_sec,
                                  crf=slim_crf, max_short_side=max_short_side)
                if slim["slimmed"]:
                    _log.info("сток ужат: %s %.1f → %.1f МБ", candidate.id,
                              slim["before"] / 1e6, slim["after"] / 1e6)
                ctx.storage.put(key, local_file)

            seen_hashes.append((candidate.id, hashes))
            slot_candidates.append({
                "slot_index": slot["index"], "origin": origin,
                "asset_id": candidate.id, "source": candidate.source,
                "kind": candidate.kind, "query": query,
                "license": candidate.license,
                "license_confirmed": candidate.license_confirmed or origin != "press",
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
                "palette": verdict,
                "press": dict(candidate.meta) if origin == "press" else {},
            })
            return True

        def harvest(search_queries: list[str]) -> None:
            """Найти, скачать и принять кандидатов по списку запросов.

            Сначала собираем метаданные по всем запросам (это бесплатно), затем
            ранжируем и качаем только лучших. §7.2.4 даёт 50 скачиваний на
            ролик: если тратить их подряд, последние слоты останутся пустыми.
            """
            found_all: list[tuple[str, Any, str]] = []
            for query in search_queries:
                for source in source_order:
                    provider = providers.get(source)
                    if provider is None:
                        continue
                    try:
                        for candidate in provider.search(query, kind="video", limit=per_query):
                            found_all.append((source, candidate, query))
                    except Exception as exc:  # noqa: BLE001 — источник не должен ронять прогон
                        ctx.warn(f"источник {source} недоступен: {exc}",
                                 source=source, query=query)

            passed: list[tuple[str, Any, str]] = []
            for source, candidate, query in found_all:
                reason = _stage1_reject(candidate, cfg, float(slot["duration"]),
                                        routing=routing)
                if reason:
                    stage1_rejected.append({"id": candidate.id, "source": candidate.source,
                                            "reason": reason, "query": query})
                else:
                    passed.append((source, candidate, query))

            passed.sort(key=lambda item: _prefetch_rank(item[1], source_order,
                                                        float(slot["duration"])))

            remaining_slots = max(1, len(slots) - slots.index(slot))
            budget = max(2, (max_downloads - downloads) // remaining_slots)
            taken = 0

            for source, candidate, query in passed:
                if taken >= min(budget, per_query) or downloads >= max_downloads:
                    break
                if accept(providers[source], candidate, query):
                    taken += 1

        # --- 2. Press/news from scripted article URLs (before stock) ---------
        # Always attempt when the draft cites a URL: evidence slots should prefer
        # the real page frame over generic stock, even if local cache already
        # filled something thematic.
        article = _article_for(slot, plan)
        if press is not None and article:
            try:
                found = press.search(article["url"], kind="photo", limit=3)
            except Exception as exc:  # noqa: BLE001
                ctx.warn(f"страница источника недоступна: {exc}",
                         slot=slot["index"], url=article["url"][:120])
                found = []
            for candidate in found:
                reason = _stage1_reject(candidate, cfg, float(slot["duration"]),
                                        routing=routing)
                if reason:
                    stage1_rejected.append({"id": candidate.id, "source": candidate.source,
                                            "reason": reason, "query": article["url"]})
                    continue
                if accept(press, candidate, article["url"], origin="press",
                          palette_max=press_palette_max, grade=True):
                    press_used += 1
                    break

        # --- 3. External stock harvest ---------------------------------------
        harvest(queries)

        # Второй заход. Пустой слот уходит в генерацию (§7.3), а генерация
        # ограничена сорока процентами хронометража (QC-14) и стоит денег.
        # Прежде чем тратить и то и другое, стоит спросить сток ещё раз —
        # запросом, который называет нужную картинку прямо: тёмный кадр,
        # приглушённый цвет. На 0047 сток по запросу «abstract dark red gradient
        # background» отдал стену розовых кубов; уточнение — единственное, чем
        # на это можно ответить, не платя за генерацию.
        if not slot_candidates and not frozen:
            refined = _refine_queries(queries)
            ctx.warn(f"слот {slot['index']}: ни один кандидат не прошёл отбор — "
                     f"второй заход по уточнённым запросам",
                     slot=slot["index"], queries=refined)
            researched += 1
            harvest(refined)

        if not slot_candidates:
            ctx.warn(f"слот {slot['index']} ({slot['block_id']}) не получил ни одного кандидата",
                     slot=slot["index"], queries=queries)
        candidates_out.extend(slot_candidates)

    # --- мемы (§5.8, §14.3) --------------------------------------------------
    # Мем не ищут на стоке и не генерируют: он берётся из собственной
    # курированной базы. Слот планирует P5, а закрыть его должен именно этот
    # шаг — иначе кадр уходит в рендер пустым, как это и случилось на первом
    # ролике, где сработал иронический маркер.
    meme_candidates = _pick_memes(ctx, plan, recent_videos)
    candidates_out.extend(meme_candidates)

    doc = {
        "video_id": plan["video_id"],
        "slots_needing_asset": len(slots) + len(meme_candidates),
        "meme_slots_filled": len(meme_candidates),
        "pool_size": len(candidates_out),
        "pool_target": [pool_min, pool_max],
        "downloads": downloads,
        "download_limit": max_downloads,
        "from_local_cache": from_cache,
        "index_entries_without_files": sorted(set(missing_in_storage)),
        "cache_share": round(from_cache / max(len(candidates_out), 1), 4),
        "stage1_rejected": stage1_rejected,
        "slots_researched": researched,
        "slots_from_press": press_used,
        "stage1_reject_share": round(
            len(stage1_rejected) / max(len(stage1_rejected) + len(candidates_out), 1), 4),
        "candidates": candidates_out,
    }
    ctx.write("candidates.json", doc)

    if missing_in_storage:
        ctx.warn(f"{len(set(missing_in_storage))} записей индекса без файлов в storage — "
                 f"пропущены; вычистить: python -m src.cli maintenance",
                 count=len(set(missing_in_storage)))
    if len(candidates_out) < pool_min:
        ctx.warn(f"пул кандидатов {len(candidates_out)} меньше рекомендованных {pool_min} (§7.2.3)",
                 pool=len(candidates_out))
    _log.info("поиск B-roll завершён", extra={
        "slots": len(slots), "pool": len(candidates_out), "downloads": downloads,
        "from_cache": from_cache, "stage1_rejected": len(stage1_rejected),
        "researched": researched, "press": press_used,
    })
    return {"pool": len(candidates_out), "downloads": downloads,
            "from_cache": from_cache, "researched": researched,
            "press": press_used}


def _pick_memes(ctx, plan: dict[str, Any], recent_videos: list[str]) -> list[dict[str, Any]]:
    """Закрыть мем-слоты карточками из библиотеки (§5.8, §14.3).

    Эмоция берётся из причины вставки: P5 ставит мем там, где нашёл
    иронический маркер, и «ирония» — это и есть тег в базе. Один и тот же мем
    в ролике не повторяется, а использованный в последних роликах берётся лишь
    когда другого нет: §14.3 требует, чтобы мемы не примелькались.
    """
    meme_slots = [s for s in plan["slots"] if s.get("needs_asset") and s.get("asset_role") == "meme"]
    if not meme_slots:
        return []

    library = open_library(ctx.cfg, "memes")
    if not library.items:
        ctx.warn(f"{len(meme_slots)} мем-слотов не закрыты: библиотека мемов пуста "
                 f"(§14.3, наполнить: python -m src.cli fill-libraries --kind memes)",
                 slots=[s["index"] for s in meme_slots])
        return []

    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for slot in meme_slots:
        emotion = str(slot.get("meme_emotion") or "").strip()
        wanted = [emotion] if emotion else []
        ranked = library.find_by_tags(wanted, exclude_recent=recent_videos, cooldown=5)
        # Ни по тегу, ни по «свежести» — берём наименее использованный: пустой
        # кадр хуже повтора.
        pool = ranked or sorted(library.items, key=lambda i: (len(i.used_in), i.id))
        record = next((i for i in pool if i.id not in used), pool[0] if pool else None)
        if record is None:
            continue
        used.add(record.id)
        path = library.dir / record.file
        if not path.is_file():
            ctx.warn(f"мем {record.id} есть в манифесте, но файла нет: {path}",
                     slot=slot["index"], asset_id=record.id)
            continue
        out.append({
            "slot_index": slot["index"], "origin": "meme_library",
            "asset_id": record.id, "source": record.source, "kind": "image",
            "query": emotion or "meme", "license": record.license,
            "license_confirmed": True,
            "attribution": "собственная база REDSHIFT (§14.3)",
            "author": "REDSHIFT", "page_url": "",
            "width": 0, "height": 0, "duration_sec": record.duration_sec,
            "fps": 0.0, "local_file": str(path), "storage_key": "",
            "tags": record.tags, "phashes": [record.phash] if record.phash else [],
            "mock": bool(record.mock),
        })
    return out


# Слова, которыми запрос объясняет стоку палитру канала. Не перевод брендбука,
# а то, на что сток отзывается: у стоков нет поля «оттенок», зато есть теги.
_PALETTE_HINTS = ("dark", "low key", "black background", "monochrome", "desaturated")


def _refine_queries(queries: Iterable[str], limit: int = 3) -> list[str]:
    """Те же запросы, но с прямым указанием на палитру.

    Второй заход отличается от первого только этим: искать то же самое ещё раз
    теми же словами бессмысленно — сток отдаст ту же выдачу.
    """
    base = [q for q in queries if q][:limit]
    return [f"{q} {hint}" for q, hint in zip(base, _PALETTE_HINTS)]


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
