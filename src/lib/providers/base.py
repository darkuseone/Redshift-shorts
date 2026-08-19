"""Базовые типы провайдеров и разрешение режима live/mock."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from ...errors import MissingCredentials
from ..logging import get_logger

_log = get_logger("providers")


class ProviderMode(str, enum.Enum):
    LIVE = "live"
    MOCK = "mock"
    AUTO = "auto"


def resolve_mode(cfg, *, api_key: str | None, service: str) -> ProviderMode:
    """Какой режим использовать для конкретного сервиса."""
    mode = ProviderMode(str(cfg.get("providers.mode", "auto")).lower())
    if mode is ProviderMode.LIVE:
        if not api_key:
            raise MissingCredentials(
                f"providers.mode=live, но ключ для {service} не задан",
                service=service,
            )
        return ProviderMode.LIVE
    if mode is ProviderMode.MOCK:
        return ProviderMode.MOCK
    if api_key:
        return ProviderMode.LIVE
    _log.warning(
        "нет ключа — сервис работает в mock-режиме; материал будет помечен как synthetic-mock",
        extra={"service": service},
    )
    return ProviderMode.MOCK


@dataclass
class Provider:
    """Общая часть провайдера: конфиг, журнал расходов, режим."""

    cfg: Any
    costs: Any = None
    mode: ProviderMode = ProviderMode.MOCK
    name: str = "provider"
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_mock(self) -> bool:
        return self.mode is ProviderMode.MOCK

    def charge(self, operation: str, units: float, unit: str, usd: float, **extra: Any) -> None:
        """Списать стоимость. В mock-режиме расход нулевой, но запись остаётся."""
        if self.costs is None:
            return
        self.costs.add(self.name, operation, units, unit,
                       0.0 if self.is_mock else usd, mock=self.is_mock, **extra)

    def _timeout(self) -> int:
        return int(self.cfg.get("providers.request_timeout_sec", 60))

    def _retry_kwargs(self, what: str) -> dict[str, Any]:
        return {
            "attempts": int(self.cfg.get("providers.retries", 3)),
            "base_delay": float(self.cfg.get("providers.backoff_base_sec", 2.0)),
            "what": what,
        }
