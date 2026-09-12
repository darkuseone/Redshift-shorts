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

import math
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..lib.ffmpeg import extract_frames, grade_to_palette, probe
from ..lib.hydrate_footage import hydrate_repo_footage
from ..lib.logging import get_logger
from ..lib.manifest import AssetRecord, FootageIndex, open_library, tag_url_coherence
from ..lib.palette import palette_verdict
from ..lib.phash import phash_image
from ..lib.pin_match import (
    ctx_words, filter_queries_for_beat, pin_slot_prefer_key, slot_visual_beat,
)
from ..lib.providers.press import build_press_provider
from ..lib.providers.stock import StockCandidate, build_stock_providers
from ..lib.query import (
    QUERY_MAX, QUERY_MIN, TEXTURE_FILL, TEXTURE_FILL_ALT, allow_generic_pad,
    classify_intent, compile_slot_search, extra_fits_slot, is_sci_topic,
    negative_reject_reason, search_report_payload, thematic_reject_reason,
    topical_tokens,
)
from ..lib.render.shots import slim_video
from ..lib.text import sync_broll_from_script

SCI_QUERY_PAD = (
    "dilution refrigerator",
    "cryostat gold cylinder",
    "quantum processor macro",
    "cleanroom laboratory",
    "supercomputer server blink",
)
SPACE_NEWS_PAD = (
    "deep space stars",
    "galaxy nebula",
    "earth orbit view",
    "newsroom broadcast desk",
    "breaking news screen",
)


def pad_slot_queries(
    queries: list[str],
    *,
    queries_per_slot: int,
    intent_kind: str = "",
    category: str = "",
    slot: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    entities: Iterable[str] | None = None,
) -> list[str]:
    """Дополнить короткую лестницу запросов.

    Научный слот сначала получает лабораторию и чип, и только потом — общий
    пад. Сам общий пад проходит через гейт §9.1: пять запросов про космос и
    студию новостей подходят чему угодно и поэтому не подходят ничему.
    Подмешивались они **в каждый слот каждого ролика**, и ролик про квантовый
    чип честно получал галактику.

    MUST-016: пад, который не делит слова с сущностью/понятием блока,
    не добавляется. Потолок — 5 запросов.
    """
    cap = min(QUERY_MAX, max(1, int(queries_per_slot)))
    out = list(queries)[:cap]
    if len(out) >= cap:
        return out
    tokens = topical_tokens(slot or {}, plan or {}, out)
    for ent in entities or ():
        tokens.update(w.lower() for w in str(ent).split() if len(w) > 2)
    extras: list[str] = []
    if is_sci_topic(category=category, intent_kind=intent_kind):
        extras.extend(extra for extra in SCI_QUERY_PAD
                      if extra_fits_slot(extra, tokens))
    if slot is None or allow_generic_pad(slot, plan, intent_kind=intent_kind,
                                         category=category):
        extras.extend(extra for extra in SPACE_NEWS_PAD
                      if extra_fits_slot(extra, tokens))
    existing = {q.lower() for q in out}
    for extra in extras:
        if len(out) >= cap:
            break
        if extra.lower() not in existing:
            out.append(extra)
            existing.add(extra.lower())
    if len(out) < QUERY_MIN:
        for fill in (TEXTURE_FILL, TEXTURE_FILL_ALT):
            if fill.lower() not in existing:
                out.append(fill)
                existing.add(fill.lower())
            if len(out) >= QUERY_MIN:
                break
    return out[:cap]


def short_side_over_cap(width: Any, height: Any, max_h: int = 1080) -> bool:
    """True если короткая сторона > потолка скачивания (§3.6.1, MUST-018)."""
    try:
        w, h = int(width or 0), int(height or 0)
    except (TypeError, ValueError):
        return False
    if not w or not h:
        return False
    return min(w, h) > int(max_h)


def stage1_dead_ids(rows: Iterable[dict[str, Any]] | None) -> set[str]:
    """Id, которые нельзя судить зрением (MUST-018).

    Дубль внутри ролика — не смерть клипа: тот же файл уже принят в другой
    слот, и P8 не имеет права выкинуть его и там, где он единственный
    кандидат. Иначе кэш из пяти клипов даёт fill_rate 0.
    """
    dead: set[str] = set()
    for row in rows or ():
        aid = str(row.get("id") or "")
        if not aid:
            continue
        reason = str(row.get("reason") or "").casefold()
        if "дубль" in reason or "duplicate" in reason:
            continue
        dead.add(aid)
    return dead


