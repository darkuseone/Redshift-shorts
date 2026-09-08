#!/usr/bin/env python3
"""Лёгкие индексы каталога и словаря интентов — чтобы агент не читал гигабайты.

Зачем. `templates/manifest.json` весит сотни килобайт,
`config/template_scenarios.json` — тоже, а
`src/lib/render/hyperframes/templates.py` перевалил за 700 КБ. Агенту, который
ищет один рендерер или проверяет, в какой категории живёт приём, читать их
целиком незачем: он тратит контекст и всё равно не удерживает подробности.

Индекс отвечает на три вопроса без открытия источника: какие есть категории и
сколько в них приёмов, какой у приёма рендерер и требования, какие интенты
ведут в эту категорию. Дальше — точечный `grep -n` и срез по строкам.

Запуск:
    python tools/gen_indexes.py            # переписать индексы
    python tools/gen_indexes.py --check    # только проверить совпадение

`--check` возвращает 1, если индекс разошёлся с источником: этим же кодом
пользуется тест, чтобы устаревший индекс не жил в репозитории незамеченным.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "templates" / "manifest.json"
SCENARIOS = ROOT / "config" / "template_scenarios.json"
MANIFEST_INDEX = ROOT / "templates" / "manifest.index.json"
SCENARIOS_INDEX = ROOT / "config" / "template_scenarios.index.json"


def build_manifest_index(manifest: dict) -> dict:
    """Категория → приёмы: id, рендерер, требования, уровень частоты."""
    by_category: dict[str, list[dict]] = {}
    for template in manifest.get("templates", []):
        row = {
            "id": template["id"],
            "renderer": template.get("renderer", ""),
            "needs": list(template.get("needs") or []),
            "frequency": template.get("frequency", ""),
            "status": template.get("status", "active"),
        }
        by_category.setdefault(template.get("category", "?"), []).append(row)
    for rows in by_category.values():
        rows.sort(key=lambda r: r["id"])
    return {
        "_note": "Индекс каталога. Источник — templates/manifest.json, "
                 "перегенерация — python tools/gen_indexes.py.",
        "counts": {cat: len(rows) for cat, rows in sorted(by_category.items())},
        "total": sum(len(rows) for rows in by_category.values()),
        "categories": dict(sorted(by_category.items())),
    }


def build_scenarios_index(scenarios: dict) -> dict:
    """Категория → интенты, которые в неё ведут, с весом и условиями."""
    by_category: dict[str, list[dict]] = {}
    for intent in scenarios.get("intents", []):
        row = {
            "id": intent["id"],
            "weight": intent.get("weight", 0),
            "variants": list(intent.get("variants") or []),
            "needs": list(intent.get("needs") or []),
            "signals_any": list(intent.get("signals_any") or []),
            "templates": len(intent.get("templates") or []),
        }
        for category in intent.get("categories") or ["?"]:
            by_category.setdefault(category, []).append(dict(row))
    for rows in by_category.values():
        rows.sort(key=lambda r: (-int(r["weight"]), r["id"]))
    return {
        "_note": "Индекс словаря интентов. Источник — "
                 "config/template_scenarios.json, перегенерация — "
                 "python tools/gen_indexes.py.",
        "specific_weight_min": scenarios.get("specific_weight_min"),
        "default_weight_min": scenarios.get("default_weight_min"),
        "unreachable_categories": list(scenarios.get("unreachable_categories") or []),
        "intents_total": len(scenarios.get("intents") or []),
        "categories": dict(sorted(by_category.items())),
    }


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def generate() -> dict[Path, str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    return {
        MANIFEST_INDEX: _dump(build_manifest_index(manifest)),
        SCENARIOS_INDEX: _dump(build_scenarios_index(scenarios)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="не писать, а проверить совпадение с источником")
    args = parser.parse_args()

    stale: list[str] = []
    for path, payload in generate().items():
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == payload:
            continue
        if args.check:
            stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(payload, encoding="utf-8")
            print(f"переписан {path.relative_to(ROOT)}")
    if stale:
        print("индексы разошлись с источником: " + ", ".join(stale), file=sys.stderr)
        print("перегенерация: python tools/gen_indexes.py", file=sys.stderr)
        return 1
    if args.check:
        print("индексы совпадают с источником")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
