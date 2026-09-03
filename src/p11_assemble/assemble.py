"""P11: всё предыдущее → ``edit_plan_A.json`` и ``edit_plan_B.json``.

Edit-план — самодостаточный документ: §9.1 требует, чтобы по нему можно было
**пересобрать ролик один в один без обращений к внешним API**. Поэтому в нём
лежат локальные пути подготовленных планов, все параметры анимации, тексты
оверлеев и пословные тайминги — ничего не догружается на рендере.

Версии A и B (§4.5) собираются из **одного набора материалов** и различаются
монтажными решениями: порядком вставок внутри блока, шаблонами Ken Burns и
переходов, оформлением полноэкранного текста, наличием мема. §15.12.2 требует
различия минимум в 3 шаблонных позициях, и это проверяется, а не декларируется.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ..errors import RedshiftError
from ..lib.ffmpeg import probe
from ..lib.logging import get_logger
from ..lib.providers.generation import build_generation_provider
from ..lib.render.layers import Ctx, text_behind_head
from ..lib.render.matting import assess_matte, plan_vfx_backgrounds, try_local_matting
from ..lib.render.shots import (
    ShotSpec, choose_fit, detect_focus, prepare_avatar_shot, prepare_shot,
    prepare_split_shot,
)
from ..lib.brand_icons import load_library as load_brand_icons
from ..lib.render.hyperframes.captions import pick_caption_style
from ..lib.render.hyperframes.spm_shapes import SPM_SHAPES
from ..lib.render.hyperframes.usm_shapes import USM_SHAPES
from ..lib.templates import TemplateCatalog, Template, diff_count

_log = get_logger("p11")

AVATAR_KINDS = ("avatar", "split")


# --- приёмы вокруг ведущего (§5.3, референсы заказчика) ------------------------

# Надпись над крупным словом заголовка. Роль блока сюда подставлять нельзя: она
# служебная и латиницей — «EVIDENCE» посреди русского ролика читается как
# отладочный вывод. Роль без подписи остаётся без кикера, и приём собирается
# из одного слова.
_HERO_KICKERS = {
    "hook": "ВОПРОС",
    "setup": "С ЧЕГО НАЧАЛОСЬ",
    "evidence": "ЧТО ИЗВЕСТНО",
    "develop": "ЧТО ДАЛЬШЕ",
    "twist": "НО ЕСТЬ НЮАНС",
    "cta": "ОСТАЁТСЯ ВОПРОС",
}

def _alpha_slots(avatar_meta: dict[str, Any]) -> set[int]:
    """Слоты, где аватар лёг с прозрачным фоном."""
    return {int(idx) for seg in avatar_meta.get("segments", [])
            if seg.get("has_alpha")
            for idx in seg.get("slot_indices", [])}


def _face_centres(avatar_meta: dict[str, Any]) -> dict[int, tuple[int, int]]:
    """Слот шота → центр лица в кадре.

    Круглая рамка обязана сесть на голову, а не туда, где она в среднем бывает:
    догадка «четверть высоты кадра» промахивалась на сотню пикселей. P6 уже
    измерил лицо для сдвига субтитров — берём оттуда же.
    """
    out: dict[int, tuple[int, int]] = {}
    for seg in avatar_meta.get("segments", []):
        box = seg.get("face_bbox")
        if not box or len(box) != 4:
            continue
        centre = ((int(box[0]) + int(box[2])) // 2, (int(box[1]) + int(box[3])) // 2)
        for slot in seg.get("slot_indices", []):
            out[int(slot)] = centre
    return out


def _plate_source(slot: dict[str, Any], slots: list[dict[str, Any]],
                  prepared: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    """Кадр для панели за спиной — ближайший футаж того же блока.

    Панель показывает картинку по теме блока, а не произвольный кадр: это тот
    же материал, который блок и без того выносит на весь экран, просто
    появившийся за спиной раньше. Своего материала у приёма нет — заводить под
    него отдельную закупку значит удорожать ролик ради одного слоя.
    """
    index = int(slot["index"])
    same_block = [s for s in slots
                  if s["block_id"] == slot["block_id"]
                  and s["kind"] in ("footage", "meme")
                  and int(s["index"]) in prepared]
    if not same_block:
        return None
    nearest = min(same_block, key=lambda s: (abs(int(s["index"]) - index), int(s["index"])))
    prep = prepared[int(nearest["index"])]
    return {"file": prep["dst"], "duration_sec": float(prep.get("duration_sec") or 0.0)}


# Что приёму нужно на входе. Без этого он рисует пустоту поверх ведущего, и
# отсеивать его надо **до** выбора: ``TemplateCatalog.pick`` при пустом наборе
# кандидатов возвращается ко всей категории, и неподходящий приём всё равно
# попал бы в кадр. Список ведётся здесь, а не тегами в каталоге: тег описывает,
# на что приём похож, а это — чем его кормить.
_HERO_NEEDS: dict[str, tuple[str, ...]] = {
    "hero-burst": (),
    "hero-plate": ("plate",),
    "hero-headline": ("word",),
    "hero-split": ("word",),
    "hero-knockout": ("word",),
    "hero-text-column": ("lines",),
    "hero-bubble-card": ("lines",),
    "hero-brand-pill": ("brand",),
    "hero-card-stack": ("title", "plate"),
    "hero-phone-mock": ("lines",),
    "hero-type-slab": ("lines",),
    "hero-plate-pop": ("plate",),
}


def _wrap_lines(text: str, *, width: int = 13, limit: int = 4) -> list[str]:
    """Реплику блока — в короткие строки для колонки и карточки.

    Перенос по словам и с потолком по длине: колонка занимает 46 % ширины
    кадра, и на кегле 66 в неё входит около 13 знаков. Проверено кадром — при
    20 знаках каждая строка ломалась пополам, и колонка превращалась в кашу.
    Перенос посреди слова читается как брак вёрстки, поэтому только по словам.
    """
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
            if len(lines) == limit:
                break
        else:
            current = candidate
    if current and len(lines) < limit:
        lines.append(current)
    return lines


def _hero_content(block: dict[str, Any], slot: dict[str, Any], icons,
                  face: tuple[int, int] | None = None) -> dict[str, Any]:
    """Собрать всё, чем можно накормить приёмы, из одного блока сценария."""
    text = str(block.get("text") or "").strip()
    word = str(block.get("emphasis_word") or "").strip()
    lines = _wrap_lines(text)
    accent = [i for i, line in enumerate(lines)
              if word and word.lower() in line.lower()]

    brand = None
    if icons is not None:
        for candidate in sorted({w.strip(".,!?;:»«\"'()")
                                 for w in text.split() if len(w) > 2},
                                key=lambda w: (-len(w), w)):
            found = icons.find(candidate)
            if found:
                brand = {"label": candidate, "icon": found[0].path}
                break

    return {
        "word": word,
        "lines": lines,
        "accent_lines": accent,
        # Заголовок карточки — начало реплики, а не акцентное слово: одно слово
        # крупно уже занято выбивкой и заголовком над головой.
        "title": " ".join(text.split()[:3]).strip(".,!?;:").upper(),
        "brand": brand,
        "face": face,
    }


def _hero_device(catalog: TemplateCatalog, *, slot: dict[str, Any],
                 content: dict[str, Any], has_alpha: bool,
                 plate_src: dict[str, Any] | None,
                 recent_videos: list[str], exclude: list[str],
                 seed: int) -> dict[str, Any] | None:
    """Выбрать приём вокруг ведущего под конкретный кадр.

    Приём отбрасывается, если кадр не может его показать: без альфы всё, что
    рисуется под аватаром, окажется за непрозрачным видео, а остальным нужен
    материал из ``_HERO_NEEDS``.
    """
    available = dict(content)
    available["plate"] = plate_src

    blocked = list(exclude)
    for template in catalog.by_category("hero-devices"):
        if "alpha" in set(template.tags) and not has_alpha:
            blocked.append(template.id)
            continue
        needs = _HERO_NEEDS.get(template.renderer, ())
        if any(not available.get(key) for key in needs):
            blocked.append(template.id)

    if not [t for t in catalog.by_category("hero-devices") if t.id not in blocked]:
        return None

    template = catalog.pick("hero-devices", duration=float(slot["duration"]),
                            recent_videos=recent_videos, exclude=blocked,
                            seed=seed + int(slot["index"]) * 7)
    renderer = template.renderer
    params: dict[str, Any] = {**template.params}

    if "word" in _HERO_NEEDS.get(renderer, ()):
        params["word"] = str(content["word"]).upper()
    if renderer == "hero-headline":
        params["kicker"] = _HERO_KICKERS.get(str(slot.get("role") or ""), "")
    if "lines" in _HERO_NEEDS.get(renderer, ()):
        upper = renderer in ("hero-text-column", "hero-type-slab")
        params["lines"] = [l.upper() if upper else l for l in content["lines"]]
        params["accent_lines"] = content["accent_lines"]
    if content.get("face"):
        # Круг садится на лицо, выбивка — тоже: её буквы видны только там, где
        # за ними светлее заливки.
        if renderer == "hero-bubble-card":
            params["face_cx"], params["face_cy"] = content["face"]
        if renderer == "hero-knockout":
            params["face_cy"] = content["face"][1]
    if renderer == "hero-brand-pill":
        params.update(content["brand"])
    if renderer == "hero-card-stack":
        params["title"] = content["title"]
    if renderer == "hero-phone-mock":
        params["app"] = str(slot.get("screen_template") or "ChatGPT")

    entry: dict[str, Any] = {
        "template": template.id, "renderer": renderer, "params": params,
        "file": None, "duration": None,
        # Приём, который выкладывает реплику строками, сам и есть субтитр этого
        # кадра. Пословное слово поверх той же фразы — дубль, и оно вдобавок
        # ложится прямо на карточку: проверено кадром.
        "carries_line": "lines" in _HERO_NEEDS.get(renderer, ()),
    }
    if plate_src and renderer in ("hero-plate", "hero-card-stack", "hero-plate-pop"):
        # Приём со своим кадром живёт по его длине: материал короче аватар-плана,
        # и растянутая панель досидела бы кадр пустой.
        entry["file"] = plate_src["file"]
        entry["duration"] = round(min(float(slot["duration"]),
                                      plate_src["duration_sec"]), 3)
    return entry


def _variant_seed(video_id: str, variant: str) -> int:
    return int(hashlib.sha256(f"{video_id}|{variant}".encode()).hexdigest()[:8], 16)


def _asset_for_slot(slot: dict[str, Any], accepted: dict[str, Any],
                    generated: dict[str, Any]) -> dict[str, Any] | None:
    key = str(slot["index"])
    return accepted.get(key) or generated.get(key)


def _rotate_assets(slots: list[dict[str, Any]], assets: dict[int, dict[str, Any]],
                   shift: int) -> dict[int, dict[str, Any]]:
    """Порядок вставок внутри блока — законное отличие версий (§4.5).

    Материал остаётся тот же, меняется только то, какой кадр в каком месте
    блока стоит. Это ровно «различаются монтажные решения, не материал».
    """
    if shift == 0:
        return dict(assets)
    out = dict(assets)
    by_block: dict[str, list[int]] = {}
    for slot in slots:
        if slot["index"] in assets:
            by_block.setdefault(slot["block_id"], []).append(slot["index"])
    for indices in by_block.values():
        if len(indices) < 2:
            continue
        values = [assets[i] for i in indices]
        offset = shift % len(values)
        rotated = values[offset:] + values[:offset]
        for index, value in zip(indices, rotated):
            out[index] = value
    return out


def _segment_for_slot(slot: dict[str, Any], segments: list[dict[str, Any]]
                      ) -> dict[str, Any] | None:
    """Аватар-сегмент, покрывающий слот (сегменты слиты из смежных слотов в P6)."""
    for segment in segments:
        if slot["index"] in segment.get("slot_indices", []):
            return segment
    for segment in segments:
        if float(segment["start"]) - 1e-3 <= float(slot["start"]) < float(segment["end"]):
            return segment
    return None


def _prepare_shots(ctx, slots: list[dict[str, Any]], assets: dict[int, dict[str, Any]],
                   pillarbox_limit: int,
                   avatar_segments: list[dict[str, Any]] | None = None,
                   matte_reports: dict[int, Any] | None = None,
                   behind_layers: dict[str, Path] | None = None,
                   vfx_clips: dict[int, Path] | None = None,
                   ) -> dict[int, dict[str, Any]]:
    """Нормализовать исходники в планы; одинаковые (файл, длительность) — один раз."""
    cache: dict[tuple, dict[str, Any]] = {}
    prepared: dict[int, dict[str, Any]] = {}
    pillarbox_used = 0
    width, height = ctx.cfg.resolution
    fps = ctx.cfg.fps
    segments = avatar_segments or []
    matte_reports = matte_reports or {}
    behind_layers = behind_layers or {}
    vfx_clips = vfx_clips or {}

    for slot in slots:
        # --- аватар: источник — клип сегмента, смещённый на позицию слота ----
        if slot["kind"] in AVATAR_KINDS:
            segment = _segment_for_slot(slot, segments)
            segment_file = Path(str((segment or {}).get("file", "")).strip() or "/nonexistent")
            if segment is None or not segment_file.is_file():
                # Ролик без аватара — это брак, а не «мало материала»: QC-2 и QC-11
                # всё равно завалят его через четыре минуты рендера. Падаем здесь,
                # где ещё видно, какого именно клипа не хватает.
                raise RedshiftError(
                    f"нет клипа аватара для слота {slot['index']} "
                    f"({slot['start']:.2f}–{slot['end']:.2f} сек, блок {slot['block_id']}): "
                    f"перезапустите с --from P6",
                    code="AVATAR_CLIP_MISSING", slot=slot["index"],
                    block_id=slot["block_id"],
                    expected_file=str(segment_file) if segment else None)
            offset = max(0.0, float(slot["start"]) - float(segment["start"]))
            duration = round(float(slot["duration"]), 3)
            avatar_src = Path(segment["file"])

            if slot["kind"] == "split":
                # §3.5 режим B: сверху доказательный материал, снизу аватар.
                asset = assets.get(slot["index"])
                top_path = str((asset or {}).get("local_file") or "").strip()
                top_src = Path(top_path) if top_path else None
                if top_src is None or not top_src.is_file():
                    key = (asset or {}).get("storage_key")
                    if key and ctx.storage.exists(key):
                        top_src = ctx.wpath("broll", "raw", Path(key).name)
                        ctx.storage.get(key, top_src)
                if top_src is None or not top_src.is_file():
                    ctx.warn(f"для сплита {slot['index']} нет верхней половины",
                             slot=slot["index"])
                    continue
                dst = ctx.wpath("shots", f"split_{slot['index']:02d}_{int(duration * 1000)}.mp4")
                prepared[slot["index"]] = prepare_split_shot(
                    top_src=top_src, bottom_src=avatar_src, dst=dst,
                    duration_sec=duration, width=width, height=height, fps=fps,
                    bottom_start_sec=offset,
                    bottom_has_alpha=bool(segment.get("has_alpha")),
                    bg_colors=(str(ctx.cfg.color("bg_light")).lstrip("#"),
                               str(ctx.cfg.color("bg_pure")).lstrip("#")),
                    divider_color="0x" + str(ctx.cfg.color("accent")).lstrip("#"))
                prepared[slot["index"]]["avatar_offset_sec"] = round(offset, 3)
                prepared[slot["index"]]["asset_id"] = (asset or {}).get("asset_id")
                continue

            dst = ctx.wpath("shots", f"avatar_{slot['index']:02d}_{int(duration * 1000)}.mp4")
            matte = matte_reports.get(int(segment["index"]))
            if matte is not None and matte.usable:
                # §7.7: есть годная маска — собираем фон + текст за головой + аватар.
                behind = behind_layers.get(slot["block_id"]) if slot["mode"] == "A" else None
                result = prepare_avatar_shot(
                    avatar_src=avatar_src, dst=dst, duration_sec=duration,
                    width=width, height=height, fps=fps, start_sec=offset,
                    # Фон под аватаром светлый и спокойный: заливка акцентом
                    # съела бы весь лимит §3.3.1 (акцент ≤10–12 % кадра).
                    bg_colors=(str(ctx.cfg.color("bg_light")).lstrip("#"),
                               str(ctx.cfg.color("bg_pure")).lstrip("#")),
                    behind_layer=behind,
                    vfx_src=vfx_clips.get(slot["index"]))
            else:
                result = prepare_shot(ShotSpec(src=avatar_src, dst=dst, duration_sec=duration,
                                               width=width, height=height, fps=fps,
                                               fit="crop", focus_x=0.5, focus_y=0.5,
                                               start_sec=offset))
            result["avatar_offset_sec"] = round(offset, 3)
            result["avatar_segment"] = segment["index"]
            result["matte"] = matte.to_dict() if matte else None
            prepared[slot["index"]] = result
            continue

        asset = assets.get(slot["index"])
        if asset is None:
            continue
        # Материал из локальной базы приходит без local_file — только с ключом
        # storage. Пустую строку в Path() класть нельзя: Path("") — это Path("."),
        # он существует, и дальше ffmpeg получает на вход каталог.
        local_file = str(asset.get("local_file") or "").strip()
        src = Path(local_file) if local_file else None
        if src is None or not src.is_file():
            key = asset.get("storage_key")
            if key and ctx.storage.exists(key):
                src = ctx.wpath("broll", "raw", Path(key).name)
                ctx.storage.get(key, src)
            else:
                ctx.warn(f"нет файла для слота {slot['index']} ({asset.get('asset_id')}): "
                         f"ни local_file, ни ключа в storage",
                         slot=slot["index"], asset=asset.get("asset_id"),
                         origin=asset.get("origin"))
                continue

        info = probe(src)
        fit = choose_fit(info, pillarbox_used=pillarbox_used, pillarbox_limit=pillarbox_limit)
        if fit == "pillarbox":
            pillarbox_used += 1
        duration = round(float(slot["duration"]), 3)
        cache_key = (str(src), duration, fit)
        if cache_key in cache:
            prepared[slot["index"]] = cache[cache_key]
            continue

        focus_x, focus_y = (0.5, 0.5)
        if fit == "crop" and info.width and info.height and info.width > info.height * 1.05:
            focus_x, focus_y = detect_focus(src, work_dir=ctx.wpath("shots", "_focus", ".k").parent)

        dst = ctx.wpath("shots", f"{asset['asset_id']}_{int(duration * 1000)}_{fit}.mp4")
        result = prepare_shot(ShotSpec(src=src, dst=dst, duration_sec=duration,
                                       width=width, height=height, fps=fps,
                                       fit=fit, focus_x=focus_x, focus_y=focus_y))
        cache[cache_key] = result
        prepared[slot["index"]] = result
    return prepared



def _prepare_matting(ctx, plan: dict[str, Any], avatar_meta: dict[str, Any]
                     ) -> tuple[dict[int, Any], dict[str, Path], dict[int, Path], dict[str, Any]]:
    """§7.7 — маска аватара, текст за головой и VFX-фон.

    Функция экспериментальная и полностью изолирована киллсвитчем: при
    ``features.avatar_matting: false`` она возвращает пустые словари, и сборка
    идёт как обычно — просто без текста за головой и без живого фона.
    """
    cfg = ctx.cfg
    summary: dict[str, Any] = {"enabled": bool(cfg.get("features.avatar_matting", False)),
                               "segments": [], "text_behind_head": [], "vfx": []}
    if not summary["enabled"]:
        summary["reason"] = "avatar_matting выключен киллсвитчем (§7.7)"
        return {}, {}, {}, summary

    segments = avatar_meta.get("segments", [])
    reports: dict[int, Any] = {}
    for segment in segments:
        clip = Path(segment.get("file", ""))
        if not clip.exists():
            continue
        report = assess_matte(clip, ctx.wpath("matte", f"seg_{segment['index']:02d}", ".k").parent)
        if not report.available:
            report = try_local_matting(clip, clip)     # §7.7 fallback 2
        reports[int(segment["index"])] = report
        summary["segments"].append({"index": segment["index"], **report.to_dict()})

    usable = [i for i, r in reports.items() if r.usable]
    if not usable:
        summary["degraded"] = True
        summary["reason"] = ("годной маски нет — текст за головой и VFX-фон "
                             "пропущены, остальное собирается как обычно (§7.7)")
        ctx.warn(f"§7.7: {summary['reason']}")
        return reports, {}, {}, summary

    # --- текст за головой (§5.3): только режим A и только при годной маске ---
    behind_layers: dict[str, Path] = {}
    render_ctx = Ctx.build(cfg)
    for block in plan.get("blocks", []):
        if block.get("mode") != "A":
            continue
        text = (block.get("emphasis_word") or "").strip()
        if not text:
            continue
        block_segments = [s for s in segments if s["block_id"] == block["id"]]
        if not block_segments or int(block_segments[0]["index"]) not in usable:
            continue
        layer = text_behind_head(render_ctx, text, progress=1.0)
        path = ctx.wpath("matte", f"behind_{block['id']}.png")
        layer.save(path)
        behind_layers[block["id"]] = path
        summary["text_behind_head"].append({"block_id": block["id"], "text": text})

    # --- VFX-фон (§7.7): ≤2 раза за ролик, 2–5 сек ---------------------------
    vfx_clips: dict[int, Path] = {}
    if bool(cfg.get("features.background_vfx", False)):
        limit = int(cfg.get("limits.bg_vfx_per_video", 2))
        lo, hi = cfg.get("limits.bg_vfx_sec", [2.0, 5.0])
        candidates = plan_vfx_backgrounds(
            [s for s in plan["slots"] if s["index"] in
             {idx for seg in segments if int(seg["index"]) in usable
              for idx in seg.get("slot_indices", [])}],
            limit=limit, duration_range=(float(lo), float(hi)))
        if candidates:
            provider = build_generation_provider(cfg, ctx.costs)
            for slot_index in candidates:
                slot = next(s for s in plan["slots"] if s["index"] == slot_index)
                prompt = (f"abstract living background for a science short, "
                          f"{slot.get('visual_intent') or slot['role']}, "
                          f"muted palette, single warm red accent, slow motion, "
                          f"no text, no logos, vertical 9:16")
                out = ctx.wpath("matte", f"vfx_{slot_index:02d}.mp4")
                try:
                    asset = provider.generate(prompt, out, kind="video",
                                              duration_sec=float(slot["duration"]) + 0.4,
                                              prefer_free=True)
                except Exception as exc:  # noqa: BLE001 — VFX не должен ронять сборку
                    ctx.warn(f"VFX-фон не сгенерирован: {exc}", slot=slot_index)
                    continue
                vfx_clips[slot_index] = asset.path
                summary["vfx"].append({"slot": slot_index,
                                       "duration_sec": round(float(slot["duration"]), 2)})

    summary["degraded"] = False
    return reports, behind_layers, vfx_clips, summary


_OVERLAY_BY_NAME = {
    "chat-thread": "chat_thread",
    "chat-ai-typing": "chat_thread",
    "article-highlight": "article_scroll",
    "browser-scroll": "article_scroll",
    "paper-reveal": "paper_reveal",
    "arxiv-card": "paper_reveal",
}

_NUM_IN_TEXT = re.compile(
    r"(?<![\d.])(\d+(?:[.,]\d+)?)(?:\s*(%|млрд|млн|тыс\.?|кубит(?:ов|а)?|[Tт]))?",
    re.IGNORECASE,
)
_CODEISH = re.compile(
    r"(?m)(^\s*(async\s+)?function\b|^\s*def\s+\w+|^\s*const\s+\w+|^\s*class\s+\w+"
    r"|[{};]\s*$|=>|::|\breturn\s+\w|\bimport\s+\w)",
)
_SHELLISH = re.compile(
    r"(?m)(^\s*\$\s|\b(?:npx|npm|pip3?|cargo|hyperframes|brew|apt-get)\s)",
)
_DIFFISH = re.compile(
    r"(?ms)(^\s*---\s*$)|(^\s*diff\s+--git\b)|"
    r"(^\s*-[^-\n].*$.*?^\s*\+[^+\n])",
)
_BEATISH = re.compile(
    r"(drop|freeze|beat|hard\s*cut|on the beat|дроп|бит|замороз)",
    re.I,
)


def _overlay_renderer(template: Template) -> str:
    """Какой HTML-рендерер рисует карточку источника."""
    mapped = _OVERLAY_BY_NAME.get(template.name)
    if mapped:
        return mapped
    if template.renderer in ("chat_thread", "article_scroll", "paper_reveal",
                             "source_card"):
        return template.renderer
    return "source_card"


def _plaque_overlay(*, template: Template, start: float, end: float,
                    params: dict[str, Any], why: str) -> dict[str, Any]:
    """Плашка: кастомный рендерер (accent-underline, clean-bar, dark-card), иначе generic plaque."""
    ovl: dict[str, Any] = {
        "type": "plaque", "start": start, "end": end,
        "template": template.id, "params": params, "why": why,
    }
    renderer = template.renderer
    if renderer and renderer != "plaque":
        ovl["renderer"] = renderer
    return ovl


def _stats_from_text(text: str) -> list[dict[str, Any]]:
    """Числа из реплики блока. Годы 1900–2100 отбрасываем, если есть другие."""
    found: list[dict[str, Any]] = []
    for match in _NUM_IN_TEXT.finditer(text or ""):
        raw = match.group(1).replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        suffix = (match.group(2) or "").strip()
        found.append({"value": value, "suffix": suffix,
                      "raw": match.group(0).strip()})
    if not found:
        return []
    years = [n for n in found
             if n["value"] == int(n["value"]) and 1900 <= n["value"] <= 2100]
    others = [n for n in found if n not in years]
    return others or found


def _build_overlays(ctx, plan: dict[str, Any], words: list[dict[str, Any]],
                    catalog: TemplateCatalog, *, variant: str, seed: int,
                    recent_videos: list[str], used: list[str]) -> list[dict[str, Any]]:
    """Плашки, карточки источников, подсветка, data-viz и CTA (§5.4–5.6, §6)."""
    overlays: list[dict[str, Any]] = []
    duration = float(plan["duration_sec"])
    sources = plan.get("sources", [])
    on_screen = [s for s in sources if s.get("show_on_screen", True)]

    evidence_slots = [s for s in plan["slots"]
                      if s.get("asset_role") == "evidence" or s.get("role") == "evidence"]
    if on_screen and evidence_slots:
        source = on_screen[0]
        anchor = evidence_slots[0]
        if variant == "A":
            card_category = "browser-ui"
            card_prefer = ["browser-ui/chat-thread", "browser-ui/article-highlight",
                           "browser-ui/browser-scroll"]
        else:
            card_category = "frames-cards"
            card_prefer = ["frames-cards/paper-reveal", "frames-cards/arxiv-card"]
        card_template = catalog.pick(
            card_category, duration=float(anchor["duration"]),
            recent_videos=recent_videos, exclude=used, prefer=card_prefer,
            seed=seed)
        used.append(card_template.id)
        card_start = float(anchor["start"])
        card_end = min(card_start + 3.4, float(evidence_slots[-1]["end"]))
        renderer = _overlay_renderer(card_template)
        overlays.append({
            "type": "source_card", "start": card_start, "end": card_end,
            "template": card_template.id, "renderer": renderer, "params": {
                "template": source.get("screen_template", "browser"),
                "domain": source.get("domain", ""),
                "title": source.get("title", ""),
                "snippet": source.get("snippet", ""),
                "prompt": source.get("title") or source.get("snippet", ""),
                "highlight_line": source.get("highlight_line", ""),
                "typing": bool(card_template.params.get("typing")),
                "scroll": bool(card_template.params.get("scroll")),
            },
            "why": "§5.6: источник обязан появиться на экране",
        })
        # §5.5: подсветка обязательна при показе скриншота статьи.
        overlays.append({
            "type": "highlight", "start": card_start + 0.6,
            "end": min(card_start + 1.7, card_end),
            "params": {"label": source.get("highlight_line", ""), "target": "title"},
            "why": "§5.5: фокусная подсветка ключевой строки источника",
        })
        plaque_template = catalog.pick("lower-thirds", duration=2.4,
                                       recent_videos=recent_videos, exclude=used,
                                       prefer=["lower-thirds/source-domain"], seed=seed)
        used.append(plaque_template.id)
        domain = source.get("domain", "")
        overlays.append(_plaque_overlay(
            template=plaque_template,
            start=card_end - 0.2,
            end=min(card_end + 2.2, duration),
            params={"text": domain, "subtitle": "источник",
                    "name": domain, "role": "источник",
                    **{k: v for k, v in plaque_template.params.items()
                       if k in ("position", "direction", "accent_underline",
                                "clean_bar", "dark_card")}},
            why="§5.4: плашка с доменом источника",
        ))

    _append_dataviz(plan, overlays, catalog, variant=variant, seed=seed,
                    recent_videos=recent_videos, used=used)

    # Плашки из overlay-указаний сценария (lower_third).
    for block in plan.get("blocks", []):
        overlay = block.get("overlay") or {}
        if overlay.get("type") != "lower_third":
            continue
        block_slots = [s for s in plan["slots"] if s["block_id"] == block["id"]]
        if not block_slots:
            continue
        hint = overlay.get("template_hint") or ""
        lockups = ["lower-thirds/accent-underline", "lower-thirds/clean-bar",
                   "lower-thirds/dark-card"]
        prefer = ([hint] + lockups) if hint else lockups
        template = catalog.pick("lower-thirds", duration=2.4, recent_videos=recent_videos,
                                exclude=used, prefer=prefer, seed=seed + 7)
        used.append(template.id)
        start = float(block_slots[0]["start"]) + 0.4
        content = overlay.get("content", "")
        role = (overlay.get("role") or overlay.get("subtitle")
                or overlay.get("kicker") or "")
        overlays.append(_plaque_overlay(
            template=template,
            start=start,
            end=min(start + 2.6, float(block_slots[-1]["end"])),
            params={"text": content, "content": content, "name": content,
                    "role": role,
                    **{k: v for k, v in template.params.items()
                       if k in ("position", "direction", "accent_underline",
                                "clean_bar", "dark_card")}},
            why=f"плашка из сценария, блок {block['id']}",
        ))

    # CTA — последние 2 сек, всегда (§6, QC-16). Identity close — вордмарк,
    # не кнопка: если выпал logo-brand-close, композитор рисует локуп, не пилюлю.
    cta_start, cta_end = plan.get("cta_window", [duration - 2.0, duration])
    cta_prefer = (["outro-cta/subscribe-pulse"] if variant == "A"
                  else ["outro-cta/logo-brand-close", "outro-cta/subscribe-pulse"])
    cta_template = catalog.pick("outro-cta", duration=float(cta_end) - float(cta_start),
                                recent_videos=recent_videos, exclude=used,
                                prefer=cta_prefer, seed=seed)
    used.append(cta_template.id)
    if (cta_template.renderer == "logo_brand_close"
            or cta_template.params.get("logo_close")
            or cta_template.name == "logo-brand-close"):
        overlays.append({
            "type": "cta", "start": float(cta_start), "end": float(cta_end),
            "template": cta_template.id,
            "renderer": "logo_brand_close",
            "params": dict(cta_template.params),
            "why": "§6: identity close — вордмарк, не кнопка подписки",
        })
    else:
        overlays.append({
            "type": "cta", "start": float(cta_start), "end": float(cta_end),
            "template": cta_template.id,
            "params": {"text": "ПОДПИСАТЬСЯ"},
            "why": "§6: кнопка подписки в последние 2 сек",
        })
    return overlays


def _append_dataviz(plan: dict[str, Any], overlays: list[dict[str, Any]],
                    catalog: TemplateCatalog, *, variant: str, seed: int,
                    recent_videos: list[str], used: list[str]) -> None:
    """Оверлей с числом на evidence/develop — не чаще одного на ролик."""
    duration = float(plan["duration_sec"])
    cta_start = float((plan.get("cta_window") or [duration - 2.0, duration])[0])
    occupied = [(float(o["start"]), float(o["end"])) for o in overlays
                if o.get("type") in ("source_card", "cta", "plaque")]
    blocks = {b["id"]: b for b in plan.get("blocks", [])}
    for slot in plan["slots"]:
        if slot.get("role") not in ("evidence", "develop"):
            continue
        if slot["kind"] not in ("footage", "meme", "avatar"):
            continue
        nums = _stats_from_text(str(blocks.get(slot["block_id"], {}).get("text") or ""))
        if not nums:
            continue
        start = float(slot["start"]) + 0.25
        end = min(float(slot["end"]) - 0.15, start + 3.0, cta_start)
        if end - start < 1.2:
            continue
        if any(start < occ_end and end > occ_start for occ_start, occ_end in occupied):
            continue
        pct = str(nums[0].get("suffix") or "").lstrip().startswith("%")
        declining = (len(nums) >= 2
                     and float(nums[1]["value"]) < float(nums[0]["value"]))
        prefer = (["data-viz/conic-progress-ring",
                   "data-viz/stat-countup-card"]
                  if len(nums) == 1 and pct and variant != "B"
                  else ["data-viz/stat-countup-card"] if len(nums) == 1
                  else ["data-viz/bar-chart-race",
                        "data-viz/chart-story",
                        "data-viz/mk-line-graph",
                        "data-viz/animated-bar-chart",
                        "data-viz/compare-bars", "data-viz/bar-race-mini"]
                  if len(nums) >= 4
                  else (["data-viz/decline-chart",
                         "data-viz/chart-story",
                         "data-viz/mk-line-graph",
                         "data-viz/animated-bar-chart",
                         "data-viz/compare-bars", "data-viz/bar-race-mini"]
                        if declining
                        else ["data-viz/chart-story",
                              "data-viz/mk-line-graph",
                              "data-viz/animated-bar-chart",
                              "data-viz/compare-bars", "data-viz/bar-race-mini"]))
        if variant == "B" and len(nums) >= 2:
            prefer = ["data-viz/compare-bars", "data-viz/stat-countup-card"]
        block = blocks.get(slot["block_id"], {})
        blob = " ".join([
            str(block.get("text") or ""),
            str(block.get("heading") or ""),
        ]).lower()
        if variant != "B" and any(key in blob for key in (
                "spain", "españa", "espan", "испан", "madrid", "catalun",
                "comunidad autónoma", "pib per")):
            prefer = ["data-viz/spain-map"] + [item for item in prefer
                                              if item != "data-viz/spain-map"]
        rating_like = (
            len(nums) == 1
            and not pct
            and 0.0 < float(nums[0]["value"]) <= 5.0
            and abs(float(nums[0]["value"])
                    - round(float(nums[0]["value"]))) > 1e-9
        )
        if variant != "B" and (rating_like or any(key in blob for key in (
                "stars", "star rating", "звезд", "рейтинг", "оценк",
                "отзыв", "app store", "satisfaction"))):
            prefer = ["data-viz/star-rating-fill"] + [
                item for item in prefer if item != "data-viz/star-rating-fill"]
        if variant != "B" and any(key in blob for key in (
                "united states", "u.s.", "сша", "америк", "census",
                "population density", "per square mile", " by state",
                "штат ", "калифорн", "нью-йорк", "нью йорк", "texas",
                "california")):
            prefer = ["data-viz/us-map"] + [
                item for item in prefer if item != "data-viz/us-map"]
        template = catalog.pick("data-viz", duration=end - start,
                                recent_videos=recent_videos, exclude=used,
                                prefer=prefer, seed=seed + 11)
        used.append(template.id)
        name = template.name
        if name == "decline-chart":
            start_v = float(nums[0]["value"])
            end_v = float(nums[1]["value"]) if len(nums) >= 2 else start_v
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            params = {
                "start_value": start_v,
                "end_value": end_v,
                "label": heading or "Retention",
                "values": [start_v, end_v],
            }
        elif name == "conic-progress-ring":
            val = float(nums[0]["value"])
            suffix = str(nums[0]["suffix"]) if nums[0].get("suffix") else "%"
            token = (str(int(round(val))) if abs(val - round(val)) < 1e-9
                     else f"{val:g}")
            fill = val if 0.0 <= val <= 100.0 else 100.0
            params = {
                "progress": fill,
                "value": val,
                "label": f"{token}{suffix}",
                "thickness": 12,
            }
        elif name == "star-rating-fill":
            rating = 4.8
            if nums:
                val = float(nums[0]["value"])
                if 0.0 <= val <= 5.0:
                    rating = val
            params = {
                "rating": rating,
                "starCount": 5,
                "showValue": True,
            }
        elif name == "spain-map":
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            regions = [{
                "abbr": str(shape["abbr"]),
                "name": str(shape["name"]),
                "value": float(shape["gdp"]),
            } for shape in SPM_SHAPES]
            if nums:
                ranked = sorted(regions, key=lambda row: -float(row["value"]))
                for index, num in enumerate(nums[:len(ranked)]):
                    ranked[index]["value"] = num["value"]
            params = {
                "title": heading or "PIB per cápita por Comunidad Autónoma",
                "subtitle": "Producto Interior Bruto per cápita, estimación 2024",
                "source": "Fuente: Instituto Nacional de Estadística",
                "regions": regions,
                "highlight": ["MAD", "PVA", "NAV"],
            }
        elif name == "us-map":
            heading = str(blocks.get(slot["block_id"], {}).get("heading") or "")
            regions = [{
                "abbr": str(shape["abbr"]),
                "name": str(shape["name"]),
                "value": float(shape["density"]),
            } for shape in USM_SHAPES]
            if nums:
                ranked = sorted(regions, key=lambda row: -float(row["value"]))
                for index, num in enumerate(nums[:len(ranked)]):
                    ranked[index]["value"] = num["value"]
            params = {
                "title": heading or "Population Density by State",
                "subtitle": "Residents per square mile, 2024 Census estimates",
                "source": "Source: U.S. Census Bureau",
                "regions": regions,
                "highlight": ["CA", "NY", "TX", "FL", "NJ"],
            }
        elif name in ("stat-countup-card", "counter-roll") or len(nums) == 1:
            suffix = f" {nums[0]['suffix']}" if nums[0]["suffix"] else ""
            params: dict[str, Any] = {
                "value": nums[0]["value"], "suffix": suffix,
                "label": nums[0]["raw"],
                "values": [n["value"] for n in nums[:4]],
                "labels": [n["raw"] for n in nums[:4]],
            }
        else:
            n_take = (8 if name == "bar-chart-race"
                      else 6 if name == "mk-line-graph"
                      else 4 if name == "chart-story"
                      else 7 if name == "animated-bar-chart" else 4)
            params = {
                "values": [n["value"] for n in nums[:n_take]],
                "labels": [n["raw"] for n in nums[:n_take]],
                "value": nums[0]["value"],
                "kpi": nums[0]["raw"],
            }
            if name == "bar-chart-race":
                params["value_prefix"] = ""
                params["value_suffix"] = (
                    f" {nums[0]['suffix']}" if nums[0].get("suffix") else "")
                params["title"] = str(
                    blocks.get(slot["block_id"], {}).get("heading")
                    or "Streaming Subscribers by Service")
            if name == "chart-story":
                params["unit"] = (
                    str(nums[0]["suffix"]) if nums[0].get("suffix") else "%")
                params["emphasize"] = len(params["values"]) - 1
            if name == "mk-line-graph":
                heading = str(blocks.get(slot["block_id"], {}).get("heading")
                              or "")
                series = [{
                    "name": heading or "Renders",
                    "values": [n["value"] for n in nums[:n_take]],
                }]
                rest = nums[n_take:n_take * 2]
                if len(rest) >= 2:
                    series.append({
                        "name": "Projects",
                        "values": [n["value"] for n in rest],
                    })
                params["series"] = series
                params["xLabels"] = [n["raw"] for n in nums[:n_take]]
                params["showValues"] = True
        overlays.append({
            "type": "dataviz", "start": start, "end": end,
            "template": template.id, "renderer": template.renderer,
            "params": params,
            "why": "data-viz: в блоке есть число",
        })
        return


def build_variant(ctx, plan: dict[str, Any], words_doc: dict[str, Any],
                  assets: dict[int, dict[str, Any]], prepared: dict[int, dict[str, Any]],
                  catalog: TemplateCatalog, avatar_meta: dict[str, Any],
                  sfx_map: dict[str, Any], *, variant: str,
                  recent_videos: list[str], preferences: dict[str, Any] | None = None,
                  asset_rotation: int = 0) -> dict[str, Any]:
    seed = _variant_seed(plan["video_id"], variant)
    # Накопленные предпочтения влияют на версию A: она несёт «текущий дефолт»,
    # а B остаётся альтернативой, иначе обучение схлопнет обе версии в одну.
    prefs = (preferences or {}) if variant == "A" else {}
    used_templates: list[str] = []
    slots = plan["slots"]
    shots: list[dict[str, Any]] = []

    # Приёмы вокруг ведущего ставятся через один подходящий аватар-кадр: на
    # каждом они превратились бы в заставку, а реже одного на два — потерялись
    # бы. С какого начинать, решает сид варианта, поэтому A и B получают приёмы
    # на разных кадрах, а не один и тот же ролик с другими подписями.
    alpha_slots = _alpha_slots(avatar_meta)
    face_centres = _face_centres(avatar_meta)
    blocks_by_id = {b["id"]: b for b in plan.get("blocks", [])}
    # Библиотека иконок §14: пилюля бренда берёт логотип оттуда. Её отсутствие
    # не должно валить сборку — приём просто не выпадет.
    try:
        brand_icons = load_brand_icons(ctx.cfg)
    except Exception:                                    # noqa: BLE001
        brand_icons = None
    hero_offset = seed % 2
    hero_eligible = 0

    fullscreen_styles = (["text-fullscreen/beat-freeze-cut",
                          "text-fullscreen/kinetic-stack",
                          "text-fullscreen/blur-out-up",
                          "text-fullscreen/bottom-up-letters",
                          "text-fullscreen/kinetic-type-swap",
                          "text-fullscreen/line-by-line-slide",
                          "text-fullscreen/particle-text-dissolve",
                          "text-fullscreen/per-word-crossfade",
                          "text-fullscreen/scan-band",
                          "text-fullscreen/scramble-reveal",
                          "text-fullscreen/shared-axis-z",
                          "text-fullscreen/code-3d-extrude",
                          "text-fullscreen/code-diff",
                          "text-fullscreen/code-particle-assemble",
                          "text-fullscreen/code-scroll",
                          "text-fullscreen/code-typing",
                          "text-fullscreen/terminal-simulator",
                          "text-fullscreen/apple-terminal-clear-dark",
                          "text-fullscreen/dark-plus",
                          "text-fullscreen/number-slam-card"]
                         if variant == "A" else
                         ["text-fullscreen/stack-3lines", "text-fullscreen/fact-card"])

    for slot in slots:
        entry: dict[str, Any] = {
            "index": slot["index"], "start": slot["start"], "end": slot["end"],
            "duration": slot["duration"], "kind": slot["kind"],
            "block_id": slot["block_id"], "role": slot["role"], "mode": slot["mode"],
            "reason": slot["reason"],
        }

        if slot["kind"] == "fullscreen_text":
            preferred = prefs.get(f"fullscreen_text@{slot['role']}")
            content = slot.get("content", "")
            styles = list(fullscreen_styles)
            if variant == "A" and re.search(r"\d", str(content)):
                styles = ["text-fullscreen/number-slam-card",
                          "text-fullscreen/kinetic-stack"]
            if variant == "A" and _CODEISH.search(str(content)):
                styles = ["text-fullscreen/code-3d-extrude",
                          "text-fullscreen/code-particle-assemble",
                          "text-fullscreen/code-scroll",
                          "text-fullscreen/code-typing",
                          "text-fullscreen/terminal-simulator",
                          "text-fullscreen/apple-terminal-clear-dark",
                          "text-fullscreen/dark-plus"] + styles
            if (variant == "A" and _CODEISH.search(str(content))
                    and str(content).count("\n") < 7):
                styles = ["text-fullscreen/code-typing"] + styles
            if variant == "A" and str(content).count("\n") >= 7:
                styles = ["text-fullscreen/code-scroll"] + styles
            if variant == "A" and _DIFFISH.search(str(content)):
                styles = ["text-fullscreen/code-diff"] + styles
            if variant == "A" and re.search(r"(?m)^\s*def\s+", str(content)):
                styles = ["text-fullscreen/dark-plus"] + styles
            if variant == "A" and _SHELLISH.search(str(content)):
                styles = ["text-fullscreen/apple-terminal-clear-dark",
                          "text-fullscreen/terminal-simulator"] + styles
            if variant == "A" and _BEATISH.search(str(content)):
                styles = ["text-fullscreen/beat-freeze-cut"] + styles
            template = catalog.pick("text-fullscreen", duration=float(slot["duration"]),
                                    recent_videos=recent_videos, exclude=used_templates,
                                    prefer=([preferred] if preferred else [])
                                    + [slot.get("template_hint", "")] + styles,
                                    seed=seed)
            used_templates.append(template.id)
            block = blocks_by_id.get(slot["block_id"], {})
            entry.update({
                "content": content,
                "template": template.id,
                "renderer": template.renderer,
                "params": dict(template.params),
                "invert": bool(template.params.get("invert")) or variant == "B",
                "accent_word": block.get("emphasis_word") or slot.get("emphasis_word"),
            })
            shots.append(entry)
            continue

        prep = prepared.get(slot["index"])
        asset = assets.get(slot["index"])
        if prep is None or (asset is None and slot["kind"] not in AVATAR_KINDS):
            # Пустой слот закрывается фирменной заливкой, но это дефект плана,
            # и он обязан быть виден в отчёте, а не «раствориться» в кадре.
            entry.update({"file": None, "asset_id": None,
                          "gap_reason": "материал не найден"})
            shots.append(entry)
            continue

        kb_template: Template | None = None
        if slot["kind"] in ("footage", "meme"):
            preferred = prefs.get(f"kenburns@{slot['role']}")
            kb_template = catalog.pick("kenburns", duration=float(slot["duration"]),
                                       recent_videos=recent_videos, exclude=used_templates,
                                       prefer=[preferred] if preferred else [],
                                       seed=seed + slot["index"])
            used_templates.append(kb_template.id)

        transition_entry: dict[str, Any] | None = None
        if slot.get("transition_in") == "dynamic":
            category = "avatar-entry" if slot["kind"] in AVATAR_KINDS else "transitions"
            preferred = prefs.get(f"transition@{slot['role']}")
            tr_prefer = [preferred] if preferred else []
            if variant == "A" and category == "transitions":
                tr_prefer.append("transitions/transitions-other")
                tr_prefer.append("transitions/transitions-light")
                tr_prefer.append("transitions/transitions-destruction")
                tr_prefer.append("transitions/transitions-cover")
                tr_prefer.append("transitions/transitions-blur")
                tr_prefer.append("transitions/transitions-3d")
                tr_prefer.append("transitions/mk-clone-wall-transition")
                tr_prefer.append("transitions/whip-pan")
                tr_prefer.append("transitions/thermal-distortion")
                tr_prefer.append("transitions/sdf-iris")
                tr_prefer.append("transitions/light-leak")
                tr_prefer.append("transitions/gravitational-lens")
                tr_prefer.append("transitions/glitch")
                tr_prefer.append("transitions/cinematic-zoom")
                tr_prefer.append("transitions/zoom-through")
            tr = catalog.pick(category, duration=0.24, recent_videos=recent_videos,
                              exclude=used_templates + ["transitions/cut"],
                              prefer=tr_prefer,
                              tags={"dynamic", "entry"}, seed=seed + slot["index"] * 3)
            used_templates.append(tr.id)
            transition_entry = {
                "template": tr.id, "renderer": tr.renderer,
                "duration": max(0.16, min(0.32, float(tr.duration_range[1] or 0.24))),
                "params": {**tr.params, "seed": seed + slot["index"]},
            }
        else:
            transition_entry = {"template": "transitions/cut", "renderer": "cut",
                                "duration": 0.0, "params": {}}

        asset = asset or {}
        is_avatar = slot["kind"] in AVATAR_KINDS

        hero_entry: dict[str, Any] | None = None
        # Только чистый аватар-кадр. Сплит уже сам монтажный приём: кадр в нём
        # поделён пополам, и панель сбоку или картинка за спиной спорят с этим
        # делением, а не поддерживают его.
        if slot["kind"] == "avatar":
            hero_eligible += 1
            if (hero_eligible + hero_offset) % 2 == 0:
                block = blocks_by_id.get(slot["block_id"], {})
                hero_entry = _hero_device(
                    catalog, slot=slot,
                    content=_hero_content(block, slot, brand_icons,
                                          face_centres.get(int(slot["index"]))),
                    has_alpha=int(slot["index"]) in alpha_slots,
                    plate_src=_plate_source(slot, slots, prepared),
                    recent_videos=recent_videos, exclude=used_templates,
                    seed=seed)
                if hero_entry:
                    used_templates.append(hero_entry["template"])

        entry.update({
            "file": prep["dst"],
            "asset_id": asset.get("asset_id") or (f"avatar_seg_{prep.get('avatar_segment')}"
                                                  if is_avatar else None),
            "source": "heygen" if is_avatar else asset.get("source"),
            "license": ("HeyGen ToS (цифровой двойник заказчика)" if is_avatar
                        else asset.get("license")),
            "attribution": asset.get("attribution", ""),
            "page_url": asset.get("page_url", ""),
            "avatar_offset_sec": prep.get("avatar_offset_sec"),
            "matte": prep.get("matte"),
            "background": prep.get("background"),
            # Приём на кадре отменяет слово за головой (§5.3): панель за спиной
            # перекрывает его, оставляя торчать одну букву, лучи ложатся
            # поверх, заголовок добавляет к нему третий текст, а сплит и
            # выбивка уводят ведущего с места, к которому слово привязано.
            # Слово остаётся на аватар-кадрах без приёма — их всегда половина.
            "text_behind_head": bool(prep.get("text_behind_head")) and not hero_entry,
            "ai_generated": bool(asset.get("ai_generated")),
            "mock": bool(asset.get("mock")),
            "fit": prep.get("fit"), "focus": [prep.get("focus_x"), prep.get("focus_y")],
            "kenburns": ({"template": kb_template.id, **kb_template.params}
                         if kb_template else None),
            "transition": transition_entry,
            "hero": hero_entry,
        })
        shots.append(entry)

    overlays = _build_overlays(ctx, plan, words_doc["words"], catalog, variant=variant,
                               seed=seed, recent_videos=recent_videos, used=used_templates)

    # Субтитры: весь ролик, кроме кадров с полноэкранным текстом (§5.1).
    fs_windows = [(float(s["start"]), float(s["end"])) for s in slots
                  if s["kind"] == "fullscreen_text"]
    fs_windows += [(float(s["start"]), float(s["end"])) for s in shots
                   if (s.get("hero") or {}).get("carries_line")]
    subtitles = []
    for word in words_doc["words"]:
        start, end = float(word["start"]), float(word["end"])
        # Отбрасываем по пересечению, а не по началу: слово, начавшееся до
        # склейки и дожившее до неё, оставалось висеть поверх полноэкранного
        # текста. Видно на кадре готового MP4 — «ты» поверх «ПЕРЕЖИВЁШЬ».
        if any(start < w_end and end > w_start for w_start, w_end in fs_windows):
            continue
        subtitles.append({
            "display": word["display"], "start": start, "end": end,
            "emphasis": bool(word.get("emphasis")), "block_id": word["block_id"],
        })

    return {
        "video_id": plan["video_id"],
        "variant": variant,
        "fps": plan["fps"],
        "resolution": list(ctx.cfg.resolution),
        "duration_sec": plan["duration_sec"],
        "audio": {"mix": "mix.wav", "voice": "voice_final.wav",
                  "music_bed": "music_bed.wav", "sfx_map": "sfx_map.json",
                  "loudness": sfx_map.get("loudness", {})},
        "shots": shots,
        "overlays": overlays,
        "subtitles": subtitles,
        "subtitle_style": {
            "mode": ctx.cfg.brand("subtitles.readability_mode", "stroke"),
            "baseline_y": ctx.cfg.brand("subtitles.baseline_y_default", 975),
            "caption": pick_caption_style(plan, ctx.cfg.brandbook),
        },
        "avatar": avatar_meta.get("segments", []),
        "templates_used": used_templates,
        "asset_rotation": asset_rotation,
        "preferences_applied": sorted(prefs) if prefs else [],
        "cta_window": plan.get("cta_window"),
        "stats": plan.get("stats", {}),
    }



def _force_ab_difference(plans: dict[str, dict[str, Any]], variants: list[str],
                         catalog: TemplateCatalog, required: int, ctx) -> int:
    """§15.12.2 — довести различие версий до требуемого **конструктивно**.

    Полагаться на то, что разные сиды сами дадут три различия, нельзя: пул
    шаблонов категории конечен, а предпочтения тянут версию A к устоявшимся
    вариантам. Когда различий не хватает, версия B получает другие шаблоны там,
    где это ничего не ломает: Ken Burns, переходы и оформление полноэкранного
    текста взаимозаменяемы внутри своей категории.
    """
    a_plan, b_plan = plans[variants[0]], plans[variants[1]]
    diff = diff_count(a_plan["templates_used"], b_plan["templates_used"])
    if diff >= required:
        return diff

    a_templates = set(a_plan["templates_used"])
    swapped = 0
    for shot in b_plan["shots"]:
        if diff + swapped >= required:
            break
        for field, category in (("kenburns", "kenburns"), ("transition", "transitions")):
            current = shot.get(field)
            if not current or not current.get("template"):
                continue
            if current["template"] not in a_templates:
                continue          # здесь версии уже расходятся
            alternatives = [t for t in catalog.by_category(category)
                            if t.id not in a_templates
                            and t.id not in b_plan["templates_used"]
                            and t.fits(float(shot["duration"]) if category == "kenburns" else 0.24)]
            if not alternatives:
                continue
            replacement = alternatives[0]
            old_id = current["template"]
            if field == "kenburns":
                shot["kenburns"] = {"template": replacement.id, **replacement.params}
            else:
                shot["transition"] = {
                    "template": replacement.id, "renderer": replacement.renderer,
                    "duration": current.get("duration", 0.24),
                    "params": {**replacement.params, "seed": shot["index"]},
                }
            b_plan["templates_used"] = [
                replacement.id if t == old_id else t for t in b_plan["templates_used"]]
            swapped += 1
            break

    diff = diff_count(a_plan["templates_used"], b_plan["templates_used"])
    if swapped:
        ctx.warn(f"версии сошлись по шаблонам: {swapped} решений версии B заменены "
                 f"альтернативами, различий стало {diff} (§15.12.2)",
                 swapped=swapped, diff=diff)
    return diff


def run_step(ctx) -> dict[str, Any]:
    plan = ctx.read("cut_plan.json")
    words_doc = ctx.read("words.json")
    accepted_doc = ctx.read("accepted_assets.json")
    generated_doc = ctx.read("generated_assets.json")
    avatar_meta = ctx.read_or("avatar_meta.json", {"segments": []})
    sfx_map = ctx.read_or("sfx_map.json", {})
    catalog = TemplateCatalog.load(ctx.cfg)

    accepted = accepted_doc.get("accepted", {})
    generated = generated_doc.get("generated", {})
    base_assets: dict[int, dict[str, Any]] = {}
    for slot in plan["slots"]:
        asset = _asset_for_slot(slot, accepted, generated)
        if asset is not None:
            base_assets[slot["index"]] = asset

    recent_videos = _recent_video_ids(ctx, limit=3)
    pillarbox_limit = int(ctx.cfg.get("limits.pillarbox_per_video", 2))
    preferences = _load_preferences(ctx)
    matte_reports, behind_layers, vfx_clips, matte_summary = _prepare_matting(
        ctx, plan, avatar_meta)

    variants = list(ctx.variants)
    plans: dict[str, dict[str, Any]] = {}
    for offset, variant in enumerate(variants):
        assets = _rotate_assets(plan["slots"], base_assets, shift=offset)
        prepared = _prepare_shots(ctx, plan["slots"], assets, pillarbox_limit,
                                  avatar_segments=avatar_meta.get("segments", []),
                                  matte_reports=matte_reports,
                                  behind_layers=behind_layers if variant == "A" else {},
                                  vfx_clips=vfx_clips if variant == "A" else {})
        plans[variant] = build_variant(
            ctx, plan, words_doc, assets, prepared, catalog, avatar_meta, sfx_map,
            variant=variant, recent_videos=recent_videos,
            preferences=preferences, asset_rotation=offset)
        plans[variant]["matting"] = matte_summary
        ctx.write(f"edit_plan_{variant}.json", plans[variant])

    # §15.12.2 — версии обязаны различаться минимум на 3 шаблонных позиции.
    ab_diff = None
    if len(variants) >= 2:
        required = int(ctx.cfg.get("limits.ab_min_template_diff", 3))
        ab_diff = _force_ab_difference(plans, variants, catalog, required, ctx)
        if ab_diff < required:
            raise RedshiftError(
                f"версии {variants[0]} и {variants[1]} различаются лишь {ab_diff} "
                f"шаблонными решениями, требуется {required}; альтернатив в каталоге "
                f"не нашлось (§15.12.2)",
                code="AB_TOO_SIMILAR", diff=ab_diff, required=required,
                a=plans[variants[0]]["templates_used"],
                b=plans[variants[1]]["templates_used"])
        for variant in variants:
            ctx.write(f"edit_plan_{variant}.json", plans[variant])

    catalog.mark_used(
        {t for variant in plans.values() for t in variant["templates_used"]},
        plan["video_id"])
    catalog.save()

    _log.info("edit-планы собраны", extra={
        "variants": ",".join(variants),
        "shots": len(plans[variants[0]]["shots"]),
        "overlays": len(plans[variants[0]]["overlays"]),
        "subtitles": len(plans[variants[0]]["subtitles"]),
        "ab_template_diff": ab_diff,
    })
    return {"variants": variants, "ab_template_diff": ab_diff,
            "shots": len(plans[variants[0]]["shots"]),
            "matting": {"enabled": matte_summary["enabled"],
                        "degraded": matte_summary.get("degraded"),
                        "text_behind_head": len(matte_summary["text_behind_head"]),
                        "vfx": len(matte_summary["vfx"])}}


def _load_preferences(ctx) -> dict[str, Any]:
    """Накопленные предпочтения монтажа (§4.5): «в ситуации X выбран вариант Y»."""
    from ..lib.jsonio import read_json_or

    prefs = read_json_or(ctx.cfg.repo_root / "config" / "editing_preferences.json", {})
    defaults = prefs.get("defaults", {}) or {}
    # Берём только ситуации вида "<решение>@<роль>": остальные ключи —
    # общие настройки, а не выбор конкретного шаблона.
    return {k: v for k, v in defaults.items() if "@" in str(k) and isinstance(v, str)}


def _recent_video_ids(ctx, *, limit: int = 3) -> list[str]:
    from ..lib.jsonio import read_json_or

    history = read_json_or(ctx.cfg.path("paths.cache_dir", "cache") / "run_history.json",
                           {"runs": []})
    return [r.get("video_id") for r in history.get("runs", [])][-limit:]
