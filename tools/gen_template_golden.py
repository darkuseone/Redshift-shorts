#!/usr/bin/env python3
"""Генератор golden-корпуса выбора шаблонов (Phase C, Step 3, plan v2.1 §7.1).

Снимает снимки решений на НЕМИГРИРОВАННОМ assemble.py на уровне catalog.pick
(не templates_used / не _force_ab_difference).

Генерирует:
1. tests/data/template_golden_manifest.json — замороженный снимок manifest.json
   с фиксированным состоянием last_used_in.
2. tests/data/template_golden.json — корпус кейсов (~30 сценариев × варианты A/B
   × фиксированный seed) с фиксацией category, prefer (информативно) и
   template_id (контракт).
"""

from __future__ import annotations
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence

from src.lib.jsonio import read_json, write_json
from src.lib.templates import TemplateCatalog

# Regex constants из assemble.py (сохранены с fallback на случай будущей миграции)
try:
    from src.p11_assemble.assemble import (
        _BEATISH,
        _CODEISH,
        _DIFFISH,
        _SHELLISH,
    )
except ImportError:
    _CODEISH = re.compile(
        r"(?m)(^\s*(async\s+)?function\b|^\s*def\s+\w+|^\s*const\s+\w+|^\s*class\s+\w+"
        r"|[{};]\s*$|=>|::|\breturn\s+\w|\bimport\s+\w)",
    )
    _SHELLISH = re.compile(
        r"(?m)(^\s*\$\s|\b(?:npx|npm|pip3?|cargo|hyperframes|brew|apt-get)\s)",
    )
    _DIFFISH = re.compile(
        r"(?ms)(^\s*---\s*$)|(^\s*diff\s+--git\b)|"
        r"(^\s*-[^-\n].*$.*?^\s*\+[^+\n])",
    )
    _BEATISH = re.compile(
        r"(drop|freeze|beat|hard\s*cut|on the beat|дроп|бит|замороз)",
        re.I,
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_SRC = REPO_ROOT / "templates" / "manifest.json"
DATA_DIR = REPO_ROOT / "tests" / "data"
GOLDEN_MANIFEST_PATH = DATA_DIR / "template_golden_manifest.json"
GOLDEN_CORPUS_PATH = DATA_DIR / "template_golden.json"

DEFAULT_SEED = 42


@dataclass
class ScenarioSpec:
    name: str
    category: str
    call_site: str
    blob: str
    nums: list[dict[str, Any]] = field(default_factory=list)
    duration: float = 2.5
    preferred: str = ""
    template_hint: str = ""
    exclude: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""


# --- Немигрированные эвристики assemble.py для каждого call-site -------------

def eval_unmigrated_browser_ui(blob: str, variant: str) -> tuple[str, list[str]]:
    """Логика browser-ui / frames-cards из assemble.py:1236-1289."""
    if variant == "A":
        card_category = "browser-ui"
        card_prefer = [
            "browser-ui/chat-thread",
            "browser-ui/article-highlight",
            "browser-ui/browser-scroll",
        ]
        b = blob.lower()
        if any(key in b for key in (
                "ai chat", "ai-chat", "ask anything", "chatgpt",
                "chat gpt", "нейросет", "ии-чат", "чат-бот", "chatbot",
                "gpt-4", "gpt4", "claude.ai")):
            card_prefer = ["browser-ui/ai-chat-reveal"] + [
                item for item in card_prefer if item != "browser-ui/ai-chat-reveal"
            ]
        elif any(key in b for key in (
                "app showcase", "fitness app", "weekly goal",
                "burned calories", "app store", "фитнес", "калори",
                "дашборд", "dashboard app", "workout app",
                "smartphone screens")):
            card_prefer = ["browser-ui/app-showcase"] + [
                item for item in card_prefer if item != "browser-ui/app-showcase"
            ]
        elif any(key in b for key in (
                "chatgpt exchange", "avatar ranking", "сравнение ии",
                "таблица моделей", "ranking")):
            card_prefer = ["browser-ui/chatgpt-exchange"] + [
                item for item in card_prefer if item != "browser-ui/chatgpt-exchange"
            ]
        elif any(key in b for key in (
                "claude", "anthropic", "opus", "claude exchange")):
            card_prefer = ["browser-ui/claude-exchange"] + [
                item for item in card_prefer if item != "browser-ui/claude-exchange"
            ]
        elif any(key in b for key in (
                "imessage", "message thread", "смс", "сообщения", "переписка")):
            card_prefer = ["browser-ui/message-thread-reveal"] + [
                item for item in card_prefer if item != "browser-ui/message-thread-reveal"
            ]
        elif any(key in b for key in (
                "notes", "apple notes", "заметки", "список", "notes reveal")):
            card_prefer = ["browser-ui/notes-reveal"] + [
                item for item in card_prefer if item != "browser-ui/notes-reveal"
            ]
        elif any(key in b for key in (
                "notification", "cascade", "уведомлен", "alert", "push")):
            card_prefer = ["browser-ui/notification-cascade"] + [
                item for item in card_prefer if item != "browser-ui/notification-cascade"
            ]
        return card_category, card_prefer
    else:
        card_category = "frames-cards"
        card_prefer = ["frames-cards/paper-reveal", "frames-cards/arxiv-card"]
        return card_category, card_prefer


def eval_unmigrated_dataviz(
    blob: str,
    nums: list[dict[str, Any]],
    variant: str,
) -> tuple[list[str], list[str], set[str]]:
    """Логика data-viz из assemble.py:1507-1606.

    Возвращает (prefer, prefer_base, signals).
    """
    pct = bool(nums and str(nums[0].get("suffix") or "").lstrip().startswith("%"))
    declining = bool(
        len(nums) >= 2 and float(nums[1]["value"]) < float(nums[0]["value"])
    )

    base = (
        ["data-viz/conic-progress-ring", "data-viz/stat-countup-card"]
        if len(nums) == 1 and pct and variant != "B"
        else ["data-viz/stat-countup-card"]
        if len(nums) == 1
        else [
            "data-viz/bar-chart-race",
            "data-viz/chart-story",
            "data-viz/mk-line-graph",
            "data-viz/animated-bar-chart",
            "data-viz/compare-bars",
            "data-viz/bar-race-mini",
        ]
        if len(nums) >= 4
        else (
            [
                "data-viz/decline-chart",
                "data-viz/chart-story",
                "data-viz/mk-line-graph",
                "data-viz/animated-bar-chart",
                "data-viz/compare-bars",
                "data-viz/bar-race-mini",
            ]
            if declining
            else [
                "data-viz/chart-story",
                "data-viz/mk-line-graph",
                "data-viz/animated-bar-chart",
                "data-viz/compare-bars",
                "data-viz/bar-race-mini",
            ]
        )
    )

    if variant == "B" and len(nums) >= 2:
        base = ["data-viz/compare-bars", "data-viz/stat-countup-card"]

    prefer = list(base)
    b = blob.lower()

    if variant != "B" and any(key in b for key in (
            "spain", "españa", "espan", "испан", "madrid", "catalun",
            "comunidad autónoma", "pib per")):
        prefer = ["data-viz/spain-map"] + [item for item in prefer if item != "data-viz/spain-map"]

    rating_like = bool(
        len(nums) == 1
        and not pct
        and 0.0 < float(nums[0]["value"]) <= 5.0
        and abs(float(nums[0]["value"]) - round(float(nums[0]["value"]))) > 1e-9
    )

    if variant != "B" and (rating_like or any(key in b for key in (
            "stars", "star rating", "звезд", "рейтинг", "оценк",
            "отзыв", "app store", "satisfaction"))):
        prefer = ["data-viz/star-rating-fill"] + [
            item for item in prefer if item != "data-viz/star-rating-fill"
        ]

    if variant != "B" and any(key in b for key in (
            "united states", "u.s.", "сша", "америк", "census",
            "population density", "per square mile", " by state",
            "штат ", "калифорн", "нью-йорк", "нью йорк", "texas",
            "california")):
        prefer = ["data-viz/us-map"] + [item for item in prefer if item != "data-viz/us-map"]

    if variant != "B" and any(key in b for key in (
            "interstate flow", "flow connection", "city-to-city",
            "city to city", "corridor", "миграционн", "поток между",
            "рейс между", "между городами")):
        prefer = ["data-viz/us-map-flow"] + [
            item for item in prefer if item != "data-viz/us-map-flow"
        ]

    if variant != "B" and any(key in b for key in (
            "hex grid", "hex map", "hexagonal", "hexagon",
            "гексагон", "гекс-карт", "income by state",
            "household income")):
        prefer = ["data-viz/us-map-hex"] + [
            item for item in prefer if item != "data-viz/us-map-hex"]

    if variant != "B" and any(key in b for key in (
            "world map", "global gdp", "gdp per capita",
            "world atlas", "imf", "миров", "карта мира",
            "ввп на душу")):
        prefer = ["data-viz/world-map"] + [
            item for item in prefer if item != "data-viz/world-map"]

    if variant != "B" and (re.search(r"\$\s*\d", b) or any(key in b for key in (
            "usd", "dollar", "revenue", "valuation", "market cap",
            "выручк", "капитализац", "доллар"))):
        prefer = ["data-viz/apple-money-count"] + [
            item for item in prefer if item != "data-viz/apple-money-count"]

    if variant != "B" and any(key in b for key in (
            "north korea", "northkorea", "кндр", "северной коре",
            "северная коре", "locked down", "изоляц", "санкци",
            "пхеньян", "pyongyang", "закрыт")):
        prefer = ["data-viz/north-korea-locked-down"] + [
            item for item in prefer if item != "data-viz/north-korea-locked-down"
        ]

    if variant != "B" and any(key in b for key in (
            "transatlantic", "jfk", "cdg", "new york to paris",
            "нью-йорк", "нью йорк", "париж", "рейс ", "самолёт",
            "самолет", "перелёт", "перелет", "flight to")):
        prefer = ["data-viz/nyc-paris-flight"] + [
            item for item in prefer if item != "data-viz/nyc-paris-flight"
        ]

    if variant != "B" and any(key in b for key in (
            "goals reached", "progress track", "great job",
            "целей достиг", "прогресс", "достигнут")):
        prefer = ["data-viz/mk-progress-stat"] + [
            item for item in prefer if item != "data-viz/mk-progress-stat"
        ]

    if variant != "B" and any(key in b for key in (
            "flowchart", "блок-схем", "блок схем", "дерево решен",
            "decision tree", "алгоритм", "разветвл")):
        prefer = ["data-viz/flowchart-vertical"] + [
            item for item in prefer if item != "data-viz/flowchart-vertical"
        ]

    # Сигналы для TemplatePicker
    signals = set()
    if nums:
        signals.add("numbers")
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

    return prefer, base, signals


def eval_unmigrated_text_fullscreen(
    content: str,
    variant: str,
    preferred: str = "",
    template_hint: str = "",
) -> tuple[list[str], set[str]]:
    """Логика text-fullscreen из assemble.py:1841-1905."""
    fullscreen_styles = (
        [
            "text-fullscreen/beat-freeze-cut",
            "text-fullscreen/kinetic-stack",
            "text-fullscreen/blur-out-up",
            "text-fullscreen/bottom-up-letters",
            "text-fullscreen/kinetic-type-swap",
            "text-fullscreen/line-by-line-slide",
            "text-fullscreen/particle-text-dissolve",
            "text-fullscreen/per-word-crossfade",
            "text-fullscreen/scan-band",
            "text-fullscreen/scramble-reveal",
            "text-fullscreen/shared-axis-z",
            "text-fullscreen/code-3d-extrude",
            "text-fullscreen/code-diff",
            "text-fullscreen/code-particle-assemble",
            "text-fullscreen/code-scroll",
            "text-fullscreen/code-typing",
            "text-fullscreen/terminal-simulator",
            "text-fullscreen/apple-terminal-clear-dark",
            "text-fullscreen/dark-plus",
            "text-fullscreen/number-slam-card",
        ]
        if variant == "A"
        else ["text-fullscreen/stack-3lines", "text-fullscreen/fact-card"]
    )

    styles = list(fullscreen_styles)
    s_content = str(content or "")

    if variant == "A" and re.search(r"\d", s_content):
        styles = [
            "text-fullscreen/number-slam-card",
            "text-fullscreen/kinetic-stack",
        ]
    if variant == "A" and _CODEISH.search(s_content):
        styles = [
            "text-fullscreen/code-3d-extrude",
            "text-fullscreen/code-particle-assemble",
            "text-fullscreen/code-scroll",
            "text-fullscreen/code-typing",
            "text-fullscreen/terminal-simulator",
            "text-fullscreen/apple-terminal-clear-dark",
            "text-fullscreen/dark-plus",
        ] + styles
    if variant == "A" and _CODEISH.search(s_content) and s_content.count("\n") < 7:
        styles = ["text-fullscreen/code-typing"] + styles
    if variant == "A" and s_content.count("\n") >= 7:
        styles = ["text-fullscreen/code-scroll"] + styles
    if variant == "A" and _DIFFISH.search(s_content):
        styles = ["text-fullscreen/code-diff"] + styles
    if variant == "A" and re.search(r"(?m)^\s*def\s+", s_content):
        styles = ["text-fullscreen/dark-plus"] + styles
    if variant == "A" and _SHELLISH.search(s_content):
        styles = [
            "text-fullscreen/apple-terminal-clear-dark",
            "text-fullscreen/terminal-simulator",
        ] + styles
    if variant == "A" and _BEATISH.search(s_content):
        styles = ["text-fullscreen/beat-freeze-cut"] + styles

    prefer = ([preferred] if preferred else []) + ([template_hint] if template_hint else []) + styles

    signals = set()
    if s_content.count("\n") >= 7:
        signals.add("lines_ge_7")
    else:
        signals.add("lines_lt_7")

    return prefer, signals


def eval_unmigrated_transitions(
    variant: str,
    category: str = "transitions",
    preferred: str = "",
) -> tuple[list[str], list[str], list[str]]:
    """Логика transitions из assemble.py:1960-1981.

    Возвращает (prefer, tags, exclude).
    """
    tr_prefer = [preferred] if preferred else []
    if variant == "A" and category == "transitions":
        tr_prefer.extend([
            "transitions/transitions-other",
            "transitions/transitions-light",
            "transitions/transitions-destruction",
            "transitions/transitions-cover",
            "transitions/transitions-blur",
            "transitions/transitions-3d",
            "transitions/mk-clone-wall-transition",
            "transitions/whip-pan",
            "transitions/thermal-distortion",
            "transitions/sdf-iris",
            "transitions/light-leak",
            "transitions/gravitational-lens",
            "transitions/glitch",
            "transitions/cinematic-zoom",
            "transitions/zoom-through",
        ])
    tags = ["dynamic", "entry"]
    exclude = ["transitions/cut"]
    return tr_prefer, tags, exclude


def eval_unmigrated_lowerthirds_plaque() -> list[str]:
    """Логика lower-thirds plaque domain из assemble.py:1403."""
    return ["lower-thirds/source-domain"]


def eval_unmigrated_lowerthirds_overlay(hint: str = "") -> list[str]:
    """Логика lower-thirds overlay из assemble.py:1436."""
    lockups = [
        "lower-thirds/accent-underline",
        "lower-thirds/clean-bar",
        "lower-thirds/dark-card",
    ]
    return ([hint] + lockups) if hint else lockups


def eval_unmigrated_outro_cta(variant: str) -> list[str]:
    """Логика outro-cta из assemble.py:1458-1460."""
    return (
        ["outro-cta/subscribe-pulse"]
        if variant == "A"
        else ["outro-cta/logo-brand-close", "outro-cta/subscribe-pulse"]
    )


# --- Набор репрезентативных сценариев (~30+ сценариев) ------------------------

SCENARIOS: list[ScenarioSpec] = [
    # Browser-UI (7 keyword rules + neutral + negative)
    ScenarioSpec(
        name="browser_ai_chat",
        category="browser-ui",
        call_site="assemble.py:1290",
        blob="лучший ai chat для программистов на gpt-4",
        duration=3.0,
        notes="keywords: ai chat, gpt-4 -> ai-chat-reveal",
    ),
    ScenarioSpec(
        name="browser_app_showcase",
        category="browser-ui",
        call_site="assemble.py:1290",
        blob="новый fitness app для отслеживания калорий в app store",
        duration=3.0,
        notes="keywords: fitness app, app store -> app-showcase",
    ),
    ScenarioSpec(
        name="browser_chatgpt_exchange",
        category="browser-ui",
        call_site="assemble.py:1290",
        blob="сравнение ии моделей и chatgpt exchange в тестах",
        duration=3.0,
        notes="keywords: сравнение ии, chatgpt exchange -> chatgpt-exchange",
    ),
    ScenarioSpec(
        name="browser_claude_exchange",
        category="browser-ui",
        call_site="assemble.py:1290",
        blob="обновление модели claude opus от компании anthropic",
        duration=3.0,
        notes="keywords: claude, opus, anthropic -> claude-exchange",
    ),
    ScenarioSpec(
        name="browser_message_thread",
        category="browser-ui",
        call_site="assemble.py:1290",
        blob="новая переписка и важные сообщения в imessage",
        duration=3.0,
        notes="keywords: переписка, imessage -> message-thread-reveal",
    ),
    ScenarioSpec(
        name="browser_notes_reveal",
        category="browser-ui",
        call_site="assemble.py:1290",
        blob="заметки и структурированный список в apple notes",
        duration=3.0,
        notes="keywords: заметки, apple notes -> notes-reveal",
    ),
    ScenarioSpec(
        name="browser_notification_cascade",
        category="browser-ui",
        call_site="assemble.py:1290",
        blob="системное уведомление и push alert на экране устройства",
        duration=3.0,
        notes="keywords: уведомлен, push, alert -> notification-cascade",
    ),
    ScenarioSpec(
        name="browser_neutral",
        category="browser-ui",
        call_site="assemble.py:1290",
        blob="обзор структуры открытых репозиториев github и документации",
        duration=3.0,
        notes="neutral browser-ui text -> static 3 defaults in A",
    ),
    ScenarioSpec(
        name="neg_claude_cloud",
        category="browser-ui",
        call_site="assemble.py:1290",
        blob="надежный высокоскоростной клауд-хостинг для корпоративной инфраструктуры",
        duration=3.0,
        notes="negative case: 'клауд' != 'claude'",
    ),

    # Data-Viz Keywords (11 keyword rules)
    ScenarioSpec(
        name="dataviz_spain",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="исследование регионов spain и экономика madrid",
        nums=[{"value": "12000"}],
        duration=2.5,
        notes="keywords: spain, madrid -> spain-map",
    ),
    ScenarioSpec(
        name="dataviz_star_rating",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="высокий star rating и отличные оценки пользователей",
        nums=[{"value": "4.8"}],
        duration=2.5,
        notes="keywords: star rating, оценки -> star-rating-fill",
    ),
    ScenarioSpec(
        name="dataviz_us_map",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="официальная перепись census населения в united states сша",
        nums=[{"value": "330", "suffix": "млн"}],
        duration=2.5,
        notes="keywords: census, united states, сша -> us-map",
    ),
    ScenarioSpec(
        name="dataviz_us_map_flow",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="миграционный коридор interstate flow и поток между городами",
        nums=[{"value": "50000"}],
        duration=2.5,
        notes="keywords: interstate flow, поток между -> us-map-flow",
    ),
    ScenarioSpec(
        name="dataviz_us_map_hex",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="статистика доходов income by state на карте hex grid",
        nums=[{"value": "75000"}],
        duration=2.5,
        notes="keywords: income by state, hex grid -> us-map-hex",
    ),
    ScenarioSpec(
        name="dataviz_world_map",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="мировой ввп на душу населения по данным world atlas imf",
        nums=[{"value": "15000"}],
        duration=2.5,
        notes="keywords: ввп на душу, world atlas, imf -> world-map",
    ),
    ScenarioSpec(
        name="dataviz_apple_money_count",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="квартальная выручка технологического гиганта превысила $ 90 млрд usd",
        nums=[{"value": "90", "suffix": "млрд"}],
        duration=2.5,
        notes="pattern: $ 90, keywords: выручка, usd -> apple-money-count",
    ),
    ScenarioSpec(
        name="dataviz_north_korea",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="международные санкции и закрытая экономика северная корея north korea pyongyang",
        nums=[{"value": "26", "suffix": "млн"}],
        duration=2.5,
        notes="keywords: north korea, pyongyang, санкции -> north-korea-locked-down",
    ),
    ScenarioSpec(
        name="dataviz_nyc_paris_flight",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="регулярный рейс нью-йорк париж через transatlantic маршрут cdg",
        nums=[{"value": "5800"}],
        duration=2.5,
        notes="keywords: рейс, нью-йорк, париж, transatlantic -> nyc-paris-flight",
    ),
    ScenarioSpec(
        name="dataviz_mk_progress_stat",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="ключевой рубеж достигнут goals reached в трекере задач progress track",
        nums=[{"value": "100", "suffix": "%"}],
        duration=2.5,
        notes="keywords: goals reached, progress track, достигнут -> mk-progress-stat",
    ),
    ScenarioSpec(
        name="dataviz_flowchart_vertical",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="пошаговый алгоритм и блок-схема ветвления decision tree",
        nums=[{"value": "5"}],
        duration=2.5,
        notes="keywords: алгоритм, блок-схема, decision tree -> flowchart-vertical",
    ),

    # Data-Viz Numeric forms (5 forms + neutral + negatives)
    ScenarioSpec(
        name="dataviz_num_single_pct",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="эффективность модели машинного обучения достигла целевого значения",
        nums=[{"value": "78", "suffix": "%"}],
        duration=2.5,
        notes="single number with % -> conic-progress-ring",
    ),
    ScenarioSpec(
        name="dataviz_num_single_count",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="общее число активных узлов в кластере обработки данных",
        nums=[{"value": "1540"}],
        duration=2.5,
        notes="single number without % -> stat-countup-card",
    ),
    ScenarioSpec(
        name="dataviz_num_four_bars",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="динамика показателей за четыре последовательных периода",
        nums=[{"value": "10"}, {"value": "25"}, {"value": "40"}, {"value": "60"}],
        duration=2.5,
        notes="4+ numbers -> bar-chart-race / animated-bar-chart",
    ),
    ScenarioSpec(
        name="dataviz_num_declining",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="резкое снижение метрик конверсии после сбоя",
        nums=[{"value": "95"}, {"value": "30"}],
        duration=2.5,
        notes="declining (30 < 95) -> decline-chart",
    ),
    ScenarioSpec(
        name="dataviz_num_rating_like",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="средневзвешенный балл удовлетворенности по шкале",
        nums=[{"value": "4.65"}],
        duration=2.5,
        notes="float in (0, 5] -> rating_like -> star-rating-fill",
    ),
    ScenarioSpec(
        name="dataviz_neutral",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="сравнение показателей двух периодов наблюдения",
        nums=[{"value": "40"}, {"value": "80"}],
        duration=2.5,
        notes="neutral 2 ascending numbers -> default dataviz base",
    ),
    ScenarioSpec(
        name="neg_flight_kreyser",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="старый военный крейсер аврора стоит на вечной стоянке",
        nums=[{"value": "1917"}],
        duration=2.5,
        notes="negative case: 'крейсер' != 'рейс '",
    ),
    ScenarioSpec(
        name="inherited_star_rating",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="высокий рейтинг доверия инвесторов к фонду",
        nums=[{"value": "92"}],
        duration=2.5,
        notes="inherited false positive: 'рейтинг' -> star-rating-fill",
    ),
    ScenarioSpec(
        name="inherited_progress",
        category="data-viz",
        call_site="assemble.py:1607",
        blob="заметный прогресс на мирных переговорах сторон",
        nums=[{"value": "75"}],
        duration=2.5,
        notes="inherited false positive: 'прогресс' -> mk-progress-stat",
    ),

    # Text-Fullscreen (rules: \d, code, lines, diff, def, shell, beat, beat+diff, neutral, code+digits)
    ScenarioSpec(
        name="text_number_slam",
        category="text-fullscreen",
        call_site="assemble.py:1901",
        blob="120 миллионов пользователей по всему миру",
        duration=2.0,
        notes="\\d rule: replaces styles with number-slam and kinetic-stack",
    ),
    ScenarioSpec(
        name="text_codeish_short",
        category="text-fullscreen",
        call_site="assemble.py:1901",
        blob="const token = await auth.login();",
        duration=2.0,
        notes="_CODEISH + lines < 7 -> code-typing",
    ),
    ScenarioSpec(
        name="text_codeish_long",
        category="text-fullscreen",
        call_site="assemble.py:1901",
        blob="function transform(data) {\n  let a = data.x;\n  let b = data.y;\n  let c = a * 2;\n  let d = b * 3;\n  let e = c + d;\n  return e;\n}",
        duration=2.0,
        notes="_CODEISH + lines >= 7 -> code-scroll",
    ),
    ScenarioSpec(
        name="text_diffish",
        category="text-fullscreen",
        call_site="assemble.py:1901",
        blob="--- a/engine.py\n+++ b/engine.py\n-max_retries = 3\n+max_retries = 10",
        duration=2.0,
        notes="_DIFFISH -> code-diff",
    ),
    ScenarioSpec(
        name="text_def",
        category="text-fullscreen",
        call_site="assemble.py:1901",
        blob="def compute_weights(x, y):\n    return np.dot(x, y)",
        duration=2.0,
        notes="^\\s*def\\s+ -> dark-plus",
    ),
    ScenarioSpec(
        name="text_shellish",
        category="text-fullscreen",
        call_site="assemble.py:1901",
        blob="$ pip install redshift-cli\n$ redshift init",
        duration=2.0,
        notes="_SHELLISH -> apple-terminal-clear-dark, terminal-simulator",
    ),
    ScenarioSpec(
        name="text_beatish",
        category="text-fullscreen",
        call_site="assemble.py:1901",
        blob="мощный дроп и сокрушительный бит в финале",
        duration=2.0,
        notes="_BEATISH -> beat-freeze-cut",
    ),
    ScenarioSpec(
        name="text_diff_beat",
        category="text-fullscreen",
        call_site="assemble.py:1901",
        blob="--- a/track.py\n+++ b/track.py\n-drop = False\n+beat = True",
        duration=2.0,
        notes="_DIFFISH + _BEATISH -> win direction test: beat wins",
    ),
    ScenarioSpec(
        name="text_code_and_digits",
        category="text-fullscreen",
        call_site="assemble.py:1901",
        blob="const count = 42;\nconst limit = 100;",
        duration=2.0,
        notes="code + digits -> subtractive \\d rule test",
    ),
    ScenarioSpec(
        name="text_neutral",
        category="text-fullscreen",
        call_site="assemble.py:1901",
        blob="Будущее искусственного интеллекта уже меняет индустрию",
        duration=2.0,
        notes="neutral text -> static fullscreen styles (20 in A, 2 in B)",
    ),

    # Other Call-Sites
    ScenarioSpec(
        name="transitions_dynamic",
        category="transitions",
        call_site="assemble.py:1978",
        blob="",
        duration=0.24,
        tags=["dynamic", "entry"],
        exclude=["transitions/cut"],
        notes="dynamic transition in A/B",
    ),
    ScenarioSpec(
        name="lowerthirds_domain",
        category="lower-thirds",
        call_site="assemble.py:1403",
        blob="techcrunch.com",
        duration=2.4,
        notes="domain plaque -> source-domain",
    ),
    ScenarioSpec(
        name="lowerthirds_lockup",
        category="lower-thirds",
        call_site="assemble.py:1436",
        blob="Экспертный комментарий",
        duration=2.4,
        notes="scenario overlay plaque -> lockups",
    ),
    ScenarioSpec(
        name="outro_cta",
        category="outro-cta",
        call_site="assemble.py:1460",
        blob="Подписывайтесь на канал",
        duration=2.0,
        notes="CTA window -> subscribe-pulse / logo-brand-close",
    ),
    ScenarioSpec(
        name="hero_devices",
        category="hero-devices",
        call_site="assemble.py:776",
        blob="",
        duration=3.0,
        exclude=["hero-devices/imac-float", "hero-devices/macbook-open"],
        notes="hero devices with blocked exclusion",
    ),
]


def freeze_manifest(force: bool = False) -> Path:
    """Заморозить копию manifest.json в tests/data/template_golden_manifest.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not GOLDEN_MANIFEST_PATH.exists() or force:
        if not MANIFEST_SRC.exists():
            raise FileNotFoundError(f"Исходный манифест не найден: {MANIFEST_SRC}")
        data = read_json(MANIFEST_SRC)
        write_json(GOLDEN_MANIFEST_PATH, data)
        print(f"Заморожен манифест ({len(data.get('templates', []))} шаблонов) -> {GOLDEN_MANIFEST_PATH}")
    return GOLDEN_MANIFEST_PATH


def generate_golden_corpus(
    catalog: TemplateCatalog,
    *,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Сгенерировать golden-корпус решений на немигрированном assemble.py."""
    cases = []

    for spec in SCENARIOS:
        for variant in ("A", "B"):
            case_id = f"{spec.name}__var_{variant}"
            category = spec.category
            tags = list(spec.tags)
            exclude = list(spec.exclude)
            prefer_base: list[str] = []
            signals: list[str] = []
            prefer: list[str] = []

            # 1. Вычисление немигрированного prefer
            if spec.call_site == "assemble.py:1290":
                cat, prefer = eval_unmigrated_browser_ui(spec.blob, variant)
                category = cat
            elif spec.call_site == "assemble.py:1607":
                prefer, prefer_base, sig_set = eval_unmigrated_dataviz(
                    spec.blob, spec.nums, variant
                )
                signals = sorted(sig_set)
            elif spec.call_site == "assemble.py:1901":
                prefer, sig_set = eval_unmigrated_text_fullscreen(
                    spec.blob, variant, preferred=spec.preferred, template_hint=spec.template_hint
                )
                signals = sorted(sig_set)
            elif spec.call_site == "assemble.py:1978":
                prefer, tags, exclude = eval_unmigrated_transitions(
                    variant, category=spec.category, preferred=spec.preferred
                )
            elif spec.call_site == "assemble.py:1403":
                prefer = eval_unmigrated_lowerthirds_plaque()
            elif spec.call_site == "assemble.py:1436":
                prefer = eval_unmigrated_lowerthirds_overlay(spec.template_hint)
            elif spec.call_site == "assemble.py:1460":
                prefer = eval_unmigrated_outro_cta(variant)
            elif spec.call_site == "assemble.py:776":
                prefer = []
            else:
                prefer = [spec.preferred] if spec.preferred else []

            # 2. Непосредственный вызов catalog.pick (НЕ templates_used / НЕ _force_ab_difference)
            t = catalog.pick(
                category,
                duration=spec.duration,
                recent_videos=(),
                exclude=exclude,
                prefer=prefer,
                seed=seed,
                tags=tags,
            )

            cases.append({
                "id": case_id,
                "scenario": spec.name,
                "call_site": spec.call_site,
                "category": category,
                "variant": variant,
                "blob": spec.blob,
                "prefer": prefer,  # информативно
                "template_id": t.id,  # контракт
                "duration": spec.duration,
                "seed": seed,
                "exclude": exclude,
                "tags": tags,
                "signals": signals,
                "prefer_base": prefer_base,
                "nums": spec.nums,
                "notes": spec.notes,
            })

    return {
        "version": 1,
        "manifest_path": "tests/data/template_golden_manifest.json",
        "seed": seed,
        "total_cases": len(cases),
        "cases": cases,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate golden template-choice corpus.")
    parser.add_argument("--force-manifest", action="store_true", help="Overwrite frozen manifest")
    parser.add_argument("--check", action="store_true", help="Verify reproducibility against existing corpus")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Fixed random seed")
    args = parser.parse_args(argv)

    manifest_path = freeze_manifest(force=args.force_manifest)
    catalog = TemplateCatalog(manifest_path, read_json(manifest_path))

    if args.check:
        if not GOLDEN_CORPUS_PATH.exists():
            print(f"Golden-корпус не найден: {GOLDEN_CORPUS_PATH}", file=sys.stderr)
            return 1
        existing = read_json(GOLDEN_CORPUS_PATH)
        generated = generate_golden_corpus(catalog, seed=args.seed)
        mismatches = []
        for exp, act in zip(existing["cases"], generated["cases"]):
            if exp["template_id"] != act["template_id"]:
                mismatches.append(f"{exp['id']}: expected {exp['template_id']}, got {act['template_id']}")
        if mismatches:
            print("Расхождения воспроизводимости:", file=sys.stderr)
            for m in mismatches:
                print(f"  {m}", file=sys.stderr)
            return 1
        print(f"Воспроизводимость подтверждена: {len(existing['cases'])} кейсов идентичны.")
        return 0

    corpus = generate_golden_corpus(catalog, seed=args.seed)
    write_json(GOLDEN_CORPUS_PATH, corpus)
    print(f"Сгенерирован golden-корпус ({corpus['total_cases']} кейсов) -> {GOLDEN_CORPUS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
