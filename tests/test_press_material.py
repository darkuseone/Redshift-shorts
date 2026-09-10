"""Кадр со страницы источника и сама карточка источника (§5.5, §5.6, §7.2).

Заказчик просил больше реального материала: «если материал по какой-то статье,
то можешь брать прям оттуда кадры или видео», и чтобы страница в кадре читалась
как живой сайт, а не как AI-макет.
"""

from __future__ import annotations

import re

import pytest

from src.lib.providers.press import PressProvider, meta_map
from src.lib.providers.stock import StockCandidate
from src.p11_assemble.assemble import _evidence_runs
from src.p7_broll_search.search import _article_for, _license_mode, _press_pages_for, _stage1_reject

PAGE = """
<!doctype html><html><head>
<meta charset="utf-8">
<meta property="og:site_name" content="Nature">
<meta content="Quantum error correction &amp; the surface code" property="og:title">
<meta name='twitter:image' content='/img/small.jpg'>
<meta property="og:image" content="https://media.nature.com/lw1024/hero.jpg">
<meta property="article:published_time" content="2024-12-09T16:00:00Z">
</head><body>…</body></html>
"""

ROUTING = {"sources": {"press": {"license_check": "owner_decision"},
                       "pexels": {"license_check": "source_default"}}}


class _Cfg:
    """Конфиг ровно в том объёме, в каком его читает отбраковка шага 1."""

    def get(self, key, default=None):
        return default


def test_meta_is_read_in_any_attribute_order():
    """Издания пишут og-теги и так и эдак, и кавычки у них любые."""
    meta = meta_map(PAGE)
    assert meta["og:site_name"] == "Nature"
    # content раньше property — тот же тег, и его нельзя терять.
    assert meta["og:title"] == "Quantum error correction &amp; the surface code"
    assert meta["twitter:image"] == "/img/small.jpg"
    assert meta["article:published_time"].startswith("2024-12-09")


def test_date_is_found_where_the_publisher_put_it(monkeypatch):
    """Дату каждое издание кладёт по-своему, и карточке она нужна.

    Проверено на живых страницах: blog.google отдаёт article:published_time,
    nature.com — только dc.date и prism.publicationdate.
    """
    page = ('<meta property="og:image" content="https://x/h.jpg">'
            '<meta name="dc.date" content="2024-12-09">'
            '<meta name="prism.publicationdate" content="2024-12-09">')
    provider = PressProvider.__new__(PressProvider)
    provider.name = "press"
    monkeypatch.setattr(PressProvider, "_fetch", lambda self, url: page)
    monkeypatch.setattr(PressProvider, "charge",
                        lambda self, *a, **k: None, raising=False)

    candidate = provider.search("https://www.nature.com/articles/s41586")[0]
    assert candidate.meta["published"] == "2024-12-09"


def test_press_candidate_carries_the_page_it_came_from(monkeypatch):
    """У кадра из статьи обязаны быть домен, ссылка и кредит: без них §1
    (правило 8) не выполнить, а показывать такой кадр нельзя."""
    provider = PressProvider.__new__(PressProvider)
    provider.name = "press"
    monkeypatch.setattr(PressProvider, "_fetch", lambda self, url: PAGE)
    monkeypatch.setattr(PressProvider, "charge",
                        lambda self, *a, **k: None, raising=False)

    url = "https://www.nature.com/articles/s41586-024-08449-y"
    candidate = provider.search(url)[0]
    assert candidate.source == "press"
    assert candidate.page_url == url
    assert candidate.download_url == "https://media.nature.com/lw1024/hero.jpg"
    assert candidate.attribution == "Nature"
    # Лицензию издания подтвердить нечем, и делать вид, что подтвердили, нельзя.
    assert candidate.license_confirmed is False
    assert candidate.meta["domain"] == "nature.com"
    # Экранированный амперсанд в заголовке — не «&amp;» в кадре.
    assert "&" in candidate.meta["title"] and "amp;" not in candidate.meta["title"]


def test_relative_image_is_resolved_against_the_article(monkeypatch):
    """og:image часто относительный: без склейки скачивать нечего."""
    page = '<meta property="og:image" content="/media/hero.jpg">'
    provider = PressProvider.__new__(PressProvider)
    provider.name = "press"
    monkeypatch.setattr(PressProvider, "_fetch", lambda self, url: page)
    monkeypatch.setattr(PressProvider, "charge",
                        lambda self, *a, **k: None, raising=False)

    candidate = provider.search("https://blog.google/technology/willow/")[0]
    assert candidate.download_url == "https://blog.google/media/hero.jpg"


