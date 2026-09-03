"""Вечнозелёная база материала: то, что нужно каждому ролику канала.

Заказчик: «чтоб не искать их постоянно новые, а брать из базы». Локальная база
просматривается раньше внешних стоков (§7.2.1) — механизм был, наполнения не
было: после чистки мок-записей в базе не осталось ни одного файла, и каждый
слот каждого ролика снова уходил в сеть.

Канал говорит об одном и том же круге тем: космос, Земля, недра, лаборатория,
техника, лёд и вода, вулканы. Материал по ним не устаревает — снимок галактики
годится и через год, — поэтому он закачивается один раз и живёт в репозитории.

Источник — NASA и Internet Archive: общественное достояние, без ключа и без
денег. Это же снимает вопрос прав: у такого кадра нет владельца, которому надо
платить, и нет подписи, которую обязательно ставить в кадр.

Кадры приводятся к палитре канала при закачке, а не при монтаже: в базе лежит
то, что уже годится, и повторный грейд на каждый ролик не нужен.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .ffmpeg import extract_frames, grade_to_palette, probe
from .logging import get_logger
from .manifest import AssetRecord, FootageIndex, new_id, today
from .palette import palette_verdict
from .phash import phash_image
from .storage import sniff_suffix

_log = get_logger("footage_seed")


# Круг тем канала. Запрос — английский, потому что каталоги ищут по-английски;
# теги — те же слова, потому что P7 достаёт теги слота из своих же запросов
# (``_tags_for``), и совпасть они обязаны буквально.
#
# Список закрытый и небольшой намеренно: база не склад, а полка под рукой.
# Разрастаясь, она начинает подсовывать в ролик «что-то похожее» вместо того,
# что нужно этому кадру, — а материал по теме всё равно доищется в сети.
EVERGREEN: tuple[dict[str, Any], ...] = (
    {"id": "galaxy", "query": "hubble deep field galaxies",
     "intent": "далёкие галактики в глубоком поле телескопа",
     "tags": ["galaxy", "galaxies", "deep", "field", "space", "universe",
              "cosmos", "stars", "starfield"]},
    {"id": "nebula", "query": "nebula star forming region",
     "intent": "туманность, облако газа и пыли со звёздами",
     "tags": ["nebula", "star", "forming", "region", "space", "gas", "dust"]},
    {"id": "black-hole", "query": "chandra x-ray galactic center",
     "intent": "рентгеновский снимок центра галактики",
     "tags": ["black", "hole", "accretion", "disk", "singularity", "gravity"]},
    {"id": "earth-orbit", "query": "earth from space station limb",
     "intent": "Земля из космоса, край атмосферы",
     "tags": ["earth", "orbit", "space", "station", "planet", "atmosphere",
              "horizon", "globe"]},
    {"id": "sun", "query": "solar flare sun surface",
     "intent": "Солнце, вспышка или затмение",
     "tags": ["sun", "solar", "flare", "corona", "plasma", "star"]},
    {"id": "mars", "query": "mars curiosity self portrait",
     "intent": "поверхность Марса, марсоход",
     "tags": ["mars", "surface", "rover", "planet", "desert", "crater"]},
    {"id": "moon", "query": "moon surface crater apollo",
     "intent": "поверхность Луны, кратеры",
     "tags": ["moon", "lunar", "surface", "crater", "apollo", "regolith"]},
    {"id": "rocket", "query": "rocket launch night pad",
     "intent": "ракета на старте или в полёте",
     "tags": ["rocket", "launch", "pad", "engine", "flame", "liftoff",
              "spacecraft"]},
    {"id": "telescope", "query": "hubble telescope shuttle orbit",
     "intent": "космический телескоп, аппарат целиком",
     "tags": ["telescope", "observatory", "dome", "mirror", "astronomy"]},
    {"id": "ice", "query": "antarctic ice sheet aerial",
     "intent": "лёд, ледник, снежная равнина",
     "tags": ["ice", "antarctic", "arctic", "glacier", "sheet", "frozen",
              "snow", "polar"]},
    {"id": "volcano", "query": "volcano ash plume from orbit",
     "intent": "вулкан, шлейф пепла",
     "tags": ["volcano", "eruption", "lava", "magma", "crater", "ash"]},
    {"id": "ocean", "query": "hurricane eye from space",
     "intent": "океан, шторм или ураган сверху",
     "tags": ["ocean", "sea", "water", "storm", "hurricane", "wave"]},
    {"id": "desert", "query": "desert dunes from orbit",
     "intent": "пустыня, дюны, сухая земля сверху",
     "tags": ["desert", "dunes", "sand", "arid", "dry", "tundra"]},
    {"id": "lab", "query": "laboratory clean room engineer",
     "intent": "лаборатория, чистая комната, инженеры за работой",
     "tags": ["laboratory", "lab", "clean", "room", "engineer", "science",
              "research", "instrument"]},
    {"id": "machine", "query": "spacecraft assembly facility",
     "intent": "техника, сборочный цех, крупный агрегат",
     "tags": ["machine", "machinery", "facility", "tunnel", "test",
              "engineering", "industrial", "metal"]},
    {"id": "drill", "query": "curiosity drill hole rock",
     "intent": "бур, керн, скважина в породе",
     "tags": ["drill", "drilling", "rig", "core", "sample", "borehole",
              "geology", "rock"]},
)

# Оценка сеянного материала. Не единица: у него нет приговора зрения, и
# перебивать им кадр, который критик посмотрел и оценил выше, он не должен.
# Но и выше порога ``min_score``, иначе поиск его не увидит вовсе.
SEED_SCORE = 0.62

# Порог годности снимка для кадра 1080×1920. Первый засев положил в базу
# полосу 640×113 и снимок 640×360: в вертикальном кадре такой материал можно
# только растянуть, и выглядит это ровно на те деньги, которых стоило.
MIN_SHORT_SIDE = 900
# Панорама и полоска — не кадр: вписать их в вертикаль нечем.
ASPECT_RANGE = (0.4, 2.6)
# Потолок веса. База едет в репозитории, а ролики от неё не выигрывают
# настолько, чтобы держать в git пятидесятимегабайтные плёнки Internet Archive:
# первый засев так набрал 200 МБ на четырёх файлах.
MAX_BYTES = 12 * 1024 * 1024

# Заказчик: «преимущество всегда за реальным материалом». У NASA половина
# выдачи по космосу — концепты художника, и в кадре они читаются ровно как
# AI-генерация, от которой мы уходим. Отличить их можно только по подписи.
NOT_A_PHOTOGRAPH = ("artist", "concept", "illustration", "rendering",
                    "animation", "simulation", "graphic", "logo", "poster")


def _index_path(cfg) -> Path:
    return cfg.path("paths.cache_dir", "cache") / "footage_index.json"


def seed_footage(cfg, *, storage, costs=None, per_topic: int = 2,
                 topics: tuple[str, ...] = (), dry_run: bool = False) -> dict[str, Any]:
    """Закачать вечнозелёный материал в базу репозитория.

    Идемпотентно: тема, по которой в базе уже есть ``per_topic`` записей,
    пропускается, а совпавший по pHash кадр не кладётся второй раз. Запускать
    можно сколько угодно — второй запуск ничего не скачает.
    """
    from .providers.base import ProviderMode
    from .providers.stock import build_stock_providers
    from .providers.vision import build_vision_provider

    index = FootageIndex.load(cfg)
    providers = build_stock_providers(cfg, costs)
    sources = [providers[name] for name in ("nasa", "internet_archive")
               if name in providers]

    # Судья — тот же, что смотрит сток в P8 и генерацию в P9. Первый засев шёл
    # без него, и в базу легли три концепта художника вместо чёрной дыры,
    # диаграмма с осями вместо вулкана и самолёт вместо океана: слово «ocean»
    # стояло в описании миссии, а не на снимке. Подпись врёт, глаз — нет.
    #
    # Мок-судья к материалу не допускается: он раздаёт оценки, не глядя, и
    # такой приговор хуже отсутствующего. Без ключа остаётся фильтр подписей.
    critic = build_vision_provider(cfg, costs, role="primary")
    if getattr(critic, "mode", None) is not ProviderMode.LIVE:
        critic = None
    min_score = float(cfg.get("vision.seed_min_score",
                              cfg.get("vision.min_score", 0.6)))

    palette_rules = dict(cfg.brandbook.get("color_rules", {}).get("footage_palette", {}))
    grade_rules = {k: float(v) for k, v in
                   (palette_rules.get("press_grade") or {}).items()}
    # Порог палитры для сеянного — тот же, что для кадра со страницы статьи:
    # снимок туманности розовый по природе, и мерка ролика ему не по росту.
    # Он всё равно приводится к палитре грейдом, приговор здесь — от совсем
    # чужого цвета.
    off_share_max = float(palette_rules.get("press_off_share_max", 0.35))

    wanted = [t for t in EVERGREEN if not topics or t["id"] in topics]
    report: dict[str, Any] = {"added": [], "skipped": [], "topics": len(wanted)}
    work = cfg.path("paths.work_dir", "work") / "seed"
    work.mkdir(parents=True, exist_ok=True)

    for topic in wanted:
        have = [i for i in index.items
                if topic["id"] in (i.extra or {}).get("seed_topic", "")]
        need = max(0, per_topic - len(have))
        if not need:
            report["skipped"].append({"topic": topic["id"], "reason": "уже в базе"})
            continue

        taken = 0
        for provider in sources:
            if taken >= need:
                break
            try:
                candidates = provider.search(topic["query"], kind="photo",
                                             limit=max(4, need * 3))
            except Exception as exc:  # noqa: BLE001 — источник молчит, тема ждёт
                _log.warning("источник не ответил", extra={
                    "source": getattr(provider, "name", "?"), "topic": topic["id"],
                    "error": str(exc)[:200]})
                continue

            for candidate in candidates:
                if taken >= need:
                    break
                caption = (f"{candidate.meta.get('title', '')} "
                           f"{candidate.meta.get('description', '')}").lower()
                if any(word in caption for word in NOT_A_PHOTOGRAPH):
                    report["skipped"].append({"topic": topic["id"], "id": candidate.id,
                                              "reason": "рисунок, а не снимок"})
                    continue
                if dry_run:
                    report["added"].append({"topic": topic["id"],
                                            "id": candidate.id, "dry_run": True})
                    taken += 1
                    continue

                local = work / f"{candidate.id}.bin"
                try:
                    provider.download(candidate, local)
                except Exception as exc:  # noqa: BLE001
                    report["skipped"].append({"topic": topic["id"], "id": candidate.id,
                                              "reason": f"скачивание: {exc}"[:120]})
                    continue

                # Имя даёт содержимое: ссылка кандидата у NASA ведёт на
                # collection.json, а приходит по ней JPEG.
                suffix = sniff_suffix(local, ".jpg" if candidate.kind == "photo" else ".mp4")
                key = f"seed/{topic['id']}/{candidate.id}{suffix}"
                local = local.replace(local.with_suffix(suffix))

                # Видео из архива весит десятки мегабайт и в репозиторий не
                # едет: засев — это полка снимков, движение делает наезд.
                if suffix not in (".jpg", ".png", ".webp"):
                    report["skipped"].append({"topic": topic["id"], "id": candidate.id,
                                              "reason": f"не снимок ({suffix or '?'})"})
                    local.unlink(missing_ok=True)
                    continue
                if local.stat().st_size > MAX_BYTES:
                    report["skipped"].append({
                        "topic": topic["id"], "id": candidate.id,
                        "reason": f"{local.stat().st_size // 1024 // 1024} МБ при пределе "
                                  f"{MAX_BYTES // 1024 // 1024}"})
                    local.unlink(missing_ok=True)
                    continue

                if grade_rules:
                    try:
                        graded = local.with_name(f"{local.stem}_g{local.suffix}")
                        grade_to_palette(local, graded, **grade_rules)
                        graded.replace(local)
                    except Exception as exc:  # noqa: BLE001 — грейд не роняет засев
                        _log.warning("грейд не удался, кадр берётся как есть",
                                     extra={"id": candidate.id, "error": str(exc)[:200]})

                try:
                    info = probe(local)
                    frames = extract_frames(local, work / "frames" / candidate.id, [0.5])
                except Exception as exc:  # noqa: BLE001
                    report["skipped"].append({"topic": topic["id"], "id": candidate.id,
                                              "reason": f"битый файл: {exc}"[:120]})
                    continue

                short = min(info.width, info.height)
                ratio = (info.width / info.height) if info.height else 0.0
                if short < MIN_SHORT_SIDE or not (
                        ASPECT_RANGE[0] <= ratio <= ASPECT_RANGE[1]):
                    report["skipped"].append({
                        "topic": topic["id"], "id": candidate.id,
                        "reason": f"{info.width}×{info.height} — мелко или не тот формат"})
                    local.unlink(missing_ok=True)
                    continue

                hashes = [phash_image(f) for f in frames]
                dup = index.find_duplicate(hashes)
                if dup is not None:
                    report["skipped"].append({"topic": topic["id"], "id": candidate.id,
                                              "reason": f"дубль {dup.id}"})
                    continue

                rules = dict(palette_rules, off_share_max=off_share_max)
                verdict = palette_verdict(frames, rules)
                if not verdict["passed"]:
                    report["skipped"].append({"topic": topic["id"], "id": candidate.id,
                                              "reason": f"палитра: {verdict['reason']}"[:120]})
                    continue

                score = SEED_SCORE
                summary = str(candidate.meta.get("title", ""))
                if critic is not None:
                    verdict_v = critic.judge(frames, intent=topic["intent"],
                                             role="broll", query=topic["query"])
                    score = float(verdict_v.score)
                    summary = verdict_v.summary or summary
                    if score < min_score:
                        report["skipped"].append({
                            "topic": topic["id"], "id": candidate.id,
                            "reason": f"судья {score:.2f}: {verdict_v.reason}"[:120]})
                        local.unlink(missing_ok=True)
                        continue

                storage.put(key, local)
                index.add(AssetRecord(
                    id=candidate.id or new_id(),
                    type="photo", source=candidate.source,
                    license=candidate.license or "public domain",
                    url_origin=candidate.page_url,
                    phash=hashes[0], phashes=hashes,
                    tags=list(dict.fromkeys(list(topic["tags"]) + list(candidate.tags))),
                    vision_summary=summary,
                    score=score,
                    width=info.width or candidate.width,
                    height=info.height or candidate.height,
                    file=key, added=today(),
                    extra={"attribution": candidate.attribution,
                           "seed_topic": topic["id"]},
                ))
                report["added"].append({"topic": topic["id"], "id": candidate.id,
                                        "source": candidate.source, "key": key})
                taken += 1

        if taken < need:
            report["skipped"].append({"topic": topic["id"],
                                      "reason": f"добрано {taken} из {need}"})

    if not dry_run and report["added"]:
        index.save()
    report["index"] = index.status()
    return report
