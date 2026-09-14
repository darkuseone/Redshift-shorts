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
        "b5": "FLUIDS", "b5b": "WEATHER", "b5c": "AIRFOIL",
        "b5d": "VALVES", "b5e": "PLASMA",
    }
    for bid, label in labels.items():
        ov = by_id[bid]["overlay"]
        assert ov["type"] == "lower_third"
        assert ov["content"] == label
        assert ov["content"].strip()
        assert ov["template_hint"].startswith("lower-thirds/")
        assert "bigtext-mask-footage" not in ov.get("template_hint", "")
    assert len(set(labels.values())) == 5
    # QC-25: один id шаблона не больше двух раз за ролик. Конкретные id
    # проверять бессмысленно — P11 их всё равно разводит при сборке; важно,
    # чтобы сценарий не приносил одну и ту же плашку семь раз подряд.
    hints = [b["overlay"]["template_hint"] for b in script["blocks"]
             if (b.get("overlay") or {}).get("template_hint")]
    for hint in set(hints):
        assert hints.count(hint) <= 2, (hint, hints)
    assert by_id["b6"]["overlay"]["type"] == "lower_third"
    assert by_id["b6"]["overlay"]["content"] == "REJECTED"
    assert by_id["b6"]["overlay"]["template_hint"].startswith("lower-thirds/")
    assert "НЕТ" not in by_id["b6"]["overlay"]["content"]
    assert by_id["b7"]["overlay"]["type"] == "lower_third"
    assert by_id["b7"]["overlay"]["content"] == "FOLLOWUP"
    assert by_id["b7"]["overlay"]["template_hint"].startswith("lower-thirds/")
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
    # Порядок внутри prefer ролик не решает: каждый слот прибит поимённо в
    # slots_lock. Проверяем состав, а не очередь — иначе тест ломается на
    # каждой перестановке, ничего не защищая.
    assert set(prefer[:12]) >= {
        "magnific_0050_weather", "magnific_0050_wing",
        "magnific_0050_pipes", "magnific_0050_blood",
        "magnific_0050_fluids", "magnific_0050_inkswirl",
        "magnific_0050_coolvortex",
    }
    assert "magnific_0050_stamp" in prefer
    assert "magnific_0050_city" in prefer
    for aid in (
        "fp_code_editor", "fp_chalkboard_eq",
        "magnific_0050_fluids", "magnific_0050_inkswirl", "magnific_0050_coolvortex",
        "magnific_0050_weather", "magnific_0050_stamp", "magnific_0050_city",
        "magnific_0050_wing", "magnific_0050_pipes", "magnific_0050_blood",
        "magnific_0050_codeglow", "magnific_0050_nightstatic",
        "magnific_0050_tealmister", "magnific_0050_blueember",
        "magnific_0050_charcoalash", "magnific_0050_cyanrain",
        "magnific_0050_frostscan", "magnific_0050_deepcoil",
        "magnific_0050_steelglow",
    ):
        assert aid in prefer, aid
    # Серверный коридор — отдельной строкой: его выкинули по критике («повтор
    # серверов» трижды за ролик), и вернуть его в prefer молча нельзя.
    for aid in ("fp_server_room", "pexels_v38431825",
                "magnific_0050_voidpulse", "magnific_0050_darkgrid",
                "magnific_0050_slateiron"):
        assert aid not in prefer, aid
        assert aid in deny, aid
    for aid in (
        "magnific_0050_darkember", "magnific_0050_redsmoke", "magnific_0050_ashdrift",
        "magnific_0050_coalglow", "magnific_0050_ironrust", "magnific_0050_sparkrain",
        "magnific_0050_vortex", "magnific_0050_coldspark",
    ):
        assert aid not in prefer, aid
        assert aid in deny, aid
    assert "pexels_v7565432" not in prefer
    assert "pexels_v7565432" in deny
    by_block = entry.get("by_block") or {}
    assert by_block.get("b3") == "magnific_0050_gpu"
    assert by_block.get("b4") == "magnific_0050_steelglow"
    assert by_block.get("b5") == "magnific_0050_fluids"
    assert by_block.get("b5b") == "magnific_0050_weather"
    assert by_block.get("b6") == "magnific_0050_stamp"
    assert by_block.get("b7") == "magnific_0050_city"
    assert "magnific_0050_gpu" in prefer
    assert "magnific_0050_lean" in prefer
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
    assert "Ink swirl" in plan["slots"][0]["visual_intent"]


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
    # Токен склеен намеренно: ровно так помечен штамп в индексе футажа
    # (tags: rubberstamp / deskstamp). Развёрнутое «rubber stamp» тега не
    # находит, P7 остаётся без кандидатов и b6 теряет одобренный штамп.
    assert "rubberstamp" in " ".join(by_id["b6"]["broll_queries"]).lower()
    for bid in ("b5", "b5b", "b6", "b7"):
        assert by_id[bid]["overlay"]["template_hint"].startswith("lower-thirds/")


