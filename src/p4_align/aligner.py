"""P4 — Word-level выравнивание.

Заглушка Фазы 0: контракт шага объявлен, реализация приходит в своей фазе
(§17). Падает с внятным кодом, а не молча пропускает работу.
"""

from __future__ import annotations

from typing import Any

from ..errors import RedshiftError


def run_step(ctx) -> dict[str, Any]:
    raise RedshiftError(
        "шаг P4 (Word-level выравнивание) ещё не реализован",
        code="STEP_NOT_IMPLEMENTED", step="P4",
    )
