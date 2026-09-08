"""Шов лупа и ротатор концовок: Q3.1 + Q3.2 (§6.3, §6.4).

Канал закончился одинаково шесть роликов подряд — все шесть сценариев
`redshift_0042…0047` писали `cta.type: "question"`, и перечень типов знал
ровно три значения. Здесь проверяется, что восемь типов действительно
ротируются, что старые имена не сломали уже написанные сценарии, и что
`visual_loop_seam` — не украшение, а обязательство, которое меряется числом
по отрендеренному файлу.
"""

from __future__ import annotations

import json

import pytest

from src.lib import endings
from src.lib.phash import hamming
from src.lib.schema import CTA_LEGACY, CTA_TYPES
from src.p0_validate.validator import _map_legacy_cta, validate_script
from src.p11_assemble.assemble import _close_loop_seam, _mirror_kenburns
from src.p12_render_qc.qc import run_qc


# --- Q3.1: ротатор -----------------------------------------------------------

class TestTheEndingRingActuallyRotates:

    def test_eight_types_exist(self):
        assert len(CTA_TYPES) == 8
        assert "visual_loop_seam" in CTA_TYPES
        assert "binary_vote" in CTA_TYPES

    def test_every_legacy_name_maps_to_a_live_type(self):
        for old, new in CTA_LEGACY.items():
            assert old not in CTA_TYPES, f"{old} осталось и типом, и псевдонимом"
            assert new in CTA_TYPES

    def test_the_mapper_rewrites_in_place_and_says_so(self):
        script = {"cta": {"text": "Что думаешь?", "type": "question"}}
        warnings = _map_legacy_cta(script)
        assert script["cta"]["type"] == "open_question"
        assert [w["code"] for w in warnings] == ["CTA_TYPE_RENAMED"]

    def test_a_modern_type_passes_through_untouched(self):
        script = {"cta": {"text": "Один или два?", "type": "binary_vote"}}
        assert _map_legacy_cta(script) == []
        assert script["cta"]["type"] == "binary_vote"

    def test_the_same_type_is_not_offered_twice_in_a_row(self, cfg, tmp_path,
                                                         monkeypatch):
        _memory(cfg, tmp_path, monkeypatch, ["open_question"])
        assert endings.last_ending_type(cfg) == "open_question"
        assert "open_question" not in endings.allowed_types(cfg)
        assert endings.next_ending_type(cfg) != "open_question"

    def test_soft_subscribe_is_at_most_one_in_three(self, cfg, tmp_path, monkeypatch):
        _memory(cfg, tmp_path, monkeypatch, ["soft_subscribe", "binary_vote"])
        # Просьба о подписке стоит через ролик — третьим ставить нельзя.
        assert "soft_subscribe" not in endings.allowed_types(cfg)
        _memory(cfg, tmp_path, monkeypatch,
                ["soft_subscribe", "binary_vote", "part2_cliff"])
        assert "soft_subscribe" in endings.allowed_types(cfg)

    def test_the_seam_type_needs_the_editor_to_be_able_to_close_it(self, cfg,
                                                                  tmp_path,
                                                                  monkeypatch):
        _memory(cfg, tmp_path, monkeypatch, ["binary_vote"])
        assert "visual_loop_seam" not in endings.allowed_types(cfg)
        assert "visual_loop_seam" in endings.allowed_types(cfg, allow_loop_seam=True)

    def test_the_ring_walks_forward_rather_than_bouncing(self, cfg, tmp_path,
                                                         monkeypatch):
        """Кольцо идёт по кругу, а не колеблется между двумя любимыми типами."""
        _memory(cfg, tmp_path, monkeypatch, ["open_question"])
        first = endings.next_ending_type(cfg)
        _memory(cfg, tmp_path, monkeypatch, ["open_question", first])
        second = endings.next_ending_type(cfg)
        assert second not in ("open_question", first)

    def test_recording_moves_the_memory(self, cfg, tmp_path, monkeypatch):
        _memory(cfg, tmp_path, monkeypatch, ["open_question"])
        endings.record_ending(cfg, video_id="redshift_9001", kind="binary_vote")
        assert endings.last_ending_type(cfg) == "binary_vote"
        # Идемпотентность: тот же ролик не занимает в истории два места.
        endings.record_ending(cfg, video_id="redshift_9001", kind="binary_vote")
        prefs = endings.load_prefs(cfg)
        ids = [r["video_id"] for r in prefs["ending_history"]]
        assert ids.count("redshift_9001") == 1

    def test_a_video_does_not_repeat_itself(self, cfg, tmp_path, monkeypatch):
        """Пересборка 0042 не имеет права сообщать, что 0042 повторяет 0042."""
        _memory(cfg, tmp_path, monkeypatch, ["open_question"])
        prefs = endings.load_prefs(cfg)
        mine = prefs["ending_history"][-1]["video_id"]
        assert endings.repeats_previous(cfg, "open_question", video_id=mine) is False
        assert endings.repeats_previous(cfg, "open_question",
                                        video_id="redshift_9999") is True

    def test_an_unknown_type_is_not_recorded(self, cfg, tmp_path, monkeypatch):
        _memory(cfg, tmp_path, monkeypatch, ["open_question"])
        out = endings.record_ending(cfg, video_id="redshift_9002", kind="zzz")
        assert out["recorded"] is False
        assert endings.last_ending_type(cfg) == "open_question"


