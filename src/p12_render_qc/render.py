"""P12: edit-планы → MP4, QC, артефакты прогона (§9, §11).

Шаг выдаёт всё, что перечислено в §9: два ролика, обложку, звук, субтитры,
метаданные для публикации, отчёт QC, отчёт по кредитам и манифест использованных
материалов с лицензиями — документ на случай спора по правам (§9.2).

Провал блокирующего QC (§11.1, §11.2) означает, что ролик **не выдаётся**: файл
переносится в ``rejected/``, а причина и таймкод пишутся в отчёт.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..errors import QCFailed
from ..lib.ffmpeg import make_thumbnail, probe, run as ffmpeg_run
from ..lib.costs import CostLedger
from ..lib.providers.generation import (
    GeminiImageGeneration, GrokImageGeneration, build_generation_provider,
)
from ..lib.endings import push_ring, record_ending
from ..lib.jsonio import read_json_or, write_json
from ..lib.logging import get_logger
from ..lib.render.compositor import Compositor
from ..lib.render.hyperframes import HyperFramesCompositor
from ..lib.render.layers import Ctx
from .overlays import build_overlay_renderer
from ..lib.palette import accent_share_max
from ..lib.phash import dhash_image, hamming
from ..lib.ffmpeg import extract_frames
from .qc import apply_semantic_qc, run_qc
from .vision_qc import run_vision_qc, sample_positions
from ..p8_broll_judge.judge import CRITIC_METRIC_KEYS, critic_metrics_payload
from ..p10_audio.audio_build import sfx_skipped_from_events

_log = get_logger("p12")


def _thumbnail_prompt(plan: dict[str, Any], script: dict[str, Any] | None,
                      *, variant: str = "A") -> str:
    """YouTube Shorts collage thumb: face + huge multi-color text + busy thematic bg."""
    meta = (script or {}).get("meta") or plan.get("meta") or {}
    title = str(meta.get("title") or plan.get("title") or "science short").strip()
    topic = str(meta.get("topic") or meta.get("category") or "").strip()
    punches: list[str] = []
    for block in (script or {}).get("blocks") or plan.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        ov = block.get("overlay") or {}
        if str(ov.get("type") or "") in ("fullscreen_text", "lower_third", "plaque"):
            c = str(ov.get("content") or "").strip()
            if c:
                punches.append(c.upper())
        ew = str(block.get("emphasis_word") or "").strip()
        if ew and ew.upper() not in {p.upper() for p in punches}:
            punches.append(ew.upper())
    if variant.upper() == "B" and len(punches) > 1:
        headline, alt = punches[1], punches[0]
    else:
        headline = punches[0] if punches else title.split(",")[0].upper()
        alt = punches[1] if len(punches) > 1 else (punches[0] if punches else "REDSHIFT")
    subject = topic or title
    return (
        "YouTube Shorts vertical thumbnail 9:16, maximalist collage cover, mobile-first, "
        "high contrast. Channel host face ONLY — recognizable Markus-like tech creator: "
        "adult man, long dark wavy hair, groomed beard, expressive intense eyes looking "
        "at camera, green shirt or green hoodie (Russian tech Shorts vibe), dramatic "
        "red/cyan rim light, large sharp cutout in foreground interacting with the scene. "
        "NO morph face, NO unknown/random face, NO stock-model look. Huge bold multi-color "
        f"Russian all-caps sans-serif brandbook text stacked 2-4 lines: primary «{headline}», "
        f"secondary «{alt}», colors white + bright yellow + brand red (#C8453D). "
        "Key facts/stats/tables MUST sit on visible frosted glass / glassmorphism cards "
        "(translucent dark panels, subtle white/red border, soft blur) — never floating "
        f"bare text. Busy thematic collage for «{subject}»: quantum computer fridge, "
        "qubit lattice, motherboard traces, deep-space nebula, Redshift black/red/white. "
        "Dense layered collage, grunge tech-noir, no watermark, no UI chrome, "
        "no tiny unreadable text."
    )


def make_shorts_thumbnail(ctx, *, out_file: Path, thumb: Path,
                          plan: dict[str, Any], script: dict[str, Any] | None,
                          variant: str) -> dict[str, Any]:
    """Обложка Shorts: Grok image, иначе кадр ffmpeg.

    ``render.thumbnail_mode``: ``auto`` (Grok → ffmpeg), ``grok``, ``gemini``
    (только при generation.allow_gemini), или ``ffmpeg``. Gemini по умолчанию
    не вызывается. Сбой/mock → ffmpeg fallback на ``thumbnail_time_sec``.
    """
    cfg = ctx.cfg
    mode = str(cfg.get("render.thumbnail_mode", "auto") or "auto").lower()
    time_sec = float(cfg.get("render.thumbnail_time_sec", 1.0))
    meta: dict[str, Any] = {"mode": "ffmpeg", "variant": variant}

    # skip_generate / generation.skip: ZERO gemini_image/grok_image — сразу ffmpeg.
    # skip_vision / vision.skip_live: тоже без live image (rebuild без paid APIs).
    skip_image = (bool(cfg.get("generation.skip", False))
                  or bool(cfg.get("vision.skip_live", False)))
    if skip_image and mode in ("auto", "gemini", "grok"):
        _log.warning("thumb: skip image API → ffmpeg",
                     extra={"variant": variant,
                            "generation.skip": bool(cfg.get("generation.skip", False)),
                            "vision.skip_live": bool(cfg.get("vision.skip_live", False))})
        mode = "ffmpeg"
        meta["skipped_ai"] = True

    if mode in ("auto", "gemini", "grok"):
        prev_params = None
        try:
            costs = getattr(ctx, "costs", None) or CostLedger(video_id=str(
                plan.get("video_id") or getattr(ctx, "video_id", "thumb")))
            thumb_extra = dict(cfg.get("render.thumbnail_grok_params", {}) or {})
            if thumb_extra:
                gen = cfg.data.setdefault("generation", {})
                prev_params = dict(gen.get("grok_image_params") or {})
                merged = dict(prev_params)
                merged.update(thumb_extra)
                gen["grok_image_params"] = merged
            provider = build_generation_provider(cfg, costs)
            # Prefer outer provider (may be FallbackGeneration) so 403→secondary works.
            leaf = getattr(provider, "primary", provider)
            if mode == "gemini" and not isinstance(leaf, GeminiImageGeneration):
                leaf = None
                for attr in ("primary", "secondary"):
                    inner = getattr(provider, attr, None)
                    if isinstance(inner, GeminiImageGeneration):
                        leaf = inner
                        provider = inner
                        break
            elif mode == "grok" and not isinstance(leaf, GrokImageGeneration):
                leaf = None
                for attr in ("primary", "secondary"):
                    inner = getattr(provider, attr, None)
                    if isinstance(inner, GrokImageGeneration):
                        leaf = inner
                        provider = inner
                        break
            live_image = isinstance(
                leaf, (GeminiImageGeneration, GrokImageGeneration))
            if live_image:
                prompt = _thumbnail_prompt(plan, script, variant=variant)
                raw = thumb.with_suffix(".ai.png")
                asset = provider.generate(
                    prompt, raw, kind="photo", duration_sec=0.0)
                src = Path(asset.path)
                ffmpeg_run(
                    ["-y", "-i", str(src), "-vf", "scale=1080:-2",
                     "-q:v", "2", str(thumb)],
                    what="shorts thumbnail jpeg",
                )
                if src.resolve() != thumb.resolve():
                    src.unlink(missing_ok=True)
                if raw.exists() and raw.resolve() != thumb.resolve():
                    raw.unlink(missing_ok=True)
                via = str((asset.meta or {}).get("still_from")
                          or ("gemini" if "gemini" in asset.model else "grok"))
                meta.update({
                    "mode": via,
                    "model": asset.model,
                    "prompt": prompt[:240],
                    "path": str(thumb),
                })
                _log.info("обложка AI", extra={
                    "variant": variant, "model": asset.model, "via": via})
                return meta
            _log.info("AI thumb недоступен — ffmpeg fallback",
                      extra={"variant": variant, "provider": type(provider).__name__})
        except Exception as exc:  # noqa: BLE001
            _log.warning("AI thumb сбой — ffmpeg fallback",
                         extra={"variant": variant, "err": str(exc)[:240]})
        finally:
            if prev_params is not None:
                cfg.data.setdefault("generation", {})["grok_image_params"] = prev_params

    make_thumbnail(out_file, thumb, time_sec=time_sec)
    meta["path"] = str(thumb)
    meta["time_sec"] = time_sec
    return meta




def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst)


def _assets_manifest(plan: dict[str, Any], accepted: dict[str, Any],
                     generated: dict[str, Any], avatar_meta: dict[str, Any],
                     sfx_map: dict[str, Any], cfg) -> dict[str, Any]:
    """§9.2 — лицензия каждого материала фиксируется поимённо."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for shot in plan["shots"]:
        asset_id = shot.get("asset_id")
        if not asset_id or asset_id in seen:
            continue
        seen.add(asset_id)
        items.append({
            "id": asset_id, "type": "video", "role": "broll",
            "source": shot.get("source"), "license": shot.get("license"),
            "attribution": shot.get("attribution", ""),
            "url_origin": shot.get("page_url", ""),
            "ai_generated": bool(shot.get("ai_generated")),
            "mock": bool(shot.get("mock")),
            "used_at_sec": [round(float(shot["start"]), 2)],
        })

    for event in sfx_map.get("events", []):
        if event.get("status") != "placed":
            continue
        asset_id = event.get("asset_id")
        if not asset_id or asset_id in seen:
            continue
        seen.add(asset_id)
        items.append({"id": asset_id, "type": "sfx", "role": event.get("role"),
                      "source": "synth", "license": "generated-owned (REDSHIFT)",
                      "used_at_sec": [round(float(event["t"]), 2)]})

    music = sfx_map.get("music", {})
    if music.get("asset_id"):
        items.append({"id": music["asset_id"], "type": "music", "role": music.get("mood"),
                      "source": "synth", "license": "generated-owned (REDSHIFT)"})

    if avatar_meta.get("segments"):
        items.append({
            "id": avatar_meta.get("avatar_id"), "type": "avatar",
            "source": "heygen", "license": "HeyGen ToS (цифровой двойник заказчика)",
            "segments": len(avatar_meta["segments"]),
            "mock": avatar_meta.get("provider_mode") == "mock",
        })

    unlicensed = [i["id"] for i in items if not i.get("license")]
    return {
        "video_id": plan["video_id"],
        "items": items,
        "count": len(items),
        "unlicensed": unlicensed,
        "ai_generated_count": sum(1 for i in items if i.get("ai_generated")),
        "mock_count": sum(1 for i in items if i.get("mock")),
    }


