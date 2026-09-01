"""Оркестратор пайплайна P0…P12 (§7.1).

Свойства, которых требует ТЗ:

* **идемпотентность** — шаг сверяет fingerprint входа с кэшем и не тратит
  кредиты повторно (§7.6);
* **resume** — падение на шаге N не требует перезапуска с P0 (§7.1): состояние
  живёт в рабочем каталоге прогона, ``--from/--only`` позволяют дожать хвост;
* **контракты** — у каждого шага объявлены входы/выходы из таблицы §7.1, и
  оркестратор проверяет их наличие, а не полагается на добрую волю шага.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .errors import RedshiftError
from .lib.cache import StepCache, code_fingerprint, hash_files, hash_obj
from .lib.config import Config
from .lib.costs import CostLedger
from .lib.jsonio import read_json, read_json_or, write_json
from .lib.logging import get_logger
from .lib.storage import StorageBackend

_log = get_logger("pipeline")


@dataclass
class RunContext:
    """Всё, что нужно шагу: конфиг, пути, кэш, журнал расходов, storage."""

    video_id: str
    cfg: Config
    work_dir: Path
    output_dir: Path
    script_path: Path
    cache: StepCache
    costs: CostLedger
    storage: StorageBackend
    variants: tuple[str, ...] = ("A", "B")
    dry_run: bool = False
    warnings: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)

    # --- пути ---
    def wpath(self, *parts: str) -> Path:
        p = self.work_dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def opath(self, *parts: str) -> Path:
        p = self.output_dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # --- артефакты шагов ---
    def read(self, name: str) -> Any:
        return read_json(self.work_dir / name)

    def read_or(self, name: str, default: Any) -> Any:
        return read_json_or(self.work_dir / name, default)

    def write(self, name: str, data: Any) -> Path:
        return write_json(self.wpath(name), data)

    def exists(self, name: str) -> bool:
        return (self.work_dir / name).exists()

    def warn(self, message: str, **fields: Any) -> None:
        self.warnings.append(message)
        _log.warning(message, extra=fields)

    @property
    def repo_root(self) -> Path:
        return self.cfg.repo_root


StepFn = Callable[[RunContext], dict[str, Any] | None]


@dataclass
class Step:
    """Шаг пайплайна с объявленным контрактом (§7.1)."""

    name: str
    title: str
    fn: StepFn
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    # Файлы репозитория, которые шаг читает помимо артефактов прогона:
    # брендбук, словарь произношений, накопленные предпочтения монтажа.
    # Не объявишь — шаг вернётся из кэша с результатом по старому файлу.
    config_inputs: tuple[str, ...] = ()
    # Файлы, которые шаг кладёт не в рабочий каталог, а в выдачу. Кэш обязан
    # проверять и их: рабочий каталог переживает прогон в кэше Actions, а
    # `output/` — нет. P12 объявлял выходом только свой отчёт, и возобновление
    # с него возвращалось «из кэша», не отрендерив ни одного ролика: прогон
    # №33508293306 закончился за две минуты и оставил выдачу пустой.
    # ``{video_id}`` и ``{variant}`` подставляются по контексту прогона.
    deliverables: tuple[str, ...] = ()
    version: str = "1"
    optional: bool = False          # шаг может быть пропущен по фиче-флагу
    cacheable: bool = True

    def deliverable_paths(self, ctx: "RunContext") -> tuple[Path, ...]:
        """Абсолютные пути к тому, что шаг обязан оставить в выдаче."""
        out: list[Path] = []
        for pattern in self.deliverables:
            names = ([pattern.format(video_id=ctx.video_id, variant=v)
                      for v in ctx.variants] if "{variant}" in pattern
                     else [pattern.format(video_id=ctx.video_id)])
            out += [ctx.output_dir / name for name in names]
        return tuple(out)

    def fingerprint(self, ctx: RunContext) -> str:
        """Хеш входа: версия шага + код шага + входные артефакты + конфиг."""
        payload: dict[str, Any] = {"step": self.name, "version": self.version,
                                   "code": code_fingerprint(self.fn.__module__)}
        for name in self.inputs:
            path = ctx.work_dir / name
            if path.exists():
                if path.suffix == ".json":
                    payload[name] = read_json_or(path, None)
                else:
                    payload[name] = path.stat().st_size
        if self.config_inputs:
            payload["_files"] = hash_files(
                str(ctx.cfg.repo_root / name) for name in self.config_inputs)
        payload["_cfg"] = {
            "limits": ctx.cfg.get("limits", {}),
            "audio": ctx.cfg.get("audio", {}),
            "render": ctx.cfg.get("render", {}),
            "features": ctx.cfg.get("features", {}),
            "providers_mode": ctx.cfg.get("providers.mode", "auto"),
        }
        return hash_obj(payload)


class Pipeline:
    def __init__(self, steps: Sequence[Step]) -> None:
        self.steps = list(steps)
        self._by_name = {s.name: s for s in self.steps}

    def names(self) -> list[str]:
        return [s.name for s in self.steps]

    def select(self, *, from_step: str | None = None, to_step: str | None = None,
               only: Iterable[str] | None = None) -> list[Step]:
        if only:
            wanted = set(only)
            unknown = wanted - set(self._by_name)
            if unknown:
                raise RedshiftError(f"неизвестные шаги: {sorted(unknown)}", code="CONFIG_ERROR")
            return [s for s in self.steps if s.name in wanted]
        start = 0
        end = len(self.steps)
        if from_step:
            if from_step not in self._by_name:
                raise RedshiftError(f"неизвестный шаг {from_step}", code="CONFIG_ERROR")
            start = self.names().index(from_step)
        if to_step:
            if to_step not in self._by_name:
                raise RedshiftError(f"неизвестный шаг {to_step}", code="CONFIG_ERROR")
            end = self.names().index(to_step) + 1
        return self.steps[start:end]

    def run(self, ctx: RunContext, *, from_step: str | None = None,
            to_step: str | None = None, only: Iterable[str] | None = None,
            force: bool = False) -> dict[str, Any]:
        selected = self.select(from_step=from_step, to_step=to_step, only=only)
        report: dict[str, Any] = {"video_id": ctx.video_id, "steps": [], "status": "ok"}
        started_all = time.time()

        for step in selected:
            entry: dict[str, Any] = {"step": step.name, "title": step.title}
            missing = [n for n in step.inputs if not (ctx.work_dir / n).exists()]
            if missing:
                raise RedshiftError(
                    f"шаг {step.name}: нет входных артефактов {missing}. "
                    f"Запустите с --from <более ранний шаг>",
                    code="MISSING_STEP_INPUT", step=step.name, missing=missing,
                )

            fp = step.fingerprint(ctx)
            expected = tuple(step.outputs) + step.deliverable_paths(ctx)
            if not force and step.cacheable and ctx.cache.is_fresh(step.name, fp, expected):
                _log.info("шаг из кэша", extra={"step": step.name})
                entry.update({"status": "cached", "duration_sec": 0.0})
                report["steps"].append(entry)
                continue

            _log.info("шаг стартовал", extra={"step": step.name, "title": step.title})
            started = time.time()
            try:
                result = step.fn(ctx) or {}
            except RedshiftError as exc:
                entry.update({"status": "failed", "error": exc.to_dict(),
                              "duration_sec": round(time.time() - started, 2)})
                report["steps"].append(entry)
                report["status"] = "failed"
                report["error"] = exc.to_dict()
                _log.error("шаг упал", extra={"step": step.name, **exc.to_dict()})
                raise
            except Exception as exc:  # noqa: BLE001 — оборачиваем в код
                wrapped = RedshiftError(f"шаг {step.name}: непредвиденная ошибка: {exc}",
                                        code="STEP_CRASHED", step=step.name,
                                        traceback=traceback.format_exc()[-2000:])
                entry.update({"status": "failed", "error": wrapped.to_dict(),
                              "duration_sec": round(time.time() - started, 2)})
                report["steps"].append(entry)
                report["status"] = "failed"
                report["error"] = wrapped.to_dict()
                _log.error("шаг упал", extra={"step": step.name, "error": str(exc)})
                raise wrapped from exc

            elapsed = round(time.time() - started, 2)
            produced_missing = [n for n in step.outputs if not (ctx.work_dir / n).exists()]
            if produced_missing and not step.optional:
                raise RedshiftError(
                    f"шаг {step.name} не создал заявленные выходы: {produced_missing}",
                    code="STEP_CONTRACT_VIOLATION", step=step.name, missing=produced_missing,
                )
            if step.cacheable:
                ctx.cache.record(step.name, fp, outputs=step.outputs, meta=result)
            entry.update({"status": "ok", "duration_sec": elapsed, "result": result})
            report["steps"].append(entry)
            _log.info("шаг завершён", extra={"step": step.name, "sec": elapsed})

        report["duration_sec"] = round(time.time() - started_all, 2)
        report["warnings"] = list(ctx.warnings)
        report["cost_usd"] = ctx.costs.total_usd
        return report
