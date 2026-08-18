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
from ..lib.templates import TemplateCatalog, Template, diff_count

_log = get_logger("p11")

AVATAR_KINDS = ("avatar", "split")


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
            if segment is None or not Path(segment.get("file", "")).exists():
                ctx.warn(f"нет аватар-клипа для слота {slot['index']}", slot=slot["index"])
                continue
            offset = max(0.0, float(slot["start"]) - float(segment["start"]))
            duration = round(float(slot["duration"]), 3)
            avatar_src = Path(segment["file"])

            if slot["kind"] == "split":
                # §3.5 режим B: сверху доказательный материал, снизу аватар.
                asset = assets.get(slot["index"])
                top_src = Path(asset.get("local_file") or "") if asset else Path()
                if not top_src.exists():
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
        src = Path(asset.get("local_file") or "")
        if not src.exists():
            key = asset.get("storage_key")
            if key and ctx.storage.exists(key):
                src = ctx.wpath("broll", "raw", Path(key).name)
                ctx.storage.get(key, src)
            else:
                ctx.warn(f"нет файла для слота {slot['index']} ({asset.get('asset_id')})",
                         slot=slot["index"])
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


def _build_overlays(ctx, plan: dict[str, Any], words: list[dict[str, Any]],
                    catalog: TemplateCatalog, *, variant: str, seed: int,
                    recent_videos: list[str], used: list[str]) -> list[dict[str, Any]]:
    """Плашки, карточки источников, подсветка и CTA (§5.4–5.6, §6)."""
    overlays: list[dict[str, Any]] = []
    duration = float(plan["duration_sec"])
    sources = plan.get("sources", [])
    on_screen = [s for s in sources if s.get("show_on_screen", True)]

    evidence_slots = [s for s in plan["slots"]
                      if s.get("asset_role") == "evidence" or s.get("role") == "evidence"]
    if on_screen and evidence_slots:
        source = on_screen[0]
        anchor = evidence_slots[0]
        card_template = catalog.pick(
            "browser-ui" if variant == "A" else "frames-cards",
            duration=float(anchor["duration"]), recent_videos=recent_videos,
            exclude=used, seed=seed)
        used.append(card_template.id)
        card_start = float(anchor["start"])
        card_end = min(card_start + 3.4, float(evidence_slots[-1]["end"]))
        overlays.append({
            "type": "source_card", "start": card_start, "end": card_end,
            "template": card_template.id, "params": {
                "template": source.get("screen_template", "browser"),
                "domain": source.get("domain", ""),
                "title": source.get("title", ""),
                "snippet": source.get("snippet", ""),
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
        overlays.append({
            "type": "plaque", "start": card_end - 0.2,
            "end": min(card_end + 2.2, duration),
            "template": plaque_template.id,
            "params": {"text": source.get("domain", ""), "subtitle": "источник",
                       **{k: v for k, v in plaque_template.params.items()
                          if k in ("position", "direction")}},
            "why": "§5.4: плашка с доменом источника",
        })

    # Плашки из overlay-указаний сценария (lower_third).
    for block in plan.get("blocks", []):
        overlay = block.get("overlay") or {}
        if overlay.get("type") != "lower_third":
            continue
        block_slots = [s for s in plan["slots"] if s["block_id"] == block["id"]]
        if not block_slots:
            continue
        template = catalog.pick("lower-thirds", duration=2.4, recent_videos=recent_videos,
                                exclude=used, prefer=[overlay.get("template_hint", "")],
                                seed=seed + 7)
        used.append(template.id)
        start = float(block_slots[0]["start"]) + 0.4
        overlays.append({
            "type": "plaque", "start": start,
            "end": min(start + 2.6, float(block_slots[-1]["end"])),
            "template": template.id,
            "params": {"text": overlay.get("content", ""),
                       **{k: v for k, v in template.params.items()
                          if k in ("position", "direction")}},
            "why": f"плашка из сценария, блок {block['id']}",
        })

    # CTA — последние 2 сек, всегда (§6, QC-16).
    cta_start, cta_end = plan.get("cta_window", [duration - 2.0, duration])
    cta_template = catalog.pick("outro-cta", duration=float(cta_end) - float(cta_start),
                                recent_videos=recent_videos, exclude=used,
                                prefer=["outro-cta/subscribe-pulse"], seed=seed)
    used.append(cta_template.id)
    overlays.append({
        "type": "cta", "start": float(cta_start), "end": float(cta_end),
        "template": cta_template.id,
        "params": {"text": "ПОДПИСАТЬСЯ"},
        "why": "§6: кнопка подписки в последние 2 сек",
    })
    return overlays


def build_variant(ctx, plan: dict[str, Any], words_doc: dict[str, Any],
                  assets: dict[int, dict[str, Any]], prepared: dict[int, dict[str, Any]],
                  catalog: TemplateCatalog, avatar_meta: dict[str, Any],
                  sfx_map: dict[str, Any], *, variant: str,
                  recent_videos: list[str]) -> dict[str, Any]:
    seed = _variant_seed(plan["video_id"], variant)
    used_templates: list[str] = []
    slots = plan["slots"]
    shots: list[dict[str, Any]] = []

    fullscreen_styles = (["text-fullscreen/impact-01", "text-fullscreen/impact-02"]
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
            template = catalog.pick("text-fullscreen", duration=float(slot["duration"]),
                                    recent_videos=recent_videos, exclude=used_templates,
                                    prefer=[slot.get("template_hint", "")] + fullscreen_styles,
                                    seed=seed)
            used_templates.append(template.id)
            entry.update({
                "content": slot.get("content", ""),
                "template": template.id,
                "invert": bool(template.params.get("invert")) or variant == "B",
                "accent_word": None,
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
            kb_template = catalog.pick("kenburns", duration=float(slot["duration"]),
                                       recent_videos=recent_videos, exclude=used_templates,
                                       seed=seed + slot["index"])
            used_templates.append(kb_template.id)

        transition_entry: dict[str, Any] | None = None
        if slot.get("transition_in") == "dynamic":
            category = "avatar-entry" if slot["kind"] in AVATAR_KINDS else "transitions"
            tr = catalog.pick(category, duration=0.24, recent_videos=recent_videos,
                              exclude=used_templates + ["transitions/cut"],
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
            "text_behind_head": bool(prep.get("text_behind_head")),
            "ai_generated": bool(asset.get("ai_generated")),
            "mock": bool(asset.get("mock")),
            "fit": prep.get("fit"), "focus": [prep.get("focus_x"), prep.get("focus_y")],
            "kenburns": ({"template": kb_template.id, **kb_template.params}
                         if kb_template else None),
            "transition": transition_entry,
        })
        shots.append(entry)

    overlays = _build_overlays(ctx, plan, words_doc["words"], catalog, variant=variant,
                               seed=seed, recent_videos=recent_videos, used=used_templates)

    # Субтитры: весь ролик, кроме кадров с полноэкранным текстом (§5.1).
    fs_windows = [(float(s["start"]), float(s["end"])) for s in slots
                  if s["kind"] == "fullscreen_text"]
    subtitles = []
    for word in words_doc["words"]:
        start, end = float(word["start"]), float(word["end"])
        if any(w_start <= start < w_end for w_start, w_end in fs_windows):
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
        },
        "avatar": avatar_meta.get("segments", []),
        "templates_used": used_templates,
        "cta_window": plan.get("cta_window"),
        "stats": plan.get("stats", {}),
    }


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
            variant=variant, recent_videos=recent_videos)
        plans[variant]["matting"] = matte_summary
        ctx.write(f"edit_plan_{variant}.json", plans[variant])

    # §15.12.2 — версии обязаны различаться минимум на 3 шаблонных позиции.
    ab_diff = None
    if len(variants) >= 2:
        a_templates = plans[variants[0]]["templates_used"]
        b_templates = plans[variants[1]]["templates_used"]
        ab_diff = diff_count(a_templates, b_templates)
        required = int(ctx.cfg.get("limits.ab_min_template_diff", 3))
        if ab_diff < required:
            raise RedshiftError(
                f"версии {variants[0]} и {variants[1]} различаются лишь {ab_diff} "
                f"шаблонными решениями, требуется {required} (§15.12.2)",
                code="AB_TOO_SIMILAR", diff=ab_diff, required=required,
                a=a_templates, b=b_templates)

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


def _recent_video_ids(ctx, *, limit: int = 3) -> list[str]:
    from ..lib.jsonio import read_json_or

    history = read_json_or(ctx.cfg.path("paths.cache_dir", "cache") / "run_history.json",
                           {"runs": []})
    return [r.get("video_id") for r in history.get("runs", [])][-limit:]
