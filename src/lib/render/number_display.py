"""Цифры в субтитрах: речь может быть словами, экран — числом.

TTS озвучивает «двенадцать тысяч», кадр обязан показать «12 000». Группы
тысяч разделяет узкий неразрывный пробел (U+202F). Годы 1900–2099 не бьём.
"""

from __future__ import annotations

import re

NARROW_NBSP = "\u202f"

_ONES = {
    "ноль": 0, "нуль": 0,
    "один": 1, "одна": 1, "одно": 1, "одного": 1, "одну": 1,
    "два": 2, "две": 2, "двух": 2,
    "три": 3, "трёх": 3, "трех": 3,
    "четыре": 4, "четырёх": 4, "четырех": 4,
    "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6,
    "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8,
    "девять": 9, "девяти": 9,
    "десять": 10, "десяти": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
    "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
}
_TENS = {
    "двадцать": 20, "тридцать": 30, "сорок": 40,
    "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90,
}
_HUNDREDS = {
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400,
    "пятьсот": 500, "шестьсот": 600, "семьсот": 700,
    "восемьсот": 800, "девятьсот": 900,
}
_SCALES = {
    "тысяча": 1_000, "тысячи": 1_000, "тысяч": 1_000,
    "миллион": 1_000_000, "миллиона": 1_000_000, "миллионов": 1_000_000,
    "миллиард": 1_000_000_000, "миллиарда": 1_000_000_000, "миллиардов": 1_000_000_000,
    "млн": 1_000_000, "млрд": 1_000_000_000,
}
_UNITS_SKIP = {
    "процент", "процента", "процентов", "процентах",
    "целых", "целая", "десятых", "сотых", "тысячных",
}

_NUMBER_TOKEN_RE = re.compile(
    r"^[\$€£₽]?\d{1,3}(?:[ \u00a0\u202f]?\d{3})*(?:[.,]\d+)?%?$|^\d+[.,]\d+$"
)
_PURE_INT_RE = re.compile(r"^\d+$")
_DECIMAL_RE = re.compile(r"^(\d+)[.,](\d+)$")
_YEAR_MIN, _YEAR_MAX = 1900, 2099

MONEY_RE = re.compile(
    r"\$|€|£|₽|\busd\b|\beur\b|руб(?:л|\b)|доллар|бюджет|убыт|"
    r"выигрыш|проигрыш|цен[аеуы]|стоим|млрд|миллиард|миллион\w*|\bмлн\b",
    re.I,
)


def format_grouped_int(value: int) -> str:
    """12000 → '12 000'; 105 и годы — как есть."""
    sign = "-" if value < 0 else ""
    n = abs(int(value))
    if _YEAR_MIN <= n <= _YEAR_MAX or n < 10_000:
        return f"{sign}{n}"
    digits = str(n)
    parts: list[str] = []
    while digits:
        parts.append(digits[-3:])
        digits = digits[:-3]
    return sign + NARROW_NBSP.join(reversed(parts))


def format_number_display(raw: str) -> str:
    """Цифра в кадре: группировка тысяч, запятая в десятичных как в исходнике."""
    text = (raw or "").strip()
    if not text:
        return text
    prefix = ""
    suffix = ""
    body = text
    if body[0] in "$€£₽":
        prefix, body = body[0], body[1:]
    if body.endswith("%"):
        suffix, body = "%", body[:-1]
    body = body.replace(" ", "").replace("\u00a0", "").replace(NARROW_NBSP, "")
    match = _DECIMAL_RE.match(body)
    if match:
        whole = format_grouped_int(int(match.group(1)))
        frac = match.group(2)
        sep = "," if "," in raw else "."
        return f"{prefix}{whole}{sep}{frac}{suffix}"
    if _PURE_INT_RE.match(body):
        return f"{prefix}{format_grouped_int(int(body))}{suffix}"
    return text


def _lookup(word: str) -> tuple[str, int] | None:
    key = (word or "").strip().strip(".,!?;:—–…«»\"'()").lower()
    if key in _ONES:
        return "ones", _ONES[key]
    if key in _TENS:
        return "tens", _TENS[key]
    if key in _HUNDREDS:
        return "hundreds", _HUNDREDS[key]
    if key in _SCALES:
        return "scale", _SCALES[key]
    if key in _UNITS_SKIP:
        return "unit", 0
    return None


def parse_ru_number_words(words: list[str]) -> int | float | None:
    """Разобрать последовательность русских числительных. None — не число."""
    if not words:
        return None
    total = 0
    current = 0
    saw_value = False
    for raw in words:
        found = _lookup(raw)
        if found is None:
            return None
        kind, value = found
        if kind == "unit":
            continue
        saw_value = True
        if kind == "scale":
            current = (current or 1) * value
            total += current
            current = 0
        else:
            current += value
    if not saw_value:
        return None
    return total + current


def number_word_to_digit_display(word: str) -> str:
    """Одно слово-числительное → цифра. 'тысяч' одно не трогаем."""
    found = _lookup(word)
    if found is None:
        if _NUMBER_TOKEN_RE.match((word or "").strip()):
            return format_number_display(word)
        return word
    kind, value = found
    if kind in ("scale", "unit"):
        return word
    return format_grouped_int(value)


def extract_fact_numbers(text: str) -> list[str]:
    """Конкретные цифры и составные числительные из речи сценария."""
    blob = text or ""
    found: list[str] = []
    for match in re.finditer(r"[\$€£₽]?\d+(?:[ \u00a0\u202f]?\d{3})*(?:[.,]\d+)?%?", blob):
        found.append(match.group(0))
    tokens = re.findall(r"[^\W_]+", blob.lower(), flags=re.UNICODE)
    i = 0
    while i < len(tokens):
        run: list[str] = []
        j = i
        while j < len(tokens) and _lookup(tokens[j]) is not None:
            run.append(tokens[j])
            j += 1
        if run and parse_ru_number_words(run) is not None and any(
                _lookup(w) and _lookup(w)[0] != "unit" for w in run):
            # одиночное «раз»/мусор не поймаем: unit-only отсеян parse
            if any(_lookup(w) and _lookup(w)[0] != "unit" for w in run):
                value = parse_ru_number_words(run)
                if value is not None and (
                        len(run) >= 2 or (_lookup(run[0]) and _lookup(run[0])[0] != "scale")):
                    found.append(" ".join(run))
            i = j
            continue
        i += 1
    return found


def has_money_number(text: str) -> bool:
    return bool(MONEY_RE.search(text or "")) and bool(extract_fact_numbers(text or ""))