def test_0050_ci_request_is_p5_prepared_skip_generate():
    req = json.loads((REPO / "config" / "ci_build_request.json").read_text(encoding="utf-8"))
    assert req["script"] == "scripts/redshift_0050.json"
    assert req["video_id"] == "redshift_0050"
    assert req["from_step"] == "P5"
    assert req["heygen_source"] == "prepared"
    assert req["skip_generate"] is True
    assert req["skip_vision"] is True
    assert req["providers_mode"] == "live"
    assert int(req.get("round") or 0) == 47
    assert req["note"].startswith(f"round{int(req['round'])}")
    assert "QC-SEMANTIC" in req["note"] or "skip_vision" in req["note"]
    assert "skip_generate" in req["note"] or req["skip_generate"] is True
    assert "P5" in req["note"] or req["from_step"] == "P5"


def test_0050_qc25_cap_splits_third_dark_card():
    from src.lib.slots_lock import cap_plan_templates_qc25

    plan = {
        "shots": [{"index": 0, "template": "intro-hooks/hook-number-slam"}],
        "overlays": [
            {"type": "plaque", "template": "lower-thirds/dark-card", "params": {"text": "FLUIDS"}},
            {"type": "plaque", "template": "lower-thirds/dark-card", "params": {"text": "VALVES"}},
            {"type": "plaque", "template": "lower-thirds/dark-card", "params": {"text": "PLASMA"}},
            {"type": "plaque", "template": "lower-thirds/dark-card", "params": {"text": "REJECTED"}},
            {"type": "plaque", "template": "lower-thirds/dark-card", "params": {"text": "FOLLOWUP"}},
        ],
        "templates_used": ["intro-hooks/hook-number-slam", "lower-thirds/dark-card"],
    }
    changed = cap_plan_templates_qc25(plan)
    assert changed >= 3
    from collections import Counter
    counts = Counter(o["template"] for o in plan["overlays"])
    assert counts["lower-thirds/dark-card"] <= 2
    assert all(n <= 2 for n in counts.values())


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
        ("magnific_0050_tealmister", "teal"),
        ("magnific_0050_darkgrid", "grid"),
        ("magnific_0050_codeglow", "code"),
        ("magnific_0050_coolvortex", "cool"),
        ("magnific_0050_blueember", "blue"),
        ("magnific_0050_cyanrain", "cyan"),
        ("magnific_0050_frostscan", "frost"),
        ("magnific_0050_deepcoil", "radar"),
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
    weather = _coerce_latin_cleanbar_dark(
        {"clean_bar": True, "position": "bottom"},
        content="WEATHER",
        template_id="lower-thirds/clean-bar",
    )
    assert weather.get("dark_card") is True
    assert weather.get("clean_bar") is False
    for label in ("AIRFOIL", "VALVES", "PLASMA", "FLUIDS", "REJECTED"):
        got = _coerce_latin_cleanbar_dark(
            {"position": "bottom"}, content=label, template_id="lower-thirds/note-pin")
        assert got.get("dark_card") is True, label


