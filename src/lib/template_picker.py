"""Сценарный выбор шаблонов поверх ротации каталога (Phase C, §4).

Модуль реализует двухуровневый выбор шаблона:
1. Наведение (head / specific / base) — упорядоченный singleton-walk (D1),
   где кандидаты опрашивают catalog.pick по одному ID. Первый выживший шаблон
   побеждает с tie_class == 1.
2. Ротация (default / generic) — передаётся одним множеством (fallback)
   в финальный catalog.pick, где решение принимает ротация §15.12.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

from src.errors import RedshiftError
from src.lib.config import Config
from src.lib.templates import Template, TemplateCatalog

logger = logging.getLogger(__name__)

SCENARIO_CFG_KEY = "paths.template_scenarios"  # default "config/template_scenarios.json"
MAX_WALK = 24  # cap ТОЛЬКО на список наведения (head+specific+base); D4.3


def build_blob(*parts: Any) -> str:
    """Нормализация текстовых фрагментов в единый поисковый blob в нижнем регистре."""
    return " ".join(str(p or "") for p in parts).lower()


def _dedup(items: Iterable[str]) -> tuple[str, ...]:
    """Дедупликация элементов с сохранением исходного порядка."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


@dataclass(frozen=True)
class Intent:
    id: str
    title: str
    categories: tuple[str, ...]
    keywords: tuple[str, ...]
    patterns: tuple[re.Pattern, ...]
    needs: frozenset[str]
    signals_any: frozenset[str]
    templates: tuple[str, ...]
    weight: int
    variants: frozenset[str]
    replaces_default: bool = False  # D2 п. 7 — субтрактивное правило `\d`


@dataclass(frozen=True)
class PickTrace:
    fired: tuple[tuple[str, int], ...]  # (intent_id, weight), по (-weight, id)
    channels: dict[str, tuple[str, ...]]  # head/specific/base/default/generic — как собрано
    walk: tuple[str, ...]  # head+specific+base после dedup, <= MAX_WALK (D1)
    fallback: tuple[str, ...]  # default_eff (+generic) — множество ротации (D4.2)
    won_at: int | None  # индекс победителя в walk, None = решила ротация
    tie_class: int  # |{explicit==0}| на выигравшем вызове; 1 при попадании в walk
    replaced_default_by: str | None  # intent_id с replaces_default, если сработал (D2 п. 7)


