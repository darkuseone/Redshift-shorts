"""vision.skip_live + generation.skip — без live API / image gen."""

from __future__ import annotations

from src.lib.config import load_config


def test_skip_flags_default_off():
    cfg = load_config()
    assert cfg.get("vision.skip_live") is False
    assert cfg.get("generation.skip") is False


def test_skip_flags_cli_override():
    cfg = load_config(overrides=["vision.skip_live=true", "generation.skip=true"])
    assert cfg.get("vision.skip_live") is True
    assert cfg.get("generation.skip") is True
