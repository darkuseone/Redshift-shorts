"""Появление аватара короче §3.5 не доходит до кадра.

0050 r61: `avatar_request.json` нёс сегмент в 0.256 сек («Lean проверяет»),
и ведущий на 48.83 выпрыгивал в кадр на четверть секунды. Заказчик: «на 49
секунде аватар выпрыгивает и исчезает быстро, так быть не должно».

Ни один из проходов P5 не был виноват целиком: перебивка §7.4.3 срезала хвост,
а оставшийся огрызок никто не перемерил. Проверяем не проход, а итог.
"""
from src.p5_replan.replanner import Slot, _heal_stub_appearances


def _avatar(start, end, block="b6"):
    return Slot(index=0, start=start, end=end, kind="avatar", block_id=block,
                role="twist", mode="A")


def _footage(start, end, block="b6", asset_role="interstitial"):
    return Slot(index=0, start=start, end=end, kind="footage", block_id=block,
                role="twist", mode="C", needs_asset=True, asset_role=asset_role)


def test_a_stub_merges_with_its_neighbour_through_the_interstitial():
    # Ровно случай 0050: 0.26 сек, перебивка 1.2 сек, затем 4.92 сек.
    slots = [_footage(44.36, 48.83, block="b5e", asset_role="broll"),
             _avatar(48.83, 49.09),
             _footage(49.09, 50.29),
             _avatar(50.29, 55.21)]
    notes: list[str] = []
    out = _heal_stub_appearances(slots, 3.0, 12.0, notes)
    kinds = [(s.kind, round(s.start, 2), round(s.end, 2)) for s in out]
    assert kinds == [("footage", 44.36, 48.83), ("avatar", 48.83, 55.21)]
    assert any("слито" in n for n in notes)


def test_a_stub_that_cannot_merge_becomes_footage():
    # Сосед слишком длинный: вместе они вышли бы за 12 сек (§3.5).
    slots = [_avatar(10.0, 10.3),
             _footage(10.3, 11.5),
             _avatar(11.5, 23.0)]
    notes: list[str] = []
    out = _heal_stub_appearances(slots, 3.0, 12.0, notes)
    assert [s.kind for s in out] == ["footage", "footage", "avatar"]
    assert out[0].needs_asset is True
    assert any("отдано под футаж" in n for n in notes)


def test_a_lone_stub_with_no_neighbour_becomes_footage():
    slots = [_avatar(10.0, 11.0), _footage(11.0, 20.0, asset_role="broll")]
    out = _heal_stub_appearances(slots, 3.0, 12.0, [])
    assert [s.kind for s in out] == ["footage", "footage"]


def test_a_legal_appearance_is_left_alone():
    slots = [_avatar(10.0, 14.0), _footage(14.0, 15.2), _avatar(15.2, 19.0)]
    out = _heal_stub_appearances(slots, 3.0, 12.0, [])
    assert [(s.kind, s.start, s.end) for s in out] == [
        ("avatar", 10.0, 14.0), ("footage", 14.0, 15.2), ("avatar", 15.2, 19.0)]


def test_two_stubs_in_a_row_are_both_healed():
    slots = [_avatar(0.0, 0.4), _footage(0.4, 1.6), _avatar(1.6, 2.0),
             _footage(2.0, 3.2), _avatar(3.2, 9.0)]
    out = _heal_stub_appearances(slots, 3.0, 12.0, [])
    assert all(s.kind != "avatar" or s.end - s.start >= 3.0 for s in out)
