"""旁白版双语字幕合成:中上英下同一时间块,长段自动切分为短字幕条。

每条字幕限制:中文 ≤ 2 行(约 54 字),英文按字符比例 ≤ 2 行(约 100 字符)。
时间在段内按中文字符比例线性分摊,保证与旁白语音大致同步。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MAX_CN_PER_CUE = 52          # 每条中文字符上限(两行)
MAX_EN_PER_CUE = 96          # 每条英文字符上限
MIN_CUE_SEC = 1.2            # 单条最短显示时长


def _to_ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def normalize_zh(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_FILLERS = re.compile(
    r"\b(?:uh|um|ah|er|hmm|you know|kind of|sort of)\b", re.IGNORECASE)


def normalize_en(text: str) -> str:
    text = _FILLERS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_by_len(text: str, max_len: int) -> list[str]:
    """按句末标点优先切分,超长再硬切。"""
    parts = re.split(r"(?<=[。！？；.!?;])\s*", text.strip())
    out, cur = [], ""
    for p in parts:
        if not p:
            continue
        if cur and len(cur) + len(p) > max_len:
            out.append(cur)
            cur = ""
        while len(p) > max_len:
            out.append(p[:max_len])
            p = p[max_len:]
        cur += p
    if cur:
        out.append(cur)
    return out or [text]


def compose_bilingual(runs: list[dict], slots: list[dict]) -> list[tuple]:
    """runs + 英文原文 → [(start,end,中文,英文)] 长段自动切短。"""
    zh_by_id = {r["id"]: r["text"] for r in runs}
    en_by_id = {s["id"]: s["text"] for s in slots}
    rows = []
    for r in runs:
        zh = normalize_zh(zh_by_id.get(r["id"], ""))
        en_parts = []
        for i in r.get("source_ids", []):
            t = en_by_id.get(i)
            if t:
                en_parts.append(normalize_en(t))
        en = " ".join(en_parts)
        zh_parts = _split_by_len(zh, MAX_CN_PER_CUE)
        en_parts2 = _split_by_len(en, MAX_EN_PER_CUE) if en else []
        # 中英条数对齐:多的一侧均分给少的一侧
        n = max(len(zh_parts), len(en_parts2))
        zh_parts = zh_parts + [""] * (n - len(zh_parts))
        en_parts2 = en_parts2 + [""] * (n - len(en_parts2))
        span = (r["source_end"] - r["source_start"]) / n
        for k in range(n):
            s0 = r["source_start"] + span * k
            s1 = r["source_start"] + span * (k + 1)
            rows.append((s0, s1, zh_parts[k], en_parts2[k]))
    return rows


def write_bilingual_srt(rows, out: Path) -> None:
    lines = []
    idx = 0
    prev_end = 0.0
    for start, end, zh, en in rows:
        start = max(start, prev_end)
        if end - start < MIN_CUE_SEC:
            end = start + MIN_CUE_SEC
        prev_end = end
        idx += 1
        lines.append(str(idx))
        lines.append(f"{_to_ts(start)} --> {_to_ts(end)}")
        if zh:
            lines.append(zh)
        if en:
            lines.append(en)
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
