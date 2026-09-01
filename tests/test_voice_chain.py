"""Фаза 1 — голосовой тракт: P1 план, P2 TTS, P3 оптимизация речи, P4 выравнивание."""

from __future__ import annotations

import json

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


# --- формат ответа ElevenLabs -------------------------------------------------

def test_pcm_rate_is_one_the_service_actually_offers():
    """Конвейер живёт на 48 кГц, а PCM ElevenLabs на этой частоте не отдаёт.

    Поймано живым прогоном: запрос pcm_48000 возвращал не сырой PCM, и разбор
    падал невнятным «buffer size must be a multiple of element size».
    """
    from src.lib.providers.tts import ELEVENLABS_PCM_RATES, _nearest_supported_rate

    assert 48000 not in ELEVENLABS_PCM_RATES
    assert _nearest_supported_rate(48000) == 44100
    for sr in (8000, 16000, 22050, 24000, 44100):
        assert _nearest_supported_rate(sr) == sr
    # Ниже самой малой частоты выбирается она же, а не пустота.
    assert _nearest_supported_rate(4000) == 8000


def test_unknown_body_names_what_came_back(tmp_path, monkeypatch):
    """Без проверки numpy роняет прогон сообщением, по которому не найти причину."""
    import base64

    from src.errors import ProviderError
    from src.lib.config import load_config
    from src.lib.costs import CostLedger
    from src.lib.providers.tts import ElevenLabsTTS

    cfg = load_config()
    provider = ElevenLabsTTS(cfg, CostLedger(video_id="t"), "key", "voice")

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            # Нечётная длина и без узнаваемого заголовка — это не аудио.
            return {"audio_base64": base64.b64encode(b"\x00\x01\x02").decode(),
                    "alignment": {}}

    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp())
    with pytest.raises(ProviderError) as exc:
        provider._request("текст", tmp_path / "out.wav",
                          model="eleven_v3", speed=1.0)
    assert "не PCM" in exc.value.message
    assert exc.value.details.get("bytes") == 3


def test_mp3_body_is_decoded_instead_of_crashing(tmp_path, monkeypatch):
    """pcm_* есть не на всех тарифах, и сервис молча отдаёт mp3.

    Поймано живым прогоном: тело начиналось с ID3, а код разбирал его как
    s16le. Формат определяется по байтам, а не по тому, что мы попросили.
    """
    import base64
    import subprocess

    import numpy as np

    from src.lib.audio import load_wav, save_wav
    from src.lib.config import load_config
    from src.lib.costs import CostLedger
    from src.lib.ffmpeg import ffmpeg_bin
    from src.lib.providers.tts import ElevenLabsTTS

    # Настоящий mp3 на секунду — чтобы проверялся разбор, а не заглушка.
    src = tmp_path / "tone.wav"
    sr = 44100
    save_wav(src, (0.2 * np.sin(np.linspace(0, 220 * 2 * np.pi, sr))).astype(np.float32), sr)
    mp3 = tmp_path / "tone.mp3"
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(src), "-codec:a", "libmp3lame", "-b:a", "128k",
                    str(mp3)], check=True, capture_output=True)
    body = mp3.read_bytes()
    assert body[:3] == b"ID3" or body[0] == 0xFF

    cfg = load_config()
    cfg.set("elevenlabs.sample_rate", 48000)
    provider = ElevenLabsTTS(cfg, CostLedger(video_id="t"), "key", "voice")

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"audio_base64": base64.b64encode(body).decode(), "alignment": {}}

    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp())
    out = tmp_path / "out.wav"
    result = provider._request("текст", out, model="eleven_v3", speed=1.0)

    data, out_sr = load_wav(out)
    assert out_sr == 48000
    assert abs(result.duration_sec - 1.0) < 0.1
    assert float(np.abs(data).max()) > 0.01, "получилась тишина"


