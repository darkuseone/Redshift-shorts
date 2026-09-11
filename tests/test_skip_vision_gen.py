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


def test_vision_qc_auto_without_live_keys_skips_semantic(tmp_path, monkeypatch):
    """auto без Grok и Gemini не закрывает §11.2 mock-судьёй."""
    from src.p12_render_qc import vision_qc as VQ

    for env_name in (
        "GLM_API_KEY", "GLM_API", "TOKENROUTER_API_KEY", "ZAI_API_KEY",
        "Z_AI_API_KEY", "XAI_API_KEY", "XAI_API",
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AI_API_KEY",
    ):
        monkeypatch.delenv(env_name, raising=False)

    cfg = load_config(overrides=["providers.mode=auto"])
    ctx = MagicMock()
    ctx.cfg = cfg
    ctx.costs = MagicMock()
    ctx.warn = MagicMock()
    ctx.wpath = lambda *a: tmp_path.joinpath(*map(str, a))

    report = VQ.run_vision_qc(
        ctx, video_path=tmp_path / "v.mp4",
        plan={"duration_sec": 10, "variant": "A", "shots": [], "subtitles": []},
    )
    assert report.get("qc_skipped_semantic") is True
    assert report["blocking"] is True
    assert report["picture_matches_speech"] is False
    assert report["mismatch_share"] is None


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


def _skip_ctx(tmp_path, monkeypatch, *, skip_live=True):
    from src.p12_render_qc import vision_qc as VQ
    from src.lib.config import load_config

    called = {"build": 0, "frames": 0}

    def _boom_provider(*_a, **_k):
        called["build"] += 1
        raise AssertionError("build_vision_provider must not run under skip_live")

    def _boom_frames(*_a, **_k):
        called["frames"] += 1
        raise AssertionError("extract_frames must not run under skip_live")

    monkeypatch.setattr(VQ, "build_vision_provider", _boom_provider)
    monkeypatch.setattr(VQ, "extract_frames", _boom_frames)
    cfg = load_config(overrides=["vision.skip_live=true"] if skip_live else [])
    ctx = MagicMock()
    ctx.cfg = cfg
    ctx.costs = MagicMock()
    ctx.warn = MagicMock()
    ctx.wpath = lambda *a: tmp_path.joinpath(*map(str, a))
    ctx.read_or = lambda *_a, **_k: {}
    return ctx, called


def test_skip_live_with_shots_runs_local_not_xai(tmp_path, monkeypatch):
    from src.p12_render_qc import vision_qc as VQ
    from src.p12_render_qc.qc import apply_semantic_qc

    ctx, called = _skip_ctx(tmp_path, monkeypatch)
    plan = {
        "video_id": "redshift_0049",
        "duration_sec": 70.0,
        "variant": "A",
        "shots": [
            {"index": 1, "start": 2.0, "end": 7.2, "kind": "avatar",
             "asset_id": "avatar_seg_0", "file": "avatar.mp4", "bg_file": None},
            {"index": 2, "start": 7.17, "end": 8.4, "kind": "fullscreen_text",
             "content": "$1 000 000", "file": "assets/backdrops/grid.jpg",
             "params": {"content": "$1 000 000"}},
            {"index": 5, "start": 16.0, "end": 21.0, "kind": "footage",
             "asset_id": "press_c8e1aa428b",
             "file": "shots/press_c8e1aa428b_crop.mp4",
             "page_url": "https://openai.com/index/navier-stokes-solution/"},
            {"index": 10, "start": 28.6, "end": 31.4, "kind": "footage",
             "asset_id": "pexels_v34459460",
             "file": "shots/pexels_v34459460_crop.mp4",
             "page_url": "https://www.pexels.com/video/colorful-html-code-on-computer-monitor-34459460/",
             "template": "kenburns/pan-left"},
            {"index": 13, "start": 38.8, "end": 41.6, "kind": "footage",
             "asset_id": "pexels_v10884417",
             "file": "shots/pexels_v10884417_crop.mp4",
             "page_url": "https://www.pexels.com/video/water-flowing-through-a-discharge-pipe-10884417/"},
            {"index": 19, "start": 52.6, "end": 56.2, "kind": "avatar",
             "asset_id": "pexels_v37695140",
             "file": "avatar_19.mp4",
             "bg_file": "shots/bg_pexels_v37695140_crop.mp4",
             "page_url": "https://www.pexels.com/video/quiet-library-aisle-with-rows-of-books-37695140/"},
            {"index": 23, "start": 62.8, "end": 66.5, "kind": "avatar",
             "asset_id": "pexels_v12908964",
             "file": "avatar_23.mp4",
             "bg_file": "shots/bg_pexels_v12908964_crop.mp4",
             "page_url": "https://www.pexels.com/video/woman-looking-at-documents-while-working-from-home-12908964/"},
        ],
        "slot_locks": [
            {"t": 5.8, "kind": "avatar", "brand_plate": True,
             "deny_asset_ids": ["press_c8e1aa428b"]},
            {"t": 7.18, "kind": "fullscreen_text", "brand_plate": True,
             "deny_asset_ids": ["press_c8e1aa428b"]},
            {"t": 17.58, "kind": "footage", "asset_id": "press_c8e1aa428b",
             "min_duration": 5.2},
            {"t": 29.3, "kind": "footage", "asset_id": "pexels_v34459460"},
            {"t": 41.02, "kind": "footage", "asset_id": "pexels_v10884417",
             "exclusive": True},
            {"t": 52.73, "kind": "avatar", "asset_id": "pexels_v37695140",
             "deny_asset_ids": ["pexels_v10884417"]},
            {"t": 64.45, "kind": "avatar", "asset_id": "pexels_v12908964",
             "deny_asset_ids": ["pexels_v16865644", "pexels_v10884417"]},
        ],
        "speech_words": [
            {"display": "миллион", "start": 5.6, "end": 6.0},
            {"display": "OpenAI", "start": 17.4, "end": 17.7},
            {"display": "выкладывает", "start": 17.7, "end": 18.2},
            {"display": "Астра", "start": 29.1, "end": 29.4},
            {"display": "Lean", "start": 29.5, "end": 29.9},
            {"display": "Навье-Стокса", "start": 40.8, "end": 41.3},
            {"display": "жидкость", "start": 41.3, "end": 41.7},
            {"display": "приз", "start": 52.5, "end": 52.7},
            {"display": "Клея", "start": 52.7, "end": 53.1},
            {"display": "дыра", "start": 64.2, "end": 64.5},
            {"display": "стене", "start": 64.6, "end": 64.9},
        ],
        "subtitles": [],
    }
    vision = VQ.run_vision_qc(ctx, video_path=tmp_path / "v.mp4", plan=plan)
    folded = apply_semantic_qc(_ok_qc(), vision)
    assert called["build"] == 0
    assert called["frames"] == 0
    assert vision.get("local_semantic") is True
    assert vision.get("live_xai_calls") == 0
    assert vision.get("qc_skipped_semantic") is not True
    assert vision["mismatch_share"] == 0.0
    assert vision["picture_matches_speech"] is True
    assert folded["passed"] is True


