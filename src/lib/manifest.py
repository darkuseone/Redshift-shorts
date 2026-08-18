"""Манифесты библиотек ассетов и индекс кэша футажей (§14, скилл ``redshift-asset-library``).

Принцип §14: брендовые библиотеки конечны и стабильны, футажный кэш растёт.

* SFX — 20 файлов, музыка — 5, мемы — 100. По достижении лимита библиотека
  замораживается: попытка сгенерировать ещё один звук — это не «дополнение», а
  ошибка процесса (§4.4.4), и она возвращает ``LIBRARY_FROZEN``.
* Футажи растут без лимита; в репозитории живёт только индекс, файлы — во
  внешнем storage, вытеснение LRU (§14.4, §14.5).

Формат записи манифеста — из §14.6.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..errors import LibraryFrozen
from .jsonio import read_json_or, write_json
from .logging import get_logger
from .phash import DEFAULT_THRESHOLD, hamming, video_is_duplicate

_log = get_logger("library")

LIBRARY_KINDS = ("sfx", "music", "memes")
MANIFEST_NAMES = {"sfx": "sfx_manifest.json", "music": "music_manifest.json",
                  "memes": "memes_manifest.json"}


def today() -> str:
    return _dt.date.today().isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass
class AssetRecord:
    """Запись манифеста по §14.6."""

    id: str
    type: str                       # video | photo | sfx | music | meme | template
    source: str                     # pexels | nasa | magnific | elevenlabs | generated | mock
    license: str = ""
    url_origin: str = ""
    phash: str = ""
    phashes: list[str] = field(default_factory=list)     # для видео — по 3 кадрам
    tags: list[str] = field(default_factory=list)
    vision_summary: str = ""
    score: float = 0.0
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    file: str = ""                  # путь относительно каталога библиотеки/ключ в storage
    role: str = ""                  # для SFX — роль из таблицы §14.1
    mood: str = ""                  # для музыки — настроение из §14.2
    emotion: str = ""               # для мемов — эмоция из §14.3
    used_in: list[str] = field(default_factory=list)
    last_used: str | None = None
    added: str = field(default_factory=today)
    ai_generated: bool = False
    mock: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id, "type": self.type, "source": self.source,
            "license": self.license, "url_origin": self.url_origin,
            "phash": self.phash, "tags": self.tags,
            "vision_summary": self.vision_summary, "score": round(self.score, 4),
            "duration_sec": round(self.duration_sec, 3),
            "used_in": self.used_in, "last_used": self.last_used, "added": self.added,
        }
        for key in ("phashes", "width", "height", "file", "role", "mood", "emotion",
                    "ai_generated", "mock"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.extra:
            data["extra"] = self.extra
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssetRecord":
        known = {f for f in cls.__dataclass_fields__}          # noqa: SLF001
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs.setdefault("id", new_id())
        kwargs.setdefault("type", "video")
        kwargs.setdefault("source", "unknown")
        extra = {k: v for k, v in data.items() if k not in known and k != "extra"}
        if extra:
            kwargs.setdefault("extra", {}).update(extra)
        return cls(**kwargs)


class AssetLibrary:
    """Капнутая библиотека (SFX / музыка / мемы) с жёстким лимитом."""

    def __init__(self, kind: str, directory: str | Path, *, max_items: int | None,
                 frozen_when_full: bool = True) -> None:
        self.kind = kind
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.max_items = max_items
        self.frozen_when_full = frozen_when_full
        self.path = self.dir / MANIFEST_NAMES.get(kind, f"{kind}_manifest.json")
        raw = read_json_or(self.path, {"kind": kind, "max_items": max_items, "items": []})
        self.items: list[AssetRecord] = [AssetRecord.from_dict(i) for i in raw.get("items", [])]
        self._comment = raw.get("_comment", "")

    # --- состояние ------------------------------------------------------
    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def is_full(self) -> bool:
        return self.max_items is not None and self.count >= self.max_items

    @property
    def frozen(self) -> bool:
        return self.is_full and self.frozen_when_full

    def free_slots(self) -> int | None:
        return None if self.max_items is None else max(0, self.max_items - self.count)

    def status(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "count": self.count, "max_items": self.max_items,
            "free_slots": self.free_slots(), "frozen": self.frozen,
            "path": str(self.path),
            "roles": sorted({i.role for i in self.items if i.role}),
            "moods": sorted({i.mood for i in self.items if i.mood}),
            "emotions": sorted({i.emotion for i in self.items if i.emotion}),
        }

    # --- операции -------------------------------------------------------
    def add(self, record: AssetRecord) -> AssetRecord:
        if self.frozen:
            raise LibraryFrozen(
                f"библиотека {self.kind} заполнена ({self.count}/{self.max_items}): "
                f"пополнение заблокировано, используйте существующие материалы (§14)",
                kind=self.kind, count=self.count, max_items=self.max_items,
            )
        if self.max_items is not None and self.count >= self.max_items:
            raise LibraryFrozen(f"библиотека {self.kind} переполнена", kind=self.kind)
        self.items.append(record)
        return record

    def has_role(self, role: str) -> bool:
        return any(i.role == role for i in self.items)

    def by_role(self, role: str) -> AssetRecord | None:
        return next((i for i in self.items if i.role == role), None)

    def by_mood(self, mood: str) -> AssetRecord | None:
        return next((i for i in self.items if i.mood == mood), None)

    def by_id(self, asset_id: str) -> AssetRecord | None:
        return next((i for i in self.items if i.id == asset_id), None)

    def find_by_tags(self, tags: Iterable[str], *, exclude_recent: Sequence[str] = (),
                     cooldown: int = 0) -> list[AssetRecord]:
        """Материалы, отсортированные по совпадению тегов и «свежести» использования."""
        wanted = {t.lower() for t in tags}
        recent = set(exclude_recent)
        scored: list[tuple[float, AssetRecord]] = []
        for item in self.items:
            if cooldown and item.used_in and set(item.used_in[-cooldown:]) & recent:
                continue
            overlap = len(wanted & {t.lower() for t in item.tags})
            if not overlap and wanted:
                continue
            usage_penalty = len(item.used_in) * 0.01
            scored.append((overlap - usage_penalty, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _score, item in scored]

    def is_duplicate(self, phash: str, threshold: int = DEFAULT_THRESHOLD) -> AssetRecord | None:
        for item in self.items:
            if item.phash and hamming(item.phash, phash) <= threshold:
                return item
        return None

    def mark_used(self, asset_id: str, video_id: str) -> None:
        item = self.by_id(asset_id)
        if item is None:
            return
        if video_id not in item.used_in:
            item.used_in.append(video_id)
        item.last_used = today()

    def save(self) -> Path:
        payload = {
            "_comment": self._comment or (
                f"Библиотека {self.kind}. Лимит {self.max_items} (§14). "
                f"По достижении лимита пополнение блокируется."),
            "kind": self.kind,
            "max_items": self.max_items,
            "count": self.count,
            "frozen": self.frozen,
            "updated": today(),
            "items": [i.to_dict() for i in self.items],
        }
        return write_json(self.path, payload)

    def file_path(self, record: AssetRecord) -> Path:
        return self.dir / (record.file or f"{record.id}")


def open_library(cfg, kind: str) -> AssetLibrary:
    settings = cfg.get(f"libraries.{kind}", {}) or {}
    directory = cfg.path("paths.assets_dir", "assets") / kind
    return AssetLibrary(
        kind, directory,
        max_items=settings.get("max_items"),
        frozen_when_full=bool(settings.get("frozen_when_full", True)),
    )


def library_status(cfg) -> dict[str, Any]:
    out: dict[str, Any] = {"libraries": {}}
    for kind in LIBRARY_KINDS:
        out["libraries"][kind] = open_library(cfg, kind).status()
    index = FootageIndex.load(cfg)
    out["footage"] = index.status()
    return out


class FootageIndex:
    """Индекс кэша футажей: в git — только он, файлы во внешнем storage (§14.5)."""

    def __init__(self, path: str | Path, *, freeze: bool = False) -> None:
        self.path = Path(path)
        raw = read_json_or(self.path, {"version": 1, "items": []})
        self.items: list[AssetRecord] = [AssetRecord.from_dict(i) for i in raw.get("items", [])]
        self.freeze = freeze

    @classmethod
    def load(cfg) -> "FootageIndex":  # type: ignore[misc]
        raise NotImplementedError    # переопределяется ниже как classmethod

    def status(self) -> dict[str, Any]:
        return {
            "count": len(self.items),
            "freeze": self.freeze,
            "path": str(self.path),
            "ai_generated": sum(1 for i in self.items if i.ai_generated),
            "sources": sorted({i.source for i in self.items}),
            "total_duration_sec": round(sum(i.duration_sec for i in self.items), 1),
        }

    def by_id(self, asset_id: str) -> AssetRecord | None:
        return next((i for i in self.items if i.id == asset_id), None)

    def add(self, record: AssetRecord) -> AssetRecord:
        self.items.append(record)
        return record

    def search(self, tags: Iterable[str], *, limit: int = 10,
               exclude_videos: Sequence[str] = (), min_score: float = 0.0,
               allow_recent: bool = False) -> list[AssetRecord]:
        """§7.2.1 — локальная база всегда просматривается раньше внешних стоков.

        §14.4: материал из последних 5 роликов **не переиспользуется при наличии
        альтернативы**. Альтернатива есть всегда, пока доступны внешние стоки,
        поэтому по умолчанию такой материал исключается жёстко. Мягкий штраф
        вместо исключения приводил к тому, что второй ролик набирался из первого
        и валил QC-6 (пересечение с последними 5 роликами ≤20 %).

        ``allow_recent=True`` включается только при замороженном кэше
        (``libraries.footage.freeze``), когда внешних источников действительно нет.
        """
        wanted = {t.lower() for t in tags if t}
        recent = set(exclude_videos)
        scored: list[tuple[float, AssetRecord]] = []
        for item in self.items:
            if item.score < min_score:
                continue
            used_recently = bool(set(item.used_in) & recent)
            if used_recently and not allow_recent:
                continue
            item_tags = {t.lower() for t in item.tags}
            overlap = len(wanted & item_tags)
            if wanted and not overlap:
                continue
            score = overlap * 1.0 + item.score - (5.0 if used_recently else 0.0)
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _s, item in scored[:limit]]

    def find_duplicate(self, phashes: Sequence[str],
                       threshold: int = DEFAULT_THRESHOLD) -> AssetRecord | None:
        for item in self.items:
            known = item.phashes or ([item.phash] if item.phash else [])
            if known and video_is_duplicate(list(phashes), known, threshold):
                return item
        return None

    def mark_used(self, asset_id: str, video_id: str) -> None:
        item = self.by_id(asset_id)
        if item is None:
            return
        if video_id not in item.used_in:
            item.used_in.append(video_id)
        item.last_used = today()

    def save(self) -> Path:
        return write_json(self.path, {
            "_comment": "Индекс кэша футажей (§14.5): в git — только индекс, "
                        "файлы во внешнем storage. Вытеснение LRU (§14.4).",
            "version": 1,
            "updated": today(),
            "count": len(self.items),
            "items": [i.to_dict() for i in self.items],
        })


def _footage_index_load(cls, cfg) -> FootageIndex:
    path = cfg.path("paths.cache_dir", "cache") / "footage_index.json"
    return cls(path, freeze=bool(cfg.get("libraries.footage.freeze", False)))


FootageIndex.load = classmethod(_footage_index_load)  # type: ignore[assignment]
