# -*- coding: utf-8 -*-
"""av_qc 幻觉段过滤:whisper 静音尾段的水印串不进 CER(不调真实 ASR)。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

_spec = importlib.util.spec_from_file_location("av_qc", SRC / "av_qc.py")
av_qc = importlib.util.module_from_spec(_spec)
sys.modules["av_qc"] = av_qc
_spec.loader.exec_module(av_qc)


def test_known_hallucinations_detected():
    assert av_qc.is_hallucination("请不吝点赞 订阅 转发 打赏支持明镜与点点栏目")
    assert av_qc.is_hallucination("优优独播剧场——YoYo Television Series Exclusive")
    assert av_qc.is_hallucination("字幕由XYZ提供")


def test_real_speech_never_matches():
    assert not av_qc.is_hallucination("带头的大太监刘瑾趁机揽权")
    assert not av_qc.is_hallucination("皇帝亲手砍翻一人,明军士气大振")
    assert not av_qc.is_hallucination("")


def test_drop_hallucination_keeps_order_and_content():
    segs = [(0.0, 2.0, "别看正德爱玩"),
            (29.3, 59.2, "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目"),
            (2.0, 4.0, "打仗他是真上")]
    kept = av_qc.drop_hallucination(segs)
    assert [s[2] for s in kept] == ["别看正德爱玩", "打仗他是真上"]
