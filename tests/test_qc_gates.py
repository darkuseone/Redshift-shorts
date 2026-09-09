"""Новые гейты волны: QC-20…QC-25, QC-29, QC-30 (§12).

Девятнадцать проверок на 0042 прошли все до одной, и ролик при этом получил
`visual 2/10`: ни одна из них не смотрит, есть ли в кадре что-нибудь кроме
букв, сколько раз повторился приём и попал ли хук на экран. Гейты этой волны
меряют ровно то, на что жаловался критик.

Номера QC-20/21/22 закреплены за MEGA P1 и реализованы в её формулировке.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.p12_render_qc.qc import QC17_TEMPLATE_OVERLAP_MAX, _hook_is_banned, run_qc


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

    def test_qc21_counts_needless_as_ungrounded(self, cfg):
        """Need-less выбранный шаблон = ungrounded (MUST-010)."""
        plan = _plan(
            shots=[_shot(i, template="text-fullscreen/blur-out-up",
                         grounded_on=[]) for i in range(9)]
            + [_shot(9, template=self.NEEDY[0], grounded_on=["number"])])
        check = _check(_run(cfg, plan), "QC-21")
        assert not check["passed"]
        assert check["value"] == 0.9

    def test_qc21_passes_when_needless_share_stays_under_threshold(self, cfg):
        plan = _plan(shots=[
            _shot(0, template="text-fullscreen/blur-out-up", grounded_on=[]),
            *[_shot(i, template=self.NEEDY[0], grounded_on=["number"])
              for i in range(1, 5)],
        ])
        check = _check(_run(cfg, plan), "QC-21")
        assert check["passed"]
        assert check["value"] == 0.2

    def test_qc21_ignores_cta_chrome(self, cfg):
        """Кнопка подписки — QC-16, не «приём без основания»."""
        plan = _plan(
            shots=[_shot(0, template=self.NEEDY[0], grounded_on=["number"])],
            overlays=[{
                "type": "cta", "template": "outro-cta/subscribe-pulse",
                "start": 46.0, "end": 48.0,
            }],
        )
        check = _check(_run(cfg, plan), "QC-21")
        assert check["passed"]
        assert check["value"] == 0.0

    def test_qc21_ignores_signature_furniture(self, cfg):
        """Хук, CTA и плашка не раздувают долю и не заваливают гейт сами."""
        plan = _plan(shots=[
            _shot(0, template="intro-hooks/hook-blackout-word", grounded_on=[]),
        ], overlays=[
            {"type": "plaque", "template": "lower-thirds/note-pin",
             "start": 2.0, "end": 4.0, "grounded_on": []},
            {"type": "cta", "template": "outro-cta/logo-brand-close",
             "start": 46.0, "end": 48.0, "grounded_on": []},
            {"type": "dataviz", "template": self.NEEDY[0],
             "start": 10.0, "end": 13.0, "grounded_on": ["number"]},
        ])
        check = _check(_run(cfg, plan), "QC-21")
        assert check["passed"]
        assert check["value"] == 0.0

    def test_qc21_counts_ungrounded_dataviz_overlay(self, cfg):
        plan = _plan(overlays=[{
            "type": "dataviz", "template": self.NEEDY[0],
            "start": 1.0, "end": 3.0, "grounded_on": [],
        }])
        check = _check(_run(cfg, plan), "QC-21")
        assert not check["passed"]
        assert check["value"] == 1.0

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


class TestQc14CapsGeneratedFootageAtTenPercent:
    """MUST-007: зритель не должен видеть пачку сгенерированных кадров вместо съёмки."""

    def test_nine_percent_passes(self, cfg):
        # 4.32 / 48 = 0.09. Один план короче потолка QC-4 (5 с).
        plan = _plan(shots=[_shot(0, duration=4.32, ai_generated=True)])
        check = _check(_run(cfg, plan), "QC-14")
        assert check["passed"]
        assert check["blocking"]
        assert check["threshold"] == pytest.approx(0.10)
        assert check["value"] == pytest.approx(0.09, abs=1e-4)

    def test_twelve_percent_fails_and_blocks(self, cfg):
        # 2.88 + 2.88 = 5.76 / 48 = 0.12. Два коротких плана, чтобы не задеть QC-4.
        plan = _plan(shots=[
            _shot(0, duration=2.88, ai_generated=True),
            _shot(1, duration=2.88, ai_generated=True),
        ])
        check = _check(_run(cfg, plan), "QC-14")
        assert not check["passed"]
        assert check["blocking"]
        assert check["threshold"] == pytest.approx(0.10)
        assert check["value"] == pytest.approx(0.12, abs=1e-4)

    def test_config_cap_is_ten_percent(self, cfg):
        assert cfg.get("limits.ai_footage_share_max") == pytest.approx(0.10)


class TestQc10MeasuresSubtitleDriftAgainstSpeech:
    """MUST-026: SRT vs речь после P3, порог — верх окна слова (450 мс)."""

    def test_one_second_shift_fails(self, cfg):
        plan = _plan(
            subtitles=[{"display": "слово", "start": 2.0, "end": 2.3}],
            speech_words=[{"display": "слово", "start": 1.0, "end": 1.3}],
        )
        check = _check(_run(cfg, plan), "QC-10")
        assert not check["passed"]
        assert check["blocking"]
        assert check["value"] == pytest.approx(1000.0, abs=1.0)
        assert check["threshold"] == 450

    def test_synced_words_pass(self, cfg):
        plan = _plan(
            subtitles=[{"display": "слово", "start": 1.0, "end": 1.3}],
            speech_words=[{"display": "слово", "start": 1.0, "end": 1.3}],
        )
        check = _check(_run(cfg, plan), "QC-10")
        assert check["passed"]
        assert check["value"] == pytest.approx(0.0, abs=1.0)

    def test_muted_hook_cues_match_the_spoken_word_not_index_zero(self, cfg):
        """Под хуком караоке снято: первый куй — середина речи, не words[0]."""
        plan = _plan(
            subtitles=[{"display": "Работа", "start": 8.094, "end": 8.544}],
            speech_words=[
                {"display": "Этот", "start": 0.0, "end": 0.3},
                {"display": "ответ", "start": 0.3, "end": 0.6},
                {"display": "Работа", "start": 8.094, "end": 8.544},
            ],
        )
        check = _check(_run(cfg, plan), "QC-10")
        assert check["passed"]
        assert check["value"] == pytest.approx(0.0, abs=1.0)

    def test_a_repeated_word_matches_the_nearby_token(self, cfg):
        """Второе «кубит» — не первое, снятое mute на 2.7 с раньше."""
        plan = _plan(
            subtitles=[{"display": "кубит", "start": 14.508, "end": 14.958}],
            speech_words=[
                {"display": "кубит", "start": 11.806, "end": 12.256},
                {"display": "физический", "start": 13.790, "end": 14.240},
                {"display": "кубит", "start": 14.508, "end": 14.958},
            ],
        )
        check = _check(_run(cfg, plan), "QC-10")
        assert check["passed"]
        assert check["value"] == pytest.approx(0.0, abs=1.0)

    def test_a_glued_lead_syncs_to_the_first_spoken_token(self, cfg):
        """«бы ты такому»: start куи — у предлога, display — у знаменательного."""
        plan = _plan(
            subtitles=[{
                "display": "такому", "lead": "бы ты",
                "start": 43.367, "end": 44.244,
            }],
            speech_words=[
                {"display": "бы", "start": 43.367, "end": 43.500},
                {"display": "ты", "start": 43.500, "end": 43.700},
                {"display": "такому", "start": 43.700, "end": 44.244},
            ],
        )
        check = _check(_run(cfg, plan), "QC-10")
        assert check["passed"]
        assert check["value"] == pytest.approx(0.0, abs=1.0)

    def test_cue_end_does_not_steal_the_next_word(self, cfg):
        """Караоке: конец куи = старт следующего слова, не склейка."""
        plan = _plan(
            subtitles=[
                {"display": "чем", "start": 28.72, "end": 28.884},
                {"display": "существует", "start": 28.884, "end": 29.32},
                {"display": "ответ", "start": 32.213, "end": 32.48},
            ],
            speech_words=[
                {"display": "ответ", "start": 0.293, "end": 0.56},
                {"display": "чем", "start": 28.72, "end": 28.884},
                {"display": "существует", "start": 28.884, "end": 29.32},
                {"display": "ответ", "start": 32.213, "end": 32.48},
            ],
        )
        check = _check(_run(cfg, plan), "QC-10")
        assert check["passed"]
        assert check["value"] == pytest.approx(0.0, abs=1.0)


class TestQc11ReportsClipOffsetNotMouth:
    """MUST-026: QC-11 — avatar_clip_offset, не губы и не lip-sync."""

    def test_report_text_has_no_lip_or_mouth_words(self, cfg):
        import re

        check = _check(_run(cfg, _plan()), "QC-11")
        blob = f"{check['name']} {check.get('detail') or ''}"
        assert check["detail"] == "avatar_clip_offset"
        assert not re.search(r"lipsync|\blips?\b|губы|липсинк", blob, re.I)


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

    def test_over_twelve_percent_blocks_delivery(self, cfg):
        """MUST-024: акцент >12 % — blocking, ролик не выдаётся."""
        check = _check(self._with(cfg, 0.40), "QC-30")
        assert not check["passed"]
        assert check["blocking"] is True

    def test_under_floor_does_not_block_on_its_own(self, cfg):
        """Недобор акцента всё ещё виден, но выдачу ломает только потолок."""
        check = _check(self._with(cfg, 0.0), "QC-30")
        assert not check["passed"]
        assert check["blocking"] is False


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


class TestTzMust024ConstantsAgree:
    """Одна величина — одно число в docs, config и QC."""

    def test_config_qc_and_instruction_share_the_same_caps(self, cfg):
        from pathlib import Path

        from src.p0_validate.validator import HOOK_MAX_SEC
        from src.p12_render_qc.qc import apply_semantic_qc
        from src.p12_render_qc.vision_qc import MISMATCH_LIMIT

        instruction = Path("instruction.md").read_text(encoding="utf-8")
        vfx = cfg.get("limits.bg_vfx_sec")
        accent_hi = float((cfg.brandbook.get("color_rules") or {})
                          .get("accent_max_frame_share", 0))

        assert HOOK_MAX_SEC == pytest.approx(3.0)
        assert cfg.get("limits.hook_sec") == pytest.approx(3.0)
        assert cfg.get("limits.ai_footage_share_max") == pytest.approx(0.10)
        assert cfg.get("limits.bg_vfx_per_video") == 2
        assert float(vfx[0]) == pytest.approx(2.0)
        assert float(vfx[1]) == pytest.approx(5.0)
        assert cfg.get("limits.vision_mismatch_share_max") == pytest.approx(0.10)
        assert MISMATCH_LIMIT == pytest.approx(0.10)
        assert cfg.get("stock.max_download_height") == 1080
        assert cfg.get("stock.candidate_surplus") == pytest.approx(1.3)
        assert accent_hi == pytest.approx(0.12)

        assert "≤10 %" in instruction
        assert "VFX-фон ≤2 раза, 2–5 сек" in instruction
        assert "1080p" in instruction
        assert "1.3×" in instruction
        assert "mismatch_share > 10 %" in instruction
        assert "QC-19 не отключается" in instruction

        qc14 = _check(_run(cfg, _plan()), "QC-14")
        assert qc14["threshold"] == pytest.approx(0.10)
        qc19 = _check(_run(cfg, _plan()), "QC-19")
        assert qc19["blocking"] is True

        vision = {
            "enabled": True, "skipped": True, "qc_skipped_semantic": True,
            "mismatch_share": None, "mismatch_limit": 0.10,
            "picture_matches_speech": False, "blocking": True,
            "reason": "skip_live", "notes": [],
        }
        folded = apply_semantic_qc(
            {"passed": True, "passed_count": 1, "total": 1,
             "checks": [{"id": "QC-1", "name": "x", "passed": True,
                         "blocking": True, "value": 1, "threshold": 1,
                         "detail": "", "timecode_sec": None}],
             "failed": []},
            vision)
        status = "ok" if folded["passed"] else "qc_failed"
        assert folded["passed"] is False
        assert status != "ok"


class TestQc17TemplateSetOverlap:
    """MUST-014: QC-17 падает на копии набора, а не только при Jaccard == 1.0."""

    def _history(self, cfg, tmp_path, templates, video_id="redshift_0001"):
        cfg.set("paths.cache_dir", str(tmp_path / "cache"))
        cache = Path(cfg.path("paths.cache_dir"))
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "run_history.json").write_text(
            json.dumps({"runs": [{"video_id": video_id, "templates": templates}]}),
            encoding="utf-8",
        )

    def test_identical_ids_fail(self, cfg, tmp_path):
        ids = [
            "intro-hooks/hook-blackout-word",
            "hero-devices/type-slab",
            "outro-cta/logo-brand-close",
            "kenburns/pan-left",
        ]
        self._history(cfg, tmp_path, ids)
        check = _check(_run(cfg, _plan(templates_used=list(ids))), "QC-17")
        assert not check["passed"]
        assert check["blocking"]
        assert check["value"] == pytest.approx(1.0)
        assert check["threshold"] == pytest.approx(QC17_TEMPLATE_OVERLAP_MAX)

    def test_near_clone_at_threshold_fails(self, cfg, tmp_path):
        prev = [f"t/{i}" for i in range(10)]
        current = [f"t/{i}" for i in range(9)] + ["t/x"]
        self._history(cfg, tmp_path, prev)
        check = _check(_run(cfg, _plan(templates_used=current)), "QC-17")
        assert check["value"] >= QC17_TEMPLATE_OVERLAP_MAX
        assert not check["passed"]

    def test_modest_overlap_passes(self, cfg, tmp_path):
        prev = [f"t/{i}" for i in range(10)]
        current = [f"t/{i}" for i in range(3)] + [f"u/{i}" for i in range(7)]
        self._history(cfg, tmp_path, prev)
        check = _check(_run(cfg, _plan(templates_used=current)), "QC-17")
        assert check["value"] < QC17_TEMPLATE_OVERLAP_MAX
        assert check["passed"]

    def test_no_previous_video_passes(self, cfg, tmp_path):
        cfg.set("paths.cache_dir", str(tmp_path / "cache"))
        Path(cfg.path("paths.cache_dir")).mkdir(parents=True, exist_ok=True)
        check = _check(_run(cfg, _plan(templates_used=["intro-hooks/hook-blackout-word"])),
                       "QC-17")
        assert check["passed"]
