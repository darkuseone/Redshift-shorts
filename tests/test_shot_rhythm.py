"""Ритм монтажа: кадры встык, без перебивок короче двух секунд.

Браки 0050, из-за которых правила и появились: длительность кадра росла
отдельно от старта, так что объявленные две секунды накрывались следующим
кадром через 1.29 с; между блоками светили дыры; аватар вспыхивал на 0.26 с;
плашка AIRFOIL переживала своё крыло и висела над трубами.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.p11_assemble.assemble import (
    MIN_FOOTAGE_SHOT_SEC, MIN_FULLSCREEN_SHOT_SEC, clamp_plaques_to_shots,
    close_slot_holes, enforce_slot_rhythm,
)


REPO = Path(__file__).resolve().parents[1]


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

    def test_a_short_cutaway_borrows_from_the_footage_on_its_left(self):
        slots = [_slot(0.0, 6.0, "footage", "b1"),
                 _slot(6.0, 7.4, "footage", "b2"),
                 _slot(7.4, 13.0, "avatar", "b3")]
        enforce_slot_rhythm(slots, total=13.0)
        insert = next(s for s in slots if s["block_id"] == "b2")
        assert insert["duration"] >= MIN_FOOTAGE_SHOT_SEC - 1e-3
        # Речь не двигается — двигается только граница склейки.
        assert slots[0]["start"] == 0.0 and slots[-1]["end"] == 13.0

    def test_a_cutaway_never_borrows_from_the_next_shot(self):
        """Иначе кадр переезжает через следующее слово.

        На 0050 крыло, дотянувшись до двух секунд за счёт крови, стояло на
        экране, когда диктор уже говорил «ток крови»: подпись PLASMA висела
        над крылом, а кровь приезжала после своего слова.
        """
        slots = [_slot(38.63, 41.88, "footage", "fluids"),
                 _slot(41.88, 43.14, "footage", "wing"),
                 _slot(43.14, 48.49, "footage", "blood")]
        enforce_slot_rhythm(slots, total=48.49)
        blood = [s for s in slots if s["block_id"] == "blood"]
        assert blood, "кровь не должна была исчезнуть"
        # Крыло добрало недостающее у жидкости слева, а не у крови справа.
        assert blood[0]["start"] <= 43.14 + 1e-3
        wing = next(s for s in slots if s["block_id"] == "wing")
        assert wing["start"] < 41.88

    def test_a_neighbour_is_never_starved_below_its_own_floor(self):
        slots = [_slot(0.0, 1.2, "fullscreen_text", "b1"),
                 _slot(1.2, 3.0, "footage", "b2")]
        enforce_slot_rhythm(slots, total=3.0)
        card = next(s for s in slots if s["kind"] == "fullscreen_text")
        assert card["duration"] >= MIN_FULLSCREEN_SHOT_SEC - 1e-3

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

    def test_a_face_flash_is_left_alone_because_its_clip_is_frozen(self):
        """Аватар не трогаем даже ради правила: его окна — платный контракт.

        Сборка один раз сняла вспышку лица в 0.26 с, P6 переписал заявку
        ``avatar_request.json`` на три сегмента вместо пяти, и заморозка окон
        развалилась: следующий прогон потребовал бы новой генерации HeyGen.
        Такая вспышка лечится только новым рендером — решением заказчика.
        """
        slots = [_slot(0.0, 4.0, "footage", "b1"),
                 _slot(4.0, 4.26, "avatar", "b6"),
                 _slot(4.26, 8.0, "footage", "b7")]
        dropped = enforce_slot_rhythm(slots, total=8.0)
        assert "b6" not in dropped
        avatar = [s for s in slots if s["kind"] == "avatar"]
        assert len(avatar) == 1
        assert (avatar[0]["start"], avatar[0]["end"]) == (4.0, 4.26)

    def test_a_cutaway_never_borrows_from_an_avatar(self):
        """Занять у аватара — значит сдвинуть окно замороженного webm."""
        slots = [_slot(0.0, 6.0, "avatar", "b1"),
                 _slot(6.0, 7.4, "footage", "b2"),
                 _slot(7.4, 13.0, "avatar", "b3")]
        enforce_slot_rhythm(slots, total=13.0)
        assert (slots[0]["start"], slots[0]["end"]) == (0.0, 6.0)
        assert (slots[-1]["start"], slots[-1]["end"]) == (7.4, 13.0)
        # Вставка остаётся короткой: удлинить её без нового аватара нечем.
        insert = next(s for s in slots if s["block_id"] == "b2")
        assert insert["duration"] == pytest.approx(1.4, abs=1e-3)

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


class TestOdinMaterialNeStavitsyaDvazhdyPodryad:
    """``same_asset_max_slots: 1``: два кадра на одном клипе — это один кадр.

    Заполнители зазоров вокруг аватара идентификатора материала не несут, и
    на 0050 они дважды подряд ставили один и тот же файл: склейки между ними
    не видно, а закон считает их двумя кадрами.
    """

    def test_two_shots_on_one_clip_become_one(self):
        slots = [_slot(36.63, 38.63, "footage", "b5", file="/w/teal_2370.mp4"),
                 _slot(38.63, 41.88, "footage", "b5", file="/w/teal_2370.mp4"),
                 _slot(41.88, 44.36, "footage", "b5c", asset_id="wing")]
        enforce_slot_rhythm(slots, total=44.36)
        assert len(slots) == 2
        assert (slots[0]["start"], slots[0]["end"]) == (36.63, 41.88)

    def test_the_block_keeps_its_plaque_after_such_a_merge(self):
        """Блок никуда не делся — снимать его подпись не за что."""
        slots = [_slot(36.63, 38.63, "footage", "b5", file="/w/teal.mp4"),
                 _slot(38.63, 41.88, "footage", "b5", file="/w/teal.mp4")]
        assert enforce_slot_rhythm(slots, total=41.88) == []

    def test_different_material_is_left_alone(self):
        slots = [_slot(24.80, 27.25, "footage", "b4", asset_id="steelglow"),
                 _slot(27.25, 29.37, "footage", "b4", asset_id="charcoalash")]
        enforce_slot_rhythm(slots, total=29.37)
        assert len(slots) == 2

    def test_the_same_clip_across_an_avatar_is_not_merged(self):
        """Между ними лицо — это не один кадр, а два появления материала."""
        slots = [_slot(49.09, 50.29, "footage", "b6", file="/w/lean.mp4"),
                 _slot(50.29, 55.21, "avatar", "b6"),
                 _slot(55.21, 56.61, "footage", "b6", file="/w/lean.mp4")]
        enforce_slot_rhythm(slots, total=56.61)
        assert [s["kind"] for s in slots] == ["footage", "avatar", "footage"]


class TestPlashkaNePerezhivaetSvoyKadr:

    def _shots(self):
        return [{"start": 41.88, "end": 45.14, "block_id": "b5c"},
                {"start": 45.14, "end": 48.49, "block_id": "b5e"}]

    def _plaque(self, start, end, text="AIRFOIL"):
        # Ровно те ключи, что кладёт P11: block_id среди них нет.
        return {"type": "plaque", "start": start, "end": end,
                "template": "lower-thirds/dark-card", "params": {"text": text}}

    def test_a_plaque_is_cut_to_its_shot(self):
        overlays = [self._plaque(41.88, 47.0)]
        clamp_plaques_to_shots(overlays, self._shots())
        assert overlays[0]["end"] == 45.14

    def test_the_real_plasma_lag_is_cut(self):
        """PLASMA стоял 44.36–47.86 над крылом, кровь начиналась в 45.14."""
        overlays = [self._plaque(44.36, 47.86, "PLASMA")]
        clamp_plaques_to_shots(overlays, self._shots())
        assert overlays[0]["end"] == 45.14

    def test_a_plaque_inside_its_shot_is_left_alone(self):
        overlays = [self._plaque(45.5, 47.0, "PLASMA")]
        clamp_plaques_to_shots(overlays, self._shots())
        assert overlays[0]["end"] == 47.0

    def test_a_plaque_whose_shot_is_gone_is_dropped(self):
        overlays = [self._plaque(42.0, 44.0, "VALVES")]
        clamp_plaques_to_shots(overlays, self._shots(), dropped_blocks=["b5c"])
        assert overlays == []

    def test_other_overlays_are_not_touched(self):
        overlays = [{"type": "source_card", "start": 0.0, "end": 60.0}]
        clamp_plaques_to_shots(overlays, self._shots())
        assert overlays[0]["end"] == 60.0

    def test_a_plaque_squeezed_to_nothing_is_dropped(self):
        overlays = [self._plaque(44.9, 45.1)]
        clamp_plaques_to_shots(overlays, self._shots())
        assert overlays == []


class TestTheFrozenAvatarContractSurvives:
    """Заявка на клипы — платный контракт, а не производный файл.

    Сборка, сдвинувшая окна аватара, заставила P6 переписать
    ``avatar_request.json``: пять сегментов превратились в три, вспышка в
    0.26 с растянулась до 3.13 с, заморозка окон перестала загружаться. Следом
    прогон потребовал бы новой генерации HeyGen — то есть денег.
    """

    def test_the_request_still_lists_five_frozen_segments(self):
        request = json.loads(
            (REPO / "assets" / "avatar_clips" / "redshift_0050"
             / "avatar_request.json").read_text(encoding="utf-8"))
        segments = request["segments"]
        assert [s["index"] for s in segments] == [0, 1, 2, 3, 4]
        assert request["avatar_id"] == "99ccc74e764947c394cd4ef210960a6f"

    def test_every_segment_has_the_webm_it_promises(self):
        clips = REPO / "assets" / "avatar_clips" / "redshift_0050"
        request = json.loads((clips / "avatar_request.json").read_text(encoding="utf-8"))
        for segment in request["segments"]:
            assert (clips / segment["expected_clip"]).is_file(), segment["expected_clip"]

    def test_the_rhythm_pass_moves_no_avatar_window(self):
        request = json.loads(
            (REPO / "assets" / "avatar_clips" / "redshift_0050"
             / "avatar_request.json").read_text(encoding="utf-8"))
        slots = [_slot(0.0, 4.575, "footage", "b1")]
        for segment in request["segments"]:
            slots.append(_slot(float(segment["start"]), float(segment["end"]),
                               "avatar", segment["block_id"]))
            slots.append(_slot(float(segment["end"]),
                               float(segment["end"]) + 1.2, "footage", "gap"))
        total = slots[-1]["end"]
        before = [(s["start"], s["end"]) for s in slots if s["kind"] == "avatar"]
        enforce_slot_rhythm(slots, total=total)
        after = [(s["start"], s["end"]) for s in slots if s["kind"] == "avatar"]
        assert after == before
