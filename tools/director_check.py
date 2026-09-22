#!/usr/bin/env python3
"""Линт сценария с режиссёрским таймлайном — до пуша, без сети и без денег.

    python tools/director_check.py scripts/redshift_0052.json

Что проверяется: P0 целиком (хук ≤3 с, петля, длительность, схема), затем
секция ``director`` (docs/director/TIMELINE.md): шаблоны есть в каталоге,
якоря есть в тексте блоков, у футажа есть лицензия и источник, генерации
не больше 20 %, нет окон без движения дольше 4 с, приёмов достаточно.
Ниже печатается черновая раскладка окон по времени — по слогам, темп 1.2.

Код выхода 1 — есть ошибки; предупреждения не валят.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return 2
    from src.errors import RedshiftError
    from src.lib.config import load_config
    from src.lib.director import _estimate_windows, summarize, validate
    from src.p0_validate.validator import validate_script

    path = Path(args[0])
    script = json.loads(path.read_text(encoding="utf-8"))
    cfg = load_config(None, None, overrides=["providers.mode=mock"])
    status = 0
    try:
        validated = validate_script(json.loads(path.read_text(encoding="utf-8")), cfg)
        print(f"P0: ok · ~{validated['_validation']['estimated_duration_sec']} с")
        for w in validated["_validation"]["warnings"]:
            if w["code"] != "DIRECTOR_WARN":
                print(f"  ⚠ {w['code']}: {w['message']}")
    except RedshiftError as exc:
        print(f"P0: ОШИБКА {exc.code}: {exc.message}")
        status = 1

    issues = validate(script, ai_share_max=float(cfg.get("limits.ai_footage_share_max", 0.20)))
    report = summarize(issues)
    if not script.get("director"):
        print("director: секции нет — ролик соберёт эвристика P11 (так больше не делаем)")
        return status or 1
    print(f"director: ошибок {report['errors']}, предупреждений {report['warnings']}")
    for item in report["issues"]:
        mark = "✗" if item["level"] == "error" else "⚠"
        print(f"  {mark} {item['where']}: {item['message']}")
    if report["errors"]:
        status = 1

    footage = script["director"].get("footage") or {}
    print("\nраскладка (оценка по слогам, темп 1.2):")
    for start, end, shot in _estimate_windows(script, script["director"]):
        what = (f"footage:{shot['footage']}" if shot.get("footage")
                else f"fullscreen:{(shot.get('fullscreen') or {}).get('content')}" if shot.get("fullscreen")
                else "avatar" if shot.get("avatar") else "scene")
        ai = " [AI]" if shot.get("footage") and (footage.get(shot["footage"]) or {}).get("ai_generated") else ""
        extra = " ".join(str(shot.get(k) if not isinstance(shot.get(k), dict) else shot[k].get("template"))
                         for k in ("transition", "motion", "hero") if shot.get(k))
        print(f"  {start:5.1f}–{end:5.1f}  {shot['block']:<4} {what}{ai}  {extra}")
    for ovl in script["director"].get("overlays") or []:
        print(f"  overlay {ovl.get('block')}@{ovl.get('at', '')}: {ovl.get('template') or ovl.get('renderer')}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
