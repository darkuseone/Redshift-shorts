"""P1-1: poisoned footage index rows stay quarantined."""

from __future__ import annotations

from pathlib import Path

from src.lib.manifest import FootageIndex, tag_url_coherence


def test_poisoned_ids_not_returned_by_search():
    idx = FootageIndex(Path("cache/footage_index.json"))
    poisoned = {
        "pexels_v20757503",
        "pexels_v20068211",
        "pexels_v20349634",
    }
    for asset_id in poisoned:
        rec = idx.by_id(asset_id)
        assert rec is not None
        assert rec.quarantined or tag_url_coherence(rec) < 0.15

    assert "pexels_v20757503" not in {
        r.id for r in idx.search(["processor", "macro", "shot"], limit=50)
    }
    assert "pexels_v20068211" not in {
        r.id for r in idx.search(["cryostat", "laboratory"], limit=50)
    }
    assert "pexels_v20349634" not in {
        r.id for r in idx.search(["galaxy", "nebula"], limit=50)
    }


def test_pins_file_lists_good_and_deny():
    import json
    pins = json.loads(Path("config/footage_pins.json").read_text(encoding="utf-8"))
    entry = pins["redshift_0042"]
    assert "pexels_v18069803" in entry["prefer"]
    assert "pexels_v20757503" in entry["deny"]
