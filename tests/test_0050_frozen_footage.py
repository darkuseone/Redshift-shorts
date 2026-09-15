"""Заявка 0050 после покадрового разбора: пять правок и заморозка остального.

Хозяин попросил починить ровно пять пунктов, а весь остальной футаж
зафиксировать, чтобы он не уехал в новой генерации. Фиксация — это замок
слотов: каждый кадр с материалом назван поимённо и привязан к своей реплике.
"""
import json

import pytest

REPO_PINS = json.load(open("config/footage_pins.json", encoding="utf-8"))
PINS = REPO_PINS["redshift_0050"]
LOCK = PINS["slots_lock"]
M = "magnific_0050_"


def _assets():
    return [s["asset"] for s in LOCK]


def test_every_lock_line_names_a_block_and_a_phrase():
    for spec in LOCK:
        assert spec.get("block"), spec
        assert spec.get("on"), spec
        assert spec.get("asset"), spec


def test_the_dead_fp_code_editor_line_is_gone():
    # Материала с таким id нет ни в индексе, ни на диске: строка только
    # писала в журнал «нет донора» и не двигала ничего.
    assert "fp_code_editor" not in _assets()
    assert "fp_code_editor" not in PINS["prefer"]


def test_the_two_black_clips_under_the_b4_numbers_are_replaced():
    # steelglow давал 0.8 % видимого кадра, charcoalash — 0.2 %: под числами
    # b4 четыре с половиной секунды стоял чёрный экран с субтитром.
    b4 = [s["asset"] for s in LOCK if s["block"] == "b4"]
    assert M + "steelglow" not in b4
    assert M + "charcoalash" not in b4
    assert M + "slateiron" in b4
    assert M + "voidpulse" in b4
    # ironrust ярче, но по phash это тот же цех, что и pipes на «Трубах».
    assert M + "ironrust" not in b4


def test_the_black_clips_cannot_come_back_through_prefer():
    for asset in (M + "steelglow", M + "charcoalash"):
        assert asset not in PINS["prefer"], asset
        assert asset in PINS["deny"], asset


def test_the_replacement_clips_are_no_longer_denied():
    for asset in (M + "slateiron", M + "voidpulse"):
        assert asset not in PINS["deny"], asset
        assert asset in PINS["prefer"], asset


def test_the_enumeration_items_each_name_their_own_material():
    # «Погода. Крыло самолёта. Трубы в доме. Ток крови.» — четыре реплики,
    # четыре разных кадра. Раньше b5b и b5d сливались с соседом, и на
    # «Трубы в доме» стояло крыло самолёта.
    want = {"b5b": M + "weather", "b5c": M + "wing",
            "b5d": M + "pipes", "b5e": M + "blood"}
    got = {s["block"]: s["asset"] for s in LOCK if s["block"] in want}
    assert got == want


def test_the_clay_stamp_keeps_its_phrase():
    stamp = [s for s in LOCK if s["asset"] == M + "stamp"]
    assert len(stamp) == 1
    assert stamp[0]["block"] == "b6"
    assert "не берёт" in stamp[0]["on"]
    assert stamp[0]["plaque"] == "REJECTED"


def test_every_footage_shot_of_the_approved_cut_is_pinned():
    # Заморозка: всё, что стояло в прогоне 181 и остаётся, названо в замке.
    frozen = {M + n for n in (
        "frostscan", "deepcoil", "codeglow", "lean", "blueember", "cyanrain",
        "tealmister", "fluids", "wing", "blood", "nightstatic", "stamp", "city")}
    assert frozen <= set(_assets())


def test_no_asset_is_named_by_two_lock_lines():
    """``reuse: True`` does not make two lines safe — it makes QC-5 certain.

    Круг 60 упал на QC-5: b5 нёс две строки на tealmister («Называются» и
    «Страшное», вторая с ``reuse: True``). Флаг только пропускает шаг, который
    забирает актив у прежнего слота — он не мешает второй записи нести те же
    ``phashes``, что и первой. Естественный сплит b5 на два соседних кадра уже
    выходил из ОДНОГО принятого слота P8 безо всякого замка; вторая строка
    была лишней и только заводила дубль.
    """
    seen: dict[str, dict] = {}
    for spec in LOCK:
        prev = seen.get(spec["asset"])
        assert prev is None, (spec["asset"], prev, spec)
        seen[spec["asset"]] = spec


@pytest.mark.parametrize("asset", sorted({s["asset"] for s in LOCK}))
def test_every_pinned_asset_exists_in_the_index(asset):
    index = json.load(open("cache/footage_index.json", encoding="utf-8"))
    assert asset in {i["id"] for i in index["items"]}


def test_no_two_pinned_clips_are_the_same_shot():
    """QC-5 ловит визуальные дубли — но уже в готовом ролике, через прогон.

    На круге 59 в b4 встал ironrust: по яркости и по миниатюре он подходил,
    а по phash отличался от pipes — кадра «Трубы в доме» — на четыре бита при
    пороге восемь. Это один и тот же цех, снятый чуть иначе. Замок такое
    обязан отсекать у себя, а не в Actions девять минут спустя.
    """
    from src.lib.phash import DEFAULT_THRESHOLD, video_is_duplicate

    index = json.load(open("cache/footage_index.json", encoding="utf-8"))
    by = {i["id"]: i for i in index["items"]}

    def hashes(asset: str) -> list[str]:
        row = by[asset]
        return list(row.get("phashes") or [row["phash"]])

    pinned = sorted({s["asset"] for s in LOCK})
    clashes = [
        (a, b)
        for i, a in enumerate(pinned)
        for b in pinned[i + 1:]
        if video_is_duplicate(hashes(a), hashes(b), DEFAULT_THRESHOLD)
    ]
    assert clashes == [], clashes
