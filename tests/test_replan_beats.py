"""Карта битов и правило эскалации: Q3.3 (§6.1 R-1/R-2, §6.5).

`script_playbook.md` описывает пять битов, P0 их валидирует — а до монтажа
карта не доезжала: в `edit_plan` не было поля `beat`, и `assemble` решал по
`role`. Роль говорит о содержании блока, бит — о месте в петле: «evidence»
бывает и затяжкой, и ответом.

Второе — эскалация. На 0042 `payoff`-кадром был `text-fullscreen/blur-out-up`,
тот же приём, что и двумя кадрами раньше. Правило §6.5 требует, чтобы ответ
отличался от затяжки **классом**, а не только id.
"""

from __future__ import annotations

import pytest

from src.lib.beats import (
    BEATS, HIT_MAX_SEC, annotate_slots, answer_block_index, beat_by_block,
    beat_for_slot,
)
from src.lib.templates import Template, TemplateCatalog
from src.lib.template_picker import ScenarioIndex, TemplatePicker
from src.p11_assemble.assemble import _Escalation


def _blocks(*roles, answers=None):
    out = []
    for i, role in enumerate(roles, start=1):
        block = {"id": f"b{i}", "role": role, "text": f"текст {i}"}
        if answers == i:
            block["answers_hook"] = True
        out.append(block)
    return out


class TestTheBeatMapReadsTheLoopNotTheRoles:

    def test_the_five_beats_are_the_playbook_five(self):
        assert BEATS == ("hit", "question", "stretch", "payoff", "residue")

    def test_the_canonical_shape(self):
        blocks = _blocks("hook", "setup", "evidence", "develop", "twist", "cta")
        assert beat_by_block(blocks) == {
            "b1": "hit", "b2": "question", "b3": "stretch",
            "b4": "stretch", "b5": "payoff", "b6": "residue",
        }

    def test_an_explicit_answers_hook_beats_the_twist_role(self):
        """Пометка сценариста сильнее роли — так же, как её читает P0."""
        blocks = _blocks("hook", "setup", "evidence", "twist", "cta", answers=3)
        mapping = beat_by_block(blocks)
        assert mapping["b3"] == "payoff"
        # После ответа — осадок, даже если роль называется «twist».
        assert mapping["b4"] == "residue"

    def test_a_script_without_an_answer_still_gets_a_payoff(self):
        """P0 предупредит отдельно; монтажу всё равно нужно знать, где ответ."""
        blocks = _blocks("hook", "setup", "evidence", "cta")
        mapping = beat_by_block(blocks)
        assert mapping["b3"] == "payoff"

    def test_no_blocks_no_map(self):
        assert beat_by_block([]) == {}

    def test_the_answer_index_is_the_one_p0_uses(self):
        blocks = _blocks("hook", "setup", "twist", "cta")
        assert answer_block_index(blocks) == 2
        assert answer_block_index(_blocks("hook", "setup")) is None

    def test_a_long_hook_turns_into_a_question_partway_through(self):
        """§6.1 запрещает на ударе статичную голову — но не на всю четверть ролика."""
        assert beat_for_slot(0.0, "b1", "hit") == "hit"
        assert beat_for_slot(HIT_MAX_SEC - 0.01, "b1", "hit") == "hit"
        assert beat_for_slot(HIT_MAX_SEC + 0.5, "b1", "hit") == "question"

    def test_other_beats_do_not_drift_with_time(self):
        assert beat_for_slot(30.0, "b4", "stretch") == "stretch"


class TestSlotsCarryTheBeat:

    def test_slots_are_annotated_and_counted(self):
        blocks = _blocks("hook", "setup", "evidence", "twist", "cta")
        slots = [{"index": i, "start": s, "block_id": b}
                 for i, (s, b) in enumerate(
                     [(0.0, "b1"), (2.0, "b1"), (4.0, "b2"), (8.0, "b3"),
                      (14.0, "b4"), (20.0, "b5")])]
        counts = annotate_slots(slots, blocks)
        assert [s["beat"] for s in slots] == [
            "hit", "question", "question", "stretch", "payoff", "residue"]
        assert counts == {"hit": 1, "question": 2, "stretch": 1,
                          "payoff": 1, "residue": 1}

    def test_a_slot_of_an_unknown_block_falls_back_to_stretch(self):
        slots = [{"index": 0, "start": 0.0, "block_id": "b99"}]
        annotate_slots(slots, _blocks("hook", "cta"))
        assert slots[0]["beat"] == "stretch"

    def test_it_works_on_dataclass_slots_too(self):
        from src.p5_replan.replanner import Slot

        slot = Slot(index=0, start=0.0, end=1.0, kind="avatar",
                    block_id="b1", role="hook", mode="A")
        annotate_slots([slot], _blocks("hook", "cta"))
        assert slot.beat == "hit"
        assert slot.to_dict()["beat"] == "hit"


