"""Правка сценария обязана отменять кэш шагов, которые сценарий читают.

0050, прогон 166: сборка шла с `--from P5`, запросы к стоку в сценарии были
исправлены — и P5–P11 приехали из кэша. Отпечаток шага подмешивал сценарий
только у шагов без входных файлов, а у P5 входные файлы есть. Рендер
переснял прежний план, правка молча не доехала, и понять это по зелёному
прогону было нельзя.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.steps import build_pipeline

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def ctx(tmp_path, cfg):
    """Минимальный контекст прогона: сценарий на диске и пустой work/."""
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"meta": {"video_id": "x"}, "blocks": []}),
                      encoding="utf-8")

    class _Ctx:
        script_path = script
        work_dir = tmp_path / "work"
        output_dir = tmp_path / "out"
        video_id = "x"
        variants = ("A",)

    _Ctx.work_dir.mkdir()
    _Ctx.cfg = cfg
    return _Ctx()


def _steps():
    return {s.name: s for s in build_pipeline().steps}


class TestTheScriptReachesTheFingerprint:

    @pytest.mark.parametrize("name", ["P5", "P7", "P8", "P11"])
    def test_editing_the_script_changes_the_fingerprint(self, name, ctx):
        step = _steps()[name]
        before = step.fingerprint(ctx)
        ctx.script_path.write_text(
            json.dumps({"meta": {"video_id": "x"},
                        "blocks": [{"broll_queries": ["rubberstamp"]}]}),
            encoding="utf-8")
        assert step.fingerprint(ctx) != before, (
            f"{name} не заметил правку сценария — кэш отдаст прежний результат")

    @pytest.mark.parametrize("name", ["P5", "P7", "P8", "P11"])
    def test_the_flag_is_declared(self, name):
        assert _steps()[name].uses_script is True


class TestVoiceIsDeliberatelyLeftOut:

    def test_p2_does_not_rerun_on_any_script_edit(self, ctx):
        """Переозвучка стоит денег и двигает границы фраз.

        Её судьбу решает срез речи (`input_slice`), а не правка соседнего
        поля вроде поискового запроса к стоку.
        """
        p2 = _steps()["P2"]
        assert p2.uses_script is False
        before = p2.fingerprint(ctx)
        ctx.script_path.write_text(
            json.dumps({"meta": {"video_id": "x"},
                        "blocks": [{"broll_queries": ["другой запрос"]}]}),
            encoding="utf-8")
        assert p2.fingerprint(ctx) == before
