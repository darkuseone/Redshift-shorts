"""P0 — таблица кодов ошибок §8.2 проверяется по каждому коду."""

from __future__ import annotations

import pytest

from src.errors import (
    BudgetExceeded, DurationOutOfRange, HookUnanswered, MissingCta, MissingHook,
    NoSource, QuoteTooLong, ValidationError,
)
from src.lib.jsonio import read_json
from src.lib.schema import estimate_block_duration
from src.p0_validate.validator import HOOK_MAX_SEC, validate_script

# Spoken hook ≤3.0 с. Для прочих правил P0 режем хук в памяти, не раздувая 0042.
_SHORT_HOOK = "Этот ответ невозможно проверить. Совсем никак."
_HOOK_3_1 = "Этот ответ невозможно проверить никаким опытом."
_CHANNEL_SCRIPTS = tuple(f"redshift_00{n}.json" for n in range(42, 48))


@pytest.fixture
def sample_script(sample_script):
    hook = next(b for b in sample_script["blocks"] if b.get("role") == "hook")
    hook["text"] = _SHORT_HOOK
    return sample_script


def test_valid_script_passes(sample_script, cfg):
    result = validate_script(sample_script, cfg)
    info = result["_validation"]
    assert info["ok"] is True
    assert 35 <= info["estimated_duration_sec"] <= 75
    # Ролей три, а гарнитур может быть больше: у субтитра есть резерв.
    assert {f["role"] for f in info["fonts"]} >= {"subtitle", "display", "mono"}
    assert info["warnings"] == []


def test_missing_hook(sample_script, cfg):
    sample_script["blocks"][0]["role"] = "setup"
    with pytest.raises(MissingHook) as exc:
        validate_script(sample_script, cfg)
    assert exc.value.code == "MISSING_HOOK"


def test_missing_cta(sample_script, cfg):
    sample_script["blocks"] = [b for b in sample_script["blocks"] if b["role"] != "cta"]
    sample_script.pop("cta", None)
    with pytest.raises(MissingCta):
        validate_script(sample_script, cfg)


def test_hook_unanswered(sample_script, cfg):
    sample_script["blocks"][0]["text"] = (
        "Почему кальмары меняют окраску быстрее, чем моргает человек, "
        "и куда девается пигмент при этом превращении?"
    )
    for block in sample_script["blocks"][1:]:
        block.pop("answers_hook", None)
    with pytest.raises(HookUnanswered) as exc:
        validate_script(sample_script, cfg)
    assert exc.value.code == "HOOK_UNANSWERED"


def test_hook_answered_by_explicit_flag(sample_script, cfg):
    sample_script["blocks"][0]["text"] = "Почему кальмары меняют окраску так быстро?"
    sample_script["blocks"][4]["answers_hook"] = True
    # Хронометраж мог просесть — восстанавливаем длину другим блоком.
    sample_script["blocks"][3]["text"] += (
        " Каждый следующий слой добавляет ещё немного точности к общему результату счёта."
    )
    result = validate_script(sample_script, cfg)
    assert result["_validation"]["ok"]


def test_quote_too_long(sample_script, cfg):
    long_quote = " ".join(f"слово{i}" for i in range(20))
    sample_script["blocks"][2]["text"] = f"Автор пишет: «{long_quote}»."
    with pytest.raises(QuoteTooLong) as exc:
        validate_script(sample_script, cfg)
    assert exc.value.details["words"] == 20


def test_quote_within_limit_passes(sample_script, cfg):
    sample_script["blocks"][2]["text"] = (
        "В статье сказано: «логический кубит живёт дольше физического» — это и есть перелом."
    )
    result = validate_script(sample_script, cfg)
    assert result["_validation"]["ok"]


def test_no_source(sample_script, cfg):
    sample_script["sources"] = []
    with pytest.raises(NoSource):
        validate_script(sample_script, cfg)