def _metadata(plan: dict[str, Any], script: dict[str, Any], qc: dict[str, Any],
              avatar_meta: dict[str, Any], cfg) -> dict[str, Any]:
    """§9 metadata.json + §10.3.3 отметка о синтетическом контенте."""
    meta = script.get("meta", {})
    sources = script.get("sources", [])
    topic_tags = [w.lower() for w in str(meta.get("topic", "")).split() if len(w) > 3][:5]
    hashtags = ["#наука", "#технологии", f"#{meta.get('category', 'tech')}", "#shorts",
                "#redshift"][:5]

    description_lines = [
        str(meta.get("title", "")),
        "",
        str(plan.get("cta", {}).get("text", "")) if plan.get("cta") else "",
        "",
        "Источники:",
    ]
    for source in sources:
        line = f"— {source.get('title', '')}"
        if source.get("url"):
            line += f" — {source['url']}"
        description_lines.append(line)
    description_lines += [
        "",
        "В ролике использован цифровой двойник ведущего и материалы, "
        "созданные с помощью ИИ.",
    ]

    return {
        "video_id": plan["video_id"],
        "title": meta.get("title") or meta.get("topic", ""),
        "description": "\n".join(line for line in description_lines if line is not None),
        "hashtags": hashtags,
        "tags": topic_tags + [meta.get("category", "")],
        "category": meta.get("category"),
        "language": meta.get("language", "ru"),
        "publish_date": meta.get("publish_date"),
        "sources": [{"title": s.get("title"), "domain": s.get("domain"), "url": s.get("url")}
                    for s in sources],
        "synthetic_content_disclosure": {
            # §10.3.3 — обязательная отметка при публикации.
            "altered_or_synthetic": True,
            "reasons": ["цифровой двойник ведущего (HeyGen)",
                        "синтезированная речь (ElevenLabs)"]
                       + (["сгенерированный ИИ видеоряд"] if qc.get("ai_share", 0) > 0 else []),
            "youtube_field": "altered_content=yes",
        },
        "medical_disclaimer": (
            "Материал носит исследовательский характер и не является медицинской "
            "рекомендацией." if meta.get("category") == "medicine" else None),
        "qc_passed": qc.get("passed", False),
    }