class TestTheEscalationRule:

    def test_two_stretch_shots_in_a_row_may_not_share_a_renderer(self):
        esc = _Escalation()
        esc.note("stretch", "hero-split")
        assert esc.bans("stretch") == frozenset({"hero-split"})

    def test_the_first_stretch_shot_bans_nothing(self):
        assert _Escalation().bans("stretch") == frozenset()

    def test_a_beat_change_clears_the_adjacency_ban(self):
        esc = _Escalation()
        esc.note("question", "hero-type-slab")
        assert esc.bans("stretch") == frozenset()

    def test_the_payoff_is_barred_from_every_stretch_renderer(self):
        """§6.5: ответ обязан отличаться классом, а не только id."""
        esc = _Escalation()
        esc.note("stretch", "hero-split")
        esc.note("stretch", "hero-knockout")
        esc.note("payoff", "")
        assert esc.bans("payoff") == frozenset({"hero-split", "hero-knockout"})

    def test_beats_outside_the_rule_are_free(self):
        esc = _Escalation()
        esc.note("stretch", "hero-split")
        assert esc.bans("residue") == frozenset()
        assert esc.bans("hit") == frozenset()

    def test_an_empty_renderer_is_not_a_ban(self):
        esc = _Escalation()
        esc.note("stretch", "")
        assert esc.bans("stretch") == frozenset()


class TestThePickerHonoursTheBan:

    def test_a_banned_renderer_is_not_returned(self, cfg):
        catalog = TemplateCatalog.load(cfg)
        picker = TemplatePicker(catalog, ScenarioIndex.load(cfg, catalog=catalog))
        free, _ = picker.pick("text-fullscreen", variant="A", seed=7)
        banned, _ = picker.pick("text-fullscreen", variant="A", seed=7,
                                exclude_renderers={free.renderer})
        # Либо приём сменился, либо в категории не осталось ничего другого —
        # запрет снимается, но молча подсунуть тот же класс он не может, пока
        # альтернатива есть.
        alternatives = {t.renderer for t in catalog.by_category("text-fullscreen")
                        if t.is_active} - {free.renderer}
        if alternatives:
            assert banned.renderer != free.renderer

    def test_banning_everything_still_returns_a_template(self, cfg):
        """Кадр без приёма хуже повторённого приёма — запрет снимается."""
        catalog = TemplateCatalog.load(cfg)
        picker = TemplatePicker(catalog, ScenarioIndex.load(cfg, catalog=catalog))
        everything = {t.renderer for t in catalog.by_category("text-fullscreen")}
        chosen, _ = picker.pick("text-fullscreen", variant="A", seed=3,
                                exclude_renderers=everything)
        assert isinstance(chosen, Template)


class TestTheReferenceVideoObeysTheRule:
    """DoD Q3.3, замер по собранному плану 0042 (не по замыслу).

    Оговорка честности: обратный прогон с отключённым правилом даёт тот же
    план. На 0042 после Q1/Q2 приёмов, несущих рендерер, всего пять-семь, и
    они уже расходятся сами. Эти два теста стерегут результат, а работу
    самого правила проверяют `TestTheEscalationRule` и
    `TestThePickerHonoursTheBan`.
    """

    @pytest.mark.parametrize("variant", ["A", "B"])
    def test_payoff_renderer_is_not_a_stretch_renderer(self, cfg, variant):
        import json

        path = cfg.repo_root / "work" / "redshift_0042" / f"edit_plan_{variant}.json"
        if not path.exists():
            pytest.skip("нет собранного плана 0042 — замер делается на живом прогоне")
        shots = json.loads(path.read_text(encoding="utf-8"))["shots"]
        rows = []
        for shot in shots:
            renderer = (shot.get("renderer")
                        or (shot.get("hero") or {}).get("renderer") or "")
            if renderer:
                rows.append((str(shot.get("beat") or ""), renderer))
        stretch = {r for b, r in rows if b == "stretch"}
        payoff = {r for b, r in rows if b == "payoff"}
        assert not (payoff & stretch), f"ответ повторяет затяжку: {payoff & stretch}"

    @pytest.mark.parametrize("variant", ["A", "B"])
    def test_no_two_adjacent_stretch_shots_share_a_renderer(self, cfg, variant):
        import json

        path = cfg.repo_root / "work" / "redshift_0042" / f"edit_plan_{variant}.json"
        if not path.exists():
            pytest.skip("нет собранного плана 0042 — замер делается на живом прогоне")
        shots = json.loads(path.read_text(encoding="utf-8"))["shots"]
        rows = [(str(s.get("beat") or ""),
                 s.get("renderer") or (s.get("hero") or {}).get("renderer") or "")
                for s in shots]
        rows = [(b, r) for b, r in rows if r]
        repeats = [rows[i] for i in range(1, len(rows))
                   if rows[i] == rows[i - 1] and rows[i][0] == "stretch"]
        assert not repeats, f"приём в затяжке повторился подряд: {repeats}"
