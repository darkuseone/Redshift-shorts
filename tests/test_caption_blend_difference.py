"""caption-blend-difference — mix-blend-mode: difference against footage.

Catalog: https://hyperframes.heygen.com/catalog/components/caption-blend-difference
Engine cannot tween blend-mode. Isolation on #root is required so the
composite sees the video, not the page. Accent words stay mix-blend-mode
normal so blood-red does not invert to cyan.

Opt-in only: empty caption / pop-in still resolve to gradient-fill.
"""
from __future__ import annotations

import copy
import re

from src.lib.render.hyperframes.brand_css import build_css
from src.lib.render.hyperframes.captions import (
    caption_css, pick_caption_style, resolve_caption,
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
            "mode": "stroke", "baseline_y": 975, "caption": "blend-difference",
        },
    }
    plan.update(extra)
    return plan


def _blend(cfg, words, **extra):
    return CompositionBuilder(_plan(words, **extra), cfg.brandbook, {}).build(
        "assets/mix.wav")


def test_resolve_catalog_aliases() -> None:
    assert resolve_caption("blend-difference") == "blend-difference"
    assert resolve_caption("caption-blend-difference") == "blend-difference"
    assert resolve_caption("blend_difference") == "blend-difference"


def test_empty_and_pop_in_stay_gradient_fill() -> None:
    assert resolve_caption("") == "gradient-fill"
    assert resolve_caption("pop-in") == "gradient-fill"
    assert resolve_caption("word-pop") == "gradient-fill"


def test_space_still_clip_wipe_unless_explicit_blend(cfg) -> None:
    plan = {"category": "space", "title": "Чип"}
    assert pick_caption_style(plan, cfg.brandbook) == "clip-wipe"
    brand = copy.deepcopy(cfg.brandbook)
    brand["subtitles"]["caption"] = "blend-difference"
    assert pick_caption_style(plan, brand) == "blend-difference"
    brand["subtitles"]["caption"] = "caption-blend-difference"
    assert pick_caption_style(plan, brand) == "blend-difference"


def test_pick_does_not_auto_select_blend(cfg) -> None:
    plan = {
        "category": "ai",
        "title": "Квантовый чип",
        "blocks": [{"text": "Логический кубит прожил дольше."}],
    }
    assert pick_caption_style(plan, cfg.brandbook) == "gradient-fill"
    assert pick_caption_style(plan, {}) == "gradient-fill"


def test_missing_caption_key_does_not_emit_blend(cfg) -> None:
    plan = _plan(_words("пиши", "html"))
    del plan["subtitle_style"]["caption"]
    out = CompositionBuilder(plan, cfg.brandbook, {}).build("assets/mix.wav")
    assert 'class="clip caption-grad"' in out
    assert 'class="clip caption-blend"' not in out


def test_css_has_difference_and_accent_escape(cfg) -> None:
    css = caption_css(cfg.brandbook)
    assert "mix-blend-mode:var(--blend-mode,difference)" in css.replace(" ", "")
    assert ".caption-blend-accent{" in css
    assert ".bd-word.is-accent" in css
    assert ".bd-word.is-spacer" in css
    assert "mix-blend-mode:normal" in css.replace(" ", "")
    assert "clip-path" not in css
    assert "filter" not in css
    word_rule = css.split(".bd-word{")[1].split(".bd-word.is-spacer")[0]
    assert "mix-blend-mode" not in word_rule
    assert "text-shadow" not in word_rule


def test_root_isolation_in_full_css(cfg) -> None:
    css = build_css(cfg.brandbook, {"display": "Oswald-Bold.ttf"})
    root = re.search(r"#root\{([^}]*)\}", css).group(1)
    assert "isolation:isolate" in root.replace(" ", "")
    assert "background" not in root
    assert ".caption-blend{" in css
    assert css.count("{") == css.count("}"), "лишняя скобка ломает последующие правила"
    assert caption_css(cfg.brandbook).count("{") == caption_css(cfg.brandbook).count("}")


def test_build_emits_group_enter_not_clip_opacity(cfg) -> None:
    out = _blend(cfg, _words("пиши", ("html", True), "код"))
    assert 'class="clip caption-blend"' in out
    assert 'class="clip caption-blend-accent"' in out
    assert 'id="bd-00-g"' in out
    assert 'id="bd-00a-g"' in out
    assert 'id="bd-00-w0"' in out
    assert 'id="bd-00a-w1"' in out
    assert 'class="bd-word is-accent"' in out
    assert 'class="bd-word is-spacer"' in out
    assert ">HTML<" in out
    assert 'fromTo("#bd-00-g"' in out
    assert 'fromTo("#bd-00a-g"' in out
    assert 'fromTo("#bd-00",' not in out
    assert 'fromTo("#bd-00a",' not in out
    tween_blob = "\n".join(
        line for line in out.splitlines() if line.strip().startswith("tl."))
    assert "mix-blend-mode" not in tween_blob
    assert "mixBlendMode" not in tween_blob
    assert "filter" not in tween_blob.lower()
    assert "clip-path" not in out
    assert "Math.random" not in out
    assert "repeat:-1" not in out.replace(" ", "")


def test_blend_mode_lives_in_css_not_markup(cfg) -> None:
    out = _blend(cfg, _words("пиши", ("html", True)))
    clip = re.search(r'<div id="bd-00"[^>]*>.*?</div>\s*</div>', out, re.S)
    assert clip, out
    assert "mix-blend-mode" not in clip.group(0)
    assert "mix-blend-mode:var(--blend-mode,difference)" in caption_css(cfg.brandbook).replace(" ", "")


def test_every_blend_tween_target_exists(cfg) -> None:
    out = _blend(cfg, _words("а", "б", "в"))
    ids = set(re.findall(r'\sid="([^"]+)"', out))
    for tween in [l for l in out.splitlines() if l.strip().startswith("tl.")]:
        selector = re.search(r'"#([^" ]+)', tween).group(1)
        assert selector in ids, f"твин целится в несуществующий {selector}: {tween}"


def test_enter_rise_scales_with_fitted_size(cfg) -> None:
    short = _blend(cfg, _words("А"))
    wide = _blend(cfg, _words("ПРОФЕССИОНАЛЬНОЕ", "ВИДЕООБРАБОТКА", "КОМПИЛЯЦИЯ"))
    def rise(html: str) -> float:
        match = re.search(r'fromTo\("#bd-00-g",\{opacity:0,y:([\d.]+)\}', html)
        assert match, html
        return float(match.group(1))
    assert rise(short) > rise(wide)


def test_unique_clip_ids_across_phrases(cfg) -> None:
    words = [
        {"display": "раз", "start": 0.1, "end": 0.5, "emphasis": False, "block_id": "b1"},
        {"display": "два", "start": 0.6, "end": 1.0, "emphasis": True, "block_id": "b1"},
        {"display": "три", "start": 2.0, "end": 2.4, "emphasis": False, "block_id": "b2"},
        {"display": "четыре", "start": 2.5, "end": 2.9, "emphasis": True, "block_id": "b2"},
    ]
    out = _blend(cfg, words)
    assert 'id="bd-00"' in out
    assert 'id="bd-00a"' in out
    assert 'id="bd-01"' in out
    assert 'id="bd-01a"' in out
    assert 'id="bd-00-g"' in out
    assert 'id="bd-01-g"' in out
    ids = re.findall(r'\sid="([^"]+)"', out)
    assert len(ids) == len(set(ids))
