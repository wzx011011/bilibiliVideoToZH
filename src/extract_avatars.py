# -*- coding: utf-8 -*-
"""从原片锚点时刻提取播客头像:截帧 + 居中方形裁剪。

anchors 是声纹锚点(每说话人一段单人发言),取中点时刻截帧,
按画面高度居中裁正方形再缩到 768px。两人同框/构图偏移时可
手工替换同名文件后只重跑渲染阶段,无需重配音。

用法:
  python extract_avatars.py --video a.mp4 \
      --anchors '{"A":[60,80],"B":[300,320]}' --out-dir work/podcast-studio/public/avatars/<slug>
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
SIZE = 768


def grab(video: Path, at: float, out: Path) -> None:
    tmp = out.with_suffix(".tmp.png")
    subprocess.run([str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", str(at), "-i", str(video),
                    "-frames:v", "1", str(tmp)], check=True)
    img = Image.open(tmp)
    w, h = img.size
    side = min(w, h)
    box = ((w - side) // 2, (h - side) // 2,
           (w - side) // 2 + side, (h - side) // 2 + side)
    img.crop(box).resize((SIZE, SIZE), Image.LANCZOS).save(out, quality=90)
    tmp.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--anchors", required=True,
                    help='{"A":[起,止],"B":[起,止]}')
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    anchors = json.loads(args.anchors)
    for spk, (a0, a1) in anchors.items():
        out = args.out_dir / f"speaker-{spk}.jpg"
        if out.exists():
            print(f"[跳过] {out} 已存在(人工替换后可保留)")
            continue
        grab(args.video, (float(a0) + float(a1)) / 2, out)
        print(f"[✓] {spk} @ {(float(a0) + float(a1)) / 2:.1f}s -> {out}")


if __name__ == "__main__":
    main()
