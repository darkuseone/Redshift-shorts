"""0050 remount: spoken lock, overlays, pins, query sync — no TTS rewrite."""

from __future__ import annotations

import json
from pathlib import Path

from src.lib.pin_match import pin_slot_prefer_key
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
    assert got == SPOKEN
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
    assert by_id["b6"]["overlay"]["content"] == "CLAY: REJECT"
    assert "НЕТ" not in by_id["b6"]["overlay"]["content"]
    assert by_id["b7"]["overlay"]["content"] == "REDSHIFT"
    assert not by_id["b7"]["overlay"]["content"].endswith(".")
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
    for aid in (
        "fp_water_vortex", "fp_river_current", "fp_blue_ink", "pexels_v7565432",
        "fp_server_room", "grok_supercomputer_0042", "freepik_5200850",
        "freepik_8945319", "freepik_682745",
        "freepik_4175316", "freepik_3497298", "freepik_136238",
        "freepik_8816084", "freepik_6468157", "freepik_2321764",
        "fp_code_editor", "fp_desk_code", "freepik_9127165",
        "fp_chalkboard_eq", "fp_writing_equations", "fp_quad_formula",
        "pexels_v38431825",
        "fp_stapling_docs", "fp_library_books",
        "fp_white_ink", "fp_sand_ripples",
    ):
        assert aid in prefer, aid
    assert "press_21bc8e2d72" not in prefer
    assert "press_21bc8e2d72" in deny
    assert "nasa_*" in deny
    for aid in (
        "fp_cracked_wall", "fp_plaster_wall", "fp_peeling_wall",
        "fp_cracked_concrete", "fp_cracked_earth", "fp_rock_surface",
        "fp_corroded_mesh", "pixabay_v144678",
        "grok_cryostat_0042", "pexels_v20068211", "pexels_v30775057",
    ):
        assert aid in deny, aid
        assert aid not in prefer
    assert int(entry["same_asset_max_slots"]) == 1
    assert pin_id_denied("nasa_PIA13308", set(deny))
    assert pin_id_denied("nasa_S74-23458", set(deny))


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
