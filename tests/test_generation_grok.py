"""Пустые слоты закрываются кадром Grok, а движение делает ffmpeg.

Magnific из генерации выведен: HTTP-эндпоинт отвечает 404, а MCP-путь живёт в
чате, а не в Actions, и списывает кредиты. Видео у Grok не заказывается вовсе —
слот закрывается статичным кадром с наездом, тем же приёмом Ken Burns, которым
оживляются фотослоты стока.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.ffmpeg import probe
from src.lib.providers.generation import (
    GrokImageGeneration, MockGeneration, build_generation_provider,
)


def _png_b64(width: int = 1024, height: int = 1024) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (18, 18, 22)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return ""


@pytest.fixture
def cfg():
    return load_config()


def test_still_becomes_a_clip_of_the_requested_length(cfg, tmp_path, monkeypatch):
    """P9 просит видео, и получить он обязан видео — нужного размера и длины."""
    import requests

    payload = {"data": [{"b64_json": _png_b64()}]}
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(payload))

    provider = GrokImageGeneration(cfg, CostLedger(video_id="t"), "ключ")
    asset = provider.generate("чёрная дыра, вертикальный кадр",
                              tmp_path / "slot_00.mp4",
                              kind="video", duration_sec=3.0)

    info = probe(asset.path)
    assert (info.width, info.height) == tuple(cfg.resolution), "кадр не 1080×1920"
    assert abs(info.duration_sec - 3.0) < 0.2, f"длительность {info.duration_sec}"
    assert asset.to_dict()["ai_generated"] is True, "AI-материал обязан быть помечен"
    assert not asset.path.with_suffix(".src.png").exists(), "исходный кадр не убран"


def test_movement_is_real_not_a_freeze(cfg, tmp_path, monkeypatch):
    """Наезд обязан быть виден: §H7 — всё приближается, ничего не включается.

    Кадр заливки одноцветный, поэтому движение проверяется не по пикселям, а по
    тому, что клип собран как последовательность, а не как один кадр: у зависшей
    картинки все кадры идентичны и битрейт вырождается.
    """
    import requests

    # Картинка с деталями, иначе кодек сожмёт статику до неразличимости.
    buf = io.BytesIO()
    image = Image.new("RGB", (1024, 1024))
    for x in range(1024):
        for y in range(0, 1024, 8):
            image.putpixel((x, y), ((x * 7) % 255, (y * 3) % 255, 90))
    image.save(buf, format="PNG")
    payload = {"data": [{"b64_json": base64.b64encode(buf.getvalue()).decode()}]}
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(payload))

    provider = GrokImageGeneration(cfg, CostLedger(video_id="t"), "ключ")
    asset = provider.generate("звёздное поле", tmp_path / "slot_01.mp4",
                              kind="video", duration_sec=2.0)

    from src.lib.ffmpeg import extract_frames
    from src.lib.phash import phash_image

    frames = extract_frames(asset.path, tmp_path / "frames", [0.05, 0.95])
    assert phash_image(frames[0]) != phash_image(frames[1]), \
        "первый и последний кадр совпали — наезда нет"


def test_grok_is_the_generation_source(cfg, costs=None, **_):
    """Источник генерации берётся из конфига, а не из наличия ключа Magnific."""
    assert str(cfg.get("generation.source")).lower() == "grok"


def test_without_a_key_generation_falls_back_to_mock(cfg, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg.set("providers.mode", "auto")
    provider = build_generation_provider(cfg, CostLedger(video_id="t"))
    assert isinstance(provider, MockGeneration)