def test_duration_too_short(sample_script, cfg):
    # Короткие, но разные: иначе петля бьёт PAYOFF_RESTATES_SETUP раньше длительности.
    texts = [
        "Удар хука.",
        "Сетап кадра.",
        "Факт evid.",
        "Ход мысли.",
        "Иной ответ на вопрос.",
        "Конец роли.",
    ]
    for block, text in zip(sample_script["blocks"], texts):
        block["text"] = text
    with pytest.raises(DurationOutOfRange) as exc:
        validate_script(sample_script, cfg)
    assert exc.value.details["estimated_sec"] < 35


def test_duration_too_long(sample_script, cfg):
    # Хук не раздуваем: иначе сработает HOOK_TOO_LONG раньше DURATION_OUT_OF_RANGE.
    for block in sample_script["blocks"]:
        if block.get("role") != "hook":
            block["text"] = block["text"] * 4
    with pytest.raises(DurationOutOfRange):
        validate_script(sample_script, cfg)


def test_meme_in_medicine_forces_off_with_warning(sample_script, cfg):
    sample_script["meta"]["category"] = "medicine"
    sample_script["meta"]["allow_memes"] = True
    result = validate_script(sample_script, cfg)
    assert result["meta"]["allow_memes"] is False
    codes = [w["code"] for w in result["_validation"]["warnings"]]
    assert "MEME_IN_MEDICINE" in codes
    assert all(b["meme_allowed"] is False for b in result["blocks"])


def test_budget_exceeded(sample_script, cfg):
    cfg.set("budget.max_cost_per_video_usd", 0.01)
    with pytest.raises(BudgetExceeded):
        validate_script(sample_script, cfg)


def test_schema_rejects_unknown_field(sample_script, cfg):
    sample_script["blocks"][0]["unexpected_field"] = 1
    with pytest.raises(ValidationError) as exc:
        validate_script(sample_script, cfg)
    assert exc.value.code == "SCHEMA_INVALID"


def test_schema_rejects_bad_role(sample_script, cfg):
    sample_script["blocks"][1]["role"] = "intro"
    with pytest.raises(ValidationError):
        validate_script(sample_script, cfg)


def test_duplicate_block_ids(sample_script, cfg):
    sample_script["blocks"][1]["id"] = sample_script["blocks"][0]["id"]
    with pytest.raises(ValidationError) as exc:
        validate_script(sample_script, cfg)
    assert exc.value.code == "DUPLICATE_BLOCK_ID"


def test_hook_just_over_three_seconds_is_blocking(sample_script, cfg):
    sample_script["blocks"][0]["text"] = _HOOK_3_1
    duration = estimate_block_duration(_HOOK_3_1)
    assert duration > HOOK_MAX_SEC
    with pytest.raises(ValidationError) as exc:
        validate_script(sample_script, cfg)
    assert exc.value.code == "HOOK_TOO_LONG"
    assert "вступление" in exc.value.message


def test_hook_under_three_seconds_without_greeting_passes(sample_script, cfg):
    sample_script["blocks"][0]["text"] = _SHORT_HOOK
    assert estimate_block_duration(_SHORT_HOOK) <= HOOK_MAX_SEC
    result = validate_script(sample_script, cfg)
    assert result["_validation"]["ok"] is True
    codes = [w["code"] for w in result["_validation"]["warnings"]]
    assert "HOOK_TOO_LONG" not in codes