def _devices_report(plans: dict[str, dict]) -> dict:
    """Какие приёмы поставлены и чем каждый оправдан.

    Заказчик просил «понимать смысл, когда и какой шаблон использовать».
    Отчёт отвечает на это списком: приём, таймкод, признак блока. Приём без
    основания не запрещён — говорящая голова законно стоит и без него, — но
    он виден: строкой «без основания» и счётчиком внизу.
    """
    out: dict[str, dict] = {}
    for variant, plan in plans.items():
        placed: list[dict] = []
        for shot in plan.get("shots", []):
            hero = shot.get("hero") or {}
            if hero.get("renderer"):
                placed.append({"at": round(float(shot["start"]), 2),
                               "kind": "приём вокруг ведущего",
                               "template": hero.get("template", ""),
                               "grounded_on": hero.get("grounded_on", []),
                               "why": hero.get("why", "")})
            if shot.get("kind") == "fullscreen_text":
                placed.append({"at": round(float(shot["start"]), 2),
                               "kind": "полноэкранный текст",
                               "template": shot.get("template", ""),
                               "grounded_on": shot.get("grounded_on", []),
                               "why": shot.get("why_template", "")})
        for overlay in plan.get("overlays", []):
            placed.append({"at": round(float(overlay["start"]), 2),
                           "kind": str(overlay.get("type") or "оверлей"),
                           "template": overlay.get("template", ""),
                           "grounded_on": overlay.get("grounded_on", []),
                           "why": overlay.get("why", "")})
        placed.sort(key=lambda item: item["at"])
        grounded = sum(1 for item in placed if item["grounded_on"])
        out[variant] = {
            "count": len(placed),
            "grounded": grounded,
            "ungrounded": len(placed) - grounded,
            "placed": placed,
        }
    return out



