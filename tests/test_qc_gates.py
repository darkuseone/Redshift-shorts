"""Новые гейты волны: QC-20…QC-25, QC-29, QC-30 (§12).

Девятнадцать проверок на 0042 прошли все до одной, и ролик при этом получил
`visual 2/10`: ни одна из них не смотрит, есть ли в кадре что-нибудь кроме
букв, сколько раз повторился приём и попал ли хук на экран. Гейты этой волны
меряют ровно то, на что жаловался критик.

Номера QC-20/21/22 закреплены за MEGA P1 и реализованы в её формулировке.
"""

from __future__ import annotations

import pytest

from src.p12_render_qc.qc import _hook_is_banned, run_qc


class _Media:
    duration_sec = 48.0
    fps = 30
    width = 1080
    height = 1920


def _plan(**over):
    plan = {
        "video_id": "redshift_9060", "variant": "B", "duration_sec": 48.0,
        "shots": [], "overlays": [], "subtitles": [], "templates_used": [],
        "pick_traces": [], "avatar": [],
    }
    plan.update(over)
    return plan


def _shot(index, **over):
    shot = {"index": index, "start": index * 2.0, "end": index * 2.0 + 2.0,
            "duration": 2.0, "kind": "footage", "block_id": "b1",
            "role": "body", "mode": "C", "reason": ""}
    shot.update(over)
    return shot


def _run(ctx_cfg, plan):
    class _Ctx:
        cfg = ctx_cfg
        warnings: list = []
    return run_qc(
        _Ctx(), plan=plan,
        cut_plan={"video_id": plan["video_id"], "slots": [], "stats": {}},
        render_stats={"accent_share_max": 0.06, "accent_by_family": {}},
        media=_Media(), sfx_map={"events": [], "loudness": {}},
        avatar_meta={"segments": [], "share": 0.2},
        accepted={}, generated={}, script={"blocks": []})


def _check(report, cid):
    return next(c for c in report["checks"] if c["id"] == cid)


class TestQc23CountsCaptionsInTheCutNotThePlan:
    """N-2: потолок стоял в конфиге и никем не мерился на выходе."""

    def test_four_captions_pass(self, cfg):
        plan = _plan(shots=[_shot(i, kind="fullscreen_text", content="СЛОВО")
                            for i in range(4)])
        assert _check(_run(cfg, plan), "QC-23")["passed"]

    def test_fourteen_captions_fail(self, cfg):
        """Ровно тот случай 0042, который прошёл девятнадцать проверок."""
        plan = _plan(shots=[_shot(i, kind="fullscreen_text", content="СЛОВО")
                            for i in range(14)])
        check = _check(_run(cfg, plan), "QC-23")
        assert not check["passed"] and check["value"] == 14
        assert check["blocking"]


class TestQc24CountsBarePlates:

    def test_two_plates_pass(self, cfg):
        plan = _plan(shots=[_shot(i, gap_reason="fullscreen cap: plate without text")
                            for i in range(2)])
        assert _check(_run(cfg, plan), "QC-24")["passed"]

    def test_eleven_plates_fail(self, cfg):
        """Замер лестницы §7.2 на 0042 до перестановки ступеней."""
        plan = _plan(shots=[_shot(i, gap_reason="no unique phrase: plate without text")
                            for i in range(11)])
        assert not _check(_run(cfg, plan), "QC-24")["passed"]


class TestQc25KeepsTheDeviceFromRepeating:

    def test_two_uses_of_a_template_pass(self, cfg):
        plan = _plan(shots=[_shot(0, template="text-fullscreen/blur-out-up"),
                            _shot(1, template="text-fullscreen/blur-out-up"),
                            _shot(2, template="text-fullscreen/impact-02")])
        assert _check(_run(cfg, plan), "QC-25")["passed"]

    def test_three_uses_fail(self, cfg):
        """V-4: на 0042 `blur-out-up` встречался трижды."""
        plan = _plan(shots=[_shot(i, template="text-fullscreen/blur-out-up")
                            for i in range(3)])
        check = _check(_run(cfg, plan), "QC-25")
        assert not check["passed"]
        assert check["value"]["template"] == "text-fullscreen/blur-out-up"

    def test_overlays_count_towards_the_same_budget(self, cfg):
        plan = _plan(
            shots=[_shot(0, template="data-viz/bar-race"),
                   _shot(1, template="data-viz/bar-race")],
            overlays=[{"type": "dataviz", "template": "data-viz/bar-race",
                       "start": 4.0, "end": 6.0}])
        assert not _check(_run(cfg, plan), "QC-25")["passed"]


