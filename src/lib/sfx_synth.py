"""Синтез брендовых SFX и музыкальных подложек (§14.1, §14.2).

Библиотеки капнутые и конечные: 20 звуков и 15 подложек на всю жизнь канала.
Синтез собственными средствами даёт три вещи, которых не даёт сток:

* нулевой риск Content ID — звук не существовал до этого прогона;
* полная лицензионная чистота (материал принадлежит каналу);
* узнаваемость: одни и те же звуки во всех роликах — это не бедность, а
  фирменный почерк (прямая формулировка §14).

Все звуки — WAV 48 kHz, нормализованные, ≤2 сек, как требует §14.1.
"""

from __future__ import annotations

import hashlib
import inspect
import math
import zlib
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


def _decay(n: int, rate: float, sr: int = SR) -> np.ndarray:
    """Экспоненциальный спад. ``rate`` — во сколько e раз за секунду."""
    return np.exp(-rate * np.arange(n, dtype=np.float64) / sr)


def _transient(duration: float, rng, *, hp: float = 3000.0,
               rate: float = 120.0) -> np.ndarray:
    """Широкополосный щелчок атаки — то, из чего слышна «дорогая» подача."""
    n = int(duration * SR)
    return _highpass(_noise(duration, rng), hp)[:n] * _decay(n, rate)


def _air(duration: float, rng, *, hp: float = 7000.0,
         rate: float = 22.0) -> np.ndarray:
    """Высокий хвост. Без него удар звучит глухо, будто отрезан фильтром."""
    n = int(duration * SR)
    return _highpass(_noise(duration, rng), hp)[:n] * _decay(n, rate)


def _drive(x: np.ndarray, amount: float = 1.8) -> np.ndarray:
    """Мягкое насыщение: даёт гармоники, которыми низ слышен на телефоне."""
    return np.tanh(x * amount) / np.tanh(amount)


# Динамик телефона ниже этой частоты почти ничего не отдаёт. Слой ниже неё
# ощущается на хорошей акустике и пропадает на телефоне — значит, нести смысл
# он не может, и громким его делать нельзя.
PHONE_FLOOR_HZ = 350.0


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
    """Удар в четыре слоя: щелчок, тело, саб и воздух.

    Был одним синусом на 70 Гц с тихим щелчком поверх. На телефоне 70 Гц не
    воспроизводится вовсе — от удара оставался только слабый шорох, и он читался
    как дешёвый. Смысл теперь несёт тело в 180–270 Гц с гармониками от
    насыщения: это полоса, которую динамик телефона отдаёт. Саб оставлен, но
    тихим — он для хорошей акустики, а не для смысла.
    """
    dur = 0.55
    n = int(dur * SR)
    t = _t(dur)
    # Средний слой стоит выше PHONE_FLOOR_HZ намеренно: он и есть удар на
    # телефоне. Нижний и саб оставлены для нормальной акустики.
    mid = _drive(np.sin(2 * np.pi * 430 * t) + 0.7 * np.sin(2 * np.pi * 660 * t),
                 2.0) * _decay(n, 20.0)
    low = _drive(np.sin(2 * np.pi * 160 * t), 2.2) * _decay(n, 14.0)
    sub = np.sin(2 * np.pi * 58 * t) * _decay(n, 14.0)
    mix = (_transient(dur, rng, hp=2800, rate=150.0) * 0.70
           + mid * 1.2 + low * 0.45 + sub * 0.16 + _air(dur, rng) * 0.14)
    return _stereo(_normalize(mix * _env(n, 0.004, 0.996, curve=2.6)))


