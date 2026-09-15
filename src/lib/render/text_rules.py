"""Правила показа слова на экране (§5.1).

Живут отдельно от рисования: одно и то же слово одинаково обрабатывают оба
движка — покадровый композитор на Python и генератор HTML-композиции. Пока
правило лежало внутри функции отрисовки, второй движок его просто не увидел, и
в кадр поехали заглавные и точки в конце фраз.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .number_display import (
    _lookup, format_grouped_int, format_number_display,
    number_word_to_digit_display, parse_ru_number_words,
)

TRAILING_PUNCTUATION = ",.!?;:—–…«»\"'()"
STRESS_MARK = "\u0301"   # комбинируемое ударение: живёт в озвучке, не в кадре

_BRANDS_CACHE: list[tuple[tuple[re.Pattern[str], ...], str]] | None = None


def _brand_rules() -> list[tuple[tuple[re.Pattern[str], ...], str]]:
    """Бренды латиницей: последовательность произнесённых слов → одно слово.

    Правило лежит в ``config/glossary.json`` (``brands_latin``), а не в коде:
    каждый ролик приносит свои имена, и добавлять их правкой рендерера —
    гарантированный способ забыть одно из них.

    Ключ — цепочка слов, потому что диктор произносит бренд по слогам:
    «опен эй ай» — три слова дорожки и одно слово на экране. Резать бренд на
    три субтитра — то же самое, что рвать слово.
    """
    global _BRANDS_CACHE
    if _BRANDS_CACHE is None:
        from pathlib import Path as _Path

        from ..jsonio import read_json_or

        root = _Path(__file__).resolve().parents[3]
        raw = read_json_or(root / "config" / "glossary.json", {})
        rules: list[tuple[tuple[re.Pattern[str], ...], str]] = []
        for item in raw.get("brands_latin") or []:
            words = [str(w) for w in (item.get("words") or []) if str(w).strip()]
            replace = str(item.get("replace") or "").strip()
            if not words or not replace:
                continue
            rules.append((
                tuple(re.compile(rf"^{w}$", re.IGNORECASE) for w in words),
                replace,
            ))
        # Длинные цепочки первыми: «опен эй ай» должно победить «эй».
        rules.sort(key=lambda r: len(r[0]), reverse=True)
        _BRANDS_CACHE = rules
    return _BRANDS_CACHE


def _brand_key(text: str) -> str:
    """Слово без ударения и краевой пунктуации — по нему и ищем бренд."""
    return clean_word(text).lower()


def merge_brand_phrases(words: list[dict[str, Any]], *,
                        key: str = "display") -> list[dict[str, Any]]:
    """Склеить произнесённый по слогам бренд в одно экранное слово.

    Возвращает новый список: слова цепочки заменяются одним элементом, у
    которого ``start`` первого и ``end`` последнего, чтобы заливка шла ровно
    столько, сколько бренд звучит.
    """
    rules = _brand_rules()
    if not rules or not words:
        return list(words)
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(words):
        hit = None
        for patterns, replace in rules:
            n = len(patterns)
            if i + n > len(words):
                continue
            chunk = words[i:i + n]
            if all(p.match(_brand_key(w.get(key))) for p, w in zip(patterns, chunk)):
                hit = (n, replace, chunk)
                break
        if hit is None:
            out.append(words[i])
            i += 1
            continue
        n, replace, chunk = hit
        merged = dict(chunk[0])
        merged[key] = replace
        merged["end"] = chunk[-1].get("end", merged.get("end"))
        merged["brand_latin"] = True
        # Приклеенный предлог соседнего слова не должен уехать в бренд.
        merged.pop("lead", None)
        merged["sentence_end"] = bool(chunk[-1].get("sentence_end"))
        merged["clause_end"] = bool(chunk[-1].get("clause_end"))
        out.append(merged)
        i += n
    return out


def _is_compound_number(run: list[str]) -> bool:
    """Настоящее ли это составное числительное, а не два числа подряд.

    «Восемьдесят восемь» — одно число: разряды идут по убыванию. «Три
    четыре» — два разных числа, и склеивать их в «7» нельзя, хотя парсер
    послушно сложит. Поэтому внутри разряда значения обязаны строго убывать,
    а слово-масштаб («тысяч», «миллиона») группу закрывает и начинает новую.
    """
    previous: int | None = None
    for raw in run:
        found = _lookup(raw)
        if found is None:
            return False
        kind, value = found
        if kind == "unit":
            continue
        if kind == "scale":
            previous = None
            continue
        if previous is not None and value >= previous:
            return False
        previous = value
    return True


def merge_number_phrases(words: list[dict[str, Any]], *,
                         key: str = "display") -> list[dict[str, Any]]:
    """Склеить составное числительное в одно число на экране.

    Диктор говорит «две тысячи двадцать шесть», и пословная оцифровка ставила
    в кадр «2 ТЫСЯЧИ 20 6» — на 0050 это год выхода работы. Точно так же
    «восемьдесят восемь часов» распадалось на «80 8 ЧАСОВ».

    Склеивается только цепочка из двух и более числительных, где есть хотя бы
    одно значение: одинокий «миллион» остаётся словом, как и был.
    """
    if not words:
        return list(words)
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(words):
        run: list[str] = []
        j = i
        while j < len(words):
            token = _brand_key(words[j].get(key))
            if not token or _lookup(token) is None:
                break
            run.append(token)
            j += 1
        value = (parse_ru_number_words(run)
                 if len(run) >= 2 and _is_compound_number(run) else None)
        if value is None or not isinstance(value, int):
            out.append(words[i])
            i += 1
            continue
        chunk = words[i:j]
        merged = dict(chunk[0])
        merged[key] = format_grouped_int(value)
        merged["end"] = chunk[-1].get("end", merged.get("end"))
        merged["number_joined"] = True
        merged.pop("lead", None)
        out.append(merged)
        i = j
    return out


def latin_brand(word: str) -> str:
    """Одиночное слово → бренд латиницей, если правило его знает."""
    key = _brand_key(word)
    for patterns, replace in _brand_rules():
        if len(patterns) == 1 and patterns[0].match(key):
            return replace
    return word


def clean_word(word: str) -> str:
    """Убрать краевую пунктуацию и знак ударения.

    Ударение (U+0301) — служебный знак для TTS: он говорит синтезатору, где
    бить, и в кадре ему делать нечего. На 0050 он доехал до субтитра и на
    экране стояло «ЧЕ́ТВЕРТЬ» — лишняя палка над буквой, которую зритель
    читает как артефакт рендера.
    """
    return ((word or "").replace(STRESS_MARK, "")
            .strip().strip(TRAILING_PUNCTUATION).strip())


def apply_case(text: str, mode: str) -> str:
    """Привести слово к единому регистру.

    ``lower`` — режим по умолчанию: заглавная в начале фразы делает первую
    букву визуально крупнее остальных, и на быстрой смене слов кадр «прыгает».
    Аббревиатуры (слово целиком заглавными: ОТО, НАСА, ИИ) не трогаем — внутри
    них все буквы и так одного размера, а «ото» вместо «ОТО» меняет смысл.
    """
    if mode == "upper":
        return text.upper()
    if mode != "lower":
        return text
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) > 1 and all(ch.isupper() for ch in letters):
        return text
    return text.lower()


def subtitle_word(word: str, mode: str) -> str:
    """Полное правило для слова субтитра: чистка краёв, цифра вместо слова, регистр."""
    cleaned = clean_word(word)
    digitized = number_word_to_digit_display(cleaned)
    if digitized != cleaned:
        cleaned = digitized
    else:
        cleaned = format_number_display(cleaned)
    return apply_case(cleaned, mode)


# Реплика в один-два знака в кадре не живёт. На 0047 «а» стоит 88 мс, «и» — 93,
# и таких реплик тридцать из ста сорока шести: пятая часть дорожки субтитров —
# вспышка одной буквы посреди кадра, которую не успевают прочитать и которая
# читается как сбой рендера. Растянуть её нельзя: субтитры лежат на одном треке
# встык, и удлинение слова наехало бы на соседнее (см. MIN_WORD_SEC).
#
# Поэтому короткое служебное слово не показывается само по себе, а приклеивается
# к следующему: «а расчёты», «не в бюджет». Так оно и держится дольше, и
# отрицание — «не» перед словом — перестаёт мелькать отдельно от того, что оно
# отрицает.
SHORT_CUE_LETTERS = 2
# Пауза, через которую клеить уже нельзя: за ней слово принадлежит не этой
# фразе, а следующей.
GLUE_GAP_SEC = 0.6


def _cue_letters(text: str) -> int:
    return sum(1 for ch in clean_word(text) if ch.isalpha())


def glue_short_cues(cues: list[dict], *, max_letters: int = SHORT_CUE_LETTERS,
                    max_gap: float = GLUE_GAP_SEC) -> list[dict]:
    """Склеить короткие служебные слова со следующим за ними.

    Реплика получает поле ``lead`` — приклеенное начало. Отдельным полем, а не
    в ``display``: акцент §5.1 принадлежит знаменательному слову, и красить в
    него ещё и предлог нельзя — цвет тогда означает «начало фразы», а не
    ударение. Рисуется ``lead`` отдельным span, а в SRT просто дописывается
    перед словом.

    Идём с конца: подряд идущие короткие слова («не в бюджет») собираются в одну
    реплику, а не тянут цепочку по одному.
    """
    out: list[dict] = []
    for cue in reversed(cues):
        nxt = out[-1] if out else None
        cleaned = clean_word(str(cue.get("display") or ""))
        # Digits are the line («105 кубитов»). Gluing them into ``lead``
        # hid the number from clip-wipe, which only paints ``display``.
        if (nxt is not None
                and _cue_letters(cleaned) <= max_letters
                and not any(ch.isdigit() for ch in cleaned)
                and cue.get("block_id") == nxt.get("block_id")
                and float(nxt["start"]) - float(cue["end"]) <= max_gap):
            merged = dict(nxt)
            lead = clean_word(str(cue.get("display") or ""))
            merged["lead"] = f"{lead} {nxt['lead']}" if nxt.get("lead") else lead
            merged["start"] = float(cue["start"])
            out[-1] = merged
            continue
        out.append(dict(cue))
    out.reverse()
    return out


def drop_orphan_short_cues(cues: list[dict], *,
                           max_letters: int = SHORT_CUE_LETTERS) -> list[dict]:
    """Drop leftover 1–2 letter chips that ``glue_short_cues`` could not attach.

    After glue, «а расчёты» is one cue. A stranded «ТИ» / «ВЕ» with no neighbour
    in range stays a one-glyph flash and must not reach the frame. Numeric cues
    (``105``) have no letters and are kept.
    """
    kept: list[dict] = []
    for cue in cues:
        text = str(cue.get("display") or "")
        cleaned = clean_word(text)
        letters = _cue_letters(text)
        if letters <= max_letters and not any(ch.isdigit() for ch in cleaned):
            continue
        kept.append(cue)
    return kept
