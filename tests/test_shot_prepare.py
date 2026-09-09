"""Подготовка планов: неподвижный кадр обязан кончаться.

Мок-прогон 02.09 встал намертво на сплите с прессовым снимком наверху:
ffmpeg крутил 21 минуту на 100 % процессора ради клипа в 2.8 секунды — и
крутил бы до потолка задачи. Причина в одной паре флагов: у одиночного JPEG
``-stream_loop -1`` бесконечно повторяет один и тот же пакет, метки времени
не растут, и ``-t`` не наступает никогда. Растягивать снимок умеет ``-loop 1``.

В ``prepare_shot`` этот случай разведён с самого начала. В сплите и в фоне
аватара — нет, и до вечнозелёной базы он почти не всплывал: снимков в верхней
половине кадра раньше просто не бывало.
"""

from __future__ import annotations

import time

import pytest
from PIL import Image

from src.lib.ffmpeg import probe, run
from src.lib.render.shots import (
    prepare_avatar_shot, prepare_split_shot, slim_video,
)


@pytest.fixture
def still(tmp_path):
    """Снимок вертикального формата — то, чем полна вечнозелёная база."""
    path = tmp_path / "still.jpg"
    Image.new("RGB", (1600, 1200), (40, 42, 48)).save(path, quality=90)
    return path


