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

from .render.number_display import format_number_display, parse_ru_number_words
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
    return _digitize_subtitle_tokens(tokens)


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


def _digitize_subtitle_tokens(tokens: list[Token]) -> list[Token]:
    """Экран: цифры с узким пробелом. Речь не трогаем."""
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _NUMBER_RE.match(tok.display.lstrip("$€£₽").rstrip("%")):
            tok.display = format_number_display(tok.display)
            out.append(tok)
            i += 1
            continue
        run = [tok]
        j = i + 1
        while j < len(tokens):
            words = [t.display for t in run] + [tokens[j].display]
            if parse_ru_number_words(words) is None:
                break
            run.append(tokens[j])
            j += 1
        value = parse_ru_number_words([t.display for t in run])
        if value is not None and len(run) >= 1 and (
                len(run) >= 2 or str(run[0].display).lower() not in (
                    "тысяча", "тысячи", "тысяч", "миллион", "миллиона", "миллионов",
                    "миллиард", "миллиарда", "миллиардов", "млн", "млрд",
                    "процент", "процента", "процентов")):
            first = run[0]
            spoken: list[str] = []
            for item in run:
                spoken.extend(item.spoken)
            suffix = ""
            last_key = str(run[-1].display).lower().strip(".,")
            if last_key.startswith("процент"):
                suffix = "%"
            first.display = format_number_display(str(int(value))) + suffix
            first.spoken = spoken
            out.append(first)
            i = j
            continue
        out.append(tok)
        i += 1
    return out


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
    # Long single-word punches already read as the line. Expanding
    # «СИНГУЛЯРНОСТЬ» picked «За семнадцать часов» from a neighbouring clause.
    if (len(tokens) == 1 and len(_bare_word(tokens[0])) >= 6
            and not any(ch.isdigit() for ch in tokens[0])):
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


def sync_overlays_from_script(
        plan: dict[str, Any],
        repo_root=None,
        *,
        script: dict[str, Any] | None = None) -> int:
    """Cut/draft overlays can drift from ``scripts/*.json`` (stale P0 cache).

    0048 kept «88 ЧАСОВ» on b4 after the script moved the card to
    «СИНГУЛЯРНОСТЬ». Enrich then parked the punch on «семнадцать часов».
    Authored type/content/hint win; other overlay keys stay.
    """
    import json
    from pathlib import Path

    if script is None:
        meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
        video_id = str(plan.get("video_id") or meta.get("video_id") or "").strip()
        if not video_id or repo_root is None:
            return 0
        path = Path(repo_root) / "scripts" / f"{video_id}.json"
        if not path.is_file():
            return 0
        try:
            script = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return 0
    src_blocks = {
        str(block.get("id") or ""): block
        for block in (script.get("blocks") or [])
        if isinstance(block, dict)
    }
    updated = 0
    for block in plan.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        src = src_blocks.get(str(block.get("id") or ""))
        if not src:
            continue
        overlay = src.get("overlay")
        if not isinstance(overlay, dict) or not overlay.get("type"):
            continue
        current = dict(block.get("overlay") or {})
        changed = False
        for key in ("type", "content", "template_hint"):
            if key not in overlay:
                continue
            if current.get(key) != overlay.get(key):
                current[key] = overlay[key]
                changed = True
        if changed:
            block["overlay"] = current
            updated += 1
    return updated


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



# On-screen jargon → plain display (VO/TTS untouched). Prefer broad-audience words
# or a short gloss on cards; karaoke single-word captions stay spoken form.
# Запасная таблица на случай, если `config/glossary.json` недоступен: она
# повторяет то, что лежит в файле, и нужна только чтобы сборка не падала из-за
# отсутствующего конфига. Правки вносятся в файл, а не сюда.
_ON_SCREEN_PLAIN: tuple[tuple[str, str], ...] = (
    (r"(?i)квантов(?:ый|ого|ому|ым|ом)?\s+чип(?:а|у|ом|е|ы|ов)?",
     "квантовый компьютер"),
    (r"(?i)\bчип(?:а|у|ом|е|ы|ов)?\b", "процессор"),
    (r"(?i)below the surface code threshold",
     "ниже порога ошибок"),
    (r"(?i)surface code threshold", "порог ошибок"),
    (r"(?i)\bqubits?\b", "кубиты"),
)

