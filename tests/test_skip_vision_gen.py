"""vision.skip_live + generation.skip — без live API / image gen."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.lib.config import load_config


def test_skip_flags_default_off():
    cfg = load_config()
    assert cfg.get("vision.skip_live") is False
    assert cfg.get("generation.skip") is False
    assert cfg.get("limits.vision_mismatch_share_max") == 0.10


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
    assert report.get("qc_skipped_semantic") is True
    assert report.get("skipped") is True
    assert report["blocking"] is True
    assert report["picture_matches_speech"] is False
    assert report["mismatch_share"] is None
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
    assert report.get("qc_skipped_semantic") is True
    assert report["blocking"] is True
    assert report["picture_matches_speech"] is False
    ctx.warn.assert_called()


def test_vision_qc_keeps_collected_samples_after_later_429(tmp_path, monkeypatch):
    """429 на хвосте не выкидывает уже измеренные пробы (0042: 5/6, потом skip)."""
    from src.errors import ProviderError
    from src.lib.providers import vision as V
    from src.p12_render_qc import vision_qc as VQ
    from src.p12_render_qc.qc import apply_semantic_qc

    calls = {"n": 0}

    class _Partial:
        def judge(self, *_a, **_k):
            calls["n"] += 1
            if calls["n"] > 5:
                raise ProviderError("Gemini вернул 429", status=429)
            return V.VisionVerdict(score=0.9, reason="ok", summary="кадр",
                                   judge="spy")

    monkeypatch.setattr(VQ, "build_vision_provider", lambda *_a, **_k: _Partial())
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"x")
    monkeypatch.setattr(VQ, "extract_frames", lambda *_a, **_k: [frame] * VQ.SAMPLES)
    keys = iter(f"k{i}" for i in range(VQ.SAMPLES))
    monkeypatch.setattr(VQ, "_verdict_key", lambda *_a, **_k: next(keys))

    cfg = load_config()
    ctx = MagicMock()
    ctx.cfg = cfg
    ctx.costs = MagicMock()
    ctx.warn = MagicMock()
    ctx.work_dir = tmp_path
    ctx.wpath = lambda *a: tmp_path.joinpath(*map(str, a))

    vision = VQ.run_vision_qc(
        ctx, video_path=tmp_path / "v.mp4",
        plan={"duration_sec": 12, "variant": "A",
              "shots": [{"index": 0, "start": 0.0, "end": 12.0, "kind": "avatar",
                         "role": "hook", "reason": "x"}],
              "subtitles": []},
    )
    assert vision.get("qc_skipped_semantic") is not True
    assert vision["sample_count"] == 5
    assert vision["mismatch_share"] == 0.0
    assert vision["blocking"] is False
    qc = apply_semantic_qc({"checks": [], "failed": [], "passed": True}, vision)
    assert all(c["passed"] for c in qc["checks"] if c["id"] == "QC-SEMANTIC")


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


# --- Q3.10: дедуп смыслового QC по вариантам (§11.3) -------------------------

class TestTheJudgeIsNotAskedTheSameQuestionTwice:
    """Версии A и B расходятся шестью шаблонами из двадцати кадров.

    Значит часть проб B — это те же кадры под ту же речь, и второй платный
    вызов по ним ничего не узнаёт. Замер на отрендеренном 0042: три кадра из
    шести совпадают побитово — экономия три вызова из двенадцати.
    """

    def test_the_same_frame_and_the_same_speech_give_the_same_key(self, tmp_path):
        from PIL import Image

        from src.p12_render_qc.vision_qc import _verdict_key

        frame = tmp_path / "f.png"
        Image.new("RGB", (32, 32), (10, 20, 30)).save(frame)
        a = _verdict_key(frame, role="body", spoken="речь", intent="кадр")
        b = _verdict_key(frame, role="body", spoken="речь", intent="кадр")
        assert a == b and a

    def test_a_different_frame_gives_a_different_key(self, tmp_path):
        from PIL import Image

        from src.p12_render_qc.vision_qc import _verdict_key

        one, two = tmp_path / "a.png", tmp_path / "b.png"
        Image.new("RGB", (32, 32), (10, 20, 30)).save(one)
        # Полоса вертикальная, а не горизонтальная: dHash сравнивает соседей
        # по строке, и горизонтальная линия его вообще не сдвигает.
        img = Image.new("RGB", (32, 32), (10, 20, 30))
        for y in range(32):
            for x in range(16):
                img.putpixel((x, y), (250, 250, 250))
        img.save(two)
        assert _verdict_key(one, role="body", spoken="речь", intent="кадр") != \
            _verdict_key(two, role="body", spoken="речь", intent="кадр")

    def test_the_same_frame_under_different_speech_is_a_different_question(self, tmp_path):
        from PIL import Image

        from src.p12_render_qc.vision_qc import _verdict_key

        frame = tmp_path / "f.png"
        Image.new("RGB", (32, 32), (10, 20, 30)).save(frame)
        assert _verdict_key(frame, role="body", spoken="одно", intent="кадр") != \
            _verdict_key(frame, role="body", spoken="другое", intent="кадр")

    def test_an_unreadable_frame_disables_caching_rather_than_guessing(self, tmp_path):
        from src.p12_render_qc.vision_qc import _verdict_key

        broken = tmp_path / "broken.png"
        broken.write_bytes(b"not an image")
        assert _verdict_key(broken, role="body", spoken="речь", intent="кадр") == ""

    def test_the_cache_belongs_to_the_run_not_the_module(self):
        """Две сборки в одном процессе не делятся вердиктами о разных роликах."""
        from src.p12_render_qc.vision_qc import _verdict_cache

        class _Ctx:
            pass

        first, second = _Ctx(), _Ctx()
        _verdict_cache(first)["k"] = "v"
        assert _verdict_cache(second) == {}
        assert _verdict_cache(first) == {"k": "v"}

    def test_a_context_that_refuses_attributes_still_works(self):
        """Кэш — оптимизация, а не условие работы: без него QC обязан идти."""
        from src.p12_render_qc.vision_qc import _verdict_cache

        class _Frozen:
            __slots__ = ()

        assert _verdict_cache(_Frozen()) == {}


def _ok_qc():
    return {
        "passed": True, "passed_count": 1, "total": 1,
        "checks": [{"id": "QC-1", "name": "длительность", "passed": True,
                    "blocking": True, "value": 48, "threshold": [35, 70],
                    "detail": "", "timecode_sec": None}],
        "failed": [],
    }


def test_mismatch_share_eleven_percent_blocks():
    """Фикстура MUST-006: 11 % расхождений — blocking fail."""
    from src.p12_render_qc.qc import apply_semantic_qc
    from src.p12_render_qc.vision_qc import semantic_blocks

    assert semantic_blocks(mismatch_share=0.11, limit=0.10, skipped=False)
    vision = {
        "enabled": True, "skipped": False, "qc_skipped_semantic": False,
        "mismatch_share": 0.11, "mismatch_limit": 0.10,
        "picture_matches_speech": False, "blocking": True, "notes": [],
    }
    folded = apply_semantic_qc(_ok_qc(), vision)
    assert not folded["passed"]
    assert folded["vision"]["blocking"] is True
    assert any(c["id"] == "QC-SEMANTIC" and c["blocking"] and not c["passed"]
               for c in folded["checks"])


def test_mismatch_share_nine_percent_passes():
    """Фикстура MUST-006: 9 % расхождений — pass."""
    from src.p12_render_qc.qc import apply_semantic_qc
    from src.p12_render_qc.vision_qc import semantic_blocks

    assert not semantic_blocks(mismatch_share=0.09, limit=0.10, skipped=False)
    vision = {
        "enabled": True, "skipped": False, "qc_skipped_semantic": False,
        "mismatch_share": 0.09, "mismatch_limit": 0.10,
        "picture_matches_speech": True, "blocking": False, "notes": [],
    }
    folded = apply_semantic_qc(_ok_qc(), vision)
    assert folded["passed"]
    assert folded["vision"]["blocking"] is False


def test_skip_live_is_not_a_shipped_semantic_success(tmp_path, monkeypatch):
    """skip_live не пишет semantic pass и не даёт status success."""
    from src.p12_render_qc import vision_qc as VQ
    from src.p12_render_qc.qc import apply_semantic_qc

    monkeypatch.setattr(VQ, "build_vision_provider", lambda *_a, **_k: None)
    cfg = load_config(overrides=["vision.skip_live=true"])
    ctx = MagicMock()
    ctx.cfg = cfg
    ctx.costs = MagicMock()
    ctx.warn = MagicMock()
    ctx.wpath = lambda *a: tmp_path.joinpath(*map(str, a))

    vision = VQ.run_vision_qc(
        ctx, video_path=tmp_path / "v.mp4",
        plan={"duration_sec": 10, "variant": "A", "shots": [], "subtitles": []},
    )
    folded = apply_semantic_qc(_ok_qc(), vision)
    status = "ok" if folded["passed"] else "qc_failed"
    assert vision["qc_skipped_semantic"] is True
    assert vision["picture_matches_speech"] is not True
    assert folded["passed"] is False
    assert status != "ok"
    assert "success" not in status
    assert folded.get("vision")
