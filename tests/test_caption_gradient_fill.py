"""Субтитры caption-gradient-fill: bounce и кровавая заливка акцента."""

from __future__ import annotations

import re

from src.lib.render.hyperframes.brand_css import build_css
from src.lib.render.hyperframes.captions import (
    caption_css, is_explicit_space, is_space_theme, pick_caption_style,
    resolve_caption,
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


def _plan(words, **extra):
    plan = {
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
            "mode": "stroke", "baseline_y": 975, "caption": "gradient-fill",
        },
    }
    plan.update(extra)
    return plan


def _fill(cfg, words, **extra):
    return CompositionBuilder(_plan(words, **extra), cfg.brandbook, {}).build(
        "assets/mix.wav")


def test_missing_caption_key_uses_gradient_fill(cfg):
    plan = _plan(_words("пиши", "html"))
    del plan["subtitle_style"]["caption"]
    out = CompositionBuilder(plan, cfg.brandbook, {}).build("assets/mix.wav")
    assert 'class="clip caption-grad"' in out
    assert 'class="clip word' not in out
    assert 'id="w-0000"' not in out


def test_legacy_pop_in_is_remapped(cfg):
    out = _fill(cfg, _words("пиши"), subtitle_style={
        "mode": "stroke", "baseline_y": 975, "caption": "word-pop",
    })
    assert 'class="clip caption-grad"' in out
    assert resolve_caption("pop-in") == "gradient-fill"
    assert resolve_caption("") == "gradient-fill"


def test_gradient_fill_does_not_tween_forbidden_props(cfg):
    out = _fill(cfg, _words("пиши", ("html", True), "код"))
    assert "backgroundPosition" not in out
    assert "background-position" not in out
    assert "clip-path" not in out
    assert "filter:" not in out
    assert "Math.random" not in out
    assert "repeat:-1" not in out.replace(" ", "")
    assert 'fromTo("#gf-00"' not in out


def test_fill_is_one_layer_in_one_colour(cfg):
    """Закон канала: один слой, белая фраза, заливка только #D7263D."""
    out = _fill(cfg, _words("пиши", ("html", True), "код"))
    accent = cfg.brandbook["colors"]["accent"]
    assert accent == "#D7263D"
    for banned in ("#fe9f1b", "#f76e49", "#ff2063", "#fd56cb", "#ffd700",
                   "#f2566b",  # светло-красный убран из палитры 23.09
                   cfg.brandbook["colors"]["cyan"].lower()):
        assert banned not in out.lower(), banned
    assert accent in out
    # Ни HTML-дубля под SVG, ни отдельного акцентного класса: слово рисуется
    # ровно одним <svg> с белым текстом и красным поверх него под маской.
    assert 'class="gf-base"' not in out
    assert "gf-accent" not in out
    assert ">HTML<" in out
    assert out.count('<text class="gf-ink"') == out.count('class="gf-word"') * 2


def test_every_word_fills_as_it_is_spoken(cfg):
    """Заливается текущее слово, а не одно «акцентное» на фразу."""
    out = _fill(cfg, _words("пиши", ("html", True)))
    rects = [ln for ln in out.splitlines() if "-r\"" in ln and "scaleX" in ln]
    assert any("gf-00-w0-r" in line for line in rects)
    assert any("gf-00-w1-r" in line for line in rects)
    # И гаснет: к концу фразы строка снова белая.
    assert 'tl.set("#gf-00-w0-r",{scaleX:0}' in out


def test_phrase_never_wraps_to_a_second_line(cfg):
    """Перенос склеивал соседние слова («ВРЁТСАМОЛЁТ»). Строка одна."""
    css = caption_css(cfg.brandbook)
    assert "flex-wrap:nowrap" in css
    assert "flex-wrap:wrap" not in css.split(".gf-group{")[1].split("}")[0]
    out = _fill(cfg, _words("врёт", "самолёт"))
    assert ">ВРЁТ<" in out and ">САМОЛЁТ<" in out
    assert ">ВРЁТСАМОЛЁТ<" not in out


def test_fill_tweens_scale_on_the_mask_rect(cfg):
    out = _fill(cfg, _words("пиши", ("html", True)))
    assert 'fromTo("#gf-00-w1-r"' in out
    assert "scaleX" in "".join(
        l for l in out.splitlines() if "gf-00-w1-r" in l)
    assert 'tl.set("#gf-00-w0"' in out
    assert 'tl.to("#gf-00-w0"' in out


