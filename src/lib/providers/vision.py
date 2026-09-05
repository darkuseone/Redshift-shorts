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
from ..retry import call_with_retry, is_capacity_error
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


# Тот же судья, но другой вопрос. §11.2 показывает ему кадр **готового** ролика,
# а спрашивал его прежний промпт про «материал B-roll» — и судья честно снижал
# оценку за наш собственный субтитр («крупный текст в центре портит B-roll») и
# за самого ведущего («это говорящая голова, а не B-roll»). На 0047 из шести
# проб так набралось четыре: доля расхождений вышла 67 % там, где картинка не
# совпала с речью в лучшем случае дважды. Мерили не то, что хотели измерить.
FINAL_FRAME_PROMPT = """Ты — придирчивый видеоредактор канала о науке и технологиях.
Перед тобой кадр ГОТОВОГО вертикального ролика 9:16, а не материал для монтажа.

Что в этом кадре по замыслу: {intent}
Речь в этот момент: {query}
Роль блока в ролике: {role}

Оформление канала — субтитр (одно слово крупно по центру), слово за головой,
плашка, карточка источника, кнопка подписки, ведущий в кадре — так задумано.
Это НЕ дефект, оценку за это не снижай и текстом в кадре не считай.

Верни СТРОГО JSON без пояснений:
{{"score": 0.0-1.0, "summary": "что реально изображено, одной фразой",
 "relevance": 0.0-1.0, "quality": 0.0-1.0, "composition_9x16": 0.0-1.0,
 "has_text": bool, "has_logo": bool, "watermark": bool, "stocky": bool,
 "reason": "коротко, почему такая оценка"}}

score — насколько картинка соответствует тому, что произносится, и замыслу
кадра. Снижай за: картинку не про то, о чём речь; обрезанные головы и битые
маски; нечитаемую надпись (контраст, пёстрый фон); растяжение и артефакты.
has_text — только ЧУЖОЙ текст: подпись стока, логотип, надпись, вшитая в
исходный материал. Оформление канала сюда не входит.
stocky — постановочный или «нейросетевой» вид самого материала."""

PROMPTS = {"broll": PROMPT, "final_frame": FINAL_FRAME_PROMPT}


def prompt_for(kind: str, *, intent: str, role: str, query: str) -> str:
    """Текст запроса судье под задачу. Неизвестная задача — прежний вопрос."""
    return PROMPTS.get(kind, PROMPT).format(intent=intent, role=role, query=query)


class VisionProvider(Provider):
    def judge(self, frames: Sequence[Path], *, intent: str, role: str,
              query: str, kind: str = "broll") -> VisionVerdict:
        """``kind`` выбирает вопрос: отбор материала или кадр готового ролика."""
        raise NotImplementedError


# --- mock ---------------------------------------------------------------------

class MockVision(VisionProvider):
    """Оценка по измеримым свойствам кадра — детерминированная и осмысленная."""

    def __init__(self, cfg, costs, *, judge_name: str = "gemini") -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.MOCK, name=judge_name)
        self.judge_name = judge_name

    def judge(self, frames: Sequence[Path], *, intent: str, role: str,
              query: str, kind: str = "broll") -> VisionVerdict:
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
        # Плотность краёв на кадре готового ролика поднимает наш собственный
        # субтитр, а не чужая подпись. Спрашивают здесь про чужую — значит и
        # мерить надо без оформления канала.
        has_text = bool(kind != "final_frame"
                        and np.mean([s["edge_density"] for s in stats]) > 0.34
                        and seed % 5 == 0)
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
              query: str, kind: str = "broll") -> VisionVerdict:
        import requests

        primary = str(self.cfg.get("vision.gemini_model", "gemini-3.8-flash"))
        spare = str(self.cfg.get("vision.gemini_model_fallback", "")).strip()
        models = [primary]
        if spare and spare != primary:
            models.append(spare)

        base = str(self.cfg.get("vision.gemini_api_base",
                                "https://generativelanguage.googleapis.com"))
        parts: list[dict[str, Any]] = [
            {"text": prompt_for(kind, intent=intent, role=role, query=query)}]
        for frame in frames:
            parts.append({"inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(frame.read_bytes()).decode("ascii"),
            }})

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }

        last_exc: ProviderError | None = None
        data: dict[str, Any] | None = None
        model = primary
        for model in models:
            url = f"{base}/v1beta/models/{model}:generateContent"

            def _call(url=url, model=model) -> dict[str, Any]:
                resp = requests.post(url, params={"key": self.api_key}, json=payload,
                                     timeout=self._timeout())
                if resp.status_code >= 400:
                    raise ProviderError(f"Gemini вернул {resp.status_code}",
                                        status=resp.status_code, body=resp.text[:300],
                                        model=model)
                return resp.json()

            try:
                data = call_with_retry(_call, **self._retry_kwargs("Gemini vision"))
                break
            except ProviderError as exc:
                last_exc = exc
                if not is_capacity_error(exc) or model == models[-1]:
                    raise
                _log.warning(
                    "Gemini vision 503/high demand — пробую следующий Flash",
                    extra={"model": model, "fallback": models[-1],
                           "err": str(exc)[:200]},
                )

        if data is None:
            assert last_exc is not None
            raise last_exc

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
              query: str, kind: str = "broll") -> VisionVerdict:
        import requests

        model = str(self.cfg.get("vision.grok_model", "grok-4-fast"))
        base = str(self.cfg.get("vision.grok_api_base", "https://api.x.ai"))
        content: list[dict[str, Any]] = [
            {"type": "text",
             "text": prompt_for(kind, intent=intent, role=role, query=query)}]
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


