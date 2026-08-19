"""Фаза 1 — голосовой тракт: P1 план, P2 TTS, P3 оптимизация речи, P4 выравнивание."""

from __future__ import annotations

import numpy as np
import pytest

from src.errors import ScriptTooShort
from src.lib import audio as A
from src.lib.providers.tts import MockTTS, _words_from_alignment
from src.lib.text import (
    Token, apply_stress, normalize_text, number_to_words, plural_form, spoken_text,
)
from src.p1_plan.planner import plan
from src.p3_speech_opt.optimizer import (
    collect_gaps, pause_target_sec, plan_segments, remap_time, render_segments,
)
from src.p4_align.aligner import align_by_energy, build_srt, map_tokens_to_words
from src.p0_validate.validator import validate_script


# --- нормализация текста (§4.2.5) --------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (0, "ноль"), (1, "один"), (11, "одиннадцать"), (21, "двадцать один"),
    (105, "сто пять"), (1000, "одна тысяча"), (2500, "две тысячи пятьсот"),
    (1_000_000, "один миллион"), (100_000_000, "сто миллионов"),
    (-42, "минус сорок два"),
])
def test_number_to_words(value, expected):
    assert number_to_words(value) == expected


def test_plural_forms():
    assert plural_form(1, "кубит", "кубита", "кубитов") == "кубит"
    assert plural_form(3, "кубит", "кубита", "кубитов") == "кубита"
    assert plural_form(11, "кубит", "кубита", "кубитов") == "кубитов"


def test_apply_stress_moves_to_vowel():
    assert "́" in apply_stress("процессор", 6)
    stressed = apply_stress("чип", 0)      # индекс на согласной → сдвиг к гласной
    assert stressed.index("́") == 2


def test_normalize_expands_numbers_and_keeps_display():
    tokens = normalize_text("Внутри 105 кубитов.")
    by_display = {t.display: t for t in tokens}
    assert "105" in by_display
    assert by_display["105"].spoken == ["сто", "пять"]
    assert "сто пять" in spoken_text(tokens)


def test_normalize_expands_abbreviations():
    pron = {"abbreviations": {"NASA": "НАСА"}, "words": {}, "units": {}}
    tokens = normalize_text("Отчёт NASA вышел.", pron)
    assert [t.spoken for t in tokens if t.display == "NASA"] == [["НАСА"]]


def test_emphasis_marks_only_first_occurrence():
    tokens = normalize_text("Мы верим, потому что верим.", emphasis_word="верим")
    assert sum(1 for t in tokens if t.emphasis) == 1


def test_normalize_applies_stress_from_dictionary():
    pron = {"words": {"кубит": {"stress": 3}}, "abbreviations": {}, "units": {}}
    tokens = normalize_text("Один кубит.", pron)
    assert any("́" in s for t in tokens for s in t.spoken)


# --- P1 планирование (§3.5, §6) ----------------------------------------------

def test_plan_keeps_avatar_share_in_range(sample_script, cfg):
    validated = validate_script(sample_script, cfg)
    draft = plan(validated, cfg)
    lo, hi = cfg.get("limits.avatar_share")
    assert lo <= draft["avatar"]["planned_share"] <= hi


def test_plan_first_avatar_within_six_seconds(sample_script, cfg):
    validated = validate_script(sample_script, cfg)
    draft = plan(validated, cfg)
    cursor = 0.0
    for block in draft["blocks"]:
        if block["mode"] in ("A", "B"):
            assert cursor <= cfg.get("limits.first_avatar_appearance_sec")
            return
        cursor += block["_estimated_sec"]
    pytest.fail("аватар не появляется вовсе")


def test_plan_reports_conflict_when_avatar_cannot_appear_early(sample_script, cfg):
    """Неразрешимый конфликт §6 обязан всплыть, а не «рассосаться» молча."""
    for block in sample_script["blocks"][:3]:
        block["avatar"] = "off"
        block["mode_hint"] = "C"
    sample_script["blocks"][0]["text"] = (
        "Этот ответ невозможно проверить ничем, и это самое странное свойство "
        "всей затеи с квантовыми вычислениями сегодня."
    )
    validated = validate_script(sample_script, cfg)
    draft = plan(validated, cfg)
    codes = [c["code"] for c in draft["conflicts"]]
    assert "AVATAR_FIRST_APPEARANCE_LATE" in codes


