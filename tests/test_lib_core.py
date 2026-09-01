"""Тесты базовых подсистем: шрифты, аудио, pHash, кэш, бюджет, storage."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.errors import BudgetExceeded, FontMissingCyrillic
from src.lib import audio as A
from src.lib import phash
from src.lib.cache import StepCache, code_fingerprint, hash_obj
from src.lib.costs import CostLedger
from src.lib.fonts import pick_font, read_font, validate_font
from src.lib.storage import LocalStorage, evict_lru

FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"


# --- шрифты (§3.4, skill redshift-fonts) -------------------------------------

@pytest.mark.parametrize("name", ["Oswald-Bold", "Nunito-ExtraBold", "JetBrainsMono-Bold"])
def test_brand_fonts_have_cyrillic_and_free_license(name):
    info = validate_font(FONTS / f"{name}.ttf")
    assert info.has_cyrillic()
    assert info.embedding_allowed
    assert info.commercial_use_allowed


def test_font_covers_required_sample():
    info = read_font(FONTS / "Nunito-ExtraBold.ttf")
    assert info.covers("Привет, мир! ЁжЪ 42")


def test_font_without_cyrillic_is_rejected(tmp_path):
    """Контроль правила §3.4: шрифт без кириллицы обязан ронять прогон."""
    src = (FONTS / "Oswald-Bold.ttf").read_bytes()
    broken = tmp_path / "broken.ttf"
    broken.write_bytes(src[:200])          # обрезанный файл — cmap не разберётся
    with pytest.raises(Exception):
        validate_font(broken)


def test_pick_font_falls_back_and_reports_rejections(tmp_path):
    missing = tmp_path / "nope.ttf"
    path, info, rejected = pick_font([missing, FONTS / "Oswald-Bold.ttf"])
    assert path.name == "Oswald-Bold.ttf"
    assert info.family == "Oswald"
    assert rejected and rejected[0]["reason"] == "файл не найден"


def test_pick_font_raises_when_nothing_valid(tmp_path):
    with pytest.raises(FontMissingCyrillic):
        pick_font([tmp_path / "a.ttf", tmp_path / "b.ttf"])


# --- аудио (§4.4, QC 8/9/13) --------------------------------------------------

def _tone(seconds=3.0, freq=440.0, amp=0.2, sr=48000):
    t = np.arange(int(sr * seconds)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_wav_roundtrip(tmp_path):
    sig = A.to_stereo(_tone(1.0))
    p = tmp_path / "x.wav"
    A.save_wav(p, sig)
    back, sr = A.load_wav(p)
    assert sr == 48000
    assert back.shape == sig.shape
    assert np.max(np.abs(back - sig)) < 1e-3


def test_lufs_matches_ffmpeg_reference(tmp_path):
    """Собственная реализация BS.1770 сверяется с ebur128 из ffmpeg."""
    p = tmp_path / "tone.wav"
    A.save_wav(p, A.to_stereo(_tone(3.0, 1000.0, 0.2)))
    ff = A.measure_loudness_file(p)
    data, sr = A.load_wav(p)
    mine = A.measure_lufs_array(data, sr)
    assert abs(ff.integrated_lufs - mine) < 0.5


def test_normalize_to_lufs_hits_target():
    sig = A.to_stereo(_tone(3.0, 1000.0, 0.05))
    out, delta = A.normalize_to_lufs(sig, -14.0)
    assert delta > 0
    assert abs(A.measure_lufs_array(out) - (-14.0)) < 0.3


def test_music_bed_level_is_in_spec():
    """§4.4: подложка −30…−34 LUFS, «на грани слышимости»."""
    bed = A.to_stereo(_tone(3.0, 220.0, 0.5))
    bed, _ = A.normalize_to_lufs(bed, -32.0)
    assert -34.0 <= A.measure_lufs_array(bed) <= -30.0


def test_true_peak_limiter():
    loud = A.to_stereo(_tone(1.0, 1000.0, 0.99))
    limited = A.limit_true_peak(loud, -1.0)
    assert A.true_peak_dbtp(limited) <= -0.9


def test_detect_silences_finds_gap():
    sr = 48000
    speech = np.concatenate([_tone(0.5, 300, 0.3), np.zeros(int(sr * 0.4), np.float32),
                             _tone(0.5, 300, 0.3)])
    silences = A.detect_silences(speech, sr, min_ms=150)
    assert any(0.4 < s < 0.6 and 0.85 < e < 1.05 for s, e in silences)


def test_trailing_silence_measured():
    sr = 48000
    sig = np.concatenate([_tone(0.5, 300, 0.3), np.zeros(int(sr * 0.25), np.float32)])
    assert 200 <= A.trailing_silence_ms(sig, sr) <= 300


def test_duck_lowers_bed_under_speech():
    sr = 48000
    speech = np.concatenate([np.zeros(int(sr * 0.5), np.float32), _tone(1.0, 300, 0.4)])
    bed = A.to_stereo(_tone(1.5, 100, 0.3))
    ducked = A.duck(bed, speech, sr, depth_db=-7.0)
    quiet_part = np.abs(ducked[int(sr * 1.0):int(sr * 1.4)]).mean()
    loud_part = np.abs(ducked[:int(sr * 0.3)]).mean()
    assert quiet_part < loud_part * 0.7


def test_loop_to_length_extends():
    sr = 48000
    bed = A.to_stereo(_tone(2.0, 200, 0.2))
    out = A.loop_to_length(bed, sr * 5, sr=sr)
    assert len(out) == sr * 5


def test_crossfade_concat_has_no_clicks():
    a = _tone(0.2, 300, 0.4)
    b = _tone(0.2, 300, 0.4)
    joined = A.crossfade_concat([a, b], 48000, fade_ms=8)
    diff = np.abs(np.diff(joined))
    assert diff.max() < 0.05


# --- pHash (§3.6.6, §7.2.5) ---------------------------------------------------

def _img(color, size=(200, 200)):
    return Image.new("RGB", size, color)


def test_phash_identical_images_match():
    a = _img((30, 60, 90))
    b = _img((30, 60, 90))
    assert phash.hamming(phash.phash_image(a), phash.phash_image(b)) == 0


def _photo_like(size: int = 640) -> Image.Image:
    """Кадр с плавными градиентами и пятнами — как реальный футаж.

    Мелкие периодические узоры (тонкие полосы) для такой проверки не годятся:
    они принципиально неустойчивы к ресемплингу, и тест на них ловит версию
    Pillow, а не работу pHash.
    """
    from PIL import ImageDraw

    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for i in range(size):
        draw.line([(0, i), (size, i)],
                  fill=(30 + i // 5, 60 + i // 8, max(0, 120 - i // 9)))
    draw.ellipse((size * 0.19, size * 0.23, size * 0.66, size * 0.73), fill=(220, 140, 90))
    draw.ellipse((size * 0.59, size * 0.09, size * 0.88, size * 0.38), fill=(40, 40, 60))
    return img


@pytest.mark.parametrize("target", [320, 256, 160, 96])
def test_phash_survives_rescaling(target):
    """§7.2.5 — дедуп обязан узнавать тот же кадр в другом разрешении."""
    img = _photo_like()
    assert phash.is_duplicate(phash.phash_image(img),
                              phash.phash_image(img.resize((target, target))))


def test_phash_survives_jpeg_compression():
    import io

    img = _photo_like()
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=55)
    assert phash.is_duplicate(phash.phash_image(img), phash.phash_image(Image.open(buf)))


def test_phash_survives_brightness_change():
    """DC-коэффициент исключён из хеша, поэтому экспозиция на него не влияет."""
    from PIL import ImageEnhance

    img = _photo_like()
    brighter = ImageEnhance.Brightness(img).enhance(1.2)
    assert phash.hamming(phash.phash_image(img), phash.phash_image(brighter)) <= 2


def test_phash_distinguishes_different_images():
    a = Image.new("RGB", (200, 200), (255, 255, 255))
    for i in range(200):
        a.putpixel((i, i), (0, 0, 0))
    b = Image.new("RGB", (200, 200), (255, 255, 255))
    for i in range(0, 200, 3):
        for j in range(200):
            b.putpixel((i, j), (0, 0, 0))
    assert not phash.is_duplicate(phash.phash_image(a), phash.phash_image(b))


def test_video_duplicate_needs_half_frames():
    a = ["0" * 16, "0" * 16, "f" * 16]
    b = ["0" * 16, "0" * 16, "0" * 16]
    assert phash.video_is_duplicate(a, b)
    assert not phash.video_is_duplicate(["f" * 16, "f" * 16], ["0" * 16, "0" * 16])


# --- кэш шагов (§7.1 идемпотентность) ----------------------------------------

def test_step_cache_roundtrip(tmp_path):
    cache = StepCache(tmp_path)
    out = tmp_path / "out.json"
    out.write_text("{}", encoding="utf-8")
    fp = hash_obj({"a": 1})
    assert not cache.is_fresh("P1", fp, ["out.json"])
    cache.record("P1", fp, outputs=["out.json"])
    assert cache.is_fresh("P1", fp, ["out.json"])
    assert not cache.is_fresh("P1", hash_obj({"a": 2}), ["out.json"])
    out.unlink()
    assert not cache.is_fresh("P1", fp, ["out.json"])


def test_render_is_not_fresh_without_the_videos(tmp_path):
    """Ролики лежат в выдаче, а она прогон не переживает.

    P12 объявлял выходом только свой отчёт — тот живёт в рабочем каталоге и
    приезжает из кэша Actions целым. Возобновление с P12 из-за этого
    возвращалось «из кэша» за две минуты и оставляло выдачу пустой: прогон
    №33508293306 не отрендерил ни одного ролика и не оставил ни превью, ни mp4.
    """
    from src.lib.config import load_config
    from src.lib.costs import CostLedger
    from src.lib.storage import build_storage
    from src.pipeline import RunContext, Step
    from src.steps import build_pipeline

    work, out = tmp_path / "work", tmp_path / "out"
    work.mkdir()
    out.mkdir()
    (work / "build_report.json").write_text("{}", encoding="utf-8")

    cfg = load_config(overrides=["providers.mode=mock"])
    ctx = RunContext(video_id="redshift_0047", cfg=cfg, work_dir=work, output_dir=out,
                     script_path=tmp_path / "s.json", cache=StepCache(work),
                     costs=CostLedger(video_id="redshift_0047"),
                     storage=build_storage(cfg))
    p12 = next(s for s in build_pipeline().steps if s.name == "P12")

    expected = tuple(p12.outputs) + p12.deliverable_paths(ctx)
    assert [p.name for p in p12.deliverable_paths(ctx)] == [
        "redshift_0047_A.mp4", "redshift_0047_B.mp4"]

    fp = hash_obj({"p12": 1})
    ctx.cache.record("P12", fp, outputs=expected)
    # Отчёт на месте, роликов нет — шаг обязан считаться несвежим.
    assert not ctx.cache.is_fresh("P12", fp, expected)

    for path in p12.deliverable_paths(ctx):
        path.write_bytes(b"mp4")
    assert ctx.cache.is_fresh("P12", fp, expected)


def test_step_cache_disabled(tmp_path):
    cache = StepCache(tmp_path, enabled=False)
    cache.record("P1", "x", outputs=[])
    assert not cache.is_fresh("P1", "x", [])


def test_code_fingerprint_follows_source_changes(tmp_path):
    """Правка кода шага обязана инвалидировать кэш, иначе шаг вернёт старый результат."""
    import sys
    import types

    mod_file = tmp_path / "probe.py"
    mod_file.write_text("VALUE = 1\n", encoding="utf-8")
    module = types.ModuleType("src._probe_module")
    module.__file__ = str(mod_file)
    sys.modules["src._probe_module"] = module
    try:
        code_fingerprint.cache_clear()
        before = code_fingerprint("src._probe_module")
        mod_file.write_text("VALUE = 2\n", encoding="utf-8")
        code_fingerprint.cache_clear()
        assert code_fingerprint("src._probe_module") != before
    finally:
        sys.modules.pop("src._probe_module", None)
        code_fingerprint.cache_clear()


def test_code_fingerprint_is_scoped_to_step_dependencies():
    """Отпечаток берёт только то, что шаг реально импортирует: правка P5 не
    должна обнулять кэш P6 — в live-режиме это лишние кредиты HeyGen."""
    from src.lib.cache import _reachable_source_files
    import importlib

    p5 = _reachable_source_files(importlib.import_module("src.p5_replan.replanner"))
    assert any(f.endswith("p5_replan/replanner.py") for f in p5)
    assert not any("p6_avatar" in f for f in p5)


# --- бюджет (§7.6, redshift-cost-guard) --------------------------------------

def test_cost_ledger_hard_stop():
    ledger = CostLedger(max_usd=1.0, hard_stop=True)
    ledger.add("heygen", "generate", 10, "sec", 0.5)
    with pytest.raises(BudgetExceeded):
        ledger.add("heygen", "generate", 20, "sec", 0.8)


def test_cost_ledger_soft_warning():
    ledger = CostLedger(max_usd=1.0, hard_stop=False)
    ledger.add("x", "y", 1, "u", 5.0)
    assert ledger.total_usd == 5.0
    assert ledger.to_dict()["within_budget"] is False


# --- storage LRU (§14.4, R-11) ------------------------------------------------

def test_lru_eviction_removes_oldest(tmp_path):
    store = LocalStorage(tmp_path / "store")
    import os
    import time as _t
    for i in range(4):
        src = tmp_path / f"f{i}.bin"
        src.write_bytes(b"x" * 1000)
        store.put(f"f{i}.bin", src)
        os.utime(store.root / f"f{i}.bin", (_t.time() - (10 - i) * 100, _t.time()))
    removed = evict_lru(store, max_bytes=2500)
    assert removed == ["f0.bin", "f1.bin"]
    assert store.exists("f3.bin")


def test_lru_respects_protected(tmp_path):
    store = LocalStorage(tmp_path / "store")
    import os
    import time as _t
    for i in range(3):
        src = tmp_path / f"g{i}.bin"
        src.write_bytes(b"y" * 1000)
        store.put(f"g{i}.bin", src)
        os.utime(store.root / f"g{i}.bin", (_t.time() - (10 - i) * 100, _t.time()))
    removed = evict_lru(store, max_bytes=1500, protected={"g0.bin"})
    assert "g0.bin" not in removed
    assert store.exists("g0.bin")


def _ctx_for(tmp_path, script: Path):
    from src.lib.config import load_config
    from src.lib.costs import CostLedger
    from src.lib.storage import build_storage
    from src.pipeline import RunContext

    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    cfg = load_config(overrides=["providers.mode=mock"])
    return RunContext(video_id="redshift_0047", cfg=cfg, work_dir=work,
                      output_dir=tmp_path / "out", script_path=script,
                      cache=StepCache(work), costs=CostLedger(video_id="redshift_0047"),
                      storage=build_storage(cfg))


def test_editing_the_script_invalidates_the_first_step(tmp_path):
    """Шаг без входных файлов читает сам сценарий — и обязан от него зависеть.

    У P0 ``inputs`` пуст, и его отпечаток состоял из имени, версии и кода шага.
    При тёплом кэше он считался свежим всегда: правка сценария не отменяла
    ничего, P0 отдавал прежний validated_script.json, и правка молча пропадала.
    """
    from src.steps import build_pipeline

    script = tmp_path / "s.json"
    script.write_text('{"meta": {"video_id": "x"}, "blocks": []}', encoding="utf-8")
    ctx = _ctx_for(tmp_path, script)
    p0 = next(s for s in build_pipeline().steps if s.name == "P0")

    before = p0.fingerprint(ctx)
    script.write_text('{"meta": {"video_id": "x"}, "blocks": [{"id": "b1"}]}',
                      encoding="utf-8")
    assert p0.fingerprint(ctx) != before


def test_a_footage_query_never_reprices_the_voice(tmp_path):
    """Поисковый запрос футажа лежит в том же плане, что и речь.

    Пока отпечаток P2 считался по всему файлу, правка одной строки запроса
    означала переозвучку: ElevenLabs списывал кредиты, границы фраз сдвигались, и
    клипы ведущего, сгенерированные под прежнюю речь, шли в брак все разом.
    Цена промаха — оба сервиса сразу, поэтому правило закреплено тестом.
    """
    import json

    from src.steps import build_pipeline

    ctx = _ctx_for(tmp_path, tmp_path / "s.json")
    plan = {"video_id": "redshift_0047", "tts_target_sec": 58.0,
            "blocks": [{"id": "b1", "role": "hook", "spoken_text": "Самая глубокая дыра",
                        "broll_queries": ["deep drilling rig night fog"],
                        "visual_intent": "Тёмный кадр"}]}
    path = ctx.work_dir / "draft_plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    p2 = next(s for s in build_pipeline().steps if s.name == "P2")
    before = p2.fingerprint(ctx)

    plan["blocks"][0]["broll_queries"] = ["welded steel hatch on concrete"]
    plan["blocks"][0]["visual_intent"] = "Заваренный люк"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    assert p2.fingerprint(ctx) == before, "правка запроса футажа переозвучивает ролик"

    # А правка самой речи — обязана переозвучить.
    plan["blocks"][0]["spoken_text"] = "Самая глубокая скважина"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    assert p2.fingerprint(ctx) != before