def test_css_has_no_clip_path_or_filter(cfg):
    css = caption_css(cfg.brandbook)
    assert "clip-path" not in css
    assert "filter" not in css
    assert ".caption-grad{" in css
    full = build_css(cfg.brandbook, {"display": "Oswald-Bold.ttf"})
    assert ".caption-grad{" in full
    # glow-дефолт main живёт на `.word`; жесты caption — поверх него.
    assert ".word{" in full
    assert "text-shadow" in full


def test_every_fill_tween_target_exists(cfg):
    out = _fill(cfg, _words("а", "б", "в"))
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for tween in [l for l in out.splitlines() if l.strip().startswith("tl.")]:
        selector = re.search(r'"#([^" ]+)', tween).group(1)
        assert selector in ids, f"твин целится в несуществующий {selector}: {tween}"


def test_fill_scale_tweens_on_accent_rect_do_not_overlap(cfg):
    out = _fill(cfg, _words("пиши", ("html", True), "код"))
    windows = []
    for line in out.splitlines():
        if "scaleX" not in line or "fromTo" not in line:
            continue
        dur = float(re.search(r"duration:([\d.]+)", line).group(1))
        at = float(line.rstrip(");").rsplit(",", 1)[1])
        windows.append((at, at + dur))
    assert windows
    windows.sort()
    for prev, nxt in zip(windows, windows[1:]):
        assert prev[1] <= nxt[0] + 1e-6, windows


def test_space_category_picks_clip_wipe_only_without_one_style(cfg):
    import copy as _copy
    plan = {"category": "space", "title": "Чип"}
    assert is_space_theme(plan)
    # Канал 22.09: один жест во всех роликах.
    assert pick_caption_style(plan, cfg.brandbook) == "gradient-fill"
    legacy = _copy.deepcopy(cfg.brandbook)
    legacy["subtitles"]["one_style_all_videos"] = False
    assert pick_caption_style(plan, legacy) == "clip-wipe"


def test_cosmic_topic_without_space_category_stays_gradient_fill(cfg):
    """clip-wipe — только явный ``category: space``.

    Эвристика по словам темы ловила «орбиту» в обычном ролике и уводила его
    с единственного разрешённого жеста канала.
    """
    plan = {
        "category": "science",
        "title": "Сбой на орбите МКС",
        "blocks": [{"text": "Станция потеряла ориентацию."}],
    }
    assert is_space_theme(plan)
    assert not is_explicit_space(plan)
    assert pick_caption_style(plan, cfg.brandbook) == "gradient-fill"


def test_gradient_fill_does_not_hold_across_mute_hole(cfg):
    """Muted karaoke used to stretch «ДНЯ» until the next visible phrase."""
    words = [
        {"display": "дня", "start": 2.99, "end": 3.29,
         "emphasis": True, "block_id": "b1"},
        {"display": "модель", "start": 19.8, "end": 20.2,
         "emphasis": False, "block_id": "b3"},
    ]
    out = _fill(cfg, words, duration_sec=68.0)
    match = re.search(r'id="gf-00"[^>]*data-duration="([\d.]+)"', out)
    assert match, out[:400]
    assert float(match.group(1)) < 1.2


def test_adjacent_gradient_phrases_do_not_share_a_frame(cfg):
    words = [
        {"display": "вихрь", "start": 1.00, "end": 1.20,
         "emphasis": False, "block_id": "b4"},
        {"display": "как", "start": 1.20, "end": 1.35,
         "emphasis": False, "block_id": "b4"},
        {"display": "спагетти,", "start": 1.35, "end": 1.70,
         "emphasis": False, "block_id": "b4"},
        {"display": "которое", "start": 1.76, "end": 2.10,
         "emphasis": False, "block_id": "b4"},
    ]
    out = _fill(cfg, words, duration_sec=4.0)
    starts = re.findall(r'id="gf-0(\d)"[^>]*data-start="([\d.]+)"', out)
    durs = re.findall(r'id="gf-0(\d)"[^>]*data-duration="([\d.]+)"', out)
    assert len(starts) >= 2 and len(durs) >= 2
    end0 = float(starts[0][1]) + float(durs[0][1])
    start1 = float(starts[1][1])
    assert end0 <= start1 + 1e-6


def test_ai_topic_stays_on_gradient_fill(cfg):
    plan = {
        "category": "ai",
        "title": "Квантовый чип",
        "blocks": [{"text": "Логический кубит прожил дольше."}],
    }
    assert not is_space_theme(plan)
    assert pick_caption_style(plan, cfg.brandbook) == "gradient-fill"
