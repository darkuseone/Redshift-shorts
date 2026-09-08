"""Хук первых пяти секунд — решением, а не остатком (§5).

Три независимые улики говорили одно и то же. `picker.pick("intro-hooks", …)`
не вызывался нигде: все десять точек подбора в `assemble.py` передавали одну
из десяти других категорий, и конфиг честно числил категорию недостижимой.
`plan.hook_window` писался в `replanner.py:1027` и не читался никем. А на
живом 0042 хук собрался случайно: кадр 0 отдал 0.47 с футажа, кадры 1 и 2
стали двумя полноэкранными надписями подряд, и обе фразы выбрала
`gap_phrase` — «что вынести на экран, когда материала нет».

При этом вся оснастка лежала в репозитории: восемь шаблонов, семь интентов,
рендереры под каждый и валидация петли на P0. Не хватало одного вызова
picker'а и трёх полей схемы.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.errors import HookGreeting
from src.lib.cache import StepCache
from src.lib.costs import CostLedger
from src.lib.storage import build_storage
from src.lib.templates import TemplateCatalog
from src.p0_validate.validator import validate_script
from src.p11_assemble.assemble import (
    HOOK_STYLE_TEMPLATES, _hook_signals, _pick_hook_shot, build_variant,
)
from src.pipeline import RunContext

REPO_ROOT = Path(__file__).resolve().parents[1]

HOOK_TEXT = "Этот ответ невозможно проверить. Вообще ничем."
BLOCKS = [
    {"id": "h1", "role": "hook", "mode": "C", "emphasis_word": "невозможно",
     "text": HOOK_TEXT},
    {"id": "b2", "role": "evidence", "mode": "C", "emphasis_word": "кубитов",
     "text": "Внутри процессора сто пять кубитов, и проверить их нечем.",
     "answers_hook": True},
    {"id": "b3", "role": "cta", "mode": "C", "emphasis_word": "доверил",
     "text": "Доверил бы ты такому ответу свои деньги?"},
]


def _plan(*, hook: dict | None = None, hook_hi: float = 3.0) -> dict:
    slots = []
    for i, block in enumerate(BLOCKS):
        start = round(i * 2.5, 3)
        slots.append({
            "index": i, "start": start, "end": round(start + 2.5, 3),
            "duration": 2.5, "kind": "footage", "block_id": block["id"],
            "role": block["role"], "mode": "C", "visual_intent": "",
            "queries": [], "content": "", "transition_in": "cut", "events": [],
            "needs_asset": True, "asset_role": "broll", "template_hint": "",
            "meme_emotion": "", "reason": "режим C: футаж во весь кадр (§3.5)",
        })
    return {
        "video_id": "redshift_9051", "title": "Порог квантовой коррекции",
        "fps": 30, "duration_sec": 7.5, "target_duration_sec": 7.5,
        "music_mood": "tension", "music_tags": [], "category": "science",
        "sources": [{"title": "Quantum error correction", "domain": "nature.com",
                     "url": "https://www.nature.com/x", "show_on_screen": True,
                     "snippet": "Логический кубит живёт дольше физического."}],
        "cta": {"text": "Доверил бы ты такому ответу свои деньги?",
                "type": "question"},
        "cta_window": [5.5, 7.5], "hook_window": [0.0, hook_hi],
        "hook": hook or {}, "avatar_id": "", "stats": {}, "notes": [],
        "slots": slots, "avatar_segments": [], "blocks": BLOCKS,
    }


def _words(plan: dict) -> dict:
    words = []
    for block, slot in zip(BLOCKS, plan["slots"]):
        parts = block["text"].split()
        step = slot["duration"] / max(len(parts), 1)
        for j, part in enumerate(parts):
            display = part.strip(".,:«»—?")
            words.append({
                "index": len(words), "display": display,
                "start": round(slot["start"] + j * step, 3),
                "end": round(slot["start"] + (j + 1) * step, 3),
                "block_id": block["id"], "role": block["role"],
                "emphasis": display.lower() == block["emphasis_word"].lower(),
                "spoken": [display], "source": "test",
            })
    return {"video_id": plan["video_id"], "duration_sec": plan["duration_sec"],
            "stats": {}, "words": words}


@pytest.fixture()
def hook_ctx(cfg, tmp_path):
    cfg.set("providers.mode", "mock")
    work = tmp_path / "work"
    work.mkdir(parents=True)
    return RunContext(
        video_id="redshift_9051", cfg=cfg, work_dir=work,
        output_dir=tmp_path / "out", script_path=tmp_path / "s.json",
        cache=StepCache(tmp_path / "cache"),
        costs=CostLedger(video_id="redshift_9051"),
        storage=build_storage(cfg))


def _build(ctx, plan):
    return build_variant(
        ctx, plan, _words(plan), assets={}, prepared={},
        catalog=TemplateCatalog.load(ctx.cfg), avatar_meta={"segments": []},
        sfx_map={}, variant="B", recent_videos=[])


class TestTheHookWindowIsFinallyRead:
    """`hook_window` писался и не читался — единственное вхождение во всём src/."""

    def test_hook_window_is_read(self, hook_ctx):
        built = _build(hook_ctx, _plan(hook={"on_screen": "НЕВОЗМОЖНО ПРОВЕРИТЬ"}))
        first = built["shots"][0]
        assert str(first.get("template") or "").startswith("intro-hooks/"), \
            f"кадр хука взял приём {first.get('template')!r}, а не из intro-hooks"

    def test_a_slot_outside_the_window_is_left_alone(self, hook_ctx):
        """Хук — это первые секунды, а не любой кадр с ролью hook."""
        plan = _plan(hook={"on_screen": "НЕВОЗМОЖНО ПРОВЕРИТЬ"}, hook_hi=3.0)
        plan["slots"][0]["start"] = 9.0
        plan["slots"][0]["end"] = 11.5
        picked = _pick_hook_shot(
            plan["slots"][0], BLOCKS[0], plan,
            _picker(hook_ctx), TemplateCatalog.load(hook_ctx.cfg),
            variant="B", seed=1, recent_videos=[], used_templates=[],
            has_asset=False)
        assert picked is None

    def test_only_the_hook_role_gets_a_hook_device(self, hook_ctx):
        plan = _plan(hook={"on_screen": "НЕВОЗМОЖНО ПРОВЕРИТЬ"})
        picked = _pick_hook_shot(
            plan["slots"][1], BLOCKS[1], plan,
            _picker(hook_ctx), TemplateCatalog.load(hook_ctx.cfg),
            variant="B", seed=1, recent_videos=[], used_templates=[],
            has_asset=False)
        assert picked is None


def _picker(ctx):
    from src.lib.template_picker import TemplatePicker
    from src.lib.templates import TemplateCatalog as _Cat
    catalog = _Cat.load(ctx.cfg)
    from src.p11_assemble.assemble import ScenarioIndex
    return TemplatePicker(catalog, ScenarioIndex.load(ctx.cfg, catalog=catalog))


class TestTheStyleFromTheScriptReachesTheCatalogue:

    def test_hook_style_maps_to_template(self):
        """Семь стилей — семь разных приёмов, а не один на всех."""
        ids = set(HOOK_STYLE_TEMPLATES.values())
        assert len(ids) == len(HOOK_STYLE_TEMPLATES) == 7

    def test_every_style_names_a_template_that_exists(self, cfg):
        catalog = TemplateCatalog.load(cfg)
        known = {t.id for t in catalog.by_category("intro-hooks")}
        missing = set(HOOK_STYLE_TEMPLATES.values()) - known
        assert not missing, f"стиль указывает на несуществующий приём: {missing}"

    def test_a_named_style_wins_the_pick(self, hook_ctx):
        built = _build(hook_ctx, _plan(hook={"on_screen": "НЕВОЗМОЖНО ПРОВЕРИТЬ",
                                             "style": "blackout_word"}))
        assert built["shots"][0]["template"] == \
            HOOK_STYLE_TEMPLATES["blackout_word"]


class TestTheTwoDictionariesOfConditionsFinallyMeet:
    """N-14: интент ждал сигнала `numbers`, шаблон — признака `number`."""

    def test_number_hook_fires_on_word_numerals(self, hook_ctx):
        """«Сто пять кубитов» — цифр нет, а число названо."""
        block = {"id": "h1", "role": "hook", "mode": "C",
                 "text": "Сто пять кубитов. И ни один не считает как бит.",
                 "emphasis_word": "кубитов"}
        plan = _plan(hook={"on_screen": "105 КУБИТОВ"})
        plan["blocks"] = [block] + BLOCKS[1:]
        picked = _pick_hook_shot(
            plan["slots"][0], block, plan, _picker(hook_ctx),
            TemplateCatalog.load(hook_ctx.cfg), variant="B", seed=3,
            recent_videos=[], used_templates=[], has_asset=False)
        assert picked is not None
        template, trace = picked
        assert "number" in _hook_signals({}, {"number"}, has_asset=False)
        assert "hook-number" in [fid for fid, _ in trace.fired], \
            f"интент числового хука не сработал: {[f for f, _ in trace.fired]}"

    def test_the_signals_carry_the_block_traits(self):
        signals = _hook_signals({"on_screen": "КТО ЭТО ПРОВЕРИЛ?"},
                                {"question", "device"}, has_asset=True)
        assert "question" in signals            # признак блока стал сигналом
        assert "footage" in signals             # структура кадра
        assert "on_screen" in signals
        assert "device" not in signals          # не всякий признак — сигнал хука


class TestAGreetingIsNotAHook:

    def test_greeting_is_blocking(self, cfg, sample_script):
        script = copy.deepcopy(sample_script)
        script["blocks"][0]["text"] = "Привет, с вами Redshift. Разберём квант."
        with pytest.raises(HookGreeting):
            validate_script(script, cfg)

    @pytest.mark.parametrize("opener", [
        "Всем привет, сегодня разберём квантовый компьютер и его порог.",
        "В этом видео я расскажу, почему ответ невозможно проверить ничем.",
        "Сегодня поговорим о том, почему ответ невозможно проверить ничем.",
    ])
    def test_every_known_opener_is_caught(self, cfg, sample_script, opener):
        script = copy.deepcopy(sample_script)
        script["blocks"][0]["text"] = opener
        with pytest.raises(HookGreeting):
            validate_script(script, cfg)

    def test_a_real_hook_passes(self, cfg, sample_script):
        """Сторож не должен ловить нормальный хук."""
        script = copy.deepcopy(sample_script)
        assert validate_script(script, cfg)["_validation"] is not None

    def test_a_hook_without_a_screen_line_is_named(self, cfg, sample_script):
        script = copy.deepcopy(sample_script)
        script["blocks"][0].pop("overlay", None)
        script.get("meta", {}).pop("hook", None)
        codes = [w["code"] for w in
                 validate_script(script, cfg)["_validation"]["warnings"]]
        assert "HOOK_NO_ON_SCREEN" in codes

    def test_a_long_screen_line_is_named(self, cfg, sample_script):
        script = copy.deepcopy(sample_script)
        script["meta"]["hook"] = {
            "on_screen": "этот ответ никто никогда не сможет проверить вообще ничем"}
        codes = [w["code"] for w in
                 validate_script(script, cfg)["_validation"]["warnings"]]
        assert "HOOK_ON_SCREEN_TOO_LONG" in codes


class TestTheHookLandsBeforeTheFirstSecond:

    def test_on_screen_text_lands_before_1s(self, hook_ctx):
        built = _build(hook_ctx, _plan(hook={"on_screen": "НЕВОЗМОЖНО ПРОВЕРИТЬ"}))
        first = built["shots"][0]
        assert first["kind"] == "fullscreen_text"
        delay = float((first.get("params") or {}).get("enter_delay") or 0.0)
        assert float(first["start"]) + delay <= 1.0, \
            f"строка хука появляется на {float(first['start']) + delay:.2f} с"

    def test_the_screen_line_comes_from_the_script(self, hook_ctx):
        built = _build(hook_ctx, _plan(hook={"on_screen": "НЕВОЗМОЖНО ПРОВЕРИТЬ"}))
        assert "НЕВОЗМОЖНО" in str(built["shots"][0].get("content") or "").upper()

    def test_the_hook_device_is_placed_once(self, hook_ctx):
        """В окно 0–3 с попадает не один слот, а приём хука — один.

        На живом 0042 в окно попадают три слота. Без потолка все три брали бы
        приём из `intro-hooks` подряд — те самые «две полноэкранные надписи
        подряд», из-за которых хук и переделывали.
        """
        plan = _plan(hook={"on_screen": "НЕВОЗМОЖНО ПРОВЕРИТЬ"}, hook_hi=8.0)
        for slot in plan["slots"]:
            slot["role"] = "hook"
        built = _build(hook_ctx, plan)
        hooks = [s for s in built["shots"]
                 if str(s.get("template") or "").startswith("intro-hooks/")]
        assert len(hooks) == 1, f"приёмов хука {len(hooks)}: {[h['template'] for h in hooks]}"

    def test_the_plan_says_the_hook_was_a_decision(self, hook_ctx):
        built = _build(hook_ctx, _plan(hook={"on_screen": "НЕВОЗМОЖНО ПРОВЕРИТЬ"}))
        assert built["shots"][0].get("hook") is True
        assert "хук" in str(built["shots"][0].get("why") or "")


class TestTheRecordOfUnreachabilityIsGone:

    def test_no_intro_hooks_regression(self):
        cfg = json.loads((REPO_ROOT / "config" / "template_scenarios.json")
                         .read_text(encoding="utf-8"))
        assert "intro-hooks" not in cfg["unreachable_categories"]

    def test_the_assembler_actually_calls_the_category(self):
        """Запись снимается вместе с вызовом, а не вместо него."""
        source = (REPO_ROOT / "src" / "p11_assemble" / "assemble.py") \
            .read_text(encoding="utf-8")
        assert '"intro-hooks",' in source