@dataclass(frozen=True)
class ScenarioIndex:
    intents: tuple[Intent, ...]
    specific_weight_min: int = 20
    default_weight_min: int = 10
    unreachable_categories: tuple[str, ...] = ()
    reason: str = ""
    tag_intents: dict[str, tuple[str, ...]] = field(default_factory=dict)
    version: int = 1

    @classmethod
    def empty(cls) -> "ScenarioIndex":
        """Пустой индекс для работы без файла конфигурации."""
        return cls(
            intents=(),
            specific_weight_min=20,
            default_weight_min=10,
            unreachable_categories=(),
            reason="",
            tag_intents={},
            version=1,
        )

    @classmethod
    def load(
        cls,
        cfg: Config | None = None,
        *,
        path: Path | str | None = None,
        catalog: TemplateCatalog | None = None,
    ) -> "ScenarioIndex":
        """Загрузить и валидировать индекс сценариев."""
        if path is not None:
            file_path = Path(path)
        elif cfg is not None:
            file_path = cfg.path(SCENARIO_CFG_KEY, "config/template_scenarios.json")
        else:
            file_path = Path("config/template_scenarios.json")

        if not file_path.exists():
            logger.warning("Сценарный индекс не найден по пути %s; используется пустой индекс", file_path)
            return cls.empty()

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            raise RedshiftError(
                f"Невалидный JSON в файле сценарного индекса {file_path}: {exc}",
                code="SCENARIO_INDEX_INVALID",
                path=str(file_path),
            ) from exc

        return cls.from_dict(data, catalog=catalog, cfg=cfg)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        catalog: TemplateCatalog | None = None,
        cfg: Config | None = None,
    ) -> "ScenarioIndex":
        """Собрать и валидировать ScenarioIndex из словаря."""
        if not isinstance(data, dict):
            raise RedshiftError(
                "Сценарный индекс должен быть JSON-объектом",
                code="SCENARIO_INDEX_INVALID",
            )

        if catalog is None and cfg is not None:
            try:
                manifest_path = cfg.path("paths.templates_dir", "templates") / "manifest.json"
                if manifest_path.exists():
                    catalog = TemplateCatalog.load(cfg)
            except Exception:
                catalog = None

        if catalog is None:
            try:
                def_manifest = Path("templates/manifest.json")
                if def_manifest.exists():
                    with open(def_manifest, "r", encoding="utf-8") as f:
                        catalog = TemplateCatalog(def_manifest, json.load(f))
            except Exception:
                catalog = None

        version = int(data.get("version", 1))
        spec_min = int(data.get("specific_weight_min", 20))
        def_min = int(data.get("default_weight_min", 10))
        if def_min < 0 or spec_min < def_min:
            raise RedshiftError(
                f"Полосы весов невалидны: default_weight_min={def_min}, specific_weight_min={spec_min}",
                code="SCENARIO_INDEX_INVALID",
            )

        unreachable = tuple(data.get("unreachable_categories", ()))
        reason = str(data.get("reason", ""))

        raw_intents = data.get("intents")
        if not isinstance(raw_intents, list):
            raise RedshiftError(
                "Поле 'intents' в сценарном индексе должно быть списком",
                code="SCENARIO_INDEX_INVALID",
            )

        seen_ids: set[str] = set()
        parsed_intents: list[Intent] = []

        for item in raw_intents:
            if not isinstance(item, dict):
                raise RedshiftError(
                    "Интент должен быть объектом",
                    code="SCENARIO_INDEX_INVALID",
                )
            iid = item.get("id")
            if not iid or not isinstance(iid, str):
                raise RedshiftError(
                    "Интент не содержит строкового поля 'id'",
                    code="SCENARIO_INDEX_INVALID",
                )
            if iid in seen_ids:
                raise RedshiftError(
                    f"Дублирующийся id интента: '{iid}'",
                    code="SCENARIO_INDEX_INVALID",
                )
            seen_ids.add(iid)

            w = item.get("weight")
            if not isinstance(w, int) or w < 0:
                raise RedshiftError(
                    f"Интент '{iid}' имеет невалидный вес {w} (должен быть целым >= 0)",
                    code="SCENARIO_INDEX_INVALID",
                )

            cats = tuple(item.get("categories", ()))
            if not cats:
                raise RedshiftError(
                    f"Интент '{iid}' не задаёт категории",
                    code="SCENARIO_INDEX_INVALID",
                )

            tmpls = tuple(item.get("templates", ()))
            if not tmpls:
                raise RedshiftError(
                    f"Интент '{iid}' не задаёт шаблоны",
                    code="SCENARIO_INDEX_INVALID",
                )

            if catalog is not None:
                for tid in tmpls:
                    tmpl = catalog.by_id(tid)
                    if tmpl is None:
                        raise RedshiftError(
                            f"Неизвестный id шаблона '{tid}' в интенте '{iid}'",
                            code="SCENARIO_INDEX_INVALID",
                        )
                    if tmpl.category not in cats:
                        raise RedshiftError(
                            f"Несовпадение категории шаблона '{tid}' ({tmpl.category}) с категориями интента '{iid}' ({cats})",
                            code="SCENARIO_INDEX_INVALID",
                        )

            try:
                compiled_patterns = tuple(
                    re.compile(p, re.IGNORECASE) for p in item.get("patterns", ())
                )
            except re.error as exc:
                raise RedshiftError(
                    f"Невалидный регулярный паттерн в интенте '{iid}': {exc}",
                    code="SCENARIO_INDEX_INVALID",
                ) from exc

            parsed_intents.append(
                Intent(
                    id=iid,
                    title=str(item.get("title", "")),
                    categories=cats,
                    keywords=tuple(item.get("keywords", ())),
                    patterns=compiled_patterns,
                    needs=frozenset(item.get("needs", ())),
                    signals_any=frozenset(item.get("signals_any", ())),
                    templates=tmpls,
                    weight=w,
                    variants=frozenset(item.get("variants", ())),
                    replaces_default=bool(item.get("replaces_default", False)),
                )
            )

        raw_tag_intents = data.get("tag_intents", {})
        if not isinstance(raw_tag_intents, dict):
            raise RedshiftError(
                "Поле 'tag_intents' должно быть объектом",
                code="SCENARIO_INDEX_INVALID",
            )
        parsed_tag_intents: dict[str, tuple[str, ...]] = {}
        for tag, iids in raw_tag_intents.items():
            if not isinstance(iids, (list, tuple)):
                raise RedshiftError(
                    f"tag_intents['{tag}'] должен быть списком",
                    code="SCENARIO_INDEX_INVALID",
                )
            for ref_id in iids:
                if ref_id not in seen_ids:
                    raise RedshiftError(
                        f"tag_intents['{tag}'] ссылается на несуществующий интент '{ref_id}'",
                        code="SCENARIO_INDEX_INVALID",
                    )
            parsed_tag_intents[tag] = tuple(iids)

        return cls(
            intents=tuple(parsed_intents),
            specific_weight_min=spec_min,
            default_weight_min=def_min,
            unreachable_categories=unreachable,
            reason=reason,
            tag_intents=parsed_tag_intents,
            version=version,
        )

    def detect_intents(
        self,
        blob: str = "",
        *,
        category: str,
        variant: str = "A",
        signals: frozenset[str] | set[str] = frozenset(),
    ) -> list[Intent]:
        """Определить сработавшие интенты, отсортированные по (-weight, id)."""
        blob_lower = blob.lower()
        signals_set = set(signals)
        matched: list[Intent] = []

        for intent in self.intents:
            if category not in intent.categories:
                continue
            if variant not in intent.variants:
                continue
            if intent.needs and not intent.needs.issubset(signals_set):
                continue

            if not intent.keywords and not intent.patterns and not intent.signals_any:
                matched.append(intent)
                continue

            is_triggered = False
            if intent.keywords and any(kw.lower() in blob_lower for kw in intent.keywords):
                is_triggered = True
            elif intent.patterns and any(p.search(blob) for p in intent.patterns):
                is_triggered = True
            elif intent.signals_any and any(s in signals_set for s in intent.signals_any):
                is_triggered = True

            if is_triggered:
                matched.append(intent)

        matched.sort(key=lambda it: (-it.weight, it.id))
        return matched


