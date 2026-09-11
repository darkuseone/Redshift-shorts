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
    from src.lib.render.hyperframes.brand_css import build_css
    css = build_css(bb, {"display": "Oswald-Bold.ttf"})
    assert ".plaque.source-chip{" in css
    assert "max-width:260px" in css


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


def test_source_card_holds_through_mute_hole():
    """0049 semantic probe 17.58 sat 0.3s after a 3.4s card; hold 5.2s."""
    import json as _json

    from src.lib.templates import TemplateCatalog
    from src.p11_assemble.assemble import _build_overlays

    path = ROOT / "templates" / "manifest.json"
    cat = TemplateCatalog(path, _json.loads(path.read_text(encoding="utf-8")))
    plan = {
        "video_id": "card_hold_test",
        "duration_sec": 20.0,
        "cta_window": [18.0, 20.0],
        "sources": [{
            "title": "On the Navier–Stokes Millennium Prize Problem",
            "domain": "openai.com",
            "url": "https://openai.com/index/navier-stokes-solution/",
            "show_on_screen": True,
            "snippet": "Внутренняя модель сильнее GPT-6 Astra нашла доказательство.",
            "highlight_line": "сильнее GPT-6 Astra",
        }],
        "blocks": [{"id": "b3", "role": "evidence",
                    "text": "OpenAI выкладывает работу."}],
        "slots": [
            {"index": 0, "block_id": "b3", "role": "evidence",
             "asset_role": "evidence", "kind": "footage",
             "start": 13.869, "end": 20.0, "duration": 6.131},
        ],
    }
    overlays = _build_overlays(None, plan, [], cat, variant="A",
                               seed=1, recent_videos=[], used=[])
    cards = [o for o in overlays if o["type"] == "source_card"]
    assert cards
    assert abs(cards[0]["start"] - 13.869) < 1e-6
    assert abs(cards[0]["end"] - (13.869 + 5.2)) < 1e-6


def test_source_card_covers_spoken_phrase_plus_tail():
    """0049: card lives through «OpenAI выкладывает работу» + 1s, ≥5.2s."""
    import json as _json

    from src.lib.templates import TemplateCatalog
    from src.p11_assemble.assemble import _build_overlays

    path = ROOT / "templates" / "manifest.json"
    cat = TemplateCatalog(path, _json.loads(path.read_text(encoding="utf-8")))
    plan = {
        "video_id": "card_phrase_test",
        "duration_sec": 28.0,
        "cta_window": [26.0, 28.0],
        "sources": [{
            "title": "On the Navier–Stokes Millennium Prize Problem",
            "domain": "openai.com",
            "url": "https://openai.com/index/navier-stokes-solution/",
            "show_on_screen": True,
            "snippet": "Внутренняя модель сильнее GPT-6 Astra нашла доказательство.",
            "highlight_line": "сильнее GPT-6 Astra",
        }],
        "blocks": [{"id": "b3", "role": "evidence",
                    "text": "OpenAI выкладывает работу."}],
        "slots": [
            {"index": 0, "block_id": "b3", "role": "evidence",
             "asset_role": "evidence", "kind": "footage",
             "start": 13.869, "end": 28.0, "duration": 14.131},
        ],
    }
    words = [
        {"display": "OpenAI", "start": 16.269, "end": 16.719},
        {"display": "выкладывает", "start": 17.042, "end": 17.492},
        {"display": "работу.", "start": 17.709, "end": 18.159},
        {"display": "агентов.", "start": 22.0, "end": 22.4},
    ]
    overlays = _build_overlays(None, plan, words, cat, variant="A",
                               seed=1, recent_videos=[], used=[])
    cards = [o for o in overlays if o["type"] == "source_card"]
    assert cards
    assert cards[0]["start"] == 13.869
    assert cards[0]["end"] >= 18.159 + 1.0 - 1e-6
    assert cards[0]["end"] - cards[0]["start"] >= 5.2 - 1e-6
    assert cards[0]["end"] < 22.0
    assert cards[0]["end"] > 17.58


def test_hero_device_catalog_has_no_face_circle_bubbles():
    import json as _json

    from src.lib.templates import TemplateCatalog
    from src.lib.render.hyperframes.templates import HERO

    path = ROOT / "templates" / "manifest.json"
    cat = TemplateCatalog(path, _json.loads(path.read_text(encoding="utf-8")))
    ids = {t.id for t in cat.all()}
    assert "hero-devices/bubble-card" not in ids
    assert "hero-devices/bubble-typed" not in ids
    assert "hero-bubble-card" not in HERO
    assert "hero-bubble-typed" not in HERO


