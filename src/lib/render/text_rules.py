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