class TestTheSixWrittenScriptsStillValidate:
    """Риск §15: «смена CTA_TYPES сломает старые сценарии»."""

    @pytest.mark.parametrize("video_id", ["redshift_0042", "redshift_0043",
                                          "redshift_0044", "redshift_0045",
                                          "redshift_0046", "redshift_0047"])
    def test_script_validates(self, cfg, video_id):
        path = cfg.repo_root / "scripts" / f"{video_id}.json"
        script = json.loads(path.read_text(encoding="utf-8"))
        result = validate_script(script, cfg)
        assert result["_validation"]["ok"]
        kind = (result.get("cta") or {}).get("type")
        assert kind is None or kind in CTA_TYPES

    def test_0043_does_not_repeat_the_ending_of_0042(self, cfg):
        """DoD Q3.1 — ровно это и требуется от ротатора."""
        def kind(video_id):
            path = cfg.repo_root / "scripts" / f"{video_id}.json"
            script = json.loads(path.read_text(encoding="utf-8"))
            return (validate_script(script, cfg).get("cta") or {}).get("type")

        assert kind("redshift_0042") != kind("redshift_0043")


# --- Q3.2: шов ---------------------------------------------------------------

def _shot(index, **over):
    shot = {"index": index, "start": index * 2.0, "end": index * 2.0 + 2.0,
            "duration": 2.0, "kind": "footage", "block_id": f"b{index}",
            "role": "body", "mode": "C", "reason": "",
            "file": f"/w/shot_{index}.mp4", "asset_id": f"a{index}",
            "source": "pexels", "license": "pexels", "attribution": "",
            "credit": "", "page_url": "", "ai_generated": False, "mock": False,
            "fit": "crop", "focus": [0.5, 0.5],
            "kenburns": {"template": "kenburns/zoom-in-center", "zoom": [1.0, 1.12]}}
    shot.update(over)
    return shot


class TestTheSeamIsClosedOnlyWhenItIsPromised:

    def test_a_plain_ending_is_left_alone(self):
        shots = [_shot(0), _shot(1), _shot(2)]
        seam = _close_loop_seam(shots, {"cta": {"type": "open_question"}})
        assert seam is None
        assert shots[-1]["asset_id"] == "a2"
        assert "loop_seam" not in shots[-1]

    def test_the_last_shot_takes_the_material_of_the_first(self):
        shots = [_shot(0), _shot(1), _shot(2)]
        seam = _close_loop_seam(shots, {"cta": {"type": "visual_loop_seam"}})
        assert seam is not None
        assert shots[-1]["file"] == shots[0]["file"]
        assert shots[-1]["asset_id"] == shots[0]["asset_id"]
        assert shots[-1]["loop_seam"] is True
        assert "asset_id" in seam["changed_fields"]

    def test_the_camera_runs_backwards(self):
        shots = [_shot(0), _shot(1), _shot(2)]
        _close_loop_seam(shots, {"cta": {"type": "visual_loop_seam"}})
        kb = shots[-1]["kenburns"]
        assert kb["template"] == "kenburns/zoom-out-center"
        assert kb["zoom"] == [1.12, 1.0]
        assert kb["mirrored"] is True

    def test_the_on_screen_glyph_comes_along(self):
        shots = [_shot(0, kind="fullscreen_text", content="105 КУБИТОВ"),
                 _shot(1), _shot(2)]
        _close_loop_seam(shots, {"cta": {"type": "visual_loop_seam"}})
        assert shots[-1]["content"] == "105 КУБИТОВ"
        assert shots[-1]["kind"] == "fullscreen_text"

    def test_a_single_shot_video_has_nothing_to_close(self):
        shots = [_shot(0)]
        assert _close_loop_seam(shots, {"cta": {"type": "visual_loop_seam"}}) is None

    def test_pan_is_mirrored_by_sign(self):
        kb = _mirror_kenburns({"template": "kenburns/pan-left", "pan": [1, 0]})
        assert kb["template"] == "kenburns/pan-right"
        assert kb["pan"] == [-1.0, -0.0]

    def test_an_unknown_kenburns_keeps_its_name_but_reverses_its_numbers(self):
        kb = _mirror_kenburns({"template": "kenburns/drift-oddball",
                               "zoom": [1.0, 1.2]})
        assert kb["template"] == "kenburns/drift-oddball"
        assert kb["zoom"] == [1.2, 1.0]

    def test_nothing_to_mirror(self):
        assert _mirror_kenburns(None) is None