def test_0050_snap_life_beats_to_weather_keyword():
    from src.lib.text import (
        reassign_words_for_script_children, snap_block_windows_to_keywords,
    )

    words = [
        {"display": "Называются", "start": 34.56, "end": 35.12, "block_id": "b5"},
        {"display": "уравнения", "start": 35.16, "end": 35.60, "block_id": "b5"},
        {"display": "Навье-Стокса", "start": 35.66, "end": 36.56, "block_id": "b5"},
        {"display": "жидкость", "start": 39.74, "end": 40.24, "block_id": "b5"},
        {"display": "толкают", "start": 40.62, "end": 41.28, "block_id": "b5"},
        {"display": "Погода", "start": 41.36, "end": 42.32, "block_id": "b5"},
        {"display": "Крыло", "start": 42.44, "end": 42.80, "block_id": "b5"},
        {"display": "самолёта", "start": 42.86, "end": 43.60, "block_id": "b5"},
        {"display": "Трубы", "start": 43.68, "end": 44.00, "block_id": "b5"},
        {"display": "доме", "start": 44.16, "end": 44.60, "block_id": "b5"},
        {"display": "крови", "start": 44.98, "end": 45.52, "block_id": "b5"},
        {"display": "извиняется", "start": 47.74, "end": 48.51, "block_id": "b5"},
    ]
    children = [
        {"id": "b5", "text": "Называются уравнения Навье-Стокса. жидкость толкают."},
        {"id": "b5b", "text": "Погода."},
        {"id": "b5c", "text": "Крыло самолёта."},
        {"id": "b5d", "text": "Трубы в доме."},
        {"id": "b5e", "text": "Ток крови. извиняется."},
    ]
    assert reassign_words_for_script_children(words, "b5", children) > 0
    assert any(w["block_id"] == "b5b" and "Погод" in w["display"] for w in words)
    assert any(w["block_id"] == "b5c" and "Крыло" in w["display"] for w in words)
    plan = {
        "video_id": "redshift_0050",
        "slots": [
            {"index": 10, "block_id": "b5b", "kind": "footage",
             "start": 37.14, "end": 40.19, "duration": 3.05},
            {"index": 11, "block_id": "b5c", "kind": "footage",
             "start": 40.19, "end": 42.0, "duration": 1.81},
        ],
        "blocks": children,
    }
    script = {"blocks": children}
    n = snap_block_windows_to_keywords(plan, words, script=script)
    assert n >= 1
    weather_slot = next(s for s in plan["slots"] if s["block_id"] == "b5b")
    assert weather_slot["start"] >= 40.5
    assert weather_slot["start"] <= 41.5



def test_0050_prepared_avatar_windows_frozen_match_request():
    """P5 must keep prepared seg durations so P6 does not demand new clips."""
    from src.lib.config import load_config
    from src.p5_replan.replanner import (
        Slot, apply_prepared_avatar_windows, compute_stats,
        densify_after_prepared_freeze, load_prepared_avatar_windows,
    )
    from src.p6_avatar.avatar import merge_segments

    cfg = load_config()
    cfg.data.setdefault("heygen", {})["source"] = "prepared"
    windows = load_prepared_avatar_windows(cfg, "redshift_0050")
    assert windows is not None and len(windows) == 5
    assert [round(w["duration"], 3) for w in windows] == [
        4.094, 5.871, 0.256, 4.921, 6.452]

    # Simulate a P5 rebuild that carved different b6 avatar spans.
    slots = [
        Slot(0, 0.0, 4.575, "footage", "b1", "hook", "C", needs_asset=True),
        Slot(1, 4.575, 12.0, "avatar", "b2", "setup", "A"),
        Slot(2, 12.0, 48.0, "footage", "b5b", "develop", "C", needs_asset=True),
        Slot(3, 48.0, 51.131, "avatar", "b6", "twist", "A"),
        Slot(4, 51.131, 65.87, "footage", "b7", "cta", "C", needs_asset=True),
    ]
    notes: list[str] = []
    out = apply_prepared_avatar_windows(
        slots, windows, duration=65.87, notes=notes)
    assert any("prepared avatar windows frozen" in n for n in notes)
    # Round17 bug: freeze cleared events → max_gap ≈ full duration.
    frozen_stats = compute_stats(out, 65.87)
    assert frozen_stats["max_event_gap_sec"] > 60.0
    out = densify_after_prepared_freeze(out, cfg, notes=notes)
    assert any("internal events restored" in n for n in notes)
    densified = compute_stats(out, 65.87)
    assert densified["max_event_gap_sec"] <= 2.5 + 1e-3
    assert densified["max_shot_sec"] <= 7.0 + 1e-3
    merged = merge_segments([s.to_dict() for s in out])
    assert len(merged) == 5
    for seg, win in zip(merged, windows):
        assert abs((seg["end"] - seg["start"]) - win["duration"]) < 1e-6
        assert abs(seg["start"] - win["start"]) < 1e-6


