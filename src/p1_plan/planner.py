"""P1: ``validated_script.json`` → ``draft_plan.json``.

Черновой план — это распределение ролей блоков по режимам кадра (§3.5) и
подготовка произносимого текста для TTS (§4.2.5). Точные тайминги здесь ещё
неизвестны: они появятся после озвучки и выравнивания, и P5 пересчитает план
уже по ним (§7.1). Задача P1 — принять **структурные** решения:

* какой блок идёт в каком режиме кадра и где появляется аватар;
* сколько full-screen text, подсветок и мемов планируется на ролик;
* какая музыкальная подложка соответствует категории;
* сколько озвучки заказать с запасом +18…25 % (§4.2.4).
"""

from __future__ import annotations

import hashlib
from typing import Any

from ..lib.logging import get_logger
from ..lib.schema import estimate_block_duration
from ..lib.text import load_pronunciation, normalize_text, spoken_text

_log = get_logger("p1")

# Режимы по ролям — опорная сетка §6.
ROLE_MODE_PREFERENCE: dict[str, tuple[str, ...]] = {
    "hook":     ("C", "A"),
    "setup":    ("A", "C"),
    "evidence": ("B", "C"),
    "develop":  ("C", "A"),
    "twist":    ("A", "C"),
    "cta":      ("A", "C"),
}

# Подложка выбирается по тегам, а не по имени файла (§14.2).
#
# Заказчик прислал живые записи и попросил: «Пометь их тэгами для удобного
# использования в видео, чтобы монтаж умел брать их самостоятельно». Тег
# честнее слота: у записи их несколько, и подложка находится по совпадению
# смыслов. Здесь задаётся, чего мы хотим от подложки в каждой рубрике, а
# ``pick_bed`` уже ищет, что этому ближе всего из того, что есть в наличии.
MUSIC_TAGS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "space":    ("space", "ambient", "wide"),
    "ai":       ("tech", "pulse", "driving"),
    "tech":     ("tech", "driving"),
    "science":  ("space", "strings", "bright"),
    "medicine": ("calm", "piano", "sparse"),
}
MUSIC_TAGS_DEFAULT: tuple[str, ...] = ("space", "ambient", "calm")
# Поворот в сюжете просит нажима, и здесь рубрика уступает драматургии.
MUSIC_TAGS_ON_TWIST: tuple[str, ...] = ("tense", "driving", "strings")


def music_tags_for(category: str, *, twist: bool = False) -> tuple[str, ...]:
    """Каких тегов ждём от подложки под эту рубрику."""
    if twist:
        return MUSIC_TAGS_ON_TWIST
    return MUSIC_TAGS_BY_CATEGORY.get(category or "", MUSIC_TAGS_DEFAULT)


AVATAR_MODES = ("A", "B")   # режимы, в которых аватар присутствует в кадре


def _mode_for_block(block: dict[str, Any], *, avatar_forced: str) -> str:
    hint = block.get("mode_hint")
    if hint:
        return hint
    prefs = ROLE_MODE_PREFERENCE.get(block.get("role", "develop"), ("C",))
    if avatar_forced == "off":
        return "C"
    if avatar_forced == "on":
        return prefs[0] if prefs[0] in AVATAR_MODES else "A"
    return prefs[0]


def _balance_avatar_share(blocks: list[dict[str, Any]], total_sec: float,
                          share_range: tuple[float, float]) -> list[dict[str, Any]]:
    """Подогнать долю аватара под 35–60 % (§3.5), не ломая жёсткие указания.

    Блоки с ``avatar: on|off`` неприкосновенны — это решение сценариста.
    Двигаем только ``auto``: сначала добираем долю самыми «личными» ролями
    (twist, setup), затем снимаем лишнее с наименее личных (develop, evidence).
    """
    lo, hi = share_range
    mid = (lo + hi) / 2.0

    def current() -> float:
        return sum(b["_estimated_sec"] for b in blocks if b["mode"] in AVATAR_MODES) / max(total_sec, 1e-6)

    # Насколько «личная» роль: чем меньше индекс, тем охотнее блок отдаём аватару.
    role_rank = {"twist": 0, "setup": 1, "cta": 2, "evidence": 3, "develop": 4, "hook": 5}

    def _rank(block: dict[str, Any]) -> int:
        return role_rank.get(block["role"], 99)

    guard = 0
    while current() < lo and guard < 40:
        guard += 1
        candidates = [b for b in blocks if b["avatar_directive"] == "auto" and b["mode"] == "C"]
        if not candidates:
            break
        # Берём тот блок, после которого доля окажется ближе всего к середине
        # диапазона: так один длинный блок не выбрасывает нас за верхнюю границу.
        chosen = min(candidates, key=lambda b: (
            abs((current() + b["_estimated_sec"] / max(total_sec, 1e-6)) - mid), _rank(b)))
        chosen["mode"] = "B" if chosen["role"] == "evidence" else "A"
        chosen["mode_reason"] = "добор доли аватара до нижней границы 35 %"

    guard = 0
    while current() > hi and guard < 40:
        guard += 1
        candidates = [b for b in blocks if b["avatar_directive"] == "auto" and b["mode"] in AVATAR_MODES]
        if not candidates:
            break
        chosen = min(candidates, key=lambda b: (
            abs((current() - b["_estimated_sec"] / max(total_sec, 1e-6)) - mid), _rank(b)))
        chosen["mode"] = "C"
        chosen["mode_reason"] = "снятие доли аватара до верхней границы 60 %"
    return blocks


