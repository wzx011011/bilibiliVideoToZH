# -*- coding: utf-8 -*-
"""播客版音频精修:解决语速偏快、边界爆音/电流声、双音色响度不一致。

对 48 个分段逐个做(单 ffmpeg 链):
  1. 70Hz 高通       —— 去低频嗡声/电流感
  2. 首尾静音切除     —— CosyVoice 偶发的尾噪
  3. atempo 0.93     —— 整体放慢 ~7%,更从容
  4. loudnorm        —— 主持人/Hinton 两路音色响度统一(I=-16)
  5. 12ms 淡入 + 90ms 淡出 —— 消除拼接点的咔哒/爆音

输入:work/studio/hinton-medicine-v2/work/narration/parts_doubao/item_*.wav
输出:work/podcast-studio/public/audio_polished/NNNN.wav
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "work/video-tools/ffmpeg.exe"

def build_filter(speed: float) -> str:
    tempo = "" if abs(speed - 1.0) < 1e-6 else f"atempo={speed},"
    return (
    "highpass=f=70,"
    "silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB,"
    "areverse,silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB,areverse,"
    + tempo +
    "loudnorm=I=-16:TP=-1.5:LRA=11,"
    "afade=t=in:st=0:d=0.012,"
    "areverse,afade=t=in:st=0:d=0.09,areverse"
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parts-dir", type=Path,
                    default=ROOT / "work/studio/hinton-medicine-v2/work/narration/parts_doubao")
    ap.add_argument("--out-dir", type=Path,
                    default=ROOT / "work/podcast-studio/public/audio_polished")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="1.0=原速;英文参考克隆时代用 0.93 放慢")
    args = ap.parse_args()
    parts_dir, out = args.parts_dir, args.out_dir
    speed = args.speed
    OUT = out
    OUT.mkdir(parents=True, exist_ok=True)
    parts = sorted(parts_dir.glob("item_*.wav"))
    for p in parts:
        dst = OUT / p.name.replace("item_", "")
        cmd = [str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
               "-i", str(p), "-af", build_filter(speed), "-ar", "24000", "-ac", "1", str(dst)]
        subprocess.run(cmd, check=True)
        print(f"  {dst.name}", flush=True)
    print(f"[✓] 精修 {len(parts)} 段 -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