def test_pcm_is_resampled_to_the_pipeline_rate(tmp_path, monkeypatch):
    """Сервис отдаёт 44100, конвейер работает на 48000 — приводим сами."""
    import base64

    import numpy as np

    from src.lib.audio import load_wav
    from src.lib.config import load_config
    from src.lib.costs import CostLedger
    from src.lib.providers.tts import ElevenLabsTTS

    cfg = load_config()
    cfg.set("elevenlabs.sample_rate", 48000)
    provider = ElevenLabsTTS(cfg, CostLedger(video_id="t"), "key", "voice")

    one_second_at_44100 = (np.zeros(44100, dtype="<i2")).tobytes()

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"audio_base64": base64.b64encode(one_second_at_44100).decode(),
                    "alignment": {}}

    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp())
    out = tmp_path / "out.wav"
    result = provider._request("текст", out, model="eleven_v3", speed=1.0)

    data, sr = load_wav(out)
    assert sr == 48000
    assert len(data) == 48000                      # секунда осталась секундой
    assert abs(result.duration_sec - 1.0) < 1e-3


def test_pace_makes_speech_faster_and_the_target_shorter():
    """Темп 1.1 обязан пережить коррекцию длины.

    Поднять одну скорость мало: коррекция подгоняет озвучку под плановую
    длительность и вернула бы прежний темп. Поэтому цель едет вместе со
    скоростью — речь быстрее, ролик соразмерно короче.
    """
    from src.lib.config import load_config

    cfg = load_config()
    cfg.set("elevenlabs.pace", 1.1)
    pace = float(cfg.get("elevenlabs.pace"))
    target = 60.0

    assert abs(target / pace - 54.55) < 0.05, "цель не сдвинулась на ту же долю"
    # Потолок коррекции тоже обязан ехать, иначе он срежет саму прибавку.
    assert 1.35 * pace > 1.35, "предел коррекции не даст speed выйти выше 1.35"


def test_voice_canon_is_one_rule_for_pipeline_and_probe():
    """Проба брала звук из клипа как есть и звучала на 13 дБ тише ролика.

    Правило громкости живёт одной функцией: и P3, и проба зовут её. Проверяем
    не число в конфиге, а то, что функция действительно приводит тихий вход к
    канону и держит потолок пика.
    """
    import numpy as np

    from src.lib.audio import (
        VOICE_LUFS, VOICE_TRUE_PEAK_DBTP, measure_loudness_buffer, normalize_voice,
    )

    sr = 48000
    # Сигнал с речевым пик-фактором: тон под медленной огибающей. Гауссов шум
    # тут не годится — у него пики на 12 дБ выше среднего, лимитер срезал бы
    # интеграл, и проверка ловила бы свойство тестового сигнала, а не правила.
    t = np.arange(sr * 3) / sr
    envelope = 0.55 + 0.45 * np.sin(2 * np.pi * 2.3 * t)
    quiet = (np.sin(2 * np.pi * 1000 * t) * envelope * 0.008).astype(np.float32)

    before = measure_loudness_buffer(quiet, sr).integrated_lufs
    assert before < VOICE_LUFS - 8, f"вход недостаточно тихий для проверки: {before}"

    loud, gain_db = normalize_voice(quiet, sr)
    after = measure_loudness_buffer(loud, sr)
    assert abs(after.integrated_lufs - VOICE_LUFS) <= 1.0, after.integrated_lufs
    assert after.true_peak_dbtp <= VOICE_TRUE_PEAK_DBTP + 0.05, after.true_peak_dbtp
    assert gain_db > 8, f"гейн не применён: {gain_db}"


def test_voice_settings_come_from_config_and_ask_for_expression():
    """Характер подачи был зашит в код, style и speaker boost не слались вовсе.

    На stability 0.45 речь выходила плоской: разброс громкости готового ролика
    2.0 LU. Проверяется, что настройки читаются из конфига и что дефолт просит
    выразительности, а не ровности.
    """
    from src.lib.config import load_config
    from src.lib.providers.tts import ElevenLabsTTS

    cfg = load_config()
    provider = ElevenLabsTTS.__new__(ElevenLabsTTS)
    provider.cfg = cfg

    settings = provider._voice_settings(1.1, model="eleven_multilingual_v2")
    assert settings["speed"] == 1.1
    assert settings["stability"] <= 0.35, "ровность выше — речь снова плоская"
    assert settings["style"] > 0, "манера исходного голоса не усиливается"
    assert settings["use_speaker_boost"] is True

    cfg.data["elevenlabs"]["voice_settings"]["stability"] = 0.7
    assert provider._voice_settings(1.0, model="eleven_multilingual_v2")["stability"] == 0.7, \
        "конфиг не читается"


