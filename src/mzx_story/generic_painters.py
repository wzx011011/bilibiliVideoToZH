# -*- coding: utf-8 -*-
"""通用兜底 painters:矢量层已从成品退场(2026-10-14 用户定),本模块仅为渲染管线提供
必经的 PAINTERS/CAMS 占位与无图时的兜底画面,正常生产中不可见。

用法:内容 JSON 写 "painters": "generic_painters.py" 即可,无需每集手写场景模块。
bind(content) 时按章节标题自动构建 s1..sN 画法;skin 用中性羊皮配色。
"""
from __future__ import annotations

_STATE: dict = {}
C: dict = {}


def bind(content: dict) -> None:
    _STATE["content"] = content
    globals()["PAINTERS"] = {ch["kind"]: _make(ch) for ch in content["chapters"]}


def skin(vr) -> None:
    _STATE["vr"] = vr
    C.update(PAPER=(238, 233, 222), INK=(42, 38, 32), RED=(168, 60, 46),
             DARKRED=(122, 40, 30), GRAY=(133, 127, 116))
    vr.PAPER = C["PAPER"]; vr.INK = C["INK"]; vr.RED = C["RED"]
    vr.DARKRED = C["DARKRED"]; vr.BLUE = C["DARKRED"]; vr.GRAY = C["GRAY"]


def _make(ch: dict):
    title = str(ch.get("title", ""))
    year = ch.get("year", "")

    def painter(b, _t=title, _y=year):
        b.tag((140, 175), _y + " · " + _t if _y else _t, (.04, .14),
              fill=C["DARKRED"], size=34)
        b.text((150, 280), _t, 60, C["INK"], .06, .18)
        b.line((150, 890), (1770, 890), C["GRAY"], 2, .04, .10, amp=1.0)
        b.bubble(1480, 760, 340, 104, (.6, .76))
        b.text((1360, 732), "本拍插画缺失兜底", 26, C["GRAY"], .64, .78)
    return painter


PAINTERS: dict = {}
CAMS = {f"s{i}": (lambda p: (960, 552, 0.80)) for i in range(1, 13)}
