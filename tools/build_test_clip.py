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

Приём называется рендерером (`hero-paper`) или id шаблона
(`hero-devices/headline-behind-head`), когда у одного рендерера несколько
пресетов. Приёмам с материалом нужен `--plate` — кадр футажа: в конвейере он
приходит из соседнего шота, которого в пробе нет.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.lib.audio import (                                            # noqa: E402
    load_wav, measure_loudness_buffer, normalize_voice, save_wav, to_stereo,
)
from src.lib.backdrop import describe as scene_why                     # noqa: E402
from src.lib.backdrop import pick_scene, tone as scene_tone            # noqa: E402
from src.lib.config import load_config                                 # noqa: E402
from src.lib.ffmpeg import (alpha_opacity, has_alpha, head_box,   # noqa: E402
                            probe, run)
from src.lib.render.hyperframes import runner                          # noqa: E402
from src.lib.render.hyperframes.project import HyperFramesProject      # noqa: E402
from src.p4_align.aligner import align_by_energy, is_spoken_word       # noqa: E402
from src.p11_assemble.assemble import (                                # noqa: E402
    _FULL_FRAME_HEROES, _HERO_NEEDS, _backdrop_plate, _hero_content,
    hero_mutes_subtitle, hero_params,
)

# Приёмы по умолчанию — те, что показывают и материал источника, и речь.
DEFAULT_DEVICES = ("hero-paper", "hero-bubble-typed")


