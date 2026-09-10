#!/usr/bin/env python3
"""Параметры прогона build-video: GitHub Actions, не Cursor.

workflow_dispatch — поля формы. push заявки — ``config/ci_build_request.json``.
Печатает ``KEY=value`` для ``GITHUB_ENV``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUEST_PATH = ROOT / "config" / "ci_build_request.json"

DEFAULTS = {
    "BUILD_SCRIPT": "scripts/redshift_0042.json",
    "BUILD_PROVIDERS_MODE": "live",
    "BUILD_FROM_STEP": "",
    "BUILD_FORCE": "false",
    "BUILD_SKIP_VISION": "false",
    "BUILD_SKIP_GENERATE": "false",
    "BUILD_PUBLISH_RELEASE": "false",
    "BUILD_HEYGEN_SOURCE": "api",
}


def _as_bool_str(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value or "").strip().lower()
    if text in ("1", "true", "yes"):
        return "true"
    if text in ("0", "false", "no", ""):
        return "false"
    return text


def _load_file() -> dict:
    if not REQUEST_PATH.is_file():
        return {}
    data = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def resolve(*, event_name: str, environ: dict[str, str] | None = None) -> dict[str, str]:
    env = environ or os.environ
    file_req = _load_file()
    out = dict(DEFAULTS)

    def from_file(key: str, dest: str, *, boolean: bool = False) -> None:
        if key not in file_req or file_req[key] is None:
            return
        raw = file_req[key]
        out[dest] = _as_bool_str(raw) if boolean else str(raw).strip()

    from_file("script", "BUILD_SCRIPT")
    from_file("providers_mode", "BUILD_PROVIDERS_MODE")
    from_file("from_step", "BUILD_FROM_STEP")
    from_file("force", "BUILD_FORCE", boolean=True)
    from_file("skip_vision", "BUILD_SKIP_VISION", boolean=True)
    from_file("skip_generate", "BUILD_SKIP_GENERATE", boolean=True)
    from_file("publish_release", "BUILD_PUBLISH_RELEASE", boolean=True)
    from_file("heygen_source", "BUILD_HEYGEN_SOURCE")

    if event_name == "workflow_dispatch":
        mapping = {
            "IN_SCRIPT": "BUILD_SCRIPT",
            "IN_PROVIDERS_MODE": "BUILD_PROVIDERS_MODE",
            "IN_FROM_STEP": "BUILD_FROM_STEP",
            "IN_FORCE": "BUILD_FORCE",
            "IN_SKIP_VISION": "BUILD_SKIP_VISION",
            "IN_SKIP_GENERATE": "BUILD_SKIP_GENERATE",
            "IN_PUBLISH_RELEASE": "BUILD_PUBLISH_RELEASE",
            "IN_HEYGEN_SOURCE": "BUILD_HEYGEN_SOURCE",
        }
        bool_keys = {
            "BUILD_FORCE", "BUILD_SKIP_VISION", "BUILD_SKIP_GENERATE",
            "BUILD_PUBLISH_RELEASE",
        }
        for src, dest in mapping.items():
            if src not in env:
                continue
            raw = env.get(src)
            if raw is None:
                continue
            # Пустой from_step/heygen_source — законный ввод формы, не «нет поля».
            if dest in bool_keys:
                out[dest] = _as_bool_str(raw)
            else:
                out[dest] = str(raw).strip()

    return out


def main() -> int:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    resolved = resolve(event_name=event, environ=dict(os.environ))
    for key, value in resolved.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