def judge_blocks_stage1_dead(candidate: dict[str, Any], *,
                             dead_ids: set[str], max_h: int = 1080) -> str | None:
    """Почему кандидат нельзя отдавать vision. None — можно."""
    aid = str(candidate.get("asset_id") or candidate.get("id") or "")
    if aid and aid in dead_ids:
        return "stage1_dead"
    if short_side_over_cap(candidate.get("width"), candidate.get("height"), max_h):
        return f"short_side>{max_h}"
    return None


def footage_pool_count(candidates: Iterable[dict[str, Any]]) -> int:
    """Кандидаты футажа без мемов — знаменатель surplus."""
    return sum(1 for c in candidates if str(c.get("origin") or "") != "meme_library")


def surplus_target(slots_needing: int, ratio: float = 1.3) -> int:
    """ceil(ratio × слотов с футажом). 10 слотов → 13 кандидатов."""
    return math.ceil(float(ratio) * max(0, int(slots_needing)))


def surplus_report(n_candidates: int, slots_needing: int,
                   ratio: float = 1.3) -> dict[str, Any]:
    """Сводка +30% запаса до Gemini/Grok/Magnific (MUST-017)."""
    target = surplus_target(slots_needing, ratio)
    ok = True if slots_needing <= 0 else int(n_candidates) >= target
    return {
        "ratio": float(ratio),
        "slots_needing_footage": int(slots_needing),
        "candidates": int(n_candidates),
        "target": int(target),
        "ok": ok,
        "status": "ok" if ok else "underfilled",
    }


_log = get_logger("p7")


def _load_routing(cfg) -> dict[str, Any]:
    path = cfg.repo_root / "config" / "stock_sources.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _source_enabled(name: str, routing: dict[str, Any] | None) -> bool:
    """False when yaml says enabled: false — disabled donors stay research-only."""
    spec = ((routing or {}).get("sources") or {}).get(name)
    if spec is None:
        return True
    return bool(spec.get("enabled", True))


def _sources_for(intent_kind: str, routing: dict[str, Any]) -> list[str]:
    table = routing.get("routing", {})
    names = list(table.get(intent_kind) or table.get("default", ["pexels"]))
    return [n for n in names if _source_enabled(n, routing)]


def live_unconfirmed_sources(routing: dict[str, Any] | None) -> list[str]:
    """Live routing ∩ donors whose yaml license is unconfirmed or a known lie.

    MUST-027: esa.int as CC-BY-SA and Mixkit as source_default live = ∅.
    """
    routing = routing or {}
    sources = routing.get("sources") or {}
    routed: set[str] = set()
    for names in (routing.get("routing") or {}).values():
        for name in names or []:
            if _source_enabled(str(name), routing):
                routed.add(str(name))
    bad: list[str] = []
    for name in sorted(routed):
        spec = sources.get(name) or {}
        lic = str(spec.get("license") or "")
        if spec.get("research_only") or spec.get("live") is False:
            bad.append(name)
            continue
        if spec.get("license_unconfirmed"):
            bad.append(name)
            continue
        if "ESA-CC-BY-SA" in lic or (name == "esa" and "CC-BY-SA" in lic.upper()):
            bad.append(name)
            continue
        if name == "mixkit" and str(spec.get("license_check") or "") != "per_item":
            bad.append(name)
    return bad


def _restricted_license_reason(candidate: Any) -> str | None:
    """Mixkit videoRestricted and similar per-item bans before download."""
    meta = candidate.meta if isinstance(getattr(candidate, "meta", None), dict) else {}
    data_license = str(meta.get("data-license") or meta.get("data_license") or "")
    lic = " ".join([
        str(getattr(candidate, "license", "") or ""),
        data_license,
        str(meta.get("license") or ""),
    ]).lower()
    compact = re.sub(r"[^a-z0-9]+", "", lic)
    source = str(getattr(candidate, "source", "") or "").lower()
    if "videorestricted" in compact or data_license.lower() == "videorestricted":
        return "Mixkit Restricted — нельзя на monetized канал"
    if source == "mixkit" and "restricted" in lic:
        return "Mixkit Restricted — нельзя на monetized канал"
    return None


