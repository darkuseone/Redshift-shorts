#!/usr/bin/env python3
"""Параметры живой сборки: workflow_dispatch ИЛИ config/ci_build_request.json.

Cursor не умеет workflow_dispatch токеном агента — заявка в git единственный
триггер станка. ``--force-paid`` из заявки игнорируется всегда.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REQUEST_PATH = REPO / "config" / "ci_build_request.json"

DEFAULTS = {
    "script": "scripts/redshift_0042.json",
    "providers_mode": "auto",
    "from_step": "",
    "heygen_source": "prepared",
    "skip_generate": "false",
    "skip_vision": "false",
    "force": "false",
    "requested_by": "",
    "note": "",
    "tts_pace": "",
}


def _flag(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value or "").strip().lower()
    if text in ("1", "true", "yes"):
        return "true"
    return "false"


def load_request(*, event_name: str, environ: dict[str, str] | None = None) -> dict[str, str]:
    env = environ or os.environ
    out = dict(DEFAULTS)
    if event_name == "workflow_dispatch":
        out["script"] = env.get("INPUT_SCRIPT") or out["script"]
        out["providers_mode"] = env.get("INPUT_MODE") or out["providers_mode"]
        out["from_step"] = env.get("INPUT_FROM") or ""
        out["heygen_source"] = env.get("INPUT_HEYGEN") or "prepared"
        out["skip_generate"] = _flag(env.get("INPUT_SKIP_GENERATE"))
        out["skip_vision"] = _flag(env.get("INPUT_SKIP_VISION"))
        out["force"] = _flag(env.get("INPUT_FORCE"))
        out["requested_by"] = "workflow_dispatch"
        out["tts_pace"] = ""
        return out

    if not REQUEST_PATH.is_file():
        raise SystemExit(f"нет заявки {REQUEST_PATH}")
    data = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("ci_build_request.json должен быть объектом")
    out["script"] = str(data.get("script") or out["script"])
    out["providers_mode"] = str(data.get("providers_mode") or "auto")
    from_step = data.get("from_step")
    out["from_step"] = "" if from_step is None else str(from_step).strip()
    out["heygen_source"] = str(data.get("heygen_source") or "prepared").lower()
    # TZ-0050+: allow live Avatar V via Actions secrets (`api`). Do not coerce.
    if out["heygen_source"] in ("live", "avatar_v"):
        out["heygen_source"] = "api"
    out["skip_generate"] = _flag(data.get("skip_generate", False))
    # Optional TTS pace override for a single build request.
    pace = data.get("tts_pace")
    out["tts_pace"] = "" if pace in (None, "") else str(pace)
    out["skip_vision"] = _flag(data.get("skip_vision", False))
    out["force"] = "false"
    # --force-paid из заявки Cursor никогда не проходит.
    out["requested_by"] = str(data.get("requested_by") or "cursor")
    out["note"] = str(data.get("note") or "")
    return out


def emit(values: dict[str, str], sink) -> None:
    for key, value in values.items():
        text = str(value).replace("\n", " ").replace("\r", "")
        sink.write(f"{key}={text}\n")


def main(argv: list[str] | None = None) -> int:
    event = (os.environ.get("EVENT_NAME") or "push").strip()
    values = load_request(event_name=event)
    github_out = os.environ.get("GITHUB_OUTPUT")
    if github_out:
        with open(github_out, "a", encoding="utf-8") as handle:
            emit(values, handle)
    emit(values, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
