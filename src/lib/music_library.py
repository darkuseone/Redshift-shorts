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

from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

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
# ролик не идёт. Отрезок по умолчанию — 70 секунд, ровно потолок ролика:
# так подложка ни разу не повторится даже в самом длинном.
MIN_DURATION_SEC = 20.0
MAX_DURATION_SEC = 180.0
# Клиппованный исходник в миксе станет только хуже: P10 добавит к нему голос.
MAX_PEAK_DBFS = -0.5
# Совсем тихую запись нормализация вытянет вместе с шумом полки.
MIN_LUFS = -40.0


# --- словарь тегов ------------------------------------------------------------
#
# Заказчик попросил именно теги, а не фиксированные слоты: «пометь их тэгами
# для удобного использования в видео, чтобы монтаж умел брать их
# самостоятельно, где то скрипка где то пианино где то эмбиент где то космос».
# Тег честнее слота: у одной записи их несколько, и подложка находится по
# совпадению смыслов, а не по тому, в какую единственную ячейку её положили.

INSTRUMENTS: dict[str, str] = {
    "strings": "струнные, смычок",
    "piano": "фортепиано и клавиши",
    "ambient": "эмбиент без выраженных нот",
    "pulse": "пульс, арпеджио, ритмический рисунок",
}

THEMES: dict[str, str] = {
    "space": "космос, масштаб, пустота",
    "tech": "техника, данные, лаборатория",
    "nature": "земля, вода, живое",
}

CHARACTER: dict[str, str] = {
    "calm": "спокойно, без нажима",
    "driving": "с движением вперёд",
    "wide": "широко, много воздуха",
    "dark": "темно, низко",
    "bright": "светло, верх открыт",
    "sparse": "редко, много тишины между событиями",
    "tense": "напряжённо",
}

TAGS: dict[str, str] = {**INSTRUMENTS, **THEMES, **CHARACTER}


def describe_tags(tags: Sequence[str]) -> str:
    """Теги словами — для отчётов и для человека."""
    return ", ".join(TAGS.get(t, t) for t in tags)


def unknown_tags(tags: Iterable[str]) -> list[str]:
    return [t for t in tags if t not in TAGS]


def find_segment(path: Path, *, length_sec: float = 70.0,
                 skip_head_sec: float = 10.0, skip_tail_sec: float = 8.0) -> float:
    """Найти интересный отрезок: где играть, а не где вступление.

    Заказчик просил «вырезай всегда интересный отрезок для видео», и это не
    вкусовщина, а измеримое требование. Присланные записи идут по три минуты и
    устроены одинаково: тихое вступление, развитие, затухание. Взять начало —
    значит положить под ролик почти тишину.

    Окно оценивается по четырём признакам, и все четыре нужны:

    * **громкость** — отрезок должен быть из плотной части, а не из провала;
    * **ровность** — качели по громкости в подложке слышны как «уплывает»;
    * **стык** — если ролик длиннее отрезка, P10 закольцует его, и разница
      уровней между началом и концом станет толчком на склейке;
    * **провалы** — доля почти-тишины внутри окна; из-за неё подложка
      пропадает под голосом и возвращается рывком.

    Края отбрасываются: вступление и затухание не годятся ни при какой оценке.
    """
    audio, sr = load_audio_any(path, SAMPLE_RATE)
    mono = audio.mean(axis=1) if getattr(audio, "ndim", 1) == 2 else audio
    sr = sr or SAMPLE_RATE
    hop = max(1, int(0.05 * sr))
    env = np.array([float(np.sqrt((mono[i:i + hop] ** 2).mean() + 1e-12))
                    for i in range(0, len(mono) - hop, hop)])
    if env.size == 0:
        return 0.0
    width = int(length_sec / 0.05)
    lo = int(skip_head_sec / 0.05)
    hi = len(env) - width - int(skip_tail_sec / 0.05)
    if hi <= lo:                       # запись короче, чем окно с отступами
        return 0.0

    edge = int(2.0 / 0.05)
    best_score, best_start = None, float(lo * 0.05)
    for start in range(lo, hi, int(1.0 / 0.05)):
        window = env[start:start + width]
        if window.size < width:
            break
        mean = float(window.mean()) or 1e-9
        steady = 1.0 - min(float(window.std()) / mean, 1.0)
        seam = 1.0 - min(abs(float(window[:edge].mean() - window[-edge:].mean())) / mean, 1.0)
        quiet = float((window < mean * 0.25).mean())
        score = mean / float(env.max()) * 0.5 + steady * 0.25 + seam * 0.25 - quiet * 0.5
        if best_score is None or score > best_score:
            best_score, best_start = score, start * 0.05
    return round(best_start, 1)


