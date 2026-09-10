"""GitHub Releases — выдача готового ролика заказчику."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cli import build_parser, main
from src.errors import QCFailed
from src.lib.jsonio import write_json
from src.lib.release import (
    build_notes, collect_release, infer_repo, publish_github,
)


def test_infer_repo_from_https_and_ssh():
    assert infer_repo("https://github.com/darkuseone/Redshift-shorts.git") == (
        "darkuseone/Redshift-shorts")
    assert infer_repo("git@github.com:darkuseone/Redshift-shorts.git") == (
        "darkuseone/Redshift-shorts")


def test_build_notes_lists_sources_and_qc():
    notes = build_notes({
        "video_id": "redshift_0042",
        "title": "Квантовый чип, который обогнал время",
        "variant": "A",
        "qc_passed": True,
        "qc_passed_count": 29,
        "qc_total": 29,
        "duration_sec": 44.5,
        "sources": [{"title": "Willow", "url": "https://blog.google/willow"}],
        "hashtags": ["#наука", "#shorts"],
        "notes_extra": "Первый выданный ролик.",
    })
    assert "44.5 с" in notes
    assert "29/29" in notes
    assert "https://blog.google/willow" in notes
    assert "Первый выданный ролик." in notes
    assert "1080×1920" in notes


def _write_output(root: Path, *, video_id: str = "redshift_0042",
                  qc_passed: bool = True) -> Path:
    out = root / video_id
    out.mkdir(parents=True)
    (out / f"{video_id}_A.mp4").write_bytes(b"fake-mp4")
    (out / "thumbnail.jpg").write_bytes(b"jpg")
    (out / "subtitles.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n",
                                       encoding="utf-8")
    write_json(out / "metadata.json", {
        "video_id": video_id,
        "title": "Квантовый чип, который обогнал время",
        "qc_passed": qc_passed,
        "hashtags": ["#наука"],
        "sources": [{"title": "Nature", "url": "https://nature.com/x"}],
    })
    write_json(out / "build_report.json", {
        "video_id": video_id,
        "status": "ok" if qc_passed else "rejected",
        "variants": {"A": {"duration_sec": 44.53, "file": str(out / f"{video_id}_A.mp4")}},
        "qc": {"A": {"passed": qc_passed, "passed_count": 29 if qc_passed else 28,
                     "total": 29, "checks": [{"id": "QC-1", "value": 44.53}]}},
    })
    return out


def test_collect_release_from_output_tree(tmp_path):
    out = _write_output(tmp_path)
    bundle = collect_release(out)
    assert bundle.video_id == "redshift_0042"
    assert bundle.qc_passed is True
    assert bundle.mp4.name.endswith("_A.mp4")
    assert bundle.duration_sec == pytest.approx(44.53)
    names = {p.name for p in bundle.files}
    assert "thumbnail.jpg" in names
    assert "subtitles.srt" in names
    assert "Квантовый чип" in bundle.notes


def test_publish_refuses_failed_qc(tmp_path):
    out = _write_output(tmp_path, qc_passed=False)
    bundle = collect_release(out)
    with pytest.raises(QCFailed):
        publish_github(bundle, repo="darkuseone/Redshift-shorts", dry_run=True)


def test_publish_dry_run_does_not_call_gh(tmp_path):
    out = _write_output(tmp_path)
    bundle = collect_release(out, notes_extra="учебный релиз")

    def boom(*a, **k):
        raise AssertionError("gh не должен вызываться в dry-run")

    result = publish_github(bundle, repo="darkuseone/Redshift-shorts",
                            runner=boom, dry_run=True)
    assert result["dry_run"] is True
    assert result["tag"] == "redshift_0042"
    assert "releases/tag/redshift_0042" in result["html_url"]
    assert "учебный релиз" in result["notes"]


def test_publish_create_then_upload_on_exists(tmp_path):
    out = _write_output(tmp_path)
    bundle = collect_release(out)
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        from subprocess import CompletedProcess
        if argv[1:3] == ["release", "create"]:
            return CompletedProcess(argv, 1, stdout="", stderr="already exists")
        if argv[1:3] == ["release", "upload"]:
            return CompletedProcess(argv, 0, stdout="uploaded", stderr="")
        if argv[1:3] == ["release", "view"]:
            return CompletedProcess(
                argv, 0,
                stdout='{"url":"https://github.com/darkuseone/Redshift-shorts/releases/tag/redshift_0042"}',
                stderr="",
            )
        return CompletedProcess(argv, 1, stdout="", stderr="unexpected")

    result = publish_github(bundle, repo="darkuseone/Redshift-shorts", runner=fake_run)
    assert result["updated"] is True
    assert any(c[1:3] == ["release", "upload"] for c in calls)
    assert "redshift_0042.mp4" in " ".join(calls[1])


def test_cli_publish_help_mentions_releases():
    help_text = build_parser().format_help()
    assert "publish" in help_text
    pub = build_parser()._subparsers._group_actions[0].choices["publish"].format_help()
    assert "GitHub Releases" in pub


def test_cli_publish_dry_run(tmp_path, monkeypatch):
    _write_output(tmp_path)
    monkeypatch.chdir(tmp_path)
    code = main([
        "publish", "--video-id", "redshift_0042",
        "--output-dir", str(tmp_path),
        "--repo", "darkuseone/Redshift-shorts",
        "--dry-run",
    ])
    assert code == 0
