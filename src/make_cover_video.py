"""把豆包朗读音频 + 字幕 + 封面图合成视频。

生成"静态封面图 + 中文字幕"的视频，按豆包语音节奏走，不和原视频对齐。

用法：
  python make_cover_video.py --audio episode-01-doubao-full.mp3 \\
      --srt episode-01.srt --cover cover.jpg --output episode-01.mp4

若无封面图，用 --gen-cover 自动生成一张标题图。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def gen_cover(title: str, subtitle: str, output: Path,
              width: int = 1920, height: int = 1080) -> None:
    """用 PIL 生成一张简洁的封面图。"""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), (26, 58, 92))  # 深蓝底
    draw = ImageDraw.Draw(img)

    # 尝试加载中文字体
    font_paths = [
        "C:/Windows/Fonts/msyhbd.ttc",   # 微软雅黑粗体
        "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",   # 黑体
    ]
    title_font = subtitle_font = None
    for fp in font_paths:
        try:
            title_font = ImageFont.truetype(fp, 96)
            subtitle_font = ImageFont.truetype(fp, 48)
            break
        except (OSError, IOError):
            continue
    if title_font is None:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()

    # 居中绘制标题
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((width - tw) / 2, height / 2 - th - 40), title,
              fill=(255, 255, 255), font=title_font)

    # 副标题
    bbox2 = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    sw = bbox2[2] - bbox2[0]
    draw.text(((width - sw) / 2, height / 2 + 60), subtitle,
              fill=(200, 220, 255), font=subtitle_font)

    img.save(str(output), "JPEG", quality=95)
    print(f"[✓] 封面图生成: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="封面图 + 音频 + 字幕 → 视频（按音频节奏，不与原视频对齐）")
    parser.add_argument("--audio", required=True, type=Path, help="豆包朗读音频 mp3/wav")
    parser.add_argument("--srt", required=True, type=Path, help="中文字幕 SRT")
    parser.add_argument("--cover", type=Path, default=None, help="封面图（不传则自动生成）")
    parser.add_argument("--output", "-o", type=Path, default=Path("episode.mp4"))
    parser.add_argument("--gen-cover", action="store_true",
                        help="无封面图时自动生成标题图")
    parser.add_argument("--title", default="哈佛积极心理学",
                        help="自动生成封面时的标题")
    parser.add_argument("--subtitle", default="Tal Ben-Shahar",
                        help="自动生成封面时的副标题")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--watermark", default=None,
                        help="左下角水印文字（如 wzx）")
    args = parser.parse_args()

    if not args.audio.exists():
        sys.exit(f"[✗] 音频不存在: {args.audio}")
    if not args.srt.exists():
        sys.exit(f"[✗] 字幕不存在: {args.srt}")

    # 封面图
    cover = args.cover
    if cover is None or not cover.exists():
        if args.gen_cover:
            # 用 --cover 指定的路径，或默认输出目录
            cover = cover or (args.output.parent / "cover.jpg")
            gen_cover(args.title, args.subtitle, cover, args.width, args.height)
            print(f"[✓] 生成封面: {cover}")
        else:
            sys.exit("[✗] 无封面图，加 --gen-cover 自动生成，或 --cover 指定")

    duration = probe_duration(args.audio)
    print(f"音频: {args.audio.name} ({duration:.0f}s = {duration / 60:.1f}分钟)")
    print(f"字幕: {args.srt.name}")
    print(f"封面: {cover.name} ({args.width}x{args.height})")

    # ffmpeg: 静态封面图循环 + 音频 + 字幕烧录 + 水印
    # subtitles 滤镜需要 SRT 路径用正斜杠/转义
    srt_escaped = str(args.srt.resolve()).replace("\\", "/").replace(":", "\\:")
    vf = f"subtitles='{srt_escaped}':force_style='Fontname=Microsoft YaHei," \
         f"FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000," \
         f"BorderStyle=3,Outline=2,Alignment=2,MarginV=30'"

    # 左下角水印（drawtext，用微软雅黑避免 Fontconfig 问题）
    if args.watermark:
        wm = args.watermark.replace("'", r"\'")
        vf += (
            f",drawtext=fontfile='C\\:/Windows/Fonts/msyh.ttc':"
            f"text='{wm}':fontcolor=white@0.7:fontsize=36:"
            f"x=40:y=h-th-40"
        )

    cmd = [
        str(FFMPEG), "-y", "-loglevel", "error",
        "-loop", "1", "-i", str(cover),
        "-i", str(args.audio),
        "-vf", vf,
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(args.output),
    ]
    print("合成中...")
    subprocess.run(cmd, check=True)
    out_size = args.output.stat().st_size / 1024 / 1024
    print(f"\n[✓] 完成: {args.output} ({out_size:.1f}MB)")


if __name__ == "__main__":
    main()
