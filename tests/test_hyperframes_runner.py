"""Пинованная версия HyperFrames и поиск CLI."""

from __future__ import annotations

import json
from pathlib import Path

from src.lib.render.hyperframes.runner import PINNED_VERSION, cli_command


def test_pinned_version_is_latest_release():
    assert PINNED_VERSION == "0.8.26"


def test_package_json_pins_same_version():
    pkg = json.loads(Path("package.json").read_text(encoding="utf-8"))
    assert pkg["dependencies"]["hyperframes"] == PINNED_VERSION


def test_github_actions_pin_the_same_version():
    for workflow in (
        Path(".github/workflows/ci.yml"),
        Path(".github/workflows/build-video.yml"),
    ):
        text = workflow.read_text(encoding="utf-8")
        assert f'HYPERFRAMES_VERSION: "{PINNED_VERSION}"' in text
        assert "npm ci" in text
        assert "hyperframes --version" in text


def test_cli_prefers_project_binary(monkeypatch, tmp_path):
    from src.lib.render.hyperframes import runner

    fake = tmp_path / "hyperframes"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    runner.cli_command.cache_clear()
    monkeypatch.delenv("HYPERFRAMES_BIN", raising=False)
    monkeypatch.setattr(runner, "_local_cli", lambda: fake)
    try:
        assert cli_command() == [str(fake)]
    finally:
        runner.cli_command.cache_clear()


def test_cli_npx_fallback_uses_pinned_version(monkeypatch):
    from src.lib.render.hyperframes import runner

    runner.cli_command.cache_clear()
    monkeypatch.delenv("HYPERFRAMES_BIN", raising=False)
    monkeypatch.setattr(runner, "_local_cli", lambda: None)

    def _which(name: str) -> str | None:
        if name == "npx":
            return "/usr/bin/npx"
        return None

    monkeypatch.setattr(runner.shutil, "which", _which)
    try:
        assert cli_command() == ["/usr/bin/npx", "--yes", f"hyperframes@{PINNED_VERSION}"]
    finally:
        runner.cli_command.cache_clear()
