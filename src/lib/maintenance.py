"""Обслуживание: LRU-очистка кэша футажей и отчёты (§14.4, R-11, workflow maintenance)."""

from __future__ import annotations

from typing import Any

from .jsonio import read_json_or, write_json
from .logging import get_logger
from .manifest import FootageIndex, library_status
from .storage import build_storage, evict_lru

_log = get_logger("maintenance")


def run_maintenance(cfg, *, dry_run: bool = True) -> dict[str, Any]:
    storage = build_storage(cfg)
    index = FootageIndex.load(cfg)
    max_bytes = int(cfg.get("storage.max_bytes", 20 * 1024 ** 3))

    objects = list(storage.list())
    total_bytes = sum(o.size_bytes for o in objects)

    # Материал из последних 5 роликов не вытесняем: он ещё может понадобиться
    # для пересборки и участвует в проверке пересечения (QC-6).
    history = read_json_or(cfg.path("paths.cache_dir", "cache") / "run_history.json",
                           {"runs": []})
    recent_videos = {r.get("video_id") for r in history.get("runs", [])[-5:]}
    protected = {item.file for item in index.items
                 if item.file and set(item.used_in) & recent_videos}

    removed: list[str] = []
    if total_bytes > max_bytes and not dry_run:
        removed = evict_lru(storage, max_bytes=max_bytes, protected=protected)
        if removed:
            removed_set = set(removed)
            index.items = [item for item in index.items if item.file not in removed_set]
            index.save()

    orphans = [item.id for item in index.items
               if item.file and not storage.exists(item.file)]
    if orphans and not dry_run:
        orphan_set = set(orphans)
        index.items = [item for item in index.items if item.id not in orphan_set]
        index.save()

    report = {
        "dry_run": dry_run,
        "storage": {
            "backend": cfg.get("storage.backend", "local"),
            "objects": len(objects),
            "total_bytes": total_bytes,
            "total_gb": round(total_bytes / 1024 ** 3, 3),
            "max_bytes": max_bytes,
            "over_limit": total_bytes > max_bytes,
            "protected_count": len(protected),
        },
        "evicted": removed,
        "evicted_count": len(removed),
        "orphans_removed": orphans,
        "index": index.status(),
        "libraries": library_status(cfg)["libraries"],
        "runs_tracked": len(history.get("runs", [])),
    }
    _log.info("обслуживание завершено", extra={
        "objects": len(objects), "evicted": len(removed), "orphans": len(orphans),
        "dry_run": dry_run,
    })
    return report
