"""Атомарный JSON I/O.

Пайплайн переживает падения (§7.1), поэтому запись всегда через временный файл
с последующим os.replace — недописанный артефакт шага никогда не остаётся на
диске и не путает resume.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_json_or(path: str | Path, default: Any) -> Any:
    try:
        return read_json(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: str | Path, data: Any, *, indent: int = 2) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=indent, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def write_text(path: str | Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path


def stable_json(data: Any) -> str:
    """Каноническое представление для хеширования входа шага."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
