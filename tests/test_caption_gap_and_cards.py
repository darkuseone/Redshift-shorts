"""Слова не слипаются, число не рвётся, хвост не лезет на карточку.

Осмотр прогона 179 покадрово дал три брака одного класса — «на экране стоит
не то, что написано в плане»:

* «СТРАШНОЕ ИМЯ» вышло как «СТРАШНОЕИМЯ»: зазор 0.18em на узком Oswald на
  стыке Е|И не читается как пробел (у соседних букв почти нет полуапрошей).
* карточка b2 «7 · $1 000 000 · 25 Y» разложилась лесенкой как «7 · $1» /
  «000 000 ·» / «25 Y» — разбивка по пробелам приняла разряды за границы слов.
* хвост «НЕ БРАЛ» висел поверх той же карточки, а «СООБЩЕНИЙ» и «17 ЧАСОВ» —
  поверх графика b4.
"""
import json
import re

from src.lib.render.hyperframes.captions import (
    _CAPTION_YIELDS_TO, _frame_taking_starts, build_gradient_fill,
    fit_wipe_group, gradient_fill_params,
)
from src.lib.render.hyperframes.templates import glue_number_runs

BRANDBOOK = json.load(open("config/brandbook.json", encoding="utf-8"))


def _fit(texts):
    p = gradient_fill_params(BRANDBOOK)
    size, widths = fit_wipe_group(
        texts, max_width=p["frame_w"], base=p["base_px"],
        letter_spacing_em=p["letter_spacing_em"], gap_em=p["gap_em"],
        min_size=int(p["min_px"]))
    return size, widths, size * p["gap_em"]


def test_the_word_gap_reads_as_a_space_on_a_condensed_face():
    # 0.18em на Oswald — половина обычного межсловного пробела: буквы узкие,
    # и «СТРАШНОЕ ИМЯ» слиплось в один токен.
    size, _widths, gap = _fit(["СТРАШНОЕ", "ИМЯ"])
    assert gap / size >= 0.28


def test_the_tightest_real_phrase_still_gets_its_gap():
    for texts in (["ПРОСТОЙ", "СМЫСЛ"], ["ТРУБЫ", "В ДОМЕ"],
                  ["10 000", "АГЕНТОВ"]):
        size, widths, gap = _fit(texts)
        assert gap / size >= 0.28, texts
        # и фраза по-прежнему влезает в рабочую зону одной строкой
        assert sum(widths) + gap <= gradient_fill_params(BRANDBOOK)["frame_w"]


def test_a_stacked_card_never_breaks_a_number_across_lines():
    content = "7 · $1 000 000 · 25 Y"
    words = [w for w in re.split(r"[ \t]+", glue_number_runs(content)) if w]
    per = max(1, (len(words) + 2) // 3)
    lines = [" ".join(words[i:i + per]) for i in range(0, len(words), per)][:3]
    joined = "\n".join(lines)
    assert "$1 000 000" in joined
    for line in lines:
        # ни одна строка не начинается и не кончается куском числа
        assert not re.fullmatch(r"0{3}", line.strip(" ·"))


def _plan(overlays, shots=()):
    return {
        "subtitles": [
            {"display": "Не", "start": 2.0, "end": 2.4},
            {"display": "брал", "start": 2.45, "end": 3.0},
        ],
        "subtitle_style": {},
        "overlays": list(overlays),
        "shots": list(shots),
    }


def _clip_end(nodes):
    start = float(re.search(r'data-start="([\d.]+)"', nodes[0]).group(1))
    dur = float(re.search(r'data-duration="([\d.]+)"', nodes[0]).group(1))
    return start + dur


def test_a_caption_tail_stops_where_a_card_starts():
    # Карточка приходит в план шотом (kind), а не оверлеем (type): список,
    # собранный по одним overlays, её не видел — и хвост «НЕ БРАЛ» лежал
    # поверх «7 · $1 000 000 · 25 Y» весь прогон 180.
    free, _t, _c = build_gradient_fill(_plan([]), BRANDBOOK, duration=10.0)
    card, _t, _c = build_gradient_fill(
        _plan([], shots=[{"kind": "fullscreen_text", "start": 3.2, "end": 4.6}]),
        BRANDBOOK, duration=10.0)
    assert _clip_end(free) > 3.2  # без карточки хвост жил дольше
    assert _clip_end(card) <= 3.2 + 1e-6


def test_a_chart_takes_the_frame_from_the_caption_tail_too():
    out, _t, _c = build_gradient_fill(
        _plan([{"type": "dataviz", "start": 3.1, "end": 6.0}]),
        BRANDBOOK, duration=10.0)
    assert _clip_end(out) <= 3.1 + 1e-6


def test_the_spoken_word_itself_is_never_cut_away():
    # оверлей посреди произносимого слова хвост не режет: на экране остаётся
    # то, что звучит.
    out, _t, _c = build_gradient_fill(
        _plan([{"type": "dataviz", "start": 2.6, "end": 6.0}]),
        BRANDBOOK, duration=10.0)
    assert _clip_end(out) >= 3.0


def test_the_yield_list_covers_the_frame_filling_overlays():
    assert {"dataviz", "plaque", "cta", "source_card"} <= _CAPTION_YIELDS_TO


def test_both_collections_are_read_for_cut_points():
    # оверлей лежит в plan["overlays"], карточка — в plan["shots"]
    starts = _frame_taking_starts({
        "overlays": [{"type": "dataviz", "start": 9.0},
                     {"type": "highlight", "start": 1.0}],
        "shots": [{"kind": "fullscreen_text", "start": 3.2},
                  {"kind": "footage", "start": 5.0}],
    })
    assert sorted(starts) == [3.2, 9.0]