def test_0050_snap_never_rewrites_avatar_slots():
    from src.lib.text import snap_block_windows_to_keywords

    plan = {
        "video_id": "redshift_0050",
        "slots": [
            {"block_id": "b6", "kind": "avatar", "start": 50.286, "end": 55.207},
            {"block_id": "b6", "kind": "footage", "start": 55.207, "end": 56.607},
        ],
        "blocks": [{"id": "b6", "text": "Клей не принял документ"}],
    }
    words = [
        {"display": "Клей", "start": 52.67, "end": 53.19, "block_id": "b6"},
        {"display": "принял", "start": 53.36, "end": 53.87, "block_id": "b6"},
    ]
    before = (plan["slots"][0]["start"], plan["slots"][0]["end"])
    snap_block_windows_to_keywords(plan, words, script={"blocks": plan["blocks"]})
    assert (plan["slots"][0]["start"], plan["slots"][0]["end"]) == before


def test_0050_p8_fingerprints_cut_plan_after_densify():
    """Densify changes cut_plan; P8 must not cache-hit on candidates alone."""
    pipe = build_pipeline()
    p8 = next(s for s in pipe.steps if s.name == "P8")
    assert "cut_plan.json" in p8.inputs
    assert "candidates.json" in p8.inputs


def test_force_by_block_pins_one_asset_per_slot_no_densify_clones(tmp_path, monkeypatch):
    """by_block pin lands on one densify sibling only (same_asset_max_slots=1)."""
    from types import SimpleNamespace
    from src.p8_broll_judge import judge as judge_mod

    class Rec:
        def __init__(self, aid):
            self.id = aid
            self.file = f"magnific/{aid}.mp4"
            self.quarantined = False
            self.source = "magnific"
            self.type = "video"
            self.license = "owner_decision"
            self.url_origin = ""
            self.tags = ["magnific"]
            self.vision_summary = ""
            self.score = 0.92
            self.duration_sec = 2.0
            self.width = 1080
            self.height = 1920
            self.phashes = []
            self.phash = ""
            self.ai_generated = False
            self.mock = False
            self.extra = {}

    class Index:
        def by_id(self, pid):
            return Rec(pid) if pid.startswith("magnific_") else None

    slots = [
        {"index": 6, "block_id": "b3", "needs_asset": True, "asset_role": "broll",
         "visual_intent": "gpu", "reason": "densify after prepared freeze",
         "start": 0, "end": 2},
        {"index": 7, "block_id": "b3", "needs_asset": True, "asset_role": "broll",
         "visual_intent": "gpu", "reason": "densify after prepared freeze",
         "start": 2, "end": 4},
        {"index": 8, "block_id": "b3", "needs_asset": True, "asset_role": "broll",
         "visual_intent": "gpu", "reason": "densify after prepared freeze",
         "start": 4, "end": 6},
        {"index": 16, "block_id": "b5b", "needs_asset": True, "asset_role": "broll",
         "visual_intent": "weather", "reason": "life", "start": 6, "end": 8},
    ]
    plan = {"slots": slots, "video_id": "redshift_0050"}
    # Round19 bug: same pin already cloned onto every densify sibling.
    accepted = {
        6: {"asset_id": "magnific_0050_gpu", "decision": "accept_prefer"},
        7: {"asset_id": "magnific_0050_gpu", "decision": "accept_prefer"},
        8: {"asset_id": "magnific_0050_gpu", "decision": "accept_prefer"},
    }
    accepted_counts = {"magnific_0050_gpu": 3}
    judged = []
    slots_by_index = {s["index"]: s for s in slots}
    storage = SimpleNamespace(exists=lambda key: True)
    ctx = SimpleNamespace(storage=storage)
    cfg = SimpleNamespace()

    monkeypatch.setattr(judge_mod, "hydrate_repo_footage", lambda *a, **k: 0)
    monkeypatch.setattr(judge_mod, "_engine_gate_reason", lambda *a, **k: None)
    monkeypatch.setattr(judge_mod, "palette_verdict", lambda *a, **k: {"passed": True, "reason": ""})
    monkeypatch.setattr(judge_mod, "skip_live_verdict", lambda c, intent: {
        "score": 0.9, "reason": "pin by_block", "summary": "", "judge": "pin", "frames": 0,
    })

    forced = judge_mod._force_by_block_pins(
        ctx=ctx, cfg=cfg, plan=plan, slots_by_index=slots_by_index,
        accepted=accepted, accepted_counts=accepted_counts, judged=judged,
        by_block={"b3": "magnific_0050_gpu", "b5b": "magnific_0050_weather"},
        pin_deny=set(), index=Index(), skip_live=True, palette_rules={},
        repeat_max=1,
        pin_prefer=["magnific_0050_gpu", "magnific_0050_weather"],
    )
    gpu_slots = [idx for idx, e in accepted.items()
                 if e.get("asset_id") == "magnific_0050_gpu"]
    assert len(gpu_slots) == 1, gpu_slots
    assert accepted_counts.get("magnific_0050_gpu", 0) == 1
    # Densify siblings must stay empty for distinct leftover/stock plates.
    assert 7 not in accepted or accepted[7].get("asset_id") != "magnific_0050_gpu"
    assert 8 not in accepted or accepted[8].get("asset_id") != "magnific_0050_gpu"
    assert accepted[16]["asset_id"] == "magnific_0050_weather"
    assert accepted[16].get("speech_locked") is True
    assert forced >= 1  # weather at least (gpu may only scrub clones)



