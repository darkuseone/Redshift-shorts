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


@pytest.fixture(scope="session", autouse=True)
def _the_suite_leaves_the_real_base_alone(repo_root):
    """Тесты не имеют права дописывать материал в репозиторий.

    Случалось дважды. Мок-прогон намыл 81 клип на 19 МБ, и `git add -A` унёс
    их в историю. Позже засев в тестах подменял не тот ключ конфига —
    ``paths.storage_dir`` вместо ``storage.local_root``, который читает
    ``build_storage``, — и три PNG-заглушки ложились в настоящую базу,
    возвращаясь после каждого прогона тестов.

    Сторож на всю сессию: считает файлы базы до и после. Дешевле любого
    разбирательства постфактум — и куда дешевле переписывания истории git.
    """
    base = repo_root / "assets" / "footage"

    def snapshot() -> set[str]:
        return {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()} \
            if base.exists() else set()

    before = snapshot()
    yield
    added = sorted(snapshot() - before)
    assert not added, (
        "тесты дописали файлы в общую базу материала — так она и засоряется: "
        + ", ".join(added[:10]))
