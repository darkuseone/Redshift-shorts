"""Интеграционные проверки: аудио-микс, матирование, QC, обучение, обслуживание."""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.lib import audio as A
from src.lib.library_filler import fill_sfx
from src.lib.manifest import open_library
from src.lib.render.matting import MatteReport, QUALITY_THRESHOLD, plan_vfx_backgrounds
from src.lib.sfx_synth import SFX_ROLES, synth_sfx
from src.p10_audio.audio_build import _plan_sfx


# --- синтез библиотек (§14.1, §14.2) -----------------------------------------

def test_sfx_catalog_matches_spec():
    """§14.1 требует ровно 20 ролей — и именно тех, что перечислены в таблице."""
    assert len(SFX_ROLES) == 20
    assert set(SFX_ROLES) == {
        "whoosh_in", "whoosh_out", "hit_impact", "sub_drop", "riser", "pop", "ui_click",
        "type_key", "swipe", "glitch", "reveal", "chime", "notification",
        "camera_shutter", "data_beep", "tick", "boom", "error_buzz", "meme_stinger",
        "subscribe_ping",
    }


@pytest.mark.parametrize("role", ["whoosh_in", "hit_impact", "pop", "subscribe_ping"])
def test_sfx_is_short_and_normalized(role):
    """§14.1: каждый файл ≤2 сек и нормализован."""
    audio = synth_sfx(role)
    assert len(audio) / 48000 <= 2.0
    assert -1.5 <= A.peak_dbfs(audio) <= 0.0


def test_sfx_is_deterministic():
    assert np.array_equal(synth_sfx("pop"), synth_sfx("pop"))


def test_fill_sfx_adds_nothing(cfg):
    """`fill-libraries` не имеет права воссоздать отвергнутые короткие звуки."""
    result = fill_sfx(cfg, dry_run=True)
    assert result["added"] == []
    assert result["curated"] is True
    assert result["max_items"] == 20


def test_repository_sfx_and_music_are_curated(cfg):
    """SFX и музыка курируемые: синтетика запрещена, пустая база законна."""
    sfx = open_library(cfg, "sfx")
    music = open_library(cfg, "music")
    assert all(i.source != "synth" for i in sfx.items)
    assert sfx.count == 0 or all(i.source == "curated" for i in sfx.items)
    assert music.count == 0 or all(i.source == "curated" for i in music.items)
    for item in sfx.items:
        path = sfx.file_path(item)
        assert path.exists(), f"в манифесте {item.id}, файла нет"
        assert item.duration_sec <= 2.05


def test_fill_sfx_does_not_write_files(cfg, repo_root):
    folder = repo_root / "assets" / "sfx"
    before = {p.name for p in folder.glob("*") if p.is_file()}
    result = fill_sfx(cfg)
    after = {p.name for p in folder.glob("*") if p.is_file()}
    assert result["added"] == []
    assert after == before


# --- расстановка SFX (§4.4) ---------------------------------------------------

def _plan_stub():
    return {
        "duration_sec": 20.0,
        "cta_window": [18.0, 20.0],
        "blocks": [{"id": "b1", "sfx": "hit_impact"}],
        "slots": [
            {"index": 0, "start": 0.0, "end": 3.0, "kind": "footage", "block_id": "b1",
             "transition_in": "cut"},
            {"index": 1, "start": 3.0, "end": 4.2, "kind": "fullscreen_text",
             "block_id": "b1", "transition_in": "cut"},
            {"index": 2, "start": 4.2, "end": 9.0, "kind": "avatar", "block_id": "b2",
             "transition_in": "dynamic"},
            {"index": 3, "start": 9.0, "end": 18.0, "kind": "footage", "block_id": "b2",
             "transition_in": "cut"},
        ],
    }


def test_sfx_density_respects_two_second_rule(cfg):
    events = _plan_sfx(_plan_stub(), cfg)
    times = [e["t"] for e in events]
    assert times == sorted(times)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(g >= 0.35 for g in gaps), gaps


def test_sfx_covers_mandatory_points(cfg):
    intents = {e["intent"] for e in _plan_sfx(_plan_stub(), cfg)}
    assert "fullscreen" in intents
    assert "cta" in intents
    assert {"avatar_in", "avatar_out", "transition", "picture_in"} & intents


def test_dynamic_transition_always_gets_sfx(cfg):
    events = _plan_sfx(_plan_stub(), cfg)
    # §4.3: динамический переход на 4.2 сек обязан звучать.
    assert any(abs(e["t"] - 4.2) < 1e-6 for e in events)


# --- матирование §7.7 ---------------------------------------------------------

