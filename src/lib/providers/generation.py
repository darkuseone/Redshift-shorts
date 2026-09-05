"""Генерация недостающего материала (§7.2 «Абстрактные data-виз», P9, §7.7 VFX).

Live — Magnific: эндпоинты вынесены в конфиг (``magnific.endpoints``), потому что
маршруты и имена моделей у сервиса меняются чаще, чем код пайплайна; менять их
правкой YAML безопаснее, чем правкой модуля.

Mock — генерация фирменного абстрактного клипа средствами ffmpeg в цветах
брендбука. Материал честно помечается ``ai_generated``, чтобы QC-14 считал долю
AI-футажа по фактам, а не по намерениям.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...errors import ProviderError
from ..ffmpeg import run
from ..logging import get_logger
from ..retry import call_with_retry, is_capacity_error
from .base import Provider, ProviderMode, resolve_mode

# Типы градиента фильтра ffmpeg ``gradients`` в порядке предпочтения. Набор
# зависит от сборки: в imageio-ffmpeg 7.0 их пять, в ubuntu-сборке CI — четыре,
# а ``conical`` из документации другой версии не существует нигде и стоил
# провала P9 на четвёртом ролике. Поэтому список — только пожелание, а
# фактический набор берётся у самого ffmpeg.
GRADIENT_TYPES = ("linear", "radial", "circular", "spiral", "square")


@lru_cache(maxsize=1)
def supported_gradient_types() -> tuple[str, ...]:
    """Типы градиента, которые понимает установленная сборка ffmpeg."""
    import subprocess

    from ..ffmpeg import ffmpeg_bin

    try:
        out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-h", "filter=gradients"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ("linear",)
    found = tuple(name for name in GRADIENT_TYPES
                  if re.search(rf"^\s+{name}\s+\d+\s", out, re.MULTILINE))
    # ``linear`` — значение по умолчанию самого фильтра: если разобрать справку
    # не удалось, лучше один рабочий тип, чем падение в середине прогона.
    return found or ("linear",)

_log = get_logger("generation")


@dataclass
class GeneratedAsset:
    id: str
    path: Path
    kind: str                      # video | photo
    prompt: str
    model: str
    duration_sec: float = 0.0
    width: int = 1080
    height: int = 1920
    paid_model: bool = False
    mock: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "path": str(self.path), "kind": self.kind,
            "prompt": self.prompt, "model": self.model,
            "duration_sec": round(self.duration_sec, 2),
            "width": self.width, "height": self.height,
            "paid_model": self.paid_model, "mock": self.mock,
            "license": "generated-owned", "ai_generated": True,
        }


class GenerationProvider(Provider):
    def generate(self, prompt: str, dst: Path, *, kind: str = "video",
                 duration_sec: float = 4.0, prefer_free: bool = True) -> GeneratedAsset:
        raise NotImplementedError


class MockGeneration(GenerationProvider):
    """Фирменный абстрактный B-roll: градиент брендбука + мягкое движение."""

    def __init__(self, cfg, costs) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.MOCK, name="magnific")

    def generate(self, prompt: str, dst: Path, *, kind: str = "video",
                 duration_sec: float = 4.0, prefer_free: bool = True) -> GeneratedAsset:
        seed = int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)
        width, height = self.cfg.resolution
        palette = [str(self.cfg.color(name)).lstrip("#")
                   for name in ("accent", "accent_deep", "ink", "accent_soft", "muted")]
        c0 = palette[seed % len(palette)]
        # Второй цвет обязан отличаться от первого. Раньше он брался
        # независимо, и на пятицветной палитре пара нет-нет да совпадала —
        # градиент вырождался в заливку.
        c1 = palette[(seed % len(palette) + 1 + (seed // 7) % (len(palette) - 1))
                     % len(palette)]
        # Разные промпты обязаны давать визуально разный кадр: одинаковый
        # градиент — это готовый дубль, который завалит QC-5.
        types = supported_gradient_types()
        gradient_type = types[seed % len(types)]

        dst.parent.mkdir(parents=True, exist_ok=True)
        source = (f"gradients=s={width}x{height}:c0=0x{c0}:c1=0x{c1}"
                  f":x0={seed % max(width, 1)}:y0={(seed // 3) % max(height, 1)}"
                  f":speed={0.008 + (seed % 9) / 500.0:.4f}"
                  f":d={duration_sec:.2f}:type={gradient_type}")
        # Поворот — единственная часть картинки, которая различает кадры при
        # любой сборке ffmpeg. Типов градиента у сборки может оказаться и один:
        # ``supported_gradient_types`` разбирает справку фильтра, и если разбор
        # не удался, остаётся ``linear``. На CI так и вышло — три промпта дали
        # один тип, пара цветов у двух совпала, и перцептивные хэши разошлись
        # ровно на 8 бит при пороге «больше 8». Локально было 30–38: сборка
        # знала четыре типа, и разница бралась оттуда. Угол же зависит только
        # от семени и меняет саму геометрию кадра, а не палитру, — его видит
        # и хэш, считающий по яркости.
        angle = (seed % 360) * 3.14159265 / 180.0
        chain = f"rotate=a={angle:.4f}:c=0x{c0}:ow=iw:oh=ih"
        if kind == "photo":
            run(["-y", "-f", "lavfi", "-i", source, "-vf", chain,
                 "-frames:v", "1", str(dst)],
                what="mock generation photo")
        else:
            run(["-y", "-f", "lavfi", "-i", source, "-vf", chain,
                 "-t", f"{duration_sec:.2f}",
                 "-r", str(self.cfg.fps), "-c:v", "libx264", "-preset", "ultrafast",
                 "-crf", "30", "-g", "30", "-pix_fmt", "yuv420p", str(dst)],
                what="mock generation video")

        price_key = "magnific_per_video_sec" if kind == "video" else "magnific_per_image"
        units = duration_sec if kind == "video" else 1
        self.charge("generate", units, "sec" if kind == "video" else "image",
                    units * float(self.cfg.get(f"budget.price.{price_key}", 0.08)))
        return GeneratedAsset(
            id=f"gen_mock_{seed:08x}", path=dst, kind=kind, prompt=prompt,
            model="mock-gradient-v1", duration_sec=duration_sec,
            width=width, height=height, paid_model=False, mock=True,
        )


class MagnificGeneration(GenerationProvider):
    def __init__(self, cfg, costs, api_key: str) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="magnific")
        self.api_key = api_key

    def generate(self, prompt: str, dst: Path, *, kind: str = "video",
                 duration_sec: float = 4.0, prefer_free: bool = True) -> GeneratedAsset:
        import requests

        base = str(self.cfg.get("magnific.api_base", "https://api.magnific.ai"))
        endpoints = self.cfg.get("magnific.endpoints", {}) or {}
        path = endpoints.get("video" if kind == "video" else "image",
                             "/v1/video/generate" if kind == "video" else "/v1/image/generate")
        models = self.cfg.get("magnific.models", {}) or {}
        model = models.get(("free_" if prefer_free else "paid_") + kind) or models.get(kind, "")
        width, height = self.cfg.resolution

        payload: dict[str, Any] = {
            "prompt": prompt, "width": width, "height": height,
            "aspect_ratio": "9:16",
        }
        if model:
            payload["model"] = model
        if kind == "video":
            payload["duration"] = round(duration_sec, 2)

        def _call() -> dict[str, Any]:
            resp = requests.post(f"{base}{path}", json=payload,
                                 headers={"Authorization": f"Bearer {self.api_key}"},
                                 timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"Magnific вернул {resp.status_code}",
                                    status=resp.status_code, body=resp.text[:300])
            return resp.json()

        data = call_with_retry(_call, **self._retry_kwargs("Magnific generate"))
        url = _first_url(data)
        if not url:
            raise ProviderError("Magnific не вернул ссылку на результат", keys=list(data)[:10])

        dst.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=self._timeout()) as resp:
            if resp.status_code >= 400:
                raise ProviderError("не удалось скачать результат Magnific",
                                    status=resp.status_code)
            with open(dst, "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    fh.write(chunk)

        price_key = "magnific_per_video_sec" if kind == "video" else "magnific_per_image"
        units = duration_sec if kind == "video" else 1
        self.charge("generate", units, "sec" if kind == "video" else "image",
                    units * float(self.cfg.get(f"budget.price.{price_key}", 0.08)),
                    model=model or "default")
        return GeneratedAsset(
            id=f"gen_{hashlib.sha256(prompt.encode()).hexdigest()[:12]}",
            path=dst, kind=kind, prompt=prompt, model=model or "magnific-default",
            duration_sec=duration_sec, width=width, height=height,
            paid_model=not prefer_free,
        )


def _first_url(data: Any) -> str:
    """Найти первую http-ссылку в ответе произвольной формы."""
    if isinstance(data, str):
        return data if data.startswith("http") else ""
    if isinstance(data, dict):
        for key in ("url", "output_url", "result_url", "video_url", "image_url"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        for value in data.values():
            found = _first_url(value)
            if found:
                return found
    if isinstance(data, list):
        for value in data:
            found = _first_url(value)
            if found:
                return found
    return ""


class GrokImageGeneration(GenerationProvider):
    """Кадр рисует Grok, движение делает ffmpeg.

    Видео у Grok не заказывается вовсе, и это осознанно: слот §7.3 закрывается
    статичным кадром с медленным наездом — тем же приёмом Ken Burns, которым
    оживляются фотослоты стока. Синтетическое видео здесь не нужно, а кадр
    выходит дешевле и предсказуемее.

    Magnific-генерация из этого пути выведена: её HTTP-эндпоинт отдаёт 404, а
    MCP-путь считает кредиты и в живом прогоне Actions недоступен.
    """

    def __init__(self, cfg, costs, api_key: str) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="grok_image")
        self.api_key = api_key

    def _image_bytes(self, prompt: str, model: str) -> bytes:
        import base64

        import requests

        base = str(self.cfg.get("vision.grok_api_base", "https://api.x.ai"))
        # Дополнительные поля запроса — из конфига. Заказчик просит самую
        # качественную модель Imagine, а тарифицируемые режимы у сервиса
        # меняются чаще, чем код: слаг и режим правятся строкой YAML.
        extra = dict(self.cfg.get("generation.grok_image_params", {}) or {})

        def _call() -> bytes:
            resp = requests.post(
                f"{base}/v1/images/generations",
                json={"model": model, "prompt": prompt, "n": 1,
                      "response_format": "b64_json", **extra},
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"Grok image вернул {resp.status_code}",
                                    status=resp.status_code, body=resp.text[:300],
                                    model=model, params=sorted(extra))
            payload = resp.json()
            items = payload.get("data") or []
            if not items:
                raise ProviderError("Grok image не вернул кадр", keys=list(payload)[:10])
            encoded = items[0].get("b64_json")
            if encoded:
                return base64.b64decode(encoded)
            url = _first_url(items[0])
            if not url:
                raise ProviderError("Grok image: ни b64_json, ни ссылки",
                                    keys=list(items[0])[:10])
            got = requests.get(url, timeout=self._timeout())
            if got.status_code >= 400:
                raise ProviderError("не удалось скачать кадр Grok",
                                    status=got.status_code)
            return got.content

        return call_with_retry(_call, **self._retry_kwargs("Grok image"))

    def generate(self, prompt: str, dst: Path, *, kind: str = "video",
                 duration_sec: float = 4.0, prefer_free: bool = True) -> GeneratedAsset:
        model = str(self.cfg.get("generation.grok_image_model", "grok-2-image-1212"))
        width, height = self.cfg.resolution
        dst.parent.mkdir(parents=True, exist_ok=True)

        still = dst.with_suffix(".src.png")
        try:
            still.write_bytes(self._image_bytes(prompt, model))
        except ProviderError as exc:
            # Слаг модели живёт своей жизнью: grok-2-image-1212 вывели из
            # обращения, и прогон встал целиком. Сервис в теле ошибки сам
            # называет замену, но узнать это можно было только по упавшему
            # прогону. Теперь запасная модель берётся из конфига, а промах
            # слага стоит одной строки в логе, а не всего ролика.
            spare = str(self.cfg.get("generation.grok_image_model_fallback", "")).strip()
            if not spare or spare == model:
                raise
            _log.warning("модель генерации не принята — беру запасную",
                         extra={"model": model, "fallback": spare,
                                "reason": str(exc)[:200]})
            still.write_bytes(self._image_bytes(prompt, spare))
            model = spare

        if kind == "photo":
            dst = dst.with_suffix(".png")
            dst.write_bytes(still.read_bytes())
            still.unlink(missing_ok=True)
        else:
            # Наезд, а не статика: §H7 требует, чтобы всё приближалось. Кадр
            # приходит в своей пропорции, поэтому сначала он покрывает вертикаль
            # с запасом, и только потом внутри неё едет масштаб.
            fps = self.cfg.fps
            frames = max(2, int(round(duration_sec * fps)))
            zoom = float(self.cfg.get("generation.ken_burns_zoom", 1.12))
            cover = (f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
                     f"crop={width * 2}:{height * 2}")
            motion = (f"zoompan=z='1+({zoom - 1:.4f})*on/{frames}':d={frames}"
                      f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                      f":s={width}x{height}:fps={fps}")
            run(["-y", "-loop", "1", "-i", str(still), "-t", f"{duration_sec:.2f}",
                 "-vf", f"{cover},{motion},format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-r", str(fps), str(dst)], what="Ken Burns по кадру Grok")
            still.unlink(missing_ok=True)

        self.charge("generate", 1, "image",
                    float(self.cfg.get("budget.price.grok_per_image", 0.02)),
                    model=model)
        return GeneratedAsset(
            id=f"gen_{hashlib.sha256(prompt.encode()).hexdigest()[:12]}",
            path=dst, kind=kind, prompt=prompt, model=model,
            duration_sec=duration_sec if kind == "video" else 0.0,
            width=width, height=height, paid_model=False,
            meta={"still_from": "grok", "motion": "ken_burns"},
        )


def _gemini_api_key(cfg) -> str | None:
    key = cfg.secret_for("vision.gemini_api_key_env", purpose="Gemini (генерация кадров)")
    if key:
        return key
    for env_name in ("GOOGLE_API_KEY", "GOOGLE_AI_API_KEY"):
        key = cfg.secret(env_name, purpose="Gemini (генерация кадров)")
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
    status = _provider_http_status(exc)
    if status in (401, 402, 403):
        return True
    text = str(exc).lower()
    return any(token in text for token in (
        "credit", "credits", "spending limit", "quota", "insufficient",
        "billing", "payment required",
    ))


class GeminiImageGeneration(GenerationProvider):
    """Кадр рисует Gemini Image (Nano Banana), движение — ffmpeg Ken Burns.

    Imagen ``:predict`` на Gemini API снят (август 2026). Актуальный путь —
    ``generateContent`` у моделей ``gemini-*-flash-image`` / ``gemini-*-pro-image``.
    """

    def __init__(self, cfg, costs, api_key: str) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE, name="gemini_image")
        self.api_key = api_key

    def _image_bytes(self, prompt: str, model: str) -> bytes:
        import base64

        import requests

        base = str(self.cfg.get("vision.gemini_api_base",
                                "https://generativelanguage.googleapis.com"))
        url = f"{base}/v1beta/models/{model}:generateContent"
        aspect = str(self.cfg.get("generation.gemini_image_aspect", "9:16"))
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {"aspectRatio": aspect},
            },
        }

        def _call() -> bytes:
            resp = requests.post(url, params={"key": self.api_key}, json=payload,
                                 timeout=self._timeout())
            if resp.status_code >= 400:
                raise ProviderError(f"Gemini image вернул {resp.status_code}",
                                    status=resp.status_code, body=resp.text[:300],
                                    model=model)
            data = resp.json()
            for candidate in data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    inline = part.get("inlineData") or part.get("inline_data") or {}
                    encoded = inline.get("data")
                    if encoded:
                        return base64.b64decode(encoded)
            raise ProviderError("Gemini image не вернул кадр",
                                keys=list(data)[:10], model=model)

        return call_with_retry(_call, **self._retry_kwargs("Gemini image"))

    def generate(self, prompt: str, dst: Path, *, kind: str = "video",
                 duration_sec: float = 4.0, prefer_free: bool = True) -> GeneratedAsset:
        model = str(self.cfg.get("generation.gemini_image_model",
                                 "gemini-3.1-flash-image"))
        width, height = self.cfg.resolution
        dst.parent.mkdir(parents=True, exist_ok=True)

        still = dst.with_suffix(".src.png")
        try:
            still.write_bytes(self._image_bytes(prompt, model))
        except ProviderError as exc:
            spare = str(self.cfg.get("generation.gemini_image_model_fallback", "")).strip()
            if not spare or spare == model:
                raise
            why = ("503/high demand" if is_capacity_error(exc)
                   else "модель не принята")
            _log.warning(f"Gemini image {why} — беру запасную",
                         extra={"model": model, "fallback": spare,
                                "reason": str(exc)[:200]})
            still.write_bytes(self._image_bytes(prompt, spare))
            model = spare

        if kind == "photo":
            dst = dst.with_suffix(".png")
            dst.write_bytes(still.read_bytes())
            still.unlink(missing_ok=True)
        else:
            fps = self.cfg.fps
            frames = max(2, int(round(duration_sec * fps)))
            zoom = float(self.cfg.get("generation.ken_burns_zoom", 1.12))
            cover = (f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
                     f"crop={width * 2}:{height * 2}")
            motion = (f"zoompan=z='1+({zoom - 1:.4f})*on/{frames}':d={frames}"
                      f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                      f":s={width}x{height}:fps={fps}")
            run(["-y", "-loop", "1", "-i", str(still), "-t", f"{duration_sec:.2f}",
                 "-vf", f"{cover},{motion},format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-r", str(fps), str(dst)], what="Ken Burns по кадру Gemini")
            still.unlink(missing_ok=True)

        self.charge("generate", 1, "image",
                    float(self.cfg.get("budget.price.gemini_image", 0.04)),
                    model=model)
        return GeneratedAsset(
            id=f"gen_{hashlib.sha256(prompt.encode()).hexdigest()[:12]}",
            path=dst, kind=kind, prompt=prompt, model=model,
            duration_sec=duration_sec if kind == "video" else 0.0,
            width=width, height=height, paid_model=False,
            meta={"still_from": "gemini", "motion": "ken_burns"},
        )


class FallbackGeneration(GenerationProvider):
    """Основной генератор + запасной при 401/402/403 / исчерпанных кредитах."""

    def __init__(self, cfg, costs, primary: GenerationProvider,
                 secondary: GenerationProvider) -> None:
        super().__init__(cfg=cfg, costs=costs, mode=ProviderMode.LIVE,
                         name=f"{primary.name}+{secondary.name}")
        self.primary = primary
        self.secondary = secondary

    def generate(self, prompt: str, dst: Path, *, kind: str = "video",
                 duration_sec: float = 4.0, prefer_free: bool = True) -> GeneratedAsset:
        try:
            return self.primary.generate(prompt, dst, kind=kind,
                                         duration_sec=duration_sec,
                                         prefer_free=prefer_free)
        except ProviderError as exc:
            if not _credits_or_auth_failure(exc):
                raise
            _log.warning("generation primary отказал — запасной",
                         extra={"primary": self.primary.name,
                                "fallback": self.secondary.name,
                                "err": str(exc)[:200]})
            return self.secondary.generate(prompt, dst, kind=kind,
                                           duration_sec=duration_sec,
                                           prefer_free=prefer_free)


def _live_generation(cfg, costs, source: str) -> GenerationProvider | None:
    if source == "gemini":
        key = _gemini_api_key(cfg)
        if not key:
            return None
        if resolve_mode(cfg, api_key=key, service="gemini") is ProviderMode.LIVE:
            return GeminiImageGeneration(cfg, costs, key)
        return None
    if source == "grok":
        key = cfg.secret_for("vision.grok_api_key_env", purpose="Grok (генерация кадров)")
        if not key:
            return None
        if resolve_mode(cfg, api_key=key, service="grok") is ProviderMode.LIVE:
            return GrokImageGeneration(cfg, costs, key)
        return None
    if source == "magnific":
        key = cfg.secret_for("magnific.api_key_env", purpose="Magnific")
        if not key:
            return None
        if resolve_mode(cfg, api_key=key, service="magnific") is ProviderMode.LIVE:
            return MagnificGeneration(cfg, costs, key)
        return None
    return None


def build_generation_provider(cfg, costs) -> GenerationProvider:
    """Кто закрывает пустые слоты.

    Magnific HTTP-генерация выведена (404). Временно (XAI без кредитов) источник
    — Gemini Image; ``generation.fallback`` держит Grok. При 403/402 по кредитам
    вызывается запасной live-генератор.
    """
    preferred = str(cfg.get("generation.source", "gemini")).lower()
    fallback = str(cfg.get("generation.fallback", "grok")).lower()
    order: list[str] = []
    for name in (preferred, fallback, "gemini", "grok"):
        if name and name not in order and name not in ("mock", "magnific"):
            order.append(name)

    live: list[GenerationProvider] = []
    for name in order:
        provider = _live_generation(cfg, costs, name)
        if provider is not None:
            live.append(provider)

    if len(live) >= 2:
        return FallbackGeneration(cfg, costs, live[0], live[1])
    if len(live) == 1:
        return live[0]
    return MockGeneration(cfg, costs)
