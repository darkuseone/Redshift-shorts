"""params.media must be staged and remapped for HyperFrames lint."""

from __future__ import annotations

from pathlib import Path

from src.lib.config import load_config
from src.lib.render.hyperframes.composition import CompositionBuilder
from src.lib.render.hyperframes.project import HyperFramesProject


def test_fullscreen_params_media_uses_staged_asset_path():
    """Raw work/... paths in params.media must become assets/mNNN_... in HTML."""
    media_src = "/w/shots/pexels_v34550739_303_crop.mp4"
    plan = {
        "video_id": "redshift_0042",
        "variant": "B",
        "fps": 30,
        "resolution": [1080, 1920],
        "duration_sec": 3.0,
        "shots": [
            {
                "index": 0,
                "start": 0.0,
                "end": 3.0,
                "duration": 3.0,
                "kind": "fullscreen_text",
                "block_id": "b1",
                "content": "ЗДЕСЬ ВСЁ НАОБОРОТ",
                "accent_word": "НАОБОРОТ",
                "invert": True,
                "renderer": "fs_number_slam",
                "params": {
                    "slam": True,
                    "media": media_src,
                    "content": "ЗДЕСЬ ВСЁ НАОБОРОТ",
                    "accent_word": "НАОБОРОТ",
                    "invert": True,
                },
                "bg_file": media_src,
            },
        ],
        "avatar": [],
        "overlays": [],
        "subtitles": [],
    }
    assets = {media_src: "assets/m000_pexels_v34550739_303_crop.mp4"}
    brandbook = load_config().brandbook
    out = CompositionBuilder(plan, brandbook, assets).build("assets/mix.wav")
    assert "fs-slam-media" in out
    assert 'src="assets/m000_pexels_v34550739_303_crop.mp4"' in out
    assert media_src not in out
    assert "/w/shots/" not in out


def test_stage_media_includes_params_media(tmp_path: Path):
    crop = tmp_path / "pexels_v34550739_303_crop.mp4"
    crop.write_bytes(b"fake")
    mix = tmp_path / "mix.wav"
    mix.write_bytes(b"RIFF")
    plan = {
        "shots": [
            {
                "index": 0,
                "file": str(crop),
                "params": {"media": str(crop), "slam": True},
            }
        ],
        "avatar": [],
        "overlays": [],
    }
    root = tmp_path / "hf"
    proj = HyperFramesProject(root, load_config())
    staged = proj._stage_media(plan)
    assert str(crop) in staged
    assert staged[str(crop)].startswith("assets/")
    assert (root / "assets" / Path(staged[str(crop)]).name).exists() or (
        root / staged[str(crop)]
    ).exists() or any(root.joinpath("assets").iterdir())
