"""Композитор на HyperFrames — замена покадровому Python-композитору.

Интерфейс совпадает с ``lib.render.compositor.Compositor``: P12 не знает, какой
движок собирает кадр, и обе реализации отдают одинаковую статистику, поэтому 19
проверок QC (§11.1) работают без изменений.

Разница в том, откуда берётся картинка. Python-композитор рисовал каждый кадр
сам; здесь кадр описывается разметкой, а рисует его Chrome. Для режима A это
принципиально: фон, слово за головой и аватар с альфой становятся отдельными
слоями, а не сплющенным заранее файлом.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...logging import get_logger
from ..compositor import RenderStats
from . import runner
from .project import HyperFramesProject

_log = get_logger("hyperframes.compositor")


def _subtitle_coverage_sec(plan: dict[str, Any]) -> float:
    """Сколько секунд ролика занято субтитрами.

    Окна слов складываются объединением, а не суммой: соседние слова могут
    примыкать встык, и простая сумма завысила бы покрытие на стыках.
    """
    windows = sorted((float(w["start"]), float(w["end"]))
                     for w in plan.get("subtitles", []) if w.get("display"))
    total = 0.0
    cur_start: float | None = None
    cur_end = 0.0
    for start, end in windows:
        if cur_start is None:
            cur_start, cur_end = start, end
        elif start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
    if cur_start is not None:
        total += cur_end - cur_start
    return total


class HyperFramesCompositor:
    """Собирает ролик через HTML-композицию и CLI HyperFrames."""

    def __init__(self, ctx, cfg, *, work_dir: Path,
                 blocks: list[dict[str, Any]] | None = None) -> None:
        self.ctx = ctx
        self.cfg = cfg
        self.work_dir = work_dir
        self.blocks = blocks or []
        self.stats = RenderStats()

    def render(self, plan: dict[str, Any], out_path: Path,
               audio_path: Path | None = None) -> RenderStats:
        variant = plan.get("variant", "A")
        project_dir = self.work_dir / "hf" / str(variant)

        mix = audio_path or (self.work_dir / "mix.wav")
        if not mix.exists():
            raise FileNotFoundError(f"нет сведённой дорожки: {mix}")

        project = HyperFramesProject(project_dir, self.cfg)
        project.prepare(plan, mix, blocks=self.blocks)

        runner.lint(project_dir)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = runner.render(
            project_dir, out_path,
            fps=int(plan["fps"]),
            crf=int(self.cfg.get("render.crf", 19)),
            quality=str(self.cfg.get("render.hyperframes_quality", "high")),
        )

        duration = float(plan["duration_sec"])
        fps = int(plan["fps"])
        built = project.stats
        covered = _subtitle_coverage_sec(plan)
        self.stats = RenderStats(
            frames=result.get("frames") or int(round(duration * fps)),
            duration_sec=duration,
            shots=built["shots"],
            overlay_draws=built["overlay_draws"],
            # Кадры с субтитром и кадры с речью — это одно и то же окно:
            # субтитр держится ровно столько, сколько звучит слово (§5.1).
            subtitle_frames=int(round(covered * fps)),
            speech_frames=int(round(covered * fps)),
        )
        _log.info("HyperFrames: кадр собран", extra={
            "variant": variant, "frames": self.stats.frames,
            "shots": built["shots"], "avatar": built["avatar_clips"]})
        return self.stats
