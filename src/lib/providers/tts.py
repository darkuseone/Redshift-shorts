"""TTS-провайдеры (§4.2, R-4, скилл ``redshift-voice``).

Live: ElevenLabs с эндпоинтом ``with-timestamps`` — он возвращает посимвольное
выравнивание, из которого собираются пословные тайминги; фолбэк на
``multilingual_v2`` при недоступности основной модели закрывает риск R-4.

Mock: локальный синтез речеподобного сигнала с точными таймингами слов. Он не
имитирует голос, а воспроизводит **структуру** речи — длительности по слогам,
межсловные зазоры и «лишние» паузы, — чтобы P3 (срез пауз) и P4 (выравнивание)
работали на честных данных, а не на тишине.
"""

from __future__ import annotations

import base64
import hashlib
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ...errors import ProviderError
from ..audio import (SAMPLE_RATE, load_audio_any, resample, save_wav,
                     speech_bandwidth_hz)
from ..logging import get_logger
from ..retry import call_with_retry
from ..schema import count_syllables
from .base import Provider, ProviderMode, resolve_mode

_log = get_logger("tts")


@dataclass
class WordTiming:
    word: str
    start: float
    end: float

    def to_dict(self) -> dict[str, Any]:
        return {"word": self.word, "start": round(self.start, 4), "end": round(self.end, 4)}


@dataclass
class TTSResult:
    audio_path: Path
    sample_rate: int
    duration_sec: float
    words: list[WordTiming] = field(default_factory=list)
    model: str = ""
    provider_mode: str = "mock"
    voice_id: str = ""
    chars: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "audio_path": str(self.audio_path),
            "sample_rate": self.sample_rate,
            "duration_sec": round(self.duration_sec, 3),
            "model": self.model,
            "provider_mode": self.provider_mode,
            "voice_id": self.voice_id,
            "chars": self.chars,
            "words": [w.to_dict() for w in self.words],
        }


class TTSProvider(Provider):
    name = "elevenlabs"

    def synthesize(self, text: str, out_path: Path, *, speed: float = 1.0) -> TTSResult:
        raise NotImplementedError


# --- mock --------------------------------------------------------------------

