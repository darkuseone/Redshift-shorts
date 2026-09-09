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
    BudgetExceeded, DurationOutOfRange, FillerWords, HookGreeting, HookUnanswered,
    MissingCta, MissingHook, NoSource, QuoteTooLong, ValidationError,
)
from ..lib.beats import answer_block_index
from ..lib.costs import estimate_cost, guard_estimate
from ..lib.fillers import discourse_hits, strip_hesitations
from ..lib.fonts import validate_font
from ..lib.jsonio import read_json
from ..lib.logging import get_logger
from ..lib.endings import last_ending_type, next_ending_type, repeats_previous
from ..lib.schema import (
    CTA_LEGACY, SCRIPT_SCHEMA, count_words, estimate_block_duration,
    estimate_script_duration, extract_quotes,
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

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")

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


# Разгон вместо хука: ролик начинается с представления, а не с причины
# смотреть. Первые секунды — единственное, что видит пролистывающий, и
# «всем привет, сегодня разберём» тратит их на вежливость.
_GREETING_OPENERS = (
    "привет", "всем привет", "здравствуй", "здравствуйте", "добрый день",
    "добрый вечер", "с вами", "это канал", "на связи",
    "в этом видео", "в сегодняшнем видео", "сегодня разберём", "сегодня разберем",
    "сегодня поговорим", "сегодня я расскажу", "подписывайтесь",
)


def _check_hook_greeting(blocks: list[dict[str, Any]]) -> None:
    """§5.2 H-5 HOOK_GREETING: приветствие в первом блоке — брак.

    Блокирующий, а не предупреждение: предупреждение здесь ничего не меняет —
    ролик всё равно уедет в рендер, а зритель всё равно уйдёт на первой
    секунде. Дешевле остановить на P0, где правка стоит одну строку сценария.
    """
    hook = next((b for b in blocks if b.get("role") == "hook"), None) or \
        (blocks[0] if blocks else None)
    if not hook:
        return
    opening = re.sub(r"^[\s\-—«\"']+", "", str(hook.get("text") or "")).lower()
    for opener in _GREETING_OPENERS:
        if opening.startswith(opener):
            raise HookGreeting(
                f"хук начинается с приветствия {opener!r}: первые секунды обязаны "
                f"дать причину смотреть, а не представление "
                f"(§5.2; банк хуков — в ТЗ §5.4)",
                block_id=hook.get("id"), opener=opener,
            )


def _check_hook_on_screen(meta: dict[str, Any],
                          blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Экранная строка хука: есть ли она и не длинна ли (§5.2 H-5)."""
    out: list[dict[str, Any]] = []
    spec = meta.get("hook") or {}
    on_screen = str(spec.get("on_screen") or "").strip()
    hook = next((b for b in blocks if b.get("role") == "hook"), None) or {}
    overlay_content = str((hook.get("overlay") or {}).get("content") or "").strip()
    if not on_screen and not overlay_content:
        out.append({
            "code": "HOOK_NO_ON_SCREEN",
            "message": "у хука нет экранной строки: ни meta.hook.on_screen, ни "
                       "overlay.content — приём выберется вслепую",
        })
    if on_screen and count_words(on_screen) > 7:
        out.append({
            "code": "HOOK_ON_SCREEN_TOO_LONG",
            "message": f"экранная строка хука — {count_words(on_screen)} слов "
                       f"при потолке 7: за секунду её не прочитать",
        })
    return out


# --- петля удержания (script_playbook.md) ------------------------------------
# Ролик держат не «интересной темой», а незакрытым вопросом: он открывается в
# первые секунды и закрывается ответом, которого зритель не предсказал. Длина
# хука — отказ: удар длиннее limits.hook_sec уже вступление, а не хук. Остальные
# проверки формы петли пока предупреждения: сценарий бывает намеренно устроен
# иначе. Молча пропускать ролик, где ответ стоит вторым блоком, нельзя.

# Доля хронометража, раньше которой ответ гасит интригу, не успев её раскачать.
PAYOFF_EARLIEST_SHARE = 0.40
# Доля, позже которой ответу негде осесть: за ним ещё перенос и CTA.
PAYOFF_LATEST_SHARE = 0.88
# Fallback, если в конфиге нет limits.hook_sec. Истина — config.yaml.
HOOK_MAX_SEC = 3.0
# Сколько новых слов обязан принести ответ сверх уже сказанного.
PAYOFF_MIN_NEW_WORDS = 2

# Маркеры CTA, который открывает следующую петлю, а не закрывает эту.
_NEXT_LOOP_MARKERS = (
    "следующ", "дальше", "продолжен", "вторая часть", "второй части", "часть втор",
    "ещё страннее", "еще страннее", "самое странное", "не рассказал", "не сказал",
    "остал", "впереди",
)


def _map_legacy_cta(script: dict[str, Any]) -> list[dict[str, Any]]:
    """Старые три типа концовки → восемь новых (§6.4), до проверки схемы.

    Шесть уже написанных сценариев канала используют ``question``. Отвергать их
    было бы правкой ради правки: имя типа изменилось, замысел — нет. Перевод
    идёт **до** ``_schema_validate``, иначе схема упадёт на легитимном сценарии.
    """
    cta = script.get("cta")
    if not isinstance(cta, dict):
        return []
    kind = cta.get("type")
    if not isinstance(kind, str) or kind not in CTA_LEGACY:
        return []
    cta["type"] = CTA_LEGACY[kind]
    return [{
        "code": "CTA_TYPE_RENAMED",
        "message": (f"тип концовки «{kind}» переименован в «{cta['type']}» (§6.4): "
                    "перечень вырос с трёх типов до восьми, старое имя оставлено "
                    "как псевдоним"),
    }]


def _check_ending_rotation(cta: dict[str, Any] | None, cfg, *,
                           video_id: str = "") -> list[dict[str, Any]]:
    """Ротация концовок (§6.4): тот же тип не два ролика подряд.

    Предупреждение, а не отказ: решает автор. Но молчать нельзя — именно так
    канал и закончился одинаково шесть роликов подряд, каждый раз законно.
    """
    kind = str((cta or {}).get("type") or "")
    if not kind:
        return []
    try:
        if not repeats_previous(cfg, kind, video_id=video_id):
            return []
        suggestion = next_ending_type(cfg, allow_loop_seam=False)
        previous = last_ending_type(cfg)
    except Exception:  # noqa: BLE001 — память ротации не обязана существовать
        return []
    return [{
        "code": "CTA_TYPE_REPEATS",
        "message": (f"предыдущий ролик закончился тем же типом «{previous}»: "
                    f"кольцо §6.4 предлагает «{suggestion}» — канал не должен "
                    "заканчиваться одинаково два раза подряд"),
    }]


# Где закрывается гештальт хука. Определение переехало в `lib/beats.py`: ту же
# точку ищет карта битов §6.1, и разойтись гейт с монтажом не имеет права —
# иначе P0 предупреждает про один блок, а монтаж считает ответом другой.
_answer_block_index = answer_block_index


def _hook_max_sec(cfg) -> float:
    """Потолок хука: один источник с P5 — ``limits.hook_sec``."""
    if cfg is None:
        return HOOK_MAX_SEC
    return float(cfg.get("limits.hook_sec", HOOK_MAX_SEC))


def _check_retention_loop(blocks: list[dict[str, Any]],
                          cta: dict[str, Any] | None, *,
                          hook_max_sec: float = HOOK_MAX_SEC) -> list[dict[str, Any]]:
    """Форма петли: удар — интрига — затяжка — ответ — CTA на следующую петлю."""
    warnings: list[dict[str, Any]] = []
    if not blocks:
        return warnings

    spans = [estimate_block_duration(b.get("text", "")) for b in blocks]
    total = sum(spans)
    starts = [sum(spans[:i]) for i in range(len(blocks))]

    hook_i = next((i for i, b in enumerate(blocks) if b.get("role") == "hook"), None)
    if hook_i is not None and spans[hook_i] > hook_max_sec:
        raise ValidationError(
            f"хук длится ~{spans[hook_i]:.1f} сек (потолок {hook_max_sec}): "
            "это уже вступление, а не удар — режьте до одного обещания",
            code="HOOK_TOO_LONG",
            duration_sec=round(spans[hook_i], 3),
            max_sec=hook_max_sec,
        )

    answer_i = _answer_block_index(blocks)
    if answer_i is None:
        warnings.append({
            "code": "LOOP_NO_PAYOFF_BLOCK",
            "message": ("нет ни блока twist, ни пометки answers_hook: непонятно, "
                        "где ролик отдаёт обещанное — ответ размазан по тексту"),
        })
        return warnings

    share = starts[answer_i] / total if total else 0.0
    if share < PAYOFF_EARLIEST_SHARE:
        warnings.append({
            "code": "PAYOFF_TOO_EARLY",
            "message": (f"ответ приходит на {share:.0%} хронометража (раньше "
                        f"{PAYOFF_EARLIEST_SHARE:.0%}): интригу нечем держать, "
                        "добавьте затяжку между хуком и ответом"),
        })
    elif share > PAYOFF_LATEST_SHARE:
        warnings.append({
            "code": "PAYOFF_TOO_LATE",
            "message": (f"ответ приходит на {share:.0%} хронометража (позже "
                        f"{PAYOFF_LATEST_SHARE:.0%}): ему негде осесть перед CTA"),
        })

    said = set()
    for block in blocks[:answer_i]:
        said |= _content_words(block.get("text", ""))
    fresh = _content_words(blocks[answer_i].get("text", "")) - said
    if len(fresh) < PAYOFF_MIN_NEW_WORDS:
        warnings.append({
            "code": "PAYOFF_RESTATES_SETUP",
            "message": (f"блок {blocks[answer_i].get('id')} закрывает хук, но не приносит "
                        "ничего нового: ответ пересказывает уже сказанное вместо того, "
                        "чтобы разойтись с ожиданием"),
        })

    text = str((cta or {}).get("text") or "")
    kind = str((cta or {}).get("type") or "")
    opens_next = any(m in text.lower() for m in _NEXT_LOOP_MARKERS)
    if kind == "soft_subscribe" and not opens_next:
        warnings.append({
            "code": "CTA_CLOSES_EVERYTHING",
            "message": ("CTA ничего не открывает: тип soft_subscribe и ни слова о "
                        "следующем ролике — подписка держится на новой петле, а не "
                        "на просьбе"),
        })
    return warnings


def _check_source_snippets(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Русский `snippet` обязателен на карточке источника (§7.3, Q3.5).

    Латинский заголовок на карточку не попадает: `_on_screen_copy` его
    выбрасывает, и без русской строки карточка выходит без первой строки —
    рамка с доменом и пустотой. Требуем то, что карточка обязана показать,
    а не то, что у источника есть.

    Предупреждение, а не отказ: сценарий с источником без цитаты собрать
    можно, просто карточка выйдет беднее — решает автор.
    """
    warnings: list[dict[str, Any]] = []
    for source in sources or []:
        if not source.get("show_on_screen", True):
            continue
        snippet = str(source.get("snippet") or "").strip()
        if snippet and _CYRILLIC_RE.search(snippet):
            continue
        title = str(source.get("title") or "")
        warnings.append({
            "code": "SOURCE_SNIPPET_MISSING",
            "message": (f"источник «{title[:60]}» показывается на экране без русской "
                        "цитаты: английский заголовок на карточку не попадает "
                        "(§7.3), и первая строка останется пустой"),
        })
    return warnings


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
    warnings.extend(_map_legacy_cta(script))
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

    # --- HOOK_GREETING / HOOK_UNANSWERED
    _check_hook_greeting(blocks)
    _check_hook_answered(blocks)
    warnings.extend(_check_hook_on_screen(meta, blocks))

    # --- форма петли удержания (HOOK_TOO_LONG — отказ; остальное — предупреждения)
    warnings.extend(_check_retention_loop(
        blocks, script.get("cta"), hook_max_sec=_hook_max_sec(cfg),
    ))
    warnings.extend(_check_ending_rotation(script.get("cta"), cfg,
                                           video_id=str(meta.get("video_id") or "")))

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
    warnings.extend(_check_source_snippets(sources))

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
        script["cta"] = {"text": cta_block.get("text", ""), "type": "soft_subscribe"}

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
