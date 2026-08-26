# -*- coding: utf-8 -*-
"""TTS 朗读文本正则化:显示写法与读音写法分离。

CosyVoice 对"大写缩写-数字"的连字符读音不稳(GPT-5 会读出连字符),
字幕要显示 GPT-5 而朗读要读 GPT5 —— 显示文本保持原样,仅送入 TTS
的副本做转换。

规则(保守,只动确定有益的):
  GPT-5 → GPT5     (大写缩写-数字,连字符去掉;COVID-19 等同理)
  GPT-4o → GPT4o   (缩写-数字+小写后缀)
"""
from __future__ import annotations

import re

# 大写字母缩写 + 连字符 + 数字(可带小写字母后缀)
_DASH_NUM = re.compile(r"\b([A-Z]{2,})-(\d+[a-z]?)")


def normalize_tts(text: str) -> str:
    return _DASH_NUM.sub(r"\1\2", text)
