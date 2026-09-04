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
from src.p7_broll_search.search import _article_for, _license_mode, _stage1_reject

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
    """MAIN: BL-подпись для любого не-AI стока/пресса; AI — без подписи.

    Раньше подпись включалась только при attribution_required. После BL-credits
    на main кадр показывает источник и для Pexels/NASA — зритель видит, откуда
    кадр. Сгенерированное по-прежнему без подписи.
    """
    from src.p11_assemble.assemble import _credit_line

    spec = {"sources": {"press": {"attribution_required": True},
                        "pexels": {"attribution_required": False}}}

    press = {"source": "press", "attribution": "Nature",
             "meta": {"domain": "nature.com"}}
    assert _credit_line(press, spec) == "Nature · nature.com"
    assert _credit_line({"source": "pexels", "attribution": "Иван Петров"}, spec) == "Иван Петров"
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