def missing_on_screen_credit(asset: dict[str, Any],
                             routing: dict[str, Any] | None) -> str | None:
    """Hubble/Webb/ESO CC BY 4.0: credit in frame/end card, not description-only."""
    source = str((asset or {}).get("source") or "").strip()
    spec = ((routing or {}).get("sources") or {}).get(source) or {}
    if not spec.get("on_screen_credit"):
        return None
    credit = " ".join([
        str((asset or {}).get("credit") or ""),
        str((asset or {}).get("attribution") or ""),
    ]).strip()
    if credit:
        return None
    return (f"{source}: нужен кредит в кадре (CC BY 4.0), "
            "не только YouTube description")


def _license_mode(source: str, routing: dict[str, Any]) -> str:
    """Как источник подтверждает лицензию: ``per_item``, ``source_default`` или
    ``owner_decision`` — последнее принимает владелец канала, а не конвейер."""
    spec = ((routing or {}).get("sources") or {}).get(source) or {}
    return str(spec.get("license_check") or "per_item")


def _stage1_reject(candidate: StockCandidate, cfg, slot_duration: float, *,
                   routing: dict[str, Any] | None = None,
                   category: str = "", intent_kind: str = "",
                   pin_deny: set[str] | None = None,
                   video_id: str = "",
                   negatives: Iterable[str] | None = None) -> str | None:
    """Шаг 1 §7.3 — дешёвая отбраковка без vision. Возвращает причину или None."""
    if pin_id_denied(getattr(candidate, "id", "") or "", pin_deny or set()):
        return f"pin_deny: {candidate.id}"
    if (not candidate.license_confirmed
            and _license_mode(candidate.source, routing or {}) != "owner_decision"):
        return "лицензия не подтверждена (§7.2.7)"
    restricted = _restricted_license_reason(candidate)
    if restricted:
        return restricted
    if not _source_enabled(str(candidate.source or ""), routing or {}):
        return f"источник {candidate.source} выключен (research-only / нет проверенной лицензии)"
    max_h = int(cfg.get("stock.max_download_height", 1080))
    if short_side_over_cap(candidate.width, candidate.height, max_h):
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
    # Sci light guardrail: URL/title/tags must not look like drug/hose junk or
    # known off-theme mis-picks (darkroom-as-cryostat, race-day-as-circuit).
    hay = " ".join([
        candidate.id or "",
        candidate.source or "",
        candidate.page_url or "",
        candidate.attribution or "",
        candidate.query or "",
        " ".join(candidate.tags or []),
        str((candidate.meta or {}).get("title") or ""),
        str((candidate.meta or {}).get("alt") or ""),
    ])
    thematic = thematic_reject_reason(
        hay, category=category, intent_kind=intent_kind, video_id=video_id)
    if thematic:
        return thematic
    denied = negative_reject_reason(hay, negatives)
    if denied:
        return denied
    return None


def _local_thematic_reject(record, *, category: str = "",
                           intent_kind: str = "",
                           video_id: str = "") -> str | None:
    """Same junk guard for footage_index rows (local_cache bypassed stage1)."""
    hay = " ".join([
        getattr(record, "url_origin", "") or "",
        " ".join(getattr(record, "tags", None) or []),
        getattr(record, "vision_summary", "") or "",
        str((getattr(record, "extra", None) or {}).get("attribution") or ""),
        str((getattr(record, "extra", None) or {}).get("judged_intent") or ""),
        getattr(record, "id", "") or "",
    ])
    return thematic_reject_reason(
        hay, category=category, intent_kind=intent_kind, video_id=video_id)


_ORPHAN_LICENSE = {
    "pexels": "Pexels License",
    "pixabay": "Pixabay Content License",
}


