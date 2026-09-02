"""Курируемая библиотека музыкальных подложек (§14.2).

Подложки больше не синтезируются. Пятнадцать сгенерированных бедов заказчик
отверг словами «это ужас, я хотел хорошие сэмплы живых инструментов» — и он
прав. Аккорд с медленными биениями и партия из синусоид с наклеенной атакой
звучат синтезатором, а не инструментом; никакая правка параметров этого не
чинит, потому что разница между записью скрипки и математической моделью
скрипки слышна с первой ноты.

Поэтому библиотека наполняется руками: заказчик приносит готовые записи, а
конвейер их принимает, промеряет и заводит в манифест. Синтез удалён целиком,
чтобы `fill-libraries` не воссоздал отвергнутое.

Приём делает три вещи и ни одной лишней:

* **меряет**, а не доверяет на слово — длительность, громкость, стык петли;
* **приводит к одному формату** (AAC 192 кбит/с, 48 кГц, стерео), чтобы
  P10 не разбирался с чужими контейнерами в середине прогона;
* **заводит запись** с настроением, по которому P1 подложку и выбирает.

Уровень здесь не трогается: P10 нормализует бед по LUFS под конкретный ролик
(``audio.music_lufs``), и вгонять исходник в тот же коридор заранее значит
дважды жать одно и то же.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio import (
    SAMPLE_RATE,
    load_audio_any,
    measure_loudness_buffer,
    peak_dbfs,
    to_stereo,
)
from ..errors import RedshiftError
from .ffmpeg import run as ffmpeg_run
from .logging import get_logger

_log = get_logger("music")

# Формат хранения. 192 кбит/с, а не 128: у живой записи есть верх, который
# кодек на 128 подрезает около 15 кГц, и именно этого верха синтезу не хватало.
BITRATE = "192k"
SUFFIX = ".m4a"

# Границы приёма. Выведены из того, как бед используется: P10 зацикливает его
# на длину ролика (35–70 сек), поэтому слишком короткий даст слышимый повтор,
# а слишком длинный — лишние мегабайты в git при том, что дальше 70 секунд
# ролик не идёт.
MIN_DURATION_SEC = 20.0
MAX_DURATION_SEC = 180.0
# Клиппованный исходник в миксе станет только хуже: P10 добавит к нему голос.
MAX_PEAK_DBFS = -0.5
# Совсем тихую запись нормализация вытянет вместе с шумом полки.
MIN_LUFS = -40.0


@dataclass(frozen=True)
class Mood:
    """Настроение подложки: имя для планировщика и описание для человека."""

    id: str
    title: str


# Словарь настроений. Это не список файлов, а список ролей, которые библиотека
# обязана закрывать: P1 выбирает подложку по категории ролика и хэшу
# ``video_id`` (см. ``MUSIC_BY_CATEGORY`` в планировщике), и каждое имя оттуда
# должно чем-то закрываться. Пока файла нет — роль пустая, и P10 честно
# предупреждает, что подложки не будет.
MOODS: tuple[Mood, ...] = (
    Mood("cosmic_calm", "космос, медленный дрейф"),
    Mood("tech_tension", "техно-напряжение, скрытый пульс"),
    Mood("neutral_drive", "ровное движение вперёд"),
    Mood("discovery_warm", "тёплое открытие"),
    Mood("dark_pulse", "тёмный пульс"),
    Mood("violin_drive", "струнные в движении, нарастающее напряжение"),
    Mood("strings_sad", "печальные струнные, медленно"),
    Mood("strings_hope", "светлые струнные, надежда"),
    Mood("piano_quiet", "тихое пианино, разреженно"),
    Mood("piano_sad", "пианино в миноре, грустно"),
    Mood("keys_curious", "любопытство, лёгкие клавиши"),
    Mood("keys_night", "ночь, редкие ноты"),
    Mood("pulse_urgent", "тревога, частый пульс"),
    Mood("pulse_news", "новостной ход, ровный ритм"),
    Mood("drone_deep", "глубокий космос, почти без движения"),
)

MOOD_IDS: tuple[str, ...] = tuple(m.id for m in MOODS)
MOOD_TITLES: dict[str, str] = {m.id: m.title for m in MOODS}


def inspect_bed(path: Path) -> dict[str, Any]:
    """Промерить запись перед приёмом. Ничего не меняет на диске."""
    audio, sr = load_audio_any(path, SAMPLE_RATE)
    stereo = to_stereo(audio)
    duration = len(stereo) / float(sr or SAMPLE_RATE)
    loudness = measure_loudness_buffer(stereo, sr or SAMPLE_RATE)
    mono = stereo.mean(axis=1)
    # Стык петли: бед играет по кругу, и если хвост громче головы (или
    # наоборот), на склейке слышен толчок. Сравниваем по 0.2 секунды с краёв.
    edge = max(1, int(0.2 * (sr or SAMPLE_RATE)))
    head = float(abs(mono[:edge]).mean())
    tail = float(abs(mono[-edge:]).mean())
    seam = abs(head - tail) / max(head, tail, 1e-9)
    return {
        "duration_sec": round(duration, 3),
        "integrated_lufs": round(float(loudness.integrated_lufs), 2),
        "peak_dbfs": round(float(peak_dbfs(stereo)), 2),
        "loop_seam": round(seam, 3),
        "sample_rate": int(sr or SAMPLE_RATE),
        "channels": 2,
    }


def check_bed(report: dict[str, Any]) -> list[str]:
    """Что мешает принять запись. Пустой список — принимаем."""
    problems: list[str] = []
    duration = float(report["duration_sec"])
    if duration < MIN_DURATION_SEC:
        problems.append(
            f"{duration:.1f} сек — короче {MIN_DURATION_SEC:.0f}: ролик длиной "
            f"до 70 секунд услышит повтор петли")
    if duration > MAX_DURATION_SEC:
        problems.append(
            f"{duration:.1f} сек — длиннее {MAX_DURATION_SEC:.0f}: дальше "
            f"70 секунд ролик не идёт, остальное осядет в git мёртвым весом")
    if float(report["peak_dbfs"]) > MAX_PEAK_DBFS:
        problems.append(
            f"пик {report['peak_dbfs']:.1f} dBFS выше {MAX_PEAK_DBFS}: в миксе "
            f"к беду добавится голос, и запас нужен")
    if float(report["integrated_lufs"]) < MIN_LUFS:
        problems.append(
            f"{report['integrated_lufs']:.1f} LUFS тише {MIN_LUFS}: "
            f"нормализация вытянет вместе с музыкой шум полки")
    return problems


def add_bed(cfg, *, source: Path, mood: str, title: str = "",
            force: bool = False) -> dict[str, Any]:
    """Принять живую запись в библиотеку подложек.

    Возвращает отчёт с замерами. При отказе поднимает ``RedshiftError`` —
    молча положить негодный файл хуже, чем не положить никакого.
    """
    from .manifest import AssetRecord, open_library, today

    source = Path(source)
    if not source.is_file():
        raise RedshiftError(f"файла нет: {source}", code="MUSIC_SOURCE_MISSING")
    if mood not in MOOD_IDS:
        raise RedshiftError(
            f"настроение {mood!r} не из словаря; известные: {', '.join(MOOD_IDS)}",
            code="MUSIC_UNKNOWN_MOOD")

    report = inspect_bed(source)
    problems = check_bed(report)
    if problems and not force:
        raise RedshiftError(
            "запись не проходит приём: " + "; ".join(problems),
            code="MUSIC_REJECTED", mood=mood, **report)

    lib = open_library(cfg, "music")
    filename = f"{mood}{SUFFIX}"
    dst = lib.dir / filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Приводим к одному формату: P10 не должен разбираться с чужими
    # контейнерами и частотами в середине прогона.
    ffmpeg_run(["-y", "-i", str(source), "-vn", "-c:a", "aac", "-b:a", BITRATE,
                "-ar", str(SAMPLE_RATE), "-ac", "2", str(dst)],
               what=f"принять подложку {mood}")

    # Замена записи того же настроения: файл перезаписан выше, и вторая
    # запись на него была бы дублем. Отдельного remove у библиотеки нет —
    # список правится на месте, как это делает и вытеснение.
    existing = lib.by_mood(mood)
    if existing is not None:
        lib.items[:] = [i for i in lib.items if i.id != existing.id]
    lib.add(AssetRecord(
        id=f"music_{mood}", type="music", source="curated",
        license="предоставлено заказчиком", mood=mood,
        tags=[mood, "loopable", "no-vocals", "live"],
        vision_summary=title or MOOD_TITLES.get(mood, ""),
        duration_sec=report["duration_sec"], file=filename, added=today(),
        extra={"measured": report, "accepted_with_warnings": problems or None},
    ))
    lib.save()
    _log.info("подложка принята: %s (%.1f сек, %.1f LUFS, пик %.1f dBFS)",
              mood, report["duration_sec"], report["integrated_lufs"],
              report["peak_dbfs"])
    return {"mood": mood, "file": filename, "measured": report,
            "warnings": problems, "count": lib.count}


def library_status(cfg) -> dict[str, Any]:
    """Что в библиотеке есть и каких настроений не хватает."""
    from .manifest import open_library

    lib = open_library(cfg, "music")
    present = {item.mood for item in lib.items if item.mood}
    return {
        "count": lib.count,
        "present": sorted(present),
        "missing": [m for m in MOOD_IDS if m not in present],
        "titles": MOOD_TITLES,
    }
