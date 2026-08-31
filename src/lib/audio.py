"""Аудио-движок: WAV I/O, громкость по ITU-R BS.1770-4, микс, ducking, паузы.

Требования §4.4 и QC 8/9 (§11.1) оперируют LUFS и True Peak, поэтому измерения
здесь настоящие, а не «на глазок»:

* ``measure_loudness_file`` — эталонное измерение через ebur128-фильтр ffmpeg
  (integrated LUFS, LRA, true peak);
* ``measure_lufs_array`` — независимая реализация K-взвешивания и гейтирования
  на numpy: используется в тестах и как перекрёстная проверка.

Канонический формат внутри пайплайна: WAV PCM 16 бит, 48 kHz.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from ..errors import RenderError
from .ffmpeg import ffmpeg_bin, run
from .logging import get_logger

_log = get_logger("audio")

SAMPLE_RATE = 48000
EPS = 1e-12


# --- WAV I/O -----------------------------------------------------------------

def load_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """WAV → (float32 [n, channels] в диапазоне [-1, 1], sample_rate)."""
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 3:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = (raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16))
        ints = np.where(ints & 0x800000, ints - (1 << 24), ints)
        data = ints.astype(np.float32) / 8388608.0
    else:  # pragma: no cover
        raise RenderError("неподдерживаемая разрядность WAV", width=width, path=str(path))
    if channels > 1:
        data = data.reshape(-1, channels)
    else:
        data = data.reshape(-1, 1)
    return data, sr


def save_wav(path: str | Path, data: np.ndarray, sr: int = SAMPLE_RATE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, None]
    clipped = np.clip(arr, -1.0, 1.0)
    ints = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(arr.shape[1])
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(ints.tobytes())
    return path


def to_canonical_wav(src: str | Path, dst: str | Path, *, sr: int = SAMPLE_RATE,
                     channels: int = 1) -> Path:
    """Любой аудиофайл → WAV PCM16 нужной частоты/каналов (через ffmpeg)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(["-y", "-i", str(src), "-vn", "-acodec", "pcm_s16le",
         "-ar", str(sr), "-ac", str(channels), str(dst)], what="to_canonical_wav")
    return dst


def load_audio_any(path: str | Path, sr: int = SAMPLE_RATE) -> tuple[np.ndarray, int]:
    """Загрузить аудио любого формата.

    Капнутые библиотеки хранятся в git (§14.5), поэтому музыкальные подложки
    лежат в сжатом виде: 5 минутных WAV — это 67 МБ в репозитории, а на уровне
    −32 LUFS под речью разница между WAV и AAC неразличима. SFX остаются WAV,
    как требует §14.1.
    """
    path = Path(path)
    if path.suffix.lower() == ".wav":
        return load_wav(path)
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        to_canonical_wav(path, tmp_path, sr=sr, channels=2)
        return load_wav(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def duration_sec(data: np.ndarray, sr: int = SAMPLE_RATE) -> float:
    return float(len(data)) / float(sr)


def to_mono(data: np.ndarray) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float32)
    return arr[:, 0] if arr.ndim == 2 and arr.shape[1] == 1 else (
        arr.mean(axis=1) if arr.ndim == 2 else arr)


def to_stereo(data: np.ndarray) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.shape[1] == 1:
        return np.repeat(arr, 2, axis=1)
    return arr[:, :2]


