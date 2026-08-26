# -*- coding: utf-8 -*-
"""播客版中文字幕:从 Remotion props 直接生成,时间轴与画面字幕严格一致。

props 章节时间轴 = build_podcast_props 的顺序排布(换人 0.7s/同人 0.45s),
每章文本用与 Podcast.tsx splitCues 相同的切法(≤32 字,句读优先,字数占比分摊),
保证 SRT 与成片内嵌字幕逐条对应。

用法:
  python podcast_srt.py --props work/podcast-studio/props-<slug>.json -o out.srt
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MAX_CHARS = 32  # 与 Podcast.tsx MAX_CUE_CHARS 一致(单行)


def split_cues(text: str) -> list[str]:
    """与 Podcast.tsx splitCues 相同:句末标点切,超长按逗号切,短条合并。"""
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
    merged: list[str] = []
    for p in pieces:
        if merged and len(merged[-1]) + len(p) <= MAX_CHARS and len(p) < 10:
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
    ap.add_argument("--props", required=True, type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    args = ap.parse_args()

    props = json.loads(args.props.read_text(encoding="utf-8"))
    rows, idx = [], 1
    for ch in props["chapters"]:
        start, end = float(ch["start"]), float(ch["end"])
        cues = split_cues(ch.get("text", ""))
        total = sum(len(c) for c in cues) or 1
        t = start
        for c in cues:
            span = (end - start) * len(c) / total
            rows.append((idx, fmt_ts(t), fmt_ts(t + span), c))
            t += span
            idx += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for i, a, b, c in rows:
            f.write(f"{i}\n{a} --> {b}\n{c}\n\n")
    print(f"[✓] {len(rows)} 条字幕 -> {args.output}")


if __name__ == "__main__":
    main()
