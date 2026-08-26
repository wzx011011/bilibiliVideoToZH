"""原片保留渲染:原视频画面 + 中文配音音轨 + libass 烧录中文字幕 + 水印。

与 make_cover_video(封面图模式)互补,用于访谈/演讲类原片保留成品。

用法:
  python render_original.py --video hinton.mp4 --audio zh-fine.wav \\
      --srt zh-fine.srt --watermark wzx -o hinton-zh.mp4
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"

# 字幕样式与 make_cover_video 的 force_style 一致
SUBTITLE_STYLE = ("Fontname=Microsoft YaHei,FontSize=22,"
                  "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                  "BorderStyle=3,Outline=2,Alignment=2,MarginV=30")
# 水印样式与访谈试点成品一致:雅黑 36 白 70% 左下
WATERMARK_STYLE = ("fontfile='C\\:/Windows/Fonts/msyh.ttc':fontsize=36:"
                   "fontcolor=white@0.7:x=40:y=h-th-40")


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def render(video: Path, audio: Path, srt: Path, out: Path,
           watermark: str = "wzx", crf: int = 20) -> None:
    srt_escaped = str(srt.resolve()).replace("\\", "/").replace(":", "\\:")
    vf = f"subtitles='{srt_escaped}':force_style='{SUBTITLE_STYLE}'"
    if watermark:
        vf += (f",drawtext=text='{watermark}':{WATERMARK_STYLE}")
    cmd = [
        str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", vf,
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video", required=True, type=Path, help="原视频")
    ap.add_argument("--audio", required=True, type=Path, help="中文配音音轨")
    ap.add_argument("--srt", required=True, type=Path, help="中文字幕 SRT")
    ap.add_argument("--watermark", default="wzx")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("-o", "--output", required=True, type=Path)
    args = ap.parse_args()

    vd, ad = _probe_duration(args.video), _probe_duration(args.audio)
    print(f"视频 {vd:.1f}s / 音频 {ad:.1f}s" +
          (f"(音轨较短,尾部静音)" if ad < vd - 1 else ""))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    render(args.video, args.audio, args.srt, args.output,
           watermark=args.watermark, crf=args.crf)
    size = args.output.stat().st_size / 1048576
    print(f"[✓] 完成: {args.output} ({size:.1f}MB)")


if __name__ == "__main__":
    main()
