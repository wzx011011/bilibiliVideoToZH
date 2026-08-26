"""中文播客版渲染:章节画面 + 中文双音色音频 + 中文字幕 → MP4。

不依赖原视频画面。每段用一张章节图(PIL 生成:人物名 + 段落文本摘要),
按段落时长拼接成视频,叠加中文字幕与水印。

章节图由 --chapters-json 提供:
  [{"id": 0, "speaker": "A", "start": 0, "end": 45.2, "image": "path.png"}, ...]
由 prepare_chapters() 生成。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"

WIDTH, HEIGHT = 1920, 1080
BG_COLOR = (18, 22, 34)
ACCENT = (59, 91, 253)
TEXT_COLOR = (255, 255, 255)
SUB_COLOR = (160, 174, 192)

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def make_chapter_image(
    out: Path,
    speaker_name: str,
    chapter_text: str,
    chapter_index: int,
    total_chapters: int,
    title: str = "",
    width: int = WIDTH,
    height: int = HEIGHT,
) -> None:
    """生成一张章节画面:深色背景 + 人物名 + 文字摘要 + 进度条。"""
    img = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 顶部标题
    if title:
        f_title = _font(36, bold=True)
        tw = draw.textlength(title, font=f_title)
        draw.text(((width - tw) / 2, 60), title, fill=ACCENT, font=f_title)

    # 中间说话人名(大字)
    f_speaker = _font(72, bold=True)
    sw = draw.textlength(speaker_name, font=f_speaker)
    draw.text(((width - sw) / 2, height / 2 - 80), speaker_name,
              fill=TEXT_COLOR, font=f_speaker)

    # 文字摘要(最多两行)
    f_sub = _font(28)
    summary = chapter_text[:60] + ("…" if len(chapter_text) > 60 else "")
    sw2 = draw.textlength(summary, font=f_sub)
    draw.text(((width - sw2) / 2, height / 2 + 40), summary,
              fill=SUB_COLOR, font=f_sub)

    # 底部进度条
    bar_y = height - 60
    bar_w = width - 200
    draw.rectangle([100, bar_y, 100 + bar_w, bar_y + 6], fill=(60, 70, 90))
    progress = (chapter_index + 1) / max(total_chapters, 1)
    draw.rectangle([100, bar_y, 100 + int(bar_w * progress), bar_y + 6],
                   fill=ACCENT)

    # 章节编号
    f_idx = _font(20)
    idx_text = f"{chapter_index + 1} / {total_chapters}"
    iw = draw.textlength(idx_text, font=f_idx)
    draw.text(((width - iw) / 2, bar_y + 20), idx_text, fill=SUB_COLOR, font=f_idx)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=95)


def prepare_chapters(
    runs: list[dict],
    voice_names: dict[str, str],
    out_dir: Path,
    title: str = "",
) -> list[dict]:
    """runs → 章节图列表。每段生成一张,返回含 image 路径的章节列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    chapters = []
    for r in runs:
        spk = r["speaker"]
        voice_name = voice_names.get(spk, spk)
        img_path = out_dir / f"chapter_{r['id']:04d}.jpg"
        make_chapter_image(
            img_path, voice_name, r.get("text", ""),
            r["id"], len(runs), title)
        chapters.append({
            "id": r["id"],
            "speaker": spk,
            "start": r["source_start"],
            "end": r["source_end"],
            "image": str(img_path),
        })
    return chapters


def render_podcast(
    chapters: list[dict],
    audio: Path,
    srt: Path,
    output: Path,
    watermark: str = "wzx",
) -> None:
    """章节图序列 + 音频 → 视频,再烧字幕和水印。

    每章节用对应图片循环显示该段时长,concat 后叠加字幕水印。
    """
    # 1) 生成 concat 清单(每章节一张图,时长=段落时长)
    tmp = output.parent / "_podcast_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    concat_file = tmp / "concat.txt"
    lines = []
    for ch in chapters:
        dur = ch["end"] - ch["start"]
        img = tmp / f"ch_{ch['id']:04d}.jpg"
        shutil.copy2(ch["image"], img)
        lines.append(f"file '{img}'")
        lines.append(f"duration {dur:.3f}")
    # concat demuxer 需要最后一个文件重复一次
    if chapters:
        lines.append(f"file '{tmp / f'ch_{chapters[-1][chr(39)+chr(39)] if False else chapters[-1][chr(39)+chr(39)] if False else 0:04d}'.name}'" if False else "")
        # 简化:直接重复最后一张
        lines.append(f"file '{tmp / f'ch_{chapters[-1][chr(105)+chr(100)]:04d}'.name}'" if False else f"file '{tmp / ('ch_%04d.jpg' % chapters[-1]['id'])}'")
    concat_file.write_text("\n".join(lines), encoding="utf-8")

    # 2) 图片序列 → 无字幕视频
    silent_video = tmp / "video_nosub.mp4"
    subprocess.run(
        [str(FFMPEG), "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat_file), "-i", str(audio),
         "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-crf", "20", "-preset", "fast",
         "-c:a", "aac", "-b:a", "192k",
         "-shortest", str(silent_video)],
        check=True)

    # 3) 烧录字幕 + 水印
    srt_escaped = str(srt.resolve()).replace("\\", "/").replace(":", "\\:")
    vf = (f"subtitles='{srt_escaped}':force_style='Fontname=Microsoft YaHei,"
          f"FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
          f"BorderStyle=3,Outline=2,Alignment=2,MarginV=30'")
    if watermark:
        vf += (f",drawtext=text='{watermark}':fontfile='C\\:/Windows/Fonts/msyh.ttc':"
               f"fontsize=36:fontcolor=white@0.7:x=40:y=h-th-40")
    cmd = [str(FFMPEG), "-y", "-i", str(silent_video),
           "-vf", vf, "-c:v", "libx264", "-crf", "20", "-preset", "medium",
           "-c:a", "copy", str(output)]
    subprocess.run(cmd, check=True)

    shutil.rmtree(tmp, ignore_errors=True)


import shutil  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapters", required=True, type=Path,
                    help="章节 JSON(含 image/start/end)")
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--srt", required=True, type=Path)
    ap.add_argument("--watermark", default="wzx")
    ap.add_argument("-o", "--output", required=True, type=Path)
    args = ap.parse_args()
    chapters = json.loads(args.chapters.read_text(encoding="utf-8"))
    render_podcast(chapters, args.audio, args.srt, args.output, args.watermark)
    print(f"[✓] 播客版: {args.output} "
          f"({args.output.stat().st_size // 1048576}MB)")


if __name__ == "__main__":
    main()