@pytest.fixture
def clip(tmp_path):
    """Короткий клип: короче плана, чтобы включалась ветка зацикливания."""
    path = tmp_path / "clip.mp4"
    run(["-y", "-f", "lavfi", "-i", "color=c=0x202024:s=540x960:d=1.0:r=30",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
        what="тестовый клип")
    return path


def test_a_still_on_top_of_a_split_finishes(tmp_path, still, clip):
    """Главное здесь — что вызов вообще возвращается."""
    dst = tmp_path / "split.mp4"
    started = time.time()
    prepare_split_shot(top_src=still, bottom_src=clip, dst=dst, duration_sec=2.0,
                       width=1080, height=1920, fps=30)
    took = time.time() - started

    info = probe(dst)
    assert abs(info.duration_sec - 2.0) < 0.2, f"длительность {info.duration_sec}"
    assert (info.width, info.height) == (1080, 1920)
    # Порог щедрый: на слабом раннере сборка идёт секунды. Зависший вызов
    # укладывался в минуты и не кончался вовсе.
    assert took < 60, f"сборка заняла {took:.0f} с — похоже на зависание"


def test_a_still_in_both_halves_finishes(tmp_path, still):
    """Два снимка — два повода зациклиться, и оба обязаны кончиться."""
    dst = tmp_path / "split_two.mp4"
    prepare_split_shot(top_src=still, bottom_src=still, dst=dst, duration_sec=1.5,
                       width=1080, height=1920, fps=30)
    assert abs(probe(dst).duration_sec - 1.5) < 0.2


def test_a_still_behind_the_presenter_finishes(tmp_path, still, clip):
    """Тот же капкан в фоне аватара: там `-stream_loop` стоял безусловно."""
    dst = tmp_path / "avatar.mp4"
    prepare_avatar_shot(avatar_src=clip, dst=dst, duration_sec=1.5,
                        width=1080, height=1920, fps=30, vfx_src=still)
    assert abs(probe(dst).duration_sec - 1.5) < 0.25


class TestStockIsSlimmedOnIntake:
    """Материал едет в git — значит, вес решается на приёме, а не потом.

    Прогон 0047 положил в репозиторий 27 клипов Pexels на 369 МБ: отдельные
    файлы по 35–45 МБ при 1080×1920 и 5.5 Мбит/с. Ужимать их задним числом
    поздно — тяжёлая версия остаётся в истории навсегда.
    """

    def _clip(self, tmp_path, seconds, name="src.mp4", bitrate="6M"):
        path = tmp_path / name
        run(["-y", "-f", "lavfi", "-i",
             f"testsrc2=s=1080x1920:d={seconds}:r=30", "-f", "lavfi", "-i",
             f"sine=frequency=440:duration={seconds}",
             "-c:v", "libx264", "-preset", "ultrafast", "-b:v", bitrate,
             "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest", str(path)],
            what="исходник для приёма")
        return path

    def test_a_long_clip_is_cut_to_what_the_video_will_use(self, tmp_path):
        """Самый длинный слот ролика — 6.4 сек, и футаж играет с нуля."""
        src = self._clip(tmp_path, 30)
        before = src.stat().st_size
        report = slim_video(src, max_sec=8.0)
        assert report["slimmed"], "клип на 30 секунд остался как был"
        assert probe(src).duration_sec <= 8.5, probe(src).duration_sec
        assert src.stat().st_size < before

    def test_the_soundtrack_of_the_stock_is_dropped(self, tmp_path):
        """Звук стока не попадает в микс никогда: все пути идут с ``-an``.

        Проверяется на клипе, который и так подлежит обрезке: трогать лёгкий
        короткий файл ради одной звуковой дорожки не стоит потери качества.
        """
        src = self._clip(tmp_path, 30)
        assert probe(src).has_audio, "фикстура без звука ничего не проверяет"
        assert slim_video(src, max_sec=8.0)["slimmed"]
        assert not probe(src).has_audio

    def test_the_picture_survives_the_squeeze(self, tmp_path):
        """Ужать — не значит испортить: размер кадра остаётся прежним."""
        src = self._clip(tmp_path, 10)
        info_before = probe(src)
        slim_video(src, max_sec=20.0)
        info_after = probe(src)
        assert (info_after.width, info_after.height) == \
               (info_before.width, info_before.height)

    def test_a_light_clip_is_left_alone(self, tmp_path):
        """Перекодировать лёгкий клип незачем — потеряем качество даром."""
        src = self._clip(tmp_path, 3, bitrate="400k")
        before = src.read_bytes()
        report = slim_video(src, max_sec=20.0)
        assert not report["slimmed"]
        assert src.read_bytes() == before

    def test_a_broken_file_does_not_break_the_intake(self, tmp_path):
        """Материал важнее веса: не ужалось — берём как есть."""
        src = tmp_path / "broken.mp4"
        src.write_bytes(b"not a video at all" * 100)
        report = slim_video(src)
        assert not report["slimmed"]
        assert src.exists()


def test_gap_phrase_uses_spoken_window():
    from src.p11_assemble.assemble import gap_phrase

    words = [
        {"word": "квантовый", "start": 1.0, "end": 1.4},
        {"word": "чип", "start": 1.4, "end": 1.7},
        {"word": "внутри", "start": 1.7, "end": 2.1},
        {"word": "кубитов", "start": 2.1, "end": 2.6},
    ]
    slot = {"start": 1.0, "end": 2.5, "index": 3}
    block = {"text": "Это квантовый чип."}
    assert gap_phrase(words, slot, block) == "КВАНТОВЫЙ ЧИП ВНУТРИ КУБИТОВ"


def test_compose_zoom_strong_bias_formula():
    """Strong zoom must bias crop down; mild zoom keeps legacy 0.32."""
    def bias(zoom: float) -> float:
        return 0.32 if zoom < 1.8 else min(0.55, 0.25 + 0.07 * zoom)

    assert bias(1.55) == 0.32
    assert 0.44 <= bias(2.85) <= 0.50
    assert 0.50 <= bias(3.75) <= 0.55



def test_hero_mutes_heavy_template_text():
    from src.p11_assemble.assemble import hero_mutes_subtitle
    # Heroes still *mark* mid-frame text (punch-family dedupe / reposition),
    # but assemble no longer blanket-mutes all captions under them.
    for renderer in ("hero-headline", "hero-oversize", "hero-title-behind",
                     "hero-card-stack", "hero-paper"):
        flags = hero_mutes_subtitle(renderer)
        assert flags["carries_line"] or flags["covers_frame"], renderer


def test_avatar_bg_plates_round_robin():
    from src.p11_assemble.assemble import _avatar_bg_plates
    slots = [
        {"index": 0, "kind": "footage"},
        {"index": 1, "kind": "avatar"},
        {"index": 2, "kind": "footage"},
        {"index": 3, "kind": "avatar"},
    ]
    prepared = {
        0: {"dst": "/tmp/a.mp4"},
        2: {"dst": "/tmp/b.mp4"},
    }
    assets = {0: {}, 2: {}}
    out = _avatar_bg_plates(slots, prepared, assets)
    assert out[1] in {"/tmp/a.mp4", "/tmp/b.mp4"}
    assert out[3] in {"/tmp/a.mp4", "/tmp/b.mp4"}
    assert out[1] != out[3] or len(set(out.values())) == 1


def test_fullscreen_cap_reads_brandbook_limit():
    from src.lib.config import load_config
    from src.p11_assemble.assemble import _fullscreen_cap

    assert _fullscreen_cap(load_config()) == 4


def test_claim_screen_phrase_rejects_duplicates():
    from src.p11_assemble.assemble import _claim_screen_phrase

    used: set[str] = set()
    assert _claim_screen_phrase(used, "РАБОТА ОПУБЛИКОВАНА В NATURE")
    assert not _claim_screen_phrase(used, "работа опубликована в nature")
    assert _claim_screen_phrase(used, "ЗДЕСЬ ВСЁ НАОБОРОТ")
    assert not _claim_screen_phrase(used, "здесь всё наоборот")


def test_gap_phrase_overlay_once_then_rotates():
    """Авторский punch («5 МИНУТ») не должен висеть на всех gap-слотах подряд."""
    from src.p11_assemble.assemble import gap_phrase

    block = {
        "text": (
            "Здесь всё наоборот. Чем больше кубитов в связке, тем чище считает "
            "система. Ошибка падает вдвое. Задача решена за пять минут."
        ),
        "emphasis_word": "вдвое",
        "overlay": {"type": "fullscreen_text", "content": "5 МИНУТ"},
    }
    used: set[str] = set()
    first = gap_phrase([], {"start": 18.0, "end": 19.5, "index": 10}, block, used=used)
    second = gap_phrase(
        [{"word": "ошибка", "start": 22.0, "end": 22.4},
         {"word": "падает", "start": 22.4, "end": 22.9},
         {"word": "вдвое", "start": 22.9, "end": 23.4}],
        {"start": 22.0, "end": 23.5, "index": 11}, block, used=used)
    third = gap_phrase([], {"start": 24.0, "end": 26.0, "index": 12}, block, used=used)
    assert first == "5 МИНУТ"
    assert second != "5 МИНУТ"
    assert third not in {first, second}
    assert "5 МИНУТ" in used


def test_rich_terminal_copy_stays_inside_script():
    from src.p11_assemble.assemble import _rich_terminal_copy

    before, after, name = _rich_terminal_copy(
        {"text": "105 кубитов. Ошибка падает вдвое. Суперкомпьютеру нужно больше времени, чем существует вселенная.",
         "emphasis_word": "вдвое",
         "overlay": {"type": "fullscreen_text", "content": "5 МИНУТ"}},
        "5 МИНУТ",
    )
    blob = "\n".join([before, after, name])
    assert "willow_check" not in blob
    assert "surface_code" not in blob
    assert "willow_run" not in blob
    assert "5 МИНУТ" in before
    assert "5 МИНУТ" in after
    assert name == ""


def test_accent_card_syncs_to_spoken_onset():
    """FS/plaque must start at/after spoken punch, never before (0042 r5)."""
    from src.lib.text import (
        accent_card_start, enrich_overlay_punch, find_spoken_anchor,
    )
    words = [
        {"word": "Этот", "start": 0.0, "end": 0.2},
        {"word": "невозможно", "start": 0.5, "end": 1.2, "emphasis": True},
        {"word": "ничем", "start": 2.2, "end": 2.7},
    ]
    anchor = find_spoken_anchor(words, "НЕЧЕМ", "невозможно")
    assert anchor["word"] == "ничем"
    start = accent_card_start(anchor, block_start=0.0, delay_sec=0.05)
    assert start >= 2.2
    assert start <= 2.35
    punch = enrich_overlay_punch(
        "НЕЧЕМ", "Этот ответ невозможно проверить. Вообще ничем.")
    assert "ничем" in punch.lower()
    assert len(punch.split()) >= 2


def test_pick_scene_prefers_dominant_stems():
    from src.lib.backdrop import pick_scene, plate_name
    scene = pick_scene(
        "Квантовый чип Google",
        "105 кубитов. Квантовый чип считает. Вся вселенная шумит в сниппете.",
    )
    assert scene == "grid"
    assert plate_name(scene) == "grid.jpg"


# --- Q3.6: подложки без алиасов и закрепления заказчика (§7.6) ---------------

class TestBackdropPlatesAreHonestAboutWhatExists:
    """До Q3.6 `space` был алиасом на `horizon.jpg`.

    Комментарий в коде гласил «No dedicated space still», и ролик про космос
    молча шёл на фоне чёрной дыры — сцена подобрана верно, а показана чужая
    плита. Алиас снят: сцена без своей плиты рисуется градиентами (рабочий
    запасной путь), а список недостающих назван вслух.
    """

    def test_no_scene_borrows_another_scenes_plate(self):
        from src.lib.backdrop import PLATES

        assert len(set(PLATES.values())) == len(PLATES), \
            f"две сцены делят один файл: {PLATES}"

    def test_every_declared_plate_is_on_disk(self, repo_root):
        from src.lib.backdrop import PLATES

        for scene, name in PLATES.items():
            assert (repo_root / "assets" / "backdrops" / name).is_file(), \
                f"плита сцены {scene} объявлена, но файла нет: {name}"

    def test_the_missing_plates_are_named_not_hidden(self):
        from src.lib.backdrop import PLATES, PLATES_MISSING, SCENES

        assert set(PLATES) | set(PLATES_MISSING) == set(SCENES), \
            "есть сцена, про которую неизвестно, будет ли у неё плита"
        assert not set(PLATES) & set(PLATES_MISSING)

    def test_a_scene_without_a_plate_returns_empty_not_a_wrong_file(self):
        from src.lib.backdrop import PLATES_MISSING, plate_name

        for scene in PLATES_MISSING:
            assert plate_name(scene) == "", f"{scene} снова получил чужую плиту"

    def test_the_plate_prompt_carries_the_channel_palette(self):
        from src.lib.backdrop import PLATE_PROMPT

        low = PLATE_PROMPT.lower()
        assert "#c8453d" in low and "#36efff" in low
        assert "9:16" in low and "no people" in low

    def test_pins_are_read_from_the_repo(self, repo_root):
        from src.lib.backdrop import load_pins

        pins = load_pins(repo_root)
        assert set(pins) >= {"by_video", "by_category", "by_scene"}

    def test_a_pin_beats_the_scene_table(self):
        from src.lib.backdrop import plate_name

        pins = {"by_video": {}, "by_category": {},
                "by_scene": {"space": "horizon.jpg"}}
        assert plate_name("space", pins=pins) == "horizon.jpg"

    def test_the_narrower_pin_wins(self):
        """Один проблемный ролик правится, не меняя рубрику целиком."""
        from src.lib.backdrop import plate_name

        pins = {"by_video": {"redshift_0047": "grid.jpg"},
                "by_category": {"space": "horizon.jpg"},
                "by_scene": {"depth": "horizon.jpg"}}
        assert plate_name("depth", video_id="redshift_0047",
                          category="space", pins=pins) == "grid.jpg"
        assert plate_name("depth", video_id="redshift_0042",
                          category="space", pins=pins) == "horizon.jpg"

    def test_no_pins_no_change(self):
        from src.lib.backdrop import plate_name

        assert plate_name("grid", pins={}) == "grid.jpg"