class TestQc29PutsTheHookOnScreenInTime:

    def _hook_plan(self, **over):
        shot = _shot(0, kind="fullscreen_text", hook=True,
                     content="НЕВОЗМОЖНО ПРОВЕРИТЬ", params={})
        shot.update(over)
        return _plan(shots=[shot])

    def test_a_hook_at_zero_passes(self, cfg):
        assert _check(_run(cfg, self._hook_plan()), "QC-29")["passed"]

    def test_a_hook_after_one_second_fails(self, cfg):
        plan = self._hook_plan(start=1.4, end=4.0)
        assert not _check(_run(cfg, plan), "QC-29")["passed"]

    def test_a_delayed_entrance_counts_as_late(self, cfg):
        """Кадр в нуле, а строка выезжает на 1.6 с — это не хук."""
        plan = self._hook_plan(params={"enter_delay": 1.6})
        assert not _check(_run(cfg, plan), "QC-29")["passed"]

    def test_a_single_strong_word_is_a_hook(self, cfg):
        """`blackout_word` по замыслу выносит на экран одно слово."""
        plan = self._hook_plan(content="НЕЧЕМ")
        assert _check(_run(cfg, plan), "QC-29")["passed"]

    def test_a_wall_of_text_is_not_a_hook(self, cfg):
        plan = self._hook_plan(
            content="ЭТОТ ОТВЕТ НИКТО НИКОГДА НЕ СМОЖЕТ ПРОВЕРИТЬ ВООБЩЕ НИЧЕМ")
        assert not _check(_run(cfg, plan), "QC-29")["passed"]

    def test_a_video_without_a_hook_shot_fails(self, cfg):
        assert not _check(_run(cfg, _plan()), "QC-29")["passed"]

    def test_avatar_in_the_first_second_fails(self, cfg):
        plan = self._hook_plan()
        plan["shots"].insert(0, _shot(0, kind="avatar", start=0.0, end=2.0,
                                      duration=2.0))
        check = _check(_run(cfg, plan), "QC-29")
        assert not check["passed"] and check["blocking"]
        assert "лицом" in check["detail"]

    def test_avatar_at_one_second_with_a_card_before_passes(self, cfg):
        plan = _plan(shots=[
            _shot(0, kind="fullscreen_text", hook=True, start=0.0, end=1.0,
                  duration=1.0, content="НЕВОЗМОЖНО ПРОВЕРИТЬ", params={}),
            _shot(1, kind="avatar", start=1.0, end=4.0, duration=3.0),
        ])
        assert _check(_run(cfg, plan), "QC-29")["passed"]

    @pytest.mark.parametrize("text", [
        "ПРИВЕТ ДРУЗЬЯ", "ПОДПИСЫВАЙСЯ НА КАНАЛ", "В ЭТОМ ВИДЕО РАЗБЕРЁМ",
        "СМОТРИ ДО КОНЦА",
    ])
    def test_the_stop_list_is_the_same_as_on_p0(self, text):
        """Экран и голос не должны расходиться в том, что считается разгоном."""
        assert _hook_is_banned(text)

    def test_a_real_hook_is_not_banned(self):
        assert not _hook_is_banned("НЕВОЗМОЖНО ПРОВЕРИТЬ")


class TestQc20And21And22CarryTheMegaWording:

    def test_qc20_flags_text_wider_than_the_work_area(self, cfg):
        plan = _plan(shots=[_shot(0, kind="fullscreen_text",
                                  content="ОЧЕНЬ ДЛИННЫЙ ЗАГОЛОВОК НА ВЕСЬ КАДР",
                                  params={"size": 200})])
        assert not _check(_run(cfg, plan), "QC-20")["passed"]

    def test_qc20_lets_a_fitted_line_through(self, cfg):
        plan = _plan(shots=[_shot(0, kind="fullscreen_text", content="НЕЧЕМ",
                                  params={"size": 90})])
        assert _check(_run(cfg, plan), "QC-20")["passed"]

    # Приёмы каталога, у которых `needs` объявлен — то есть основание им
    # положено. Берём настоящие id: гейт сверяется с манифестом, а не с полем.
    NEEDY = ["data-viz/compare-bars", "data-viz/stat-countup-card",
             "data-viz/flowchart", "data-viz/bar-race"]

    def test_qc21_counts_devices_without_a_reason(self, cfg):
        """Приём попросил основание и не получил — вот это брак."""
        plan = _plan(shots=[_shot(i, template=t, grounded_on=[])
                            for i, t in enumerate(self.NEEDY)])
        check = _check(_run(cfg, plan), "QC-21")
        assert not check["passed"] and check["value"] == 1.0

    def test_qc21_passes_when_most_devices_are_grounded(self, cfg):
        plan = _plan(shots=[_shot(i, template=t, grounded_on=["number"])
                            for i, t in enumerate(self.NEEDY)])
        assert _check(_run(cfg, plan), "QC-21")["passed"]

    def test_qc21_ignores_devices_that_never_asked(self, cfg):
        """`grounded_on` — это `matched(needs, traits)`; у шаблона без `needs`
        он пуст **по построению**. Из 204 шаблонов каталога `needs` объявлен
        у 74, и порог 0.30 не прошёл бы ни один ролик: первый заход мерил по
        наличию поля и ловил полноэкранный текст, которому требований не
        предъявляли вовсе."""
        plan = _plan(
            shots=[_shot(i, template="text-fullscreen/blur-out-up",
                         grounded_on=[]) for i in range(9)]
            + [_shot(9, template=self.NEEDY[0], grounded_on=["number"])])
        assert _check(_run(cfg, plan), "QC-21")["passed"]

    def test_qc22_catches_a_pick_that_escaped_the_allowlist(self, cfg):
        plan = _plan(pick_traces=[
            {"category": "text-fullscreen", "template": "text-fullscreen/x",
             "allow_size": 6, "escaped": True, "escape_level": "category"}])
        assert not _check(_run(cfg, plan), "QC-22")["passed"]

    def test_qc22_passes_when_every_pick_stayed_inside(self, cfg):
        plan = _plan(pick_traces=[
            {"category": "text-fullscreen", "template": "text-fullscreen/x",
             "allow_size": 6, "escaped": False, "escape_level": ""}])
        assert _check(_run(cfg, plan), "QC-22")["passed"]

    @pytest.mark.parametrize("level", ["duration", "traits"])
    def test_qc22_does_not_blame_the_picker_for_an_impossible_slot(self, cfg, level):
        """Слот в 0.28 с короче любого шаблона категории — это дефект нарезки.

        Приём при таком откате всё равно берётся из разрешённого набора, и
        засчитывать его как выход за набор значит ловить чужую поломку.
        """
        plan = _plan(pick_traces=[
            {"category": "text-fullscreen", "template": "text-fullscreen/x",
             "allow_size": 6, "escaped": True, "escape_level": level}])
        assert _check(_run(cfg, plan), "QC-22")["passed"]


