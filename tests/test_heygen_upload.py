"""HeyGen upload: MIME файла, не отказ ключа.

Прогон 34493460154: ключ принят, 400543 «audio/wav != audio/x-wav».
Это чинится заголовком, а не MCP и не новой озвучкой.
"""

from __future__ import annotations

import json

import numpy as np

from src.errors import ProviderError
from src.lib import audio as A
from src.lib.config import load_config
from src.lib.costs import CostLedger
from src.lib.providers.avatar import (
    HEYGEN_AUDIO_CONTENT_TYPE,
    HeyGenAvatar,
    heygen_sniffed_audio_type,
)


def test_heygen_sniffed_type_parses_400543():
    body = '{"code":400543,"message":"Content type not match audio/wav != audio/x-wav"}\\n'
    assert heygen_sniffed_audio_type(body) == "audio/x-wav"


def test_heygen_upload_sends_x_wav(monkeypatch, tmp_path):
    wav = tmp_path / "seg.wav"
    A.save_wav(wav, np.zeros(4800, dtype=np.float32), 48000)
    seen: list[str] = []

    class _Resp:
        status_code = 200
        text = '{"data":{"url":"https://cdn.example/a.wav"}}'

        def json(self):
            return {"data": {"url": "https://cdn.example/a.wav"}}

    def _post(url, data=None, headers=None, timeout=None):
        seen.append(headers["Content-Type"])
        return _Resp()

    monkeypatch.setattr("requests.post", _post)
    cfg = load_config()
    cfg.set("providers.retries", 1)
    cfg.set("providers.capacity_retries", 1)
    got = HeyGenAvatar(cfg, CostLedger(video_id="t"), "test-key")._upload_audio(wav)
    assert got == "https://cdn.example/a.wav"
    assert seen == [HEYGEN_AUDIO_CONTENT_TYPE]
    assert seen[0] == "audio/x-wav"


def test_heygen_upload_retries_with_sniffed_type(monkeypatch, tmp_path):
    wav = tmp_path / "seg.wav"
    A.save_wav(wav, np.zeros(4800, dtype=np.float32), 48000)
    seen: list[str] = []

    class _Resp:
        def __init__(self, status, payload):
            self.status_code = status
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    def _post(url, data=None, headers=None, timeout=None):
        ctype = headers["Content-Type"]
        seen.append(ctype)
        if ctype == "audio/x-wav":
            return _Resp(400, {
                "code": 400543,
                "message": "Content type not match audio/x-wav != audio/wav",
            })
        return _Resp(200, {"data": {"url": "https://cdn.example/b.wav"}})

    monkeypatch.setattr("requests.post", _post)
    cfg = load_config()
    cfg.set("providers.retries", 1)
    cfg.set("providers.capacity_retries", 1)
    got = HeyGenAvatar(cfg, CostLedger(video_id="t"), "test-key")._upload_audio(wav)
    assert got == "https://cdn.example/b.wav"
    assert seen == ["audio/x-wav", "audio/wav"]


def test_heygen_upload_true_failure_still_raises(monkeypatch, tmp_path):
    wav = tmp_path / "seg.wav"
    A.save_wav(wav, np.zeros(4800, dtype=np.float32), 48000)

    class _Resp:
        status_code = 500
        text = "boom"

        def json(self):
            return {}

    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp())
    cfg = load_config()
    cfg.set("providers.retries", 1)
    cfg.set("providers.capacity_retries", 1)
    try:
        HeyGenAvatar(cfg, CostLedger(video_id="t"), "test-key")._upload_audio(wav)
    except ProviderError as exc:
        assert "500" in str(exc)
    else:
        raise AssertionError("expected ProviderError")
