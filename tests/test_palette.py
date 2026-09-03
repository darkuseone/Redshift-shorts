"""Цвет кадра против палитры канала (§3.1).

Пороги здесь не назначены, а выведены из кадров живого прогона 0047. Тесты
воспроизводят те же четыре случая, на которых мерка калибровалась, — включая
два, которые её и заставили появиться.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from src.lib.palette import off_palette_share, palette_verdict


@pytest.fixture
def rules():
    with open("config/brandbook.json", encoding="utf-8") as fh:
        return json.load(fh)["color_rules"]["footage_palette"]


def _flat(rgb: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", (320, 568), rgb)


def _mostly_dark(spot: tuple[int, int, int], share: float = 0.125) -> Image.Image:
    """Тёмный кадр с ярким пятном на заданной доле площади."""
    a = np.full((568, 320, 3), 16, dtype=np.uint8)
    rows = int(round(568 * share * 2))     # пятно на половину ширины
    a[:rows, :160] = spot
    return Image.fromarray(a)


# --- кадры, на которых мерка калибровалась -----------------------------------

@pytest.mark.parametrize("name,rgb,allowed", [
    # Фирменный красный и его соседи — проходят при любой яркости.
    ("акцент #C8453D", (200, 69, 61), True),
    ("тёмный акцент #8E2F2A", (142, 47, 42), True),
    ("почти чёрный кадр", (17, 18, 20), True),
    ("белый кадр", (247, 245, 243), True),
    # Розовые кубы Pexels: оттенок 339°, заняли весь кадр. Из-за них всё и начато.
    ("розовая маджента", (137, 33, 70), False),
    # Жёлто-оранжевая лава: тот самый золотой, который из палитры выведен.
    ("золотая лава", (232, 150, 40), False),
    ("бирюза", (40, 170, 175), False),
])
def test_flat_frames_are_judged_by_hue(rules, name, rgb, allowed):
    share = off_palette_share(_flat(rgb), rules)
    passed = share <= rules["off_share_max"]
    assert passed is allowed, f"{name}: доля постороннего цвета {share:.2f}"


def test_dark_frame_with_a_cold_highlight_passes(rules):
    """Капля на тёмном камне: холодный блик есть, цветового сдвига нет.

    Этот кадр и заставил добавить в мерку яркость. По одной насыщенности он
    набирал 0.42 — вровень с жёлтой лавой, которую отбраковать надо.
    """
    assert off_palette_share(_mostly_dark((30, 60, 70)), rules) <= rules["off_share_max"]


@pytest.mark.parametrize("share,tolerated", [(0.125, True), (0.30, False)])
def test_alien_spot_is_judged_by_how_much_of_the_frame_it_takes(rules, share, tolerated):
    """Восьмая часть кадра — ещё не сдвиг палитры, треть — уже сдвиг."""
    measured = off_palette_share(_mostly_dark((40, 200, 90), share), rules)
    assert (measured <= rules["off_share_max"]) is tolerated, f"доля {measured:.2f}"


# --- приговор по кадрам кандидата --------------------------------------------

def test_worst_frame_decides_not_the_average(rules, tmp_path):
    """Посторонний цвет на трети клипа зритель увидит, среднее его размажет."""
    good, bad = tmp_path / "a.png", tmp_path / "b.png"
    _flat((17, 18, 20)).save(good)
    _flat((137, 33, 70)).save(bad)

    assert palette_verdict([good, good], rules)["passed"]
    verdict = palette_verdict([good, good, bad], rules)
    assert not verdict["passed"]
    assert verdict["off_share"] == pytest.approx(1.0, abs=0.01)
    assert "палитра канала" in verdict["reason"]


def test_no_frames_is_not_a_rejection(rules, tmp_path):
    """Нечего мерить — нечего и предъявлять: кандидат судится по смыслу."""
    verdict = palette_verdict([tmp_path / "нет.png"], rules)
    assert verdict["passed"] and not verdict["measured"]


class TestPinkNeverPassesAgain:
    """Розовое поле — то, что заказчик назвал прямо, посмотрев 0047.

    Прежняя мерка его пропускала: коридор был симметричным, и его холодный
    край (343.5°) впускал пурпурно-розовое как «красное». Клип
    ``pexels_v15168370`` набирал 0.026 при пороге 0.15 и уехал в ролик.

    Кадры здесь собираются из чисел, а не берутся из репозитория: клипы,
    на которых мерка калибровалась, из базы удалены — держать в git 58 МБ
    брака ради теста незачем.
    """

    def _field(self, rgb, share=1.0):
        """Кадр, залитый цветом на заданную долю; остальное — почти чёрное."""
        a = np.full((568, 320, 3), 14, dtype=np.uint8)
        a[: int(568 * share)] = rgb
        return Image.fromarray(a)

    def test_a_pink_haze_is_rejected(self, rules):
        """Тон 330–347°, насыщенность 0.25–0.40 — та самая дымка."""
        for rgb in ((214, 150, 178), (198, 120, 155), (232, 168, 196)):
            verdict = palette_verdict([self._field(rgb, 0.5)], rules)
            assert not verdict["passed"], f"{rgb}: розовая дымка прошла"

    def test_the_brand_red_still_passes_at_any_size(self, rules):
        for rgb in ((200, 69, 61), (142, 47, 42), (228, 114, 106)):
            assert palette_verdict([self._field(rgb)], rules)["passed"], rgb

    def test_earth_passes_but_gold_does_not(self, rules):
        """Оба стоят на 30–45°, и разводит их насыщенность, а не оттенок.

        Песок карьера и порода — 0.46–0.58, жёлто-оранжевая лава — 0.83.
        Без этой границы пришлось бы выбирать между двумя ошибками: либо
        снятый материал уходит в брак вместе с золотом, либо наоборот.
        """
        sand = (186, 150, 104)          # тон ~38°, насыщенность 0.44
        gold = (232, 150, 40)           # тон ~34°, насыщенность 0.83
        assert palette_verdict([self._field(sand, 0.6)], rules)["passed"], "земля в браке"
        assert not palette_verdict([self._field(gold, 0.6)], rules)["passed"], "золото прошло"

    def test_one_hue_and_five_hues_of_the_same_size_end_differently(self, rules):
        """Розовое поле и живая сцена различаются не количеством цвета.

        Мерка по сумме этого не различала: рабочий стол с деревом, кожей и
        зелёными клавишами набирал 0.217 — больше, чем фиолетовые чернила.
        Здесь оба кадра несут поровну постороннего цвета, 14 % площади, и
        оба укладываются в общий предел 15 %. Расходятся они на том, как
        этот цвет разложен: пять тонов по 2.8 % — живая съёмка, один
        пурпурный на все 14 % — заливка, которой в палитре канала нет.
        """
        def bands(colors):
            a = np.full((568, 320, 3), 20, dtype=np.uint8)
            height = int(568 * 0.14 / len(colors))
            for i, rgb in enumerate(colors):
                a[i * height:(i + 1) * height] = rgb
            return Image.fromarray(a)

        alive = bands([(150, 120, 90), (60, 140, 130), (120, 110, 160),
                       (90, 150, 90), (170, 130, 110)])
        pink = bands([(214, 150, 178)])
        assert palette_verdict([alive], rules)["passed"], \
            palette_verdict([alive], rules)["reason"]
        assert not palette_verdict([pink], rules)["passed"], "розовая заливка прошла"

    def test_the_verdict_names_the_offending_hue(self, rules):
        """Отчёт обязан говорить, какой именно тон забраковал кадр."""
        verdict = palette_verdict([self._field((214, 150, 178), 0.5)], rules)
        assert 300 <= verdict["dominant_off_hue"] <= 345, verdict
        assert "°" in verdict["reason"] and "розов" in verdict["reason"]