# --- QC-27 -------------------------------------------------------------------

class _Media:
    duration_sec = 48.0
    fps = 30
    width = 1080
    height = 1920


def _qc(cfg, *, cta_type, bits):
    class _Ctx:
        pass
    _Ctx.cfg = cfg
    _Ctx.warnings = []
    plan = {"video_id": "redshift_9060", "variant": "B", "duration_sec": 48.0,
            "shots": [], "overlays": [], "subtitles": [], "templates_used": [],
            "pick_traces": [], "avatar": []}
    stats = {"accent_share_max": 0.06, "accent_by_family": {}}
    if bits is not None:
        stats["loop_seam_dhash_bits"] = bits
    return run_qc(_Ctx(), plan=plan,
                  cut_plan={"video_id": "redshift_9060", "slots": [], "stats": {},
                            "cta": {"type": cta_type}},
                  render_stats=stats, media=_Media(),
                  sfx_map={"events": [], "loudness": {}},
                  avatar_meta={"segments": [], "share": 0.2},
                  accepted={}, generated={}, script={"blocks": []})


def _check(report, cid):
    return next(c for c in report["checks"] if c["id"] == cid)


class TestQc27MeasuresTheSeamOnlyWhereItWasPromised:

    def test_a_tight_seam_passes(self, cfg):
        check = _check(_qc(cfg, cta_type="visual_loop_seam", bits=4), "QC-27")
        assert check["passed"] and check["blocking"]

    def test_twelve_bits_is_still_a_seam(self, cfg):
        assert _check(_qc(cfg, cta_type="visual_loop_seam", bits=12), "QC-27")["passed"]

    def test_thirteen_bits_is_not(self, cfg):
        check = _check(_qc(cfg, cta_type="visual_loop_seam", bits=13), "QC-27")
        assert not check["passed"] and check["blocking"]

    def test_an_unmeasured_seam_is_not_a_green_gate(self, cfg):
        """Упавший ffmpeg не имеет права выглядеть как сомкнутый шов."""
        check = _check(_qc(cfg, cta_type="visual_loop_seam", bits=None), "QC-27")
        assert not check["passed"]
        assert "замер не выполнен" in check["detail"]

    def test_other_endings_are_not_held_to_it(self, cfg):
        check = _check(_qc(cfg, cta_type="open_question", bits=None), "QC-27")
        assert check["passed"] and not check["blocking"]

    def test_a_wide_seam_on_another_ending_is_reported_not_blocked(self, cfg):
        check = _check(_qc(cfg, cta_type="binary_vote", bits=61), "QC-27")
        assert check["passed"] and not check["blocking"]


class TestTheHashItselfSeparatesFrames:
    """Порог 12/64 осмыслен, только если хеш вообще что-то различает."""

    def test_identical_frames_are_zero_apart(self):
        assert hamming("0f1e2d3c4b5a6978", "0f1e2d3c4b5a6978") == 0

    def test_a_missing_hash_is_maximally_far(self):
        assert hamming("", "0f1e2d3c4b5a6978") == 64


# --- вспомогательное ---------------------------------------------------------

def _memory(cfg, tmp_path, monkeypatch, history):
    """Подменить память ротации на временный файл предпочтений."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "editing_preferences.json").write_text(json.dumps({
        "version": 1, "runs": [], "situation_weights": {}, "defaults": {},
        "ending_ring": list(endings.ENDING_RING_DEFAULT),
        "ending_last_type": history[-1] if history else None,
        "ending_history": [{"video_id": f"redshift_90{i:02d}", "type": kind,
                            "recorded_at": "2026-09-08"}
                           for i, kind in enumerate(history)],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(type(cfg), "repo_root", property(lambda self: root),
                        raising=False)
    return root