def _sub_drop(rng) -> np.ndarray:
    """Падение вниз. Слышно его по гармоникам, а не по основному тону.

    Чистый скользящий синус с 90 до 28 Гц на телефоне беззвучен. Насыщение
    даёт ему ряд гармоник — падение слышно как движение тембра вниз даже там,
    где самой основы нет.
    """
    dur = 1.1
    n = int(dur * SR)
    t = _t(dur)
    freq = 110 * np.exp(-2.2 * t) + 34
    tone = _drive(np.sin(2 * np.pi * np.cumsum(freq) / SR), 2.6)
    # Тот же спуск октавой выше — он остаётся в полосе телефона и ведёт
    # движение там, где основы уже не слышно.
    upper = _drive(np.sin(2 * np.pi * np.cumsum(freq * 4.0) / SR), 1.8) * _decay(n, 3.4)
    mix = (_transient(dur, rng, hp=2200, rate=90.0) * 0.45
           + tone * 0.60 + upper * 0.55 + _air(dur, rng, rate=14.0) * 0.10)
    return _stereo(_normalize(mix * _env(n, 0.008, 0.992, curve=2.2)), width=0.25)


def _riser(rng) -> np.ndarray:
    dur = 1.6
    t = _t(dur)
    noise = _sweep_lowpass(_noise(dur, rng), 400, 9000)
    tone = np.sin(2 * np.pi * (220 + 380 * (t / dur) ** 2) * t)
    mix = noise * 0.7 + tone * 0.3
    env = (t / dur) ** 1.7
    return _stereo(_normalize(mix * env), width=0.6)


def _pop(rng) -> np.ndarray:
    """Появление плашки. Не «поп», а мягкий удар с телом и воздухом.

    Было: голая падающая синусоида 900→400 Гц за 0.14 с. Заказчик услышал её
    как дешёвый звук — и он прав: одна синусоида без атаки и без тела звучит
    генератором, а не предметом, который лёг в кадр.

    Что делает звук «дорогим» — три слоя, а не громкость. Атака даёт материал
    (по ней ухо узнаёт, обо что ударили), низ даёт вес, воздух даёт воздух —
    ту же полосу выше 9 кГц, в которой теперь дышит и музыкальная подложка.
    """
    dur = 0.32
    n = int(dur * SR)
    t = _t(dur)

    # Атака: короткий яркий скол. Гаснет за десятки миллисекунд.
    attack = _highpass(_noise(dur, rng), 2600) * _decay(n, 90.0) * 0.55
    # Тело: главный вес. Свип держится в 460…210 Гц — там, где у телефона
    # ещё есть отдача. Первая версия шла 150→80 Гц, и мерка динамика показала
    # потерю 11.6 дБ: вес был, но слышал его только тот, кто в наушниках.
    body = np.sin(2 * np.pi * (460 - 250 * t / dur) * t) * _decay(n, 13.0) * 0.85
    # Подпор снизу: на хорошем динамике даёт объём, на телефоне пропадает —
    # и пропадать ему нечего, вес уже отдан телом.
    sub = np.sin(2 * np.pi * (150 - 70 * t / dur) * t) * _decay(n, 9.0) * 0.40
    # Призвук наверху: та же полоса, что у воздуха подложки.
    air = _highpass(_noise(dur, rng), 9000) * _decay(n, 26.0) * 0.22

    mix = (attack + body + sub + air) * _env(n, 0.004, 0.996, curve=2.0)
    return _stereo(_normalize(mix), width=0.35)


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
    n = int(dur * SR)
    t = _t(dur)
    # Аккорд, а не три равных тона: верхние тише и гаснут раньше — так слышен
    # предмет, а не генератор.
    shimmer = (np.sin(2 * np.pi * 880 * t) * _decay(n, 3.0)
               + np.sin(2 * np.pi * 1320 * t) * _decay(n, 4.5) * 0.55
               + np.sin(2 * np.pi * 1760 * t) * _decay(n, 6.5) * 0.3)
    noise = _sweep_lowpass(_noise(dur, rng), 2000, 8000)[:n] * 0.3
    env = _env(n, 0.06, 0.94, curve=2.2)
    mix = (shimmer * 0.7 + noise + _air(dur, rng, hp=10000, rate=5.0) * 0.10) * env
    return _stereo(_normalize(mix), width=0.5)


