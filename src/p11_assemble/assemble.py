"""P11: всё предыдущее → ``edit_plan_A.json`` и ``edit_plan_B.json``.

Edit-план — самодостаточный документ: §9.1 требует, чтобы по нему можно было
**пересобрать ролик один в один без обращений к внешним API**. Поэтому в нём
лежат локальные пути подготовленных планов, все параметры анимации, тексты
оверлеев и пословные тайминги — ничего не догружается на рендере.

Версии A и B (§4.5) собираются из **одного набора материалов** и различаются
монтажными решениями: порядком вставок внутри блока, шаблонами Ken Burns и
переходов, оформлением полноэкранного текста, наличием мема. §15.12.2 требует
различия минимум в 3 шаблонных позициях, и это проверяется, а не декларируется.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable

from ..errors import RedshiftError
from ..lib.ffmpeg import probe
from ..lib.logging import get_logger
from ..lib.render.layers import Ctx, text_behind_head
from ..lib.render.matting import assess_matte, plan_vfx_backgrounds, try_local_matting
from ..lib.render.shots import (
    ShotSpec, choose_fit, detect_focus, prepare_avatar_shot, prepare_shot,
    prepare_split_shot,
)
from ..lib.render.text_rules import glue_short_cues
from ..lib.backdrop import plate_name as _scene_plate_name
from ..lib.brand_icons import load_library as load_brand_icons
from ..lib.backdrop import describe as scene_why
from ..lib.backdrop import pick_scene
from ..lib.backdrop import tone as scene_tone
from ..lib.text import (
    accent_card_start, enrich_overlay_punch, find_spoken_anchor,
)
from ..lib.glyphs import match_glyphs
from ..lib.meaning import block_traits, explain, matched
from ..lib.render.hyperframes.captions import pick_caption_style
from ..lib.render.hyperframes.spm_shapes import SPM_SHAPES
from ..lib.render.hyperframes.umf_shapes import UMF_CITIES, UMF_FLOWS
from ..lib.render.hyperframes.usm_shapes import USM_SHAPES
from ..lib.templates import TemplateCatalog, Template, diff_count
from ..lib.template_picker import ScenarioIndex, TemplatePicker, build_blob

_log = get_logger("p11")


def _load_yaml(path) -> dict:
    """Каталог источников как есть. Отсутствие файла — не повод падать."""
    import yaml

    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}

AVATAR_KINDS = ("avatar", "split")


# --- приёмы вокруг ведущего (§5.3, референсы заказчика) ------------------------

# Надпись над крупным словом заголовка. Роль блока сюда подставлять нельзя: она
# служебная и латиницей — «EVIDENCE» посреди русского ролика читается как
# отладочный вывод. Роль без подписи остаётся без кикера, и приём собирается
# из одного слова.
_HERO_KICKERS = {
    "hook": "ВОПРОС",
    "setup": "С ЧЕГО НАЧАЛОСЬ",
    "evidence": "ЧТО ИЗВЕСТНО",
    "develop": "ЧТО ДАЛЬШЕ",
    "twist": "НО ЕСТЬ НЮАНС",
    "cta": "ОСТАЁТСЯ ВОПРОС",
}


# Catalog demo strings that must never reach a live cut when shot.content exists.
_FS_DEMO_WORDS = frozenset({
    "FLIGHT", "BREAKING", "BREAKING NEWS", "BREAKING NEWS: SOMETHING HAPPENED",
    "SOMETHING HAPPENED", "HELLO", "WORLD", "LOREM", "IPSUM",
})

# Discourse openers that are not the "big word" meaning of the block.
_DISCOURSE_PREFIX = re.compile(
    r"^(?:и\s+вот\s+ответ(?:\s+на(?:\s+вопрос)?)?[.!?]?\s*"
    r"|вот\s+ответ(?:\s+на(?:\s+вопрос)?)?[.!?]?\s*"
    r"|и\s+тут\s+срабатывает[^.]*[.!?]?\s*)",
    re.IGNORECASE,
)


def _strip_discourse(text: str) -> str:
    """Drop 'и вот ответ…' style openers so cards show the real meaning."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    cleaned = _DISCOURSE_PREFIX.sub("", raw).strip(" ,.;:—-")
    return cleaned or raw


def _semantic_screen_text(block: dict[str, Any], *, fallback: str = "") -> str:
    """Author-intent screen phrase: overlay punch → emphasis window → body."""
    overlay = block.get("overlay") or {}
    otype = str(overlay.get("type") or "")
    ocontent = str(overlay.get("content") or "").strip()
    if otype == "fullscreen_text" and ocontent:
        return ocontent
    if otype in ("lower_third", "plaque", "note") and ocontent:
        return ocontent
    punch = _punch(block)
    if punch:
        return " ".join(punch)
    emphasis = str(block.get("emphasis_word") or "").strip()
    body = _strip_discourse(str(block.get("text") or fallback or ""))
    if emphasis and body:
        words = body.split()
        hit = next((i for i, w in enumerate(words)
                    if emphasis.lower() in w.lower()), None)
        if hit is not None:
            lo = max(0, hit - 1)
            hi = min(len(words), hit + 2)
            return " ".join(words[lo:hi])
    return body


def _rich_terminal_copy(block: dict[str, Any], phrase: str) -> tuple[str, str, str]:
    """Многострочный «терминальный» сниппет вместо одной короткой фразы.

    code_diff / code_morph / code_highlight с ``code: "5 МИНУТ"`` оставляют
    пустое окно greet.js. Собираем before/after из фактов блока + punch.
    """
    body = _strip_discourse(str(block.get("text") or ""))
    emphasis = str(block.get("emphasis_word") or "").strip()
    punch = _norm_screen_key(phrase) or _norm_screen_key(
        _semantic_screen_text(block))
    nums = re.findall(r"\d+(?:[.,]\d+)?(?:\s*%|\s*кубит\w*)?", body, flags=re.I)
    facts: list[str] = []
    if nums:
        facts.append(f"qubits: {nums[0].replace(' ', '')}")
    if "ошиб" in body.lower() or "вдвое" in body.lower():
        facts.append("error_rate: /2 per step")
    if punch:
        facts.append(f"runtime: {punch.lower()}")
    if "вселенн" in body.lower() or "суперкомпьютер" in body.lower():
        facts.append("classical_eta: > universe_age")
    if emphasis:
        facts.append(f"signal: {emphasis}")
    if not facts:
        facts = [f"note: {punch or 'ok'}", "status: verified"]
    # Keep 4–6 lines so the window has substance.
    while len(facts) < 4:
        facts.append(f"trace[{len(facts)}]: ok")
    before = "\n".join([
        "# willow_check",
        "load surface_code",
        *facts[:3],
        "status: pending",
    ])
    after = "\n".join([
        "# willow_check",
        "load surface_code",
        *facts[:4],
        "status: PASS",
    ])
    return before, after, "willow_run.log"


def _fullscreen_params(template: Any, content: str,
                       block: dict[str, Any] | None = None) -> dict[str, Any]:
    """Template catalog params + live shot content; never leave demo copy.

    Catalog JSON ships demo ``word``/``text`` (FLIGHT, BREAKING NEWS). Assemble
    used to copy those into the edit plan unchanged while ``content`` sat unused
    for renderers that read params.word/text. Fill from the spoken phrase and
    drop known demos. Tone ``ink`` on dark plates becomes ``paper``-safe by
    forcing invert so glyphs stay light over footage.
    """
    params = dict(getattr(template, "params", None) or {})
    phrase = str(content or "").strip()
    block = block or {}
    if not phrase:
        phrase = _semantic_screen_text(block)
    phrase = phrase.strip()
    params["content"] = phrase

    # Override catalog demo word/text with semantic content.
    demo_word = str(params.get("word") or "").strip()
    if (not demo_word) or demo_word.upper() in _FS_DEMO_WORDS or demo_word.upper() == "FLIGHT":
        # Prefer emphasis / short token from phrase for flap boards.
        emphasis = str(block.get("emphasis_word") or "").strip()
        seed = emphasis.strip() if emphasis else (
            phrase.split()[0] if phrase.split() else "")
        token = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "", seed)
        if token:
            params["word"] = token.upper()[:8]
        else:
            params.pop("word", None)

    demo_text = str(params.get("text") or "").strip()
    if (not demo_text) or demo_text.upper() in _FS_DEMO_WORDS or "BREAKING" in demo_text.upper():
        if phrase:
            params["text"] = phrase
        else:
            params.pop("text", None)

    # Code templates without real code must not invent greet.js demos: feed
    # multi-line terminal facts when the on-screen punch is a short slogan
    # («5 МИНУТ»), else the phrase itself. Empty → Piece().
    if (params.get("code_diff") or params.get("code_highlight")
            or params.get("code") or params.get("code_morph")):
        has_shaped = any(params.get(k) for k in (
            "code_before", "code_after", "code", "before", "after"))
        if not has_shaped:
            if phrase and len(phrase.split()) <= 4:
                before, after, filename = _rich_terminal_copy(block, phrase)
                params["code_before"] = before
                params["code_after"] = after
                params["code"] = f"{before}\n---\n{after}"
                params["filename"] = filename
                params["text"] = after
            elif phrase:
                params["code"] = phrase
            else:
                params.pop("code_diff", None)
                params.pop("code_highlight", None)
                params.pop("code_morph", None)
        elif phrase and len(str(params.get("code") or "").split()) <= 4:
            # Catalog/params already set a short slogan as code — enrich it.
            before, after, filename = _rich_terminal_copy(block, phrase)
            params["code_before"] = before
            params["code_after"] = after
            params["code"] = f"{before}\n---\n{after}"
            params["filename"] = filename

    # Dark-plate readability: catalog tone=ink means black glyphs in some
    # templates; over footage we want light. Invert covers the common path.
    tone = str(params.get("tone") or "").lower()
    if tone == "ink":
        params["tone"] = "accent"  # brand red/light-safe on dark; not black
    return params



def _alpha_slots(avatar_meta: dict[str, Any]) -> set[int]:
    """Слоты, где аватар лёг с прозрачным фоном."""
    return {int(idx) for seg in avatar_meta.get("segments", [])
            if seg.get("has_alpha")
            for idx in seg.get("slot_indices", [])}


def _backdrop_plate(cfg, scene: str) -> str:
    """Путь к плите сцены — или пусто, если её нет на диске.

    Проверка существования не формальность: имя плиты записано в
    :mod:`src.lib.backdrop`, а сам файл живёт в ассетах, и разъехаться они
    могут. Пустая строка честнее ссылки в никуда — сцена нарисуется
    градиентами, как и задумано запасным путём.
    """
    name = _scene_plate_name(scene)
    if not name:
        return ""
    path = cfg.path("paths.assets_dir", "assets") / "backdrops" / name
    return str(path) if path.exists() else ""


def _head_boxes(avatar_meta: dict[str, Any]) -> dict[int, tuple[int, int, int, int]]:
    """Слот шота → коробка головы в кадре.

    Приёмам, которые стоят **за** головой, нужен не центр, а макушка: от неё
    считается, насколько голова перекроет низ строки.
    """
    out: dict[int, tuple[int, int, int, int]] = {}
    for seg in avatar_meta.get("segments", []):
        box = seg.get("face_bbox")
        if not box or len(box) != 4:
            continue
        for slot in seg.get("slot_indices", []):
            out[int(slot)] = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
    return out


