"""Выдача готового ролика в GitHub Releases.

Артефакты Actions живут две недели и прячутся в прогоне. Заказчик скачивает
mp4 с страницы Releases: тема → прогон → QC → релиз → ссылка.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..errors import QCFailed, RedshiftError
from .jsonio import read_json, read_json_or

GhRunner = Callable[..., subprocess.CompletedProcess]


@dataclass
class ReleaseBundle:
    video_id: str
    title: str
    tag: str
    variant: str
    qc_passed: bool
    qc_passed_count: int | None
    qc_total: int | None
    duration_sec: float | None
    mp4: Path
    files: list[Path]
    notes: str
    extra: dict[str, Any] = field(default_factory=dict)


def infer_repo(remote: str | None = None) -> str:
    """``owner/repo`` из GITHUB_REPOSITORY или git remote."""
    env = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if env and "/" in env:
        return env
    url = (remote or "").strip()
    if not url:
        try:
            url = subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            url = ""
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)", url)
    if not match:
        raise RedshiftError(
            "не удалось определить GitHub-репозиторий: задайте --repo owner/repo",
            code="PUBLISH_NO_REPO",
        )
    return f"{match.group('owner')}/{match.group('repo')}"


def _qc_blob(report: dict[str, Any], variant: str) -> dict[str, Any]:
    qc = report.get("qc") or {}
    blob = qc.get(variant) or {}
    if not blob and len(qc) == 1:
        blob = next(iter(qc.values()))
    return blob if isinstance(blob, dict) else {}


def _pick_mp4(output_dir: Path, video_id: str, variant: str) -> Path:
    candidates = [
        output_dir / f"{video_id}_{variant}.mp4",
        output_dir / f"{video_id}.mp4",
    ]
    for path in candidates:
        if path.is_file():
            return path
    found = sorted(p for p in output_dir.glob("*.mp4")
                   if "rejected" not in p.parts and p.stat().st_size > 0)
    if found:
        return found[0]
    raise RedshiftError(
        f"в {output_dir} нет mp4 для выдачи",
        code="PUBLISH_NO_MP4", video_id=video_id,
    )


def build_notes(bundle: dict[str, Any]) -> str:
    """Текст релиза: что скачивать и чем ролик закрыт."""
    title = bundle.get("title") or bundle["video_id"]
    lines = [
        f"## {title}",
        "",
        f"- id: `{bundle['video_id']}`",
        f"- вариант: **{bundle.get('variant', 'A')}**",
    ]
    duration = bundle.get("duration_sec")
    if duration:
        lines.append(f"- длительность: **{float(duration):.1f} с**")
    passed = bundle.get("qc_passed_count")
    total = bundle.get("qc_total")
    if passed is not None and total is not None:
        mark = "пройден" if bundle.get("qc_passed") else "не пройден"
        lines.append(f"- QC: **{passed}/{total}** ({mark})")
    lines += [
        "",
        "Скачайте mp4 из Assets ниже — это готовый ролик 1080×1920.",
        "Рядом: превью, субтитры, metadata.",
        "",
    ]
    sources = bundle.get("sources") or []
    if sources:
        lines.append("### Источники")
        for src in sources:
            if not isinstance(src, dict):
                continue
            name = src.get("title") or src.get("domain") or "источник"
            url = src.get("url") or ""
            lines.append(f"- {name}" + (f" — {url}" if url else ""))
        lines.append("")
    hashtags = bundle.get("hashtags") or []
    if hashtags:
        lines.append(" ".join(str(h) for h in hashtags))
        lines.append("")
    extra = (bundle.get("notes_extra") or "").strip()
    if extra:
        lines.append(extra)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def collect_release(output_dir: Path, *, variant: str = "A",
                    notes_extra: str = "") -> ReleaseBundle:
    """Собрать файлы и карточку релиза из ``output/<id>/``."""
    output_dir = Path(output_dir)
    meta = read_json_or(output_dir / "metadata.json", {}) or {}
    report = read_json_or(output_dir / "build_report.json", {}) or {}
    video_id = str(meta.get("video_id") or output_dir.name)
    qc = _qc_blob(report, variant)
    qc_passed = bool(meta.get("qc_passed", qc.get("passed", False)))
    variant_info = (report.get("variants") or {}).get(variant) or {}
    mp4 = _pick_mp4(output_dir, video_id, variant)
    files: list[Path] = [mp4]
    for name in ("thumbnail.jpg", "subtitles.srt", "metadata.json"):
        path = output_dir / name
        if path.is_file():
            files.append(path)
    duration = variant_info.get("duration_sec") or qc.get("value")
    if duration is None:
        for check in qc.get("checks") or []:
            if check.get("id") == "QC-1" and check.get("value") is not None:
                duration = check["value"]
                break
    payload = {
        "video_id": video_id,
        "title": meta.get("title") or video_id,
        "variant": variant,
        "qc_passed": qc_passed,
        "qc_passed_count": qc.get("passed_count"),
        "qc_total": qc.get("total"),
        "duration_sec": duration,
        "sources": meta.get("sources") or [],
        "hashtags": meta.get("hashtags") or [],
        "notes_extra": notes_extra,
    }
    return ReleaseBundle(
        video_id=video_id,
        title=str(payload["title"]),
        tag=video_id,
        variant=variant,
        qc_passed=qc_passed,
        qc_passed_count=qc.get("passed_count"),
        qc_total=qc.get("total"),
        duration_sec=None if duration is None else float(duration),
        mp4=mp4,
        files=files,
        notes=build_notes(payload),
        extra={"metadata": meta, "report_status": report.get("status")},
    )


def _stage_assets(bundle: ReleaseBundle, staging: Path) -> list[Path]:
    staged: list[Path] = []
    mp4_name = f"{bundle.video_id}.mp4"
    dest = staging / mp4_name
    shutil.copy2(bundle.mp4, dest)
    staged.append(dest)
    for path in bundle.files:
        if path.resolve() == bundle.mp4.resolve():
            continue
        if path.name == "thumbnail.jpg":
            name = f"{bundle.video_id}_thumbnail.jpg"
        elif path.name == "subtitles.srt":
            name = f"{bundle.video_id}.srt"
        else:
            name = f"{bundle.video_id}_{path.name}"
        target = staging / name
        shutil.copy2(path, target)
        staged.append(target)
    notes = staging / "NOTES.md"
    notes.write_text(bundle.notes, encoding="utf-8")
    return staged


def _gh(runner: GhRunner, args: list[str]) -> subprocess.CompletedProcess:
    return runner(["gh", *args], capture_output=True, text=True, check=False)


def publish_github(bundle: ReleaseBundle, *, repo: str,
                   runner: GhRunner = subprocess.run,
                   dry_run: bool = False,
                   draft: bool = False,
                   target: str | None = None,
                   require_qc: bool = True) -> dict[str, Any]:
    """Создать или обновить GitHub Release. QC — входной билет."""
    if require_qc and not bundle.qc_passed:
        raise QCFailed(
            f"{bundle.video_id}: QC не пройден — в Releases не кладём",
            video_id=bundle.video_id,
        )
    payload = {
        "video_id": bundle.video_id,
        "tag": bundle.tag,
        "title": f"{bundle.video_id} — {bundle.title}",
        "repo": repo,
        "draft": draft,
        "files": [str(p) for p in bundle.files],
        "html_url": f"https://github.com/{repo}/releases/tag/{bundle.tag}",
    }
    if dry_run:
        payload["dry_run"] = True
        payload["notes"] = bundle.notes
        return payload

    with tempfile.TemporaryDirectory(prefix="redshift-release-") as tmp:
        staged = _stage_assets(bundle, Path(tmp))
        create = [
            "release", "create", bundle.tag,
            *[str(p) for p in staged],
            "--repo", repo,
            "--title", payload["title"],
            "--notes", bundle.notes,
        ]
        if draft:
            create.append("--draft")
        if target:
            create.extend(["--target", target])
        created = _gh(runner, create)
        if created.returncode != 0:
            err = (created.stderr or created.stdout or "").lower()
            already = "already exists" in err or "release already exists" in err
            if not already:
                raise RedshiftError(
                    f"gh release create не удался: {(created.stderr or created.stdout or '').strip()}",
                    code="PUBLISH_FAILED", video_id=bundle.video_id,
                    stderr=created.stderr, stdout=created.stdout,
                )
            upload = _gh(runner, [
                "release", "upload", bundle.tag,
                *[str(p) for p in staged],
                "--repo", repo, "--clobber",
            ])
            if upload.returncode != 0:
                raise RedshiftError(
                    f"gh release upload не удался: {(upload.stderr or upload.stdout or '').strip()}",
                    code="PUBLISH_FAILED", video_id=bundle.video_id,
                    stderr=upload.stderr, stdout=upload.stdout,
                )
            payload["updated"] = True
        else:
            payload["created"] = True
        view = _gh(runner, [
            "release", "view", bundle.tag, "--repo", repo, "--json", "url,htmlUrl,tagName",
        ])
        if view.returncode == 0 and view.stdout:
            payload["gh"] = view.stdout.strip()
            match = re.search(r"https://github\.com/[^\s\"]+/releases/[^\s\"]+", view.stdout)
            if match:
                payload["html_url"] = match.group(0)
    return payload


def discover_output_ids(output_root: Path) -> list[str]:
    root = Path(output_root)
    if not root.is_dir():
        return []
    ids = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "metadata.json").is_file():
            ids.append(child.name)
    return ids
