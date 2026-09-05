"""Ретраи с экспоненциальным бэкоффом.

§10.5.3: все внешние вызовы — 3 попытки, экспоненциальный бэкофф, таймауты.
§10.5.4: ошибка внешнего API логируется с кодом, а не приводит к молчаливой
деградации, поэтому исчерпание попыток всегда поднимает ProviderError.

503 / UNAVAILABLE / high demand: отдельный более длинный бэкофф
(по умолчанию 5/10/20…) и больше попыток — пики нагрузки у Gemini обычно
короткие, 2–4 с между тремя попытками не хватает.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable, TypeVar

from ..errors import ProviderError
from .logging import get_logger

T = TypeVar("T")
_log = get_logger("retry")

RETRYABLE_STATUS = (408, 425, 429, 500, 502, 503, 504)
CAPACITY_STATUS = (429, 503)
_CAPACITY_MARKERS = (
    "unavailable",
    "high demand",
    "resource_exhausted",
    "try again later",
    "resource exhausted",
)


def is_capacity_error(exc: BaseException) -> bool:
    """503/UNAVAILABLE/high demand (и схожий rate-limit 429)."""
    details = getattr(exc, "details", None)
    if not isinstance(details, dict):
        details = {}
    status = details.get("status")
    try:
        if status is not None and int(status) in CAPACITY_STATUS:
            return True
    except (TypeError, ValueError):
        pass
    body = str(details.get("body", "")).lower()
    text = f"{exc} {body}".lower()
    if any(marker in text for marker in _CAPACITY_MARKERS):
        return True
    # Явный код в теле ответа Gemini JSON.
    return '"code": 503' in text or " returned 503" in text or "вернул 503" in text


def call_with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    capacity_attempts: int | None = None,
    capacity_base_delay: float | None = None,
    what: str = "external call",
    retry_on: Iterable[type[BaseException]] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    retry_on = tuple(retry_on)
    last: BaseException | None = None
    cap_attempts = capacity_attempts if capacity_attempts is not None else attempts
    cap_base = capacity_base_delay if capacity_base_delay is not None else base_delay
    max_rounds = max(attempts, cap_attempts)

    for attempt in range(1, max_rounds + 1):
        try:
            return fn()
        except retry_on as exc:  # noqa: PERF203 — ретрай по смыслу
            last = exc
            capacity = is_capacity_error(exc)
            limit = cap_attempts if capacity else attempts
            if attempt >= limit:
                break
            delay_base = cap_base if capacity else base_delay
            delay = delay_base * (2 ** (attempt - 1))
            _log.warning(
                "попытка не удалась, повтор",
                extra={"what": what, "attempt": attempt, "of": limit,
                       "delay_sec": delay, "capacity": capacity,
                       "error": type(exc).__name__},
            )
            sleep(delay)
    used = cap_attempts if last is not None and is_capacity_error(last) else attempts
    raise ProviderError(
        f"{what}: исчерпаны {used} попытки",
        cause=type(last).__name__ if last else None,
        detail=str(last)[:500] if last else None,
    ) from last
