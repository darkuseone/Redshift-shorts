#!/usr/bin/env python3
"""Голос из чата → готовый голос ролика в ``assets/voice/<video_id>/``.

Режиссёр в чате синтезирует озвучку сам (ElevenLabs MCP, голос NIKITA2,
eleven_v3), заказчик слушает дубли и выбирает. Этот инструмент превращает
выбранный дубль в то, что станок берёт вместо P2: ``voice_final.wav``,
``speech_map.json``, ``draft_plan.json``. В Actions голос тогда не синтезируется
повторно и кредиты ElevenLabs не тратятся (``src/p2_tts/tts.py``,
``adopt_prepared_voice``).

Шаги внутри — настоящие P0/P1/P3 пайплайна, а не их копии: срез пауз,
драматические паузы ``silence_after_ms``, громкость −14 LUFS.

    # 1. Текст для синтеза: по блокам, с аудиотегами tts_text и ударениями
    python tools/voice_import.py prompt --script scripts/redshift_0052.json

    # 2. Выбранный дубль (+ пословные тайминги от ElevenLabs STT, если есть)
    python tools/voice_import.py import --script scripts/redshift_0052.json \\
        --audio take3.mp3 --words take3_stt.json --tempo 1.25

Темп: ElevenLabs отдаёт скорость до 1.2. Остальное добирается ``atempo``
без смены высоты голоса; ``--tempo 1.0`` — оставить как есть.
"""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.lib.director import norm_word  # noqa: E402


def _pipeline(script_path: Path, work: Path):
    """Контекст прогона + P0/P1 в отдельном рабочем каталоге."""
    from src.cli import _make_context
    from src.lib.config import load_config
    from src.p0_validate.validator import validate_script
    from src.p1_plan.planner import plan as plan_blocks

    cfg = load_config(None, None, overrides=["providers.mode=mock"])
    script = json.loads(script_path.read_text(encoding="utf-8"))
    video_id = script["meta"]["video_id"]
    args = Namespace(work_dir=str(work), output_dir=str(work / "_out"),
                     pretty_logs=True, no_cache=True, dry_run=False)
    ctx = _make_context(args, cfg, video_id=video_id, script_path=script_path)
    validated = validate_script(json.loads(script_path.read_text(encoding="utf-8")), cfg)
    ctx.write("validated_script.json", validated)
    draft = plan_blocks(validated, cfg)
    ctx.write("draft_plan.json", draft)
    return ctx, script, validated, draft


def _spoken_words(block: dict[str, Any]) -> list[str]:
    from src.p4_align.aligner import is_spoken_word
    out: list[str] = []
    for token in block.get("tokens") or []:
        out.extend(s for s in token.get("spoken") or [] if is_spoken_word(s))
    return out


def cmd_prompt(args) -> int:
    work = REPO / ".redshift_cache" / "voice_import" / "_prompt"
    _ctx, script, _validated, draft = _pipeline(Path(args.script).resolve(), work)
    by_id = {b["id"]: b for b in script["blocks"]}
    lines = []
    for block in draft["blocks"]:
        raw = by_id.get(block["id"], {})
        text = str(raw.get("tts_text") or block.get("spoken_text") or block["text"])
        pause = int(raw.get("silence_after_ms") or 0)
        lines.append(text)
        print(f"[{block['id']} · {block['role']}]{' · пауза ' + str(pause) + ' мс' if pause else ''}")
        print(f"  {text}\n")
    print("=== одним куском для ElevenLabs (eleven_v3, NIKITA2) ===")
    print(" ".join(lines))
    return 0


def _load_words(path: Path, tempo: float) -> list[dict[str, Any]]:
    """Пословные тайминги: ElevenLabs STT (words[type=word]) или список {word,start,end}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("words") if isinstance(data, dict) else data
    if isinstance(data, dict) and "transcripts" in data:
        items = (data["transcripts"][0] or {}).get("words")
    out = []
    for w in items or []:
        if str(w.get("type") or "word") != "word":
            continue
        text = str(w.get("text") or w.get("word") or "").strip()
        if not text:
            continue
        out.append({"word": text, "start": float(w["start"]) / tempo,
                    "end": float(w["end"]) / tempo})
    return out


def _monotonic(times: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Слова идут друг за другом: начало не раньше конца предыдущего.

    STT отдаёт короткие слова с общим началом («Так» и «что» — оба 24.677),
    и QC-10 отдаёт второе слово субтитру первого: дальше «что» ищет себе пару
    в хуке и рассинхрон выходит в 23 с. Наезд короче 40 мс — делим общий
    отрезок пополам, иначе просто сдвигаем начало за конец соседа.
    """
    out = [(float(s), max(float(e), float(s) + 0.04)) for s, e in times]
    for i in range(1, len(out)):
        ps, pe = out[i - 1]
        s, e = out[i]
        if s >= pe:
            continue
        if e > pe + 0.04:
            out[i] = (pe, e)
        else:
            hi = max(e, pe)
            mid = (ps + hi) / 2
            out[i - 1] = (ps, mid)
            out[i] = (mid, hi)
    return out


