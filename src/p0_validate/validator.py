"""P0: ``script.json`` + ``config.yaml`` → ``validated_script.json`` или ошибка.

Реализует таблицу кодов §8.2 целиком. Принцип: лучше отклонить сценарий с
внятным кодом, чем собрать брак. Единственное исключение — ``MEME_IN_MEDICINE``:
по ТЗ это не отказ, а принудительное выключение мемов с warning.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..errors import (
    BudgetExceeded, DurationOutOfRange, FillerWords, HookUnanswered, MissingCta,
    MissingHook, NoSource, QuoteTooLong, ValidationError,
)
from ..lib.costs import estimate_cost, guard_estimate
from ..lib.fillers import discourse_hits, strip_hesitations
from ..lib.fonts import validate_font
from ..lib.jsonio import read_json
from ..lib.logging import get_logger
from ..lib.schema import (
    SCRIPT_SCHEMA, count_words, estimate_block_duration, estimate_script_duration,
    extract_quotes,
)

_log = get_logger("p0")

# Категории, где источник обязателен (§8.2 NO_SOURCE)
SOURCE_REQUIRED_CATEGORIES = ("ai", "space", "tech", "medicine")

_STOPWORDS = {
    "этот", "этой", "этом", "который", "которая", "которые", "чтобы", "потому",
    "когда", "может", "быть", "если", "самый", "только", "очень", "нужно", "тоже",
    "весь", "вся", "всё", "все", "как", "что", "где", "чем", "уже", "ещё", "еще",
    "его", "их", "она", "они", "оно", "мы", "вы", "ты", "но", "и", "а", "или",
    "для", "над", "под", "при", "про", "без", "из", "от", "до", "по", "за", "на",
    "не", "ни", "же", "ли", "бы", "вот", "так", "там", "тут", "then", "the",
}

_QUESTION_MARKERS = ("почему", "как ", "зачем", "что если", "правда ли", "сколько",
                     "когда", "кто ", "чем ", "?")


def _content_words(text: str, *, min_len: int = 4) -> set[str]:
    words = re.findall(r"[^\W\d_]{%d,}" % min_len, text.lower(), flags=re.UNICODE)
    return {w[:6] for w in words if w not in _STOPWORDS}   # грубая «лемматизация» по основе


def _schema_validate(script: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        _log.warning("jsonschema не установлена — проверка схемы пропущена")
        return
    validator = jsonschema.Draft202012Validator(SCRIPT_SCHEMA)
    errors = sorted(validator.iter_errors(script), key=lambda e: list(e.path))
    if errors:
        details = [
            {"path": "/".join(str(p) for p in err.path) or "<root>", "message": err.message}
            for err in errors[:12]
        ]
        raise ValidationError(
            f"сценарий не соответствует схеме ({len(errors)} нарушений)",
            code="SCHEMA_INVALID", errors=details,
        )


def _check_hook_answered(blocks: list[dict[str, Any]]) -> None:
    """§8.2 HOOK_UNANSWERED: хук без ответа — брак (§6, жёсткое правило 1)."""
    hook = next((b for b in blocks if b.get("role") == "hook"), None)
    if hook is None:
        return
    later = [b for b in blocks if b is not hook]
    if any(b.get("answers_hook") for b in later):
        return

    hook_text = hook.get("text", "")
    hook_terms = _content_words(hook_text)
    is_question = any(m in hook_text.lower() for m in _QUESTION_MARKERS)

    answer_roles = {"twist", "develop", "evidence", "setup", "cta"}
    for block in later:
        if block.get("role") not in answer_roles:
            continue
        shared = hook_terms & _content_words(block.get("text", ""))
        if len(shared) >= (1 if not is_question else 2) or (
            is_question and block.get("role") == "twist" and shared
        ):
            return

    raise HookUnanswered(
        "хук не получает ответа ни в одном блоке: добавьте блок с ответом "
        "или пометьте отвечающий блок полем \"answers_hook\": true",
        hook_id=hook.get("id"), hook_terms=sorted(hook_terms)[:10],
    )


def _check_quotes(blocks: list[dict[str, Any]], max_words: int) -> None:
    for block in blocks:
        for quote in extract_quotes(block.get("text", "")):
            words = count_words(quote)
            if words > max_words:
                raise QuoteTooLong(
                    f"прямая цитата в блоке {block.get('id')} длиннее {max_words} слов "
                    f"({words}): пересказывайте факт, а не текст источника",
                    block_id=block.get("id"), words=words, quote=quote[:160],
                )


def _check_fonts(cfg) -> list[dict[str, Any]]:
    """§8.2 FONT_MISSING_CYRILLIC — падать до монтажа, а не рендерить «квадратики»."""
    manifest_path = cfg.path("paths.assets_dir", "assets") / "fonts" / "fonts_manifest.json"
    fonts_dir = manifest_path.parent
    checked: list[dict[str, Any]] = []
    if not manifest_path.exists():
        raise ValidationError("нет assets/fonts/fonts_manifest.json — шрифты не подключены",
                              code="FONT_MANIFEST_MISSING", path=str(manifest_path))
    manifest = read_json(manifest_path)
    sample = cfg.brand("typography.required_sample_text", None)
    for entry in manifest.get("fonts", []):
        path = fonts_dir / entry["file"]
        if not path.exists():
            raise ValidationError(f"файл шрифта отсутствует: {entry['file']}",
                                  code="FONT_FILE_MISSING", path=str(path))
        info = validate_font(path, require_cyrillic=True, sample_text=sample)
        checked.append({"role": entry.get("role"), "family": info.family,
                        "file": entry["file"], "glyphs": len(info.codepoints)})
    return checked


def validate_script(script: dict[str, Any], cfg) -> dict[str, Any]:
    """Полная валидация. Возвращает нормализованный сценарий с блоком ``_validation``."""
    warnings: list[dict[str, Any]] = []
    _schema_validate(script)

    meta = script.get("meta", {})
    blocks: list[dict[str, Any]] = script.get("blocks", [])
    roles = [b.get("role") for b in blocks]

    # --- id блоков уникальны
    ids = [b.get("id") for b in blocks]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValidationError(f"дублирующиеся id блоков: {dupes}", code="DUPLICATE_BLOCK_ID")

    # --- MISSING_HOOK / MISSING_CTA
    if "hook" not in roles:
        raise MissingHook("в сценарии нет блока с ролью hook (§6: хук обязателен в первые 3 сек)")
    if "cta" not in roles and not script.get("cta"):
        raise MissingCta("в сценарии нет ни блока с ролью cta, ни секции cta")
    if roles[0] != "hook":
        warnings.append({"code": "HOOK_NOT_FIRST",
                         "message": "блок hook не первый — порядок будет исправлен планировщиком"})

    # --- HOOK_UNANSWERED
    _check_hook_answered(blocks)

    # --- QUOTE_TOO_LONG
    _check_quotes(blocks, int(cfg.get("limits.quote_max_words", 15)))

    # --- NO_SOURCE
    category = meta.get("category")
    sources = script.get("sources", [])
    if category in SOURCE_REQUIRED_CATEGORIES and not sources:
        raise NoSource(
            f"категория {category!r} требует источников: §5.6 обязывает показать источник на экране",
            category=category,
        )

    # --- MEME_IN_MEDICINE: не отказ, а принудительное выключение (§8.2)
    if category == "medicine" and meta.get("allow_memes", True):
        meta["allow_memes"] = False
        warnings.append({
            "code": "MEME_IN_MEDICINE",
            "message": "категория medicine: мемы принудительно выключены (§5.8, §10.3.5)",
        })
    for block in blocks:
        if category == "medicine":
            block["meme_allowed"] = False

    # --- DURATION_OUT_OF_RANGE
    lo, hi = cfg.get("limits.duration_sec", [35, 70])
    estimated = estimate_script_duration(script)
    if estimated < lo or estimated > hi:
        need = round(lo - estimated, 1) if estimated < lo else round(estimated - hi, 1)
        raise DurationOutOfRange(
            f"расчётный хронометраж {estimated:.1f} сек вне диапазона {lo}–{hi} сек "
            f"({'не хватает' if estimated < lo else 'лишних'} ~{abs(need)} сек текста)",
            estimated_sec=estimated, min_sec=lo, max_sec=hi, delta_sec=need,
        )
    target = float(meta.get("target_duration_sec", estimated))
    if abs(target - estimated) > max(6.0, target * 0.2):
        warnings.append({
            "code": "TARGET_DURATION_MISMATCH",
            "message": f"target_duration_sec={target} заметно расходится с оценкой {estimated:.1f} сек",
        })

    # --- FILLER_WORDS
    # Речь ролика — это TTS нашего же текста, поэтому паразит попадает в звук
    # единственным путём: его написали здесь. Ловим до синтеза, пока он ничего
    # не стоит. Запинка — ошибка сценария: она бессмысленна в любой позиции.
    # Вводное слово — предупреждение: «вот» бывает усилителем, «значит» —
    # сказуемым, и решать, паразит ли это, обязан человек, а не список.
    for block in blocks:
        text = str(block.get("text") or "")
        _cleaned, hesitations = strip_hesitations(text)
        if hesitations:
            raise FillerWords(
                f"блок {block.get('id')}: запинки в тексте "
                f"({', '.join(hesitations)}) — их незачем озвучивать",
                block_id=block.get("id"), words=hesitations,
            )
        hits = discourse_hits(text)
        if hits:
            warnings.append({
                "code": "FILLER_WORDS",
                "message": (f"блок {block.get('id')}: вводные слова "
                            f"({', '.join(hits)}) — проверьте, не паразиты ли"),
            })

    # --- FONT_MISSING_CYRILLIC
    fonts = _check_fonts(cfg)

    # --- BUDGET_EXCEEDED
    estimate = estimate_cost(script, cfg)
    guard_estimate(estimate, cfg)

    # --- нормализация значений по умолчанию
    meta.setdefault("language", cfg.get("project.language", "ru"))
    meta.setdefault("allow_memes", True)
    meta.setdefault("allow_bg_vfx", True)
    meta.setdefault("title", meta.get("topic", ""))
    for block in blocks:
        block.setdefault("avatar", "auto")
        block.setdefault("broll_queries", [])
        block.setdefault("overlay", {"type": "none"})
        block.setdefault("meme_allowed", bool(meta.get("allow_memes", True)))
        block["_estimated_sec"] = round(estimate_block_duration(block.get("text", "")), 2)
        block["_words"] = count_words(block.get("text", ""))

    if not script.get("cta") and "cta" in roles:
        cta_block = next(b for b in blocks if b.get("role") == "cta")
        script["cta"] = {"text": cta_block.get("text", ""), "type": "statement"}

    validated = dict(script)
    validated["meta"] = meta
    validated["blocks"] = blocks
    validated["_validation"] = {
        "ok": True,
        "estimated_duration_sec": estimated,
        "duration_range": [lo, hi],
        "warnings": warnings,
        "fonts": fonts,
        "cost_estimate": estimate,
        "roles": roles,
    }
    return validated


def run_step(ctx) -> dict[str, Any]:
    """Шаг пайплайна P0."""
    script = read_json(ctx.script_path)
    validated = validate_script(script, ctx.cfg)
    ctx.write("validated_script.json", validated)
    for w in validated["_validation"]["warnings"]:
        ctx.warn(f"{w['code']}: {w['message']}")
    _log.info("сценарий валиден", extra={
        "video_id": validated["meta"]["video_id"],
        "estimated_sec": validated["_validation"]["estimated_duration_sec"],
        "blocks": len(validated["blocks"]),
        "cost_estimate_usd": validated["_validation"]["cost_estimate"]["total_usd"],
    })
    return {
        "blocks": len(validated["blocks"]),
        "estimated_sec": validated["_validation"]["estimated_duration_sec"],
        "warnings": len(validated["_validation"]["warnings"]),
    }
