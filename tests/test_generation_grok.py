"""Пустые слоты закрываются кадром Grok, а движение делает ffmpeg.

Magnific из генерации выведен: HTTP-эндпоинт отвечает 404, а MCP-путь живёт в
чате, а не в Actions, и списывает кредиты. Видео у Grok не заказывается вовсе —
слот закрывается статичным кадром с наездом, тем же приёмом Ken Burns, которым
оживляются фотослоты стока.
"""

from __future__ import annotations

import base64
import io
import json

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


def test_prompt_asks_for_a_photograph_not_an_illustration():
    """Заказчик просил, чтобы кадр не читался как AI-генерация.

    Узнаётся она по «нарисованности»: 3D-рендер, иллюстрация, глянец без
    единой случайной детали. Промпт поэтому просит фотографию — камеру, оптику,
    зерно — и прямо запрещает рендер.
    """
    from src.p9_generate.generate import _prompt_for_slot

    slot = {"index": 4, "role": "develop", "duration": 3.0,
            "visual_intent": "буровая колонна в стволе скважины",
            "queries": ["deep borehole drill string"]}
    plan = {"category": "science", "title": "Кольская сверхглубокая", "blocks": []}
    prompt = _prompt_for_slot(slot, plan).lower()

    for asked in ("photographic", "35mm", "film grain"):
        assert asked in prompt
    for banned in ("no illustration", "no 3d render", "no cgi", "no text", "no logos"):
        assert banned in prompt


def _run_generation(tmp_path, monkeypatch, cfg):
    """Прогнать P9 на одном пустом слоте с мок-генератором."""
    import json

    from src.lib.cache import StepCache
    from src.lib.storage import build_storage
    from src.pipeline import RunContext
    from src.p9_generate import generate as G

    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    plan = {"video_id": "redshift_0099", "duration_sec": 30.0,
            "slots": [{"index": 3, "kind": "footage", "asset_role": "broll",
                       "role": "develop", "duration": 3.0, "block_id": "b1",
                       "queries": ["granite fracture macro"],
                       "visual_intent": "Трещиноватый гранит крупным планом"}]}
    (work / "cut_plan.json").write_text(json.dumps(plan, ensure_ascii=False),
                                        encoding="utf-8")
    (work / "accepted_assets.json").write_text(
        json.dumps({"accepted": {}, "unfilled_slots": [3]}), encoding="utf-8")

    cfg.set("providers.mode", "mock")
    cfg.set("paths.storage_dir", str(tmp_path / "storage"))
    cfg.set("paths.cache_dir", str(tmp_path / "cache"))
    ctx = RunContext(video_id="redshift_0099", cfg=cfg, work_dir=work,
                     output_dir=tmp_path / "out", script_path=tmp_path / "s.json",
                     cache=StepCache(work), costs=CostLedger(video_id="redshift_0099"),
                     storage=build_storage(cfg))
    (tmp_path / "out").mkdir(exist_ok=True)
    return G.run_step(ctx)


def test_a_generated_frame_faces_the_same_critic_as_stock(tmp_path, monkeypatch, cfg):
    """Генерация проверялась только на дубль — то есть ни на что.

    «Материал сделан под слот, релевантность гарантирована» — так и было
    записано в коде, и на 0047 из этого вышел раскалённый камень в пустыне
    вместо трещиноватого гранита, а доля AI-материала дошла до 34 %. Модель
    рисует по промпту, а не по смыслу блока, и увидеть разницу можно только
    взглядом. Слабый кадр отправляется на пересборку, а не в монтаж.
    """
    from src.lib.providers.vision import VisionVerdict
    from src.p9_generate import generate as G

    scores = iter([0.20, 0.80])
    seen: list[float] = []

    class _Critic:
        def judge(self, frames, *, intent, role, query, kind="broll"):
            score = next(scores, 0.9)
            seen.append(score)
            return VisionVerdict(score=score, reason="проба", summary="кадр",
                                 judge="critic")

    monkeypatch.setattr(G, "build_vision_provider", lambda *a, **k: _Critic())
    _run_generation(tmp_path, monkeypatch, cfg)

    # Первая попытка забракована, вторая принята — и её оценка ушла в паспорт.
    assert seen == [0.20, 0.80]
    doc = json.loads((tmp_path / "work" / "generated_assets.json").read_text("utf-8"))
    entry = next(iter(doc["generated"].values()))
    assert entry["score"] == 0.80
    assert entry["verdict"]["judge"] == "critic"


def test_a_hopeless_slot_stays_empty_instead_of_taking_a_weak_frame(
        tmp_path, monkeypatch, cfg):
    """Пустой слот честнее плохого кадра: его видно в отчёте, кадр — только зрителю."""
    from src.lib.providers.vision import VisionVerdict
    from src.p9_generate import generate as G

    class _Critic:
        def judge(self, frames, *, intent, role, query, kind="broll"):
            return VisionVerdict(score=0.1, reason="не про то", summary="пятно",
                                 judge="critic")

    monkeypatch.setattr(G, "build_vision_provider", lambda *a, **k: _Critic())
    report = _run_generation(tmp_path, monkeypatch, cfg)

    assert report["generated"] == 0
    doc = json.loads((tmp_path / "work" / "generated_assets.json").read_text("utf-8"))
    assert doc["generated"] == {}
    assert "судья" in doc["skipped"][0]["reason"]
