"""Запуск CLI HyperFrames.

Бинарь ищется в PATH, затем в node_modules проекта, затем через ``npx``. В
GitHub Actions ставится глобально одной строкой, локально удобнее npx — обе
дороги ведут к одному исполняемому файлу.

Перед рендером обязательно гоняется ``lint``: у композиции есть ошибки, которые
иначе всплывают не сообщением, а сорокапятисекундным ожиданием таймлайна и
пустым кадром.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from ....errors import RenderError
from ...logging import get_logger

_log = get_logger("hyperframes.cli")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@lru_cache(maxsize=1)
def cli_command() -> list[str]:
    env = os.environ.get("HYPERFRAMES_BIN")
    if env and Path(env).exists():
        return [env]
    found = shutil.which("hyperframes")
    if found:
        return [found]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", "hyperframes@latest"]
    raise RenderError(
        "не найден CLI hyperframes",
        hint="npm install -g hyperframes  либо задайте HYPERFRAMES_BIN")


def _run(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    cmd = cli_command() + args
    _log.debug("hyperframes", extra={"args": " ".join(args)})
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          timeout=timeout)


def lint(project: Path, *, timeout: int = 300) -> dict[str, int]:
    """Проверить композицию. Ошибки — стоп, предупреждения — в лог."""
    proc = _run(["lint"], cwd=project, timeout=timeout)
    text = _ANSI.sub("", proc.stdout + proc.stderr)
    errors = [l.strip() for l in text.splitlines() if l.strip().startswith("✗")]
    warnings = [l.strip() for l in text.splitlines() if l.strip().startswith("⚠")]
    if errors:
        raise RenderError(
            "композиция HyperFrames не прошла lint: " + "; ".join(errors[:4]),
            code="HYPERFRAMES_LINT_FAILED")
    if warnings:
        _log.info("lint: предупреждения", extra={"count": len(warnings),
                                                 "first": warnings[0][:160]})
    return {"errors": len(errors), "warnings": len(warnings)}


def render(project: Path, out_path: Path, *, fps: int, crf: int | None = None,
           quality: str = "high", timeout: int = 5400) -> dict[str, Any]:
    args = ["render", "-o", str(out_path.resolve()), "--fps", str(fps),
            "--quality", quality]
    if crf is not None:
        args += ["--crf", str(crf)]
    proc = _run(args, cwd=project, timeout=timeout)
    text = _ANSI.sub("", proc.stdout + proc.stderr)
    if proc.returncode != 0 or not out_path.exists():
        tail = "\n".join(text.strip().splitlines()[-12:])
        raise RenderError(f"рендер HyperFrames упал (код {proc.returncode}):\n{tail}",
                          code="HYPERFRAMES_RENDER_FAILED")

    frames = 0
    for line in text.splitlines():
        if '"totalFrames"' in line:
            try:
                frames = max(frames, int(json.loads(line[line.index("{"):])
                                         .get("totalFrames", 0)))
            except (ValueError, json.JSONDecodeError):
                continue
    return {"frames": frames, "log_tail": text.strip().splitlines()[-3:]}
