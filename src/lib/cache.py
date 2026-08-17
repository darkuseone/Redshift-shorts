"""Кэш шагов пайплайна по хешу входа (§7.1, §7.6 «идемпотентность»).

Повторный запуск с тем же входом не тратит кредиты повторно: шаг сверяет
fingerprint (хеш входных данных + версия шага + релевантная часть конфига) с
записанным в ``.step_state.json`` и, если совпало и выходные файлы на месте,
возвращает готовый результат.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterable

from .jsonio import read_json_or, stable_json, write_json
from .logging import get_logger

_log = get_logger("cache")
STATE_FILE = ".step_state.json"


def hash_obj(obj: Any) -> str:
    return hashlib.sha256(stable_json(obj).encode("utf-8")).hexdigest()[:32]


def hash_file(path: str | Path, *, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()[:32]


def hash_files(paths: Iterable[str | Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(str(x) for x in paths):
        h.update(p.encode("utf-8"))
        try:
            h.update(hash_file(p).encode("ascii"))
        except OSError:
            h.update(b"<missing>")
    return h.hexdigest()[:32]


class StepCache:
    """Состояние шагов внутри рабочего каталога прогона."""

    def __init__(self, work_dir: str | Path, *, enabled: bool = True) -> None:
        self.work_dir = Path(work_dir)
        self.enabled = enabled
        self.state_path = self.work_dir / STATE_FILE

    def _load(self) -> dict[str, Any]:
        return read_json_or(self.state_path, {})

    def _save(self, state: dict[str, Any]) -> None:
        write_json(self.state_path, state)

    def fingerprint_of(self, step: str) -> str | None:
        return (self._load().get(step) or {}).get("fingerprint")

    def is_fresh(self, step: str, fingerprint: str, outputs: Iterable[str | Path]) -> bool:
        if not self.enabled:
            return False
        entry = self._load().get(step)
        if not entry or entry.get("fingerprint") != fingerprint:
            return False
        for out in outputs:
            p = self.work_dir / out if not os.path.isabs(str(out)) else Path(out)
            if not p.exists():
                _log.info("кэш шага устарел: нет выходного файла",
                          extra={"step": step, "missing": str(p)})
                return False
        return True

    def record(self, step: str, fingerprint: str, *, outputs: Iterable[str | Path] = (),
               meta: dict[str, Any] | None = None) -> None:
        state = self._load()
        state[step] = {
            "fingerprint": fingerprint,
            "outputs": [str(o) for o in outputs],
            "meta": meta or {},
        }
        self._save(state)

    def invalidate(self, step: str | None = None) -> None:
        if step is None:
            self._save({})
            return
        state = self._load()
        state.pop(step, None)
        self._save(state)

    def completed_steps(self) -> list[str]:
        return sorted(self._load().keys())
