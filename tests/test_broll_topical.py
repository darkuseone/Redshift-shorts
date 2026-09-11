"""Материал обязан быть про то, что звучит (§9.1-9.3).

Три отдельные поломки, которые вместе дали отзыв критика «пастельные кубики
про LLM», «фиолетовые бактерии», «ядовитая жёлто-зелёная сетка»:

1. Пять универсальных запросов подмешивались **в каждый слот каждого ролика**
   независимо от темы — ролик про квантовый чип честно получал галактику.
2. Тематического счёта не было вовсе: зрение отвечало «что изображено» и
   отвечало честно, а вопрос «про то ли это» никто не задавал.
3. `watermark` из вердикта зрения не использовался в отборе никак, и клип с
   вшитым `PEXELS / GOOGLE DEEPMIND` уехал в готовый ролик через hard-prefer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.lib.query import (
    CONCEPTS, allow_generic_pad, leftover_dest_tokens, leftover_query_fits_slot,
    slot_topical_text, topical_match_score,
)
from src.p7_broll_search.search import SPACE_NEWS_PAD, pad_slot_queries
from src.p8_broll_judge.judge import watermark_reject_reason
from src.p11_assemble.assemble import leftover_stock_off_topic

REPO_ROOT = Path(__file__).resolve().parents[1]


def _slot(**over):
    slot = {"index": 0, "block_id": "b1", "role": "body", "kind": "footage",
            "visual_intent": "", "queries": []}
    slot.update(over)
    return slot


class TestTheBlindPadIsGated:

    def test_a_topical_slot_gets_no_space_pad(self):
        """Ролик про квантовый чип не должен получать галактику."""
        plan = {"category": "ai", "blocks": [
            {"id": "b1", "text": "Внутри процессора сто пять кубитов"}]}
        assert not allow_generic_pad(_slot(), plan, category="ai")

    def test_a_slot_about_space_still_gets_it(self):
        """Пад не удалён, а огорожен: слоту про космос он по делу."""
        plan = {"category": "space", "blocks": [
            {"id": "b1", "text": "Телескоп смотрит в глубокий космос"}]}
        assert allow_generic_pad(
            _slot(visual_intent="deep space stars"), plan,
            intent_kind="space", category="space")

    def test_a_slot_without_concepts_gets_it(self):
        """Показывать нечего конкретного — общий кадр не спорит с речью."""
        plan = {"category": "ai", "blocks": [
            {"id": "b1", "text": "Мы попробовали и ничего не вышло"}]}
        assert allow_generic_pad(_slot(), plan, category="ai")

    def test_the_reference_script_never_gets_galaxy_nebula(self):
        """DoD §9.1 на живом плане 0042."""
        plan_path = REPO_ROOT / "work" / "redshift_0042" / "cut_plan.json"
        if not plan_path.exists():
            pytest.skip("нет локального плана 0042")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for slot in plan["slots"]:
            padded = pad_slot_queries(
                ["quantum processor macro"], queries_per_slot=5,
                category=str(plan.get("category") or ""), slot=slot, plan=plan)
            assert "galaxy nebula" not in padded, slot["index"]

    def test_the_gate_lives_in_one_place(self):
        """Пад жил в двух местах, и починка одного ничего не меняла."""
        search = (REPO_ROOT / "src" / "p7_broll_search" / "search.py") \
            .read_text(encoding="utf-8")
        assert "allow_generic_pad" in search
        assert len(SPACE_NEWS_PAD) == 5


class TestTopicalMatchScore:

    QUBIT = "Внутри процессора сто пять кубитов"

    def test_matching_material_scores_high(self):
        assert topical_match_score({"quantum", "chip", "macro"}, self.QUBIT) >= 0.5

    def test_a_galaxy_scores_zero_for_a_chip_block(self):
        """Зрение назвало бы это «светящимися сферами» — и было бы право."""
        assert topical_match_score({"galaxy", "nebula", "stars"}, self.QUBIT) == 0.0

    def test_the_pastel_cubes_of_0042_are_rejected(self):
        assert topical_match_score({"pastel", "cubes", "llm"}, self.QUBIT) < 0.35

    def test_a_block_without_concepts_demands_nothing(self):
        """Реплика без предметных понятий не может требовать от кадра ничего."""
        assert topical_match_score({"galaxy"}, "Мы упёрлись в это") == 1.0

    def test_material_without_tags_scores_zero(self):
        assert topical_match_score(set(), self.QUBIT) == 0.0

    def test_the_score_is_bounded(self):
        for tags in ({"quantum"}, {"quantum", "chip", "macro", "silicon", "wafer"}):
            assert 0.0 <= topical_match_score(tags, self.QUBIT) <= 1.0

    def test_all_three_call_sites_use_it(self):
        """§9.2: ранжирование, судья и вход в лестницу."""
        for rel in (("src", "p8_broll_judge", "judge.py"),
                    ("src", "p11_assemble", "assemble.py")):
            source = REPO_ROOT.joinpath(*rel).read_text(encoding="utf-8")
            assert "topical_match_score" in source, rel


class TestAStockWatermarkNeverReachesTheFrame:

    def test_a_watermarked_verdict_is_rejected(self):
        assert watermark_reject_reason({"watermark": True})

    def test_a_clean_verdict_passes(self):
        assert not watermark_reject_reason({"watermark": False})
        assert not watermark_reject_reason({})

    def test_the_index_flag_counts_too(self):
        assert watermark_reject_reason({}, {"vision": {"watermark": True}})

    def test_the_pin_path_is_gated_as_well(self):
        """Пин — «возьми вот этот кадр», а не «возьми его любой ценой»."""
        judge = (REPO_ROOT / "src" / "p8_broll_judge" / "judge.py") \
            .read_text(encoding="utf-8")
        prefer = judge[judge.index("prefer_gated = sorted("):
                       judge.index('entry["decision"] = "accept_prefer"')]
        assert "watermark_reject_reason" in prefer, \
            "hard-prefer пин снова проходит мимо проверки на вшитую подпись"


class TestTheConceptsRevision:

    @pytest.mark.parametrize("trigger,expected", [
        ("процессор", "cpu die macro"),
        ("квант", "dilution refrigerator gold"),
        ("ошибк", "error correction diagram"),
    ])
    def test_the_table_from_the_plan_landed(self, trigger, expected):
        assert expected in CONCEPTS[trigger], CONCEPTS[trigger]

    def test_the_office_desk_queries_are_gone(self):
        """`processor macro shot` тянул со стока столы и ноутбуки."""
        assert "processor macro shot" not in CONCEPTS["процессор"]
        assert "computer hardware closeup" not in CONCEPTS["процессор"]

    def test_navier_stokes_block_has_fluid_concepts(self):
        assert "weather radar storm satellite" in CONCEPTS["погод"]
        text = "Называются уравнения Навье-Стокса. Погода, крыло самолёта, ток крови."
        assert topical_match_score({"datacenter", "server", "racks"}, text) < 0.35
        assert topical_match_score({"weather", "radar", "storm"}, text) >= 0.35


class TestLeftoverQueryGate:

    def test_same_topic_leftover_fits(self):
        slot = _slot(visual_intent="quantum laboratory cryostat",
                     queries=["quantum processor macro chip"])
        assert leftover_query_fits_slot("quantum processor macro", slot, {})

    def test_datacenter_does_not_fit_fluids(self):
        slot = _slot(visual_intent="weather radar airplane wing blood",
                     queries=["weather radar storm satellite"])
        assert not leftover_query_fits_slot("gpu cluster server aisle datacenter",
                                            slot, {})

    def test_p11_drops_cross_slot_leftover_without_from_field(self):
        slot = _slot(index=12, visual_intent="weather radar airplane wing blood",
                     queries=["weather radar storm satellite"])
        asset = {
            "decision": "accept_stock_leftover",
            "query": "gpu cluster server aisle datacenter",
        }
        assert leftover_stock_off_topic(asset, slot, {})

    def test_p11_keeps_same_slot_leftover(self):
        slot = _slot(index=5, visual_intent="weather radar airplane wing blood",
                     queries=["weather radar storm satellite"])
        asset = {
            "decision": "accept_stock_leftover",
            "leftover_from_slot": 5,
            "query": "weather radar storm satellite",
        }
        assert not leftover_stock_off_topic(asset, slot, {})

    def test_p11_drops_keyboard_leftover_on_navier_speech(self):
        """Same-slot leftover still dies if this window is fluids, not Lean."""
        slot = _slot(
            index=13, start=38.8, end=41.6,
            visual_intent="код Lean и живая практика",
            queries=["code editor proof lean theorem",
                     "weather radar storm satellite"],
        )
        words = [
            {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
            {"display": "Страшное", "start": 40.8, "end": 41.3},
            {"display": "имя,", "start": 41.5, "end": 41.9},
        ]
        asset = {
            "decision": "accept_stock_leftover",
            "leftover_from_slot": 13,
            "query": "hands typing keyboard code editor",
        }
        assert leftover_stock_off_topic(asset, slot, {}, words=words)

    def test_spoken_window_beats_whole_block_lean_on_tags(self):
        """P11 used the whole b4 text, so keyboard tags passed via Lean."""
        slot = _slot(index=13, start=38.8, end=41.6)
        words = [
            {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
            {"display": "Страшное", "start": 40.8, "end": 41.3},
            {"display": "имя,", "start": 41.5, "end": 41.9},
        ]
        tags = {"keyboard", "office", "typing", "code", "editor", "computer"}
        block = ("Сама Астра переложила его в Lean. "
                 "Называются уравнения Навье-Стокса. Страшное имя.")
        assert topical_match_score(tags, block) >= 0.35
        spoken = slot_topical_text(slot, {}, words)
        assert topical_match_score(tags, spoken) < 0.35

    def test_leftover_dest_ignores_mixed_slot_queries_when_speech_covers(self):
        slot = _slot(
            index=13, start=38.8, end=41.6,
            visual_intent="код Lean и живая практика",
            queries=["code editor proof lean theorem",
                     "weather radar storm satellite"],
        )
        words = [
            {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
            {"display": "Страшное", "start": 40.8, "end": 41.3},
        ]
        tokens = leftover_dest_tokens(slot, {}, words)
        assert "editor" not in tokens
        assert "lean" not in {t.lower() for t in tokens}
        assert "navier" in tokens or "fluid" in tokens or "stokes" in tokens
