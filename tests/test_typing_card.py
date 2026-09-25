"""tools/typing_card.py: формула в окне, крупно и в палитре (0052, 25.09)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.typing_card import RED, WHITE, parse_line, render


def test_colored_segments_are_parsed():
    line = parse_line("#FFFFFF:Δa = |#D7263D:5 000 000 g")
    assert line == [("Δa = ", WHITE), ("5 000 000 g", RED)]


def test_plain_text_is_white():
    assert parse_line("кот") == [("кот", WHITE)]


def test_renders_a_vertical_clip_of_the_asked_length(tmp_path: Path):
    out = render([parse_line("#FFFFFF:Δa = c⁶·L / (4·G²·M²)")], style="browser",
                 title="redshift.shorts/tidal", heading="Проба", bg=None, sec=0.5,
                 out=tmp_path / "card.mp4")
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,nb_frames",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
    width, height, frames = probe.strip().split(",")
    assert (int(width), int(height)) == (1080, 1920)
    assert int(frames) == 15
