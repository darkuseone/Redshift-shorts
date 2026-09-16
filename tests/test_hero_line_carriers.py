"""Приём-носитель реплики либо показывает её целиком, либо не показывает.

0050 r61: `hero-type-slab` встал на аватар-плане 50.29–55.21 с репликой
«шаг. Но пункт без внешней силы Клей не принял. Миллион OpenAI», нарезанной
в шесть строк, показал первые четыре — «ШАГ. / НО ПУНКТ БЕЗ / ВНЕШНЕЙ СИЛЫ /
КЛЕЙ НЕ» — и погасил караоке на всём своём окне. Шесть секунд речи остались
без субтитра, а в кадре висело оборванное предложение.
"""
from src.lib.render.hyperframes.templates import (
    TEXT_COLUMN_MAX_LINES, TYPE_SLAB_MAX_LINES, hero_text_column,
    hero_type_slab)
from src.p11_assemble.assemble import hero_fits_lines


class _Ctx:
    def __init__(self, lines):
        self.params = {"lines": lines}
        self.index = 22
        self.start = 50.286
        self.duration = 4.921
        self.end = 55.207
        self.track = 13
        self.target = "ts-22"


def test_the_slab_refuses_a_line_it_would_have_to_cut():
    lines = ["ШАГ.", "НО ПУНКТ БЕЗ", "ВНЕШНЕЙ СИЛЫ", "КЛЕЙ НЕ", "ПРИНЯЛ.",
             "МИЛЛИОН OPENAI"]
    assert len(lines) > TYPE_SLAB_MAX_LINES
    assert hero_type_slab(_Ctx(lines)).nodes == []


def test_the_slab_draws_every_line_it_accepts():
    lines = ["ШАГ.", "НО ПУНКТ БЕЗ", "ВНЕШНЕЙ СИЛЫ", "КЛЕЙ НЕ"]
    html = "".join(hero_type_slab(_Ctx(lines)).nodes)
    for line in lines:
        assert line in html
    assert html.count("ts-line") == len(lines)


def test_the_column_keeps_its_own_ceiling():
    assert hero_text_column(_Ctx(["A"] * (TEXT_COLUMN_MAX_LINES + 1))).nodes == []
    assert hero_text_column(_Ctx(["A"] * TEXT_COLUMN_MAX_LINES)).nodes != []


def test_p11_drops_the_device_instead_of_muting_the_karaoke():
    # Тот же предел на стороне сборки: приём, который не влезет, не выбирается,
    # иначе P11 погасит караоке под приёмом, которого в кадре не будет.
    over = {"lines": ["a"] * (TYPE_SLAB_MAX_LINES + 1)}
    fits = {"lines": ["a"] * TYPE_SLAB_MAX_LINES}
    assert hero_fits_lines("hero-type-slab", over) is False
    assert hero_fits_lines("hero-type-slab", fits) is True
    # Приёмы без строк правило не касается.
    assert hero_fits_lines("hero-slam", over) is True


def test_the_slab_is_light_on_frame_not_ink_on_stage():
    # Плита лежит поверх шота, а кадры канала тёмные: цвет берётся от кадра,
    # а не от класса сцены. На 0050 сцена была `room` (светлая), кадр — чёрный,
    # и вся плита ушла в чернильный текст по чёрному.
    from src.lib.config import load_config
    from src.lib.render.hyperframes.templates import hero_css
    css = hero_css(load_config().brandbook)
    slab = css.split(".hero-type-slab .ts-line{")[1].split("}")[0]
    assert "color:var(--color-bg-light)" in slab
    assert "--color-on-stage" not in slab
