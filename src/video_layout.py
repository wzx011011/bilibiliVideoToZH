"""Shared 1920x1080 editorial layout primitives for Pillow video renderers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1920, 1080
HEADER_BOTTOM = 150
STAGE_TOP = 150
STAGE_BOTTOM = 912
SUBTITLE_TOP = 912
EDGE_MARGIN = 72

FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int
    name: str = ""

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def intersects(self, other: "Rect", padding: int = 0) -> bool:
        return not (
            self.right + padding <= other.left
            or other.right + padding <= self.left
            or self.bottom + padding <= other.top
            or other.bottom + padding <= self.top
        )

    def inside(self, other: "Rect") -> bool:
        return (
            self.left >= other.left
            and self.top >= other.top
            and self.right <= other.right
            and self.bottom <= other.bottom
        )

    def to_dict(self) -> dict:
        return asdict(self)


FRAME = Rect(0, 0, WIDTH, HEIGHT, "frame")
HEADER = Rect(0, 0, WIDTH, HEADER_BOTTOM, "header")
STAGE = Rect(0, STAGE_TOP, WIDTH, STAGE_BOTTOM, "stage")
SUBTITLE = Rect(0, SUBTITLE_TOP, WIDTH, HEIGHT, "subtitle")


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, int(size))
    except OSError:
        return ImageFont.load_default()


def text_rect(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str,
              text_font: ImageFont.ImageFont, *, spacing: int = 8,
              name: str = "text") -> Rect:
    box = draw.multiline_textbbox(xy, text, font=text_font, spacing=spacing)
    return Rect(int(box[0]), int(box[1]), int(box[2]), int(box[3]), name)


def draw_subtitle_band(image: Image.Image, subtitle: str, *,
                       band_color: tuple[int, int, int] = (24, 25, 27),
                       text_color: tuple[int, int, int] = (250, 248, 242),
                       accent_color: tuple[int, int, int] = (176, 48, 42),
                       source_line: str = "") -> list[Rect]:
    """Draw a fixed single-line subtitle band and return semantic bounds."""
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, SUBTITLE_TOP, WIDTH, HEIGHT), fill=band_color)
    draw.rectangle((0, SUBTITLE_TOP, WIDTH, SUBTITLE_TOP + 4), fill=accent_color)
    boxes = [SUBTITLE]

    if source_line:
        source_font = font(20)
        draw.text((EDGE_MARGIN, SUBTITLE_TOP + 16), source_line, font=source_font,
                  fill=(166, 164, 157))
        boxes.append(text_rect(draw, (EDGE_MARGIN, SUBTITLE_TOP + 16), source_line,
                               source_font, name="source"))

    line = str(subtitle).split("\n")[0] if subtitle else ""
    if line:
        # 整句成条后长句自动缩字号,保证单行放进字幕带
        size = 40
        while size > 26 and draw.textlength(line, font=font(size, bold=True)) > WIDTH - 2 * EDGE_MARGIN:
            size -= 4
        subtitle_font = font(size, bold=True)
        width = draw.textlength(line, font=subtitle_font)
        x = (WIDTH - width) / 2
        y = SUBTITLE_TOP + 58
        draw.text((x + 2, y + 3), line, font=subtitle_font, fill=(0, 0, 0))
        draw.text((x, y), line, font=subtitle_font, fill=text_color,
                  stroke_width=1, stroke_fill=(8, 8, 9))
        boxes.append(text_rect(draw, (x, y), line, subtitle_font,
                               name="subtitle_line_1"))
    return boxes


def validate_layout(boxes: Iterable[Rect]) -> list[dict]:
    """Validate fixed overlay bounds. Scene artwork is clipped to STAGE separately."""
    items = list(boxes)
    issues: list[dict] = []
    for box in items:
        if box.name.startswith("subtitle_line") and not box.inside(SUBTITLE):
            issues.append({"type": "outside_subtitle_band", "box": box.to_dict()})
        if box.name == "source" and not box.inside(SUBTITLE):
            issues.append({"type": "source_outside_band", "box": box.to_dict()})
        if not box.inside(FRAME):
            issues.append({"type": "outside_frame", "box": box.to_dict()})

    subtitle_lines = [b for b in items if b.name.startswith("subtitle_line")]
    for first, second in zip(subtitle_lines, subtitle_lines[1:]):
        if first.intersects(second, padding=5):
            issues.append({"type": "subtitle_overlap", "first": first.to_dict(),
                           "second": second.to_dict()})
    return issues


def black_edge_ratio(image: Image.Image, strip: int = 8) -> float:
    """Return the ratio of nearly-black pixels along the outer frame strips."""
    rgb = image.convert("RGB")
    samples = []
    samples.extend(rgb.crop((0, 0, WIDTH, strip)).getdata())
    samples.extend(rgb.crop((0, HEIGHT - strip, WIDTH, HEIGHT)).getdata())
    samples.extend(rgb.crop((0, 0, strip, HEIGHT)).getdata())
    samples.extend(rgb.crop((WIDTH - strip, 0, WIDTH, HEIGHT)).getdata())
    if not samples:
        return 0.0
    dark = sum(1 for r, g, b in samples if r < 8 and g < 8 and b < 8)
    return dark / len(samples)


def write_layout_report(path: Path, frames: list[dict]) -> None:
    import json

    issues = [issue for frame in frames for issue in frame.get("issues", [])]
    payload = {"ok": not issues, "frame_count": len(frames), "issue_count": len(issues),
               "frames": frames}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if issues:
        raise RuntimeError(f"layout validation failed with {len(issues)} issue(s): {path}")
