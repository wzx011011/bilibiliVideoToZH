# -*- coding: utf-8 -*-
"""broll 静图轮播预览:把分镜 PNG 按序拼成视频(硬切,无音频)。

用法:
  python work/make_slideshow.py --slug ming-16-sanzheng2 [--secs 8] [--all]
默认只拼分镜(排除 _bg 背景图);输出到 D:/<slug>-slideshow.mp4。
真实成片里每张的秒数 = hold(0~1 章节内占比)× 章节时长,由配音时间轴决定。
"""
import argparse
import json
import subprocess
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--slug", default="ming-16-sanzheng2")
ap.add_argument("--out", default="")
ap.add_argument("--secs", type=float, default=8.0, help="每张秒数")
ap.add_argument("--all", action="store_true", help="含 _bg 背景图")
args = ap.parse_args()

bdir = Path("work/broll") / args.slug
man = json.loads((bdir / "manifest.json").read_text(encoding="utf-8"))
items = sorted(k for k in man
               if (bdir / f"{k}.png").exists() and (args.all or not k.endswith("_bg")))
out = Path(args.out) if args.out else Path("D:/") / f"{args.slug}-slideshow.mp4"

lines = []
for k in items:
    lines.append(f"file '{(bdir / f'{k}.png').resolve().as_posix()}'")
    lines.append(f"duration {args.secs:.2f}")
lines.append(f"file '{(bdir / f'{items[-1]}.png').resolve().as_posix()}'")
lst = Path("work/_slideshow.txt")
lst.write_text("\n".join(lines), encoding="utf-8")

subprocess.run([
    "work/video-tools/ffmpeg.exe", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
    "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
           "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xE8DCC0,fps=30",
    "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
    str(out)], check=True)
lst.unlink()
print(f"{len(items)} 张 × {args.secs:.0f}s = {len(items) * args.secs:.0f}s -> {out}")