def test_phone_mock_skipped_when_face_is_in_the_lower_third():
    """ChatGPT-карточка закрывала рот, когда ведущий сидит в нижней трети."""
    import json as _json

    from src.lib.templates import TemplateCatalog
    from src.p11_assemble.assemble import _hero_device

    path = ROOT / "templates" / "manifest.json"
    cat = TemplateCatalog(path, _json.loads(path.read_text(encoding="utf-8")))
    for template in cat.all():
        template.last_used_in = []
    content = {
        "word": "НЕЧЕМ", "title": "Квантовый чип",
        "head": "КВАНТОВЫЙ", "tail": "ЧИП",
        "lines": ["квантовый", "чип", "внутри", "105 кубитов"],
        "accent_lines": [0],
        "punch": ["квантовый", "чип"], "entries": ["квантовый"],
        "figures": [], "face": (540, 1280),
        "head_box": (390, 1080, 690, 1480), "brand": None, "icons": [],
        "ask": "что внутри чипа", "answer": "105 кубитов",
        "gen_prompt": "нарисуй квантовый процессор",
        "caption": "квантовый чип",
    }
    slot = {"index": 1, "role": "setup", "duration": 3.5,
            "start": 3.08, "end": 6.6}
    plate = {"file": "/w/shots/a.mp4", "duration_sec": 3.0}
    seen = set()
    banned = {"hero-phone-mock", "hero-chat-generate", "hero-chat-typing"}
    for head_box in ((390, 1080, 690, 1480), (438, 684, 606, 912), None):
        content["head_box"] = head_box
        for seed in range(24):
            entry = _hero_device(
                cat, slot=slot, content=content, has_alpha=True,
                plate_src=plate, recent_videos=[], exclude=[], seed=seed)
            if entry:
                seen.add(entry["renderer"])
                assert entry["renderer"] not in banned, (head_box, entry)
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


def test_ticker_plate_is_skipped_for_non_cta_empty_slot():
    from src.p11_assemble.assemble import _plate_source

    slots = [
        {"index": 2, "kind": "footage", "block_id": "b4", "role": "develop"},
        {"index": 9, "kind": "footage", "block_id": "b4", "role": "develop"},
        {"index": 16, "kind": "footage", "block_id": "b6", "role": "cta"},
    ]
    prepared = {
        2: {"dst": "/tmp/lattice.mp4", "duration_sec": 1.4},
        16: {"dst": "/tmp/ticker.mp4", "duration_sec": 3.7},
    }
    assets = {
        2: {"asset_id": "pexels_v35003022", "source": "pexels", "tags": ["lattice"]},
        16: {"asset_id": "pexels_v38431825", "source": "pexels",
             "tags": ["ticker", "finance"]},
    }
    plate = _plate_source(slots[1], slots, prepared, assets)
    assert plate is not None
    assert plate["file"] == "/tmp/lattice.mp4"


def test_fluid_empty_slot_skips_typing_neighbor_plate():
    """0049 41.02: empty NS slot parallaxed the Lean typing crop."""
    from src.p11_assemble.assemble import _plate_source

    slots = [
        {"index": 12, "kind": "footage", "block_id": "b4", "role": "develop",
         "start": 36.3, "end": 38.9},
        {"index": 13, "kind": "footage", "block_id": "b4", "role": "develop",
         "start": 38.9, "end": 41.6},
        {"index": 8, "kind": "footage", "block_id": "b4", "role": "evidence",
         "start": 23.5, "end": 25.7},
    ]
    prepared = {
        12: {"dst": "/tmp/pexels_v12893579_crop.mp4", "duration_sec": 2.5},
        8: {"dst": "/tmp/pexels_v10884417_crop.mp4", "duration_sec": 2.2},
    }
    assets = {
        12: {
            "asset_id": "pexels_v12893579",
            "query": "hands typing keyboard code editor",
            "page_url": "https://www.pexels.com/video/hands-typing-on-laptop-keyboard-12893579/",
            "source": "pexels",
        },
        8: {
            "asset_id": "pexels_v10884417",
            "query": "industrial pipes water plant",
            "page_url": "https://www.pexels.com/video/water-flowing-through-pipes-10884417/",
            "source": "pexels",
        },
    }
    words = [
        {"display": "Навье-Стокса.", "start": 39.5, "end": 40.0},
        {"display": "Страшное", "start": 40.8, "end": 41.3},
    ]
    plate = _plate_source(slots[1], slots, prepared, assets, plan={}, words=words)
    assert plate is not None
    assert plate["file"] == "/tmp/pexels_v10884417_crop.mp4"