def cut_segment(source: Path, dst: Path, *, start_sec: float,
                length_sec: float = 70.0) -> Path:
    """Вырезать отрезок, вернуть запас по пику и привести к формату хранения.

    Запас нужен не «на всякий случай»: присланные мастера клиппованы — пики
    от +0.2 до +2.4 dBFS, — а в миксе к беду добавится голос. Уровень при этом
    не задаётся: его ставит P10 по LUFS под конкретный ролик.

    Короткие фейды по краям — чтобы стык петли не щёлкал.
    """
    fade = 0.8
    chain = (f"afade=t=in:st=0:d={fade},"
             f"afade=t=out:st={max(0.0, length_sec - fade):.2f}:d={fade},"
             f"loudnorm=I=-20:TP=-1.0:LRA=11:linear=true,"
             f"alimiter=limit=0.891")
    ffmpeg_run(["-y", "-ss", f"{start_sec:.2f}", "-t", f"{length_sec:.2f}",
                "-i", str(source), "-vn", "-af", chain,
                "-c:a", "aac", "-b:a", BITRATE,
                "-ar", str(SAMPLE_RATE), "-ac", "2", str(dst)],
               what=f"вырезать подложку {dst.stem}")
    return dst


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


def add_bed(cfg, *, source: Path, bed_id: str, tags: Sequence[str],
            title: str = "", start_sec: float | None = None,
            length_sec: float = 70.0, force: bool = False) -> dict[str, Any]:
    """Принять живую запись в библиотеку подложек.

    ``start_sec`` — начало интересного отрезка. Не задан — отрезок ищется сам:
    присланные записи идут по три минуты, и брать их целиком незачем, а начало
    у них всегда вступление из тишины.

    Возвращает отчёт с замерами. При отказе поднимает ``RedshiftError`` —
    молча положить негодный файл хуже, чем не положить никакого.
    """
    from .manifest import AssetRecord, open_library, today

    source = Path(source)
    if not source.is_file():
        raise RedshiftError(f"файла нет: {source}", code="MUSIC_SOURCE_MISSING")
    tags = list(dict.fromkeys(tags))
    if not tags:
        raise RedshiftError("подложке нужны теги — по ним её и выбирают",
                            code="MUSIC_NO_TAGS")
    bad = unknown_tags(tags)
    if bad:
        raise RedshiftError(
            f"теги не из словаря: {', '.join(bad)}; известные: {', '.join(sorted(TAGS))}",
            code="MUSIC_UNKNOWN_TAG")
    if not any(t in INSTRUMENTS for t in tags):
        raise RedshiftError(
            "нужен хотя бы один тег инструмента: " + ", ".join(sorted(INSTRUMENTS)),
            code="MUSIC_NO_INSTRUMENT")

    if start_sec is None:
        start_sec = find_segment(source, length_sec=length_sec)

    lib = open_library(cfg, "music")
    filename = f"{bed_id}{SUFFIX}"
    dst = lib.dir / filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    cut_segment(source, dst, start_sec=start_sec, length_sec=length_sec)

    report = inspect_bed(dst)
    problems = check_bed(report)
    if problems and not force:
        dst.unlink(missing_ok=True)
        raise RedshiftError(
            "запись не проходит приём: " + "; ".join(problems),
            code="MUSIC_REJECTED", bed_id=bed_id, **report)

    # Замена записи с тем же именем: файл перезаписан выше, и вторая запись на
    # него была бы дублем. Отдельного remove у библиотеки нет — список правится
    # на месте, как это делает и вытеснение.
    existing = lib.by_id(f"music_{bed_id}")
    if existing is not None:
        lib.items[:] = [i for i in lib.items if i.id != existing.id]
    lib.add(AssetRecord(
        id=f"music_{bed_id}", type="music", source="curated",
        license="предоставлено заказчиком",
        mood=next((t for t in tags if t in INSTRUMENTS), ""),
        tags=[*tags, "loopable", "no-vocals"],
        vision_summary=title or describe_tags(tags),
        duration_sec=report["duration_sec"], file=filename, added=today(),
        extra={"measured": report, "source_file": source.name,
               "segment_start_sec": round(float(start_sec), 1),
               "accepted_with_warnings": problems or None},
    ))
    lib.save()
    _log.info("подложка принята: %s [%s] отрезок с %.0f с (%.1f сек, %.1f LUFS)",
              bed_id, ", ".join(tags), start_sec, report["duration_sec"],
              report["integrated_lufs"])
    return {"id": bed_id, "file": filename, "tags": tags,
            "segment_start_sec": round(float(start_sec), 1),
            "measured": report, "warnings": problems, "count": lib.count}


