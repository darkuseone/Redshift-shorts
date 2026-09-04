"""Построение поисковых запросов к стокам (§7.2, скилл ``redshift-broll-search``).

Правило ТЗ: запросы строятся **на английском из смысла блока**, а не подстрочным
переводом русского текста. Поэтому здесь нет машинного перевода: есть словарь
предметных понятий канала (космос, ИИ, лаборатории, интерфейсы) и генератор
вариантов разной абстракции.

На слот выдаётся 3–5 формулировок: конкретная → предметная → метафорическая →
фактурная. Если ни одна конкретная не находит материала, метафора закрывает слот
лучше, чем пустота.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# Понятия канала: русский триггер → английские опоры запроса.
CONCEPTS: dict[str, list[str]] = {
    "квант": ["quantum processor", "quantum computer", "cryostat laboratory"],
    "кубит": ["quantum chip macro", "superconducting circuit", "quantum processor closeup"],
    "чип": ["microchip macro", "semiconductor wafer", "circuit board closeup"],
    "процессор": ["processor macro shot", "silicon chip", "computer hardware closeup"],
    "нейросет": ["neural network visualization", "ai data flow", "server room ai"],
    "интеллект": ["artificial intelligence abstract", "machine learning visualization"],
    "алгоритм": ["code on screen", "data processing abstract"],
    "космос": ["deep space stars", "galaxy nebula", "orbit earth view", "solar system planets"],
    "планет": ["planet surface", "exoplanet space", "telescope observatory", "solar system"],
    "телескоп": ["space telescope", "observatory dome night", "astronomer telescope", "james webb telescope"],
    "звезд": ["starfield timelapse", "night sky stars", "nebula deep space"],
    "ракет": ["rocket launch", "spacecraft engine", "launch pad"],
    "солнц": ["solar flare sun", "sun surface closeup", "solar observatory"],
    "орбит": ["earth orbit view", "satellite orbit earth", "iss space station"],
    "новост": ["newsroom broadcast desk", "breaking news screen", "press conference"],
    "пресс": ["newspaper printing press", "journalist press conference", "news article screen"],
    "лаборатор": ["research laboratory", "scientist microscope", "clean room laboratory", "chip fab cleanroom"],
    "завод": ["semiconductor fab cleanroom", "chip manufacturing factory", "wafer fabrication"],
    "учён": ["scientist working", "researcher laboratory", "science team discussion"],
    "исследован": ["research team laboratory", "scientific study documents"],
    "медиц": ["medical research laboratory", "hospital equipment", "dna helix"],
    "геном": ["dna helix animation", "genetic research laboratory"],
    "клетк": ["cells under microscope", "biological cells macro"],
    "мозг": ["brain scan visualization", "neuroscience laboratory", "mri brain"],
    "энерг": ["power plant", "energy grid", "solar panels field"],
    "климат": ["climate change landscape", "melting glacier", "wind turbines"],
    "робот": ["industrial robot arm", "humanoid robot", "robotics laboratory"],
    "данн": ["data visualization abstract", "data center servers", "analytics dashboard"],
    "график": ["chart data visualization", "rising graph abstract"],
    "сервер": ["server room blue light", "data center corridor"],
    "статья": ["scientific paper on screen", "reading article laptop"],
    "патент": ["patent document closeup", "technical drawing blueprint"],
    "деньг": ["financial charts screen", "stock market data"],
    "город": ["city timelapse night", "urban crowd street"],
    "люди": ["crowd people walking", "people city street"],
    "ошибк": ["error warning screen", "glitch abstract"],
    "время": ["clock time lapse", "hourglass macro"],
    "вселен": ["universe deep space", "cosmic web visualization"],
}

# Метафорические опоры по роли блока — когда предметного кадра нет.
ROLE_METAPHORS: dict[str, list[str]] = {
    "hook": ["abstract dark texture macro", "slow motion particles dark"],
    "setup": ["technology abstract background", "macro texture technology"],
    "evidence": ["documents on desk", "screen with data closeup", "news article screen"],
    "develop": ["abstract data particles", "geometric motion background"],
    "twist": ["dramatic dark abstract", "light through darkness"],
    "cta": ["abstract gradient motion", "minimal red abstract background"],
}

CATEGORY_HINT: dict[str, str] = {
    "space": "space", "ai": "ai", "tech": "tech", "medicine": "medicine", "science": "science",
}

# Классы для маршрутизации источников (§7.2)
INTENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("space", ("space", "orbit", "galaxy", "nebula", "planet", "rocket", "telescope",
               "spacecraft", "astronaut", "cosmic", "star", "solar", "sun", "iss")),
    ("lab", ("laboratory", "microscope", "scientist", "research", "clean room", "petri",
             "fab", "wafer", "semiconductor")),
    ("news", ("news", "press", "journalist", "broadcast", "newspaper", "article", "reportage")),
    ("biotech", ("dna", "genetic", "cells", "biology", "protein", "virus")),
    ("medicine", ("medical", "hospital", "patient", "clinical", "brain scan", "mri")),
    ("servers", ("server", "data center", "datacenter", "rack", "network")),
    ("interface", ("screen", "interface", "dashboard", "ui", "code", "terminal", "laptop")),
    ("dataviz", ("data visualization", "chart", "graph", "analytics", "abstract data")),
    ("city", ("city", "urban", "street", "crowd", "traffic", "skyline")),
    ("people", ("people", "person", "portrait", "team", "worker", "face")),
    ("archive", ("archive", "historical", "vintage", "1960", "1970", "old film")),
    ("logo", ("logo", "brand", "icon")),
]


def classify_intent(visual_intent: str, queries: Iterable[str], category: str = "") -> str:
    """К какому классу отнести слот — определяет приоритет источников (§7.2)."""
    haystack = " ".join([visual_intent, *queries]).lower()
    for kind, markers in INTENT_PATTERNS:
        if any(marker in haystack for marker in markers):
            return kind
    return CATEGORY_HINT.get(category, "default")


def _concepts_from_text(text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for trigger, options in CONCEPTS.items():
        if trigger in lowered:
            found.extend(options)
    return list(dict.fromkeys(found))


def _looks_english(text: str) -> bool:
    letters = re.findall(r"[a-zA-Zа-яА-ЯёЁ]", text)
    if not letters:
        return False
    latin = sum(1 for ch in letters if ch.isascii())
    return latin / len(letters) > 0.7


def build_queries(slot: dict[str, Any], plan: dict[str, Any], *, count: int = 4) -> list[str]:
    """3–5 запросов разной абстракции для одного слота (§7.2.2)."""
    out: list[str] = []

    # 1. Готовые английские запросы сценариста — самые конкретные.
    for query in slot.get("queries") or []:
        if _looks_english(query):
            out.append(query.strip())

    # 2. Предметные понятия, вытащенные из смысла блока и текста.
    block = next((b for b in plan.get("blocks", []) if b["id"] == slot.get("block_id")), {})
    source_text = " ".join([slot.get("visual_intent", ""), block.get("text", ""),
                            block.get("visual_intent", "")])
    out.extend(_concepts_from_text(source_text))

    # 3. Русские запросы сценариста не переводим подстрочно, но используем как
    #    источник понятий — иначе теряется авторское намерение.
    for query in slot.get("queries") or []:
        if not _looks_english(query):
            out.extend(_concepts_from_text(query))

    # 4. Метафора по роли блока — на случай, если предметного кадра не найдётся.
    out.extend(ROLE_METAPHORS.get(slot.get("role", ""), []))

    # 5. Фактура как последний рубеж.
    out.append("abstract macro texture slow motion")

    seen: list[str] = []
    for query in out:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query.lower() not in {q.lower() for q in seen}:
            seen.append(query)
    return seen[:max(3, count)]