def test_plan_promotes_early_auto_block_to_meet_deadline(sample_script, cfg):
    for block in sample_script["blocks"]:
        block.pop("mode_hint", None)
        block["avatar"] = "auto"
    sample_script["blocks"][0]["avatar"] = "off"
    validated = validate_script(sample_script, cfg)
    draft = plan(validated, cfg)
    assert draft["conflicts"] == []
    cursor = 0.0
    for block in draft["blocks"]:
        if block["mode"] in ("A", "B"):
            assert cursor <= cfg.get("limits.first_avatar_appearance_sec")
            break
        cursor += block["_estimated_sec"]


def test_plan_split_share_limited(sample_script, cfg):
    validated = validate_script(sample_script, cfg)
    draft = plan(validated, cfg)
    total = sum(b["_estimated_sec"] for b in draft["blocks"])
    split = sum(b["_estimated_sec"] for b in draft["blocks"] if b["mode"] == "B")
    assert split / total <= cfg.get("limits.split_share_max") + 1e-6


def test_plan_respects_avatar_off_directive(sample_script, cfg):
    validated = validate_script(sample_script, cfg)
    draft = plan(validated, cfg)
    forced_off = {b["id"] for b in validated["blocks"] if b.get("avatar") == "off"}
    for block in draft["blocks"]:
        if block["id"] in forced_off:
            assert block["mode"] == "C"


def test_plan_adds_tts_length_buffer(sample_script, cfg):
    validated = validate_script(sample_script, cfg)
    draft = plan(validated, cfg)
    ratio = draft["tts_target_sec"] / draft["estimated_speech_sec"]
    assert 1.18 <= ratio <= 1.25       # §4.2.4


# --- P2 mock TTS --------------------------------------------------------------

def test_mock_tts_is_deterministic(cfg, tmp_path):
    provider = MockTTS(cfg=cfg, costs=None)
    a = provider.synthesize("Привет мир. Это тест.", tmp_path / "a.wav")
    b = provider.synthesize("Привет мир. Это тест.", tmp_path / "b.wav")
    assert (tmp_path / "a.wav").read_bytes() == (tmp_path / "b.wav").read_bytes()
    assert [w.to_dict() for w in a.words] == [w.to_dict() for w in b.words]


def test_mock_tts_skips_standalone_punctuation(cfg, tmp_path):
    provider = MockTTS(cfg=cfg, costs=None)
    res = provider.synthesize("Внутри — сто пять кубитов.", tmp_path / "x.wav")
    assert [w.word for w in res.words] == ["Внутри", "сто", "пять", "кубитов"]


def test_mock_tts_speed_changes_duration(cfg, tmp_path):
    provider = MockTTS(cfg=cfg, costs=None)
    fast = provider.synthesize("Один два три четыре пять.", tmp_path / "f.wav", speed=1.0)
    slow = provider.synthesize("Один два три четыре пять.", tmp_path / "s.wav", speed=0.8)
    assert slow.duration_sec > fast.duration_sec


def test_elevenlabs_alignment_to_words():
    alignment = {
        "characters": list("да нет"),
        "character_start_times_seconds": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
        "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
    }
    words = _words_from_alignment(alignment)
    assert [w.word for w in words] == ["да", "нет"]
    assert words[0].start == 0.0 and words[1].end == 0.6


# --- P3 оптимизация речи (§4.2) ----------------------------------------------

def test_pause_target_within_corridor():
    for gap in (0.16, 0.4, 1.2, 3.0):
        for ratio in (0.0, 0.5, 1.0):
            target = pause_target_sec(gap, (80.0, 120.0), ratio) * 1000
            assert 80.0 - 1e-6 <= target <= 120.0 + 1e-6