def resample(data: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """Линейная передискретизация (для коротких SFX; файлы гонятся через ffmpeg)."""
    if sr_from == sr_to:
        return data
    arr = np.asarray(data, dtype=np.float32)
    single = arr.ndim == 1
    if single:
        arr = arr[:, None]
    n_out = int(round(arr.shape[0] * sr_to / sr_from))
    x_old = np.arange(arr.shape[0], dtype=np.float64)
    x_new = np.linspace(0.0, arr.shape[0] - 1, n_out, dtype=np.float64)
    out = np.stack([np.interp(x_new, x_old, arr[:, c]) for c in range(arr.shape[1])], axis=1)
    out = out.astype(np.float32)
    return out[:, 0] if single else out


# --- Громкость ---------------------------------------------------------------

def _k_weighting_coeffs(sr: int) -> tuple[tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    """Коэффициенты двух биквадов K-взвешивания BS.1770-4 для произвольной sr."""
    # Стадия 1: high-shelf +4 dB @ ~1681 Hz
    f0 = 1681.974450955533
    G = 3.999843853973347
    Q = 0.7071752369554196
    K = math.tan(math.pi * f0 / sr)
    Vh = 10.0 ** (G / 20.0)
    Vb = Vh ** 0.4996667741545416
    a0 = 1.0 + K / Q + K * K
    b1 = np.array([
        (Vh + Vb * K / Q + K * K) / a0,
        2.0 * (K * K - Vh) / a0,
        (Vh - Vb * K / Q + K * K) / a0,
    ])
    a1 = np.array([1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0])

    # Стадия 2: RLB high-pass @ ~38 Hz
    f0 = 38.13547087602444
    Q = 0.5003270373238773
    K = math.tan(math.pi * f0 / sr)
    b2 = np.array([1.0, -2.0, 1.0])
    denom = 1.0 + K / Q + K * K
    a2 = np.array([1.0, 2.0 * (K * K - 1.0) / denom, (1.0 - K / Q + K * K) / denom])
    return (b1, a1), (b2, a2)


def _biquad(x: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
    """Прямая форма II (транспонированная). Достаточна для измерений в тестах."""
    y = np.empty_like(x, dtype=np.float64)
    z1 = z2 = 0.0
    b0, b1_, b2_ = float(b[0]), float(b[1]), float(b[2])
    a1_, a2_ = float(a[1]), float(a[2])
    for i, xn in enumerate(x):
        yn = b0 * xn + z1
        z1 = b1_ * xn - a1_ * yn + z2
        z2 = b2_ * xn - a2_ * yn
        y[i] = yn
    return y


def measure_lufs_array(data: np.ndarray, sr: int = SAMPLE_RATE) -> float:
    """Integrated LUFS по BS.1770-4 (K-взвешивание + двойное гейтирование)."""
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.shape[0] < int(0.4 * sr):
        return -math.inf
    (b1, a1), (b2, a2) = _k_weighting_coeffs(sr)
    weights = [1.0, 1.0, 1.0, 1.41, 1.41]  # L, R, C, Ls, Rs

    block = int(0.4 * sr)
    step = int(0.1 * sr)  # перекрытие 75 %
    n_blocks = 1 + (arr.shape[0] - block) // step
    powers = np.zeros(n_blocks, dtype=np.float64)
    for ch in range(arr.shape[1]):
        filtered = _biquad(_biquad(arr[:, ch], b1, a1), b2, a2)
        sq = filtered ** 2
        cum = np.concatenate(([0.0], np.cumsum(sq)))
        idx = np.arange(n_blocks) * step
        mean_sq = (cum[idx + block] - cum[idx]) / block
        powers += weights[min(ch, len(weights) - 1)] * mean_sq

    with np.errstate(divide="ignore"):
        loud = -0.691 + 10.0 * np.log10(powers + EPS)
    keep = loud > -70.0                      # абсолютный гейт
    if not keep.any():
        return -math.inf
    rel = -0.691 + 10.0 * math.log10(powers[keep].mean() + EPS) - 10.0
    keep = keep & (loud > rel)               # относительный гейт −10 LU
    if not keep.any():
        return -math.inf
    return float(-0.691 + 10.0 * math.log10(powers[keep].mean() + EPS))


def _oversample_bandlimited(channel: np.ndarray, factor: int) -> np.ndarray:
    """Полосно-ограниченное восстановление сигнала между отсчётами.

    Линейная интерполяция для этого не годится: хорда между соседними отсчётами
    всегда проходит ниже настоящей огибающей, и оценка пика выходит заниженной.
    Классический пример — синус на четверти частоты дискретизации со сдвигом
    фазы: отсчёты стоят на ±0.707, а сигнал между ними доходит до 1.0.

    Ценой этой ошибки был проваленный QC-8: лимитер по своей оценке считал, что
    уложился ровно в −1 dBTP, а ffmpeg loudnorm мерил −0.77 и ролик не выдавался.
    Дополнение спектра нулями — то самое восстановление фильтром, которого
    требует BS.1770.
    """
    n = channel.shape[0]
    spec = np.fft.rfft(channel)
    padded = np.zeros(n * factor // 2 + 1, dtype=np.complex128)
    padded[:spec.shape[0]] = spec
    return np.fft.irfft(padded, n * factor) * factor


def true_peak_dbtp(data: np.ndarray, oversample: int = 4) -> float:
    """Оценка True Peak: передискретизация с фильтром, как требует BS.1770."""
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.shape[0] < 2:
        return -math.inf
    peak = 0.0
    for ch in range(arr.shape[1]):
        up = _oversample_bandlimited(arr[:, ch], oversample)
        peak = max(peak, float(np.max(np.abs(up))))
    return 20.0 * math.log10(peak + EPS)


@dataclass
class LoudnessStats:
    integrated_lufs: float
    true_peak_dbtp: float
    lra: float = 0.0
    threshold: float = 0.0
    source: str = "ffmpeg"


def measure_loudness_file(path: str | Path) -> LoudnessStats:
    """Эталонное измерение файла через ffmpeg loudnorm (EBU R128)."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(path),
           "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
           "-f", "null", "-"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    text = proc.stderr.decode("utf-8", "replace")
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.S)
    if not match:
        _log.warning("loudnorm не вернул JSON, измеряю на numpy", extra={"path": str(path)})
        data, sr = load_wav(path)
        return LoudnessStats(measure_lufs_array(data, sr), true_peak_dbtp(data), source="numpy")
    payload = json.loads(match.group(0))

    def _f(key: str) -> float:
        try:
            return float(payload.get(key, "0"))
        except (TypeError, ValueError):
            return -math.inf

    return LoudnessStats(
        integrated_lufs=_f("input_i"),
        true_peak_dbtp=_f("input_tp"),
        lra=_f("input_lra"),
        threshold=_f("input_thresh"),
        source="ffmpeg",
    )


def measure_loudness_buffer(data: np.ndarray, sr: int = SAMPLE_RATE) -> LoudnessStats:
    """Измерение буфера через ffmpeg: на порядок быстрее numpy-реализации.

    Numpy-версия остаётся эталоном для тестов, но в пайплайне на 50-секундной
    дорожке она стоит секунды, а ebur128 из ffmpeg — доли секунды.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        save_wav(tmp_path, data, sr)
        return measure_loudness_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def db_to_gain(db: float) -> float:
    return 10.0 ** (db / 20.0)


def gain_to_db(gain: float) -> float:
    return 20.0 * math.log10(max(gain, EPS))


def apply_gain_db(data: np.ndarray, db: float) -> np.ndarray:
    return (np.asarray(data, dtype=np.float32) * db_to_gain(db)).astype(np.float32)


def normalize_to_lufs(data: np.ndarray, target_lufs: float, sr: int = SAMPLE_RATE,
                      *, measured: float | None = None) -> tuple[np.ndarray, float]:
    """Привести к целевому LUFS. Возвращает (аудио, применённый gain в dB)."""
    current = measured if measured is not None else measure_lufs_array(data, sr)
    if not math.isfinite(current):
        return np.asarray(data, dtype=np.float32), 0.0
    delta = target_lufs - current
    return apply_gain_db(data, delta), delta


def limit_true_peak(data: np.ndarray, max_dbtp: float = -1.0,
                    headroom_db: float = 0.3) -> np.ndarray:
    """Мягкий лимитер: сначала гейн, затем tanh-клип на границе (§4.4, QC-8).

    Целимся не в сам потолок, а чуть ниже. Судит QC не нашей оценкой, а
    измерением ffmpeg по отрендеренному файлу, и упереться ровно в границу
    значит отдать исход на волю расхождения двух измерений — а оно всегда
    найдётся: разные фильтры восстановления, разная длина окна, перекодировка.
    Три десятых децибела запаса стоят дешевле невыданного ролика.
    """
    arr = np.asarray(data, dtype=np.float32)
    target = max_dbtp - max(0.0, headroom_db)
    tp = true_peak_dbtp(arr)
    if tp <= target or not math.isfinite(tp):
        return arr
    arr = apply_gain_db(arr, target - tp)
    ceiling = db_to_gain(target)
    over = np.abs(arr) > ceiling
    if over.any():
        arr = np.where(over, np.sign(arr) * ceiling * np.tanh(np.abs(arr) / ceiling), arr)
    return arr.astype(np.float32)


# Канон громкости голоса (§4.4): −14 LUFS, True Peak ≤ −1 dBTP. Числа лежат
# здесь, а не в каждом вызове по месту: проба брала звук из клипа HeyGen как
# есть и отдавала −27.4 LUFS — тише канона на тринадцать децибел. Заказчик
# услышал это раньше, чем кто-либо измерил.
VOICE_LUFS = -14.0
VOICE_TRUE_PEAK_DBTP = -1.0


# Сжатие пиков. Порог задан **относительно целевой громкости**, а не в dBFS:
# так он не зависит от того, насколько тихим пришёл исходник. Числа подобраны
# измерением на живой дорожке от HeyGen — это наименьшее сжатие, при котором
# канон −14 LUFS достигается с запасом по пику (получилось −2.2 dBTP).
COMPRESS_ABOVE_TARGET_DB = 8.0
COMPRESS_RATIO = 4.0


# Ниже этой частоты динамик телефона почти ничего не отдаёт. Смысл звука,
# который целиком лежит ниже, до зрителя не доходит: он слышит не удар, а
# шорох. Ролики смотрят с телефона, поэтому это рабочая граница, а не придирка.
PHONE_FLOOR_HZ = 400.0


def speech_bandwidth_hz(data, sr: int = SAMPLE_RATE, share: float = 0.999) -> float:
    """Частота, ниже которой лежит ``share`` энергии речи.

    Показывает, где кончается полезная полоса. У несжатой речи это 15–20 кГц,
    у сжатой в mp3 — стена на частоте среза кодека. На 0047 замер дал 11 кГц:
    запрошен был ``pcm_44100``, а тариф отдал сжатый звук, и определить это по
    самому ответу было нечем — формат сервис не сообщает.

    Тишина в счёт не идёт: на паузах спектр — это шум дорожки, а не голос.
    """
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    n = 1 << 14
    if arr.size < n:
        return float(sr) / 2.0
    acc = np.zeros(n // 2 + 1)
    frames = 0
    loud = float(np.sqrt(np.mean(arr ** 2))) * 0.5
    for start in range(0, arr.size - n, n // 2):
        seg = arr[start:start + n]
        if float(np.sqrt(np.mean(seg ** 2))) < loud:
            continue
        acc += np.abs(np.fft.rfft(seg * np.hanning(n))) ** 2
        frames += 1
    if frames == 0:
        return float(sr) / 2.0
    cumulative = np.cumsum(acc)
    if cumulative[-1] <= 0:
        return float(sr) / 2.0      # тишина: полосу назвать нечем
    cumulative /= cumulative[-1]
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    return float(freqs[int(np.searchsorted(cumulative, share))])


def phone_speaker_loss_db(data, sr: int = SAMPLE_RATE,
                          floor_hz: float = PHONE_FLOOR_HZ) -> float:
    """На сколько дБ тише станет звук на динамике телефона.

    Грубая, но честная модель: срез всего, что ниже ``floor_hz``, и сравнение
    громкости до и после. Ноль — звук целиком в полосе телефона; −20 дБ — от
    него на телефоне остаётся двадцатая часть.

    Мерка появилась не из теории. У SFX «удар по факту» она показала −17 дБ:
    звук был чистым синусом на 70 Гц, которого телефон не воспроизводит вовсе,
    и в ролике от него оставался только слабый шорох. Заказчик услышал это как
    «дешёвый звук» раньше, чем нашлась причина.
    """
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    if arr.size < 16:
        return 0.0
    spec = np.fft.rfft(arr)
    freqs = np.fft.rfftfreq(arr.size, 1.0 / sr)
    # Плавный скат, а не стена: у динамика спад, и резкий срез завысил бы потери.
    keep = np.clip((freqs / max(floor_hz, 1.0)) ** 2, 0.0, 1.0)
    filtered = np.fft.irfft(spec * keep, n=arr.size)
    before = float(np.sqrt(np.mean(arr ** 2))) + 1e-12
    after = float(np.sqrt(np.mean(filtered ** 2))) + 1e-12
    return float(20.0 * np.log10(after / before))


def compress_peaks(data: np.ndarray, *, threshold_dbfs: float,
                   ratio: float = COMPRESS_RATIO) -> np.ndarray:
    """Мягкое сжатие всего, что выше порога. Без атаки и восстановления.

    Компрессор по огибающей звучал бы естественнее, но он вносит время, а
    значит и зависимость результата от того, где начался буфер. Здесь сжатие
    поотсчётное: одна и та же входная выборка всегда даёт один и тот же выход,
    и рендер остаётся воспроизводимым. Для речи разница на слух невелика —
    сжимаются доли миллисекунды на вершинах.
    """
    arr = np.asarray(data, dtype=np.float32)
    thresh = db_to_gain(threshold_dbfs)
    mag = np.abs(arr)
    over = mag > thresh
    if not over.any():
        return arr
    # Над порогом превышение делится на ratio: 8 дБ сверху станут двумя.
    excess = mag[over] / thresh
    out = arr.copy()
    out[over] = np.sign(arr[over]) * thresh * excess ** (1.0 / ratio)
    return out.astype(np.float32)


def normalize_voice(data: np.ndarray, sr: int = SAMPLE_RATE, *,
                    target_lufs: float = VOICE_LUFS,
                    true_peak_max: float = VOICE_TRUE_PEAK_DBTP,
                    compress: bool = True) -> tuple[np.ndarray, float]:
    """Голос к канону громкости: поднять, придавить выбросы, поднять, закрыть.

    Порядок выведен из измерения, а не из привычки. Дорожка от HeyGen приходит
    с пик-фактором 18.9 дБ — редкие выбросы торчат высоко над телом фразы. Если
    просто поднять её до −14 LUFS, пик уходит на +4.9 dBTP, и лимитер, чтобы
    закрыть потолок, опускает **всю** дорожку обратно: получалось −20 LUFS,
    то есть тише, чем просили, при формально соблюдённом потолке.

    Поэтому: сначала подъём к цели, потом сжатие выбросов (порог считается от
    цели, а не в абсолютных dBFS — иначе он зависел бы от громкости исходника
    и на тихом входе не срабатывал вовсе, что и случилось в первой версии),
    потом подъём ещё раз, потому что сжатие немного просадило интеграл, и лишь
    затем лимитер. На живой дорожке это даёт ровно −14.0 LUFS при −2.2 dBTP.

    ``compress=False`` оставлен для дорожек, где выбросы значимы сами по себе.

    Возвращает (аудио, суммарный gain в dB) — по нему видно, насколько тихим
    пришёл исходник.
    """
    arr = np.asarray(data, dtype=np.float32)
    before = measure_loudness_buffer(arr, sr).integrated_lufs
    arr, _ = normalize_to_lufs(arr, target_lufs, sr, measured=before)
    if compress:
        arr = compress_peaks(arr, threshold_dbfs=target_lufs + COMPRESS_ABOVE_TARGET_DB)
        measured = measure_loudness_buffer(arr, sr).integrated_lufs
        arr, _ = normalize_to_lufs(arr, target_lufs, sr, measured=measured)
    arr = limit_true_peak(arr, true_peak_max)
    after = measure_loudness_buffer(arr, sr).integrated_lufs
    return arr, after - before


# --- Монтажные операции ------------------------------------------------------

def rms_envelope(data: np.ndarray, sr: int, window_ms: float = 20.0) -> np.ndarray:
    mono = to_mono(data).astype(np.float64)
    win = max(1, int(sr * window_ms / 1000.0))
    kernel = np.ones(win) / win
    return np.sqrt(np.convolve(mono ** 2, kernel, mode="same") + EPS)


def detect_silences(data: np.ndarray, sr: int, *, floor_db: float = -42.0,
                    min_ms: float = 100.0, window_ms: float = 20.0) -> list[tuple[float, float]]:
    """Интервалы тишины [(start_sec, end_sec)] — вход для срезки пауз (§4.2)."""
    env = rms_envelope(data, sr, window_ms)
    with np.errstate(divide="ignore"):
        env_db = 20.0 * np.log10(env + EPS)
    quiet = env_db < floor_db
    out: list[tuple[float, float]] = []
    start: int | None = None
    min_len = int(sr * min_ms / 1000.0)
    for i, is_quiet in enumerate(quiet):
        if is_quiet and start is None:
            start = i
        elif not is_quiet and start is not None:
            if i - start >= min_len:
                out.append((start / sr, i / sr))
            start = None
    if start is not None and len(quiet) - start >= min_len:
        out.append((start / sr, len(quiet) / sr))
    return out


def crossfade_concat(segments: Sequence[np.ndarray], sr: int, fade_ms: float = 8.0) -> np.ndarray:
    """Склейка с микро-кроссфейдом: убирает щелчки на стыках после срезки пауз."""
    segments = [np.asarray(s, dtype=np.float32) for s in segments if len(s) > 0]
    if not segments:
        return np.zeros(0, dtype=np.float32)
    fade = max(1, int(sr * fade_ms / 1000.0))
    out = segments[0]
    for seg in segments[1:]:
        n = min(fade, len(out), len(seg))
        if n <= 1:
            out = np.concatenate([out, seg])
            continue
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        if out.ndim == 2:
            ramp = ramp[:, None]
        head = out[-n:] * (1.0 - ramp) + seg[:n] * ramp
        out = np.concatenate([out[:-n], head, seg[n:]])
    return out.astype(np.float32)


def loop_to_length(data: np.ndarray, n_samples: int, *, fade_ms: float = 250.0,
                   sr: int = SAMPLE_RATE) -> np.ndarray:
    """Зациклить подложку до нужной длины с кроссфейдом на стыке (§14.2)."""
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, None]
    if len(arr) == 0:
        return np.zeros((n_samples, 1), dtype=np.float32)
    if len(arr) >= n_samples:
        return arr[:n_samples]
    fade = min(int(sr * fade_ms / 1000.0), len(arr) // 2)
    out = arr
    while len(out) < n_samples:
        if fade > 1:
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
            head = out[-fade:] * (1.0 - ramp) + arr[:fade] * ramp
            out = np.concatenate([out[:-fade], head, arr[fade:]])
        else:
            out = np.concatenate([out, arr])
    return out[:n_samples]


def duck(bed: np.ndarray, speech: np.ndarray, sr: int, *, depth_db: float = -7.0,
         attack_ms: float = 80.0, release_ms: float = 320.0,
         threshold_db: float = -45.0) -> np.ndarray:
    """Ducking подложки под речь (§4.4): огибающая речи → плавный gain на bed."""
    bed_arr = np.asarray(bed, dtype=np.float32)
    if bed_arr.ndim == 1:
        bed_arr = bed_arr[:, None]
    env = rms_envelope(speech, sr, window_ms=30.0)
    if len(env) < len(bed_arr):
        env = np.pad(env, (0, len(bed_arr) - len(env)))
    env = env[:len(bed_arr)]
    with np.errstate(divide="ignore"):
        env_db = 20.0 * np.log10(env + EPS)
    active = (env_db > threshold_db).astype(np.float64)

    # Экспоненциальное сглаживание: быстрый attack, медленный release.
    a_att = math.exp(-1.0 / max(1.0, sr * attack_ms / 1000.0))
    a_rel = math.exp(-1.0 / max(1.0, sr * release_ms / 1000.0))
    smooth = np.empty_like(active)
    state = 0.0
    for i, target in enumerate(active):
        coeff = a_att if target > state else a_rel
        state = target + coeff * (state - target)
        smooth[i] = state
    gain = db_to_gain(depth_db) + (1.0 - db_to_gain(depth_db)) * (1.0 - smooth)
    return (bed_arr * gain[:, None].astype(np.float32)).astype(np.float32)


def mix(layers: Iterable[tuple[np.ndarray, float]], length: int, channels: int = 2) -> np.ndarray:
    """Смикшировать слои [(аудио, gain_db)] в буфер заданной длины."""
    out = np.zeros((length, channels), dtype=np.float32)
    for data, gain_db in layers:
        arr = np.asarray(data, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr[:, None]
        if arr.shape[1] == 1 and channels == 2:
            arr = np.repeat(arr, 2, axis=1)
        elif arr.shape[1] > channels:
            arr = arr[:, :channels]
        n = min(len(arr), length)
        out[:n] += arr[:n] * db_to_gain(gain_db)
    return out


def place(buffer: np.ndarray, clip: np.ndarray, at_sec: float, sr: int,
          *, gain_db: float = 0.0) -> np.ndarray:
    """Подмешать клип (SFX) в буфер начиная с указанной секунды."""
    arr = np.asarray(clip, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.shape[1] == 1 and buffer.shape[1] == 2:
        arr = np.repeat(arr, 2, axis=1)
    start = max(0, int(round(at_sec * sr)))
    end = min(len(buffer), start + len(arr))
    if end <= start:
        return buffer
    buffer[start:end] += arr[:end - start] * db_to_gain(gain_db)
    return buffer


def peak_dbfs(data: np.ndarray) -> float:
    arr = np.abs(np.asarray(data, dtype=np.float64))
    return 20.0 * math.log10(float(arr.max()) + EPS) if arr.size else -math.inf


def normalize_peak(data: np.ndarray, target_dbfs: float) -> np.ndarray:
    current = peak_dbfs(data)
    if not math.isfinite(current):
        return np.asarray(data, dtype=np.float32)
    return apply_gain_db(data, target_dbfs - current)


def trailing_silence_ms(data: np.ndarray, sr: int, *, floor_db: float = -50.0) -> float:
    """Длина тишины в конце — QC-13 (§11.1) требует ≤300 мс."""
    env = rms_envelope(data, sr, window_ms=10.0)
    with np.errstate(divide="ignore"):
        env_db = 20.0 * np.log10(env + EPS)
    idx = np.nonzero(env_db > floor_db)[0]
    if len(idx) == 0:
        return duration_sec(data, sr) * 1000.0
    return (len(env_db) - 1 - int(idx[-1])) / sr * 1000.0
