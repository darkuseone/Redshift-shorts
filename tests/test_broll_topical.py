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

    def test_leftover_without_concepts_is_kept(self):
        """English leftover vs Russian VO with no CONCEPTS is not a massacre.

        extra_fits_slot required Latin∩dest; dest was Russian, so P11 emptied
        every leftover slot onto the ladder and died on QC-12.
        """
        slot = _slot(index=5, start=2.0, end=6.0)
        words = [
            {"display": "четверть", "start": 2.1, "end": 2.4},
            {"display": "века", "start": 2.5, "end": 2.8},
            {"display": "никто", "start": 2.9, "end": 3.2},
            {"display": "не", "start": 3.3, "end": 3.4},
            {"display": "брал.", "start": 3.5, "end": 3.9},
        ]
        asset = {
            "decision": "accept_stock_leftover",
            "query": "hands typing keyboard code editor",
        }
        assert not leftover_stock_off_topic(asset, slot, {}, words=words)

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

    def test_airplane_leftover_fits_navier_speech_without_krylo(self):
        """CONCEPTS[навье] is water/turbulence — wing/pipes still belong here."""
        slot = _slot(index=13, start=38.8, end=41.6)
        words = [
            {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
            {"display": "Страшное", "start": 40.8, "end": 41.3},
        ]
        assert leftover_query_fits_slot(
            "airplane wing in flight clouds", slot, {}, words)
        assert leftover_query_fits_slot(
            "industrial pipes water plant", slot, {}, words)
        assert leftover_query_fits_slot(
            "blood cells flowing microscope", slot, {}, words)
        assert leftover_query_fits_slot(
            "weather radar storm satellite", slot, {}, words)
        assert not leftover_query_fits_slot(
            "hands typing keyboard code editor", slot, {}, words)
        assert not leftover_query_fits_slot(
            "sky view airplane plane windows seat", slot, {}, words)
        assert leftover_query_fits_slot(
            "airplane wing in flight clouds", slot, {}, words)

    def test_zakryli_is_not_a_wing_fluid_window(self):
        from src.lib.query import classify_spoken_window
        assert classify_spoken_window("пункт они не закрыли. Клей") == "open"
        assert classify_spoken_window(
            "уравнения Навье-Стокса. Страшное") == "fluid"
        assert classify_spoken_window("крыло самолёта, ток крови.") == "fluid"
        assert classify_spoken_window(
            "Сама Астра доказательство не искала.") == "lean"
        assert classify_spoken_window(
            "Только приз Клея — за уравнения") == "paper"


class TestSpokenWindowBrief:
    def test_navier_window_drops_keyboard_queries(self):
        from src.lib.query import (
            brief_deny_reason, brief_reject_reason, classify_spoken_window,
            queries_for_spoken_window, slot_visual_brief,
        )
        spoken = "Называются уравнения Навье-Стокса. Страшное имя."
        assert classify_spoken_window(spoken) == "fluid"
        kept = queries_for_spoken_window(
            ["code editor proof lean theorem",
             "industrial pipes water plant",
             "hands typing keyboard code editor"],
            spoken)
        assert all("keyboard" not in q.lower() for q in kept)
        assert all("lean" not in q.lower() for q in kept)
        assert any("pipes" in q.lower() or "water" in q.lower() for q in kept)
        slot = _slot(index=13, start=38.8, end=41.6,
                     queries=["code editor proof lean theorem"])
        words = [
            {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
            {"display": "Страшное", "start": 40.8, "end": 41.3},
        ]
        brief = slot_visual_brief(slot, {}, words)
        assert brief["kind"] == "fluid"
        assert brief_deny_reason(brief, "mechanical keyboard hands typing")
        assert not brief_deny_reason(brief, "industrial pipes water plant")
        assert brief_reject_reason(brief, "mk-line-graph dataviz", rung="dataviz")
        assert brief_reject_reason(
            brief, "browser-ui/browser-scroll", rung="source",
            template="browser-ui/browser-scroll")
        assert not brief_reject_reason(
            brief, "industrial pipes water plant", rung="parallax")

    def test_openai_paper_window_denies_keyboard_leftover(self):
        slot = _slot(index=5, start=16.2, end=18.8)
        words = [
            {"display": "OpenAI", "start": 16.27, "end": 16.72},
            {"display": "выкладывает", "start": 17.04, "end": 17.49},
            {"display": "работу.", "start": 17.71, "end": 18.16},
        ]
        asset = {
            "decision": "accept_stock_leftover",
            "query": "hands typing keyboard code editor",
            "page_url": "https://www.pexels.com/video/hands-typing-on-laptop-keyboard-12893579/",
        }
        assert leftover_stock_off_topic(asset, slot, {}, words=words)

    def test_prior_accept_keyboard_not_kept_on_navier(self):
        from src.p8_broll_judge.judge import prior_accepted_ok
        slot = _slot(index=13, start=38.8, end=41.6)
        words = [{"display": "Навье-Стокса.", "start": 39.5, "end": 40.0}]
        entry = {
            "asset_id": "pexels_v32259631",
            "decision": "accept_stock_leftover",
            "query": "hands typing keyboard code editor",
            "page_url": "https://www.pexels.com/video/black-mechanical-keyboard-32259631/",
            "score": 0.4,
        }
        assert not prior_accepted_ok(entry, slot, {}, words, set())

    def test_prior_accept_kept_when_still_on_topic(self):
        from src.p8_broll_judge.judge import prior_accepted_ok
        slot = _slot(index=10, start=28.5, end=31.3)
        words = [{"display": "самолёт", "start": 29.0, "end": 29.4}]
        entry = {
            "asset_id": "pexels_v16865644",
            "decision": "accept",
            "query": "airplane wing in flight clouds",
            "tags": ["airplane", "clouds"],
            "page_url": "https://www.pexels.com/video/a-view-of-the-clouds-from-an-airplane-16865644/",
            "score": 0.86,
        }
        assert prior_accepted_ok(entry, slot, {}, words, set())


    def test_prior_accept_airplane_dropped_on_astra(self):
        from src.p8_broll_judge.judge import prior_accepted_ok
        slot = _slot(index=10, start=28.6, end=31.4)
        words = [
            {"display": "Сама", "start": 28.6, "end": 28.9},
            {"display": "Астра", "start": 28.9, "end": 29.3},
            {"display": "доказательство", "start": 29.4, "end": 29.8},
        ]
        entry = {
            "asset_id": "pexels_v16865644",
            "decision": "accept",
            "query": "airplane wing in flight clouds",
            "tags": ["airplane", "clouds"],
            "page_url": "https://www.pexels.com/video/a-view-of-the-clouds-from-an-airplane-16865644/",
            "score": 0.86,
        }
        assert not prior_accepted_ok(entry, slot, {}, words, set())


def test_append_dataviz_skips_fluid_spoken_window():
    """0049 41.02 put mk-line-graph on «Навье-Стокса» because b4 has numbers."""
    from src.p11_assemble.assemble import VisualBudget, _append_dataviz

    plan = {
        "duration_sec": 50.0,
        "cta_window": [48.0, 50.0],
        "slots": [{
            "index": 13, "start": 38.885, "end": 41.565, "duration": 2.68,
            "kind": "footage", "role": "develop", "block_id": "b4",
        }],
        "blocks": [{
            "id": "b4",
            "text": "Семнадцать часов. Называются уравнения Навье-Стокса.",
        }],
    }
    words = [
        {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
        {"display": "Страшное", "start": 40.8, "end": 41.3},
    ]
    overlays: list = []
    _append_dataviz(
        plan, overlays, catalog=None, variant="A", seed=1,
        recent_videos=[], used=[], picker=None,
        budget=VisualBudget(), words=words)
    assert overlays == []


def test_append_dataviz_skips_fluid_majority_queries_on_open_speech():
    """0049 29.30: airplane keep-prior + mk-line-graph blew QC-30."""
    from src.p11_assemble.assemble import VisualBudget, _append_dataviz

    plan = {
        "duration_sec": 50.0,
        "cta_window": [48.0, 50.0],
        "slots": [{
            "index": 10, "start": 28.6, "end": 31.4, "duration": 2.8,
            "kind": "footage", "role": "develop", "block_id": "b4",
            "queries": [
                "weather radar storm satellite",
                "airplane wing in flight clouds",
                "industrial pipes water plant",
                "blood flow medical animation microscope",
                "code editor proof lean theorem",
            ],
        }],
        "blocks": [{
            "id": "b4",
            "text": "Сама Астра доказательство не искала. Семнадцать часов.",
        }],
    }
    words = [
        {"display": "Сама", "start": 28.6, "end": 28.9},
        {"display": "Астра", "start": 28.9, "end": 29.3},
        {"display": "доказательство", "start": 29.4, "end": 29.8},
    ]
    overlays: list = []
    _append_dataviz(
        plan, overlays, catalog=None, variant="A", seed=1,
        recent_videos=[], used=[], picker=None,
        budget=VisualBudget(), words=words)
    assert overlays == []


def test_cheap_critic_fails_keyboard_on_navier_even_if_block_has_lean():
    """P8 must see the spoken window, not b4's Lean+fluids mix."""
    from src.lib.config import load_config
    from src.lib.query import slot_visual_brief
    from src.p8_broll_judge.judge import cheap_reject_reason

    slot = _slot(index=13, start=38.8, end=41.6)
    plan = {"blocks": [{
        "id": "b1",
        "text": "Проверка в Lean. Называются уравнения Навье-Стокса.",
    }]}
    words = [
        {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
        {"display": "Страшное", "start": 40.8, "end": 41.3},
    ]
    brief = slot_visual_brief(slot, plan, words)
    assert brief["kind"] == "fluid"
    keyboard = {
        "query": "hands typing keyboard code editor",
        "tags": ["keyboard", "tech", "code"],
        "page_url": "https://www.pexels.com/video/black-mechanical-keyboard-32259631/",
        "asset_id": "pexels_v32259631",
    }
    dataviz = {
        "query": "data visualization line graph dashboard",
        "tags": ["dataviz", "chart"],
        "page_url": "https://example.com/mk-line-graph",
    }
    water = {
        "query": "industrial pipes water plant",
        "tags": ["water", "pipes"],
        "page_url": "https://www.pexels.com/video/water-flowing-through-a-discharge-pipe-10884417/",
    }
    cfg = load_config()
    assert cheap_reject_reason(keyboard, cfg=cfg, brief=brief)
    assert cheap_reject_reason(dataviz, cfg=cfg, brief=brief)
    assert cheap_reject_reason(water, cfg=cfg, brief=brief) is None


def test_fluid_empty_slot_ladder_is_not_dataviz():
    """Empty pool + spoken «Навье-Стокса» must not close with the ladder chart."""
    from src.p11_assemble.assemble import VisualBudget, _close_empty_slot

    slot = {
        "index": 13, "start": 38.885, "end": 41.565, "duration": 2.68,
        "kind": "footage", "role": "develop", "block_id": "b4", "beat": "",
    }
    block = {
        "id": "b4",
        "text": "Семнадцать часов. Называются уравнения Навье-Стокса. Страшное имя.",
        "emphasis_word": "семнадцать",
    }
    words = [
        {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
        {"display": "Страшное", "start": 40.8, "end": 41.3},
    ]
    rung, hero, overlay = _close_empty_slot(
        slot, block,
        budget=VisualBudget(),
        picker=None, catalog=None,
        plan={"duration_sec": 70, "title": "", "sources": [
            {"domain": "openai.com", "title": "Astra", "snippet": "Lean"}]},
        variant="A", seed=1, recent_videos=[], used_templates=[],
        brand_icons=None, words=words, plate_src=None,
        traits={"number", "brand"}, bg_file=None)
    assert rung != "dataviz"
    assert rung != "source"
    assert overlay is None or overlay.get("type") not in {"dataviz", "source_card"}
    assert hero is None


def test_window_traits_ignore_semnadtsat_outside_the_spoken_window():
    from src.lib.meaning import window_traits
    from src.lib.query import spoken_slot_text

    slot = _slot(index=13, start=38.8, end=41.6)
    words = [
        {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
        {"display": "Страшное", "start": 40.8, "end": 41.3},
    ]
    spoken = spoken_slot_text(slot, words)
    traits = window_traits(spoken)
    assert "number" not in traits


def test_press_card_stays_off_navier_speech():
    from src.lib.pin_match import pin_slot_prefer_key

    ns = {"index": 13, "role": "develop", "asset_role": "broll",
          "start": 38.8, "end": 41.6}
    article = {"index": 5, "role": "evidence", "asset_role": "evidence",
               "start": 16.2, "end": 18.8}
    pins = ["press_c8e1aa428b", "pexels_v10884417"]
    on_ns, _ = pin_slot_prefer_key(
        "press_c8e1aa428b", ns, pins,
        words=[{"display": "Навье-Стокса.", "start": 39.5, "end": 40.0}])
    on_article, _ = pin_slot_prefer_key(
        "press_c8e1aa428b", article, pins,
        words=[{"display": "OpenAI", "start": 16.3, "end": 16.7},
               {"display": "выкладывает", "start": 17.0, "end": 17.5}])
    water_ns, _ = pin_slot_prefer_key(
        "pexels_v10884417", ns, pins,
        words=[{"display": "Навье-Стокса.", "start": 39.5, "end": 40.0}])
    assert on_ns > 0
    assert on_article < 0
    assert water_ns < 0


def test_cabin_url_not_laundered_by_wing_query():
    """34587674751: P7 query «airplane wing» parked cabin pexels_v19004433 on NS."""
    from src.lib.query import brief_reject_reason, slot_visual_brief

    slot = _slot(index=13, start=38.8, end=41.6)
    words = [
        {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
        {"display": "Страшное", "start": 40.8, "end": 41.3},
    ]
    brief = slot_visual_brief(slot, {}, words)
    hay = " ".join([
        "airplane wing in flight clouds",
        "https://www.pexels.com/video/sky-view-airplane-plane-windows-windows-seat-coolplaces4k-19004433/",
        "pexels_v19004433",
    ])
    assert brief["kind"] == "fluid"
    assert brief_reject_reason(brief, hay)


def test_astra_window_rejects_airplane_brief():
    from src.lib.query import brief_reject_reason, slot_visual_brief

    slot = _slot(index=10, start=28.6, end=31.4)
    words = [
        {"display": "Сама", "start": 28.6, "end": 28.9},
        {"display": "Астра", "start": 28.9, "end": 29.3},
        {"display": "доказательство", "start": 29.4, "end": 29.8},
    ]
    brief = slot_visual_brief(slot, {}, words)
    assert brief["kind"] == "lean"
    assert brief_reject_reason(
        brief, "airplane wing in flight clouds pexels_v16865644")
    assert not brief_reject_reason(
        brief, "code editor formal proof theorem prover")


def test_clay_paper_window_rejects_html_code():
    from src.lib.query import brief_reject_reason, slot_visual_brief

    slot = _slot(index=19, start=52.7, end=56.2, kind="avatar")
    words = [
        {"display": "Только", "start": 52.70, "end": 53.02},
        {"display": "приз", "start": 53.06, "end": 53.30},
        {"display": "Клея", "start": 53.30, "end": 53.66},
        {"display": "за", "start": 53.74, "end": 53.84},
        {"display": "уравнения", "start": 53.84, "end": 54.29},
    ]
    brief = slot_visual_brief(slot, {}, words)
    assert brief["kind"] == "paper"
    hay = (
        "https://www.pexels.com/video/"
        "colorful-html-code-on-computer-monitor-34459460/"
    )
    assert brief_reject_reason(brief, hay)


def test_query_mismatch_marks_regular_accept_off_topic():
    """Empty-concept speech used to score 1.0 and keep any tagged clip."""
    slot = _slot(index=10, start=28.6, end=31.4)
    words = [
        {"display": "Сама", "start": 28.6, "end": 28.9},
        {"display": "Астра", "start": 28.9, "end": 29.3},
        {"display": "доказательство", "start": 29.4, "end": 29.8},
    ]
    assert not leftover_query_fits_slot(
        "airplane wing in flight clouds", slot, {}, words)
    assert leftover_query_fits_slot(
        "code editor formal proof theorem prover", slot, {}, words)


