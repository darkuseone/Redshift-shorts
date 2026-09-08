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
    "квант": ["quantum processor", "quantum computer", "cryostat laboratory",
              "dilution refrigerator gold", "superconducting qubit chip"],
    "кубит": ["quantum chip macro", "superconducting circuit", "quantum processor closeup"],
    "чип": ["microchip macro", "semiconductor wafer", "circuit board closeup"],
    # Было `processor macro shot` / `computer hardware closeup` — сток отдавал
    # по ним офисные столы и ноутбуки. Нужен сам кристалл, а не «техника».
    "процессор": ["cpu die macro", "silicon wafer closeup", "circuit board macro"],
    "нейросет": ["neural network visualization", "ai data flow", "server room ai"],
    "интеллект": ["artificial intelligence abstract", "machine learning visualization"],
    "алгоритм": ["code on screen", "data processing abstract"],
    "космос": ["deep space stars", "galaxy nebula", "orbit earth view", "solar system planets", "milky way timelapse", "cosmic dust clouds"],
    "планет": ["planet surface", "exoplanet space", "telescope observatory", "solar system", "mars surface rover", "saturn rings space"],
    "телескоп": ["space telescope", "observatory dome night", "astronomer telescope", "james webb telescope", "radio telescope array"],
    "звезд": ["starfield timelapse", "night sky stars", "nebula deep space", "aurora borealis space"],
    "ракет": ["rocket launch", "spacecraft engine", "launch pad", "falcon heavy liftoff"],
    "солнц": ["solar flare sun", "sun surface closeup", "solar observatory", "solar eclipse corona"],
    "орбит": ["earth orbit view", "satellite orbit earth", "iss space station", "earth from space night"],
    "новост": ["newsroom broadcast desk", "breaking news screen", "press conference", "tv news studio anchors", "live news reportage"],
    "пресс": ["newspaper printing press", "journalist press conference", "news article screen", "magazine editorial desk"],
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
    # `error warning screen` тянул со стока красные окна винды. Реплика про
    # коррекцию ошибок — это схема и осциллограмма, а не системный сбой.
    "ошибк": ["error correction diagram", "signal noise oscilloscope",
              "glitch abstract dark", "error warning screen"],
    "время": ["clock time lapse", "hourglass macro"],
    "вселен": ["universe deep space", "cosmic web visualization"],
}