class MockTTS(TTSProvider):
    """Детерминированный синтез: одинаковый текст → побитово одинаковый WAV."""

    name = "elevenlabs"

    # Плотная подача референсов (§2.2): ~5.4 слога/сек при speed=1.0.
    SYLL_PER_SEC = 5.4
    WORD_GAP_SEC = 0.045
    SENTENCE_PAUSE_SEC = 0.42       # то, что P3 срежет до 80–120 мс
    COMMA_PAUSE_SEC = 0.26
    BREATH_EVERY_N_SENTENCES = 2

    def synthesize(self, text: str, out_path: Path, *, speed: float = 1.0) -> TTSResult:
        sr = int(self.cfg.get("elevenlabs.sample_rate", SAMPLE_RATE))
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)

        words = [w for w in text.split() if w]
        chunks: list[np.ndarray] = []
        timings: list[WordTiming] = []
        cursor = 0.0
        sentence_index = 0

        # Небольшая «преамбула» тишины — её тоже обязан подрезать P3.
        lead = 0.18
        chunks.append(np.zeros(int(lead * sr), dtype=np.float32))
        cursor += lead

        for idx, raw_word in enumerate(words):
            clean = raw_word.strip(",.!?;:—–«»\"'()")
            if not re.search(r"[^\W_]", clean, re.UNICODE):
                # Одиночная пунктуация (тире между словами) — это пауза, а не
                # слово: озвучивать её нельзя, иначе тайминги разъедутся с
                # экранными токенами в P4.
                chunks.append(np.zeros(int(0.12 * sr), dtype=np.float32))
                cursor += 0.12
                continue
            syll = max(1, count_syllables(clean))
            dur = syll / (self.SYLL_PER_SEC * max(speed, 0.05))
            audio = self._word_signal(dur, sr, rng, syll)
            chunks.append(audio)
            timings.append(WordTiming(clean, cursor, cursor + dur))
            cursor += dur

            tail = raw_word[-1:] if raw_word else ""
            if tail in ".!?":
                sentence_index += 1
                pause = self.SENTENCE_PAUSE_SEC
                if sentence_index % self.BREATH_EVERY_N_SENTENCES == 0:
                    breath = self._breath_signal(0.16, sr, rng)
                    chunks.append(breath)
                    cursor += len(breath) / sr
                    pause -= 0.16
            elif tail in ",;:—–":
                pause = self.COMMA_PAUSE_SEC
            elif idx == len(words) - 1:
                pause = 0.12
            else:
                pause = self.WORD_GAP_SEC
            pause = max(pause, 0.0)
            chunks.append(np.zeros(int(pause * sr), dtype=np.float32))
            cursor += pause

        signal = np.concatenate(chunks) if chunks else np.zeros(sr, dtype=np.float32)
        signal = np.clip(signal, -0.95, 0.95).astype(np.float32)
        save_wav(out_path, signal, sr)
        self.charge("tts", len(text), "chars",
                    len(text) / 1000.0 * float(self.cfg.get("budget.price.elevenlabs_per_1k_chars", 0.3)))

        return TTSResult(
            audio_path=Path(out_path), sample_rate=sr, duration_sec=len(signal) / sr,
            words=timings, model="mock-v1", provider_mode="mock",
            voice_id="mock-voice", chars=len(text),
        )

    def _word_signal(self, dur: float, sr: int, rng: np.random.Generator, syllables: int) -> np.ndarray:
        """Речеподобный сигнал: основной тон + гармоники + слоговая огибающая."""
        n = max(1, int(dur * sr))
        t = np.arange(n) / sr
        f0 = 118.0 + rng.uniform(-14.0, 22.0)
        vibrato = 1.0 + 0.015 * np.sin(2 * np.pi * 4.5 * t)
        sig = np.zeros(n, dtype=np.float64)
        for harmonic, amp in ((1, 1.0), (2, 0.5), (3, 0.28), (4, 0.15), (5, 0.08)):
            sig += amp * np.sin(2 * np.pi * f0 * harmonic * vibrato * t)
        # Форманты имитируем шумовой составляющей в верхней полосе.
        sig += 0.12 * rng.normal(0.0, 1.0, n) * np.exp(-3.0 * t / max(dur, 1e-6))
        # Слоговая огибающая: столько «горбов», сколько слогов.
        syl_env = 0.55 + 0.45 * np.abs(np.sin(np.pi * syllables * t / max(dur, 1e-6)))
        attack = np.minimum(1.0, np.arange(n) / max(1, int(0.012 * sr)))
        release = np.minimum(1.0, np.arange(n)[::-1] / max(1, int(0.020 * sr)))
        sig *= syl_env * attack * release
        peak = float(np.max(np.abs(sig))) or 1.0
        return (sig / peak * 0.42).astype(np.float32)

    def _breath_signal(self, dur: float, sr: int, rng: np.random.Generator) -> np.ndarray:
        """Вдох: тихий шум с плавной огибающей — P3 обязан его вырезать (§4.2.3)."""
        n = max(1, int(dur * sr))
        noise = rng.normal(0.0, 1.0, n)
        # Простой ФНЧ скользящим средним — вдох глухой, без верха.
        kernel = np.ones(24) / 24.0
        noise = np.convolve(noise, kernel, mode="same")
        env = np.sin(np.pi * np.arange(n) / n) ** 2
        return (noise * env * 0.035).astype(np.float32)


# --- live --------------------------------------------------------------------

def _decode_tts_audio(raw: bytes, *, api_sr: int, target_sr: int,
                      model: str) -> tuple[np.ndarray, str]:
    """Тело ответа TTS → моно float32 на частоте конвейера и имя контейнера.

    Контейнер возвращается наружу, а не только пишется в лог: проба голоса
    показывает заказчику, что тариф отдал на самом деле, и «просили pcm_44100 —
    пришёл .mp3» это ответ на его вопрос, а не строка в чужом журнале.

    Формат определяется по самим байтам, а не по тому, что мы попросили.
    ``pcm_*`` доступен не на всех тарифах, и на младших ElevenLabs **молча
    отдаёт mp3** вместо запрошенного PCM: поймано живым прогоном, тело
    начиналось с ``ID3``, а код разбирал его как s16le и падал.

    Контейнерные форматы отдаются ffmpeg — он и распакует, и приведёт к нужной
    частоте. Сырой PCM заголовка не имеет, распознать его нечем, поэтому он
    остаётся случаем по умолчанию.
    """
    container = None
    if raw[:3] == b"ID3" or (len(raw) > 1 and raw[0] == 0xFF and raw[1] & 0xE0 == 0xE0):
        container = ".mp3"
    elif raw[:4] == b"RIFF":
        container = ".wav"
    elif raw[:4] == b"OggS":
        container = ".ogg"

    if container:
        _log.info("сервис отдал контейнер вместо сырого PCM",
                  extra={"format": container, "model": model, "bytes": len(raw)})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"tts{container}"
            path.write_bytes(raw)
            data, _ = load_audio_any(path, sr=target_sr)
        return np.asarray(data, dtype=np.float32), container

    if len(raw) % 2:
        raise ProviderError(
            "ElevenLabs вернул не PCM 16 бит и не известный контейнер",
            model=model, requested_format=f"pcm_{api_sr}", bytes=len(raw),
            head=raw[:16].hex())
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    pcm = resample(pcm, api_sr, target_sr) if api_sr != target_sr else pcm
    return pcm, "pcm"


