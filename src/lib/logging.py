"""Структурное логирование с редактированием секретов.

§7.6: «Все ключи — GitHub Secrets, ни один не попадает в логи и артефакты».
Поэтому редактор секретов работает не на уровне «не логируй ключи», а на уровне
форматтера: любое значение известной секретной переменной окружения заменяется
на ``***`` в любом сообщении, куда бы оно ни попало.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable

_SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
_MIN_SECRET_LEN = 8

_redaction_pattern: re.Pattern[str] | None = None
_extra_secrets: set[str] = set()


def _collect_secrets() -> list[str]:
    out: list[str] = []
    for name, value in os.environ.items():
        if not value or len(value) < _MIN_SECRET_LEN:
            continue
        upper = name.upper()
        if any(hint in upper for hint in _SECRET_ENV_HINTS):
            out.append(value)
    out.extend(s for s in _extra_secrets if len(s) >= _MIN_SECRET_LEN)
    return out


def register_secret(value: str | None) -> None:
    """Добавить значение в список редактируемых (например, presigned URL)."""
    global _redaction_pattern
    if value and len(value) >= _MIN_SECRET_LEN:
        _extra_secrets.add(value)
        _redaction_pattern = None


def redact(text: str) -> str:
    global _redaction_pattern
    if _redaction_pattern is None:
        secrets = _collect_secrets()
        if secrets:
            secrets.sort(key=len, reverse=True)
            _redaction_pattern = re.compile("|".join(re.escape(s) for s in secrets))
        else:
            _redaction_pattern = re.compile(r"(?!x)x")  # никогда не совпадает
    return _redaction_pattern.sub("***", text)


class JsonFormatter(logging.Formatter):
    """Одна строка = один JSON-объект. Удобно грепать в артефактах Actions."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, ensure_ascii=False, default=str))


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{time.strftime('%H:%M:%S', time.gmtime(record.created))} " \
               f"{record.levelname:<7} {record.name:<22} {record.getMessage()}"
        fields = getattr(record, "extra_fields", {})
        if fields:
            base += "  " + " ".join(f"{k}={v}" for k, v in fields.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return redact(base)


class _StepAdapter(logging.LoggerAdapter):
    """Логгер шага пайплайна: подмешивает step/video_id в каждую запись."""

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        extra = dict(self.extra or {})
        extra.update(kwargs.pop("extra", {}) or {})
        fields = {k: v for k, v in extra.items() if v is not None}
        kwargs["extra"] = {"extra_fields": fields}
        return msg, kwargs


_configured = False


def setup_logging(
    level: str = "INFO",
    *,
    json_output: bool = True,
    log_file: str | Path | None = None,
) -> None:
    global _configured
    root = logging.getLogger("redshift")
    root.handlers.clear()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.propagate = False

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(JsonFormatter() if json_output else PlainFormatter())
    root.addHandler(stream)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
    _configured = True


def get_logger(name: str, **context: Any) -> logging.LoggerAdapter:
    if not _configured:
        setup_logging(json_output=False)
    return _StepAdapter(logging.getLogger(f"redshift.{name}"), context)


def log_lines(logger: logging.LoggerAdapter, level: int, lines: Iterable[str]) -> None:
    for line in lines:
        line = line.rstrip()
        if line:
            logger.log(level, line)
