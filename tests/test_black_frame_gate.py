"""Почти чёрный футаж попадает в журнал, но не отменяется судьёй.

Покадровый осмотр прогона 179 показал: под числами b4 (24.8–29.4 с) идут три
клипа подряд со средней яркостью 1.7–6.3 из 255 — зритель видит субтитр на
пустоте, при том что в заявке блока стоит «Not flat black». Замер темноты в
P8 при этом существовал, но включался только для перебивок.

Отказом это не делается намеренно. Замер всей библиотеки 0050: девять клипов
дают меньше 6 % видимого кадра, а весь яркий материал (vortex 88 %,
redsmoke 63 %, darkember 52 %) лежит в ``deny`` — тёмная палитра выбрана
заявкой. Гейт вычистил бы шесть занятых слотов и отдал бы их лестнице §7.2.
Поэтому: считаем и пишем в журнал, решение за заказчиком.
"""
import logging

from src.p8_broll_judge.judge import _dark_reject_reason, _warn_if_black


class _Catcher(logging.Handler):
    """Логгер проекта не всплывает в caplog — слушаем его напрямую."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _captured(fn):
    # _log в шаге — адаптер поверх logging.Logger; слушаем сам логгер.
    logger = logging.getLogger("redshift.p8")
    handler = _Catcher()
    logger.addHandler(handler)
    try:
        fn()
    finally:
        logger.removeHandler(handler)
    return "\n".join(handler.lines)

BLACK = {"measured": True, "visible_share": 0.008, "mean": 0.004}
DIM = {"measured": True, "visible_share": 0.14, "mean": 0.11}
BRIGHT = {"measured": True, "visible_share": 0.55, "mean": 0.38}

VISIBLE_MIN, BLACK_MAX = 0.20, 0.06


def _reason(light, role):
    return _dark_reject_reason(light, {"asset_role": role},
                               visible_min=VISIBLE_MIN, black_max=BLACK_MAX)


def test_a_dim_clip_is_still_refused_on_an_interstitial():
    assert _reason(DIM, "interstitial")


def test_a_black_clip_is_not_refused_on_a_plain_broll_slot():
    # Тёмная палитра — решение заявки, а не брак судьи.
    assert _reason(BLACK, "broll") == ""


def test_a_normal_clip_passes_everywhere():
    for role in ("broll", "interstitial", "evidence", "meme"):
        assert _reason(BRIGHT, role) == "", role


def test_an_unmeasured_clip_is_not_refused():
    assert _reason(None, "broll") == ""


def test_a_black_clip_is_named_in_the_log():
    out = _captured(lambda: _warn_if_black(
        BLACK, {"asset_id": "magnific_0050_steelglow"},
        {"index": 9, "block_id": "b4"}, black_max=BLACK_MAX))
    assert "почти чёрный" in out


def test_a_normal_clip_stays_out_of_the_log():
    out = _captured(lambda: _warn_if_black(
        BRIGHT, {"asset_id": "magnific_0050_wing"},
        {"index": 3, "block_id": "b5c"}, black_max=BLACK_MAX))
    assert out == ""


def test_an_unmeasured_clip_stays_out_of_the_log():
    out = _captured(lambda: _warn_if_black(
        None, {"asset_id": "x"}, {"index": 1}, black_max=BLACK_MAX))
    assert out == ""
