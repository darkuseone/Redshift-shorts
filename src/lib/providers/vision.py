"""Vision-провайдеры для трёхступенчатой оценки футажей (§7.3).

Шаг 2 — основной критик (Gemini, дешевле), шаг 3 — арбитраж (Grok, лимит 8
вызовов на ролик). Оба возвращают одинаковый вердикт, поэтому арбитраж — это
просто повторная оценка более дорогой моделью, а не отдельный формат данных.

Mock-критик не выдаёт случайное число: он реально смотрит на кадр — считает
яркость, контраст, насыщенность, плотность деталей и пригодность композиции под
кроп 9:16. Благодаря этому пороги §7.3 (0.45 / 0.70) и триггеры арбитража
работают на осмысленном распределении оценок, а не на шуме.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

from ...errors import ProviderError
from ..logging import get_logger
from ..retry import call_with_retry
from .base import Provider, ProviderMode, resolve_mode

_log = get_logger("vision")


@dataclass
class VisionVerdict:
    score: float
    reason: str
    summary: str = ""
    has_text: bool = False
    has_logo: bool = False
    watermark: bool = False
    stocky: bool = False
    composition_9x16: float = 0.5
    quality: float = 0.5
    relevance: float = 0.5
    judge: str = "mock"
    frames: int = 0
    per_frame_scores: list[float] = field(default_factory=list)

    @property
    def frame_disagreement(self) -> float:
        if len(self.per_frame_scores) < 2:
            return 0.0
        return max(self.per_frame_scores) - min(self.per_frame_scores)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4), "reason": self.reason, "summary": self.summary,
            "has_text": self.has_text, "has_logo": self.has_logo,
            "watermark": self.watermark, "stocky": self.stocky,
            "composition_9x16": round(self.composition_9x16, 3),
            "quality": round(self.quality, 3), "relevance": round(self.relevance, 3),
            "judge": self.judge, "frames": self.frames,
            "per_frame_scores": [round(s, 3) for s in self.per_frame_scores],
            "frame_disagreement": round(self.frame_disagreement, 3),
        }


PROMPT = """Ты — придирчивый видеоредактор канала о науке и технологиях.
Оцени кадры как материал B-roll для вертикального ролика 9:16.

Смысл блока: {intent}
Роль блока в ролике: {role}
Поисковый запрос: {query}

Верни СТРОГО JSON без пояснений:
{{"score": 0.0-1.0, "summary": "что реально изображено, одной фразой",
 "relevance": 0.0-1.0, "quality": 0.0-1.0, "composition_9x16": 0.0-1.0,
 "has_text": bool, "has_logo": bool, "watermark": bool, "stocky": bool,
 "reason": "коротко, почему такая оценка"}}

