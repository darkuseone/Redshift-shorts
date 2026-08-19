"""Загрузка и доступ к конфигурации (config.yaml, brandbook.json).

Один объект :class:`Config` на прогон. Секреты не хранятся в конфиге — только
имена переменных окружения; сами значения достаются через ``Config.secret()``
и сразу регистрируются в редакторе логов.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..errors import MissingCredentials
from .jsonio import read_json
from .logging import register_secret

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "config.yaml"
DEFAULT_BRANDBOOK = REPO_ROOT / "config" / "brandbook.json"

_MISSING = object()


def deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивный merge: override побеждает, словари сливаются, списки заменяются."""
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _coerce(text: str) -> Any:
    lowered = text.strip().lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "none", ""):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


@dataclass
class Config:
    """Конфиг прогона. Доступ по dot-пути: ``cfg.get("limits.duration_sec")``."""

    data: dict[str, Any]
    brandbook: dict[str, Any]
    repo_root: Path = REPO_ROOT
    source_path: Path | None = None
    warnings: list[str] = field(default_factory=list)

    # --- доступ ---------------------------------------------------------
    def get(self, dotted: str, default: Any = _MISSING) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                if default is _MISSING:
                    raise KeyError(f"config: нет ключа {dotted!r}")
                return default
        return node

    def brand(self, dotted: str, default: Any = _MISSING) -> Any:
        node: Any = self.brandbook
        for part in dotted.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                if default is _MISSING:
                    raise KeyError(f"brandbook: нет ключа {dotted!r}")
                return default
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    # --- секреты --------------------------------------------------------
    def secret(self, env_name: str | None, *, required: bool = False, purpose: str = "") -> str | None:
        """Значение секрета из окружения. Регистрируется для редактирования в логах."""
        if not env_name:
            if required:
                raise MissingCredentials(f"не задано имя переменной окружения для {purpose or 'сервиса'}")
            return None
        value = os.environ.get(env_name) or None
        if value:
            register_secret(value)
        elif required:
            raise MissingCredentials(
                f"нет секрета {env_name} (нужен для {purpose or env_name})", env=env_name
            )
        return value

    def secret_for(self, dotted_env_key: str, *, required: bool = False, purpose: str = "") -> str | None:
        """Секрет по ключу конфига, значение которого — имя переменной окружения."""
        env_name = self.get(dotted_env_key, None)
        return self.secret(env_name, required=required, purpose=purpose or dotted_env_key)

    # --- пути -----------------------------------------------------------
    def path(self, dotted: str, default: str | None = None) -> Path:
        raw = self.get(dotted, default)
        p = Path(raw)
        return p if p.is_absolute() else (self.repo_root / p)

    @property
    def fps(self) -> int:
        return int(self.get("project.fps"))

    @property
    def resolution(self) -> tuple[int, int]:
        w, h = self.get("project.resolution")
        return int(w), int(h)

    def color(self, name: str) -> str:
        return str(self.brand(f"colors.{name}"))

    def copy(self) -> "Config":
        return Config(
            data=copy.deepcopy(self.data),
            brandbook=copy.deepcopy(self.brandbook),
            repo_root=self.repo_root,
            source_path=self.source_path,
            warnings=list(self.warnings),
        )

    def redacted(self) -> dict[str, Any]:
        """Копия конфига для записи в артефакты (в нём и так нет значений секретов)."""
        return copy.deepcopy(self.data)


def apply_env_overrides(data: dict[str, Any], prefix: str = "REDSHIFT_CFG_") -> list[str]:
    """REDSHIFT_CFG_limits__max_shot_sec=6 → data['limits']['max_shot_sec']=6."""
    applied: list[str] = []
    for key, raw in os.environ.items():
        if not key.startswith(prefix):
            continue
        dotted = key[len(prefix):].lower().replace("__", ".")
        parts = dotted.split(".")
        node = data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = _coerce(raw)
        applied.append(dotted)
    return applied


def load_config(
    config_path: str | Path | None = None,
    brandbook_path: str | Path | None = None,
    *,
    overrides: Iterable[str] = (),
) -> Config:
    """Собрать конфиг: файл → env-оверрайды → CLI-оверрайды (``a.b=value``)."""
    cfg_path = Path(config_path) if config_path else DEFAULT_CONFIG
    with open(cfg_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    bb_path = Path(brandbook_path) if brandbook_path else DEFAULT_BRANDBOOK
    brandbook = read_json(bb_path)

    warnings: list[str] = []
    for dotted in apply_env_overrides(data):
        warnings.append(f"config override из окружения: {dotted}")

    for item in overrides:
        if "=" not in item:
            raise ValueError(f"оверрайд должен быть вида key.path=value, получено {item!r}")
        dotted, raw = item.split("=", 1)
        parts = dotted.strip().split(".")
        node = data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = _coerce(raw)
        warnings.append(f"config override из CLI: {dotted.strip()}")

    return Config(data=data, brandbook=brandbook, source_path=cfg_path, warnings=warnings)
