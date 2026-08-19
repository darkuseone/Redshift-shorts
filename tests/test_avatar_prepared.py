"""Двухфазный конвейер аватара: Actions ↔ MCP.

Ключа HeyGen у прогона нет — цифровой двойник приходит снаружи. Проверяется
главное свойство схемы: без клипа прогон **останавливается** и говорит, чего
не хватает, а не подставляет заглушку. Молчаливая подмена дала бы ролик без
ведущего, и заметить это можно было бы только глазами (§10.5.4).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.errors import ProviderError
from src.lib import audio as A
from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.providers.avatar import (
    MockAvatar, PreparedAvatar, build_avatar_provider,
)


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def costs(cfg):
    return CostLedger(video_id="test")


@pytest.fixture
def speech(tmp_path):
    """Кусок речи на 2 секунды — то, подо что генерируется клип."""
    path = tmp_path / "seg_00.wav"
    sr = 48000
    tone = (0.2 * np.sin(np.linspace(0, 220 * 2 * np.pi, sr * 2))).astype(np.float32)
    A.save_wav(path, tone, sr)
    return path


def _clip(path: Path, seconds: float, cfg) -> Path:
    """Настоящий клип нужной длины: провайдер сверяет длительность."""
    source = path.parent / "_source.wav"
    sr = 48000
    A.save_wav(source, np.zeros(int(sr * seconds), dtype=np.float32), sr)
    MockAvatar(cfg, CostLedger(video_id="test")).generate(
        audio_path=source, out_path=path, duration_sec=seconds, index=0)
    return path


def test_missing_clip_stops_the_run(cfg, costs, speech, tmp_path):
    provider = PreparedAvatar(cfg, costs, tmp_path / "clips")
    with pytest.raises(ProviderError) as exc:
        provider.generate(audio_path=speech, out_path=tmp_path / "out.mp4",
                          duration_sec=2.0, index=0)
    assert exc.value.code == "AVATAR_CLIP_NOT_PREPARED"
    # Заявка копится, чтобы забрать все клипы за один заход, а не по одному.
    assert provider.missing[0]["index"] == 0
    assert provider.missing[0]["duration_sec"] == 2.0


def test_prepared_clip_is_taken_as_is(cfg, costs, speech, tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    _clip(clips / "seg_00.mov", 2.0, cfg)

    provider = PreparedAvatar(cfg, costs, clips)
    seg = provider.generate(audio_path=speech, out_path=tmp_path / "out.mp4",
                            duration_sec=2.0, index=0)
    assert seg.provider_mode == "prepared"
    assert seg.has_alpha is True                 # .mov несёт альфу
    assert seg.path.exists()


def test_clip_of_wrong_length_is_rejected(cfg, costs, speech, tmp_path):
    """Расхождение длительности — это уехавший липсинк, а не мелочь."""
    clips = tmp_path / "clips"
    clips.mkdir()
    _clip(clips / "seg_00.mov", 3.0, cfg)

    provider = PreparedAvatar(cfg, costs, clips)
    with pytest.raises(ProviderError) as exc:
        provider.generate(audio_path=speech, out_path=tmp_path / "out.mp4",
                          duration_sec=2.0, index=0)
    assert exc.value.code == "AVATAR_CLIP_DURATION_MISMATCH"


def test_source_prepared_never_falls_back_to_mock(cfg, costs, tmp_path, monkeypatch):
    monkeypatch.setenv("HEYGEN_API_KEY", "")
    cfg.set("heygen.source", "prepared")
    cfg.set("heygen.prepared_dir", str(tmp_path))
    provider = build_avatar_provider(cfg, costs, video_id="redshift_0001")
    assert isinstance(provider, PreparedAvatar)


def test_auto_picks_prepared_when_clips_exist(cfg, costs, tmp_path, monkeypatch):
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    clips = tmp_path / "redshift_0001"
    clips.mkdir(parents=True)
    (clips / "seg_00.mov").write_bytes(b"x")
    cfg.set("heygen.source", "auto")
    cfg.set("heygen.prepared_dir", str(tmp_path))
    provider = build_avatar_provider(cfg, costs, video_id="redshift_0001")
    assert isinstance(provider, PreparedAvatar)


def test_live_run_without_a_key_waits_for_clips_instead_of_mocking(
        cfg, costs, tmp_path, monkeypatch):
    """Молчаливый мок-аватар в живом прогоне — худший из возможных исходов.

    Ролик собрался бы, прошёл QC и уехал к зрителю с болванкой вместо
    ведущего. Без ключа прогон обязан уйти в двухфазный конвейер: клипы
    приходят снаружи, а их отсутствие падает с понятным кодом.
    """
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    cfg.set("heygen.source", "auto")
    cfg.set("heygen.prepared_dir", str(tmp_path / "нет"))
    provider = build_avatar_provider(cfg, costs, video_id="redshift_0001")
    assert isinstance(provider, PreparedAvatar)


def test_live_mode_without_a_key_still_goes_two_phase(cfg, costs, tmp_path, monkeypatch):
    """Живой прогон без ключа HeyGen обязан дойти до заявки на клипы.

    Это не гипотетический случай, а рабочий режим проекта: ключа в секретах нет,
    аватар приходит из MCP-коннектора. Реальный прогон падал здесь на
    MISSING_CREDENTIALS, потому что режим сервиса спрашивали раньше, чем
    успевала сработать двухфазная ветка, — и она оказывалась недостижимой ровно
    в том прогоне, ради которого написана.
    """
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    cfg.set("providers.mode", "live")
    cfg.set("heygen.source", "auto")
    cfg.set("heygen.prepared_dir", str(tmp_path))
    provider = build_avatar_provider(cfg, costs, video_id="redshift_0046")
    assert isinstance(provider, PreparedAvatar)


def test_source_api_without_a_key_is_a_configuration_error(cfg, costs, monkeypatch):
    """``api`` заказан явно — значит ключ обязан быть, и молчать об этом нельзя."""
    from src.errors import MissingCredentials

    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    cfg.set("providers.mode", "live")
    cfg.set("heygen.source", "api")
    with pytest.raises(MissingCredentials):
        build_avatar_provider(cfg, costs, video_id="redshift_0046")


def test_mock_mode_overrides_any_avatar_source(cfg, costs, tmp_path, monkeypatch):
    """Mock — это «никаких внешних зависимостей», клипов в нём никто не готовит."""
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    cfg.set("providers.mode", "mock")
    cfg.set("heygen.source", "prepared")
    cfg.set("heygen.prepared_dir", str(tmp_path / "нет"))
    provider = build_avatar_provider(cfg, costs, video_id="redshift_0001")
    assert isinstance(provider, MockAvatar)


def test_green_clip_is_keyed_into_alpha(cfg, costs, speech, tmp_path):
    """HeyGen прозрачности не даёт — альфу делаем сами из ключевого цвета."""
    import subprocess
    from PIL import Image
    from src.lib.ffmpeg import ffmpeg_bin

    clips = tmp_path / "clips"
    clips.mkdir()
    frame = Image.new("RGB", (216, 384), (11, 177, 64))
    for x in range(80, 140):
        for y in range(120, 300):
            frame.putpixel((x, y), (18, 18, 22))
    png = clips / "src.png"
    frame.save(png)
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                    "-loop", "1", "-i", str(png), "-t", "2.0", "-r", "10",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(clips / "seg_00.mp4")], check=True, capture_output=True)
    png.unlink()

    cfg.set("heygen.prepared_chroma", "#00B140")
    seg = PreparedAvatar(cfg, costs, clips).generate(
        audio_path=speech, out_path=tmp_path / "out.mp4",
        duration_sec=2.0, index=0)

    assert seg.has_alpha is True
    assert seg.path.suffix == ".mov"


def test_without_chroma_setting_mp4_stays_opaque(cfg, costs, speech, tmp_path):
    """Ключевание — осознанная настройка, а не догадка по расширению."""
    import subprocess
    from src.lib.ffmpeg import ffmpeg_bin

    clips = tmp_path / "clips"
    clips.mkdir()
    from PIL import Image
    png = clips / "src.png"
    Image.new("RGB", (216, 384), (11, 177, 64)).save(png)
    subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                    "-loop", "1", "-i", str(png), "-t", "2.0", "-r", "10",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(clips / "seg_00.mp4")], check=True, capture_output=True)
    png.unlink()

    cfg.set("heygen.prepared_chroma", "")
    seg = PreparedAvatar(cfg, costs, clips).generate(
        audio_path=speech, out_path=tmp_path / "out.mp4",
        duration_sec=2.0, index=0)
    assert seg.has_alpha is False