def test_matte_report_usability_threshold():
    good = MatteReport(available=True, source="heygen", quality=0.8, stable=True)
    weak = MatteReport(available=True, source="heygen", quality=QUALITY_THRESHOLD - 0.1,
                       stable=True)
    shaky = MatteReport(available=True, source="heygen", quality=0.9, stable=False)
    absent = MatteReport(available=False, source="none")
    assert good.usable
    assert not weak.usable and not shaky.usable and not absent.usable


def test_vfx_plan_respects_limit_and_duration():
    slots = [
        {"index": 1, "kind": "avatar", "duration": 4.0, "role": "twist"},
        {"index": 2, "kind": "avatar", "duration": 3.0, "role": "setup"},
        {"index": 3, "kind": "avatar", "duration": 9.0, "role": "develop"},  # длиннее 5 сек
        {"index": 4, "kind": "footage", "duration": 3.0, "role": "develop"},  # не аватар
    ]
    chosen = plan_vfx_backgrounds(slots, limit=2, duration_range=(2.0, 5.0))
    assert chosen == [1, 2]        # twist приоритетнее, длинный и не-аватар отброшены


def test_vfx_plan_zero_limit():
    slots = [{"index": 1, "kind": "avatar", "duration": 3.0, "role": "twist"}]
    assert plan_vfx_backgrounds(slots, limit=0, duration_range=(2.0, 5.0)) == []


# --- результат прогона (§11.1) ------------------------------------------------

def test_run_output_passes_all_qc(repo_root):
    report_path = repo_root / "output" / "redshift_0042" / "build_report.json"
    if not report_path.exists():
        pytest.skip("нет собранного ролика")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for variant, qc in report["qc"].items():
        assert qc["total"] == 19, f"{variant}: проверок должно быть 19 (§11.1)"
        assert qc["passed"], f"{variant}: провалены {[f['id'] for f in qc['failed']]}"


def test_run_output_has_all_artifacts(repo_root):
    out = repo_root / "output" / "redshift_0042"
    if not (out / "build_report.json").exists():
        pytest.skip("нет собранного ролика")
    expected = ["metadata.json", "assets_manifest.json", "cost_report.json",
                "subtitles.srt", "voice_final.wav", "edit_plan_A.json", "edit_plan_B.json"]
    missing = [name for name in expected if not (out / name).exists()]
    assert not missing, f"нет артефактов §9: {missing}"


def test_metadata_declares_synthetic_content(repo_root):
    """§10.3.3 — отметка о синтетическом контенте обязательна."""
    path = repo_root / "output" / "redshift_0042" / "metadata.json"
    if not path.exists():
        pytest.skip("нет собранного ролика")
    meta = json.loads(path.read_text(encoding="utf-8"))
    disclosure = meta["synthetic_content_disclosure"]
    assert disclosure["altered_or_synthetic"] is True
    assert disclosure["reasons"]


def test_assets_manifest_has_license_for_every_item(repo_root):
    """§9.2 — манифест фиксирует лицензию каждого материала."""
    path = repo_root / "output" / "redshift_0042" / "assets_manifest.json"
    if not path.exists():
        pytest.skip("нет собранного ролика")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["unlicensed"] == []
    assert all(item.get("license") for item in manifest["items"])


def test_vp9_alpha_is_read_with_the_right_decoder(tmp_path):
    """VP9 держит альфу отдельным блоком: штатный декодер её не отдаёт.

    Без явного ``libvpx-vp9`` ffmpeg возвращает ``yuv420p``, а ``format=rgba``
    дорисовывает к нему единицы — канал выходит не пустым, а полностью
    непрозрачным. Оценка маски читала это как «покрывает почти весь кадр», то
    есть как негодную, и молча выключала текст за головой и VFX-фон.
    """
    import subprocess

    from PIL import Image

    from src.lib.ffmpeg import ffmpeg_bin
    from src.lib.render.matting import assess_matte

    # Силуэт: непрозрачная колонка на прозрачном фоне, четверть кадра.
    frame = Image.new("RGBA", (192, 384), (0, 0, 0, 0))
    for x in range(72, 120):
        for y in range(40, 384):
            frame.putpixel((x, y), (200, 180, 170, 255))
    png = tmp_path / "src.png"
    frame.save(png)
    clip = tmp_path / "seg_00.webm"
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                    "-loop", "1", "-i", str(png), "-t", "1.0", "-r", "10",
                    "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                    "-auto-alt-ref", "0", "-b:v", "0", "-crf", "30",
                    str(clip)], check=True, capture_output=True)

    report = assess_matte(clip, tmp_path / "matte")
    assert report.available, "альфа в клипе есть, а прочитана как отсутствующая"
    assert report.coverage_mean < 0.5, (
        f"маска прочитана как заливка кадра: покрытие {report.coverage_mean:.2f}")
    assert report.usable, report.reason