def disk_orphan_records(ctx, index: FootageIndex) -> list[AssetRecord]:
    """Файлы в ``assets/footage/{pexels,pixabay}``, которых нет в индексе.

    Прошлые прогоны оставили клипы на диске, а LRU вычистил запись. Без этой
    доборки P7 видит пять строк индекса и оставляет слоты пустыми при freeze.
    """
    root = ctx.cfg.path("storage.local_root", "assets/footage")
    found: list[AssetRecord] = []
    for source, license_ in _ORPHAN_LICENSE.items():
        folder = root / source
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.mp4")):
            asset_id = path.stem
            if index.by_id(asset_id) is not None:
                continue
            rel = f"{source}/{path.name}"
            try:
                info = probe(path)
            except Exception:  # noqa: BLE001
                continue
            found.append(AssetRecord(
                id=asset_id, type="video", source=source, license=license_,
                url_origin=f"https://www.{source}.com/video/{asset_id.split('_')[-1]}/",
                tags=[source, "video"], vision_summary="",
                score=0.45, duration_sec=float(info.duration_sec or 0.0),
                width=int(info.width or 0), height=int(info.height or 0),
                file=rel, extra={"attribution": f"{source} / local cache",
                                 "orphan_ingest": True},
            ))
    # Magnific plates committed under assets/footage/magnific
    seen_ids = {r.id for r in found}
    for folder in (root / "magnific", Path(ctx.cfg.repo_root) / "assets" / "footage" / "magnific"):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.mp4")):
            asset_id = path.stem
            if asset_id in seen_ids or index.by_id(asset_id) is not None:
                continue
            rel = f"magnific/{path.name}"
            try:
                info = probe(path)
            except Exception:
                continue
            found.append(AssetRecord(
                id=asset_id, type="video", source="magnific", license="owner_decision",
                url_origin="",
                tags=["magnific", "video"], vision_summary="",
                score=0.75, duration_sec=float(info.duration_sec or 0.0),
                width=int(info.width or 0), height=int(info.height or 0),
                file=rel, ai_generated=False,
                extra={"attribution": "magnific / repo assets", "orphan_ingest": True},
            ))
            seen_ids.add(asset_id)
    return found


def _local_cache_row(slot_index: int, record: AssetRecord, query: str) -> dict[str, Any]:
    """Кандидат из локальной базы / дискового добора — с url_origin для P8."""
    hashes = record.phashes or ([record.phash] if record.phash else [])
    extra = record.extra or {}
    url = record.url_origin or ""
    return {
        "slot_index": slot_index, "origin": "local_cache",
        "asset_id": record.id, "source": record.source,
        "kind": record.type, "query": query,
        "license": record.license, "license_confirmed": True,
        "width": record.width, "height": record.height,
        "duration_sec": record.duration_sec,
        "phashes": hashes,
        "storage_key": record.file, "tags": record.tags,
        "vision_summary": record.vision_summary, "prior_score": record.score,
        "prior_intent": extra.get("judged_intent", ""),
        "ai_generated": record.ai_generated, "mock": record.mock,
        "attribution": extra.get("attribution", ""),
        "page_url": url, "url_origin": url,
    }


def _local_reject_reason(record, *, category: str, intent_kind: str,
                         video_id: str, negatives: list[str],
                         max_short_side: int) -> str | None:
    """Theme / negatives / resolution — одинаково для индекса и дискового добора."""
    theme_reason = _local_thematic_reject(
        record, category=category, intent_kind=intent_kind, video_id=video_id)
    if not theme_reason:
        local_hay = " ".join([
            getattr(record, "url_origin", "") or "",
            " ".join(getattr(record, "tags", None) or []),
            getattr(record, "vision_summary", "") or "",
            getattr(record, "id", "") or "",
        ])
        theme_reason = negative_reject_reason(local_hay, negatives)
    if not theme_reason and short_side_over_cap(
            getattr(record, "width", 0), getattr(record, "height", 0),
            max_short_side):
        theme_reason = f"разрешение выше {max_short_side}p — по §3.6.1 не берём"
    return theme_reason


def _local_overlap(record, queries: list[str]) -> int:
    wanted = {w.lower() for q in queries for w in q.split() if len(w) > 2}
    tags = {t.lower() for t in (getattr(record, "tags", None) or [])}
    hay = f"{getattr(record, 'url_origin', '')} {getattr(record, 'vision_summary', '')}".lower()
    return len(wanted & tags) + sum(1 for w in wanted if w in hay)


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



