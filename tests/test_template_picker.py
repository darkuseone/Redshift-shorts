"""Тесты сценарного селектора шаблонов TemplatePicker (Phase C, Step 2)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.errors import RedshiftError
from src.lib.config import load_config
from src.lib.template_picker import (
    Intent,
    MAX_WALK,
    PickTrace,
    ScenarioIndex,
    TemplatePicker,
    build_blob,
    detect_intents,
)
from src.lib.templates import Template, TemplateCatalog


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def picker(cfg):
    return TemplatePicker.create(cfg)


class TestBlobBuilder:
    def test_build_blob_normalizes_and_lowercases(self):
        blob = build_blob("ChatGPT", "AI Chat", None, "NEW YORK")
        assert blob == "chatgpt ai chat  new york"

    def test_build_blob_empty(self):
        assert build_blob() == ""
        assert build_blob(None, "") == " "


class TestIntentDetection:
    def test_keyword_matching(self, picker):
        intents = picker.index.detect_intents(
            "заметки в apple notes",
            category="browser-ui",
            variant="A",
        )
        assert any(it.id == "browser-notes-reveal" for it in intents)

    def test_regex_pattern_matching(self, picker):
        intents = picker.index.detect_intents(
            "def calculate():\n    return 1\n",
            category="text-fullscreen",
            variant="A",
        )
        assert any(it.id == "text-dark-plus" for it in intents)

    def test_signals_any_matching(self, picker):
        intents = picker.index.detect_intents(
            "нейтральный текст",
            category="data-viz",
            variant="A",
            signals=frozenset(["mechanism"]),
        )
        assert any(it.id == "logic-flowchart" for it in intents)

    def test_needs_and_filter(self, picker):
        # text-code-scroll-long requires lines_ge_7
        intents_without = picker.index.detect_intents(
            "",
            category="text-fullscreen",
            variant="A",
            signals=frozenset(),
        )
        assert not any(it.id == "text-code-scroll-long" for it in intents_without)

        intents_with = picker.index.detect_intents(
            "",
            category="text-fullscreen",
            variant="A",
            signals=frozenset(["lines_ge_7"]),
        )
        assert any(it.id == "text-code-scroll-long" for it in intents_with)

    def test_variant_filter(self, picker):
        intents_a = picker.index.detect_intents(
            "123",
            category="text-fullscreen",
            variant="A",
        )
        assert any(it.id == "text-number-slam" for it in intents_a)

        intents_b = picker.index.detect_intents(
            "123",
            category="text-fullscreen",
            variant="B",
        )
        assert not any(it.id == "text-number-slam" for it in intents_b)

    def test_winning_direction_sorting(self, picker):
        # terminal-shell (26) > code-diff (24)
        diff_text = "$ npm install\n---\n+++ new\n- old\n+ new\n"
        intents = picker.index.detect_intents(
            diff_text,
            category="text-fullscreen",
            variant="A",
        )
        fired_ids = [it.id for it in intents]
        assert fired_ids.index("text-terminal-shell") < fired_ids.index("text-code-diff")

    def test_module_level_detect_intents(self, picker):
        intents1 = detect_intents(picker.index, "123", category="text-fullscreen", variant="A")
        intents2 = detect_intents("123", category="text-fullscreen", variant="A", index=picker.index)
        assert intents1 == intents2
        assert any(it.id == "text-number-slam" for it in intents1)


class TestEmptyTriggerNotAlwaysFire:
    """MUST-010: пустые needs+signals+keywords+patterns не матчатся сами."""

    def test_empty_trigger_without_catchall_never_fires(self, picker):
        data = {
            "version": 1,
            "intents": [
                {
                    "id": "empty-always",
                    "title": "t",
                    "categories": ["browser-ui"],
                    "keywords": [],
                    "patterns": [],
                    "needs": [],
                    "signals_any": [],
                    "templates": ["browser-ui/chat-thread"],
                    "weight": 20,
                    "variants": ["A", "B"],
                }
            ],
        }
        index = ScenarioIndex.from_dict(data, catalog=picker.catalog)
        fired = index.detect_intents(
            "любой текст без сущности",
            category="browser-ui",
            variant="A",
        )
        assert fired == []

    def test_empty_trigger_catchall_does_fire(self, picker):
        data = {
            "version": 1,
            "intents": [
                {
                    "id": "empty-catch",
                    "title": "t",
                    "categories": ["browser-ui"],
                    "keywords": [],
                    "patterns": [],
                    "needs": [],
                    "signals_any": [],
                    "templates": ["browser-ui/chat-thread"],
                    "variants": ["A"],
                    "catchall": True,
                }
            ],
        }
        index = ScenarioIndex.from_dict(data, catalog=picker.catalog)
        fired = index.detect_intents("нейтральный текст", category="browser-ui", variant="A")
        assert [it.id for it in fired] == ["empty-catch"]
        assert fired[0].weight == 0
        assert fired[0].catchall

    def test_two_catchalls_same_category_variant_rejected(self, picker):
        data = {
            "version": 1,
            "intents": [
                {
                    "id": "catch-a",
                    "title": "t",
                    "categories": ["browser-ui"],
                    "templates": ["browser-ui/chat-thread"],
                    "variants": ["A"],
                    "catchall": True,
                },
                {
                    "id": "catch-b",
                    "title": "t",
                    "categories": ["browser-ui"],
                    "templates": ["browser-ui/article-highlight"],
                    "variants": ["A"],
                    "catchall": True,
                },
            ],
        }
        with pytest.raises(RedshiftError) as exc:
            ScenarioIndex.from_dict(data, catalog=picker.catalog)
        assert exc.value.code == "SCENARIO_INDEX_INVALID"

    def test_entityless_text_does_not_fire_world_map_nk_or_chat(self, picker):
        blob = "Белок складывается сам по законам физики"
        banned = {
            "geo-world-map",
            "geo-north-korea",
            "geo-generic",
            "browser-ai-chat",
            "browser-chatgpt-exchange",
            "browser-claude-exchange",
        }
        fired = set()
        for category in ("data-viz", "browser-ui"):
            fired |= {
                it.id
                for it in picker.index.detect_intents(blob, category=category, variant="A")
            }
        assert not (fired & banned), fired & banned

    def test_production_empty_triggers_are_explicit_catchalls(self, picker):
        empty = [
            it for it in picker.index.intents
            if not it.keywords and not it.patterns and not it.signals_any and not it.needs
        ]
        assert empty, "ожидали default-полосу с пустым триггером"
        assert all(it.catchall for it in empty)
        # 0 или 1 catchall на (категория, вариант)
        slots: dict[tuple[str, str], str] = {}
        for it in picker.index.intents:
            if not it.catchall:
                continue
            for cat in it.categories:
                for var in it.variants:
                    key = (cat, var)
                    assert key not in slots, (key, slots[key], it.id)
                    slots[key] = it.id


class TestRareEntityGate:
    """MUST-011 эмпирика + MUST-013: rare geo/finance/social id выпилены."""

    def test_empirical_kolskaya_mirov_does_not_take_world_map(self, picker):
        blob = "Кольская кора миров"
        fired = {it.id for it in picker.index.detect_intents(
            blob, category="data-viz", variant="A")}
        assert "geo-world-map" not in fired
        t, _ = picker.pick("data-viz", blob=blob, variant="A")
        assert t.id != "data-viz/world-map"
        assert picker.catalog.by_id("data-viz/world-map") is None

    def test_empirical_empty_cta_does_not_take_nk(self, picker):
        blob = ""
        fired = {it.id for it in picker.index.detect_intents(
            blob, category="data-viz", variant="A")}
        assert "geo-north-korea" not in fired
        assert "geo-generic" not in fired
        t, _ = picker.pick("data-viz", blob=blob, variant="A")
        assert t.id != "data-viz/north-korea-locked-down"

    def test_empirical_protein_neuronet_does_not_take_ai_chat(self, picker):
        blob = "белок нейросет"
        fired = {it.id for it in picker.index.detect_intents(
            blob, category="browser-ui", variant="A")}
        assert "browser-ai-chat" not in fired
        t, _ = picker.pick("browser-ui", blob=blob, variant="A")
        assert t.id != "browser-ui/ai-chat-reveal"

    def test_empirical_quantum_bit_does_not_take_beat_freeze(self, picker):
        blob = "Квантовый бит живёт"
        fired = {it.id for it in picker.index.detect_intents(
            blob, category="text-fullscreen", variant="A")}
        assert "text-beat-freeze" not in fired
        t, _ = picker.pick("text-fullscreen", blob=blob, variant="A")
        assert t.id != "text-fullscreen/beat-freeze-cut"

    def test_north_korea_entity_does_not_resurrect_deleted_nk(self, picker):
        blob = "North Korea sanctions, Пхеньян"
        fired = {it.id for it in picker.index.detect_intents(
            blob, category="data-viz", variant="A")}
        assert "geo-north-korea" not in fired
        t, _ = picker.pick("data-viz", blob=blob, variant="A")
        assert t.id != "data-viz/north-korea-locked-down"
        assert picker.catalog.by_id("data-viz/north-korea-locked-down") is None

    def test_geo_generic_intent_is_gone(self, picker):
        by_id = {it.id: it for it in picker.index.intents}
        assert "geo-generic" not in by_id
        fired = picker.index.detect_intents(
            "просто карта без страны", category="data-viz", variant="A")
        assert not any(it.id == "geo-generic" for it in fired)

    def test_dollar_without_entity_does_not_take_apple_money(self, picker):
        blob = "один доллар ещё не финансы"
        fired = {it.id for it in picker.index.detect_intents(
            blob, category="data-viz", variant="A")}
        assert "finance-money-count" not in fired
        t, _ = picker.pick("data-viz", blob=blob, variant="A")
        assert t.id != "data-viz/apple-money-count"
        assert picker.catalog.by_id("data-viz/apple-money-count") is None


class TestWeightBands:
    def test_bands_boundaries(self, picker):
        idx = picker.index
        assert idx.specific_weight_min == 20
        assert idx.default_weight_min == 10

        for intent in idx.intents:
            assert intent.weight >= 0
            if intent.weight >= 20:
                # Specific band
                pass
            elif intent.weight >= 10:
                # Default band
                pass
            else:
                # Generic band (< 10)
                pass

    def test_key_scenario_weights(self, picker):
        by_id = {it.id: it.weight for it in picker.index.intents}
        assert by_id["browser-source-generic"] == 10
        assert by_id["lowerthird-lockup-generic"] == 10
        assert by_id["transitions-variant-a-order"] == 10
        assert by_id["cta-brand-close"] == 11
        assert by_id["cta-subscribe"] == 10
        assert by_id["cta-brand-close"] > by_id["cta-subscribe"]
        assert "geo-generic" not in by_id
        assert "text-beat-freeze" not in by_id

        # text-fullscreen winning direction hierarchy
        assert (
            by_id["text-terminal-shell"]
            > by_id["text-dark-plus"]
            > by_id["text-code-diff"]
            > by_id["text-code-scroll-long"]
            > by_id["text-code-typing-short"]
            > by_id["text-code-snippet"]
            > by_id["text-number-slam"]
        )


class TestValidation:
    def test_duplicate_intent_id_rejected(self, picker):
        data = {
            "version": 1,
            "intents": [
                {
                    "id": "dup",
                    "title": "t1",
                    "categories": ["browser-ui"],
                    "templates": ["browser-ui/chat-thread"],
                    "weight": 20,
                    "variants": ["A"],
                },
                {
                    "id": "dup",
                    "title": "t2",
                    "categories": ["browser-ui"],
                    "templates": ["browser-ui/chat-thread"],
                    "weight": 20,
                    "variants": ["A"],
                },
            ],
        }
        with pytest.raises(RedshiftError) as exc:
            ScenarioIndex.from_dict(data, catalog=picker.catalog)
        assert exc.value.code == "SCENARIO_INDEX_INVALID"

    def test_unknown_template_id_rejected(self, picker):
        data = {
            "version": 1,
            "intents": [
                {
                    "id": "test-unknown",
                    "title": "t",
                    "categories": ["browser-ui"],
                    "templates": ["browser-ui/nonexistent-xyz"],
                    "weight": 20,
                    "variants": ["A"],
                }
            ],
        }
        with pytest.raises(RedshiftError) as exc:
            ScenarioIndex.from_dict(data, catalog=picker.catalog)
        assert exc.value.code == "SCENARIO_INDEX_INVALID"

    def test_category_mismatch_rejected(self, picker):
        # Template is browser-ui, intent category is text-fullscreen
        data = {
            "version": 1,
            "intents": [
                {
                    "id": "test-mismatch",
                    "title": "t",
                    "categories": ["text-fullscreen"],
                    "templates": ["browser-ui/chat-thread"],
                    "weight": 20,
                    "variants": ["A"],
                }
            ],
        }
        with pytest.raises(RedshiftError) as exc:
            ScenarioIndex.from_dict(data, catalog=picker.catalog)
        assert exc.value.code == "SCENARIO_INDEX_INVALID"

    def test_tag_intents_unknown_intent_rejected(self, picker):
        data = {
            "version": 1,
            "intents": [
                {
                    "id": "test-ok",
                    "title": "t",
                    "categories": ["browser-ui"],
                    "templates": ["browser-ui/chat-thread"],
                    "weight": 20,
                    "variants": ["A"],
                }
            ],
            "tag_intents": {
                "some-tag": ["nonexistent-intent-id"],
            },
        }
        with pytest.raises(RedshiftError) as exc:
            ScenarioIndex.from_dict(data, catalog=picker.catalog)
        assert exc.value.code == "SCENARIO_INDEX_INVALID"

    def test_invalid_weight_bands_rejected(self):
        data = {
            "version": 1,
            "specific_weight_min": 10,
            "default_weight_min": 20,
            "intents": [],
        }
        with pytest.raises(RedshiftError) as exc:
            ScenarioIndex.from_dict(data)
        assert exc.value.code == "SCENARIO_INDEX_INVALID"


class TestMissingAndBrokenConfig:
    def test_missing_file_returns_empty_index_with_warn(self, tmp_path, caplog):
        nonexistent = tmp_path / "missing_scenarios.json"
        index = ScenarioIndex.load(path=nonexistent)
        assert isinstance(index, ScenarioIndex)
        assert len(index.intents) == 0

    def test_broken_json_raises_scenario_index_invalid(self, tmp_path):
        broken = tmp_path / "broken.json"
        broken.write_text("{ not valid json !!!", encoding="utf-8")
        with pytest.raises(RedshiftError) as exc:
            ScenarioIndex.load(path=broken)
        assert exc.value.code == "SCENARIO_INDEX_INVALID"


class TestPickerChannelsAndWalk:
    def test_five_channels_collected(self, picker):
        _, trace = picker.pick(
            "text-fullscreen",
            blob="120 миллионов",
            variant="A",
            prefer_head=["text-fullscreen/stack-3lines"],
            prefer_base=["text-fullscreen/dark-plus"],
        )
        assert "head" in trace.channels
        assert "specific" in trace.channels
        assert "base" in trace.channels
        assert "default" in trace.channels
        assert "generic" in trace.channels

        assert trace.channels["head"] == ("text-fullscreen/stack-3lines",)
        assert "text-fullscreen/number-slam-card" in trace.channels["specific"]
        assert trace.channels["base"] == ("text-fullscreen/dark-plus",)

    def test_max_walk_cap_applies_only_to_walk(self, picker):
        # Pass 30 head preferences
        head_many = [f"head_{i}" for i in range(30)]
        _, trace = picker.pick(
            "browser-ui",
            blob="",
            variant="A",
            prefer_head=head_many,
        )
        assert len(trace.walk) == MAX_WALK
        assert len(trace.walk) <= 24

    def test_no_cap_on_default_and_generic(self, picker):
        # text-fullscreen variant A default intent: on-brand templates covering 1.5–3.0s (P0-3)
        _, trace_text = picker.pick("text-fullscreen", blob="нейтральный текст", variant="A")
        assert len(trace_text.fallback) == 10
        assert trace_text.fallback[0] == "text-fullscreen/stack-3lines"
        assert "text-fullscreen/beat-freeze-cut" not in trace_text.fallback
        assert "text-fullscreen/news-ticker" not in trace_text.fallback
        assert "text-fullscreen/date-marker" in trace_text.fallback

        # transitions variant A default intent has exactly 15 templates
        _, trace_tr = picker.pick("transitions", blob="", variant="A")
        assert len(trace_tr.fallback) == 15
        assert trace_tr.fallback[0] == "transitions/transitions-other"
        assert trace_tr.fallback[-1] == "transitions/zoom-through"

        # browser-ui default intent (browser-source-generic) has 3 templates
        _, trace_b = picker.pick("browser-ui", blob="статья", variant="A")
        assert len(trace_b.fallback) == 3

    def test_tie_class_is_one_on_walk_hit(self, picker):
        _, trace = picker.pick(
            "data-viz",
            blob=build_blob("блок-схема дерево решений алгоритм"),
            variant="A",
        )
        assert trace.won_at == 0
        assert trace.tie_class == 1


class TestReplacesDefault:
    def test_code_plus_digit_variant_a(self, picker):
        # Code + digit: specific walk has code templates then number-slam templates
        # fallback is replaced by text-number-slam (includes longer fact-card for 2.5s+ slots)
        text = "def calculate_price(): return 42"
        t, trace = picker.pick("text-fullscreen", blob=text, variant="A")
        assert trace.replaced_default_by == "text-number-slam"
        assert trace.fallback == (
            "text-fullscreen/number-slam-card",
            "text-fullscreen/kinetic-stack",
            "text-fullscreen/fact-card",
        )
        # dark-plus wins in walk
        assert t.id == "text-fullscreen/dark-plus"
        assert trace.won_at is not None

    def test_digit_only_variant_a_leads_to_number_slam(self, picker):
        text = "120 миллионов пользователей"
        t, trace = picker.pick("text-fullscreen", blob=text, variant="A")
        assert t.id == "text-fullscreen/number-slam-card"
        assert trace.won_at == 0
        assert trace.tie_class == 1
        assert trace.replaced_default_by == "text-number-slam"

    def test_digit_variant_b_does_not_replace_default(self, picker):
        text = "120 миллионов пользователей"
        t, trace = picker.pick("text-fullscreen", blob=text, variant="B")
        assert trace.replaced_default_by is None
        assert trace.fallback[0] == "text-fullscreen/stack-3lines"
        assert "text-fullscreen/fact-card" in trace.fallback
        assert "text-fullscreen/quote-frame" in trace.fallback
        assert len(trace.fallback) == 10

    def test_text_number_slam_needs_empty_guard(self, picker):
        # Intent text-number-slam must not require 'numbers' signal
        slam = next(it for it in picker.index.intents if it.id == "text-number-slam")
        assert len(slam.needs) == 0

        # Guard: no intent of category text-fullscreen requires signals outside lines_ge_7/lines_lt_7
        allowed_text_signals = {"lines_ge_7", "lines_lt_7"}
        for it in picker.index.intents:
            if "text-fullscreen" in it.categories:
                assert it.needs.issubset(allowed_text_signals), (
                    f"Intent {it.id} in text-fullscreen requires unexpected signals: {it.needs}"
                )


class TestPassThrough:
    def test_exclude_skips_in_walk(self, picker):
        blob = build_blob("блок-схема дерево решений алгоритм")
        t1, trace1 = picker.pick("data-viz", blob=blob, variant="A")
        assert t1.id == "data-viz/flowchart-vertical"
        assert trace1.won_at == 0

        t2, trace2 = picker.pick(
            "data-viz",
            blob=blob,
            variant="A",
            exclude=["data-viz/flowchart-vertical"],
        )
        assert t2.id == "data-viz/flowchart"
        assert trace2.won_at == 1

    def test_tags_and_exclude_on_transitions(self, picker):
        # Call-site assemble.py:1978 passes tags={"dynamic", "entry"} and exclude
        t, trace = picker.pick(
            "transitions",
            variant="A",
            tags=["dynamic", "entry"],
            exclude=["transitions/transitions-other", "transitions/cut"],
        )
        assert t.id != "transitions/transitions-other"
        assert "dynamic" in t.tags or "entry" in t.tags

    def test_duration_filtering(self, picker):
        # Hard allow: duration inside scenario set; escape if empty (P0-2).
        t, trace = picker.pick(
            "transitions",
            duration=0.5,
            variant="A",
        )
        if trace.escaped:
            assert t.id in trace.fallback
        else:
            assert t.fits(0.5)


    def test_prefer_is_a_hard_allowlist(self, picker):
        """Scenario allowlist must not escape into junk like app-showcase (P0-2)."""
        from src.lib.meaning import block_traits
        blob = "Работа опубликована в Nature. Впервые логический кубит прожил дольше"
        traits = block_traits(blob)
        for seed in range(5):
            t, trace = picker.pick(
                "browser-ui",
                blob=blob,
                traits=traits,
                variant="A",
                duration=3.4,
                seed=seed,
            )
            assert t.id != "browser-ui/app-showcase"
            assert trace.allow_size > 0
            allowed = set(trace.walk) | set(trace.fallback)
            assert t.id in allowed


    def test_default_sets_cover_duration_matrix(self, picker):
        """P0-3 DoD: every variant x duration lands inside its default set."""
        default_a = {
            "text-fullscreen/stack-3lines",
            "text-fullscreen/fact-card",
            "text-fullscreen/per-word-crossfade",
            "text-fullscreen/blur-out-up",
            "text-fullscreen/bottom-up-letters",
            "text-fullscreen/bigtext-mask-footage",
            "text-fullscreen/quote-frame",
            "text-fullscreen/date-marker",
            "text-fullscreen/kinetic-type-swap",
            "text-fullscreen/label-strip",
        }
        default_b = {
            "text-fullscreen/stack-3lines",
            "text-fullscreen/fact-card",
            "text-fullscreen/quote-frame",
            "text-fullscreen/per-word-crossfade",
            "text-fullscreen/blur-out-up",
            "text-fullscreen/bigtext-mask-footage",
            "text-fullscreen/bottom-up-letters",
            "text-fullscreen/date-marker",
            "text-fullscreen/kinetic-type-swap",
            "text-fullscreen/label-strip",
        }
        blob = "ОШИБКА ПАДАЕТ ВДВОЕ"
        from src.lib.meaning import block_traits
        traits = block_traits("Здесь всё наоборот. Ошибка падает вдвое на каждом шаге.")
        for d in (1.5, 2.1, 2.5, 2.58, 3.0):
            for v in ("A", "B"):
                t, trace = picker.pick(
                    "text-fullscreen",
                    blob=blob,
                    signals={"lines_lt_7"},
                    traits=traits,
                    variant=v,
                    duration=d,
                    seed=3,
                )
                expected = default_a if v == "A" else default_b
                assert t.id in expected, f"dur={d} {v} -> {t.id} not in default set"
                assert t.fits(d), f"dur={d} {v} -> {t.id} duration_range={t.duration_range}"
                assert not trace.escaped or t.id in expected

    def test_fs_duration_matrix_never_template_category_empty(self, picker):
        """Real FS slot lengths must never raise TEMPLATE_CATEGORY_EMPTY (P0-3)."""
        from src.errors import RedshiftError
        from src.lib.meaning import block_traits

        blobs = [
            "ОШИБКА ПАДАЕТ ВДВОЕ",
            "логический кубит прожил дольше",
            "Впервые 105 кубитов работают вместе",
            "Здесь всё наоборот",
        ]
        default_b = [
            "text-fullscreen/stack-3lines",
            "text-fullscreen/fact-card",
            "text-fullscreen/quote-frame",
            "text-fullscreen/per-word-crossfade",
            "text-fullscreen/blur-out-up",
            "text-fullscreen/bigtext-mask-footage",
            "text-fullscreen/bottom-up-letters",
            "text-fullscreen/date-marker",
            "text-fullscreen/kinetic-type-swap",
            "text-fullscreen/label-strip",
        ]
        for d in (1.5, 2.1, 2.5, 2.58, 3.0):
            for v in ("A", "B"):
                for blob in blobs:
                    traits = block_traits(blob)
                    try:
                        t, trace = picker.pick(
                            "text-fullscreen",
                            blob=blob,
                            signals={"lines_lt_7"},
                            traits=traits,
                            variant=v,
                            duration=d,
                            seed=7,
                            # Exhaust allowlist like many gap FS fills in P11.
                            exclude=list(default_b) if v == "B" else list(default_b) + [
                                "text-fullscreen/number-slam-card",
                                "text-fullscreen/kinetic-stack",
                            ],
                        )
                    except RedshiftError as exc:
                        assert False, (
                            f"TEMPLATE_CATEGORY_EMPTY dur={d} {v} blob={blob!r}: {exc}"
                        )
                    assert t.id.startswith("text-fullscreen/")
                    # Hard allowlist: never reopen junk / 3-phone demos.
                    assert t.id != "browser-ui/app-showcase"
                    assert "app-showcase" not in t.id


class TestReachability:
    def test_all_manifest_templates_present_in_channels_for_live_categories(self, picker):
        live_categories = [
            cat for cat in picker.catalog.counts().keys()
            if cat not in picker.index.unreachable_categories
        ]
        # Двенадцать: живы все категории каталога — `intro-hooks` подключена
        # в Q1.2, `parallax` в Q2.6.
        assert len(live_categories) == 12

        manifest_by_cat = {cat: set() for cat in live_categories}
        for t in picker.catalog.all():
            if t.category in live_categories and t.is_active:
                manifest_by_cat[t.category].add(t.id)

        reached_by_cat = {cat: set() for cat in live_categories}
        for intent in picker.index.intents:
            for cat in intent.categories:
                if cat in live_categories:
                    for v in intent.variants:
                        if intent.keywords:
                            blob = intent.keywords[0]
                        elif intent.patterns:
                            blob = "42 test"  # pattern-only intents (e.g. text-number-slam)
                        else:
                            blob = ""
                        signals = intent.needs | intent.signals_any
                        _, trace = picker.pick(cat, blob=blob, signals=signals, variant=v)
                        for ch_templates in trace.channels.values():
                            reached_by_cat[cat].update(ch_templates)

        for cat in live_categories:
            missing = manifest_by_cat[cat] - reached_by_cat[cat]
            assert not missing, f"Category {cat} has unreached templates in channels: {missing}"

    def test_unreachable_categories_have_no_live_call_sites(self, picker):
        """Пусто: `intro-hooks` подключена в Q1.2, `parallax` — в Q2.6."""
        assert set(picker.index.unreachable_categories) == set()

    def test_the_hook_category_is_actually_reached_from_the_assembler(self):
        """Запись о недостижимости снимается вместе с вызовом, а не вместо него."""
        source = (Path(__file__).resolve().parents[1] / "src" / "p11_assemble"
                  / "assemble.py").read_text(encoding="utf-8")
        assert 'picker.pick(\n        "intro-hooks"' in source or \
            '"intro-hooks",' in source, "категория снята из списка, но не вызвана"


class TestNegativeCorpus:
    def test_kreyser_does_not_fire_flight(self, picker):
        _, trace = picker.pick("data-viz", blob=build_blob("крейсер аврора"), variant="A")
        fired_ids = [fid for fid, _ in trace.fired]
        assert "geo-flight" not in fired_ids

    def test_cloud_hosting_does_not_fire_claude(self, picker):
        _, trace = picker.pick("browser-ui", blob=build_blob("быстрый клауд-хостинг"), variant="A")
        fired_ids = [fid for fid, _ in trace.fired]
        assert "browser-claude-exchange" not in fired_ids

    def test_inherited_false_positives(self, picker):
        t_rate, trace_rate = picker.pick(
            "data-viz", blob=build_blob("рейтинг доверия"), variant="A")
        assert "dataviz-star-rating" not in {fid for fid, _ in trace_rate.fired}
        assert t_rate.id != "data-viz/star-rating-fill"
        assert picker.catalog.by_id("data-viz/star-rating-fill") is None

        t_prog, trace_prog = picker.pick(
            "data-viz", blob=build_blob("прогресс переговоров"), variant="A")
        assert "stat-progress-goals" not in {fid for fid, _ in trace_prog.fired}
        assert t_prog.id != "data-viz/mk-progress-stat"
        assert picker.catalog.by_id("data-viz/mk-progress-stat") is None


class TestStability:
    def test_last_used_in_does_not_break_guided_choice(self, picker):
        # Walk hit ignores usage counts. Cooldown is a separate hard gate and
        # applies only when recent_videos is passed (MUST-012).
        target = picker.catalog.by_id("data-viz/flowchart-vertical")
        target.last_used_in.extend(["video_01", "video_02", "video_03", "video_04"])

        t, trace = picker.pick(
            "data-viz",
            blob=build_blob("блок-схема дерево решений алгоритм"),
            variant="A",
        )
        assert t.id == "data-viz/flowchart-vertical"
        assert trace.won_at == 0
        assert trace.tie_class == 1


class TestCliExplain:
    def test_cli_templates_explain_guided_hit(self, capsys):
        from src.cli import main

        ret = main(["templates", "--explain", "блок-схема алгоритм", "--category", "data-viz"])
        assert ret == 0

        captured = capsys.readouterr()
        out = captured.out

        # Fired intents with weight
        assert "logic-flowchart (31)" in out

        # All 5 channels
        assert "head:" in out
        assert "specific:" in out
        assert "base:" in out
        assert "default:" in out
        assert "generic:" in out

        # Walk with winner
        assert "walk[0] = data-viz/flowchart-vertical" in out
        assert "data-viz/flowchart-vertical" in out

        # Won at and tie class
        assert "won_at = 0" in out or "won_at: 0" in out
        assert "tie_class = 1" in out or "tie_class: 1" in out

    def test_cli_templates_explain_replaces_default(self, capsys):
        from src.cli import main

        ret = main(["templates", "--explain", "def calc(): return 42", "--category", "text-fullscreen"])
        assert ret == 0

        captured = capsys.readouterr()
        out = captured.out

        assert "replaced_default_by: text-number-slam" in out
        assert "text-fullscreen/number-slam-card" in out
        assert "won_at = 0" in out or "won_at: 0" in out

    def test_cli_templates_explain_requires_category(self, capsys):
        from src.cli import main

        ret = main(["templates", "--explain", "рейс Нью-Йорк — Париж"])
        assert ret == 2

        captured = capsys.readouterr()
        err_data = json.loads(captured.err)
        assert err_data["code"] == "CATEGORY_REQUIRED"

    def test_cli_templates_explain_missing_scenarios_file(self, capsys, tmp_path):
        from src.cli import main

        missing_file = tmp_path / "nonexistent.json"
        ret = main([
            "--set", f"paths.template_scenarios={missing_file}",
            "templates", "--explain", "рейс", "--category", "data-viz",
        ])
        assert ret == 2

        captured = capsys.readouterr()
        err_data = json.loads(captured.err)
        assert err_data["code"] == "SCENARIO_INDEX_NOT_FOUND"

    def test_cli_templates_without_explain_prints_json(self, capsys):
        from src.cli import main

        ret = main(["templates", "--category", "data-viz"])
        assert ret == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "count" in data
        assert "by_category" in data
        assert "templates" in data
        assert data["count"] == 17
        assert "data-viz/flowchart-vertical" in data["templates"]
        assert "data-viz/nyc-paris-flight" not in data["templates"]


def test_active_templates_have_frequency(picker):
    missing = [t.id for t in picker.catalog.templates if t.is_active and not t.frequency]
    assert missing == []
    assert picker.catalog.by_id("text-fullscreen/scan-band").frequency == "rare"
    assert picker.catalog.by_id("browser-ui/chat-thread").frequency == "signature"


def test_frequency_heuristic_matches_locked_buckets():
    from src.lib.templates import frequency_for

    assert frequency_for("text-fullscreen/scan-band", "text-fullscreen", "scan_band") == "rare"
    assert frequency_for("text-fullscreen/stack-3lines", "text-fullscreen", "fullscreen_text") == "signature"
    assert frequency_for("transitions/cut", "transitions", "cut") == "variant"
    assert frequency_for("transitions/gravitational-lens", "transitions", "gravitational_lens") == "rare"


def test_pick_prefers_signature_frequency_over_rare():
    data = {
        "templates": [
            {
                "id": "text-fullscreen/rare-one", "name": "rare-one",
                "category": "text-fullscreen", "title": "r",
                "duration_range": [1.0, 5.0], "params": {}, "tags": [],
                "renderer": "x", "frequency": "rare", "status": "active",
            },
            {
                "id": "text-fullscreen/sig-one", "name": "sig-one",
                "category": "text-fullscreen", "title": "s",
                "duration_range": [1.0, 5.0], "params": {}, "tags": [],
                "renderer": "x", "frequency": "signature", "status": "active",
            },
        ]
    }
    cat = TemplateCatalog(Path("unused.json"), data)
    picked = cat.pick("text-fullscreen", duration=2.0, seed=0)
    assert picked.id == "text-fullscreen/sig-one"


def test_gen_templates_preserves_lifecycle_fields():
    src = Path("tools/gen_templates.py").read_text(encoding="utf-8")
    assert "status" in src and "retired_reason" in src and "frequency" in src
    assert "last_used_in" in src
    assert "duration_range" in src and "needs" in src
    assert "rarity" in src and "brand_ok" in src and "cooldown_videos" in src



class TestAGatedIntentIsMoreSpecificThanACatchAll:
    """N-14: интент с условием проигрывал заглушке без условий.

    `lowerthird-metric-badge` требует `number` и весил 5 — ниже
    `default_weight_min`, то есть попадал в generic-канал. А тот берётся
    только когда default-канал пуст, и `lowerthird-lockup-generic` (вес 10,
    ни ключевых слов, ни гейтов) срабатывал всегда. Плашка с метрикой не
    выигрывала ни на одном сиде при живом числе в реплике.
    """

    def _cfg(self):
        return json.loads((Path(__file__).resolve().parents[1] / "config"
                           / "template_scenarios.json").read_text(encoding="utf-8"))

    def test_no_gated_intent_sits_below_the_specific_threshold(self):
        cfg = self._cfg()
        floor = cfg["specific_weight_min"]
        low = [i["id"] for i in cfg["intents"]
               if (i.get("needs") or i.get("signals_any")) and i["weight"] < floor]
        assert not low, f"интенты с условием ниже порога специфичности: {low}"

    def test_the_metric_badge_wins_when_the_block_has_a_number(self, picker):
        from src.lib.meaning import block_traits
        traits = block_traits("Ошибка падает вдвое: сто пять кубитов держат порог")
        picked = {
            picker.pick("lower-thirds", blob=build_blob("МЕТРИКА", "порог"),
                        signals=traits, traits=traits, variant="B",
                        duration=2.4, seed=seed)[0].id
            for seed in range(12)
        }
        assert "lower-thirds/metric-badge" in picked, picked

    def test_a_block_without_a_number_keeps_the_generic_plaque(self, picker):
        """Гейт работает в обе стороны: без числа метрике в кадре нечего делать."""
        from src.lib.meaning import block_traits
        traits = block_traits("Мы упёрлись в физику и дальше не пошли")
        picked = {
            picker.pick("lower-thirds", blob=build_blob("ФИЗИКА", ""),
                        signals=traits, traits=traits, variant="B",
                        duration=2.4, seed=seed)[0].id
            for seed in range(12)
        }
        assert "lower-thirds/metric-badge" not in picked, picked

    def test_the_two_dictionaries_agree_on_the_name_of_a_number(self):
        """`numbers` — сигнал, `number` — признак; врозь они не сходились."""
        cfg = self._cfg()
        stale = [i["id"] for i in cfg["intents"] if "numbers" in (i.get("needs") or [])]
        assert not stale, f"интенты всё ещё ждут сигнал 'numbers': {stale}"
        source = (Path(__file__).resolve().parents[1] / "src" / "p11_assemble"
                  / "assemble.py").read_text(encoding="utf-8")
        assert '"numbers"' not in source


class TestTheFrequencyLevelIsAShareNotAPriority:
    """§8.5: `frequency` был жёстким ключом сортировки.

    `signature` побеждал `variant` всегда и на всех кадрах, поэтому доля
    узнаваемых приёмов упиралась в единицу, а разнообразие держалось только
    на потолке повторов одного id.
    """

    def _budget(self):
        from src.lib.templates import FrequencyBudget
        return FrequencyBudget()

    def test_an_empty_budget_forbids_nothing(self):
        budget = self._budget()
        assert not budget.saturated("signature")
        assert budget.share("signature") == 0.0

    def test_the_first_few_picks_are_not_limited(self):
        """На одном-двух приёмах доля либо 0, либо 1: это случайность, не доля."""
        budget = self._budget()
        budget.take("signature")
        budget.take("signature")
        assert not budget.saturated("signature")

    def test_the_level_saturates_at_its_ceiling(self):
        budget = self._budget()
        for _ in range(8):
            budget.take("signature")
        assert budget.saturated("signature")
        assert budget.share("signature") == 1.0

    def test_a_level_below_its_ceiling_stays_open(self):
        budget = self._budget()
        for _ in range(3):
            budget.take("signature")
        for _ in range(3):
            budget.take("variant")
        assert not budget.saturated("signature"), budget.to_dict()

    def test_the_picker_keeps_its_own_budget(self, picker):
        before = picker.freq_budget.total
        picker.pick("text-fullscreen", blob=build_blob("СЛОВО", ""),
                    variant="B", duration=2.5, seed=1)
        assert picker.freq_budget.total == before + 1

    def test_the_shares_land_inside_the_corridor_over_a_video(self, picker):
        """Инвариант §8.5 на двадцати кадрах."""
        used: list[str] = []
        for seed in range(20):
            template, _ = picker.pick(
                "text-fullscreen", blob=build_blob(f"СЛОВО {seed}", ""),
                variant="B", duration=2.5, exclude=used, seed=seed)
            used.append(template.id)
        shares = picker.freq_budget
        assert 0.55 <= shares.share("signature") <= 0.80, shares.to_dict()
        assert shares.share("rare") <= 0.10, shares.to_dict()

    def test_a_saturated_level_never_empties_the_allowed_set(self, picker):
        """Пустой allow отправил бы подбор гулять по категории — это QC-22."""
        for _ in range(12):
            picker.freq_budget.take("signature")
        template, trace = picker.pick(
            "text-fullscreen", blob=build_blob("СЛОВО", ""),
            variant="B", duration=2.5, seed=3)
        assert template.id
        assert not trace.escaped


# §9 DELETE LIST — каждый id отсутствует в живом каталоге и индексе picker.
DELETE_TEMPLATE_IDS = (
    "browser-ui/app-showcase",
    "browser-ui/blue-sweater-intro-video",
    "browser-ui/macos-notification",
    "browser-ui/notification-cascade",
    "browser-ui/spotify-card",
    "browser-ui/vpn-youtube-spot",
    "lower-thirds/instagram-follow",
    "lower-thirds/tiktok-follow",
    "text-fullscreen/split-flap-board",
    "data-viz/north-korea-locked-down",
    "data-viz/nyc-paris-flight",
    "data-viz/spain-map",
    "data-viz/us-map",
    "data-viz/us-map-flow",
    "data-viz/us-map-hex",
    "data-viz/us-map-bubble",
    "data-viz/world-map",
    "data-viz/apple-money-count",
    "data-viz/star-rating-fill",
    "data-viz/mk-progress-stat",
    "browser-ui/chatgpt-exchange",
    "browser-ui/claude-exchange",
    "browser-ui/ai-chat-reveal",
    "browser-ui/message-thread-reveal",
    "browser-ui/reddit-post",
    "browser-ui/x-post",
    "lower-thirds/yt-lower-third",
    "text-fullscreen/beat-freeze-cut",
    "text-fullscreen/news-ticker",
)

DELETE_INTENT_IDS = (
    "geo-generic",
    "geo-world-map",
    "geo-north-korea",
    "geo-flight",
    "browser-ai-chat",
    "browser-chatgpt-exchange",
    "browser-claude-exchange",
    "text-beat-freeze",
    "dataviz-star-rating",
    "finance-money-count",
    "stat-progress-goals",
)


class TestDeleteList:
    """MUST-013: §9 DELETE id нет в индексе picker и живом каталоге."""

    def test_deleted_templates_absent_from_catalog_and_picker_index(self, picker):
        catalog_ids = {t.id for t in picker.catalog.all()}
        index_ids = {t.id for t in picker.catalog.all()}
        for tid in DELETE_TEMPLATE_IDS:
            assert tid not in catalog_ids, tid
            assert picker.catalog.by_id(tid) is None
            assert tid not in index_ids

    def test_deleted_intents_absent_from_scenario_index(self, picker):
        intent_ids = {it.id for it in picker.index.intents}
        for iid in DELETE_INTENT_IDS:
            assert iid not in intent_ids, iid
        for intent in picker.index.intents:
            leftover = set(intent.templates) & set(DELETE_TEMPLATE_IDS)
            assert not leftover, (intent.id, leftover)

    def test_deleted_json_files_gone(self):
        root = Path(__file__).resolve().parents[1] / "templates"
        for tid in DELETE_TEMPLATE_IDS:
            cat, name = tid.split("/", 1)
            path = root / cat / f"{name}.json"
            assert not path.exists(), path


class TestTaxonomyMust012:
    """MUST-012: rarity / topics / requires / forbids / cooldown / brand_ok."""

    def test_every_active_template_has_taxonomy(self, picker):
        from src.lib.templates import ALLOWED_RARITY, normalize_rarity

        missing = []
        for t in picker.catalog.templates:
            if not t.is_active:
                continue
            rarity = normalize_rarity(t.rarity or t.frequency)
            ok = (
                rarity in ALLOWED_RARITY
                and isinstance(t.topics, list) and t.topics
                and isinstance(t.requires, list)
                and isinstance(t.forbids, list)
                and isinstance(t.cooldown_videos, int)
                and isinstance(t.brand_ok, bool)
            )
            if not ok:
                missing.append(t.id)
        assert missing == []

    def test_requires_unmet_on_empty_text_is_not_picked(self):
        data = {
            "templates": [
                {
                    "id": "data-viz/needs-number", "name": "needs-number",
                    "category": "data-viz", "title": "n",
                    "duration_range": [1.0, 5.0], "params": {}, "tags": [],
                    "renderer": "dataviz", "frequency": "variant",
                    "rarity": "variant", "topics": ["data-viz"],
                    "needs": ["number"], "requires": ["number"],
                    "forbids": [], "cooldown_videos": 1, "brand_ok": True,
                    "status": "active",
                },
                {
                    "id": "data-viz/needless", "name": "needless",
                    "category": "data-viz", "title": "n",
                    "duration_range": [1.0, 5.0], "params": {}, "tags": [],
                    "renderer": "dataviz", "frequency": "variant",
                    "rarity": "variant", "topics": ["data-viz"],
                    "needs": [], "requires": [],
                    "forbids": [], "cooldown_videos": 1, "brand_ok": True,
                    "status": "active",
                },
            ]
        }
        cat = TemplateCatalog(Path("unused.json"), data)
        picked = cat.pick("data-viz", duration=2.0, traits=set(), seed=0)
        assert picked.id == "data-viz/needless"

    def test_two_videos_do_not_reuse_signature_when_cooldown(self):
        data = {
            "templates": [
                {
                    "id": "text-fullscreen/sig-a", "name": "sig-a",
                    "category": "text-fullscreen", "title": "a",
                    "duration_range": [1.0, 5.0], "params": {}, "tags": [],
                    "renderer": "x", "frequency": "signature",
                    "rarity": "signature", "topics": ["text-fullscreen"],
                    "requires": [], "forbids": [], "cooldown_videos": 1,
                    "brand_ok": True, "status": "active",
                },
                {
                    "id": "text-fullscreen/sig-b", "name": "sig-b",
                    "category": "text-fullscreen", "title": "b",
                    "duration_range": [1.0, 5.0], "params": {}, "tags": [],
                    "renderer": "x", "frequency": "signature",
                    "rarity": "signature", "topics": ["text-fullscreen"],
                    "requires": [], "forbids": [], "cooldown_videos": 1,
                    "brand_ok": True, "status": "active",
                },
            ]
        }
        cat = TemplateCatalog(Path("unused.json"), data)
        first = cat.pick("text-fullscreen", duration=2.0, seed=0)
        cat.mark_used([first.id], "video_01")
        second = cat.pick(
            "text-fullscreen", duration=2.0, seed=0,
            recent_videos=["video_01"],
        )
        assert first.id != second.id

    def test_brand_ok_false_is_never_picked(self):
        data = {
            "templates": [
                {
                    "id": "kenburns/ok", "name": "ok",
                    "category": "kenburns", "title": "ok",
                    "duration_range": [1.0, 5.0], "params": {}, "tags": [],
                    "renderer": "kb", "frequency": "signature",
                    "rarity": "signature", "topics": ["kenburns"],
                    "requires": [], "forbids": [], "cooldown_videos": 3,
                    "brand_ok": True, "status": "active",
                },
                {
                    "id": "kenburns/off", "name": "off",
                    "category": "kenburns", "title": "off",
                    "duration_range": [1.0, 5.0], "params": {}, "tags": [],
                    "renderer": "kb", "frequency": "signature",
                    "rarity": "signature", "topics": ["kenburns"],
                    "requires": [], "forbids": [], "cooldown_videos": 3,
                    "brand_ok": False, "status": "active",
                },
            ]
        }
        cat = TemplateCatalog(Path("unused.json"), data)
        picked = {cat.pick("kenburns", duration=2.0, seed=s).id for s in range(12)}
        assert picked == {"kenburns/ok"}

    def test_brand_ok_false_only_catalog_is_empty_pick(self):
        data = {
            "templates": [
                {
                    "id": "kenburns/off", "name": "off",
                    "category": "kenburns", "title": "off",
                    "duration_range": [1.0, 5.0], "params": {}, "tags": [],
                    "renderer": "kb", "frequency": "signature",
                    "rarity": "signature", "topics": ["kenburns"],
                    "requires": [], "forbids": [], "cooldown_videos": 3,
                    "brand_ok": False, "status": "active",
                },
            ]
        }
        cat = TemplateCatalog(Path("unused.json"), data)
        with pytest.raises(RedshiftError) as exc:
            cat.pick("kenburns", duration=2.0, seed=0)
        assert exc.value.code == "TEMPLATE_CATEGORY_EMPTY"
