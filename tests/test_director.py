"""Чат-режиссёр: таймлайн ``director`` исполняется буквально (docs/director/TIMELINE.md).

Нейросети в Actions нет, поэтому футаж и приёмы выбирает режиссёр в чате, а
станок обязан поставить ровно их — в нужное окно, по слову речи.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.lib import director as D


def _script(**director) -> dict:
    spec = {
        "footage": {
            "bh": {"src": "https://example.org/bh.mp4", "source": "nasa",
                   "license": "public_domain", "page_url": "https://svs.gsfc.nasa.gov/x"},
            "cat": {"src": "https://example.org/cat.jpg", "source": "wikimedia",
                    "license": "cc-by-sa", "page_url": "https://commons.wikimedia.org/x"},
        },
        "shots": [
            {"block": "b1", "fullscreen": {"template": "intro-hooks/hook-question-flash",
                                           "content": "КОТ?"}},
            {"block": "b1", "at": "чёрной", "footage": "bh",
             "transition": "transitions/gravitational-lens", "motion": "kenburns/zoom-in-center"},
            {"block": "b2", "footage": "cat", "transition": "whip-pan",
             "hero": {"template": "hero-devices/oversize-word", "params": {"word": "ЛАПША"}}},
            {"block": "b2", "at": "лапшу", "footage": "bh", "transition": "glitch"},
        ],
        "overlays": [
            {"template": "data-viz/counter-roll", "block": "b2", "at": "сто",
             "dur": 1.5, "params": {"value": 100, "suffix": " КМ"}},
        ],
    }
    spec.update(director)
    return {
        "meta": {"video_id": "redshift_t001", "topic": "t", "category": "space",
                 "target_duration_sec": 30, "avatar_mode": "none"},
        "blocks": [
            {"id": "b1", "role": "hook", "text": "Что будет с котом в чёрной дыре?"},
            {"id": "b2", "role": "cta",
             "text": "Его вытянет в лапшу длиной сто километров. Подпишись."},
        ],
        "director": spec,
    }


# Сценарий, который проходит P0 целиком: хук ≤3 с, ответ на 40–88 %, 25–70 с.
VALID_BLOCKS = [
    {
        "id": "b1",
        "role": "hook",
        "text": "Что будет с котом в чёрной дыре?",
        "emphasis_word": "котом"
    },
    {
        "id": "b2",
        "role": "develop",
        "text": "Сначала ничего. Кот летит и даже не понимает, что уже всё. Горизонт событий вообще не больно. Ни вспышки, ни стены, ни таблички.",
        "emphasis_word": "горизонт"
    },
    {
        "id": "b2b",
        "role": "develop",
        "text": "Для кота снаружи время тянется, а для тебя снаружи кот замирает на краю навсегда. Красиво и жутко.",
        "emphasis_word": "навсегда",
        "silence_after_ms": 1200
    },
    {
        "id": "b3",
        "role": "twist",
        "text": "А потом гравитация тянет лапы сильнее, чем хвост. И кота вытягивает в макарошку длиной сто километров.",
        "emphasis_word": "макарошку",
        "answers_hook": True
    },
    {
        "id": "b4",
        "role": "cta",
        "text": "Учёные называют это спагеттификацией. Подпишись, пока тебя не затянуло.",
        "emphasis_word": "Подпишись"
    }
]


def _valid_script() -> dict:
    return {
        "meta": {"video_id": "redshift_t002", "topic": "black hole", "category": "space",
                 "target_duration_sec": 30, "avatar_mode": "none",
                 "hook": {"on_screen": "КОТ?", "style": "question_flash"}},
        "sources": [{"title": "Black holes", "domain": "nasa.gov",
                     "url": "https://science.nasa.gov/universe/black-holes/"}],
        "blocks": copy.deepcopy(VALID_BLOCKS),
        "cta": {"text": "Подпишись, пока тебя не затянуло.", "type": "subscribe_like"},
    }


def _errors(script) -> list[str]:
    return [f"{i.where}: {i.message}" for i in D.validate(script) if i.level == "error"]


class TestValidate:
    def test_a_sound_timeline_has_no_errors(self):
        assert _errors(_script()) == []

    def test_unknown_template_is_an_error(self):
        s = _script()
        s["director"]["shots"][1]["transition"] = "transitions/no-such-thing"
        assert any("не найден" in e for e in _errors(s))

    def test_anchor_must_be_spoken_in_the_block(self):
        s = _script()
        s["director"]["shots"][3]["at"] = "макарошку"
        assert any("якорь" in e for e in _errors(s))

    def test_second_occurrence_anchor(self):
        assert D.parse_anchor("кот#2") == ("кот", 2)
        assert D.parse_anchor("Чёрной") == ("черной", 1)

    def test_footage_without_license_is_refused(self):
        s = _script()
        del s["director"]["footage"]["bh"]["license"]
        assert any("license" in e for e in _errors(s))

    def test_shot_needs_exactly_one_kind(self):
        s = _script()
        s["director"]["shots"][2]["fullscreen"] = {"content": "ДВА"}
        assert any("ровно одно" in e for e in _errors(s))

    def test_generation_over_twenty_percent_is_an_error(self):
        s = _script()
        for entry in s["director"]["footage"].values():
            entry["ai_generated"] = True
        assert any("генерация" in e for e in _errors(s))

    def test_shots_must_follow_block_order(self):
        s = _script()
        s["director"]["shots"].reverse()
        assert any("порядку" in e for e in _errors(s))

    def test_p0_refuses_a_broken_timeline(self, cfg):
        from src.errors import ValidationError
        from src.p0_validate.validator import validate_script
        s = _valid_script()
        s["director"] = {"footage": {}, "shots": [{"block": "b1", "footage": "ghost"}]}
        with pytest.raises(ValidationError) as exc:
            validate_script(s, cfg)
        assert exc.value.code == "DIRECTOR_INVALID"


class TestAnchors:
    WORDS = {"words": [
        {"display": "Что", "start": 0.0, "end": 0.2, "block_id": "b1", "spoken": ["что"]},
        {"display": "чёрной", "start": 1.1, "end": 1.4, "block_id": "b1", "spoken": ["чёрной"]},
        {"display": "100", "start": 3.0, "end": 3.3, "block_id": "b2", "spoken": ["сто"]},
    ]}

    def test_word_start_in_final_timecode(self):
        rows = D._word_rows(self.WORDS)
        assert D.anchor_time(rows, "b1", "черной") == pytest.approx(1.1)
        assert D.anchor_time(rows, "b1") == pytest.approx(0.0)

    def test_number_found_by_its_spoken_form(self):
        rows = D._word_rows(self.WORDS)
        assert D.anchor_time(rows, "b2", "сто") == pytest.approx(3.0)

    def test_missing_anchor_raises(self):
        with pytest.raises(D.DirectorError):
            D.anchor_time(D._word_rows(self.WORDS), "b1", "жираф")


def test_apply_director_places_exactly_what_was_asked(cfg, tmp_path, monkeypatch):
    """Шоты, приёмы и оверлеи в edit-плане — ровно из таймлайна режиссёра."""
    monkeypatch.setattr(D, "_cache_dir", lambda ctx: tmp_path)
    ctx = SimpleNamespace(cfg=cfg, work_dir=tmp_path,
                          wpath=lambda *p: _mk(tmp_path.joinpath(*p)))
    words = {"words": [
        {"display": w, "start": t, "end": t + 0.3, "block_id": b, "spoken": [w.lower()]}
        for w, t, b in (("Что", 0.0, "b1"), ("чёрной", 1.2, "b1"), ("дыре", 1.6, "b1"),
                        ("Его", 2.4, "b2"), ("лапшу", 3.4, "b2"), ("сто", 4.0, "b2"),
                        ("Подпишись", 5.2, "b2"))]}
    plan = {"video_id": "redshift_t001", "duration_sec": 6.0,
            "shots": [{"index": 0, "start": 0.0, "end": 6.0, "duration": 6.0, "kind": "footage"}],
            "overlays": [{"type": "cta", "start": 4.0, "end": 6.0, "template": "outro-cta/logo-brand-close"}],
            "templates_used": ["outro-cta/logo-brand-close"]}
    out = D.apply_director(ctx, copy.deepcopy(plan), _script(), words)

    shots = out["shots"]
    assert [round(s["start"], 2) for s in shots] == [0.0, 1.2, 2.4, 3.4]
    assert shots[0]["kind"] == "fullscreen_text" and shots[0]["content"] == "КОТ?"
    assert shots[1]["transition"]["renderer"] == "gravitational_lens"
    assert shots[1]["motion"]["template"] == "kenburns/zoom-in-center"
    assert shots[2]["hero"]["renderer"] == "hero-oversize"
    assert shots[2]["motion"]["renderer"] == "kenburns"          # картинка не стоит
    assert shots[3]["transition"]["renderer"] == "glitch_shader"
    assert all(Path(s["file"]).is_file() for s in shots[1:])
    assert shots[1]["license"] == "public_domain" and shots[1]["source"] == "nasa"
    kinds = [(o["type"], o["template"]) for o in out["overlays"]]
    assert ("dataviz", "data-viz/counter-roll") in kinds
    assert ("cta", "outro-cta/logo-brand-close") in kinds        # финальная кнопка осталась
    assert out["director"]["shots"] == 4
    assert out["subtitles"], "субтитры пересчитаны по новым шотам"


def _mk(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class TestNoAvatarAndPauses:
    def test_avatar_mode_none_plans_footage_only(self, cfg):
        from src.p0_validate.validator import validate_script
        from src.p1_plan.planner import plan
        s = _valid_script()
        s["blocks"][1]["avatar"] = "on"
        s["blocks"][1]["mode_hint"] = "A"
        draft = plan(validate_script(s, cfg), cfg)
        assert draft["avatar_mode"] == "none"
        assert {b["mode"] for b in draft["blocks"]} == {"C"}

    def test_short_no_avatar_video_with_subscribe_like_passes_p0(self, cfg):
        from src.p0_validate.validator import validate_script
        out = validate_script(_valid_script(), cfg)
        assert 25 <= out["_validation"]["estimated_duration_sec"] <= 35

    def test_silence_after_block_is_held_not_cut(self):
        from src.p3_speech_opt.optimizer import plan_segments, silence_holds
        sr = 16000
        audio = np.zeros(sr * 3, dtype=np.float32)
        audio[: sr] = 0.3
        audio[int(1.1 * sr): 2 * sr] = 0.3
        words = [{"word": "раз", "start": 0.0, "end": 1.0},
                 {"word": "два", "start": 1.1, "end": 2.0}]
        holds = silence_holds({"blocks": [{"id": "a", "silence_after_ms": 1500}]},
                              [{"id": "a", "words": words[:1]}, {"id": "b", "words": words[1:]}])
        assert holds == [(1.1, 1.5)]
        segs, cuts = plan_segments(audio, sr, words, threshold_ms=50,
                                   pause_ms_range=(55, 85), ratio=0.0, extra_holds=holds)
        hold = next(c for c in cuts if c["kind"] == "silence_hold")
        assert hold["kept_sec"] + hold["added_sec"] == pytest.approx(1.5, abs=0.01)


class TestQcDefersToTheDirector:
    CHECKS = [{"id": "QC-2", "passed": False, "blocking": True, "detail": ""},
              {"id": "QC-30", "passed": False, "blocking": True, "detail": ""},
              {"id": "QC-8", "passed": False, "blocking": True, "detail": ""}]

    def test_no_avatar_softens_avatar_checks_only(self):
        from src.p12_render_qc.qc import _soften_owner_decisions
        checks = copy.deepcopy(self.CHECKS)
        _soften_owner_decisions(checks, {"avatar_mode": "none"})
        assert [c["blocking"] for c in checks] == [False, True, True]

    def test_director_softens_taste_not_defects(self):
        from src.p12_render_qc.qc import _soften_owner_decisions
        checks = copy.deepcopy(self.CHECKS)
        _soften_owner_decisions(checks, {"director": {"shots": 3}})
        assert [c["blocking"] for c in checks] == [True, False, True]   # громкость — брак


def test_director_catalog_doc_is_current():
    from tools.gen_director_catalog import OUT, build
    assert OUT.read_text(encoding="utf-8") == build(), \
        "docs/director/TEMPLATES.md устарел: python tools/gen_director_catalog.py"


def test_every_agent_entry_point_leads_to_agents_md(repo_root):
    for name in ("CLAUDE.md", "GEMINI.md", "GROK.md", "README.md"):
        assert "AGENTS.md" in (repo_root / name).read_text(encoding="utf-8"), name
    agents = (repo_root / "AGENTS.md").read_text(encoding="utf-8")
    for must in ("СТОП", "director_check.py", "ci_build_request.json", "≤20 %",
                 "owner_style.md"):
        assert must in agents