def _gemini_api_key(cfg) -> str | None:
    """GEMINI_API_KEY из конфига, иначе распространённые алиасы Google AI Studio."""
    key = cfg.secret_for("vision.gemini_api_key_env", purpose="Gemini Vision")
    if key:
        return key
    for env_name in ("GOOGLE_API_KEY", "GOOGLE_AI_API_KEY"):
        key = cfg.secret(env_name, purpose="Gemini Vision")
        if key:
            return key
    return None


def _provider_http_status(exc: BaseException) -> int | None:
    status = getattr(exc, "details", None) or {}
    if isinstance(status, dict) and status.get("status") is not None:
        try:
            return int(status["status"])
        except (TypeError, ValueError):
            return None
    return None


def _credits_or_auth_failure(exc: BaseException) -> bool:
    """403/402/401 и тексты про credits / spending limit — повод сменить провайдера."""
    status = _provider_http_status(exc)
    if status in (401, 402, 403):
        return True
    text = str(exc).lower()
    return any(token in text for token in (
        "credit", "credits", "spending limit", "quota", "insufficient",
        "billing", "payment required",
    ))


def _live_vision(cfg, costs, name: str) -> VisionProvider | None:
    # Нет ключа → None (следующий в цепочке), даже при providers.mode=live.
    # Иначе временный primary=gemini валил бы весь прогон при пустом GEMINI_API_KEY.
    if name == "gemini":
        key = _gemini_api_key(cfg)
        if not key:
            return None
        if resolve_mode(cfg, api_key=key, service="gemini") is ProviderMode.LIVE:
            return GeminiVision(cfg, costs, key)
        return None
    if name == "grok":
        key = cfg.secret_for("vision.grok_api_key_env", purpose="Grok Vision")
        if not key:
            return None
        if resolve_mode(cfg, api_key=key, service="grok") is ProviderMode.LIVE:
            return GrokVision(cfg, costs, key)
        return None
    return None


class FallbackVision(VisionProvider):
    """Основной судья + запасной при 401/402/403 / исчерпанных кредитах."""

    def __init__(self, cfg, costs, primary: VisionProvider, secondary: VisionProvider) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE,
                         name=f"{primary.name}+{secondary.name}")
        self.primary = primary
        self.secondary = secondary

    def judge(self, frames: Sequence[Path], *, intent: str, role: str,
              query: str, kind: str = "broll") -> VisionVerdict:
        try:
            return self.primary.judge(frames, intent=intent, role=role,
                                      query=query, kind=kind)
        except ProviderError as exc:
            if not _credits_or_auth_failure(exc):
                raise
            _log.warning("vision primary отказал — запасной судья",
                         extra={"primary": self.primary.name,
                                "fallback": self.secondary.name,
                                "err": str(exc)[:200]})
            return self.secondary.judge(frames, intent=intent, role=role,
                                        query=query, kind=kind)


def build_vision_provider(cfg, costs, *, role: str = "primary") -> VisionProvider:
    """Судья для роли из ``vision.primary`` / ``vision.arbiter``.

    Временно (XAI без кредитов) конфиг может ставить Gemini первым; ``vision.fallback``
    держит Grok на случай, если Gemini-ключ ещё не заведён в Actions. При 403/402
    по кредитам вызывается запасной live-судья, а не mock.
    """
    preferred = str(cfg.get(f"vision.{role}", "gemini")).lower()
    fallback = str(cfg.get("vision.fallback", "grok")).lower()
    order: list[str] = []
    for name in (preferred, fallback, "gemini", "grok"):
        if name and name not in order and name != "mock":
            order.append(name)

    live: list[VisionProvider] = []
    for name in order:
        provider = _live_vision(cfg, costs, name)
        if provider is not None:
            live.append(provider)

    if len(live) >= 2:
        return FallbackVision(cfg, costs, live[0], live[1])
    if len(live) == 1:
        return live[0]
    return MockVision(cfg, costs, judge_name=preferred or "gemini")
