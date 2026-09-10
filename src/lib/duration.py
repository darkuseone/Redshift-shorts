"""Коридор длительности ролика.

Заказчик: интересно смотреть, желательно 35–75 сек, редко до 90.
Код не режет молча 80-секундный ролик до 70 — жёсткий потолок отдельный.
"""

from __future__ import annotations

from typing import Any


def duration_limits(cfg: Any) -> tuple[float, float, float]:
    """``(lo, preferred_hi, hard_hi)``.

    ``limits.duration_sec`` — желаемый коридор (по умолчанию 35–75).
    ``limits.duration_sec_hard`` — редкий максимум (90). Ниже 35 и выше hard
    — ошибка выдачи, не предупреждение.
    """
    pair = cfg.get("limits.duration_sec", [35, 75]) or [35, 75]
    lo = float(pair[0])
    preferred_hi = float(pair[1] if len(pair) > 1 else 75)
    hard_hi = float(cfg.get("limits.duration_sec_hard", 90))
    if hard_hi < preferred_hi:
        hard_hi = preferred_hi
    return lo, preferred_hi, hard_hi
