"""Заявка CI указывает на существующий сценарий; резолвер читает файл и форму."""

from __future__ import annotations

import json
from pathlib import Path

from tools.resolve_ci_build_request import resolve


ROOT = Path(__file__).resolve().parents[1]


def test_ci_build_request_points_at_an_existing_script():
    req = json.loads((ROOT / "config" / "ci_build_request.json").read_text(encoding="utf-8"))
    script = ROOT / str(req["script"])
    assert script.is_file(), req["script"]
    assert req["providers_mode"] in {"live", "auto", "mock"}
    assert req["heygen_source"] in {"", "api", "auto", "prepared"}
    assert req["publish_release"] is False


def test_push_event_reads_the_request_file():
    got = resolve(event_name="push", environ={})
    req = json.loads((ROOT / "config" / "ci_build_request.json").read_text(encoding="utf-8"))
    assert got["BUILD_SCRIPT"] == req["script"]
    assert got["BUILD_PROVIDERS_MODE"] == req["providers_mode"]
    assert got["BUILD_HEYGEN_SOURCE"] == req["heygen_source"]
    assert got["BUILD_PUBLISH_RELEASE"] == "false"


def test_workflow_dispatch_inputs_win_including_empty_from_step():
    got = resolve(event_name="workflow_dispatch", environ={
        "IN_SCRIPT": "scripts/redshift_0042.json",
        "IN_PROVIDERS_MODE": "auto",
        "IN_FROM_STEP": "",
        "IN_FORCE": "true",
        "IN_SKIP_VISION": "false",
        "IN_SKIP_GENERATE": "false",
        "IN_PUBLISH_RELEASE": "true",
        "IN_HEYGEN_SOURCE": "prepared",
    })
    assert got["BUILD_SCRIPT"] == "scripts/redshift_0042.json"
    assert got["BUILD_PROVIDERS_MODE"] == "auto"
    assert got["BUILD_FROM_STEP"] == ""
    assert got["BUILD_FORCE"] == "true"
    assert got["BUILD_PUBLISH_RELEASE"] == "true"
    assert got["BUILD_HEYGEN_SOURCE"] == "prepared"
