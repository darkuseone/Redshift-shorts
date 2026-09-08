"""Каталог шаблонов и ротация (§15, скилл ``redshift-templates``).

Правила §15.12, реализованные здесь:

1. Шаблон, использованный в последних 3 роликах **в той же роли**, не выбирается
   при наличии альтернативы.
2. Наборы шаблонов версий A и B одного ролика отличаются минимум на 3 позиции.
3. ``manifest.json`` фиксирует использование; редко используемые получают
   приоритет — иначе каталог из 151 шаблона выродится в 5 любимых, а QC-17
   («повтор набора шаблонов с предыдущим роликом») начнёт стабильно падать.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..errors import RedshiftError
from .meaning import matched, satisfies
from .jsonio import read_json, write_json
from .logging import get_logger

_log = get_logger("templates")

ROTATION_WINDOW = 3          # §15.12.1
# Lower rank tuple value is preferred. Empty frequency sits with variant.
FREQUENCY_WEIGHT = {"signature": 0, "variant": 1, "rare": 2}

# Доли уровней на ролик (§8.5). Нижняя граница signature — это узнаваемость
# канала, верхняя — предел, за которым узнаваемость становится однообразием.
FREQUENCY_SHARE = {
    "signature": (0.55, 0.80),
    "variant": (0.15, 0.35),
    "rare": (0.0, 0.10),
}


class FrequencyBudget:
    """Сколько приёмов каждого уровня ролик уже выдал.

    `frequency` был жёстким ключом сортировки: `signature` побеждал `variant`
    всегда и на всех кадрах, поэтому доля узнаваемых приёмов упиралась в
    единицу, а разнообразие держалось только на потолке повторов одного id.
    Уровень — это доля, а не приоритет: пока signature ниже верхней границы,
    он выигрывает как раньше; как только дошёл до неё — временно уходит из
    разрешённого набора, и picker честно берёт variant.
    """

    __slots__ = ("counts",)

    def __init__(self) -> None:
        self.counts: dict[str, int] = {"signature": 0, "variant": 0, "rare": 0}

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def share(self, level: str) -> float:
        return self.counts.get(level, 0) / self.total if self.total else 0.0

    def take(self, level: str) -> None:
        key = (level or "variant").lower()
        if key in self.counts:
            self.counts[key] += 1

    def saturated(self, level: str) -> bool:
        """Дошёл ли уровень до верхней границы своей доли.

        Первые кадры не ограничиваются: на одном-двух приёмах любая доля
        либо 0, либо 1, и запрет по ней означал бы запрет по случайности.
        """
        if self.total < 4:
            return False
        top = FREQUENCY_SHARE.get(level, (0.0, 1.0))[1]
        return self.share(level) >= top

    def to_dict(self) -> dict[str, Any]:
        return {"counts": dict(self.counts),
                "shares": {k: round(self.share(k), 3) for k in self.counts}}

_FS_SIGNATURE = frozenset({
    "stack-3lines", "fact-card", "quote-frame", "per-word-crossfade",
    "blur-out-up", "bigtext-mask-footage",
})
_FS_VARIANT = frozenset({
    "date-marker", "label-strip", "bottom-up-letters", "kinetic-type-swap",
})
_FS_RARE = frozenset({"scan-band"})
_BROWSER_SIGNATURE = frozenset({
    "browser-scroll", "article-highlight", "chat-thread",
})
_EXOTIC_RENDERERS = frozenset({
    "gravitational_lens", "swirl_vortex", "ridged_burn", "thermal_distortion",
    "glitch_shader", "chromatic_radial_split", "cross_warp_morph",
    "domain_warp_dissolve", "sdf_iris", "whip_pan_shader",
})
_SIMPLE_TRANSITION = frozenset({
    "cut", "whip_pan", "zoom_punch", "mask_wipe", "paper_slide",
    "blur_dip", "white_flash", "light_sweep", "glitch",
})


def frequency_for(template_id: str, category: str, renderer: str) -> str:
    """Heuristic §F.4. Contested ids are listed in the PR, not auto-overridden."""
    name = template_id.split("/", 1)[-1]
    rend = str(renderer or "")
    if name in _FS_RARE or rend.startswith("transitions_") or rend in _EXOTIC_RENDERERS:
        return "rare"
    if category == "frames-cards" or category == "avatar-entry" or category == "kenburns":
        return "signature"
    if category == "lower-thirds":
        return "signature"
    if category == "outro-cta":
        return "signature"
    if category == "browser-ui" and name in _BROWSER_SIGNATURE:
        return "signature"
    if category == "text-fullscreen" and name in _FS_SIGNATURE:
        return "signature"
    if category == "text-fullscreen" and name in _FS_VARIANT:
        return "variant"
    if category in ("data-viz", "hero-devices", "intro-hooks", "parallax"):
        return "variant"
    if category == "transitions" and rend in _SIMPLE_TRANSITION:
        return "variant"
    if category == "transitions":
        return "rare"
    if category == "browser-ui":
        return "variant"
    if category == "text-fullscreen":
        return "variant"
    return "variant"


@dataclass
class Template:
    id: str
    name: str
    category: str
    title: str
    duration_range: list[float]
    params: dict[str, Any]
    tags: list[str]
    renderer: str
    # Чем приём обязан быть оправдан: «хотя бы один из признаков блока»
    # (см. src/lib/meaning.py). Пусто — приём смысла не несёт и годится везде.
    needs: list[str] = field(default_factory=list)
    last_used_in: list[str] = field(default_factory=list)
    added: str = ""
    example_video: str = ""
    # active | retired | gated | candidate — non-active never enter pick.
    status: str = "active"
    retired_reason: str = ""
    # signature | variant | rare — weight among active. Empty = variant.
    frequency: str = ""

    def fits(self, duration: float) -> bool:
        lo, hi = self.duration_range
        if hi <= 0:
            return True
        return lo - 1e-6 <= duration <= hi + 1e-6

    @property
    def is_active(self) -> bool:
        # gated stays pickable (needs= gate); retired/candidate do not.
        return (self.status or "active") in ("active", "gated")

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id, "name": self.name, "category": self.category,
            "title": self.title, "duration_range": self.duration_range,
            "params": self.params, "tags": self.tags, "needs": self.needs,
            "renderer": self.renderer,
            "last_used_in": self.last_used_in, "added": self.added,
            "status": self.status or "active",
        }
        if self.example_video:
            data["example_video"] = self.example_video
        if self.retired_reason:
            data["retired_reason"] = self.retired_reason
        if self.frequency:
            data["frequency"] = self.frequency
        return data


class TemplateCatalog:
    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.data = data
        self.templates = [Template(**{k: v for k, v in t.items() if k in Template.__annotations__})
                          for t in data.get("templates", [])]
        self._by_id = {t.id: t for t in self.templates}
        self._last_escaped = False
        self._last_allow_size = 0

    @classmethod
    def load(cls, cfg) -> "TemplateCatalog":
        path = cfg.path("paths.templates_dir", "templates") / "manifest.json"
        if not path.exists():
            raise RedshiftError("каталог шаблонов не найден: запустите tools/gen_templates.py",
                                code="TEMPLATES_MISSING", path=str(path))
        return cls(path, read_json(path))

    # --- доступ ---------------------------------------------------------
    def all(self) -> list[Template]:
        return list(self.templates)

    def by_id(self, template_id: str) -> Template | None:
        return self._by_id.get(template_id)

    def by_category(self, category: str, *, include_inactive: bool = False) -> list[Template]:
        """Active templates in category. ``all()`` stays full for golden counts."""
        out = [t for t in self.templates if t.category == category]
        if include_inactive:
            return out
        return [t for t in out if t.is_active]

    def by_tag(self, tag: str) -> list[Template]:
        return [t for t in self.templates if tag in t.tags]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for template in self.templates:
            out[template.category] = out.get(template.category, 0) + 1
        return out

    # --- выбор с ротацией -----------------------------------------------
    def pick(self, category: str, *, duration: float | None = None,
             recent_videos: Sequence[str] = (), exclude: Iterable[str] = (),
             prefer: Iterable[str] = (), seed: int = 0,
             tags: Iterable[str] = (),
             traits: Iterable[str] | None = None,
             allow: Iterable[str] | None = None) -> Template:
        """Pick a template: meaning first, then rotation §15.12.

        ``allow`` is a hard allowlist from the scenario set. When set, the pool
        is cut to those ids **before** exclude/duration/tags/traits. An empty
        result does **not** expand to the full category; instead we climb a
        ladder: drop duration → drop traits → allow only. If ``exclude`` empties
        the allow pool, we soft-reuse inside allow (still never reopen the full
        category). Full category is used only when ``allow`` is omitted.

        ``traits`` — block traits (src/lib/meaning.py). A template that cannot
        be filled is dropped. If meaning filter empties the pool, need-less
        templates remain; only then (and only without ``allow``) the full
        filtered pool is restored so the slot is never blank.

        ``None`` vs empty set for traits differ: ``None`` skips meaning filter;
        empty set keeps only need-less templates.
        """
        pool = self.by_category(category)
        if not pool:
            raise RedshiftError(f"в каталоге нет категории {category}",
                                code="TEMPLATE_CATEGORY_EMPTY")

        allow_set = {str(x) for x in allow} if allow is not None else None
        if allow_set is not None:
            pool = [t for t in pool if t.id in allow_set]
            if not pool:
                raise RedshiftError(
                    f"сценарный набор для {category} пуст после allow-фильтра",
                    code="TEMPLATE_CATEGORY_EMPTY",
                )

        excluded = set(exclude)
        wanted_tags = {t for t in tags if t}
        block_traits = None if traits is None else {str(t) for t in traits if t}
        base = [t for t in pool if t.id not in excluded]
        if not base:
            # Soft-drop exclude when it empties the pool. Without allow this
            # restores the full category (legacy). With allow, pool is already
            # clipped to the scenario set — reuse inside allow rather than
            # raising TEMPLATE_CATEGORY_EMPTY after many FS/gap picks. Never
            # reopen the full category when allow is set.
            if allow_set is not None:
                _log.warning(
                    "сценарный набор для категории %s исчерпан exclude — "
                    "повтор внутри allow (%d шт.)",
                    category, len(pool),
                )
            base = list(pool)

        def apply_filters(*, use_duration: bool, use_traits: bool) -> list[Template]:
            candidates = list(base)
            if use_duration and duration is not None:
                fitting = [t for t in candidates if t.fits(duration)]
                if fitting:
                    candidates = fitting
                elif allow_set is not None:
                    return []
                # without allow: keep candidates (legacy soft duration)
            if wanted_tags:
                tagged = [t for t in candidates if wanted_tags & set(t.tags)]
                if tagged:
                    candidates = tagged
                elif allow_set is not None:
                    return []
            if use_traits and block_traits is not None:
                meaningful = [t for t in candidates if satisfies(t.needs, block_traits)]
                soft = [t for t in candidates if not t.needs]
                if meaningful:
                    candidates = meaningful
                elif soft:
                    candidates = soft
                elif allow_set is not None:
                    return []
                # without allow: keep candidates as last resort below
            return candidates

        escaped = False
        candidates = apply_filters(use_duration=True, use_traits=True)
        if not candidates and allow_set is not None:
            escaped = True
            _log.warning(
                "сценарный набор для категории %s не закрыл слот "
                "(duration=%s) — откат: без duration",
                category, duration,
            )
            candidates = apply_filters(use_duration=False, use_traits=True)
        if not candidates and allow_set is not None:
            escaped = True
            _log.warning(
                "сценарный набор для категории %s — откат: без traits",
                category,
            )
            candidates = apply_filters(use_duration=False, use_traits=False)
        if not candidates and allow_set is not None:
            escaped = True
            candidates = list(base)
        if not candidates:
            if allow_set is not None:
                raise RedshiftError(
                    f"сценарный набор для {category} не смог закрыть слот",
                    code="TEMPLATE_CATEGORY_EMPTY",
                )
            candidates = list(pool)

        # Stash escape flag for callers that inspect the last pick (picker).
        self._last_escaped = escaped  # type: ignore[attr-defined]
        self._last_allow_size = len(allow_set) if allow_set is not None else 0  # type: ignore[attr-defined]

        recent = set(recent_videos)
        preferred = list(prefer)

        def rank(template: Template) -> tuple:
            explicit = 0 if template.id in preferred else 1
            freq = FREQUENCY_WEIGHT.get((template.frequency or "variant").lower(), 1)
            grounded = 0 if (template.needs and block_traits is not None
                             and satisfies(template.needs, block_traits)) else 1
            used_recently = 1 if set(template.last_used_in[-ROTATION_WINDOW:]) & recent else 0
            usage = len(template.last_used_in)
            return (explicit, freq, grounded, used_recently, usage, template.id)

        candidates.sort(key=rank)
        best_rank = rank(candidates[0])[:5]
        equals = [t for t in candidates if rank(t)[:5] == best_rank]
        return random.Random(seed).choice(equals) if len(equals) > 1 else candidates[0]

    def mark_used(self, template_ids: Iterable[str], video_id: str) -> None:
        for template_id in template_ids:
            template = self._by_id.get(template_id)
            if template is not None and video_id not in template.last_used_in:
                template.last_used_in.append(video_id)

    def save(self) -> Path:
        """Записать историю использования, не трогая состав каталога.

        Каталог перечитывается с диска перед записью: прогон длится минуты, и
        шаблон, добавленный за это время генератором, иначе пропадал бы —
        объект в памяти помнит состав на момент старта. Ловилось на живом
        прогоне: новый приём исчез из манифеста после P11.
        """
        on_disk = read_json(self.path) if self.path.exists() else self.data
        used = {t.id: t.last_used_in[-20:] for t in self.templates}
        for entry in on_disk.get("templates", []):
            if entry["id"] in used:
                entry["last_used_in"] = used[entry["id"]]
        self.data = on_disk
        return write_json(self.path, on_disk)


def diff_count(set_a: Iterable[str], set_b: Iterable[str]) -> int:
    """Насколько различаются наборы шаблонов версий A и B (§15.12.2)."""
    a, b = set(set_a), set(set_b)
    return len(a ^ b) // 2 + len(a ^ b) % 2


def overlap_share(set_a: Iterable[str], set_b: Iterable[str]) -> float:
    """Пересечение наборов — основа QC-6 и QC-17."""
    a, b = set(set_a), set(set_b)
    if not a and not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)
