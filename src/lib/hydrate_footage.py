"""Copy indexed repo footage into storage when Actions cache lacks the file."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from .logging import get_logger

_log = get_logger("hydrate_footage")


def hydrate_repo_footage(ctx: Any, index: Any) -> int:
    """Put missing index files into storage from assets/footage on disk.

    Magnific plates live in git under assets/footage/magnific/, but P7/P8
    only see storage (.redshift_cache/footage). Without this, prefer leftover
    skips weather/pipes/blood and QC-SEMANTIC fills water on «Погода».
    """
    storage = getattr(ctx, "storage", None)
    if storage is None or index is None:
        return 0
    repo_root = Path(getattr(getattr(ctx, "cfg", None), "repo_root", None) or ".")
    assets = repo_root / "assets" / "footage"
    n = 0
    items = list(getattr(index, "items", None) or [])
    for record in items:
        key = str(getattr(record, "file", "") or "")
        if not key:
            continue
        try:
            if storage.exists(key):
                continue
        except Exception:  # noqa: BLE001
            continue
        name = Path(key).name
        candidates = [
            assets / key,
            assets / "magnific" / name,
            assets / name,
            repo_root / key,
        ]
        src = next((p for p in candidates if p.is_file()), None)
        if src is None:
            continue
        try:
            storage.put(key, src)
            n += 1
        except Exception as exc:  # noqa: BLE001
            _log.warning("hydrate failed %s: %s", key, exc)
    if n:
        _log.info("hydrated %s footage file(s) from assets into storage", n)
    return n
