"""Каталог шаблонов и ротация (§15, скилл ``redshift-templates``).

Правила §15.12, реализованные здесь:

1. Шаблон, использованный в последних 3 роликах **в той же роли**, не выбирается
   при наличии альтернативы.
2. Наборы шаблонов версий A и B одного ролика отличаются минимум на 3 позиции.
3. ``manifest.json`` фиксирует использование; редко используемые получают
   приоритет — иначе каталог из 104 шаблонов выродится в 5 любимых, а QC-17
   («повтор набора шаблонов с предыдущим роликом») начнёт стабильно падать.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..errors import RedshiftError
from .jsonio import read_json, write_json
from .logging import get_logger

_log = get_logger("templates")

ROTATION_WINDOW = 3          # §15.12.1


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
    last_used_in: list[str] = field(default_factory=list)
    added: str = ""
    example_video: str = ""

    def fits(self, duration: float) -> bool:
        lo, hi = self.duration_range
        if hi <= 0:
            return True
        return lo - 1e-6 <= duration <= hi + 1e-6

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id, "name": self.name, "category": self.category,
            "title": self.title, "duration_range": self.duration_range,
            "params": self.params, "tags": self.tags, "renderer": self.renderer,
            "last_used_in": self.last_used_in, "added": self.added,
        }
        if self.example_video:
            data["example_video"] = self.example_video
        return data


class TemplateCatalog:
    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.data = data
        self.templates = [Template(**{k: v for k, v in t.items() if k in Template.__annotations__})
                          for t in data.get("templates", [])]
        self._by_id = {t.id: t for t in self.templates}

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

    def by_category(self, category: str) -> list[Template]:
        return [t for t in self.templates if t.category == category]

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
             tags: Iterable[str] = ()) -> Template:
        """Выбрать шаблон категории с учётом ротации §15.12."""
        pool = self.by_category(category)
        if not pool:
            raise RedshiftError(f"в каталоге нет категории {category}",
                                code="TEMPLATE_CATEGORY_EMPTY")

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

        recent = set(recent_videos)
        preferred = list(prefer)

        def rank(template: Template) -> tuple:
            # 1. Явное пожелание сценария/edit-плана.
            explicit = 0 if template.id in preferred else 1
            # 2. Использованные в последних N роликах — в хвост (§15.12.1).
            used_recently = 1 if set(template.last_used_in[-ROTATION_WINDOW:]) & recent else 0
            # 3. Редко используемые получают приоритет (§15.12.3).
            usage = len(template.last_used_in)
            return (explicit, used_recently, usage, template.id)

        candidates.sort(key=rank)
        best_rank = rank(candidates[0])[:3]
        equals = [t for t in candidates if rank(t)[:3] == best_rank]
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
