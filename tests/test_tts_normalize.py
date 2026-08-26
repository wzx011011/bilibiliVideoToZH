# -*- coding: utf-8 -*-
"""TTS 朗读正则化单测。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tts_normalize import normalize_tts  # noqa: E402


def test_dash_number_removed():
    assert normalize_tts("GPT-5的发布") == "GPT5的发布"
    assert normalize_tts("GPT-4和GPT-5") == "GPT4和GPT5"
    assert normalize_tts("COVID-19疫情") == "COVID19疫情"


def test_suffix_lowercase():
    assert normalize_tts("GPT-4o的表现") == "GPT4o的表现"


def test_display_text_untouched_cases():
    # 单字母缩写、小写、中文连字符不动
    assert normalize_tts("A-1测试") == "A-1测试"
    assert normalize_tts("Gpt-5") == "Gpt-5"
    assert normalize_tts("中文-测试") == "中文-测试"


def test_mixed_sentence():
    s = "山姆发布了GPT-5,而GPT-4o仍在使用,涉及AI与LLM。"
    assert normalize_tts(s) == "山姆发布了GPT5,而GPT4o仍在使用,涉及AI与LLM。"