def test_collect_gaps_finds_lead_pause_tail():
    words = [{"start": 0.5, "end": 1.0}, {"start": 1.8, "end": 2.2}]
    gaps = collect_gaps(words, 3.0)
    kinds = [g.kind for g in gaps]
    assert kinds == ["lead", "pause", "tail"]
    assert gaps[1].duration == pytest.approx(0.8)


def test_plan_segments_cuts_long_pause_but_leaves_air():
    sr = 8000
    audio = np.zeros(int(3.0 * sr), dtype=np.float32)
    audio[int(0.2 * sr):int(0.8 * sr)] = 0.3
    audio[int(2.0 * sr):int(2.6 * sr)] = 0.3
    words = [{"start": 0.2, "end": 0.8}, {"start": 2.0, "end": 2.6}]
    segments, cuts = plan_segments(audio, sr, words, threshold_ms=150,
                                   pause_ms_range=(80.0, 120.0), ratio=0.0)
    pause_cut = next(c for c in cuts if c["kind"] in ("pause", "breath"))
    assert 0.08 <= pause_cut["kept_sec"] <= 0.121      # §4.2.2: не схлопываем в ноль
    out = render_segments(audio, sr, segments)
    assert len(out) / sr < 3.0


def test_remap_time_is_exact_inside_segments():
    sr = 8000
    audio = np.zeros(int(3.0 * sr), dtype=np.float32)
    audio[int(0.2 * sr):int(0.8 * sr)] = 0.3
    audio[int(2.0 * sr):int(2.6 * sr)] = 0.3
    words = [{"start": 0.2, "end": 0.8}, {"start": 2.0, "end": 2.6}]
    segments, _ = plan_segments(audio, sr, words, threshold_ms=150,
                                pause_ms_range=(80.0, 120.0), ratio=0.0)
    assert remap_time(0.2, segments) == pytest.approx(0.1, abs=0.02)
    second = remap_time(2.0, segments)
    assert second < 2.0                       # пауза действительно сокращена
    assert remap_time(2.6, segments) - second == pytest.approx(0.6, abs=0.01)


def test_script_too_short_raises_with_deficit(tmp_path, cfg, sample_script):
    """§4.2.4 — короткий результат = ошибка с расчётом, а не короткий ролик."""
    from src.errors import ScriptTooShort as STS

    exc = STS("тест", final_sec=30.0, min_sec=35, deficit_sec=5.0, deficit_words=12)
    assert exc.code == "SCRIPT_TOO_SHORT"
    assert exc.details["deficit_sec"] == 5.0


# --- P4 выравнивание (§5.1) ---------------------------------------------------

def test_map_tokens_exact():
    tokens = [
        Token("Внутри", ["Внутри", "—"]).to_dict(),
        Token("105", ["сто", "пять"]).to_dict(),
        Token("кубитов.", ["кубитов", "."]).to_dict(),
    ]
    aligned = [
        {"word": "Внутри", "start": 0.0, "end": 0.4},
        {"word": "сто", "start": 0.5, "end": 0.8},
        {"word": "пять", "start": 0.8, "end": 1.1},
        {"word": "кубитов", "start": 1.2, "end": 1.7},
    ]
    pairs, exact = map_tokens_to_words(tokens, aligned)
    assert exact
    assert pairs[1][0]["display"] == "105"
    assert pairs[1][1] == 0.5 and pairs[1][2] == 1.1   # число склеено из двух слов


def test_map_tokens_falls_back_on_mismatch():
    tokens = [Token("раз", ["раз"]).to_dict(), Token("два", ["два"]).to_dict()]
    aligned = [{"word": "раз", "start": 0.0, "end": 1.0}]
    pairs, exact = map_tokens_to_words(tokens, aligned)
    assert not exact and len(pairs) == 2


def test_align_by_energy_orders_words():
    sr = 8000
    audio = np.zeros(int(2.0 * sr), dtype=np.float32)
    audio[int(0.1 * sr):int(0.5 * sr)] = 0.4
    audio[int(0.9 * sr):int(1.4 * sr)] = 0.4
    spans = align_by_energy(["раз", "два"], (0.0, 2.0), audio, sr)
    assert len(spans) == 2
    assert spans[0][0] < spans[1][0]
    assert spans[0][1] <= spans[1][1]


