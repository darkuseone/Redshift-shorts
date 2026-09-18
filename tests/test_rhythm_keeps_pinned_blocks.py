"""Кадр, чей материал назван заявкой, не сливается с соседом.

«Погода. Крыло самолёта. Трубы в доме. Ток крови.» — четыре реплики по
полсекунды. Правило «шот не короче двух секунд» сводило их в два кадра, и на
«Трубы в доме» оставалось крыло самолёта, а на «Погоду» — вода. Кадр короче
нормы — изъян ритма; кадр не о том, что звучит, — изъян смысла, и он дороже.
"""
import copy

from src.p11_assemble.assemble import MIN_FOOTAGE_SHOT_SEC, enforce_slot_rhythm


def _run():
    return [
        {"index": 0, "kind": "footage", "block_id": "b5", "start": 0.0, "end": 3.0},
        {"index": 1, "kind": "footage", "block_id": "b5b", "start": 3.0, "end": 3.9},
        {"index": 2, "kind": "footage", "block_id": "b5c", "start": 3.9, "end": 4.8},
        {"index": 3, "kind": "footage", "block_id": "b5d", "start": 4.8, "end": 5.7},
        {"index": 4, "kind": "footage", "block_id": "b5e", "start": 5.7, "end": 9.0},
    ]


def _blocks(slots):
    return [s["block_id"] for s in slots]


def test_without_the_lock_the_enumeration_loses_items():
    slots = _run()
    dropped = enforce_slot_rhythm(slots, total=9.0)
    # Пять реплик — три кадра: двум items картинки не досталось, и их слова
    # звучат поверх чужого материала.
    assert dropped
    assert len(_blocks(slots)) < 5


def test_a_pinned_item_keeps_its_own_shot():
    slots = _run()
    enforce_slot_rhythm(slots, total=9.0,
                        keep_blocks={"b5b", "b5c", "b5d", "b5e"})
    assert _blocks(slots) == ["b5", "b5b", "b5c", "b5d", "b5e"]


def test_a_pinned_item_is_not_swallowed_by_a_short_neighbour():
    slots = _run()
    enforce_slot_rhythm(slots, total=9.0, keep_blocks={"b5d"})
    assert "b5d" in _blocks(slots)


def test_an_unpinned_short_shot_is_still_merged():
    slots = _run()
    enforce_slot_rhythm(slots, total=9.0, keep_blocks={"b5d"})
    # b5b/b5c заявкой не названы — правило двух секунд для них в силе
    assert "b5c" not in _blocks(slots)


def test_the_shots_still_run_edge_to_edge():
    slots = _run()
    enforce_slot_rhythm(slots, total=9.0, keep_blocks={"b5b", "b5d"})
    for left, right in zip(slots, slots[1:]):
        assert abs(float(left["end"]) - float(right["start"])) < 1e-6
    assert abs(float(slots[-1]["end"]) - 9.0) < 1e-6


def test_a_long_pinned_shot_is_untouched():
    slots = [
        {"index": 0, "kind": "footage", "block_id": "b3", "start": 0.0, "end": 3.0},
        {"index": 1, "kind": "footage", "block_id": "b4", "start": 3.0, "end": 6.0},
    ]
    before = [(s["block_id"], s["start"], s["end"]) for s in copy.deepcopy(slots)]
    enforce_slot_rhythm(slots, total=6.0, keep_blocks={"b3", "b4"})
    assert [(s["block_id"], s["start"], s["end"]) for s in slots] == before
    assert MIN_FOOTAGE_SHOT_SEC == 2.0
