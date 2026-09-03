"""Приём ставится по смыслу блока, а не по его роли (§3.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.lib.meaning import (
    TRAITS, TRAIT_TITLES, block_traits, explain, matched, satisfies,
)
from src.lib.templates import TemplateCatalog


@pytest.fixture
def catalog():
    path = Path(__file__).resolve().parents[1] / "templates" / "manifest.json"
    return TemplateCatalog(path, json.loads(path.read_text(encoding="utf-8")))


class TestTheTextTellsWhatCanBeShown:
    """Признаки достаются из текста реплики, а не назначаются вручную."""

    def test_numbers_written_as_words_count_too(self):
        """Сценарий пишет числа словами: их озвучивает TTS.

        Замер по шести сценариям: регулярка на цифру находила число в 6 %
        блоков, со словами-числительными — в 25 %. Половина ролика про
        рекорды и глубины прошла бы мимо карточки числа.
        """
        assert "number" in block_traits("Дошли до двенадцати тысяч метров")
        assert "number" in block_traits("Температура 180 градусов")
        assert "number" in block_traits("Половина установки осталась внизу")
        assert "number" not in block_traits("Скважину закрыли и забыли")

    def test_a_question_is_a_question_even_without_a_mark(self):
        assert "question" in block_traits("Почему её закрыли")
        assert "question" in block_traits("И что теперь?")
        assert "question" not in block_traits("Её закрыли в девяносто втором")

    def test_a_bare_no_is_not_a_negation(self):
        """«Не только» и «не совсем» — речь, а не смысл.

        Голое «не» стояло в трети блоков: признак, который есть везде, не
        отличает ничего и приём не оправдывает.
        """
        assert "negation" not in block_traits("Это не только глубина, но и жара")
        assert "negation" in block_traits("Дело не в деньгах")
        assert "negation" in block_traits("Бурить перестали")

    def test_traits_read_as_a_sentence(self):
        text = explain(block_traits("Рекорд: двенадцать километров"))
        assert "число" in text and "рекорд" in text
        assert explain([]) == "признаков нет"

    def test_every_trait_has_a_human_name(self):
        assert set(TRAITS) == set(TRAIT_TITLES)


class TestATemplateNeedsSomethingToFillIt:
    def test_a_device_without_a_requirement_fits_anywhere(self):
        assert satisfies([], set())
        assert satisfies([], {"number"})

    def test_one_matching_trait_is_enough(self):
        assert satisfies(["negation", "superlative"], {"superlative"})
        assert not satisfies(["negation", "superlative"], {"number"})

    def test_the_match_is_named(self):
        assert matched(["number", "quote"], {"number", "place"}) == frozenset({"number"})


class TestTheCatalogPicksByMeaning:
    def test_a_chart_needs_a_number(self, catalog):
        for template in catalog.by_category("data-viz"):
            assert template.needs == ["number"], template.id

    def test_a_question_brings_the_chat_window(self, catalog):
        picked = catalog.pick("browser-ui", traits={"question"}, seed=3)
        assert "question" in picked.needs

    def test_a_quote_brings_the_article(self, catalog):
        picked = catalog.pick("browser-ui", traits={"quote"}, seed=3)
        assert "quote" in picked.needs

    def test_without_traits_only_devices_that_ask_for_nothing(self, catalog):
        for _seed in range(12):
            picked = catalog.pick("hero-devices", traits=set(), seed=_seed)
            assert picked.needs == [], picked.id

    def test_unknown_traits_do_not_switch_the_filter_on(self, catalog):
        """``None`` — «признаки неизвестны», а не «признаков нет».

        Забытый аргумент иначе молча выключил бы дюжину приёмов: они просто
        перестали бы выбираться, и заметить это было бы нечем.
        """
        renderers = {catalog.pick("hero-devices", traits=None, seed=s).renderer
                     for s in range(40)}
        assert any(catalog.by_id(t.id).needs
                   for t in catalog.by_category("hero-devices")
                   if t.renderer in renderers)

    def test_a_grounded_device_outranks_an_indifferent_one(self, catalog):
        """При прочих равных приём с основанием идёт первым."""
        picked = catalog.pick("hero-devices", traits={"brand"}, seed=5)
        assert "brand" in picked.needs


class TestThePlanSaysWhyEachDeviceIsThere:
    def test_the_reason_reaches_the_shot(self):
        from src.p11_assemble.assemble import _hero_device

        path = Path(__file__).resolve().parents[1] / "templates" / "manifest.json"
        cat = TemplateCatalog(path, json.loads(path.read_text(encoding="utf-8")))
        # У приёма два входа: наполнение (`_HERO_NEEDS` — есть ли что
        # показать) и смысл (`needs` — оправдан ли он этим блоком). Здесь
        # проверяется второй, поэтому наполнение дано всем.
        content = {"word": "ГЛУБИНА", "title": "Кольская", "lines": ["а", "б"],
                   "punch": ["а", "б"], "entries": ["а"], "figures": [],
                   "face": (540, 570), "caption": "подпись",
                   "ask": "что будет, если бурить дальше", "answer": "ствол затянет",
                   "head": "Кольская", "tail": "перестала бурить"}
        slot = {"index": 3, "role": "develop", "duration": 5.0, "start": 0.0, "end": 5.0}
        block = {"id": "b4", "text": "Что будет, если бурить дальше?"}
        reasons = set()
        for seed in range(24):
            entry = _hero_device(cat, slot=slot, content=content, has_alpha=True,
                                 plate_src=None, recent_videos=[], exclude=[],
                                 seed=seed, block=block)
            if entry:
                assert "why" in entry and entry["why"]
                assert entry["traits"] == sorted(block_traits(block["text"]))
                reasons.add(entry["why"])
        assert reasons, "приём не выбрался ни разу"
        assert any("задан вопрос" in r for r in reasons), sorted(reasons)
