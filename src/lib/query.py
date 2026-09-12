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
    "вод": ["flowing water slow motion", "river current aerial", "water vortex underwater"],
    "жидкост": ["liquid flow slow motion", "fluid dynamics visualization"],
    "крыл": ["airplane wing in flight", "aircraft wing over clouds"],
    "труб": ["industrial pipes valves", "factory pipework closeup"],
    "погод": ["weather radar storm screen", "satellite weather map"],
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
    "hook": ["abstract dark texture macro", "slow motion particles dark", "cracked wall texture"],
    "setup": ["technology abstract background", "macro texture technology", "chalkboard equations"],
    "evidence": ["documents on desk", "screen with data closeup", "news article screen", "newsroom broadcast desk"],
    "develop": ["abstract data particles", "geometric motion background", "code on screen"],
    "twist": ["dramatic dark abstract", "light through darkness", "cracked concrete texture"],
    "cta": ["abstract gradient motion", "minimal dark abstract background", "textured wall closeup"],
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
    "beaker", "red-liquid", "red liquid heating",
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
    "galaxy", "nebula", "messier", "/earth-", "video/earth",
    "/pluto-", "earth orbit",
)
# Volcano/lava is geology. AI/tech cuts must not win it; science may keep it.
SCI_VOLCANO_MARKERS: tuple[str, ...] = (
    "volcano", "lava", "magma", "eruption",
)
VOLCANO_DENY_CATEGORIES: frozenset[str] = frozenset({"ai", "tech"})


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
    if cat in VOLCANO_DENY_CATEGORIES:
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


QUERY_MIN = 3
QUERY_MAX = 5
TEXTURE_FILL = "abstract macro texture slow motion"
TEXTURE_FILL_ALT = "slow motion particles dark"
TEXTURE_WORDS = frozenset({"abstract", "texture", "particles", "gradient"})
# Слова, которые есть у любого стокового пада — по ним нельзя считать слот «про это».
WEAK_PAD_WORDS = frozenset({
    "abstract", "texture", "macro", "slow", "motion", "dark", "deep",
    "light", "background", "closeup", "wide", "shot", "view", "night",
    "particles", "gradient", "minimal", "red", "blue", "gold", "golden",
    "laboratory", "screen", "data", "earth",
})

# Именованные сущности канала: триггер в тексте блока/источника → EN-ярлык для стока.
ENTITY_TRIGGERS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("willow",), "Willow quantum chip"),
    (("кольск", "kola superdeep", "kola borehole"), "Kola Superdeep borehole"),
    (("поверхностн", "surface code"), "surface code lattice"),
    (("криостат", "cryostat", "dilution refrigerator"), "dilution refrigerator cryostat"),
    (("jwst", "james webb", "уэбб"), "James Webb Space Telescope"),
    (("hubble", "хаббл"), "Hubble Space Telescope"),
    (("crispr", "криспр"), "CRISPR gene editing"),
    (("cern", "церн", "lhc"), "CERN LHC accelerator"),
    (("iss", "мкс"), "International Space Station"),
)

# TitleCase from the block, not from source titles (OpenAI / GPT leak onto
# every slot that shares a word with openai.com).
_TITLE_ENTITY_STOP = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "processor",
    "announcement", "article", "video", "blog", "research", "technology",
    "scientific", "paper", "below", "into", "about",
    "openai", "gpt", "astra", "microsoft", "google", "anthropic", "meta",
    # Director notes / overlay labels. 0050 QC-24: TitleCase from visual_intent
    # prefixed stock search («One weather radar», «REDSHIFT city night»).
    "one", "dark", "russian", "html", "clay", "reject", "redshift",
    "latin", "cyrillic", "fluids", "stamp", "not", "then", "beat",
    "card", "thin", "collage", "sentence", "wordmark", "identity",
    "oblique", "particle", "plate", "paperwork", "close",
})


def _trigger_in_hay(trigger: str, hay: str) -> bool:
    """Substring match, but short ASCII tokens need a word boundary.

    ``iss`` in ``fissure`` used to stamp International Space Station onto
    cracked-wall slots and send NASA queries that return nothing.
    """
    token = (trigger or "").strip().lower()
    if not token:
        return False
    if token.isascii() and len(token) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", hay) is not None
    return token in hay


BASE_NEGATIVES: tuple[str, ...] = (
    "talking head",
    "watermark",
    "UI screenshot",
    "clickbait thumbnail",
    "html tutorial",
)
STOCK_SMILE_LAB = "stock smile lab"
MEDICINE_PROCEDURE_MARKERS = (
    "хирург", "операц", "процедур", "скальп", "инъекц",
    "surgery", "procedure", "incision", "injection", "scalpel",
)