def test_jsonld_image_is_taken_when_og_image_is_missing(monkeypatch):
    page = (
        '<script type="application/ld+json">'
        '{"@type":"NewsArticle","image":"https://cdn.example/official.jpg"}'
        "</script>"
    )
    provider = PressProvider.__new__(PressProvider)
    provider.name = "press"
    monkeypatch.setattr(PressProvider, "_fetch", lambda self, url: page)
    monkeypatch.setattr(PressProvider, "charge",
                        lambda self, *a, **k: None, raising=False)
    candidate = provider.search("https://openai.com/index/navier-stokes/")[0]
    assert candidate.download_url == "https://cdn.example/official.jpg"


def test_press_pages_include_wikipedia_source():
    plan = {
        "blocks": [{"id": "b3", "source_ref": "openai.com"}],
        "sources": [
            {"domain": "openai.com", "url": "https://openai.com/index/ns",
             "title": "OpenAI"},
            {"domain": "en.wikipedia.org",
             "url": "https://en.wikipedia.org/wiki/Navier-Stokes",
             "title": "Navier–Stokes"},
        ],
    }
    pages = _press_pages_for({"block_id": "b3", "asset_role": "evidence"}, plan)
    urls = [p["url"] for p in pages]
    assert "https://openai.com/index/ns" in urls
    assert any("wikipedia.org" in u for u in urls)
    assert _press_pages_for({"block_id": "b3", "asset_role": "broll"}, plan) == []


def test_only_the_named_source_may_skip_the_licence_check():
    """§7.2.7 не ослаблено для всех: режим назван поимённо в stock_sources.yaml.

    Иначе «лицензия не подтверждена» перестало бы значить что-либо, и мимо
    правила прошёл бы любой источник, у которого её просто не оказалось.
    """
    assert _license_mode("press", ROUTING) == "owner_decision"
    assert _license_mode("pexels", ROUTING) == "source_default"
    assert _license_mode("нет такого", ROUTING) == "per_item"

    press = StockCandidate(id="press_1", source="press", kind="photo", query="u",
                           license="editorial-quote", license_confirmed=False,
                           width=1200, height=630)
    stock = StockCandidate(id="px_1", source="pexels", kind="photo", query="q",
                           license="Pexels License", license_confirmed=False,
                           width=1200, height=630)
    assert _stage1_reject(press, _Cfg(), 3.0, routing=ROUTING) is None
    assert _stage1_reject(stock, _Cfg(), 3.0, routing=ROUTING)


def test_article_is_found_through_the_block_not_through_the_video():
    """Кадр иллюстрирует ту статью, которую цитирует блок, а не первую в списке."""
    plan = {
        "blocks": [{"id": "b3", "source_ref": "nature.com"},
                   {"id": "b4", "source_ref": None}],
        "sources": [{"domain": "blog.google", "url": "https://blog.google/a"},
                    {"domain": "nature.com", "url": "https://nature.com/b"}],
    }
    slot = {"block_id": "b3", "asset_role": "evidence"}
    assert _article_for(slot, plan)["url"] == "https://nature.com/b"
    # Блок без ссылки на источник кадра из статьи не получает.
    assert _article_for({"block_id": "b4", "asset_role": "evidence"}, plan) is None
    # И обычный футажный слот тоже: статья — это доказательство, а не фон.
    assert _article_for({"block_id": "b3", "asset_role": "broll"}, plan) is None


def test_evidence_slots_of_one_block_are_one_card():
    """P5 режет длинный блок на несколько слотов — карточек всё равно одна."""
    slots = [
        {"index": 5, "start": 7.0, "end": 9.0, "block_id": "b3", "asset_role": "evidence"},
        {"index": 6, "start": 9.0, "end": 11.0, "block_id": "b3", "asset_role": "evidence"},
        {"index": 7, "start": 11.0, "end": 13.0, "block_id": "b3", "asset_role": "broll"},
        {"index": 8, "start": 13.0, "end": 15.0, "block_id": "b5", "asset_role": "evidence"},
    ]
    runs = _evidence_runs(slots)
    assert [[s["index"] for s in run] for run in runs] == [[5, 6], [8]]


def test_a_still_image_yields_exactly_one_frame(tmp_path):
    """Кадр из статьи — картинка, и мерить её надо по ней самой.

    Перемотка по неподвижному кадру уходит **за** него: ffmpeg возвращает ноль
    и пустой файл, вызывающий получает пустой список — и остаётся без палитры и
    без дедупа. На мок-прогоне один и тот же кадр из-за этого встал в четыре
    слота подряд.
    """
    from PIL import Image

    from src.lib.ffmpeg import extract_frames

    src = tmp_path / "hero.jpg"
    Image.new("RGB", (1200, 630), (40, 12, 14)).save(src)
    frames = extract_frames(src, tmp_path / "frames", [0.1, 0.5, 0.9])
    assert len(frames) == 1 and frames[0].exists()