def test_v3_gets_a_stability_it_will_actually_accept():
    """eleven_v3 принимает только 0, 0.5 или 1 — промежуточное значит отказ.

    Стоимость ошибки — целый прогон, поэтому значение прижимается к ближайшему
    разрешённому здесь, а не выясняется по ответу сервиса.
    """
    from src.lib.config import load_config
    from src.lib.providers.tts import ElevenLabsTTS

    provider = ElevenLabsTTS.__new__(ElevenLabsTTS)
    provider.cfg = load_config()

    for asked, expected in ((0.30, 0.5), (0.1, 0.0), (0.9, 1.0)):
        provider.cfg.data["elevenlabs"]["voice_settings"]["stability"] = asked
        got = provider._voice_settings(1.0, model="eleven_v3")["stability"]
        assert got == expected, f"{asked} → {got}, ждали {expected}"
        assert got in ElevenLabsTTS.V3_STABILITY_STEPS


def test_hesitations_are_cut_but_meaning_is_never_touched():
    """Первая версия правила съедала сказуемое — теперь так нельзя.

    «Вот это поворот» и «Это значит, что…» — нормальная речь: вырезав из них
    слово, мы ломаем фразу. Режутся только звуки-запинки.
    """
    from src.lib.fillers import discourse_hits, strip_hesitations

    clean, dropped = strip_hesitations("Эээ, свет оказался красным.")
    assert clean == "Свет оказался красным.", clean
    assert dropped == ["Эээ,"]

    for keep in ("Вот это поворот.", "Это значит, что вселенная расширяется.",
                 "И вот ответ на вопрос."):
        assert strip_hesitations(keep) == (keep, []), keep

    # Вводные слова только называются, но не режутся.
    assert discourse_hits("Ну, короче, это работает") == ["ну", "короче"]
    assert discourse_hits("И вот ответ на вопрос") == [], "предупреждение врёт"


def test_p0_stops_hesitations_before_a_single_credit_is_spent(sample_script, cfg):
    """Запинку дешевле не озвучивать, чем вырезать из готового звука."""
    from src.errors import FillerWords
    from src.p0_validate.validator import validate_script

    sample_script["blocks"][1]["text"] = "Эээ, телескоп поймал древний свет."
    with pytest.raises(FillerWords) as exc:
        validate_script(sample_script, cfg)
    assert "Эээ," in str(exc.value)


def test_loud_voice_survives_a_high_crest_source():
    """Просто поднять громкость мало: лимитер опустит всё обратно.

    Дорожка от HeyGen приходит с пик-фактором под 19 дБ. Подъём до −14 LUFS
    выносил пик на +4.9 dBTP, лимитер закрывал потолок, опуская всю дорожку, и
    на выходе было −20 LUFS — тише, чем просили. Проверяется, что цель
    достигается **и** потолок соблюдён одновременно.
    """
    import numpy as np

    from src.lib.audio import (
        VOICE_LUFS, VOICE_TRUE_PEAK_DBTP, measure_loudness_buffer, normalize_voice,
    )

    sr = 48000
    rng = np.random.default_rng(11)
    t = np.arange(sr * 4) / sr
    body = np.sin(2 * np.pi * 900 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 2.0 * t))
    # Редкие выбросы поверх тела фразы — то, что и создаёт высокий пик-фактор.
    spikes = np.zeros_like(body)
    for at in rng.integers(0, t.size - 400, size=24):
        spikes[at:at + 220] += np.hanning(220) * 6.0
    quiet = ((body + body * spikes) * 0.02).astype(np.float32)

    before = measure_loudness_buffer(quiet, sr)
    crest = before.true_peak_dbtp - before.integrated_lufs
    assert crest > 14, f"сигнал недостаточно пиковый для проверки: {crest:.1f} дБ"

    loud, _gain = normalize_voice(quiet, sr)
    after = measure_loudness_buffer(loud, sr)
    assert abs(after.integrated_lufs - VOICE_LUFS) <= 0.6, after.integrated_lufs
    assert after.true_peak_dbtp <= VOICE_TRUE_PEAK_DBTP, after.true_peak_dbtp

    # Без сжатия та же дорожка до канона не дотягивает — ради этого оно и есть.
    flat, _ = normalize_voice(quiet, sr, compress=False)
    assert measure_loudness_buffer(flat, sr).integrated_lufs < after.integrated_lufs - 1