Снижай оценку за: несоответствие смыслу, «стоковость» (постановочные улыбки,
рукопожатия), водяные знаки, чужой брендинг, текст в кадре, плохую композицию
под вертикальный кроп, шум и артефакты сжатия."""


class VisionProvider(Provider):
    def judge(self, frames: Sequence[Path], *, intent: str, role: str,
              query: str) -> VisionVerdict:
        raise NotImplementedError


# --- mock ---------------------------------------------------------------------

class MockVision(VisionProvider):
    """Оценка по измеримым свойствам кадра — детерминированная и осмысленная."""

    def __init__(self, cfg, costs, *, judge_name: str = "gemini") -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.MOCK, name=judge_name)
        self.judge_name = judge_name

    def judge(self, frames: Sequence[Path], *, intent: str, role: str,
              query: str) -> VisionVerdict:
        if not frames:
            return VisionVerdict(score=0.0, reason="нет кадров для оценки",
                                 judge=f"{self.judge_name}-mock")
        per_frame: list[float] = []
        stats: list[dict[str, float]] = []
        for frame in frames:
            metrics = _frame_metrics(frame)
            stats.append(metrics)
            per_frame.append(metrics["frame_score"])

        avg = float(np.mean(per_frame))
        # Смещение по запросу: одинаковый запрос всегда даёт одинаковый порядок
        # кандидатов, но разные запросы — разный.
        seed = int(hashlib.sha256(f"{query}|{frames[0].name}".encode()).hexdigest()[:8], 16)
        jitter = ((seed % 1000) / 1000.0 - 0.5) * 0.22
        relevance = min(1.0, max(0.0, 0.62 + jitter))
        composition = float(np.mean([s["composition"] for s in stats]))
        quality = float(np.mean([s["quality"] for s in stats]))

        score = min(1.0, max(0.0, 0.42 * relevance + 0.30 * quality + 0.28 * composition))
        stocky = bool(seed % 11 == 0)
        has_text = bool(np.mean([s["edge_density"] for s in stats]) > 0.34 and seed % 5 == 0)
        if stocky:
            score *= 0.72
        if has_text:
            score *= 0.85

        self.charge("judge", len(frames), "images",
                    len(frames) * float(self.cfg.get(
                        f"budget.price.{'grok' if 'grok' in self.judge_name else 'gemini'}_per_image", 0.0004)))
        return VisionVerdict(
            score=round(score, 4),
            reason=_mock_reason(score, relevance, quality, composition, stocky, has_text),
            summary=_mock_summary(stats[0], query),
            has_text=has_text, stocky=stocky,
            composition_9x16=composition, quality=quality, relevance=relevance,
            judge=f"{self.judge_name}-mock", frames=len(frames),
            per_frame_scores=per_frame,
        )


def _frame_metrics(path: Path) -> dict[str, float]:
    """Измеримые свойства кадра: яркость, контраст, цветность, детали, композиция."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        width, height = img.size
        small = img.resize((96, 96), Image.Resampling.BILINEAR)
        arr = np.asarray(small, dtype=np.float64) / 255.0

    gray = arr.mean(axis=2)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    colorfulness = float(np.mean(np.std(arr, axis=2)))
    gx = np.abs(np.diff(gray, axis=1)).mean()
    gy = np.abs(np.diff(gray, axis=0)).mean()
    edge_density = float((gx + gy) / 2 * 4.0)

    # Пригодность под 9:16: насколько содержательна центральная вертикальная полоса.
    center = gray[:, 30:66]
    center_energy = float(np.abs(np.diff(center, axis=1)).mean() * 4.0)
    aspect = height / max(width, 1)
    aspect_bonus = 1.0 if aspect >= 1.5 else (0.82 if aspect >= 0.95 else 0.66)
    composition = min(1.0, (0.45 + center_energy) * aspect_bonus)

    # Качество: наказываем пересвет, недосвет и вялый контраст.
    exposure = 1.0 - abs(brightness - 0.5) * 1.4
    quality = min(1.0, max(0.05, 0.5 * max(exposure, 0.0) + 0.35 * min(contrast * 3.2, 1.0)
                           + 0.15 * min(colorfulness * 4.0, 1.0)))
    frame_score = min(1.0, 0.55 * quality + 0.45 * composition)
    return {
        "brightness": brightness, "contrast": contrast, "colorfulness": colorfulness,
        "edge_density": edge_density, "composition": composition, "quality": quality,
        "frame_score": frame_score,
    }


def _mock_reason(score: float, relevance: float, quality: float, composition: float,
                 stocky: bool, has_text: bool) -> str:
    parts: list[str] = []
    if stocky:
        parts.append("выглядит постановочно-стоково")
    if has_text:
        parts.append("в кадре есть текст")
    if composition < 0.5:
        parts.append("композиция плохо режется под 9:16")
    if quality < 0.45:
        parts.append("слабая экспозиция или контраст")
    if relevance < 0.5:
        parts.append("связь со смыслом блока натянутая")
    if not parts:
        parts.append("чистый кадр, композиция держит вертикальный кроп")
    return f"score {score:.2f}: " + ", ".join(parts)


def _mock_summary(metrics: dict[str, float], query: str) -> str:
    tone = "светлый" if metrics["brightness"] > 0.55 else (
        "тёмный" if metrics["brightness"] < 0.3 else "средний по свету")
    detail = "детализированный" if metrics["edge_density"] > 0.25 else "спокойный"
    return f"{tone}, {detail} кадр по запросу «{query}»"


# --- Gemini -------------------------------------------------------------------

