"""Учёт кредитов и бюджетный сторож (§7.6, §16 redshift-cost-guard).

Две функции:
1. ``estimate`` — смета ДО прогона; превышение лимита → BUDGET_EXCEEDED (§8.2).
2. ``CostLedger`` — факт ПОСЛЕ каждого внешнего вызова; при
   ``budget.hard_stop_on_exceed`` прогон останавливается, а не «тихо» доедает
   бюджет.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import BudgetExceeded
from .jsonio import write_json
from .logging import get_logger

_log = get_logger("cost")


@dataclass
class CostEntry:
    service: str
    operation: str
    units: float
    unit: str
    usd: float
    meta: dict[str, Any] = field(default_factory=dict)


class CostLedger:
    """Потокобезопасный журнал расходов прогона."""

    def __init__(self, *, max_usd: float | None = None, hard_stop: bool = True,
                 video_id: str = "") -> None:
        self.entries: list[CostEntry] = []
        self.max_usd = max_usd
        self.hard_stop = hard_stop
        self.video_id = video_id
        self._lock = threading.Lock()

    @property
    def total_usd(self) -> float:
        return round(sum(e.usd for e in self.entries), 6)

    def by_service(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for e in self.entries:
            out[e.service] = round(out.get(e.service, 0.0) + e.usd, 6)
        return out

    def add(self, service: str, operation: str, units: float, unit: str, usd: float,
            **meta: Any) -> CostEntry:
        entry = CostEntry(service, operation, float(units), unit, round(float(usd), 6), meta)
        with self._lock:
            self.entries.append(entry)
            total = self.total_usd
        _log.info("расход", extra={"service": service, "op": operation,
                                   "units": units, "unit": unit, "usd": entry.usd,
                                   "total_usd": total})
        self.check()
        return entry

    def check(self) -> None:
        if self.max_usd is None:
            return
        if self.total_usd > self.max_usd:
            msg = (f"бюджет превышен: {self.total_usd:.4f} USD > лимит {self.max_usd:.4f} USD")
            if self.hard_stop:
                raise BudgetExceeded(msg, total_usd=self.total_usd, limit_usd=self.max_usd,
                                     by_service=self.by_service())
            _log.error(msg, extra={"hard_stop": False})

    def remaining_usd(self) -> float | None:
        if self.max_usd is None:
            return None
        return round(self.max_usd - self.total_usd, 6)

    def to_dict(self, *, estimate: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "total_usd": self.total_usd,
            "limit_usd": self.max_usd,
            "within_budget": self.max_usd is None or self.total_usd <= self.max_usd,
            "by_service": self.by_service(),
            "estimate": estimate,
            "entries": [
                {"service": e.service, "operation": e.operation, "units": e.units,
                 "unit": e.unit, "usd": e.usd, **({"meta": e.meta} if e.meta else {})}
                for e in self.entries
            ],
        }

    def dump(self, path: str | Path, *, estimate: dict[str, Any] | None = None) -> Path:
        return write_json(path, self.to_dict(estimate=estimate))


def estimate_cost(script: dict[str, Any], cfg) -> dict[str, Any]:
    """Смета ДО прогона (§7.6: «учёт кредитов до и после прогона»).

    Считаем по худшему сценарию: озвучка всего текста с запасом длины,
    аватар — по верхней границе доли, vision — по потолку пула кандидатов.
    """
    price = cfg.get("budget.price")
    blocks = script.get("blocks", [])
    chars = sum(len(b.get("text", "")) for b in blocks)
    buffer_pct = float(cfg.get("elevenlabs.length_buffer_pct", 22)) / 100.0
    target = float(script.get("meta", {}).get("target_duration_sec", 50))

    tts_chars = chars * (1.0 + buffer_pct)
    tts_usd = (tts_chars / 1000.0) * float(price["elevenlabs_per_1k_chars"])

    avatar_share_max = float(cfg.get("limits.avatar_share")[1])
    avatar_sec = target * avatar_share_max
    avatar_usd = avatar_sec * float(price["heygen_per_second"])

    pool_max = int(cfg.get("stock.target_pool_size")[1])
    frames_per_item = len(cfg.get("stock.video_probe_frames", [0.1, 0.5, 0.9]))
    gemini_usd = pool_max * frames_per_item * float(price["gemini_per_image"])
    grok_usd = int(cfg.get("vision.arbiter_max_calls", 8)) * float(price["grok_per_image"])

    # P9: генерация закрывает не более четверти слотов — иначе ролик упирается
    # в потолок доли AI-футажа (§7.2.6).
    gen_images = max(1, int(len(blocks) * 0.5))
    magnific_usd = gen_images * float(price["magnific_per_image"])

    lines = {
        "elevenlabs": round(tts_usd, 4),
        "heygen": round(avatar_usd, 4),
        "gemini": round(gemini_usd, 4),
        "grok": round(grok_usd, 4),
        "magnific": round(magnific_usd, 4),
    }
    total = round(sum(lines.values()), 4)
    limit = cfg.get("budget.max_cost_per_video_usd", None)
    return {
        "total_usd": total,
        "limit_usd": limit,
        "within_budget": limit is None or total <= float(limit),
        "by_service": lines,
        "assumptions": {
            "tts_chars": round(tts_chars),
            "avatar_sec": round(avatar_sec, 2),
            "vision_items": pool_max,
            "grok_calls": int(cfg.get("vision.arbiter_max_calls", 8)),
            "generated_images": gen_images,
        },
    }


def guard_estimate(estimate: dict[str, Any], cfg) -> None:
    """§8.2 BUDGET_EXCEEDED — отклонить сценарий до трат."""
    limit = cfg.get("budget.max_cost_per_video_usd", None)
    if limit is None:
        return
    if estimate["total_usd"] > float(limit):
        raise BudgetExceeded(
            f"расчётная стоимость {estimate['total_usd']:.2f} USD превышает лимит {float(limit):.2f} USD",
            estimate=estimate,
        )