def test_press_material_never_lands_in_the_shared_library():
    """Кадр из статьи не переиспользуется другим роликом.

    В общей базе он был бы доступен любому сюжету, а вместе с ним исчезло бы
    единственное основание его показывать — та самая страница рядом в кадре.
    """
    from src.p8_broll_judge.judge import belongs_to_its_source

    assert belongs_to_its_source({"origin": "press", "asset_id": "press_1"})
    assert not belongs_to_its_source({"origin": "stock", "asset_id": "px_1"})
    assert not belongs_to_its_source({"asset_id": "px_1"})


def test_grade_pulls_a_colourful_frame_into_the_channel_palette(tmp_path):
    """Настоящая съёмка цветная, и отбор по палитре (§3.1) честно её бракует.

    Ответ — не поднять порог до бессмыслицы, а свести кадр к палитре канала.
    Числа взяты измерением: до грейда посторонний цвет занимает почти весь
    кадр, после — укладывается даже в общий порог 0.15.
    """
    import json

    from PIL import Image

    from src.lib.ffmpeg import grade_to_palette
    from src.lib.palette import off_palette_share

    rules = json.load(open("config/brandbook.json", encoding="utf-8"))
    rules = rules["color_rules"]["footage_palette"]
    grade = {k: v for k, v in rules["press_grade"].items()}

    src = tmp_path / "news.jpg"
    # Дневной кадр: синее небо и зелень — ровно то, чем живёт пресс-фото.
    frame = Image.new("RGB", (640, 360), (60, 130, 210))
    for y in range(180, 360):
        for x in range(0, 640, 2):
            frame.putpixel((x, y), (70, 150, 60))
    frame.save(src)
    before = off_palette_share(Image.open(src), rules)

    dst = grade_to_palette(src, tmp_path / "graded.jpg", **grade)
    after = off_palette_share(Image.open(dst), rules)

    assert before > float(rules["press_off_share_max"])
    assert after <= float(rules["off_share_max"])


# --- карточка источника -------------------------------------------------------

def _card(params: dict) -> str:
    from src.lib.render.hyperframes.composition import CompositionBuilder

    return CompositionBuilder._source_card_body(
        object.__new__(CompositionBuilder), "ovl-00", params)


def test_card_shows_the_real_address_and_a_marker_on_the_key_line():
    """Страница издания, а не «окно вообще»: адрес, дата, знак и маркер §5.5."""
    html = _card({
        "domain": "nature.com",
        "url": "https://www.nature.com/articles/s41586-024-08449-y",
        "title": "Quantum error correction below the surface code threshold",
        "snippet": "Логический кубит живёт дольше физических.",
        "published": "2024-12-09T16:00:00Z",
        "highlight": "below the surface code threshold",
    })
    assert "<b>nature.com</b>/articles/s41586-024-08449-y" in html
    # Дата — днём, без времени: часы на карточке читать некому.
    assert ">2024-12-09<" in html
    assert 'class="favicon">N<' in html
    assert '<span class="hl">below the surface code threshold</span>' in html
    # Маркер не съедает остальной заголовок.
    assert "Quantum error correction " in html


def test_card_without_a_date_says_what_it_is():
    """Сценарий даты не обязан знать — но кадр не имеет права быть пустым."""
    html = _card({"domain": "nature.com", "title": "Заголовок"})
    assert ">источник<" in html
    assert 'class="hl"' not in html


@pytest.mark.parametrize("phrase", ["", "строки, которой в тексте нет"])
def test_card_marks_nothing_when_there_is_nothing_to_mark(phrase):
    html = _card({"domain": "d.com", "title": "Заголовок статьи", "highlight": phrase})
    assert 'class="hl"' not in html
    assert re.search(r">Заголовок статьи<", html)


# --- подпись источника (§1, правило 8) ----------------------------------------

