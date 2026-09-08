"""Диаграмма достижима: числа в сценариях названы словами, а не цифрами (§8.2).

`_stats_from_text` ловил только арабские цифры, а `meaning.py` в собственной
док-строке фиксировал обратное: регулярка на `\\d` находила признак в 6 %
блоков, со словами-числительными — в 25 %. Замер по шести сценариям канала
дал один пригодный для диаграммы блок на шесть роликов — двадцать восемь
шаблонов `data-viz`, 14 % каталога, не имели ни одного шанса сработать.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.p11_assemble.assemble import (
    VisualBudget, _stats_from_text, _stats_from_words,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _values(text: str) -> list[float]:
    return [n["value"] for n in _stats_from_text(text)]


class TestNumbersSpelledOutAreStillNumbers:

    @pytest.mark.parametrize("text,expected", [
        ("Внутри процессора сто пять кубитов", 105.0),
        ("Двадцать три года спустя", 23.0),
        ("Двенадцать километров — и бурить перестали", 12.0),
        ("Пять миллионов кубитов", 5_000_000.0),
        ("Сто тысяч операций в секунду", 100_000.0),
        ("Два миллиарда долларов", 2_000_000_000.0),
    ])
    def test_the_value_is_read_from_the_words(self, text, expected):
        assert _values(text)[0] == expected

    def test_a_compound_numeral_is_one_number(self):
        """«Сто пять» — это сто пять, а не сто и пять."""
        assert _values("Внутри процессора сто пять кубитов") == [105.0]

    def test_separate_numbers_stay_separate(self):
        """Склейка работает только вплотную, иначе она выдумывает числа."""
        assert _values("Сто кубитов и пять лет") == [100.0, 5.0]

    def test_a_year_does_not_leak_a_phantom_number(self):
        """«Тысяча девятьсот девяносто первый» давал 990 — числа, которого нет."""
        vals = _values("В тысяча девятьсот девяносто первом построили сто пять станций")
        assert vals == [105.0], vals

    def test_a_multiplier_is_read_as_a_multiplier(self):
        stats = _stats_from_text("Ошибка падает вдвое на каждом шаге")
        assert stats[0]["value"] == 2.0
        assert stats[0]["suffix"] == "×"

    def test_digits_win_over_words(self):
        """«105» точнее, чем «сто пять»; вместе это одно число, названное дважды."""
        stats = _stats_from_text("Сто пять кубитов, а точнее 105 кубитов")
        assert [n["value"] for n in stats] == [105.0]
        assert not any(n.get("spelled") for n in stats)

    def test_a_block_without_numbers_stays_empty(self):
        assert _values("Логический кубит живёт дольше физического") == []
        assert _stats_from_words("Мы упёрлись в физику") == []


class TestTheReferenceScriptFinallyFeedsAChart:
    """0042: блок b2 «сто пять кубитов» — тот, ради которого §8.2 и писалась."""

    @pytest.fixture()
    def blocks(self):
        script = json.loads((REPO_ROOT / "scripts" / "redshift_0042.json")
                            .read_text(encoding="utf-8"))
        return {b["id"]: b for b in script["blocks"]}

    def test_the_qubit_block_yields_a_number(self, blocks):
        assert _values(blocks["b2"]["text"])[0] == 105.0

    def test_the_halving_block_yields_a_multiplier(self, blocks):
        stats = _stats_from_text(blocks["b4"]["text"])
        assert stats, "блок «ошибка падает вдвое» по-прежнему без числа"

    def test_more_than_one_block_of_the_reference_is_now_chartable(self, blocks):
        """Было: один пригодный блок на шесть роликов."""
        with_numbers = [bid for bid, b in blocks.items()
                        if _stats_from_text(b.get("text", ""))]
        assert len(with_numbers) >= 2, with_numbers


class TestTheChartBudgetIsTwo:

    def test_the_cap_matches_the_ladder_budget(self):
        """Потолок один на оба пути: и на лестницу, и на общий проход."""
        assert VisualBudget.CAPS["dataviz"] == 2

    def test_the_pass_stops_at_the_cap(self):
        source = (REPO_ROOT / "src" / "p11_assemble" / "assemble.py") \
            .read_text(encoding="utf-8")
        assert 'placed >= VisualBudget.CAPS["dataviz"]' in source

    def test_setup_is_among_the_roles(self):
        """На 0042 число живёт в `setup`, а не в `evidence`."""
        source = (REPO_ROOT / "src" / "p11_assemble" / "assemble.py") \
            .read_text(encoding="utf-8")
        assert '("setup", "evidence", "develop", "twist")' in source
