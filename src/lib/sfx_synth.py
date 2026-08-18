"""Синтез брендовых SFX и музыкальных подложек (§14.1, §14.2).

Библиотеки капнутые и конечные: 20 звуков и 5 подложек на всю жизнь канала.
Синтез собственными средствами даёт три вещи, которых не даёт сток:

* нулевой риск Content ID — звук не существовал до этого прогона;
* полная лицензионная чистота (материал принадлежит каналу);
* узнаваемость: одни и те же звуки во всех роликах — это не бедность, а
  фирменный почерк (прямая формулировка §14).

Все звуки — WAV 48 kHz, нормализованные, ≤2 сек, как требует §14.1.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

SR = 48000


# --- примитивы синтеза --------------------------------------------------------

def _t(duration: float, sr: int = SR) -> np.ndarray:
    return np.arange(int(duration * sr), dtype=np.float64) / sr


def _noise(duration: float, rng: np.random.Generator, sr: int = SR) -> np.ndarray:
    return rng.normal(0.0, 1.0, int(duration * sr))


def _lowpass(x: np.ndarray, cutoff_hz: float, sr: int = SR) -> np.ndarray:
    """Однополюсный ФНЧ — дёшево и достаточно для формирования тембра."""
    alpha = math.exp(-2.0 * math.pi * max(cutoff_hz, 1.0) / sr)
    out = np.empty_like(x)
    state = 0.0
    for i, sample in enumerate(x):
        state = (1 - alpha) * sample + alpha * state
        out[i] = state
    return out


def _highpass(x: np.ndarray, cutoff_hz: float, sr: int = SR) -> np.ndarray:
    return x - _lowpass(x, cutoff_hz, sr)


def _sweep_lowpass(x: np.ndarray, f_from: float, f_to: float, sr: int = SR) -> np.ndarray:
    """ФНЧ с плавно едущей частотой среза — сердце whoosh и riser."""
    n = len(x)
    cutoffs = np.linspace(f_from, f_to, n)
    out = np.empty_like(x)
    state = 0.0
    for i in range(n):
        alpha = math.exp(-2.0 * math.pi * max(cutoffs[i], 1.0) / sr)
        state = (1 - alpha) * x[i] + alpha * state
        out[i] = state
    return out


def _env(n: int, attack: float, decay: float, *, curve: float = 2.0) -> np.ndarray:
    a = max(1, int(n * attack))
    d = max(1, n - a)
    return np.concatenate([
        np.linspace(0.0, 1.0, a) ** (1 / curve),
        np.linspace(1.0, 0.0, d) ** curve,
    ])[:n]


def _normalize(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.max(np.abs(x))) or 1.0
    return (x / m * peak).astype(np.float32)


def _stereo(x: np.ndarray, width: float = 0.0) -> np.ndarray:
    """Мягкое расширение стерео сдвигом фазы одного канала."""
    if width <= 0:
        return np.stack([x, x], axis=1).astype(np.float32)
    shift = max(1, int(width * 120))
    right = np.concatenate([np.zeros(shift), x[:-shift]]) if shift < len(x) else x
    return np.stack([x, right], axis=1).astype(np.float32)


# --- 20 ролей SFX (§14.1) -----------------------------------------------------

def _whoosh(rng, *, reverse: bool = False) -> np.ndarray:
    dur = 0.55
    noise = _noise(dur, rng)
    swept = _sweep_lowpass(noise, 600, 7000) if not reverse else _sweep_lowpass(noise, 7000, 500)
    env = _env(len(swept), 0.42 if not reverse else 0.12, 0.58, curve=2.4)
    return _stereo(_normalize(swept * env), width=0.5)


def _hit_impact(rng) -> np.ndarray:
    dur = 0.5
    t = _t(dur)
    body = np.sin(2 * np.pi * 70 * t * np.exp(-2.5 * t))
    click = _highpass(_noise(dur, rng), 2500) * np.exp(-45 * t)
    mix = body * 0.9 + click * 0.35
    return _stereo(_normalize(mix * _env(len(mix), 0.005, 0.995, curve=3.0)))


def _sub_drop(rng) -> np.ndarray:
    dur = 1.1
    t = _t(dur)
    freq = 90 * np.exp(-2.2 * t) + 28
    phase = 2 * np.pi * np.cumsum(freq) / SR
    tone = np.sin(phase)
    return _stereo(_normalize(tone * _env(len(tone), 0.01, 0.99, curve=2.2)))


def _riser(rng) -> np.ndarray:
    dur = 1.6
    t = _t(dur)
    noise = _sweep_lowpass(_noise(dur, rng), 400, 9000)
    tone = np.sin(2 * np.pi * (220 + 380 * (t / dur) ** 2) * t)
    mix = noise * 0.7 + tone * 0.3
    env = (t / dur) ** 1.7
    return _stereo(_normalize(mix * env), width=0.6)


def _pop(rng) -> np.ndarray:
    dur = 0.14
    t = _t(dur)
    tone = np.sin(2 * np.pi * (900 - 500 * t / dur) * t)
    return _stereo(_normalize(tone * _env(len(tone), 0.02, 0.98, curve=3.5)))


def _ui_click(rng) -> np.ndarray:
    dur = 0.07
    click = _highpass(_noise(dur, rng), 2000)
    return _stereo(_normalize(click * _env(len(click), 0.01, 0.99, curve=4.0)) * 0.8)


def _type_key(rng) -> np.ndarray:
    dur = 0.05
    click = _highpass(_noise(dur, rng), 3500)
    return _stereo(_normalize(click * _env(len(click), 0.008, 0.99, curve=5.0)) * 0.7)


def _swipe(rng) -> np.ndarray:
    dur = 0.28
    noise = _sweep_lowpass(_noise(dur, rng), 1800, 5200)
    return _stereo(_normalize(noise * _env(len(noise), 0.25, 0.75, curve=2.0)) * 0.85,
                   width=0.4)


def _glitch(rng) -> np.ndarray:
    dur = 0.32
    n = int(dur * SR)
    out = np.zeros(n)
    pos = 0
    while pos < n:
        seg = rng.integers(400, 2600)
        if rng.random() < 0.55:
            block = _highpass(rng.normal(0, 1, int(seg)), 1200)
        else:
            freq = float(rng.integers(180, 2400))
            block = np.sin(2 * np.pi * freq * np.arange(int(seg)) / SR)
        end = min(n, pos + int(seg))
        out[pos:end] = block[:end - pos]
        pos = end
    return _stereo(_normalize(out * _env(n, 0.02, 0.98, curve=1.4)) * 0.85)


def _reveal(rng) -> np.ndarray:
    dur = 0.7
    t = _t(dur)
    shimmer = sum(np.sin(2 * np.pi * f * t) for f in (880, 1320, 1760)) / 3
    noise = _sweep_lowpass(_noise(dur, rng), 2000, 8000) * 0.3
    env = _env(len(t), 0.06, 0.94, curve=2.2)
    return _stereo(_normalize((shimmer * 0.7 + noise) * env), width=0.5)


def _chime(rng) -> np.ndarray:
    dur = 1.0
    t = _t(dur)
    tone = (np.sin(2 * np.pi * 1046 * t) * np.exp(-4 * t)
            + np.sin(2 * np.pi * 1568 * t) * np.exp(-5 * t) * 0.6)
    return _stereo(_normalize(tone), width=0.35)


def _notification(rng) -> np.ndarray:
    dur = 0.5
    t = _t(dur)
    first = np.sin(2 * np.pi * 880 * t) * np.exp(-9 * t)
    second = np.roll(np.sin(2 * np.pi * 1174 * t) * np.exp(-9 * t), int(0.11 * SR))
    return _stereo(_normalize(first + second * 0.9))


def _camera_shutter(rng) -> np.ndarray:
    dur = 0.22
    t = _t(dur)
    first = _highpass(_noise(dur, rng), 1500) * np.exp(-60 * t)
    second = np.roll(first, int(0.07 * SR)) * 0.8
    return _stereo(_normalize(first + second))


def _data_beep(rng) -> np.ndarray:
    dur = 0.24
    t = _t(dur)
    tone = np.sign(np.sin(2 * np.pi * 1400 * t)) * 0.35 + np.sin(2 * np.pi * 2100 * t) * 0.65
    return _stereo(_normalize(tone * _env(len(t), 0.05, 0.95, curve=2.5)) * 0.8)


def _tick(rng) -> np.ndarray:
    dur = 0.06
    t = _t(dur)
    tone = np.sin(2 * np.pi * 2400 * t) * np.exp(-60 * t)
    return _stereo(_normalize(tone) * 0.7)


def _boom(rng) -> np.ndarray:
    dur = 1.5
    t = _t(dur)
    freq = 55 * np.exp(-1.4 * t) + 24
    phase = 2 * np.pi * np.cumsum(freq) / SR
    body = np.sin(phase)
    crack = _highpass(_noise(dur, rng), 1800) * np.exp(-30 * t) * 0.4
    return _stereo(_normalize((body + crack) * _env(len(t), 0.004, 0.996, curve=2.0)))


def _error_buzz(rng) -> np.ndarray:
    dur = 0.42
    t = _t(dur)
    tone = np.sign(np.sin(2 * np.pi * 130 * t)) * np.sin(2 * np.pi * 62 * t)
    return _stereo(_normalize(tone * _env(len(t), 0.02, 0.98, curve=1.6)) * 0.85)


def _meme_stinger(rng) -> np.ndarray:
    dur = 0.65
    t = _t(dur)
    freq = 300 + 700 * (t / dur)
    tone = np.sin(2 * np.pi * np.cumsum(freq) / SR)
    pops = np.zeros_like(t)
    for offset in (0.0, 0.16, 0.32):
        idx = int(offset * SR)
        pops[idx:idx + 1200] += np.sin(
            2 * np.pi * 1200 * np.arange(min(1200, len(t) - idx)) / SR)[:max(0, min(1200, len(t) - idx))]
    return _stereo(_normalize((tone * 0.6 + pops * 0.5) * _env(len(t), 0.05, 0.95)))


def _subscribe_ping(rng) -> np.ndarray:
    dur = 0.85
    t = _t(dur)
    notes = (1046.5, 1318.5, 1568.0)
    tone = np.zeros_like(t)
    for i, freq in enumerate(notes):
        start = int(i * 0.09 * SR)
        seg = np.sin(2 * np.pi * freq * t) * np.exp(-6 * t)
        tone += np.roll(seg, start) * (1.0 - i * 0.18)
    return _stereo(_normalize(tone), width=0.4)


SFX_RECIPES: dict[str, tuple[Callable, str]] = {
    "whoosh_in": (lambda rng: _whoosh(rng, reverse=False), "вход аватара, влёт элемента"),
    "whoosh_out": (lambda rng: _whoosh(rng, reverse=True), "выход аватара, уход элемента"),
    "hit_impact": (_hit_impact, "акцент на цифре/факте"),
    "sub_drop": (_sub_drop, "тяжёлый акцент на повороте"),
    "riser": (_riser, "нарастание перед раскрытием"),
    "pop": (_pop, "появление плашки"),
    "ui_click": (_ui_click, "клик в интерфейсе"),
    "type_key": (_type_key, "печать текста"),
    "swipe": (_swipe, "смена кадра, свайп"),
    "glitch": (_glitch, "глитч-переход"),
    "reveal": (_reveal, "появление full-screen text"),
    "chime": (_chime, "позитивный акцент"),
    "notification": (_notification, "уведомление, входящее сообщение"),
    "camera_shutter": (_camera_shutter, "скриншот, фиксация"),
    "data_beep": (_data_beep, "данные, график, цифры"),
    "tick": (_tick, "отсчёт, мелкий акцент"),
    "boom": (_boom, "финальный удар"),
    "error_buzz": (_error_buzz, "отрицание, «не работает»"),
    "meme_stinger": (_meme_stinger, "мем-вставка"),
    "subscribe_ping": (_subscribe_ping, "кнопка подписки"),
}

SFX_ROLES = tuple(SFX_RECIPES)
assert len(SFX_ROLES) == 20, "§14.1 требует ровно 20 ролей SFX"


def synth_sfx(role: str, *, seed: int = 0) -> np.ndarray:
    if role not in SFX_RECIPES:
        raise KeyError(f"нет рецепта для роли SFX {role!r}")
    rng = np.random.default_rng(abs(hash(role)) % (2 ** 32) + seed)
    return SFX_RECIPES[role][0](rng)


def sfx_description(role: str) -> str:
    return SFX_RECIPES[role][1]


# --- 5 музыкальных подложек (§14.2) -------------------------------------------

MUSIC_MOODS: dict[str, dict] = {
    "cosmic_calm": {"root": 55.0, "chord": (1.0, 1.5, 2.0, 3.0), "lfo": 0.06,
                    "noise": 0.10, "pulse": 0.0,
                    "title": "космос, медленный дрейф"},
    "tech_tension": {"root": 65.4, "chord": (1.0, 1.19, 1.5, 2.0), "lfo": 0.11,
                     "noise": 0.07, "pulse": 0.9,
                     "title": "техно-напряжение, скрытый пульс"},
    "neutral_drive": {"root": 73.4, "chord": (1.0, 1.33, 2.0, 2.66), "lfo": 0.09,
                      "noise": 0.05, "pulse": 1.2,
                      "title": "ровное движение вперёд"},
    "discovery_warm": {"root": 61.7, "chord": (1.0, 1.25, 1.5, 2.5), "lfo": 0.05,
                       "noise": 0.06, "pulse": 0.0,
                       "title": "тёплое открытие"},
    "dark_pulse": {"root": 49.0, "chord": (1.0, 1.19, 1.78, 2.0), "lfo": 0.13,
                   "noise": 0.09, "pulse": 0.75,
                   "title": "тёмный пульс"},
}


def synth_music(mood: str, *, duration_sec: float = 75.0, seed: int = 0) -> np.ndarray:
    """Зацикливаемая подложка без вокала и без выраженной мелодии (§14.2).

    Мелодии нет намеренно: §4.4 требует, чтобы подложка была «на грани
    слышимости» и не воспринималась как музыка при обычном прослушивании.
    """
    spec = MUSIC_MOODS.get(mood) or MUSIC_MOODS["neutral_drive"]
    rng = np.random.default_rng(abs(hash(mood)) % (2 ** 32) + seed)
    t = _t(duration_sec)
    n = len(t)

    # Дрон: аккорд из чистых интервалов с медленными биениями.
    pad = np.zeros(n)
    for i, ratio in enumerate(spec["chord"]):
        freq = spec["root"] * ratio
        detune = 1.0 + (i - 1.5) * 0.0015
        lfo = 1.0 + 0.12 * np.sin(2 * np.pi * spec["lfo"] * t + i)
        pad += np.sin(2 * np.pi * freq * detune * t) * lfo / (i + 1.6)

    # Воздух: отфильтрованный шум, заполняющий тишину.
    air = _lowpass(rng.normal(0, 1, n), 900) * spec["noise"]

    # Пульс: очень тихий, задаёт ощущение движения, но не ритм.
    pulse = np.zeros(n)
    if spec["pulse"] > 0:
        period = SR * 60.0 / (spec["pulse"] * 60.0)
        phase = (np.arange(n) % period) / period
        pulse = np.exp(-8 * phase) * np.sin(2 * np.pi * spec["root"] * t) * 0.35

    signal = pad / max(len(spec["chord"]), 1) + air + pulse
    signal = _lowpass(signal, 2600)

    # Бесшовный цикл: кроссфейд хвоста в голову.
    fade = int(2.0 * SR)
    if n > fade * 2:
        ramp = np.linspace(0.0, 1.0, fade)
        signal[:fade] = signal[:fade] * ramp + signal[-fade:] * (1 - ramp)
        signal = signal[:-fade]

    return _stereo(_normalize(signal, peak=0.75), width=0.8)