# Скобочная пояснялка на карточке — брак, названный критиком дословно. Правило
# §7.3 запрещает её на любом экранном тексте, поэтому здесь это не настройка,
# а инвариант: `soften_on_screen_copy` не умеет её ставить в принципе.
_GLOSS_BRACKETS = ("(", ")")

_GLOSSARY_CACHE: dict[str, Any] = {}


def load_glossary(repo_root=None) -> dict[str, Any]:
    """Словарь терминов (§7.3, §11.3). Кэшируется по пути.

    Две колонки на термин: ``on_screen`` — чем термин становится на карточке,
    ``spoken`` — что к нему добавляется в озвучке. Разделение не косметическое:
    на экране у нас одно акцентное слово и подпись ≤ 6 слов, в речи — сколько
    угодно, потому что её слушают, а не читают за секунду.
    """
    from pathlib import Path as _Path

    from .jsonio import read_json_or

    root = _Path(repo_root) if repo_root is not None else _Path(__file__).resolve().parents[2]
    path = root / "config" / "glossary.json"
    key = str(path)
    if key not in _GLOSSARY_CACHE:
        _GLOSSARY_CACHE[key] = read_json_or(path, {"on_screen": [], "spoken": []})
    return _GLOSSARY_CACHE[key]


def _on_screen_rules(repo_root=None) -> tuple[tuple[str, str], ...]:
    rules = load_glossary(repo_root).get("on_screen") or []
    pairs = tuple((str(r["pattern"]), str(r["replace"])) for r in rules
                  if r.get("pattern") and r.get("replace") is not None)
    return pairs or _ON_SCREEN_PLAIN


_NECHEM_RE = re.compile(r"нечем", re.IGNORECASE)


def prefer_nichem_spelling(text: str) -> str:
    """On-screen copy uses ничем (и), not нечем (е). Voice is left alone."""
    def _case(match: re.Match[str]) -> str:
        src = match.group(0)
        if src.isupper():
            return "НИЧЕМ"
        if src[:1].isupper():
            return "Ничем"
        return "ничем"
    return _NECHEM_RE.sub(_case, str(text or ""))


def soften_on_screen_copy(text: str, *, repo_root=None) -> str:
    """Упростить жаргон для экранного текста, не трогая озвучку (§7.3).

    Скобочных глоссов здесь нет и не будет: «(квантовый бит)» на карточке —
    прямая цитата критика, а карточка по §7.3 несёт одно акцентное слово и
    подпись ≤ 6 слов. Пояснения уходят в озвучку — `gloss_for_speech`.
    """
    raw = str(text or "").strip()
    if not raw:
        return raw
    out = raw
    for pattern, repl in _on_screen_rules(repo_root):
        out = re.sub(pattern, repl, out)
    return prefer_nichem_spelling(out)


def gloss_for_speech(text: str, *, seen: set[str] | None = None,
                     repo_root=None) -> str:
    """Вставить пояснение термина **в устный** текст (§11.3).

    ``seen`` — уже пояснённые термины ролика: пояснение звучит один раз, иначе
    ролик превращается в лекцию. Вызывающий передаёт один и тот же набор на
    все блоки — так «кубит» поясняется в первом блоке, где встретился, и
    больше нигде.
    """
    raw = str(text or "")
    if not raw.strip():
        return raw
    seen = seen if seen is not None else set()
    out = raw
    for rule in load_glossary(repo_root).get("spoken") or []:
        term = str(rule.get("term") or "")
        gloss = str(rule.get("gloss") or "")
        if not term or not gloss:
            continue
        if rule.get("once", True) and term in seen:
            continue
        if not re.search(term, out):
            continue
        if gloss.lower() in out.lower():
            # Автор уже пояснил термин своими словами — второй раз незачем.
            seen.add(term)
            continue
        match = re.search(term, out)
        if match is None:
            continue
        tail = out[match.end():match.end() + 1]
        # Вторая запятая не ставится там, где следующий знак уже её несёт:
        # «кубитов, квантовый бит,, и это много» — не речь, а опечатка.
        closer = "" if tail in ",.!?;:" else ","
        out = f"{out[:match.end()]}, {gloss}{closer}{out[match.end():]}"
        seen.add(term)
    return out


def has_bracket_gloss(text: str) -> bool:
    """Есть ли на строке скобочная пояснялка — запрещённая §7.3 на карточке."""
    return bool(re.search(r"\([^)]{2,}\)", str(text or "")))
