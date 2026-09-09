"""Лестница закрытия кадра: пустой слот получает приём, а не надпись (§7.2).

На эталонном 0042 сток закрыл шесть кадров из двадцати. Оставшиеся
четырнадцать прошли через развилку из двух веток — «полноэкранный текст, пока
не кончился потолок» и «голая плита» — и дали четырнадцать надписей подряд.
Критик назвал это «хаотичным слайд-шоу из текста» и поставил `visual 2/10`
при девятнадцати пройденных QC: ни один из них не смотрит, есть ли в кадре
хоть что-нибудь кроме букв.

Здесь проверяется ровно тот случай: четырнадцать слотов без материала на
входе в `build_variant`. Тест намеренно идёт через настоящую сборку, а не
через `_close_empty_slot` напрямую — сама лестница ничего не гарантирует,
пока её вызывает старая развилка, и прошлый заход на этот же дефект уже
показал, что охранный тест мимо реального пути кода стоит ровно ничего.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from src.lib.cache import StepCache
from src.lib.costs import CostLedger
from src.lib.storage import build_storage
from src.lib.templates import TemplateCatalog
from src.p11_assemble.assemble import VisualBudget, build_variant
from src.pipeline import RunContext

REPO_ROOT = Path(__file__).resolve().parents[1]

# Четырнадцать блоков ровно того состава, что даёт живой сценарий канала:
# часть с числом, часть с цитатой и брендом, часть — просто утверждение.
# Ступень выбирается тем, чем блок её оправдывает, поэтому состав блоков
# и есть содержание теста.
BLOCKS = [
    {"id": "g01", "role": "body", "mode": "C", "emphasis_word": "кубитов",
     "text": "Внутри процессора сто пять кубитов, и каждый живёт микросекунды."},
    {"id": "g02", "role": "body", "mode": "C", "emphasis_word": "порог",
     "text": "Ошибка падает вдвое на каждом шаге: 3 на 3, потом 5 на 5, потом 7 на 7."},
    {"id": "g03", "role": "body", "mode": "C", "emphasis_word": "Nature",
     "text": "В статье Nature сказано прямо: «логический кубит живёт дольше физического»."},
    {"id": "g04", "role": "body", "mode": "C", "emphasis_word": "Google",
     "text": "Google показал чип Willow на своём сайте и в блоге компании."},
    {"id": "g05", "role": "body", "mode": "C", "emphasis_word": "экране",
     "text": "На экране телефона это выглядит как обычное приложение, цитата из документа."},
    {"id": "g06", "role": "body", "mode": "C", "emphasis_word": "холод",
     "text": "Холод здесь не метафора: криостат держит температуру ниже космоса."},
    {"id": "g07", "role": "body", "mode": "C", "emphasis_word": "проверить",
     "text": "Проверить этот ответ нечем — классический компьютер считал бы его вечность."},
    {"id": "g08", "role": "body", "mode": "C", "emphasis_word": "шум",
     "text": "Шум съедает состояние быстрее, чем алгоритм успевает его прочитать."},
    {"id": "g09", "role": "body", "mode": "C", "emphasis_word": "коррекция",
     "text": "Коррекция ошибок собирает один надёжный кубит из множества шумных."},
    {"id": "g10", "role": "body", "mode": "C", "emphasis_word": "порядок",
     "text": "Порядок величин изменился, и это главное в этой истории."},
    {"id": "g11", "role": "body", "mode": "C", "emphasis_word": "лаборатория",
     "text": "Лаборатория работает без остановки, смены идут круглые сутки."},
    {"id": "g12", "role": "body", "mode": "C", "emphasis_word": "предел",
     "text": "Предел был теоретическим ровно до того дня, пока его не перешли."},
    {"id": "g13", "role": "body", "mode": "C", "emphasis_word": "инженеры",
     "text": "Инженеры называют это порогом, физики — фазовым переходом."},
    {"id": "g14", "role": "cta", "mode": "C", "emphasis_word": "дальше",
     "text": "Дальше будет интереснее, и мы к этому ещё вернёмся."},
]

SOURCES = [
    {
        "title": "Quantum error correction below the surface code threshold",
        "domain": "nature.com",
        "url": "https://www.nature.com/articles/s41586-024-08449-y",
        "show_on_screen": True,
        "screen_template": "browser",
        "snippet": "Логический кубит впервые живёт дольше, чем составляющие его физические кубиты.",
        "highlight_line": "below the surface code threshold",
    },
    {
        "title": "Willow processor announcement",
        "domain": "blog.google",
        "url": "https://blog.google/technology/research/google-willow-quantum-chip/",
        "show_on_screen": True,
        "screen_template": "browser",
        "snippet": "Чип назвали Willow и показали на нём порог коррекции ошибок.",
        "highlight_line": "",
    },
]


def _plan() -> dict:
    slots = []
    for i, block in enumerate(BLOCKS):
        start = round(i * 3.0, 3)
        end = round(start + 3.0, 3)
        slots.append({
            "index": i, "start": start, "end": end, "duration": 3.0,
            "kind": "footage", "block_id": block["id"], "role": block["role"],
            "mode": "C", "visual_intent": "", "queries": [], "content": "",
            "transition_in": "cut", "events": [], "needs_asset": True,
            "asset_role": "broll", "template_hint": "", "meme_emotion": "",
            "reason": "режим C: футаж во весь кадр (§3.5)",
        })
    return {
        "video_id": "redshift_9042", "title": "Порог квантовой коррекции",
        "fps": 30, "duration_sec": float(len(BLOCKS) * 3.0),
        "target_duration_sec": float(len(BLOCKS) * 3.0),
        "music_mood": "tension", "music_tags": [], "category": "science",
        "sources": SOURCES,
        "cta": {"text": "Доверил бы ты такому ответу свои деньги?", "type": "question"},
        "cta_window": [float(len(BLOCKS) * 3.0 - 2.0), float(len(BLOCKS) * 3.0)],
        "hook_window": [0.0, 5.0],
        "avatar_id": "", "stats": {}, "notes": [], "slots": slots,
        "avatar_segments": [], "blocks": BLOCKS,
    }


def _words(plan: dict) -> dict:
    """Разметка речи в том же виде, в каком её кладёт P4.

    Ключи не сокращены до нужных лестнице: `_log_entries` читает `display`
    без запасного варианта, и тест на урезанной разметке проверял бы не
    сборку, а собственную выдумку.
    """
    words = []
    for block, slot in zip(BLOCKS, plan["slots"]):
        parts = block["text"].split()
        step = slot["duration"] / max(len(parts), 1)
        for j, part in enumerate(parts):
            display = part.strip(".,:«»—")
            words.append({
                "index": len(words),
                "display": display,
                "start": round(slot["start"] + j * step, 3),
                "end": round(slot["start"] + (j + 1) * step, 3),
                "block_id": block["id"],
                "role": block["role"],
                "emphasis": display.lower() == block["emphasis_word"].lower(),
                "spoken": [display],
                "source": "test",
            })
    return {"video_id": plan["video_id"], "duration_sec": plan["duration_sec"],
            "stats": {}, "words": words}


@pytest.fixture()
def gap_ctx(cfg, tmp_path):
    """Контекст сборки без единого готового ассета."""
    cfg.set("providers.mode", "mock")
    work = tmp_path / "work"
    work.mkdir(parents=True)
    return RunContext(
        video_id="redshift_9042", cfg=cfg, work_dir=work,
        output_dir=tmp_path / "out", script_path=tmp_path / "s.json",
        cache=StepCache(tmp_path / "cache"),
        costs=CostLedger(video_id="redshift_9042"),
        storage=build_storage(cfg),
    )


@pytest.fixture()
def built(gap_ctx):
    plan = _plan()
    catalog = TemplateCatalog.load(gap_ctx.cfg)
    return build_variant(
        gap_ctx, plan, _words(plan),
        assets={}, prepared={}, catalog=catalog,
        avatar_meta={"segments": []}, sfx_map={},
        variant="B", recent_videos=[])


def _rungs(built: dict) -> Counter:
    return Counter(str(s.get("ladder_rung") or "") for s in built["shots"])


class TestFourteenEmptySlotsAreNotFourteenCaptions:
    """DoD Q1.1: при 14 пустых слотах FS ≤ 4, плит ≤ 2, приёмов ≥ 6."""

    def test_every_slot_still_becomes_a_shot(self, built):
        assert len(built["shots"]) == len(BLOCKS)

    def test_fullscreen_text_stays_within_the_brandbook_cap(self, built):
        rungs = _rungs(built)
        fs = rungs["fullscreen"]
        assert fs <= 4, f"полноэкранного текста {fs}, потолок брендбука 4: {rungs}"

    def test_bare_plates_stay_within_two(self, built):
        """Маркер xfail снят в Q2: арифметика ТЗ сошлась, когда ступеней стало
        четыре. Диаграмма ожила в Q2.5 (числительные словами), параллакс — в
        Q2.6 (диспатч `render_motion` и свой задний слой)."""
        rungs = _rungs(built)
        assert rungs["plate"] <= 2, f"голых плит {rungs['plate']}, потолок 2: {rungs}"

    def test_at_least_six_frames_are_closed_by_a_device(self, built):
        """Четыре приёмные ступени — то, ради чего лестница и появилась."""
        rungs = _rungs(built)
        devices = (rungs["card"] + rungs["dataviz"] + rungs["source"]
                   + rungs["parallax"])
        assert devices >= 6, f"приёмами закрыто лишь {devices} кадров из 14: {rungs}"

    def test_a_device_frame_carries_the_device_it_claims(self, built):
        """`ladder_rung` без приёма в кадре — отчёт, а не монтаж."""
        overlay_kinds = {(o.get("type") or o.get("kind") or ""): 0
                         for o in built["overlays"]}
        for shot in built["shots"]:
            rung = str(shot.get("ladder_rung") or "")
            if rung == "card":
                assert shot.get("hero"), f"кадр {shot['index']}: ступень card без hero"
                assert shot["hero"].get("template"), shot["hero"]
            elif rung in {"dataviz", "source"}:
                assert any(
                    float(o.get("start", -1)) >= float(shot["start"])
                    and float(o.get("end", -1)) <= float(shot["end"]) + 0.01
                    for o in built["overlays"]), (
                    f"кадр {shot['index']}: ступень {rung} без оверлея; "
                    f"в плане {overlay_kinds}")

    def test_the_plan_says_which_rung_closed_each_frame(self, built):
        """Причина остаётся в плане: её читает человек, а не разбор."""
        for shot in built["shots"]:
            if shot.get("ladder_rung") in {"card", "dataviz", "source"}:
                assert "закрыт приёмом" in str(shot.get("gap_reason") or "")

    def test_the_numbers_block_gets_its_chart(self, built):
        """«Сто пять кубитов» — ради этого §8.2 и оживляла категорию."""
        rungs = _rungs(built)
        assert rungs["dataviz"] >= 1, f"ни одной диаграммы на числовых блоках: {rungs}"

    def test_dataviz_overlays_record_the_number_they_stand_on(self, built):
        """Без grounded_on QC-21 считал живую диаграмму «приёмом без основания»."""
        charts = [o for o in built["overlays"] if o.get("type") == "dataviz"]
        assert charts, "лестница не поставила ни одной диаграммы"
        for ov in charts:
            assert "number" in (ov.get("grounded_on") or []), ov


class TestTheBudgetKeepsTheLadderFromSlidingToOneRung:
    """Без потолка на каждую ступень лестница даст 14 карточек вместо 14 надписей."""

    def test_no_single_device_rung_takes_the_whole_video(self, built):
        """Плита сюда не входит: её потолок держит не лестница, а QC-23.

        Отказать последней ветке нечем — кадр всё равно нужно чем-то закрыть.
        Поэтому `VisualBudget.plate` только считает, а роняет сборку QC-23.
        """
        rungs = _rungs(built)
        for rung, cap in VisualBudget.CAPS.items():
            if rung == "plate":
                continue
            assert rungs[rung] <= cap, f"ступень {rung}: {rungs[rung]} при потолке {cap}"

    def test_the_caps_are_declared_for_every_rung_the_ladder_can_take(self):
        """Ступень без потолка — это ступень, на которую лестница сползёт."""
        assert set(VisualBudget.CAPS) == {"card", "dataviz", "source",
                                          "parallax", "plate"}

    def test_a_budget_stops_giving_once_the_cap_is_reached(self):
        budget = VisualBudget()
        taken = 0
        while budget.allows("card"):
            budget.take("card")
            taken += 1
            assert taken <= 10, "потолок карточки не останавливает лестницу"
        assert taken == VisualBudget.CAPS["card"]
        assert not budget.allows("card")


class TestTheLadderNeverInventsADocument:
    """Окно статьи рисуется только под настоящий источник из плана."""

    def test_without_sources_no_source_card_appears(self, gap_ctx):
        plan = _plan()
        plan["sources"] = []
        catalog = TemplateCatalog.load(gap_ctx.cfg)
        built = build_variant(
            gap_ctx, plan, _words(plan), assets={}, prepared={}, catalog=catalog,
            avatar_meta={"segments": []}, sfx_map={}, variant="B", recent_videos=[])
        assert _rungs(built)["source"] == 0

    def test_the_source_card_repeats_the_plan_verbatim(self, built):
        """Карточка цитирует план буква в букву — иначе это выдуманный документ."""
        by_domain = {s["domain"]: s for s in SOURCES}
        cards = [o for o in built["overlays"] if o.get("type") == "source_card"]
        for card in cards:
            source = by_domain.get(card["params"]["domain"])
            assert source, f"домен не из плана: {card['params']['domain']}"
            assert card["params"]["title"] == source["title"]
            assert card["params"]["body"] == source["snippet"]

    def test_no_source_is_shown_twice(self, built):
        """Один документ, дважды въехавший в кадр, — то самое «дублирование карточек»."""
        cards = [o for o in built["overlays"] if o.get("type") == "source_card"]
        domains = [c["params"]["domain"] for c in cards]
        assert len(domains) == len(set(domains)), f"источник повторён: {domains}"
