from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from video_layout import (  # noqa: E402
    HEIGHT,
    SUBTITLE,
    WIDTH,
    black_edge_ratio,
    draw_subtitle_band,
    validate_layout,
)


def test_subtitle_band_renders_single_line_only():
    image = Image.new("RGB", (WIDTH, HEIGHT), (240, 240, 240))
    boxes = draw_subtitle_band(image, "第一行字幕\n第二行不该出现", source_line="来源")
    assert not validate_layout(boxes)
    lines = [box for box in boxes if box.name.startswith("subtitle_line")]
    assert len(lines) == 1
    assert lines[0].inside(SUBTITLE)
    assert lines[0].height <= 60


def test_subtitle_band_handles_empty_text_without_error():
    image = Image.new("RGB", (WIDTH, HEIGHT), (240, 240, 240))
    boxes = draw_subtitle_band(image, "")
    assert boxes[0].name == "subtitle"
    assert not validate_layout(boxes)


def test_black_edge_ratio_does_not_flag_paper_frame():
    image = Image.new("RGB", (WIDTH, HEIGHT), (243, 238, 228))
    assert black_edge_ratio(image) == 0.0
