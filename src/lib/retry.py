"""Ретраи с экспоненциальным бэкоффом.

§10.5.3: все внешние вызовы — 3 попытки, экспоненциальный бэкофф, таймауты.
§10.5.4: ошибка внешнего API логируется с кодом, а не приводит к молчаливой
деградации, поэтому исчерпание попыток всегда поднимает ProviderError.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable, TypeVar

from ..errors import ProviderError
from .logging import get_logger

T = TypeVar("T")
_log = get_logger("retry")

RETRYABLE_STATUS = (408, 425, 429, 500, 502, 503, 504)


def call_with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    what: str = "external call",
    retry_on: Iterable[type[BaseException]] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    retry_on = tuple(retry_on)
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:  # noqa: PERF203 — ретрай по смыслу
            last = exc
            if attempt >= attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            _log.warning(
                "попытка не удалась, повтор",
                extra={"what": what, "attempt": attempt, "of": attempts,
                       "delay_sec": delay, "error": type(exc).__name__},
            )
            sleep(delay)
    raise ProviderError(
        f"{what}: исчерпаны {attempts} попытки",
        cause=type(last).__name__ if last else None,
        detail=str(last)[:500] if last else None,
    ) from last
