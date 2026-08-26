"""interview_lib 单测:说话人分离、分角色分块、提示词、多音色对齐校验。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import interview_lib as ilib


# ======================== diarize_alternating ========================

def test_diarize_alternating_two_speakers():
    """停顿 > 阈值处换人,双人交替。"""
    segs = [
        (0.0, 2.0, "Hello everyone."),      # A
        (2.0, 4.0, "welcome to the show."), # A(停顿 0,同 turn)
        (6.0, 8.0, "Thanks for having me."),  # gap=2.0 → B
        (10.5, 12.0, "Great to be here."),    # gap=2.5 → A
    ]
    turns = ilib.diarize_alternating(segs, speakers=2)
    assert [t["speaker"] for t in turns] == ["A", "B", "A"]
    assert turns[0]["text"] == "Hello everyone. welcome to the show."
    assert turns[1]["start"] == 6.0


def test_diarize_single_speaker_degrades():
    """speakers=1 时全部归 A。"""
    segs = [(0.0, 2.0, "甲"), (5.0, 8.0, "乙")]
    turns = ilib.diarize_alternating(segs, speakers=1)
    assert len(turns) == 1
    assert turns[0]["speaker"] == "A"
    assert "甲" in turns[0]["text"] and "乙" in turns[0]["text"]


def test_diarize_short_gap_same_turn():
    """停顿 ≤ 阈值不换人。"""
    segs = [(0.0, 2.0, "a"), (2.8, 4.0, "b")]  # gap=0.8 < 1.2
    turns = ilib.diarize_alternating(segs, speakers=2)
    assert len(turns) == 1


def test_diarize_empty():
    assert ilib.diarize_alternating([], speakers=2) == []


# ======================== build_chunks / split_turn_text ========================

def test_split_turn_text_keeps_short():
    assert ilib.split_turn_text("短句。") == ["短句。"]


def test_split_turn_text_splits_long_at_sentence():
    text = "句子一。 " * 500  # 2000 字,句号分句
    parts = ilib.split_turn_text(text, max_chars=100)
    assert all(len(p) <= 100 for p in parts)
    assert sum(len(p) for p in parts) >= 1900  # 内容不丢


def test_build_chunks_records_speaker_and_order():
    turns = [
        {"speaker": "A", "start": 0, "end": 10, "text": "主持人问了一个问题?"},
        {"speaker": "B", "start": 10.5, "end": 20, "text": "嘉宾回答。嘉宾继续回答。"},
    ]
    chunks = ilib.build_chunks(turns)
    assert [c["chunk_index"] for c in chunks] == [1, 2]
    assert [c["speaker"] for c in chunks] == ["A", "B"]
    assert chunks[0]["turn_start"] == 0


def test_build_chunks_long_turn_split_same_speaker():
    turns = [{"speaker": "B", "start": 0, "end": 100,
              "text": "很长的一句话。" * 300}]
    chunks = ilib.build_chunks(turns, max_chars=100)
    assert len(chunks) > 1
    assert all(c["speaker"] == "B" for c in chunks)


# ======================== build_prompt ========================

def test_prompt_en_translation():
    p = ilib.build_prompt("Hello world", "B", "en", {"B": "马斯克"})
    assert "翻译" in p
    assert "马斯克" in p
    assert "Hello world" in p


def test_prompt_zh_polish():
    p = ilib.build_prompt("大家好", "A", "zh", {"A": "主持人"})
    assert "标点" in p
    assert "大家好" in p
    assert "翻译" not in p


def test_prompt_default_roles():
    """未提供角色名时 A=主持人(先开口),B=嘉宾。"""
    pa = ilib.build_prompt("x", "A", "en")
    pb = ilib.build_prompt("y", "B", "en")
    assert "主持人" in pa
    assert "嘉宾" in pb