def test_0050_hole_filler_pins_are_neutral_leftover():
    """Densify hole fillers accept at bonus 0; life-beat mismatch stays +10."""
    from src.lib.pin_match import pin_slot_prefer_key

    empty = {
        "index": 7, "role": "evidence", "asset_role": "broll",
        "visual_intent": "", "queries": [], "start": 18.0, "end": 21.0,
        "block_id": "b3",
    }
    prefer = [
        "magnific_0050_gpu", "magnific_0050_tealmister", "magnific_0050_weather",
    ]
    filler_bonus, _ = pin_slot_prefer_key(
        "magnific_0050_tealmister", empty, prefer, words=[])
    weather_on_empty, _ = pin_slot_prefer_key(
        "magnific_0050_weather", empty, prefer, words=[])
    assert filler_bonus == 0
    assert weather_on_empty > 0


def test_0050_leftover_fills_densify_holes_with_distinct_fillers(monkeypatch):
    """After by_block one-pin, leftover places distinct hole fillers on siblings."""
    from types import SimpleNamespace
    from src.p8_broll_judge import judge as judge_mod
    from src.lib.manifest import AssetRecord

    fillers = [
        "magnific_0050_tealmister", "magnific_0050_blueember", "magnific_0050_charcoalash",
    ]

    class Rec:
        def __init__(self, aid):
            self.id = aid
            self.file = f"magnific/{aid}.mp4"
            self.quarantined = False
            self.source = "magnific"
            self.type = "video"
            self.license = "owner_decision"
            self.url_origin = ""
            self.tags = ["dark"]
            self.vision_summary = "dark plate"
            self.score = 0.9
            self.duration_sec = 4.0
            self.width = 1080
            self.height = 1920
            self.phashes = []
            self.phash = ""
            self.ai_generated = False
            self.mock = False
            self.extra = {"hole_filler": True}

    class Index:
        def by_id(self, pid):
            if pid.startswith("magnific_"):
                return Rec(pid)
            return None

    slots = [
        {"index": 6, "block_id": "b3", "needs_asset": True, "asset_role": "broll",
         "visual_intent": "gpu", "reason": "primary", "start": 0, "end": 2},
        {"index": 7, "block_id": "b3", "needs_asset": True, "asset_role": "broll",
         "visual_intent": "", "reason": "densify after prepared freeze",
         "start": 2, "end": 4, "queries": []},
        {"index": 8, "block_id": "b3", "needs_asset": True, "asset_role": "broll",
         "visual_intent": "", "reason": "densify after prepared freeze",
         "start": 4, "end": 6, "queries": []},
    ]
    plan = {"slots": slots, "video_id": "redshift_0050", "duration_sec": 6.0}
    accepted = {6: {"asset_id": "magnific_0050_gpu", "decision": "accept_prefer",
                    "fallback_reason": "pin by_block"}}
    accepted_counts = {"magnific_0050_gpu": 1}
    judged = []
    slots_by_index = {s["index"]: s for s in slots}
    storage = SimpleNamespace(exists=lambda key: True)
    ctx = SimpleNamespace(storage=storage)
    cfg = SimpleNamespace(get=lambda *a, **k: 0.10 if "ai_footage" in str(a) else None)

    monkeypatch.setattr(judge_mod, "hydrate_repo_footage", lambda *a, **k: 0)
    monkeypatch.setattr(judge_mod, "_engine_gate_reason", lambda *a, **k: None)
    monkeypatch.setattr(judge_mod, "cheap_reject_reason", lambda *a, **k: None)
    monkeypatch.setattr(judge_mod, "palette_verdict", lambda *a, **k: {"passed": True})
    monkeypatch.setattr(judge_mod, "slot_negatives", lambda *a, **k: [])
    monkeypatch.setattr(judge_mod, "classify_intent", lambda *a, **k: "broll")
    monkeypatch.setattr(judge_mod, "skip_live_verdict", lambda c, intent: {
        "score": 0.9, "reason": "leftover", "summary": "", "judge": "pin", "frames": 0,
    })

    filled = judge_mod._fill_unfilled_from_leftover_prefers(
        ctx=ctx, cfg=cfg, plan=plan, slots_by_index=slots_by_index,
        accepted=accepted, accepted_counts=accepted_counts, judged=judged,
        pin_prefer=["magnific_0050_gpu"] + fillers,
        pin_deny=set(), index=Index(), repeat_max=1, skip_live=True,
        palette_rules={}, visible_min=0.5, words=[],
        by_block={"b3": "magnific_0050_gpu"},
    )
    assert filled == 2
    assert accepted[6]["asset_id"] == "magnific_0050_gpu"
    aids = {accepted[7]["asset_id"], accepted[8]["asset_id"]}
    assert aids <= set(fillers)
    assert len(aids) == 2  # distinct
    assert "magnific_0050_gpu" not in aids


