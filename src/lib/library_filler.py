"""Наполнение капнутых библиотек до лимитов §14 (workflow ``fill-libraries``).

Принцип §14: библиотеки конечны. После достижения лимита пополнение
блокируется, и дальше — **только переиспользование**. Повторная генерация
уже имеющегося звука считается ошибкой процесса (§4.4.4).

SFX и музыка курируемые: их приносит заказчик. Синтез обоих удалён из
наполнителя, а не спрятан за флагом — ``fill-libraries`` стоит в наборе
по умолчанию и иначе вернул бы отвергнутое первым же прогоном.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..errors import LibraryFrozen
from .logging import get_logger
from .manifest import AssetRecord, open_library, today

_log = get_logger("library_filler")

# §14.3 — эмоции мемов
MEME_EMOTIONS = ("ирония", "абсурд", "разочарование", "удивление", "сарказм")


def fill_sfx(cfg, *, costs=None, dry_run: bool = False) -> dict[str, Any]:
    """Короткие звуки не синтезируются: библиотека курируемая (§14.1).

    Двадцать синтетических wav заказчик снял, чтобы залить свои. Синтез
    у наполнителя убран, а не отключён флагом: отключённый он вернулся бы
    первым же прогоном ``fill-libraries``, который в наборе по умолчанию.

    Функция осталась, чтобы ``fill_libraries`` не спотыкался о недостающий
    обработчик. Класть файлы будет заказчик; конвейер их подхватит из
    манифеста, когда записи появятся.
    """
    lib = open_library(cfg, "sfx")
    return {
        "kind": "sfx",
        "added": [],
        "blocked": [],
        "curated": True,
        "count": lib.count,
        "max_items": lib.max_items,
        "frozen": lib.frozen,
        "note": "короткие звуки кладутся руками заказчиком, не синтезируются",
    }


def fill_music(cfg, *, costs=None, dry_run: bool = False) -> dict[str, Any]:
    """Подложки не синтезируются: библиотека курируемая (§14.2).

    Пятнадцать сгенерированных бедов заказчик отверг — «это ужас, я хотел
    хорошие сэмплы живых инструментов». Синтез удалён, а не отключён флагом:
    отключённый он вернулся бы первым же прогоном ``fill-libraries``, который
    в наборе по умолчанию.

    Функция осталась, чтобы ``fill_libraries`` не спотыкался о недостающий
    обработчик, и чтобы отчёт честно показывал, каких настроений не хватает.
    Класть файлы — ``python -m src.cli add-music``.
    """
    from .music_library import library_status

    status = library_status(cfg)
    return {
        "kind": "music",
        "added": [],
        "blocked": [],
        "curated": True,
        "count": status["count"],
        "instruments_missing": status["instruments_missing"],
        "by_tag": status["by_tag"],
        "note": ("подложки кладутся руками: python -m src.cli add-music "
                 "--file <запись> --id <имя> --tag <тег> [--tag ...]"),
    }


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