def _chime(rng) -> np.ndarray:
    """Колокольчик: удар язычка, тон с обертоном и воздух.

    Был двумя чистыми синусами. Синус без атаки и без воздуха слышен как
    сигнал будильника, а не как звук предмета: у настоящего колокольчика
    сначала щелчок касания, потом тон, поверх — шум затухающего металла.
    """
    dur = 1.0
    n = int(dur * SR)
    t = _t(dur)
    tone = (np.sin(2 * np.pi * 1046 * t) * _decay(n, 4.0)
            + np.sin(2 * np.pi * 1568 * t) * _decay(n, 5.0) * 0.6
            + np.sin(2 * np.pi * 3136 * t) * _decay(n, 9.0) * 0.22)
    mix = (_transient(dur, rng, hp=4000, rate=320.0) * 0.42
           + tone * 0.9 + _air(dur, rng, hp=9000, rate=6.0) * 0.08)
    return _stereo(_normalize(mix), width=0.35)


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
    """Финальный удар с телом и длинным воздушным хвостом."""
    dur = 1.5
    n = int(dur * SR)
    t = _t(dur)
    freq = 80 * np.exp(-1.4 * t) + 30
    low = _drive(np.sin(2 * np.pi * np.cumsum(freq) / SR), 2.4) * _decay(n, 2.4)
    body = _drive(np.sin(2 * np.pi * 210 * t), 1.9) * _decay(n, 9.0)
    mid = _drive(np.sin(2 * np.pi * 480 * t) + 0.6 * np.sin(2 * np.pi * 720 * t),
                 1.8) * _decay(n, 6.0)
    mix = (_transient(dur, rng, hp=2000, rate=70.0) * 0.50
           + low * 0.45 + body * 0.40 + mid * 0.95 + _air(dur, rng, rate=9.0) * 0.13)
    return _stereo(_normalize(mix * _env(n, 0.003, 0.997, curve=1.9)), width=0.3)


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
    n = int(dur * SR)
    t = _t(dur)
    notes = (1046.5, 1318.5, 1568.0)
    tone = np.zeros_like(t)
    for i, freq in enumerate(notes):
        start = int(i * 0.09 * SR)
        seg = (np.sin(2 * np.pi * freq * t) * _decay(n, 6.0)
               + np.sin(2 * np.pi * freq * 2 * t) * _decay(n, 11.0) * 0.18)
        tone += np.roll(seg, start) * (1.0 - i * 0.18)
    mix = (_transient(dur, rng, hp=4500, rate=380.0) * 0.55
           + tone * 0.9 + _air(dur, rng, hp=9000, rate=7.0) * 0.07)
    return _stereo(_normalize(mix), width=0.4)


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


def _seed(name: str, extra: int = 0) -> int:
    """Зерно, одинаковое во всех запусках.

    Здесь стоял встроенный ``hash(name)``, а он у строк рандомизируется от
    процесса к процессу (PYTHONHASHSEED). Шум в рецептах брался от этого зерна,
    и звук получался новый при каждом запуске: библиотека расходилась с кодом
    молча, а обещание пересобираемости ролика не выполнялось. Обнаружено
    сравнением записанных файлов с тем, что выдаёт синтез.
    """
    return (zlib.crc32(name.encode("utf-8")) + extra) % (2 ** 32)


def synth_sfx(role: str, *, seed: int = 0) -> np.ndarray:
    if role not in SFX_RECIPES:
        raise KeyError(f"нет рецепта для роли SFX {role!r}")
    return SFX_RECIPES[role][0](np.random.default_rng(_seed(role, seed)))


def sfx_description(role: str) -> str:
    return SFX_RECIPES[role][1]

# Синтез музыкальных подложек отсюда удалён. Пятнадцать сгенерированных бедов
# заказчик отверг словами «это ужас, я хотел хорошие сэмплы живых
# инструментов» — и он прав: аккорд с биениями и партия из синусоид с
# наклеенной атакой звучат синтезатором, а не инструментом. Никакая правка
# параметров этого не меняет: разница между сэмплом скрипки и математической
# моделью скрипки слышна сразу, и догонять её было бы работой без конца.
#
# Библиотека подложек теперь курируемая: живые записи кладутся руками через
# ``python -m src.cli add-music``. Словарь настроений и приём файлов живут в
# ``src.lib.music_library``.
