#!/usr/bin/env python3
"""Прогнать композицию через настоящий lint HyperFrames, не тратя прогон Actions.

Зачем. Правила lint движка ловят то, чего не видит ни один наш тест: наезд
клипов на треке, затухание без гашения, видео внутри тайминга. Узнать про них
можно было только из упавшего прогона — а прогон стоит четверть часа и денег на
поиск футажа, и падает он в самом конце, после всей работы. Три захода подряд
на 0047 ушли именно так.

Здесь тот же lint запускается по синтетическому плану за несколько секунд. План
не про красоту: он собран так, чтобы в композицию попал **каждый** переход и
**каждый** приём вокруг ведущего, а субтитры легли встык с шагом, на котором
ломается округление границ (0.4996 сек — ровно тот случай, что уронил прогон).

Проверено: обе поломки 0047 воспроизводятся здесь и обе исчезают с правкой.

Запуск:
    python tools/lint_composition.py            # найдёт hyperframes сам
    python tools/lint_composition.py --bin path/to/hyperframes

Возвращает код lint: 0 — ошибок нет, предупреждения при этом печатаются.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.lib.config import load_config                              # noqa: E402
from src.lib.ffmpeg import ffmpeg_bin                               # noqa: E402
from src.lib.render.hyperframes.project import HyperFramesProject   # noqa: E402
from src.lib.render.hyperframes.templates import HERO, TRANSITIONS  # noqa: E402

# Шаг субтитра, на котором ломалось двойное округление: начало и длительность
# округлялись порознь и обе уезжали вверх. Держим его здесь нарочно.
WORD_STEP = 0.4996
SHOT_SEC = 2.4

# Один набор параметров на все приёмы: чего в нём нет, то приём молча не
# нарисует — вернёт пустой Piece, и lint такого шаблона просто не увидит.
# Поэтому здесь лежит по ключу на каждую нужду каталога, а `run` проверяет,
# что каждый приём и правда собрал узлы.
HERO_PARAMS: dict = {
    "content": "КОЛЬСКАЯ", "text": "двенадцать километров",
    "title": "Кольская", "lines": ["один", "два", "три"],
    "values": [3.0, 7.0, 12.0], "labels": ["а", "б", "в"],
    "value": 12262, "domain": "nature.com",
    "word": "ТЕЧЁТ", "caption": "порода течёт",
    "ask": "почему скважину закрыли",
    "answer": "порода начала течь",
    "gen_prompt": "покажи ствол скважины на глубине",
    "app": "ChatGPT",
    "head": "КОЛЬСКАЯ", "tail": "СВЕРХГЛУБОКАЯ",
    "punch": ["ПОРОДА", "ТЕЧЁТ"],
    "entries": [{"text": "двенадцать", "at": 0.2},
                {"text": "километров", "at": 0.8}],
    "figures": [{"value": "12 262", "label": "метров"},
                {"value": "220", "label": "°C"}],
    "icons": [{"glyph": "chip"}, {"glyph": "flask"}, {"glyph": "bolt"}],
    "label": "Кольская", "accent": "ТЕЧЁТ",
    "source": "nature.com", "quote": "порода перестаёт быть камнем",
    "detail": "двенадцать километров", "credit": "nature.com",
}


def _media(dst: Path) -> dict[str, Path]:
    """Минимальные заглушки материала. Lint смотрит разметку, а не картинку."""
    dst.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg_bin()
    files = {"shot": dst / "shot.mp4", "avatar": dst / "av.webm",
             "mix": dst / "mix.wav", "plate": dst / "plate.png"}
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"color=c=0x101014:s=1080x1920:d={SHOT_SEC + 1}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(files["shot"])],
                   check=True)
    # Аватар с настоящей альфой: без неё режим A собирается другой веткой.
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"color=c=0x202028:s=1080x1920:d={SHOT_SEC + 1}",
                    "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0",
                    "-crf", "40", "-auto-alt-ref", "0", str(files["avatar"])],
                   check=True)
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=220:duration=120", "-ac", "2",
                    "-ar", "48000", str(files["mix"])], check=True)
    from PIL import Image
    Image.new("RGB", (800, 600), (60, 20, 20)).save(files["plate"])
    return files


def build_plan(media: dict[str, Path]) -> tuple[dict, list[dict]]:
    """План, в который попадает каждый переход и каждый приём."""
    transitions = [n for n in sorted(TRANSITIONS) if n != "cut"]
    heroes = sorted(HERO)

    shots, avatar, subtitles, overlays = [], [], [], []
    t = 0.0
    for i in range(max(len(transitions), len(heroes))):
        kind = "avatar" if i % 3 == 2 else "footage"
        shot = {
            "index": i, "start": round(t, 3), "end": round(t + SHOT_SEC, 3),
            "duration": SHOT_SEC, "kind": kind, "block_id": f"b{i % 6 + 1}",
            "file": str(media["shot"]),
            "kenburns": {"from_scale": 1.0, "to_scale": 1.08},
            "transition": {"renderer": transitions[i % len(transitions)],
                           "duration": 0.32},
        }
        if i < len(heroes):
            shot["hero"] = {
                "renderer": heroes[i], "file": str(media["plate"]),
                "params": dict(HERO_PARAMS),
            }
        if kind == "avatar":
            avatar.append({
                "index": len(avatar), "start": round(t, 3),
                "end": round(t + SHOT_SEC, 3), "duration": SHOT_SEC,
                "block_id": shot["block_id"], "file": str(media["avatar"]),
                "slot_indices": [i], "has_alpha": True,
            })
        shots.append(shot)

        # Слова встык: соседство на одном треке и есть проверяемое место.
        w = t
        while w < t + SHOT_SEC - 0.2:
            subtitles.append({"display": "слово", "start": round(w, 4),
                              "end": round(min(w + WORD_STEP, t + SHOT_SEC), 4),
                              "emphasis": w == t})
            w += WORD_STEP
        t += SHOT_SEC

    # Полноэкранный текст с фоном: у него свой трек под материал, и проверить
    # его надо здесь, а не живым прогоном.
    shots.append({
        "index": len(shots), "start": round(t, 3), "end": round(t + 1.4, 3),
        "duration": 1.4, "kind": "fullscreen_text", "block_id": "b1",
        "content": "180 ГРАДУСОВ", "accent_word": "180", "invert": False,
        "file": str(media["shot"]),
        "transition": {"renderer": "white_flash", "duration": 0.3},
    })
    t += 1.4

    for i, kind in enumerate(("source_card", "plaque", "cta")):
        overlays.append({"type": kind, "start": round(2.0 + i * 6.0, 3),
                         "end": round(5.0 + i * 6.0, 3),
                         "params": {"domain": "nature.com", "title": "Заголовок",
                                    "snippet": "Выдержка", "content": "ПЛАШКА"}})
    overlays.append({
        "type": "dataviz", "start": 8.0, "end": 13.0,
        "template": "data-viz/apple-money-count", "renderer": "dataviz",
        "params": {"end_value": 10000, "prefix": "$"},
    })
    overlays.append({
        "type": "dataviz", "start": 14.0, "end": 21.0,
        "template": "data-viz/north-korea-locked-down", "renderer": "dataviz",
        "params": {"label": "LOCKED DOWN"},
    })
    overlays.append({
        "type": "dataviz", "start": 22.0, "end": 28.0,
        "template": "data-viz/nyc-paris-flight", "renderer": "dataviz",
        "params": {
            "origin": "New York", "dest": "Paris",
            "origin_code": "JFK / NYC", "dest_code": "CDG / FR",
            "km": "5,837",
        },
    })
    overlays.append({
        "type": "dataviz", "start": 29.0, "end": 36.0,
        "template": "data-viz/mk-progress-stat", "renderer": "dataviz",
        "params": {
            "value": 22, "max": 30, "label": "Goals reached",
            "caption": "Great job, we are getting closer!",
        },
    })
    overlays.append({
        "type": "dataviz", "start": 37.0, "end": 49.0,
        "template": "data-viz/flowchart-vertical", "renderer": "dataviz",
        "params": {
            "root": "Should I learn to code?",
            "branches": ["Yes", "Not sure"],
            "leaves": [
                "Start with Python", "Try no-code first",
                "Build a personal website", "Take a free intro course",
            ],
        },
    })
    overlays.append({
        "type": "source_card", "start": 50.0, "end": 64.0,
        "template": "browser-ui/chatgpt-exchange", "renderer": "chatgpt_exchange",
        "params": {
            "prompt": "Hey what is the best tool for ai avatars",
            "intro1": "It really depends on what you are trying to do.",
            "intro2": "For most creators and marketers, here is how I rank them:",
            "tableHeadUse": "Use case", "tableHeadTool": "Best tool", "tableHeadWhy": "Why",
            "row1Use": "Overall realism", "row1Tool": "HeyGen",
            "row1Why": "Most natural facial expressions and lip sync.",
            "row1Chip": "Official A.I Ranking",
            "row2Use": "Enterprise", "row2Tool": "Synthesia",
            "row2Why": "Better collaboration and workflows.",
            "row2Chip": "Official A.I Ranking",
            "row3Use": "Mobile UGC", "row3Tool": "Captions",
            "row3Why": "Fast mobile workflow and social editing.",
            "row3Chip": "Creator Stack",
            "row4Use": "Real-time", "row4Tool": "Tavus",
            "row4Why": "Interactive avatars that hold live conversations.",
            "row4Chip": "Creator Stack",
        },
    })
    overlays.append({
        "type": "source_card", "start": 65.0, "end": 78.0,
        "template": "browser-ui/claude-exchange", "renderer": "claude_exchange",
        "params": {
            "prompt": "What's the best tool for ai avatars?",
            "thinking": "Weighing accuracy against market…",
            "lead": "I'll search for the current state.",
            "search": "best AI avatar video generator 2026",
            "answer1": "It depends on what you are making.",
            "answer2": "**HeyGen** is where most teams land {HeyGen}.",
        },
    })
    overlays.append({
        "type": "source_card", "start": 79.0, "end": 92.0,
        "template": "browser-ui/message-thread-reveal", "renderer": "message_thread_reveal",
        "params": {
            "contactName": "Rachel",
            "questionMessage": "what r u using for the launch video??",
            "teaserMessage": "wait look 👀",
            "cardTitle": "HyperFrames | Write HTML, render pixel-perfect video",
            "cardDomain": "hyperframes.heygen.com",
            "reactionMessage": "OMG IT'S HTML",
        },
    })
    overlays.append({
        "type": "source_card", "start": 93.0, "end": 106.0,
        "template": "browser-ui/notes-reveal", "renderer": "notes_reveal",
        "params": {
            "titleL1": "Things nobody told me",
            "titleL2": "about video.",
            "noteLine1": "my videos sucked",
            "cardTop": "THE POWER",
            "cardMid": "OF",
            "cardBottom": "ONE FILE",
        },
    })
    overlays.append({
        "type": "source_card", "start": 107.0, "end": 120.0,
        "template": "browser-ui/notification-cascade", "renderer": "notification_cascade",
        "params": {
            "notifTitle": "New render",
            "message1": "Launch video is ready.",
            "appName": "HyperFrames",
            "headlineTop": "SHIP VIDEO",
            "headlineAccent": "FROM HTML",
            "footerText": "hyperframes.heygen.com",
        },
    })
    overlays.append({
        "type": "plaque", "start": 121.0, "end": 125.5,
        "template": "lower-thirds/instagram-follow", "renderer": "instagram_follow",
        "params": {
            "displayName": "HeyGen",
            "handle": "@heygen_official",
            "followers": "47.5K followers",
            "buttonText": "Follow",
            "followingText": "Following",
        },
    })
    overlays.append({
        "type": "plaque", "start": 126.0, "end": 130.5,
        "template": "lower-thirds/tiktok-follow", "renderer": "tiktok_follow",
        "params": {
            "displayName": "HeyGen",
            "handle": "@heygen.com",
            "followers": "1,999 followers",
            "buttonText": "Follow",
            "followingText": "Following",
        },
    })
    overlays.append({
        "type": "plaque", "start": 131.0, "end": 135.5,
        "template": "lower-thirds/yt-lower-third", "renderer": "yt_lower_third",
        "params": {
            "channelName": "HeyGen",
            "subscriberCount": "82.2K subscribers",
            "buttonText": "Subscribe",
            "subscribedText": "Subscribed",
        },
    })
    overlays.append({
        "type": "source_card", "start": 136.0, "end": 141.0,
        "template": "browser-ui/x-post", "renderer": "x_post",
        "params": {
            "displayName": "Hyperframes",
            "handle": "@hyperframes",
            "text": "Write HTML, render pixel-perfect video. Zero external dependencies, pure web standards. #HyperFrames",
            "timestamp": "1:10 PM · Apr 7, 2026",
            "replies": "34",
            "reposts": "2.3K",
            "likes": "10.9K",
            "likesActive": "11.0K",
            "views": "150K",
        },
    })
    overlays.append({
        "type": "source_card", "start": 142.0, "end": 147.0,
        "template": "browser-ui/reddit-post", "renderer": "reddit_post",
        "params": {
            "subreddit": "r/hyperframes",
            "author": "u/developer · 3h",
            "title": "Writing HTML to render video changed everything for our pipeline",
            "body": "Zero external dependencies, pure web standards, and pixel-perfect 4K rendering in seconds. The whole workflow runs headlessly.",
            "votes": "4.2k",
            "votesActive": "4.3k",
            "comments": "328",
        },
    })





    plan = {
        "video_id": "lintcheck", "variant": "A", "fps": 30,
        "resolution": [1080, 1920], "duration_sec": round(t, 3),
        "shots": shots, "avatar": avatar, "overlays": overlays,
        "subtitles": subtitles,
        "subtitle_style": {"mode": "stroke", "baseline_y": 975},
    }
    blocks = [{"id": f"b{i}", "emphasis_word": "рекорд", "mode": "A"}
              for i in range(1, 7)]
    return plan, blocks


def _uncovered(media: dict[str, Path]) -> list[str]:
    """Приёмы, которые на этом наборе параметров ничего не рисуют.

    Пустой Piece — не ошибка разметки, а дыра в проверке: шаблона в проекте
    просто нет, и lint о нём ничего не скажет. Ловим это здесь, а не кадром.
    """
    from src.lib.render.hyperframes.templates import TemplateCtx, render_hero
    params = {**HERO_PARAMS, "src": str(media["plate"]),
              "icon": str(media["plate"])}
    silent = []
    for name in sorted(HERO):
        piece = render_hero(name, TemplateCtx(index=1, start=1.0, duration=SHOT_SEC,
                                              target="#shot-01", track=6,
                                              params=dict(params)))
        if not piece.nodes:
            silent.append(name)
    return silent


def run(hyperframes: str, work: Path) -> tuple[int, str]:
    """Собрать проект и отдать его lint. Возвращает (код, вывод)."""
    media = _media(work / "media")
    silent = _uncovered(media)
    plan, blocks = build_plan(media)
    root = work / "project"
    HyperFramesProject(root, load_config()).prepare(plan, media["mix"], blocks=blocks)
    proc = subprocess.run([hyperframes, "lint"], cwd=root,
                          capture_output=True, text=True, timeout=300)
    out = proc.stdout + proc.stderr
    if silent:
        out += ("\nприёмы без узлов (проверкой не покрыты): "
                + ", ".join(silent) + "\n")
    return (proc.returncode or (1 if silent else 0)), out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", default=shutil.which("hyperframes"),
                        help="путь к CLI hyperframes")
    parser.add_argument("--keep", type=Path, default=None,
                        help="куда положить проект (иначе временный каталог)")
    args = parser.parse_args()
    if not args.bin:
        print("hyperframes не найден: npm install -g hyperframes@0.8.2", file=sys.stderr)
        return 2

    if args.keep:
        args.keep.mkdir(parents=True, exist_ok=True)
        code, out = run(args.bin, args.keep)
    else:
        with tempfile.TemporaryDirectory() as td:
            code, out = run(args.bin, Path(td))
    print(out)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