def run_step(ctx) -> dict[str, Any]:
    cfg = ctx.cfg
    script = ctx.read("validated_script.json")
    cut_plan = ctx.read("cut_plan.json")
    accepted = ctx.read_or("accepted_assets.json", {}).get("accepted", {})
    generated = ctx.read_or("generated_assets.json", {}).get("generated", {})
    avatar_meta = ctx.read_or("avatar_meta.json", {"segments": []})
    sfx_map = ctx.read_or("sfx_map.json", {})

    render_ctx = Ctx.build(cfg)
    face_bboxes = {seg["block_id"]: tuple(seg["face_bbox"])
                   for seg in avatar_meta.get("segments", [])}

    results: dict[str, Any] = {}
    qc_reports: dict[str, Any] = {}
    variants = list(ctx.variants)

    engine = str(cfg.get("render.engine", "hyperframes"))

    for variant in variants:
        plan = ctx.read(f"edit_plan_{variant}.json")
        out_file = ctx.opath(f"{plan['video_id']}_{variant}.mp4")
        if engine == "hyperframes":
            compositor = HyperFramesCompositor(
                render_ctx, cfg, work_dir=ctx.work_dir,
                blocks=script.get("blocks", []))
        else:
            overlay_renderer = build_overlay_renderer(
                render_ctx, plan, avatar_face_bbox=face_bboxes)
            compositor = Compositor(render_ctx, cfg,
                                    overlay_renderer=overlay_renderer)

        _log.info("рендер стартовал", extra={"variant": variant,
                                             "file": out_file.name,
                                             "engine": engine})
        stats = compositor.render(plan, out_file, ctx.work_dir / "mix.wav")
        info = probe(out_file)

        # Доля акцента (§7.5). Кадры снимаются один раз и уходят дальше в
        # смысловой QC: `render_stats.accent_share_max` до этой волны оставался
        # нулём на пути HyperFrames, потому что его считал только старый
        # PIL-компоновщик, а бюджет 0.12 был объявлен и не измерялся ни разу.
        qc_frames = None
        try:
            qc_frames = extract_frames(
                out_file, ctx.wpath("qc", variant, ".k").parent,
                sample_positions(), width=540)
            accent = accent_share_max(qc_frames)
            stats.accent_share_max = float(accent["max"])
            stats.accent_by_family = {"red": accent["red"], "cyan": accent["cyan"]}
        except Exception as exc:                              # noqa: BLE001
            _log.warning("доля акцента не измерена", extra={"variant": variant,
                                                            "error": str(exc)})

        # Шов лупа (§6.3 R-4) — два дополнительных кадра, и только когда шов
        # обещан типом концовки: за один ролик это лишние 0.2 с ffmpeg, за сто
        # роликов — двадцать секунд впустую, если мерить всегда.
        if str((cut_plan.get("cta") or {}).get("type") or "") == "visual_loop_seam":
            try:
                # `extract_frames` берёт **относительные** позиции 0..1, а не
                # секунды: 0.1 с от конца — это доля, а не смещение.
                total = float(info.get("duration_sec") or plan["duration_sec"] or 0.0)
                tail_rel = max(0.0, (total - 0.1) / total) if total > 0.1 else 1.0
                seam_frames = extract_frames(
                    out_file, ctx.wpath("seam", variant, ".k").parent,
                    [0.0, tail_rel], width=540)
                if len(seam_frames) == 2:
                    stats.loop_seam_dhash_bits = hamming(
                        dhash_image(seam_frames[0]), dhash_image(seam_frames[1]))
            except Exception as exc:                          # noqa: BLE001
                _log.warning("шов лупа не измерен", extra={"variant": variant,
                                                           "error": str(exc)})

        qc = run_qc(ctx, plan=plan, cut_plan=cut_plan, render_stats=stats.to_dict(),
                    media=info, sfx_map=sfx_map, avatar_meta=avatar_meta,
                    accepted=accepted, generated=generated, script=script)
        qc_reports[variant] = qc

        if not qc["passed"]:
            rejected = ctx.opath("rejected", out_file.name)
            shutil.move(str(out_file), str(rejected))
            _log.error("QC не пройден — ролик не выдан", extra={
                "variant": variant,
                "failed": [c["id"] for c in qc["checks"] if not c["passed"]],
            })
            results[variant] = {"file": None, "rejected_file": str(rejected),
                                "qc_passed": False}
            continue

        # §11.2 — смысловой QC по готовому файлу. mismatch > 10 % и skip_live
        # блокируют выдачу так же, как §11.1.
        vision = run_vision_qc(ctx, video_path=out_file, plan=plan,
                               frames=qc_frames)
        qc = apply_semantic_qc(qc, vision)
        qc_reports[variant] = qc

        if not qc["passed"]:
            rejected = ctx.opath("rejected", out_file.name)
            shutil.move(str(out_file), str(rejected))
            _log.error("смысловой QC не пройден — ролик не выдан", extra={
                "variant": variant,
                "failed": [c["id"] for c in qc["checks"] if not c["passed"]],
            })
            results[variant] = {"file": None, "rejected_file": str(rejected),
                                "qc_passed": False}
            continue

        thumb = ctx.opath("thumbnail.jpg") if variant == variants[0] else \
            ctx.opath(f"thumbnail_{variant}.jpg")
        thumb_meta = make_shorts_thumbnail(
            ctx, out_file=out_file, thumb=thumb, plan=plan, script=script,
            variant=variant)
        results[variant] = {
            "file": str(out_file), "size_bytes": out_file.stat().st_size,
            "duration_sec": round(info.duration_sec, 3), "fps": info.fps,
            "resolution": [info.width, info.height],
            "thumbnail": str(thumb), "thumbnail_meta": thumb_meta,
            "qc_passed": True,
            "render_stats": stats.to_dict(),
        }
        _log.info("рендер завершён", extra={
            "variant": variant, "sec": round(info.duration_sec, 2),
            "mb": round(out_file.stat().st_size / 1e6, 1),
            "qc": f"{qc['passed_count']}/{qc['total']}",
        })

    # --- артефакты прогона (§9) -------------------------------------------
    _copy(ctx.work_dir / "voice_final.wav", ctx.opath("voice_final.wav"))
    _copy(ctx.work_dir / "subtitles.srt", ctx.opath("subtitles.srt"))
    for variant in variants:
        _copy(ctx.work_dir / f"edit_plan_{variant}.json",
              ctx.opath(f"edit_plan_{variant}.json"))

    primary_plan = ctx.read(f"edit_plan_{variants[0]}.json")
    manifest = _assets_manifest(primary_plan, accepted, generated, avatar_meta, sfx_map, cfg)
    write_json(ctx.opath("assets_manifest.json"), manifest)
    metadata = _metadata(primary_plan, script, qc_reports.get(variants[0], {}),
                         avatar_meta, cfg)
    write_json(ctx.opath("metadata.json"), metadata)

    all_passed = all(r.get("qc_passed") for r in results.values())
    candidates_doc = ctx.read_or("candidates.json", {})
    accepted_doc = ctx.read_or("accepted_assets.json", {})
    generated_doc = ctx.read_or("generated.json", {})
    search_report = dict(candidates_doc.get("search") or {})
    surplus = candidates_doc.get("surplus") or accepted_doc.get("surplus")
    if surplus:
        search_report["surplus"] = surplus
    critic = critic_metrics_payload(
        accepted_doc, generated=generated_doc, costs=ctx.costs,
        candidates=candidates_doc)
    cost_report = ctx.costs.to_dict()
    cost_report.update(critic)
    report = {
        "video_id": cut_plan["video_id"],
        "status": "ok" if all_passed else "qc_failed",
        "variants": results,
        "qc": qc_reports,
        "assets": {"count": manifest["count"], "unlicensed": manifest["unlicensed"],
                   "mock_count": manifest["mock_count"]},
        "warnings": list(ctx.warnings),
        "devices": _devices_report({v: ctx.read(f"edit_plan_{v}.json") for v in variants}),
        "cost_usd": ctx.costs.total_usd,
        # Деньги по сервисам, а не одной суммой: денежный DoD §4.4 требует
        # видеть, что elevenlabs=0 и heygen=0, а не только что итог невелик.
        "costs": cost_report,
        # Трассы подбора приёмов: `PickTrace` возвращался всеми вызовами
        # `picker.pick` и везде выбрасывался в `_`. Без него QC-25 и разбор
        # «почему выбран этот приём» нечем закрыть.
        "pick_traces": {v: ctx.read(f"edit_plan_{v}.json").get("pick_traces", [])
                        for v in variants},
        # MUST-016/017: запросы на слот + surplus до paid critic.
        "search": search_report,
        "sfx_skipped": list(
            sfx_map.get("sfx_skipped")
            or sfx_skipped_from_events(sfx_map.get("events") or [])),
    }
    report.update({k: critic[k] for k in CRITIC_METRIC_KEYS})
    ctx.write("build_report.json", report)
    write_json(ctx.opath("build_report.json"), report)
    _record_run(ctx, report, cut_plan)
    # Кольцо концовок (§6.4) сдвигается только на выданных роликах: прогон,
    # упавший на QC, ничем не закончился и права занимать тип не имеет.
    if all_passed:
        report["ending"] = record_ending(
            cfg, video_id=cut_plan["video_id"],
            kind=str((script.get("cta") or {}).get("type") or ""))
        # Кольца звука (§10.1, §10.3) — там же и по той же причине: два
        # соседних ролика не должны звучать одинаково при замороженной
        # библиотеке.
        report["rings"] = {
            "sfx_scenario": push_ring(cfg, "sfx_scenario_ring",
                                      str(sfx_map.get("scenario") or "")),
            "bed": push_ring(cfg, "bed_ring", str(sfx_map.get("bed_id") or "")),
        }
        ctx.write("build_report.json", report)
        write_json(ctx.opath("build_report.json"), report)

    if not all_passed:
        failed = {v: [c["id"] for c in q["checks"]
                      if not c["passed"] and c.get("blocking", True)]
                  for v, q in qc_reports.items()}
        raise QCFailed("ролик не прошёл блокирующий QC (§11.1) и не выдан",
                       failed_checks=failed)

    return {"variants": list(results), "qc": {v: q["passed"] for v, q in qc_reports.items()}}


def _record_run(ctx, report: dict[str, Any], cut_plan: dict[str, Any]) -> None:
    """История прогонов: нужна ротации шаблонов и QC-6/QC-17."""
    path = ctx.cfg.path("paths.cache_dir", "cache") / "run_history.json"
    history = read_json_or(path, {"runs": []})
    plan_a = ctx.read_or(f"edit_plan_{ctx.variants[0]}.json", {})
    history["runs"] = [r for r in history.get("runs", [])
                       if r.get("video_id") != cut_plan["video_id"]]
    history["runs"].append({
        "video_id": cut_plan["video_id"],
        "status": report["status"],
        "templates": plan_a.get("templates_used", []),
        "assets": [s.get("asset_id") for s in plan_a.get("shots", []) if s.get("asset_id")],
        "duration_sec": cut_plan["duration_sec"],
    })
    history["runs"] = history["runs"][-50:]
    write_json(path, history)
