"""MUST-028: CTA Subscribe / gaze plaque follow meta/roles, not video_id."""

from __future__ import annotations

import copy
from pathlib import Path

from src.p11_assemble.assemble import (
    _gaze_plaque_copy, show_subscribe_cta, wants_gaze_plaque,
)


ROOT = Path(__file__).resolve().parents[1]


def test_src_has_no_redshift_0042_id_gate():
    hits = []
    for path in (ROOT / "src").rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".md", ".yaml", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "redshift_0042" in text:
            hits.append(str(path.relative_to(ROOT)))
    assert hits == [], hits


def test_subscribe_follows_meta_cta_not_video_id(sample_script):
    script = copy.deepcopy(sample_script)
    script["meta"]["video_id"] = "other_video"
    script["meta"]["cta"] = False
    plan = {"video_id": "other_video", "meta": script["meta"],
            "show_subscribe": False}
    assert show_subscribe_cta(plan) is False

    script["meta"]["video_id"] = "redshift_0042"
    script["meta"]["cta"] = True
    plan = {"video_id": "redshift_0042", "meta": script["meta"],
            "show_subscribe": True}
    assert show_subscribe_cta(plan) is True


def test_0042_script_hides_subscribe_via_meta(sample_script):
    assert sample_script["meta"]["cta"] is False
    plan = {"video_id": "renamed", "meta": sample_script["meta"],
            "show_subscribe": False}
    assert show_subscribe_cta(plan) is False


def test_gaze_follows_evidence_card_not_video_id(sample_script):
    script = copy.deepcopy(sample_script)
    script["meta"]["video_id"] = "renamed"
    plan = {
        "video_id": "renamed",
        "hook": script["meta"].get("hook") or {},
        "blocks": script["blocks"],
        "sources": script["sources"],
    }
    assert wants_gaze_plaque(plan) is True
    assert _gaze_plaque_copy(plan) == "НЕВОЗМОЖНО ПРОВЕРИТЬ"


def test_gaze_absent_without_look_at_or_evidence_card():
    plan = {
        "video_id": "redshift_0042",
        "hook": {},
        "blocks": [
            {"role": "hook", "text": "сто пять кубитов", "overlay": {"type": "none"}},
            {"role": "setup", "text": "чип", "overlay": {"type": "none"}},
            {"role": "cta", "text": "подпишись", "overlay": {"type": "none"}},
        ],
    }
    assert wants_gaze_plaque(plan) is False


def test_gaze_from_explicit_look_at_without_evidence():
    plan = {
        "video_id": "any",
        "blocks": [
            {"role": "setup", "text": "смотри сюда", "look_at": True,
             "overlay": {"type": "none"}},
        ],
    }
    assert wants_gaze_plaque(plan) is True


def test_0047_like_plan_does_not_use_qubit_regex_for_gaze():
    plan = {
        "video_id": "redshift_0047",
        "hook": {},
        "blocks": [
            {"role": "hook", "text": "Самая глубокая дыра на Земле",
             "overlay": {"type": "none"}},
            {"role": "evidence", "text": "термометр показал сто восемьдесят",
             "source_ref": "nature.com",
             "overlay": {"type": "fullscreen_text", "content": "180 ГРАДУСОВ"}},
        ],
        "sources": [],
    }
    assert wants_gaze_plaque(plan) is True
    copy_text = _gaze_plaque_copy(plan)
    assert "КУБИТ" not in copy_text
    assert copy_text == "ФАКТ"


def test_gaze_plaque_skipped_when_face_lives_in_the_lower_third():
    from src.p11_assemble.assemble import gaze_plaque_fits_face_band

    assert gaze_plaque_fits_face_band({"avatar": {"face_band_y": [1080, 1480]}}) is False
    assert gaze_plaque_fits_face_band({"avatar": {"face_band_y": [420, 820]}}) is True
    assert gaze_plaque_fits_face_band({}) is False