def test_srt_format():
    from src.p4_align.aligner import AlignedWord

    words = [AlignedWord(0, "Привет", 1.5, 1.9, "b1", "hook", False, ["Привет"], "provider")]
    srt = build_srt(words)
    assert "00:00:01,500 --> 00:00:01,900" in srt
    assert "Привет" in srt


# --- плотность акцентов (§5.1) ------------------------------------------------

_SAMPLE = (
    "можно ли выжить внутри чёрной дыры горизонт событий это не стена а точка "
    "невозврата приливные силы растянут тело в спагетти но у сверхмассивной "
    "дыры градиент слабее и пересечение проходит незаметно дальше сингулярность "
    "ждёт всех одинаково и уйти от неё нельзя потому что она лежит в будущем "
    "а не в стороне"
).split()


def _sample_words(author_accents=()):
    from src.p4_align.aligner import AlignedWord

    accents = set(author_accents)
    return [AlignedWord(index=i, display=w, start=i * 0.35, end=i * 0.35 + 0.3,
                        block_id="b1", role="body", emphasis=w in accents,
                        spoken=[w], source="provider")
            for i, w in enumerate(_SAMPLE)]


@pytest.mark.parametrize("author", [(), ("спагетти",),
                                    ("спагетти", "горизонт", "сингулярность")])
def test_accent_density_matches_the_brandbook(author):
    """Один акцент на 6–8 слов.

    Сценарий даёт по одному ``emphasis_word`` на блок — четыре цветных слова на
    сотню. Цвет в потоке субтитров и есть единственный смысловой акцент, и в
    такой концентрации он не читается.
    """
    from src.p4_align.aligner import top_up_emphasis

    words = _sample_words(author)
    top_up_emphasis(words, [6, 8])
    accents = [w for w in words if w.emphasis]
    assert accents
    assert 6 <= len(words) / len(accents) <= 8.4


def test_accents_are_not_adjacent():
    """Два цветных слова подряд — заливка, а не ударение."""
    from src.p4_align.aligner import top_up_emphasis

    words = _sample_words(("спагетти",))
    top_up_emphasis(words, [6, 8])
    hits = [w.index for w in words if w.emphasis]
    assert min(b - a for a, b in zip(hits, hits[1:])) >= 6


def test_author_accents_are_never_dropped():
    """Слово, выбранное сценарием, остаётся акцентом при любом доборе."""
    from src.p4_align.aligner import top_up_emphasis

    words = _sample_words(("спагетти", "сингулярность"))
    top_up_emphasis(words, [6, 8])
    kept = {w.display for w in words if w.emphasis}
    assert {"спагетти", "сингулярность"} <= kept


def test_function_words_never_become_accents():
    """Подсвеченный предлог читается как сбой рендера."""
    from src.p4_align.aligner import top_up_emphasis

    words = _sample_words()
    top_up_emphasis(words, [6, 8])
    picked = {w.display for w in words if w.emphasis}
    assert not picked & {"и", "а", "но", "это", "не", "от", "в", "на"}
    assert all(len(w) >= 5 for w in picked)


def test_top_up_is_deterministic():
    """Рендер сэмплирует кадры не по порядку: два прогона обязаны совпасть."""
    from src.p4_align.aligner import top_up_emphasis

    first, second = _sample_words(("спагетти",)), _sample_words(("спагетти",))
    top_up_emphasis(first, [6, 8])
    top_up_emphasis(second, [6, 8])
    assert [w.emphasis for w in first] == [w.emphasis for w in second]


def test_top_up_survives_a_text_of_only_function_words():
    """Короткая служебная фраза не должна ни падать, ни красить предлоги."""
    from src.p4_align.aligner import AlignedWord, top_up_emphasis

    words = [AlignedWord(index=i, display=w, start=i * 0.3, end=i * 0.3 + 0.25,
                         block_id="b", role="body", emphasis=False,
                         spoken=[w], source="provider")
             for i, w in enumerate("и а но то же ли бы не ни как".split())]
    assert top_up_emphasis(words, [6, 8]) == 0
    assert not any(w.emphasis for w in words)
