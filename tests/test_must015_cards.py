"""MUST-015: card copy from script/source, plaque enter 200–280 ms, SFX skip report."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.lib.render.canvas import plaque_enter_ms, plaque_enter_sec
from src.lib.render.hyperframes.templates import TemplateCtx, ov_source_card
from src.lib.templates import TemplateCatalog
from src.p10_audio.audio_build import _plan_sfx, sfx_skipped_from_events
from src.p11_assemble.assemble import (
    _build_overlays,
    _copy_from_script_or_source,
    _script_source_corpus,
)


ROOT = Path(__file__).resolve().parents[1]


def _catalog():
    path = ROOT / "templates" / "manifest.json"
    return TemplateCatalog(path, json.loads(path.read_text(encoding="utf-8")))


def _card_plan(*, highlight: str = "X", snippet: str = "факт X из статьи"):
    return {
        "video_id": "must015",
        "duration_sec": 12.0,
        "cta_window": [10.0, 12.0],
        "sources": [{
            "title": "Заголовок источника",
            "domain": "nature.com",
            "url": "https://www.nature.com/articles/x",
            "show_on_screen": True,
            "snippet": snippet,
            "highlight_line": highlight,
        }],
        "blocks": [{
            "id": "b1", "role": "evidence",
            "text": "В статье сказано: факт X из статьи.",
            "overlay": {"type": "none"},
        }],
        "slots": [
            {"index": 0, "block_id": "b1", "role": "evidence",
             "asset_role": "evidence", "kind": "footage",
             "start": 2.0, "end": 6.0, "duration": 4.0},
        ],
    }


def test_highlight_line_x_is_shown_verbatim(cfg):
    plan = _card_plan(highlight="X")
    overlays = _build_overlays(
        SimpleNamespace(cfg=cfg), plan, [], _catalog(),
        variant="B", seed=1, recent_videos=[], used=[])
    cards = [o for o in overlays if o["type"] == "source_card"]
    assert cards, "source card must appear on footage evidence"
    assert cards[0]["params"]["highlight_line"] == "X"
    piece = ov_source_card(TemplateCtx(
        index=0, start=2.0, duration=3.0, target="ovl-00", track=5,
        params=cards[0]["params"]))
    assert piece.nodes
    assert ">X<" in piece.nodes[0] or "X" in piece.nodes[0]


def test_invented_card_copy_is_rejected():
    corpus = _script_source_corpus(_card_plan())
    assert _copy_from_script_or_source("X", corpus) == "X"
    assert _copy_from_script_or_source("# willow_check", corpus) == ""
    assert _copy_from_script_or_source("surface_code", corpus) == ""


def test_card_enter_duration_is_brandbook_window(cfg):
    lo, hi = 0.20, 0.28
    assert lo <= plaque_enter_sec(brandbook=cfg.brandbook) <= hi
    assert plaque_enter_ms(660, brandbook=cfg.brandbook) == 280
    assert plaque_enter_ms(100, brandbook=cfg.brandbook) == 200
    plan = _card_plan()
    overlays = _build_overlays(
        SimpleNamespace(cfg=cfg), plan, [], _catalog(),
        variant="B", seed=1, recent_videos=[], used=[])
    cards = [o for o in overlays if o["type"] in ("source_card", "plaque")]
    assert cards
    for ovl in cards:
        assert lo <= float(ovl["enter_sec"]) <= hi
        assert 200 <= int(ovl["enter_ms"]) <= 280


def test_source_card_tween_uses_clamped_enter():
    piece = ov_source_card(TemplateCtx(
        index=0, start=1.0, duration=3.0, target="ovl-00", track=5,
        params={"title": "Заголовок", "snippet": "строка X",
                "highlight_line": "X", "domain": "nature.com",
                "enter_ms": 260}))
    tween = piece.tweens[0]
    assert "duration:0.26" in tween
    assert "duration:0.66" not in tween


def test_card_overlay_fires_card_appear_not_picture_in(cfg):
    plan = {
        "video_id": "must015_sfx",
        "duration_sec": 8.0,
        "cta_window": [6.0, 8.0],
        "blocks": [{
            "id": "b1", "sfx": "none",
            "overlay": {"type": "source_card", "content": "X"},
        }],
        "slots": [
            {"index": 0, "start": 0.0, "end": 6.0, "kind": "footage",
             "block_id": "b1", "transition_in": "cut"},
        ],
    }
    events = _plan_sfx(plan, cfg)
    cards = [e for e in events if e["intent"] == "card_appear"]
    pictures = [e for e in events if e["intent"] == "picture_in"]
    assert cards
    assert not pictures


def test_missing_sfx_file_is_reported_in_sfx_skipped():
    events = [
        {"t": 1.2, "intent": "card_appear", "role": "pop",
         "status": "file_missing", "file": "/tmp/no-such-click.wav",
         "why": "карточка блока b1"},
        {"t": 3.0, "intent": "avatar_in", "status": "placed", "asset_id": "whoosh"},
    ]
    skipped = sfx_skipped_from_events(events)
    assert skipped
    assert skipped[0]["intent"] == "card_appear"
    assert skipped[0]["status"] == "file_missing"
    report = {"sfx_skipped": skipped}
    assert report["sfx_skipped"]