def test_densify_prefers_internal_events_over_split_under_max_shot_ev():
    """Shots ≤ max_shot_sec_with_events stay one plate (events cover QC-3/4)."""
    from src.lib.config import load_config
    from src.p5_replan.replanner import Slot, densify_after_prepared_freeze

    cfg = load_config()
    # 6.5s is above max_shot (5) but under max_shot_with_events (7).
    slots = [
        Slot(0, 0.0, 6.5, "footage", "b3", "develop", "C", needs_asset=True,
             asset_role="broll", reason="gpu plate"),
    ]
    notes: list[str] = []
    out = densify_after_prepared_freeze(slots, cfg, notes=notes)
    assert len(out) == 1
    assert abs(out[0].duration - 6.5) < 1e-6
    assert any("one plate with internal events" in n for n in notes)
    assert out[0].events  # kenburns/push restored
    assert len(out[0].events) >= 2


def test_0050_avatar_bg_skips_red_plates():
    from src.p11_assemble.assemble import _avatar_bg_asset_ok, _avatar_bg_plates

    assert _avatar_bg_asset_ok({"id": "magnific_0050_voidpulse", "tags": ["dark"]}, video_id="redshift_0050")
    assert not _avatar_bg_asset_ok({"id": "magnific_0050_redsmoke", "tags": ["red"]}, video_id="redshift_0050")
    assert not _avatar_bg_asset_ok({"id": "magnific_0050_vortex", "tags": ["red", "ink"]}, video_id="redshift_0050")
    # other videos unrestricted
    assert _avatar_bg_asset_ok({"id": "magnific_0050_vortex", "tags": ["red"]}, video_id="redshift_0042")

    slots = [
        {"index": 0, "kind": "footage", "block_id": "b1", "start": 0.0, "end": 2.0},
        {"index": 1, "kind": "avatar", "block_id": "b2", "start": 2.0, "end": 6.0},
    ]
    prepared = {
        0: {"dst": "/tmp/magnific_0050_vortex_crop.mp4"},
        1: {"dst": "/tmp/avatar.webm"},
    }
    assets = {
        0: {"id": "magnific_0050_vortex", "tags": ["red", "ink"], "ai_generated": False},
        1: {"id": "avatar_seg_0", "ai_generated": False},
    }
    # With only vortex available, pool is empty for 0050.
    assert _avatar_bg_plates(slots, prepared, assets, plan={"video_id": "redshift_0050"}) == {}
    # Cool plate is accepted.
    prepared[0] = {"dst": "/tmp/magnific_0050_tealmister_crop.mp4"}
    assets[0] = {"id": "magnific_0050_tealmister", "tags": ["teal", "cool"], "ai_generated": False}
    got = _avatar_bg_plates(slots, prepared, assets, plan={"video_id": "redshift_0050"})
    assert got[1].endswith("tealmister_crop.mp4")


