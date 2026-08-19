#!/usr/bin/env python3
"""Фаза 2 двухфазного конвейера: забрать готовые клипы аватара в репозиторий.

Actions доходит до P6 без ключа HeyGen и оставляет `avatar_request.json`:
нарезанные куски речи и то, какой длины должен быть каждый клип. Клипы
генерируются снаружи — MCP-коннектором HeyGen из чата, — и возвращаются сюда
по ссылкам.

Скрипт не просто качает файлы. Он сверяет длительность каждого клипа с куском
речи, под который тот сгенерирован: P6 отбраковывает расхождение больше 0.20
сек как уехавший липсинк, и узнать об этом лучше здесь, за секунды, чем на
следующем прогоне Actions, за двадцать минут.

Запуск:
    python tools/fetch_avatar_clips.py work/redshift_0046/avatar_request.json urls.json

где urls.json — {"0": "https://…/seg0.mp4", "1": …} либо список ссылок по
порядку сегментов.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.lib.ffmpeg import probe  # noqa: E402

TOLERANCE_SEC = 0.20      # тот же допуск, что у PreparedAvatar
CHUNK = 1 << 20


def _download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as response, dst.open("wb") as out:
        while chunk := response.read(CHUNK):
            out.write(chunk)


def _suffix(url: str) -> str:
    tail = url.split("?", 1)[0].rsplit(".", 1)
    ext = f".{tail[-1].lower()}" if len(tail) == 2 else ""
    # Расширение решает, считается ли клип носителем альфы, поэтому чужое
    # расширение из ссылки не берём — только знакомые контейнеры.
    return ext if ext in (".mp4", ".mov", ".webm") else ".mp4"


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("использование: fetch_avatar_clips.py <avatar_request.json> <urls.json>",
              file=sys.stderr)
        return 2

    request = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    raw = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    segments = request["segments"]
    if isinstance(raw, list):
        if len(raw) != len(segments):
            print(f"ссылок {len(raw)}, сегментов {len(segments)} — списком так нельзя",
                  file=sys.stderr)
            return 1
        urls = {int(seg["index"]): url for seg, url in zip(segments, raw)}
    else:
        urls = {int(key): value for key, value in raw.items()}

    clips_dir = Path(request["clips_dir"])
    problems: list[str] = []

    for segment in segments:
        index = int(segment["index"])
        url = urls.get(index)
        if not url:
            problems.append(f"сегмент {index}: ссылки нет")
            continue
        dst = clips_dir / f"seg_{index:02d}{_suffix(url)}"
        _download(url, dst)

        want = float(segment["duration_sec"])
        got = probe(dst).duration_sec
        drift = abs(got - want)
        mark = "ok" if drift <= TOLERANCE_SEC else "РАСХОЖДЕНИЕ"
        print(f"seg_{index:02d}: {got:.2f} сек при нужных {want:.2f} — {mark}")
        if drift > TOLERANCE_SEC:
            problems.append(f"сегмент {index}: липсинк уедет на {drift:.2f} сек")

    if problems:
        print("\nне готово к возобновлению прогона:", file=sys.stderr)
        for problem in problems:
            print(f"  — {problem}", file=sys.stderr)
        return 1

    print(f"\nвсе {len(segments)} клипов на месте: {clips_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
