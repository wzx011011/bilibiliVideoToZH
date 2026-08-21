"""中文旁白版的语义段落编排。

把细粒度字幕槽合并为 30~90 秒的连续语义段：同说话人、间隔较短、
不超过最大源时长才合并。每段在中文音轨中按其原片起点自然朗读，
不做 atempo 强行拉伸；段后保留静音，原英文音轨以低音量补氛围。
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _join_zh(parts: list[str]) -> str:
    """合并槽译文，保留已有句末标点，避免段内生硬拼接。"""
    out: list[str] = []
    for text in parts:
        text = text.strip()
        if not text:
            continue
        if out and not re.search(r"[。！？；…]$", out[-1]):
            out[-1] += "。"
        out.append(text)
    return " ".join(out)


def build_runs(
    slots: list[dict],
    zh: dict[str, str],
    max_duration: float = 90.0,
    max_gap: float = 6.0,
) -> list[dict]:
    """slots + 中文译文 → 适合自然旁白的连续段。

    不跨说话人；源槽间隔超过 max_gap 或段源时长超过 max_duration 时断段。
    返回项含 source_start/source_end，供自然速度音频放回原片时间轴。
    """
    runs: list[dict] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        current["id"] = len(runs)
        current["duration"] = round(
            current["source_end"] - current["source_start"], 3
        )
        current["text"] = _join_zh(current.pop("texts"))
        runs.append(current)
        current = None

    for slot in sorted(slots, key=lambda x: x["start"]):
        text = zh.get(str(slot["id"]), "").strip()
        if not text:
            continue
        if current:
            same_speaker = current["speaker"] == slot["speaker"]
            gap = slot["start"] - current["source_end"]
            span = slot["end"] - current["source_start"]
            if same_speaker and gap <= max_gap and span <= max_duration:
                current["source_end"] = slot["end"]
                current["source_ids"].append(slot["id"])
                current["texts"].append(text)
                continue
            flush()
        current = {
            "speaker": slot["speaker"],
            "source_start": round(slot["start"], 3),
            "source_end": round(slot["end"], 3),
            "source_ids": [slot["id"]],
            "texts": [text],
        }
    flush()
    return runs


def save_runs(runs: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
