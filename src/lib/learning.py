"""Самообучение: запись выбора A/B и обновление правил (§4.5, §7.8).

§4.5 требует записывать выбор в формате «в ситуации X выбран вариант Y», а не
просто «понравилась B». Ситуация — это набор монтажных решений, которыми версии
различались: именно они и должны смещать дефолты, а не сам ярлык версии.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from ..errors import RedshiftError
from .jsonio import read_json_or, write_json
from .logging import get_logger

_log = get_logger("learning")


def _differences(plan_a: dict[str, Any], plan_b: dict[str, Any]) -> list[dict[str, Any]]:
    """Чем именно версии различались — по позициям, а не по названиям целиком."""
    out: list[dict[str, Any]] = []
    shots_a = {s["index"]: s for s in plan_a.get("shots", [])}
    shots_b = {s["index"]: s for s in plan_b.get("shots", [])}
    for index in sorted(set(shots_a) & set(shots_b)):
        a, b = shots_a[index], shots_b[index]
        if (a.get("kenburns") or {}).get("template") != (b.get("kenburns") or {}).get("template"):
            out.append({"situation": f"kenburns@{a['role']}",
                        "A": (a.get("kenburns") or {}).get("template"),
                        "B": (b.get("kenburns") or {}).get("template")})
        if (a.get("transition") or {}).get("template") != (b.get("transition") or {}).get("template"):
            out.append({"situation": f"transition@{a['role']}",
                        "A": (a.get("transition") or {}).get("template"),
                        "B": (b.get("transition") or {}).get("template")})
        if a.get("template") != b.get("template") and a.get("kind") == "fullscreen_text":
            out.append({"situation": f"fullscreen_text@{a['role']}",
                        "A": a.get("template"), "B": b.get("template")})
        if a.get("asset_id") != b.get("asset_id"):
            out.append({"situation": f"asset_order@{a['block_id']}",
                        "A": a.get("asset_id"), "B": b.get("asset_id")})

    overlays_a = {(o["type"], round(float(o["start"]), 1)): o.get("template")
                  for o in plan_a.get("overlays", [])}
    overlays_b = {(o["type"], round(float(o["start"]), 1)): o.get("template")
                  for o in plan_b.get("overlays", [])}
    for key in sorted(set(overlays_a) | set(overlays_b)):
        if overlays_a.get(key) != overlays_b.get(key):
            out.append({"situation": f"overlay@{key[0]}",
                        "A": overlays_a.get(key), "B": overlays_b.get(key)})
    return out


def record_choice(cfg, *, video_id: str, choice: str, note: str = "",
                  output_dir: Path | None = None) -> dict[str, Any]:
    """Записать выбор заказчика и сместить дефолты (§4.5, §7.8)."""
    choice = choice.upper()
    if choice not in ("A", "B"):
        raise RedshiftError("выбор должен быть A или B", code="INVALID_CHOICE")

    out_dir = output_dir or (cfg.path("paths.output_dir", "output") / video_id)
    plan_a = read_json_or(out_dir / "edit_plan_A.json", None)
    plan_b = read_json_or(out_dir / "edit_plan_B.json", None)
    if plan_a is None or plan_b is None:
        work_dir = cfg.path("paths.work_dir", "work") / video_id
        plan_a = plan_a or read_json_or(work_dir / "edit_plan_A.json", None)
        plan_b = plan_b or read_json_or(work_dir / "edit_plan_B.json", None)
    if plan_a is None or plan_b is None:
        raise RedshiftError(f"не найдены edit-планы прогона {video_id}",
                            code="EDIT_PLANS_MISSING", video_id=video_id)

    prefs_path = cfg.repo_root / "config" / "editing_preferences.json"
    prefs = read_json_or(prefs_path, {"version": 1, "runs": [], "situation_weights": {},
                                      "defaults": {}})

    differences = _differences(plan_a, plan_b)
    weights: dict[str, Any] = prefs.setdefault("situation_weights", {})
    for diff in differences:
        situation = diff["situation"]
        winner = diff.get(choice)
        loser = diff.get("B" if choice == "A" else "A")
        if not winner:
            continue
        bucket = weights.setdefault(situation, {})
        bucket[str(winner)] = round(float(bucket.get(str(winner), 0.0)) + 1.0, 3)
        if loser:
            bucket[str(loser)] = round(float(bucket.get(str(loser), 0.0)) - 0.5, 3)

    prefs["runs"] = [r for r in prefs.get("runs", []) if r.get("video_id") != video_id]
    prefs["runs"].append({
        "video_id": video_id,
        "choice": choice,
        "note": note,
        "recorded_at": _dt.date.today().isoformat(),
        "differences": differences,
    })
    prefs["runs"] = prefs["runs"][-100:]
    prefs["updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    # Дефолты смещаются к тому, что выбирают чаще (§4.5).
    defaults: dict[str, Any] = prefs.setdefault("defaults", {})
    for situation, bucket in weights.items():
        if not bucket:
            continue
        best = max(bucket.items(), key=lambda kv: kv[1])
        if best[1] >= 2.0:
            defaults[situation] = best[0]

    write_json(prefs_path, prefs)
    _log.info("предпочтение записано", extra={
        "video_id": video_id, "choice": choice, "differences": len(differences),
        "defaults": len(defaults),
    })
    return {"video_id": video_id, "choice": choice,
            "differences_recorded": len(differences),
            "situations": sorted({d["situation"] for d in differences}),
            "defaults": defaults, "path": str(prefs_path)}
