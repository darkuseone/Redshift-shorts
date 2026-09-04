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
    INSTRUMENTS, MAX_PEAK_DBFS, TAGS, add_bed, check_bed, find_segment,
    inspect_bed, library_status, pick_bed,
)


def _bed(path: Path, *, seconds: float = 40.0, db: float = -6.0,
         freq: int = 220) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:duration={seconds}",
         "-af", f"volume={db}dB", "-c:a", "libmp3lame", "-b:a", "320k", str(path)],
        check=True)
    return path


def _quiet_then_loud(path: Path) -> Path:
    """Запись как присланные: тихое вступление, потом плотная середина."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=220:duration=120",
         "-af", "volume='if(lt(t,40),0.02,0.6)':eval=frame",
         "-ar", "48000", "-ac", "2", str(path)], check=True)
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

    def test_filling_sfx_also_adds_nothing(self, cfg):
        """Короткие звуки тоже курируемые: fill не синтезирует их обратно."""
        from src.lib.library_filler import fill_sfx

        result = fill_sfx(cfg)
        assert result["added"] == []
        assert result["curated"] is True


class TestIntakeMeasuresBeforeItAccepts:
    def test_a_good_recording_is_accepted_and_measured(self, cfg, tmp_path):
        report = add_bed(cfg, source=_bed(tmp_path / "live.mp3", seconds=120.0),
                         bed_id="live_one", tags=["strings", "space", "wide"],
                         title="живые струнные")
        assert report["warnings"] == []
        assert report["measured"]["duration_sec"] == pytest.approx(70.0, abs=0.3)
        assert [b["id"] for b in library_status(cfg)["beds"]] == ["music_live_one"]

    def test_the_interesting_part_is_cut_not_the_intro(self, cfg, tmp_path):
        """Начало записи — вступление из тишины, под ролик оно не годится.

        Заказчик просил «вырезай всегда интересный отрезок». Здесь запись
        нарочно устроена как присланные: тихое начало, плотная середина.
        """
        src = _quiet_then_loud(tmp_path / "shaped.wav")
        start = find_segment(src, length_sec=60.0)
        assert start > 30.0, f"взято вступление: старт {start} с"

    def test_the_clipped_master_gets_headroom_back(self, cfg, tmp_path):
        """Присланные мастера клиппованы: пики от +0.2 до +2.4 dBFS.

        В миксе к беду добавится голос, и запас нужен. Уровень при этом не
        задаётся — его ставит P10 по LUFS под конкретный ролик.
        """
        loud = _bed(tmp_path / "hot.mp3", seconds=120.0, db=6.0)
        report = add_bed(cfg, source=loud, bed_id="hot_one", tags=["ambient", "space"])
        assert report["measured"]["peak_dbfs"] <= MAX_PEAK_DBFS, report["measured"]

    def test_a_recording_without_tags_is_refused(self, cfg, tmp_path):
        """Тег — это то, по чему подложку и находят."""
        from src.errors import RedshiftError

        with pytest.raises(RedshiftError) as excinfo:
            add_bed(cfg, source=_bed(tmp_path / "live.mp3"), bed_id="no_tags", tags=[])
        assert excinfo.value.code == "MUSIC_NO_TAGS"

    def test_a_recording_without_an_instrument_is_refused(self, cfg, tmp_path):
        """Без инструмента монтаж не отличит скрипку от эмбиента."""
        from src.errors import RedshiftError

        with pytest.raises(RedshiftError) as excinfo:
            add_bed(cfg, source=_bed(tmp_path / "live.mp3"), bed_id="themed",
                    tags=["space", "calm"])
        assert excinfo.value.code == "MUSIC_NO_INSTRUMENT"

    def test_an_unknown_tag_is_refused(self, cfg, tmp_path):
        """Словарь закрытый: опечатка в теге — это подложка, которую не найдут."""
        from src.errors import RedshiftError

        with pytest.raises(RedshiftError) as excinfo:
            add_bed(cfg, source=_bed(tmp_path / "live.mp3"), bed_id="typo",
                    tags=["strings", "kosmos"])
        assert excinfo.value.code == "MUSIC_UNKNOWN_TAG"

    def test_the_same_id_twice_replaces_and_does_not_duplicate(self, cfg, tmp_path):
        add_bed(cfg, source=_bed(tmp_path / "a.mp3", seconds=120.0),
                bed_id="twice", tags=["strings", "space"])
        add_bed(cfg, source=_bed(tmp_path / "b.mp3", seconds=120.0, freq=330),
                bed_id="twice", tags=["strings", "space"])
        assert library_status(cfg)["count"] == 1

    def test_inspecting_changes_nothing(self, cfg, tmp_path):
        src = _bed(tmp_path / "live.mp3", seconds=120.0)
        before = src.read_bytes()
        assert inspect_bed(src)["duration_sec"] > 0
        assert src.read_bytes() == before
        assert library_status(cfg)["count"] == 0


class TestTheMontagePicksOnItsOwn:
    """«Чтобы монтаж умел брать их самостоятельно» — слова заказчика."""

    def _fill(self, cfg, tmp_path):
        for bed_id, tags in (("wide_space", ["ambient", "space", "wide"]),
                             ("deep_space", ["ambient", "space", "calm"]),
                             ("busy_tech", ["pulse", "tech", "driving"])):
            add_bed(cfg, source=_bed(tmp_path / f"{bed_id}.mp3", seconds=120.0),
                    bed_id=bed_id, tags=tags)

    def test_tags_decide_which_bed_plays(self, cfg, tmp_path):
        self._fill(cfg, tmp_path)
        bed = pick_bed(cfg, want=["tech", "pulse", "driving"], video_id="redshift_0100")
        assert bed.id == "music_busy_tech", bed.tags

    def test_a_tie_is_split_so_the_channel_does_not_repeat_itself(self, cfg, tmp_path):
        """Два беда с равным совпадением обязаны разойтись по роликам.

        Прежний развод брал первый байт хэша, то есть делил надвое по
        чётности: у роликов 0047, 0048 и 0049 он оказался 216, 186 и 196 —
        все чётные, и все три получили одну и ту же подложку.
        """
        self._fill(cfg, tmp_path)
        picked = {pick_bed(cfg, want=["ambient", "space"],
                           video_id=f"redshift_{n:04d}").id for n in range(40, 70)}
        assert len(picked) > 1, "вся рубрика на одной подложке"

    def test_a_recently_used_bed_yields_to_a_fresh_one(self, cfg, tmp_path):
        """При равном совпадении вперёд идёт та, что звучала реже."""
        from src.lib.manifest import open_library

        self._fill(cfg, tmp_path)
        lib = open_library(cfg, "music")
        lib.mark_used("music_wide_space", "redshift_0001")
        lib.mark_used("music_wide_space", "redshift_0002")
        lib.save()
        bed = pick_bed(cfg, want=["ambient", "space"], video_id="redshift_0003")
        assert bed.id == "music_deep_space", "заезженная подложка снова выиграла"

    def test_matching_beats_freshness(self, cfg, tmp_path):
        """Свежесть — второе правило: лучше повтор верного, чем свежий чужой."""
        from src.lib.manifest import open_library

        self._fill(cfg, tmp_path)
        lib = open_library(cfg, "music")
        for n in range(5):
            lib.mark_used("music_busy_tech", f"redshift_{n:04d}")
        lib.save()
        bed = pick_bed(cfg, want=["tech", "pulse", "driving"], video_id="redshift_0100")
        assert bed.id == "music_busy_tech"

    def test_the_same_video_always_gets_the_same_bed(self, cfg, tmp_path):
        """Иначе версии A и B разъедутся по звуку, и сравнивать станет нечем."""
        self._fill(cfg, tmp_path)
        first = pick_bed(cfg, want=["ambient", "space"], video_id="redshift_0047")
        second = pick_bed(cfg, want=["ambient", "space"], video_id="redshift_0047")
        assert first.id == second.id

    def test_an_empty_library_says_so_instead_of_guessing(self, cfg):
        assert pick_bed(cfg, want=["space"], video_id="redshift_0001") is None


def test_the_planner_asks_only_for_tags_that_exist():
    """Планировщик не имеет права просить тег, которого нет в словаре."""
    from src.p1_plan.planner import (
        MUSIC_TAGS_BY_CATEGORY, MUSIC_TAGS_DEFAULT, MUSIC_TAGS_ON_TWIST,
    )

    wanted = set(MUSIC_TAGS_DEFAULT) | set(MUSIC_TAGS_ON_TWIST)
    for family in MUSIC_TAGS_BY_CATEGORY.values():
        wanted |= set(family)
    assert wanted <= set(TAGS), sorted(wanted - set(TAGS))
    assert any(t in INSTRUMENTS for t in wanted), "ни одна рубрика не просит инструмент"


def test_the_committed_library_is_tagged_for_the_montage():
    """Библиотека в репозитории: у каждой подложки инструмент и тема."""
    import json
    from pathlib import Path

    from src.lib.music_library import THEMES

    manifest = Path("assets/music/music_manifest.json")
    if not manifest.exists():
        pytest.skip("манифеста нет")
    items = json.loads(manifest.read_text("utf-8"))["items"]
    if not items:
        pytest.skip("библиотека пуста")
    for item in items:
        tags = set(item["tags"])
        assert tags & set(INSTRUMENTS), f"{item['id']}: нет тега инструмента"
        assert tags & set(THEMES), f"{item['id']}: нет тега темы"
        assert (Path("assets/music") / item["file"]).exists(), item["file"]


class TestThePlanReachesTheMix:
    """Стык «план → библиотека»: P10 обязан услышать теги из плана.

    Проверяется отдельной функцией, а не через весь P10: поднимать ради трёх
    условий голос, SFX и ffmpeg значит не проверять стык вовсе. Ровно на
    непроверенном стыке конвейер уже падал — строка жила под условием,
    которого не бывает в мок-режиме, и вылезла только на живом прогоне через
    полчаса работы раннера.
    """

    def _fill(self, cfg, tmp_path):
        for bed_id, tags in (("calm_space", ["ambient", "space", "calm"]),
                             ("busy_tech", ["pulse", "tech", "driving"]),
                             ("soft_keys", ["piano", "tech", "sparse"])):
            add_bed(cfg, source=_bed(tmp_path / f"{bed_id}.mp3", seconds=120.0),
                    bed_id=bed_id, tags=tags)

    def test_tags_from_the_plan_choose_the_bed(self, cfg, tmp_path):
        from src.p10_audio.audio_build import choose_bed

        self._fill(cfg, tmp_path)
        bed = choose_bed(cfg, {"video_id": "redshift_0047",
                               "music_tags": ["tech", "pulse", "driving"]})
        assert bed.id == "music_busy_tech", bed.tags

    def test_a_mood_named_by_the_script_wins_over_tags(self, cfg, tmp_path):
        """Ручное решение автора важнее любой автоматики."""
        from src.p10_audio.audio_build import choose_bed

        self._fill(cfg, tmp_path)
        bed = choose_bed(cfg, {"video_id": "redshift_0047", "music_mood": "piano",
                               "music_tags": ["tech", "pulse", "driving"]})
        assert bed.id == "music_soft_keys", bed.tags

    def test_a_plan_without_music_still_gets_a_bed(self, cfg, tmp_path):
        """Старый план без тегов не должен оставлять ролик без подложки."""
        from src.p10_audio.audio_build import choose_bed

        self._fill(cfg, tmp_path)
        assert choose_bed(cfg, {"video_id": "redshift_0047"}) is not None

    def test_an_empty_library_leaves_the_mix_without_a_bed(self, cfg):
        """И это не падение: P10 предупреждает и собирает микс без подложки."""
        from src.p10_audio.audio_build import choose_bed

        assert choose_bed(cfg, {"video_id": "redshift_0047",
                                "music_tags": ["space"]}) is None


class TestTheBedIsAShareOfTheVoice:
    """Уровень подложки задан долей от голоса, а не абсолютным LUFS.

    Заказчик думает именно так — «5-7% громкости от моего голоса», — и
    переводить это в LUFS руками при каждой правке значит однажды перевести
    неверно. Доля амплитудная: 0.06 → −24.4 дБ от голоса.
    """

    def test_the_target_matches_the_requested_share(self):
        import math

        from src.lib.config import load_config
        from src.p10_audio.audio_build import music_target_lufs

        cfg = load_config()
        ratio = cfg.get("audio.music_voice_ratio")
        assert ratio, "доля не задана — уровень снова абсолютный"
        voice = float(cfg.get("audio.voice_lufs", -14))
        share = 10 ** ((music_target_lufs(cfg) - voice) / 20)
        # Цель округлена до сотых децибела, поэтому доля попадает в коридор с
        # точностью до 0.01 дБ — на границе коридора это ±0.02 % громкости.
        slack = 0.0002
        assert float(ratio[0]) - slack <= share <= float(ratio[-1]) + slack, \
            f"{share:.3f} вне коридора {ratio}"

    def test_qc_measures_the_same_corridor_the_mix_aims_at(self):
        """Два места с одним смыслом обязаны считать одинаково.

        Иначе QC однажды забракует ровно то, что конвейер сам и собрал.
        """
        import math

        from src.lib.config import load_config
        from src.p10_audio.audio_build import music_target_lufs

        cfg = load_config()
        ratio = cfg.get("audio.music_voice_ratio")
        voice = float(cfg.get("audio.voice_lufs", -14))
        lo = voice + 20 * math.log10(float(ratio[0])) - 1.5
        hi = voice + 20 * math.log10(float(ratio[-1])) + 1.5
        assert lo < music_target_lufs(cfg) < hi

    def test_an_absolute_corridor_still_works_without_a_share(self):
        """Запасной путь: доля не задана — берём абсолютные числа."""
        from src.lib.config import load_config
        from src.p10_audio.audio_build import music_target_lufs

        cfg = load_config()
        cfg.set("audio.music_voice_ratio", None)
        cfg.set("audio.music_lufs", [-40, -36])
        assert music_target_lufs(cfg) == pytest.approx(-38.0)


def test_every_bed_is_cut_to_the_length_of_a_whole_video():
    """70 секунд — потолок длины ролика: подложка не повторится ни разу.

    Заказчик назвал это число прямо. До него резали по 60, и в самом длинном
    ролике петля успевала прозвучать дважды.
    """
    import json
    from pathlib import Path

    manifest = Path("assets/music/music_manifest.json")
    if not manifest.exists():
        pytest.skip("манифеста нет")
    items = json.loads(manifest.read_text("utf-8"))["items"]
    if not items:
        pytest.skip("библиотека пуста")
    for item in items:
        assert item["duration_sec"] == pytest.approx(70.0, abs=0.5), \
            f"{item['id']}: {item['duration_sec']} сек"
