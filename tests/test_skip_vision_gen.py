"""vision.skip_live + generation.skip — без live API / image gen."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.lib.config import load_config


def test_skip_flags_default_off():
    cfg = load_config()
    assert cfg.get("vision.skip_live") is False
    assert cfg.get("generation.skip") is False


def test_skip_flags_cli_override():
    cfg = load_config(overrides=["vision.skip_live=true", "generation.skip=true"])
    assert cfg.get("vision.skip_live") is True
    assert cfg.get("generation.skip") is True


def test_vision_qc_skip_live_short_circuits(tmp_path, monkeypatch):
    """P12 semantic QC must not call Gemini/Grok when vision.skip_live."""
    from src.p12_render_qc import vision_qc as VQ

    called = {"build": 0}

    def _boom(*_a, **_k):
        called["build"] += 1
        raise AssertionError("build_vision_provider must not run under skip_live")

    monkeypatch.setattr(VQ, "build_vision_provider", _boom)
    monkeypatch.setattr(
        VQ, "extract_frames",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("extract_frames")),
    )

    cfg = load_config(overrides=["vision.skip_live=true"])
    ctx = MagicMock()
    ctx.cfg = cfg
    ctx.costs = MagicMock()
    ctx.warn = MagicMock()
    ctx.wpath = lambda *a: tmp_path.joinpath(*map(str, a))

    report = VQ.run_vision_qc(
        ctx, video_path=tmp_path / "v.mp4",
        plan={"duration_sec": 10, "variant": "B", "shots": [], "subtitles": []},
    )
    assert report["enabled"] is False
    assert report.get("skipped") is True
    assert report["blocking"] is False
    assert called["build"] == 0


def test_vision_qc_provider_error_is_non_blocking(tmp_path, monkeypatch):
    """§11.2 never hard-fails the job on 429/403 provider errors."""
    from src.errors import ProviderError
    from src.p12_render_qc import vision_qc as VQ

    class _Boom:
        def judge(self, *_a, **_k):
            raise ProviderError("Grok вернул 403", status=403)

    monkeypatch.setattr(VQ, "build_vision_provider", lambda *_a, **_k: _Boom())
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"x")
    monkeypatch.setattr(VQ, "extract_frames", lambda *_a, **_k: [frame] * VQ.SAMPLES)

    cfg = load_config()
    ctx = MagicMock()
    ctx.cfg = cfg
    ctx.costs = MagicMock()
    ctx.warn = MagicMock()
    ctx.wpath = lambda *a: tmp_path.joinpath(*map(str, a))

    report = VQ.run_vision_qc(
        ctx, video_path=tmp_path / "v.mp4",
        plan={"duration_sec": 12, "variant": "B",
              "shots": [{"index": 0, "start": 0.0, "end": 12.0, "kind": "avatar",
                         "role": "hook", "reason": "x"}],
              "subtitles": []},
    )
    assert report.get("provider_error") or report.get("skipped")
    assert report["blocking"] is False
    assert report["picture_matches_speech"] is True
    ctx.warn.assert_called()


def test_thumbnail_skip_generate_goes_straight_to_ffmpeg(tmp_path, monkeypatch):
    """generation.skip: never call gemini_image/grok_image for thumbs."""
    from src.lib.ffmpeg import run as ffmpeg_run
    from src.p12_render_qc.render import make_shorts_thumbnail

    called = {"build": 0}

    def _boom(*_a, **_k):
        called["build"] += 1
        raise AssertionError("build_generation_provider must not run under generation.skip")

    monkeypatch.setattr(
        "src.p12_render_qc.render.build_generation_provider", _boom)

    src = tmp_path / "clip.mp4"
    ffmpeg_run([
        "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src),
    ], what="thumb fixture")
    thumb = tmp_path / "thumbnail.jpg"

    cfg = load_config(overrides=["generation.skip=true"])
    cfg.data.setdefault("render", {})["thumbnail_mode"] = "auto"
    ctx = MagicMock()
    ctx.cfg = cfg
    ctx.costs = MagicMock()

    meta = make_shorts_thumbnail(
        ctx, out_file=src, thumb=thumb,
        plan={"video_id": "t", "meta": {"title": "Test"}},
        script={"meta": {"title": "Test", "topic": "quantum"}},
        variant="A",
    )
    assert called["build"] == 0
    assert meta["mode"] == "ffmpeg"
    assert meta.get("skipped_ai") is True
    assert thumb.exists() and thumb.stat().st_size > 500


def test_thumbnail_skip_vision_also_forces_ffmpeg(tmp_path, monkeypatch):
    from src.lib.ffmpeg import run as ffmpeg_run
    from src.p12_render_qc.render import make_shorts_thumbnail

    called = {"build": 0}

    def _count(*_a, **_k):
        called["build"] += 1
        raise AssertionError("no image API")

    monkeypatch.setattr(
        "src.p12_render_qc.render.build_generation_provider", _count)

    src = tmp_path / "clip.mp4"
    ffmpeg_run([
        "-y", "-f", "lavfi", "-i", "color=c=red:s=1080x1920:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src),
    ], what="thumb fixture")
    thumb = tmp_path / "thumbnail_B.jpg"

    cfg = load_config(overrides=["vision.skip_live=true"])
    cfg.data.setdefault("render", {})["thumbnail_mode"] = "auto"
    ctx = MagicMock()
    ctx.cfg = cfg
    ctx.costs = MagicMock()

    meta = make_shorts_thumbnail(
        ctx, out_file=src, thumb=thumb,
        plan={"video_id": "t"}, script={"meta": {"title": "X"}},
        variant="B",
    )
    assert called["build"] == 0
    assert meta["mode"] == "ffmpeg"
    assert thumb.exists()
