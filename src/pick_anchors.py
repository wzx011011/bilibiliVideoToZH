# -*- coding: utf-8 -*-
"""从 VTT 字幕自动挑选声纹锚点:qwen3 读开头文本判断主持人/嘉宾时段。

访谈开头的对话内容足以区分角色(主持人介绍/提问 vs 嘉宾长回答)。
LLM 只给时间建议,最终声纹归属仍由 campplus 判定——锚点选错段
会导致全片单人(见 sam-gpt5 教训),建议建任务后抽查说话人分布。

用法:
  python pick_anchors.py --vtt x.en.vtt [--model qwen3:14b]
输出: {"A":[起,止],"B":[起,止]} (stdout)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HEAD_SEC = 900   # 只看开头 15 分钟
SPAN = 20        # 锚点段长约 20s


def parse_vtt(path: Path):
    cues = []
    ts = re.compile(r"(\d+):(\d+):(\d+)\.(\d+) --> (\d+):(\d+):(\d+)\.(\d+)")
    for block in path.read_text(encoding="utf-8").split("\n\n"):
        m = ts.search(block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        s = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        e = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = " ".join(l for l in block.splitlines()
                        if "-->" not in l and not l.strip().isdigit())
        text = re.sub(r"<[^>]+>", "", text).strip()
        if text:
            cues.append((s, e, text))
    return cues


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vtt", required=True, type=Path)
    ap.add_argument("--model", default="qwen3:14b")
    ap.add_argument("--url", default="http://127.0.0.1:11434/api/generate")
    args = ap.parse_args()

    cues = [c for c in parse_vtt(args.vtt) if c[0] < HEAD_SEC]
    if len(cues) < 10:
        raise SystemExit("vtt 头部 cue 不足")

    lines = [f"[{s:.0f}-{e:.0f}] {t}" for s, e, t in cues]
    head = "\n".join(lines)[:12000]
    prompt = (
        "以下是一段英文访谈视频开头部分的字幕(每行[起-止秒]文本)。\n"
        "请判断:1) 主持人(HOST)在介绍/提问的一段连续独白;"
        "2) 嘉宾(GUEST)的一段连续长回答(不是插话)。\n"
        "各选约20秒的连续时间段,时间必须落在字幕覆盖范围内且段内只有该角色说话。\n"
        "只输出 JSON:{\"A\":[起,止],\"B\":[起,止]}(A=主持人,B=嘉宾),不要解释。\n\n"
        + head
    )
    req = urllib.request.Request(
        args.url, data=json.dumps(
            {"model": args.model, "prompt": prompt, "stream": False,
             "options": {"num_predict": 2500}}).encode(),
        headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=300).read())
    out = re.sub(r"<think>.*?</think>", "", resp.get("response", ""),
                 flags=re.S)
    m = re.search(r"\{[^{}]*\"A\"[^{}]*\}", out)
    if not m:
        raise SystemExit(f"LLM 未给出锚点 JSON: {out[:200]}")
    anchors = json.loads(m.group(0))
    for k in ("A", "B"):
        s, e = float(anchors[k][0]), float(anchors[k][1])
        if e - s < 8 or s < 0:
            raise SystemExit(f"锚点 {k} 段过短/非法: {anchors}")
        anchors[k] = [round(s, 1), round(e, 1)]
    print(json.dumps(anchors))


if __name__ == "__main__":
    sys.exit(main())
