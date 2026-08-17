"""Общие фикстуры тестов."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.lib.config import load_config  # noqa: E402
from src.lib.jsonio import read_json  # noqa: E402


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture()
def cfg():
    """Конфиг с провайдерами в mock-режиме: тесты не ходят в сеть."""
    c = load_config(overrides=["providers.mode=mock"])
    return c


@pytest.fixture()
def sample_script() -> dict:
    return copy.deepcopy(read_json(REPO_ROOT / "scripts" / "redshift_0042.json"))
