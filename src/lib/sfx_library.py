"""Курируемая библиотека коротких звуков (§14.1).

Синтетические wav заказчик снял и залил свои: вжухи, клики, электричество,
калимба. Синтез в ``fill-libraries`` не возвращается — как с подложками.

Приём делает три вещи:

* **меряет**, а не доверяет имени файла;
* **режет** интересный отрезок ≤2 сек и приводит к WAV 48 кГц стерео;
* **заводит** запись с ролью (для старых сценариев) и тегами (для монтажа).

Монтаж берёт звук по смыслу кадра: появилась картинка — вжух; плашка — клик;
кнопка подписки — награда. Роль из сценария — ручное решение автора, оно
важнее автоматики. Нет роли в базе — звук не выдумывается.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..errors import RedshiftError
from .audio import (
    SAMPLE_RATE,
    load_audio_any,
    normalize_peak,
    peak_dbfs,
    phone_speaker_loss_db,
    save_wav,
    to_stereo,
)
from .ffmpeg import run as ffmpeg_run
from .logging import get_logger

_log = get_logger("sfx")

SUFFIX = ".wav"
MAX_DURATION_SEC = 2.0
MIN_DURATION_SEC = 0.04
MAX_PEAK_DBFS = -0.5

# --- словарь тегов ------------------------------------------------------------
#
# Как у подложек: у записи тегов несколько, монтаж ищет совпадение смыслов.
# «Вжух» честнее слота whoosh_in: один файл может закрыть вход аватара,
# появление картинки и динамический переход.

KINDS: dict[str, str] = {
    "whoosh": "вжух воздуха, появление или уход",
    "hit": "удар, акцент на факте",
    "click": "клик, клацанье, UI",
    "chime": "тональный акцент, калимба",
    "electric": "электричество, искра, ток",
    "reward": "награда, CTA, мем",
    "rumble": "глухой воздух, почти инфразвук — не для телефона",
}

SHAPE: dict[str, str] = {
    "air": "воздух, поток",
    "sharp": "острый, слышен на динамике телефона",
    "soft": "мягкий, басовый",
    "swipe": "свайп, двойное движение",
    "wide": "широкий, кинематографический",
    "punch": "короткий удар",
    "sub": "низкий, под голосом",
    "thud": "глухой толчок",
    "tick": "тик, деревянный клик",
    "ui": "интерфейс, кнопка, мышь",
    "clap": "хлопок",
    "snap": "щелчок",
    "hat": "открытый хэт, появление",
    "bright": "верх открыт",
    "spark": "искра, разряд",
    "build": "нарастание",
    "sting": "короткий джингл",
    "kalimba": "калимба, lamellophone",
    "reveal": "раскрытие, полноэкранный текст",
}

TAGS: dict[str, str] = {**KINDS, **SHAPE}

# Смысл кадра → какие теги просим. Совпадение важнее имени файла.
INTENTS: dict[str, tuple[str, ...]] = {
    "picture_in": ("whoosh", "sharp"),
    "picture_out": ("whoosh", "soft"),
    "avatar_in": ("whoosh", "sharp"),
    "avatar_out": ("whoosh", "soft"),
    "transition": ("whoosh", "swipe"),
    "fullscreen": ("reveal", "hat"),
    "plaque": ("click", "snap"),
    "cta": ("reward", "chime"),
    "meme": ("reward", "sting"),
    "impact": ("hit", "punch"),
    "sub": ("sub", "hit"),
    "ui": ("click", "ui"),
    "data": ("electric", "spark"),
    "riser": ("electric", "build"),
    "tick": ("tick", "click"),
}

# Старые имена ролей из сценариев → смысл. Сценарий не переписываем:
# «whoosh_in» по-прежнему работает, просто закрывается живым вжухом.
ROLE_TO_INTENT: dict[str, str] = {
    "whoosh_in": "picture_in",
    "whoosh_out": "picture_out",
    "swipe": "transition",
    "hit_impact": "impact",
    "sub_drop": "sub",
    "boom": "impact",
    "riser": "riser",
    "pop": "plaque",
    "ui_click": "ui",
    "type_key": "tick",
    "tick": "tick",
    "glitch": "data",
    "data_beep": "data",
    "reveal": "fullscreen",
    "chime": "cta",
    "notification": "cta",
    "camera_shutter": "plaque",
    "error_buzz": "sub",
    "meme_stinger": "meme",
    "subscribe_ping": "cta",
}

WHOOSH_INTENTS = frozenset({
    "picture_in", "picture_out", "avatar_in", "avatar_out", "transition",
})

# Присланные файлы. Имена — как заказчик залил; после приёма они уходят.
# start/length сняты с огибающей: берём плотную часть, не тишину по краям.
CUSTOMER_DROP: tuple[dict[str, Any], ...] = (
    {"source": "air-effect-single-sharp.mp3", "id": "whoosh_sharp",
     "role": "whoosh_in", "tags": ["whoosh", "air", "sharp"],
     "title": "острый вжух воздуха", "start": 0.28, "length": 1.10},
    {"source": "d53b652c49b8b0b.mp3", "id": "whoosh_soft",
     "role": "whoosh_out", "tags": ["whoosh", "air", "soft"],
     "title": "мягкий басовый вжух", "start": 0.12, "length": 1.10},
    {"source": "149206cfec5991.mp3", "id": "whoosh_double",
     "role": "swipe", "tags": ["whoosh", "swipe", "air"],
     "title": "двойной вжух-свайп", "start": 0.0, "length": 0.73},
    {"source": "viralaudio-descent-whoosh-long-cinematic-sound-effect-405921.mp3",
     "id": "whoosh_cinematic", "role": "boom",
     "tags": ["whoosh", "air", "wide"],
     "title": "широкий кинематографический вжух", "start": 1.85, "length": 2.00},
    {"source": "air-effect-muted-soft.mp3", "id": "rumble_air",
     "role": "", "tags": ["rumble", "sub", "air"],
     "title": "глухой воздух: на телефоне не слышен, в монтаж картинки не берём",
     "start": 0.0, "length": 1.69},
    {"source": "scifi-airflow-with-current-sound-effects.mp3", "id": "electric_airflow",
     "role": "riser", "tags": ["electric", "air", "build"],
     "title": "электрический поток, нарастание", "start": 1.35, "length": 2.00},
    {"source": "fe6e86e9eaa9860.mp3", "id": "electric_spark",
     "role": "glitch", "tags": ["electric", "spark"],
     "title": "искра, разряд", "start": 0.18, "length": 0.70},
    {"source": "1393d3ce4a381f6.mp3", "id": "hit_punch",
     "role": "hit_impact", "tags": ["hit", "punch"],
     "title": "короткий удар", "start": 0.04, "length": 0.50},
    {"source": "dyihatelnaya-artilleriya--vyistrel-tishinyi.mp3", "id": "hit_silence",
     "role": "sub_drop", "tags": ["hit", "sub"],
     "title": "выстрел тишины", "start": 0.0, "length": 0.55},
    {"source": "4035a95a765fd86.mp3", "id": "hit_thud",
     "role": "error_buzz", "tags": ["hit", "sub", "thud"],
     "title": "глухой толчок", "start": 0.0, "length": 0.62},
    {"source": "35916__altemark__claves.wav", "id": "click_claves",
     "role": "ui_click", "tags": ["click", "tick", "ui"],
     "title": "клаве, клик кнопки", "start": 0.0, "length": 0.06},
    {"source": "35917__altemark__claves2.wav", "id": "click_wood",
     "role": "tick", "tags": ["click", "tick", "ui"],
     "title": "деревянный клик, мышь", "start": 0.0, "length": 0.06},
    {"source": "35915__altemark__claps.wav", "id": "snap_clap",
     "role": "pop", "tags": ["click", "clap", "snap"],
     "title": "хлопок, щелчок плашки", "start": 0.0, "length": 0.23},
    {"source": "35918__altemark__conga.wav", "id": "hit_conga",
     "role": "camera_shutter", "tags": ["hit", "click"],
     "title": "короткий удар мембраны", "start": 0.0, "length": 0.07},
    {"source": "35919__altemark__oh.wav", "id": "hat_open",
     "role": "reveal", "tags": ["hat", "bright", "reveal"],
     "title": "открытый хэт — появление текста", "start": 0.0, "length": 0.74},
    {"source": "35268__linse__thumbpiano_e_2.wav", "id": "chime_kalimba_e",
     "role": "chime", "tags": ["chime", "kalimba", "bright"],
     "title": "калимба E", "start": 0.0, "length": 1.55},
    {"source": "35271__linse__thumbpiano_g_1.wav", "id": "chime_kalimba_g",
     "role": "notification", "tags": ["chime", "kalimba", "bright"],
     "title": "калимба G", "start": 0.0, "length": 1.50},
    {"source": "646673__sounddesignforyou__coin-pickup-sfx-1.wav", "id": "coin_pickup",
     "role": "subscribe_ping", "tags": ["reward", "chime", "sting"],
     "title": "звон награды, кнопка подписки", "start": 0.0, "length": 1.20},
)


def describe_tags(tags: Sequence[str]) -> str:
    return ", ".join(TAGS.get(t, t) for t in tags)


def unknown_tags(tags: Iterable[str]) -> list[str]:
    return [t for t in tags if t not in TAGS]


def intent_for_role(role: str) -> str:
    return ROLE_TO_INTENT.get(role, "")


def inspect_clip(path: Path) -> dict[str, Any]:
    """Промерить запись. Ничего не меняет на диске."""
    audio, sr = load_audio_any(path, SAMPLE_RATE)
    stereo = to_stereo(audio)
    duration = len(stereo) / float(sr or SAMPLE_RATE)
    try:
        phone_loss = round(float(phone_speaker_loss_db(stereo, sr or SAMPLE_RATE)), 2)
    except Exception:  # noqa: BLE001 — мерка справочная, отказ не блокирует приём
        phone_loss = None
    return {
        "duration_sec": round(duration, 3),
        "peak_dbfs": round(float(peak_dbfs(stereo)), 2),
        "sample_rate": int(sr or SAMPLE_RATE),
        "channels": int(stereo.shape[1]),
        "phone_loss_db": phone_loss,
    }


def check_clip(report: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    duration = float(report["duration_sec"])
    if duration < MIN_DURATION_SEC:
        problems.append(f"{duration:.3f} сек — короче щелчка, в ролике не услышать")
    if duration > MAX_DURATION_SEC + 0.05:
        problems.append(
            f"{duration:.2f} сек — длиннее {MAX_DURATION_SEC:.0f}: короткий "
            f"звук не должен тянуться под речь")
    if float(report["peak_dbfs"]) > MAX_PEAK_DBFS:
        problems.append(
            f"пик {report['peak_dbfs']:.1f} dBFS выше {MAX_PEAK_DBFS}: "
            f"в миксе к нему добавится голос")
    return problems


def cut_clip(source: Path, dst: Path, *, start_sec: float, length_sec: float) -> Path:
    """Вырезать отрезок, вернуть запас по пику, привести к WAV 48 кГц стерео."""
    length_sec = min(float(length_sec), MAX_DURATION_SEC)
    fade_in = 0.006
    fade_out = min(0.03, max(0.008, length_sec * 0.08))
    out_start = max(0.0, length_sec - fade_out)
    chain = (f"volume=0.5,"
             f"afade=t=in:st=0:d={fade_in},"
             f"afade=t=out:st={out_start:.3f}:d={fade_out:.3f}")
    ffmpeg_run(
        ["-y", "-ss", f"{start_sec:.3f}", "-t", f"{length_sec:.3f}",
         "-i", str(source), "-vn", "-af", chain,
         "-c:a", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", "2", str(dst)],
        what=f"вырезать sfx {dst.stem}",
    )
    return dst


def add_clip(cfg, *, source: Path, clip_id: str, tags: Sequence[str],
             role: str = "", title: str = "", start_sec: float = 0.0,
             length_sec: float | None = None, force: bool = False) -> dict[str, Any]:
    """Принять короткий звук в библиотеку."""
    from .manifest import AssetRecord, open_library, today

    source = Path(source)
    if not source.is_file():
        raise RedshiftError(f"файла нет: {source}", code="SFX_SOURCE_MISSING")
    tags = list(dict.fromkeys(tags))
    if not tags:
        raise RedshiftError("звуку нужны теги — по ним его и выбирают",
                            code="SFX_NO_TAGS")
    bad = unknown_tags(tags)
    if bad:
        raise RedshiftError(
            f"теги не из словаря: {', '.join(bad)}; известные: {', '.join(sorted(TAGS))}",
            code="SFX_UNKNOWN_TAG")

    measured_src = inspect_clip(source)
    if length_sec is None:
        length_sec = min(float(measured_src["duration_sec"]) - float(start_sec),
                         MAX_DURATION_SEC)
    length_sec = max(MIN_DURATION_SEC, min(float(length_sec), MAX_DURATION_SEC))

    lib = open_library(cfg, "sfx")
    filename = f"{clip_id}{SUFFIX}"
    dst = lib.dir / filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Источник может лежать в той же папке: режем через временный файл,
    # иначе ffmpeg читает и пишет один путь.
    tmp = dst.with_suffix(".tmp.wav")
    try:
        cut_clip(source, tmp, start_sec=float(start_sec), length_sec=length_sec)
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)

    # Декодер mp3 на клиппованном мастере может отдать семплы выше 1.0 —
    # ffmpeg volume=0.5 тогда всё равно садится в 0 dBFS. Запас возвращаем
    # по факту, уже в float.
    audio, sr = load_audio_any(dst, SAMPLE_RATE)
    if peak_dbfs(to_stereo(audio)) > MAX_PEAK_DBFS:
        save_wav(dst, normalize_peak(audio, -6.0), sr)

    report = inspect_clip(dst)
    problems = check_clip(report)
    if problems and not force:
        dst.unlink(missing_ok=True)
        raise RedshiftError(
            "запись не проходит приём: " + "; ".join(problems),
            code="SFX_REJECTED", clip_id=clip_id, **report)

    existing = lib.by_id(f"sfx_{clip_id}")
    if existing is not None:
        lib.items[:] = [i for i in lib.items if i.id != existing.id]
    if role:
        twin = lib.by_role(role)
        if twin is not None and twin.id != f"sfx_{clip_id}":
            twin.role = ""
    lib.add(AssetRecord(
        id=f"sfx_{clip_id}", type="sfx", source="curated",
        license="предоставлено заказчиком",
        role=role, tags=list(tags),
        vision_summary=title or describe_tags(tags),
        duration_sec=report["duration_sec"], file=filename, added=today(),
        extra={"measured": report, "source_file": source.name,
               "segment_start_sec": round(float(start_sec), 3),
               "accepted_with_warnings": problems or None},
    ))
    lib.save()
    _log.info("sfx принят: %s [%s] %.2f сек, пик %.1f dBFS",
              clip_id, ", ".join(tags), report["duration_sec"], report["peak_dbfs"])
    return {"id": clip_id, "file": filename, "role": role, "tags": tags,
            "measured": report, "warnings": problems, "count": lib.count}


def ingest_customer_drop(cfg, folder: Path | None = None) -> dict[str, Any]:
    """Принять пачку, которую заказчик залил в ``assets/sfx/``."""
    from .manifest import open_library

    lib = open_library(cfg, "sfx")
    folder = Path(folder) if folder is not None else lib.dir
    added: list[str] = []
    for spec in CUSTOMER_DROP:
        source = folder / spec["source"]
        add_clip(
            cfg, source=source, clip_id=spec["id"], tags=spec["tags"],
            role=spec.get("role") or "", title=spec.get("title") or "",
            start_sec=float(spec.get("start") or 0.0),
            length_sec=float(spec["length"]), force=True,
        )
        added.append(spec["id"])
    keep = {item.file for item in open_library(cfg, "sfx").items}
    keep.add("sfx_manifest.json")
    removed: list[str] = []
    for path in folder.iterdir():
        if path.is_file() and path.name not in keep:
            path.unlink()
            removed.append(path.name)
    return {"added": added, "removed": removed,
            "count": open_library(cfg, "sfx").count}


def library_status(cfg) -> dict[str, Any]:
    from .manifest import open_library

    lib = open_library(cfg, "sfx")
    covered: dict[str, list[str]] = {}
    for item in lib.items:
        for tag in item.tags:
            if tag in TAGS:
                covered.setdefault(tag, []).append(item.id)
    return {
        "count": lib.count,
        "clips": [{"id": i.id, "role": i.role, "tags": [t for t in i.tags if t in TAGS],
                   "duration_sec": i.duration_sec, "file": i.file}
                  for i in lib.items],
        "by_tag": {t: sorted(ids) for t, ids in sorted(covered.items())},
        "kinds_missing": [t for t in KINDS if t not in covered],
        "vocabulary": TAGS,
    }


def pick_sfx(cfg, *, want: Sequence[str], video_id: str,
             avoid_ids: Sequence[str] = ()) -> Any:
    """Выбрать звук по тегам. Совпадение важнее свежести, свежесть — хэша.

    ``avoid_ids`` — уже поставленные в этом ролике: один вжух на все склейки
    слышен как петля. Нет замены — берём повтор, тишина хуже.
    """
    from .manifest import open_library

    lib = open_library(cfg, "sfx")
    if not lib.items:
        return None
    want_set = set(want)
    avoid = set(avoid_ids)
    pool = [i for i in lib.items if i.id not in avoid] or list(lib.items)

    def rank(item: Any) -> tuple[int, int]:
        matched = len(want_set & set(item.tags)) if want_set else 1
        return matched, -len(item.used_in)

    # rumble на телефоне теряет ~29 дБ: картинку им не озвучиваем.
    if "whoosh" in want_set or "click" in want_set or "hit" in want_set:
        audible = [i for i in pool if "rumble" not in i.tags]
        if audible:
            pool = audible

    best = max(rank(i) for i in pool)
    if want_set and best[0] <= 0:
        return None
    finalists = sorted((i for i in pool if rank(i) == best), key=lambda i: i.id)
    digest = hashlib.sha256((video_id or "").encode("utf-8")).digest()
    return finalists[int.from_bytes(digest[:8], "big") % len(finalists)]
