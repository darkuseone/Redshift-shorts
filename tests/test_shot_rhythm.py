"""Ритм монтажа: кадры встык, без перебивок короче двух секунд.

Браки 0050, из-за которых правила и появились: длительность кадра росла
отдельно от старта, так что объявленные две секунды накрывались следующим
кадром через 1.29 с; между блоками светили дыры; аватар вспыхивал на 0.26 с;
плашка AIRFOIL переживала своё крыло и висела над трубами.
"""

from __future__ import annotations

import pytest

from src.p11_assemble.assemble import (
    MIN_AVATAR_SHOT_SEC, MIN_FOOTAGE_SHOT_SEC, clamp_plaques_to_shots,
    close_slot_holes, enforce_slot_rhythm,
)


def _slot(start, end, kind="footage", block=None, **extra):
    return {"start": start, "end": end, "duration": round(end - start, 3),
            "kind": kind, "block_id": block, **extra}


class TestKadryVstyk:

    def test_a_hole_between_shots_is_closed(self):
        slots = [_slot(0.0, 2.0), _slot(2.5, 5.0)]
        close_slot_holes(slots, total=6.0)
        assert slots[0]["end"] == 2.5
        assert slots[1]["end"] == 6.0
        assert slots[0]["duration"] == 2.5

    def test_an_overlap_is_trimmed_to_the_next_start(self):
        """Кадр, объявивший две секунды, а накрытый через 1.29, врёт плану."""
        slots = [_slot(40.59, 42.59), _slot(41.88, 43.88)]
        close_slot_holes(slots, total=46.0)
        assert slots[0]["end"] == 41.88
        assert slots[0]["duration"] == pytest.approx(1.29, abs=1e-3)


class TestPerebivkiKorocheDvuhSekund:

    def test_a_short_cutaway_borrows_from_its_neighbours(self):
        slots = [_slot(0.0, 6.0, "avatar", "b1"),
                 _slot(6.0, 7.4, "footage", "b2"),
                 _slot(7.4, 13.0, "avatar", "b3")]
        enforce_slot_rhythm(slots, total=13.0)
        insert = next(s for s in slots if s["block_id"] == "b2")
        assert insert["duration"] >= MIN_FOOTAGE_SHOT_SEC - 1e-3
        # Речь не двигается — двигается только граница склейки.
        assert slots[0]["start"] == 0.0 and slots[-1]["end"] == 13.0

    def test_a_neighbour_is_never_starved_below_its_own_floor(self):
        slots = [_slot(0.0, 1.7, "avatar", "b1"),
                 _slot(1.7, 3.0, "footage", "b2")]
        enforce_slot_rhythm(slots, total=3.0)
        avatar = [s for s in slots if s["kind"] == "avatar"]
        assert not avatar or avatar[0]["duration"] >= MIN_AVATAR_SHOT_SEC - 1e-3

    def test_a_run_of_short_cutaways_merges_into_long_ones(self):
        """Четыре удара перечисления в 3.8 с четырьмя кадрами не показать."""
        slots = [_slot(40.59, 41.88, "footage", "b5b"),
                 _slot(41.88, 43.14, "footage", "b5c"),
                 _slot(43.14, 44.36, "footage", "b5d"),
                 _slot(44.36, 48.49, "footage", "b5e")]
        dropped = enforce_slot_rhythm(slots, total=48.49)
        assert dropped
        for slot in slots:
            assert slot["duration"] >= MIN_FOOTAGE_SHOT_SEC - 1e-3, slot
        # Группа остаётся на материале своего первого кадра — того, на чьё
        # слово она начиналась.
        assert slots[0]["block_id"] == "b5b"

    def test_a_face_flash_is_dropped_outright(self):
        slots = [_slot(0.0, 4.0, "footage", "b1"),
                 _slot(4.0, 4.26, "avatar", "b6"),
                 _slot(4.26, 8.0, "footage", "b7")]
        dropped = enforce_slot_rhythm(slots, total=8.0)
        assert "b6" in dropped
        assert all(s["kind"] != "avatar" for s in slots)
        assert slots[0]["end"] == slots[1]["start"]

    def test_a_cutaway_between_two_avatars_is_left_alone_when_nothing_can_give(self):
        """Длина такой вставки — длина куска речи, а не решение монтажа."""
        slots = [_slot(0.0, 1.6, "avatar", "b1"),
                 _slot(1.6, 3.0, "footage", "b2"),
                 _slot(3.0, 4.6, "avatar", "b3")]
        enforce_slot_rhythm(slots, total=4.6)
        assert [s["kind"] for s in slots] == ["avatar", "footage", "avatar"]

    def test_nothing_is_lost_from_the_timeline(self):
        slots = [_slot(0.0, 1.2, "fullscreen_text", "b1"),
                 _slot(1.2, 2.3, "footage", "b2"),
                 _slot(2.3, 3.1, "footage", "b3"),
                 _slot(3.1, 9.0, "avatar", "b4")]
        enforce_slot_rhythm(slots, total=9.0)
        assert slots[0]["start"] == 0.0
        assert slots[-1]["end"] == 9.0
        for a, b in zip(slots, slots[1:]):
            assert a["end"] == b["start"]


class TestPlashkaNePerezhivaetSvoyKadr:

    def _shots(self):
        return [{"start": 41.88, "end": 45.14, "block_id": "b5c"},
                {"start": 45.14, "end": 48.49, "block_id": "b5e"}]

    def test_a_plaque_is_cut_to_its_shot(self):
        overlays = [{"type": "plaque", "block_id": "b5c",
                     "start": 41.88, "end": 47.0, "params": {"text": "AIRFOIL"}}]
        clamp_plaques_to_shots(overlays, self._shots())
        assert overlays[0]["end"] == 45.14

    def test_a_plaque_whose_shot_is_gone_is_dropped(self):
        overlays = [{"type": "plaque", "block_id": "b5d",
                     "start": 43.14, "end": 45.14, "params": {"text": "VALVES"}}]
        clamp_plaques_to_shots(overlays, self._shots(), dropped_blocks=["b5d"])
        assert overlays == []

    def test_other_overlays_are_not_touched(self):
        overlays = [{"type": "source_card", "block_id": "b5c",
                     "start": 0.0, "end": 60.0}]
        clamp_plaques_to_shots(overlays, self._shots())
        assert overlays[0]["end"] == 60.0

    def test_a_plaque_squeezed_to_nothing_is_dropped(self):
        overlays = [{"type": "plaque", "block_id": "b5c",
                     "start": 44.9, "end": 45.1, "params": {"text": "AIRFOIL"}}]
        clamp_plaques_to_shots(overlays, self._shots())
        assert overlays == []
