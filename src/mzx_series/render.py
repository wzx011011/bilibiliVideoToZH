"""毛选推演系列·战略批注风渲染器（论持久战试点）。

画面语言：米黄作战文件纸底 + 墨黑正文 + 红(日)/蓝(我)推演双色 + 印章批注。
复用 gpt_explainer 的音频拼装/时间轴/字幕/探测管线，舞台皮肤为本系列专属。

用法:
  python src/mzx_series/render.py --preview   # 不依赖配音,出代表帧+拼图
  python src/mzx_series/render.py --render    # 配音就绪后出全片
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[0]
sys.path.insert(0, str(SRC))

from gpt_explainer.render import (  # noqa: E402
    WIDTH, HEIGHT, FPS,
    assemble_audio, build_subtitle_cues, build_timeline, write_srt,
    _part_files, _probe_video, _cue_for,
)

ROOT = HERE.parents[1]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
CONTENT = HERE / "lunchiuzhan.json"
OUT = Path("D:/mzx-lunchiuzhan")

PAPER = (242, 235, 220)
RULE = (229, 220, 199)
INK = (43, 40, 36)
RED = (176, 48, 42)
DEEPRED = (140, 36, 32)
BLUE = (46, 74, 106)
OCHRE = (168, 122, 60)
MUTED = (124, 112, 95)
LINE = (206, 194, 170)
CARD = (249, 244, 232)
GOLD = (216, 198, 160)
DISCLAIMER = "原文引用已标注 · 非本片实测"


def _font(size: int, bold: bool = False, kai: bool = False):
    paths = [("C:/Windows/Fonts/simkai.ttf", {}), ] if kai else []
    try:
        if kai:
            return ImageFont.truetype("C:/Windows/Fonts/simkai.ttf", size)
        return ImageFont.truetype(
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc", size)
    except OSError:
        return ImageFont.load_default()


def _wrap(draw, text, font, width) -> list[str]:
    lines, line = [], ""
    for ch in str(text):
        if line and draw.textlength(line + ch, font=font) > width:
            lines.append(line)
            line = ch
        else:
            line += ch
    if line:
        lines.append(line)
    return lines or [""]


def _paper() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    d = ImageDraw.Draw(img)
    for y in range(150, HEIGHT - 160, 110):
        d.line((60, y, WIDTH - 60, y), fill=RULE, width=1)
    d.rectangle((26, 26, WIDTH - 26, HEIGHT - 26), outline=INK, width=3)
    d.rectangle((40, 40, WIDTH - 40, HEIGHT - 40), outline=LINE, width=1)
    return img


def _chrome(d, content, index, progress, total):
    d.text((92, 66), content.get("title", ""), font=_font(28, True), fill=INK)
    as_of = f"文本标注 · {content.get('as_of', '')}"
    d.text((WIDTH - 92 - d.textlength(as_of, font=_font(24)), 72), as_of,
           font=_font(24), fill=MUTED)
    num_text = f"{index + 1:02d} / {total:02d}"
    d.text((92, 128), num_text, font=_font(24, True), fill=RED)
    kicker = str(content["chapters"][index].get("kicker", ""))
    parts = kicker.split("/", 1)
    if len(parts) == 2 and parts[0].strip().isdigit():
        kicker = parts[1].strip()
    d.text((100 + d.textlength(num_text, font=_font(24, True)), 128), kicker,
           font=_font(24, True), fill=BLUE)
    d.line((92, 176, WIDTH - 92, 176), fill=LINE, width=2)
    d.rectangle((92, 176, 92 + int((WIDTH - 184) * ((index + progress) / max(total, 1))), 182),
                fill=RED)


def _bottom(d, sources, subtitle=""):
    d.rectangle((0, 880, WIDTH, HEIGHT), fill=INK)
    d.text((92, 898), sources, font=_font(22, True), fill=GOLD)
    d.text((WIDTH - 92 - d.textlength(DISCLAIMER, font=_font(20)), 900), DISCLAIMER,
           font=_font(20), fill=(172, 162, 144))
    if subtitle:
        text = "\n".join(subtitle.split("\n")[:2])
        f = _font(34, True)
        bbox = d.multiline_textbbox((0, 0), text, font=f, spacing=6, align="center")
        d.multiline_text(((WIDTH - (bbox[2] - bbox[0])) / 2, 934), text,
                         font=f, fill=(246, 242, 232), spacing=6, align="center")


def _card(d, box, outline=LINE):
    d.rounded_rectangle(box, radius=10, fill=CARD, outline=outline, width=2)


def _seal(d, box, text="推演", size=54):
    d.rounded_rectangle(box, radius=14, fill=RED)
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    f = _font(size, True)
    w = d.textlength(text, font=f)
    d.text((cx - w / 2, cy - size * 0.62), text, font=f, fill=CARD)


def _sc_cover(d, ch, area, progress):
    left, top, right, bottom = area
    d.text((100, top + 60), ch.get("headline", ""), font=_font(104, True), fill=INK)
    d.rectangle((104, top + 210, 560, top + 218), fill=RED)
    y = top + 270
    for note in ch.get("notes", []):
        d.rectangle((104, y + 12, 118, y + 26), fill=RED)
        for i, ln in enumerate(_wrap(d, note, _font(30), 760)):
            d.text((136 + (0 if i == 0 else 32), y), ln, font=_font(30),
                   fill=INK if i == 0 else MUTED)
            y += 44
        y += 18
    _seal(d, (right - 250, top + 80, right - 70, top + 260), "推演", 62)


def _sc_versus(d, ch, area, progress):
    left, top, right, bottom = area
    gap = 44
    card_w = (right - left - gap) / 2
    for i, side in enumerate(("left", "right")):
        data = ch.get(side, {})
        color = BLUE if side == "left" else RED
        x0 = left + i * (card_w + gap)
        box = (x0, top + 40, x0 + card_w, bottom - 110)
        d.rounded_rectangle(box, radius=12, fill=CARD, outline=color, width=4)
        d.rounded_rectangle((x0, top + 40, x0 + card_w, top + 120), radius=12,
                            fill=color)
        d.rectangle((x0, top + 90, x0 + card_w, top + 120), fill=color)
        name = str(data.get("name", ""))
        f = _font(42, True)
        d.text((x0 + (card_w - d.textlength(name, font=f)) / 2, top + 58), name,
               font=f, fill=CARD)
        y = top + 170
        for ln in data.get("lines", []):
            for piece in _wrap(d, ln, _font(30, True), card_w - 100):
                d.text((x0 + 50, y), piece, font=_font(30, True), fill=INK)
                y += 46
            y += 22
    cx, cy = WIDTH / 2, (top + bottom) / 2 - 20
    d.ellipse((cx - 48, cy - 48, cx + 48, cy + 48), fill=INK, outline=PAPER, width=5)
    vs = "VS"
    f = _font(38, True)
    d.text((cx - d.textlength(vs, font=f) / 2, cy - 26), vs, font=f, fill=PAPER)
    common = str(ch.get("common", ""))
    d.rounded_rectangle((left, bottom - 78, right, bottom - 14), radius=8,
                        outline=RED, width=3)
    f = _font(28, True)
    d.text((left + (right - left - d.textlength(common, font=f)) / 2, bottom - 62),
           common, font=f, fill=DEEPRED)


def _sc_compare(d, ch, area, progress):
    left, top, right, bottom = area
    d.rectangle((right - 260, top + 26, right - 236, top + 44), fill=RED)
    d.text((right - 226, top + 18), "日本", font=_font(24), fill=INK)
    d.rectangle((right - 140, top + 26, right - 116, top + 44), fill=BLUE)
    d.text((right - 106, top + 18), "中国", font=_font(24), fill=INK)
    cx = (left + right) / 2
    max_len = 520
    groups = ch.get("groups", [])
    gy = top + 30
    d.line((cx, top + 16, cx, top + 30 + len(groups) * 108 + 10), fill=INK, width=3)
    for g in groups:
        label = str(g.get("label", ""))
        f = _font(28, True)
        d.text((cx - d.textlength(label, font=f) / 2, gy), label, font=f, fill=INK)
        by = gy + 40
        for side, color in (("jp", RED), ("cn", BLUE)):
            data = g.get(side, {})
            v = max(0.0, min(100.0, float(data.get("v", 0)))) * min(1.0, progress * 1.6 + .2)
            length = max(8, max_len * v / 100)
            text = str(data.get("text", ""))
            ft = _font(26, True)
            if side == "jp":
                d.rounded_rectangle((cx - 26 - length, by, cx - 26, by + 32),
                                    radius=6, fill=color)
                d.text((cx - 40 - length - d.textlength(text, font=ft), by - 2),
                       text, font=ft, fill=DEEPRED)
            else:
                d.rounded_rectangle((cx + 26, by, cx + 26 + length, by + 32),
                                    radius=6, fill=color)
                d.text((cx + 40 + length, by - 2), text, font=ft, fill=BLUE)
        gy = by + 32 + 34
    note = str(ch.get("note", ""))
    f = _font(26)
    d.text((cx - d.textlength(note, font=f) / 2, bottom - 64), note, font=f, fill=MUTED)


def _sc_timeline(d, ch, area, progress):
    left, top, right, bottom = area
    quote = str(ch.get("quote", ""))
    _card(d, (left, top + 20, right, top + 168))
    fq = _font(34, kai=True)
    d.text((left + 34, top + 38), "「", font=_font(40, True), fill=RED)
    lines = _wrap(d, quote, fq, right - left - 160)
    d.multiline_text((left + 90, top + 44), "\n".join(lines[:2]), font=fq,
                     fill=INK, spacing=10)
    d.text((right - 76, top + 118), "」", font=_font(40, True), fill=RED)
    phases = ch.get("phases", [])
    ax0, ax1, ay = left + 30, right - 30, top + 400
    total_w = ax1 - ax0
    x = ax0
    colors = [BLUE, OCHRE, RED]
    centers = []
    for i, p in enumerate(phases):
        w = total_w * float(p.get("w", 30)) / 100.0
        reveal = min(1.0, progress * 1.5 + i * 0.18 + 0.15)
        d.rectangle((x, ay - 14, x + max(10, w * reveal), ay + 14), fill=colors[i % 3])
        centers.append(x + w / 2)
        x += w
    d.rectangle((x - 30, ay - 14, x - 6, ay + 14), fill=LINE)
    x = ax0
    for i, p in enumerate(phases):
        w = total_w * float(p.get("w", 30)) / 100.0
        name, era = str(p.get("name", "")), str(p.get("era", ""))
        f = _font(30, True)
        d.text((centers[i] - d.textlength(name, font=f) / 2, ay - 78), name,
               font=f, fill=INK)
        fe = _font(22)
        d.text((centers[i] - d.textlength(era, font=fe) / 2, ay - 40), era,
               font=fe, fill=MUTED)
        note_y = ay + 74 if p.get("events") else ay + 34
        for j, ln in enumerate(_wrap(d, str(p.get("note", "")), _font(23), w - 24)):
            d.text((x + 12, note_y + j * 32), ln, font=_font(23), fill=INK)
        for j, ev in enumerate(p.get("events", [])):
            ex = x + 40 + j * 96
            d.ellipse((ex - 9, ay - 9, ex + 9, ay + 9), outline=DEEPRED, width=4)
            d.line((ex, ay + 9, ex, ay + 24), fill=DEEPRED, width=2)
            d.text((ex - d.textlength(ev, font=_font(21)) / 2, ay + 26), ev,
                   font=_font(21), fill=DEEPRED)
        x += w


def _sc_matrix(d, ch, area, progress):
    left, top, right, bottom = area
    header = ch.get("header", [])
    cols = [left + 40, left + 260, left + 920]
    if header:
        for i, h in enumerate(header):
            d.text((cols[i], top + 30), str(h), font=_font(26, True), fill=MUTED)
        d.line((left + 36, top + 76, right - 36, top + 76), fill=LINE, width=2)
    rows = ch.get("rows", [])
    for i, row in enumerate(rows[:4]):
        y = top + 100 + i * 128
        _card(d, (left + 24, y, right - 24, y + 104))
        d.rounded_rectangle((left + 24, y, left + 40, y + 104), radius=4, fill=RED)
        d.text((cols[0], y + 32), str(row[0]), font=_font(32, True), fill=DEEPRED)
        d.text((cols[1], y + 32), str(row[1]), font=_font(30, True), fill=INK)
        d.text((cols[2], y + 34), str(row[2] if len(row) > 2 else ""),
               font=_font(26), fill=MUTED)
    principle = str(ch.get("principle", ""))
    box = (left + 120, bottom - 92, right - 120, bottom - 20)
    d.rounded_rectangle(box, radius=10, outline=DEEPRED, width=3)
    f = _font(30, True)
    d.text(((left + right - d.textlength(principle, font=f)) / 2, bottom - 74),
           principle, font=f, fill=DEEPRED)


def _sc_flow(d, ch, area, progress):
    left, top, right, bottom = area
    label = str(ch.get("headline", ""))
    f = _font(40, True)
    d.text(((left + right - d.textlength(label, font=f)) / 2, top + 24), label,
           font=f, fill=DEEPRED)
    _card(d, (left + 140, top + 110, right - 140, top + 330), outline=RED)
    fq = _font(40, kai=True)
    d.text((left + 170, top + 126), "「", font=_font(46, True), fill=RED)
    lines = _wrap(d, str(ch.get("quote", "")), fq, right - left - 380)
    d.multiline_text((left + 230, top + 138), "\n".join(lines[:2]), font=fq,
                     fill=INK, spacing=16)
    d.text((right - 200, top + 268), "」", font=_font(46, True), fill=RED)
    notes = ch.get("notes", [])
    nw = (right - left - 100 - 40 * (len(notes) - 1)) / max(len(notes), 1)
    for i, note in enumerate(notes):
        x = left + 50 + i * (nw + 40)
        _card(d, (x, top + 400, x + nw, top + 560))
        for j, ln in enumerate(_wrap(d, note, _font(27, True), nw - 60)):
            d.text((x + 30, top + 430 + j * 42), ln, font=_font(27, True), fill=INK)


def _sc_checklist(d, ch, area, progress):
    left, top, right, bottom = area
    rows = ch.get("rows", [])
    for i, row in enumerate(rows[:4]):
        y = top + 26 + i * 128
        cy = y + 44
        d.ellipse((left + 40, cy - 22, left + 84, cy + 22), outline=DEEPRED, width=4)
        d.line((left + 51, cy + 1, left + 66, cy + 15), fill=DEEPRED, width=5)
        d.line((left + 66, cy + 15, left + 76, cy - 12), fill=DEEPRED, width=5)
        for j, ln in enumerate(_wrap(d, str(row[0]), _font(30, kai=True), 600)):
            d.text((left + 110, cy - 22 + j * 40), ln, font=_font(30, kai=True), fill=INK)
        d.text((left + 740, cy - 20), "→", font=_font(34, True), fill=RED)
        fx = left + 810
        for j, ln in enumerate(_wrap(d, str(row[1] if len(row) > 1 else ""),
                                     _font(28, True), right - fx - 40)):
            d.text((fx, cy - 20 + j * 40), ln, font=_font(28, True), fill=BLUE)
        if i < len(rows) - 1:
            d.line((left + 40, y + 104, right - 40, y + 104), fill=LINE, width=1)
    note = str(ch.get("note", ""))
    f = _font(26)
    d.text(((left + right - d.textlength(note, font=f)) / 2, bottom - 56), note,
           font=f, fill=MUTED)


def _sc_summary(d, ch, area, progress):
    left, top, right, bottom = area
    cards = ch.get("cards", [])
    cw, chh = (right - left - 50) / 2, 250
    for i, card in enumerate(cards[:4]):
        x = left + (i % 2) * (cw + 50)
        y = top + 30 + (i // 2) * (chh + 44)
        _card(d, (x, y, x + cw, y + chh))
        d.rounded_rectangle((x, y, x + 14, y + chh), radius=4,
                            fill=RED if i % 2 == 0 else BLUE)
        d.text((x + 44, y + 28), f"{i + 1:02d}", font=_font(34, True), fill=RED)
        d.text((x + 120, y + 26), str(card.get("t", "")), font=_font(38, True), fill=INK)
        yy = y + 108
        for ln in _wrap(d, str(card.get("d", "")), _font(26), cw - 90):
            d.text((x + 44, yy), ln, font=_font(26), fill=MUTED)
            yy += 38


SCENES = {"cover": _sc_cover, "versus": _sc_versus, "compare": _sc_compare,
          "timeline": _sc_timeline, "matrix": _sc_matrix, "flow": _sc_flow,
          "checklist": _sc_checklist, "summary": _sc_summary}


def render_scene(chapter: dict[str, Any], progress: float = 0.0, *, content=None,
                 index: int = 0, total: int = 1, subtitle: str = "") -> Image.Image:
    content = content or {}
    img = _paper()
    d = ImageDraw.Draw(img)
    progress = max(0.0, min(1.0, progress))
    _chrome(d, content, index, progress, total)
    if str(chapter.get("kind", "")) != "cover":
        d.text((92, 216), str(chapter.get("headline", chapter.get("title", ""))),
               font=_font(48, True), fill=INK)
    kind = str(chapter.get("kind", "summary"))
    area = (92, 300, WIDTH - 92, 852)
    SCENES.get(kind, _sc_summary)(d, chapter, area, progress)
    ids = " ｜ ".join(str(s) for s in chapter.get("source_ids", [])) or "—"
    src = " ｜ ".join(s["label"] for s in content.get("sources", [])
                      if s["id"] in str(ids)) or ids
    _bottom(d, src, subtitle)
    return img


def _contact_sheet(frames: list[Path], output: Path) -> None:
    tw, th, cols = 480, 270, 2
    sheet = Image.new("RGB", (cols * tw, math.ceil(len(frames) / cols) * th), INK)
    for i, p in enumerate(frames):
        with Image.open(p) as im:
            im.thumbnail((tw, th))
            sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    sheet.save(output, "PNG")


def render_video(content, timeline, cues, audio: Path, output: Path) -> dict:
    frame_count = max(1, int(math.ceil(float(timeline["audio_duration"]) * FPS)))
    proc = subprocess.Popen(
        [str(FFMPEG), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt",
         "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
         "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
         "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-b:a", "192k", "-shortest", str(output)], stdin=subprocess.PIPE)
    assert proc.stdin is not None
    chapters = timeline["chapters"]
    total = len(chapters)
    cached = None
    try:
        for frame in range(frame_count):
            sec = frame / FPS
            idx = max((i for i, c in enumerate(chapters) if c["start"] <= sec),
                      default=0)
            entry = chapters[idx]
            local = max(0.0, min(1.0, (sec - entry["start"]) / max(entry["duration"], .001)))
            if frame % 2 == 0:  # 15fps 绘制,复制成 30fps 流
                img = render_scene(content["chapters"][idx], local, content=content,
                                   index=idx, total=total,
                                   subtitle=_cue_for(cues, sec))
                cached = img.tobytes()
            proc.stdin.write(cached)
    except BrokenPipeError as exc:
        raise RuntimeError("ffmpeg 提前退出") from exc
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg 编码失败")
    report = _probe_video(output)
    report["output"] = str(output)
    report["expected_duration"] = timeline["audio_duration"]
    report["verified"] = (report["width"] == WIDTH and report["height"] == HEIGHT
                          and report["has_audio"]
                          and abs(report["duration"] - report["audio_duration"]) < 0.15
                          and abs(report["duration"] - timeline["audio_duration"]) < 0.15)
    if not report["verified"]:
        raise RuntimeError(f"成片校验失败: {report}")
    return report


def run(preview: bool = False, render: bool = False, out: Path = OUT) -> dict:
    content = json.loads(CONTENT.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    if preview:
        durations = [max(2.5, len(c.get("narration", "")) * 0.19)
                     for c in content["chapters"]]
    else:
        parts = _part_files(out)
        _, durations = assemble_audio(out, parts)
    timeline = build_timeline(content, durations)
    cues = build_subtitle_cues(content, timeline)
    frames_dir = out / "frames"
    frames_dir.mkdir(exist_ok=True)
    total = len(timeline["chapters"])
    frames = []
    for i, ch in enumerate(content["chapters"]):
        entry = timeline["chapters"][i]
        img = render_scene(ch, 0.45, content=content, index=i, total=total,
                           subtitle=_cue_for(cues, entry["start"] + entry["duration"] * 0.45))
        p = frames_dir / f"chapter_{i:04d}.png"
        img.save(p, "PNG")
        frames.append(p)
    result: dict[str, Any] = {"frames": [str(p) for p in frames]}
    if preview:
        sheet = out / "contact_sheet.png"
        _contact_sheet(frames, sheet)
        result["contact_sheet"] = str(sheet)
    if render:
        audio = out / "audio.wav"
        (out / "timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
        write_srt(cues, out / "subtitles.srt")
        video = out / "论持久战-战略推演.mp4"
        result["report"] = render_video(content, timeline, cues, audio, video)
        result["video"] = str(video)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="无配音,渲染代表帧")
    parser.add_argument("--render", action="store_true", help="渲染全片(需配音完成)")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    try:
        result = run(preview=args.preview or not args.render,
                     render=args.render, out=args.out)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