NEGATIVE_ALIASES: dict[str, tuple[str, ...]] = {
    "talking head": ("talking head", "talking-head", "talkinghead"),
    "watermark": ("watermark", "shutterstock", "getty images"),
    "UI screenshot": ("ui screenshot", "app screenshot", "desktop screenshot"),
    "clickbait thumbnail": ("clickbait thumbnail", "clickbait", "youtube thumbnail"),
    "html tutorial": (
        "html tutorial", "hello world javascript", "hello js",
        "learn javascript", "html css tutorial", "coding tutorial beginner",
    ),
    "cracked wall": (
        "cracked wall", "cracked concrete", "peeling wall", "plaster wall",
        "cracked earth",
    ),
    "stock smile lab": (
        "stock smile lab", "stock smile", "smiling scientist",
        "smiling doctor", "happy lab team",
    ),
}


def _looks_english(text: str) -> bool:
    letters = re.findall(r"[a-zA-Zа-яА-ЯёЁ]", text)
    if not letters:
        return False
    latin = sum(1 for ch in letters if ch.isascii())
    return latin / len(letters) > 0.7


def _query_words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[a-zA-Zа-яА-ЯёЁ]{3,}", text or "")}


def _block_of(slot: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return next((b for b in plan.get("blocks", []) if b.get("id") == slot.get("block_id")), {})


def _block_text(slot: dict[str, Any], plan: dict[str, Any]) -> str:
    block = _block_of(slot, plan)
    return " ".join([
        str(slot.get("visual_intent") or ""),
        str(block.get("text") or ""),
        str(block.get("visual_intent") or ""),
        " ".join(str(q) for q in (slot.get("queries") or [])),
    ])


def _is_medicine_procedure(slot: dict[str, Any], plan: dict[str, Any]) -> bool:
    cat = str((plan or {}).get("category") or "").strip().lower()
    if cat != "medicine":
        return False
    blob = _block_text(slot, plan).lower()
    return any(m in blob for m in MEDICINE_PROCEDURE_MARKERS)


def slot_negatives(slot: dict[str, Any], plan: dict[str, Any] | None = None) -> list[str]:
    """Negatives на слот: talking head / watermark / UI / clickbait / stock smile."""
    out = list(BASE_NEGATIVES)
    if not _is_medicine_procedure(slot, plan or {}):
        out.append(STOCK_SMILE_LAB)
    video_id = str((plan or {}).get("video_id") or "")
    if video_id == "redshift_0050":
        out.append("cracked wall")
    return out


def negative_reject_reason(haystack: str, negatives: Iterable[str] | None = None) -> str | None:
    """Дешёвый отказ по negatives без vision. Phrase match по алиасам."""
    blob = " ".join((haystack or "").split()).lower()
    if not blob:
        return None
    for neg in negatives or ():
        aliases = NEGATIVE_ALIASES.get(neg, (neg,))
        for alias in aliases:
            token = alias.lower().strip()
            if token and token in blob:
                return f"negative «{neg}»"
    return None


def extra_fits_slot(extra: str, tokens: set[str]) -> bool:
    """Пад уместен только если делит сильные слова с сущностью/понятием блока."""
    if not extra:
        return False
    extra_words = {w for w in re.findall(r"[a-zA-Z]{3,}", extra.lower())} - WEAK_PAD_WORDS
    strong = {t.lower() for t in tokens} - WEAK_PAD_WORDS
    if not extra_words:
        return False
    if not strong:
        return False
    return bool(extra_words & strong)


def topical_tokens(slot: dict[str, Any], plan: dict[str, Any] | None = None,
                   queries: Iterable[str] | None = None) -> set[str]:
    """Слова, которыми пад обязан пересекаться, иначе это чужой кадр."""
    plan = plan or {}
    blob = _block_text(slot, plan)
    words = _query_words(blob)
    for phrase in _concepts_from_text(blob):
        words.update(_query_words(phrase))
    for ent in extract_entities(slot, plan):
        words.update(_query_words(ent))
    for query in queries or slot.get("queries") or []:
        if str(query).strip().lower() == TEXTURE_FILL:
            continue
        words.update(_query_words(str(query)))
    return {w for w in words if len(w) > 2}


def _source_haystacks(slot: dict[str, Any], plan: dict[str, Any],
                      concept_words: set[str]) -> list[str]:
    """Источники ролика — только если слот про них или делит с ними понятия."""
    block = _block_of(slot, plan)
    ref = str(block.get("source_ref") or "").strip().lower()
    out: list[str] = []
    for source in plan.get("sources") or []:
        title = str(source.get("title") or "")
        url = str(source.get("url") or "")
        domain = str(source.get("domain") or "")
        hay = " ".join([title, url, domain])
        low = hay.lower()
        if ref and ref in (domain.lower(), url.lower(), low):
            out.append(hay)
            continue
        src_words = {w for w in _query_words(hay) if w.isascii()}
        if concept_words and concept_words & src_words:
            out.append(hay)
    return out


def extract_entities(slot: dict[str, Any], plan: dict[str, Any] | None = None) -> list[str]:
    """Именованные сущности блока: прибор, миссия, метод — на английском."""
    plan = plan or {}
    blob = _block_text(slot, plan)
    concept_words = _query_words(" ".join(_concepts_from_text(blob)))
    parts = [blob, *(_source_haystacks(slot, plan, concept_words))]
    hay = " ".join(parts).lower()
    found: list[str] = []
    for triggers, label in ENTITY_TRIGGERS:
        if any(_trigger_in_hay(tr, hay) for tr in triggers):
            found.append(label)
    # TitleCase only from spoken text + author queries. visual_intent is
    # director copy («One beat», «CLAY: REJECT», «REDSHIFT Latin») and must
    # not become a stock prefix.
    block = _block_of(slot, plan)
    title_src = " ".join([
        str(block.get("text") or ""),
        " ".join(str(q) for q in (slot.get("queries") or [])),
    ])
    for token in re.findall(r"\b[A-Z][a-zA-Z0-9\-]{2,}\b", title_src):
        if token.lower() in _TITLE_ENTITY_STOP:
            continue
        if any(token.lower() in existing.lower() for existing in found):
            continue
        if token not in found:
            found.append(token)
    return list(dict.fromkeys(found))


def _clamp_query_count(count: int) -> int:
    return min(QUERY_MAX, max(QUERY_MIN, int(count or QUERY_MAX)))


def _dedupe_queries(items: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for query in scrub_queries(list(items)):
        query = re.sub(r"\s+", " ", query).strip()
        if query and query.lower() not in {q.lower() for q in seen}:
            seen.append(query)
    return seen


def compile_slot_search(slot: dict[str, Any], plan: dict[str, Any],
                        *, count: int = 4) -> dict[str, Any]:
    """Запросы + сущности + negatives одним словарём для P7 и отчёта."""
    return {
        "queries": build_queries(slot, plan, count=count),
        "entities": extract_entities(slot, plan),
        "negatives": slot_negatives(slot, plan),
    }


def search_report_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Стабильная форма `build_report.search`: queries/entities/negatives по слоту."""
    queries: dict[str, list[str]] = {}
    entities: dict[str, list[str]] = {}
    negatives: dict[str, list[str]] = {}
    for entry in entries:
        key = str(entry.get("slot_index"))
        queries[key] = list(entry.get("queries") or [])
        entities[key] = list(entry.get("entities") or [])
        negatives[key] = list(entry.get("negatives") or [])
    return {"queries": queries, "entities": entities, "negatives": negatives}


def build_queries(slot: dict[str, Any], plan: dict[str, Any], *, count: int = 4) -> list[str]:
    """3–5 EN-запросов: сущности блока + 1–2 визуальных якоря, без чужого пада."""
    limit = _clamp_query_count(count)
    entities = extract_entities(slot, plan)
    source_text = _block_text(slot, plan)
    concepts = _concepts_from_text(source_text)
    tokens = topical_tokens(slot, plan)
    author_en = [q.strip() for q in (slot.get("queries") or []) if _looks_english(q)]
    author_tokens = _query_words(" ".join(author_en))
    anchors = list(author_en[:2]) or list(concepts[:2])

    out: list[str] = []
    # Author phrases first so entity prefixes cannot spend the per-slot
    # download budget on «One weather radar» / «Lean rubber stamp».
    out.extend(author_en)
    for ent in entities:
        if str(ent).lower() in _TITLE_ENTITY_STOP:
            continue
        if author_en and not extra_fits_slot(str(ent), author_tokens):
            continue
        if anchors:
            anchor = anchors[0]
            if ent.lower() not in anchor.lower():
                out.append(f"{ent} {anchor}")
            else:
                out.append(anchor)
        else:
            out.append(ent)
        if len(entities) > 1 and len(anchors) > 1:
            second = anchors[1]
            if ent.lower() not in second.lower():
                out.append(f"{ent} {second}")

    out.extend(concepts)
    for query in slot.get("queries") or []:
        if not _looks_english(query):
            out.extend(_concepts_from_text(query))

    video_id = str(plan.get("video_id") or "")
    skip_cracked = video_id == "redshift_0050"
    for metaphor in ROLE_METAPHORS.get(slot.get("role", ""), []):
        low = metaphor.lower()
        if skip_cracked and ("cracked" in low or " wall" in f" {low}"):
            continue
        if extra_fits_slot(metaphor, tokens):
            out.append(metaphor)

    out.append(TEXTURE_FILL)
    seen = _dedupe_queries(out)

    def _carries_entity(query: str) -> bool:
        low = query.lower()
        return any(ent.lower() in low for ent in entities)

    if entities and seen and not any(_carries_entity(q) for q in seen[:limit]):
        lead = next(
            (ent for ent in entities
             if str(ent).lower() not in _TITLE_ENTITY_STOP
             and extra_fits_slot(str(ent), author_tokens or tokens)),
            None,
        )
        if lead:
            seen = _dedupe_queries([lead, *seen])
    if len(seen) < QUERY_MIN:
        seen = _dedupe_queries([*seen, TEXTURE_FILL, TEXTURE_FILL_ALT])
    return seen[:limit]