def _footage_pin_entry(cfg, video_id: str) -> dict[str, Any]:
    """Raw per-video pin object from config/footage_pins.json, or {}."""
    from pathlib import Path as _P
    try:
        path = cfg.path("paths.footage_pins", "config/footage_pins.json")
    except Exception:
        path = _P("config/footage_pins.json")
    if not _P(path).exists():
        path = _P("config/footage_pins.json")
    if not _P(path).exists():
        return {}
    try:
        import json as _json
        data = _json.loads(_P(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    entry = data.get(video_id) or {}
    return entry if isinstance(entry, dict) else {}


def pin_id_denied(asset_id: str, deny: set[str]) -> bool:
    """True when the id is listed or matches a deny prefix token (``nasa_*``)."""
    aid = str(asset_id or "")
    if not aid or not deny:
        return False
    if aid in deny:
        return True
    for token in deny:
        if token.endswith("*") and len(token) > 1 and aid.startswith(token[:-1]):
            return True
    return False


def _load_footage_by_block(cfg, video_id: str) -> dict[str, str | None]:
    """Hard per-block asset pins from footage_pins.json ``by_block`` map."""
    entry = _footage_pin_entry(cfg, video_id)
    raw = entry.get("by_block") or {}
    out: dict[str, str | None] = {}
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        bid = str(key or "").strip()
        if not bid:
            continue
        out[bid] = None if val is None else str(val)
    return out


def _load_footage_pins(cfg, video_id: str) -> tuple[set[str], list[str]]:
    """Return (deny_ids, prefer_ids) for this video from config/footage_pins.json."""
    entry = _footage_pin_entry(cfg, video_id)
    deny = {str(x) for x in (entry.get("deny") or []) if x}
    prefer = [str(x) for x in (entry.get("prefer") or []) if x]
    return deny, prefer


def run_step(ctx) -> dict[str, Any]:
    plan = ctx.read("cut_plan.json")
    words = ctx_words(ctx)
    sync_broll_from_script(plan, ctx.cfg.repo_root, words=words)
    cfg = ctx.cfg
    routing = _load_routing(cfg)
    providers = build_stock_providers(cfg, ctx.costs)
    index = FootageIndex.load(cfg)
    pin_deny, pin_prefer = _load_footage_pins(cfg, str(plan.get("video_id") or ""))
    orphans = disk_orphan_records(ctx, index)
    if orphans:
        ctx.warn(f"на диске {len(orphans)} клипов стока нет в индексе — добор",
                 count=len(orphans))
    hydrate_repo_footage(ctx, index)

    queries_per_slot = min(QUERY_MAX, max(3, int(cfg.get("stock.queries_per_slot", 5))))
    per_query = int(cfg.get("stock.max_candidates_per_query", 8))
    pool_min, pool_max = cfg.get("stock.target_pool_size", [30, 60])
    surplus_ratio = float(cfg.get("stock.candidate_surplus", 1.3))
    max_downloads = int(cfg.get("magnific.max_downloads_per_video", 50))
    probe_positions = cfg.get("stock.video_probe_frames", [0.10, 0.50, 0.90])
    dedup_threshold = int(cfg.get("stock.dedup_hamming_max", 8))
    frozen = bool(cfg.get("libraries.footage.freeze", False))

    # Материал из последних 5 роликов не переиспользуем при наличии альтернативы.
    # Текущий id из истории выкидываем: иначе повторный прогон того же ролика
    # исключает собственные клипы (used_in уже содержит этот id после QC).
    recent_videos = _recent_video_ids(
        ctx, limit=5, current=str(plan.get("video_id") or ""))

    # Перебивка — тот же b-roll, только с отдельной ролью: она живёт 1.4
    # секунды и обязана быть событием, поэтому судится строже по светлоте.
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
    # Только первый кандидат слота занимает id. keep_per_slot=2 парковал
    # неиспользованные prefer как запасные — taken_ids сжигал их, и хвост
    # ролика (0042: криостат Grok) оставался пустым.
    exclusive_ids: set[str] = set()
    remote_pin_tried: set[str] = set()
    from_cache = 0
    missing_in_storage: list[str] = []
    slot_search: list[dict[str, Any]] = []

    frames_dir = ctx.wpath("broll", "frames", ".keep").parent

    for slot in slots:
        search_slot = slot
        if str(plan.get("video_id") or "") == "redshift_0050":
            beat = slot_visual_beat(slot, words)
            filtered = filter_queries_for_beat(list(slot.get("queries") or []), beat)
            if filtered:
                search_slot = dict(slot)
                search_slot["queries"] = filtered
        intent_kind = classify_intent(search_slot.get("visual_intent", ""),
                                      search_slot.get("queries", []),
                                      plan.get("category", ""))
        compiled = compile_slot_search(search_slot, plan, count=queries_per_slot)
        queries = pad_slot_queries(
            compiled["queries"],
            queries_per_slot=queries_per_slot,
            intent_kind=intent_kind,
            category=str(plan.get("category") or ""),
            slot=slot,
            plan=plan,
            entities=compiled["entities"],
        )
        negatives = list(compiled["negatives"])
        slot_search.append({
            "slot_index": slot["index"],
            "block_id": slot.get("block_id"),
            "queries": list(queries),
            "entities": list(compiled["entities"]),
            "negatives": negatives,
        })
        source_order = _sources_for(intent_kind, routing)
        slot_candidates: list[dict[str, Any]] = []

        # --- 1. локальная база (§7.2.1) --------------------------------------
        local_limit = max(6, int(cfg.get("stock.local_candidates_per_slot", 24)))
        keep_per_slot = max(1, int(cfg.get("stock.local_keep_per_slot", 2)))
        local = index.search(_tags_for(queries), limit=local_limit,
                             exclude_videos=recent_videos,
                             allow_recent=frozen)
        # Pins: hard deny + inject/boost prefer so P8 can hard-accept them.
        if pin_deny:
            local = [r for r in local if not pin_id_denied(r.id, pin_deny)]
        if pin_prefer:
            have = {r.id for r in local}
            for pid in pin_prefer:
                if pid in have or pin_id_denied(pid, pin_deny):
                    continue
                rec = index.by_id(pid)
                if rec is None or rec.quarantined:
                    continue
                if not rec.file:
                    continue
                local.append(rec)
                have.add(pid)
            prefer_set = set(pin_prefer)
            local = sorted(local, key=lambda r: (0 if r.id in prefer_set else 1, -r.score))
        taken_ids = set(exclusive_ids)
        category = str(plan.get("category") or "")
        video_id = str(plan.get("video_id") or "")
        pooled: list[tuple[Any, dict[str, Any]]] = []
        for record in local:
            # Индекс живёт в git, а файлы — во внешнем storage (§14.5). На свежем
            # клоне записи есть, а payload'а нет: предлагать такой материал нельзя,
            # иначе слот «закроется» пустотой и сборка упадёт на подготовке плана.
            if record.id in taken_ids or pin_id_denied(record.id, pin_deny):
                continue
            if not record.file or not ctx.storage.exists(record.file):
                missing_in_storage.append(record.id)
                continue
            theme_reason = _local_reject_reason(
                record, category=category, intent_kind=intent_kind,
                video_id=video_id, negatives=negatives,
                max_short_side=max_short_side)
            if theme_reason:
                stage1_rejected.append({
                    "id": record.id, "source": record.source,
                    "reason": theme_reason, "query": queries[0],
                })
                continue
            coherence = tag_url_coherence(record)
            if coherence < 0.15:
                stage1_rejected.append({
                    "id": record.id, "source": record.source,
                    "reason": f"tag_url_coherence {coherence:.2f} < 0.15",
                    "query": queries[0],
                })
                continue
            if frozen and float(record.score or 0) < float(
                    cfg.get("vision.accept_threshold", 0.70)):
                # Freeze: paid critic выключен. P8 не примет 0.55 как accept,
                # слот останется пустым — лучше сразу отдать место добору.
                continue
            pooled.append((record, _local_cache_row(slot["index"], record, queries[0])))

        prefer_set = set(pin_prefer)
        pooled.sort(key=lambda pair: (
            pin_slot_prefer_key(pair[0].id, slot, pin_prefer, words=words)[0],
            0 if pair[0].id in prefer_set else 1,
            -float(pair[0].score or 0),
        ))
        # Хеши помечаем только у выбранных: иначе слот 0 сжигает уникальный
        # пул, а хвост ролика видит одни «дубли из базы».
        for record, row in pooled:
            if len(slot_candidates) >= keep_per_slot:
                break
            hashes = row.get("phashes") or []
            if hashes:
                dup = _find_dup(hashes, seen_hashes, dedup_threshold)
                if dup:
                    stage1_rejected.append({
                        "id": record.id, "source": record.source,
                        "reason": f"дубль {dup} (материал из базы)",
                        "query": queries[0],
                    })
                    continue
                seen_hashes.append((record.id, hashes))
            slot_candidates.append(row)
            from_cache += 1
        if slot_candidates:
            primary = str(slot_candidates[0].get("asset_id") or "")
            if primary:
                exclusive_ids.add(primary)
                taken_ids.add(primary)

        # Prefer-пины и лимит поиска занимали первые слоты одними и теми же
        # id: хвост ролика видел только «дубль из базы». Если слот пуст —
        # берём уникальный оставшийся клип из индекса и с диска.
        if not slot_candidates:
            ranked = sorted(
                list(index.items) + list(orphans),
                key=lambda rec: (
                    0 if rec.id in set(pin_prefer) else 1,
                    -_local_overlap(rec, queries),
                    -float(rec.score or 0),
                ),
            )
            for record in ranked:
                if record.id in taken_ids or pin_id_denied(record.id, pin_deny):
                    continue
                if getattr(record, "quarantined", False):
                    continue
                # Тот же запрет, что у index.search: пустой слот не должен
                # подбирать кадр из последних пяти роликов и валить QC-6.
                if (not frozen and recent_videos
                        and set(record.used_in or []) & set(recent_videos)):
                    continue
                if not record.file or not ctx.storage.exists(record.file):
                    continue
                # Empty-slot fallback used to dump any orphan (tags=[pexels,video],
                # score 0.72) into a quantum cut — earth, galaxy, a chemistry
                # beaker. Require a real overlap with the slot queries.
                if _local_overlap(record, queries) < 1:
                    continue
                theme_reason = _local_reject_reason(
                    record, category=category, intent_kind=intent_kind,
                    video_id=video_id, negatives=negatives,
                    max_short_side=max_short_side)
                if theme_reason:
                    continue
                if tag_url_coherence(record) < 0.15:
                    continue
                if frozen and float(record.score or 0) < float(
                        cfg.get("vision.accept_threshold", 0.70)):
                    continue
                record_hashes = record.phashes or ([record.phash] if record.phash else [])
                if record_hashes:
                    dup = _find_dup(record_hashes, seen_hashes, dedup_threshold)
                    if dup:
                        continue
                    seen_hashes.append((record.id, record_hashes))
                slot_candidates.append(
                    _local_cache_row(slot["index"], record, queries[0]))
                from_cache += 1
                exclusive_ids.add(record.id)
                taken_ids.add(record.id)
                break

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
                reason = _stage1_reject(
                    candidate, cfg, float(slot["duration"]), routing=routing,
                    category=str(plan.get("category") or ""),
                    intent_kind=intent_kind, pin_deny=pin_deny,
                    video_id=str(plan.get("video_id") or ""),
                    negatives=negatives)
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

        # --- 2. кадр из самой статьи (§7.2, «реальный материал») -------------
        # Заказчик просил брать материал прямо со страницы, на которую ролик и
        # ссылается. Это идёт до стоков: слот доказательства лучше закрыть той
        # самой статьей, чем «чем-нибудь по теме», и уж точно лучше, чем
        # генерацией. Палитра здесь мягче: пресс-кадр — цитата в рамке
        # источника, и требовать от него палитру канала значит не брать его
        # никогда.
        article = _article_for(slot, plan)
        if press is not None and article and not slot_candidates:
            try:
                # Просим не один кадр, а сколько есть: у страницы og:image один,
                # но брать надо первый **прошедший** отбор, а не первый по счёту.
                found = press.search(article["url"], kind="photo", limit=3)
            except Exception as exc:  # noqa: BLE001 — страница не должна ронять прогон
                ctx.warn(f"страница источника недоступна: {exc}",
                         slot=slot["index"], url=article["url"][:120])
                found = []
            for candidate in found:
                reason = _stage1_reject(
                    candidate, cfg, float(slot["duration"]), routing=routing,
                    category=str(plan.get("category") or ""),
                    intent_kind=intent_kind, pin_deny=pin_deny,
                    video_id=str(plan.get("video_id") or ""),
                    negatives=negatives)
                if reason:
                    stage1_rejected.append({"id": candidate.id, "source": candidate.source,
                                            "reason": reason, "query": article["url"]})
                    continue
                if accept(press, candidate, article["url"], origin="press",
                          palette_max=press_palette_max, grade=True):
                    press_used += 1
                    break

        # Prefer Freepik IDs that are not in the local index: download by id
        # only when pin_match says this slot is the one (bonus < 0).
        fp_provider = providers.get("freepik")
        if fp_provider is not None and pin_prefer:
            for pid in pin_prefer:
                if not pid.startswith("freepik_") or pid in remote_pin_tried:
                    continue
                if pin_id_denied(pid, pin_deny):
                    continue
                if any(str(row.get("asset_id") or "") == pid
                       for row in slot_candidates):
                    continue
                rec = index.by_id(pid)
                if rec is not None and rec.file and ctx.storage.exists(rec.file):
                    continue
                bonus = pin_slot_prefer_key(pid, slot, pin_prefer, words=words)[0]
                if bonus >= 0:
                    continue
                remote_pin_tried.add(pid)
                cand = StockCandidate(
                    id=pid, source="freepik", kind="video", query=pid,
                    license=getattr(fp_provider, "license_name", "") or "Freepik",
                    license_confirmed=True, attribution="Freepik",
                )
                if accept(fp_provider, cand, queries[0] if queries else pid):
                    exclusive_ids.add(pid)

        # --- 3. внешние стоки -------------------------------------------------
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

        # MUST-017: запас +30% добирается дешёвым поиском, не vision/Magnific.
        have_so_far = footage_pool_count(candidates_out) + len(slot_candidates)
        expected_so_far = surplus_target(slots.index(slot) + 1, surplus_ratio)
        if not frozen and have_so_far < expected_so_far:
            extra = [q for q in _refine_queries(queries, limit=3) if q not in queries]
            if extra:
                harvest(extra)
                researched += 1

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

    surplus = surplus_report(
        footage_pool_count(candidates_out), len(slots), surplus_ratio)
    search_blob = search_report_payload(slot_search)
    search_blob["surplus"] = surplus

    doc = {
        "video_id": plan["video_id"],
        "slots_needing_asset": len(slots) + len(meme_candidates),
        "meme_slots_filled": len(meme_candidates),
        "pool_size": len(candidates_out),
        "pool_target": [pool_min, pool_max],
        "surplus": surplus,
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
        "search": search_blob,
        "candidates": candidates_out,
    }
    ctx.write("candidates.json", doc)

    if missing_in_storage:
        ctx.warn(f"{len(set(missing_in_storage))} записей индекса без файлов в storage — "
                 f"пропущены; вычистить: python -m src.cli maintenance",
                 count=len(set(missing_in_storage)))
    if not surplus["ok"]:
        ctx.warn(
            f"surplus {surplus['candidates']}/{surplus['target']} "
            f"({surplus['ratio']:.1f}×) — paid critic не вызывать",
            **{k: surplus[k] for k in ("candidates", "target", "slots_needing_footage")})
    if len(candidates_out) < pool_min:
        ctx.warn(f"пул кандидатов {len(candidates_out)} меньше рекомендованных {pool_min} (§7.2.3)",
                 pool=len(candidates_out))
    _log.info("поиск B-roll завершён", extra={
        "slots": len(slots), "pool": len(candidates_out), "downloads": downloads,
        "from_cache": from_cache, "stage1_rejected": len(stage1_rejected),
        "researched": researched, "press": press_used,
        "surplus": surplus["status"],
    })
    return {"pool": len(candidates_out), "downloads": downloads,
            "from_cache": from_cache, "researched": researched,
            "press": press_used, "surplus": surplus["status"]}


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


def _recent_video_ids(ctx, *, limit: int = 5, current: str = "") -> list[str]:
    """Последние ролики — для правила «не переиспользовать в 5 подряд» (§14.4).

    ``current`` — id ролика, который сейчас собираем. Он может уже стоять
    в ``run_history`` после проваленного QC; в пятёрку соседей он не входит.
    """
    history_path = ctx.cfg.path("paths.cache_dir", "cache") / "run_history.json"
    from ..lib.jsonio import read_json_or

    history = read_json_or(history_path, {"runs": []})
    seen: list[str] = []
    current_id = str(current or "")
    for vid in reversed([
        str(r.get("video_id") or "") for r in history.get("runs", [])
    ]):
        if not vid or vid == current_id or vid in seen:
            continue
        seen.append(vid)
        if len(seen) >= limit:
            break
    seen.reverse()
    return seen


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
