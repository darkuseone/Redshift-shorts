"""0042 visual r6: VO-gated punches, punch-family dedupe, empty end tagline."""

from __future__ import annotations

import json
from pathlib import Path

from src.lib.text import (
    enrich_overlay_punch, punch_families_overlap, spoken_onset_for_content,
)
from src.p11_assemble.assemble import gap_phrase, _retime_fullscreen_slots


ROOT = Path(__file__).resolve().parents[1]


def _words():
    sm = json.loads((ROOT / "assets/voice/redshift_0042/speech_map.json").read_text())
    out = []
    for b in sm["blocks"]:
        for w in b["words"]:
            ww = dict(w)
            ww["block_id"] = b["id"]
            out.append(ww)
    return out


def _script_block(bid: str):
    script = json.loads((ROOT / "scripts/redshift_0042.json").read_text())
    return next(b for b in script["blocks"] if b["id"] == bid)


def test_enrich_keeps_authored_two_word_overlay():
    assert enrich_overlay_punch(
        "Проверить нечем",
        "Проверить результат мы не можем — нечем.",
    ) == "Проверить нечем"


def test_enrich_expands_short_stub():
    out = enrich_overlay_punch("5 МИНУТ", "задача решена за пять минут.")
    assert "минут" in out.lower()
    assert "решена" in out.lower()


def test_punch_family_overlap_nechem():
    assert punch_families_overlap("ПРОВЕРИТЬ НЕЧЕМ", "нечем")
    assert punch_families_overlap("Вообще ничем", "НЕЧЕМ")


def test_gap_phrase_blocks_future_punch():
    words = _words()
    b4 = _script_block("b4")
    early = gap_phrase(words, {"start": 18.5, "end": 19.7}, b4, used=set())
    assert "минут" not in early.lower()
    assert "решена" not in early.lower()
    late = gap_phrase(words, {"start": 29.5, "end": 31.8}, b4, used=set())
    assert "минут" in late.lower()


def test_retime_demotes_early_intentional_fs():
    words = _words()
    b4 = _script_block("b4")
    slots = [{
        "index": 10, "start": 18.42, "end": 19.62, "duration": 1.2,
        "kind": "fullscreen_text", "block_id": "b4",
        "content": "решена за пять минут",
        "reason": "полноэкранный текст (§5.2)",
    }]
    _retime_fullscreen_slots(slots, {"blocks": [b4]}, words)
    assert slots[0]["kind"] == "footage"


def test_logo_brand_close_default_tagline_empty():
    from src.lib.render.hyperframes.templates import _LBC_DEFAULT_TAG, _lbc_copy
    assert _LBC_DEFAULT_TAG == ""
    wm, tag, url = _lbc_copy({"wordmark": "REDSHIFT", "tagline": "", "url": "redshift.shorts"})
    assert tag == ""
    assert url == "redshift.shorts"
