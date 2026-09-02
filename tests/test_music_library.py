"""Курируемая библиотека подложек: приём живых записей вместо синтеза.

Пятнадцать сгенерированных бедов заказчик отверг словами «это ужас, я хотел
хорошие сэмплы живых инструментов». Синтез удалён целиком, а не спрятан за
флагом: отключённый он вернулся бы первым же прогоном ``fill-libraries``,
который стоит в наборе по умолчанию.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.lib.config import load_config
from src.lib.music_library import (
    MAX_PEAK_DBFS, MIN_DURATION_SEC, MOOD_IDS, add_bed, check_bed, inspect_bed,
    library_status,
)


def _bed(path: Path, *, seconds: float = 40.0, db: float = -6.0,
         freq: int = 220) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:duration={seconds}",
         "-af", f"volume={db}dB", "-c:a", "libmp3lame", "-b:a", "320k", str(path)],
        check=True)
    return path


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config()
    cfg.set("paths.assets_dir", str(tmp_path / "assets"))
    return cfg


class TestTheSynthesiserIsGone:
    def test_nothing_can_synthesise_a_bed_any_more(self):
        """Функции синтеза музыки не должно существовать ни под каким именем."""
        import src.lib.sfx_synth as synth

        for name in ("synth_music", "MUSIC_MOODS", "music_recipe", "_sequence", "_note"):
            assert not hasattr(synth, name), f"{name} вернулся в модуль синтеза"

    def test_filling_the_library_adds_nothing(self, cfg):
        """`fill-libraries` не имеет права воссоздать отвергнутое."""
        from src.lib.library_filler import fill_music

        result = fill_music(cfg)
        assert result["added"] == []
        assert result["curated"] is True
        assert "add-music" in result["note"]

    def test_the_sfx_synthesiser_is_untouched(self):
        """Удалена музыка, а не звук: двадцать SFX остаются синтезированными."""
        from src.lib.sfx_synth import SFX_ROLES, synth_sfx

        assert len(SFX_ROLES) == 20
        assert len(synth_sfx("pop")) > 0


class TestIntakeMeasuresBeforeItAccepts:
    def test_a_good_recording_is_accepted_and_measured(self, cfg, tmp_path):
        report = add_bed(cfg, source=_bed(tmp_path / "live.mp3"), mood="piano_quiet",
                         title="живое пианино")
        assert report["warnings"] == []
        assert report["measured"]["duration_sec"] == pytest.approx(40.0, abs=0.2)
        assert library_status(cfg)["present"] == ["piano_quiet"]

    def test_a_short_recording_is_refused(self, cfg, tmp_path):
        """Короче двадцати секунд — ролик услышит повтор петли."""
        from src.errors import RedshiftError

        with pytest.raises(RedshiftError) as excinfo:
            add_bed(cfg, source=_bed(tmp_path / "short.mp3", seconds=8.0),
                    mood="piano_sad")
        assert excinfo.value.code == "MUSIC_REJECTED"
        assert "короче" in str(excinfo.value)

    def test_a_clipped_recording_is_refused(self):
        """Пик под нулём: в миксе к беду добавится голос, и запас нужен."""
        problems = check_bed({"duration_sec": 40.0, "integrated_lufs": -18.0,
                              "peak_dbfs": -0.1, "loop_seam": 0.0})
        assert any("пик" in p for p in problems), problems
        assert MAX_PEAK_DBFS < 0

    def test_an_unknown_mood_is_refused(self, cfg, tmp_path):
        """Настроение — это роль, по которой планировщик выбирает бед."""
        from src.errors import RedshiftError

        with pytest.raises(RedshiftError) as excinfo:
            add_bed(cfg, source=_bed(tmp_path / "live.mp3"), mood="лучший_трек")
        assert excinfo.value.code == "MUSIC_UNKNOWN_MOOD"

    def test_force_takes_a_recording_the_checks_dislike(self, cfg, tmp_path):
        """Последнее слово за заказчиком — но замечания остаются в записи."""
        report = add_bed(cfg, source=_bed(tmp_path / "short.mp3", seconds=8.0),
                         mood="piano_sad", force=True)
        assert report["warnings"], "замечания потерялись"
        assert MIN_DURATION_SEC > 8.0

    def test_the_same_mood_twice_replaces_and_does_not_duplicate(self, cfg, tmp_path):
        add_bed(cfg, source=_bed(tmp_path / "a.mp3"), mood="violin_drive")
        add_bed(cfg, source=_bed(tmp_path / "b.mp3", freq=330), mood="violin_drive")
        status = library_status(cfg)
        assert status["count"] == 1 and status["present"] == ["violin_drive"]

    def test_inspecting_changes_nothing(self, cfg, tmp_path):
        src = _bed(tmp_path / "live.mp3")
        before = src.read_bytes()
        report = inspect_bed(src)
        assert report["duration_sec"] > 0
        assert src.read_bytes() == before
        assert library_status(cfg)["count"] == 0


def test_every_mood_the_planner_can_pick_is_in_the_vocabulary():
    """Планировщик не имеет права попросить бед, которого нет в словаре."""
    from src.p1_plan.planner import (
        MUSIC_BY_CATEGORY, MUSIC_BY_SCRIPT_ONLY, MUSIC_DEFAULT, MUSIC_ON_TWIST,
    )

    reachable = set(MUSIC_BY_SCRIPT_ONLY) | set(MUSIC_DEFAULT) | set(MUSIC_ON_TWIST)
    for family in MUSIC_BY_CATEGORY.values():
        reachable |= set(family)
    assert reachable <= set(MOOD_IDS), sorted(reachable - set(MOOD_IDS))
