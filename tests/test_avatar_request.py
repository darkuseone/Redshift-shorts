"""Заявка на клипы аватара: фаза 1 обязана назвать всё, чего не хватает.

За клипами ходят вручную, через MCP-коннектор, и каждый заход стоит прогона
Actions. Поэтому заявка должна собираться целиком за один раз: и по сегментам,
для которых клипа нет, и по тем, чей клип не той длины. И то и другое надо
генерировать заново — разница только в том, лежит ли рядом негодный файл.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.errors import RedshiftError
from src.lib import audio as A
from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.providers.avatar import MockAvatar
from src.p6_avatar.avatar import run_step
from src.pipeline import RunContext
from src.lib.cache import StepCache
from src.lib.storage import build_storage


SEGMENTS = ((0.0, 4.0), (6.0, 11.0))


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    cfg = load_config()
    cfg.set("providers.mode", "live")
    cfg.set("heygen.source", "auto")
    cfg.set("heygen.prepared_dir", str(tmp_path / "clips"))
    cfg.set("heygen.prepared_chroma", "")

    work = tmp_path / "work"
    work.mkdir(parents=True)
    sr = 48000
    total = int(sr * 12)
    A.save_wav(work / "voice_final.wav",
               (0.1 * np.sin(np.linspace(0, 400 * 2 * np.pi, total))).astype(np.float32), sr)

    slots = [{"index": i, "start": s, "end": e, "mode": "avatar", "kind": "avatar",
              "block_id": f"b{i}"}
             for i, (s, e) in enumerate(SEGMENTS)]
    (work / "cut_plan.json").write_text(
        json.dumps({"video_id": "redshift_0001", "duration_sec": 12.0, "slots": slots}),
        encoding="utf-8")

    return RunContext(
        video_id="redshift_0001", cfg=cfg, work_dir=work,
        output_dir=tmp_path / "out", script_path=tmp_path / "s.json",
        cache=StepCache(tmp_path / "cache"), costs=CostLedger(video_id="redshift_0001"),
        storage=build_storage(cfg),
    )


def _request(ctx) -> dict:
    return json.loads((ctx.work_dir / "avatar_request.json").read_text(encoding="utf-8"))


def test_every_missing_segment_lands_in_one_request(ctx):
    with pytest.raises(RedshiftError) as exc:
        run_step(ctx)
    assert exc.value.code == "AVATAR_CLIPS_NOT_PREPARED"
    assert [s["index"] for s in _request(ctx)["segments"]] == [0, 1]


def test_clip_of_wrong_length_joins_the_request_instead_of_aborting(ctx):
    """Негодный клип не должен обрывать заявку на первом же сегменте.

    Так и было: расхождение длительности роняло шаг сразу, заявка не
    дописывалась, и, чтобы узнать про остальные куски речи, приходилось удалять
    клипы руками и тратить ещё один прогон.
    """
    clips = ctx.cfg.path("heygen.prepared_dir") / "redshift_0001"
    clips.mkdir(parents=True)
    source = clips / "_src.wav"
    A.save_wav(source, np.zeros(48000 * 2, dtype=np.float32), 48000)
    # Клип на 2 сек там, где речь идёт 4 — расхождение вдвое больше допуска.
    MockAvatar(ctx.cfg, CostLedger(video_id="t")).generate(
        audio_path=source, out_path=clips / "seg_00.mov", duration_sec=2.0, index=0)

    with pytest.raises(RedshiftError) as exc:
        run_step(ctx)
    assert exc.value.code == "AVATAR_CLIPS_NOT_PREPARED"

    segments = _request(ctx)["segments"]
    assert [s["index"] for s in segments] == [0, 1], "второй сегмент потерян"
    assert "длительность" in segments[0].get("reason", ""), \
        "не сказано, почему клип негоден"
    assert "reason" not in segments[1], "у отсутствующего клипа причины быть не должно"


# --- Freepik ------------------------------------------------------------------

class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_freepik_reads_catalogue_durations(monkeypatch, tmp_path):
    """«00:00:05» — это пять секунд, а не повод потерять источник.

    Каталог отдаёт длительность строкой «ЧЧ:ММ:СС». float() на ней бросал
    ValueError, ошибка одного поля уносила весь поиск, и Freepik — первый по
    очереди источник — не дал за живой прогон ни одного кандидата ни по одному
    из запросов. Двенадцать слотов из-за этого ушли в генерацию.
    """
    import requests
    from src.lib.providers.stock import FreepikStock

    payload = {"data": [
        # Вертикаль 1080×1920 — это ровно тот формат, ради которого всё и
        # делается, и отбраковываться он не должен.
        {"id": "1", "duration": "00:00:05", "dimensions": {"width": 1080, "height": 1920}},
        # 4K по короткой стороне — мимо §3.6.1, но выдачу ронять не должен.
        {"id": "2", "duration": "00:00:10", "dimensions": {"width": 2160, "height": 3840}},
        {"id": "3", "duration": "00:01:30", "dimensions": {"width": 1080, "height": 1920}},
    ]}
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(payload))

    cfg = load_config()
    provider = FreepikStock(cfg, CostLedger(video_id="t"), "ключ")
    found = provider.search("чёрная дыра", kind="video", limit=8)

    assert [c.duration_sec for c in found] == [5.0, 90.0], "длительности разобраны неверно"
    assert [c.id for c in found] == ["freepik_1", "freepik_3"], \
        "4K должен быть пропущен, а вертикаль 1080×1920 — оставлена"
    assert all(c.orientation == "portrait" for c in found)
