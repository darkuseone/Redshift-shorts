"""P12: edit-планы → MP4, QC, артефакты прогона (§9, §11).

Шаг выдаёт всё, что перечислено в §9: два ролика, обложку, звук, субтитры,
метаданные для публикации, отчёт QC, отчёт по кредитам и манифест использованных
материалов с лицензиями — документ на случай спора по правам (§9.2).

Провал блокирующего QC (§11.1) означает, что ролик **не выдаётся**: файл
переносится в ``rejected/``, а причина и таймкод пишутся в отчёт.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..errors import QCFailed
from ..lib.ffmpeg import make_thumbnail, probe
from ..lib.jsonio import read_json_or, write_json
from ..lib.logging import get_logger
from ..lib.render.compositor import Compositor
from ..lib.render.hyperframes import HyperFramesCompositor
from ..lib.render.layers import Ctx
from .overlays import build_overlay_renderer
from .qc import run_qc
from .vision_qc import run_vision_qc

_log = get_logger("p12")


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

        # §11.2 — смысловой QC по готовому файлу. Не блокирует выдачу: он даёт
        # материал для правки правил, а решение о браке принимает §11.1.
        qc["vision"] = run_vision_qc(ctx, video_path=out_file, plan=plan)

        thumb = ctx.opath("thumbnail.jpg") if variant == variants[0] else \
            ctx.opath(f"thumbnail_{variant}.jpg")
        make_thumbnail(out_file, thumb,
                       time_sec=float(cfg.get("render.thumbnail_time_sec", 1.0)))
        results[variant] = {
            "file": str(out_file), "size_bytes": out_file.stat().st_size,
            "duration_sec": round(info.duration_sec, 3), "fps": info.fps,
            "resolution": [info.width, info.height],
            "thumbnail": str(thumb), "qc_passed": True,
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
    }
    ctx.write("build_report.json", report)
    write_json(ctx.opath("build_report.json"), report)
    _record_run(ctx, report, cut_plan)

    if not all_passed:
        failed = {v: [c["id"] for c in q["checks"] if not c["passed"]]
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
