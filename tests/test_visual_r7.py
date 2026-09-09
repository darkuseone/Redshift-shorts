"""0042 visual r7: glass cards, plain on-screen copy, Grok thumb cards."""

from __future__ import annotations

import json
from pathlib import Path

from src.lib.text import soften_on_screen_copy
from src.p12_render_qc.render import _thumbnail_prompt


ROOT = Path(__file__).resolve().parents[1]


def test_soften_quantum_chip_to_computer():
    assert "компьютер" in soften_on_screen_copy("Это квантовый чип.").lower()
    assert "чип" not in soften_on_screen_copy("квантовый чип").lower()


def test_soften_english_surface_code_highlight():
    out = soften_on_screen_copy("below the surface code threshold")
    assert "порог" in out.lower()
    assert "surface" not in out.lower()


def test_the_screen_never_carries_a_bracket_gloss():
    """Q3.4: «(квантовый бит)» на карточке — брак, названный критиком дословно.

    Флага `gloss_qubit` больше нет: пояснение уехало в озвучку
    (`gloss_for_speech`), а на экране это теперь инвариант, а не настройка.
    """
    from src.lib.text import gloss_for_speech

    assert soften_on_screen_copy("кубитов") == "кубитов"
    phrase = soften_on_screen_copy("105 кубитов внутри")
    assert "квантовый бит" not in phrase.lower()
    assert "(" not in phrase
    # Пояснение живо — но только голосом и без скобок.
    spoken = gloss_for_speech("105 кубитов внутри", seen=set())
    assert "квантовый бит" in spoken.lower()
    assert "(" not in spoken


def test_thumbnail_prompt_requires_glass_cards_and_markus_like():
    script = json.loads((ROOT / "scripts/redshift_0042.json").read_text())
    prompt = _thumbnail_prompt({"meta": script["meta"]}, script, variant="A")
    low = prompt.lower()
    assert "frosted" in low or "glass" in low
    assert "markus" in low or "green" in low
    assert "morph" in low  # forbidden morph face called out
    assert "card" in low


def test_plaque_brandbook_is_glass_not_opaque():
    bb = json.loads((ROOT / "config/brandbook.json").read_text())
    assert float(bb["plaque"]["bg_alpha"]) <= 0.6
    assert int(bb["plaque"].get("glass_blur_px") or 0) >= 12
    assert float(bb["fullscreen_text"]["scrim_alpha"]) <= 0.45


def test_invert_fact_and_slam_cards_use_glass_css():
    from src.lib.render.hyperframes.templates import overlay_css
    css = overlay_css(json.loads((ROOT / "config/brandbook.json").read_text()))
    compact = css.replace(" ", "").replace("\n", "")
    assert "backdrop-filter:blur" in css
    assert "invert.fs-fact{background:rgba(26,31,46,0.52)" in compact
    assert "invert.fs-slam-card{background:rgba(26,31,46,0.52)" in compact
    assert "lt-dc-card{display:flex;flex-direction:column;gap:12px;" \
           "background:rgba(26,31,46,0.52)" in compact
    assert "lt-dc-card{display:flex;flex-direction:column;gap:12px;" \
           "background:#111214" not in compact


def test_hero_title_behind_first_line_clears_the_crown():
    from src.lib.render.hyperframes.templates import (
        CAP_SHARE, behind_head_top,
    )

    head_top = 620
    size = 150
    top = behind_head_top({"head_top": head_top}, size, rows=2, fallback=300)
    cap = size * CAP_SHARE
    assert top + cap < head_top


def test_late_beat_skips_title_behind_and_clears_crown():
    import json as _json

    from src.lib.templates import TemplateCatalog
    from src.p11_assemble.assemble import _hero_device

    path = ROOT / "templates" / "manifest.json"
    cat = TemplateCatalog(path, _json.loads(path.read_text(encoding="utf-8")))
    content = {
        "word": "ЧИП", "title": "Квантовый чип",
        "head": "КВАНТОВЫЙ", "tail": "ЧИП",
        "lines": ["квантовый", "чип"], "accent_lines": [0],
        "punch": ["квантовый", "чип"], "entries": ["квантовый"],
        "figures": [], "face": (540, 570),
        "head_box": (200, 620, 880, 1400), "brand": None, "icons": [],
    }
    slot = {"index": 8, "role": "twist", "duration": 4.0,
            "start": 32.0, "end": 36.0}
    seen = set()
    for seed in range(24):
        entry = _hero_device(
            cat, slot=slot, content=content, has_alpha=True,
            plate_src=None, recent_videos=[], exclude=[], seed=seed,
            video_duration=40.0)
        if entry:
            seen.add(entry["renderer"])
            assert entry["renderer"] != "hero-title-behind", entry
            assert entry["params"].get("clear_crown") is True
    assert seen