def _face_centres(avatar_meta: dict[str, Any]) -> dict[int, tuple[int, int]]:
    """Слот шота → центр лица в кадре.

    Круглая рамка обязана сесть на голову, а не туда, где она в среднем бывает:
    догадка «четверть высоты кадра» промахивалась на сотню пикселей. P6 уже
    измерил лицо для сдвига субтитров — берём оттуда же.
    """
    out: dict[int, tuple[int, int]] = {}
    for seg in avatar_meta.get("segments", []):
        box = seg.get("face_bbox")
        if not box or len(box) != 4:
            continue
        centre = ((int(box[0]) + int(box[2])) // 2, (int(box[1]) + int(box[3])) // 2)
        for slot in seg.get("slot_indices", []):
            out[int(slot)] = centre
    return out


def _plate_source(slot: dict[str, Any], slots: list[dict[str, Any]],
                  prepared: dict[int, dict[str, Any]],
                  assets: dict[int, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Nearest real (non-AI) footage for hero/fullscreen plates.

    Prefer same-block stock/press; if that block has no real media (empty P7/P9
    gaps), fall back to the nearest real prepared footage anywhere in the cut
    so plate-needing heroes still show NASA/news instead of an empty panel.
    AI-only pools return None — heroes then skip plate templates.
    """
    index = int(slot["index"])
    assets = assets or {}

    def _is_ai(s: dict[str, Any]) -> bool:
        return bool((assets.get(int(s["index"])) or {}).get("ai_generated"))

    def _pool(same_block_only: bool) -> list[dict[str, Any]]:
        out = []
        for s in slots:
            if s["kind"] not in ("footage", "meme"):
                continue
            if int(s["index"]) not in prepared:
                continue
            if same_block_only and s["block_id"] != slot["block_id"]:
                continue
            if _is_ai(s):
                continue
            out.append(s)
        return out

    pool = _pool(True) or _pool(False)
    if not pool:
        return None
    nearest = min(pool, key=lambda s: (abs(int(s["index"]) - index), int(s["index"])))
    prep = prepared[int(nearest["index"])]
    # Credit travels with the plate asset so exhibit/BL caption name the frame shown.
    asset = assets.get(int(nearest["index"])) or {}
    credit = str(asset.get("attribution") or asset.get("source") or "").strip()
    return {"file": prep["dst"], "duration_sec": float(prep.get("duration_sec") or 0.0),
            "credit": credit, "ai_generated": bool(asset.get("ai_generated"))}


# Что приёму нужно на входе. Без этого он рисует пустоту поверх ведущего, и
# отсеивать его надо **до** выбора: ``TemplateCatalog.pick`` при пустом наборе
# кандидатов возвращается ко всей категории, и неподходящий приём всё равно
# попал бы в кадр. Список ведётся здесь, а не тегами в каталоге: тег описывает,
# на что приём похож, а это — чем его кормить.
_HERO_NEEDS: dict[str, tuple[str, ...]] = {
    "hero-icons": ("icons",),
    "hero-plate": ("plate",),
    "hero-headline": ("word",),
    "hero-split": ("word",),
    "hero-knockout": ("word",),
    "hero-text-column": ("lines",),
    "hero-bubble-card": ("lines",),
    "hero-brand-pill": ("brand",),
    "hero-card-stack": ("title", "plate"),
    "hero-phone-mock": ("lines",),
    "hero-type-slab": ("lines",),
    "hero-plate-pop": ("plate",),
    "hero-script-stack": ("lines",),
    "hero-chat-typing": ("ask",),
    "hero-chat-generate": ("gen_prompt", "plate"),
    "hero-title-behind": ("head", "tail"),
    "hero-exhibit": ("plate", "title"),
    "hero-slam": ("punch",),
    "hero-log": ("entries",),
    "hero-oversize": ("word",),
    "hero-figure": ("figures",),
    "hero-verdict": ("punch",),
    "hero-paper": ("source", "quote"),
    "hero-bubble-typed": ("entries",),
}


def _wrap_lines(text: str, *, width: int = 13, limit: int = 4) -> list[str]:
    """Реплику блока — в короткие строки для колонки и карточки.

    Перенос по словам и с потолком по длине: колонка занимает 46 % ширины
    кадра, и на кегле 66 в неё входит около 13 знаков. Проверено кадром — при
    20 знаках каждая строка ломалась пополам, и колонка превращалась в кашу.
    Перенос посреди слова читается как брак вёрстки, поэтому только по словам.
    """
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
            if len(lines) == limit:
                break
        else:
            current = candidate
    if current and len(lines) < limit:
        lines.append(current)
    return lines


def _sentence(text: str, index: int, *, limit: int) -> str:
    """Фраза по счёту, ужатая до ``limit`` слов."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()]
    if index >= len(parts):
        return ""
    return " ".join(parts[index].split()[:limit]).strip(".,!?;:")


def _avatar_bg_plates(slots: list[dict[str, Any]],
                       prepared: dict[int, dict[str, Any]],
                       assets: dict[int, dict[str, Any]]) -> dict[int, str]:
    """Real (non-AI) footage paths for alpha talking-head backgrounds.

    HyperFrames alpha avatars used a single static scene plate for the whole
    cut — background never changed. Round-robin distinct prepared plates so
    each avatar beat gets interesting B-roll behind the transparent subject.
    """
    plates: list[str] = []
    seen: set[str] = set()
    for slot in slots:
        idx = int(slot["index"])
        asset = assets.get(idx) or {}
        prep = prepared.get(idx) or {}
        if asset.get("ai_generated"):
            continue
        path = str(prep.get("dst") or "").strip()
        if not path or path in seen:
            continue
        if slot.get("kind") not in ("footage", "meme", "fullscreen_text"):
            # Prefer footage/meme/fullscreen plates; skip baked avatar composites.
            if slot.get("kind") in ("avatar", "split"):
                continue
        seen.add(path)
        plates.append(path)
    if not plates:
        # Fall back to any non-AI prepared file (borrowed plate path).
        for slot in slots:
            plate = _plate_source(slot, slots, prepared, assets)
            path = str((plate or {}).get("file") or "").strip()
            if path and path not in seen:
                seen.add(path)
                plates.append(path)
    out: dict[int, str] = {}
    if not plates:
        return out
    cursor = 0
    for slot in slots:
        if slot.get("kind") != "avatar":
            continue
        out[int(slot["index"])] = plates[cursor % len(plates)]
        cursor += 1
    return out


def _caption(text: str, *, limit: int = 8) -> str:
    """Подпись под экспонатом — целая фраза, а не первые ``limit`` слов.

    Обрезка по счёту слов давала обрывок: на 0047 под материалом стояло
    «Скважину закрыли в девяносто втором, и сегодня это» — подпись обрывалась
    на «это». В музейной табличке это читается как сбой набора, а не как
    подпись. То же правило уже записано у плашки-удара (см. ``ask``).

    Не влезла фраза целиком — берётся её первая часть до запятой или тире,
    если та сама по себе законченная. Не влезла и она — подписи не будет:
    приём покажет имя и кредит, а выдумывать текст неоткуда.
    """
    first = _sentence(text, 0, limit=10_000)
    if not first:
        return ""
    if len(first.split()) <= limit:
        return first
    for part in re.split(r"[,—–:;]", first):
        words = part.split()
        if 3 <= len(words) <= limit:
            return " ".join(words).strip(".,!?;: ")
    return ""


def _question(text: str, *, limit: int = 8) -> str:
    """Фраза-вопрос из реплики. Пусто, если блок ни о чём не спрашивает.

    Приём с перепиской показывает запрос в поисковом окне. Он собирался из
    первой фразы **любого** блока, и окно всплывало там, где никто ничего не
    спрашивал. Заказчик просил ставить его по смыслу: окно уместно там, где в
    кадре и правда вопрос.

    Признак — знак вопроса, и только он. Первая версия добавляла к нему список
    вопросительных слов в начале фразы, чтобы поймать вопрос без знака. На
    шести сценариях репозитория список не поймал ни одного лишнего вопроса, но
    выдумал один: «Когда звезда умирала, она раздувалась…» — здесь «когда»
    значит «в то время как», а не «в какой момент». Знак вопроса нашёл все
    шесть настоящих вопросов и ни одного ложного.

    Ищется по всем фразам блока, а не только по первой: реплика часто подводит
    к вопросу и задаёт его в конце — «Куда, по-твоему, копать дальше?».
    """
    for part in (p.strip() for p in re.split(r"(?<=[.!?…])\s+", text)):
        if "?" in part:
            return " ".join(part.split()[:limit]).strip(".,!?;:")
    return ""


# Слова, по которым видно, что реплика про генерацию, а не про что угодно.
# Список короткий и предметный: «модель» сюда не входит — в науке это модель
# Вселенной куда чаще, чем модель нейросети, и окно генерации всплыло бы в
# ролике про чёрные дыры. Ровно так уже промахнулся список вопросительных слов
# для окна переписки.
_GEN_MARKERS = re.compile(
    r"(нейросет|нейронк|сгенерир|генерир|генерац|промпт|prompt|chatgpt|"
    r"midjourney|dall|sora|stable diffusion|диффузионн|искусственн\w+ интеллект|"
    r"\bии\b|\bai\b|\bgpt\b)", re.IGNORECASE)


def _gen_prompt(block: dict[str, Any], *, limit: int = 7) -> str:
    """Короткий промпт для окна генерации — или пусто, если блок не про неё.

    Заказчик просил показывать генерацию там, где о ней и речь: «новость про
    искусственный интеллект, как будто делаешь короткий запрос, и там окно
    генерации или уже сгенерированная картинка». Значит, приём включает не
    длина реплики, а её предмет.

    Промпт берётся клаузой с акцентным словом, а не первыми словами блока:
    обрывок, начатый с середины чужой мысли, читается как сбой набора. Строчные
    буквы — так и печатают в поле запроса; заглавная тут выдала бы заголовок.
    """
    text = str(block.get("text") or "").strip()
    if not text or not _GEN_MARKERS.search(text):
        return ""
    clause = _accent_clause(block) or text
    return " ".join(clause.split()[:limit]).strip(".,!?;:").lower()


def _accent_clause(block: dict[str, Any]) -> str:
    """Клауза реплики с акцентным словом — или первая, если его нет.

    Клауза — то, что между запятыми, тире и двоеточиями: окно, перешагнувшее
    такую границу, начинается с середины чужой мысли.
    """
    text = str(block.get("text") or "").strip()
    word = str(block.get("emphasis_word") or "").strip()
    clauses = [c.strip(" —–-") for c in re.split(r"[,;:—–]|(?<=[.!?])\s+", text) if c.strip()]
    return next((c for c in clauses if word and word.lower() in c.lower()),
                clauses[0] if clauses else "")


def _punch(block: dict[str, Any]) -> list[str]:
    """Фраза для плашки-удара: две короткие строки, акцент — во второй.

    Если автор сценария сам написал полноэкранную строку для этого блока —
    берём её: она короткая по определению. Иначе режем окно, кончающееся
    акцентным словом, и не длиннее клаузы: плашка живёт полторы секунды и
    закрывает кадр целиком, за это время читаются две строки, а не фраза.
    """
    overlay = block.get("overlay") or {}
    if overlay.get("type") == "fullscreen_text" and str(overlay.get("content") or "").strip():
        return _wrap_lines(str(overlay["content"]).strip(), width=13, limit=2)

    word = str(block.get("emphasis_word") or "").strip()
    words = [w for w in _accent_clause(block).split() if w]
    if not words:
        return []
    end = next((i + 1 for i, w in enumerate(words) if word and word.lower() in w.lower()),
               len(words))
    window = words[max(0, end - 4):end]
    return _wrap_lines(" ".join(window).strip(".,!?;:"), width=13, limit=2)


# Служебные слова в конце подписи читаются как обрыв: «кубитов почти».
_FILLER = {"и", "а", "но", "то", "уже", "ещё", "еще", "это", "как", "же",
           "в", "на", "за", "по", "из", "с", "к", "у", "о", "от", "до",
           "почти", "просто", "всего", "лишь", "даже", "тоже", "опять"}


def _trim_filler(words: list[str]) -> str:
    tail = list(words)
    while tail and tail[-1].lower() in _FILLER:
        tail.pop()
    return " ".join(tail)


_NUMBER = re.compile(
    r"(?:[$₽]\s?)?\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?\s*"
    r"(?:%|₽|\$|тыс\.?|млн|млрд)?")


def _figures(text: str) -> list[dict[str, Any]]:
    """Числа реплики с короткой подписью под каждым.

    Приём сравнивает значения, поэтому подпись у них общая по смыслу: берём
    слова, идущие следом за числом. Если число замыкает фразу — берём то, что
    стоит перед ним: «получает Google» и «84 года» одинаково подписаны словом
    рядом, а не пересказом всей реплики.
    """
    words = text.split()
    out: list[dict[str, Any]] = []
    for i, word in enumerate(words):
        match = _NUMBER.fullmatch(word.strip(".,!?;:()»«"))
        if not match or not any(ch.isdigit() for ch in word):
            continue
        after = [w.strip(".,!?;:") for w in words[i + 1:i + 3]]
        before = [w.strip(".,!?;:") for w in words[max(0, i - 2):i]]
        note = _trim_filler(after) or _trim_filler(before)
        out.append({"value": match.group(0).strip(), "note": note})
        if len(out) >= 3:
            break
    return out


def _log_entries(words: list[dict[str, Any]], start: float) -> list[dict[str, Any]]:
    """Куски реплики с отметкой, когда каждый произносится.

    Приём «список копится» держится на совпадении с речью: кусок обязан
    появиться на своём слове, а не через ровный интервал. Границы — знаки
    препинания, потолок в четыре слова — чтобы кусок читался за раз.
    """
    chunk: list[str] = []
    out: list[dict[str, Any]] = []
    at = 0.0
    for word in words:
        if not chunk:
            at = max(0.0, float(word["start"]) - start)
        chunk.append(str(word["display"]))
        closed = str(word["display"]).rstrip().endswith((",", ".", "!", "?", ":", ";", "—"))
        if closed or len(chunk) >= 4:
            out.append({"text": " ".join(chunk), "at": round(at, 3)})
            chunk = []
    if chunk:
        out.append({"text": " ".join(chunk), "at": round(at, 3)})
    # Кусок из одной пунктуации — «—» отдельной строкой — читается как сбой
    # вёрстки. Тире закрывает кусок так же, как запятая, и когда оно стоит
    # отдельным словом, кусок из него одного и получается. Такой кусок
    # прирастает к предыдущему, а первым — просто выбрасывается.
    merged: list[dict[str, Any]] = []
    for entry in out:
        if any(ch.isalnum() for ch in entry["text"]):
            merged.append(entry)
        elif merged:
            merged[-1]["text"] = f'{merged[-1]["text"]} {entry["text"]}'
    out = merged[:5]
    # Последний кусок обрывается там, где кончился кадр, — и часто это предлог:
    # «ошибка падает вдвое на». В списке это читается как брак, а в набираемой
    # карточке последний кусок ещё и выделен акцентом. Служебный хвост
    # срезается; если от куска ничего не осталось, он выбрасывается целиком.
    if out:
        tail = _trim_filler(out[-1]["text"].split())
        if tail:
            out[-1]["text"] = tail
        elif len(out) > 1:
            out.pop()
    return out


_URL_HOST = re.compile(r"https?://([^/\s]+)")


def _source_site(block: dict[str, Any]) -> str:
    """Что написать в адресной строке страницы первоисточника.

    Из ссылки берётся хост, всё остальное показывается как есть. Достраивать
    домен по имени («Nature» → nature.org») нельзя: это уже не ссылка автора,
    а выдумка сборки под видом источника.
    """
    ref = str(block.get("source_ref") or "").strip()
    if not ref:
        return ""
    found = _URL_HOST.search(ref)
    if found:
        return found.group(1).lower().removeprefix("www.")
    return ref


def _quote(block: dict[str, Any]) -> str:
    """Строка, которую страница подсвечивает маркером.

    Первым делом — то, что автор сценария сам пометил как цитату из источника
    (``overlay.highlight``): это единственный текст в сценарии, про который
    известно, что он взят из статьи. Своей реплики хватает на замену, но
    маркер по ней — уже пересказ, а не цитата, поэтому она идёт второй.
    """
    overlay = block.get("overlay") or {}
    if overlay.get("type") == "highlight" and str(overlay.get("content") or "").strip():
        return str(overlay["content"]).strip()
    return _accent_clause(block)


def _stem(word: str) -> str:
    """Начало слова, по которому сравниваются формы одного корня.

    Акцентное слово блока стоит в падеже реплики, а в полноэкранной фразе — в
    своём: «воду» против «ВОДА». Сравнение целиком их не сводит, а полноценная
    морфология здесь не нужна — достаточно общего начала. Длина растёт вместе
    со словом: у короткого остаётся три буквы, у длинного почти всё.

    Сравниваются начала целиком, а не «одно начинается с другого»: при
    сравнении с вложением пятибуквенный «порыв» сжимался до «пор» и совпадал
    с «породой». Равенство начал такого не допускает.
    """
    bare = word.strip(".,!?;:«»\"'—–").lower().replace("ё", "е")
    return bare[:max(3, len(bare) - 2)]


def _credit_line(asset: dict[str, Any], sources: dict[str, Any]) -> str:
    """Small bottom-left source line for real photo/video (not AI).

    Show domain/source for all non-AI stock and press so viewers see where the
    frame came from. ``attribution_required`` sources still prefer the formal
    attribution string; others fall back to attribution, domain, or source id.
    Empty string = no caption. Generated assets never get a credit.
    """
    if not asset or asset.get("ai_generated"):
        return ""
    source = str(asset.get("source") or "").strip()
    if not source and not asset.get("attribution"):
        return ""
    # ``sources`` kept for callers / future license hooks; name resolution below.
    _ = (sources.get("sources") or {}).get(source) or {}
    name = str(asset.get("attribution") or "").strip()
    meta = asset.get("meta") or {}
    domain = str(meta.get("domain") or "").strip()
    if name and domain and domain.lower() not in name.lower():
        return f"{name} · {domain}"
    return name or domain or source


def _fullscreen_accent(content: str, block: dict[str, Any]) -> str | None:
    """Какое слово в полноэкранной фразе горит красным.

    Красным выделяется одно слово, а не строка (§3.3.2), и выбирать его наугад
    нельзя: акцент — это то, ради чего кадр и появился. Поэтому берётся
    акцентное слово блока, если оно в этой фразе есть; иначе — число, потому
    что фраза с числом всегда про число; иначе — самое длинное слово, самое
    содержательное из оставшихся.

    ``None`` только для фразы из одного слова: там выделять нечего, всё и так
    выделено размером.
    """
    words = [w for w in content.split() if w.strip(".,!?;:«»\"'—–")]
    if len(words) < 2:
        return None
    emphasis = _stem(str(block.get("emphasis_word") or ""))
    if emphasis:
        for word in words:
            bare = word.strip(".,!?;:«»\"'—–")
            if _stem(bare) == emphasis:
                return bare
    digits = [w.strip(".,!?;:«»\"'—–") for w in words
              if any(ch.isdigit() for ch in w)]
    if digits:
        return digits[0]
    return max((w.strip(".,!?;:«»\"'—–") for w in words), key=len)


def _hero_content(block: dict[str, Any], slot: dict[str, Any], icons,
                  face: tuple[int, int] | None = None,
                  title: str = "",
                  words: list[dict[str, Any]] | None = None,
                  head_box: tuple[int, int, int, int] | None = None) -> dict[str, Any]:
    """Собрать всё, чем можно накормить приёмы, из одного блока сценария."""
    text = str(block.get("text") or "").strip()
    word = str(block.get("emphasis_word") or "").strip()
    # Big-word lines must carry speech meaning, not discourse openers like
    # «И вот ответ на вопрос» — Markus QA: answer card showed only that kicker.
    role = str(slot.get("role") or "")
    text_for_lines = text
    if block.get("answers_hook") or role in ("twist", "cta"):
        semantic = _semantic_screen_text(block, fallback=text)
        text_for_lines = semantic or _strip_discourse(text) or text
    else:
        text_for_lines = _strip_discourse(text) if _DISCOURSE_PREFIX.match(text) else text
    lines = _wrap_lines(text_for_lines)
    accent = [i for i, line in enumerate(lines)
              if word and word.lower() in line.lower()]

    # Знак бренда ищет сама библиотека: она знает и русские написания, и
    # падежи. Перебор слов реплики, который стоял здесь, сверял «Гугла» со
    # слагом ``google`` и не находил ничего — за весь прогон 0047 в кадр не
    # попал ни один логотип при библиотеке в сотню знаков.
    brand = None
    if icons is not None:
        match = icons.match_text(text)
        if match:
            brand = {"label": match.brand, "icon": match.path}

    # Двухстрочная тема за головой: первая строка — подлежащее реплики, вторая
    # — то, что с ним происходит, и она же берёт акцент. Делим по акцентному
    # слову, если оно есть: на нём и держится смысл фразы.
    # Не ``words``: так зовётся параметр с таймингами кадра, и локальный
    # список слов текста затенял бы его — список копился бы по буквам.
    text_words = [w for w in text.split() if w]
    # За головой стоит тема ролика, а не обрывок текущей реплики: приём держит
    # весь блок, и фраза из середины предложения читалась бы как оговорка.
    # Обе строки идут через весь кадр без переноса, поэтому делим пополам по
    # словам, а не по акценту: кегль подбирается под длинную из двух.
    head = tail = ""
    title_words = [w for w in str(title or "").split() if w]
    if len(title_words) >= 2:
        cut = (len(title_words) + 1) // 2
        head = " ".join(title_words[:cut]).strip(".,!?;:")
        tail = " ".join(title_words[cut:]).strip(".,!?;:")

    # Знаки за головой: сначала логотип, если бренд в реплике назван — он
    # конкретнее рисованного знака, — потом знаки по тексту. Реплика, в
    # которой не названо ничего предметного, знаков не получает, и приём в
    # таком кадре не показывается: иконки ни о чём — шум, а не монтаж.
    icons: list[dict[str, Any]] = []
    if brand and brand.get("icon"):
        icons.append({"file": brand["icon"], "label": brand.get("label", "")})
    icons += [{"glyph": name} for name in match_glyphs(text, limit=5)]

    return {
        "word": word,
        "lines": lines,
        "accent_lines": accent,
        # Заголовок карточки — начало реплики, а не акцентное слово: одно слово
        # крупно уже занято выбивкой и заголовком над головой.
        "title": " ".join(text.split()[:3]).strip(".,!?;:").upper(),
        # Запрос в переписке — только если реплика и правда спрашивает.
        # Резать по счёту слов нельзя: обрывок «Это и» на месте вопроса
        # читается как сбой набора, а не как реплика.
        "ask": _question(text),
        "answer": _sentence(text, 1, limit=6),
        # Промпт для окна генерации — только если блок и правда про генерацию.
        "gen_prompt": _gen_prompt(block),
        "head": head,
        "tail": tail,
        # Фраза для плашки-удара: одна фраза реплики, разбитая на две короткие
        # строки. Длиннее — и плашка перестаёт читаться за секунду, ради
        # которой она и появляется.
        "punch": _punch(block),
        # Подпись под экспонатом: первая фраза реплики целиком. Поисковый
        # запрос сюда не годится — он английский и написан для стока, а не
        # для зрителя.
        "caption": _caption(text),
        # Куски для накопительного списка — по словам этого кадра, а не по
        # тексту блока: список идёт за речью, а кадр покрывает её часть.
        "entries": _log_entries(words or [], float(slot.get("start") or 0.0)),
        # Числа реплики: приём ставит их одно за другим на одном месте.
        "figures": _figures(text),
        "brand": brand,
        # Меньше двух — не очередь, а одиночная мигалка, и приём на этом не
        # держится. Отсечка стоит здесь, а не в рендерере: конвейер выбирает
        # приём по наличию содержимого, и пустой Piece дал бы кадр без приёма
        # молча — так уже было с двумя шаблонами.
        "icons": icons[:5] if len(icons) >= 2 else [],
        "face": face,
        # Не ``head``: так уже зовётся первая строка темы за головой, и коробка
        # затёрла бы её — приём получил бы вместо текста кортеж координат.
        # Проверено тестом, а не рассуждением.
        "head_box": head_box,
        # Страница первоисточника: домен из ссылки блока и та строка, которую
        # сценарий взял из статьи. Без ссылки приём не показывается вовсе —
        # страница без домена не источник, а просто белый лист.
        "source": _source_site(block),
        "quote": _quote(block),
    }


# Приёмы, закрывающие кадр сплошной заливкой. Заливка живёт секунду-две и
# глушит субтитр на своём окне: под ней его всё равно не видно.
_FULL_FRAME_HEROES = ("hero-slam", "hero-knockout")

# Приёмы, которые выкладывают реплику **не** строками, а подписью, и потому не
# попадают под проверку по `_HERO_NEEDS`. Экспонат подписывает материал фразой
# целиком (`detail`), и пословный субтитр ложился на неё поверх: на кадре
# читалось «Модель обучили на|вятнадцать дней» — подпись и субтитр в одну
# строку. Ловится только кадром: в разметке оба элемента корректны по
# отдельности.
_CAPTION_HEROES = ("hero-exhibit",)

# Large mid-frame type that collides with word captions at ~baseline 1100–1280.
# Word/title/head heroes used to leave captions on; Markus rejected the overlap.
_TEXT_ZONE_HEROES = (
    "hero-headline", "hero-oversize", "hero-split", "hero-title-behind",
    "hero-figure", "hero-card-stack", "hero-paper", "hero-brand-pill",
)


def hero_mutes_subtitle(renderer: str) -> dict[str, bool]:
    """Отменяет ли приём пословный субтитр — и по какой из двух причин.

    Отдельной функцией, а не двумя выражениями по месту: тем же правилом
    живёт проба (`tools/build_test_clip.py`), и разъехавшись, она показала бы
    кадр, которого конвейер не соберёт. Ровно так и вышло с выбивкой: в пробе
    субтитр остался стоять на заливке.
    """
    return {
        # Приём, который выкладывает реплику строками, сам и есть субтитр
        # этого кадра. Пословное слово поверх той же фразы — дубль, и оно
        # вдобавок ложится прямо на карточку: проверено кадром.
        "carries_line": (bool({"lines", "punch", "entries", "word", "title",
                               "head", "tail", "figures", "source", "quote",
                               "brand"}
                              & set(_HERO_NEEDS.get(renderer, ())))
                         or renderer in _CAPTION_HEROES
                         or renderer in _TEXT_ZONE_HEROES),
        # Приём, закрывающий кадр сплошной заливкой, съедает и субтитр: белое
        # слово на светлой заливке не читается, а чернильное на тёмной — тем
        # более. Своё слово он в кадре уже показывает.
        "covers_frame": renderer in _FULL_FRAME_HEROES,
    }


def hero_params(renderer: str, base: dict[str, Any], content: dict[str, Any],
                slot: dict[str, Any]) -> dict[str, Any]:
    """Наполнить пресет приёма содержимым блока.

    Отдельной функцией, а не куском выбора: тем же отображением пользуется
    витрина приёмов (``tools/build_showcase.py``), и разъехавшись, она начала
    бы показывать не то, что собирает конвейер.
    """
    params: dict[str, Any] = {**base}
    if "word" in _HERO_NEEDS.get(renderer, ()):
        params["word"] = str(content["word"]).upper()
    if renderer == "hero-headline":
        params["kicker"] = _HERO_KICKERS.get(str(slot.get("role") or ""), "")
    if "lines" in _HERO_NEEDS.get(renderer, ()):
        upper = renderer in ("hero-text-column", "hero-type-slab")
        params["lines"] = [l.upper() if upper else l for l in content["lines"]]
        params["accent_lines"] = content["accent_lines"]
    if content.get("head_box") and renderer in ("hero-headline", "hero-title-behind"):
        # Приём стоит за головой, и от макушки зависит, где начнётся строка.
        params["head_top"] = int(content["head_box"][1])
    if renderer == "hero-icons" and content.get("head_box"):
        # Дуга строится вокруг настоящей головы: её центр и полуразмер.
        box = content["head_box"]
        params["face_cx"] = (int(box[0]) + int(box[2])) // 2
        params["face_cy"] = (int(box[1]) + int(box[3])) // 2
        params["head_half"] = max(int(box[2]) - int(box[0]),
                                  int(box[3]) - int(box[1])) // 2
    if content.get("face"):
        # Круг садится на лицо, выбивка — тоже: её буквы видны только там, где
        # за ними светлее заливки.
        if renderer in ("hero-bubble-card", "hero-bubble-typed"):
            params["face_cx"], params["face_cy"] = content["face"]
            if content.get("head_box"):
                # Круг считается от коробки головы: по фиксированному диаметру
                # он срезал щёки и подбородок. Центр — тоже её, а не лица:
                # радиус описан вокруг головы, и если посадить его на середину
                # лица, макушка вылезет ровно на разницу между ними.
                box = content["head_box"]
                params["head_w"] = int(box[2]) - int(box[0])
                params["head_h"] = int(box[3]) - int(box[1])
                params["face_cx"] = (int(box[0]) + int(box[2])) // 2
                params["face_cy"] = (int(box[1]) + int(box[3])) // 2
        if renderer == "hero-knockout":
            params["face_cy"] = content["face"][1]
            if content.get("head_box"):
                # Выбивке нужна не точка лица, а его полоса: буквы вырезаны
                # насквозь, и выше бровей за ними тёмные волосы — то же
                # тёмное по тёмному, что и на торсе. Полосу приём считает
                # сам, ему хватает макушки и высоты головы.
                box = content["head_box"]
                params["head_top"] = int(box[1])
                params["head_h"] = int(box[3]) - int(box[1])
    if renderer == "hero-brand-pill":
        params.update(content["brand"])
    if renderer in ("hero-card-stack", "hero-exhibit"):
        params["title"] = content["title"]
    if renderer == "hero-exhibit":
        # Title + detail on the plaque; source goes to thin BL `.credit` only
        # so we do not stack a giant ex-credit with the on-screen caption.
        params["title"] = str(content.get("word") or content["title"])
        params["detail"] = content.get("caption", "")
    if renderer == "hero-log":
        # Список набирается чёрным, и одно слово в нём горит — акцентное слово
        # реплики. Приёму нужен сам текст акцента, а не номера строк.
        params["accent"] = content["word"]
    if renderer == "hero-phone-mock":
        params["app"] = str(slot.get("screen_template") or "ChatGPT")
    # Текстовые нужды приёма переносятся один в один: имя ключа в
    # ``_HERO_NEEDS`` и есть имя параметра рендерера. Правила выше — про те
    # ключи, где содержимое ещё нужно причесать (регистр, лицо, иконка).
    _SHAPED = ("word", "lines", "plate", "brand", "title")
    for key in _HERO_NEEDS.get(renderer, ()):
        if key not in _SHAPED and content.get(key):
            params[key] = content[key]
    if renderer == "hero-chat-typing":
        # Ответ приёму не обязателен: без него он показывает ожидание, и это
        # рабочий кадр. Но если реплика длинная — ответ есть, и он читается.
        params["answer"] = content.get("answer", "")
        params["app"] = str(slot.get("screen_template") or "ChatGPT")
    if renderer == "hero-chat-generate":
        params["app"] = str(slot.get("screen_template") or "ChatGPT")
    return params


def _norm_screen_key(text: str) -> str:
    return " ".join(str(text or "").upper().split()).strip(" ,.;:—-")


def _block_clauses(text: str) -> list[str]:
    """Разбить тело блока на короткие смысловые фразы для ротации на экране."""
    body = _strip_discourse(str(text or ""))
    if not body:
        return []
    parts = re.split(r"[.!?…;:—]+", body)
    out: list[str] = []
    for part in parts:
        words = [w for w in part.split() if w.strip()]
        if len(words) < 2:
            continue
        # 3–4 слова — потолок кегля полноэкранного текста.
        chunk = " ".join(words[:4]).strip(" ,.;:—-")
        if chunk:
            out.append(chunk)
    return out


def gap_phrase(words: list[dict[str, Any]], slot: dict[str, Any],
               block: dict[str, Any],
               *, used: set[str] | None = None) -> str:
    """Что вынести на экран, когда материала под кадр нет.

    Смысл речи, не каталожный плейсхолдер и не дискурс-открывашка («и вот
    ответ»). Overlay-punch («5 МИНУТ») — один раз на блок: иначе одна фраза
    висит на всех gap-слотах подряд. Дальше — окно речи / другие клаузы.
    """
    used = used if used is not None else None
    semantic = _semantic_screen_text(block)
    overlay = block.get("overlay") or {}
    otype = str(overlay.get("type") or "")

    def _take(phrase: str) -> str:
        key = _norm_screen_key(phrase)
        if not key:
            return ""
        if used is not None:
            if key in used:
                return ""
            used.add(key)
        return key

    # Overlay punch only once — not on every subsequent gap in the same block.
    if (semantic and len(semantic.split()) <= 5
            and otype in ("fullscreen_text", "lower_third", "plaque", "note")):
        hit = _take(semantic)
        if hit:
            return hit

    start, end = float(slot["start"]), float(slot["end"])
    said = [str(w.get("word") or "") for w in words
            if float(w["end"]) > start and float(w["start"]) < end]
    said = [w for w in said if w.strip()]
    if said:
        joined = " ".join(said)
        if _DISCOURSE_PREFIX.match(joined):
            body = _strip_discourse(str(block.get("text") or joined))
            said = body.split()[:4] or said
        hit = _take(" ".join(said[:4]))
        if hit:
            return hit

    for clause in _block_clauses(str(block.get("text") or semantic or "")):
        hit = _take(clause)
        if hit:
            return hit

    body = _strip_discourse(str(block.get("text") or semantic or ""))
    said = body.split()[:4]
    fallback = " ".join(said[:4]).upper().strip(" ,.;:—-")
    if used is not None and fallback:
        used.add(_norm_screen_key(fallback))
    return fallback


def explain_choice(template: Any, traits: Iterable[str]) -> str:
    """Почему именно этот приём здесь — словами, а не «роль блока».

    Одна формулировка на все категории: строка уходит в edit-план и в отчёт
    сборки, и читать её будет человек, а не разбор.
    """
    hit = matched(template.needs, traits)
    if hit:
        return f"приём оправдан: {explain(hit)}"
    return "приём без смысловых требований: держит кадр, не спорит с речью"



def _hero_device(catalog: TemplateCatalog, *, slot: dict[str, Any],
                 content: dict[str, Any], has_alpha: bool,
                 plate_src: dict[str, Any] | None,
                 recent_videos: list[str], exclude: list[str],
                 seed: int,
                 picker: TemplatePicker | None = None,
                 variant: str = "A",
                 block: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Выбрать приём вокруг ведущего под конкретный кадр.

    Приём отбрасывается, если кадр не может его показать: без альфы всё, что
    рисуется под аватаром, окажется за непрозрачным видео, а остальным нужен
    материал из ``_HERO_NEEDS``.
    """
    if picker is None:
        picker = TemplatePicker(catalog, ScenarioIndex.load(catalog=catalog))
    available = dict(content)
    # Plate-needing heroes require a real (non-AI) plate; otherwise fall back
    # to non-plate templates rather than an empty or generated panel.
    real_plate = plate_src if plate_src and not plate_src.get("ai_generated") else None
    available["plate"] = real_plate
    if real_plate and real_plate.get("credit"):
        content = {**content, "credit": real_plate["credit"]}

    blocked = list(exclude)
    for template in catalog.by_category("hero-devices"):
        if "alpha" in set(template.tags) and not has_alpha:
            blocked.append(template.id)
            continue
        needs = _HERO_NEEDS.get(template.renderer, ())
        if any(not available.get(key) for key in needs):
            blocked.append(template.id)
            continue
        # Музейная табличка — утверждение о материале: вот вещь, вот её имя,
        # вот кем она снята. Под сгенерированным пятном она подписывала
        # «REDSHIFT / GENERATED» и тем самым объявляла зрителю ровно то, чего
        # заказчик просил не показывать. Приём остаётся для настоящего кадра.
        if template.renderer in _CAPTION_HEROES and not real_plate:
            blocked.append(template.id)

    if not [t for t in catalog.by_category("hero-devices") if t.id not in blocked]:
        return None

    signals = {k for k, v in available.items() if v and k in ("plate", "icons", "word", "lines", "brand", "title")}
    if has_alpha:
        signals.add("alpha")
    # Meaning traits stay separate from structural signals (plate/alpha/word).
    traits = None if block is None else block_traits(str((block.get("text") if isinstance(block, dict) else block) or ""))
    if content.get("figures"):
        signals.add("numbers")
    blob = build_blob(content.get("title"), content.get("caption"), " ".join(content.get("lines") or []), content.get("word"))
    template, _ = picker.pick(
        "hero-devices",
        blob=blob,
        signals=signals,
        traits=traits,
        variant=variant,
        duration=float(slot["duration"]),
        recent_videos=recent_videos,
        exclude=blocked,
        seed=seed + int(slot["index"]) * 7,
    )
    renderer = template.renderer
    params = hero_params(renderer, template.params, content, slot)

    entry: dict[str, Any] = {
        "template": template.id, "renderer": renderer, "params": params,
        "file": None, "duration": None,
        "traits": sorted(traits or ()),
        "grounded_on": sorted(matched(template.needs, traits or ())),
        "why": explain_choice(template, traits or ()),
        **hero_mutes_subtitle(renderer),
    }
    if real_plate and renderer == "hero-chat-generate":
        # Window lasts the whole shot; media inside may be shorter than the avatar plan.
        entry["file"] = real_plate["file"]
        if real_plate.get("duration_sec"):
            params["media_sec"] = round(float(real_plate["duration_sec"]), 3)
    elif real_plate and renderer in ("hero-plate", "hero-card-stack",
                                    "hero-exhibit", "hero-plate-pop"):
        # Plate heroes follow the plate length so the panel does not hang empty.
        entry["file"] = real_plate["file"]
        entry["duration"] = round(min(float(slot["duration"]),
                                      real_plate["duration_sec"]), 3)
    if renderer in _FULL_FRAME_HEROES:
        # Заливка закрывает ведущего целиком и потому живёт секунду-две, а не
        # весь кадр: дольше — и это уже не удар, а пауза в ролике.
        entry["duration"] = round(min(float(slot["duration"]),
                                      float(template.duration_range[1])), 3)
    return entry


def _variant_seed(video_id: str, variant: str) -> int:
    return int(hashlib.sha256(f"{video_id}|{variant}".encode()).hexdigest()[:8], 16)


def _asset_for_slot(slot: dict[str, Any], accepted: dict[str, Any],
                    generated: dict[str, Any]) -> dict[str, Any] | None:
    key = str(slot["index"])
    return accepted.get(key) or generated.get(key)


def _rotate_assets(slots: list[dict[str, Any]], assets: dict[int, dict[str, Any]],
                   shift: int, *, ai_budget_sec: float | None = None,
                   ) -> dict[int, dict[str, Any]]:
    """Порядок вставок внутри блока — законное отличие версий (§4.5).

    Материал остаётся тот же, меняется только то, какой кадр в каком месте
    блока стоит. Это ровно «различаются монтажные решения, не материал».

    Но экранное время у слотов разное, и перестановка меняет не только
    порядок. P9 выдаёт генерацию под конкретные слоты и считает долю по их
    длительности; ротация переносит тот же кадр на слот вдвое длиннее, и доля
    растёт, хотя материала не прибавилось. Прогон CI 33607509470: P9
    отчитался о 0.1995, вариант A собрался в 0.3420, вариант B — в 0.3971 при
    потолке 0.35, и QC-14 не выдал ролик, за который уже заплачено всё.

    ``ai_budget_sec`` — потолок экранного времени AI-материала. Ротация,
    выводящая за него, откатывается по блокам: сначала тот блок, который
    добавил больше всего AI-секунд. Различие версий при этом сохраняется
    везде, где оно ничего не ломает.
    """
    if shift == 0:
        return dict(assets)
    out = dict(assets)
    by_block: dict[str, list[int]] = {}
    for slot in slots:
        if slot["index"] in assets:
            by_block.setdefault(slot["block_id"], []).append(slot["index"])

    rotated_blocks: list[list[int]] = []
    for indices in by_block.values():
        if len(indices) < 2:
            continue
        values = [assets[i] for i in indices]
        offset = shift % len(values)
        rotated = values[offset:] + values[:offset]
        for index, value in zip(indices, rotated):
            out[index] = value
        rotated_blocks.append(indices)

    if ai_budget_sec is None:
        return out

    seconds = {int(s["index"]): float(s.get("duration") or 0.0) for s in slots}

    def ai_sec(mapping: dict[int, dict[str, Any]], indices=None) -> float:
        keys = mapping if indices is None else indices
        return sum(seconds.get(i, 0.0) for i in keys
                   if (mapping.get(i) or {}).get("ai_generated"))

    while ai_sec(out) > ai_budget_sec + 1e-6 and rotated_blocks:
        # Откатываем блок, чья перестановка стоила больше всего AI-секунд.
        worst = max(rotated_blocks,
                    key=lambda idx: ai_sec(out, idx) - ai_sec(assets, idx))
        for index in worst:
            out[index] = assets[index]
        rotated_blocks.remove(worst)
    return out


def _segment_for_slot(slot: dict[str, Any], segments: list[dict[str, Any]]
                      ) -> dict[str, Any] | None:
    """Аватар-сегмент, покрывающий слот (сегменты слиты из смежных слотов в P6)."""
    for segment in segments:
        if slot["index"] in segment.get("slot_indices", []):
            return segment
    for segment in segments:
        if float(segment["start"]) - 1e-3 <= float(slot["start"]) < float(segment["end"]):
            return segment
    return None


def _prepare_shots(ctx, slots: list[dict[str, Any]], assets: dict[int, dict[str, Any]],
                   pillarbox_limit: int,
                   avatar_segments: list[dict[str, Any]] | None = None,
                   matte_reports: dict[int, Any] | None = None,
                   behind_layers: dict[str, Path] | None = None,
                   vfx_clips: dict[int, Path] | None = None,
                   ) -> dict[int, dict[str, Any]]:
    """Нормализовать исходники в планы; одинаковые (файл, длительность) — один раз."""
    cache: dict[tuple, dict[str, Any]] = {}
    prepared: dict[int, dict[str, Any]] = {}
    pillarbox_used = 0
    width, height = ctx.cfg.resolution
    fps = ctx.cfg.fps
    segments = avatar_segments or []
    matte_reports = matte_reports or {}
    behind_layers = behind_layers or {}
    vfx_clips = vfx_clips or {}

    for slot in slots:
        # --- аватар: источник — клип сегмента, смещённый на позицию слота ----
        if slot["kind"] in AVATAR_KINDS:
            segment = _segment_for_slot(slot, segments)
            segment_file = Path(str((segment or {}).get("file", "")).strip() or "/nonexistent")
            if segment is None or not segment_file.is_file():
                # Ролик без аватара — это брак, а не «мало материала»: QC-2 и QC-11
                # всё равно завалят его через четыре минуты рендера. Падаем здесь,
                # где ещё видно, какого именно клипа не хватает.
                raise RedshiftError(
                    f"нет клипа аватара для слота {slot['index']} "
                    f"({slot['start']:.2f}–{slot['end']:.2f} сек, блок {slot['block_id']}): "
                    f"перезапустите с --from P6",
                    code="AVATAR_CLIP_MISSING", slot=slot["index"],
                    block_id=slot["block_id"],
                    expected_file=str(segment_file) if segment else None)
            offset = max(0.0, float(slot["start"]) - float(segment["start"]))
            duration = round(float(slot["duration"]), 3)
            avatar_src = Path(segment["file"])

            if slot["kind"] == "split":
                # §3.5 режим B: сверху доказательный материал, снизу аватар.
                asset = assets.get(slot["index"])
                top_path = str((asset or {}).get("local_file") or "").strip()
                top_src = Path(top_path) if top_path else None
                if top_src is None or not top_src.is_file():
                    key = (asset or {}).get("storage_key")
                    if key and ctx.storage.exists(key):
                        top_src = ctx.wpath("broll", "raw", Path(key).name)
                        ctx.storage.get(key, top_src)
                if top_src is None or not top_src.is_file():
                    ctx.warn(f"для сплита {slot['index']} нет верхней половины",
                             slot=slot["index"])
                    continue
                dst = ctx.wpath("shots", f"split_{slot['index']:02d}_{int(duration * 1000)}.mp4")
                prepared[slot["index"]] = prepare_split_shot(
                    top_src=top_src, bottom_src=avatar_src, dst=dst,
                    duration_sec=duration, width=width, height=height, fps=fps,
                    bottom_start_sec=offset,
                    bottom_has_alpha=bool(segment.get("has_alpha")),
                    bg_colors=(str(ctx.cfg.color("bg_light")).lstrip("#"),
                               str(ctx.cfg.color("bg_pure")).lstrip("#")),
                    divider_color="0x" + str(ctx.cfg.color("accent")).lstrip("#"))
                prepared[slot["index"]]["avatar_offset_sec"] = round(offset, 3)
                prepared[slot["index"]]["asset_id"] = (asset or {}).get("asset_id")
                continue

            dst = ctx.wpath("shots", f"avatar_{slot['index']:02d}_{int(duration * 1000)}.mp4")
            matte = matte_reports.get(int(segment["index"]))
            if matte is not None and matte.usable:
                # §7.7: есть годная маска — собираем фон + текст за головой + аватар.
                behind = behind_layers.get(slot["block_id"]) if slot["mode"] == "A" else None
                result = prepare_avatar_shot(
                    avatar_src=avatar_src, dst=dst, duration_sec=duration,
                    width=width, height=height, fps=fps, start_sec=offset,
                    # Light brand bg under avatar — accent fill would blow §3.3.1.
                    bg_colors=(str(ctx.cfg.color("bg_light")).lstrip("#"),
                               str(ctx.cfg.color("bg_pure")).lstrip("#")),
                    behind_layer=behind,
                    vfx_src=vfx_clips.get(slot["index"]),
                    compose_zoom=float(ctx.cfg.get("heygen.compose_zoom", 1.0) or 1.0))
            else:
                # Opaque fallback: same compose_zoom via ShotSpec (source already 9:16).
                # focus_y ~0.55 matches prepare_avatar_shot strong-zoom crop bias
                # so opaque Avatar V plates also trim the black void above the head.
                result = prepare_shot(ShotSpec(
                    src=avatar_src, dst=dst, duration_sec=duration,
                    width=width, height=height, fps=fps, fit="crop",
                    focus_x=0.5, focus_y=0.55, start_sec=offset,
                    compose_zoom=float(ctx.cfg.get("heygen.compose_zoom", 1.0) or 1.0)))
            result["avatar_offset_sec"] = round(offset, 3)
            result["avatar_segment"] = segment["index"]
            result["matte"] = matte.to_dict() if matte else None
            prepared[slot["index"]] = result
            continue

        asset = assets.get(slot["index"])
        if asset is None:
            continue
        # Материал из локальной базы приходит без local_file — только с ключом
        # storage. Пустую строку в Path() класть нельзя: Path("") — это Path("."),
        # он существует, и дальше ffmpeg получает на вход каталог.
        local_file = str(asset.get("local_file") or "").strip()
        src = Path(local_file) if local_file else None
        if src is None or not src.is_file():
            key = asset.get("storage_key")
            if key and ctx.storage.exists(key):
                src = ctx.wpath("broll", "raw", Path(key).name)
                ctx.storage.get(key, src)
            else:
                ctx.warn(f"нет файла для слота {slot['index']} ({asset.get('asset_id')}): "
                         f"ни local_file, ни ключа в storage",
                         slot=slot["index"], asset=asset.get("asset_id"),
                         origin=asset.get("origin"))
                continue

        info = probe(src)
        fit = choose_fit(info, pillarbox_used=pillarbox_used, pillarbox_limit=pillarbox_limit)
        if fit == "pillarbox":
            pillarbox_used += 1
        duration = round(float(slot["duration"]), 3)
        cache_key = (str(src), duration, fit)
        if cache_key in cache:
            prepared[slot["index"]] = cache[cache_key]
            continue

        focus_x, focus_y = (0.5, 0.5)
        if fit == "crop" and info.width and info.height and info.width > info.height * 1.05:
            focus_x, focus_y = detect_focus(src, work_dir=ctx.wpath("shots", "_focus", ".k").parent)

        dst = ctx.wpath("shots", f"{asset['asset_id']}_{int(duration * 1000)}_{fit}.mp4")
        result = prepare_shot(ShotSpec(src=src, dst=dst, duration_sec=duration,
                                       width=width, height=height, fps=fps,
                                       fit=fit, focus_x=focus_x, focus_y=focus_y))
        cache[cache_key] = result
        prepared[slot["index"]] = result
    return prepared



def _prepare_matting(ctx, plan: dict[str, Any], avatar_meta: dict[str, Any]
                     ) -> tuple[dict[int, Any], dict[str, Path], dict[int, Path], dict[str, Any]]:
    """§7.7 — маска аватара, текст за головой и VFX-фон.

    Функция экспериментальная и полностью изолирована киллсвитчем: при
    ``features.avatar_matting: false`` она возвращает пустые словари, и сборка
    идёт как обычно — просто без текста за головой и без живого фона.
    """
    cfg = ctx.cfg
    summary: dict[str, Any] = {"enabled": bool(cfg.get("features.avatar_matting", False)),
                               "segments": [], "text_behind_head": [], "vfx": []}
    if not summary["enabled"]:
        summary["reason"] = "avatar_matting выключен киллсвитчем (§7.7)"
        return {}, {}, {}, summary

    segments = avatar_meta.get("segments", [])
    reports: dict[int, Any] = {}
    for segment in segments:
        clip = Path(segment.get("file", ""))
        if not clip.exists():
            continue
        report = assess_matte(clip, ctx.wpath("matte", f"seg_{segment['index']:02d}", ".k").parent)
        if not report.available:
            report = try_local_matting(clip, clip)     # §7.7 fallback 2
        reports[int(segment["index"])] = report
        summary["segments"].append({"index": segment["index"], **report.to_dict()})

    usable = [i for i, r in reports.items() if r.usable]
    if not usable:
        summary["degraded"] = True
        summary["reason"] = ("годной маски нет — текст за головой и VFX-фон "
                             "пропущены, остальное собирается как обычно (§7.7)")
        ctx.warn(f"§7.7: {summary['reason']}")
        return reports, {}, {}, summary

    # --- текст за головой (§5.3): только режим A и только при годной маске ---
    behind_layers: dict[str, Path] = {}
    render_ctx = Ctx.build(cfg)
    for block in plan.get("blocks", []):
        if block.get("mode") != "A":
            continue
        text = (block.get("emphasis_word") or "").strip()
        if not text:
            continue
        block_segments = [s for s in segments if s["block_id"] == block["id"]]
        if not block_segments or int(block_segments[0]["index"]) not in usable:
            continue
        layer = text_behind_head(render_ctx, text, progress=1.0)
        path = ctx.wpath("matte", f"behind_{block['id']}.png")
        layer.save(path)
        behind_layers[block["id"]] = path
        summary["text_behind_head"].append({"block_id": block["id"], "text": text})

    # --- VFX-фон (§7.7): stock B-roll behind avatar (no paid AI gen) -------
    # Prefer real footage plates already harvested by P7/P8. AI generation was
    # money + often abstract mush; Markus wants interesting stock behind alpha.
    vfx_clips: dict[int, Path] = {}
    if bool(cfg.get("features.background_vfx", False)):
        limit = int(cfg.get("limits.bg_vfx_per_video", 2))
        lo, hi = cfg.get("limits.bg_vfx_sec", [2.0, 5.0])
        avatar_slot_idxs = {idx for seg in segments if int(seg["index"]) in usable
                            for idx in seg.get("slot_indices", [])}
        candidates = plan_vfx_backgrounds(
            [s for s in plan["slots"] if s["index"] in avatar_slot_idxs],
            limit=limit, duration_range=(float(lo), float(hi)))
        # Stock plates from accepted assets for this cut (dict slot→entry).
        stock_paths: list[Path] = []
        try:
            accepted_doc = ctx.read("accepted_assets.json")
        except Exception:  # noqa: BLE001
            accepted_doc = {}
        accepted_map = accepted_doc.get("accepted") or {}
        items = (list(accepted_map.values()) if isinstance(accepted_map, dict)
                 else list(accepted_map or []))
        for item in items:
            if not isinstance(item, dict) or item.get("ai_generated"):
                continue
            local = str(item.get("local_file") or "").strip()
            if local and Path(local).is_file():
                stock_paths.append(Path(local))
                continue
            key = str(item.get("storage_key") or "").strip()
            if key and ctx.storage.exists(key):
                dst = ctx.wpath("broll", "raw", Path(key).name)
                if not dst.is_file():
                    ctx.storage.get(key, dst)
                if dst.is_file():
                    stock_paths.append(dst)
        cursor = 0
        for slot_index in candidates:
            slot = next(s for s in plan["slots"] if s["index"] == slot_index)
            if stock_paths:
                vfx_clips[slot_index] = stock_paths[cursor % len(stock_paths)]
                cursor += 1
                summary["vfx"].append({"slot": slot_index, "source": "stock",
                                       "duration_sec": round(float(slot["duration"]), 2)})
                continue
            # Last resort: skip (brand gradient under avatar) — do NOT spend
            # Magnific/Kling credits on abstract VFX for talking-head BGs.
            ctx.warn("нет сток-плиты для фона аватара — градиент брендбука",
                     slot=slot_index)

    summary["degraded"] = False
    return reports, behind_layers, vfx_clips, summary


_OVERLAY_BY_NAME = {
    "chat-thread": "chat_thread",
    "chat-ai-typing": "chat_thread",
    "article-highlight": "article_scroll",
    "browser-scroll": "article_scroll",
    "paper-reveal": "paper_reveal",
    "arxiv-card": "paper_reveal",
    "ai-chat-reveal": "ai_chat_reveal",
    "app-showcase": "app_showcase",
    "chatgpt-exchange": "chatgpt_exchange",
    "claude-exchange": "claude_exchange",
    "message-thread-reveal": "message_thread_reveal",
    "notes-reveal": "notes_reveal",
    "notification-cascade": "notification_cascade",
    "instagram-follow": "instagram_follow",
    "tiktok-follow": "tiktok_follow",
    "yt-lower-third": "yt_lower_third",
    "x-post": "x_post",
    "reddit-post": "reddit_post",
    "spotify-card": "spotify_card",
    "macos-notification": "macos_notification",
}

_NUM_IN_TEXT = re.compile(
    r"(?<![\d.])(\d+(?:[.,]\d+)?)(?:\s*(%|млрд|млн|тыс\.?|кубит(?:ов|а)?|[Tт]))?",
    re.IGNORECASE,
)


def _overlay_renderer(template: Template) -> str:
    """Какой HTML-рендерер рисует карточку источника."""
    mapped = _OVERLAY_BY_NAME.get(template.name)
    if mapped:
        return mapped
    if template.renderer in ("chat_thread", "article_scroll", "paper_reveal",
                             "source_card", "ai_chat_reveal", "app_showcase",
                             "chatgpt_exchange", "claude_exchange",
                             "message_thread_reveal", "notes_reveal",
                             "notification_cascade", "instagram_follow",
                             "tiktok_follow", "yt_lower_third", "x_post",
                             "reddit_post", "spotify_card",
                             "macos_notification"):
        return template.renderer
    return "source_card"


def _plaque_overlay(*, template: Template, start: float, end: float,
                    params: dict[str, Any], why: str) -> dict[str, Any]:
    """Плашка: кастомный рендерер (accent-underline, clean-bar, dark-card), иначе generic plaque."""
    ovl: dict[str, Any] = {
        "type": "plaque", "start": start, "end": end,
        "template": template.id, "params": params, "why": why,
    }
    renderer = template.renderer
    if renderer and renderer != "plaque":
        ovl["renderer"] = renderer
    return ovl


def _stats_from_text(text: str) -> list[dict[str, Any]]:
    """Числа из реплики блока. Годы 1900–2100 отбрасываем, если есть другие."""
    found: list[dict[str, Any]] = []
    for match in _NUM_IN_TEXT.finditer(text or ""):
        raw = match.group(1).replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        suffix = (match.group(2) or "").strip()
        found.append({"value": value, "suffix": suffix,
                      "raw": match.group(0).strip()})
    if not found:
        return []
    years = [n for n in found
             if n["value"] == int(n["value"]) and 1900 <= n["value"] <= 2100]
    others = [n for n in found if n not in years]
    return others or found

def _evidence_runs(slots: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Куски доказательства: подряд идущие слоты одного блока — один кусок.

    Карточка источника привязана к куску, а не к слоту: P5 режет длинный блок
    на несколько слотов по лимиту длины кадра, и по слотам карточек вышло бы
    три подряд на одной и той же статье.
    """
    runs: list[list[dict[str, Any]]] = []
    for slot in slots:
        if slot.get("asset_role") != "evidence" and slot.get("role") != "evidence":
            continue
        if (runs and runs[-1][-1]["block_id"] == slot["block_id"]
                and abs(float(runs[-1][-1]["end"]) - float(slot["start"])) < 1e-6):
            runs[-1].append(slot)
        else:
            runs.append([slot])
    return runs


def _build_overlays(ctx, plan: dict[str, Any], words: list[dict[str, Any]],
                    catalog: TemplateCatalog, *, variant: str, seed: int,
                    recent_videos: list[str], used: list[str],
                    picker: TemplatePicker | None = None) -> list[dict[str, Any]]:
    """Плашки, карточки источников, подсветка, data-viz и CTA (§5.4–5.6, §6)."""
    if picker is None:
        cfg = getattr(ctx, "cfg", None)
        picker = TemplatePicker(catalog, ScenarioIndex.load(cfg, catalog=catalog))
    overlays: list[dict[str, Any]] = []
    duration = float(plan["duration_sec"])
    sources = plan.get("sources", [])
    # Bulky browser/source_card overlays are opt-in proof beats only.
    # Routine real footage uses the thin BL `.credit` from `_credit_line`.
    # Require both show_on_screen and proof_card so legacy scripts that only
    # set show_on_screen:true no longer spawn full-frame source badges.
    on_screen = [s for s in sources
                 if s.get("show_on_screen") and (s.get("proof_card") or s.get("snippet") or s.get("highlight_line"))]

    for i, (source, run) in enumerate(zip(on_screen, _evidence_runs(plan["slots"]))):
        anchor = run[0]
        card_category = "browser-ui" if variant == "A" else "frames-cards"
        ev_block = next((b for b in (plan.get("blocks") or [])
                         if b.get("id") == anchor.get("block_id")), {})
        card_traits = block_traits(str(ev_block.get("text") or source.get("snippet") or ""))
        blob = build_blob(
            source.get("title"),
            source.get("snippet"),
            source.get("domain"),
            source.get("screen_template"),
        )
        card_template, _ = picker.pick(
            card_category,
            blob=blob,
            signals=set(card_traits),
            traits=card_traits,
            variant=variant,
            duration=float(anchor["duration"]),
            recent_videos=recent_videos,
            exclude=used,
            seed=seed + i,
        )
        used.append(card_template.id)
        card_start = float(anchor["start"])
        card_end = min(card_start + 3.4, float(run[-1]["end"]))
        renderer = _overlay_renderer(card_template)
        card_params = {
            "template": source.get("screen_template", "browser"),
            "domain": source.get("domain", ""),
            "url": source.get("url", ""),
            "title": source.get("title", ""),
            "snippet": source.get("snippet", ""),
            "published": source.get("published", ""),
            "prompt": source.get("title") or source.get("snippet", ""),
            "highlight_line": source.get("highlight_line", ""),
            "highlight": source.get("highlight_line", ""),
            "typing": bool(card_template.params.get("typing")),
            "scroll": bool(card_template.params.get("scroll")),
        }
        if renderer == "ai_chat_reveal":
            card_params["userMessage"] = (
                source.get("title") or source.get("snippet") or "")
            card_params["botName"] = "Assistant"
        if renderer == "app_showcase":
            card_params["tagline"] = (
                source.get("title") or source.get("snippet") or "")
            card_params["name"] = source.get("domain") or ""
        if renderer == "chatgpt_exchange":
            card_params["prompt"] = (
                source.get("title") or source.get("snippet") or "")
            if source.get("domain"):
                card_params["row1Tool"] = source.get("domain")
        if renderer == "claude_exchange":
            card_params["prompt"] = (
                source.get("title") or source.get("snippet") or "")
            if source.get("domain"):
                card_params["domain"] = source.get("domain")
        if renderer == "message_thread_reveal":
            if source.get("title"):
                card_params["cardTitle"] = source.get("title")
            if source.get("domain"):
                card_params["cardDomain"] = source.get("domain")
        if renderer == "notes_reveal":
            if source.get("title"):
                card_params["titleL1"] = source.get("title")
            if source.get("domain"):
                card_params["brandDomain"] = source.get("domain")
        if renderer == "notification_cascade":
            if source.get("title"):
                card_params["notifTitle"] = source.get("title")
            if source.get("snippet"):
                card_params["message1"] = source.get("snippet")
            if source.get("domain"):
                card_params["footerText"] = source.get("domain")
                card_params["appName"] = source.get("domain")
        if renderer == "instagram_follow":
            if source.get("title"):
                card_params["displayName"] = source.get("title")
            if source.get("domain"):
                card_params["handle"] = source.get("domain")
        if renderer == "tiktok_follow":
            if source.get("title"):
                card_params["displayName"] = source.get("title")
            if source.get("domain"):
                card_params["handle"] = source.get("domain")
        if renderer == "yt_lower_third":
            if source.get("title"):
                card_params["channelName"] = source.get("title")
            if source.get("domain"):
                card_params["subscriberCount"] = source.get("domain")
        if renderer == "x_post":
            if source.get("title"):
                card_params["displayName"] = source.get("title")
            if source.get("domain"):
                card_params["handle"] = source.get("domain")
            if source.get("snippet"):
                card_params["text"] = source.get("snippet")
        if renderer == "reddit_post":
            if source.get("title"):
                card_params["title"] = source.get("title")
            if source.get("domain"):
                card_params["subreddit"] = source.get("domain")
            if source.get("snippet"):
                card_params["body"] = source.get("snippet")
        if renderer == "spotify_card":
            if source.get("title"):
                card_params["trackName"] = source.get("title")
            if source.get("domain"):
                card_params["artistName"] = source.get("domain")
            if source.get("snippet"):
                card_params["brandText"] = source.get("snippet")
        if renderer == "macos_notification":
            if source.get("title"):
                card_params["title"] = source.get("title")
            if source.get("domain"):
                card_params["appName"] = source.get("domain")
            if source.get("snippet"):
                card_params["body"] = source.get("snippet")
        overlays.append({
            "type": "source_card", "start": card_start, "end": card_end,
            "template": card_template.id, "renderer": renderer,
            "params": card_params,
            "traits": sorted(card_traits),
            "grounded_on": sorted(matched(card_template.needs, card_traits)),
            "why": explain_choice(card_template, card_traits)
                   or "§5.6: источник обязан появиться на экране",
        })
        # §5.5: подсветка обязательна при показе скриншота статьи.
        overlays.append({
            "type": "highlight", "start": card_start + 0.6,
            "end": min(card_start + 1.7, card_end),
            "params": {"label": source.get("highlight_line", ""), "target": "title"},
            "why": "§5.5: фокусная подсветка ключевой строки источника",
        })
        domain = source.get("domain", "")
        plaque_template, _ = picker.pick(
            "lower-thirds",
            blob=build_blob(domain, source.get("title")),
            variant=variant,
            duration=2.4,
            recent_videos=recent_videos,
            exclude=used,
            prefer_head=["lower-thirds/source-domain"],
            seed=seed + i,
        )
        used.append(plaque_template.id)
        overlays.append(_plaque_overlay(
            template=plaque_template,
            start=card_end - 0.2,
            end=min(card_end + 2.2, duration),
            params={"text": domain, "subtitle": "источник",
                    "name": domain, "role": "источник",
                    **{k: v for k, v in plaque_template.params.items()
                       if k in ("position", "direction", "accent_underline",
                                "clean_bar", "dark_card")}},
            why="§5.4: плашка с доменом источника",
        ))

    _append_dataviz(plan, overlays, catalog, variant=variant, seed=seed,
                    recent_videos=recent_videos, used=used, picker=picker)

    # Плашки из overlay-указаний сценария (lower_third).
    for block in plan.get("blocks", []):
        overlay = block.get("overlay") or {}
        if overlay.get("type") != "lower_third":
            continue
        block_slots = [s for s in plan["slots"] if s["block_id"] == block["id"]]
        if not block_slots:
            continue
        hint = overlay.get("template_hint") or ""
        head = [hint] if hint else []
        content = overlay.get("content", "")
        role = (overlay.get("role") or overlay.get("subtitle")
                or overlay.get("kicker") or "")
        template, _ = picker.pick(
            "lower-thirds",
            blob=build_blob(content, role),
            variant=variant,
            duration=2.4,
            recent_videos=recent_videos,
            exclude=used,
            prefer_head=head,
            seed=seed + 7,
        )
        used.append(template.id)
        # Word-onset sync: plaque lands on/after spoken punch, never block+0.4 early.
        content = enrich_overlay_punch(str(content or ""), str(block.get("text") or "")) or content
        b_start = float(block_slots[0]["start"])
        b_end = float(block_slots[-1]["end"])
        bwords = [w for w in words if str(w.get("block_id") or "") == str(block.get("id") or "")]
        anchor = find_spoken_anchor(bwords or words, content, block.get("emphasis_word"))
        if anchor is not None:
            start = accent_card_start(anchor, block_start=b_start, delay_sec=0.05)
        else:
            start = b_start + 0.4
        start = min(start, max(b_start, b_end - 1.2))
        overlays.append(_plaque_overlay(
            template=template,
            start=start,
            end=min(start + 2.6, b_end),
            params={"text": content, "content": content, "name": content,
                    "role": role,
                    **{k: v for k, v in template.params.items()
                       if k in ("position", "direction", "accent_underline",
                                "clean_bar", "dark_card")}},
            why=f"плашка из сценария, блок {block['id']}",
        ))

    # CTA — last ~2s (§6, QC-16). Picker stays free across outro-cta scenarios
    # (loop question, subscribe pill, phrase+SFX, brand-close). When brand-close
    # wins, wordmark defaults are EN CAPS REDSHIFT — not forced every video.
    cta_start, cta_end = plan.get("cta_window", [duration - 2.0, duration])
    cta_template, _ = picker.pick(
        "outro-cta",
        variant=variant,
        duration=float(cta_end) - float(cta_start),
        recent_videos=recent_videos,
        exclude=used,
        seed=seed,
    )
    used.append(cta_template.id)
    if (cta_template.renderer == "logo_brand_close"
            or cta_template.params.get("logo_close")
            or cta_template.name == "logo-brand-close"):
        cta_params = dict(cta_template.params)
        # Dark end plates (mesh/space): force light glyphs — ink tagline blends.
        cta_params["invert"] = True
        cta_params.setdefault("tone", "paper")
        overlays.append({
            "type": "cta", "start": float(cta_start), "end": float(cta_end),
            "template": cta_template.id,
            "renderer": "logo_brand_close",
            "params": cta_params,
            "why": "§6: identity close — вордмарк, не кнопка подписки",
        })
    else:
        overlays.append({
            "type": "cta", "start": float(cta_start), "end": float(cta_end),
            "template": cta_template.id,
            "params": {"text": "SUBSCRIBE"},
            "why": "§6: кнопка подписки в последние 2 сек",
        })
    return overlays


def _append_dataviz(plan: dict[str, Any], overlays: list[dict[str, Any]],
                    catalog: TemplateCatalog, *, variant: str, seed: int,
                    recent_videos: list[str], used: list[str],
                    picker: TemplatePicker | None = None) -> None:
    """Оверлей с числом на evidence/develop — не чаще одного на ролик."""
    if picker is None:
        picker = TemplatePicker(catalog, ScenarioIndex.empty())
    duration = float(plan["duration_sec"])
    cta_start = float((plan.get("cta_window") or [duration - 2.0, duration])[0])
    occupied = [(float(o["start"]), float(o["end"])) for o in overlays
                if o.get("type") in ("source_card", "cta", "plaque")]
    blocks = {b["id"]: b for b in plan.get("blocks", [])}
    for slot in plan["slots"]:
        if slot.get("role") not in ("evidence", "develop"):
            continue
        if slot["kind"] not in ("footage", "meme", "avatar"):
            continue
        nums = _stats_from_text(str(blocks.get(slot["block_id"], {}).get("text") or ""))
        if not nums:
            continue
        start = float(slot["start"]) + 0.25
        end = min(float(slot["end"]) - 0.15, start + 3.0, cta_start)
        if end - start < 1.2:
            continue
        if any(start < occ_end and end > occ_start for occ_start, occ_end in occupied):
            continue
        pct = str(nums[0].get("suffix") or "").lstrip().startswith("%")
        declining = (len(nums) >= 2
                     and float(nums[1]["value"]) < float(nums[0]["value"]))
        base = (["data-viz/conic-progress-ring",
                   "data-viz/stat-countup-card"]
                  if len(nums) == 1 and pct and variant != "B"
                  else ["data-viz/stat-countup-card"] if len(nums) == 1
                  else ["data-viz/bar-chart-race",
                        "data-viz/chart-story",
                        "data-viz/mk-line-graph",
                        "data-viz/animated-bar-chart",
                        "data-viz/compare-bars", "data-viz/bar-race-mini"]
                  if len(nums) >= 4
                  else (["data-viz/decline-chart",
                         "data-viz/chart-story",
                         "data-viz/mk-line-graph",
                         "data-viz/animated-bar-chart",
                         "data-viz/compare-bars", "data-viz/bar-race-mini"]
                        if declining
                        else ["data-viz/chart-story",
                              "data-viz/mk-line-graph",
                              "data-viz/animated-bar-chart",
                              "data-viz/compare-bars", "data-viz/bar-race-mini"]))
        if variant == "B" and len(nums) >= 2:
            base = ["data-viz/compare-bars", "data-viz/stat-countup-card"]

        rating_like = (
            len(nums) == 1
            and not pct
            and 0.0 < float(nums[0]["value"]) <= 5.0
            and abs(float(nums[0]["value"])
                    - round(float(nums[0]["value"]))) > 1e-9
        )

        signals = {"numbers"}
        if len(nums) >= 2:
            signals.add("two_numbers")
        if len(nums) >= 4:
            signals.add("four_numbers")
        if pct:
            signals.add("pct")
        if declining:
            signals.add("declining")
        if rating_like:
            signals.add("rating_like")

        block = blocks.get(slot["block_id"], {})
        blob = build_blob(block.get("text"), block.get("heading"))
        template, _ = picker.pick(
            "data-viz",
            blob=blob,
            signals=signals,
            variant=variant,
            duration=end - start,
            recent_videos=recent_videos,
            exclude=used,
            seed=seed + 11,
            prefer_base=base,
        )
        used.append(template.id)
        name = template.name
        if name == "decline-chart":
            start_v = float(nums[0]["value"])
            end_v = float(nums[1]["value"]) if len(nums) >= 2 else start_v
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            params = {
                "start_value": start_v,
                "end_value": end_v,
                "label": heading or "Retention",
                "values": [start_v, end_v],
            }
        elif name == "conic-progress-ring":
            val = float(nums[0]["value"])
            suffix = str(nums[0]["suffix"]) if nums[0].get("suffix") else "%"
            token = (str(int(round(val))) if abs(val - round(val)) < 1e-9
                     else f"{val:g}")
            fill = val if 0.0 <= val <= 100.0 else 100.0
            params = {
                "progress": fill,
                "value": val,
                "label": f"{token}{suffix}",
                "thickness": 12,
            }
        elif name == "star-rating-fill":
            rating = 4.8
            if nums:
                val = float(nums[0]["value"])
                if 0.0 <= val <= 5.0:
                    rating = val
            params = {
                "rating": rating,
                "starCount": 5,
                "showValue": True,
            }
        elif name == "spain-map":
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            regions = [{
                "abbr": str(shape["abbr"]),
                "name": str(shape["name"]),
                "value": float(shape["gdp"]),
            } for shape in SPM_SHAPES]
            if nums:
                ranked = sorted(regions, key=lambda row: -float(row["value"]))
                for index, num in enumerate(nums[:len(ranked)]):
                    ranked[index]["value"] = num["value"]
            params = {
                "title": heading or "PIB per cápita por Comunidad Autónoma",
                "subtitle": "Producto Interior Bruto per cápita, estimación 2024",
                "source": "Fuente: Instituto Nacional de Estadística",
                "regions": regions,
                "highlight": ["MAD", "PVA", "NAV"],
            }
        elif name == "us-map":
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            regions = [{
                "abbr": str(shape["abbr"]),
                "name": str(shape["name"]),
                "value": float(shape["density"]),
            } for shape in USM_SHAPES]
            if nums:
                ranked = sorted(regions, key=lambda row: -float(row["value"]))
                for index, num in enumerate(nums[:len(ranked)]):
                    ranked[index]["value"] = num["value"]
            params = {
                "title": heading or "Population Density by State",
                "subtitle": "Residents per square mile, 2024 Census estimates",
                "source": "Source: U.S. Census Bureau",
                "regions": regions,
                "highlight": ["CA", "NY", "TX", "FL", "NJ"],
            }
        elif name == "us-map-hex":
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            params = {
                "title": heading or "Median Household Income by State",
                "subtitle": "American Community Survey, 2024",
                "source": "Source: U.S. Census Bureau, American Community Survey 2024",
                "highlight": ["MD", "NJ", "MA", "CT", "HI"],
            }
        elif name == "world-map":
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            params = {
                "title": heading or "Global GDP per Capita",
                "subtitle": "Nominal GDP per capita, 2024 IMF estimates",
                "source": "Source: International Monetary Fund",
                "highlight": ["756", "578", "840", "036", "752"],
            }
        elif name == "apple-money-count":
            val = float(nums[0]["value"]) if nums else 10000.0
            params = {"end_value": val, "prefix": "$"}
        elif name == "north-korea-locked-down":
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            params = {"label": heading or "LOCKED DOWN"}
        elif name == "nyc-paris-flight":
            params = {
                "origin": "New York", "dest": "Paris",
                "origin_code": "JFK / NYC", "dest_code": "CDG / FR",
                "km": "5,837",
            }
        elif name == "mk-progress-stat":
            val = float(nums[0]["value"]) if nums else 22.0
            params = {
                "value": int(round(val)),
                "max": max(int(round(val * 1.4)), int(round(val)) + 1),
                "suffix": str(nums[0].get("suffix") or "") if nums else "",
                "label": str(blocks.get(slot["block_id"], {}).get("heading")
                             or "Goals reached"),
                "caption": "Great job, we are getting closer!",
            }
        elif name == "flowchart-vertical":
            params = {
                "root": "Should I learn to code?",
                "branches": ["Yes", "Not sure"],
                "leaves": [
                    "Start with Python", "Try no-code first",
                    "Build a personal website", "Take a free intro course",
                ],
            }
        elif name == "us-map-flow":
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            cities = [{
                "name": str(city["name"]),
                "x": float(city["x"]),
                "y": float(city["y"]),
            } for city in UMF_CITIES]
            flows = [{
                "from": str(flow["from"]),
                "to": str(flow["to"]),
                "volume": float(flow["volume"]),
            } for flow in UMF_FLOWS]
            if nums:
                for index, flow in enumerate(flows):
                    if index >= len(nums):
                        break
                    flow["volume"] = float(nums[index]["value"])
            params = {
                "title": heading or "Interstate Flow Connections",
                "subtitle": "Relative volume of major city-to-city corridors",
                "source": "Source: Illustrative data",
                "cities": cities,
                "flows": flows,
            }
        elif name in ("stat-countup-card", "counter-roll") or len(nums) == 1:
            suffix = f" {nums[0]['suffix']}" if nums[0]["suffix"] else ""
            params: dict[str, Any] = {
                "value": nums[0]["value"], "suffix": suffix,
                "label": nums[0]["raw"],
                "values": [n["value"] for n in nums[:4]],
                "labels": [n["raw"] for n in nums[:4]],
            }
        else:
            n_take = (8 if name == "bar-chart-race"
                      else 6 if name == "mk-line-graph"
                      else 4 if name == "chart-story"
                      else 7 if name == "animated-bar-chart" else 4)
            params = {
                "values": [n["value"] for n in nums[:n_take]],
                "labels": [n["raw"] for n in nums[:n_take]],
                "value": nums[0]["value"],
                "kpi": nums[0]["raw"],
            }
            if name == "bar-chart-race":
                params["value_prefix"] = ""
                params["value_suffix"] = (
                    f" {nums[0]['suffix']}" if nums[0].get("suffix") else "")
                params["title"] = str(
                    blocks.get(slot["block_id"], {}).get("heading")
                    or "Streaming Subscribers by Service")
            if name == "chart-story":
                params["unit"] = (
                    str(nums[0]["suffix"]) if nums[0].get("suffix") else "%")
                params["emphasize"] = len(params["values"]) - 1
            if name == "mk-line-graph":
                heading = str(blocks.get(slot["block_id"], {}).get("heading")
                              or "")
                series = [{
                    "name": heading or "Renders",
                    "values": [n["value"] for n in nums[:n_take]],
                }]
                rest = nums[n_take:n_take * 2]
                if len(rest) >= 2:
                    series.append({
                        "name": "Projects",
                        "values": [n["value"] for n in rest],
                    })
                params["series"] = series
                params["xLabels"] = [n["raw"] for n in nums[:n_take]]
                params["showValues"] = True
        overlays.append({
            "type": "dataviz", "start": start, "end": end,
            "template": template.id, "renderer": template.renderer,
            "params": params,
            "why": "data-viz: в блоке есть число",
        })
        return


def build_variant(ctx, plan: dict[str, Any], words_doc: dict[str, Any],
                  assets: dict[int, dict[str, Any]], prepared: dict[int, dict[str, Any]],
                  catalog: TemplateCatalog, avatar_meta: dict[str, Any],
                  sfx_map: dict[str, Any], *, variant: str,
                  recent_videos: list[str], preferences: dict[str, Any] | None = None,
                  asset_rotation: int = 0,
                  picker: TemplatePicker | None = None) -> dict[str, Any]:
    if picker is None:
        cfg = getattr(ctx, "cfg", None)
        picker = TemplatePicker(catalog, ScenarioIndex.load(cfg, catalog=catalog))
    seed = _variant_seed(plan["video_id"], variant)
    # Какие источники требуют подписи в кадре — сказано в самом каталоге
    # источников, а не в коде: право на кадр приходит вместе с ним.
    sources_spec = _load_yaml(ctx.cfg.repo_root / "config" / "stock_sources.yaml")
    # Накопленные предпочтения влияют на версию A: она несёт «текущий дефолт»,
    # а B остаётся альтернативой, иначе обучение схлопнет обе версии в одну.
    prefs = (preferences or {}) if variant == "A" else {}
    used_templates: list[str] = []
    slots = plan["slots"]
    shots: list[dict[str, Any]] = []

    # Приёмы вокруг ведущего ставятся через один подходящий аватар-кадр: на
    # каждом они превратились бы в заставку, а реже одного на два — потерялись
    # бы. С какого начинать, решает сид варианта, поэтому A и B получают приёмы
    # на разных кадрах, а не один и тот же ролик с другими подписями.
    alpha_slots = _alpha_slots(avatar_meta)
    face_centres = _face_centres(avatar_meta)
    head_boxes = _head_boxes(avatar_meta)
    avatar_bgs = _avatar_bg_plates(slots, prepared, assets)
    compose_zoom = float(ctx.cfg.get("heygen.compose_zoom", 1.0) or 1.0)
    blocks_by_id = {b["id"]: b for b in plan.get("blocks", [])}
    # Dedup on-screen slogans across intentional FS + gap FS (0042: «5 МИНУТ»).
    used_screen_phrases: set[str] = set()
    # Библиотека иконок §14: пилюля бренда берёт логотип оттуда. Её отсутствие
    # не должно валить сборку — приём просто не выпадет.
    try:
        brand_icons = load_brand_icons(ctx.cfg)
    except Exception:                                    # noqa: BLE001
        brand_icons = None
    hero_offset = seed % 2
    hero_eligible = 0

    for slot in slots:
        entry: dict[str, Any] = {
            "index": slot["index"], "start": slot["start"], "end": slot["end"],
            "duration": slot["duration"], "kind": slot["kind"],
            "block_id": slot["block_id"], "role": slot["role"], "mode": slot["mode"],
            "reason": slot["reason"],
        }

        if slot["kind"] == "fullscreen_text":
            preferred = prefs.get(f"fullscreen_text@{slot['role']}")
            content = slot.get("content", "")
            s_content = str(content or "")
            signals = {"lines_ge_7"} if s_content.count("\n") >= 7 else {"lines_lt_7"}
            head = [p for p in (preferred, slot.get("template_hint")) if p]
            template, _ = picker.pick(
                "text-fullscreen",
                blob=s_content,
                signals=signals,
                variant=variant,
                duration=float(slot["duration"]),
                recent_videos=recent_videos,
                exclude=used_templates,
                seed=seed,
                prefer_head=head,
            )
            used_templates.append(template.id)
            content = slot.get("content", "")
            block = blocks_by_id.get(slot["block_id"], {})
            # Фон под текстом — тот же футаж, что и у остальных кадров блока.
            # Раньше слот его не просил, и кадр выходил белыми буквами на
            # пустом чёрном: фраза вынесена крупно, а стоит она ни на чём.
            prep = prepared.get(slot["index"])
            asset = assets.get(slot["index"])
            content = enrich_overlay_punch(str(content or ""), str(block.get("text") or "")) or content
            fs_params = _fullscreen_params(template, content, block)
            key = _norm_screen_key(str(content or ""))
            if key:
                used_screen_phrases.add(key)
            # Never leave intentional FS on empty black: stock plate → scene plate.
            bg_file = prep["dst"] if prep is not None else None
            gap_reason = None
            if bg_file is None:
                plate = _plate_source(slot, slots, prepared, assets)
                if plate and plate.get("file"):
                    bg_file = plate["file"]
                    gap_reason = "фон — ближайший сток блока"
                else:
                    scene_name = pick_scene(
                        str(plan.get("title") or ""),
                        " ".join(str(b.get("text") or "")
                                 for b in plan.get("blocks", [])))
                    plate_path = _backdrop_plate(ctx.cfg, scene_name)
                    if plate_path:
                        bg_file = plate_path
                        gap_reason = "фон — плита сцены ролика"
                    else:
                        gap_reason = "фон под полноэкранный текст не найден"
            entry.update({
                "content": content,
                "template": template.id,
                "renderer": template.renderer,
                "params": fs_params,
                # Light glyphs on dark plates (0042 QA: black hero/fullscreen unreadable).
                "invert": True,
                "accent_word": _fullscreen_accent(content, block),
                "file": bg_file,
                # Full passport for QC-12; credit feeds thin BL caption over media.
                "asset_id": (asset or {}).get("asset_id"),
                "source": (asset or {}).get("source"),
                "license": (asset or {}).get("license"),
                "attribution": (asset or {}).get("attribution", ""),
                "page_url": (asset or {}).get("page_url", ""),
                "ai_generated": bool((asset or {}).get("ai_generated")),
                "credit": _credit_line(asset or {}, sources_spec),
            })
            if gap_reason:
                entry["gap_reason"] = gap_reason
            shots.append(entry)
            continue

        prep = prepared.get(slot["index"])
        asset = assets.get(slot["index"])
        if prep is None or (asset is None and slot["kind"] not in AVATAR_KINDS):
            # Empty slot → spoken-word fullscreen, not a dark brand fill.
            # Live 0042/0047 left multi-second black cards when P7 missed and
            # P9 hit the 35% AI ceiling; Claude 1ff38b2 closed those with text.
            gap_block = blocks_by_id.get(slot["block_id"], {})
            content = gap_phrase(words_doc["words"], slot, gap_block,
                                 used=used_screen_phrases)
            gap_traits = block_traits(str(gap_block.get("text") or "")) if gap_block else set()

            s_content = str(content or "")
            signals = {"lines_ge_7"} if s_content.count("\n") >= 7 else {"lines_lt_7"}
            preferred = prefs.get(f"fullscreen_text@{slot['role']}")
            head = [p for p in (preferred, slot.get("template_hint")) if p]
            template, _ = picker.pick(
                "text-fullscreen",
                blob=s_content or str(gap_block.get("text") or ""),
                signals=signals,
                traits=gap_traits,
                variant=variant,
                duration=float(slot["duration"]),
                recent_videos=recent_videos,
                exclude=used_templates,
                seed=seed + int(slot["index"]),
                prefer_head=head,
            )
            used_templates.append(template.id)
            # Borrow nearest real plate as bg when any footage exists in the cut.
            plate = _plate_source(slot, slots, prepared, assets)
            bg_file = (plate or {}).get("file") if plate else None
            fs_params = _fullscreen_params(template, content, gap_block)
            entry.update({
                "kind": "fullscreen_text",
                "content": content,
                "template": template.id,
                "renderer": template.renderer,
                "params": fs_params,
                "invert": True,
                "accent_word": _fullscreen_accent(content, gap_block),
                "traits": sorted(gap_traits) if gap_traits else [],
                "grounded_on": sorted(matched(template.needs, gap_traits)) if gap_traits else [],
                "why_template": explain_choice(template, gap_traits) if gap_traits else "",
                "file": bg_file,
                "asset_id": None,
                "gap_reason": "материал не найден: кадр закрыт словом блока",
            })
            if bg_file is None:
                entry["gap_reason"] += "; фон — сцена ролика"
            shots.append(entry)
            continue

        kb_template: Template | None = None
        if slot["kind"] in ("footage", "meme"):
            preferred = prefs.get(f"kenburns@{slot['role']}")
            head = [preferred] if preferred else []
            content = slot.get("content", "")
            kb_template, _ = picker.pick(
                "kenburns",
                blob=str(content or ""),
                variant=variant,
                duration=float(slot["duration"]),
                recent_videos=recent_videos,
                exclude=used_templates,
                prefer_head=head,
                seed=seed + slot["index"],
            )
            used_templates.append(kb_template.id)

        transition_entry: dict[str, Any] | None = None
        if slot.get("transition_in") == "dynamic":
            category = "avatar-entry" if slot["kind"] in AVATAR_KINDS else "transitions"
            preferred = prefs.get(f"transition@{slot['role']}")
            head = [preferred] if preferred else []
            tr, _ = picker.pick(
                category,
                variant=variant,
                duration=0.24,
                recent_videos=recent_videos,
                exclude=used_templates + ["transitions/cut"],
                prefer_head=head,
                tags={"dynamic", "entry"},
                seed=seed + slot["index"] * 3,
            )
            used_templates.append(tr.id)
            transition_entry = {
                "template": tr.id, "renderer": tr.renderer,
                "duration": max(0.16, min(0.32, float(tr.duration_range[1] or 0.24))),
                "params": {**tr.params, "seed": seed + slot["index"]},
            }
        else:
            transition_entry = {"template": "transitions/cut", "renderer": "cut",
                                "duration": 0.0, "params": {}}

        asset = asset or {}
        is_avatar = slot["kind"] in AVATAR_KINDS

        hero_entry: dict[str, Any] | None = None
        # Только чистый аватар-кадр. Сплит уже сам монтажный приём: кадр в нём
        # поделён пополам, и панель сбоку или картинка за спиной спорят с этим
        # делением, а не поддерживают его.
        if slot["kind"] == "avatar":
            hero_eligible += 1
            if (hero_eligible + hero_offset) % 2 == 0:
                block = blocks_by_id.get(slot["block_id"], {})
                hero_entry = _hero_device(
                    catalog, slot=slot,
                    content=_hero_content(
                        block, slot, brand_icons,
                        face_centres.get(int(slot["index"])),
                        title=str(plan.get("title") or ""),
                        words=[w for w in words_doc["words"]
                               if float(w["end"]) > float(slot["start"])
                               and float(w["start"]) < float(slot["end"])],
                        head_box=head_boxes.get(int(slot["index"]))),
                    has_alpha=int(slot["index"]) in alpha_slots,
                    plate_src=_plate_source(slot, slots, prepared, assets),
                    recent_videos=recent_videos, exclude=used_templates,
                    seed=seed, picker=picker, variant=variant, block=block)
                if hero_entry:
                    used_templates.append(hero_entry["template"])

        entry.update({
            "file": prep["dst"],
            "bg_file": (avatar_bgs.get(int(slot["index"]))
                        if slot["kind"] == "avatar"
                        and int(slot["index"]) in alpha_slots else None),
            "asset_id": asset.get("asset_id") or (f"avatar_seg_{prep.get('avatar_segment')}"
                                                  if is_avatar else None),
            "source": "heygen" if is_avatar else asset.get("source"),
            "license": ("HeyGen ToS (цифровой двойник заказчика)" if is_avatar
                        else asset.get("license")),
            "attribution": asset.get("attribution", ""),
            "credit": _credit_line(asset, sources_spec),
            "page_url": asset.get("page_url", ""),
            "avatar_offset_sec": prep.get("avatar_offset_sec"),
            "matte": prep.get("matte"),
            "background": prep.get("background"),
            # Приём на кадре отменяет слово за головой (§5.3): панель за спиной
            # перекрывает его, оставляя торчать одну букву, лучи ложатся
            # поверх, заголовок добавляет к нему третий текст, а сплит и
            # выбивка уводят ведущего с места, к которому слово привязано.
            # Слово остаётся на аватар-кадрах без приёма — их всегда половина.
            "text_behind_head": bool(prep.get("text_behind_head")) and not hero_entry,
            "ai_generated": bool(asset.get("ai_generated")),
            "mock": bool(asset.get("mock")),
            "fit": prep.get("fit"), "focus": [prep.get("focus_x"), prep.get("focus_y")],
            "kenburns": ({"template": kb_template.id, **kb_template.params}
                         if kb_template else None),
            "transition": transition_entry,
            "hero": hero_entry,
        })
        shots.append(entry)

    overlays = _build_overlays(ctx, plan, words_doc["words"], catalog, variant=variant,
                               seed=seed, recent_videos=recent_videos, used=used_templates,
                               picker=picker)

    # Субтитры: весь ролик, кроме кадров с полноэкранным текстом (§5.1).
    fs_windows = [(float(s["start"]), float(s["end"])) for s in slots
                  if s["kind"] == "fullscreen_text"]
    for shot in shots:
        hero = shot.get("hero") or {}
        if not (hero.get("carries_line") or hero.get("covers_frame")):
            continue
        # Приём со своей длиной глушит субтитр только на своём окне: плашка на
        # 1.8 сек внутри четырёхсекундного кадра забрала бы все четыре.
        end = float(shot["end"])
        if hero.get("duration"):
            end = min(end, float(shot["start"]) + float(hero["duration"]))
        fs_windows.append((float(shot["start"]), end))
    # Bulky source/browser cards own the frame; word captions collide with them.
    _BULKY_OVL = {"source_card", "browser", "chatgpt_exchange", "claude_exchange",
                  "ai_chat_reveal", "app_showcase", "dataviz"}
    for ovl in overlays:
        kind = str(ovl.get("type") or "")
        renderer = str(ovl.get("renderer") or "")
        if kind in _BULKY_OVL or renderer in _BULKY_OVL:
            fs_windows.append((float(ovl["start"]), float(ovl["end"])))
    subtitles = []
    for word in words_doc["words"]:
        start, end = float(word["start"]), float(word["end"])
        # Отбрасываем по пересечению, а не по началу: слово, начавшееся до
        # склейки и дожившее до неё, оставалось висеть поверх полноэкранного
        # текста. Видно на кадре готового MP4 — «ты» поверх «ПЕРЕЖИВЁШЬ».
        if any(start < w_end and end > w_start for w_start, w_end in fs_windows):
            continue
        subtitles.append({
            "display": word["display"], "start": start, "end": end,
            "emphasis": bool(word.get("emphasis")), "block_id": word["block_id"],
        })
    # Склейка — после отбраковки, а не до: слово, снятое полноэкранным текстом,
    # не имеет права утащить с собой приклеенный к нему предлог.
    subtitles = glue_short_cues(subtitles)

    # Сцена фона — по теме ролика целиком: заголовок плюс все реплики. Фон
    # держится весь ролик и посреди него не меняется.
    scene = pick_scene(str(plan.get("title") or ""),
                       " ".join(str(b.get("text") or "")
                                for b in plan.get("blocks", [])))

    return {
        "video_id": plan["video_id"],
        "variant": variant,
        "fps": plan["fps"],
        "resolution": list(ctx.cfg.resolution),
        "duration_sec": plan["duration_sec"],
        "audio": {"mix": "mix.wav", "voice": "voice_final.wav",
                  "music_bed": "music_bed.wav", "sfx_map": "sfx_map.json",
                  "loudness": sfx_map.get("loudness", {})},
        "shots": shots,
        "overlays": overlays,
        "subtitles": subtitles,
        "backdrop": {"scene": scene, "tone": scene_tone(scene),
                     "why": scene_why(scene),
                     "plate": _backdrop_plate(ctx.cfg, scene)},
        "subtitle_style": {
            "mode": ctx.cfg.brand("subtitles.readability_mode", "stroke"),
            "baseline_y": ctx.cfg.brand("subtitles.baseline_y_default", 1180),
            "caption": pick_caption_style(plan, ctx.cfg.brandbook),
        },
        "avatar_compose_zoom": compose_zoom,
        "avatar": avatar_meta.get("segments", []),
        "templates_used": used_templates,
        "asset_rotation": asset_rotation,
        "preferences_applied": sorted(prefs) if prefs else [],
        "cta_window": plan.get("cta_window"),
        "stats": plan.get("stats", {}),
    }



def _force_ab_difference(plans: dict[str, dict[str, Any]], variants: list[str],
                         catalog: TemplateCatalog, required: int, ctx) -> int:
    """§15.12.2 — довести различие версий до требуемого **конструктивно**.

    Полагаться на то, что разные сиды сами дадут три различия, нельзя: пул
    шаблонов категории конечен, а предпочтения тянут версию A к устоявшимся
    вариантам. Когда различий не хватает, версия B получает другие шаблоны там,
    где это ничего не ломает: Ken Burns, переходы и оформление полноэкранного
    текста взаимозаменяемы внутри своей категории.
    """
    a_plan, b_plan = plans[variants[0]], plans[variants[1]]
    diff = diff_count(a_plan["templates_used"], b_plan["templates_used"])
    if diff >= required:
        return diff

    a_templates = set(a_plan["templates_used"])
    swapped = 0
    for shot in b_plan["shots"]:
        if diff + swapped >= required:
            break
        for field, category in (("kenburns", "kenburns"), ("transition", "transitions")):
            current = shot.get(field)
            if not current or not current.get("template"):
                continue
            if current["template"] not in a_templates:
                continue          # здесь версии уже расходятся
            alternatives = [t for t in catalog.by_category(category)
                            if t.id not in a_templates
                            and t.id not in b_plan["templates_used"]
                            and t.fits(float(shot["duration"]) if category == "kenburns" else 0.24)]
            if not alternatives:
                continue
            replacement = alternatives[0]
            old_id = current["template"]
            if field == "kenburns":
                shot["kenburns"] = {"template": replacement.id, **replacement.params}
            else:
                shot["transition"] = {
                    "template": replacement.id, "renderer": replacement.renderer,
                    "duration": current.get("duration", 0.24),
                    "params": {**replacement.params, "seed": shot["index"]},
                }
            b_plan["templates_used"] = [
                replacement.id if t == old_id else t for t in b_plan["templates_used"]]
            swapped += 1
            break

    diff = diff_count(a_plan["templates_used"], b_plan["templates_used"])
    if swapped:
        ctx.warn(f"версии сошлись по шаблонам: {swapped} решений версии B заменены "
                 f"альтернативами, различий стало {diff} (§15.12.2)",
                 swapped=swapped, diff=diff)
    return diff


def run_step(ctx) -> dict[str, Any]:
    plan = ctx.read("cut_plan.json")
    words_doc = ctx.read("words.json")
    accepted_doc = ctx.read("accepted_assets.json")
    generated_doc = ctx.read("generated_assets.json")
    avatar_meta = ctx.read_or("avatar_meta.json", {"segments": []})
    sfx_map = ctx.read_or("sfx_map.json", {})
    catalog = TemplateCatalog.load(ctx.cfg)
    picker = TemplatePicker(catalog, ScenarioIndex.load(ctx.cfg, catalog=catalog))

    accepted = accepted_doc.get("accepted", {})
    generated = generated_doc.get("generated", {})
    base_assets: dict[int, dict[str, Any]] = {}
    for slot in plan["slots"]:
        asset = _asset_for_slot(slot, accepted, generated)
        if asset is not None:
            base_assets[slot["index"]] = asset

    recent_videos = _recent_video_ids(ctx, limit=3)
    pillarbox_limit = int(ctx.cfg.get("limits.pillarbox_per_video", 2))
    preferences = _load_preferences(ctx)
    matte_reports, behind_layers, vfx_clips, matte_summary = _prepare_matting(
        ctx, plan, avatar_meta)

    variants = list(ctx.variants)
    plans: dict[str, dict[str, Any]] = {}
    for offset, variant in enumerate(variants):
        # Потолок доли AI считается по экранному времени — там же, где его
        # меряет QC-14. Иначе ротация версии B выносит за него ролик, за
        # который уже заплачены и голос, и аватар, и генерация.
        ai_budget = float(ctx.cfg.get("limits.ai_footage_share_max", 0.35)) * \
            float(plan["duration_sec"])
        assets = _rotate_assets(plan["slots"], base_assets, shift=offset,
                                ai_budget_sec=ai_budget)
        prepared = _prepare_shots(ctx, plan["slots"], assets, pillarbox_limit,
                                  avatar_segments=avatar_meta.get("segments", []),
                                  matte_reports=matte_reports,
                                  behind_layers=behind_layers if variant == "A" else {},
                                  vfx_clips=vfx_clips if variant == "A" else {})
        plans[variant] = build_variant(
            ctx, plan, words_doc, assets, prepared, catalog, avatar_meta, sfx_map,
            variant=variant, recent_videos=recent_videos,
            preferences=preferences, asset_rotation=offset, picker=picker)
        plans[variant]["matting"] = matte_summary
        ctx.write(f"edit_plan_{variant}.json", plans[variant])

    # §15.12.2 — версии обязаны различаться минимум на 3 шаблонных позиции.
    ab_diff = None
    if len(variants) >= 2:
        required = int(ctx.cfg.get("limits.ab_min_template_diff", 3))
        ab_diff = _force_ab_difference(plans, variants, catalog, required, ctx)
        if ab_diff < required:
            raise RedshiftError(
                f"версии {variants[0]} и {variants[1]} различаются лишь {ab_diff} "
                f"шаблонными решениями, требуется {required}; альтернатив в каталоге "
                f"не нашлось (§15.12.2)",
                code="AB_TOO_SIMILAR", diff=ab_diff, required=required,
                a=plans[variants[0]]["templates_used"],
                b=plans[variants[1]]["templates_used"])
        for variant in variants:
            ctx.write(f"edit_plan_{variant}.json", plans[variant])

    catalog.mark_used(
        {t for variant in plans.values() for t in variant["templates_used"]},
        plan["video_id"])
    catalog.save()

    _log.info("edit-планы собраны", extra={
        "variants": ",".join(variants),
        "shots": len(plans[variants[0]]["shots"]),
        "overlays": len(plans[variants[0]]["overlays"]),
        "subtitles": len(plans[variants[0]]["subtitles"]),
        "ab_template_diff": ab_diff,
    })
    return {"variants": variants, "ab_template_diff": ab_diff,
            "shots": len(plans[variants[0]]["shots"]),
            "matting": {"enabled": matte_summary["enabled"],
                        "degraded": matte_summary.get("degraded"),
                        "text_behind_head": len(matte_summary["text_behind_head"]),
                        "vfx": len(matte_summary["vfx"])}}


def _load_preferences(ctx) -> dict[str, Any]:
    """Накопленные предпочтения монтажа (§4.5): «в ситуации X выбран вариант Y»."""
    from ..lib.jsonio import read_json_or

    prefs = read_json_or(ctx.cfg.repo_root / "config" / "editing_preferences.json", {})
    defaults = prefs.get("defaults", {}) or {}
    # Берём только ситуации вида "<решение>@<роль>": остальные ключи —
    # общие настройки, а не выбор конкретного шаблона.
    return {k: v for k, v in defaults.items() if "@" in str(k) and isinstance(v, str)}


def _recent_video_ids(ctx, *, limit: int = 3) -> list[str]:
    from ..lib.jsonio import read_json_or

    history = read_json_or(ctx.cfg.path("paths.cache_dir", "cache") / "run_history.json",
                           {"runs": []})
    return [r.get("video_id") for r in history.get("runs", [])][-limit:]
