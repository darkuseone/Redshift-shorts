"""Субтитры caption-clip-wipe: слово стоит, маска раскрывается слева направо."""

from __future__ import annotations

import re

from src.lib.render.hyperframes.brand_css import build_css
from src.lib.render.hyperframes.captions import caption_css, fit_wipe_group
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
            "mode": "stroke", "baseline_y": 975, "caption": "clip-wipe",
        },
    }


def _wipe(cfg, words):
    return CompositionBuilder(_plan(words), cfg.brandbook, {}).build("assets/mix.wav")


def test_fit_group_shrinks_to_work_area():
    size, widths = fit_wipe_group(
        ["ПРОФЕССИОНАЛЬНОЕ", "ВИДЕО", "СОБИРАЕТСЯ"],
        max_width=740, base=88, letter_spacing_em=0.04, gap_em=0.22)
    assert size <= 88
    assert size >= 24
    assert sum(widths) <= 740


def test_clip_wipe_uses_mask_scale_not_clip_path(cfg):
    out = _wipe(cfg, _words("пиши", ("html", True), "код"))
    assert 'class="clip caption-wipe"' in out
    assert 'class="cw-mask"' in out
    assert "clip-path" not in out
    assert "clipPath" not in out
    assert "inset(" not in out
    assert 'fromTo("#cw-00"' not in out
    assert 'fromTo("#cw-00-w0-r"' in out
    assert "scaleX" in out
    assert "Math.random" not in out
    assert "repeat:-1" not in out.replace(" ", "")


def test_clip_wipe_css_has_no_clip_path_or_filter(cfg):
    css = caption_css(cfg.brandbook)
    assert "clip-path" not in css
    assert "filter" not in css
    assert "overflow:hidden" in css
    assert ".caption-wipe{" in css
    full = build_css(cfg.brandbook, {"display": "Oswald-Bold.ttf"})
    assert ".caption-wipe{" in full


def test_gold_flash_maps_to_accent(cfg):
    out = _wipe(cfg, _words("пиши", ("html", True), "код"))
    assert "#FFD700" not in out
    assert "#ffd84d" not in out.lower()
    assert cfg.brandbook["colors"]["accent"] in out
    # Одна вспышка на фразу, даже если emphasis два.
    # Вспышка — to-состояние. from dim тоже держит акцент, его не считаем.
    assert out.count(f'color:"{cfg.brandbook["colors"]["accent"]}",duration') == 1
    assert ">HTML<" in out


def test_clip_wipe_is_uppercase_and_escaped(cfg):
    out = _wipe(cfg, [
        {"display": "ку<и>&я", "start": 0.1, "end": 0.5, "emphasis": False},
        {"display": "счётчик.", "start": 0.6, "end": 1.0, "emphasis": False},
    ])
    assert "КУ&lt;И&gt;&amp;Я" in out
    assert ">СЧЁТЧИК<" in out


def test_every_wipe_tween_target_exists(cfg):
    out = _wipe(cfg, _words("а", "б", "в"))
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for tween in [l for l in out.splitlines() if l.strip().startswith("tl.")]:
        selector = re.search(r'"#([^" ]+)', tween).group(1)
        assert selector in ids, f"твин целится в несуществующий {selector}: {tween}"


def test_adjacent_wipe_phrases_use_two_tracks(cfg):
    words = _words("один", "два") + [
        {"display": "три", "start": 2.0, "end": 2.4, "emphasis": False, "block_id": "b2"},
        {"display": "четыре", "start": 2.5, "end": 2.9, "emphasis": False, "block_id": "b2"},
    ]
    out = _wipe(cfg, words)
    tracks = re.findall(r'id="cw-(\d+)"[^>]*data-track-index="(\d+)"', out)
    assert len(tracks) == 2
    assert tracks[0][1] != tracks[1][1]
    assert {t for _, t in tracks} <= {"18", "19"}


def test_wipe_scale_tweens_on_a_word_do_not_overlap(cfg):
    out = _wipe(cfg, _words("пиши", "html", "код"))
    by_target: dict[str, list[tuple[float, float]]] = {}
    for line in out.splitlines():
        if "scaleX" not in line or "fromTo" not in line:
            continue
        target = re.search(r'"#([^"]+)"', line).group(1)
        dur = float(re.search(r"duration:([\d.]+)", line).group(1))
        at = float(line.rstrip(");").rsplit(",", 1)[1])
        by_target.setdefault(target, []).append((at, at + dur))
    assert by_target
    for target, windows in by_target.items():
        windows.sort()
        for prev, nxt in zip(windows, windows[1:]):
            assert prev[1] <= nxt[0] + 1e-6, f"{target}: {windows}"


def test_default_caption_is_the_glow_of_the_channel(cfg):
    """Умолчание брендбука — гало канала; жесты лежат рядом альтернативами."""
    assert cfg.brand("subtitles.caption") == "glow"
    for gesture in ("gradient_fill", "clip_wipe", "camera_follow", "blend_difference"):
        assert cfg.brand(f"subtitles.{gesture}"), f"жест {gesture} пропал из брендбука"