def detect_intents(
    target: Any,
    blob: str = "",
    *,
    category: str = "",
    variant: str = "A",
    signals: frozenset[str] | set[str] = frozenset(),
    index: ScenarioIndex | None = None,
) -> list[Intent]:
    """Хелпер верхнего уровня для детекции интентов."""
    if isinstance(target, ScenarioIndex):
        return target.detect_intents(blob, category=category, variant=variant, signals=signals)
    if index is not None:
        return index.detect_intents(str(target), category=category, variant=variant, signals=signals)
    raise ValueError("Необходимо передать ScenarioIndex в качестве первого аргумента или через index=")


class TemplatePicker:
    """Сценарный селектор шаблонов поверх каталога и ротации."""

    def __init__(self, catalog: TemplateCatalog, index: ScenarioIndex) -> None:
        self.catalog = catalog
        self.index = index

    @classmethod
    def create(cls, cfg: Config) -> "TemplatePicker":
        catalog = TemplateCatalog.load(cfg)
        index = ScenarioIndex.load(cfg, catalog=catalog)
        return cls(catalog, index)

    def _active_candidates(
        self,
        category: str,
        *,
        duration: float | None = None,
        exclude: Iterable[str] = (),
        tags: Iterable[str] = (),
    ) -> list[Template]:
        pool = self.catalog.by_category(category)
        if not pool:
            return []
        excluded = set(exclude)
        wanted_tags = {t for t in tags if t}
        candidates = [t for t in pool if t.id not in excluded]
        if duration is not None:
            fitting = [t for t in candidates if t.fits(duration)]
            candidates = fitting or candidates
        if wanted_tags:
            tagged = [t for t in candidates if wanted_tags & set(t.tags)]
            candidates = tagged or candidates
        if not candidates:
            candidates = pool
        return candidates

    def pick(
        self,
        category: str,
        *,
        blob: str = "",
        signals: frozenset[str] | set[str] = frozenset(),
        variant: str = "A",
        duration: float | None = None,
        recent_videos: Sequence[str] = (),
        exclude: Iterable[str] = (),
        seed: int = 0,
        tags: Iterable[str] = (),
        prefer_head: Sequence[str] = (),
        prefer_base: Sequence[str] = (),
    ) -> tuple[Template, PickTrace]:
        """Выбрать шаблон с трассировкой пяти каналов prefer."""
        # tag_intents не исполняется на pick (D6, §4)
        fired_intents = self.index.detect_intents(
            blob,
            category=category,
            variant=variant,
            signals=signals,
        )
        fired: tuple[tuple[str, int], ...] = tuple((it.id, it.weight) for it in fired_intents)

        specific_intents = [
            it for it in fired_intents if it.weight >= self.index.specific_weight_min
        ]
        default_intents = [
            it
            for it in fired_intents
            if self.index.default_weight_min <= it.weight < self.index.specific_weight_min
        ]
        generic_intents = [
            it for it in fired_intents if it.weight < self.index.default_weight_min
        ]

        ch_head = _dedup(prefer_head)
        ch_specific = _dedup(t for it in specific_intents for t in it.templates)
        ch_base = _dedup(prefer_base)
        ch_default = _dedup(t for it in default_intents for t in it.templates)
        ch_generic = _dedup(t for it in generic_intents for t in it.templates)

        channels: dict[str, tuple[str, ...]] = {
            "head": ch_head,
            "specific": ch_specific,
            "base": ch_base,
            "default": ch_default,
            "generic": ch_generic,
        }

        # 1. Список наведения (walk) — только head, specific, base с ограничением MAX_WALK
        walk: tuple[str, ...] = _dedup(ch_head + ch_specific + ch_base)[:MAX_WALK]

        # 2. Множество ротации (fallback) — без cap
        replaces_intents = [it for it in fired_intents if it.replaces_default]
        if replaces_intents:
            # Старший по весу интент с replaces_default (fired_intents уже отсортирован по (-weight, id))
            highest_rd = replaces_intents[0]
            replaced_default_by: str | None = highest_rd.id
            default_eff = _dedup(highest_rd.templates)
            fallback: tuple[str, ...] = default_eff
        else:
            replaced_default_by = None
            default_raw = ch_default
            default_eff = default_raw
            if default_raw:
                fallback = default_eff
            else:
                fallback = ch_generic

        # 3. Исполнение: singleton-walk по каналам наведения
        won_at: int | None = None
        tie_class: int = 0
        chosen: Template | None = None

        for idx, tid in enumerate(walk):
            t = self.catalog.pick(
                category,
                prefer=[tid],
                duration=duration,
                recent_videos=recent_videos,
                exclude=exclude,
                seed=seed,
                tags=tags,
            )
            if t.id == tid:
                won_at = idx
                tie_class = 1
                chosen = t
                break

        # 4. Если никто из walk не выжил — решает ротация внутри множества fallback
        if chosen is None:
            chosen = self.catalog.pick(
                category,
                prefer=list(fallback),
                duration=duration,
                recent_videos=recent_videos,
                exclude=exclude,
                seed=seed,
                tags=tags,
            )
            won_at = None
            active = self._active_candidates(
                category,
                duration=duration,
                exclude=exclude,
                tags=tags,
            )
            fallback_set = set(fallback)
            tie_class = sum(1 for cand in active if cand.id in fallback_set)

        trace = PickTrace(
            fired=fired,
            channels=channels,
            walk=walk,
            fallback=fallback,
            won_at=won_at,
            tie_class=tie_class,
            replaced_default_by=replaced_default_by,
        )
        return chosen, trace
