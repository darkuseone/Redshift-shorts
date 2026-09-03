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
        """График без числа — пустая рамка; карта — исключение по смыслу.

        Требование категории («число») перебивается требованием id там, где
        приём говорит не о величине: карта мира показывает место, и числа
        в блоке может не быть вовсе.
        """
        for template in catalog.by_category("data-viz"):
            assert template.needs, template.id
            assert template.needs == ["number"] or "place" in template.needs, \
                template.id

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


class TestTheSourceCardSurvivesTheMerge:
    """Карточка источника собирается — и с признаком, и без него.

    Слияние ветки шаблонов оставило в этом месте обращение к переменной,
    которую объявляла только та сторона: `NameError: name 'renderer' is not
    defined` на шаге P11. Локально не ловилось — у сценария 0047 источников
    нет вовсе, и ветка кода не выполнялась ни разу. CI собирает 0042, где
    источника два, и падал там.
    """

    def _plan(self):
        return {
            "video_id": "redshift_0001",
            "duration_sec": 40.0,
            "sources": [{"title": "Кольская скважина", "domain": "nature.com",
                         "url": "https://nature.com/kola", "show_on_screen": True,
                         "snippet": "по словам геологов, границы не оказалось",
                         "highlight_line": "границы не оказалось"}],
            "blocks": [{"id": "b3", "role": "evidence",
                        "text": "По словам геологов, «границы не оказалось»."}],
            "slots": [{"index": 2, "block_id": "b3", "role": "evidence",
                       "asset_role": "evidence", "kind": "footage",
                       "start": 8.0, "end": 12.0, "duration": 4.0}],
        }

    def _overlays(self, variant):
        from pathlib import Path
        import json as _json

        from src.p11_assemble.assemble import _build_overlays

        path = Path(__file__).resolve().parents[1] / "templates" / "manifest.json"
        cat = TemplateCatalog(path, _json.loads(path.read_text(encoding="utf-8")))
        return _build_overlays(None, self._plan(), [], cat, variant=variant,
                               seed=1, recent_videos=[], used=[])

    @pytest.mark.parametrize("variant", ["A", "B"])
    def test_the_card_is_built_and_names_its_renderer(self, variant):
        cards = [o for o in self._overlays(variant) if o["type"] == "source_card"]
        assert cards, "карточка источника не собралась"
        card = cards[0]
        assert card["renderer"], "у карточки нет рендерера"
        assert card["template"]
        assert card["why"]

    def test_a_quote_in_the_block_grounds_the_card(self):
        card = next(o for o in self._overlays("A") if o["type"] == "source_card")
        assert "quote" in card["grounded_on"], card["why"]


class TestTheTransitionAnswersToWhatItIntroduces:
    """Переход отвечает за то, что вводит, — и не ставится просто так.

    Гравитационная линза, марево, разрушение — приёмы со значением. Поставить
    линзу между двумя планами ведущего значит украсить кадр, а не сказать им
    что-то; заказчик назвал это прямо: «не вставляй анимации куда попало».
    Нейтральные переходы — резка, шторка, наезд — требований не несут и
    остаются доступны везде.
    """

    def test_a_strong_transition_needs_its_meaning(self, catalog):
        strong = [t for t in catalog.by_category("transitions") if t.needs]
        assert strong, "в каталоге нет ни одного смыслового перехода"
        for _seed in range(30):
            picked = catalog.pick("transitions", duration=0.24, traits=set(),
                                  seed=_seed, tags={"dynamic", "entry"})
            assert not picked.needs, picked.id

    def test_the_lens_comes_to_a_discovery(self, catalog):
        picked = catalog.pick("transitions", duration=0.24,
                              traits={"discovery"}, seed=1,
                              prefer=["transitions/gravitational-lens"])
        assert picked.id == "transitions/gravitational-lens"
        assert "discovery" in picked.needs

    def test_the_plan_says_why_the_transition_is_there(self):
        """Основание уходит в edit-план: его читает человек, а не разбор."""
        from src.p11_assemble.assemble import explain_choice

        path = Path(__file__).resolve().parents[1] / "templates" / "manifest.json"
        cat = TemplateCatalog(path, json.loads(path.read_text(encoding="utf-8")))
        strong = cat.by_id("transitions/thermal-distortion")
        assert "приём оправдан" in explain_choice(strong, {"danger"})
        assert "не спорит с речью" in explain_choice(strong, {"number"})


class TestAnEmptySlotIsNeverAnEmptyFrame:
    """Кадру без материала достаётся приём, а не заливка.

    В живом 0047 четыре слота остались пустыми: сток ничего не дал, а
    генерация упёрлась в потолок доли AI (35 %). Заливка превратила их в
    чёрный экран — 9.5 секунды из 60, пять из них подряд, с одним субтитром
    на пустоте. QC показал 19 из 19: он не проверяет, есть ли в кадре
    что-нибудь. Слово, вынесенное крупно, честнее пустоты — и оно то же
    самое, что звучит.
    """

    def _built(self):
        from src.p11_assemble.assemble import gap_phrase

        return gap_phrase

    def test_the_screen_says_what_the_voice_says(self):
        gap_phrase = self._built()
        words = [{"word": "мы", "start": 10.0, "end": 10.3},
                 {"word": "упёрлись", "start": 10.3, "end": 10.9},
                 {"word": "в", "start": 10.9, "end": 11.0},
                 {"word": "физику", "start": 11.0, "end": 11.6},
                 {"word": "дальше", "start": 12.4, "end": 12.9}]
        slot = {"start": 10.0, "end": 11.8, "index": 3}
        assert gap_phrase(words, slot, {}) == "МЫ УПЁРЛИСЬ В ФИЗИКУ"

    def test_silence_falls_back_to_the_block(self):
        gap_phrase = self._built()
        slot = {"start": 40.0, "end": 41.4, "index": 9}
        phrase = gap_phrase([], slot, {"text": "Скважину закрыли и забыли о ней"})
        assert phrase == "СКВАЖИНУ ЗАКРЫЛИ И ЗАБЫЛИ"

    def test_a_gap_becomes_a_device_not_a_fill(self, catalog):
        """Слот без материала выходит из сборки полноэкранным текстом."""
        import json as _json
        from pathlib import Path as _Path

        from src.p11_assemble.assemble import build_variant

        # Плана целиком здесь не строим: проверяется одно — что ветка пустого
        # слота выбирает приём и кладёт в кадр слово, а не оставляет `file`
        # единственным содержимым.
        source = (_Path(__file__).resolve().parents[1]
                  / "src" / "p11_assemble" / "assemble.py").read_text(encoding="utf-8")
        branch = source[source.index('if prep is None or (asset is None'):]
        branch = branch[:branch.index("shots.append(entry)")]
        assert '"kind": "fullscreen_text"' in branch
        assert "catalog.pick(" in branch
        assert "gap_phrase(" in branch
        assert '"gap_reason"' in branch, "причина пропуска обязана остаться в отчёте"
        assert build_variant is not None
