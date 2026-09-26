"""Звук режиссёрского ролика стоит на склейках таймлайна, а не на слотах P5.

0052, круг 8: заказчик — «чего-то не хватает». P10 ставил SFX по слотам
эвристики P5, а картинку резал таймлайн из чата; удары приходились мимо
склеек, плотность две секунды снимала половину. Теперь P10 читает те же окна,
что режет P11 (`director.shot_windows`), и каждая склейка звучит.
"""

from __future__ import annotations

import pytest

from src.lib import director as D
from src.lib.config import load_config
from src.p10_audio.audio_build import _plan_director_sfx
from src.steps import build_pipeline

BLOCKS = [
    {"id": "b1", "role": "hook", "text": "Кот упал в дыру."},
    {"id": "b2", "role": "body", "text": "Лапы тянет в макаронину, физики так говорят."},
]

# Слова в финальном таймкоде: b1 0.0–1.2, b2 2.0–5.2.
WORDS = {"words": [
    {"display": w, "start": t, "end": t + 0.3, "block_id": b, "spoken": [w.lower()]}
    for b, w, t in (
        ("b1", "Кот", 0.0), ("b1", "упал", 0.4), ("b1", "в", 0.7), ("b1", "дыру", 0.9),
        ("b2", "Лапы", 2.0), ("b2", "тянет", 2.4), ("b2", "в", 2.8),
        ("b2", "макаронину", 3.2), ("b2", "физики", 4.2), ("b2", "так", 4.6),
        ("b2", "говорят", 4.9),
    )
]}

PLAN = {"video_id": "redshift_t002", "duration_sec": 6.0, "cta_window": [5.5, 6.0]}


def _spec(**over) -> dict:
    spec = {
        "footage": {"bh": {"src": "https://example.org/bh.mp4", "source": "nasa",
                           "license": "public_domain", "page_url": "https://svs.gsfc.nasa.gov/x"}},
        "shots": [
            {"block": "b1", "fullscreen": {"template": "intro-hooks/hook-question-flash",
                                           "content": "КОТ?"}},
            {"block": "b1", "at": "дыру", "footage": "bh"},
            {"block": "b2", "footage": "bh", "transition": "transitions/whip-pan-l"},
            {"block": "b2", "at": "макаронину", "footage": "bh",
             "transition": "transitions/zoom-punch-in"},
            {"block": "b2", "at": "физики", "footage": "bh"},
        ],
        "overlays": [
            {"template": "data-viz/counter-roll", "block": "b2", "at": "тянет",
             "params": {"value": 13}},
        ],
    }
    spec.update(over)
    return spec


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _by_time(events):
    return {round(e["t"], 2): e for e in events}


def test_every_cut_of_the_timeline_sounds(cfg):
    events = _by_time(_plan_director_sfx(PLAN, _spec(), WORDS, cfg))
    for start, _end, _shot in D.shot_windows(_spec(), D._word_rows(WORDS), 6.0):
        assert round(start, 2) in events, f"склейка {start:.2f} без звука"


def test_the_sound_follows_the_device_of_the_cut(cfg):
    events = _by_time(_plan_director_sfx(PLAN, _spec(), WORDS, cfg))
    assert events[0.0]["role"] == "reveal"          # полноэкранный хук
    assert events[0.9]["role"] == "whoosh_in"       # прямой рез внутри блока
    assert events[2.0]["role"] == "swipe"           # whip-pan на смене блока
    assert events[3.2]["intent"] == "impact"        # zoom-punch — удар
    assert events[2.4]["role"] == "tick"            # счётчик
    assert events[5.5]["intent"] == "subscribe_cta"


def test_block_change_without_a_transition_still_whooshes(cfg):
    spec = _spec()
    del spec["shots"][2]["transition"]
    events = _by_time(_plan_director_sfx(PLAN, spec, WORDS, cfg))
    assert events[2.0]["role"] == "swipe"


def test_director_sfx_overrides_and_silences(cfg):
    spec = _spec()
    spec["shots"][3]["sfx"] = "sub_drop"
    spec["shots"][4]["sfx"] = "none"
    events = _by_time(_plan_director_sfx(PLAN, spec, WORDS, cfg))
    assert events[3.2]["role"] == "sub_drop"
    assert 4.2 not in events


def test_cuts_closer_than_two_seconds_are_not_thinned_away(cfg):
    events = _plan_director_sfx(PLAN, _spec(), WORDS, cfg)
    shot_starts = {0.0, 0.9, 2.0, 3.2, 4.2}
    assert shot_starts <= {round(e["t"], 2) for e in events}


def test_unknown_sfx_role_is_a_lint_error():
    script = {"meta": {"video_id": "redshift_t002", "avatar_mode": "none"},
              "blocks": BLOCKS, "director": _spec()}
    script["director"]["shots"][1]["sfx"] = "kaboom"
    errors = [i.message for i in D.validate(script) if i.level == "error"]
    assert any("kaboom" in e for e in errors)


def test_p10_cache_busts_when_the_timeline_or_words_change(cfg):
    step = next(s for s in build_pipeline().steps if s.name == "P10")
    assert step.uses_script
    assert "words.json" in step.inputs


def test_the_subscribe_button_sounds_even_when_the_library_is_spent(cfg):
    """0052, круг 8: 18 склеек выбрали всю библиотеку, и кнопка CTA вышла немой."""
    from src.lib.manifest import open_library
    from src.p10_audio.audio_build import _resolve_sfx

    # Свободными остались только звуки не по смыслу кнопки — как в том прогоне.
    spent = [r.id for r in open_library(cfg, "sfx").items
             if not ({"rumble", "spark"} & set(r.tags))]
    cta = next(e for e in _plan_director_sfx(PLAN, _spec(), WORDS, cfg)
               if e["intent"] == "subscribe_cta")
    assert _resolve_sfx(cfg, cta, video_id=PLAN["video_id"], avoid_ids=spent) is not None
