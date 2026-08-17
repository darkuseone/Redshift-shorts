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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ...errors import ProviderError
from ..audio import SAMPLE_RATE, save_wav
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

    def _request(self, text: str, out_path: Path, *, model: str, speed: float) -> TTSResult:
        import requests

        base = str(self.cfg.get("elevenlabs.api_base", "https://api.elevenlabs.io"))
        sr = int(self.cfg.get("elevenlabs.sample_rate", SAMPLE_RATE))
        url = f"{base}/v1/text-to-speech/{self.voice_id}/with-timestamps"
        payload = {
            "text": text,
            "model_id": model,
            "output_format": f"pcm_{sr}",
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "speed": speed},
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
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
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
