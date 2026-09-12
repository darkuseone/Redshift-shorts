"""P11: предыдущие шаги → ``edit_plan_A.json`` (одна версия монтажа).

Edit-план — самодостаточный документ: §9.1 требует, чтобы по нему можно было
**пересобрать ролик один в один без обращений к внешним API**. Поэтому в нём
лежат локальные пути подготовленных планов, все параметры анимации, тексты
оверлеев и пословные тайминги — ничего не догружается на рендере.

Версия B не собирается: один edit-план, один mp4.
"""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..errors import RedshiftError
from ..lib.beats import annotate_slots
from ..lib.ffmpeg import probe
from ..lib.logging import get_logger
from ..lib.render.avatar_compose import fit_compose_zoom
from ..lib.render.matting import assess_matte, plan_vfx_backgrounds, try_local_matting
from ..lib.render.shots import (
    ShotSpec, choose_fit, detect_focus, prepare_avatar_shot, prepare_shot,
    prepare_split_shot,
)
from ..lib.render.text_rules import drop_orphan_short_cues, glue_short_cues
from ..lib.backdrop import load_pins as _load_backdrop_pins
from ..lib.backdrop import plate_name as _scene_plate_name
from ..lib.brand_icons import load_library as load_brand_icons
from ..lib.backdrop import describe as scene_why
from ..lib.backdrop import pick_scene
from ..lib.backdrop import tone as scene_tone
from ..lib.text import (
    accent_card_start, enrich_overlay_punch, find_spoken_anchor,
    is_latin_overlay_label, punch_families_overlap, soften_on_screen_copy,
    spoken_onset_for_content,
    stems_match, sync_broll_from_script, sync_overlays_from_script,
)
from ..lib.glyphs import match_glyphs
from ..lib.meaning import block_traits, explain, grounded_for, matched
from ..lib.query import topical_match_score
from ..lib.render.canvas import plaque_enter_ms
from ..lib.render.hyperframes.captions import group_caption_phrases, pick_caption_style
from ..lib.render.hyperframes.spm_shapes import SPM_SHAPES
from ..lib.render.hyperframes.umf_shapes import UMF_CITIES, UMF_FLOWS
from ..lib.render.hyperframes.usm_shapes import USM_SHAPES
from ..lib.templates import TemplateCatalog, Template, diff_count
from ..lib.template_picker import ScenarioIndex, TemplatePicker, build_blob
from ..lib.pin_match import overlapping_speech

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
# White disk of circle-mask-grow sits opaque on the presenter's face.
AVATAR_ENTRY_DENY = ("avatar-entry/circle-mask-grow",)
# Full-frame accent card. QC-30 samples the CTA shot head; this wipe is 77 % red.
CTA_TRANSITION_DENY = (
    "transitions/mk-clone-wall-transition",
    "transitions/transitions-cover",
    "transitions/transitions-3d",
    "transitions/transitions-other",
)


def degrade_split_without_top(slot: dict[str, Any]) -> dict[str, Any]:
    """Mode B with no upper B-roll → mode A. No empty blue void."""
    slot["kind"] = "avatar"
    slot["mode"] = "A"
    slot["needs_asset"] = False
    slot["asset_role"] = ""
    slot["reason"] = "split degraded to A: no upper B-roll"
    return slot


def _transition_exclude(category: str, used: list[str], *, role: str = "") -> list[str]:
    """Exclude list for the transition picker; avatar-entry hard-denies the white disk.

    The CTA shot starts where QC-30's last file probe lands (~11/12 of the
    cut). Clone-wall paints a brand-red card over that frame; keep it off
    the identity close so the ticker stays the picture.
    """
    extra = list(AVATAR_ENTRY_DENY) if category == "avatar-entry" else []
    if str(role or "") == "cta":
        extra.extend(CTA_TRANSITION_DENY)
    return list(used) + ["transitions/cut"] + extra


_FACE_ZONE_BOTTOM = 1080
_COMPACT_CARD_MIN_PX = 260
_LATIN_COPY_RATIO = 0.60
_DOMAIN_OR_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+(?:/.*)?$",
    re.I,
)


