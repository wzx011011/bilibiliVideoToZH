"""旁白版中文字幕生成:时间轴与 assemble_narration 的放置逻辑严格一致。

每段旁白:起点 = max(原片段落起点, 前段结束 + 250ms),终点 = 起点 + 实际音频时长。
段内文本按句读切成字幕条(≤54 字两行容量,AGENTS 约定),时长按字数比例分摊。

用法:
  python narration_srt.py --runs work/<slug>/work/narration/runs.json \
      --parts-dir work/<slug>/work/narration/parts_doubao -o out.srt
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FFPROBE = ROOT / "work" / "video-tools" / "ffprobe.exe"
MAX_CHARS = 54  # 两行字幕容量
GAP_MS = 250    # 与 assemble_narration 一致


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True).stdout.strip()
    return float(out)


def split_cues(text: str) -> list[str]:
    """按句末标点切条,超 54 字再按逗号切,碎片合并;保持语义完整优先。"""
    parts = [p.strip() for p in re.split(r"(?<=[。？！；])", text) if p.strip()]
    pieces: list[str] = []
    for p in parts:
        if len(p) <= MAX_CHARS:
            pieces.append(p)
            continue
        subs = [s.strip() for s in re.split(r"(?<=[，、：])", p) if s.strip()]
        buf = ""
        for s in subs:
            if buf and len(buf) + len(s) > MAX_CHARS:
                pieces.append(buf)
                buf = s
            else:
                buf += s
        if buf:
            pieces.append(buf)
    # 相邻短条合并(仍 ≤ 54),避免一闪而过
    merged: list[str] = []
    for p in pieces:
        if merged and len(merged[-1]) + len(p) <= MAX_CHARS and len(p) < 12:
            merged[-1] += p
        else:
            merged.append(p)
    return merged


def fmt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", required=True, type=Path)
    ap.add_argument("--items", required=True, type=Path,
                    help="配音文本 JSON([{id,text,speaker}],即实际合成所用译文)")
    ap.add_argument("--parts-dir", required=True, type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    args = ap.parse_args()

    runs = json.loads(args.runs.read_text(encoding="utf-8"))
    texts = {it["id"]: it["text"] for it in
             json.loads(args.items.read_text(encoding="utf-8"))}
    rows, cursor_ms, idx = [], 0, 1
    for run in runs:
        part = args.parts_dir / f"item_{int(run['id']):04d}.wav"
        dur = probe_duration(part)
        start_ms = max(int(run["source_start"] * 1000), cursor_ms)
        end_ms = start_ms + int(dur * 1000)
        cursor_ms = end_ms + GAP_MS
        cues = split_cues(texts.get(int(run["id"]), run.get("text", "")))
        total = sum(len(c) for c in cues) or 1
        t = start_ms
        for c in cues:
            span = int((end_ms - start_ms) * len(c) / total)
            rows.append((idx, fmt_ts(t / 1000), fmt_ts((t + span) / 1000), c))
            t += span
            idx += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for i, a, b, c in rows:
            f.write(f"{i}\n{a} --> {b}\n{c}\n\n")
    print(f"[✓] {len(rows)} 条字幕 -> {args.output}")


if __name__ == "__main__":
    main()
