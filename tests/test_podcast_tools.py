# -*- coding: utf-8 -*-
"""播客链工具单测:props 排布/分块 + 播客字幕切分(与 Podcast.tsx 对齐)。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from build_podcast_props import build_chapters, chunk_bounds  # noqa: E402
from podcast_srt import split_cues, fmt_ts  # noqa: E402


def _fake_probe_map(durs):
    return lambda p: durs[int(p.stem.split("_")[-1])]


def test_build_chapters_sequential_gaps(tmp_path, monkeypatch):
    """换人 0.7s/同人 0.45s;章 start/end 按实际音频时长累加。"""
    runs = [{"id": 0, "speaker": "A"}, {"id": 1, "speaker": "A"},
            {"id": 2, "speaker": "B"}]
    texts = {0: "甲", 1: "乙", 2: "丙"}
    monkeypatch.setattr("build_podcast_props.probe",
                        _fake_probe_map({0: 10.0, 1: 5.0, 2: 8.0}))
    ch, total = build_chapters(runs, texts, tmp_path, "audio-x",
                               "avatars/x", {"A": "主持人", "B": "嘉宾"})
    assert [c["speaker"] for c in ch] == ["A", "A", "B"]
    assert ch[0]["start"] == 0.0 and ch[0]["end"] == 10.0
    assert ch[1]["start"] == 10.45          # 同人 0.45
    assert ch[1]["end"] == 15.45
    assert ch[2]["start"] == 16.15          # 换人 0.7
    assert total == ch[2]["end"] == 24.15
    assert ch[0]["audioFile"] == "audio-x/0000.wav"
    assert ch[0]["avatarFile"] == "avatars/x/speaker-A.jpg"
    assert ch[0]["speakerName"] == "主持人"


def test_chunk_bounds_respects_limits():
    ch = [{"start": i * 60.0, "end": i * 60.0 + 50.0} for i in range(30)]
    edges = chunk_bounds(ch, 30 * 60.0, max_chapters=12, max_minutes=25.0)
    assert edges[0] == 0 and edges[-1] == int(30 * 60.0 * 30) + 90
    # 每块 ≤12 章:30 章 → ≥3 块;块内跨度 <25 分钟
    assert len(edges) - 1 >= 3
    for a, b in zip(edges, edges[1:]):
        assert (b - 1 - a) / 30 / 60 <= 25.0 + 1.0


def test_split_cues_matches_remotion_style():
    """句读优先切条 ≤32 字;短碎片合并。"""
    text = "这是一个测试句子。第二句比较长一些，包含逗号分隔的多个部分，用来验证切分逻辑的正确性；最后一句。"
    cues = split_cues(text)
    assert all(len(c) <= 32 for c in cues)
    assert "".join(cues) == text
    assert len(cues) >= 2


def test_fmt_ts():
    assert fmt_ts(3661.5) == "01:01:01,500"
    assert fmt_ts(0.0) == "00:00:00,000"
