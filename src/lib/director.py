"""Режиссёрский таймлайн из чата (docs/director/TIMELINE.md).

До этой волны ролик собирала эвристика: P7/P8 искали футаж по тегам, P11
выбирал один-два шаблона из 173 и резал остальное капами и банами. Нейросети
в GitHub Actions нет, поэтому «выбор» получался случайным и плоским.

Теперь режиссёр — нейросеть в чате. Она смотрит материал своим зрением,
выбирает приёмы по смыслу и отдаёт станку готовое решение: секцию
``director`` в сценарии. Этот модуль делает две вещи:

* ``validate`` — проверка таймлайна без сети и без рендера (P0 и
  ``tools/director_check.py``): шаблон существует, якорь есть в тексте блока,
  у футажа есть лицензия, генерации не больше потолка;
* ``apply_director`` — после сборки P11 переписывает шоты и оверлеи ровно так,
  как сказал режиссёр: скачивает футаж, режет его в план 9:16, ставит приём,
  переход и движение. Эвристика P11 остаётся запасом для окон, которые
  режиссёр не занял.

Окна привязаны к словам речи, а не к секундам: P3 режет паузы после синтеза,
и секунды из чата к рендеру уже не совпадают.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..errors import RedshiftError
from .logging import get_logger

_log = get_logger("director")

# Категории каталога → вид окна в edit-плане.
FULLSCREEN_CATEGORIES = ("text-fullscreen", "intro-hooks", "outro-cta")
OVERLAY_CATEGORIES = ("data-viz", "lower-thirds", "frames-cards", "browser-ui",
                      "outro-cta", "intro-hooks")
MOTION_CATEGORIES = ("kenburns", "parallax")
TRANSITION_CATEGORIES = ("transitions", "avatar-entry")
HERO_CATEGORY = "hero-devices"

SHOT_KINDS = ("footage", "fullscreen", "avatar", "scene")
LICENSES_OK = ("public_domain", "cc0", "cc-by", "cc-by-sa", "pexels", "pixabay",
               "magnific", "freepik", "owner", "generated-owned",
               "editorial_source_figure", "press_kit", "fair_use_news",
               "nasa", "esa", "eso", "noirlab")
DEFAULT_OVERLAY_SEC = 1.8
MIN_SHOT_SEC = 0.35
# Потолок генерации (заказчик 22.09) — дублируется в config limits.ai_footage_share_max;
# здесь только запас, если конфига нет.
AI_SHARE_MAX_DEFAULT = 0.20
# Дыра без смены картинки, после которой линт предупреждает (§1.3: 2.5 с;
# движение внутри плана тоже событие, поэтому здесь мягче).
MAX_STATIC_SEC = 4.0

_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[-'][0-9A-Za-zА-Яа-яЁё]+)*")
_VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".m4v", ".mkv")
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff")


class DirectorError(RedshiftError):
    """Таймлайн режиссёра нельзя исполнить как написан."""

    default_code = "DIRECTOR_INVALID"

    def __init__(self, message: str, **details: Any) -> None:
        details.setdefault("code", self.default_code)
        super().__init__(message, **details)


# --- общие утилиты -----------------------------------------------------------

def norm_word(text: str) -> str:
    """Слово для сравнения якоря: нижний регистр, ё→е, без ударений и знаков."""
    text = str(text or "").lower().replace("ё", "е").replace("́", "").replace("+", "")
    found = _WORD_RE.findall(text)
    return found[0] if found else ""


def text_words(text: str) -> list[str]:
    text = str(text or "").replace("́", "").replace("+", "")
    return [norm_word(w) for w in _WORD_RE.findall(text)]


def parse_anchor(at: Any) -> tuple[str, int]:
    """``"лапшу"`` → (лапшу, 1); ``"кот#2"`` → (кот, 2) — второе вхождение."""
    raw = str(at or "").strip()
    if not raw:
        return "", 1
    word, _, nth = raw.partition("#")
    try:
        n = max(1, int(nth)) if nth else 1
    except ValueError:
        n = 1
    return norm_word(word), n


def director_spec(script: Mapping[str, Any] | None) -> dict[str, Any] | None:
    spec = (script or {}).get("director")
    return spec if isinstance(spec, dict) and spec else None


def _catalog_index(catalog: Any = None) -> dict[str, dict[str, Any]]:
    """id шаблона → {category, renderer, params, duration_range}."""
    out: dict[str, dict[str, Any]] = {}
    if catalog is not None:
        for tpl in getattr(catalog, "templates", None) or []:
            tid = str(getattr(tpl, "id", "") or "")
            if tid:
                out[tid] = {"category": getattr(tpl, "category", tid.split("/")[0]),
                            "renderer": getattr(tpl, "renderer", ""),
                            "params": dict(getattr(tpl, "params", None) or {}),
                            "status": getattr(tpl, "status", None)}
        if out:
            return out
    import json
    manifest = Path(__file__).resolve().parents[2] / "templates" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for tpl in data.get("templates") or []:
        out[str(tpl["id"])] = {"category": tpl.get("category", ""),
                               "renderer": tpl.get("renderer", ""),
                               "params": dict(tpl.get("params") or {}),
                               "status": tpl.get("status")}
    return out


def _registries() -> dict[str, set[str]]:
    from .render.hyperframes import templates as T
    return {
        "transitions": set(T.TRANSITIONS),
        "motion": set(T.MOTION),
        "hero": set(T.HERO),
        "fullscreen": set(T.FULLSCREEN),
        "overlays": set(T.OVERLAYS),
        "dataviz": set(T.DATAVIZ),
    }


def _footage_kind(entry: Mapping[str, Any]) -> str:
    kind = str(entry.get("kind") or "").lower()
    if kind in ("video", "image"):
        return kind
    src = str(entry.get("src") or "").lower().split("?", 1)[0]
    return "image" if src.endswith(_IMAGE_SUFFIXES) else "video"


# --- проверка ----------------------------------------------------------------

@dataclass
class Issue:
    level: str          # error | warn
    where: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"level": self.level, "where": self.where, "message": self.message}


def _resolve_template(ref: str, catalog: Mapping[str, Mapping[str, Any]],
                      categories: Sequence[str]) -> dict[str, Any] | None:
    ref = str(ref or "").strip()
    if not ref:
        return None
    if ref in catalog:
        return {"id": ref, **catalog[ref]}
    # Короткое имя без категории: «whip-pan» → transitions/whip-pan.
    for cat in categories:
        tid = f"{cat}/{ref}"
        if tid in catalog:
            return {"id": tid, **catalog[tid]}
    return None


def validate(script: Mapping[str, Any], *, catalog: Any = None,
             ai_share_max: float = AI_SHARE_MAX_DEFAULT) -> list[Issue]:
    """Проверить таймлайн режиссёра, ничего не скачивая и не рендеря."""
    spec = director_spec(script)
    if spec is None:
        return []
    issues: list[Issue] = []
    cat = _catalog_index(catalog)
    reg = _registries()
    blocks = {str(b.get("id")): b for b in script.get("blocks") or []}
    block_order = [str(b.get("id")) for b in script.get("blocks") or []]
    footage = spec.get("footage") or {}
    if not isinstance(footage, dict):
        issues.append(Issue("error", "director.footage", "должен быть объектом id → описание"))
        footage = {}

    for fid, entry in footage.items():
        where = f"footage.{fid}"
        if not isinstance(entry, dict):
            issues.append(Issue("error", where, "описание футажа — объект"))
            continue
        if not str(entry.get("src") or "").strip():
            issues.append(Issue("error", where, "нет src (URL или путь в репо)"))
        lic = str(entry.get("license") or "").strip().lower()
        if not lic:
            issues.append(Issue("error", where, "нет license — без лицензии футаж в ролик не идёт"))
        elif not any(lic.startswith(ok) for ok in LICENSES_OK):
            issues.append(Issue("warn", where, f"лицензия «{lic}» не из известного списка — проверь права"))
        if not str(entry.get("source") or "").strip():
            issues.append(Issue("error", where, "нет source (nasa, wikimedia, magnific, pexels…)"))
        if not entry.get("ai_generated") and not str(entry.get("page_url") or "").strip():
            issues.append(Issue("warn", where, "нет page_url — источник не подтвердить в споре"))
        src = str(entry.get("src") or "")
        if src and not src.startswith(("http://", "https://")):
            if not (Path(__file__).resolve().parents[2] / src).is_file():
                issues.append(Issue("error", where, f"файл {src} не найден в репо"))

    shots = spec.get("shots") or []
    if not isinstance(shots, list) or not shots:
        issues.append(Issue("error", "director.shots", "нет ни одного шота"))
        shots = []
    seen_blocks: list[str] = []
    for i, shot in enumerate(shots):
        where = f"shots[{i}]"
        if not isinstance(shot, dict):
            issues.append(Issue("error", where, "шот — объект"))
            continue
        bid = str(shot.get("block") or "")
        if bid not in blocks:
            issues.append(Issue("error", where, f"блок «{bid}» не найден в сценарии"))
            continue
        if seen_blocks and block_order.index(bid) < block_order.index(seen_blocks[-1]):
            issues.append(Issue("error", where, "шоты идут не по порядку блоков"))
        seen_blocks.append(bid)
        word, nth = parse_anchor(shot.get("at"))
        if word:
            count = text_words(blocks[bid].get("text", "")).count(word)
            if count < nth:
                issues.append(Issue("error", where,
                                    f"якорь «{shot.get('at')}» не найден в тексте блока {bid}"))
        kinds = [k for k in SHOT_KINDS if shot.get(k)]
        if len(kinds) != 1:
            issues.append(Issue("error", where,
                                "ровно одно из: footage | fullscreen | avatar | scene"))
        if shot.get("footage") and str(shot["footage"]) not in footage:
            issues.append(Issue("error", where, f"футаж «{shot['footage']}» не описан в director.footage"))
        fs = shot.get("fullscreen")
        if fs:
            if not isinstance(fs, dict) or not str(fs.get("content") or "").strip():
                issues.append(Issue("error", where, "fullscreen: нужен content (1–4 слова)"))
            else:
                tpl = _resolve_template(fs.get("template") or "text-fullscreen/impact-01",
                                        cat, FULLSCREEN_CATEGORIES)
                if tpl is None:
                    issues.append(Issue("error", where, f"шаблон «{fs.get('template')}» не найден"))
                elif str(tpl["renderer"]) not in reg["fullscreen"] and tpl["renderer"] != "logo_brand_close":
                    issues.append(Issue("error", where,
                                        f"{tpl['id']}: рендерер {tpl['renderer']} не полноэкранный"))
                if fs.get("footage") and str(fs["footage"]) not in footage:
                    issues.append(Issue("error", where, f"фон «{fs['footage']}» не описан в director.footage"))
                if len(str(fs.get("content") or "").split()) > 5:
                    issues.append(Issue("warn", where, "полноэкранный текст длиннее 4 слов не читается"))
        tr = shot.get("transition")
        if tr:
            name = tr.get("template") if isinstance(tr, dict) else tr
            tpl = _resolve_template(str(name), cat, TRANSITION_CATEGORIES)
            if tpl is None and str(name) not in reg["transitions"]:
                issues.append(Issue("error", where, f"переход «{name}» не найден"))
        mo = shot.get("motion")
        if mo:
            name = mo.get("template") if isinstance(mo, dict) else mo
            tpl = _resolve_template(str(name), cat, MOTION_CATEGORIES)
            if tpl is None and str(name) not in reg["motion"]:
                issues.append(Issue("error", where, f"движение «{name}» не найдено"))
        hero = shot.get("hero")
        if hero:
            name = hero.get("template") if isinstance(hero, dict) else hero
            tpl = _resolve_template(str(name), cat, (HERO_CATEGORY,))
            ren = (tpl or {}).get("renderer") or str(name)
            if ren.rsplit("/", 1)[-1] not in reg["hero"]:
                issues.append(Issue("error", where, f"приём «{name}» не найден среди hero-devices"))
            elif not shot.get("avatar"):
                # hero-приёмы строились вокруг ведущего: на чистом футаже
                # многие кладут сплошную плиту и прячут кадр (проба 22.09).
                issues.append(Issue("warn", where,
                                    "hero-приём без ведущего может закрыть футаж плитой — "
                                    "слово поверх кадра ставь через fullscreen с footage"))

    for i, ovl in enumerate(spec.get("overlays") or []):
        where = f"overlays[{i}]"
        if not isinstance(ovl, dict):
            issues.append(Issue("error", where, "оверлей — объект"))
            continue
        bid = str(ovl.get("block") or "")
        if bid not in blocks:
            issues.append(Issue("error", where, f"блок «{bid}» не найден"))
            continue
        for key in ("at", "until"):
            word, nth = parse_anchor(ovl.get(key))
            if word and text_words(blocks[bid].get("text", "")).count(word) < nth:
                issues.append(Issue("error", where, f"якорь {key}=«{ovl.get(key)}» не найден в блоке {bid}"))
        if not ovl.get("template") and not ovl.get("renderer"):
            issues.append(Issue("error", where, "нужен template (id каталога) или renderer"))
            continue
        if ovl.get("template"):
            tpl = _resolve_template(str(ovl["template"]), cat, OVERLAY_CATEGORIES)
            if tpl is None:
                issues.append(Issue("error", where, f"шаблон «{ovl['template']}» не найден"))
        else:
            ren = str(ovl["renderer"])
            if not any(ren in reg[k] for k in ("overlays", "dataviz", "fullscreen")):
                issues.append(Issue("error", where, f"рендерер «{ren}» не зарегистрирован"))

    issues.extend(_density_and_share(script, spec, ai_share_max))
    return issues


def _estimate_windows(script: Mapping[str, Any], spec: Mapping[str, Any]
                      ) -> list[tuple[float, float, dict[str, Any]]]:
    """Грубая раскладка шотов по слогам текста — только для линта в чате."""
    from .schema import count_syllables
    rate = 5.4 * 1.2
    starts: dict[str, float] = {}
    word_times: dict[str, list[tuple[str, float]]] = {}
    cursor = 0.0
    for block in script.get("blocks") or []:
        bid = str(block.get("id"))
        starts[bid] = cursor
        times: list[tuple[str, float]] = []
        for raw in _WORD_RE.findall(str(block.get("text") or "")):
            times.append((norm_word(raw), cursor))
            cursor += max(1, count_syllables(raw)) / rate
        word_times[bid] = times
        cursor += 0.1 + int(block.get("silence_after_ms") or 0) / 1000.0
    total = cursor
    points: list[tuple[float, dict[str, Any]]] = []
    for shot in spec.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        bid = str(shot.get("block") or "")
        t = starts.get(bid, 0.0)
        word, nth = parse_anchor(shot.get("at"))
        if word:
            hits = [tt for w, tt in word_times.get(bid, []) if w == word]
            if len(hits) >= nth:
                t = hits[nth - 1]
        points.append((t + float(shot.get("offset") or 0.0), shot))
    if points:
        points[0] = (0.0, points[0][1])
    out = []
    for i, (t, shot) in enumerate(points):
        end = points[i + 1][0] if i + 1 < len(points) else total
        out.append((t, end, shot))
    return out


def _density_and_share(script: Mapping[str, Any], spec: Mapping[str, Any],
                       ai_share_max: float) -> list[Issue]:
    issues: list[Issue] = []
    windows = _estimate_windows(script, spec)
    if not windows:
        return issues
    total = max(windows[-1][1], 1e-6)
    footage = spec.get("footage") or {}
    ai_sec = 0.0
    for start, end, shot in windows:
        fid = shot.get("footage") or (shot.get("fullscreen") or {}).get("footage")
        if fid and (footage.get(str(fid)) or {}).get("ai_generated"):
            ai_sec += max(0.0, end - start)
        if end - start > MAX_STATIC_SEC and not shot.get("motion") and not shot.get("hero"):
            issues.append(Issue("warn", f"block {shot.get('block')}",
                                f"окно ~{end - start:.1f} с без смены картинки и без движения"))
        if end - start < MIN_SHOT_SEC:
            issues.append(Issue("warn", f"block {shot.get('block')}",
                                f"окно ~{end - start:.2f} с — мелькание, склеится с соседом"))
    share = ai_sec / total
    if share > ai_share_max + 1e-6:
        issues.append(Issue("error", "director", f"генерация ~{share:.0%} хронометража — потолок {ai_share_max:.0%}"))
    kinds = {k for _, _, s in windows for k in ("transition", "motion", "hero") if s.get(k)}
    uniq = {str(s.get("transition") or s.get("motion") or s.get("hero") or "")
            for _, _, s in windows} | {str(o.get("template") or o.get("renderer"))
                                      for o in spec.get("overlays") or [] if isinstance(o, dict)}
    uniq.discard("")
    if len(uniq) < max(3, int(total / 6)):
        issues.append(Issue("warn", "director",
                            f"всего {len(uniq)} разных приёмов на ~{total:.0f} с — ролик будет плоским"))
    if "transition" not in kinds:
        issues.append(Issue("warn", "director", "ни одного перехода-VFX"))
    return issues


# --- исполнение в P11 --------------------------------------------------------

def _word_rows(words_doc: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for w in words_doc.get("words") or []:
        rows.setdefault(str(w.get("block_id") or ""), []).append(w)
    return rows


def _word_forms(w: Mapping[str, Any]) -> set[str]:
    forms = {norm_word(w.get("display") or "")}
    for sp in w.get("spoken") or []:
        forms.add(norm_word(sp))
    forms.discard("")
    return forms


def anchor_time(rows: Mapping[str, list[dict[str, Any]]], block_id: str,
                at: Any = None) -> float | None:
    """Начало слова-якоря в финальном таймкоде; без якоря — начало блока."""
    block_words = rows.get(str(block_id)) or []
    if not block_words:
        return None
    word, nth = parse_anchor(at)
    if not word:
        return float(block_words[0]["start"])
    hits = [w for w in block_words if word in _word_forms(w)]
    if len(hits) < nth:
        # Субтитр мог показать «100» вместо «сто»: ищем по началу слова.
        hits = [w for w in block_words
                if any(f.startswith(word[:4]) for f in _word_forms(w))]
    if len(hits) < nth:
        raise DirectorError(f"якорь «{at}» не найден в речи блока {block_id}",
                            block_id=block_id, at=str(at))
    return float(hits[nth - 1]["start"])


def _cache_dir(ctx) -> Path:
    root = Path(getattr(ctx.cfg, "repo_root", ".")) / ".redshift_cache" / "director"
    root.mkdir(parents=True, exist_ok=True)
    return root


def fetch_footage(ctx, fid: str, entry: Mapping[str, Any]) -> Path:
    """Файл футажа локально: путь в репо или скачанный по URL (кэш по URL)."""
    src = str(entry.get("src") or "").strip()
    repo_root = Path(getattr(ctx.cfg, "repo_root", "."))
    if not src.startswith(("http://", "https://")):
        path = (repo_root / src).resolve()
        if not path.is_file():
            raise DirectorError(f"футаж {fid}: файл {src} не найден", footage=fid)
        return path
    suffix = Path(src.split("?", 1)[0]).suffix.lower()
    if suffix not in _VIDEO_SUFFIXES + _IMAGE_SUFFIXES:
        suffix = ".jpg" if _footage_kind(entry) == "image" else ".mp4"
    digest = hashlib.sha1(src.encode("utf-8")).hexdigest()[:12]
    dst = _cache_dir(ctx) / f"{re.sub(r'[^A-Za-z0-9_-]+', '_', fid)}_{digest}{suffix}"
    if dst.is_file() and dst.stat().st_size > 0:
        return dst
    if str(ctx.cfg.get("providers.mode", "auto")).lower() == "mock":
        return _mock_footage(ctx, fid, entry, dst)
    import requests
    headers = {"User-Agent": "REDSHIFT-director/1.0 (+https://github.com/darkuseone/redshift-shorts)"}
    last: Exception | None = None
    for attempt in range(3):
        try:
            with requests.get(src, headers=headers, timeout=60, stream=True) as resp:
                resp.raise_for_status()
                tmp = dst.with_suffix(dst.suffix + ".part")
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_content(1 << 16):
                        fh.write(chunk)
                tmp.replace(dst)
            _log.info("футаж режиссёра скачан", extra={"footage": fid, "bytes": dst.stat().st_size})
            return dst
        except Exception as exc:  # noqa: BLE001 — сеть, повтор
            last = exc
    raise DirectorError(f"футаж {fid} не скачался: {last}", footage=fid, src=src)


def _mock_footage(ctx, fid: str, entry: Mapping[str, Any], dst: Path) -> Path:
    """Mock-прогон без сети: синтетический кадр вместо скачивания."""
    from .ffmpeg import run as run_ffmpeg
    colour = "0x" + hashlib.sha1(fid.encode("utf-8")).hexdigest()[:6]
    if dst.suffix in _IMAGE_SUFFIXES:
        run_ffmpeg(["-y", "-f", "lavfi", "-i", f"color=c={colour}:s=1280x720",
                    "-frames:v", "1", str(dst)], what=f"mock footage {fid}")
    else:
        run_ffmpeg(["-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=6",
                    "-f", "lavfi", "-i", f"color=c={colour}:s=1280x720:r=30:d=6",
                    "-filter_complex", "[0][1]blend=all_mode=overlay",
                    "-t", "6", "-pix_fmt", "yuv420p", str(dst)], what=f"mock footage {fid}")
    return dst


def _transition_spec(value: Any, cat: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    if not value:
        return None
    if isinstance(value, dict):
        name = str(value.get("template") or value.get("renderer") or "")
        duration = value.get("duration")
        params = dict(value.get("params") or {})
    else:
        name, duration, params = str(value), None, {}
    tpl = _resolve_template(name, cat, TRANSITION_CATEGORIES)
    renderer = str((tpl or {}).get("renderer") or name)
    if renderer == "cut":
        return None
    merged = {**dict((tpl or {}).get("params") or {}), **params}
    spec = {"renderer": renderer, "template": (tpl or {}).get("id", name),
            "duration": float(duration or merged.pop("duration", 0) or 0.32),
            "params": merged}
    return spec


def _motion_spec(value: Any, cat: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    if not value:
        return None
    if isinstance(value, dict):
        name = str(value.get("template") or value.get("renderer") or "")
        params = dict(value.get("params") or {})
    else:
        name, params = str(value), {}
    tpl = _resolve_template(name, cat, MOTION_CATEGORIES)
    renderer = str((tpl or {}).get("renderer") or name)
    spec = {**dict((tpl or {}).get("params") or {}), **params,
            "renderer": renderer, "template": (tpl or {}).get("id", name)}
    return spec


def _overlay_entry(ovl: Mapping[str, Any], cat: Mapping[str, Mapping[str, Any]],
                   start: float, end: float) -> dict[str, Any]:
    params = dict(ovl.get("params") or {})
    if ovl.get("template"):
        tpl = _resolve_template(str(ovl["template"]), cat, OVERLAY_CATEGORIES) or {}
        tid = str(tpl.get("id") or ovl["template"])
        renderer = str(tpl.get("renderer") or "")
        category = str(tpl.get("category") or tid.split("/")[0])
        params = {**dict(tpl.get("params") or {}), **params}
    else:
        tid, renderer, category = "", str(ovl.get("renderer") or ""), ""
    if category == "data-viz" or tid.startswith("data-viz/"):
        kind = "dataviz"
    elif renderer == "plaque":
        kind = "plaque"
    elif category == "outro-cta" or renderer in ("logo_brand_close", "cta_button"):
        kind = "cta"
    elif renderer == "source_card":
        kind = "source_card"
    elif category == "lower-thirds":
        kind = "lower_third"
    else:
        kind = renderer or "plaque"
    if kind == "plaque" and "text" not in params and ovl.get("content"):
        params["text"] = str(ovl["content"])
    return {"type": kind, "start": round(start, 3), "end": round(end, 3),
            "template": tid or renderer, "renderer": renderer, "params": params,
            "director": True, "why": "режиссёр: " + str(ovl.get("why") or tid or renderer)}


def apply_director(ctx, edit_plan: dict[str, Any], script: Mapping[str, Any],
                   words_doc: Mapping[str, Any], catalog: Any = None) -> dict[str, Any]:
    """Переписать edit-план по таймлайну режиссёра. Без секции — план как есть."""
    spec = director_spec(script)
    if spec is None:
        return edit_plan
    errors = [i for i in validate(script, catalog=catalog,
                                  ai_share_max=float(ctx.cfg.get("limits.ai_footage_share_max",
                                                                 AI_SHARE_MAX_DEFAULT)))
              if i.level == "error" and i.where != "director"]
    if errors:
        raise DirectorError("таймлайн режиссёра с ошибками: "
                            + "; ".join(f"{e.where}: {e.message}" for e in errors[:6]),
                            errors=[e.to_dict() for e in errors])

    from ..p11_assemble import assemble as A
    from .render.shots import ShotSpec, choose_fit, detect_focus, prepare_shot
    from .ffmpeg import probe

    cat = _catalog_index(catalog)
    rows = _word_rows(words_doc)
    duration = float(edit_plan["duration_sec"])
    blocks = {str(b.get("id")): b for b in script.get("blocks") or []}
    footage = spec.get("footage") or {}
    width, height = ctx.cfg.resolution
    fps = ctx.cfg.fps

    # 1. Окна шотов по якорям речи.
    points: list[tuple[float, dict[str, Any]]] = []
    for shot in spec.get("shots") or []:
        t = anchor_time(rows, shot["block"], shot.get("at"))
        if t is None:
            raise DirectorError(f"в речи нет слов блока {shot['block']}", block_id=shot["block"])
        t += float(shot.get("offset") or 0.0)
        points.append((max(0.0, min(t, duration)), shot))
    points.sort(key=lambda p: p[0])
    if points:
        points[0] = (0.0, points[0][1])
    windows: list[tuple[float, float, dict[str, Any]]] = []
    for i, (t, shot) in enumerate(points):
        end = points[i + 1][0] if i + 1 < len(points) else duration
        if end - t >= 0.05:
            windows.append((t, end, shot))

    # 2. Окна ведущего: исходные шоты аватара остаются как собрал P11.
    original = list(edit_plan.get("shots") or [])
    avatar_kinds = ("avatar", "split")
    kept: list[dict[str, Any]] = []
    for start, end, shot in windows:
        if shot.get("avatar"):
            kept += [s for s in original if s.get("kind") in avatar_kinds
                     and float(s["start"]) < end and float(s["end"]) > start]
    kept = list({id(s): s for s in kept}.values())

    def _free_spans(start: float, end: float) -> list[tuple[float, float]]:
        spans = [(start, end)]
        for s in kept:
            ks, ke = float(s["start"]), float(s["end"])
            nxt = []
            for a, b in spans:
                if ke <= a or ks >= b:
                    nxt.append((a, b))
                    continue
                if ks > a:
                    nxt.append((a, ks))
                if ke < b:
                    nxt.append((ke, b))
            spans = nxt
        return [(a, b) for a, b in spans if b - a >= MIN_SHOT_SEC]

    # 3. Футаж: скачать один раз, резать под каждое окно.
    local: dict[str, Path] = {}

    def _source(fid: str) -> Path:
        if fid not in local:
            local[fid] = fetch_footage(ctx, fid, footage[fid])
        return local[fid]

    pillarbox_used = 0

    def _prepared(fid: str, dur: float, *, in_sec: float, fit_hint: str | None) -> dict[str, Any]:
        nonlocal pillarbox_used
        src = _source(fid)
        info = probe(src)
        fit = fit_hint or choose_fit(info, pillarbox_used=pillarbox_used,
                                     pillarbox_limit=int(ctx.cfg.get("limits.pillarbox_per_video", 2)))
        if fit == "pillarbox":
            pillarbox_used += 1
        fx, fy = (0.5, 0.5)
        entry = footage[fid]
        if entry.get("focus"):
            fx, fy = (float(v) for v in entry["focus"])
        elif fit == "crop" and info.width and info.height and info.width > info.height * 1.05:
            fx, fy = detect_focus(src, work_dir=ctx.wpath("shots", "_focus", ".k").parent)
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", fid)
        dst = ctx.wpath("shots", f"dir_{safe}_{int(in_sec * 1000)}_{int(dur * 1000)}_{fit}.mp4")
        src_len = float(getattr(info, "duration_sec", 0) or 0)
        loop = bool(src_len and src_len - in_sec < dur)
        return prepare_shot(ShotSpec(src=src, dst=dst, duration_sec=dur, width=width,
                                     height=height, fps=fps, fit=fit, focus_x=fx,
                                     focus_y=fy, start_sec=in_sec, loop=loop))

    def _asset_fields(fid: str | None) -> dict[str, Any]:
        if not fid:
            return {"asset_id": None}
        e = footage[fid]
        return {"asset_id": f"dir_{fid}", "source": e.get("source", ""),
                "license": e.get("license", ""), "attribution": e.get("attribution", ""),
                "page_url": e.get("page_url", ""), "ai_generated": bool(e.get("ai_generated")),
                "credit": str(e.get("credit") or "")}

    new_shots: list[dict[str, Any]] = []
    used_templates: list[str] = []
    index = 100
    offsets: dict[str, float] = {}
    for start, end, shot in windows:
        if shot.get("avatar"):
            continue
        for a, b in _free_spans(start, end):
            dur = round(b - a, 3)
            block = blocks.get(str(shot["block"]), {})
            entry: dict[str, Any] = {
                "index": index, "start": round(a, 3), "end": round(b, 3), "duration": dur,
                "block_id": shot["block"], "role": block.get("role", ""), "mode": "C",
                "director": True, "why": "режиссёр: " + str(shot.get("why") or ""),
            }
            index += 1
            tr = _transition_spec(shot.get("transition"), cat)
            if tr and new_shots:
                entry["transition"] = tr
                used_templates.append(tr["template"])
            if shot.get("footage"):
                fid = str(shot["footage"])
                base = float(shot.get("in_sec", footage[fid].get("in_sec", 0.0)) or 0.0)
                # Повтор того же футажа продолжает клип, а не крутит начало.
                in_sec = base + (offsets.get(fid, 0.0) if "in_sec" not in shot else 0.0)
                if _footage_kind(footage[fid]) == "video":
                    offsets[fid] = offsets.get(fid, 0.0) + dur
                prep = _prepared(fid, dur, in_sec=in_sec, fit_hint=shot.get("fit"))
                entry.update({"kind": "footage", "file": prep["dst"], "fit": prep.get("fit"),
                              **_asset_fields(fid)})
                mo = _motion_spec(shot.get("motion") or ("kenburns/zoom-in-center"
                                  if _footage_kind(footage[fid]) == "image" else None), cat)
                if mo:
                    entry["motion"] = mo
                    used_templates.append(mo["template"])
            elif shot.get("fullscreen"):
                fs = dict(shot["fullscreen"])
                tpl_ref = _resolve_template(fs.get("template") or "text-fullscreen/impact-01",
                                            cat, FULLSCREEN_CATEGORIES) or {}
                tpl_obj = (catalog.by_id(tpl_ref["id"])
                           if catalog is not None and hasattr(catalog, "by_id") else None)
                content = str(fs.get("content") or "")
                params = A._fullscreen_params(tpl_obj or _Tpl(tpl_ref), content, block,
                                              {"blocks": list(blocks.values())})
                params.update(dict(fs.get("params") or {}))
                bg = None
                bg_fields: dict[str, Any] = {"asset_id": None}
                if fs.get("footage"):
                    bg = _prepared(str(fs["footage"]), dur, in_sec=float(
                        footage[str(fs["footage"])].get("in_sec", 0.0) or 0.0), fit_hint=None)["dst"]
                    bg_fields = _asset_fields(str(fs["footage"]))
                entry.update({
                    "kind": "fullscreen_text", "content": content,
                    "template": tpl_ref.get("id"), "renderer": tpl_ref.get("renderer"),
                    "params": params, "invert": True, "carries_line": True,
                    "accent_word": fs.get("accent_word") or A._fullscreen_accent(content, block),
                    "accent_family": A.accent_family(block), "file": bg,
                    "hook": block.get("role") == "hook", **bg_fields,
                })
                used_templates.append(str(tpl_ref.get("id")))
            else:
                entry.update({"kind": "footage", "file": None, "asset_id": None,
                              "gap_reason": "режиссёр: сцена фона ролика"})
            hero = shot.get("hero")
            if hero:
                hero = hero if isinstance(hero, dict) else {"template": hero}
                tpl = _resolve_template(str(hero.get("template")), cat, (HERO_CATEGORY,)) or {}
                hparams = {**dict(tpl.get("params") or {}), **dict(hero.get("params") or {})}
                hentry: dict[str, Any] = {"template": tpl.get("id", hero.get("template")),
                                          "renderer": tpl.get("renderer") or hero.get("template"),
                                          "params": hparams}
                if hero.get("footage"):
                    hentry["file"] = str(_source(str(hero["footage"])))
                if hero.get("duration"):
                    hentry["duration"] = float(hero["duration"])
                entry["hero"] = hentry
                used_templates.append(str(hentry["template"]))
            new_shots.append(entry)

    shots = sorted(kept + new_shots, key=lambda s: float(s["start"]))

    # 4. Оверлеи режиссёра поверх; из P11 остаётся только финальная кнопка,
    # если режиссёр свою не поставил.
    overlays: list[dict[str, Any]] = []
    for ovl in spec.get("overlays") or []:
        start = anchor_time(rows, ovl["block"], ovl.get("at")) or 0.0
        start += float(ovl.get("offset") or 0.0)
        if ovl.get("until"):
            end = anchor_time(rows, ovl["block"], ovl.get("until")) or start
            end = max(end, start + 0.6)
        else:
            end = start + float(ovl.get("dur") or DEFAULT_OVERLAY_SEC)
        entry = _overlay_entry(ovl, cat, max(0.0, start), min(end, duration))
        overlays.append(entry)
        used_templates.append(str(entry["template"]))
    if not any(o["type"] == "cta" for o in overlays) and spec.get("keep_auto_cta", True):
        overlays += [o for o in edit_plan.get("overlays") or [] if o.get("type") == "cta"]
    overlays.sort(key=lambda o: float(o["start"]))

    words = list(words_doc.get("words") or [])
    brandbook = ctx.cfg.brandbook
    edit_plan = dict(edit_plan)
    edit_plan["shots"] = shots
    edit_plan["overlays"] = overlays
    edit_plan["subtitles"] = A.build_subtitles(shots, overlays, words,
                                               list(blocks.values()), brandbook)
    edit_plan["templates_used"] = list(dict.fromkeys(
        [t for t in used_templates if t] + [t for t in edit_plan.get("templates_used") or []
                                            if t.startswith("outro-cta/")]))
    edit_plan["director"] = {
        "shots": len(new_shots), "avatar_windows": len(kept),
        "overlays": len(overlays), "footage": sorted(local),
        "templates": len(set(used_templates)),
    }
    _log.info("таймлайн режиссёра применён", extra=edit_plan["director"])
    return edit_plan


class _Tpl:
    """Шаблон из индекса каталога в форме, которую ждёт ``_fullscreen_params``."""

    def __init__(self, ref: Mapping[str, Any]):
        self.id = ref.get("id", "")
        self.renderer = ref.get("renderer", "")
        self.params = dict(ref.get("params") or {})
        self.needs: tuple[str, ...] = ()


def summarize(issues: Iterable[Issue]) -> dict[str, Any]:
    items = [i.to_dict() for i in issues]
    return {"errors": sum(1 for i in items if i["level"] == "error"),
            "warnings": sum(1 for i in items if i["level"] == "warn"),
            "issues": items}
