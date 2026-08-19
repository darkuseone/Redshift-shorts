"""Наполнение капнутых библиотек до лимитов §14 (workflow ``fill-libraries``).

Принцип §14: библиотеки конечны. Первые прогоны добирают недостающее, после
достижения лимита пополнение блокируется, и дальше — **только переиспользование**.
Повторная генерация уже имеющегося звука считается ошибкой процесса (§4.4.4),
поэтому filler никогда не трогает роли, которые в библиотеке уже есть.

SFX и музыка синтезируются собственными средствами (``sfx_synth``): это снимает
риск Content ID полностью и делает звук ролика узнаваемым. Live-провайдер
ElevenLabs используется, когда он доступен и в конфиге разрешён.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from ..errors import LibraryFrozen
from .audio import SAMPLE_RATE, measure_loudness_buffer, normalize_peak, save_wav
from .ffmpeg import run as ffmpeg_run
from .logging import get_logger
from .manifest import AssetRecord, open_library, today
from .sfx_synth import (
    MUSIC_MOODS, SFX_ROLES, sfx_description, synth_music, synth_sfx,
)

_log = get_logger("library_filler")

# §14.3 — эмоции мемов
MEME_EMOTIONS = ("ирония", "абсурд", "разочарование", "удивление", "сарказм")


def fill_sfx(cfg, *, costs=None, dry_run: bool = False) -> dict[str, Any]:
    """Добрать SFX до 20 ролей §14.1. Существующие роли не трогаем."""
    lib = open_library(cfg, "sfx")
    existing = {item.role for item in lib.items if item.role}
    missing = [role for role in SFX_ROLES if role not in existing]
    added: list[str] = []
    blocked: list[str] = []

    for role in missing:
        if lib.is_full:
            blocked.append(role)
            continue
        if dry_run:
            added.append(role)
            continue
        audio = synth_sfx(role)
        audio = normalize_peak(audio, -12.0)      # §4.4: пики SFX −16…−12 dBFS
        filename = f"{role}.wav"
        save_wav(lib.dir / filename, audio, SAMPLE_RATE)
        duration = len(audio) / SAMPLE_RATE
        try:
            lib.add(AssetRecord(
                id=f"sfx_{role}", type="sfx", source="synth",
                license="generated-owned (REDSHIFT)", role=role,
                tags=[role, *sfx_description(role).split()[:3]],
                vision_summary=sfx_description(role),
                duration_sec=duration, file=filename, added=today(),
            ))
        except LibraryFrozen:
            blocked.append(role)
            break
        added.append(role)
        if costs is not None:
            costs.add("elevenlabs", "sfx_synth", 1, "clip", 0.0, mock=True, role=role)

    if not dry_run:
        lib.save()
    return {"kind": "sfx", "added": added, "blocked": blocked,
            "count": lib.count if not dry_run else lib.count + len(added),
            "max_items": lib.max_items, "frozen": lib.frozen,
            "missing_after": [r for r in SFX_ROLES
                              if r not in existing and r not in added]}


def fill_music(cfg, *, costs=None, dry_run: bool = False) -> dict[str, Any]:
    """Добрать подложки до 5 настроений §14.2."""
    lib = open_library(cfg, "music")
    existing = {item.mood for item in lib.items if item.mood}
    missing = [mood for mood in MUSIC_MOODS if mood not in existing]
    added: list[str] = []
    blocked: list[str] = []

    duration = float(cfg.get("libraries.music.duration_sec", 62.0))
    for mood in missing:
        if lib.is_full:
            blocked.append(mood)
            continue
        if dry_run:
            added.append(mood)
            continue
        audio = synth_music(mood, duration_sec=duration)
        # Подложка хранится сжатой: см. load_audio_any и §14.5.
        filename = f"{mood}.m4a"
        tmp_wav = lib.dir / f".{mood}.tmp.wav"
        save_wav(tmp_wav, audio, SAMPLE_RATE)
        ffmpeg_run(["-y", "-i", str(tmp_wav), "-c:a", "aac", "-b:a", "96k",
                    "-ar", str(SAMPLE_RATE), "-ac", "2", str(lib.dir / filename)],
                   what="encode music bed")
        tmp_wav.unlink(missing_ok=True)
        try:
            lib.add(AssetRecord(
                id=f"music_{mood}", type="music", source="synth",
                license="generated-owned (REDSHIFT)", mood=mood,
                tags=[mood, "loopable", "no-vocals", "no-melody"],
                vision_summary=MUSIC_MOODS[mood]["title"],
                duration_sec=len(audio) / SAMPLE_RATE, file=filename, added=today(),
            ))
        except LibraryFrozen:
            blocked.append(mood)
            break
        added.append(mood)
        if costs is not None:
            costs.add("elevenlabs", "music_synth", 1, "clip", 0.0, mock=True, mood=mood)

    if not dry_run:
        lib.save()
    return {"kind": "music", "added": added, "blocked": blocked,
            "count": lib.count if not dry_run else lib.count + len(added),
            "max_items": lib.max_items, "frozen": lib.frozen}


def fill_memes(cfg, *, costs=None, dry_run: bool = False) -> dict[str, Any]:
    """Добор мемов до 100 (§14.3), не более ``per_run_intake`` за прогон.

    Мемы нельзя «сгенерировать»: §14.3 требует отобранную собственную базу без
    узнаваемых фрагментов фильмов и ТВ с оригинальным аудио. Поэтому здесь
    добавляются только карточки-реакции собственного производства, помеченные
    ``mock``: они позволяют прогнать пайплайн, но QC видит, что это не
    настоящая курированная база.
    """
    lib = open_library(cfg, "memes")
    per_run = int(cfg.get("libraries.memes.per_run_intake", 18))
    free = lib.free_slots()
    quota = per_run if free is None else min(per_run, free)
    added: list[str] = []

    if quota <= 0:
        return {"kind": "memes", "added": [], "count": lib.count,
                "max_items": lib.max_items, "frozen": lib.frozen,
                "note": "библиотека заполнена — пополнение только вручную заказчиком (§14.3)"}

    from PIL import Image, ImageDraw

    from .render.canvas import FontBook, parse_color

    fonts = FontBook.load(cfg) if not dry_run else None
    start_index = lib.count
    for i in range(quota):
        emotion = MEME_EMOTIONS[(start_index + i) % len(MEME_EMOTIONS)]
        meme_id = f"meme_{start_index + i:03d}_{emotion}"
        if dry_run:
            added.append(meme_id)
            continue
        filename = f"{meme_id}.png"
        image = Image.new("RGB", (720, 720), parse_color(cfg.color("bg_light"))[:3])
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((30, 30, 690, 690), radius=40,
                               outline=parse_color(cfg.color("accent"))[:3], width=8)
        assert fonts is not None
        draw.text((360, 330), emotion.upper(), font=fonts.font("display", 92),
                  fill=parse_color(cfg.color("ink"))[:3], anchor="mm")
        draw.text((360, 440), "заглушка базы мемов", font=fonts.font("subtitle", 34),
                  fill=parse_color(cfg.color("muted"))[:3], anchor="mm")
        image.save(lib.dir / filename)
        try:
            lib.add(AssetRecord(
                id=meme_id, type="meme", source="placeholder",
                license="generated-owned (REDSHIFT)", emotion=emotion,
                tags=[emotion, "placeholder"], file=filename,
                vision_summary=f"карточка-реакция «{emotion}» (заглушка)",
                duration_sec=1.0, added=today(), mock=True,
            ))
        except LibraryFrozen:
            break
        added.append(meme_id)

    if not dry_run:
        lib.save()
    return {"kind": "memes", "added": added, "count": lib.count,
            "max_items": lib.max_items, "frozen": lib.frozen,
            "per_run_intake": per_run,
            "note": ("это карточки-заглушки: настоящая база мемов курируется "
                     "заказчиком, §14.3 запрещает фрагменты фильмов и ТВ с "
                     "оригинальным аудио")}


def fill_libraries(cfg, *, kinds: Sequence[str] = ("sfx", "music", "memes"),
                   costs=None, dry_run: bool = False) -> dict[str, Any]:
    handlers = {"sfx": fill_sfx, "music": fill_music, "memes": fill_memes}
    result: dict[str, Any] = {"dry_run": dry_run, "results": {}}
    for kind in kinds:
        handler = handlers.get(kind)
        if handler is None:
            continue
        outcome = handler(cfg, costs=costs, dry_run=dry_run)
        result["results"][kind] = outcome
        _log.info("библиотека обработана", extra={
            "kind": kind, "added": len(outcome.get("added", [])),
            "count": outcome.get("count"), "frozen": outcome.get("frozen"),
        })
    return result
