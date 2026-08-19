"""JSON-схема входного сценария (§8.1) и оценка хронометража.

Схема нарочно строгая: ``additionalProperties: false`` на верхних уровнях, чтобы
опечатка в имени поля падала на P0, а не превращалась в молча проигнорированное
указание режиссёра.
"""

from __future__ import annotations

import re
from typing import Any

BLOCK_ROLES = ("hook", "setup", "evidence", "develop", "twist", "cta")
CATEGORIES = ("ai", "space", "tech", "medicine", "science")
OVERLAY_TYPES = ("fullscreen_text", "frame", "lower_third", "highlight", "none")
SCREEN_TEMPLATES = ("browser", "notepad", "search", "chat_ai", "arxiv_card", "patent_card")
AVATAR_MODES = ("auto", "on", "off")
CTA_TYPES = ("question", "loop", "statement")

SCRIPT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "REDSHIFT script",
    "type": "object",
    "required": ["meta", "blocks"],
    "additionalProperties": False,
    "properties": {
        "meta": {
            "type": "object",
            "required": ["video_id", "topic", "category", "target_duration_sec"],
            "additionalProperties": False,
            "properties": {
                "video_id": {"type": "string", "pattern": r"^[A-Za-z0-9_\-]{3,64}$"},
                "title": {"type": "string"},
                "topic": {"type": "string", "minLength": 2},
                "category": {"enum": list(CATEGORIES)},
                "language": {"type": "string", "default": "ru"},
                "target_duration_sec": {"type": "number", "minimum": 20, "maximum": 120},
                "allow_memes": {"type": "boolean", "default": True},
                "allow_bg_vfx": {"type": "boolean", "default": True},
                "publish_date": {"type": "string"},
                "music_mood": {"type": "string"},
                "notes": {"type": "string"},
            },
        },
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "domain"],
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "domain": {"type": "string"},
                    "url": {"type": "string"},
                    "show_on_screen": {"type": "boolean", "default": True},
                    "screen_template": {"enum": list(SCREEN_TEMPLATES)},
                    "snippet": {"type": "string"},
                    "highlight_line": {"type": "string"},
                    "license": {"type": "string"},
                },
            },
        },
        "blocks": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["id", "role", "text"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": r"^[A-Za-z0-9_\-]{1,32}$"},
                    "role": {"enum": list(BLOCK_ROLES)},
                    "text": {"type": "string", "minLength": 1},
                    "emphasis_word": {"type": "string"},
                    "avatar": {"enum": list(AVATAR_MODES), "default": "auto"},
                    "visual_intent": {"type": "string"},
                    "broll_queries": {"type": "array", "items": {"type": "string"}},
                    "overlay": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "type": {"enum": list(OVERLAY_TYPES)},
                            "content": {"type": "string"},
                            "template_hint": {"type": "string"},
                            "target": {"type": "string"},
                        },
                    },
                    "sfx": {"type": "string"},
                    "meme_allowed": {"type": "boolean"},
                    "answers_hook": {"type": "boolean"},
                    "source_ref": {"type": "string"},
                    "mode_hint": {"enum": ["A", "B", "C"]},
                },
            },
        },
        "cta": {
            "type": "object",
            "required": ["text"],
            "additionalProperties": False,
            "properties": {
                "text": {"type": "string"},
                "type": {"enum": list(CTA_TYPES), "default": "question"},
            },
        },
    },
}

# --- оценка хронометража -----------------------------------------------------

_VOWELS_RU = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
_VOWELS_LAT = set("aeiouyAEIOUY")
# Средний темп плотной подачи в референсах: ~5.4 слога/сек (§2.2 «без воздуха»).
SYLLABLES_PER_SEC = 5.4
# Межблочные микропаузы после оптимизации (§4.2.2: 80–120 мс).
INTER_BLOCK_PAUSE_SEC = 0.10


def count_syllables(text: str) -> int:
    """Слоги ≈ гласные. Для русского это оценка с погрешностью <5 %."""
    total = 0
    for word in re.findall(r"[^\W\d_]+", text, flags=re.UNICODE):
        vowels = sum(1 for ch in word if ch in _VOWELS_RU or ch in _VOWELS_LAT)
        total += max(1, vowels)
    return total


def count_words(text: str) -> int:
    return len(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def estimate_block_duration(text: str, *, rate: float = SYLLABLES_PER_SEC) -> float:
    syll = count_syllables(text)
    if syll == 0:
        return 0.0
    # Знаки препинания дают короткие паузы даже после оптимизации.
    punct = len(re.findall(r"[,.;:!?—–]", text))
    return syll / rate + punct * 0.06


def estimate_script_duration(script: dict[str, Any], *, rate: float = SYLLABLES_PER_SEC) -> float:
    blocks = script.get("blocks", [])
    total = sum(estimate_block_duration(b.get("text", ""), rate=rate) for b in blocks)
    total += max(0, len(blocks) - 1) * INTER_BLOCK_PAUSE_SEC
    return round(total, 2)


def extract_quotes(text: str) -> list[str]:
    """Прямые цитаты: «…», "…", '…' (§8.2 QUOTE_TOO_LONG)."""
    out: list[str] = []
    for pattern in (r"«([^»]+)»", r"\"([^\"]+)\"", r"“([^”]+)”"):
        out.extend(re.findall(pattern, text))
    return out