def _align(blocks: list[dict[str, Any]], heard: list[dict[str, Any]],
           audio_path: Path) -> list[dict[str, Any]]:
    """Сопоставить слова сценария с услышанными; дыры — интерполяцией/энергией."""
    import numpy as np
    from src.lib.audio import load_wav
    from src.p4_align.aligner import align_by_energy

    script_words: list[tuple[str, str]] = []   # (block_id, word)
    for block in blocks:
        script_words += [(block["id"], w) for w in _spoken_words(block)]
    audio, sr = load_wav(audio_path)
    audio = audio[:, 0] if audio.ndim == 2 else audio
    total = len(audio) / sr

    times: list[tuple[float, float] | None] = [None] * len(script_words)
    if heard:
        a = [norm_word(w) for _, w in script_words]
        b = [norm_word(h["word"]) for h in heard]
        matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
                for k in range(i2 - i1):
                    h = heard[j1 + k]
                    times[i1 + k] = (h["start"], h["end"])
            elif tag == "replace" and j2 > j1:
                # «100» против «сто»: делим услышанный кусок поровну.
                s, e = heard[j1]["start"], heard[j2 - 1]["end"]
                n = i2 - i1
                for k in range(n):
                    times[i1 + k] = (s + (e - s) * k / n, s + (e - s) * (k + 1) / n)
        # Интерполяция пропусков между известными соседями.
        known = [i for i, t in enumerate(times) if t is not None]
        for i, t in enumerate(times):
            if t is not None:
                continue
            left = max((k for k in known if k < i), default=None)
            right = min((k for k in known if k > i), default=None)
            lo = times[left][1] if left is not None else 0.0
            hi = times[right][0] if right is not None else total
            gap_words = (right if right is not None else len(times)) - (left if left is not None else -1) - 1
            pos = i - (left if left is not None else -1) - 1
            step = (hi - lo) / max(gap_words, 1)
            times[i] = (lo + step * pos, lo + step * (pos + 1))
    else:
        spans = align_by_energy([w for _, w in script_words], (0.0, total), audio, sr)
        times = list(spans)
    times = _monotonic(times)

    out = []
    cursor = 0
    for block in blocks:
        n = len(_spoken_words(block))
        chunk = [{"word": script_words[cursor + k][1],
                  "start": round(float(times[cursor + k][0]), 4),
                  "end": round(float(max(times[cursor + k][1], times[cursor + k][0] + 0.04)), 4)}
                 for k in range(n)]
        cursor += n
        out.append({"id": block["id"], "role": block["role"],
                    "start": chunk[0]["start"] if chunk else 0.0,
                    "end": chunk[-1]["end"] if chunk else 0.0,
                    "spoken_text": block.get("spoken_text", ""),
                    "chars": len(block.get("spoken_text", "")),
                    "words": chunk})
    return out


def cmd_import(args) -> int:
    from src.lib.ffmpeg import ffmpeg_bin
    from src.p3_speech_opt.optimizer import run_step as p3

    script_path = Path(args.script).resolve()
    video_id = json.loads(script_path.read_text(encoding="utf-8"))["meta"]["video_id"]
    work = REPO / ".redshift_cache" / "voice_import" / video_id
    if work.exists():
        shutil.rmtree(work)
    ctx, script, validated, draft = _pipeline(script_path, work)
    sr = int(ctx.cfg.get("elevenlabs.sample_rate", 48000))
    tempo = float(args.tempo)
    chain = []
    t = tempo
    while t > 2.0:
        chain.append("atempo=2.0")
        t /= 2.0
    if abs(t - 1.0) > 1e-3:
        chain.append(f"atempo={t:.4f}")
    af = ["-af", ",".join(chain)] if chain else []
    raw = ctx.wpath("voice_raw.wav")
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(Path(args.audio).resolve()),
                    *af, "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(raw)], check=True)

    heard = _load_words(Path(args.words), tempo) if args.words else []
    blocks_meta = _align(draft["blocks"], heard, raw)
    from src.lib.audio import load_wav
    audio, _ = load_wav(raw)
    meta = {
        "video_id": video_id, "sample_rate": sr,
        "duration_sec": round(len(audio) / sr, 3),
        "desired_sec": float(draft.get("tts_target_sec") or 0.0),
        "speed": tempo, "length_correction": None,
        "model": args.model, "provider_mode": "chat_import",
        "voice_id": args.voice_id, "block_gap_sec": 0.0,
        "has_provider_word_timings": bool(heard),
        "blocks": blocks_meta,
        "total_chars": sum(b["chars"] for b in blocks_meta),
    }
    ctx.write("tts_meta.json", meta)
    result = p3(ctx)

    out = Path(args.out) if args.out else REPO / "assets" / "voice" / video_id
    out.mkdir(parents=True, exist_ok=True)
    for name in ("voice_final.wav", "speech_map.json", "draft_plan.json", "validated_script.json"):
        shutil.copy2(work / name, out / name)
    (out / "voice_meta.json").write_text(json.dumps({
        "source": "chat", "audio": Path(args.audio).name, "voice_id": args.voice_id,
        "model": args.model, "tempo": tempo, "word_timings": "stt" if heard else "energy",
        "duration_sec": result.get("duration_sec"), "removed_sec": result.get("removed_sec"),
        "lufs": result.get("lufs"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), **result, "tempo": tempo,
                      "word_timings": "stt" if heard else "energy"}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prompt", help="текст для синтеза по блокам")
    p.add_argument("--script", required=True)
    p.set_defaults(fn=cmd_prompt)
    i = sub.add_parser("import", help="дубль из чата → assets/voice/<id>/")
    i.add_argument("--script", required=True)
    i.add_argument("--audio", required=True, help="mp3/wav дубля")
    i.add_argument("--words", default=None, help="JSON пословных таймингов (ElevenLabs STT)")
    i.add_argument("--tempo", default="1.0", help="доп. ускорение atempo (1.0–1.4)")
    i.add_argument("--voice-id", default="14NozJq5eoBmDc1FXFDq", help="NIKITA2")
    i.add_argument("--model", default="eleven_v3")
    i.add_argument("--out", default=None)
    i.set_defaults(fn=cmd_import)
    args = parser.parse_args(argv)
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
