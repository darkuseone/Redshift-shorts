"""Субтитры caption-camera-follow: слова стоят, едет камера."""

from __future__ import annotations

import re

from src.lib.render.hyperframes.brand_css import build_css
from src.lib.render.hyperframes.captions import (
    caption_css, group_caption_phrases, layout_camera_follow, pose_for,
)
from src.lib.render.hyperframes.composition import CompositionBuilder


def _words(*pairs, block="b1"):
    out = []
    t = 0.1
    for item in pairs:
        if isinstance(item, tuple):
            text, emph = item
        else:
            text, emph = item, False
        out.append({
            "display": text, "start": t, "end": t + 0.4,
            "emphasis": emph, "block_id": block,
        })
        t += 0.55
    return out


def _plan(words):
    return {
        "video_id": "redshift_0001",
        "variant": "A",
        "fps": 30,
        "resolution": [1080, 1920],
        "duration_sec": 10.0,
        "shots": [],
        "avatar": [],
        "overlays": [],
        "subtitles": words,
        "subtitle_style": {
            "mode": "stroke", "baseline_y": 975, "caption": "camera-follow",
        },
    }


def _follow(cfg, words):
    return CompositionBuilder(_plan(words), cfg.brandbook, {}).build("assets/mix.wav")


def _world_windows(markup: str) -> list[tuple[float, float]]:
    windows = []
    for line in markup.splitlines():
        if 'fromTo("#cf-' not in line or "-world" not in line:
            continue
        dur = float(re.search(r"duration:([\d.]+)", line).group(1))
        at = float(line.rstrip(");").rsplit(",", 1)[1])
        windows.append((at, at + dur))
    return windows


def test_layout_is_deterministic():
    kwargs = dict(frame_w=740, frame_h=1370, base=219.2, ratio=0.72)
    a = layout_camera_follow(["ПАДЕНИЕ", "В", "ПРОПАСТЬ"], **kwargs)
    b = layout_camera_follow(["ПАДЕНИЕ", "В", "ПРОПАСТЬ"], **kwargs)
    assert [(w.x, w.y, w.fs, w.box) for w in a] == [(w.x, w.y, w.fs, w.box) for w in b]


def test_first_word_sits_at_origin():
    laid = layout_camera_follow(
        ["КОД", "РЕНДЕР"], frame_w=740, frame_h=1370, base=200)
    assert laid[0].x == 0 and laid[0].y == 0
    assert laid[1].box.x1 > laid[0].box.x1 or laid[1].box.y1 > laid[0].box.y1


def test_narrow_block_grows_right_wide_block_grows_down():
    def skinny(text: str, fs: float, tracking: float) -> float:
        return fs * 0.25

    def wide(text: str, fs: float, tracking: float) -> float:
        return fs * 1.4

    right = layout_camera_follow(
        ["A", "B"], frame_w=740, frame_h=1370, base=200, measure=skinny)
    assert right[1].x > right[0].x
    down = layout_camera_follow(
        ["A", "B"], frame_w=740, frame_h=1370, base=200, measure=wide)
    assert down[1].y > down[0].y
    assert down[1].x == down[0].x


def test_camera_scale_only_pulls_back():
    laid = layout_camera_follow(
        ["ПИШИ", "HTML", "И", "ВИДЕО", "СОБИРАЕТСЯ", "САМО"],
        frame_w=740, frame_h=1370, base=219.2)
    scales = [pose_for(w.box, 1.36, 740, 1370, 90, 150).scale for w in laid]
    assert scales == sorted(scales, reverse=True)


def test_phrases_split_on_pause_block_and_length():
    words = [
        {"display": "а", "start": 0.0, "end": 0.3, "block_id": "b1"},
        {"display": "б", "start": 0.4, "end": 0.7, "block_id": "b1"},
        {"display": "в", "start": 1.3, "end": 1.6, "block_id": "b1"},
        {"display": "г", "start": 1.7, "end": 2.0, "block_id": "b2"},
    ]
    groups = group_caption_phrases(words, pause_break_sec=0.45)
    assert [len(g) for g in groups] == [2, 1, 1]

    long = [{"display": str(i), "start": i * 0.2, "end": i * 0.2 + 0.1,
             "block_id": "b"} for i in range(20)]
    packed = group_caption_phrases(long, max_words=12)
    assert [len(g) for g in packed] == [12, 8]