def test_clear_crown_title_sits_entirely_above_head():
    from src.lib.render.hyperframes.templates import (
        CAP_SHARE, behind_head_top,
    )

    head_top = 620
    size = 150
    line = size * 0.94
    top = behind_head_top(
        {"head_top": head_top, "clear_crown": True},
        size, rows=2, fallback=300, bite=0.0, gap=12.0)
    cap = size * CAP_SHARE
    bottom = top + cap + line
    assert bottom <= head_top


def test_0042_cta_has_no_subscribe_button():
    import json as _json

    from src.lib.templates import TemplateCatalog
    from src.p11_assemble.assemble import _build_overlays

    path = ROOT / "templates" / "manifest.json"
    cat = TemplateCatalog(path, _json.loads(path.read_text(encoding="utf-8")))
    plan = {
        "video_id": "renamed_id",
        "show_subscribe": False,
        "duration_sec": 12.0,
        "cta_window": [10.0, 12.0],
        "sources": [],
        "blocks": [{"id": "b1", "role": "cta", "text": "Остаётся вопрос."}],
        "slots": [{"index": 0, "block_id": "b1", "role": "cta",
                   "kind": "footage", "start": 0.0, "end": 12.0,
                   "duration": 12.0}],
    }
    overlays = _build_overlays(None, plan, [], cat, variant="B",
                               seed=1, recent_videos=[], used=[])
    cta = next(o for o in overlays if o["type"] == "cta")
    assert not cta["params"].get("buttonText")
    assert cta["params"].get("subscribe") is False


def test_logo_brand_close_hides_sub_when_subscribe_false():
    from src.lib.render.hyperframes.templates import TemplateCtx, render_fullscreen

    piece = render_fullscreen(TemplateCtx(
        index=1, start=0.0, duration=4.0, target="shot-01", track=1,
        params={"wordmark": "REDSHIFT", "url": "redshift.shorts",
                "subscribe": False, "buttonText": "", "logo_close": True,
                "available_px": 900}))
    node = piece.nodes[0]
    assert "lbc-sub" not in node


def test_latin_heavy_copy_drops_english_not_domains():
    from src.p11_assemble.assemble import _latin_heavy_copy, _on_screen_copy

    assert _latin_heavy_copy("below the surface code threshold")
    assert not _latin_heavy_copy("nature.com")
    assert not _latin_heavy_copy("ниже порога поверхностного кода")
    assert _on_screen_copy("below the surface code threshold",
                           field="title") == ""
    assert _on_screen_copy("nature.com", field="domain") == "nature.com"


def test_source_card_skipped_on_all_avatar_evidence():
    import json as _json

    from src.lib.templates import TemplateCatalog
    from src.p11_assemble.assemble import _build_overlays

    path = ROOT / "templates" / "manifest.json"
    cat = TemplateCatalog(path, _json.loads(path.read_text(encoding="utf-8")))
    plan = {
        "video_id": "redshift_0042",
        "duration_sec": 12.0,
        "cta_window": [10.0, 12.0],
        "sources": [{
            "title": "Работа опубликована в Nature",
            "domain": "nature.com",
            "url": "https://www.nature.com/articles/s41586-024-08449-y",
            "show_on_screen": True,
            "snippet": "Логический кубит живёт дольше физических.",
            "highlight_line": "ниже порога поверхностного кода",
        }],
        "blocks": [{"id": "b3", "role": "evidence",
                    "text": "Работа опубликована в Nature."}],
        "slots": [
            {"index": 0, "block_id": "b3", "role": "evidence",
             "asset_role": "evidence", "kind": "avatar",
             "start": 8.0, "end": 10.5, "duration": 2.5},
            {"index": 1, "block_id": "b3", "role": "evidence",
             "asset_role": "evidence", "kind": "split",
             "start": 10.5, "end": 12.0, "duration": 1.5},
        ],
    }
    overlays = _build_overlays(None, plan, [], cat, variant="B",
                               seed=1, recent_videos=[], used=[])
    assert [o for o in overlays if o["type"] == "source_card"] == []


def test_split_without_top_degrades_to_avatar():
    from src.p11_assemble.assemble import degrade_split_without_top

    slot = {
        "index": 3, "kind": "split", "mode": "B", "needs_asset": True,
        "asset_role": "evidence", "reason": "режим B",
    }
    out = degrade_split_without_top(slot)
    assert out["kind"] == "avatar"
    assert out["mode"] == "A"
    assert out["needs_asset"] is False
    assert slot["kind"] == "avatar"


