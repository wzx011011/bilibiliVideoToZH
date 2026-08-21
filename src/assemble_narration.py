"""中文旁白版音轨合成与原声低混。"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from pydub import AudioSegment

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def assemble_narration(
    runs: list[dict],
    parts_dir: Path,
    output: Path,
    total_duration: float,
) -> None:
    """把自然速度中文段按原片段落起点放到时间线上，不做语速拉伸。"""
    # 48 段按原片段落起点延迟后混合。直接用 ffmpeg，避免 pydub 在
    # Windows 上丢失 ffprobe 路径的问题。
    cmd = [str(FFMPEG), "-y"]
    labels = []
    cursor_ms = 0
    gap_ms = 250
    # 段落仍尽量从原片对应位置开始；若中文自然语速超过下一个段落起点，
    # 后段仅顺延到前段结束+短停顿，避免双人声音叠在一起。
    for index, run in enumerate(runs):
        part = parts_dir / f"item_{int(run['id']):04d}.wav"
        if not part.exists():
            raise FileNotFoundError(f"缺旁白段: {part}")
        part_duration = probe_duration(part)
        cmd += ["-i", str(part)]
        delay = max(int(run["source_start"] * 1000), cursor_ms)
        labels.append((index, delay))
        cursor_ms = delay + int(part_duration * 1000) + gap_ms
    filters = [f"[{index}:a]adelay={delay}|{delay}[n{index}]"
               for index, delay in labels]
    filters.append("".join(f"[n{index}]" for index, _ in labels)
                   + f"amix=inputs={len(labels)}:normalize=0,apad=pad_dur={int(total_duration) + 1}[out]")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd += ["-filter_complex", ";".join(filters), "-map", "[out]",
            "-t", str(total_duration), "-ar", "48000", "-ac", "1",
            "-c:a", "pcm_s16le", str(output)]
    subprocess.run(cmd, check=True)


def mix_original_audio(
    narration: Path,
    original_video: Path,
    output: Path,
    original_db: float = -22.0,
) -> None:
    """中文旁白为主轨，英文原声降低 original_db dB 作为氛围。"""
    filter_complex = (
        f"[0:a]volume={original_db}dB[orig];"
        "[1:a][orig]amix=inputs=2:duration=first:normalize=0[a]"
    )
    subprocess.run(
        [str(FFMPEG), "-y", "-i", str(original_video), "-i", str(narration),
         "-filter_complex", filter_complex, "-map", "[a]", "-c:a", "pcm_s16le",
         str(output)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", required=True, type=Path)
    ap.add_argument("--parts-dir", required=True, type=Path)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--narration-out", required=True, type=Path)
    ap.add_argument("--mixed-out", required=True, type=Path)
    ap.add_argument("--original-db", type=float, default=-22.0)
    args = ap.parse_args()
    runs = json.loads(args.runs.read_text(encoding="utf-8"))
    total = probe_duration(args.video)
    assemble_narration(runs, args.parts_dir, args.narration_out, total)
    mix_original_audio(args.narration_out, args.video, args.mixed_out, args.original_db)
    print(f"[✓] 旁白音轨: {args.narration_out}")
    print(f"[✓] 低混音轨: {args.mixed_out}")


if __name__ == "__main__":
    main()