def _limit_split_share(blocks: list[dict[str, Any]], total_sec: float, max_share: float) -> None:
    """§3.5: режим B (сплит) — не более 25 % хронометража."""
    def share() -> float:
        return sum(b["_estimated_sec"] for b in blocks if b["mode"] == "B") / max(total_sec, 1e-6)

    guard = 0
    while share() > max_share and guard < 20:
        guard += 1
        splits = [b for b in blocks if b["mode"] == "B"]
        if not splits:
            break
        # Убираем самый длинный сплит: он и «съедает» долю.
        victim = max(splits, key=lambda b: b["_estimated_sec"])
        victim["mode"] = "A" if victim["avatar_directive"] != "off" else "C"
        victim["mode_reason"] = "сплит-скрин ограничен 25 % хронометража"


def plan(script: dict[str, Any], cfg) -> dict[str, Any]:
    meta = script["meta"]
    pron = load_pronunciation(cfg.repo_root / "config" / "pronunciation.json")
    limits = cfg.get("limits")

    blocks: list[dict[str, Any]] = []
    for raw in script["blocks"]:
        tokens = normalize_text(raw["text"], pron, block_id=raw["id"],
                                emphasis_word=raw.get("emphasis_word"))
        directive = raw.get("avatar", "auto")
        entry = {
            "id": raw["id"],
            "role": raw["role"],
            "text": raw["text"],
            "spoken_text": spoken_text(tokens),
            "tokens": [t.to_dict() for t in tokens],
            "emphasis_word": raw.get("emphasis_word"),
            # Кто закрывает хук — знает P0, а держать паузу перед ударом
            # приходится P3: без этой пометки он ищет ответ по роли вслепую.
            "answers_hook": bool(raw.get("answers_hook", False)),
            "avatar_directive": directive,
            "mode": _mode_for_block(raw, avatar_forced=directive),
            "mode_reason": "роль блока (§6)" if not raw.get("mode_hint") else "mode_hint из сценария",
            "visual_intent": raw.get("visual_intent", ""),
            "broll_queries": list(raw.get("broll_queries", [])),
            "overlay": raw.get("overlay", {"type": "none"}),
            "sfx": raw.get("sfx", "none"),
            "meme_allowed": bool(raw.get("meme_allowed", meta.get("allow_memes", True))),
            "source_ref": raw.get("source_ref"),
            "_estimated_sec": round(estimate_block_duration(raw["text"]), 3),
        }
        blocks.append(entry)

    total_sec = sum(b["_estimated_sec"] for b in blocks)

    # Первое появление аватара — не позже 0:06 (§3.5, §6).
    first_limit = float(limits.get("first_avatar_appearance_sec", 6.0))
    conflicts: list[dict[str, Any]] = []

    def _first_avatar_at() -> float | None:
        cursor = 0.0
        for block in blocks:
            if block["mode"] in AVATAR_MODES:
                return cursor
            cursor += block["_estimated_sec"]
        return None

    if (_first_avatar_at() or 1e9) > first_limit:
        # Кандидаты — блоки, целиком укладывающиеся в лимит и не запрещённые
        # автору сценария явной директивой avatar: off.
        cursor = 0.0
        promoted = False
        for block in blocks:
            if cursor > first_limit:
                break
            if block["avatar_directive"] != "off" and block["mode"] == "C":
                block["mode"] = "A"
                block["mode_reason"] = "первое появление аватара обязано быть ≤ 0:06 (§6)"
                promoted = True
                break
            cursor += block["_estimated_sec"]
        if not promoted and (_first_avatar_at() or 1e9) > first_limit:
            # Ни один ранний блок не отдаётся аватару: это конфликт сценария и
            # §6, и его нельзя разрешить молча — либо хук короче, либо аватар
            # разрешён в первом блоке.
            conflicts.append({
                "code": "AVATAR_FIRST_APPEARANCE_LATE",
                "message": (
                    f"первое появление аватара на {_first_avatar_at():.1f} сек, "
                    f"позже требуемых {first_limit:.0f} сек: ранние блоки помечены "
                    f"avatar: off. Сократите хук или разрешите аватар раньше"
                ),
                "first_avatar_sec": round(_first_avatar_at() or 0.0, 2),
                "limit_sec": first_limit,
            })

    blocks = _balance_avatar_share(
        blocks, total_sec, tuple(limits.get("avatar_share", [0.35, 0.60])))
    _limit_split_share(blocks, total_sec, float(limits.get("split_share_max", 0.25)))

    # Раскладка по таймлайну — черновая, будет пересчитана в P5.
    cursor = 0.0
    for block in blocks:
        block["planned_start_sec"] = round(cursor, 3)
        cursor += block["_estimated_sec"]
        block["planned_end_sec"] = round(cursor, 3)

    avatar_sec = sum(b["_estimated_sec"] for b in blocks if b["mode"] in AVATAR_MODES)
    fs_lo, fs_hi = limits.get("fullscreen_text_per_video", [2, 4])
    scripted_fs = sum(1 for b in blocks if b["overlay"].get("type") == "fullscreen_text")
    hl_lo, hl_hi = limits.get("highlight_per_video", [1, 3])
    scripted_hl = sum(1 for b in blocks if b["overlay"].get("type") == "highlight")

    twist = (any(b["role"] == "twist" for b in blocks)
             and meta.get("category") in ("ai", "tech"))
    music_tags = list(music_tags_for(meta.get("category", ""), twist=twist))
    music_mood = meta.get("music_mood") or ""

    buffer_pct = float(cfg.get("elevenlabs.length_buffer_pct", 22))
    target = float(meta.get("target_duration_sec", total_sec))

    draft = {
        "video_id": meta["video_id"],
        "title": meta.get("title", ""),
        "category": meta.get("category"),
        "language": meta.get("language", "ru"),
        "target_duration_sec": target,
        "estimated_speech_sec": round(total_sec, 3),
        "tts_length_buffer_pct": buffer_pct,
        "tts_target_sec": round(total_sec * (1.0 + buffer_pct / 100.0), 3),
        "blocks": blocks,
        "avatar": {
            "planned_share": round(avatar_sec / max(total_sec, 1e-6), 4),
            "planned_sec": round(avatar_sec, 3),
            "appearances": sum(1 for b in blocks if b["mode"] in AVATAR_MODES),
            "avatar_id": cfg.get("heygen.avatar_id"),
        },
        "planned_counts": {
            "fullscreen_text": max(fs_lo, min(fs_hi, max(scripted_fs, fs_lo))),
            "fullscreen_text_scripted": scripted_fs,
            "highlight": max(hl_lo, min(hl_hi, max(scripted_hl, hl_lo))),
            "highlight_scripted": scripted_hl,
            "memes": 1 if (meta.get("allow_memes") and any(b["meme_allowed"] for b in blocks)) else 0,
            "bg_vfx": int(limits.get("bg_vfx_per_video", 2)) if meta.get("allow_bg_vfx") else 0,
        },
        "music_mood": music_mood,
        "music_tags": music_tags,
        "sources": script.get("sources", []),
        "cta": script.get("cta", {}),
        "modes_by_block": {b["id"]: b["mode"] for b in blocks},
        "conflicts": conflicts,
    }
    return draft


def run_step(ctx) -> dict[str, Any]:
    script = ctx.read("validated_script.json")
    draft = plan(script, ctx.cfg)
    ctx.write("draft_plan.json", draft)

    for conflict in draft.get("conflicts", []):
        ctx.warn(f"{conflict['code']}: {conflict['message']}", **{
            k: v for k, v in conflict.items() if k not in ("code", "message")})

    share = draft["avatar"]["planned_share"]
    lo, hi = ctx.cfg.get("limits.avatar_share", [0.35, 0.60])
    if not (lo <= share <= hi):
        ctx.warn(
            f"плановая доля аватара {share:.0%} вне {lo:.0%}–{hi:.0%}; "
            f"P5 доберёт её врезками",
            planned_share=share,
        )
    _log.info("черновой план готов", extra={
        "blocks": len(draft["blocks"]),
        "avatar_share": share,
        "modes": ",".join(f"{b['id']}:{b['mode']}" for b in draft["blocks"]),
        "tts_target_sec": draft["tts_target_sec"],
        "music": ", ".join(draft["music_tags"]),
    })
    return {"avatar_share": share, "tts_target_sec": draft["tts_target_sec"],
            "music_mood": draft["music_mood"], "music_tags": draft["music_tags"]}
