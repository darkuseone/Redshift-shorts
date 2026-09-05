"""Нормализация текста для TTS и разметка токенов (§4.2.5).

Задача двойная:

1. Дать TTS произносимый текст: развернуть аббревиатуры и единицы, перевести
   числа в слова, проставить ударения из ``pronunciation.json``.
2. Сохранить связь «как произносится» → «как показывается в субтитре»: субтитр
   обязан показывать исходное «105», а не «сто пять», поэтому каждый токен несёт
   и ``display``, и ``spoken``, а выравнивание (P4) склеивает тайминги группы
   произносимых слов обратно в один экранный токен.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

STRESS_MARK = "́"          # комбинируемое ударение
_VOWELS_RU = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"

_ONES = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
         "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
         "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_ONES_F = dict(_ONES and {1: "одна", 2: "две"})
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят",
         "семьдесят", "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот",
             "семьсот", "восемьсот", "девятьсот"]
_SCALES = [
    ("", "", "", None),
    ("тысяча", "тысячи", "тысяч", "f"),
    ("миллион", "миллиона", "миллионов", "m"),
    ("миллиард", "миллиарда", "миллиардов", "m"),
    ("триллион", "триллиона", "триллионов", "m"),
]


def plural_form(number: int, one: str, few: str, many: str) -> str:
    n = abs(number) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def _triplet_to_words(value: int, feminine: bool) -> list[str]:
    out: list[str] = []
    if value >= 100:
        out.append(_HUNDREDS[value // 100])
        value %= 100
    if value >= 20:
        out.append(_TENS[value // 10])
        value %= 10
    if value:
        if feminine and value in (1, 2):
            out.append({1: "одна", 2: "две"}[value])
        else:
            out.append(_ONES[value])
    return out


def number_to_words(number: int | float) -> str:
    """Кардинальное числительное в именительном падеже.

    Падеж и род по контексту не выводятся — это требует синтаксического разбора.
    Для сложных случаев сценарист пишет числительное словами прямо в тексте;
    правило зафиксировано в instruction.md.
    """
    if isinstance(number, float) and not number.is_integer():
        whole = int(number)
        frac_str = f"{number:.10f}".rstrip("0").split(".")[1]
        frac = int(frac_str)
        unit = {1: "десятая", 2: "сотая", 3: "тысячная"}.get(len(frac_str), "долей")
        unit_pl = plural_form(frac, unit, unit[:-2] + "ых", unit[:-2] + "ых")
        return f"{number_to_words(whole)} целых {number_to_words(frac)} {unit_pl}"

    n = int(number)
    if n == 0:
        return "ноль"
    prefix = "минус " if n < 0 else ""
    n = abs(n)

    groups: list[int] = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    parts: list[str] = []
    for idx in range(len(groups) - 1, -1, -1):
        value = groups[idx]
        if not value:
            continue
        scale = _SCALES[idx] if idx < len(_SCALES) else _SCALES[-1]
        parts.extend(_triplet_to_words(value, feminine=scale[3] == "f"))
        if idx:
            parts.append(plural_form(value, scale[0], scale[1], scale[2]))
    return prefix + " ".join(parts)


def apply_stress(word: str, index: int) -> str:
    """Поставить знак ударения после ``index``-й буквы слова (0-based)."""
    if index < 0 or index >= len(word):
        return word
    if word[index] not in _VOWELS_RU:
        # Индекс указывает на согласную — сдвигаемся к ближайшей гласной справа.
        for i in range(index, len(word)):
            if word[i] in _VOWELS_RU:
                index = i
                break
        else:
            return word
    return word[: index + 1] + STRESS_MARK + word[index + 1:]


@dataclass
class Token:
    """Единица текста: как показывается и как произносится."""

    display: str                    # то, что увидит зритель в субтитре
    spoken: list[str] = field(default_factory=list)   # слова, ушедшие в TTS
    is_word: bool = True
    block_id: str = ""
    emphasis: bool = False          # акцентное слово блока (§5.1)

    def to_dict(self) -> dict[str, Any]:
        return {"display": self.display, "spoken": self.spoken, "is_word": self.is_word,
                "block_id": self.block_id, "emphasis": self.emphasis}


_TOKEN_RE = re.compile(r"[^\W_]+(?:[-–][^\W_]+)*|[^\s\w]+", re.UNICODE)
_NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)?$")


def normalize_text(text: str, pronunciation: dict[str, Any] | None = None, *,
                   block_id: str = "", emphasis_word: str | None = None) -> list[Token]:
    """Текст блока → список токенов с произносимой формой."""
    pron = pronunciation or {}
    abbreviations: dict[str, str] = pron.get("abbreviations", {})
    units: dict[str, str] = pron.get("units", {})
    words: dict[str, Any] = pron.get("words", {})
    emphasis_norm = (emphasis_word or "").strip().lower()
    emphasis_used = False

    tokens: list[Token] = []
    for raw in _TOKEN_RE.findall(text):
        if not raw.strip():
            continue
        if not re.match(r"[^\W_]", raw, re.UNICODE):
            # Пунктуация: в TTS уходит, на экране отдельным словом не показывается.
            if tokens:
                tokens[-1].display += raw if raw in ",.!?;:" else f" {raw}"
                tokens[-1].spoken.append(raw)
            continue

        spoken_words: list[str] = []
        if raw in abbreviations:
            spoken_words = abbreviations[raw].split()
        elif raw in units:
            spoken_words = units[raw].split()
        elif _NUMBER_RE.match(raw):
            value = float(raw.replace(",", ".")) if ("," in raw or "." in raw) else int(raw)
            spoken_words = number_to_words(value).split()
        else:
            entry = words.get(raw.lower())
            if isinstance(entry, dict) and entry.get("say_as"):
                spoken_words = str(entry["say_as"]).split()
            elif isinstance(entry, dict) and entry.get("stress") is not None:
                spoken_words = [apply_stress(raw, int(entry["stress"]))]
            else:
                spoken_words = [raw]

        # Акцент — на первом вхождении ключевого слова: §5.1 просит выделять
        # одно слово фразы, а не подсвечивать его каждый раз.
        is_emphasis = bool(
            emphasis_norm and not emphasis_used
            and raw.lower().strip(".,!?;:") == emphasis_norm
        )
        if is_emphasis:
            emphasis_used = True

        tokens.append(Token(
            display=raw,
            spoken=spoken_words,
            block_id=block_id,
            emphasis=is_emphasis,
        ))
    return tokens


def spoken_text(tokens: Iterable[Token]) -> str:
    """Собрать строку для TTS из токенов."""
    parts: list[str] = []
    for token in tokens:
        for word in token.spoken:
            if word in ",.!?;:" and parts:
                parts[-1] += word
            else:
                parts.append(word)
    return " ".join(parts)


def load_pronunciation(path) -> dict[str, Any]:
    from .jsonio import read_json_or

    return read_json_or(path, {"words": {}, "abbreviations": {}, "units": {}})


def strip_stress(text: str) -> str:
    return text.replace(STRESS_MARK, "")


def word_stem(word: str) -> str:
    """Общее начало словоформ («ничем»/«НЕЧЕМ»/«нечем»)."""
    bare = _bare_word(word)
    if not bare:
        return ""
    return bare[:max(3, len(bare) - 2)]


def _bare_word(word: str) -> str:
    return word.strip(".,!?;:«»\"'—–").lower().replace("ё", "е")


def stems_match(a: str, b: str) -> bool:
    """Совпадение словоформ, включая ничем/нечем (гласная во 2-й позиции)."""
    ba, bb = _bare_word(a), _bare_word(b)
    if not ba or not bb:
        return False
    if word_stem(ba) == word_stem(bb):
        return True
    # Одна согласная + гласная + общий хвост: ничем ↔ нечем.
    if (len(ba) >= 4 and len(bb) >= 4
            and ba[0] == bb[0] and ba[2:] == bb[2:]
            and ba[1] in "аеёиоуыэюя" and bb[1] in "аеёиоуыэюя"):
        return True
    return False


def _content_tokens(content: str) -> list[str]:
    return [t for t in re.split(r"\s+", str(content or "").strip()) if t.strip(".,!?;:«»\"'—–")]


def find_spoken_anchor(words: list[dict[str, Any]], content: str = "",
                       emphasis_word: str | None = None) -> dict[str, Any] | None:
    """Слово выравнивания, под которое ставить акцентную карточку.

    Сначала ищем в речи токены из ``content`` (оверлей/плашка), потом
    ``emphasis_word``, потом слово с флагом emphasis. Карточка должна сесть
    на произнесённый удар, а не на начало блока.
    """
    if not words:
        return None
    for token in reversed(_content_tokens(content)):
        if len(_bare_word(token)) < 3:
            continue
        for w in words:
            spoken = str(w.get("word") or w.get("display") or "")
            if stems_match(spoken, token):
                return w
    emph = str(emphasis_word or "").strip()
    if emph:
        for w in words:
            spoken = str(w.get("word") or w.get("display") or "")
            if stems_match(spoken, emph):
                return w
    for w in words:
        if w.get("emphasis"):
            return w
    return None


def accent_card_start(anchor: dict[str, Any], *, block_start: float,
                      delay_sec: float = 0.05) -> float:
    """Старт карточки: onset слова + небольшая задержка, никогда раньше слова."""
    onset = float(anchor.get("start") or block_start)
    delay = max(0.0, min(0.15, float(delay_sec)))
    return max(float(block_start), onset + delay)


def enrich_overlay_punch(content: str, block_text: str, *,
                         max_words: int = 4) -> str:
    """Короткий stub («НЕЧЕМ») → окно клаузы, где этот удар реально несёт смысл.

    Authored multi-token overlays («Проверить нечем») stay as-is when they
    already read as a clause; only ultra-short stubs (≤1 real word, or a
    digit+unit like «5 МИНУТ») get expanded from block text.
    """
    raw = str(content or "").strip()
    text = str(block_text or "").strip()
    if not raw or not text:
        return raw
    tokens = _content_tokens(raw)
    if len(tokens) > 2:
        return raw
    # Two+ alphabetic tokens already carry meaning — keep author copy.
    alpha_tokens = [t for t in tokens if len(_bare_word(t)) >= 3 and not t.isdigit()]
    if len(alpha_tokens) >= 2:
        return raw
    needle = tokens[-1]
    if len(_bare_word(needle)) < 3:
        return raw
    clauses = [c.strip(" —–-") for c in re.split(r"[,;:—–]|(?<=[.!?])\s+", text) if c.strip()]
    clause = next((c for c in clauses if any(stems_match(w, needle) for w in c.split())),
                  clauses[-1] if clauses else text)
    words = [w for w in clause.split() if w.strip(".,!?;:«»\"\'—–")]
    if not words:
        return raw
    end = next((i + 1 for i, w in enumerate(words) if stems_match(w, needle)), len(words))
    window = words[max(0, end - max_words):end]
    enriched = " ".join(window).strip(".,!?;:")
    return enriched or raw


def punch_stems(text: str) -> set[str]:
    """Stem keys for punch-family dedupe (НЕЧЕМ / ничем / Проверить нечем)."""
    out: set[str] = set()
    for token in _content_tokens(text):
        bare = _bare_word(token).lower().replace("ё", "е")
        if len(bare) < 3:
            continue
        # crude RU stem: drop common inflection tails
        stem = bare
        for suf in ("ами", "ями", "ов", "ев", "ей", "ом", "ем", "ах", "ях",
                    "ую", "юю", "ая", "яя", "ые", "ие", "ых", "их",
                    "ть", "ти", "ла", "ли", "ло", "ы", "и", "а", "я", "у", "ю", "е", "о"):
            if len(stem) > 4 and stem.endswith(suf):
                stem = stem[: -len(suf)]
                break
        stem = stem[:6] if len(stem) >= 6 else stem
        # ничем/нечем share a family (и↔е)
        if stem.startswith("нич"):
            stem = "неч" + stem[3:]
        out.add(stem)
    return out


def punch_families_overlap(a: str, b: str) -> bool:
    return bool(punch_stems(a) & punch_stems(b))


def spoken_onset_for_content(words: list[dict[str, Any]], content: str,
                             emphasis_word: str | None = None,
                             *, default: float | None = None) -> float | None:
    """Absolute start sec of the spoken punch for ``content``, or default."""
    anchor = find_spoken_anchor(words, content, emphasis_word)
    if anchor is None:
        return default
    try:
        return float(anchor.get("start"))
    except (TypeError, ValueError):
        return default

