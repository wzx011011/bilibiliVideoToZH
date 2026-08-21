"""旁白版双语字幕合成:中上英下同一时间块。

输入:
- runs.json(旁白段:source_start/source_end/source_ids/text)
- slots.json(英文原文按 id)
输出 SRT:每条 = 中文(有标点)在上,对应段的英文原文在下,合成一句。
不做逐词对齐,以旁白段为最小单位,保证时间与旁白语音一致。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _to_ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def normalize_zh(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


# YouTube 自动转写常带的填充/噪音词
_FILLERS = re.compile(
    r"\b(?:uh|um|ah|er|hmm|like you know|you know|kind of|sort of)\b",
    re.IGNORECASE)


def normalize_en(text: str) -> str:
    text = _FILLERS.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compose_bilingual(runs: list[dict], slots: list[dict]) -> list[tuple]:
    """runs + 英文原文 → [(start,end,中文,英文)]。"""
    zh_by_id = {r["id"]: r["text"] for r in runs}
    en_by_id = {s["id"]: s["text"] for s in slots}
    out = []
    for r in runs:
        zh = zh_by_id.get(r["id"], "").strip()
        en_parts = []
        for i in r.get("source_ids", []):
            t = en_by_id.get(i)
            if t:
                en_parts.append(t.strip())
        en = " ".join(en_parts).strip()
        out.append((r["source_start"], r["source_end"], zh, en))
    return out


def write_bilingual_srt(rows, out: Path) -> None:
    lines = []
    for i, (start, end, zh, en) in enumerate(rows, 1):
        lines.append(str(i))
        lines.append(f"{_to_ts(start)} --> {_to_ts(end)}")
        if zh:
            lines.append(normalize_zh(zh))
        if en:
            lines.append(normalize_en(en).strip())
        lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", required=True, type=Path)
    ap.add_argument("--slots", required=True, type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    args = ap.parse_args()
    runs = json.loads(args.runs.read_text(encoding="utf-8"))
    slots = json.loads(args.slots.read_text(encoding="utf-8"))
    rows = compose_bilingual(runs, slots)
    write_bilingual_srt(rows, args.output)
    print(f"[✓] 双语字幕 {len(rows)} 条 -> {args.output}")


if __name__ == "__main__":
    main()