def test_camera_follow_moves_the_world_not_the_clip(cfg):
    out = _follow(cfg, _words("Падение", ("в", True), "пропасть"))
    assert 'id="cf-00-world"' in out
    assert 'class="clip caption-camera"' in out
    assert 'tl.fromTo("#cf-00"' not in out
    assert 'fromTo("#cf-00-world"' in out
    assert 'tl.fromTo("#w-0000-t"' not in out
    assert "Math.random" not in out
    assert "repeat:-1" not in out.replace(" ", "")


def test_camera_follow_has_no_filter_smear(cfg):
    css = caption_css(cfg.brandbook)
    assert "filter" not in css
    out = _follow(cfg, _words("код", "сам"))
    tweens = "\n".join(l for l in out.splitlines() if l.strip().startswith("tl."))
    assert "filter" not in tweens
    assert "--amt" not in out and "--k" not in out


def test_camera_tweens_do_not_overlap(cfg):
    out = _follow(cfg, _words("пиши", "html", "и", "видео", "собирается"))
    windows = _world_windows(out)
    assert windows, out
    windows.sort()
    for prev, nxt in zip(windows, windows[1:]):
        assert prev[1] <= nxt[0] + 1e-6, f"камера пересекается: {windows}"


def test_one_accent_word_per_phrase(cfg):
    out = _follow(cfg, _words("пиши", ("html", True), "и", ("код", True)))
    assert out.count("cf-word is-accent") == 1
    assert ">HTML<" in out


def test_camera_follow_is_uppercase_and_escaped(cfg):
    out = _follow(cfg, [
        {"display": "ку<и>&я", "start": 0.1, "end": 0.5, "emphasis": False},
        {"display": "счётчик.", "start": 0.6, "end": 1.0, "emphasis": False},
    ])
    assert "КУ&lt;И&gt;&amp;Я" in out
    assert ">СЧЁТЧИК<" in out
    assert "счётчик." not in out


def test_camera_follow_clip_has_a_paint_box(cfg):
    """Клип нулевой площади продюсер выбрасывает вместе с детьми."""
    css = caption_css(cfg.brandbook)
    assert "width:var(--frame-w)" in css
    assert "height:var(--frame-h)" in css


def test_gold_maps_to_brand_accent(cfg):
    css = caption_css(cfg.brandbook)
    assert "var(--color-accent)" in css
    assert "#ffd84d" not in css
    full = build_css(cfg.brandbook, {"display": "Oswald-Bold.ttf"})
    # Цвет читается из брендбука: акцент канала сменился на #E63946, и тест,
    # знающий его наизусть, ломался бы на правке палитры, а не кода.
    assert f"--color-accent: {cfg.brandbook['colors']['accent']};" in full
    assert ".caption-camera{" in full


def test_every_camera_tween_target_exists(cfg):
    out = _follow(cfg, _words("а", "б", "в"))
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for tween in [l for l in out.splitlines() if l.strip().startswith("tl.")]:
        selector = re.search(r'"#([^" ]+)', tween).group(1)
        assert selector in ids, f"твин целится в несуществующий {selector}: {tween}"


def test_adjacent_phrases_use_two_tracks(cfg):
    words = _words("один", "два") + [
        {"display": "три", "start": 2.0, "end": 2.4, "emphasis": False, "block_id": "b2"},
        {"display": "четыре", "start": 2.5, "end": 2.9, "emphasis": False, "block_id": "b2"},
    ]
    out = _follow(cfg, words)
    tracks = re.findall(r'id="cf-(\d+)"[^>]*data-track-index="(\d+)"', out)
    assert len(tracks) == 2
    assert tracks[0][1] != tracks[1][1]
    assert {t for _, t in tracks} <= {"18", "19"}


def test_brandbook_default_caption_is_gradient_fill(cfg):
    assert cfg.brand("subtitles.caption") == "gradient-fill"