# --- короткие реплики субтитра (§5.1) -----------------------------------------

def _cues(words, *, step=0.14, hold=0.12, block="b1"):
    out, t = [], 0.0
    for word in words:
        out.append({"display": word, "start": t, "end": t + hold, "block_id": block})
        t += step
    return out


def test_single_letter_never_stands_alone_in_the_frame():
    """«а» держалась 88 мс посреди кадра и читалась как сбой рендера.

    Проверено на готовом ролике 0047: тридцать реплик из ста сорока шести — это
    вспышка одной-двух букв. Растянуть её нельзя (соседний клип на том же
    треке), поэтому она уезжает к следующему слову.
    """
    from src.lib.render.text_rules import glue_short_cues

    glued = glue_short_cues(_cues(["гранит,", "а", "расчёты", "обещали"]))
    assert [c["display"] for c in glued] == ["гранит,", "расчёты", "обещали"]
    assert glued[1]["lead"] == "а"
    # Реплика начинается там, где начиналось приклеенное слово: пропасть между
    # речью и субтитром недопустима.
    assert glued[1]["start"] == pytest.approx(0.14)
    assert glued[1]["end"] == pytest.approx(0.40)


def test_two_short_words_in_a_row_become_one_cue():
    """«не в бюджет» — одна реплика, а не цепочка из трёх вспышек."""
    from src.lib.render.text_rules import glue_short_cues

    glued = glue_short_cues(_cues(["не", "в", "бюджет,", "а", "в", "физику."]))
    assert [(c.get("lead"), c["display"]) for c in glued] == [
        ("не в", "бюджет,"), ("а в", "физику.")]


def test_a_short_word_does_not_jump_over_a_pause_or_a_block():
    """За паузой и за границей блока слово принадлежит уже другой фразе."""
    from src.lib.render.text_rules import glue_short_cues

    far = _cues(["и", "дошли"], step=1.5)
    assert [c.get("lead") for c in glue_short_cues(far)] == [None, None]

    split = _cues(["и"]) + [{"display": "дошли", "start": 0.2, "end": 0.5,
                             "block_id": "b2"}]
    assert [c["display"] for c in glue_short_cues(split)] == ["и", "дошли"]


def test_the_glued_word_keeps_the_accent_off_the_preposition():
    """Красный цвет означает ударение, а не начало фразы (§5.1).

    Поэтому приклеенное слово уезжает в отдельный span, а не в текст реплики:
    иначе `.word.emphasis` покрасил бы и предлог.
    """
    from src.lib.render.hyperframes.composition import CompositionBuilder

    cue = {"display": "расчёты", "lead": "а", "start": 1.0, "end": 1.4,
           "emphasis": True, "block_id": "b1"}
    builder = object.__new__(CompositionBuilder)
    builder.brandbook = json.load(open("config/brandbook.json", encoding="utf-8"))
    builder.plan = {"subtitles": [cue], "subtitle_style": {}}
    builder.duration = 2.0
    builder.tweens = []
    builder.stats = {"subtitle_words": 0}
    html = "".join(builder._subtitle_nodes())
    assert 'class="clip word emphasis"' in html
    assert '<i class="lead">А</i> РАСЧЁТЫ' in html


def test_srt_shows_the_same_cues_as_the_frame():
    """Файл субтитров и кадр обязаны говорить одно и то же."""
    from src.p4_align.aligner import AlignedWord

    words = [
        AlignedWord(0, "гранит,", 1.00, 1.12, "b1", "body", False, ["гранит"], "provider"),
        AlignedWord(1, "а", 1.14, 1.26, "b1", "body", False, ["а"], "provider"),
        AlignedWord(2, "расчёты", 1.28, 1.70, "b1", "body", False, ["расчёты"], "provider"),
    ]
    srt = build_srt(words)
    assert "а расчёты" in srt
    assert "\nа\n" not in srt
    # Две реплики, а не три: нумерация обязана идти подряд.
    assert srt.strip().split("\n\n")[-1].startswith("2")
