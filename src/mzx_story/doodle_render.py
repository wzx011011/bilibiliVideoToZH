# -*- coding: utf-8 -*-
"""明朝故事线·白板手绘"边画边讲"渲染器(靖难之役试点)。

画面语言:白板底 + 黑蓝马克笔抖动笔画 + 手写字 + 笔尖跟随,笔画随解说进度生长。
复用 gpt_explainer 的音频/时间轴/字幕/探测管线。

用法:
  python src/mzx_story/doodle_render.py --preview   # 无配音,出分镜中段+完成态拼图
  python src/mzx_story/doodle_render.py --render    # 配音就绪后出全片
"""
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[0]
sys.path.insert(0, str(SRC))

from gpt_explainer.render import (  # noqa: E402
    WIDTH, HEIGHT, FPS,
    assemble_audio, build_subtitle_cues, build_timeline, write_srt,
    _part_files, _probe_video, _cue_for,
)

ROOT = HERE.parents[1]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
CONTENT = HERE / "ming-01-jingnan.json"
OUT = Path("D:/mzx-ming01")

BOARD = (250, 250, 248)
BLACK = (38, 38, 42)
BLUE = (28, 62, 148)
RED = (176, 48, 42)
GRAY = (130, 130, 136)
INKBAND = (30, 30, 32)


def _font(size: int, hand: bool = True):
    names = ("STXINGKA.TTF", "simkai.ttf", "msyh.ttc") if hand else ("msyhbd.ttc",)
    for name in names:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def _jit(p0, p1, rng, amp=2.5):
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = max(3, int(length / 55))
    nx, ny = -(p1[1] - p0[1]), (p1[0] - p0[0])
    norm = math.hypot(nx, ny) or 1.0
    nx, ny = nx / norm, ny / norm
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append((p0[0] + (p1[0] - p0[0]) * t + nx * rng.uniform(-amp, amp),
                    p0[1] + (p1[1] - p0[1]) * t + ny * rng.uniform(-amp, amp)))
    pts[0], pts[-1] = p0, p1
    return pts