def library_status(cfg) -> dict[str, Any]:
    """Что в библиотеке есть и какими тегами она покрыта."""
    from .manifest import open_library

    lib = open_library(cfg, "music")
    covered: dict[str, list[str]] = {}
    for item in lib.items:
        for tag in item.tags:
            if tag in TAGS:
                covered.setdefault(tag, []).append(item.id)
    return {
        "count": lib.count,
        "beds": [{"id": i.id, "tags": [t for t in i.tags if t in TAGS],
                  "duration_sec": i.duration_sec, "used_in": i.used_in}
                 for i in lib.items],
        "by_tag": {t: sorted(ids) for t, ids in sorted(covered.items())},
        "instruments_missing": [t for t in INSTRUMENTS if t not in covered],
        "vocabulary": TAGS,
    }


def pick_bed(cfg, *, want: Sequence[str], video_id: str,
             recent_videos: Sequence[str] = ()) -> Any:
    """Выбрать подложку: сперва по тегам, потом по свежести, потом по хэшу.

    Три правила по убыванию важности, и каждое из-за своего изъяна:

    * **совпадение тегов** — это и есть смысл. Просили «пульс, техника» —
      получите пульс, а не эмбиент.
    * **свежесть** — бед, звучавший в одном из последних роликов, при равном
      совпадении уступает. Без этого канал звучит одинаково: на девяти бедах
      и пяти рубриках выбор без истории намертво прилипает к одному.
    * **хэш ``video_id``** — на полном отпечатке, а не на первом байте.
      Первый байт делит надвое по чётности, и три ролика подряд (0047, 0048,
      0049) попали в одну сторону: 216, 186, 196 — все чётные. Пересборка
      того же ролика по-прежнему даёт тот же бед, иначе версии A и B
      разъедутся по звуку и сравнивать их станет нечем.
    """
    import hashlib

    from .manifest import open_library

    lib = open_library(cfg, "music")
    if not lib.items:
        return None
    want_set = set(want)
    recent = set(recent_videos)

    def rank(item: Any) -> tuple[int, int, int]:
        matched = len(want_set & set(item.tags))
        # Прямой запрет: бед из последних роликов не берём, если есть замена.
        stale = 1 if recent and set(item.used_in) & recent else 0
        # И общий счётчик — им ротация держится сама, без внешней истории:
        # при равном совпадении вперёд идёт тот, что звучал реже. Так же
        # ротируются шаблоны, и по той же причине — иначе канал звучит
        # одинаково, а на девяти бедах это слышно с третьего ролика.
        return matched, -stale, -len(item.used_in)

    best = max(rank(i) for i in lib.items)
    finalists = sorted((i for i in lib.items if rank(i) == best), key=lambda i: i.id)
    digest = hashlib.sha256((video_id or "").encode("utf-8")).digest()
    return finalists[int.from_bytes(digest[:8], "big") % len(finalists)]