# Метафорические опоры по роли блока — когда предметного кадра нет.
ROLE_METAPHORS: dict[str, list[str]] = {
    "hook": ["abstract dark texture macro", "slow motion particles dark", "deep space stars"],
    "setup": ["technology abstract background", "macro texture technology", "server room blue light"],
    "evidence": ["documents on desk", "screen with data closeup", "news article screen", "newsroom broadcast desk"],
    "develop": ["abstract data particles", "geometric motion background", "galaxy nebula"],
    "twist": ["dramatic dark abstract", "light through darkness", "solar flare sun"],
    "cta": ["abstract gradient motion", "minimal red abstract background", "earth orbit view"],
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


# --- light thematic guardrail for sci topics (stock junk) -------------------
# Result/URL haystack markers that must not win quantum/lab/tech/AI slots.
# Keep tight: only clear junk + known mis-pick classes (darkroom/race/guitar).
SCI_CATEGORIES = frozenset({"ai", "tech", "science", "space", "medicine", "biotech"})
SCI_INTENT_KINDS = frozenset({
    "lab", "servers", "dataviz", "interface", "space", "biotech", "medicine", "news",
})

# Hard junk — always filtered from queries; rejected on sci topics in stage1.
STOCK_JUNK_MARKERS: tuple[str, ...] = (
    "drug", "addict", "junkie", "narcotic", "heroin", "cocaine", "meth ",
    "hose", "garden hose", "water pump", "irrigation", "sprinkler", "fire hose",
)

# Sci off-theme URL/title classes that previously slipped in as "cryostat"/circuit.
SCI_OFFTHEME_MARKERS: tuple[str, ...] = (
    "darkroom", "race-day", "race day", "racecar", "race car", "nascar",
    "motorsport", "guitar", "underwater paint", "party drug",
)

# Rover / MSL stills tagged "laboratory" won quantum slots (nasa_PIA13308).
# Space-category videos may still use them; AI/tech/lab must not.
SCI_ROVER_MARKERS: tuple[str, ...] = (
    "mars science laboratory", "curiosity", "rover", " msl", "msl ",
)

# NASA planetary/solar archives won 14s of a quantum-chip cut (nasa_S74-23458).
SCI_NASA_ARCHIVE_MARKERS: tuple[str, ...] = (
    "nasa_", "images.nasa.gov",
)
SCI_PLANETARY_MARKERS: tuple[str, ...] = (
    "lunar", "moon surface", "solar flare", "sun surface",
    "mars surface", "planetary",
)
# Volcano/lava won 14s of redshift_0042 (pixabay_v144678). Geology videos
# (0047 lava-flow intent) must keep the path — pin + video_id only.
SCI_VOLCANO_MARKERS: tuple[str, ...] = (
    "volcano", "lava", "magma", "eruption",
)
VOLCANO_DENY_VIDEOS: frozenset[str] = frozenset({"redshift_0042"})


def is_sci_topic(*, category: str = "", intent_kind: str = "") -> bool:
    cat = (category or "").strip().lower()
    kind = (intent_kind or "").strip().lower()
    return cat in SCI_CATEGORIES or kind in SCI_INTENT_KINDS


def thematic_reject_reason(
    haystack: str,
    *,
    category: str = "",
    intent_kind: str = "",
    video_id: str = "",
) -> str | None:
    """Cheap string reject for sci B-roll. Returns reason or None.

    Light guardrail: only when the slot/plan is sci (ai/tech/lab/…). Drug/hose
    junk and known off-theme URL classes (darkroom, race-day) are dropped so
    mis-tagged stock cannot win quantum/lab picks.
    """
    cat = (category or "").strip().lower()
    kind = (intent_kind or "").strip().lower()
    if not is_sci_topic(category=cat, intent_kind=kind):
        return None
    blob = " ".join(haystack.split()).lower()
    if not blob:
        return None
    for marker in STOCK_JUNK_MARKERS:
        if marker in blob:
            return f"тематический отсев (junk): «{marker}»"
    for marker in SCI_OFFTHEME_MARKERS:
        if marker in blob:
            return f"sci off-theme: «{marker}»"
    space_topic = cat == "space" or kind == "space"
    if not space_topic:
        for marker in SCI_ROVER_MARKERS:
            if marker in blob:
                return f"sci off-theme rover: «{marker.strip()}»"
        for marker in SCI_NASA_ARCHIVE_MARKERS:
            if marker in blob:
                return f"sci off-theme nasa archive: «{marker}»"
        for marker in SCI_PLANETARY_MARKERS:
            if marker in blob:
                return f"sci off-theme planetary: «{marker}»"
    vid = str(video_id or "").strip()
    if vid in VOLCANO_DENY_VIDEOS:
        for marker in SCI_VOLCANO_MARKERS:
            if marker in blob:
                return f"sci off-theme volcano: «{marker}»"
    return None


def scrub_queries(queries: list[str]) -> list[str]:
    """Drop search strings that themselves ask for junk footage."""
    out: list[str] = []
    for q in queries:
        low = q.lower()
        if any(m in low for m in STOCK_JUNK_MARKERS):
            continue
        out.append(q)
    return out


def classify_intent(visual_intent: str, queries: Iterable[str], category: str = "") -> str:
    """К какому классу отнести слот — определяет приоритет источников (§7.2)."""
    haystack = " ".join([visual_intent, *queries]).lower()
    for kind, markers in INTENT_PATTERNS:
        if any(marker in haystack for marker in markers):
            return kind
    return CATEGORY_HINT.get(category, "default")


# Универсальный пад: пять запросов, которые подходят чему угодно и поэтому не
# подходят ничему. Ролик про квантовый чип честно получал галактику и студию
# новостей — отсюда и «пастельные кубики про LLM» в отзыве критика.
GENERIC_PAD_KINDS = frozenset({"space", "news"})


def allow_generic_pad(slot: dict[str, Any], plan: dict[str, Any] | None = None,
                      *, intent_kind: str = "", category: str = "") -> bool:
    """Можно ли доливать слот космосом и новостной студией (§9.1).

    Можно в двух случаях: слот **про это** (`space`/`news`), либо у слота нет
    ни одного предметного понятия — тогда общий кадр честнее пустоты. Во всех
    остальных случаях пад врёт про тему, и лучше короткая лестница запросов.

    Гейт один на оба места, где пад живёт: `build_queries` здесь и
    `pad_slot_queries` в P7. Раньше они расходились, и починка одного места
    ничего не меняла.
    """
    kind = intent_kind or classify_intent(
        str(slot.get("visual_intent") or ""), slot.get("queries") or [], category)
    if kind in GENERIC_PAD_KINDS:
        return True
    block = {}
    if plan:
        block = next((b for b in plan.get("blocks", [])
                      if b.get("id") == slot.get("block_id")), {})
    source_text = " ".join([
        str(slot.get("visual_intent") or ""),
        str(block.get("text") or ""),
        str(block.get("visual_intent") or ""),
        " ".join(str(q) for q in (slot.get("queries") or [])),
    ])
    # Предметных понятий нет — значит показывать нечего конкретного, и общий
    # кадр не спорит с речью.
    return not _concepts_from_text(source_text)


def _concepts_from_text(text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for trigger, options in CONCEPTS.items():
        if trigger in lowered:
            found.extend(options)
    return list(dict.fromkeys(found))


def topical_match_score(candidate_tags: set[str] | list[str], block_text: str,
                        category: str = "") -> float:
    """0..1: насколько материал про то, о чём сейчас звучит реплика (§9.2).

    Зрение отвечает на вопрос «что изображено» и отвечает честно: на 0042 оно
    написало бы «светящиеся фиолетовые сферы» — и было бы право. Отбраковать
    такой клип должен не критик качества, а тематический счёт: «относится ли
    изображённое к тому, что говорят».

    Счёт — доля попаданий тегов кандидата в понятия, которые даёт сама реплика.
    Понятия берутся из `CONCEPTS`, то есть из того же словаря, по которому
    строился запрос: если материал не пересекается с ним ни одним словом, он
    пришёл из общего пада или из чужого слота.
    """
    tags = {str(t).lower().strip() for t in (candidate_tags or []) if str(t).strip()}
    if not tags:
        return 0.0
    wanted = _concepts_from_text(str(block_text or ""))
    if not wanted:
        # Реплика без предметных понятий ничего не требует от кадра — и
        # штрафовать материал не за что.
        return 1.0
    words: set[str] = set()
    for phrase in wanted:
        words.update(w for w in phrase.lower().split() if len(w) > 2)
    if not words:
        return 1.0
    hits = sum(1 for tag in tags
               if any(w in tag or tag in w for w in words))
    return round(min(1.0, hits / max(1, min(len(tags), 4))), 3)


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

    # 5. Фактура как последний рубеж. Space/news padding lives in P7
    # ``pad_slot_queries`` and only fills a short ladder.
    out.append("abstract macro texture slow motion")

    seen: list[str] = []
    for query in scrub_queries(out):
        query = re.sub(r"\s+", " ", query).strip()
        if query and query.lower() not in {q.lower() for q in seen}:
            seen.append(query)
    return seen[:max(3, count)]