def test_credit_is_printed_only_where_the_licence_asks_for_it():
    """Press keeps a human credit; Pexels/Pixabay brand watermarks stay off."""
    from src.p11_assemble.assemble import _credit_line

    spec = {"sources": {"press": {"attribution_required": True},
                        "pexels": {"attribution_required": False},
                        "pixabay": {"attribution_required": False},
                        "freepik": {"attribution_required": True}}}

    press = {"source": "press", "attribution": "Nature",
             "meta": {"domain": "nature.com"}}
    assert _credit_line(press, spec) == "Nature · nature.com"
    # Burned-in stock brands duplicate on-screen; hide unless the licence
    # actually requires a non-brand human name.
    assert _credit_line({"source": "pexels", "attribution": "Иван Петров"}, spec) == ""
    assert _credit_line({"source": "pexels",
                         "attribution": "Pexels / Google DeepMind"}, spec) == ""
    assert _credit_line({"source": "pixabay",
                         "attribution": "Pixabay / Digital_View"}, spec) == ""
    assert _credit_line({"source": "freepik",
                         "attribution": "Freepik / Magnific stock"}, spec) == ""
    spec_req = {"sources": {"pexels": {"attribution_required": True}}}
    assert _credit_line({"source": "pexels", "attribution": "Иван Петров"},
                        spec_req) == "Иван Петров"
    assert _credit_line({"source": "pexels", "attribution": "PEXELS"}, spec_req) == ""
    # Своё авторство в кадре не декларируют.
    assert _credit_line({**press, "ai_generated": True}, spec) == ""
    # Домен не дублируется, если он уже в имени.
    assert _credit_line({"source": "press", "attribution": "nature.com"}, spec) == "nature.com"


def test_the_credit_sits_above_the_subtitle_band_and_never_over_it():
    """Подпись — сноска, а не элемент композиции: она не имеет права лезть в
    полосу субтитров и в колонку лайк/коммент/шер справа."""
    import json
    import re

    from src.lib.render.hyperframes.brand_css import build_css

    brandbook = json.load(open("config/brandbook.json", encoding="utf-8"))
    css = build_css(brandbook, {})
    rule = re.search(r"\.credit\{([^}]*)\}", css).group(1)
    assert "left:var(--safe-x-min)" in rule, "подпись ушла в правую колонку"
    bottom = int(re.search(r"bottom:(\d+)px", rule).group(1))
    subs = brandbook["subtitles"]
    height = int(brandbook["canvas"]["height"])
    assert bottom >= height - int(subs["baseline_y_default"]) + int(subs["size_px"][1]) // 2


# --- Q3.4/Q3.5: язык экрана против языка озвучки (§7.3, §11.3) ---------------

class TestTheGlossLivesInTheVoiceNotOnTheCard:
    """Критик назвал «(квантовый бит)» на карточке дословно.

    §7.3: карточка — акцентное слово + подпись ≤ 6 слов + медиа. Скобочные
    глоссы запрещены на любом экранном тексте, а пояснение уходит в озвучку.
    """

    def test_the_glossary_is_data_not_regexes_in_code(self, repo_root):
        import json

        path = repo_root / "config" / "glossary.json"
        assert path.exists(), "config/glossary.json — часть Q3.4"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["on_screen"] and data["spoken"]
        for rule in data["on_screen"]:
            assert rule["pattern"] and rule["replace"]
            assert "(" not in rule["replace"], "скобки на экране запрещены (§7.3)"

    def test_screen_copy_never_gains_a_bracket_gloss(self):
        from src.lib.text import has_bracket_gloss, soften_on_screen_copy

        for line in ("105 кубитов внутри", "кубит", "квантовый чип",
                     "below the surface code threshold"):
            out = soften_on_screen_copy(line)
            assert not has_bracket_gloss(out), f"скобочный глосс на экране: {out!r}"

    def test_the_english_service_line_becomes_russian(self):
        from src.lib.text import soften_on_screen_copy

        out = soften_on_screen_copy("below the surface code threshold")
        assert "порог" in out.lower() and "surface" not in out.lower()

    def test_the_voice_gets_the_gloss_once_per_video(self):
        from src.lib.text import gloss_for_speech

        seen: set[str] = set()
        first = gloss_for_speech("Внутри 105 кубитов.", seen=seen)
        second = gloss_for_speech("И ещё кубиты сверху.", seen=seen)
        assert "квантовый бит" in first.lower()
        assert "квантовый бит" not in second.lower(), "пояснение звучит один раз"

    def test_the_voice_gloss_carries_no_brackets(self):
        from src.lib.text import gloss_for_speech, has_bracket_gloss

        out = gloss_for_speech("Кубит держит суперпозицию.", seen=set())
        assert not has_bracket_gloss(out)
        assert out.count(",,") == 0, "двойная запятая — опечатка, а не речь"

    def test_an_author_who_explained_it_himself_is_left_alone(self):
        from src.lib.text import gloss_for_speech

        line = "Кубит — это квантовый бит, и он хрупкий."
        assert gloss_for_speech(line, seen=set()) == line

    def test_the_pipeline_puts_the_gloss_in_spoken_text_only(self, cfg, repo_root):
        """P1 кладёт пояснение в `spoken_text`, а `text` для экрана не трогает."""
        import json

        from src.p1_plan.planner import plan as build_plan

        script = json.loads(
            (repo_root / "scripts" / "redshift_0042.json").read_text(encoding="utf-8"))
        from src.p0_validate.validator import validate_script

        from src.lib.text import strip_stress

        # Хук на диске уже ≤3 с; для этого теста всё равно фиксируем короткую фразу.
        hook = next(b for b in script["blocks"] if b.get("role") == "hook")
        hook["text"] = "Этот ответ невозможно проверить. Совсем никак."
        plan = build_plan(validate_script(script, cfg), cfg)
        # `spoken_text` несёт знаки ударения — их ставит нормализация для TTS.
        glossed = [b for b in plan["blocks"]
                   if "квантовый бит" in strip_stress(str(b["spoken_text"])).lower()]
        assert glossed, "пояснение не доехало до озвучки"
        for block in plan["blocks"]:
            assert "квантовый бит" not in str(block["text"]).lower(), \
                "пояснение просочилось в экранный текст"