# PCM ElevenLabs отдаёт только на этих частотах — проверено ответом сервиса.
# Конвейер живёт на 48 кГц (audio.sample_rate), поэтому берём ближайшую снизу
# доступную и передискретизируем у себя.
ELEVENLABS_PCM_RATES = (8000, 16000, 22050, 24000, 44100)


def _nearest_supported_rate(sr: int) -> int:
    """Ближайшая частота, которую сервис действительно умеет отдавать."""
    if sr in ELEVENLABS_PCM_RATES:
        return sr
    below = [r for r in ELEVENLABS_PCM_RATES if r <= sr]
    return max(below) if below else min(ELEVENLABS_PCM_RATES)


class ElevenLabsTTS(TTSProvider):
    name = "elevenlabs"

    def __init__(self, cfg, costs, api_key: str, voice_id: str) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="elevenlabs")
        self.api_key = api_key
        self.voice_id = voice_id

    def synthesize(self, text: str, out_path: Path, *, speed: float = 1.0) -> TTSResult:
        model = str(self.cfg.get("elevenlabs.model", "eleven_v3"))
        fallback = str(self.cfg.get("elevenlabs.fallback_model", "eleven_multilingual_v2"))
        try:
            return self._request(text, out_path, model=model, speed=speed)
        except ProviderError as exc:
            # R-4: доступность v3 в API не гарантирована — уходим на multilingual.
            _log.warning("основная модель недоступна, фолбэк",
                         extra={"model": model, "fallback": fallback, "error": exc.message})
            return self._request(text, out_path, model=fallback, speed=speed)

    # eleven_v3 принимает не любую ровность, а одно из трёх значений. Прислав
    # промежуточное, получаешь отказ — и это стоит целого прогона. Числа взяты
    # из схемы API: 0 — «творческий», 0.5 — «естественный», 1 — «ровный».
    V3_STABILITY_STEPS = (0.0, 0.5, 1.0)

    def _voice_settings(self, speed: float, *, model: str = "") -> dict[str, Any]:
        """Характер подачи. Числа в конфиге, а не здесь: их подбирают на слух.

        ``stability`` у ElevenLabs — это ровность, а не качество: чем выше, тем
        монотоннее читает. На 0.45 речь выходила плоской — измеренный разброс
        громкости готового ролика 2.0 LU, то есть почти ровная линия, и на слух
        «неживо». Ниже — шире интонационный размах, но растёт риск, что модель
        уведёт произношение; 0.30 — та граница, где размах уже слышен, а голос
        ещё узнаётся.

        ``style`` усиливает манеру исходного голоса, ``use_speaker_boost``
        держит тембр ближе к клону. Оба параметра раньше не отправлялись вовсе,
        и сервис применял свои значения по умолчанию.
        """
        node = self.cfg.get("elevenlabs.voice_settings", {}) or {}
        stability = float(node.get("stability", 0.30))
        if model.startswith("eleven_v3"):
            # Прижимаем к ближайшему разрешённому, а не падаем: конфиг
            # настраивают на слух под основную модель, и запрет одной из них
            # не повод останавливать прогон.
            stability = min(self.V3_STABILITY_STEPS,
                            key=lambda step: abs(step - stability))
        settings: dict[str, Any] = {
            "stability": stability,
            "similarity_boost": float(node.get("similarity_boost", 0.85)),
            "style": float(node.get("style", 0.45)),
            "use_speaker_boost": bool(node.get("use_speaker_boost", True)),
            "speed": speed,
        }
        return settings

    def _request(self, text: str, out_path: Path, *, model: str, speed: float) -> TTSResult:
        import requests

        base = str(self.cfg.get("elevenlabs.api_base", "https://api.elevenlabs.io"))
        sr = int(self.cfg.get("elevenlabs.sample_rate", SAMPLE_RATE))
        # Просить у сервиса частоту, которой у него нет, нельзя: конвейер живёт
        # на 48 кГц, а PCM ElevenLabs отдаёт только на перечисленных частотах.
        # На pcm_48000 ответ приходил не сырым PCM, и разбор падал невнятным
        # «buffer size must be a multiple of element size» — поймано на живом
        # прогоне. Берём ближайшую доступную и приводим к канону сами.
        api_sr = _nearest_supported_rate(sr)
        # Формат вынесен в конфиг: он зависит от тарифа, а не от кода. На нашем
        # тарифе pcm_* недоступен, и сервис молча подменяет его сжатым mp3 —
        # заменить это правкой YAML должно быть можно без прогона по коду.
        fmt = str(self.cfg.get("elevenlabs.output_format", "") or f"pcm_{api_sr}")
        url = f"{base}/v1/text-to-speech/{self.voice_id}/with-timestamps"
        payload = {
            "text": text,
            "model_id": model,
            "output_format": fmt,
            "voice_settings": self._voice_settings(speed, model=model),
        }
        headers = {"xi-api-key": self.api_key, "Content-Type": "application/json"}

        def _call() -> dict[str, Any]:
            resp = requests.post(url, json=payload, headers=headers, timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"ElevenLabs вернул {resp.status_code}",
                                    status=resp.status_code, body=resp.text[:400])
            return resp.json()

        data = call_with_retry(_call, **self._retry_kwargs("ElevenLabs TTS"))

        raw = base64.b64decode(data.get("audio_base64", ""))
        if not raw:
            raise ProviderError("ElevenLabs вернул пустое аудио", model=model)
        pcm, container = _decode_tts_audio(raw, api_sr=api_sr, target_sr=sr,
                                           model=model)

        # Полоса — единственное, по чему видно, что на самом деле отдал сервис.
        # На 0047 запрошен был pcm_44100, а пришёл сжатый mp3 со срезом на
        # 11 кГц, и заказчик услышал это как «низкое качество» раньше, чем
        # нашлась причина. Молча принимать такое нельзя: конвейер обязан
        # сказать, что упёрся в тариф, а не в свой тракт.
        band = speech_bandwidth_hz(pcm, sr)
        floor = float(self.cfg.get("elevenlabs.min_bandwidth_hz", 14000))
        # Что попросили и что получили — на виду у пробы голоса.
        self.last_delivery = {"requested_format": fmt, "container": container,
                              "bandwidth_hz": round(band)}
        _log.info("полоса синтезированной речи", extra={
            "bandwidth_hz": round(band), "requested_format": fmt, "model": model})
        if band < floor:
            _log.warning(
                "полоса речи ниже ожидаемой: сервис отдал сжатый звук",
                extra={"bandwidth_hz": round(band), "expected_hz": round(floor),
                       "requested_format": fmt, "model": model,
                       "hint": "поднять тариф ElevenLabs или задать "
                               "elevenlabs.output_format"})

        save_wav(out_path, pcm, sr)

        words = _words_from_alignment(
            data.get("alignment") or data.get("normalized_alignment") or {}
        )
        self.charge("tts", len(text), "chars",
                    len(text) / 1000.0 * float(self.cfg.get("budget.price.elevenlabs_per_1k_chars", 0.3)),
                    model=model)
        return TTSResult(
            audio_path=Path(out_path), sample_rate=sr, duration_sec=len(pcm) / sr,
            words=words, model=model, provider_mode="live",
            voice_id=self.voice_id, chars=len(text),
        )


