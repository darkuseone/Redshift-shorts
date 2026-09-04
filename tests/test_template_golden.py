"""Тесты golden-корпуса выбора шаблонов (Phase C, Step 3, plan v2.1 §7.1).

Проверяет:
1. Воспроизводимость съёма: повторный вызов catalog.pick на зафиксированных
   входах и замороженном манифесте побайтово совпадает с template_id контракта.
2. Воспроизводимость эвристик: вычисление prefer немигрированной логики
   assemble.py даёт в точности зафиксированный список prefer.
3. Покрытие: все 18 keyword-правил, числовые селекторы, текстовые правила,
   негативный корпус, оба варианта A/B.
4. Валидность замороженного манифеста: 204 шаблона, 12 категорий.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.lib.jsonio import read_json
from src.lib.templates import TemplateCatalog
from tools.gen_template_golden import (
    GOLDEN_CORPUS_PATH,
    GOLDEN_MANIFEST_PATH,
    SCENARIOS,
    eval_unmigrated_browser_ui,
    eval_unmigrated_dataviz,
    eval_unmigrated_lowerthirds_overlay,
    eval_unmigrated_lowerthirds_plaque,
    eval_unmigrated_outro_cta,
    eval_unmigrated_text_fullscreen,
    eval_unmigrated_transitions,
)


@pytest.fixture(scope="module")
def golden_manifest_data() -> dict:
    assert GOLDEN_MANIFEST_PATH.exists(), f"Замороженный манифест не найден: {GOLDEN_MANIFEST_PATH}"
    return read_json(GOLDEN_MANIFEST_PATH)


@pytest.fixture(scope="module")
def golden_corpus_data() -> dict:
    assert GOLDEN_CORPUS_PATH.exists(), f"Golden-корпус не найден: {GOLDEN_CORPUS_PATH}"
    return read_json(GOLDEN_CORPUS_PATH)


@pytest.fixture(scope="module")
def golden_catalog(golden_manifest_data) -> TemplateCatalog:
    return TemplateCatalog(GOLDEN_MANIFEST_PATH, golden_manifest_data)


class TestGoldenManifestIntegrity:
    def test_manifest_contains_exact_templates(self, golden_manifest_data):
        templates = golden_manifest_data.get("templates", [])
        assert len(templates) == 204, f"Ожидалось 204 шаблона, получено {len(templates)}"

    def test_manifest_categories(self, golden_catalog):
        counts = golden_catalog.counts()
        expected = {
            "intro-hooks": 8,
            "text-fullscreen": 34,
            "lower-thirds": 14,
            "frames-cards": 7,
            "browser-ui": 21,
            "transitions": 41,
            "avatar-entry": 6,
            "kenburns": 10,
            "parallax": 4,
            "data-viz": 28,
            "outro-cta": 6,
            "hero-devices": 25,
        }
        for cat, exp_count in expected.items():
            assert counts.get(cat, 0) == exp_count, f"Категория {cat}: {counts.get(cat, 0)} != {exp_count}"


class TestGoldenCorpusSelfReproducibility:
    def test_corpus_size_and_structure(self, golden_corpus_data):
        cases = golden_corpus_data.get("cases", [])
        assert len(cases) == 88, f"Ожидалось 88 кейсов, получено {len(cases)}"
        assert golden_corpus_data.get("seed") == 42

    def test_reproduce_catalog_pick_for_all_cases(self, golden_corpus_data, golden_catalog):
        """Контракт: повторный catalog.pick на тех же входах возвращает template_id."""
        cases = golden_corpus_data.get("cases", [])
        for case in cases:
            picked = golden_catalog.pick(
                case["category"],
                duration=case["duration"],
                recent_videos=(),
                exclude=case["exclude"],
                prefer=case["prefer"],
                seed=case["seed"],
                tags=case["tags"],
            )
            assert picked.id == case["template_id"], (
                f"Кейс {case['id']} не воспроизвёлся: ожидался {case['template_id']}, получен {picked.id}"
            )

    def test_reproduce_heuristics_prefer_for_all_cases(self, golden_corpus_data):
        """Информативно: вычисление prefer немигрированной логикой идентично сохранённому prefer."""
        cases = golden_corpus_data.get("cases", [])
        for case in cases:
            call_site = case["call_site"]
            variant = case["variant"]
            blob = case["blob"]

            if call_site == "assemble.py:1290":
                cat, prefer = eval_unmigrated_browser_ui(blob, variant)
                assert cat == case["category"]
                assert prefer == case["prefer"], f"{case['id']}: prefer mismatch"
            elif call_site == "assemble.py:1607":
                prefer, _, _ = eval_unmigrated_dataviz(blob, case.get("nums", []), variant)
                assert prefer == case["prefer"], f"{case['id']}: prefer mismatch"
            elif call_site == "assemble.py:1901":
                prefer, _ = eval_unmigrated_text_fullscreen(blob, variant)
                assert prefer == case["prefer"], f"{case['id']}: prefer mismatch"
            elif call_site == "assemble.py:1978":
                prefer, tags, exclude = eval_unmigrated_transitions(variant, category=case["category"])
                assert prefer == case["prefer"], f"{case['id']}: prefer mismatch"
                assert tags == case["tags"], f"{case['id']}: tags mismatch"
                assert exclude == case["exclude"], f"{case['id']}: exclude mismatch"
            elif call_site == "assemble.py:1403":
                prefer = eval_unmigrated_lowerthirds_plaque()
                assert prefer == case["prefer"], f"{case['id']}: prefer mismatch"
            elif call_site == "assemble.py:1436":
                prefer = eval_unmigrated_lowerthirds_overlay("")
                assert prefer == case["prefer"], f"{case['id']}: prefer mismatch"
            elif call_site == "assemble.py:1460":
                prefer = eval_unmigrated_outro_cta(variant)
                assert prefer == case["prefer"], f"{case['id']}: prefer mismatch"


class TestCorpusCoverage:
    def test_all_18_keyword_rules_covered(self, golden_corpus_data):
        """Проверка покрытия всех 18 keyword-правил (7 browser-ui + 11 data-viz)."""
        scenarios = {c["scenario"] for c in golden_corpus_data["cases"]}

        # 7 browser-ui rules
        browser_rules = {
            "browser_ai_chat",
            "browser_app_showcase",
            "browser_chatgpt_exchange",
            "browser_claude_exchange",
            "browser_message_thread",
            "browser_notes_reveal",
            "browser_notification_cascade",
        }
        missing_browser = browser_rules - scenarios
        assert not missing_browser, f"Пропущены правила browser-ui: {missing_browser}"

        # 11 data-viz rules
        dataviz_rules = {
            "dataviz_spain",
            "dataviz_star_rating",
            "dataviz_us_map",
            "dataviz_us_map_flow",
            "dataviz_us_map_hex",
            "dataviz_world_map",
            "dataviz_apple_money_count",
            "dataviz_north_korea",
            "dataviz_nyc_paris_flight",
            "dataviz_mk_progress_stat",
            "dataviz_flowchart_vertical",
        }
        missing_dataviz = dataviz_rules - scenarios
        assert not missing_dataviz, f"Пропущены правила data-viz: {missing_dataviz}"

    def test_numeric_forms_covered(self, golden_corpus_data):
        scenarios = {c["scenario"] for c in golden_corpus_data["cases"]}
        numeric_rules = {
            "dataviz_num_single_pct",
            "dataviz_num_single_count",
            "dataviz_num_four_bars",
            "dataviz_num_declining",
            "dataviz_num_rating_like",
            "dataviz_neutral",
        }
        missing = numeric_rules - scenarios
        assert not missing, f"Пропущены числовые формы data-viz: {missing}"

    def test_text_fullscreen_rules_covered(self, golden_corpus_data):
        scenarios = {c["scenario"] for c in golden_corpus_data["cases"]}
        text_rules = {
            "text_number_slam",
            "text_codeish_short",
            "text_codeish_long",
            "text_diffish",
            "text_def",
            "text_shellish",
            "text_beatish",
            "text_diff_beat",
            "text_code_and_digits",
            "text_neutral",
        }
        missing = text_rules - scenarios
        assert not missing, f"Пропущены правила text-fullscreen: {missing}"

    def test_negative_corpus_covered(self, golden_corpus_data):
        scenarios = {c["scenario"] for c in golden_corpus_data["cases"]}
        neg_rules = {
            "neg_claude_cloud",
            "neg_flight_kreyser",
            "inherited_star_rating",
            "inherited_progress",
        }
        missing = neg_rules - scenarios
        assert not missing, f"Пропущен негативный корпус: {missing}"

    def test_win_direction_in_heuristics(self, golden_corpus_data):
        """Diff-подобный текст со словом бит/дроп даёт beat-freeze-cut во главе prefer."""
        cases_by_id = {c["id"]: c for c in golden_corpus_data["cases"]}
        case = cases_by_id["text_diff_beat__var_A"]
        assert case["prefer"][0] == "text-fullscreen/beat-freeze-cut"
        assert "text-fullscreen/code-diff" in case["prefer"]

    def test_subtractive_digit_rule(self, golden_corpus_data):
        """Кейс код + цифра заменяет дефолтные 20 стилей на [number-slam, kinetic-stack]."""
        cases_by_id = {c["id"]: c for c in golden_corpus_data["cases"]}
        case = cases_by_id["text_code_and_digits__var_A"]
        prefer = case["prefer"]
        # Кодовые стили идут в начале
        assert prefer[0] == "text-fullscreen/code-typing"
        # В конце ровно [number-slam-card, kinetic-stack] без остальных 18 дефолтных стилей
        assert prefer[-2:] == ["text-fullscreen/number-slam-card", "text-fullscreen/kinetic-stack"]
        assert "text-fullscreen/blur-out-up" not in prefer

    def test_ab_variants_presence(self, golden_corpus_data):
        """Каждый сценарий представлен вариантами A и B."""
        cases = golden_corpus_data["cases"]
        scenarios_a = {c["scenario"] for c in cases if c["variant"] == "A"}
        scenarios_b = {c["scenario"] for c in cases if c["variant"] == "B"}
        assert scenarios_a == scenarios_b
        assert len(scenarios_a) == len(SCENARIOS)
