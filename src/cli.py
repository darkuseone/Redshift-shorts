"""CLI REDSHIFT.

    python -m src.cli run --script scripts/redshift_0042.json
    python -m src.cli validate --script scripts/redshift_0042.json
    python -m src.cli run --script ... --from P7          # resume после падения
    python -m src.cli fonts-check
    python -m src.cli libraries --status
    python -m src.cli fill-libraries --kind sfx
    python -m src.cli maintenance
    python -m src.cli learn --video-id redshift_0042 --choice A
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from .errors import RedshiftError
from .lib.cache import StepCache
from .lib.config import load_config
from .lib.costs import CostLedger
from .lib.jsonio import read_json, write_json
from .lib.logging import get_logger, setup_logging
from .lib.storage import build_storage
from .pipeline import RunContext
from .steps import PIPELINE_STEPS, build_pipeline

_log = get_logger("cli")


def _make_context(args, cfg, *, video_id: str, script_path: Path) -> RunContext:
    work_dir = Path(args.work_dir) if args.work_dir else (cfg.path("paths.work_dir", "work") / video_id)
    output_dir = Path(args.output_dir) if getattr(args, "output_dir", None) else (
        cfg.path("paths.output_dir", "output") / video_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(
        level=cfg.get("logging.level", "INFO"),
        json_output=bool(cfg.get("logging.json", True)) and not args.pretty_logs,
        log_file=output_dir / cfg.get("paths.logs_subdir", "logs") / "pipeline.log",
    )

    costs = CostLedger(
        max_usd=cfg.get("budget.max_cost_per_video_usd", None),
        hard_stop=bool(cfg.get("budget.hard_stop_on_exceed", True)),
        video_id=video_id,
    )
    variants = tuple(cfg.get("render.ab_versions", ["A", "B"])) if cfg.get("features.ab_versions", True) else ("A",)
    return RunContext(
        video_id=video_id,
        cfg=cfg,
        work_dir=work_dir,
        output_dir=output_dir,
        script_path=script_path,
        cache=StepCache(work_dir, enabled=not args.no_cache),
        costs=costs,
        storage=build_storage(cfg),
        variants=variants,
        dry_run=getattr(args, "dry_run", False),
    )


def _load_cfg(args):
    return load_config(args.config, args.brandbook, overrides=args.set or [])


# --- команды -----------------------------------------------------------------

def cmd_run(args) -> int:
    cfg = _load_cfg(args)
    script_path = Path(args.script)
    script = read_json(script_path)
    video_id = script.get("meta", {}).get("video_id") or script_path.stem
    ctx = _make_context(args, cfg, video_id=video_id, script_path=script_path)

    _log.info("прогон стартовал", extra={
        "video_id": video_id, "work_dir": str(ctx.work_dir),
        "providers_mode": cfg.get("providers.mode", "auto"),
        "variants": ",".join(ctx.variants),
    })
    started = time.time()
    pipeline = build_pipeline()
    try:
        report = pipeline.run(
            ctx, from_step=args.from_step, to_step=args.to_step,
            only=args.only, force=args.force,
        )
    except RedshiftError as exc:
        report = {"video_id": video_id, "status": "failed", "error": exc.to_dict(),
                  "duration_sec": round(time.time() - started, 2),
                  "warnings": ctx.warnings, "cost_usd": ctx.costs.total_usd}
        write_json(ctx.opath("build_report.json"), report)
        ctx.costs.dump(ctx.opath("cost_report.json"))
        print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    ctx.costs.dump(ctx.opath("cost_report.json"))
    write_json(ctx.opath("run_report.json"), report)
    print(json.dumps({
        "status": report["status"],
        "video_id": video_id,
        "duration_sec": report["duration_sec"],
        "cost_usd": report["cost_usd"],
        "output": str(ctx.output_dir),
        "steps": [f"{s['step']}:{s['status']}" for s in report["steps"]],
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 2


def cmd_validate(args) -> int:
    from .p0_validate.validator import validate_script

    cfg = _load_cfg(args)
    setup_logging(level="INFO", json_output=False)
    script = read_json(args.script)
    try:
        validated = validate_script(script, cfg)
    except RedshiftError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    info = validated["_validation"]
    print(json.dumps({
        "ok": True,
        "video_id": validated["meta"]["video_id"],
        "estimated_duration_sec": info["estimated_duration_sec"],
        "blocks": len(validated["blocks"]),
        "warnings": info["warnings"],
        "cost_estimate_usd": info["cost_estimate"]["total_usd"],
        "fonts": [f["family"] for f in info["fonts"]],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_fonts_check(args) -> int:
    from .lib.fonts import read_font, validate_font

    cfg = _load_cfg(args)
    setup_logging(level="INFO", json_output=False)
    fonts_dir = cfg.path("paths.assets_dir", "assets") / "fonts"
    manifest = read_json(fonts_dir / "fonts_manifest.json")
    sample = cfg.brand("typography.required_sample_text", None)
    rows: list[dict[str, Any]] = []
    failed = 0
    for entry in manifest.get("fonts", []):
        path = fonts_dir / entry["file"]
        row: dict[str, Any] = {"file": entry["file"], "role": entry.get("role")}
        try:
            info = validate_font(path, require_cyrillic=True, sample_text=sample)
            row.update({"ok": True, "family": info.family, "glyphs": len(info.codepoints),
                        "license": info.license_url or info.license_description[:60]})
        except RedshiftError as exc:
            failed += 1
            row.update({"ok": False, "code": exc.code, "error": exc.message})
        except Exception as exc:  # noqa: BLE001
            failed += 1
            row.update({"ok": False, "error": str(exc)})
        rows.append(row)
    print(json.dumps({"ok": failed == 0, "fonts": rows}, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 2


def cmd_libraries(args) -> int:
    from .lib.manifest import library_status

    cfg = _load_cfg(args)
    setup_logging(level="INFO", json_output=False)
    print(json.dumps(library_status(cfg), ensure_ascii=False, indent=2))
    return 0


def cmd_fill_libraries(args) -> int:
    from .lib.library_filler import fill_libraries

    cfg = _load_cfg(args)
    setup_logging(level=cfg.get("logging.level", "INFO"), json_output=not args.pretty_logs)
    costs = CostLedger(max_usd=cfg.get("budget.max_cost_per_video_usd", None),
                       hard_stop=bool(cfg.get("budget.hard_stop_on_exceed", True)))
    result = fill_libraries(cfg, kinds=args.kind or ["sfx", "music", "memes"],
                            costs=costs, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_maintenance(args) -> int:
    from .lib.maintenance import run_maintenance

    cfg = _load_cfg(args)
    setup_logging(level="INFO", json_output=not args.pretty_logs)
    print(json.dumps(run_maintenance(cfg, dry_run=args.dry_run), ensure_ascii=False, indent=2))
    return 0


def cmd_learn(args) -> int:
    from .lib.learning import record_choice

    cfg = _load_cfg(args)
    setup_logging(level="INFO", json_output=False)
    result = record_choice(cfg, video_id=args.video_id, choice=args.choice,
                           note=args.note or "")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_templates(args) -> int:
    from .lib.templates import TemplateCatalog

    cfg = _load_cfg(args)
    setup_logging(level="INFO", json_output=False)
    catalog = TemplateCatalog.load(cfg)
    if args.category:
        items = catalog.by_category(args.category)
    else:
        items = catalog.all()
    print(json.dumps({
        "count": len(items),
        "by_category": catalog.counts(),
        "templates": [t.to_dict() for t in items] if args.verbose else [t.id for t in items],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_steps(args) -> int:
    pipeline = build_pipeline()
    print(json.dumps([
        {"step": s.name, "title": s.title, "inputs": list(s.inputs), "outputs": list(s.outputs)}
        for s in pipeline.steps
    ], ensure_ascii=False, indent=2))
    return 0


# --- разбор аргументов --------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="redshift", description="REDSHIFT — сборка YouTube Shorts")
    parser.add_argument("--config", default=None, help="путь к config.yaml")
    parser.add_argument("--brandbook", default=None, help="путь к brandbook.json")
    parser.add_argument("--set", action="append", metavar="KEY.PATH=VALUE",
                        help="точечный оверрайд конфига (можно несколько раз)")
    parser.add_argument("--pretty-logs", action="store_true", help="человекочитаемые логи вместо JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="полный прогон пайплайна")
    run.add_argument("--script", required=True)
    run.add_argument("--work-dir", default=None)
    run.add_argument("--output-dir", default=None)
    run.add_argument("--from", dest="from_step", choices=PIPELINE_STEPS, default=None)
    run.add_argument("--to", dest="to_step", choices=PIPELINE_STEPS, default=None)
    run.add_argument("--only", nargs="+", choices=PIPELINE_STEPS, default=None)
    run.add_argument("--force", action="store_true", help="игнорировать кэш шагов")
    run.add_argument("--no-cache", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)

    val = sub.add_parser("validate", help="только P0")
    val.add_argument("--script", required=True)
    val.set_defaults(func=cmd_validate)

    fc = sub.add_parser("fonts-check", help="проверка кириллицы и лицензий шрифтов")
    fc.set_defaults(func=cmd_fonts_check)

    lib = sub.add_parser("libraries", help="состояние библиотек ассетов и лимитов")
    lib.add_argument("--status", action="store_true", default=True)
    lib.set_defaults(func=cmd_libraries)

    fill = sub.add_parser("fill-libraries", help="дозаполнение SFX/музыки/мемов до лимитов")
    fill.add_argument("--kind", nargs="+", choices=["sfx", "music", "memes"], default=None)
    fill.add_argument("--dry-run", action="store_true")
    fill.set_defaults(func=cmd_fill_libraries)

    mnt = sub.add_parser("maintenance", help="LRU-очистка кэша футажей и отчёты")
    mnt.add_argument("--dry-run", action="store_true")
    mnt.set_defaults(func=cmd_maintenance)

    learn = sub.add_parser("learn", help="записать выбор версии A/B")
    learn.add_argument("--video-id", required=True)
    learn.add_argument("--choice", required=True, choices=["A", "B"])
    learn.add_argument("--note", default=None)
    learn.set_defaults(func=cmd_learn)

    tpl = sub.add_parser("templates", help="каталог шаблонов")
    tpl.add_argument("--category", default=None)
    tpl.add_argument("--verbose", action="store_true")
    tpl.set_defaults(func=cmd_templates)

    st = sub.add_parser("steps", help="контракты шагов пайплайна")
    st.set_defaults(func=cmd_steps)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for attr in ("work_dir", "no_cache", "dry_run"):
        if not hasattr(args, attr):
            setattr(args, attr, None if attr == "work_dir" else False)
    try:
        return int(args.func(args))
    except RedshiftError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        print("прервано пользователем", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
