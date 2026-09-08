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
        "pexels_v34912823",
        "pixabay_v113379",
        "pexels_v35288383",
        "pexels_v34550739",
        "nasa_PIA13308",
        "nasa_PIA20602",
        "nasa_PIA20603",
        "nasa_PIA19142",
        "nasa_S74-23458",
        "nasa_AFRC2017-0233-007",
        "nasa_as08-14-2506",
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
    found = {r.id for r in idx.search(["abstract", "particles", "quantum"], limit=50)}
    assert "pexels_v34912823" not in found
    assert "pexels_v35288383" not in found
    assert "pexels_v34550739" not in found
    found_grid = {r.id for r in idx.search(["network", "geometric", "cybernetic"], limit=50)}
    assert "pixabay_v113379" not in found_grid
    found_lab = {r.id for r in idx.search(["laboratory", "lab", "clean"], limit=50)}
    assert "nasa_PIA13308" not in found_lab
    found_mars = {r.id for r in idx.search(["mars", "rover", "curiosity"], limit=50)}
    assert not found_mars & {
        "nasa_PIA13308", "nasa_PIA20602", "nasa_PIA20603", "nasa_PIA19142",
    }
    found_sun = {r.id for r in idx.search(["sun", "solar", "flare"], limit=50)}
    assert "nasa_S74-23458" not in found_sun
    found_moon = {r.id for r in idx.search(["moon", "lunar"], limit=50)}
    assert "nasa_as08-14-2506" not in found_moon


def test_pins_file_lists_good_and_deny():
    import json
    pins = json.loads(Path("config/footage_pins.json").read_text(encoding="utf-8"))
    entry = pins["redshift_0042"]
    assert entry["prefer"][:3] == [
        "pexels_v25935014", "pexels_v30775057", "pexels_v18069803",
    ]
    assert "pexels_v18069803" in entry["prefer"]
    assert "pexels_v25935014" in entry["prefer"]
    assert "pexels_v30775057" in entry["prefer"]
    assert "pexels_v20349219" not in entry["prefer"]
    assert "pexels_v7565432" not in entry["prefer"]
    assert "pexels_v7565432" in entry["deny"]
    assert "nasa_*" in entry["deny"]
    assert "nasa_S74-23458" in entry["deny"]
    assert "nasa_PIA13308" in entry["deny"]
    assert "nasa_PIA20602" in entry["deny"]
    assert "nasa_PIA20603" in entry["deny"]
    assert "nasa_PIA19142" in entry["deny"]
    assert int(entry.get("same_asset_max_slots") or 0) == 1
    assert "pexels_v20757503" in entry["deny"]
    assert "pexels_v34912823" in entry["deny"]
    assert "pixabay_v113379" in entry["deny"]
    assert "pexels_v34550739" in entry["deny"]
    assert "pexels_v35288383" in entry["deny"]
    assert "pixabay_v113383" in entry["deny"]
    assert "pexels_v34912823" not in entry["prefer"]
    assert "pixabay_v113379" not in entry["prefer"]
    assert "pexels_v34550739" not in entry["prefer"]
    assert "pexels_v35288383" not in entry["prefer"]
    assert "pixabay_v113383" not in entry["prefer"]


def test_pin_deny_prefix_matches_every_nasa_id():
    from src.p7_broll_search.search import pin_id_denied

    idx = FootageIndex(Path("cache/footage_index.json"))
    deny = {"nasa_*"}
    nasa_ids = [rec.id for rec in idx.items if rec.id.startswith("nasa_")]
    assert nasa_ids
    assert all(pin_id_denied(aid, deny) for aid in nasa_ids)
    assert not pin_id_denied("pexels_v25935014", deny)
    assert pin_id_denied("nasa_S74-23458", {"nasa_S74-23458"})
