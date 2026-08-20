"""True Peak: между отсчётами сигнал выше, чем в них самих.

QC-8 требует потолка −1 dBTP и меряет его ffmpeg loudnorm по готовому файлу.
Наш лимитер меряет своей оценкой, и пока она была линейной интерполяцией,
эти два измерения расходились: лимитер считал, что вывел микс ровно на −1.0,
loudnorm показывал −0.77, и обе версии ролика уходили в rejected.
"""

from __future__ import annotations

import math

import numpy as np

from src.lib.audio import limit_true_peak, true_peak_dbtp


def _intersample_signal(sr: int = 48000, seconds: float = 0.5) -> np.ndarray:
    """Синус на четверти частоты дискретизации, сдвинутый на π/4.

    Отсчёты садятся ровно на ±cos(π/4) ≈ ±0.707, то есть пик по отсчётам равен
    −3.01 dB. Настоящий сигнал между ними доходит до 1.0 — ровно 0 dBTP. Точный
    ответ известен заранее, поэтому оценку можно проверять, а не сравнивать
    саму с собой.
    """
    n = int(sr * seconds)
    t = np.arange(n) / sr
    return np.cos(2 * np.pi * (sr / 4) * t + np.pi / 4).astype(np.float32)


def test_intersample_peak_is_seen():
    signal = _intersample_signal()
    sample_peak_db = 20 * math.log10(float(np.max(np.abs(signal))))
    assert abs(sample_peak_db - (-3.01)) < 0.05, "проверочный сигнал построен неверно"

    measured = true_peak_dbtp(signal)
    assert abs(measured - 0.0) < 0.15, (
        f"межотсчётный пик не увиден: {measured:.2f} dBTP вместо 0.0. "
        "Линейная интерполяция именно так и ошибалась — на все три децибела")


def test_limiter_leaves_headroom_under_the_ceiling():
    """Упереться ровно в потолок значит отдать исход расхождению измерений."""
    loud = (_intersample_signal() * 1.2).astype(np.float32)
    limited = limit_true_peak(loud, max_dbtp=-1.0)

    after = true_peak_dbtp(limited)
    assert after <= -1.0, f"потолок пробит: {after:.2f} dBTP"
    assert after <= -1.2, (
        f"запаса нет: {after:.2f} dBTP вплотную к границе — "
        "любое расхождение с ffmpeg снова провалит QC-8")


def test_quiet_signal_is_left_alone():
    quiet = (_intersample_signal() * 0.05).astype(np.float32)
    assert np.allclose(limit_true_peak(quiet, max_dbtp=-1.0), quiet), \
        "тихий микс трогать незачем"