def _blob_pts(cx, cy, rx, ry, rng, amp=3.0, n=26):
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        k = 1 + rng.uniform(-amp / max(rx, 1), amp / max(rx, 1))
        pts.append((cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
    pts.append(pts[0])
    return pts


def _poly_len(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
               for i in range(len(pts) - 1))


def _partial(pts, f):
    if f >= 1.0:
        return pts, pts[-1]
    budget = _poly_len(pts) * max(0.0, f)
    out = [pts[0]]
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        d = math.hypot(x1 - x0, y1 - y0)
        if budget >= d:
            out.append((x1, y1)); budget -= d
        else:
            t = budget / max(d, 1e-6)
            tip = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            out.append(tip)
            return out, tip
    return out, out[-1]


class Board:
    """一集场景的白板:笔画/填充/文字都带时间窗,render(t) 画出该时刻。"""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.strokes: list[tuple[list, tuple, int, float, float]] = []
        self.fills: list[tuple[str, tuple, tuple, float, float]] = []
        self.texts: list[tuple[tuple, str, int, tuple, float, float, bool]] = []
        self.order: list[tuple[str, int]] = []

    def _reg(self, kind, idx, t0):
        self.order.append((kind, idx, t0))

    def line(self, p0, p1, color=BLACK, width=5, t0=0.0, t1=1.0, amp=2.5):
        self._reg("s", len(self.strokes), t0)
        self.strokes.append((_jit(p0, p1, self.rng, amp), color, width, t0, t1))

    def poly(self, pts, color=BLACK, width=5, t0=0.0, t1=1.0, close=False):
        seq = list(pts) + ([pts[0]] if close else [])
        flat = []
        for a, b in zip(seq, seq[1:]):
            flat.extend(_jit(a, b, self.rng)[:-1])
            flat.append(b)
        self._reg("s", len(self.strokes), t0)
        self.strokes.append((flat, color, width, t0, t1))

    def blob(self, cx, cy, rx, ry, color=BLACK, width=5, t0=0.0, t1=1.0):
        self._reg("s", len(self.strokes), t0)
        self.strokes.append((_blob_pts(cx, cy, rx, ry, self.rng), color, width, t0, t1))

    def fill(self, box, color, t0=0.0, radius=10):
        self._reg("f", len(self.fills), t0)
        self.fills.append(("rrect", box, color, t0, radius))

    def text(self, xy, s, size, color=BLACK, t0=0.0, t1=0.0, hand=True):
        self._reg("t", len(self.texts), t0)
        self.texts.append((xy, str(s), size, color, t0, t1 or t0 + 0.001, hand))

    # ---- 元素库 ----
    def castle(self, cx, cy, s, span, color=BLACK):
        t0, t1 = span
        f = lambda k: t0 + (t1 - t0) * k
        self.line((cx - 3 * s, cy), (cx - 3 * s, cy - 3 * s), color, 5, f(.0), f(.4))
        self.line((cx + 3 * s, cy), (cx + 3 * s, cy - 3 * s), color, 5, f(.0), f(.4))
        self.line((cx - 3 * s, cy - 3 * s), (cx + 3 * s, cy - 3 * s), color, 5, f(.3), f(.6))
        for i, x in enumerate((-3, -1.6, -0.2, 1.2, 2.6)):
            self.line((cx + x * s, cy - 3 * s), (cx + x * s, cy - 4 * s), color, 4,
                      f(.55), f(.85 + i * .01))
        self.blob(cx, cy - 0.2 * s, 0.8 * s, 0.9 * s, color, 4, f(.8), t1)

    def stickman(self, cx, cy, s, span, *, hat=None, sword=False, sweat=False,
                 blanket=False, raise_arm=False, color=BLACK):
        t0, t1 = span
        f = lambda k: t0 + (t1 - t0) * k
        self.blob(cx, cy - 3.2 * s, s * 1.05, s * 1.2, color, 5, f(.0), f(.18))
        self.line((cx, cy - 2.1 * s), (cx, cy + 0.6 * s), color, 5, f(.15), f(.35))
        if raise_arm:
            self.line((cx, cy - 1.2 * s), (cx - 1.5 * s, cy + 0.1 * s), color, 5, f(.3), f(.5))
            self.line((cx, cy - 1.2 * s), (cx + 1.7 * s, cy - 2.6 * s), color, 5, f(.3), f(.5))
        else:
            self.line((cx, cy - 1.2 * s), (cx - 1.5 * s, cy + 0.1 * s), color, 5, f(.3), f(.5))
            self.line((cx, cy - 1.2 * s), (cx + 1.5 * s, cy + 0.1 * s), color, 5, f(.3), f(.5))
        self.line((cx, cy + 0.6 * s), (cx - 1.1 * s, cy + 2.4 * s), color, 5, f(.45), f(.65))
        self.line((cx, cy + 0.6 * s), (cx + 1.1 * s, cy + 2.4 * s), color, 5, f(.45), f(.65))
        if hat == "crown":
            self.line((cx - 1.4 * s, cy - 4.4 * s), (cx + 1.4 * s, cy - 4.4 * s), color, 5, f(.65), f(.8))
            self.line((cx - 0.5 * s, cy - 4.4 * s), (cx - 0.7 * s, cy - 5.3 * s), color, 5, f(.7), f(.85))
            self.line((cx + 0.5 * s, cy - 4.4 * s), (cx + 0.7 * s, cy - 5.3 * s), color, 5, f(.75), f(.9))
        elif hat == "emperor":
            self.line((cx - 1.6 * s, cy - 4.5 * s), (cx + 1.6 * s, cy - 4.5 * s), color, 5, f(.65), f(.8))
            for x in (-1.6, 1.6):
                self.line((cx + x * s, cy - 4.5 * s), (cx + x * s, cy - 3.4 * s), color, 4, f(.75), f(.9))
                self.blob(cx + x * s, cy - 3.2 * s, 0.15 * s, 0.15 * s, color, 3, f(.85), t1)
        if sword:
            self.line((cx + 1.7 * s, cy - 2.6 * s), (cx + 3.2 * s, cy - 4.2 * s), color, 4, f(.8), t1)
        if sweat:
            for dx, dy in ((2.0, -4.2), (2.6, -3.4)):
                self.line((cx + dx * s, cy + dy * s), (cx + (dx + .3) * s, cy + (dy + .8) * s),
                          BLUE, 4, f(.6), t1)
        if blanket:
            self.blob(cx, cy - 0.7 * s, 2.3 * s, 2.5 * s, color, 5, f(.5), f(.9))

    def crowd(self, cx, cy, s, n, span, color=BLACK):
        t0, t1 = span
        step = (t1 - t0) / max(n, 1)
        for i in range(n):
            x = cx + i * 2.2 * s
            a = t0 + i * step
            b = a + step * 0.9
            self.blob(x, cy - 1.6 * s, 0.38 * s, 0.42 * s, color, 4, a, a + (b - a) * .4)
            self.line((x, cy - 1.2 * s), (x, cy + 0.4 * s), color, 4, a + (b - a) * .3, a + (b - a) * .6)
            self.line((x - 0.5 * s, cy + 1.2 * s), (x, cy + 0.4 * s), color, 4, a + (b - a) * .5, b)
            self.line((x + 0.5 * s, cy + 1.2 * s), (x, cy + 0.4 * s), color, 4, a + (b - a) * .5, b)

    def flame(self, cx, cy, s, span, color=BLACK):
        t0, t1 = span
        f = lambda k: t0 + (t1 - t0) * k
        self.poly([(cx - 1.2 * s, cy), (cx - 0.5 * s, cy - 1.8 * s),
                   (cx - 0.1 * s, cy - 0.6 * s), (cx + 0.4 * s, cy - 2.6 * s),
                   (cx + 0.9 * s, cy - 0.9 * s), (cx + 1.2 * s, cy)], color, 5, f(.0), f(.7))
        self.poly([(cx - 0.5 * s, cy), (cx - 0.1 * s, cy - 1.0 * s),
                   (cx + 0.2 * s, cy - 0.3 * s), (cx + 0.5 * s, cy)], RED, 4, f(.5), t1)

    def flag(self, cx, cy, s, span, color=BLACK):
        t0, t1 = span
        f = lambda k: t0 + (t1 - t0) * k
        self.line((cx, cy), (cx, cy - 7 * s), color, 5, f(.0), f(.4))
        self.poly([(cx, cy - 7 * s), (cx + 4.2 * s, cy - 6.3 * s),
                   (cx + 3.8 * s, cy - 4.6 * s), (cx, cy - 5.2 * s)], RED, 5, f(.35), t1)

    def bubble(self, cx, cy, w, h, span, color=BLACK):
        t0, t1 = span
        self.blob(cx, cy, w, h, color, 4, t0, t0 + (t1 - t0) * .7)
        self.line((cx - 0.3 * w, cy + h * .9), (cx - 0.9 * w, cy + h * 1.9), color, 4,
                  t0 + (t1 - t0) * .6, t1)
        self.line((cx + 0.1 * w, cy + h * .95), (cx - 0.4 * w, cy + h * 1.8), color, 4,
                  t0 + (t1 - t0) * .65, t1)

    def arrow(self, pts, span, color=BLUE, width=7):
        t0, t1 = span
        f = lambda k: t0 + (t1 - t0) * k
        self.poly(pts, color, width, f(.0), f(.85))
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        d = math.hypot(x1 - x0, y1 - y0) or 1.0
        ux, uy = (x1 - x0) / d, (y1 - y0) / d
        px, py = -uy, ux
        self.poly([(x0, y0), (x1 - ux * 26 + px * 14, y1 - uy * 26 + py * 14),
                   (x1 - ux * 26 - px * 14, y1 - uy * 26 - py * 14)], color, width, f(.8), t1)

    def xmark(self, cx, cy, s, span, color=RED):
        t0, t1 = span
        self.line((cx - s, cy - s), (cx + s, cy + s), color, 5, t0, t0 + (t1 - t0) * .5)
        self.line((cx - s, cy + s), (cx + s, cy - s), color, 5, t0 + (t1 - t0) * .5, t1)

    def bracket(self, x0, x1, y, span, color=BLACK):
        t0, t1 = span
        self.line((x0, y), (x1, y), color, 6, t0, t0 + (t1 - t0) * .6)
        self.line((x0, y), (x0, y - 22), color, 5, t0 + (t1 - t0) * .5, t1)
        self.line((x1, y), (x1, y - 22), color, 5, t0 + (t1 - t0) * .5, t1)

    # ---- 渲染 ----
    def render(self, t: float) -> Image.Image:
        img = Image.new("RGB", (WIDTH, HEIGHT), BOARD)
        d = ImageDraw.Draw(img)
        tip = None
        for kind_idx, (kind, idx, reg_t0) in zip(self.order, self.order):
            pass
        for i, (kind, idx, reg_t0) in enumerate(self.order):
            if t <= reg_t0:
                continue
            if kind == "s":
                pts, color, width, t0, t1 = self.strokes[idx]
                f = 1.0 if t >= t1 else (t - t0) / max(t1 - t0, 1e-6)
                seg, end = _partial(pts, min(1.0, f))
                if len(seg) >= 2:
                    d.line(seg, fill=color, width=width, joint="curve")
                    for x, y in seg[::6]:
                        d.ellipse((x - width * .45, y - width * .45,
                                   x + width * .45, y + width * .45), fill=color)
                if f < 1.0 and (tip is None or t0 >= tip[0]):
                    tip = (t0, end)
            elif kind == "f":
                _, box, color, t0, radius = self.fills[idx]
                d.rounded_rectangle(box, radius=radius, fill=color)
            else:
                xy, s, size, color, t0, t1, hand = self.texts[idx]
                f = 1.0 if t >= t1 else (t - t0) / max(t1 - t0, 1e-6)
                d.text(xy, s[:max(1, int(len(s) * min(1.0, f)) + (1 if f > 0 else 0))],
                       font=_font(size, hand), fill=color)
        return img


def seq_spans(n: int, start=0.03, end=0.97, overlap=0.82):
    step = (end - start) / n
    return [(start + i * step, start + (i + overlap) * step) for i in range(n)]


# ---------------- 场景编排(手绘分镜) ----------------

def p_s1(b: Board):
    b.line((150, 880), (1770, 880), GRAY, 3, .04, .10, amp=2.0)
    b.text((140, 110), "靖难之役", 150, BLACK, .06, .20)
    b.text((155, 320), "—— 叔叔和侄子的火并", 48, BLUE, .18, .27)
    b.fill((1720, 120, 1850, 250), RED, .88, radius=14)
    b.text((1736, 138), "壹", 84, BOARD, .90, .91)
    b.stickman(700, 660, 52, (.26, .44), hat="emperor")
    b.text((590, 800), "朱元璋·71岁", 40, BLUE, .40, .49)
    b.stickman(1050, 670, 46, (.42, .58), hat="crown")
    b.text((950, 805), "朱允炆·建文帝", 40, BLUE, .54, .62)
    b.stickman(1400, 660, 52, (.56, .74), hat="crown", sword=True)
    b.text((1290, 800), "燕王朱棣·北平", 40, BLUE, .70, .78)
    b.text((1190, 420), "？？", 110, RED, .76, .90)


def p_s2(b: Board):
    b.line((150, 900), (1770, 900), GRAY, 3, .04, .09, amp=2.0)
    b.castle(960, 760, 40, (.06, .18))
    b.text((830, 790), "南京", 42, BLUE, .13, .20)
    b.stickman(250, 430, 44, (.16, .32), hat="emperor")
    b.text((120, 260), "朱元璋的分封", 42, BLACK, .27, .36)
    pos = [(520, 350), (860, 300), (1350, 300), (1680, 360), (330, 620), (1700, 640)]
    spans = seq_spans(6, .30, .62)
    for (x, y), sp in zip(pos, spans):
        b.line((960, 700), (x, y + 30), GRAY, 3, sp[0], sp[1], amp=2.0)
        b.castle(x, y, 24, sp)
    b.castle(1350, 300, 30, (.55, .68))
    b.text((1150, 160), "北平·燕王", 40, BLUE, .62, .70)
    b.stickman(1450, 240, 30, (.64, .74), hat="crown", sword=True)
    b.bubble(640, 480, 240, 90, (.72, .86))
    b.text((480, 455), "自家人，靠得住", 36, BLACK, .78, .88)


def p_s3(b: Board):
    b.stickman(280, 620, 46, (.05, .18), hat="crown")
    b.text((190, 760), "建文帝", 38, BLUE, .14, .21)
    b.stickman(540, 640, 34, (.15, .27))
    b.stickman(670, 650, 34, (.18, .30))
    b.text((470, 760), "齐泰·黄子澄", 36, BLUE, .27, .36)
    b.bubble(620, 420, 230, 85, (.32, .44))
    b.text((480, 395), "先挑软柿子捏", 34, BLACK, .38, .48)
    xs = [950, 1120, 1290, 1460, 1630]
    names = ["周王", "齐王", "湘王", "代王", "岷王"]
    spans = seq_spans(5, .40, .62)
    for x, name, sp in zip(xs, names, spans):
        b.castle(x, 250, 22, sp)
        b.text((x - 42, 130), name, 32, BLACK, .60, .68)
        b.xmark(x, 220, 26, (.68, .78))
    b.flame(1290, 320, 30, (.74, .84))
    b.text((1120, 340), "湘王全家自焚…", 34, RED, .78, .86)
    b.castle(1350, 700, 32, (.80, .90))
    b.stickman(1470, 640, 32, (.82, .93), hat="crown", sword=True, sweat=True)
    b.text((1180, 800), "下一个：燕王？", 40, RED, .90, .97)


def p_s4(b: Board):
    b.blob(230, 180, 55, 55, BLACK, 5, .05, .12)
    for a in range(8):
        x = 230 + 85 * math.cos(a / 8 * 6.283)
        y = 180 + 85 * math.sin(a / 8 * 6.283)
        b.line((230 + 68 * math.cos(a / 8 * 6.283), 180 + 68 * math.sin(a / 8 * 6.283)),
               (x, y), BLACK, 4, .09, .14, amp=1.5)
    b.text((320, 140), "大夏天", 38, BLUE, .11, .17)
    b.line((150, 880), (1250, 880), GRAY, 3, .06, .11, amp=2.0)
    b.stickman(700, 700, 50, (.13, .30), blanket=True, sweat=True)
    b.text((600, 860), "朱棣", 38, BLUE, .26, .32)
    b.flame(870, 860, 45, (.27, .37))
    b.text((930, 880), "烤火", 34, BLACK, .33, .39)
    b.bubble(430, 470, 220, 85, (.37, .47))
    b.text((330, 445), "我疯了…", 36, BLACK, .42, .50)
    b.stickman(1250, 720, 42, (.47, .59))
    b.text((1160, 850), "朝廷探子", 36, BLUE, .55, .62)
    b.bubble(1520, 480, 230, 85, (.57, .68))
    b.text((1390, 455), "得，真疯了", 34, BLACK, .62, .70)
    b.poly([(1420, 780), (1420, 640), (1850, 640), (1850, 780)], BLACK, 4, .68, .80)
    b.line((1460, 750), (1560, 690), BLACK, 5, .77, .83)
    b.line((1600, 750), (1700, 690), BLACK, 5, .79, .85)
    b.line((1740, 750), (1810, 695), BLACK, 5, .81, .87)
    b.text((1450, 590), "后院：招兵买马·赶造兵器", 32, RED, .85, .95)


def p_s5(b: Board):
    b.line((150, 890), (1770, 890), GRAY, 3, .04, .09, amp=2.0)
    b.castle(860, 780, 46, (.05, .18))
    b.text((760, 830), "北平", 40, BLUE, .14, .20)
    b.stickman(600, 700, 48, (.16, .32), hat="crown", raise_arm=True, sword=True)
    b.text((500, 830), "朱棣", 38, BLUE, .28, .34)
    b.crowd(1000, 810, 26, 7, (.30, .46))
    b.text((1050, 880), "八百死士", 36, BLACK, .42, .50)
    b.stickman(1240, 780, 26, (.44, .52))
    b.stickman(1310, 785, 26, (.46, .54))
    b.xmark(1275, 745, 34, (.52, .60))
    b.text((1180, 660), "来使·咔嚓", 32, RED, .56, .64)
    b.flag(1560, 860, 40, (.58, .72))
    b.text((1600, 480), "奉天靖难", 40, RED, .68, .76)
    b.text((1600, 545), "清君侧", 40, RED, .72, .80)
    b.bubble(700, 330, 260, 90, (.76, .88))
    b.text((520, 305), "皇帝没错，错的是奸臣", 34, BLACK, .82, .92)
    b.text((150, 140), "建文元年·七月", 38, BLUE, .88, .96)


def p_s6(b: Board):
    b.poly([(960, 780), (890, 900), (1030, 900)], BLACK, 5, .04, .12)
    b.line((560, 730), (1360, 690), BLACK, 6, .08, .16)
    b.crowd(600, 660, 26, 8, (.14, .30))
    b.text((380, 760), "朝廷：兵多粮多", 38, BLACK, .26, .35)
    b.stickman(1290, 580, 44, (.28, .42), hat="crown", sword=True)
    b.text((1200, 720), "燕军：能打，但穷", 38, BLACK, .38, .47)
    b.text((150, 230), "北平保卫战：50万大军被打崩", 36, BLACK, .44, .54)
    b.text((150, 310), "济南：铁铉死守，啃不动", 36, BLACK, .52, .61)
    b.text((150, 390), "东昌：差点交代", 36, BLACK, .59, .68)
    b.poly([(1480, 560), (1560, 520), (1640, 560), (1640, 640), (1560, 680),
            (1480, 640)], BLUE, 5, .66, .78)
    b.text((1465, 585), "不杀叔叔", 32, RED, .74, .82, hand=False)
    b.text((1400, 720), "朝廷自带上debuff", 34, BLUE, .80, .90)
    b.text((420, 500), "← 谁也压不住谁 →", 34, GRAY, .88, .96)


def p_s7(b: Board):
    b.castle(350, 330, 28, (.04, .14))
    b.text((240, 370), "北平", 38, BLUE, .10, .16)
    b.castle(1560, 830, 44, (.12, .26))
    b.text((1460, 870), "南京", 40, BLUE, .22, .29)
    b.blob(800, 480, 26, 26, BLACK, 4, .28, .36)
    b.text((760, 420), "济南", 30, BLACK, .32, .38)
    b.blob(1100, 620, 26, 26, BLACK, 4, .33, .41)
    b.xmark(800, 480, 20, (.38, .46))
    b.xmark(1100, 620, 20, (.40, .48))
    b.text((860, 300), "重镇？绕开。", 36, RED, .46, .55)
    b.arrow([(400, 360), (900, 560), (1430, 760)], (.50, .68))
    b.text((950, 520), "轻骑直插", 42, BLUE, .60, .68)
    b.flame(1480, 660, 55, (.66, .78))
    b.flame(1650, 660, 55, (.69, .81))
    b.text((1420, 560), "皇宫起火", 38, BLACK, .74, .82)
    b.text((1700, 460), "？", 130, RED, .80, .92)
    b.text((150, 150), "建文四年·六月·瓜洲渡江", 38, BLUE, .88, .97)


def p_s8(b: Board):
    b.line((150, 890), (1770, 890), GRAY, 3, .04, .09, amp=2.0)
    b.castle(380, 760, 42, (.05, .17))
    b.text((260, 800), "迁都北京", 38, BLUE, .13, .21)
    b.poly([(760, 720), (1180, 720), (1120, 800), (820, 800)], BLACK, 5, .17, .30)
    b.line((970, 715), (970, 540), BLACK, 5, .24, .32)
    b.poly([(970, 545), (1120, 610), (970, 675)], BLUE, 5, .28, .38)
    b.text((820, 840), "郑和下西洋", 38, BLUE, .34, .43)
    b.poly([(1330, 760), (1500, 760), (1490, 620), (1340, 620)], BLACK, 5, .38, .48)
    b.line((1360, 660), (1470, 660), GRAY, 3, .44, .50, amp=1.5)
    b.line((1360, 695), (1470, 695), GRAY, 3, .46, .52, amp=1.5)
    b.line((1360, 730), (1470, 730), GRAY, 3, .48, .54, amp=1.5)
    b.text((1300, 800), "永乐大典", 38, BLUE, .50, .58)
    b.stickman(1700, 700, 40, (.54, .66), hat="crown", sweat=True)
    b.text((1650, 460), "？", 120, RED, .60, .72)
    b.text((1490, 800), "建文帝？", 38, BLACK, .66, .74)
    b.text((1180, 330), "烧死了？出家了？找了三十年？", 36, BLACK, .70, .80)
    b.bubble(600, 380, 300, 95, (.76, .88))
    b.text((390, 355), "你觉得他去哪了？评论区聊", 36, BLACK, .82, .93)
    b.fill((1740, 120, 1850, 230), RED, .92, radius=14)
    b.text((1762, 130), "完", 76, BOARD, .94, .95)


PAINTERS = {"s1": p_s1, "s2": p_s2, "s3": p_s3, "s4": p_s4,
            "s5": p_s5, "s6": p_s6, "s7": p_s7, "s8": p_s8}


def render_scene(chapter: dict[str, Any], progress: float, *, content: dict,
                 index: int, total: int, subtitle: str) -> Image.Image:
    painter = PAINTERS.get(str(chapter.get("kind")), p_s1)
    board = Board(seed=1000 + index)
    painter(board)
    img = board.render(max(0.0, min(1.0, progress)))
    d = ImageDraw.Draw(img)
    # 顶部手写版式
    d.text((100, 55), content.get("title", ""), font=_font(44), fill=INKBAND)
    num = f"{index + 1:02d}/{total:02d}"
    d.text((WIDTH - 220, 66), num, font=_font(34, hand=False), fill=INKBAND)
    d.rectangle((100, 122, 100 + int((WIDTH - 200) * ((index + progress) / max(total, 1))), 128),
                fill=RED)
    # 底部字幕:白字黑边(B站样式),不遮画
    if subtitle:
        text = "\n".join(subtitle.split("\n")[:2])
        f = _font(40, hand=False)
        lines = text.split("\n")
        y = HEIGHT - 150 - (len(lines) - 1) * 52
        for ln in lines:
            w = d.textlength(ln, font=f)
            x = (WIDTH - w) / 2
            for dx in (-4, -2, 0, 2, 4):
                for dy in (-4, -2, 0, 2, 4):
                    if abs(dx) + abs(dy):
                        d.text((x + dx, y + dy), ln, font=f, fill=(20, 20, 22))
            d.text((x, y), ln, font=f, fill=(252, 252, 250))
            y += 52
    return img


def _contact_sheet(frames: list[Path], output: Path) -> None:
    tw, th, cols = 480, 270, 2
    sheet = Image.new("RGB", (cols * tw, math.ceil(len(frames) / cols) * th), INKBAND)
    for i, p in enumerate(frames):
        with Image.open(p) as im:
            im.thumbnail((tw, th))
            sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    sheet.save(output, "PNG")


def render_video(content, timeline, cues, audio: Path, output: Path) -> dict:
    frame_count = max(1, int(math.ceil(float(timeline["audio_duration"]) * FPS)))
    proc = subprocess.Popen(
        [str(FFMPEG), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt",
         "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
         "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
         "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-b:a", "192k", "-shortest", str(output)], stdin=subprocess.PIPE)
    assert proc.stdin is not None
    chapters = timeline["chapters"]
    total = len(chapters)
    cached = None
    try:
        for frame in range(frame_count):
            sec = frame / FPS
            idx = max((i for i, c in enumerate(chapters) if c["start"] <= sec), default=0)
            entry = chapters[idx]
            local = max(0.0, min(1.0, (sec - entry["start"]) / max(entry["duration"], .001)))
            if frame % 2 == 0:  # 15fps 绘制,复制成 30fps
                img = render_scene(content["chapters"][idx], local, content=content,
                                   index=idx, total=total, subtitle=_cue_for(cues, sec))
                cached = img.tobytes()
            proc.stdin.write(cached)
    except BrokenPipeError as exc:
        raise RuntimeError("ffmpeg 提前退出") from exc
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg 编码失败")
    report = _probe_video(output)
    report["output"] = str(output)
    report["expected_duration"] = timeline["audio_duration"]
    report["verified"] = (report["width"] == WIDTH and report["height"] == HEIGHT
                          and report["has_audio"]
                          and abs(report["duration"] - report["audio_duration"]) < 0.15
                          and abs(report["duration"] - timeline["audio_duration"]) < 0.15)
    if not report["verified"]:
        raise RuntimeError(f"成片校验失败: {report}")
    return report


def run(preview: bool = False, render: bool = False, out: Path = OUT) -> dict:
    content = json.loads(CONTENT.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    if preview:
        durations = [max(2.5, len(c.get("narration", "")) * 0.19)
                     for c in content["chapters"]]
    else:
        parts = _part_files(out)
        _, durations = assemble_audio(out, parts)
    timeline = build_timeline(content, durations)
    cues = build_subtitle_cues(content, timeline)
    frames_dir = out / "frames"
    frames_dir.mkdir(exist_ok=True)
    total = len(timeline["chapters"])
    frames = []
    for i, ch in enumerate(content["chapters"]):
        entry = timeline["chapters"][i]
        mid = render_scene(ch, 0.55, content=content, index=i, total=total,
                           subtitle=_cue_for(cues, entry["start"] + entry["duration"] * .55))
        p = frames_dir / f"{ch.get('kind', 'x')}_mid.png"
        mid.save(p, "PNG")
        frames.append(p)
        fin = render_scene(ch, 1.0, content=content, index=i, total=total,
                           subtitle=_cue_for(cues, entry["start"] + entry["duration"] * .99))
        p = frames_dir / f"{ch.get('kind', 'x')}_fin.png"
        fin.save(p, "PNG")
        frames.append(p)
    result: dict[str, Any] = {"frames": [str(p) for p in frames]}
    if preview:
        sheet = out / "contact_sheet.png"
        _contact_sheet(frames, sheet)
        result["contact_sheet"] = str(sheet)
    if render:
        audio = out / "audio.wav"
        (out / "timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
        write_srt(cues, out / "subtitles.srt")
        video = out / "靖难之役-边画边讲.mp4"
        result["report"] = render_video(content, timeline, cues, audio, video)
        result["video"] = str(video)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    try:
        result = run(preview=args.preview or not args.render,
                     render=args.render, out=args.out)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
