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
from src.lib.render.shots import prepare_avatar_shot, prepare_split_shot


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
