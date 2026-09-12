"""Заявка на станок: push JSON, не workflow_dispatch токеном агента."""

from __future__ import annotations

import json

from tools.ci_build_request import load_request


def test_dispatch_reads_inputs():
    env = {
        "INPUT_SCRIPT": "scripts/redshift_0048.json",
        "INPUT_MODE": "auto",
        "INPUT_FROM": "P6",
        "INPUT_HEYGEN": "prepared",
        "INPUT_SKIP_GENERATE": "false",
        "INPUT_FORCE": "true",
    }
    out = load_request(event_name="workflow_dispatch", environ=env)
    assert out["script"] == "scripts/redshift_0048.json"
    assert out["from_step"] == "P6"
    assert out["heygen_source"] == "prepared"
    assert out["force"] == "true"
    assert out["requested_by"] == "workflow_dispatch"


def test_push_reads_file(tmp_path, monkeypatch):
    from tools import ci_build_request as M

    req = tmp_path / "ci_build_request.json"
    req.write_text(json.dumps({
        "script": "scripts/redshift_0048.json",
        "providers_mode": "auto",
        "from_step": "P6",
        "heygen_source": "api",
        "skip_generate": False,
        "force": True,
        "force_paid": True,
        "requested_by": "cursor",
        "note": "фаза 2",
    }), encoding="utf-8")
    monkeypatch.setattr(M, "REQUEST_PATH", req)
    out = load_request(event_name="push", environ={})
    assert out["script"] == "scripts/redshift_0048.json"
    assert out["from_step"] == "P6"
    assert out["heygen_source"] == "api"
    assert out["force"] == "false"
    assert out["requested_by"] == "cursor"


def test_empty_from_step_is_phase_one(tmp_path, monkeypatch):
    from tools import ci_build_request as M

    req = tmp_path / "ci_build_request.json"
    req.write_text(json.dumps({
        "script": "scripts/x.json",
        "from_step": "",
        "heygen_source": "prepared",
    }), encoding="utf-8")
    monkeypatch.setattr(M, "REQUEST_PATH", req)
    out = load_request(event_name="push", environ={})
    assert out["from_step"] == ""