def test_on_screen_spelling_is_nichem():
    from src.lib.text import prefer_nichem_spelling, soften_on_screen_copy

    assert prefer_nichem_spelling("НЕЧЕМ") == "НИЧЕМ"
    assert prefer_nichem_spelling("Проверить нечем") == "Проверить ничем"
    assert soften_on_screen_copy("НЕЧЕМ") == "НИЧЕМ"
    out = soften_on_screen_copy("Проверить нечем")
    assert "ничем" in out.lower()
    assert "нечем" not in out.lower()


def test_script_0042_spells_nichem_on_screen():
    script = json.loads((ROOT / "scripts/redshift_0042.json").read_text())
    hook = next(b for b in script["blocks"] if b["id"] == "b1")
    assert hook["overlay"]["content"] == "НИЧЕМ"
    twist = next(b for b in script["blocks"] if b["id"] == "b5")
    assert "ничем" in twist["overlay"]["content"].lower()
    assert "нечем" not in twist["overlay"]["content"].lower()


def test_source_chip_does_not_mute_captions():
    from src.p11_assemble.assemble import _plaque_covers_captions

    assert not _plaque_covers_captions({
        "type": "plaque", "template": "lower-thirds/source-domain",
        "params": {"source_chip": True, "position": "bottom",
                   "direction": "left"},
    })


def test_source_chip_bbox_is_bottom_left(cfg):
    from src.lib.render.canvas import overlay_layout_bbox

    box = overlay_layout_bbox({
        "type": "plaque",
        "template": "lower-thirds/source-domain",
        "params": {"source_chip": True},
    }, cfg.brandbook)
    assert box[2] - box[0] <= 270
    assert box[3] - box[1] <= 64
    assert box[0] <= 90
    safe = cfg.brandbook["safe_zones"]["work_area"]
    assert box[3] <= float(safe["y_max"]) + 1e-6
    from src.p11_assemble.assemble import _clamp_end_before_next_avatar

    shots = [
        {"kind": "split", "start": 8.0, "end": 10.52},
        {"kind": "split", "start": 10.52, "end": 13.04},
        {"kind": "avatar", "start": 31.84, "end": 36.21},
    ]
    end = _clamp_end_before_next_avatar(8.35, 10.55, shots)
    assert end == 10.55


def test_split_karaoke_sits_under_the_paper_letterbox():
    from src.p11_assemble.assemble import _stamp_subtitle_baselines

    subs = [
        {"display": "ОПУБЛИКОВАНА", "start": 8.2, "end": 8.8},
        {"display": "КУБИТОВ", "start": 4.0, "end": 4.5},
        {"display": "СУПЕРКОМПЬЮТЕРУ", "start": 22.0, "end": 22.6},
    ]
    shots = [
        {"kind": "avatar", "start": 3.0, "end": 6.6},
        {"kind": "split", "start": 8.0, "end": 15.5},
        {"kind": "footage", "start": 20.8, "end": 30.6},
    ]
    brand = {
        "canvas": {"height": 1920},
        "subtitles": {
            "baseline_y_default": 1180,
            "baseline_y_avatar_shift": 720,
        },
    }
    _stamp_subtitle_baselines(subs, shots, brand)
    assert abs(subs[0]["baseline_y"] - (1920 * 0.52 - 180)) < 1e-6
    assert 700 <= subs[0]["baseline_y"] <= 900
    assert "baseline_y" not in subs[1]
    assert subs[2]["baseline_y"] == 1180


def test_portrait_split_karaoke_sits_on_avatar_chest(tmp_path):
    from PIL import Image
    from src.p11_assemble.assemble import _stamp_subtitle_baselines

    portrait = tmp_path / "portrait.jpg"
    Image.new("RGB", (1080, 1920), "black").save(portrait)
    subs = [{"display": "ПРОЖИЛ", "start": 11.5, "end": 11.9}]
    shots = [{"kind": "split", "start": 10.5, "end": 13.0,
              "bg_file": str(portrait)}]
    _stamp_subtitle_baselines(subs, shots, {"canvas": {"height": 1920}})
    y = subs[0]["baseline_y"]
    seam = 1920 * 0.52
    assert y > seam
    assert y >= 1500
