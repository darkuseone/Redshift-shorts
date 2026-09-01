"""Правила показа слова на экране (§5.1).

Живут отдельно от рисования: одно и то же слово одинаково обрабатывают оба
движка — покадровый композитор на Python и генератор HTML-композиции. Пока
правило лежало внутри функции отрисовки, второй движок его просто не увидел, и
в кадр поехали заглавные и точки в конце фраз.
"""

from __future__ import annotations

TRAILING_PUNCTUATION = ",.!?;:—–…«»\"'()"


def clean_word(word: str) -> str:
    """Убрать краевую пунктуацию: на экране слово, а не кусок предложения."""
    return (word or "").strip().strip(TRAILING_PUNCTUATION).strip()


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
    """Полное правило для слова субтитра: чистка краёв плюс регистр."""
    return apply_case(clean_word(word), mode)


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
        if (nxt is not None
                and _cue_letters(str(cue.get("display") or "")) <= max_letters
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
