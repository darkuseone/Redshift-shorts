#!/usr/bin/env python3
"""Короткий тестовый ролик из одного клипа аватара — быстрая проверка кадра.

Полный прогон стоит денег и двадцати минут, а посмотреть, как приём лежит на
**живом** ведущем, нужно раньше. Этот сборщик берёт один готовый клип аватара
(например, скачанный из HeyGen через MCP) и собирает из него ролик на его
длину: несколько шотов на одном непрерывном клипе, приёмы поверх, субтитр по
речи.

Не обходной путь мимо конвейера, а его же куски: тайминги слов считает
энергетический выравниватель P4, кадр собирает `CompositionBuilder` P11,
рендерит HyperFrames. Мимо идёт только P0 — там длительность ролика заперта в
35–70 секунд (§8.2), и десятисекундной пробе там делать нечего. Поэтому
QC-отчёта здесь тоже нет: проба судится глазами, а не отчётом.

Запуск:

    python tools/build_test_clip.py clip.webm --text "реплика, которую он говорит" \\
        --devices hero-paper,hero-bubble-typed -o test.mp4

Реплика обязана совпадать с тем, что в клипе произносится: по ней считаются
тайминги слов, и разойдясь, субтитр уедет. Вместо `--text` можно отдать блок
сценария целиком (`--block block.json`) — тогда приёмам достанутся и
`source_ref`, и `overlay`, и акцентное слово.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.lib.audio import load_wav                                     # noqa: E402
from src.lib.config import load_config                                 # noqa: E402
from src.lib.ffmpeg import alpha_opacity, has_alpha, probe, run   # noqa: E402
from src.lib.render.hyperframes import runner                          # noqa: E402
from src.lib.render.hyperframes.project import HyperFramesProject      # noqa: E402
from src.p4_align.aligner import align_by_energy, is_spoken_word       # noqa: E402
from src.p11_assemble.assemble import (                                # noqa: E402
    _HERO_NEEDS, _hero_content, hero_params,
)

# Приёмы по умолчанию — те, что показывают и материал источника, и речь.
DEFAULT_DEVICES = ("hero-paper", "hero-bubble-typed")


def _voice_track(clip: Path, dst: Path) -> Path:
    """Дорожка речи из клипа: по ней считаются тайминги слов."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(["-y", "-i", str(clip), "-ac", "1", "-ar", "48000", str(dst)],
        what="test_clip_voice")
    return dst


def _cuts(duration: float, devices: list[str]) -> list[tuple[float, float, str | None]]:
    """Разрезать клип на шоты: первый — чистый ведущий, дальше по приёму на шот.

    Первый шот без приёма намеренно: зритель обязан увидеть, кто говорит,
    прежде чем кадр начнёт им распоряжаться.
    """
    pieces = len(devices) + 1
    step = duration / pieces
    out: list[tuple[float, float, str | None]] = []
    for i in range(pieces):
        start = round(i * step, 3)
        end = round(duration if i == pieces - 1 else (i + 1) * step, 3)
        out.append((start, end, None if i == 0 else devices[i - 1]))
    return out


