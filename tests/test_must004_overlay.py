"""MUST-004: overlay / terminal copy ⊆ script ∪ sources. No invented ids."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.lib.render.hyperframes.templates import TemplateCtx, fs_code_diff
from src.lib.templates import TemplateCatalog
from src.p11_assemble.assemble import (
    _build_overlays,
    _copy_from_script_or_source,
    _fullscreen_params,
    _rich_terminal_copy,
    _script_source_corpus,
    overlay_on_screen_text,
)


ROOT = Path(__file__).resolve().parents[1]
_INVENTED = (
    "willow_check",
    "surface_code",
    "willow_run",
    "classical_eta",
    "universe_age",
    "greet.js",
    "qubits:",
    "error_rate:",
    "trace[0]",
    "status: pending",
    "status: PASS",
)


def _catalog():
    path = ROOT / "templates" / "manifest.json"
    return TemplateCatalog(path, json.loads(path.read_text(encoding="utf-8")))


def _willow_block(**overlay_extra):
    overlay = {"type": "fullscreen_text", "content": "5 МИНУТ"}
    overlay.update(overlay_extra)
    return {
        "id": "b4",
        "role": "twist",
        "text": ("105 кубитов. Ошибка падает вдвое. "
                 "Суперкомпьютеру нужно больше времени, чем существует вселенная."),
        "emphasis_word": "вдвое",
        "overlay": overlay,
    }


def _willow_plan(**overlay_extra):
    block = _willow_block(**overlay_extra)
    return {
        "video_id": "must004_willow",
        "duration_sec": 12.0,
        "cta_window": [10.0, 12.0],
        "meta": {"hook": {"on_screen": "НЕВОЗМОЖНО ПРОВЕРИТЬ"}},
        "sources": [{
            "title": "Квантовая коррекция ошибок ниже порога поверхностного кода",
            "domain": "nature.com",
            "url": "https://www.nature.com/articles/s41586-024-08449-y",
            "show_on_screen": True,
            "snippet": "Логический кубит впервые живёт дольше, чем составляющие его физические кубиты.",
            "highlight_line": "ниже порога поверхностного кода",
        }],
        "blocks": [block],
        "slots": [
            {"index": 0, "block_id": "b4", "role": "twist",
             "asset_role": "evidence", "kind": "footage",
             "start": 2.0, "end": 6.0, "duration": 4.0},
        ],
    }


def _assert_no_invented(blob: str, corpus: str) -> None:
    low = blob.lower()
    corpus_low = corpus.lower()
    for needle in _INVENTED:
        if needle.lower() in low:
            assert needle.lower() in corpus_low, needle


def test_rich_terminal_copy_does_not_invent_willow_ids():
    block = _willow_block()
    before, after, name = _rich_terminal_copy(block, "5 МИНУТ")
    blob = "\n".join([before, after, name])
    _assert_no_invented(blob, _block_corpus(block, "5 МИНУТ"))
    assert "5 МИНУТ" in before
    assert "5 МИНУТ" in after
    assert name == ""


def _block_corpus(block, *extras):
    from src.p11_assemble.assemble import _block_copy_corpus
    return _block_copy_corpus(block, *extras)


def test_authored_terminal_in_script_is_kept():
    block = _willow_block(code_before="load surface_code",
                          code_after="load surface_code",
                          filename="willow_run.log")
    before, after, name = _rich_terminal_copy(block, "5 МИНУТ")
    assert "load surface_code" in before
    assert name == "willow_run.log"


def test_fullscreen_code_diff_layers_stay_in_script():
    catalog = _catalog()
    tpl = catalog.by_id("text-fullscreen/code-diff")
    assert tpl is not None
    plan = _willow_plan()
    block = plan["blocks"][0]
    params = _fullscreen_params(tpl, "5 МИНУТ", block, plan)
    blob = json.dumps(params, ensure_ascii=False)
    corpus = _script_source_corpus(plan)
    _assert_no_invented(blob, corpus)
    assert "5 МИНУТ" in blob
    assert params.get("code") == "5 МИНУТ"
    assert "filename" not in params or params["filename"] == ""


def test_code_diff_html_has_no_default_greet_js():
    piece = fs_code_diff(TemplateCtx(
        index=0, start=0.0, duration=3.0, target="ovl-00", track=5,
        params={"code_diff": True, "code": "5 МИНУТ"}))
    assert piece.nodes
    node = piece.nodes[0]
    assert "МИНУТ" in node
    assert "greet.js" not in node
    assert "willow_check" not in node


def test_overlay_tree_of_source_card_has_no_invented_terminal(cfg):
    plan = _willow_plan()
    overlays = _build_overlays(
        SimpleNamespace(cfg=cfg), plan, [], _catalog(),
        variant="B", seed=1, recent_videos=[], used=[])
    blob = overlay_on_screen_text(*overlays)
    corpus = _script_source_corpus(plan)
    _assert_no_invented(blob, corpus)
    assert "ниже порога поверхностного кода" in blob
    assert _copy_from_script_or_source("# willow_check", corpus) == ""


def test_invented_token_rejected_unless_in_json():
    plan = _willow_plan()
    corpus = _script_source_corpus(plan)
    assert _copy_from_script_or_source("# willow_check", corpus) == ""
    assert _copy_from_script_or_source("surface_code", corpus) == ""
    assert _copy_from_script_or_source("5 МИНУТ", corpus) == "5 МИНУТ"
    assert _copy_from_script_or_source(
        "ниже порога поверхностного кода", corpus
    ) == "ниже порога поверхностного кода"