def _words_from_alignment(alignment: dict[str, Any]) -> list[WordTiming]:
    """Посимвольное выравнивание ElevenLabs → пословные тайминги."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not chars or len(chars) != len(starts) or len(chars) != len(ends):
        return []
    words: list[WordTiming] = []
    buf: list[str] = []
    start: float | None = None
    end = 0.0
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if buf:
                words.append(WordTiming("".join(buf).strip(",.!?;:—–«»\"'()"), start or 0.0, end))
                buf, start = [], None
            continue
        if start is None:
            start = float(s)
        buf.append(ch)
        end = float(e)
    if buf:
        words.append(WordTiming("".join(buf).strip(",.!?;:—–«»\"'()"), start or 0.0, end))
    return [w for w in words if w.word]


def build_tts_provider(cfg, costs) -> TTSProvider:
    api_key = cfg.secret_for("elevenlabs.api_key_env", purpose="ElevenLabs TTS")
    voice_id = cfg.get("elevenlabs.voice_id", "") or cfg.secret_for("elevenlabs.voice_id_env") or ""
    mode = resolve_mode(cfg, api_key=api_key if (api_key and voice_id) else None, service="elevenlabs")
    if mode is ProviderMode.LIVE:
        return ElevenLabsTTS(cfg, costs, api_key or "", voice_id)
    return MockTTS(cfg=cfg, costs=costs, mode=ProviderMode.MOCK, name="elevenlabs")