def _is_url_or_domain(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    if "://" in s:
        return True
    if " " in s:
        return False
    return bool(_DOMAIN_OR_URL.match(s))


def _latin_heavy_copy(text: str, *, threshold: float = _LATIN_COPY_RATIO) -> bool:
    """True when on-screen copy is mostly Latin letters and not a URL/domain."""
    raw = str(text or "").strip()
    if not raw or _is_url_or_domain(raw):
        return False
    letters = [ch for ch in raw if ch.isalpha()]
    if not letters:
        return False
    latin = sum(1 for ch in letters if ch.isascii())
    return (latin / len(letters)) >= threshold


def _on_screen_copy(text: str, *, field: str) -> str:
    """Drop Latin-majority overlay strings; keep URLs/domains and Cyrillic."""
    raw = str(text or "")
    if _latin_heavy_copy(raw):
        _log.warning("latin overlay copy dropped", extra={
            "field": field, "text": raw[:80]})
        return ""
    return raw


_SOURCE_COPY_FIELDS = (
    "title", "snippet", "highlight_line", "proof_card", "domain", "url",
    "published",
)


_OVERLAY_COPY_KEYS = (
    "content", "highlight_line", "snippet", "text", "highlight",
    "proof_card", "on_screen", "code", "code_before", "code_after",
    "before", "after", "filename",
)


def _script_source_corpus(plan: dict[str, Any]) -> str:
    """Union of spoken blocks and authored source fields (MUST-015 / MUST-004)."""
    chunks: list[str] = []
    meta_hook = (plan.get("meta") or {}).get("hook") or {}
    if isinstance(meta_hook, dict):
        chunks.append(str(meta_hook.get("on_screen") or ""))
    plan_hook = plan.get("hook") or {}
    if isinstance(plan_hook, dict):
        chunks.append(str(plan_hook.get("on_screen") or ""))
    for block in plan.get("blocks") or []:
        chunks.append(str(block.get("text") or ""))
        chunks.append(str(block.get("emphasis_word") or ""))
        overlay = block.get("overlay") or {}
        for key in _OVERLAY_COPY_KEYS:
            chunks.append(str(overlay.get(key) or ""))
    for source in plan.get("sources") or []:
        for key in _SOURCE_COPY_FIELDS:
            chunks.append(str(source.get(key) or ""))
    return "\n".join(chunks)


def _copy_from_script_or_source(text: str, corpus: str) -> str:
    """Keep card/terminal copy only when it already lives in script ∪ sources."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw in corpus or raw.lower() in corpus.lower():
        return raw
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) > 1 and all(
            ln in corpus or ln.lower() in corpus.lower() for ln in lines):
        return raw
    return ""


def _block_copy_corpus(block: dict[str, Any], *extras: str,
                       plan: dict[str, Any] | None = None) -> str:
    """Local script ∪ source union for one block (MUST-004)."""
    overlay = block.get("overlay") if isinstance(block.get("overlay"), dict) else {}
    chunks = [
        str(block.get("text") or ""),
        str(block.get("emphasis_word") or ""),
        *[str(overlay.get(k) or "") for k in _OVERLAY_COPY_KEYS],
        *[str(x or "") for x in extras],
    ]
    if plan is not None:
        chunks.append(_script_source_corpus(plan))
    return "\n".join(chunks)


_ON_SCREEN_PARAM_KEYS = (
    "content", "text", "code", "code_before", "code_after", "before", "after",
    "filename", "highlight_line", "highlight", "snippet", "proof_card",
    "title", "subtitle", "word", "body", "label", "name", "message",
    "message1", "brandText", "prompt",
)


def overlay_on_screen_text(*nodes: dict[str, Any]) -> str:
    """Flatten on-screen copy fields from shots/overlays for tests and QC."""
    chunks: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        chunks.append(str(node.get("content") or ""))
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        for key in _ON_SCREEN_PARAM_KEYS:
            chunks.append(str(params.get(key) or ""))
        hero = node.get("hero") if isinstance(node.get("hero"), dict) else {}
        hero_params = hero.get("params") if isinstance(hero.get("params"), dict) else {}
        for key in _ON_SCREEN_PARAM_KEYS:
            chunks.append(str(hero.get(key) or ""))
            chunks.append(str(hero_params.get(key) or ""))
    return "\n".join(chunks)


def _overlay_enter_ms(ctx, requested: float | None = None) -> int:
    brandbook = None
    cfg = getattr(ctx, "cfg", None) if ctx is not None else None
    if cfg is not None:
        brandbook = getattr(cfg, "brandbook", None)
    return plaque_enter_ms(requested, brandbook=brandbook)


def _stamp_card_enter(ovl: dict[str, Any], enter_ms: int) -> dict[str, Any]:
    """Write brandbook enter onto the overlay that lands in edit_plan."""
    ms = int(enter_ms)
    ovl["enter_ms"] = ms
    ovl["enter_sec"] = round(ms / 1000.0, 3)
    params = dict(ovl.get("params") or {})
    params["enter_ms"] = ms
    ovl["params"] = params
    return ovl


# Заголовок карточки источника: сколько слов помещается в строку А по §7.3
# («акцентное слово + подпись ≤ 6 слов»). Шесть — верхняя граница подписи;
# заголовок берём той же меры, чтобы карточка не превращалась в абзац.
_CARD_HEADLINE_WORDS = 6


def _russian_headline(source: dict[str, Any]) -> str:
    """Русский заголовок карточки источника (§7.3, Q3.5).

    До этой правки латинский заголовок просто выбрасывался
    (`_on_screen_copy`), и карточка оставалась без строки А — «Quantum error
    correction…» уходил в лог, а на экране не появлялось ничего. Теперь
    английский заголовок не занимает первую строку **никогда**: его место —
    домен внизу карточки, а строку А держит русский `snippet`, обрезанный до
    меры подписи.
    """
    title = str(source.get("title") or "").strip()
    if title and not _latin_heavy_copy(title):
        return title
    snippet = str(source.get("snippet") or "").strip()
    if not snippet:
        return ""
    # Первое предложение целиком, если оно короткое; иначе — первые слова.
    lead = re.split(r"(?<=[.!?])\s+", snippet)[0].strip()
    words = [w for w in lead.split() if w]
    if len(words) <= _CARD_HEADLINE_WORDS:
        return lead.rstrip(".")
    return " ".join(words[:_CARD_HEADLINE_WORDS]).rstrip(",;:") + "…"


def _source_card_room_px(brandbook: dict[str, Any] | None) -> int:
    """Pixels between the face-zone floor and the subtitle-pinned card bottom.

    Card is bottom-anchored at subtitle_top and grows up. If that span is
    smaller than ``_COMPACT_CARD_MIN_PX``, skip the bulky card.
    """
    if not brandbook:
        return 0
    subs = brandbook.get("subtitles") or {}
    size = subs.get("size_px") or [84, 104]
    size_hi = int(size[1] if isinstance(size, (list, tuple)) and len(size) > 1
                  else (size[0] if size else 104))
    subtitle_top = int(subs.get("baseline_y_avatar_shift")
                       or subs.get("baseline_y_default", 1180)) - size_hi // 2 - 30
    face_floor = int(((brandbook.get("avatar") or {}).get("face_band_y")
                      or [_FACE_ZONE_BOTTOM, 1480])[0])
    return int(subtitle_top - face_floor)


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
    "DROP", "HARD", "CUT", "FREEZE", "LIVE", "BEAT", "RAMP",
    "HARD CUT", "MUSIC PROMO", "ON THE BEAT", "NEXT SHOT", "VO BEAT",
    "Beat-locked", "BEAT-LOCKED",
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


def _rich_terminal_copy(block: dict[str, Any], phrase: str,
                        *, plan: dict[str, Any] | None = None
                        ) -> tuple[str, str, str]:
    """Terminal copy ⊆ script ∪ sources. No invented scientific identifiers.

    code_diff / code_morph / code_highlight used to pad a short punch
    («5 МИНУТ») with ``# willow_check`` / ``load surface_code``. Those
    tokens are not in the VO or sources — they must not reach the frame.
    Authored overlay.code_* wins; otherwise the spoken/on-screen phrase
    itself is the snippet. Empty → caller drops the code template.
    """
    overlay = block.get("overlay") if isinstance(block.get("overlay"), dict) else {}
    corpus = _block_copy_corpus(block, phrase, plan=plan)

    def keep(raw: str) -> str:
        return _copy_from_script_or_source(str(raw or ""), corpus)

    before = keep(overlay.get("code_before") or overlay.get("before") or "")
    after = keep(overlay.get("code_after") or overlay.get("after") or "")
    code = keep(overlay.get("code") or "")
    filename = keep(overlay.get("filename") or "")
    punch = keep(phrase) or keep(_semantic_screen_text(block))
    if before or after:
        return before or punch, after or before or punch, filename
    if code:
        return code, code, filename
    if punch:
        return punch, punch, filename
    return "", "", ""



def _attach_fs_media(fs_params: dict[str, Any], bg_file: str | None) -> dict[str, Any]:
    """Optional in-card footage/image thumb for informative phrase cards."""
    if bg_file and (fs_params.get("slam") or fs_params.get("card")
                    or fs_params.get("scale_from")):
        fs_params = dict(fs_params)
        fs_params.setdefault("media", str(bg_file))
    return fs_params


def _fullscreen_params(template: Any, content: str,
                       block: dict[str, Any] | None = None,
                       plan: dict[str, Any] | None = None) -> dict[str, Any]:
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
    # Семейство акцента едет в параметры приёма: красит слово рендерер, а не
    # план, и без этого поля cyan оставался токеном в JSON.
    params["accent_family"] = accent_family(block)
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

    # Code templates: only script ∪ source copy. Short slogans stay slogans;
    # catalog demo code is not «enriched» with invented terminal identifiers.
    # Empty → drop code flags so the renderer returns Piece().
    if (params.get("code_diff") or params.get("code_highlight")
            or params.get("code") or params.get("code_morph")):
        corpus = _block_copy_corpus(block, phrase, plan=plan)
        catalog_code = str(
            params.get("code_before") or params.get("code_after")
            or params.get("code") or params.get("before")
            or params.get("after") or "")
        grounded_catalog = _copy_from_script_or_source(catalog_code, corpus)
        before, after, filename = _rich_terminal_copy(block, phrase, plan=plan)
        if before or after:
            params["code_before"] = before
            params["code_after"] = after
            params["code"] = (
                f"{before}\n---\n{after}" if before != after else (before or after)
            )
            params["text"] = after or before
            if filename:
                params["filename"] = filename
            else:
                params.pop("filename", None)
        elif grounded_catalog:
            params["code"] = grounded_catalog
            params.pop("filename", None)
        elif phrase:
            params["code"] = phrase
            params["code_before"] = phrase
            params["code_after"] = phrase
            params["text"] = phrase
            params.pop("filename", None)
        else:
            params.pop("code_diff", None)
            params.pop("code_highlight", None)
            params.pop("code_morph", None)
            params.pop("filename", None)
            params.pop("code", None)
            params.pop("code_before", None)
            params.pop("code_after", None)
            params.pop("before", None)
            params.pop("after", None)
        for key in ("code_before", "code_after", "before", "after",
                    "filename"):
            kept = _copy_from_script_or_source(str(params.get(key) or ""), corpus)
            if kept:
                params[key] = kept
            else:
                params.pop(key, None)
        before_g = str(params.get("code_before") or params.get("before") or "")
        after_g = str(params.get("code_after") or params.get("after") or "")
        if before_g or after_g:
            params["code"] = (
                f"{before_g}\n---\n{after_g}" if before_g != after_g
                else (before_g or after_g)
            )
        else:
            kept = _copy_from_script_or_source(str(params.get("code") or ""), corpus)
            if kept:
                params["code"] = kept
            else:
                params.pop("code", None)

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


def _backdrop_plate(cfg, scene: str, *, video_id: str = "",
                    category: str = "") -> str:
    """Путь к плите сцены — или пусто, если её нет на диске.

    Проверка существования не формальность: имя плиты записано в
    :mod:`src.lib.backdrop`, а сам файл живёт в ассетах, и разъехаться они
    могут. Пустая строка честнее ссылки в никуда — сцена нарисуется
    градиентами, как и задумано запасным путём.

    Закрепления (`config/backdrop_pins.json`, §7.6) читаются здесь, а не в
    самом словаре сцен: подбор сцены — про смысл текста, закрепление — про
    решение заказчика, и смешивать их в одной таблице значило бы потерять,
    что именно сработало.
    """
    try:
        pins = _load_backdrop_pins(cfg.repo_root)
    except Exception:                                    # noqa: BLE001
        pins = {}
    name = _scene_plate_name(scene, video_id=video_id, category=category, pins=pins)
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


def _slot_compose_fit(ctx, slot: dict[str, Any], segment: dict[str, Any] | None,
                      width: int, height: int):
    """MUST-009: requested compose_zoom clamped to face_band / captions."""
    requested = float(ctx.cfg.get("heygen.compose_zoom", 1.0) or 1.0)
    mode = "B" if slot.get("kind") == "split" or slot.get("mode") == "B" else "A"
    box = (segment or {}).get("face_bbox")
    return fit_compose_zoom(
        box, requested, brandbook=ctx.cfg.brandbook,
        width=width, height=height, mode=mode)


def _gaze_plaque_copy(plan: dict[str, Any]) -> str:
    """Gaze mask card: script/source fields only. Not a regex on one noun."""
    for blob in (plan.get("hook"), (plan.get("meta") or {}).get("hook")):
        if isinstance(blob, dict):
            on_screen = str(blob.get("on_screen") or "").strip()
            if on_screen:
                return on_screen.upper()
    for block in plan.get("blocks") or []:
        if block.get("role") != "hook":
            continue
        overlay = block.get("overlay") if isinstance(block.get("overlay"), dict) else {}
        content = str(overlay.get("content") or "").strip()
        if content:
            return content.upper()
    for source in plan.get("sources") or []:
        if not isinstance(source, dict):
            continue
        for key in ("highlight_line", "snippet"):
            line = str(source.get(key) or "").strip()
            if line:
                return " ".join(line.split()[:6]).upper()
    return "ФАКТ"


def show_subscribe_cta(plan: dict[str, Any]) -> bool:
    """Subscribe XOR loop-вопрос: не оба сразу."""
    if plan.get("show_subscribe") is False:
        return False
    meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
    if meta.get("cta") is False or meta.get("show_subscribe") is False:
        return False
    cta = plan.get("cta") if isinstance(plan.get("cta"), dict) else {}
    kind = str(cta.get("type") or "")
    if kind in {"open_question", "visual_loop_seam", "part2_cliff"}:
        return False
    if plan.get("loop_seam"):
        return False
    return True


def gaze_plaque_fits_face_band(brandbook: dict[str, Any] | None) -> bool:
    """Top note-pin sits on the eyes when the face already lives in the lower third.

    The gaze card was a mask for a centred talking head. With
    ``avatar.face_band_y`` starting at 1080 the same «top» plaque lands on
    the mouth. Skip it there; keep it when the face still sits above the
    lower third. Missing brandbook follows the channel default (lower third).
    """
    band = ((brandbook or {}).get("avatar") or {}).get("face_band_y") or [1080, 1480]
    try:
        return int(band[0]) < 900
    except (TypeError, ValueError, IndexError):
        return False


def wants_gaze_plaque(plan: dict[str, Any]) -> bool:
    """Gaze plaque if look-at/gaze is set or an evidence card is in the script."""
    def flagged(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        return bool(node.get("gaze") or node.get("look_at") or node.get("look-at"))

    if flagged(plan) or flagged(plan.get("hook")) or flagged(plan.get("meta")):
        return True
    for block in plan.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        if flagged(block):
            return True
        if block.get("role") != "evidence":
            continue
        overlay = block.get("overlay") if isinstance(block.get("overlay"), dict) else {}
        otype = str(overlay.get("type") or "")
        if block.get("source_ref") or otype in (
                "highlight", "frame", "lower_third", "source_card"):
            return True
    return False


def _is_nasa_asset(asset: dict[str, Any] | None) -> bool:
    """NASA stills/clips are off-topic for quantum/AI cuts (0042 S74 still)."""
    if not asset:
        return False
    aid = str(asset.get("asset_id") or "")
    src = str(asset.get("source") or "").lower()
    return aid.startswith("nasa_") or src == "nasa"


def _is_ticker_asset(asset: dict[str, Any] | None) -> bool:
    """Stock ticker is a money/CTA plate, not a generic empty-slot fill."""
    if not asset:
        return False
    aid = str(asset.get("asset_id") or "")
    tags = [str(t).lower() for t in (asset.get("tags") or [])]
    return "38431825" in aid or "ticker" in tags or "finance" in tags


def _slot_wants_ticker(slot: dict[str, Any]) -> bool:
    role = str(slot.get("role") or "")
    intent = str(slot.get("visual_intent") or "").lower()
    return role == "cta" or "деньг" in intent or "подписк" in intent


def _plate_source(slot: dict[str, Any], slots: list[dict[str, Any]],
                  prepared: dict[int, dict[str, Any]],
                  assets: dict[int, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Nearest real (non-AI, non-NASA) footage for hero/fullscreen plates.

    Only same-block neighbors may fill an empty footage shot — never clone
    weather/wing/etc. from b5b onto b4/b5. NASA archive stills are skipped —
    empty slots take a brand plate instead. AI-only pools return None — heroes
    then skip plate templates.
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
            if _is_ai(s) or _is_nasa_asset(assets.get(int(s["index"]))):
                continue
            if (_is_ticker_asset(assets.get(int(s["index"])))
                    and not _slot_wants_ticker(slot)):
                continue
            out.append(s)
        return out

    pool = _pool(True)
    if not pool:
        return None
    nearest = min(pool, key=lambda s: (abs(int(s["index"]) - index), int(s["index"])))
    prep = prepared[int(nearest["index"])]
    # Credit travels with the plate asset so exhibit/BL caption name the frame shown.
    asset = assets.get(int(nearest["index"])) or {}
    credit = str(asset.get("attribution") or asset.get("source") or "").strip()
    return {"file": prep["dst"], "duration_sec": float(prep.get("duration_sec") or 0.0),
            "credit": credit, "ai_generated": bool(asset.get("ai_generated"))}


def _brand_plate_file(ctx, plan: dict[str, Any]) -> str | None:
    """Scene backdrop or procedural grid — never a NASA still."""
    scene_name = pick_scene(
        str(plan.get("title") or ""),
        " ".join(str(b.get("text") or "") for b in plan.get("blocks", [])))
    plate_path = _backdrop_plate(ctx.cfg, scene_name)
    if plate_path:
        return plate_path
    assets_dir = ctx.cfg.path("paths.assets_dir", "assets")
    for name in ("grid.jpg", "horizon.jpg"):
        cand = assets_dir / "backdrops" / name
        if cand.exists():
            return str(cand)
    return None


def _slot_bg_file(slot: dict[str, Any], slots: list[dict[str, Any]],
                  prepared: dict[int, dict[str, Any]],
                  assets: dict[int, dict[str, Any]], ctx, plan: dict[str, Any]
                  ) -> str | None:
    """Prepared dst, nearest non-NASA plate, or a brand grid — never invent text."""
    inherit = slot.get("inherit_from")
    if inherit is not None:
        inherited = prepared.get(int(inherit))
        if inherited is not None and inherited.get("dst"):
            return str(inherited["dst"])
    prep = prepared.get(slot["index"])
    if prep is not None and prep.get("dst"):
        asset = assets.get(slot["index"])
        if not _is_nasa_asset(asset) and (
                _slot_wants_ticker(slot) or not _is_ticker_asset(asset)):
            return prep["dst"]
    plate = _plate_source(slot, slots, prepared, assets)
    if plate and plate.get("file"):
        return str(plate["file"])
    return _brand_plate_file(ctx, plan)


def _fullscreen_cap(cfg) -> int:
    rng = [2, 4]
    if cfg is not None:
        try:
            rng = cfg.get("limits.fullscreen_text_per_video", [2, 4]) or [2, 4]
        except Exception:  # noqa: BLE001
            rng = [2, 4]
    if isinstance(rng, (list, tuple)) and rng:
        return int(rng[-1])
    try:
        return int(rng)
    except (TypeError, ValueError):
        return 4


@dataclass
class VisualBudget:
    """Сколько раз ролик уже закрыл пустой кадр каждым способом.

    Потолок полноэкранного текста был и раньше (`fs_cap`). Без остальных
    потолков лестница §7.2 просто сползла бы на первую подходящую ступень:
    на эталонном 0042 это дало бы четырнадцать карточек вместо четырнадцати
    надписей — то же слайд-шоу, другим шрифтом. Потолок нужен каждой ступени,
    а не только последней.
    """

    card: int = 0
    dataviz: int = 0
    source: int = 0
    parallax: int = 0
    fullscreen: int = 0
    plate: int = 0
    dataviz_blocks: set[str] = field(default_factory=set)

    # Потолки на ролик. `fullscreen` берётся из брендбука (`fs_cap`), поэтому
    # здесь его нет: у него уже есть свой источник правды.
    CAPS = {"card": 4, "dataviz": 2, "source": 3, "parallax": 3, "plate": 2}

    def allows(self, rung: str) -> bool:
        return int(getattr(self, rung, 0)) < int(self.CAPS.get(rung, 0))

    def take(self, rung: str) -> None:
        setattr(self, rung, int(getattr(self, rung, 0)) + 1)


def _claim_screen_phrase(used: set[str], content: str) -> bool:
    """Reserve a unique on-screen slogan. False = already used or empty."""
    key = _norm_screen_key(content)
    if not key:
        return False
    if key in used:
        return False
    used.add(key)
    return True


_0050_TEMPLATE_BAN = ("text-fullscreen/bigtext-mask-footage",)


def _authored_overlay_owns_gap_fs(block: dict[str, Any] | None) -> bool:
    """Authored overlay (not none) owns on-screen copy for this block.

    Gap-phrase used to invent a long Russian sentence on 0050 b5
    (overlay type none → QC-30 bigtext-mask). Lower-thirds / frames with
    content must also block that path so leftover shots can stay footage.
    """
    overlay = block.get("overlay") if isinstance((block or {}).get("overlay"), dict) else {}
    otype = str(overlay.get("type") or "")
    if otype in ("", "none"):
        return False
    return bool(str(overlay.get("content") or "").strip())


def _cta_wordmark(plan: dict[str, Any], catalog_wordmark: str = "") -> str:
    """Latin REDSHIFT for 0050 / authored overlay; never catalog «РЕДШИФТ»."""
    vid = str(plan.get("video_id") or "")
    cta_block = next(
        (b for b in (plan.get("blocks") or [])
         if str(b.get("role") or "") == "cta" and isinstance(b, dict)),
        {},
    )
    authored = str((cta_block.get("overlay") or {}).get("content") or "").strip()
    mark = authored or str(catalog_wordmark or "").strip() or "REDSHIFT"
    folded = mark.replace(".", "").upper()
    if vid == "redshift_0050" or folded == "REDSHIFT" or "РЕДШИФТ" in mark.upper():
        mark = "REDSHIFT"
    return mark.rstrip(".")


def _cta_close_style(plan: dict[str, Any]) -> dict[str, Any]:
    """Identity close: 0050 keeps stock under the mark (QC-30 paper invert)."""
    if str(plan.get("video_id") or "") == "redshift_0050":
        return {"logo_close": True, "invert": False, "tone": "ink"}
    return {"logo_close": True, "invert": True, "tone": "paper"}


def _template_excludes_for(plan: dict[str, Any], ctx=None) -> list[str]:
    """Per-video template bans from editing_preferences + 0050 hard bans."""
    vid = str(plan.get("video_id") or "")
    out: list[str] = []
    if vid == "redshift_0050":
        out.extend(_0050_TEMPLATE_BAN)
    prefs: dict[str, Any] = {}
    root = None
    if ctx is not None:
        cfg = getattr(ctx, "cfg", None)
        root = getattr(cfg, "repo_root", None)
    if root is None:
        from pathlib import Path as _Path
        root = _Path(__file__).resolve().parents[2]
    try:
        from ..lib.jsonio import read_json_or
        prefs = read_json_or(root / "config" / "editing_preferences.json", {}) or {}
    except Exception:  # noqa: BLE001
        prefs = {}
    extra = ((prefs.get("template_excludes") or {}).get(vid) or [])
    for tid in extra:
        text = str(tid or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _is_cta_overlay(ovl: dict[str, Any]) -> bool:
    kind = str(ovl.get("type") or "")
    renderer = str(ovl.get("renderer") or "")
    template = str(ovl.get("template") or "")
    return (kind == "cta" or renderer == "logo_brand_close"
            or "logo-brand-close" in template)


# Majority of words under a card → drop the phrase. Sparse hits drop only
# those words so spoken VO outside bulky cards still has captions.
PHRASE_MUTE_RATIO = 0.50
# Match clip-wipe grouping so a hole in the middle cannot spawn orphan words.
# Visual gradient-fill may use a wider brandbook cap; mute stays 3-word groups
# so a card over two words does not swallow the next phrase.
_CAPTION_MAX_WORDS = 3
_CAPTION_PAUSE_BREAK = 0.45
# Fullscreen slam is visually dominant for ~a beat, not the whole B-roll hold.
FS_MUTE_SEC = 1.6
MUTE_COVERAGE_WARN = 0.45
# Late-timeline title-behind sits on a full avatar and eats the line.
LATE_HERO_BEAT = 0.60
# Large punch/slam that actually covers the caption band. Subtle behind-head
# kickers and above-crown headlines do not mute spoken VO.
_BULKY_HERO_MUTE = frozenset({
    "hero-slam", "hero-knockout", "hero-oversize", "hero-split", "hero-exhibit",
})


def _plaque_covers_captions(ovl: dict[str, Any]) -> bool:
    """Top/note-pin/source-chip plaques sit off the caption band — do not mute VO."""
    params = ovl.get("params") if isinstance(ovl.get("params"), dict) else {}
    pos = str(params.get("position") or "").lower()
    if pos in ("top", "tl", "tr", "bl", "bottom-left"):
        return False
    if params.get("source_chip"):
        return False
    template = str(ovl.get("template") or "")
    if "note-pin" in template or "source-domain" in template:
        return False
    return True


def _fs_mute_span(shot: dict[str, Any]) -> tuple[float, float]:
    """Mute only while fullscreen type is visually dominant, not the B-roll hold."""
    start = float(shot["start"])
    end = float(shot["end"])
    delay = float((shot.get("params") or {}).get("enter_delay") or 0.0)
    vis = start + max(0.0, delay)
    mute_end = min(end, vis + FS_MUTE_SEC)
    if mute_end <= vis + 1e-6:
        vis = start
        mute_end = min(end, start + FS_MUTE_SEC)
    return vis, mute_end


def _union_span(windows: list[tuple[float, float]]) -> float:
    ordered = sorted((float(a), float(b)) for a, b in windows if b > a)
    if not ordered:
        return 0.0
    total = 0.0
    cur_s, cur_e = ordered[0]
    for start, end in ordered[1:]:
        if start <= cur_e:
            cur_e = max(cur_e, end)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = start, end
    return total + cur_e - cur_s


def _hero_line_span(shot: dict[str, Any], hero: dict[str, Any]) -> tuple[float, float]:
    end = float(shot["end"])
    if hero.get("duration"):
        end = min(end, float(shot["start"]) + float(hero["duration"]))
    return float(shot["start"]), end


def _caption_line_windows(
    shots: list[dict[str, Any]],
    overlays: list[dict[str, Any]],
) -> list[tuple[float, float]]:
    """Windows where a card carries the spoken line — mute the whole phrase."""
    windows: list[tuple[float, float]] = []
    for shot in shots:
        if shot.get("kind") == "fullscreen_text" and shot.get("content"):
            windows.append(_fs_mute_span(shot))
            continue
        hero = shot.get("hero") or {}
        if hero.get("carries_line") or shot.get("carries_line"):
            if hero:
                windows.append(_hero_line_span(shot, hero))
            else:
                windows.append((float(shot["start"]), float(shot["end"])))
    for ovl in overlays:
        params = ovl.get("params") if isinstance(ovl.get("params"), dict) else {}
        kind = str(ovl.get("type") or "")
        if (ovl.get("carries_line") or params.get("carries_line")
                or kind in ("source_card", "fullscreen_text")):
            windows.append((float(ovl["start"]), float(ovl["end"])))
    return windows


def _caption_mute_windows(
    shots: list[dict[str, Any]],
    overlays: list[dict[str, Any]],
) -> list[tuple[float, float]]:
    """Windows where bulky on-screen type hides karaoke — not every overlay."""
    windows: list[tuple[float, float]] = []
    for shot in shots:
        if shot.get("kind") == "fullscreen_text":
            windows.append(_fs_mute_span(shot))
            continue
        hero = shot.get("hero") or {}
        renderer = str(hero.get("renderer") or "")
        bulky = bool(hero.get("covers_frame")) or renderer in _BULKY_HERO_MUTE
        # Mid-frame type (title-behind, oversize) still covers karaoke.
        # Behind-head kickers (hero-headline) do not — punch-family mute
        # drops the overlapping word; the rest of the VO stays captioned.
        text_zone = renderer in _TEXT_ZONE_HEROES and renderer != "hero-headline"
        if not bulky and not text_zone:
            continue
        windows.append(_hero_line_span(shot, hero))
    bulky_ovl = {"source_card", "browser", "chatgpt_exchange", "claude_exchange",
                 "ai_chat_reveal", "app_showcase"}
    for ovl in overlays:
        kind = str(ovl.get("type") or "")
        renderer = str(ovl.get("renderer") or "")
        if kind == "plaque":
            if _plaque_covers_captions(ovl):
                windows.append((float(ovl["start"]), float(ovl["end"])))
            continue
        if kind in bulky_ovl or renderer in bulky_ovl:
            windows.append((float(ovl["start"]), float(ovl["end"])))
        if _is_cta_overlay(ovl):
            windows.append((float(ovl["start"]), float(ovl["end"])))
    return windows


def _warn_mute_coverage(windows: list[tuple[float, float]],
                        words: list[dict[str, Any]]) -> None:
    if not words or not windows:
        return
    speech0 = float(words[0]["start"])
    speech1 = float(words[-1]["end"])
    speech = speech1 - speech0
    if speech <= 0:
        return
    clipped = [(max(s, speech0), min(e, speech1)) for s, e in windows]
    frac = _union_span(clipped) / speech
    if frac > MUTE_COVERAGE_WARN:
        _log.warning(
            "caption mute covers %.0f%% of speech (limit %.0f%%)",
            frac * 100.0, MUTE_COVERAGE_WARN * 100.0,
        )


def _word_is_muted(
    word: dict[str, Any],
    *,
    punch_windows: list[tuple[float, float, str]],
    mute_windows: list[tuple[float, float]],
) -> bool:
    start, end = float(word["start"]), float(word["end"])
    spoken = str(word.get("display") or word.get("word") or "")
    if any(start < pe and end > ps and punch_families_overlap(spoken, pc)
           for ps, pe, pc in punch_windows if pc):
        return True
    return any(start < ce and end > cs for cs, ce in mute_windows)


def _phrase_hits_windows(phrase: list[dict[str, Any]],
                         windows: list[tuple[float, float]],
                         *, min_overlap: float = 0.05) -> bool:
    """True when a word substantially overlaps a mute/line window.

    A 3 ms kiss at the slot join used to swallow «дэ: трёхмерный поток»
    because ``поток`` ended on the next hero's start (0048).
    """
    if not windows:
        return False
    floor = max(0.0, float(min_overlap))
    for word in phrase:
        try:
            ws = float(word["start"])
            we = float(word["end"])
        except (TypeError, ValueError, KeyError):
            continue
        for start, end in windows:
            overlap = min(we, end) - max(ws, start)
            if overlap >= floor:
                return True
    return False


# Какое семейство акцента у блока (MEGA D-9). Красный — про чувство и миф,
# cyan — про технику, число и источник. Токен `cyan` лежит в брендбуке «IT
# КОСМОС» первым классом с §14, но до кадра не доезжал ни разу: `emphasis_family`
# объявлен в схеме и не читался ни одним модулем, а `captions.py` жёстко писал
# `var(--color-accent)`. Правило разводит два акцента по смыслу, а не по вкусу.
ACCENT_FAMILY_BY_EMPHASIS = {
    "myth": "red", "emotion": "red",
    "tech": "cyan", "number": "cyan", "source": "cyan",
}


def accent_family(block: dict[str, Any] | None) -> str:
    """Семейство акцента блока: ``red`` либо ``cyan``. По умолчанию красный."""
    if not block:
        return "red"
    return ACCENT_FAMILY_BY_EMPHASIS.get(
        str(block.get("emphasis_family") or ""), "red")


def _build_subtitle_cues(words: list[dict[str, Any]], *,
                         punch_windows: list[tuple[float, float, str]],
                         mute_windows: list[tuple[float, float]],
                         line_windows: list[tuple[float, float]] | None = None,
                         family_by_block: dict[str, str] | None = None,
                         ) -> list[dict[str, Any]]:
    """Karaoke cues at the default baseline; mute on punch/card/CTA, never raise.

    Heavily covered phrases (muted-word ratio ≥ PHRASE_MUTE_RATIO) stay silent
    so a hole in the middle cannot spawn clip-wipe orphans. Sparse mutes drop
    only the covered words; leftovers are re-glued and 1–2 letter chips fall
    off. A phrase that would keep fewer than two spoken words after a sparse
    mute is dropped rather than left as a one-word flash.

    ``carries_line`` windows drop the whole phrase on any overlap so a typed
    bubble cannot share the band with karaoke leftovers.
    """
    line_windows = list(line_windows or [])
    phrases = group_caption_phrases(
        words,
        max_words=_CAPTION_MAX_WORDS,
        pause_break_sec=_CAPTION_PAUSE_BREAK,
    )
    subtitles: list[dict[str, Any]] = []
    for phrase in phrases:
        if not phrase:
            continue
        if _phrase_hits_windows(phrase, line_windows):
            continue
        flags = [
            _word_is_muted(word, punch_windows=punch_windows,
                           mute_windows=mute_windows)
            for word in phrase
        ]
        muted = sum(flags)
        if muted / len(phrase) >= PHRASE_MUTE_RATIO:
            continue
        kept = [word for word, hit in zip(phrase, flags) if not hit]
        if muted and len(kept) < 2:
            continue
        for word in kept:
            cue = {
                "display": word["display"], "start": float(word["start"]),
                "end": float(word["end"]),
                "emphasis": bool(word.get("emphasis")),
                "block_id": word["block_id"],
                # Семейство акцента едет со словом: субтитр красится там же,
                # где рисуется, а не угадывает цвет по соседям.
                "accent_family": (family_by_block or {}).get(
                    str(word.get("block_id") or ""), "red"),
            }
            if word.get("lead"):
                cue["lead"] = word["lead"]
            subtitles.append(cue)
    subtitles = glue_short_cues(subtitles)
    for cue in subtitles:
        lead = str(cue.get("lead") or "")
        if lead and any(ch.isdigit() for ch in lead):
            cue["display"] = f"{lead} {cue['display']}".strip()
            cue["lead"] = ""
    return drop_orphan_short_cues(subtitles)


def _split_top_letterboxes(
    shot: dict[str, Any], *, frame_w: float = 1080.0, frame_h: float = 1920.0,
) -> bool:
    """Wide proof (Nature figure) letterboxes in the top half; portrait fills it."""
    src = str(shot.get("bg_file") or shot.get("top_src") or "").strip()
    path = Path(src) if src else None
    if path is None or not path.is_file():
        return True
    try:
        info = probe(path)
    except Exception:
        return True
    half = frame_h / 2.0
    src_w = max(float(info.width or 0), 1.0)
    src_h = max(float(info.height or 0), 1.0)
    scale = max(frame_w / src_w, half / src_h)
    cropped_w_share = 1.0 - (frame_w / max(src_w * scale, 1.0))
    return cropped_w_share > 0.25


def _stamp_subtitle_baselines(
    subtitles: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    brandbook: dict[str, Any] | None = None,
) -> None:
    """On a 50/50 split, karaoke at the avatar-shift band paints the paper.

    Split-top is 52% of the frame with object-fit contain, so a wide Nature
    figure letterboxes. Drop cues into that lower black bar — off the paper,
    above the avatar seam. A portrait top fills the half: those cues sit on
    the avatar chest instead of the figure.
    """
    height = 1920.0
    if isinstance(brandbook, dict):
        height = float((brandbook.get("canvas") or {}).get("height") or height)
    seam = height * 0.52
    letterbox_y = seam - 180.0
    portrait_y = seam + 0.70 * (height - seam)
    ordered = sorted(shots, key=lambda s: float(s.get("start") or 0))
    for cue in subtitles:
        t = (float(cue.get("start") or 0) + float(cue.get("end") or 0)) / 2.0
        for shot in ordered:
            if float(shot.get("start") or 0) - 1e-6 <= t < float(shot.get("end") or 0) + 1e-6:
                if str(shot.get("kind") or "") == "split":
                    cue["baseline_y"] = (
                        letterbox_y if _split_top_letterboxes(
                            shot, frame_w=1080.0, frame_h=height)
                        else portrait_y)
                break


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
        if current.endswith((".", "!", "?", "…", ",", ";", ":")):
            lines.append(current)
            current = word
            if len(lines) == limit:
                break
            continue
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
        if _is_ticker_asset(asset):
            continue
        plates.append(path)
    ticker_plates: list[str] = []
    ticker_seen: set[str] = set()
    for slot in slots:
        idx = int(slot["index"])
        asset = assets.get(idx) or {}
        prep = prepared.get(idx) or {}
        if not _is_ticker_asset(asset):
            continue
        path = str(prep.get("dst") or "").strip()
        if path and path not in ticker_seen:
            ticker_seen.add(path)
            ticker_plates.append(path)
    if not plates:
        # Fall back to any non-AI prepared file (borrowed plate path).
        for slot in slots:
            plate = _plate_source(slot, slots, prepared, assets)
            path = str((plate or {}).get("file") or "").strip()
            if path and path not in seen:
                seen.add(path)
                plates.append(path)
    out: dict[int, str] = {}
    pool = plates or ticker_plates
    if not pool:
        return out
    cursor = 0
    for slot in slots:
        if slot.get("kind") != "avatar":
            continue
        if _slot_wants_ticker(slot) and ticker_plates:
            out[int(slot["index"])] = ticker_plates[0]
            continue
        out[int(slot["index"])] = pool[cursor % len(pool)]
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
        # MUST-015: highlight is authored script copy, not a softened paraphrase.
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
    bare = word.strip(".,!?;:«»\"'—–()[]").lower().replace("ё", "е")
    return bare[:max(3, len(bare) - 2)]


_STOCK_BRAND_SOURCES = ("pexels", "pixabay", "freepik", "magnific")
_ACCENT_STRIP = ".,!?;:«»\"'—–()[]"


def _is_stock_brand_credit(text: str) -> bool:
    """True for burned-in Pexels/Pixabay watermark-style credit strings."""
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not t:
        return False
    for brand in _STOCK_BRAND_SOURCES:
        if t == brand:
            return True
        if t.startswith(f"{brand} ") or t.startswith(f"{brand}/") or t.startswith(f"{brand} /"):
            return True
        if t.endswith(f" {brand}") or t.endswith(f"/{brand}") or t.endswith(f"/ {brand}"):
            return True
    return False


def _credit_line(asset: dict[str, Any], sources: dict[str, Any]) -> str:
    """Small bottom-left source line for real photo/video (not AI).

    Press and other named sources keep a human/domain credit. Pexels/Pixabay
    burn their brand into the frame already — do not print ``PEXELS`` /
    ``PIXABAY`` again unless the licence ``attribution_required`` and the
    string is a non-brand human name. Empty string = no caption.
    """
    if not asset or asset.get("ai_generated"):
        return ""
    source = str(asset.get("source") or "").strip()
    if not source and not asset.get("attribution"):
        return ""
    src_meta = (sources.get("sources") or {}).get(source) or {}
    required = bool(src_meta.get("attribution_required"))
    name = str(asset.get("attribution") or "").strip()
    meta = asset.get("meta") or {}
    domain = str(meta.get("domain") or "").strip()
    source_l = source.lower()

    if source_l in _STOCK_BRAND_SOURCES:
        if not required:
            return ""
        if name and not _is_stock_brand_credit(name):
            return name
        return ""
    if _is_stock_brand_credit(name) or _is_stock_brand_credit(source):
        return ""
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
    words = [w for w in content.split() if w.strip(_ACCENT_STRIP)]
    if len(words) < 2:
        return None
    emphasis = _stem(str(block.get("emphasis_word") or ""))
    if emphasis:
        for word in words:
            bare = word.strip(_ACCENT_STRIP)
            if _stem(bare) == emphasis:
                return bare
    digits = [w.strip(_ACCENT_STRIP) for w in words
              if any(ch.isdigit() for ch in w)]
    if digits:
        return digits[0]
    return max((w.strip(_ACCENT_STRIP) for w in words), key=len)


def _emphasis_spoken_in_slot(
        words: list[dict[str, Any]] | None,
        start: float,
        end: float,
        needle: str) -> bool:
    """True only if ``needle`` is actually said inside ``[start, end)``."""
    if not needle or words is None:
        return False
    for item in words:
        token = str(item.get("display") or item.get("word") or "")
        if not token or not stems_match(needle, token):
            continue
        try:
            w_start = float(item.get("start"))
            w_end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        # Touching the cut is not overlap. Word end 45.1514 vs slot start
        # 45.151 is 0.4 ms of rounding, not a second delivery of the punch.
        overlap = min(w_end, end) - max(w_start, start)
        if overlap <= 0.05:
            continue
        return True
    return False


def _spoken_window_text(
        words: list[dict[str, Any]] | None,
        slot: dict[str, Any]) -> str:
    """Words actually said in this slot, in order. Empty if no speech map."""
    if not words:
        return ""
    start = float(slot.get("start") or 0.0)
    end = float(slot.get("end") or 0.0)
    bits: list[str] = []
    for item in words:
        try:
            w_start = float(item.get("start"))
            w_end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        if w_end <= start + 0.05 or w_start >= end - 0.05:
            continue
        token = str(item.get("display") or item.get("word") or "").strip()
        if token:
            bits.append(token)
    return " ".join(bits)


def _authored_punch_span(
        plan: dict[str, Any], block_id: str) -> tuple[float, float] | None:
    """Start/end of the authored fullscreen punch in this block, if any."""
    spans = [
        (float(slot["start"]), float(slot["end"]))
        for slot in (plan.get("slots") or [])
        if slot.get("authored_punch")
        and str(slot.get("block_id") or "") == str(block_id or "")
    ]
    if not spans:
        return None
    return min(s[0] for s in spans), max(s[1] for s in spans)


def _authored_punch_end(plan: dict[str, Any], block_id: str) -> float | None:
    """End of the authored fullscreen punch in this block, if any."""
    span = _authored_punch_span(plan, block_id)
    return None if span is None else span[1]


def _hero_content(block: dict[str, Any], slot: dict[str, Any], icons,
                  face: tuple[int, int] | None = None,
                  title: str = "",
                  words: list[dict[str, Any]] | None = None,
                  head_box: tuple[int, int, int, int] | None = None) -> dict[str, Any]:
    """Собрать всё, чем можно накормить приёмы, из одного блока сценария."""
    text = str(block.get("text") or "").strip()
    word = str(block.get("emphasis_word") or "").strip()
    # Oversize/headline «МИЛЛИОН» on a Poincaré beat: the emphasis belongs to
    # the block, not this window. Empty word drops those heroes via _HERO_NEEDS.
    # ``words is None`` keeps the word (caller did not pass a speech map).
    # An empty or out-of-window list clears it — including the post-punch
    # remainder that still inherits the block's emphasis.
    if word and words is not None:
        if not _emphasis_spoken_in_slot(
                words,
                float(slot.get("start") or 0.0),
                float(slot.get("end") or 0.0),
                word):
            word = ""
    # Big-word lines must carry speech meaning, not discourse openers like
    # «И вот ответ на вопрос» — Markus QA: answer card showed only that kicker.
    role = str(slot.get("role") or "")
    text_for_lines = text
    if block.get("answers_hook") or role in ("twist", "cta"):
        semantic = _semantic_screen_text(block, fallback=text)
        text_for_lines = semantic or _strip_discourse(text) or text
    else:
        text_for_lines = _strip_discourse(text) if _DISCOURSE_PREFIX.match(text) else text
    window_text = _spoken_window_text(words, slot)
    if window_text:
        # Column/stack must track this shot's VO, not the block opening.
        # 0048 printed «ДВЕ ТЫСЯЧИ ГОД» over Poincaré / Navier–Stokes.
        text_for_lines = window_text
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
        "title": " ".join(text_for_lines.split()[:3]).strip(".,!?;:").upper(),
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

# ChatGPT-карточка / окно чата в середине кадра закрывают лицо, когда ведущий
# сидит в нижней трети. Кружок уже выкинут; эти приёмы — тот же класс брака.
_FACE_COVERING_UI = frozenset({
    "hero-phone-mock", "hero-chat-generate", "hero-chat-typing",
})

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
        # Выбивка целит в светлую полосу лица: буквы видны только там, где
        # за ними светлее заливки.
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
        brand = content.get("brand") or {}
        if isinstance(brand, dict):
            params.update(brand)
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



_PHRASE_TRAILERS = frozenset({
    "в", "на", "с", "и", "а", "но", "что", "чем", "как", "для", "при", "по",
    "из", "от", "до", "же", "ли", "бы", "к", "у", "о", "об", "про", "без",
    "над", "под", "между", "через", "или", "либо", "то", "не",
})


def _is_readable_phrase(text: str) -> bool:
    """True when on-screen copy reads as a finished phrase, not a fragment."""
    words = [w for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9\-]+", str(text or "")) if w]
    if len(words) < 2:
        return False
    low = [w.lower().replace("ё", "е") for w in words]
    if low[0] in _PHRASE_TRAILERS or low[-1] in _PHRASE_TRAILERS:
        return False
    # broken mid-word truncation like "КАЖДОМ Ш"
    if len(low[-1]) == 1 and not low[-1].isdigit():
        return False
    return True


def _shorten_clause(clause: str, *, lo: int = 2, hi: int = 5) -> str:
    words = [w for w in str(clause or "").split() if w]
    if not words:
        return ""
    for n in range(min(hi, len(words)), lo - 1, -1):
        candidate = " ".join(words[:n])
        if _is_readable_phrase(candidate):
            return candidate
    return ""


def gap_phrase(words: list[dict[str, Any]], slot: dict[str, Any],
               block: dict[str, Any],
               *, used: set[str] | None = None) -> str:
    """Что вынести на экран, когда материала под кадр нет.

    Смысл речи, не каталожный плейсхолдер и не дискурс-открывашка («и вот
    ответ»). Overlay-punch («5 МИНУТ») — один раз на блок **и только после
    spoken onset** (0042 r6: early РЕШЕНА/5 минут spam). До удара — только
    уже произнесённые слова / нейтральные клаузы без будущего панча.
    """
    used = used if used is not None else None
    semantic = _semantic_screen_text(block)
    overlay = block.get("overlay") or {}
    otype = str(overlay.get("type") or "")
    start, end = float(slot["start"]), float(slot["end"])
    bwords = [w for w in words
              if str(w.get("block_id") or "") == str(block.get("id") or "")]
    pool = bwords or words

    def _take(phrase: str) -> str:
        key = _norm_screen_key(phrase)
        if not key:
            return ""
        if used is not None:
            if key in used:
                return ""
            used.add(key)
        return key

    punch_onset = None
    if otype in ("fullscreen_text", "lower_third", "plaque", "note") and semantic:
        punch_onset = spoken_onset_for_content(
            pool, semantic, block.get("emphasis_word"))

    # Overlay punch only once — never before VO; prefer the slot that
    # *covers* the spoken onset so the card lands on the beat.
    if (semantic and len(semantic.split()) <= 5
            and otype in ("fullscreen_text", "lower_third", "plaque", "note")):
        covers_onset = (punch_onset is not None
                        and start - 1e-6 <= float(punch_onset) < end + 1e-6)
        after_onset = (punch_onset is None
                       or start + 0.05 >= float(punch_onset) - 1e-6)
        if covers_onset or after_onset:
            hit = _take(semantic if not covers_onset else (
                enrich_overlay_punch(semantic, str(block.get("text") or ""))
                or semantic))
            if hit:
                return hit

    said = [str(w.get("word") or "") for w in words
            if float(w["end"]) > start and float(w["start"]) < end]
    said = [w for w in said if w.strip()]
    if said:
        joined = " ".join(said)
        if _DISCOURSE_PREFIX.match(joined):
            body = _strip_discourse(str(block.get("text") or joined))
            said = body.split()[:4] or said
        # Drop future punch tokens still not spoken by slot midpoint.
        mid = (start + end) / 2.0
        if punch_onset is not None and mid < float(punch_onset) - 1e-6:
            safe = []
            for w in said:
                # skip tokens that belong to the future punch family
                if punch_families_overlap(w, semantic or ""):
                    continue
                safe.append(w)
            said = safe or said
        # Prefer a finished phrase over a raw 4-word sliding window.
        joined4 = " ".join(said[:4])
        if _is_readable_phrase(joined4):
            hit = _take(joined4)
            if hit:
                return hit
        for n in range(min(5, len(said)), 1, -1):
            cand = " ".join(said[:n])
            if _is_readable_phrase(cand):
                hit = _take(cand)
                if hit:
                    return hit

    for clause in _block_clauses(str(block.get("text") or "")):
        if semantic and punch_onset is not None and start + 0.05 < float(punch_onset) - 1e-6:
            if punch_families_overlap(clause, semantic):
                continue
        hit = _take(clause)
        if hit:
            return hit

    body = _strip_discourse(str(block.get("text") or ""))
    # Prefer early informative clause when punch is still ahead.
    if semantic and punch_onset is not None and start + 0.05 < float(punch_onset) - 1e-6:
        for clause in _block_clauses(body):
            if not punch_families_overlap(clause, semantic):
                hit = _take(clause)
                if hit:
                    return hit
    # Last resort: nearest finished clause, shortened to 2–5 words.
    # Empty string → slot can demote to footage (see _retime_fullscreen_slots).
    fallback = ""
    for clause in _block_clauses(body):
        if semantic and punch_onset is not None and start + 0.05 < float(punch_onset) - 1e-6:
            if punch_families_overlap(clause, semantic):
                continue
        shortened = _shorten_clause(clause)
        if shortened and _is_readable_phrase(shortened):
            fallback = shortened.upper().strip(" ,.;:—-")
            break
    if not fallback:
        return ""
    if used is not None and fallback:
        used.add(_norm_screen_key(fallback))
    return fallback


def _sync_fullscreen_overlay_content(
        slots: list[dict[str, Any]], plan: dict[str, Any]) -> None:
    """Cached P5 parks a neighbour clause («За семнадцать часов») on the FS slot.

    Retiming must score the *authored* overlay (СИНГУЛЯРНОСТЬ), not the stub
    that happened to sit in ``cut_plan.json``.
    """
    blocks = {b["id"]: b for b in plan.get("blocks", [])}
    for slot in slots:
        if slot.get("kind") != "fullscreen_text":
            continue
        block = blocks.get(slot.get("block_id"), {})
        overlay = block.get("overlay") or {}
        if str(overlay.get("type") or "") != "fullscreen_text":
            continue
        raw = str(overlay.get("content") or "").strip()
        if not raw:
            continue
        slot["content"] = (
            enrich_overlay_punch(raw, str(block.get("text") or "")) or raw)


def _retime_fullscreen_slots(slots: list[dict[str, Any]],
                             plan: dict[str, Any],
                             words: list[dict[str, Any]]) -> None:
    """Demote intentional FS that starts before spoken punch (P7+ self-heal).

    Cached P5 plans park «решена за пять минут» at block head. Turning those
    slots into footage lets ``gap_phrase`` fill with informative in-window
    copy; the slot that *covers* punch onset may then take the punch once.
    """
    blocks = {b["id"]: b for b in plan.get("blocks", [])}
    for slot in slots:
        if slot.get("kind") != "fullscreen_text":
            continue
        reason = str(slot.get("reason") or "")
        if "полноэкранный текст" not in reason:
            continue
        block = blocks.get(slot.get("block_id"), {})
        overlay = block.get("overlay") or {}
        raw = str(slot.get("content") or overlay.get("content") or "").strip()
        if not raw:
            continue
        content = enrich_overlay_punch(raw, str(block.get("text") or "")) or raw
        bwords = [w for w in words
                  if str(w.get("block_id") or "") == str(block.get("id") or "")]
        onset = spoken_onset_for_content(
            bwords or words, content, block.get("emphasis_word"))
        if onset is None:
            continue
        if float(slot["start"]) + 0.2 < float(onset):
            slot["kind"] = "footage"
            slot["needs_asset"] = True
            slot["asset_role"] = slot.get("asset_role") or "broll"
            slot["content"] = ""
            slot["reason"] = (
                "early punch demoted to informative fill (§5.2 r6); " + reason)
            continue
        # Snap slightly-early starts onto onset.
        new_start = max(float(slot["start"]), float(onset) + 0.05)
        if new_start > float(slot["start"]) + 1e-3:
            block_end = float(bwords[-1]["end"]) if bwords else float(slot["end"])
            new_end = max(new_start + 0.55, float(slot["end"]))
            new_end = min(block_end, new_end)
            if new_end - new_start >= 0.55 - 1e-6:
                slot["start"] = round(new_start, 3)
                slot["end"] = round(new_end, 3)
                slot["duration"] = round(new_end - new_start, 3)
                slot["content"] = content




def explain_choice(template: Any, traits: Iterable[str],
                   *, shown: str = "") -> str:
    """Почему именно этот приём здесь — словами, а не «роль блока».

    Одна формулировка на все категории: строка уходит в edit-план и в отчёт
    сборки, и читать её будет человек, а не разбор.
    """
    hit = grounded_for(template.needs, traits, shown=shown)
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
                 block: dict[str, Any] | None = None,
                 video_duration: float | None = None,
                 exclude_renderers: "frozenset[str] | set[str]" = frozenset(),
                 ) -> dict[str, Any] | None:
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
    banned_rend = set(exclude_renderers or ())
    late = bool(
        video_duration
        and float(video_duration) > 0
        and float(slot.get("start") or 0) > LATE_HERO_BEAT * float(video_duration)
    )
    for template in catalog.by_category("hero-devices"):
        if template.renderer in banned_rend:
            blocked.append(template.id)
            continue
        if "alpha" in set(template.tags) and not has_alpha:
            blocked.append(template.id)
            continue
        needs = _HERO_NEEDS.get(template.renderer, ())
        if any(not available.get(key) for key in needs):
            blocked.append(template.id)
            continue
        # Late beat: title-behind over a full avatar eats the line. Headline
        # above the crown (clear_crown) stays readable.
        if late and template.renderer == "hero-title-behind":
            blocked.append(template.id)
            continue
        # CTA is the host asking a question. A full-frame slam paints a black
        # plate over the face («МАШИНАМ МОЖНО») and eats the vote beat.
        if (str(slot.get("role") or "") == "cta"
                and template.renderer in ("hero-slam", "hero-knockout",
                                          "hero-oversize")):
            blocked.append(template.id)
            continue
        if has_alpha and template.renderer in (
                "hero-slam", "hero-knockout", "hero-oversize"):
            blocked.append(template.id)
            continue
        if template.renderer in _FACE_COVERING_UI:
            # ChatGPT-карточка закрывает лицо на аватаре и врёт «чат» на
            # пустой перебивке. Не ставим ни там, ни там.
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
        signals.add("number")
    blob = build_blob(content.get("title"), content.get("caption"), " ".join(content.get("lines") or []), content.get("word"))
    rest = [t.id for t in catalog.by_category("hero-devices") if t.id not in blocked]
    prefer = (
        "hero-devices/headline-behind-head",
        "hero-devices/headline-over-head",
        "hero-devices/oversize-word",
        "hero-devices/text-column-left",
        "hero-devices/type-slab",
        "hero-devices/script-stack",
        "hero-devices/statement-slam",
        "hero-devices/split-panel-right",
        "hero-devices/figure-swap",
        "hero-devices/knockout-negative",
    )
    feedable_ids = [tid for tid in prefer if tid in rest]
    feedable_ids.extend(tid for tid in rest if tid not in feedable_ids)
    template, trace = picker.pick(
        "hero-devices",
        blob=blob,
        signals=signals,
        traits=traits,
        variant=variant,
        duration=float(slot["duration"]),
        recent_videos=recent_videos,
        exclude=blocked,
        seed=seed + int(slot["index"]) * 7,
        exclude_renderers=exclude_renderers,
    )
    renderer = template.renderer
    needs = _HERO_NEEDS.get(renderer, ())
    if template.id in blocked or any(not available.get(key) for key in needs):
        picked = None
        for tid in feedable_ids:
            cand = catalog.by_id(tid)
            if cand is None:
                continue
            cand_needs = _HERO_NEEDS.get(cand.renderer, ())
            if any(not available.get(key) for key in cand_needs):
                continue
            if cand.renderer in _FACE_COVERING_UI:
                continue
            if cand.renderer in banned_rend:
                continue
            if has_alpha and cand.renderer in (
                    "hero-slam", "hero-knockout", "hero-oversize"):
                continue
            picked = cand
            break
        if picked is None:
            return None
        template = picked
        renderer = template.renderer
        needs = _HERO_NEEDS.get(renderer, ())
        if any(not available.get(key) for key in needs):
            return None
    params = hero_params(renderer, template.params, content, slot)
    if late:
        params["clear_crown"] = True

    shown = " ".join(str(content.get(key) or "") for key in (
        "word", "title", "head", "tail", "punch", "kicker", "caption"))
    entry: dict[str, Any] = {
        "template": template.id, "renderer": renderer, "params": params,
        "file": None, "duration": None,
        "traits": sorted(traits or ()),
        "grounded_on": grounded_for(template.needs, traits or (), shown=shown),
        "why": explain_choice(template, traits or (), shown=shown),
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
    elif renderer in ("hero-headline", "hero-oversize"):
        # Kicker+word above the crown, or a full-frame oversize. A 3 s hold
        # left «МИЛЛИОН» on black while the VO had already moved to Poincaré.
        entry["duration"] = round(min(float(slot["duration"]), 1.5), 3)
    return entry


def _variant_seed(video_id: str, variant: str) -> int:
    return int(hashlib.sha256(f"{video_id}|{variant}".encode()).hexdigest()[:8], 16)


def _asset_for_slot(slot: dict[str, Any], accepted: dict[str, Any],
                    generated: dict[str, Any]) -> dict[str, Any] | None:
    key = str(slot["index"])
    return accepted.get(key) or generated.get(key)


def apply_ai_carves(slots: list[dict[str, Any]],
                    assets: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Split a slot whose accepted AI pin only covers a spoken window.

    P8 stores ``carve_sec`` when leftover AI would blow QC-14 on the full
    slot. The prefix keeps the pin; the remainder inherits like an empty C.
    """
    max_idx = max((int(s["index"]) for s in slots), default=0)
    out: list[dict[str, Any]] = []
    for slot in slots:
        idx = int(slot["index"])
        asset = assets.get(idx)
        try:
            carve = float((asset or {}).get("carve_sec") or 0.0)
        except (TypeError, ValueError):
            carve = 0.0
        start = float(slot["start"])
        end = float(slot["end"])
        dur = end - start
        if asset is None or carve < 1.15 or carve >= dur - 0.2:
            out.append(slot)
            continue
        first = copy.deepcopy(slot)
        first["end"] = start + carve
        first["duration"] = round(carve, 3)
        reason = str(slot.get("reason") or "").strip()
        first["reason"] = (reason + "; окно AI-prefer под речь").strip("; ")
        rest = copy.deepcopy(slot)
        max_idx += 1
        rest["index"] = max_idx
        rest["start"] = first["end"]
        rest["end"] = end
        rest["duration"] = round(end - rest["start"], 3)
        rest["needs_asset"] = True
        rest["reason"] = "остаток слота после окна AI-prefer"
        rest["carve_remainder"] = True
        rest["inherit_from"] = idx
        rest["events"] = [
            ev for ev in (rest.get("events") or [])
            if float(ev.get("t") or 0) >= float(rest["start"]) - 1e-6
        ]
        first["events"] = [
            ev for ev in (first.get("events") or [])
            if float(ev.get("t") or 0) < float(first["end"]) - 1e-6
        ]
        out.append(first)
        out.append(rest)
    return out


def inherit_ai_plates_onto_speech(
        slots: list[dict[str, Any]],
        assets: dict[int, dict[str, Any]],
        words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the carved hall on «вселенная» without a second AI flag.

    Empty C after the spoken supercomputer window used to pick a stock ticker
    plate. The pixels already exist on the carved shot; inheriting them does
    not add AI screen time (QC-14 counts ``ai_generated`` on the shot).
    """
    donors: list[dict[str, Any]] = []
    for slot in slots:
        asset = assets.get(int(slot["index"])) or {}
        if not asset.get("ai_generated"):
            continue
        aid = str(asset.get("asset_id") or "").lower()
        if "supercomputer" not in aid and "hall" not in aid:
            continue
        donors.append(slot)
    if not donors:
        return slots
    for slot in slots:
        if assets.get(int(slot["index"])):
            continue
        if slot.get("inherit_from") is not None:
            continue
        speech = overlapping_speech(slot, words).lower()
        if not any(tok in speech for tok in ("вселенн", "суперкомп", "supercomputer")):
            continue
        prior = [d for d in donors
                 if d.get("block_id") == slot.get("block_id")
                 and float(d.get("start") or 0) <= float(slot.get("start") or 0) + 1e-6]
        donor = prior[-1] if prior else donors[-1]
        slot["inherit_from"] = int(donor["index"])
    return slots


def split_empty_at_authored_punch(
        slots: list[dict[str, Any]],
        plan: dict[str, Any],
        assets: dict[int, dict[str, Any]],
        words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Park «5 МИНУТ» on the spoken onset, not on the whole empty C.

    A 3-second empty develop slot covers both «вселенная» and the punch.
    Ladder-filling the whole slot hid the authored overlay; splitting lets
    the hall hold the universe line and the tail become the punch card.
    """
    blocks = {str(b.get("id") or ""): b for b in plan.get("blocks") or []}
    used_idx = {int(s["index"]) for s in slots}
    max_idx = max(used_idx, default=0)
    out: list[dict[str, Any]] = []
    first_min = 0.55
    # 0.6 s flash of «решена за пять минут» is unreadable; hold a beat.
    punch_min = 1.15
    for slot in slots:
        block = blocks.get(str(slot.get("block_id") or ""), {})
        overlay = block.get("overlay") or {}
        if str(overlay.get("type") or "") != "fullscreen_text":
            out.append(slot)
            continue
        content = str(overlay.get("content") or "").strip()
        if not content:
            out.append(slot)
            continue
        content = enrich_overlay_punch(content, str(block.get("text") or "")) or content
        bwords = [w for w in words
                  if str(w.get("block_id") or "") == str(block.get("id") or "")]
        onset = spoken_onset_for_content(
            bwords or words, content, block.get("emphasis_word"))
        if onset is None:
            out.append(slot)
            continue
        start = float(slot["start"])
        end = float(slot["end"])
        punch_at = float(onset)
        # Min-hold must not pull the cut into an earlier empty slot of the
        # same block: 0042 then split three lattice Cs and spent the FS cap
        # on «решена за пять минут» before the spoken punch.
        if not (start - 1e-6 <= punch_at < end + 1e-6):
            out.append(slot)
            continue
        # Million-dollar FS is already the next slot. Splitting the host
        # shot parked authored_punch on the face (0048 index 28).
        if str(slot.get("kind") or "") in AVATAR_KINDS:
            neighbors = [
                other for other in slots
                if other is not slot
                and str(other.get("block_id") or "") == str(slot.get("block_id") or "")
                and str(other.get("kind") or "") == "fullscreen_text"
            ]
            if any(
                abs(float(other.get("start") or 0) - punch_at) <= 0.35
                or (float(other.get("start") or 0) - 1e-6
                    <= punch_at
                    < float(other.get("end") or 0) + 1e-6)
                for other in neighbors
            ):
                out.append(slot)
                continue
        if end - punch_at < punch_min and (end - start) >= first_min + punch_min:
            punch_at = max(start + first_min, end - punch_min)
        hint = str(overlay.get("template_hint") or "").strip()

        def _stamp_punch(target: dict[str, Any]) -> None:
            target["authored_punch"] = True
            if hint:
                target["template_hint"] = hint

        if punch_at < start + first_min or punch_at > end - first_min:
            if (end - punch_at) >= first_min:
                _stamp_punch(slot)
            out.append(slot)
            continue
        first = copy.deepcopy(slot)
        first["end"] = punch_at
        first["duration"] = round(punch_at - start, 3)
        rest = copy.deepcopy(slot)
        max_idx += 1
        while max_idx in used_idx:
            max_idx += 1
        rest["index"] = max_idx
        used_idx.add(max_idx)
        rest["start"] = punch_at
        rest["end"] = end
        rest["duration"] = round(end - punch_at, 3)
        rest["needs_asset"] = True
        _stamp_punch(rest)
        if first.get("inherit_from") is not None:
            rest["inherit_from"] = first["inherit_from"]
        elif assets.get(int(first["index"])):
            # Filled slot: keep the plate under the punch instead of a black card.
            rest["inherit_from"] = int(first["index"])
        out.append(first)
        out.append(rest)
    return out


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
                    ctx.warn(f"для сплита {slot['index']} нет верхней половины — режим A",
                             slot=slot["index"])
                    degrade_split_without_top(slot)
                    # Fall through to the avatar prepare path below.
                else:
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
                    # Original evidence, not the baked vstack: HyperFrames
                    # paints this in `.split-top` over the live avatar.
                    prepared[slot["index"]]["top_src"] = str(top_src)
                    continue

            dst = ctx.wpath("shots", f"avatar_{slot['index']:02d}_{int(duration * 1000)}.mp4")
            matte = matte_reports.get(int(segment["index"]))
            fit = _slot_compose_fit(ctx, slot, segment, width, height)
            bbox = tuple(int(v) for v in (segment.get("face_bbox") or ())) or None
            if bbox is not None and len(bbox) != 4:
                bbox = None
            if matte is not None and matte.usable:
                # §7.7: matte + VFX bg. Karaoke must not be baked behind the
                # head — leftover syllable scraps (0042). Keyword type uses
                # hero-title-behind, not this PNG path.
                result = prepare_avatar_shot(
                    avatar_src=avatar_src, dst=dst, duration_sec=duration,
                    width=width, height=height, fps=fps, start_sec=offset,
                    # Light brand bg under avatar — accent fill would blow §3.3.1.
                    bg_colors=(str(ctx.cfg.color("bg_light")).lstrip("#"),
                               str(ctx.cfg.color("bg_pure")).lstrip("#")),
                    behind_layer=None,
                    vfx_src=vfx_clips.get(slot["index"]),
                    compose_zoom=fit.zoom,
                    face_bbox=bbox,
                    brandbook=ctx.cfg.brandbook,
                    mode=fit.mode)
            else:
                # Opaque fallback: fitted compose_zoom via ShotSpec (source already 9:16).
                result = prepare_shot(ShotSpec(
                    src=avatar_src, dst=dst, duration_sec=duration,
                    width=width, height=height, fps=fps, fit="crop",
                    focus_x=fit.fx, focus_y=fit.fy, start_sec=offset,
                    compose_zoom=fit.zoom))
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

    # Karaoke captions must not be matted behind the head (0042 syllable
    # scraps). Intentional single-keyword type is hero-title-behind HTML.
    behind_layers: dict[str, Path] = {}

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
            if _is_nasa_asset(item):
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


def _clamp_end_before_next_avatar(
    start: float, end: float, shots: list[dict[str, Any]],
) -> float:
    """Stop a plaque at the cut if the next shot is a talking head.

    Evidence splits are the paper itself — clamping onto the next split
    used to leave nature.com on screen for 0.2 s (0042).
    """
    for shot in shots:
        if str(shot.get("kind") or "") != "avatar":
            continue
        a0 = float(shot["start"])
        if start < a0 - 1e-4 < end:
            end = min(end, a0)
    return end



def _clear_plate_gap_when_covered(shots, overlays):
    """QC-24 reads gap_reason; clear when a text-bearing overlay covers the shot."""
    covers = []
    for ov in overlays or []:
        t = str(ov.get('type') or '')
        if t not in ('plaque', 'cta', 'fullscreen_text', 'accent', 'source_card'):
            continue
        covers.append((float(ov['start']), float(ov['end'])))
    for s in shots or []:
        gr = str(s.get('gap_reason') or '')
        if 'plate without text' not in gr:
            continue
        a, b = float(s.get('start') or 0), float(s.get('end') or 0)
        mid = (a + b) / 2.0
        # cover if any overlay spans the midpoint (or ≥50% of shot)
        if any(o0 - 1e-3 <= mid <= o1 + 1e-3 for o0, o1 in covers):
            # strip only the plate-without-text marker; keep other reasons if useful
            s['gap_reason'] = gr.replace('no unique phrase: plate without text', '').replace('fullscreen cap or duplicate phrase: plate without text', '').replace('fullscreen cap: plate without text', '').strip(' ;')
            if not s['gap_reason']:
                s.pop('gap_reason', None)
            elif 'plate without text' in s['gap_reason']:
                s['gap_reason'] = s['gap_reason'].replace('plate without text', '').strip(' ;:') or None
                if not s.get('gap_reason'):
                    s.pop('gap_reason', None)
    return shots


def _clamp_plaques_at_avatar_cuts(
    overlays: list[dict[str, Any]],
    shots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Plaque/note-pin must not carry across a cut onto an avatar chest.

    Latin authored lower-thirds (WEATHER / REJECTED / FOLLOWUP) keep
    full-block timing so QC-24 bare plates between avatar cuts stay covered.
    """
    for ovl in overlays:
        kind = str(ovl.get("type") or "")
        template = str(ovl.get("template") or "")
        if kind != "plaque" and "note-pin" not in template:
            continue
        params = ovl.get("params") or {}
        label = str(params.get("text") or params.get("content") or "")
        if is_latin_overlay_label(label):
            continue
        ovl["end"] = round(
            _clamp_end_before_next_avatar(
                float(ovl["start"]), float(ovl["end"]), shots),
            3,
        )
    return overlays


def _plaque_overlay(*, template: Template, start: float, end: float,
                    params: dict[str, Any], why: str,
                    enter_ms: int | None = None) -> dict[str, Any]:
    """Плашка: кастомный рендерер (accent-underline, clean-bar, dark-card), иначе generic plaque."""
    ovl: dict[str, Any] = {
        "type": "plaque", "start": start, "end": end,
        "template": template.id, "params": params, "why": why,
    }
    renderer = template.renderer
    if renderer and renderer != "plaque":
        ovl["renderer"] = renderer
    if enter_ms is not None:
        _stamp_card_enter(ovl, enter_ms)
    return ovl


# Числительные словами → значение. `meaning.py` уже ловит их как признак
# блока, но диаграмме нужен не признак, а число: столбик надо чем-то мерить.
# Двадцать частотных плюс доли и множители — ровно то, чем говорят сценарии
# канала: «сто пять кубитов», «ошибка падает вдвое», «треть мощности».
_WORD_VALUES: dict[str, float] = {
    "ноль": 0, "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2, "три": 3,
    "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17,
    "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20, "тридцать": 30,
    "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90, "сто": 100, "двести": 200,
    "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600,
    "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
    # «Тысяча» стоит здесь как самостоятельное числительное, а не только как
    # множитель после другого: без неё «тысяча девятьсот девяносто первый»
    # разбирался в 990 — число, которого в реплике нет, и оно проскакивало
    # мимо отбраковки годов, потому что в диапазон 1900–2100 не попадало.
    "тысяча": 1000, "тысячи": 1000, "тысячу": 1000,
}
# Множители и доли идут отдельно: «вдвое» — это не число предметов, а во
# сколько раз, и на столбике это подпись, а не высота.
_WORD_FACTORS: dict[str, tuple[float, str]] = {
    "вдвое": (2.0, "×"), "втрое": (3.0, "×"), "вчетверо": (4.0, "×"),
    "половина": (0.5, ""), "половину": (0.5, ""), "треть": (1 / 3, ""),
    "четверть": (0.25, ""),
}
_WORD_SCALES: dict[str, tuple[float, str]] = {
    "тысяч": (1e3, "тыс."), "миллион": (1e6, "млн"), "миллиард": (1e9, "млрд"),
}
# Значения-множители: слагаемым в составном числительном они не бывают.
_WORD_SCALE_VALUES = frozenset({1e3, 1e6, 1e9})
_WORD_NUM_RE = re.compile(
    r"\b(" + "|".join(sorted(_WORD_VALUES, key=len, reverse=True))
    + r")\w*(?:\s+(тысяч\w*|миллион\w*|миллиард\w*))?", re.IGNORECASE)
_WORD_FACTOR_RE = re.compile(
    r"\b(" + "|".join(sorted(_WORD_FACTORS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE)


def _stats_from_words(text: str) -> list[dict[str, Any]]:
    """Числа, названные словами. §8.2: цифры есть в 6 % блоков, слова — в 25 %.

    Замер по шести сценариям канала: пригодных для диаграммы блоков с цифрами
    — один на шесть роликов. Двадцать восемь шаблонов `data-viz` (14 %
    каталога) не имели ни одного шанса сработать.
    """
    out: list[dict[str, Any]] = []
    low = str(text or "").lower()
    parts: list[dict[str, Any]] = []
    for match in _WORD_NUM_RE.finditer(low):
        value = _WORD_VALUES.get(match.group(1))
        if value is None:
            continue
        suffix = ""
        scale = match.group(2) or ""
        for stem, (mult, label) in _WORD_SCALES.items():
            if scale.startswith(stem):
                value *= mult
                suffix = label
                break
        parts.append({"value": float(value), "suffix": suffix,
                      "raw": match.group(0).strip(), "spelled": True,
                      "at": match.start(), "end": match.end()})

    # «Сто пять» — это сто пять, а не сто и пять. Слагаемые склеиваются, пока
    # каждое следующее меньше предыдущего и стоит вплотную: так устроен русский
    # составной числительный, и ровно этот блок 0042 («сто пять кубитов») —
    # тот, ради которого §8.2 и оживляла категорию.
    for part in parts:
        prev = out[-1] if out else None
        adjacent = prev is not None and low[prev["end"]:part["at"]].strip() == ""
        if (prev is not None and adjacent and not prev["suffix"]
                and not part["suffix"] and part["value"] < prev["value"]
                and part["value"] not in _WORD_SCALE_VALUES):
            prev["value"] += part["value"]
            prev["raw"] = f"{prev['raw']} {part['raw']}"
            prev["end"] = part["end"]
            continue
        # «два миллиона семьсот тысяч» is 2.7e6, not 2e6 then 700_000.
        # The first token already has a scale suffix, so the сто-пять glue
        # above refuses it. Smaller scale sitting against a larger one is
        # still one numeral.
        if (prev is not None and adjacent
                and prev.get("suffix") in {"млн", "млрд"}
                and part.get("suffix") in {"тыс.", "млн"}
                and part["value"] < prev["value"]):
            prev["value"] += part["value"]
            prev["raw"] = f"{prev['raw']} {part['raw']}"
            prev["end"] = part["end"]
            continue
        out.append(part)
    for part in out:
        part.pop("at", None)
        part.pop("end", None)
    for match in _WORD_FACTOR_RE.finditer(low):
        value, suffix = _WORD_FACTORS[match.group(1)]
        out.append({"value": float(value), "suffix": suffix,
                    "raw": match.group(0).strip(), "spelled": True})
    return out


def _comparable_stats(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep a bar/line series only when the numbers share one dimension.

    «Десять тысяч агентов, восемьдесят восемь часов, два миллиона сообщений»
    is three units. Charting them as Streaming-style bars is a lie. Mixed
    suffixes, or a 100× spread with empty suffixes, collapse to one KPI.
    """
    if len(nums) <= 1:
        return list(nums)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in nums:
        key = str(item.get("suffix") or "").strip().lower()
        groups.setdefault(key, []).append(item)
    best = max(
        groups.values(),
        key=lambda group: (
            len(group),
            max(abs(float(n["value"])) for n in group),
        ),
    )
    if len(best) >= 2:
        vals = [abs(float(n["value"])) for n in best]
        positive = [v for v in vals if v > 0]
        # Same unit (%, часов) may span two orders. Unitless fragments
        # like 26 / 6 / 88 from «две тысячи двадцать шесть / GPT-шесть /
        # восемьдесят восемь часов» are not one series — 0048 drew them
        # as a line chart labelled «Renders».
        empty_suffix = not str(best[0].get("suffix") or "").strip()
        spread_cap = 8.0 if empty_suffix else 100.0
        if positive and max(vals) / min(positive) <= spread_cap:
            return best
    ranked = sorted(
        nums,
        key=lambda n: (
            1 if str(n.get("suffix") or "").strip() else 0,
            abs(float(n["value"])),
        ),
        reverse=True,
    )
    return ranked[:1]


_COUNTUP_SCALE_SUFFIX = {"млн": 1e6, "тыс.": 1e3, "тыс": 1e3, "млрд": 1e9}


def _countup_suffix(num: dict[str, Any]) -> str:
    """Avoid «2 000 000 млн» when the value already includes the scale."""
    raw = str(num.get("suffix") or "").strip()
    if not raw:
        return ""
    key = raw.lower().rstrip(".")
    scale = _COUNTUP_SCALE_SUFFIX.get(raw) or _COUNTUP_SCALE_SUFFIX.get(key)
    if scale and abs(float(num.get("value") or 0)) + 1e-6 >= scale:
        return ""
    return f" {raw}"


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
    # Цифры важнее слов: «105» точнее, чем «сто пять», и если в блоке есть
    # и то и другое — это одно и то же число, названное дважды.
    if not found:
        found = _stats_from_words(text)
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



# A published article is not a chat log. Rotation still picked chat-thread
# for openai.com on 0048 A and covered the paper with a fake messenger.
_BROWSER_NOT_CHAT = (
    "browser-ui/chat-thread",
    "browser-ui/chat-ai-typing",
)


def _hint_from_screen_template(screen: str | None) -> str | None:
    """Map script screen_template shorthand to a concrete template id."""
    key = str(screen or "").strip().lower()
    if not key:
        return None
    mapping = {
        "browser": "browser-ui/browser-scroll",
        "search": "browser-ui/google-typing",
        "chat": "browser-ui/chat-thread",
        "paper": "frames-cards/arxiv-card",
        "arxiv": "frames-cards/arxiv-card",
    }
    return mapping.get(key)


def _source_card_category(source: dict[str, Any], *, variant: str) -> str:
    """Pick overlay category from source shape; A/B differ inside the category."""
    url = str(source.get("url") or "").lower()
    domain = str(source.get("domain") or "").lower()
    hay = f"{url} {domain} {source.get('screen_template') or ''}".lower()
    if any(tok in hay for tok in ("arxiv", "doi.org", ".pdf")):
        return "frames-cards"
    if source.get("url") or source.get("domain"):
        return "browser-ui"
    return "browser-ui" if variant == "A" else "frames-cards"


def _build_overlays(ctx, plan: dict[str, Any], words: list[dict[str, Any]],
                    catalog: TemplateCatalog, *, variant: str, seed: int,
                    recent_videos: list[str], used: list[str],
                    picker: TemplatePicker | None = None,
                    budget: "VisualBudget | None" = None,
                    loop_seam: dict[str, Any] | None = None,
                    peer_exclude: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Плашки, карточки источников, подсветка, data-viz и CTA (§5.4–5.6, §6)."""
    if picker is None:
        cfg = getattr(ctx, "cfg", None)
        picker = TemplatePicker(catalog, ScenarioIndex.load(cfg, catalog=catalog))
    overlays: list[dict[str, Any]] = []
    duration = float(plan["duration_sec"])
    sources = plan.get("sources", [])
    enter_ms = _overlay_enter_ms(ctx)
    # Bulky browser/source_card overlays are opt-in proof beats only.
    # Routine real footage uses the thin BL `.credit` from `_credit_line`.
    # Require both show_on_screen and proof_card so legacy scripts that only
    # set show_on_screen:true no longer spawn full-frame source badges.
    on_screen = [s for s in sources
                 if s.get("show_on_screen") and (s.get("proof_card") or s.get("snippet") or s.get("highlight_line"))]

    for i, (source, run) in enumerate(zip(on_screen, _evidence_runs(plan["slots"]))):
        anchor = next((s for s in run if s.get("kind") not in AVATAR_KINDS), run[0])
        card_category = _source_card_category(source, variant=variant)
        ev_block = next((b for b in (plan.get("blocks") or [])
                         if b.get("id") == anchor.get("block_id")), {})
        card_traits = set(block_traits(str(ev_block.get("text") or source.get("snippet") or "")))
        # Source cards with a quote/snippet honestly ground browser-scroll (needs=quote).
        if source.get("snippet") or source.get("highlight_line"):
            card_traits.add("quote")
        head = [
            h for h in (
                source.get("template_hint"),
                _hint_from_screen_template(source.get("screen_template")),
                (ev_block.get("overlay") or {}).get("template_hint"),
            ) if h
        ]
        blob = build_blob(
            source.get("title"),
            source.get("snippet"),
            source.get("domain"),
            source.get("screen_template"),
        )
        browser_article = str(source.get("screen_template") or "").lower() == "browser"
        card_template, _ = picker.pick(
            card_category,
            blob=blob,
            signals=set(card_traits),
            traits=card_traits,
            variant=variant,
            duration=float(anchor["duration"]),
            recent_videos=recent_videos,
            exclude=list(used) + (list(_BROWSER_NOT_CHAT) if browser_article else []),
            seed=seed + i,
            prefer_head=head,
            exclude_renderers=("chat_thread",) if browser_article else (),
        )
        # Rotation still returned chat-thread on 0048 A after exclude: the
        # pool emptied and exclude was soft-dropped. A paper is a browser.
        if browser_article and card_template.id in _BROWSER_NOT_CHAT:
            forced = catalog.by_id("browser-ui/browser-scroll")
            if forced is not None:
                card_template = forced
        used.append(card_template.id)
        card_start = float(anchor["start"])
        card_end = min(card_start + 3.4, float(run[-1]["end"]))
        for later in run:
            if float(later["start"]) <= card_start + 1e-4:
                continue
            if str(later.get("kind") or "") in AVATAR_KINDS:
                card_end = min(card_end, float(later["start"]))
                break
        renderer = _overlay_renderer(card_template)
        avatar_anchor = str(anchor.get("kind") or "") in AVATAR_KINDS
        skip_bulky = False
        compact_card = False
        if avatar_anchor:
            # Nature/arxiv cards on the talking head (0042 08–10.5s). No
            # compact fallback — skip the bulky card on avatar/split entirely.
            skip_bulky = True
        if card_end - card_start < 0.6:
            skip_bulky = True
        title = _russian_headline(source)
        # MUST-015: card copy is the authored source fields, not a latin-drop
        # or a softened paraphrase. highlight_line "X" must remain "X".
        snippet = str(source.get("snippet") or "")
        highlight_line = str(source.get("highlight_line") or "")
        enter_ms = _overlay_enter_ms(ctx)
        card_params = {
            "template": source.get("screen_template", "browser"),
            "domain": source.get("domain", ""),
            "url": source.get("url", ""),
            "title": title,
            "snippet": snippet,
            "published": source.get("published", ""),
            "prompt": title or snippet,
            "highlight_line": highlight_line,
            "highlight": highlight_line,
            "typing": bool(card_template.params.get("typing")),
            "scroll": bool(card_template.params.get("scroll")),
            "enter_ms": enter_ms,
        }
        if compact_card:
            card_params["compact"] = True
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
        if not skip_bulky:
            overlays.append(_stamp_card_enter({
                "type": "source_card", "start": card_start, "end": card_end,
                "template": card_template.id, "renderer": renderer,
                "carries_line": True,
                "params": card_params,
                "traits": sorted(card_traits),
                "grounded_on": sorted(matched(card_template.needs, card_traits)),
                "why": explain_choice(card_template, card_traits)
                       or "§5.6: источник обязан появиться на экране",
            }, enter_ms))
            # §5.5: подсветка обязательна при показе скриншота статьи.
            overlays.append(_stamp_card_enter({
                "type": "highlight", "start": card_start + 0.6,
                "end": min(card_start + 1.7, card_end),
                "params": {"label": highlight_line, "target": "title"},
                "why": "§5.5: фокусная подсветка ключевой строки источника",
            }, enter_ms))
        domain = source.get("domain", "")
        plaque_template, _ = picker.pick(
            "lower-thirds",
            blob=build_blob(domain, source.get("title")),
            signals=block_traits(str(source.get("snippet") or "")),
            traits={"brand"} if domain else set(),
            variant=variant,
            duration=2.4,
            recent_videos=recent_videos,
            exclude=used,
            prefer_head=["lower-thirds/source-domain"],
            seed=seed + i,
        )
        used.append(plaque_template.id)
        plaque_start = float(anchor["start"]) + 0.35
        plaque_end = min(plaque_start + 2.2, float(anchor["end"]))
        if plaque_end - plaque_start < 0.8:
            plaque_start = max(float(anchor["start"]), float(anchor["end"]) - 2.0)
            plaque_end = float(anchor["end"])
        overlays.append(_plaque_overlay(
            template=plaque_template,
            start=plaque_start,
            end=plaque_end,
            params={"text": domain, "subtitle": "источник",
                    "name": domain, "role": "источник",
                    "source_chip": True,
                    "position": "bottom",
                    "direction": "left",
                    **{k: v for k, v in plaque_template.params.items()
                       if k in ("accent_underline",
                                "clean_bar", "dark_card")}},
            why="§5.4: плашка с доменом источника",
            enter_ms=enter_ms,
        ))

    _append_dataviz(plan, overlays, catalog, variant=variant, seed=seed,
                    budget=budget,
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
        content = str(overlay.get("content") or "").strip()
        if not content:
            continue
        role = (overlay.get("role") or overlay.get("subtitle")
                or overlay.get("kicker") or "")
        # Признаки блока идут сигналами: словарь интентов нижней трети ждёт
        # их именно так, а раньше на этом пути не выставлялось ничего, и
        # `lowerthird-metric-badge` был недостижим при живом числе в реплике.
        lt_traits = block_traits(str(block.get("text") or ""))
        template, _ = picker.pick(
            "lower-thirds",
            blob=build_blob(content, role),
            signals=lt_traits,
            traits=lt_traits,
            variant=variant,
            duration=2.4,
            recent_videos=recent_videos,
            exclude=used,
            prefer_head=head,
            seed=seed + 7,
        )
        used.append(template.id)
        latin = is_latin_overlay_label(content)
        # Word-onset sync: plaque lands on/after spoken punch, never block+0.4 early.
        # Latin authored labels keep verbatim copy and full-block timing (QC-24).
        if not latin:
            content = enrich_overlay_punch(str(content or ""), str(block.get("text") or "")) or content
            content = soften_on_screen_copy(content)
        b_start = float(block_slots[0]["start"])
        b_end = float(block_slots[-1]["end"])
        if latin:
            start = b_start
            plaque_end = b_end
        else:
            bwords = [w for w in words if str(w.get("block_id") or "") == str(block.get("id") or "")]
            anchor = find_spoken_anchor(bwords or words, content, block.get("emphasis_word"))
            if anchor is not None:
                start = accent_card_start(anchor, block_start=b_start, delay_sec=0.05)
            else:
                start = b_start + 0.4
            start = min(start, max(b_start, b_end - 1.2))
            plaque_end = min(start + 2.6, b_end)
            plaque_end = _clamp_end_before_next_avatar(
                start, plaque_end, plan.get("slots") or [])
        if plaque_end - start < 0.35:
            continue
        # Suppress plaque when a punch-family FS/accent card already owns
        # the beat (0042 r6: triple НЕЧЕМ = card + plaque + captions).
        conflict = False
        for s in plan.get("slots", []):
            if s.get("kind") != "fullscreen_text":
                continue
            if float(s["end"]) <= start or float(s["start"]) >= plaque_end:
                continue
            sc = str(s.get("content") or "")
            if not sc:
                continue
            # Latin plaques only collide with FS on identical text (same as
            # plaque-plaque). Punch-stem overlap would drop e.g. CLAY REJECT
            # vs fullscreen «CLAY: НЕТ».
            if latin:
                if sc.strip() == str(content).strip():
                    conflict = True
                    break
            elif punch_families_overlap(sc, str(content)):
                conflict = True
                break
        if not conflict:
            for ov in overlays:
                if ov.get("type") not in ("fullscreen_text", "accent", "cta"):
                    # also check shots-to-be: use slot content above
                    pass
            # Also suppress if any earlier overlay plaque same family.
            # Latin labels only collide on identical text (not punch stems).
            for ov in overlays:
                if ov.get("type") != "plaque":
                    continue
                pt = str((ov.get("params") or {}).get("text") or "")
                if not pt:
                    continue
                if float(ov["end"]) <= start or float(ov["start"]) >= plaque_end:
                    continue
                if latin:
                    if pt.strip() == str(content).strip():
                        conflict = True
                        break
                elif punch_families_overlap(pt, str(content)):
                    conflict = True
                    break
        if conflict:
            continue
        overlays.append(_plaque_overlay(
            template=template,
            start=start,
            end=plaque_end,
            params={"text": content, "content": content, "name": content,
                    "role": role,
                    **{k: v for k, v in template.params.items()
                       if k in ("position", "direction", "accent_underline",
                                "clean_bar", "dark_card")}},
            why=f"плашка из сценария, блок {block['id']}",
            enter_ms=enter_ms,
        ))

    # CTA — last ~2s (§6). Always: REDSHIFT. + handle + red Subscribe.
    # No slogan tagline; invert is transparent so stock/cosmic underlay shows.
    cta_start, cta_end = plan.get("cta_window", [duration - 2.0, duration])
    # Шов лупа не переживёт полноэкранной плашки с логотипом: она закроет
    # ровно тот кадр, который обязан совпасть с первым. Под этот тип концовки
    # в каталоге лежит `outro-cta/loop-back` (`renderer: footage`) — до сегодня
    # с пустым `last_used_in`.
    seam = bool(loop_seam)
    cta_exclude = list(used) + [str(x) for x in peer_exclude if x]
    cta_template, _ = picker.pick(
        "outro-cta",
        variant=variant,
        duration=float(cta_end) - float(cta_start),
        recent_videos=recent_videos,
        exclude=cta_exclude,
        prefer_head=(["outro-cta/loop-back"] if seam else
                     ["outro-cta/logo-brand-close", "outro-cta/subscribe-pulse"]),
        seed=seed,
    )
    used.append(cta_template.id)
    cta_params = dict(cta_template.params)
    show_subscribe = show_subscribe_cta(plan)
    cta_params.update({
        "wordmark": _cta_wordmark(plan, str(cta_params.get("wordmark") or "")),
        "tagline": "",  # 0042 r6: drop «Write code. Ship to orbit.»
        "url": str(cta_params.get("url") or "redshift.shorts"),
        "subscribe": show_subscribe,
        "buttonText": "Subscribe" if show_subscribe else "",
        "exit": "none",
        **_cta_close_style(plan),
    })
    if seam:
        # Подпись поверх шва — мелкая и прижатая к низу: она не должна попасть
        # в те 64 бита, по которым QC-27 сравнивает первый кадр с последним.
        cta_params.update({"logo_close": False, "invert": False,
                           "compact": True, "position": "bottom"})
    overlays.append({
        "type": "cta", "start": float(cta_start), "end": float(cta_end),
        "template": cta_template.id,
        "renderer": cta_template.renderer,
        "params": cta_params,
        "why": ("§6.3 R-4: шов лупа — CTA не закрывает кадр, который смыкается "
                "с первым"
                if seam else
                "§6 r6: REDSHIFT + handle (no Subscribe)"
                if not show_subscribe else
                "§6 r6: REDSHIFT + handle + Subscribe (no slogan)"),
    })
    return overlays


def _dataviz_label(block: dict[str, Any], *,
                   english_fallback: str = "Retention") -> str:
    """Chart chrome follows the spoken language; never default English on Russian copy."""
    heading = str(block.get("heading") or "").strip()
    if heading:
        return heading
    text = str(block.get("text") or "")
    if re.search(r"[А-Яа-яЁё]", text):
        if re.search(r"ошибк", text, re.I):
            return "ОШИБКА"
        emph = str(block.get("emphasis_word") or "").strip()
        if emph:
            return emph.upper()
        return "ДАННЫЕ"
    return english_fallback


def _error_step_series(block: dict[str, Any]) -> list[float] | None:
    """Error halves each surface-code step — not the 'five minutes' count."""
    text = f"{block.get('text') or ''} {block.get('heading') or ''}"
    if re.search(r"ошибк", text, re.I) and re.search(
            r"вдвое|в два раза|половин", text, re.I):
        return [100.0, 50.0, 25.0]
    return None


def _dataviz_overlay(slot: dict[str, Any], nums: list[dict[str, Any]],
                     blocks: dict[str, Any], picker: TemplatePicker, *,
                     variant: str, seed: int, recent_videos: list[str],
                     used: list[str], start: float, end: float,
                     why: str = "data-viz: в блоке есть число",
                     ) -> dict[str, Any]:
    """Собрать оверлей-диаграмму по числам блока.

    Вынесено из `_append_dataviz`, чтобы лестница закрытия кадра (§7.2)
    строила диаграмму тем же кодом, а не своей копией: параметры двадцати
    восьми шаблонов подобраны по одному, и вторая их редакция разошлась бы
    с первой на первом же новом приёме.
    """
    nums = _comparable_stats(list(nums))
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

    signals = {"number"}
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
        block = blocks.get(slot["block_id"], {})
        series = _error_step_series(block)
        if series:
            start_v, end_v = series[0], series[-1]
            params = {
                "start_value": start_v,
                "end_value": end_v,
                "values": series,
                "label": _dataviz_label(block),
                "subtitle": "×½ на каждом шаге",
                "unit": "%",
                "x_labels": ["шаг 1", "шаг 2", "шаг 3"],
                "source": "поверхностный код",
            }
        else:
            params = {
                "start_value": start_v,
                "end_value": end_v,
                "label": _dataviz_label(block),
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
        suffix = _countup_suffix(nums[0])
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
            # Catalog demo title must never reach a live Russian cut.
            params["title"] = _dataviz_label(blocks.get(slot["block_id"], {}))
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
        if name == "animated-bar-chart":
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            params["title"] = heading or str(nums[0].get("raw") or "Ошибка")
            params["subtitle"] = "по реплике блока"
    traits = set(signals) | set(block_traits(str(block.get("text") or "")))
    return {
        "type": "dataviz", "start": start, "end": end,
        "template": template.id, "renderer": template.renderer,
        "params": params,
        "traits": sorted(traits),
        "grounded_on": sorted(matched(template.needs, traits)),
        "why": why,
    }


def _append_dataviz(plan: dict[str, Any], overlays: list[dict[str, Any]],
                    catalog: TemplateCatalog, *, variant: str, seed: int,
                    recent_videos: list[str], used: list[str],
                    picker: TemplatePicker | None = None,
                    budget: "VisualBudget | None" = None) -> None:
    """Оверлеи с числом — до двух на ролик (§8.2, бюджет `VisualBudget`).

    Роли шире, чем `evidence`/`develop`: на 0042 число живёт в `setup`
    («внутри процессора сто пять кубитов»), и по старому списку ролей блок,
    ради которого категорию и оживляли, диаграммы бы не получил.
    """
    if picker is None:
        picker = TemplatePicker(catalog, ScenarioIndex.empty())
    duration = float(plan["duration_sec"])
    cta_start = float((plan.get("cta_window") or [duration - 2.0, duration])[0])
    occupied = [(float(o["start"]), float(o["end"])) for o in overlays
                if o.get("type") in ("source_card", "cta", "plaque")]
    blocks = {b["id"]: b for b in plan.get("blocks", [])}
    # Счётчик общий с лестницей §7.2: у диаграммы один потолок на ролик, а не
    # по одному на каждый путь. Врозь они давали четыре графика на 0042 и
    # `compare-bars` четыре раза подряд — то самое, что ловит QC-25.
    budget = budget if budget is not None else VisualBudget()
    for slot in plan["slots"]:
        # Потолок проверяется до постановки, а не после: иначе последний
        # график всегда ставился «на один больше».
        if not budget.allows("dataviz"):
            return
        if slot.get("role") not in ("setup", "evidence", "develop", "twist"):
            continue
        if slot["kind"] not in ("footage", "meme"):
            continue
        nums = _stats_from_text(str(blocks.get(slot["block_id"], {}).get("text") or ""))
        if not nums:
            continue
        bid = str(slot.get("block_id") or "")
        if bid and bid in budget.dataviz_blocks:
            continue
        start = float(slot["start"]) + 0.25
        end = min(float(slot["end"]) - 0.15, start + 3.0, cta_start)
        if end - start < 1.2:
            continue
        if any(start < occ_end and end > occ_start for occ_start, occ_end in occupied):
            continue
        overlays.append(_dataviz_overlay(
            slot, nums, blocks, picker, variant=variant, seed=seed,
            recent_videos=recent_videos, used=used, start=start, end=end))
        occupied.append((start, end))
        budget.take("dataviz")
        if bid:
            budget.dataviz_blocks.add(bid)


# Рендереры browser-ui, которые честно показывают настоящий источник.
# Окна чата и мессенджера сюда не входят: их содержимое пришлось бы
# сочинить, а выдуманная переписка — не иллюстрация, а подделка.
class _RecordingPicker:
    """Тот же picker, но запоминает, чем кончился каждый подбор.

    `PickTrace` возвращался всеми десятью вызовами `picker.pick` и везде
    выбрасывался в `_`. Без него нечем закрыть ни QC-25, ни простой вопрос
    «почему в кадре именно этот приём»: в отчёте оставались только id.

    Обёртка, а не правка десяти мест: одиннадцатый вызов, который добавят
    завтра, попадёт в отчёт сам, а не забудет записаться.
    """

    __slots__ = ("_inner", "traces")

    def __init__(self, inner: TemplatePicker) -> None:
        self._inner = inner
        self.traces: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def pick(self, category: str, **kw: Any):
        template, trace = self._inner.pick(category, **kw)
        self.traces.append({
            "category": category,
            "template": template.id,
            "fired": [fid for fid, _w in trace.fired],
            "walk": list(trace.walk),
            "won_at": trace.won_at,
            "allow_size": trace.allow_size,
            "escaped": bool(trace.escaped),
            "escape_level": str(getattr(trace, "escape_level", "") or ""),
        })
        return template, trace


# Стиль хука из сценария → приём каталога (§5.2 H-2). Словарь здесь, а не в
# схеме: схема описывает сценарий, а соответствие приёму — дело сборщика.
HOOK_STYLE_TEMPLATES = {
    "number_slam": "intro-hooks/hook-number-slam",
    "question_flash": "intro-hooks/hook-question-flash",
    "blackout_word": "intro-hooks/hook-blackout-word",
    "cold_open": "intro-hooks/hook-footage-cold-open",
    "split_reveal": "intro-hooks/hook-split-reveal",
    "typing_search": "intro-hooks/hook-typing-search",
    "avatar_direct": "intro-hooks/hook-avatar-direct",
}

# Признаки блока, которые словарь интентов хука ждёт как **сигналы** (N-14).
# Два словаря — признаки из `meaning.py` и сигналы из `assemble.py` — до сих
# пор не пересекались на пути хука: интент `hook-number` требовал сигнала
# `numbers`, которого на этом пути никто не выставлял, и не срабатывал никогда.
_HOOK_TRAIT_SIGNALS = frozenset({"number", "question", "comparison",
                                 "superlative", "negation", "quote", "danger"})


def _hook_signals(spec: dict[str, Any], traits: set[str], *,
                  has_asset: bool) -> set[str]:
    """Сигналы для подбора хука: признаки блока плюс структура кадра."""
    signals = {t for t in traits if t in _HOOK_TRAIT_SIGNALS}
    if has_asset:
        signals.add("footage")
    if str(spec.get("on_screen") or "").strip():
        signals.add("on_screen")
    if str(spec.get("cold_open_query") or "").strip():
        signals.add("cold_open")
    return signals


# Рендереры хука, которые сборщик действительно кладёт в кадр. Список короче
# каталога намеренно: `split`, `avatar` и `source_card` тоже помечены как хуки,
# но кадр под них надо собирать иначе — сплит требует второго слоя, аватар
# требует альфа-слота, а «ввод поискового запроса» требует параметров строки
# поиска, которых в сценарии сегодня нет. Пока их нечем наполнить, приём,
# выбранный и не показанный, — это пустое место в самых дорогих секундах
# ролика. Три оставшихся ждут своего кадра, а не подбора.
_HOOK_RENDERED = frozenset({"fullscreen_text", "footage"})


def _hook_allows(template_id: str, renderer: str, *, slot: dict[str, Any],
                 has_asset: bool, has_source: bool) -> bool:
    """Может ли этот кадр показать этот приём хука."""
    if renderer not in _HOOK_RENDERED:
        return False
    if renderer == "footage":
        return has_asset
    return True                                   # fullscreen_text — всегда


def _pick_hook_shot(slot: dict[str, Any], block: dict[str, Any],
                    plan: dict[str, Any], picker: TemplatePicker,
                    catalog: TemplateCatalog, *, variant: str, seed: int,
                    recent_videos: list[str], used_templates: list[str],
                    has_asset: bool):
    """Приём первых секунд — решением, а не остатком (§5.2 H-1).

    До этой функции `picker.pick("intro-hooks", …)` не вызывался нигде: все
    десять точек подбора передавали одну из десяти других категорий, и конфиг
    честно числил категорию недостижимой. На 0042 хук собрался случайно —
    кадр 0 отдал 0.47 с футажа, кадры 1 и 2 стали двумя полноэкранными
    надписями подряд, и обе фразы выбрала `gap_phrase`, то есть «что вынести
    на экран, когда материала нет». Хука как решения не было — был отказ
    материала.

    Возвращает ``(template, trace)`` либо ``None``, если кадр вне окна хука
    или ни один приём каталога этому кадру не по силам.
    """
    if str(slot.get("role") or "") != "hook":
        return None
    window = plan.get("hook_window") or [0.0, 3.0]
    if float(slot["start"]) >= float(window[1]):
        return None

    spec = dict(plan.get("hook") or {})
    traits = block_traits(str(block.get("text") or "")) if block else set()
    has_source = bool(plan.get("sources"))
    blocked = list(used_templates)
    for template in catalog.by_category("intro-hooks"):
        if not _hook_allows(template.id, template.renderer, slot=slot,
                            has_asset=has_asset, has_source=has_source):
            blocked.append(template.id)
    if not [t for t in catalog.by_category("intro-hooks")
            if t.id not in blocked]:
        return None

    hint = str(spec.get("template_hint") or "")
    styled = HOOK_STYLE_TEMPLATES.get(str(spec.get("style") or ""))
    head = [t for t in (hint, styled) if t and t not in blocked]
    return picker.pick(
        "intro-hooks",
        blob=" ".join([str(spec.get("on_screen") or ""),
                       str(block.get("text") or "")]).strip(),
        signals=_hook_signals(spec, traits, has_asset=has_asset),
        traits=traits,
        variant=variant,
        duration=float(slot["duration"]),
        recent_videos=recent_videos,
        exclude=blocked,
        seed=seed,
        prefer_head=head,
    )


# Ниже этого счёта материал говорит не о том, что звучит (§9.2). Тот же порог,
# что у судьи в P8: два места с одним смыслом не должны расходиться.
_TOPICAL_MIN = 0.35

_LADDER_SOURCE_RENDERERS = frozenset({"article_scroll", "paper_reveal",
                                      "source_card"})


def _block_gap_fullscreen(slot: dict[str, Any]) -> bool:
    """Carve remainders must not become need-less red FS (QC-21 / QC-30).

    The spoken AI window already used the 10 % budget; the leftover 0.9 s
    used to pick ``text-fullscreen/fact-card`` with empty ``grounded_on``.
    """
    return bool(slot.get("carve_remainder"))


def _close_empty_slot(slot: dict[str, Any], block: dict[str, Any], *,
                      budget: VisualBudget, picker: TemplatePicker,
                      catalog: TemplateCatalog, plan: dict[str, Any],
                      variant: str, seed: int, recent_videos: list[str],
                      used_templates: list[str], brand_icons,
                      words: list[dict[str, Any]], plate_src: dict[str, Any] | None,
                      traits: set[str], bg_file: str | None = None,
                      ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    """Чем закрыть кадр, которому не досталось материала (§7.2).

    До этой лестницы у сборщика было ровно две ветки: полноэкранный текст или
    голая плита. На эталонном 0042 стока хватило на шесть кадров из двадцати, и
    четырнадцать закрылись надписью — критик назвал это «хаотичным слайд-шоу из
    текста» и поставил `visual 2/10` при девятнадцати пройденных QC.

    Возвращается ``(ступень, приём-hero, оверлей)``; текст и плита ступеней не
    имеют — их собирает вызывающий код, потому что он же держит счётчик фраз.

    **Порядок обратный таблице ТЗ, и это главное решение здесь.** В таблице
    ступени стоят от самой содержательной к самой дешёвой: карточка, данные,
    источник. Но карточке нужно только акцентное слово — оно есть у каждого
    блока, — а диаграмме нужно число, источнику нужна цитата или бренд. При
    порядке из таблицы трат-free ступень выгребает свой потолок первой, на
    самых обычных блоках, и к блоку с числом лестница приходит уже пустой.

    Замер на эталонном 0042 при нулевом стоке, порядок из таблицы:
    ``card 4, dataviz 1, fullscreen 4, plate 11`` — одиннадцать голых плит при
    норме две. Поэтому ступени идут по редкости условия: сначала те, чьё
    основание блок либо имеет, либо нет (число, цитата), и только потом
    карточка, которая подходит всему. Содержательность решает спор равных.
    """
    nums = _stats_from_text(str(block.get("text") or "")) if block else []
    start = float(slot["start"]) + 0.2
    end = min(float(slot["end"]) - 0.1, start + 3.2)
    window_ok = end - start >= 1.2
    if slot.get("authored_punch"):
        return "", None, None
    # Inherited hall/plate is already the picture. A huge emphasis word on
    # top of the supercomputer shot was the 0042 defect («ВДВОЕ» over the hall).
    if slot.get("inherit_from") is not None:
        return "inherit", None, None

    # 2. Данные — когда блок назвал число. Идёт первой: число больше нечем
    #    показать, а карточка и текст умеют говорить о чём угодно.
    bid = str((block or {}).get("id") or "")
    if (nums and window_ok and budget.allows("dataviz")
            and bid not in budget.dataviz_blocks):
        overlay = _dataviz_overlay(
            slot, nums, {block.get("id", ""): block}, picker,
            variant=variant, seed=seed + int(slot["index"]),
            recent_videos=recent_videos, used=used_templates,
            start=start, end=end,
            why="лестница §7.2, ступень 2: в блоке названо число")
        budget.take("dataviz")
        budget.dataviz_blocks.add(bid)
        used_templates.append(str(overlay.get("template") or ""))
        return "dataviz", None, overlay

    # 3. Источник или устройство. Гейт жёсткий и намеренный: окно статьи
    #    рисуется **только** под настоящий источник из плана. Карточка,
    #    похожая на цитату, но собранная из воздуха, — выдуманный документ, а
    #    не приём монтажа.
    # Каждый показ берёт **свой** источник. Один и тот же документ, трижды
    # въехавший в кадр, — это ровно то «грубое дублирование карточек», на
    # которое жаловался критик; потолок ступени тут упирается не в цифру 3, а
    # в то, сколько источников у ролика вообще есть.
    sources = [s for s in (plan.get("sources") or []) if s.get("domain")]
    source = sources[budget.source] if budget.source < len(sources) else None
    if (source and window_ok and budget.allows("source")
            and {"quote", "brand", "device"} & set(traits)):
        template, _ = picker.pick(
            "browser-ui",
            blob=build_blob(block.get("text"), block.get("heading")),
            traits=traits, variant=variant, duration=end - start,
            recent_videos=recent_videos, exclude=used_templates,
            seed=seed + int(slot["index"]))
        if template.renderer in _LADDER_SOURCE_RENDERERS:
            budget.take("source")
            used_templates.append(template.id)
            return "source", None, {
                "type": "source_card", "start": start, "end": end,
                "template": template.id, "renderer": template.renderer,
                "params": {
                    "domain": str(source.get("domain") or ""),
                    "title": str(source.get("title") or ""),
                    "body": str(source.get("snippet") or ""),
                    "url": str(source.get("url") or ""),
                },
                "traits": sorted(traits),
                "grounded_on": sorted(matched(template.needs, traits)),
                "why": "лестница §7.2, ступень 3: у блока цитата и есть источник",
            }

    # 4. Параллакс-плита: кадр расходится на два слоя, глубина без 3D.
    #    Ступень идёт перед карточкой по той же причине, что и остальные: ей
    #    нужен кадр под приём (`plate_src`) и слот не короче полутора секунд,
    #    а карточке хватает любого блока с акцентным словом.
    # Кадр под приём: пин или подложка, которую этот шот и так покажет. Оба
    # варианта — настоящая картинка из библиотеки; сгенерированную сюда не
    # берём, у неё своя мерка доли AI.
    still = (plate_src and not plate_src.get("ai_generated")) or bool(bg_file)
    # Avatar interstitials are 1.4 s by cut rules; the 1.5 s gate sent them
    # to a need-less red fullscreen and blew QC-21 / QC-30 on 0042.
    reason = str(slot.get("reason") or "")
    interstitial = (
        slot.get("asset_role") == "interstitial" or "перебивка" in reason)
    parallax_min = 1.2 if interstitial else 1.2
    if still and float(slot["duration"]) >= parallax_min and budget.allows("parallax"):
        budget.take("parallax")
        return "parallax", None, {
            "type": "motion", "start": float(slot["start"]),
            "end": float(slot["end"]), "renderer": "parallax",
            "shift_pct": 0.04,
            "why": "лестница §7.2, ступень 4: есть кадр под приём и слот ≥ "
                   f"{parallax_min:g} с",
        }

    # 1. Карточка-ключ — акцентное слово блока, по возможности с медиа. Идёт
    #    последней среди приёмов: подходит любому блоку, поэтому раньше она
    #    забирала потолок у ступеней, которым блок нужен особенный.
    #    `has_alpha=False`: аватара в этом кадре нет, и всё, что рисуется под
    #    ним, оказалось бы за непрозрачным видео. Отбор по `_HERO_NEEDS` сам
    #    отбросит приёмы, которым нечем наполниться.
    punch_span = _authored_punch_span(
        plan, str((block or {}).get("id") or slot.get("block_id") or ""))
    skip_card = False
    if punch_span is not None:
        _punch_start, punch_end = punch_span
        skip_card = float(slot["start"]) + 0.05 >= punch_end
    # After the authored FS punch the remainder still belongs to this block.
    # A card here reprinted the block opening over the spaghetti line.
    if (not skip_card and block.get("emphasis_word") and budget.allows("card")):
        hero = _hero_device(
            catalog, slot=slot,
            content=_hero_content(
                block, slot, brand_icons,
                title=str(plan.get("title") or ""), words=words),
            has_alpha=False, plate_src=plate_src,
            recent_videos=recent_videos, exclude=used_templates,
            seed=seed + int(slot["index"]), picker=picker, variant=variant,
            block=block, video_duration=float(plan["duration_sec"]),
            exclude_renderers=frozenset(_FULL_FRAME_HEROES) | {"hero-oversize"})
        if hero:
            budget.take("card")
            used_templates.append(hero["template"])
            hero["why"] = "лестница §7.2, ступень 1: у блока есть акцентное слово"
            return "card", hero, None

    return "", None, None


# Тип концовки, при котором последний кадр обязан совпасть с первым (§6.3).
LOOP_SEAM_CTA = "visual_loop_seam"

# Разворот движения камеры: шов держится, только если в конце камера идёт
# обратно — иначе первый кадр после петли рванёт в ту же сторону, и склейка
# станет заметна именно тем, чем должна была спрятаться.
_KENBURNS_MIRROR = {
    "kenburns/zoom-in-center": "kenburns/zoom-out-center",
    "kenburns/zoom-out-center": "kenburns/zoom-in-center",
    "kenburns/pan-left": "kenburns/pan-right",
    "kenburns/pan-right": "kenburns/pan-left",
    "kenburns/pan-up": "kenburns/pan-down",
    "kenburns/pan-down": "kenburns/pan-up",
}


def _mirror_kenburns(kb: dict[str, Any] | None) -> dict[str, Any] | None:
    """Тот же наезд, пущенный назад.

    Если у шаблона нет пары в словаре, разворачиваем численно: `zoom` и `pan` —
    это и есть всё движение, а имя шаблона остаётся честным указанием на то,
    откуда взяты параметры.
    """
    if not kb:
        return None
    out = dict(kb)
    name = str(kb.get("template") or "")
    out["template"] = _KENBURNS_MIRROR.get(name, name)
    zoom = kb.get("zoom")
    if isinstance(zoom, (list, tuple)) and len(zoom) == 2:
        out["zoom"] = [float(zoom[1]), float(zoom[0])]
    pan = kb.get("pan")
    if isinstance(pan, (list, tuple)) and len(pan) == 2:
        out["pan"] = [-float(pan[0]), -float(pan[1])]
    out["mirrored"] = True
    return out


def _close_loop_seam(shots: list[dict[str, Any]], plan: dict[str, Any],
                     ) -> dict[str, Any] | None:
    """Свести последний кадр с первым (§6.3, R-4).

    Работает только при ``cta.type == "visual_loop_seam"``: шов — это тип
    концовки, а не украшение, которое можно навесить на любой ролик. Совпасть
    обязаны три вещи — материал в кадре, движение камеры (в обратную сторону)
    и экранный глиф. Проверяет это уже не код сборки, а QC-27 по кадрам
    отрендеренного файла: план может обещать совпадение и всё равно разойтись
    на посадке текста.

    Возвращает описание шва для плана либо ``None``, если тип концовки другой
    или сводить нечего (ролик из одного кадра).
    """
    cta_type = str((plan.get("cta") or {}).get("type") or "")
    if cta_type != LOOP_SEAM_CTA or len(shots) < 2:
        return None

    head, tail = shots[0], shots[-1]
    fields = []
    for field in ("file", "asset_id", "source", "license", "attribution",
                  "credit", "page_url", "ai_generated", "mock", "fit", "focus"):
        if field in head:
            if tail.get(field) != head.get(field):
                fields.append(field)
            tail[field] = head[field]
    if head.get("kind") in ("footage", "fullscreen_text"):
        tail["kind"] = head["kind"]
    if head.get("content"):
        tail["content"] = head["content"]
    mirrored = _mirror_kenburns(head.get("kenburns"))
    if mirrored is not None:
        tail["kenburns"] = mirrored
    tail["loop_seam"] = True
    tail["reason"] = ("§6.3 R-4: шов лупа — последний кадр повторяет первый, "
                      "камера идёт обратно")
    return {
        "cta_type": cta_type,
        "head_index": int(head.get("index", 0)),
        "tail_index": int(tail.get("index", len(shots) - 1)),
        "asset_id": head.get("asset_id"),
        "kenburns": (mirrored or {}).get("template"),
        "changed_fields": fields,
    }


class _Escalation:
    """Правило эскалации §6.1 R-2 и §6.5: приём обязан меняться.

    Две вещи, которые ритм не покрывает и на которых 0042 потерял удержание:

    * внутри затяжки два соседних кадра не могут держаться на одном рендерере
      — иначе это не «новый визуальный факт каждые 1.5–3 с», а один и тот же
      приём с другими буквами;
    * ответ обязан отличаться от всей затяжки **классом**, а не только id.
      На 0042 `payoff`-кадром был `text-fullscreen/blur-out-up` — ровно тот же
      приём, что и двумя кадрами раньше.

    Запрет уходит в `TemplatePicker.pick(exclude_renderers=…)` и там снимается,
    если после него в разрешённом наборе ничего не остаётся: кадр без приёма
    хуже повторённого приёма.

    Замер на 0042 после Q1/Q2, обе версии: план **не меняется** от включения
    правила — приёмов, несущих рендерер, в ролике всего пять-семь, и они уже
    расходятся. Проверено обратным прогоном с `bans()`, возвращающим пустое
    множество: `payoff ∩ stretch` пусто в обоих случаях. То есть здесь это
    страховка, а не починка; она сработает на сценарии, где затяжка длиннее и
    приёмов в ней больше.
    """

    def __init__(self) -> None:
        self.prev_beat: str = ""
        self.prev_renderer: str = ""
        self.stretch_renderers: set[str] = set()

    def bans(self, beat: str) -> frozenset[str]:
        if beat == "payoff":
            return frozenset(self.stretch_renderers)
        if beat == "stretch" and self.prev_beat == "stretch" and self.prev_renderer:
            return frozenset({self.prev_renderer})
        return frozenset()

    def note(self, beat: str, renderer: str) -> None:
        renderer = str(renderer or "")
        if beat == "stretch" and renderer:
            self.stretch_renderers.add(renderer)
        self.prev_beat = beat
        self.prev_renderer = renderer


def _slot_beats(plan: dict[str, Any]) -> None:
    """Проставить `beat` слотам, если план собран до §6.1.

    Кэш переживает правки кода: `--from P7` поднимает `cut_plan.json`, снятый
    прошлой сборкой, и слоты в нём биты не несут. Считаем на месте — карта
    выводится из блоков, а они в плане есть.
    """
    slots = plan.get("slots") or []
    if slots and all(s.get("beat") for s in slots):
        return
    annotate_slots(slots, plan.get("blocks") or [])


def build_variant(ctx, plan: dict[str, Any], words_doc: dict[str, Any],
                  assets: dict[int, dict[str, Any]], prepared: dict[int, dict[str, Any]],
                  catalog: TemplateCatalog, avatar_meta: dict[str, Any],
                  sfx_map: dict[str, Any], *, variant: str,
                  recent_videos: list[str], preferences: dict[str, Any] | None = None,
                  asset_rotation: int = 0,
                  picker: TemplatePicker | None = None,
                  peer_exclude: Iterable[str] = ()) -> dict[str, Any]:
    if picker is None:
        cfg = getattr(ctx, "cfg", None)
        picker = TemplatePicker(catalog, ScenarioIndex.load(cfg, catalog=catalog))
    picker = _RecordingPicker(picker)
    seed = _variant_seed(plan["video_id"], variant)
    # Какие источники требуют подписи в кадре — сказано в самом каталоге
    # источников, а не в коде: право на кадр приходит вместе с ним.
    sources_spec = _load_yaml(ctx.cfg.repo_root / "config" / "stock_sources.yaml")
    # Накопленные предпочтения влияют на версию A: она несёт «текущий дефолт»,
    # а B остаётся альтернативой, иначе обучение схлопнет обе версии в одну.
    prefs = (preferences or {}) if variant == "A" else {}
    ban_templates = _template_excludes_for(plan, ctx)
    used_templates: list[str] = []
    peer_block = [str(x) for x in peer_exclude if x]
    slots = plan["slots"]
    _slot_beats(plan)
    escalation = _Escalation()
    _sync_fullscreen_overlay_content(slots, plan)
    _retime_fullscreen_slots(slots, plan, words_doc.get("words") or [])
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
    fs_cap = _fullscreen_cap(ctx.cfg)
    fs_count = 0
    budget = VisualBudget()
    # Приём хука ставится один раз за ролик. В окно 0–3 с на 0042 попадают три
    # слота, и без этого флага все три брали бы приём из intro-hooks подряд —
    # то же «две полноэкранные надписи подряд», из-за которых хук и переделан.
    hook_placed = False
    # Оверлеи, которые поставила лестница закрытия кадра: они рождаются в цикле
    # шотов, а общий список оверлеев собирается ниже — сливаются после.
    ladder_overlays: list[dict[str, Any]] = []
    # Библиотека иконок §14: пилюля бренда берёт логотип оттуда. Её отсутствие
    # не должно валить сборку — приём просто не выпадет.
    try:
        brand_icons = load_brand_icons(ctx.cfg)
    except Exception:                                    # noqa: BLE001
        brand_icons = None
    hero_offset = seed % 2
    hero_eligible = 0

    for slot in slots:
        # Что поставил предыдущий кадр — известно только после того, как он
        # собран: веток выхода из итерации много, и запоминать приём в каждой
        # значило бы забыть в одной. Складываем на входе в следующую.
        if shots:
            prev = shots[-1]
            escalation.note(
                str(prev.get("beat") or ""),
                str(prev.get("renderer")
                    or (prev.get("hero") or {}).get("renderer") or ""))
        entry: dict[str, Any] = {
            "index": slot["index"], "start": slot["start"], "end": slot["end"],
            "duration": slot["duration"], "kind": slot["kind"],
            "block_id": slot["block_id"], "role": slot["role"], "mode": slot["mode"],
            "beat": str(slot.get("beat") or "stretch"),
            "reason": slot["reason"],
        }

        # Хук первых секунд разбирается до общих веток: приём этих кадров —
        # решение сценария, а не то, что осталось после подбора материала.
        hook_block = blocks_by_id.get(slot["block_id"], {})
        hook_pick = None if hook_placed else _pick_hook_shot(
            slot, hook_block, plan, picker, catalog, variant=variant, seed=seed,
            recent_videos=recent_videos,
            used_templates=used_templates + peer_block,
            has_asset=assets.get(slot["index"]) is not None)
        if hook_pick is not None:
            hook_tpl, _hook_trace = hook_pick
            if hook_tpl.renderer == "fullscreen_text":
                # Экранная строка хука — из сценария; `gap_phrase` остаётся
                # запасным вариантом, а не источником по умолчанию.
                content = str((plan.get("hook") or {}).get("on_screen") or "").strip()
                if not content:
                    content = str(slot.get("content")
                                  or (hook_block.get("overlay") or {}).get("content")
                                  or "").strip()
                content = soften_on_screen_copy(content)
                if content and _claim_screen_phrase(used_screen_phrases, content):
                    bg_file = _slot_bg_file(slot, slots, prepared, assets, ctx, plan)
                    asset = assets.get(slot["index"])
                    used_templates.append(hook_tpl.id)
                    fs_params = _attach_fs_media(
                        _fullscreen_params(hook_tpl, content, hook_block, plan), bg_file)
                    # Хук читают за секунду: задержки входа здесь нет намеренно.
                    fs_params.pop("enter_delay", None)
                    entry.update({
                        "kind": "fullscreen_text",
                        "content": content,
                        "template": hook_tpl.id,
                        "renderer": hook_tpl.renderer,
                        "params": fs_params,
                        "invert": True,
                        "carries_line": True,
                        "hook": True,
                        "accent_word": _fullscreen_accent(content, hook_block),
                        "accent_family": accent_family(hook_block),
                        "file": bg_file,
                        "asset_id": (asset or {}).get("asset_id"),
                        "source": (asset or {}).get("source"),
                        "license": (asset or {}).get("license"),
                        "attribution": (asset or {}).get("attribution", ""),
                        "page_url": (asset or {}).get("page_url", ""),
                        "ai_generated": bool((asset or {}).get("ai_generated")),
                        "credit": _credit_line(asset or {}, sources_spec),
                        "why": "хук §5.2: приём первых секунд выбран по сценарию",
                    })
                    fs_count += 1
                    hook_placed = True
                    shots.append(entry)
                    continue
            elif hook_tpl.renderer == "footage":
                # Холодное открытие: кадр до первого слова, без надписи.
                prep = prepared.get(slot["index"])
                asset = assets.get(slot["index"])
                if prep is not None and asset is not None:
                    used_templates.append(hook_tpl.id)
                    entry.update({
                        "kind": "footage",
                        "template": hook_tpl.id,
                        "renderer": hook_tpl.renderer,
                        "hook": True,
                        "file": prep["file"],
                        "asset_id": asset.get("asset_id"),
                        "source": asset.get("source"),
                        "license": asset.get("license"),
                        "attribution": asset.get("attribution", ""),
                        "page_url": asset.get("page_url", ""),
                        "ai_generated": bool(asset.get("ai_generated")),
                        "credit": _credit_line(asset, sources_spec),
                        "why": "хук §5.2: холодное открытие кадром до первого слова",
                    })
                    hook_placed = True
                    shots.append(entry)
                    continue

        if (slot.get("authored_punch")
                and slot["kind"] not in (*AVATAR_KINDS, "fullscreen_text")):
            punch_block = blocks_by_id.get(slot.get("block_id"), {})
            overlay = punch_block.get("overlay") or {}
            raw = str(overlay.get("content") or slot.get("content") or "").strip()
            raw = enrich_overlay_punch(raw, str(punch_block.get("text") or "")) or raw
            if raw:
                slot["kind"] = "fullscreen_text"
                slot["content"] = raw
                entry["kind"] = "fullscreen_text"
                entry["content"] = raw

        if slot["kind"] == "fullscreen_text":
            content = slot.get("content", "")
            block = blocks_by_id.get(slot["block_id"], {})
            asset = assets.get(slot["index"])
            content = enrich_overlay_punch(str(content or ""), str(block.get("text") or "")) or content
            onset = spoken_onset_for_content(
                [w for w in words_doc["words"]
                 if str(w.get("block_id") or "") == str(slot.get("block_id") or "")],
                str(content), block.get("emphasis_word"))
            content = soften_on_screen_copy(str(content or ""))
            bg_file = _slot_bg_file(slot, slots, prepared, assets, ctx, plan)
            # Cap + uniqueness: skip duplicate Nature / НАОБОРОТ; over-cap → plate.
            if fs_count >= fs_cap or not _claim_screen_phrase(used_screen_phrases, content):
                entry.update({
                    "kind": "footage",
                    "file": bg_file,
                    "asset_id": (asset or {}).get("asset_id"),
                    "source": (asset or {}).get("source"),
                    "license": (asset or {}).get("license"),
                    "attribution": (asset or {}).get("attribution", ""),
                    "page_url": (asset or {}).get("page_url", ""),
                    "ai_generated": bool((asset or {}).get("ai_generated")),
                    "credit": _credit_line(asset or {}, sources_spec),
                    "gap_reason": "fullscreen cap or duplicate phrase: plate without text",
                })
                shots.append(entry)
                continue
            preferred = prefs.get(f"fullscreen_text@{slot['role']}")
            s_content = str(content or "")
            signals = {"lines_ge_7"} if s_content.count("\n") >= 7 else {"lines_lt_7"}
            overlay_hint = str((block.get("overlay") or {}).get("template_hint") or "")
            head = [p for p in (preferred, slot.get("template_hint"), overlay_hint) if p]
            fs_traits = block_traits(str(block.get("text") or ""))
            template, _ = picker.pick(
                "text-fullscreen",
                blob=s_content,
                signals=signals,
                traits=fs_traits,
                variant=variant,
                duration=float(slot["duration"]),
                recent_videos=recent_videos,
                exclude=used_templates + ban_templates,
                seed=seed,
                prefer_head=head,
                exclude_renderers=escalation.bans(str(slot.get("beat") or "")),
            )
            used_templates.append(template.id)
            fs_params = _fullscreen_params(template, content, block, plan)
            fs_params = _attach_fs_media(fs_params, bg_file)
            if onset is not None and float(slot["start"]) + 0.15 < float(onset):
                fs_params["enter_delay"] = max(
                    float(fs_params.get("enter_delay") or 0),
                    float(onset) + 0.05 - float(slot["start"]))
            entry.update({
                "kind": "fullscreen_text",
                "content": content,
                "template": template.id,
                "renderer": template.renderer,
                "params": fs_params,
                "invert": True,
                "carries_line": True,
                "accent_word": _fullscreen_accent(content, block),
                "accent_family": accent_family(block),
                "traits": sorted(fs_traits) if fs_traits else [],
                "grounded_on": grounded_for(
                    template.needs, fs_traits, shown=str(content or "")),
                "why_template": explain_choice(
                    template, fs_traits, shown=str(content or "")),
                "file": bg_file,
                "asset_id": (asset or {}).get("asset_id"),
                "source": (asset or {}).get("source"),
                "license": (asset or {}).get("license"),
                "attribution": (asset or {}).get("attribution", ""),
                "page_url": (asset or {}).get("page_url", ""),
                "ai_generated": bool((asset or {}).get("ai_generated")),
                "credit": _credit_line(asset or {}, sources_spec),
            })
            if bg_file is None:
                entry["gap_reason"] = "фон под полноэкранный текст не найден"
            fs_count += 1
            shots.append(entry)
            continue

        prep = prepared.get(slot["index"])
        asset = assets.get(slot["index"])
        # §9.2, третья точка: материал есть, но он не про эту реплику. Честнее
        # закрыть кадр приёмом, чем поставить чужую картинку — зритель видит
        # расхождение раньше, чем успевает прочитать субтитр.
        off_topic = False
        if asset is not None and slot["kind"] not in AVATAR_KINDS:
            topical = asset.get("topical")
            if topical is None:
                topical = topical_match_score(
                    asset.get("tags") or [],
                    str(blocks_by_id.get(slot["block_id"], {}).get("text") or ""),
                    str(plan.get("category") or ""))
            off_topic = float(topical) < _TOPICAL_MIN
            # Prefer pins locked to overlapping speech (Nature figure, carved
            # supercomputer hall) must not be discarded because the whole-block
            # CONCEPTS table does not list that noun.
            if off_topic and asset.get("speech_locked"):
                off_topic = False
        if prep is None or off_topic or (asset is None
                                         and slot["kind"] not in AVATAR_KINDS):
            # Пустой слот идёт по лестнице §7.2: карточка → диаграмма →
            # источник → полноэкранный текст → плита. Раньше веток было две,
            # и на 0042 четырнадцать кадров из двадцати закрылись надписью.
            bg_file = _slot_bg_file(slot, slots, prepared, assets, ctx, plan)
            gap_block = blocks_by_id.get(slot["block_id"], {})
            gap_traits = block_traits(str(gap_block.get("text") or "")) if gap_block else set()
            rung, hero_dev, overlay_dev = _close_empty_slot(
                slot, gap_block, budget=budget, picker=picker, catalog=catalog,
                plan=plan, variant=variant, seed=seed,
                recent_videos=recent_videos, used_templates=used_templates,
                brand_icons=brand_icons,
                words=[w for w in words_doc["words"]
                       if float(w["end"]) > float(slot["start"])
                       and float(w["start"]) < float(slot["end"])],
                plate_src=_plate_source(slot, slots, prepared, assets),
                traits=gap_traits, bg_file=bg_file)
            if rung:
                entry.update({
                    "kind": "footage",
                    "file": bg_file,
                    "asset_id": None,
                    "traits": sorted(gap_traits) if gap_traits else [],
                    "gap_reason": f"материал не найден: кадр закрыт приёмом ({rung})",
                    "ladder_rung": rung,
                })
                if hero_dev:
                    entry["hero"] = hero_dev
                if overlay_dev and overlay_dev.get("type") == "motion":
                    # Движение кадра живёт на самом шоте, а не в оверлеях:
                    # композитор читает `shot["motion"]`, и оверлеем приём
                    # доехал бы до плана и не доехал бы до кадра.
                    entry["motion"] = {k: v for k, v in overlay_dev.items()
                                       if k not in ("type", "start", "end")}
                elif overlay_dev:
                    ladder_overlays.append(overlay_dev)
                shots.append(entry)
                continue
            content = ""
            if fs_count < fs_cap and not _block_gap_fullscreen(slot):
                if slot.get("authored_punch"):
                    overlay = gap_block.get("overlay") or {}
                    raw = str(overlay.get("content") or "")
                    content = (enrich_overlay_punch(
                        raw, str(gap_block.get("text") or "")) or raw)
                    content = soften_on_screen_copy(str(content or ""))
                    if not _claim_screen_phrase(used_screen_phrases, content):
                        content = ""
                elif _authored_overlay_owns_gap_fs(gap_block):
                    # Authored punch / plaque owns the copy for this block.
                    # Auto «Называются уравнения Навье-Стокса» stole the
                    # 0050 b5 card and blew QC-30 / QC-24 leftover plates.
                    content = ""
                else:
                    raw = gap_phrase(words_doc["words"], slot, gap_block,
                                     used=used_screen_phrases)
                    content = soften_on_screen_copy(str(raw or ""))
                    key = _norm_screen_key(content)
                    raw_key = _norm_screen_key(raw)
                    # Soften must not recreate a slogan already on screen.
                    if key and key in used_screen_phrases and key != raw_key:
                        content = ""
                    elif key:
                        used_screen_phrases.add(key)
            if fs_count >= fs_cap or not content:
                entry.update({
                    "kind": "footage",
                    "file": bg_file,
                    "asset_id": None,
                    "gap_reason": ("fullscreen cap: plate without text"
                                   if fs_count >= fs_cap
                                   else "no unique phrase: plate without text"),
                    "ladder_rung": "plate",
                })
                budget.take("plate")
                shots.append(entry)
                continue
            gap_traits = block_traits(str(gap_block.get("text") or "")) if gap_block else set()
            s_content = str(content or "")
            signals = {"lines_ge_7"} if s_content.count("\n") >= 7 else {"lines_lt_7"}
            preferred = prefs.get(f"fullscreen_text@{slot['role']}")
            overlay_hint = str((gap_block.get("overlay") or {}).get("template_hint") or "")
            head = [p for p in (preferred, slot.get("template_hint"), overlay_hint) if p]
            template, _ = picker.pick(
                "text-fullscreen",
                blob=s_content or str(gap_block.get("text") or ""),
                signals=signals,
                traits=gap_traits,
                variant=variant,
                duration=float(slot["duration"]),
                recent_videos=recent_videos,
                exclude=used_templates + ban_templates,
                seed=seed + int(slot["index"]),
                prefer_head=head,
                exclude_renderers=escalation.bans(str(slot.get("beat") or "")),
            )
            used_templates.append(template.id)
            onset = spoken_onset_for_content(
                [w for w in words_doc["words"]
                 if str(w.get("block_id") or "") == str(slot.get("block_id") or "")],
                str(content), gap_block.get("emphasis_word"))
            fs_params = _fullscreen_params(template, content, gap_block, plan)
            fs_params = _attach_fs_media(fs_params, bg_file)
            if (onset is not None and content
                    and float(slot["start"]) + 0.15 < float(onset)
                    and punch_families_overlap(str(content), _semantic_screen_text(gap_block))):
                fs_params["enter_delay"] = max(
                    float(fs_params.get("enter_delay") or 0),
                    float(onset) + 0.05 - float(slot["start"]))
            entry.update({
                "kind": "fullscreen_text",
                "content": content,
                "template": template.id,
                "renderer": template.renderer,
                "params": fs_params,
                "invert": True,
                "carries_line": True,
                "accent_word": _fullscreen_accent(content, gap_block),
                "accent_family": accent_family(gap_block),
                "traits": sorted(gap_traits) if gap_traits else [],
                "grounded_on": grounded_for(
                    template.needs, gap_traits, shown=str(content or "")),
                "why_template": explain_choice(
                    template, gap_traits, shown=str(content or "")),
                "file": bg_file,
                "asset_id": None,
                "gap_reason": "материал не найден: кадр закрыт словом блока",
                "ladder_rung": "fullscreen",
            })
            budget.take("fullscreen")
            if bg_file is None:
                entry["gap_reason"] += "; фон — сцена ролика"
            fs_count += 1
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
                exclude=used_templates + ban_templates,
                prefer_head=head,
                seed=seed + slot["index"],
            )
            used_templates.append(kb_template.id)

        transition_entry: dict[str, Any] | None = None
        if slot.get("transition_in") == "dynamic":
            if str(slot.get("role") or "") == "cta":
                # Identity close must show the money shot, not a catalog wipe.
                # The last QC-30 probe is ~40.8 s of a 44.5 s cut — the CTA
                # head. Clone-wall's red card was 0.77 of that frame.
                transition_entry = {"template": "transitions/cut", "renderer": "cut",
                                    "duration": 0.0, "params": {}}
            else:
                category = "avatar-entry" if slot["kind"] in AVATAR_KINDS else "transitions"
                preferred = prefs.get(f"transition@{slot['role']}")
                head = [preferred] if preferred else []
                exclude = _transition_exclude(
                    category, used_templates, role=str(slot.get("role") or ""))
                tr, _ = picker.pick(
                    category,
                    variant=variant,
                    duration=0.24,
                    recent_videos=recent_videos,
                    exclude=exclude,
                    prefer_head=head,
                    tags={"dynamic", "entry"},
                    seed=seed + slot["index"] * 3,
                )
                if category == "avatar-entry" and tr.id in AVATAR_ENTRY_DENY:
                    transition_entry = {"template": "transitions/cut", "renderer": "cut",
                                        "duration": 0.0, "params": {}}
                else:
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
            take_hero = (hero_eligible + hero_offset) % 2 == 0
            # Setup authored «за головой — крупное слово»; seed%2 used to skip it.
            if str(slot.get("role") or "") == "setup":
                take_hero = True
            if take_hero:
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
                    has_alpha=(int(slot["index"]) in alpha_slots
                               or slot["kind"] == "avatar"),
                    plate_src=_plate_source(slot, slots, prepared, assets),
                    recent_videos=recent_videos, exclude=used_templates + peer_block,
                    seed=seed, picker=picker, variant=variant, block=block,
                    video_duration=float(plan["duration_sec"]),
                    exclude_renderers=escalation.bans(
                        str(slot.get("beat") or "")))
                if hero_entry:
                    used_templates.append(hero_entry["template"])

        entry.update({
            "file": prep["dst"],
            "bg_file": (
                (avatar_bgs.get(int(slot["index"]))
                 or avatar_bgs.get(int(slot.get("inherit_from") or -1)))
                if slot["kind"] == "avatar"
                else (str(prep.get("top_src") or "").strip() or None)
                if slot["kind"] == "split" else None
            ),
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
            # Karaoke must not go behind the head. hero-title-behind is the
            # only intentional keyword path, and it is a hero overlay.
            "text_behind_head": False,
            "ai_generated": bool(asset.get("ai_generated")),
            "mock": bool(asset.get("mock")),
            "fit": prep.get("fit"), "focus": [prep.get("focus_x"), prep.get("focus_y")],
            "kenburns": ({"template": kb_template.id, **kb_template.params}
                         if kb_template else None),
            "transition": transition_entry,
            "hero": hero_entry,
        })
        shots.append(entry)

    # Шов лупа сводится до сборки оверлеев: CTA-плашка выбирается по тому,
    # смыкается кадр или нет, а не наоборот.
    loop_seam = _close_loop_seam(shots, plan)

    overlays = _build_overlays(ctx, plan, words_doc["words"], catalog, variant=variant,
                               seed=seed, recent_videos=recent_videos, used=used_templates,
                               picker=picker, budget=budget, loop_seam=loop_seam,
                               peer_exclude=peer_block)
    # Приёмы лестницы §7.2 родились в цикле шотов — доливаем их к общим
    # оверлеям здесь, чтобы дальше все проверки видели один список.
    overlays.extend(ladder_overlays)

    # Drop plaques that echo an on-screen punch FS (slots may still say footage
    # when the plaque was built; shots are authoritative after gap promote).
    fs_punches = [
        (float(s["start"]), float(s["end"]), str(s.get("content") or ""))
        for s in shots
        if s.get("kind") == "fullscreen_text" and s.get("content")
    ]
    filtered = []
    for ov in overlays:
        if ov.get("type") == "plaque":
            pt = str((ov.get("params") or {}).get("text")
                     or (ov.get("params") or {}).get("content") or "")
            if pt and any(float(ov["start"]) < pe and float(ov["end"]) > ps
                          and punch_families_overlap(pt, pc)
                          for ps, pe, pc in fs_punches):
                continue
        filtered.append(ov)
    overlays = filtered

    # First avatar gaze mask (~2–4s): informative top/center hook card, no HeyGen.
    first_avatar = next((s for s in shots if s.get("kind") == "avatar"), None)
    brandbook = getattr(getattr(ctx, "cfg", None), "brandbook", None) or {}
    if (first_avatar is not None and wants_gaze_plaque(plan)
            and gaze_plaque_fits_face_band(brandbook)):
        a0 = float(first_avatar["start"])
        a1 = float(first_avatar["end"])
        # Cover the early eye-line beat inside the first avatar window.
        g0 = max(a0, min(a0 + 0.05, 3.0))
        if a0 <= 4.5:
            g0 = max(a0, min(2.0, a0 + 0.05)) if a0 < 2.0 else a0
        g1 = min(a1, max(g0 + 1.6, min(a0 + 2.0, 4.8)))
        if g1 - g0 >= 1.0:
            hook = _gaze_plaque_copy(plan)
            overlays.append({
                "type": "plaque",
                "start": round(g0, 3),
                "end": round(g1, 3),
                "template": "lower-thirds/note-pin",
                "params": {
                    "text": hook,
                    "content": hook,
                    "name": hook,
                    "role": "hook",
                    "position": "top",
                    "direction": "left",
                },
                "why": "r6: informative card over first avatar to mask off-camera gaze",
            })

    overlays = _clamp_plaques_at_avatar_cuts(overlays, shots)
    shots = _clear_plate_gap_when_covered(shots, overlays)

    # Smart captions: punch-family mute stays. Card mute is only bulky type
    # (FS slam beat, punch/slam heroes, source cards, CTA) — not behind-head
    # kickers or the whole FS B-roll hold.
    punch_windows: list[tuple[float, float, str]] = []
    for s in shots:
        if s.get("kind") == "fullscreen_text" and s.get("content"):
            ps, pe = _fs_mute_span(s)
            punch_windows.append((ps, pe, str(s.get("content") or "")))
        hero = s.get("hero") or {}
        hw = str(
            (hero.get("params") or {}).get("word")
            or (hero.get("params") or {}).get("title")
            or (hero.get("params") or {}).get("head")
            or (hero.get("params") or {}).get("content")
            or hero.get("word") or hero.get("title") or ""
        )
        if not hw:
            continue
        end = float(s["end"])
        if hero.get("duration"):
            end = min(end, float(s["start"]) + float(hero["duration"]))
        punch_windows.append((float(s["start"]), end, hw))
    for ovl in overlays:
        if str(ovl.get("type") or "") != "plaque":
            continue
        pt = str((ovl.get("params") or {}).get("text")
                 or (ovl.get("params") or {}).get("content") or "")
        if pt:
            punch_windows.append((float(ovl["start"]), float(ovl["end"]), pt))
    card_windows = _caption_mute_windows(shots, overlays)
    line_windows = _caption_line_windows(shots, overlays)
    _warn_mute_coverage(card_windows, words_doc["words"])
    subtitles = _build_subtitle_cues(
        words_doc["words"],
        punch_windows=punch_windows,
        mute_windows=card_windows,
        line_windows=line_windows,
        family_by_block={b["id"]: accent_family(b)
                         for b in plan.get("blocks", [])},
    )
    _stamp_subtitle_baselines(subtitles, shots, brandbook)

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
        "loop_seam": loop_seam,
        "overlays": overlays,
        "subtitles": subtitles,
        "backdrop": {"scene": scene, "tone": scene_tone(scene),
                     "why": scene_why(scene),
                     "plate": _backdrop_plate(
                         ctx.cfg, scene, video_id=str(plan.get("video_id") or ""),
                         category=str(plan.get("category") or ""))},
        "subtitle_style": {
            "mode": ctx.cfg.brand("subtitles.readability_mode", "stroke"),
            "baseline_y": (
                ctx.cfg.brand("subtitles.baseline_y_avatar_shift", 720)
                if (avatar_meta.get("segments") or [])
                else ctx.cfg.brand("subtitles.baseline_y_default", 1180)
            ),
            "caption": pick_caption_style(plan, ctx.cfg.brandbook),
        },
        "avatar_compose_zoom": compose_zoom,
        "avatar": avatar_meta.get("segments", []),
        "templates_used": used_templates,
        "pick_traces": picker.traces,
        "asset_rotation": asset_rotation,
        "preferences_applied": sorted(prefs) if prefs else [],
        "cta_window": plan.get("cta_window"),
        "stats": plan.get("stats", {}),
    }



_LOOP_BACK_CTA = "outro-cta/loop-back"


def _ab_pool_templates(plan: dict[str, Any]) -> list[str]:
    """Hook / hero / cta ids версии — пулы, которые B не должна клонировать."""
    ids: list[str] = []
    seen: set[str] = set()

    def add(tid: Any) -> None:
        name = str(tid or "")
        if name and name not in seen:
            seen.add(name)
            ids.append(name)

    for shot in plan.get("shots") or []:
        if shot.get("hook"):
            add(shot.get("template"))
        hero = shot.get("hero")
        if isinstance(hero, dict):
            add(hero.get("template"))
    for overlay in plan.get("overlays") or []:
        if str(overlay.get("type") or "") == "cta":
            add(overlay.get("template"))
    return ids


def _force_ab_difference(plans: dict[str, dict[str, Any]], variants: list[str],
                         catalog: TemplateCatalog, required: int, ctx) -> int:
    """§15.12.2 — довести различие версий до требуемого **конструктивно**.

    Сначала смысловые пулы hook / hero / cta (MUST-014): не «другой Ken Burns
    того же кадра». Затем Ken Burns и переходы внутри своей категории.
    """
    a_plan, b_plan = plans[variants[0]], plans[variants[1]]
    diff = diff_count(a_plan["templates_used"], b_plan["templates_used"])
    if diff >= required:
        return diff

    a_templates = set(a_plan["templates_used"])
    swapped = 0

    def _enough() -> bool:
        return diff + swapped >= required

    def _commit(old_id: str, new_id: str) -> None:
        nonlocal swapped
        used = list(b_plan.get("templates_used") or [])
        if old_id in used:
            b_plan["templates_used"] = [new_id if t == old_id else t for t in used]
        else:
            b_plan["templates_used"] = used + [new_id]
        swapped += 1

    def _alts(category: str, current_id: str, *,
              renderer: str | None = None,
              skip_ids: Iterable[str] = ()) -> list:
        skip = set(skip_ids)
        used_b = set(b_plan.get("templates_used") or [])
        out = []
        for template in catalog.by_category(category):
            if template.id == current_id or template.id in skip:
                continue
            if template.id in a_templates or template.id in used_b:
                continue
            if not getattr(template, "brand_ok", True):
                continue
            if renderer is not None and template.renderer != renderer:
                continue
            out.append(template)
        return out

    for shot in b_plan.get("shots") or []:
        if _enough():
            break
        if not shot.get("hook"):
            continue
        current_id = str(shot.get("template") or "")
        if not current_id or current_id not in a_templates:
            continue
        current = catalog.by_id(current_id)
        renderer = str((current.renderer if current is not None
                        else shot.get("renderer")) or "") or None
        alternatives = _alts("intro-hooks", current_id, renderer=renderer)
        if not alternatives:
            continue
        replacement = alternatives[0]
        shot["template"] = replacement.id
        _commit(current_id, replacement.id)

    for shot in b_plan.get("shots") or []:
        if _enough():
            break
        hero = shot.get("hero")
        if not isinstance(hero, dict):
            continue
        current_id = str(hero.get("template") or "")
        if not current_id or current_id not in a_templates:
            continue
        alternatives = _alts("hero-devices", current_id)
        if not alternatives:
            continue
        replacement = alternatives[0]
        hero["template"] = replacement.id
        hero["renderer"] = replacement.renderer
        _commit(current_id, replacement.id)

    if not b_plan.get("loop_seam"):
        for overlay in b_plan.get("overlays") or []:
            if _enough():
                break
            if str(overlay.get("type") or "") != "cta":
                continue
            current_id = str(overlay.get("template") or "")
            if not current_id or current_id not in a_templates:
                continue
            alternatives = _alts("outro-cta", current_id, skip_ids=(_LOOP_BACK_CTA,))
            if not alternatives:
                continue
            replacement = alternatives[0]
            overlay["template"] = replacement.id
            overlay["renderer"] = replacement.renderer
            _commit(current_id, replacement.id)

    for shot in b_plan.get("shots") or []:
        if _enough():
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
            _commit(old_id, replacement.id)
            break

    diff = diff_count(a_plan["templates_used"], b_plan["templates_used"])
    if swapped:
        ctx.warn(f"версии сошлись по шаблонам: {swapped} решений версии B заменены "
                 f"альтернативами, различий стало {diff} (§15.12.2)",
                 swapped=swapped, diff=diff)
    return diff


def run_step(ctx) -> dict[str, Any]:
    plan = copy.deepcopy(ctx.read("cut_plan.json"))
    words_doc = ctx.read("words.json")
    words = list(words_doc.get("words") or [])
    sync_overlays_from_script(plan, ctx.cfg.repo_root, words=words)
    sync_broll_from_script(plan, ctx.cfg.repo_root, words=words)
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

    plan = dict(plan)
    plan["slots"] = apply_ai_carves(plan["slots"], base_assets)
    plan["slots"] = inherit_ai_plates_onto_speech(
        plan["slots"], base_assets, words_doc.get("words") or [])
    plan["slots"] = split_empty_at_authored_punch(
        plan["slots"], plan, base_assets, words_doc.get("words") or [])

    recent_videos = _recent_video_ids(ctx, limit=3)
    pillarbox_limit = int(ctx.cfg.get("limits.pillarbox_per_video", 2))
    preferences = _load_preferences(ctx)
    matte_reports, behind_layers, vfx_clips, matte_summary = _prepare_matting(
        ctx, plan, avatar_meta)

    variants = list(ctx.variants)
    plans: dict[str, dict[str, Any]] = {}
    peer_exclude: list[str] = []
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
            preferences=preferences, asset_rotation=offset, picker=picker,
            peer_exclude=peer_exclude)
        plans[variant]["matting"] = matte_summary
        ctx.write(f"edit_plan_{variant}.json", plans[variant])
        if not peer_exclude:
            peer_exclude = _ab_pool_templates(plans[variant])

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