def _voice_track(clip: Path, dst: Path) -> tuple[Path, float, float]:
    """Дорожка речи из клипа, приведённая к канону громкости.

    HeyGen отдаёт клип заметно тише канона — измерено −27.4 LUFS против −14,
    разница в тринадцать децибел. В ролике это лечит P3, но проба шла мимо
    него и звучала «очень тихо»: заказчик услышал разницу раньше, чем её
    кто-либо измерил. Правило берётся у конвейера (`normalize_voice`), а не
    переписывается здесь — две копии одного правила расходятся.

    Возвращает (путь, LUFS исходника, применённый gain).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    raw = dst.with_name("voice_raw.wav")
    run(["-y", "-i", str(clip), "-ac", "1", "-ar", "48000", str(raw)],
        what="test_clip_voice")
    audio, sr = load_wav(raw)
    before = measure_loudness_buffer(audio, sr).integrated_lufs
    # Мерить и нормировать надо в той же раскладке каналов, в какой дорожка
    # уйдёт в ролик. BS.1770 суммирует мощность каналов, поэтому моно,
    # продублированное в стерео, измеряется на 3 LU громче: нормированная как
    # моно до −14 дорожка давала в готовом mp4 −11.2 LUFS. В конвейере это
    # учтено в P10 — здесь та же поправка, а не своя.
    stereo = to_stereo(audio)
    stereo, gain_db = normalize_voice(stereo, sr)
    save_wav(dst, stereo, sr)
    return dst, before, gain_db


# Сколько кадра оставить чистому ведущему, если приёмы просят всё.
CLEAN_MIN = 1.5


def _cuts(duration: float, devices: list[str],
          needs: list[float]) -> list[tuple[float, float, str | None]]:
    """Разрезать клип на шоты: первый — чистый ведущий, дальше по приёму на шот.

    Первый шот без приёма намеренно: зритель обязан увидеть, кто говорит,
    прежде чем кадр начнёт им распоряжаться.

    Нарезка **не** ровная. В каталоге у каждого приёма записано, сколько ему
    нужно, чтобы прочитаться (``duration_range``), и ровная нарезка эти числа
    игнорировала: набираемая карточка получала 2.39 с при заявленных 2.6 и
    показывала бы недобранную реплику. Проба, показавшая приём короче, чем он
    живёт в ролике, — это не проба, а другой приём.

    Минимумы берутся как доли; остаток раздаётся поровну. Если минимумы не
    влезают в клип вовсе, шоты делятся пропорционально им — короткий клип
    честнее показать сжатым, чем обрезать последний приём.
    """
    wants = [max(CLEAN_MIN, 0.0)] + [max(0.6, n) for n in needs]
    total = sum(wants)
    if total > duration:
        wants = [w * duration / total for w in wants]
    else:
        extra = (duration - total) / len(wants)
        wants = [w + extra for w in wants]

    out: list[tuple[float, float, str | None]] = []
    cursor = 0.0
    for i, want in enumerate(wants):
        start = round(cursor, 3)
        cursor = duration if i == len(wants) - 1 else cursor + want
        out.append((start, round(cursor, 3), None if i == 0 else devices[i - 1]))
    return out


def build(clip: Path, block: dict, title: str, devices: list[str],
          out_path: Path, work: Path, plate: Path | None = None) -> dict:
    cfg = load_config()
    info = probe(clip)
    duration = round(info.duration_sec, 3)
    opacity = alpha_opacity(clip)
    alpha = has_alpha(clip)
    # Голова меряется по альфе — от неё считаются приёмы, стоящие за ней.
    head = head_box(clip, at_sec=min(0.5, duration / 2)) if alpha else None
    print(f"клип: {duration} c, "
          f"альфа: {'есть' if alpha else 'нет'}"
          f"{'' if opacity is None else f' (непрозрачных {opacity:.0%})'}"
          f"{'' if head is None else f', голова {head}'}")

    voice, voice_lufs_before, voice_gain = _voice_track(clip, work / "voice.wav")
    print(f"голос: {voice_lufs_before:.1f} LUFS в клипе, "
          f"{voice_gain:+.1f} дБ до канона")
    audio, sr = load_wav(voice)
    tokens = [w for w in str(block["text"]).split() if is_spoken_word(w)]
    spans = align_by_energy(tokens, (0.0, duration), audio, sr)
    emphasis = str(block.get("emphasis_word") or "").lower()
    # Пунктуация остаётся в слове, как её держит конвейер («может.», а не
    # «может»). По ней приёмы режут реплику на куски: без неё «…комок газа. На
    # снимке…» слиплось в «комок газа На снимке» — видно на кадре пробы.
    spoken = [{"display": w, "start": round(a, 3),
               "end": round(b, 3), "block_id": block["id"],
               "emphasis": bool(emphasis) and emphasis in w.lower()}
              for w, (a, b) in zip(tokens, spans)]

    manifest = json.loads((ROOT / "templates" / "manifest.json").read_text("utf-8"))
    # Приём называется либо рендерером, либо id шаблона: у одного рендерера
    # бывает несколько пресетов («заголовок над головой» и «из-за головы» —
    # один `hero-headline` с разным кеглем и высотой), и проверять надо
    # именно тот, который встанет в кадр.
    catalog = {t["renderer"]: t for t in manifest["templates"]}
    catalog.update({t["id"]: t for t in manifest["templates"]})

    needs = [float((catalog.get(name) or {}).get("duration_range", [1.4, 4.0])[0])
             for name in devices]
    shots = []
    for index, (start, end, name) in enumerate(_cuts(duration, devices, needs)):
        slot = {"index": index, "start": start, "end": end, "duration": end - start,
                "role": block.get("role", "hook"), "block_id": block["id"],
                "kind": "avatar"}
        hero = None
        if name:
            template = catalog.get(name)
            if template is None:
                raise SystemExit(f"нет приёма {name}: ни рендерера, ни шаблона")
            renderer = template["renderer"]
            face = (((head[0] + head[2]) // 2, (head[1] + head[3]) // 2)
                    if head else (540, 700))
            content = _hero_content(block, slot, None, face, title=title,
                                    words=[w for w in spoken
                                           if w["end"] > start and w["start"] < end],
                                    head_box=head)
            # Материал приходит не из текста блока, а из соседнего кадра. В
            # пробе соседнего кадра нет, поэтому его отдают ключом --plate.
            if plate is not None:
                content["plate"] = {"src": str(plate), "credit": "проба"}
            missing = [k for k in _HERO_NEEDS.get(renderer, ()) if not content.get(k)]
            if missing:
                raise SystemExit(
                    f"приёму {renderer} нечем наполниться: нет {', '.join(missing)}")
            hero = {
                "template": template["id"], "renderer": renderer,
                "params": hero_params(renderer, template.get("params", {}),
                                      content, slot),
                # Материал приёма кладётся туда же, куда его кладёт конвейер, —
                # в `file`. Прямая подстановка абсолютного пути в `src` мимо
                # переноса медиа давала кадр без картинки: разметка ссылалась
                # на файл вне проекта.
                "file": str(plate) if plate is not None else None,
                "duration": None,
                **hero_mutes_subtitle(renderer),
                "why": "тестовый ролик",
            }
            if renderer in _FULL_FRAME_HEROES:
                # Заливка во весь кадр живёт секунду-две, а не весь шот —
                # то же ограничение, что и в конвейере.
                hero["duration"] = round(
                    min(slot["duration"], float(template["duration_range"][1])), 3)
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

    # Приём, который сам выкладывает реплику или закрывает кадр заливкой,
    # глушит субтитр на своём окне — правило берётся у конвейера, а не
    # переписывается здесь: две копии одного правила расходятся.
    mute = []
    for shot in shots:
        hero = shot.get("hero") or {}
        if not (hero.get("carries_line") or hero.get("covers_frame")):
            continue
        end = shot["end"]
        if hero.get("duration"):
            end = min(end, shot["start"] + float(hero["duration"]))
        mute.append((shot["start"], end))
    subtitles = [w for w in spoken
                 if not any(w["start"] < b and w["end"] > a for a, b in mute)]
    print(f"субтитр: {len(subtitles)} слов из {len(spoken)}, "
          f"приёмов: {len(devices)}")

    scene = pick_scene(title, str(block.get("text") or ""))
    print(f"фон: {scene} ({scene_why(scene)})")

    plan = {
        "video_id": out_path.stem, "variant": "A", "fps": 30,
        "backdrop": {"scene": scene, "tone": scene_tone(scene),
                     "plate": _backdrop_plate(cfg, scene)},
        "resolution": [1080, 1920], "duration_sec": duration,
        "audio": {"mix": voice.name},
        "shots": shots, "overlays": [], "subtitles": subtitles,
        "subtitle_style": {"mode": cfg.brand("subtitles.readability_mode", "stroke"),
                           "baseline_y": cfg.brand("subtitles.baseline_y_default", 975)},
        "avatar": [{
            "index": 0, "start": 0.0, "end": duration, "duration": duration,
            "block_id": block["id"], "file": str(clip),
            "face_bbox": list(head or [340, 350, 740, 750]), "has_alpha": alpha,
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
    parser.add_argument("--plate", type=Path,
                        help="кадр-материал для приёмов, которым нужен футаж")
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
          args.out, args.work, args.plate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
