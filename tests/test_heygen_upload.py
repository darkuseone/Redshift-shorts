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
    heygen_v3_avatar_payload,
    resolve_heygen_look_id,
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


def test_heygen_v3_payload_is_avatar_v_with_audio_url_not_legacy_v2():
    payload = heygen_v3_avatar_payload(
        avatar_id="99ccc74e764947c394cd4ef210960a6f",
        audio_url="https://cdn.example/seg.wav",
        engine="avatar_v",
        motion_prompt="energetic talking-head",
        want_alpha=True,
    )
    assert payload["type"] == "avatar"
    assert payload["engine"] == {"type": "avatar_v"}
    assert payload["audio_url"].endswith(".wav")
    assert payload["output_format"] == "webm"
    assert payload["aspect_ratio"] == "9:16"
    assert payload["motion_prompt"]
    assert "expressiveness" not in payload
    assert "video_inputs" not in payload
    assert "background" not in payload
    assert "script" not in payload
    assert "voice_id" not in payload


AVATAR5_LOOK = "99ccc74e764947c394cd4ef210960a6f"


def test_heygen_look_id_is_locked_avatar5_in_config():
    cfg = load_config()
    assert cfg.get("heygen.avatar_id") == AVATAR5_LOOK
    assert cfg.get("heygen.engine") == "avatar_v"


def test_heygen_look_id_ignores_secret_override(monkeypatch):
    cfg = load_config()

    def _wrong_secret(name, purpose=""):
        return "3799c0f8f9c846468efedc9680eeac6e"

    monkeypatch.setattr(cfg, "secret_for", _wrong_secret)
    assert resolve_heygen_look_id(cfg) == AVATAR5_LOOK


def test_redshift_0049_prepared_avatar_clips_exist():
    from pathlib import Path

    clips = Path("assets/avatar_clips/redshift_0049")
    for index in range(7):
        webm = clips / f"seg_{index:02d}.webm"
        wav = clips / f"seg_{index:02d}.wav"
        assert webm.is_file() and webm.stat().st_size > 0, webm
        assert wav.is_file() and wav.stat().st_size > 0, wav