class GeminiVision(VisionProvider):
    def __init__(self, cfg, costs, api_key: str) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="gemini")
        self.api_key = api_key

    def judge(self, frames: Sequence[Path], *, intent: str, role: str,
              query: str) -> VisionVerdict:
        import requests

        model = str(self.cfg.get("vision.gemini_model", "gemini-2.5-flash"))
        base = str(self.cfg.get("vision.gemini_api_base",
                                "https://generativelanguage.googleapis.com"))
        url = f"{base}/v1beta/models/{model}:generateContent"
        parts: list[dict[str, Any]] = [
            {"text": PROMPT.format(intent=intent, role=role, query=query)}]
        for frame in frames:
            parts.append({"inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(frame.read_bytes()).decode("ascii"),
            }})

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }

        def _call() -> dict[str, Any]:
            resp = requests.post(url, params={"key": self.api_key}, json=payload,
                                 timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"Gemini вернул {resp.status_code}",
                                    status=resp.status_code, body=resp.text[:300])
            return resp.json()

        data = call_with_retry(_call, **self._retry_kwargs("Gemini vision"))
        text = _gemini_text(data)
        self.charge("judge", len(frames), "images",
                    len(frames) * float(self.cfg.get("budget.price.gemini_per_image", 0.0004)),
                    model=model)
        return _verdict_from_json(text, judge="gemini", frames=len(frames))


def _gemini_text(data: dict[str, Any]) -> str:
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "text" in part:
                return str(part["text"])
    raise ProviderError("Gemini вернул ответ без текста")


# --- Grok ---------------------------------------------------------------------

class GrokVision(VisionProvider):
    def __init__(self, cfg, costs, api_key: str) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="grok")
        self.api_key = api_key

    def judge(self, frames: Sequence[Path], *, intent: str, role: str,
              query: str) -> VisionVerdict:
        import requests

        model = str(self.cfg.get("vision.grok_model", "grok-4-fast"))
        base = str(self.cfg.get("vision.grok_api_base", "https://api.x.ai"))
        content: list[dict[str, Any]] = [
            {"type": "text", "text": PROMPT.format(intent=intent, role=role, query=query)}]
        for frame in frames:
            b64 = base64.b64encode(frame.read_bytes()).decode("ascii")
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

        payload = {"model": model, "messages": [{"role": "user", "content": content}],
                   "temperature": 0.1}

        def _call() -> dict[str, Any]:
            resp = requests.post(f"{base}/v1/chat/completions", json=payload,
                                 headers={"Authorization": f"Bearer {self.api_key}"},
                                 timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"Grok вернул {resp.status_code}",
                                    status=resp.status_code, body=resp.text[:300])
            return resp.json()

        data = call_with_retry(_call, **self._retry_kwargs("Grok vision"))
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        self.charge("judge", len(frames), "images",
                    len(frames) * float(self.cfg.get("budget.price.grok_per_image", 0.006)),
                    model=model)
        return _verdict_from_json(str(text), judge="grok", frames=len(frames))


def _verdict_from_json(text: str, *, judge: str, frames: int) -> VisionVerdict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ProviderError(f"{judge}: ответ не содержит JSON", sample=text[:200])
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ProviderError(f"{judge}: не удалось разобрать JSON", sample=text[:200]) from exc

    def _f(key: str, default: float) -> float:
        try:
            return min(1.0, max(0.0, float(payload.get(key, default))))
        except (TypeError, ValueError):
            return default

    return VisionVerdict(
        score=_f("score", 0.5),
        reason=str(payload.get("reason", ""))[:400],
        summary=str(payload.get("summary", ""))[:200],
        has_text=bool(payload.get("has_text", False)),
        has_logo=bool(payload.get("has_logo", False)),
        watermark=bool(payload.get("watermark", False)),
        stocky=bool(payload.get("stocky", False)),
        composition_9x16=_f("composition_9x16", 0.5),
        quality=_f("quality", 0.5),
        relevance=_f("relevance", 0.5),
        judge=judge, frames=frames,
    )


def build_vision_provider(cfg, costs, *, role: str = "primary") -> VisionProvider:
    if role == "arbiter":
        key = cfg.secret_for("vision.grok_api_key_env", purpose="Grok Vision (арбитраж)")
        if resolve_mode(cfg, api_key=key, service="grok") is ProviderMode.LIVE:
            return GrokVision(cfg, costs, key or "")
        return MockVision(cfg, costs, judge_name="grok")

    key = cfg.secret_for("vision.gemini_api_key_env", purpose="Gemini Vision")
    if resolve_mode(cfg, api_key=key, service="gemini") is ProviderMode.LIVE:
        return GeminiVision(cfg, costs, key or "")
    return MockVision(cfg, costs, judge_name="gemini")