def build(clip: Path, block: dict, title: str, devices: list[str],
          out_path: Path, work: Path) -> dict:
    cfg = load_config()
    info = probe(clip)
    duration = round(info.duration_sec, 3)
    opacity = alpha_opacity(clip)
    alpha = has_alpha(clip)
    print(f"клип: {duration} c, "
          f"альфа: {'есть' if alpha else 'нет'}"
          f"{'' if opacity is None else f' (непрозрачных {opacity:.0%})'}")

    voice = _voice_track(clip, work / "voice.wav")
    audio, sr = load_wav(voice)
    tokens = [w for w in str(block["text"]).split() if is_spoken_word(w)]
    spans = align_by_energy(tokens, (0.0, duration), audio, sr)
    emphasis = str(block.get("emphasis_word") or "").lower()
    spoken = [{"display": w.strip(".,:;—«»\"'"), "start": round(a, 3),
               "end": round(b, 3), "block_id": block["id"],
               "emphasis": bool(emphasis) and emphasis in w.lower()}
              for w, (a, b) in zip(tokens, spans)]

    manifest = json.loads((ROOT / "templates" / "manifest.json").read_text("utf-8"))
    by_renderer = {t["renderer"]: t for t in manifest["templates"]}

    shots = []
    for index, (start, end, renderer) in enumerate(_cuts(duration, devices)):
        slot = {"index": index, "start": start, "end": end, "duration": end - start,
                "role": block.get("role", "hook"), "block_id": block["id"],
                "kind": "avatar"}
        hero = None
        if renderer:
            template = by_renderer.get(renderer)
            if template is None:
                raise SystemExit(f"нет шаблона с рендерером {renderer}")
            content = _hero_content(block, slot, None, (540, 700), title=title,
                                    words=[w for w in spoken
                                           if w["end"] > start and w["start"] < end])
            missing = [k for k in _HERO_NEEDS.get(renderer, ()) if not content.get(k)]
            if missing:
                raise SystemExit(
                    f"приёму {renderer} нечем наполниться: нет {', '.join(missing)}")
            hero = {
                "template": template["id"], "renderer": renderer,
                "params": hero_params(renderer, template.get("params", {}),
                                      content, slot),
                "file": None, "duration": None,
                "carries_line": bool({"lines", "punch", "entries"}
                                     & set(_HERO_NEEDS.get(renderer, ()))),
                "why": "тестовый ролик",
            }
        shots.append({
            "index": index, "start": start, "end": end, "duration": end - start,
            "kind": "avatar", "block_id": block["id"],
            "role": block.get("role", "hook"), "mode": "A",
            "reason": "режим A: аватар во весь кадр", "file": None,
            "asset_id": "avatar_seg_0", "source": "heygen",
            "license": "HeyGen ToS (цифровой двойник заказчика)", "attribution": "",
            "page_url": "", "avatar_offset_sec": None,
            "matte": {"available": alpha, "source": "heygen", "usable": alpha},
            "background": "vfx" if alpha else None, "text_behind_head": False,
            "ai_generated": False, "mock": False, "fit": "avatar_composite",
            "focus": [None, None], "kenburns": None,
            "transition": {"template": "transitions/cut", "renderer": "cut",
                           "duration": 0.0, "params": {}},
            "hero": hero,
        })

    # Приём, который сам выкладывает реплику, глушит субтитр на своём окне —
    # то же правило, что и в конвейере: пословное слово поверх той же фразы и
    # дубль, и перекрытие карточки.
    mute = [(s["start"], s["end"]) for s in shots
            if (s.get("hero") or {}).get("carries_line")]
    subtitles = [w for w in spoken
                 if not any(w["start"] < b and w["end"] > a for a, b in mute)]
    print(f"субтитр: {len(subtitles)} слов из {len(spoken)}, "
          f"приёмов: {len(devices)}")

    plan = {
        "video_id": out_path.stem, "variant": "A", "fps": 30,
        "resolution": [1080, 1920], "duration_sec": duration,
        "audio": {"mix": voice.name},
        "shots": shots, "overlays": [], "subtitles": subtitles,
        "subtitle_style": {"mode": cfg.brand("subtitles.readability_mode", "stroke"),
                           "baseline_y": cfg.brand("subtitles.baseline_y_default", 975)},
        "avatar": [{
            "index": 0, "start": 0.0, "end": duration, "duration": duration,
            "block_id": block["id"], "file": str(clip),
            "face_bbox": [340, 350, 740, 750], "has_alpha": alpha,
            "provider_mode": "prepared", "mode": "A", "kind": "avatar",
            "slot_indices": [s["index"] for s in shots], "text": block["text"],
        }],
        "templates_used": [s["hero"]["template"] for s in shots if s["hero"]],
        "cta_window": [duration, duration],
        "matting": {"enabled": alpha, "source": "heygen"},
    }
    (work / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")

    project = HyperFramesProject(work / "hf", cfg)
    project.prepare(plan, voice, blocks=[block])
    runner.lint(work / "hf")
    result = runner.render(work / "hf", out_path, fps=30,
                           crf=int(cfg.get("render.crf", 19)),
                           quality=str(cfg.get("render.hyperframes_quality", "high")))
    print(f"готово: {out_path} ({out_path.stat().st_size // 1024} КБ, "
          f"{result.get('frames')} кадров)")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip", type=Path, help="клип аватара (.webm/.mov/.mp4)")
    parser.add_argument("-o", "--out", type=Path, default=Path("test_clip.mp4"))
    parser.add_argument("--text", help="реплика, произносимая в клипе")
    parser.add_argument("--block", type=Path,
                        help="блок сценария целиком (json) вместо --text")
    parser.add_argument("--title", default="", help="тема ролика для приёмов")
    parser.add_argument("--emphasis", default="", help="акцентное слово реплики")
    parser.add_argument("--devices", default=",".join(DEFAULT_DEVICES),
                        help="рендереры приёмов через запятую, по одному на шот")
    parser.add_argument("--work", type=Path, default=Path("work") / "test_clip")
    args = parser.parse_args()

    if args.block:
        block = json.loads(args.block.read_text("utf-8"))
    elif args.text:
        block = {"id": "t1", "role": "hook", "text": args.text,
                 "emphasis_word": args.emphasis}
    else:
        parser.error("нужен --text или --block: по реплике считаются тайминги слов")
    block.setdefault("id", "t1")
    block.setdefault("role", "hook")

    if not args.clip.exists():
        raise SystemExit(f"нет клипа: {args.clip}")
    args.work.mkdir(parents=True, exist_ok=True)
    build(args.clip, block, args.title,
          [d.strip() for d in args.devices.split(",") if d.strip()],
          args.out, args.work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
