"""0050 remount: spoken lock, overlays, pins, query sync — no TTS rewrite."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.lib.pin_match import (
    filter_queries_for_beat, pin_slot_prefer_key, slot_visual_beat,
)
from src.lib.query import compile_slot_search, negative_reject_reason, slot_negatives
from src.lib.text import sync_broll_from_script
from src.p7_broll_search.search import pin_id_denied
from src.steps import build_pipeline

REPO = Path(__file__).resolve().parents[1]
SPOKEN = {
    "b1": "Миллион долларов. Четверть века никто не брал.",
    "b2": (
        "Восьмого сентября модель без чата закрыла кусок этой задачи. "
        "Семь задач тысячелетия. Миллион долларов за каждую. Четверть века. "
        "Это формулы воды, воздуха и крови — не мелки на доске."
    ),
    "b3": (
        "Восьмого сентября две тысячи двадцать шесть OpenAI выкладывает работу. "
        "Искал не чат, а внутренняя модель сильнее GPT-6 Astra."
    ),
    "b4": (
        "Десять тысяч агентов. Восемьдесят восемь часов. "
        "Два миллиона семьсот тысяч сообщений. "
        "Семнадцать часов переложили доказательство в Lean."
    ),
    "b5": (
        "Называются уравнения Навье-Стокса. Страшное имя, простой смысл: "
        "как течёт жидкость, когда её толкают. Погода. Крыло самолёта. "
        "Трубы в доме. Ток крови. Если формула врёт — самолёт не извиняется."
    ),
    "b6": (
        "Lean проверяет каждый шаг. Но пункт без внешней силы Клей не принял. "
        "Миллион OpenAI не берёт. Это не закрыли задачу тысячелетия целиком. "
        "Это первая дыра, которую четверть века считали глухой."
    ),
    "b7": "Какую из оставшихся шести разберём следующей?",
}


def _script() -> dict:
    return json.loads((REPO / "scripts" / "redshift_0050.json").read_text(encoding="utf-8"))


def _pins() -> dict:
    return json.loads((REPO / "config" / "footage_pins.json").read_text(encoding="utf-8"))


def test_0050_spoken_text_is_byte_identical():
    script = _script()
    got = {block["id"]: block["text"] for block in script["blocks"]}
    b5_ids = ("b5", "b5b", "b5c", "b5d", "b5e")
    assert " ".join(got[i] for i in b5_ids) == SPOKEN["b5"]
    for key in ("b1", "b2", "b3", "b4", "b6", "b7"):
        assert got[key] == SPOKEN[key]
    assert script["cta"]["text"] == SPOKEN["b7"]


def test_0050_hook_and_overlays_pass_anti_checklist():
    script = _script()
    hook = (script.get("meta") or {}).get("hook") or {}
    assert hook.get("on_screen") == "$1 000 000"
    assert hook.get("style") == "number_slam"
    assert hook.get("style") != "blackout_word"
    by_id = {block["id"]: block for block in script["blocks"]}
    assert by_id["b1"]["avatar"] == "off"
    assert by_id["b1"]["overlay"]["content"] == "$1 000 000"
    assert "ЛЕТ" not in by_id["b2"]["overlay"]["content"]
    assert by_id["b2"]["overlay"]["content"] == "7 · $1 000 000 · 25 Y"
    assert by_id["b3"]["overlay"]["content"] == "GPT-6 ASTRA"
    assert "ШЕСТЬ" not in by_id["b3"]["overlay"]["content"]
    assert by_id["b4"]["overlay"]["content"] == "10 000 · 88 Ч · 2 700 000 · 17 Ч LEAN"
    assert "80 8" not in by_id["b4"]["overlay"]["content"]
    labels = {
        "b5": ("FLUIDS", "lower-thirds/dark-card"),
        "b5b": ("WEATHER", "lower-thirds/clean-bar"),
        "b5c": ("AIRFOIL", "lower-thirds/note-pin"),
        "b5d": ("VALVES", "lower-thirds/note-pin"),
        "b5e": ("PLASMA", "lower-thirds/metric-badge"),
    }
    for bid, (label, hint) in labels.items():
        ov = by_id[bid]["overlay"]
        assert ov["type"] == "lower_third"
        assert ov["content"] == label
        assert ov["content"].strip()
        assert ov["template_hint"] == hint
        assert "bigtext-mask-footage" not in ov.get("template_hint", "")
    assert len({v[0] for v in labels.values()}) == 5
    assert by_id["b6"]["overlay"]["type"] == "lower_third"
    assert by_id["b6"]["overlay"]["content"] == "REJECTED"
    assert by_id["b6"]["overlay"]["template_hint"] == "lower-thirds/dark-card"
    assert "НЕТ" not in by_id["b6"]["overlay"]["content"]
    assert by_id["b7"]["overlay"]["type"] == "lower_third"
    assert by_id["b7"]["overlay"]["content"] == "FOLLOWUP"
    assert by_id["b7"]["overlay"]["template_hint"] == "lower-thirds/name-title"
    assert "РЕДШИФТ" not in by_id["b7"]["overlay"]["content"]
    assert not by_id["b7"]["overlay"]["content"].endswith(".")
    assert "bigtext-mask-footage" not in by_id["b7"]["overlay"].get("template_hint", "")
    source = script["sources"][0]
    assert source["url"] == "https://openai.com/index/navier-stokes-solution/"
    assert source["show_on_screen"] is True


def test_0050_pins_prefer_deny_and_keep_0042_0048():
    pins = _pins()
    assert "redshift_0042" in pins
    assert "redshift_0048" in pins
    entry = pins["redshift_0050"]
    prefer = entry["prefer"]
    deny = entry["deny"]
    assert prefer[:6] == [
        "magnific_0050_weather", "magnific_0050_wing",
        "magnific_0050_pipes", "magnific_0050_blood",
        "magnific_0050_stamp", "magnific_0050_city",
    ]
    for aid in (
        "fp_server_room", "fp_code_editor", "fp_chalkboard_eq",
        "pexels_v7565432", "pexels_v38431825",
        "magnific_0050_weather", "magnific_0050_stamp", "magnific_0050_city",
    ):
        assert aid in prefer, aid
    by_block = entry.get("by_block") or {}
    assert by_block.get("b3") == "fp_server_room"
    assert by_block.get("b4") == "fp_code_editor"
    assert by_block.get("b5b") == "magnific_0050_weather"
    assert by_block.get("b6") == "magnific_0050_stamp"
    assert by_block.get("b7") == "magnific_0050_city"
    assert "freepik_136238" not in prefer
    assert "press_21bc8e2d72" not in prefer
    assert "press_21bc8e2d72" in deny
    assert "nasa_*" in deny
    assert "freepik_136238" in deny
    for aid in (
        "fp_cracked_wall", "fp_plaster_wall", "fp_peeling_wall",
        "fp_cracked_concrete", "fp_cracked_earth", "fp_rock_surface",
        "fp_corroded_mesh", "pixabay_v144678",
        "grok_cryostat_0042", "pexels_v20068211", "pexels_v30775057",
        "freepik_136238", "pexels_v25242933",
    ):
        assert aid in deny, aid
        assert aid not in prefer
    assert int(entry["same_asset_max_slots"]) == 1
    assert pin_id_denied("nasa_PIA13308", set(deny))
    assert pin_id_denied("nasa_S74-23458", set(deny))
    assert pin_id_denied("freepik_136238", set(deny))
    assert pin_id_denied("pexels_v25242933", set(deny))


def test_0050_sync_broll_from_script_copies_queries_and_hook():
    script = _script()
    plan = {
        "video_id": "redshift_0050",
        "hook": {"on_screen": "ФУРОР", "style": "blackout_word"},
        "blocks": [{"id": "b2", "visual_intent": "old", "broll_queries": ["old q"]}],
        "slots": [{
            "block_id": "b2",
            "visual_intent": "old",
            "queries": ["old q"],
        }],
    }
    assert sync_broll_from_script(plan, script=script) >= 1
    assert plan["hook"]["on_screen"] == "$1 000 000"
    assert plan["hook"]["style"] == "number_slam"
    assert plan["slots"][0]["queries"] == script["blocks"][1]["broll_queries"]
    assert "Live water" in plan["slots"][0]["visual_intent"]


def test_0050_water_and_wing_pins_lock_speech_ticker_skips_hook():
    water = {
        "index": 2, "role": "setup", "asset_role": "broll",
        "visual_intent": "Live water / river current",
        "start": 4.0, "end": 8.0,
    }
    words_water = [
        {"display": "формулы", "start": 4.1, "end": 4.4},
        {"display": "воды", "start": 4.4, "end": 4.8},
    ]
    wing = {
        "index": 8, "role": "develop", "asset_role": "broll",
        "visual_intent": "airplane wing",
        "start": 36.0, "end": 39.0,
    }
    words_wing = [
        {"display": "Крыло", "start": 36.2, "end": 36.6},
        {"display": "самолёта", "start": 36.6, "end": 37.1},
    ]
    clay = {
        "index": 20, "role": "twist", "asset_role": "interstitial",
        "visual_intent": "Clay institute documents stamp REJECT",
        "start": 50.0, "end": 54.0,
    }
    words_clay = [
        {"display": "Клей", "start": 50.2, "end": 50.6},
        {"display": "не", "start": 50.6, "end": 50.8},
        {"display": "принял", "start": 50.8, "end": 51.2},
    ]
    hook = {
        "index": 0, "role": "hook", "asset_role": "broll",
        "visual_intent": "Motion from frame 0 data-center",
        "start": 0.0, "end": 3.0,
    }
    prefer = ["fp_water_vortex", "freepik_8945319", "fp_stapling_docs",
              "pexels_v38431825"]
    vortex, _ = pin_slot_prefer_key("fp_water_vortex", water, prefer, words=words_water)
    wing_bonus, _ = pin_slot_prefer_key(
        "freepik_8945319", wing, prefer, words=words_wing)
    staple, _ = pin_slot_prefer_key(
        "fp_stapling_docs", clay, prefer, words=words_clay)
    ticker_hook, _ = pin_slot_prefer_key(
        "pexels_v38431825", hook, prefer, words=[
            {"display": "Миллион", "start": 0.2, "end": 0.6},
        ])
    numbers = {
        "index": 10, "role": "develop", "asset_role": "broll",
        "visual_intent": "Dark translucent number cards ticker screen",
        "start": 24.0, "end": 28.0,
    }
    ticker_numbers, _ = pin_slot_prefer_key(
        "pexels_v38431825", numbers, prefer, words=[
            {"display": "агентов", "start": 24.2, "end": 24.7},
        ])
    assert vortex < 0
    assert wing_bonus < 0
    assert staple < 0
    assert ticker_hook > 0
    assert ticker_numbers < 0


def test_0050_queries_skip_html_tutorial_and_cracked_wall():
    script = _script()
    plan = {
        "blocks": script["blocks"],
        "sources": script.get("sources") or [],
        "category": "ai",
        "video_id": "redshift_0050",
        "meta": script.get("meta") or {},
    }
    for index, block in enumerate(script["blocks"]):
        slot = {
            "index": index,
            "block_id": block["id"],
            "role": block.get("role", ""),
            "queries": list(block.get("broll_queries") or []),
            "visual_intent": block.get("visual_intent") or "",
        }
        compiled = compile_slot_search(slot, plan, count=5)
        blob = " ".join(compiled["queries"]).lower()
        assert "cracked" not in blob, (block["id"], compiled["queries"])
        assert "plaster" not in blob, compiled["queries"]
        assert "html tutorial" not in blob
        assert "hello js" not in blob
        assert "html tutorial" in slot_negatives(slot, plan)
        assert "cracked wall" in slot_negatives(slot, plan)
    assert negative_reject_reason(
        "learn javascript html css tutorial hello js",
        ["html tutorial"],
    )


def test_p7_p8_config_inputs_include_footage_pins():
    pipe = build_pipeline()
    by_name = {step.name: step for step in pipe.steps}
    assert "config/footage_pins.json" in by_name["P7"].config_inputs
    assert "config/footage_pins.json" in by_name["P8"].config_inputs


def test_0050_queries_name_life_beats_not_red_particles():
    script = _script()
    by_id = {block["id"]: block for block in script["blocks"]}
    blob = " ".join(
        " ".join(by_id[i]["broll_queries"])
        for i in ("b5", "b5b", "b5c", "b5d", "b5e")
    ).lower()
    assert "weather radar" in blob
    assert "airplane wing" in blob
    assert "pipes" in blob
    assert "blood" in blob
    assert "vortex" in " ".join(by_id["b5"]["broll_queries"]).lower()
    b7 = " ".join(by_id["b7"]["broll_queries"]).lower()
    assert "city night" in b7
    assert "notebook" in b7
    assert "red accent" not in b7
    assert "particles" not in b7


def test_0050_beat_pins_lock_speech_and_cta_city():
    fluids = {
        "index": 13, "role": "develop", "asset_role": "broll",
        "visual_intent": "flowing liquid current",
        "start": 34.6, "end": 41.3,
    }
    fluids_words = [
        {"display": "Называются", "start": 34.6, "end": 35.1},
        {"display": "уравнения", "start": 35.2, "end": 35.6},
        {"display": "Навье-Стокса", "start": 35.7, "end": 36.6},
        {"display": "жидкость", "start": 39.7, "end": 40.2},
    ]
    radar = {
        "index": 14, "role": "develop", "asset_role": "broll",
        "visual_intent": "weather radar storm satellite screen",
        "start": 41.3, "end": 42.4,
    }
    radar_words = [
        {"display": "Погода", "start": 41.4, "end": 42.3},
    ]
    blood = {
        "index": 16, "role": "develop", "asset_role": "broll",
        "visual_intent": "blood cells",
        "start": 46.0, "end": 49.0,
    }
    blood_words = [
        {"display": "Ток", "start": 46.2, "end": 46.5},
        {"display": "крови", "start": 46.5, "end": 47.0},
    ]
    cta = {
        "index": 24, "role": "cta", "asset_role": "broll",
        "visual_intent": "city night aerial",
        "start": 63.0, "end": 66.0,
    }
    cta_words = [
        {"display": "Какую", "start": 63.2, "end": 63.6},
        {"display": "шести", "start": 64.0, "end": 64.4},
    ]
    prefer = [
        "magnific_0050_weather", "magnific_0050_blood",
        "fp_water_vortex", "freepik_4175316", "freepik_6468280",
        "freepik_5504514", "fp_stapling_docs",
    ]
    mag_weather_on_fluids, _ = pin_slot_prefer_key(
        "magnific_0050_weather", fluids, prefer, words=fluids_words)
    water_on_fluids, _ = pin_slot_prefer_key(
        "fp_water_vortex", fluids, prefer, words=fluids_words)
    mag_weather, _ = pin_slot_prefer_key(
        "magnific_0050_weather", radar, prefer, words=radar_words)
    water_on_radar, _ = pin_slot_prefer_key(
        "fp_water_vortex", radar, prefer, words=radar_words)
    blood_bonus, _ = pin_slot_prefer_key(
        "magnific_0050_blood", blood, prefer, words=blood_words)
    city_bonus, _ = pin_slot_prefer_key(
        "freepik_5504514", cta, prefer, words=cta_words)
    assert slot_visual_beat(fluids, fluids_words) == "fluids"
    assert slot_visual_beat(radar, radar_words) == "weather"
    assert slot_visual_beat(blood, blood_words) == "blood"
    assert slot_visual_beat(cta, cta_words) == "city"
    assert mag_weather_on_fluids > 0
    assert water_on_fluids < 0
    assert mag_weather < 0
    assert water_on_radar > 0
    assert blood_bonus < 0
    assert city_bonus < 0


def test_0050_filter_queries_keeps_matching_beat():
    queries = [
        "weather radar storm satellite screen",
        "airplane wing in flight clouds",
        "industrial water pipes valves factory",
            "red blood cells under microscope",
    ]
    assert filter_queries_for_beat(queries, "wing") == [queries[1]]
    assert filter_queries_for_beat(queries, "blood") == [queries[3]]
    assert filter_queries_for_beat(queries, "") == queries


def test_0050_cta_wordmark_latin_never_cyrillic():
    from src.p11_assemble.assemble import (
        _cta_close_style, _cta_wordmark, _template_excludes_for,
    )

    plan = {
        "video_id": "redshift_0050",
        "blocks": [{"role": "cta", "overlay": {"content": "REDSHIFT"}}],
    }
    assert _cta_wordmark(plan, "РЕДШИФТ") == "REDSHIFT"
    assert _cta_wordmark(plan, "РЕДШИФТ.") == "REDSHIFT"
    style = _cta_close_style(plan)
    assert style["invert"] is False
    assert style["tone"] != "paper"
    assert style.get("compact") is True
    assert style.get("no_period") is True
    assert style.get("position") == "bottom"
    bans = _template_excludes_for(plan)
    assert "text-fullscreen/bigtext-mask-footage" in bans


def test_0050_authored_overlay_blocks_gap_phrase():
    from src.p11_assemble.assemble import _authored_overlay_owns_gap_fs

    assert _authored_overlay_owns_gap_fs({
        "overlay": {"type": "lower_third", "content": "FLUIDS"},
    })
    assert _authored_overlay_owns_gap_fs({
        "overlay": {"type": "fullscreen_text", "content": "REDSHIFT"},
    })
    assert not _authored_overlay_owns_gap_fs({"overlay": {"type": "none"}})
    assert not _authored_overlay_owns_gap_fs({"overlay": {"type": "lower_third"}})


def test_0050_compiled_queries_are_not_poisoned_with_director_labels():
    script = _script()
    plan = {
        "blocks": script["blocks"],
        "sources": script.get("sources") or [],
        "category": "ai",
        "video_id": "redshift_0050",
        "meta": script.get("meta") or {},
    }
    poison = ("one ", "dark ", "russian ", "html ", "clay ", "reject ",
              "redshift ", "latin ", "cyrillic ", "fluids ")
    by_id = {block["id"]: block for block in script["blocks"]}
    for block_id in ("b5", "b5b", "b5c", "b5d", "b5e", "b6", "b7"):
        block = by_id[block_id]
        intent = str(block.get("visual_intent") or "")
        assert not re.search(r"\b(?:One|Dark|Russian|HTML|CLAY|REJECT|REDSHIFT|Latin|Cyrillic)\b", intent), intent
        slot = {
            "index": 14,
            "block_id": block["id"],
            "role": block.get("role", ""),
            "queries": list(block.get("broll_queries") or []),
            "visual_intent": intent,
        }
        for beat in ("fluids", "weather", "wing", "pipes", "blood", "stamp", "city", "notebook"):
            filtered = filter_queries_for_beat(list(slot["queries"]), beat)
            search_slot = dict(slot)
            search_slot["queries"] = filtered
            compiled = compile_slot_search(search_slot, plan, count=5)
            blob = " ".join(compiled["queries"]).lower()
            for prefix in poison:
                assert not any(
                    q.lower().startswith(prefix) for q in compiled["queries"]
                ), (block_id, beat, compiled["queries"])
            assert "one weather" not in blob
            assert "russian weather" not in blob
            assert "redshift city" not in blob
            assert "latin city" not in blob
            assert "clay official" not in blob
            assert "clay rubber" not in blob
    assert "rubber stamp" in " ".join(by_id["b6"]["broll_queries"]).lower()
    assert by_id["b5"]["overlay"]["template_hint"] == "lower-thirds/dark-card"
    assert by_id["b5b"]["overlay"]["template_hint"] == "lower-thirds/clean-bar"
    assert by_id["b6"]["overlay"]["template_hint"] == "lower-thirds/dark-card"
    assert by_id["b7"]["overlay"]["template_hint"] == "lower-thirds/name-title"


def test_0050_ci_request_is_p7_prepared_skip_generate():
    req = json.loads((REPO / "config" / "ci_build_request.json").read_text(encoding="utf-8"))
    assert req["script"] == "scripts/redshift_0050.json"
    assert req["from_step"] == "P7"
    assert req["heygen_source"] == "prepared"
    assert req["skip_generate"] is True
    assert req["providers_mode"] == "live"
    assert "round14" in req["note"]
    assert "REJECTED" in req["note"]
    assert "FOLLOWUP" in req["note"]
    assert "compact REDSHIFT CTA" in req["note"]


def test_0050_remap_splits_stale_b5_slots_onto_unique_overlays():
    from src.lib.text import remap_split_blocks_from_script, sync_overlays_from_script

    script = _script()
    plan = {
        "video_id": "redshift_0050",
        "blocks": [{
            "id": "b5",
            "role": "develop",
            "text": SPOKEN["b5"],
            "overlay": {"type": "lower_third", "content": "FLUIDS"},
        }],
        "slots": [
            {"block_id": "b5", "start": 34.6, "end": 41.3, "queries": ["old"]},
            {"block_id": "b5", "start": 41.3, "end": 42.4, "queries": ["old"]},
            {"block_id": "b5", "start": 42.4, "end": 43.7, "queries": ["old"]},
            {"block_id": "b5", "start": 43.7, "end": 44.7, "queries": ["old"]},
            {"block_id": "b5", "start": 44.7, "end": 48.5, "queries": ["old"]},
        ],
    }
    words = [
        {"display": "жидкость", "start": 39.7, "end": 40.2},
        {"display": "Погода", "start": 41.4, "end": 42.3},
        {"display": "Крыло", "start": 42.5, "end": 42.8},
        {"display": "Трубы", "start": 43.8, "end": 44.0},
        {"display": "крови", "start": 45.0, "end": 45.5},
    ]
    assert remap_split_blocks_from_script(plan, script, words=words) >= 1
    ids = [b["id"] for b in plan["blocks"]]
    assert ids == ["b5", "b5b", "b5c", "b5d", "b5e"]
    slot_ids = [s["block_id"] for s in plan["slots"]]
    assert slot_ids == ["b5", "b5b", "b5c", "b5d", "b5e"]
    sync_overlays_from_script(plan, script=script, words=words)
    contents = [b["overlay"]["content"] for b in plan["blocks"]]
    assert contents == ["FLUIDS", "WEATHER", "AIRFOIL", "VALVES", "PLASMA"]


def test_0050_footage_index_has_magnific_plates():
    from src.lib.manifest import FootageIndex, tag_url_coherence

    idx = FootageIndex(REPO / "cache" / "footage_index.json")
    for aid, tag in (
        ("magnific_0050_weather", "radar"),
        ("magnific_0050_wing", "winglet"),
        ("magnific_0050_pipes", "pipework"),
        ("magnific_0050_blood", "bloodcells"),
        ("magnific_0050_stamp", "rubberstamp"),
        ("magnific_0050_city", "citynight"),
    ):
        rec = idx.by_id(aid)
        assert rec is not None, aid
        assert rec.source == "magnific"
        assert rec.ai_generated is False
        assert rec.width == 1080 and rec.height == 1920
        assert rec.duration_sec == 4.0
        assert rec.file == f"magnific/{aid}.mp4"
        assert tag in rec.tags
        assert float(rec.score or 0) >= 0.9
        assert rec.vision_summary
        assert tag_url_coherence(rec) >= 0.15


def test_0050_latin_plaque_span_caps_before_avatar():
    from src.p11_assemble.assemble import _latin_plaque_span

    slots = [
        {"kind": "footage", "start": 50.0, "end": 54.0},
        {"kind": "avatar", "start": 54.0, "end": 64.0},
    ]
    start, end = _latin_plaque_span(slots, slots)
    assert start == 50.0
    assert end <= 54.0
    assert end - start <= 3.5 + 1e-6


def test_0050_followup_cleanbar_coerces_dark_card():
    from src.p11_assemble.assemble import _coerce_latin_cleanbar_dark

    params = _coerce_latin_cleanbar_dark(
        {"clean_bar": True, "position": "bottom"},
        content="FOLLOWUP",
        template_id="lower-thirds/clean-bar",
    )
    assert params.get("dark_card") is True
    assert params.get("clean_bar") is False
    name = _coerce_latin_cleanbar_dark(
        {"position": "bottom"},
        content="FOLLOWUP",
        template_id="lower-thirds/name-title",
    )
    assert name.get("dark_card") is True

