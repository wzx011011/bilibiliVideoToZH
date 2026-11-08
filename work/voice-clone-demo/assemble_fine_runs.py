"""把相邻同说话人的细槽音频合并成连续说话段，按原时间轴放置(保音高慢放)。

已参数化(默认值 = Hinton 试点原值):
  python assemble_fine_runs.py --slots fine/slots.json \\
      --parts-dir fine/parts --total 2193.15 --out interview-zh-fine.wav
--total 不给时自动取槽最大 end(中文音频与原片等长由调用方保证;
原片保留渲染时以视频轨为准)。
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent
PILOT = ROOT / "interview-pilot"
FINE = PILOT / "fine"
FFMPEG = ROOT.parent / "video-tools" / "ffmpeg.exe"


def _rel(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else ROOT / q


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slots", default=str(FINE / "slots.json"))
    ap.add_argument("--parts-dir", default=str(FINE / "parts"))
    ap.add_argument("--total", type=float, default=None,
                    help="目标总时长秒;缺省=槽最大 end")
    ap.add_argument("--out", default=str(PILOT / "interview-zh-fine.wav"))
    ap.add_argument("--runs-out", default=str(PILOT / "fine-runs.json"))
    ap.add_argument("--merge-gap", type=float, default=0.8)
    ap.add_argument("--atempo-min", type=float, default=0.65)
    ap.add_argument("--atempo-max", type=float, default=1.18)
    args = ap.parse_args()

    slots = json.loads(_rel(args.slots).read_text(encoding="utf-8"))
    parts_dir = _rel(args.parts_dir)
    out_path = _rel(args.out)
    runs_path = _rel(args.runs_out)
    total = args.total or max(s["end"] for s in slots)

    # 分段文件命名自动识别:generate_fine_audio 用 slot_NNN.wav,
    # generate_voice(v2 平台)用 item_NNNN.wav
    def part_path(i: int) -> Path:
        for name in (f"slot_{i:03d}.wav", f"item_{i:04d}.wav"):
            p = parts_dir / name
            if p.exists():
                return p
        raise FileNotFoundError(f"parts 里找不到 id={i} 的分段文件")

    # 相邻同人槽合并成连续说话段
    runs = []
    for s in slots:
        if runs and s["speaker"] == runs[-1]["speaker"] \
                and s["start"] - runs[-1]["end"] <= args.merge_gap:
            runs[-1]["end"] = s["end"]
            runs[-1]["ids"].append(s["id"])
        else:
            runs.append({"speaker": s["speaker"], "start": s["start"],
                         "end": s["end"], "ids": [s["id"]]})

    sr = torchaudio.load(str(part_path(slots[0]["id"])))[1]
    canvas = torch.zeros(1, int(total * sr))
    speech = 0.0
    groups = []
    for r in runs:
        pieces = []
        for i in r["ids"]:
            w, _ = torchaudio.load(str(part_path(i)))
            pieces.append(w)
            speech += w.shape[1] / sr
        slotdur = r["end"] - r["start"]
        total_dur = sum(x.shape[1] for x in pieces) / sr
        # 同人相邻槽之间的剩余空间均分成自然停顿
        extra = max(0.0, slotdur - total_dur)
        gap = extra / (len(pieces) - 1) if len(pieces) > 1 else 0.0
        merged = []
        for j, x in enumerate(pieces):
            merged.append(x)
            if j + 1 < len(pieces) and gap > 0:
                merged.append(torch.zeros(1, int(gap * sr)))
        wav = torch.cat(merged, dim=1)
        # 段落整体保音高慢放,限幅避免极端
        rate = wav.shape[1] / sr / slotdur if slotdur else 1.0
        if rate < 0.99 or rate > 1.03:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                src = Path(f.name)
            torchaudio.save(str(src), wav, sr)
            rate = max(args.atempo_min, min(args.atempo_max, rate))
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                dst = Path(f.name)
            subprocess.run([str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
                            "-i", str(src), "-af", f"atempo={rate:.5f}",
                            "-ar", str(sr), str(dst)], check=True)
            wav, _ = torchaudio.load(str(dst))
            src.unlink(missing_ok=True)
            dst.unlink(missing_ok=True)
        off = int(r["start"] * sr)
        end = min(off + wav.shape[1], canvas.shape[1])
        if end > off:
            canvas[:, off:end] += wav[:, :end - off]
        groups.append({**r, "slot": slotdur,
                       "speech": wav.shape[1] / sr, "atempo": rate})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out_path), canvas, sr)
    runs_path.write_text(json.dumps(groups, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    coverage = speech / sum(x["slot"] for x in groups)
    print(f"slots={len(slots)} runs={len(runs)} speech={speech:.1f}s "
          f"coverage={coverage:.3f} -> {out_path}")


if __name__ == "__main__":
    main()