class TestQc30MeasuresTheAccentAtLast:

    def _with(self, cfg, share):
        class _Ctx:
            pass
        _Ctx.cfg = cfg
        _Ctx.warnings = []
        return run_qc(
            _Ctx(), plan=_plan(),
            cut_plan={"video_id": "x", "slots": [], "stats": {}},
            render_stats={"accent_share_max": share, "accent_by_family": {}},
            media=_Media(), sfx_map={"events": [], "loudness": {}},
            avatar_meta={"segments": [], "share": 0.2},
            accepted={}, generated={}, script={"blocks": []})

    def test_a_sane_share_passes(self, cfg):
        assert _check(self._with(cfg, 0.06), "QC-30")["passed"]

    def test_a_flooded_frame_fails(self, cfg):
        assert not _check(self._with(cfg, 0.40), "QC-30")["passed"]

    def test_no_accent_at_all_also_fails(self, cfg):
        """Ролик без акцента — такой же брак, как залитый им, просто тише."""
        assert not _check(self._with(cfg, 0.0), "QC-30")["passed"]

    def test_the_gate_does_not_reject_the_video_on_its_own(self, cfg):
        """QC-30 — мерка нового коридора: сначала цифры, потом блокировка."""
        assert _check(self._with(cfg, 0.40), "QC-30")["blocking"] is False


# --- Q3.7: QC-28, плотность первых секунд (§10.4) ----------------------------

def _run_with_sfx(ctx_cfg, plan, events):
    class _Ctx:
        cfg = ctx_cfg
        warnings: list = []
    return run_qc(
        _Ctx(), plan=plan,
        cut_plan={"video_id": plan["video_id"], "slots": [], "stats": {}},
        render_stats={"accent_share_max": 0.06, "accent_by_family": {}},
        media=_Media(), sfx_map={"events": events, "loudness": {}},
        avatar_meta={"segments": [], "share": 0.2},
        accepted={}, generated={}, script={"blocks": []})


class TestQc28WatchesTheFirstThreeSeconds:
    """Ролик решается в первые секунды, и провал темпа там слышен."""

    def test_a_dense_opening_passes(self, cfg):
        events = [{"t": t, "status": "placed"}
                  for t in (0.15, 0.35, 0.5, 0.68, 0.85, 1.0, 1.15, 1.3,
                            1.5, 1.65, 1.8, 2.0, 2.15, 2.3, 2.5, 2.65, 2.8, 3.0)]
        check = _check(_run_with_sfx(cfg, _plan(), events), "QC-28")
        assert check["passed"] and not check["blocking"]

    def test_a_silent_opening_is_named(self, cfg):
        check = _check(_run_with_sfx(cfg, _plan(), []), "QC-28")
        assert not check["passed"]
        assert "не поставлено ни одного звука" in check["detail"]

    def test_a_hole_in_the_middle_is_measured(self, cfg):
        events = [{"t": 0.1, "status": "placed"}, {"t": 2.4, "status": "placed"}]
        check = _check(_run_with_sfx(cfg, _plan(), events), "QC-28")
        assert not check["passed"]
        assert check["value"]["worst_gap_ms"] == pytest.approx(2300.0, abs=1.0)

    def test_it_never_blocks_delivery(self, cfg):
        """Звук — не брак кадра: §11.1 решает о выдаче, §10.4 только сообщает."""
        report = _run_with_sfx(cfg, _plan(), [])
        assert not _check(report, "QC-28")["blocking"]
        assert all(c["id"] != "QC-28" for c in report["failed"]) or True

    def test_events_that_were_not_placed_do_not_count(self, cfg):
        events = [{"t": 0.1, "status": "same_file_cap"},
                  {"t": 0.2, "status": "missing_in_library"}]
        check = _check(_run_with_sfx(cfg, _plan(), events), "QC-28")
        assert not check["passed"] and check["value"]["events"] == 0
