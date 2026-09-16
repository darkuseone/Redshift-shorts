#!/usr/bin/env python3
"""Seed work/<video_id>/words.json from speech_map for --from P5."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: seed_words_from_speech_map.py <video_id> [work_root]", file=sys.stderr)
        return 2
    vid = args[0]
    root = Path(args[1]) if len(args) > 1 else Path("work")
    work = root / vid
    speech_path = work / "speech_map.json"
    words_path = work / "words.json"
    if words_path.is_file():
        print(f"words.json already present: {words_path}")
        return 0
    if not speech_path.is_file():
        print(f"speech_map.json missing: {speech_path}", file=sys.stderr)
        return 1
    sm = json.loads(speech_path.read_text(encoding="utf-8"))
    words: list[dict] = []
    idx = 0
    for block in sm.get("blocks") or []:
        bid = str(block.get("id") or "")
        role = str(block.get("role") or "")
        for w in block.get("words") or []:
            display = str(w.get("word") or w.get("display") or "")
            words.append({
                "index": idx,
                "display": display,
                "start": float(w.get("start") or 0.0),
                "end": float(w.get("end") or 0.0),
                "block_id": bid,
                "role": role,
                "emphasis": False,
                "spoken": [display] if display else [],
                "source": "speech_map_seed",
            })
            idx += 1
    doc = {
        "video_id": sm.get("video_id") or vid,
        "duration_sec": float(sm.get("duration_sec") or 0.0),
        "stats": {"count": len(words), "source": "seeded_from_speech_map"},
        "words": words,
    }
    words_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"words.json seeded from speech_map: {len(words)} words")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