def test_0050_beat_queries_still_match_the_tags_of_their_footage():
    """Запрос удара обязан попадать в теги своего материала.

    Склеенные токены в этих запросах — не опечатка: индекс помечает материал
    ровно так (``rubberstamp``, ``citynight``, ``stormscreen``). Стоило
    развернуть их в человеческие слова, как P7 остался без кандидатов на
    слотах b6 и переподобрал уже одобренный футаж — штамп Clay пропал из
    ролика целиком.

    Проверяются только удары, чей футаж и ищется этим запросом. b1–b4 стоят
    на пинах ``by_block`` и от текста запроса не зависят.
    """
    script = _script()
    by_id = {b["id"]: b for b in script["blocks"]}
    index = json.loads((REPO / "cache" / "footage_index.json").read_text(encoding="utf-8"))
    items = index if isinstance(index, list) else (index.get("items") or [])
    tags_by_id = {str(it.get("id")): {str(t).lower() for t in (it.get("tags") or [])}
                  for it in items}
    beats = {
        "b5b": "magnific_0050_weather",
        "b5c": "magnific_0050_wing",
        "b5d": "magnific_0050_pipes",
        "b5e": "magnific_0050_blood",
        "b6": "magnific_0050_stamp",
        "b7": "magnific_0050_city",
    }
    for block_id, asset in beats.items():
        tags = tags_by_id.get(asset)
        assert tags, f"{asset} пропал из индекса футажа"
        words = set(" ".join(by_id[block_id].get("broll_queries") or []).lower().split())
        assert words & tags, (block_id, asset, sorted(words), sorted(tags))
