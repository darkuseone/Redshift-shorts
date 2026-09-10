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
    lava = idx.by_id("pixabay_v144678")
    assert lava is not None
    assert lava.quarantined
    found_lava = {r.id for r in idx.search(["volcano", "lava", "magma"], limit=50)}
    assert "pixabay_v144678" not in found_lava


def test_pins_file_lists_good_and_deny():
    import json
    pins = json.loads(Path("config/footage_pins.json").read_text(encoding="utf-8"))
    entry = pins["redshift_0042"]
    assert entry["prefer"][:2] == [
        "pexels_v25935014", "pexels_v18069803",
    ]
    assert "pexels_v18069803" in entry["prefer"]
    assert "pexels_v25935014" in entry["prefer"]
    assert "pexels_v30775057" not in entry["prefer"]
    assert "pexels_v30775057" in entry["deny"]
    assert "pexels_v20349276" in entry["deny"]
    assert "pexels_v27975940" in entry["deny"]
    assert "pexels_v20436933" in entry["deny"]
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
    assert "pixabay_v144678" in entry["deny"]
    assert "pexels_v34912823" not in entry["prefer"]
    assert "pixabay_v113379" not in entry["prefer"]
    assert "pexels_v34550739" not in entry["prefer"]
    assert "pexels_v35288383" not in entry["prefer"]
    assert "pixabay_v113383" not in entry["prefer"]
    assert "fp_blue_bubbles" in entry["deny"]
    assert "fp_blue_bubbles" not in entry["prefer"]
    assert "pexels_v16727463" in entry["deny"]
    assert "pexels_v19162466" in entry["deny"]
    assert "pexels_v28613453" in entry["deny"]
    assert "pexels_v29669602" in entry["deny"]
    assert "pexels_v35003022" in entry["prefer"]
    assert "pexels_v38431825" in entry["prefer"]
    assert "pixabay_v200531" in entry["prefer"]
    assert "press_21bc8e2d72" in entry["prefer"]
    assert "pexels_v19532053" in entry["deny"]
    assert "pexels_v19532053" not in entry["prefer"]
    forty_nine = pins["redshift_0049"]
    assert "fp_server_room" in forty_nine["prefer"]
    assert "fp_water_vortex" in forty_nine["prefer"]
    assert "fp_cracked_wall" in forty_nine["prefer"]
    assert "fp_red_heartbeat" in forty_nine["deny"]
    assert "fp_blue_bubbles" in forty_nine["deny"]
    assert "fp_rock_surface" in forty_nine["deny"]
    assert "fp_red_heartbeat" not in forty_nine["prefer"]
    assert int(forty_nine.get("same_asset_max_slots") or 0) == 1


def test_pin_deny_prefix_matches_every_nasa_id():
    from src.p7_broll_search.search import pin_id_denied

    idx = FootageIndex(Path("cache/footage_index.json"))
    deny = {"nasa_*"}
    nasa_ids = [rec.id for rec in idx.items if rec.id.startswith("nasa_")]
    assert nasa_ids
    assert all(pin_id_denied(aid, deny) for aid in nasa_ids)
    assert not pin_id_denied("pexels_v25935014", deny)
    assert pin_id_denied("nasa_S74-23458", {"nasa_S74-23458"})


def test_tag_url_coherence_reads_page_url_and_attribution():
    """P7 кладёт URL в page_url; без него orphan с тегами pexels/video получал 0."""
    rec = {
        "tags": ["pexels", "video"],
        "page_url": "https://www.pexels.com/video/25935014/",
        "attribution": "pexels / local cache",
        "source": "pexels",
        "license": "Pexels License",
    }
    assert tag_url_coherence(rec) >= 0.15
