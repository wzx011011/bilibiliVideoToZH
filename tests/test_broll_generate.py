# -*- coding: utf-8 -*-
"""broll.generate 姓名签(cast):prompt 改写与 OCR 校验的纯函数(不调真实 API)。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

_spec = importlib.util.spec_from_file_location(
    "broll_generate", SRC / "broll" / "generate.py")
broll_generate = importlib.util.module_from_spec(_spec)
sys.modules["broll_generate"] = broll_generate
_spec.loader.exec_module(broll_generate)

STYLE = "warm aged parchment paper, flat vector picture-book style, no text"


def test_build_prompt_appends_cast_clause_and_drops_no_text():
    beat = {"prompt": "the minister in crimson robes on the left, "
                      "the regent in yellow on the right",
            "cast": ["左·于谦", "右·朱祁钰"]}
    prompt = broll_generate.build_prompt(STYLE, beat)
    assert "no text" not in prompt
    assert "the left figure" in prompt and "the right figure" in prompt
    assert '"于谦"' in prompt and '"朱祁钰"' in prompt
    assert prompt.index("regent in yellow") < prompt.index("于谦")


def test_build_prompt_single_cast_without_position():
    prompt = broll_generate.build_prompt(STYLE, {"prompt": "a general.",
                                                 "cast": ["戚继光"]})
    assert "no text" not in prompt
    assert "the figure" in prompt and '"戚继光"' in prompt
    assert "a general." in prompt  # 场景句尾句号不重复


def test_build_prompt_plain_beat_unchanged():
    assert broll_generate.build_prompt(STYLE, {"prompt": "x"}) == STYLE + ". x"
    assert broll_generate.build_prompt("", {"prompt": "x"}) == "x"


def test_cast_names_strips_position_prefix():
    assert broll_generate.cast_names(
        {"cast": ["左·于谦", "中·王振", "右·朱祁钰", "戚继光"]}) == \
        ["于谦", "王振", "朱祁钰", "戚继光"]
    assert broll_generate.cast_names({"cast": ["", " "]}) == []
    assert broll_generate.cast_names({}) == []


def test_names_missing_tolerates_punctuation_but_not_wrong_char():
    assert broll_generate.names_missing("朱祁钰于谦", ["于谦", "朱祁钰"]) == []
    assert broll_generate.names_missing("左:于谦 | 右:朱祁钰", ["于谦", "朱祁钰"]) == []
    assert broll_generate.names_missing("朱祁钰", ["于谦", "朱祁钰"]) == ["于谦"]
    # 繁体/错字不算命中(歷史人名错字是硬伤,必须重生成)
    assert broll_generate.names_missing("朱祁鈺 于謙", ["于谦", "朱祁钰"]) == \
        ["于谦", "朱祁钰"]
    assert broll_generate.names_missing("", ["于谦"]) == ["于谦"]