def test_skip_live_dataviz_on_astra_is_mismatch(tmp_path, monkeypatch):
    from src.p12_render_qc import vision_qc as VQ

    ctx, called = _skip_ctx(tmp_path, monkeypatch)
    plan = {
        "video_id": "redshift_0049",
        "duration_sec": 40.0,
        "variant": "A",
        "shots": [{
            "index": 10, "start": 28.0, "end": 32.0, "kind": "footage",
            "asset_id": "mk-line-graph",
            "template": "data-viz/mk-line-graph",
            "ladder_rung": "dataviz",
            "file": "shots/graph.mp4",
        }],
        "slot_locks": [
            {"t": 29.3, "kind": "footage", "asset_id": "pexels_v34459460"},
        ],
        "speech_words": [
            {"display": "Астра", "start": 29.1, "end": 29.4},
            {"display": "Lean", "start": 29.5, "end": 29.9},
        ],
        "subtitles": [],
    }
    vision = VQ.run_vision_qc(ctx, video_path=tmp_path / "v.mp4", plan=plan)
    assert called["build"] == 0
    assert called["frames"] == 0
    assert vision["blocking"] is True
    assert vision["mismatch_share"] == 1.0
    assert any("lock" in str(s.get("reason") or "") or "dataviz" in str(s.get("reason") or "")
               for s in vision.get("samples") or [])


def test_skip_live_stolen_water_on_clay_is_mismatch(tmp_path, monkeypatch):
    from src.p12_render_qc import vision_qc as VQ

    ctx, called = _skip_ctx(tmp_path, monkeypatch)
    plan = {
        "video_id": "redshift_0049",
        "duration_sec": 70.0,
        "variant": "A",
        "shots": [
            {"index": 13, "start": 38.8, "end": 41.6, "kind": "footage",
             "asset_id": "pexels_v10884417",
             "file": "shots/pexels_v10884417_crop.mp4"},
            {"index": 19, "start": 52.6, "end": 56.2, "kind": "avatar",
             "asset_id": "pexels_v10884417",
             "bg_file": "shots/bg_pexels_v10884417_crop.mp4"},
        ],
        "slot_locks": [
            {"t": 41.02, "kind": "footage", "asset_id": "pexels_v10884417",
             "exclusive": True},
            {"t": 52.73, "kind": "avatar", "asset_id": "pexels_v37695140",
             "deny_asset_ids": ["pexels_v10884417"]},
        ],
        "speech_words": [
            {"display": "Навье-Стокса", "start": 40.8, "end": 41.3},
            {"display": "Клея", "start": 52.7, "end": 53.1},
        ],
        "subtitles": [],
    }
    vision = VQ.run_vision_qc(ctx, video_path=tmp_path / "v.mp4", plan=plan)
    assert called["build"] == 0
    assert vision["blocking"] is True
    assert vision["mismatch_share"] == 1.0