def test_source_card_anchors_off_avatar():
    import json as _json

    from src.lib.templates import TemplateCatalog
    from src.p11_assemble.assemble import _build_overlays

    path = ROOT / "templates" / "manifest.json"
    cat = TemplateCatalog(path, _json.loads(path.read_text(encoding="utf-8")))
    plan = {
        "video_id": "anchor_test",
        "duration_sec": 12.0,
        "cta_window": [10.0, 12.0],
        "sources": [{
            "title": "Квантовая коррекция ошибок ниже порога поверхностного кода",
            "domain": "nature.com",
            "url": "https://www.nature.com/articles/s41586-024-08449-y",
            "show_on_screen": True,
            "snippet": "Логический кубит живёт дольше физических.",
            "highlight_line": "ниже порога поверхностного кода",
        }],
        "blocks": [{"id": "b3", "role": "evidence",
                    "text": "Работа опубликована в Nature."}],
        "slots": [
            {"index": 0, "block_id": "b3", "role": "evidence",
             "asset_role": "evidence", "kind": "avatar",
             "start": 8.0, "end": 10.0, "duration": 2.0},
            {"index": 1, "block_id": "b3", "role": "evidence",
             "asset_role": "evidence", "kind": "footage",
             "start": 10.0, "end": 12.0, "duration": 2.0},
        ],
    }
    overlays = _build_overlays(None, plan, [], cat, variant="B",
                               seed=1, recent_videos=[], used=[])
    cards = [o for o in overlays if o["type"] == "source_card"]
    assert cards
    assert cards[0]["start"] >= 10.0


def test_hero_device_skips_face_covering_bubbles_on_avatar():
    import json as _json

    from src.lib.templates import TemplateCatalog
    from src.p11_assemble.assemble import _hero_device

    path = ROOT / "templates" / "manifest.json"
    cat = TemplateCatalog(path, _json.loads(path.read_text(encoding="utf-8")))
    content = {
        "word": "ЧИП", "title": "Квантовый чип",
        "head": "КВАНТОВЫЙ", "tail": "ЧИП",
        "lines": ["квантовый", "чип"], "accent_lines": [0],
        "punch": ["квантовый", "чип"], "entries": ["квантовый"],
        "figures": [], "face": (540, 570),
        "head_box": (200, 620, 880, 1400), "brand": None, "icons": [],
    }
    slot = {"index": 3, "role": "twist", "duration": 4.0,
            "start": 12.0, "end": 16.0, "kind": "avatar"}
    seen = set()
    for seed in range(40):
        entry = _hero_device(
            cat, slot=slot, content=content, has_alpha=True,
            plate_src=None, recent_videos=[], exclude=[], seed=seed,
            video_duration=40.0)
        if entry:
            seen.add(entry["renderer"])
            assert entry["renderer"] not in (
                "hero-bubble-typed", "hero-bubble-card"), entry
            assert entry.get("template") != "hero-devices/bubble-typed"
    assert seen


def test_plaque_stops_at_avatar_cut():
    from src.p11_assemble.assemble import _clamp_plaques_at_avatar_cuts

    overlays = [{
        "type": "plaque", "start": 35.0, "end": 39.5,
        "template": "lower-thirds/note-pin",
        "params": {"text": "Проверить нечем", "position": "top"},
    }]
    shots = [
        {"kind": "footage", "start": 31.0, "end": 37.6},
        {"kind": "avatar", "start": 37.6, "end": 42.0},
    ]
    out = _clamp_plaques_at_avatar_cuts(overlays, shots)
    assert out[0]["end"] == 37.6


def test_nasa_plate_is_skipped_for_empty_slot_bg(tmp_path):
    from src.p11_assemble.assemble import _is_nasa_asset, _plate_source

    assert _is_nasa_asset({"asset_id": "nasa_S74-23458", "source": "nasa"})
    assert not _is_nasa_asset({"asset_id": "pexels_v25935014", "source": "pexels"})
    slots = [
        {"index": 0, "kind": "footage", "block_id": "b4"},
        {"index": 1, "kind": "footage", "block_id": "b4"},
    ]
    prepared = {0: {"dst": "/tmp/nasa.jpg", "duration_sec": 3.0}}
    assets = {0: {"asset_id": "nasa_S74-23458", "source": "nasa"}}
    assert _plate_source(slots[1], slots, prepared, assets) is None


def test_compose_zoom_unchanged_for_0042_r7():
    # Steering: do not touch avatar/zoom this run (native 9:16 is NEXT videos).
    import yaml
    cfg = yaml.safe_load((ROOT / "config/config.yaml").read_text())
    assert float(cfg["heygen"]["compose_zoom"]) == 2.7
