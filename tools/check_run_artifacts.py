#!/usr/bin/env python3
"""Проверка артефактов прогона — используется в CI после сквозного mock-прогона.

Смотрит не «файлы на месте», а то, что ролик действительно годен: QC пройден,
хронометраж в коридоре, лицензии зафиксированы, отметка о синтетическом контенте
проставлена. Иначе зелёный CI ничего не гарантирует.

Запуск: python tools/check_run_artifacts.py output/redshift_0042
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REQUIRED = ("build_report.json", "cost_report.json", "metadata.json",
            "assets_manifest.json", "subtitles.srt", "voice_final.wav",
            "edit_plan_A.json", "edit_plan_B.json")


def _fail(problems: list[str], message: str) -> None:
    problems.append(message)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("использование: check_run_artifacts.py <output/<video_id>>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    problems: list[str] = []

    if not out.exists():
        print(f"нет каталога прогона: {out}", file=sys.stderr)
        return 1

    for name in REQUIRED:
        if not (out / name).exists():
            _fail(problems, f"нет артефакта §9: {name}")

    report_path = out / "build_report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("status") != "ok":
            _fail(problems, f"статус прогона {report.get('status')!r}, ожидался ok")
        for variant, qc in (report.get("qc") or {}).items():
            if qc.get("total") != 19:
                _fail(problems, f"{variant}: проверок {qc.get('total')}, §11.1 требует 19")
            if not qc.get("passed"):
                failed = [f["id"] for f in qc.get("failed", [])]
                _fail(problems, f"{variant}: провалены проверки {failed}")

        for variant, data in (report.get("variants") or {}).items():
            path = data.get("file")
            if not path or not Path(path).exists():
                _fail(problems, f"{variant}: файл ролика отсутствует")
                continue
            duration = float(data.get("duration_sec") or 0)
            if not 35.0 <= duration <= 70.0:
                _fail(problems, f"{variant}: длительность {duration} вне 35–70 сек")
            if data.get("resolution") != [1080, 1920]:
                _fail(problems, f"{variant}: разрешение {data.get('resolution')}, ожидалось 1080×1920")

    manifest_path = out / "assets_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("unlicensed"):
            _fail(problems, f"материалы без лицензии: {manifest['unlicensed']}")

    metadata_path = out / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        disclosure = metadata.get("synthetic_content_disclosure") or {}
        if not disclosure.get("altered_or_synthetic"):
            _fail(problems, "нет отметки о синтетическом контенте (§10.3.3)")

    if problems:
        print("ПРОВЕРКА НЕ ПРОЙДЕНА:", file=sys.stderr)
        for problem in problems:
            print(f"  — {problem}", file=sys.stderr)
        return 1

    print(f"артефакты прогона в порядке: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
