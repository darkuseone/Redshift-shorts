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
            "лучший чат-бот для работы",
            category="browser-ui",
            variant="A",
        )
        assert any(it.id == "browser-ai-chat" for it in intents)

    def test_regex_pattern_matching(self, picker):
        # text-beat-freeze has pattern (drop|freeze|beat|hard*cut|...)
        intents = picker.index.detect_intents(
            "мощный бит и дроп",
            category="text-fullscreen",
            variant="A",
        )
        assert any(it.id == "text-beat-freeze" for it in intents)

    def test_signals_any_matching(self, picker):
        # dataviz-star-rating has signals_any: ['rating_like']
        intents = picker.index.detect_intents(
            "нейтральный текст",
            category="data-viz",
            variant="A",
            signals=frozenset(["rating_like"]),
        )
        assert any(it.id == "dataviz-star-rating" for it in intents)

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
        # Text with both diff and beat markers: text-beat-freeze (27) > text-code-diff (24)
        diff_text = "\n---\n+++ new\n- дроп\n+ бит\n"
        intents = picker.index.detect_intents(
            diff_text,
            category="text-fullscreen",
            variant="A",
        )
        fired_ids = [it.id for it in intents]
        assert fired_ids.index("text-beat-freeze") < fired_ids.index("text-code-diff")

    def test_module_level_detect_intents(self, picker):
        intents1 = detect_intents(picker.index, "123", category="text-fullscreen", variant="A")
        intents2 = detect_intents("123", category="text-fullscreen", variant="A", index=picker.index)
        assert intents1 == intents2
        assert any(it.id == "text-number-slam" for it in intents1)


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

        # text-fullscreen winning direction hierarchy
        assert (
            by_id["text-beat-freeze"]
            > by_id["text-terminal-shell"]
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
            prefer_head=["text-fullscreen/beat-freeze-cut"],
            prefer_base=["text-fullscreen/dark-plus"],
        )
        assert "head" in trace.channels
        assert "specific" in trace.channels
        assert "base" in trace.channels
        assert "default" in trace.channels
        assert "generic" in trace.channels

        assert trace.channels["head"] == ("text-fullscreen/beat-freeze-cut",)
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
        # text-fullscreen variant A default intent has exactly 20 templates
        _, trace_text = picker.pick("text-fullscreen", blob="нейтральный текст", variant="A")
        assert len(trace_text.fallback) == 20
        assert trace_text.fallback[0] == "text-fullscreen/beat-freeze-cut"
        assert trace_text.fallback[-1] == "text-fullscreen/number-slam-card"

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
            blob=build_blob("рейс Нью-Йорк — Париж"),
            variant="A",
        )
        assert trace.won_at == 0
        assert trace.tie_class == 1


class TestReplacesDefault:
    def test_code_plus_digit_variant_a(self, picker):
        # Code + digit: specific walk has code templates then number-slam templates
        # fallback is replaced by text-number-slam (2 templates)
        text = "def calculate_price(): return 42"
        t, trace = picker.pick("text-fullscreen", blob=text, variant="A")
        assert trace.replaced_default_by == "text-number-slam"
        assert trace.fallback == (
            "text-fullscreen/number-slam-card",
            "text-fullscreen/kinetic-stack",
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
        assert trace.fallback == (
            "text-fullscreen/stack-3lines",
            "text-fullscreen/fact-card",
        )

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
        # geo-flight templates: [nyc-paris-flight, world-map]
        t1, trace1 = picker.pick("data-viz", blob=build_blob("рейс Нью-Йорк — Париж"), variant="A")
        assert t1.id == "data-viz/nyc-paris-flight"
        assert trace1.won_at == 0

        # Exclude first template in walk
        t2, trace2 = picker.pick(
            "data-viz",
            blob=build_blob("рейс Нью-Йорк — Париж"),
            variant="A",
            exclude=["data-viz/nyc-paris-flight"],
        )
        assert t2.id == "data-viz/world-map"
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

class TestReachability:
    def test_all_manifest_templates_present_in_channels_for_live_categories(self, picker):
        live_categories = [
            cat for cat in picker.catalog.counts().keys()
            if cat not in picker.index.unreachable_categories
        ]
        assert len(live_categories) == 10

        manifest_by_cat = {cat: set() for cat in live_categories}
        for t in picker.catalog.all():
            if t.category in live_categories:
                manifest_by_cat[t.category].add(t.id)

        reached_by_cat = {cat: set() for cat in live_categories}
        for intent in picker.index.intents:
            for cat in intent.categories:
                if cat in live_categories:
                    for v in intent.variants:
                        blob = intent.keywords[0] if intent.keywords else ""
                        signals = intent.needs | intent.signals_any
                        _, trace = picker.pick(cat, blob=blob, signals=signals, variant=v)
                        for ch_templates in trace.channels.values():
                            reached_by_cat[cat].update(ch_templates)

        for cat in live_categories:
            missing = manifest_by_cat[cat] - reached_by_cat[cat]
            assert not missing, f"Category {cat} has unreached templates in channels: {missing}"

    def test_unreachable_categories_have_no_live_call_sites(self, picker):
        assert set(picker.index.unreachable_categories) == {"intro-hooks", "parallax"}


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
        # 'рейтинг' -> star-rating-fill
        t_rate, trace_rate = picker.pick("data-viz", blob=build_blob("рейтинг доверия"), variant="A")
        assert any(fid == "dataviz-star-rating" for fid, _ in trace_rate.fired)
        assert t_rate.id == "data-viz/star-rating-fill"

        # 'прогресс' -> mk-progress-stat
        t_prog, trace_prog = picker.pick("data-viz", blob=build_blob("прогресс переговоров"), variant="A")
        assert any(fid == "stat-progress-goals" for fid, _ in trace_prog.fired)
        assert t_prog.id == "data-viz/mk-progress-stat"


class TestStability:
    def test_last_used_in_does_not_break_guided_choice(self, picker):
        # Walk hit is resilient to rotation history:
        # even if nyc-paris-flight was used recently, walk still returns it because [tid] has explicit=0
        target = picker.catalog.by_id("data-viz/nyc-paris-flight")
        target.last_used_in.extend(["video_01", "video_02", "video_03", "video_04"])

        t, trace = picker.pick(
            "data-viz",
            blob=build_blob("рейс Нью-Йорк — Париж"),
            variant="A",
            recent_videos=["video_04"],
        )
        assert t.id == "data-viz/nyc-paris-flight"
        assert trace.won_at == 0
        assert trace.tie_class == 1


class TestCliExplain:
    def test_cli_templates_explain_guided_hit(self, capsys):
        from src.cli import main

        ret = main(["templates", "--explain", "рейс Нью-Йорк — Париж", "--category", "data-viz"])
        assert ret == 0

        captured = capsys.readouterr()
        out = captured.out

        # Fired intents with weight
        assert "geo-flight (29)" in out

        # All 5 channels
        assert "head:" in out
        assert "specific:" in out
        assert "base:" in out
        assert "default:" in out
        assert "generic:" in out

        # Walk with winner
        assert "walk[0] = data-viz/nyc-paris-flight" in out
        assert "data-viz/nyc-paris-flight" in out

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
        assert data["count"] == 28
        assert "data-viz/nyc-paris-flight" in data["templates"]