def test_channel_scripts_with_hook_over_three_seconds_fail(cfg, repo_root):
    """Приёмка MUST-001: spoken hook >3.0 с не получает ok. Имена — в ассерте."""
    too_long = []
    fitting = []
    for name in _CHANNEL_SCRIPTS:
        script = read_json(repo_root / "scripts" / name)
        hook = next(b for b in script["blocks"] if b.get("role") == "hook")
        if estimate_block_duration(hook["text"]) <= HOOK_MAX_SEC:
            fitting.append(name)
            continue
        too_long.append(name)
        with pytest.raises(ValidationError) as exc:
            validate_script(script, cfg)
        assert exc.value.code == "HOOK_TOO_LONG", name
    assert too_long == [
        "redshift_0044.json",
        "redshift_0045.json",
        "redshift_0046.json",
    ]
    assert "redshift_0042.json" in fitting
    assert "redshift_0047.json" in fitting
    for name in ("redshift_0042.json", "redshift_0047.json"):
        script = read_json(repo_root / "scripts" / name)
        result = validate_script(script, cfg)
        assert result["_validation"]["ok"] is True, name


class TestTheRetentionLoopHasAShape:
    """Форма петли из `script_playbook.md`.

    Петля — отказ, не предупреждение: иначе ролик с незакрытым вопросом
    уходит в выдачу.
    """

    def _codes(self, script, cfg):
        return [w["code"] for w in validate_script(script, cfg)["_validation"]["warnings"]]

    def test_a_working_script_says_nothing(self, sample_script, cfg):
        assert self._codes(sample_script, cfg) == []

    def test_a_hook_that_turns_into_an_intro_is_named(self, sample_script, cfg):
        # Без «сегодня разберём» в начале: с Q1.2 это отдельный, блокирующий
        # брак (HOOK_GREETING), и он сработал бы раньше проверки длины.
        sample_script["blocks"][0]["text"] = (
            "История началась почти сорок лет назад "
            "в северной экспедиции, и закончилась совершенно неожиданным образом "
            "для всех участников той долгой работы."
        )
        with pytest.raises(ValidationError) as exc:
            validate_script(sample_script, cfg)
        assert exc.value.code == "HOOK_TOO_LONG"

    def test_an_answer_in_the_second_block_is_blocking(self, sample_script, cfg):
        blocks = sample_script["blocks"]
        twist = next(b for b in blocks if b["role"] == "twist")
        blocks.remove(twist)
        blocks.insert(1, twist)
        with pytest.raises(ValidationError) as exc:
            validate_script(sample_script, cfg)
        assert exc.value.code == "PAYOFF_TOO_EARLY"

    def test_an_answer_that_only_repeats_the_setup_is_blocking(self, sample_script, cfg):
        blocks = sample_script["blocks"]
        twist = next(b for b in blocks if b["role"] == "twist")
        twist["text"] = " ".join(b["text"] for b in blocks[:2])[:200]
        with pytest.raises(ValidationError) as exc:
            validate_script(sample_script, cfg)
        assert exc.value.code == "PAYOFF_RESTATES_SETUP"

    def test_a_script_without_a_payoff_block_is_blocking(self, sample_script, cfg):
        for block in sample_script["blocks"]:
            if block["role"] == "twist":
                block["role"] = "develop"
            block.pop("answers_hook", None)
        with pytest.raises(ValidationError) as exc:
            validate_script(sample_script, cfg)
        assert exc.value.code in ("LOOP_NO_PAYOFF_BLOCK", "HOOK_UNANSWERED")

    def test_a_cta_that_opens_nothing_is_blocking(self, sample_script, cfg):
        sample_script["cta"] = {"text": "Подписывайтесь, если было полезно.",
                                "type": "statement"}
        with pytest.raises(ValidationError) as exc:
            validate_script(sample_script, cfg)
        assert exc.value.code == "CTA_CLOSES_EVERYTHING"

    def test_a_cta_that_promises_the_next_loop_is_quiet(self, sample_script, cfg):
        sample_script["cta"] = {"text": "В следующем ролике — что нашли на двенадцатом километре.",
                                "type": "statement"}
        result = validate_script(sample_script, cfg)
        codes = [w["code"] for w in result["_validation"]["warnings"]]
        assert "CTA_CLOSES_EVERYTHING" not in codes
        assert result["_validation"]["ok"]