class TestTheSourceCardSpeaksRussian:
    """Q3.5: русский `snippet` обязателен, английский заголовок — не в строке А."""

    def test_a_cyrillic_title_is_kept_as_is(self):
        from src.p11_assemble.assemble import _russian_headline

        title = "Квантовая коррекция ошибок ниже порога"
        assert _russian_headline({"title": title, "snippet": "что-то"}) == title

    def test_a_latin_title_gives_way_to_the_russian_snippet(self):
        from src.p11_assemble.assemble import _russian_headline

        head = _russian_headline({
            "title": "A giant planet candidate transiting a white dwarf",
            "snippet": "Планета размером с Юпитер обращается вокруг остатка мёртвой звезды."})
        assert head.startswith("Планета размером")
        assert "planet" not in head.lower()

    def test_the_headline_stays_within_the_caption_measure(self):
        from src.p11_assemble.assemble import _CARD_HEADLINE_WORDS, _russian_headline

        head = _russian_headline({
            "title": "No Way Back: Maximizing Survival Time",
            "snippet": ("Максимальное собственное время под горизонтом достигается "
                        "в свободном падении: любой манёвр двигателем его сокращает.")})
        assert len(head.split()) <= _CARD_HEADLINE_WORDS + 1  # +1 на многоточие

    def test_a_short_russian_snippet_is_taken_whole(self):
        from src.p11_assemble.assemble import _russian_headline

        assert _russian_headline({"title": "Willow announcement",
                                  "snippet": "Логический кубит живёт дольше."}) \
            == "Логический кубит живёт дольше"

    def test_no_snippet_no_headline(self):
        from src.p11_assemble.assemble import _russian_headline

        assert _russian_headline({"title": "Willow processor announcement"}) == ""

    def test_p0_names_an_on_screen_source_without_a_russian_snippet(self, cfg):
        from src.p0_validate.validator import _check_source_snippets

        codes = [w["code"] for w in _check_source_snippets([
            {"title": "A giant planet candidate", "domain": "nature.com",
             "show_on_screen": True}])]
        assert codes == ["SOURCE_SNIPPET_MISSING"]

    def test_a_source_that_stays_off_screen_needs_nothing(self):
        from src.p0_validate.validator import _check_source_snippets

        assert _check_source_snippets([
            {"title": "Willow processor announcement", "domain": "blog.google",
             "show_on_screen": False}]) == []

    def test_an_english_snippet_does_not_count(self):
        from src.p0_validate.validator import _check_source_snippets

        codes = [w["code"] for w in _check_source_snippets([
            {"title": "X", "domain": "nature.com", "show_on_screen": True,
             "snippet": "A logical qubit outlives its physical qubits."}])]
        assert codes == ["SOURCE_SNIPPET_MISSING"]

    @pytest.mark.parametrize("video_id", ["redshift_0042", "redshift_0043",
                                          "redshift_0044", "redshift_0045",
                                          "redshift_0046"])
    def test_every_on_screen_source_in_the_channel_has_one(self, repo_root, video_id):
        """DoD Q3.5 на живых сценариях, а не на выдуманном примере."""
        import json

        from src.p0_validate.validator import _check_source_snippets

        script = json.loads(
            (repo_root / "scripts" / f"{video_id}.json").read_text(encoding="utf-8"))
        assert _check_source_snippets(script.get("sources", [])) == []
