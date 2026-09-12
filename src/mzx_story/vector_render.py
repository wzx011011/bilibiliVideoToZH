# -*- coding: utf-8 -*-
"""明朝故事线·动画图解渲染器 v2(靖难之役)。

v1 白板手绘 → v2 升级:不再刻意手绘感,目标"准确+生动":
- 人物:服化道扁平插画(冕冠/乌纱/盔甲/袈裟,表情姿态),宣纸底+明黄朱红靛蓝配色
- 地图:真实经纬投影(海岸线/长江/黄河/城池),战役路线按史料走廊绘制,配史实日期标
- 镜头:逐场景推拉/平移(帧驱动,可复现);2x 超采样抗锯齿
- 保留:笔画随解说进度生长、京腔侃爷配音、gpt_explainer 音频/时间轴/字幕管线

用法:
  python src/mzx_story/vector_render.py --preview
  python src/mzx_story/vector_render.py --render
"""
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[0]
sys.path.insert(0, str(SRC))

from gpt_explainer.render import (  # noqa: E402
    WIDTH, HEIGHT, FPS,
    assemble_audio, build_subtitle_cues, build_timeline, write_srt,
    _part_files, _probe_video, _cue_for,
)
from video_layout import (  # noqa: E402
    EDGE_MARGIN, HEADER, STAGE, SUBTITLE, black_edge_ratio,
    draw_subtitle_band, font as layout_font, validate_layout,
)

ROOT = HERE.parents[1]
FFMPEG = ROOT / "work" / "video-tools" / "ffmpeg.exe"
CONTENT = HERE / "ming-01-jingnan.json"
OUT = Path("D:/mzx-ming01")

# All scene coordinates are authored in final 1920x1080 pixels.  Keep the
# multiplier at one so a coordinate or font size is never accidentally doubled.
# The renderer still owns the single compositing/crop step below.
SS = 1
MARGIN = 90            # 虚拟画布四周余量(供镜头推拉)
VW, VH = WIDTH + MARGIN * 2, HEIGHT + MARGIN * 2

PAPER = (243, 238, 228)
INK = (45, 42, 38)
RED = (176, 48, 42)
DARKRED = (132, 34, 30)
YELLOW = (222, 168, 52)
YELLOW_D = (196, 140, 36)
BLUE = (42, 72, 110)
BLUE_L = (100, 140, 170)
SEA = (214, 228, 236)
SKIN = (245, 226, 196)
OCHRE = (150, 105, 60)
ROBE_WANG = (146, 60, 52)
ROBE_SOLDIER = (110, 116, 124)
ROBE_RAG = (150, 142, 128)
GRAY = (130, 130, 136)
STAMP = (168, 164, 155)


def _font(size: int, hand: bool = True):
    names = ("STXINGKA.TTF", "simkai.ttf", "msyh.ttc") if hand else ("msyhbd.ttc", "msyh.ttc")
    for name in names:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", int(size * SS))
        except OSError:
            continue
    return ImageFont.load_default()


def _jit(p0, p1, rng, amp=1.8):
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = max(2, int(length / 90))
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append((p0[0] + (p1[0] - p0[0]) * t + rng.uniform(-amp, amp) * SS,
                    p0[1] + (p1[1] - p0[1]) * t + rng.uniform(-amp, amp) * SS))
    pts[0], pts[-1] = p0, p1
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
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            return out, out[-1]
    return out, out[-1]


class Board:
    """场景画板:笔画/填充/文字带时间窗,2x 超采样,render(t,camera) 出最终帧。"""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.strokes: list = []
        self.fills: list = []
        self.texts: list = []

    def line(self, p0, p1, color=INK, width=5, t0=0.0, t1=1.0, amp=1.8):
        self.strokes.append((_jit(p0, p1, self.rng, amp), color, width * SS, t0, t1))

    def poly(self, pts, color=INK, width=4 * SS, t0=0.0, t1=1.0, close=False, amp=1.8):
        seq = list(pts) + ([pts[0]] if close else [])
        flat = []
        for a, b in zip(seq, seq[1:]):
            flat.extend(_jit(a, b, self.rng, amp)[:-1])
            flat.append(b)
        self.strokes.append((flat, color, width, t0, t1))

    def ellipse(self, cx, cy, rx, ry, color=INK, width=4, t0=0.0, t1=1.0):
        pts = [(cx + rx * math.cos(2 * math.pi * i / 40),
                cy + ry * math.sin(2 * math.pi * i / 40)) for i in range(40)]
        self.poly(pts, color, width, t0, t1, close=True, amp=0.8)

    def fillp(self, pts, color, t0=0.0):
        self.fills.append(("poly", pts, color, t0))

    def fillr(self, box, color, t0=0.0, radius=10):
        self.fills.append(("rrect", box, color, t0, radius))

    def text(self, xy, s, size, color=INK, t0=0.0, t1=0.0, hand=True):
        self.texts.append((xy, str(s), size, color, t0, t1 or t0 + 0.001, hand))

    def _spans(self, t0, t1, n):
        step = (t1 - t0) / n
        return [(t0 + i * step, t0 + (i + 0.85) * step) for i in range(n)]

    # ---------- 元素库 ----------
    def figure(self, x, y, h, span, *, role="official", mood="neutral",
               beard=False, prop=None, flip=False):
        """扁平插画人物(x,y=脚底中心,h=身高)。role: emperor/wang/official/
        soldier/ragged/monk;prop: sword/book/horsewhip。"""
        t0, t1 = span
        sp = self._spans(t0, t1, 6)
        hr = h * 0.115
        # 头中心:头底正好搭在袍肩上(旧版头悬空 0.3h,观感头身分离)
        hy = y - h * 0.675
        robe_c = {"emperor": YELLOW, "wang": ROBE_WANG, "official": BLUE,
                  "soldier": ROBE_SOLDIER, "ragged": ROBE_RAG,
                  "monk": (196, 190, 178)}[role]
        s = 1 if not flip else -1
        # 袍身(梯形)+袖
        self.fillp([(x - h * .16, y), (x - h * .11, y - h * .56),
                    (x + h * .11, y - h * .56), (x + h * .16, y)], robe_c, sp[0][0])
        self.fillp([(x - h * .13, y - h * .52), (x - h * .30 - s * h * .06, y - h * .64),
                    (x - h * .30 - s * h * .06, y - h * .56), (x - h * .11, y - h * .42)],
                   robe_c, sp[1][0])
        self.fillp([(x + h * .13, y - h * .52), (x + h * .30 + s * h * .06, y - h * .64),
                    (x + h * .30 + s * h * .06, y - h * .56), (x + h * .11, y - h * .42)],
                   robe_c, sp[1][0])
        self.poly([(x - h * .16, y), (x - h * .11, y - h * .56), (x + h * .11, y - h * .56),
                   (x + h * .16, y)], INK, 3 * SS, sp[0][0], sp[0][1], close=True, amp=1.0)
        # 头
        self.fillp([(x + hr * math.cos(a / 36 * 6.283) * 0.92,
                     hy + hr * math.sin(a / 36 * 6.283) * 1.08)
                    for a in range(36)], SKIN, sp[2][0])
        self.ellipse(x, hy, hr * .92, hr * 1.08, INK, 3, sp[2][0], sp[2][1])
        # 眼/眉/嘴(表情)
        ey = hy - hr * .1
        for dx in (-.35, .35):
            self.fillp([(x + dx * hr - 3 * SS, ey - 3 * SS),
                        (x + dx * hr + 3 * SS, ey + 3 * SS)], INK, sp[2][0])
        brow_dy = {"worried": -hr * .28, "angry": -hr * .18, "neutral": -hr * .3,
                   "smirk": -hr * .28, "sad": -hr * .22}[mood]
        tilt = {"worried": .35, "sad": .3, "angry": -.3, "neutral": 0, "smirk": -.1}[mood]
        for dx in (-.35, .35):
            self.line((x + (dx - .18 * tilt) * hr, ey + brow_dy),
                      (x + (dx + .18 * tilt) * hr, ey + brow_dy - tilt * hr * .3),
                      INK, 3, sp[2][0], sp[2][1], amp=0.6)
        mouth = {"neutral": ("arc", 0.25), "worried": ("o", 0.16), "sad": ("frown", 0.25),
                 "angry": ("line", 0.22), "smirk": ("arc", 0.3)}[mood]
        if mouth[0] in ("arc", "frown", "line"):
            yy = hy + hr * .5
            w = hr * mouth[1]
            if mouth[0] == "frown":
                self.poly([(x - w, yy + hr * .08), (x, yy), (x + w, yy + hr * .08)],
                          INK, 3 * SS, sp[2][0], sp[2][1], amp=0.5)
            elif mouth[0] == "line":
                self.line((x - w, yy), (x + w, yy), INK, 3, sp[2][0], sp[2][1], amp=0.5)
            else:
                self.poly([(x - w, yy), (x, yy + hr * .12), (x + w, yy)],
                          INK, 3 * SS, sp[2][0], sp[2][1], amp=0.5)
        else:
            self.ellipse(x, hy + hr * .55, hr * .14, hr * .18, INK, 3, sp[2][0], sp[2][1])
        # 冠/帽
        if role == "emperor":
            self.fillr((x - hr * 1.5, hy - hr * 1.55, x + hr * 1.5, hy - hr * 1.05),
                       INK, sp[3][0], radius=4 * SS)
            self.fillr((x - hr * 1.15, hy - hr * 2.05, x + hr * 1.15, hy - hr * 1.6),
                       INK, sp[3][0], radius=3 * SS)
            for dx in (-1.5, 1.5):
                self.line((x + dx * hr, hy - hr * 1.05), (x + dx * hr, hy + hr * .3),
                          YELLOW_D, 3, sp[3][0], sp[3][1], amp=0.4)
                self.fillp([(x + dx * hr - 4 * SS, hy + hr * .3),
                            (x + dx * hr + 4 * SS, hy + hr * .3),
                            (x + dx * hr, hy + hr * .52)], YELLOW_D, sp[3][0])
        elif role in ("official", "wang"):
            self.fillp([(x - hr * 1.15, hy - hr * .6),
                        (x - hr * .95, hy - hr * 1.75), (x + hr * .95, hy - hr * 1.75),
                        (x + hr * 1.15, hy - hr * .6)], INK, sp[3][0])
            self.fillp([(x - hr * 1.95, hy - hr * 1.15), (x - hr * 1.15, hy - hr * 1.35),
                        (x - hr * 1.2, hy - hr * .95)], INK, sp[3][0])
            self.fillp([(x + hr * 1.95, hy - hr * 1.15), (x + hr * 1.15, hy - hr * 1.35),
                        (x + hr * 1.2, hy - hr * .95)], INK, sp[3][0])
        elif role == "soldier":
            self.fillp([(x - hr * 1.05, hy - hr * .7), (x - hr * .8, hy - hr * 1.8),
                        (x + hr * .8, hy - hr * 1.8), (x + hr * 1.05, hy - hr * .7)],
                       INK, sp[3][0])
            self.ellipse(x, hy - hr * 2.1, hr * .22, hr * .22, RED, 4, sp[3][0], sp[3][1])
        elif role == "monk":
            for dx in (-.4, 0, .4):
                self.fillp([(x + dx * hr - 3 * SS, hy - hr * 1.5),
                            (x + dx * hr + 3 * SS, hy - hr * 1.5),
                            (x + dx * hr, hy - hr * 1.15)], INK, sp[3][0])
        elif role == "ragged":
            for a in (-1.0, -0.3, 0.5):
                self.line((x + a * hr, hy - hr * 1.3), (x + (a + .35) * hr, hy - hr * 1.9),
                          INK, 3, sp[3][0], sp[3][1], amp=1.2)
        if beard:
            for a in (-0.9, -0.5, 0, 0.5, 0.9):
                self.line((x + a * hr * .8, hy + hr * .7),
                          (x + a * hr * 1.05, hy + hr * 1.9), (170, 165, 158), 4,
                          sp[3][0], sp[3][1], amp=0.8)
        # 道具
        if prop == "sword":
            self.line((x + h * .30 + s * h * .06, y - h * .62),
                      (x + h * .48 + s * h * .06, y - h * .90), INK, 4, sp[4][0], sp[4][1])
            self.line((x + h * .44 + s * h * .06, y - h * .82),
                      (x + h * .52 + s * h * .06, y - h * .86), RED, 4, sp[4][0], sp[4][1])
        elif prop == "book":
            self.fillr((x + h * .30, y - h * .68, x + h * .48, y - h * .56),
                       (238, 233, 220), sp[4][0], radius=2 * SS)
            self.poly([(x + h * .30, y - h * .68), (x + h * .48, y - h * .68)],
                      INK, 3 * SS, sp[4][0], sp[4][1], amp=0.5)
        # 服装中缝(仪式感)
        if role in ("emperor", "wang"):
            self.line((x, y - h * .56), (x, y), DARKRED if role == "emperor" else INK,
                      3, sp[5][0], sp[5][1], amp=0.6)
            for k in (0.2, 0.5, 0.8):
                self.ellipse(x, y - h * (0.56 - 0.56 * k), h * .012, h * .012,
                             YELLOW_D, 2, sp[5][0], sp[5][1])

    def wall(self, x0, x1, y, h, span, *, gate=True, tower=False, color=STAMP):
        t0, t1 = span
        sp = self._spans(t0, t1, 4 if gate else 3)
        self.fillr((x0, y - h, x1, y), color, sp[0][0], radius=3 * SS)
        self.poly([(x0, y - h), (x1, y - h)], INK, 3 * SS, sp[0][0], sp[0][1], amp=0.8)
        n = max(3, int((x1 - x0) / 70))
        for i in range(n):
            bx = x0 + (i + 0.5) * (x1 - x0) / n
            self.fillr((bx - 14 * SS, y - h - 16 * SS, bx + 14 * SS, y - h), color, sp[0][0])
        if gate:
            gw = (x1 - x0) * .18
            gx = (x0 + x1) / 2
            self.fillp([(gx - gw / 2, y), (gx - gw / 2, y - h * .62),
                        (gx, y - h * .85), (gx + gw / 2, y - h * .62),
                        (gx + gw / 2, y)], (70, 64, 58), sp[1][0])
        if tower:
            tx = (x0 + x1) / 2
            self.fillr((tx - h * .9, y - h - 20 * SS - h * .55, tx + h * .9, y - h - 20 * SS),
                       (90, 82, 74), sp[2][0], radius=4 * SS)
            self.fillp([(tx - h * 1.15, y - h - 20 * SS - h * .5),
                        (tx, y - h - 20 * SS - h * 1.05),
                        (tx + h * 1.15, y - h - 20 * SS - h * .5)],
                       (70, 62, 54), sp[2][0])

    def flame(self, cx, cy, s, span, glow=True):
        t0, t1 = span
        sp = self._spans(t0, t1, 3)
        if glow:
            self.fillp([(cx - s * 1.5, cy), (cx - s * 1.7, cy - s * 1.2),
                        (cx, cy - s * 2.6), (cx + s * 1.7, cy - s * 1.2),
                        (cx + s * 1.5, cy)], (236, 190, 120), sp[0][0])
        self.fillp([(cx - s * .9, cy), (cx - s * .5, cy - s * 1.6),
                    (cx, cy - s * .7), (cx + s * .45, cy - s * 2.0),
                    (cx + s * .9, cy)], RED, sp[1][0])
        self.fillp([(cx - s * .35, cy), (cx, cy - s * 1.1), (cx + s * .35, cy)],
                   YELLOW, sp[2][0])

    def flag(self, cx, cy, s, span, color=RED):
        t0, t1 = span
        f = lambda k: t0 + (t1 - t0) * k
        self.line((cx, cy), (cx, cy - 7 * s), INK, 5, f(.0), f(.4), amp=0.8)
        self.fillp([(cx, cy - 7 * s), (cx + 4.2 * s, cy - 6.3 * s),
                    (cx + 3.8 * s, cy - 4.6 * s), (cx, cy - 5.2 * s)], color, f(.35))

    def tag(self, xy, s, span, *, fill=RED, tcolor=(250, 246, 238), size=26, pad=14):
        t0, t1 = span
        # Chinese glyphs are wider than the nominal font size; leave a real
        # measured-looking margin so the label never clips its final glyph.
        glyph_width = size * (1.08 if any(ord(ch) > 127 for ch in str(s)) else 0.72)
        width = sum(glyph_width for _ in str(s))
        self.fillr((xy[0] - pad, xy[1] - pad,
                    xy[0] + pad + width, xy[1] + pad + size + 8),
                   fill, t0, radius=6)
        self.text((xy[0], xy[1]), s, size, tcolor, t0 + (t1 - t0) * .5, t1 + .001, hand=False)

    def bubble(self, cx, cy, w, h, span, *, fill=(250, 247, 240)):
        t0, t1 = span
        self.fillp([(cx + w * math.cos(a / 30 * 6.283) * 1.02,
                     cy + h * math.sin(a / 30 * 6.283) * 1.05) for a in range(30)],
                   fill, t0)
        self.ellipse(cx, cy, w, h, INK, 3, t0, t0 + (t1 - t0) * .7)
        self.line((cx - w * .3, cy + h * .9), (cx - w * .8, cy + h * 1.8), INK, 3,
                  t0 + (t1 - t0) * .6, t1, amp=0.8)

    def render(self, t: float, camera: tuple[float, float, float],
               out_size: tuple[int, int],
               background: Image.Image | None = None) -> Image.Image:
        """把场景坐标窗口渲染成 out_size 画幅。

        camera=(cx,cy,zoom):窗口中心为场景坐标 (cx,cy),窗口宽高=out_size/zoom,
        等比缩放、无各向异性拉伸;取景外的画布以纸色补底。
        background: 可选氛围底板(cover 铺满虚拟画布并与纸色 55% 混合),
        矢量笔画/文字绘制在其上,随镜头一同移动。
        """
        base = SS
        out_w, out_h = out_size
        if background is not None:
            bg = background
            scale = max(VW * base / bg.width, VH * base / bg.height)
            bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1),
                           Image.LANCZOS)
            bx, by = (bg.width - VW * base) // 2, (bg.height - VH * base) // 2
            vir = bg.crop((bx, by, bx + VW * base, by + VH * base))
            vir = Image.blend(Image.new("RGB", vir.size, PAPER), vir, 0.55)
        else:
            vir = Image.new("RGB", (VW * base, VH * base), PAPER)
        d = ImageDraw.Draw(vir)
        cx, cy, zoom = camera
        zoom = max(zoom, 0.05)
        off = MARGIN * base
        for item in self.fills:
            if t < item[3]:
                continue
            if item[0] == "poly":
                d.polygon([(px * base + off, py * base + off) for px, py in item[1]],
                          fill=item[2])
            else:
                box = item[1]
                d.rounded_rectangle([box[0] * base + off, box[1] * base + off,
                                     box[2] * base + off, box[3] * base + off],
                                    radius=item[4] * base, fill=item[2])
        for pts, color, width, t0, t1 in self.strokes:
            if t <= t0:
                continue
            f = 1.0 if t >= t1 else (t - t0) / max(t1 - t0, 1e-6)
            seg, _ = _partial(pts, min(1.0, f))
            if len(seg) >= 2:
                d.line([(px * base + off, py * base + off) for px, py in seg],
                       fill=color, width=max(2, int(width)), joint="curve")
        for xy, s, size, color, t0, t1, hand in self.texts:
            if t < t0:
                continue
            f = 1.0 if t >= t1 else (t - t0) / max(t1 - t0, 1e-6)
            n = max(1, int(len(s) * min(1.0, f) + (1 if f > 0 else 0)))
            d.text((xy[0] * base + off, xy[1] * base + off), s[:n],
                   font=_font(size, hand), fill=color)
        step = base / zoom
        ox = ((cx + MARGIN) - out_w / (2 * zoom)) * base
        oy = ((cy + MARGIN) - out_h / (2 * zoom)) * base
        frame = vir.transform((out_w * base, out_h * base), Image.AFFINE,
                              (step, 0, ox, 0, step, oy), resample=Image.BILINEAR,
                              fillcolor=PAPER)
        return frame.resize((out_w, out_h), Image.LANCZOS)


# ---------------- 史料数据(经纬) ----------------
COAST = [(121.8, 40.2), (119.8, 40.0), (119.6, 39.9), (118.2, 39.1), (118.0, 38.4),
         (118.9, 38.2), (119.1, 37.8), (120.2, 37.7), (121.0, 37.5), (122.2, 37.4),
         (122.6, 37.4), (122.0, 36.9), (121.0, 36.6), (120.4, 36.1), (119.8, 35.6),
         (119.5, 35.4), (119.4, 34.7), (119.9, 34.5), (120.3, 34.0), (120.9, 33.3),
         (121.4, 32.8), (121.9, 31.9), (121.9, 31.4), (121.4, 30.3), (121.9, 29.9)]
YANGTZE = [(116.2, 30.5), (117.0, 30.6), (117.6, 30.9), (118.0, 31.3), (118.4, 31.35),
           (118.7, 31.9), (118.8, 32.06), (119.0, 32.3), (119.4, 32.4), (120.0, 32.1),
           (120.7, 32.1), (121.9, 31.4)]
YELLOW_R = [(114.3, 34.9), (115.5, 34.9), (116.5, 34.9), (117.2, 34.5), (118.0, 34.0),
            (118.7, 33.8), (119.3, 33.7), (120.0, 34.0), (120.3, 34.3)]
HUAI = [(116.0, 32.6), (117.0, 32.9), (118.0, 33.0), (118.8, 33.0), (119.5, 33.3),
        (120.2, 33.8)]
CITIES = {"北平": (116.4, 39.9), "宣府": (115.1, 40.6), "大同": (113.3, 40.1),
          "太原": (112.5, 37.9), "西安": (108.9, 34.3), "开封": (114.35, 34.8),
          "济南": (117.0, 36.67), "青州": (118.5, 36.7), "兖州": (116.85, 35.55),
          "东昌": (116.0, 36.45), "徐州": (117.2, 34.26), "宿州": (116.98, 33.63),
          "灵璧": (117.56, 33.54), "淮安": (119.15, 33.5), "扬州": (119.42, 32.39),
          "荆州": (112.2, 30.35), "成都": (104.06, 30.66), "昆明": (102.7, 25.04),
          "杭州": (120.16, 30.25), "苏州": (120.62, 31.32), "南京": (118.78, 32.06),
          "真定": (114.6, 38.2), "河间": (116.1, 38.4), "馆陶": (115.3, 36.55),
          "天长": (119.0, 32.68), "瓜洲": (119.42, 32.05)}
ROUTE_1402 = [("北平", 116.4, 39.9), ("馆陶", 115.3, 36.55), ("徐州", 117.05, 34.3),
              ("宿州", 116.98, 33.63), ("灵璧", 117.56, 33.54), ("淮安", 118.6, 33.0),
              ("天长", 119.0, 32.68), ("扬州", 119.42, 32.39), ("瓜洲", 119.42, 32.05),
              ("金川门", 118.83, 32.09)]


def make_proj(lon0, lat0, k, ox, oy):
    return (lambda lon: ox + (lon - lon0) * k,
            lambda lat: oy + (lat0 - lat) * k * 1.3)


def draw_map(b: Board, gx, gy, span, *, rivers=True, cities=(), cap_span=None):
    t0, t1 = span
    sea = COAST + [(123.5, 29.5), (123.5, 41.5)]
    b.fillp([(gx(lon), gy(lat)) for lon, lat in sea], SEA, t0)
    if rivers:
        for river in (YANGTZE, YELLOW_R, HUAI):
            pts = [(gx(lon), gy(lat)) for lon, lat in river]
            b.poly(pts, BLUE_L, 4, t0, t0 + (t1 - t0) * .4, amp=0.8)
    b.poly([(gx(lon), gy(lat)) for lon, lat in COAST], INK, 4,
           t0, t0 + (t1 - t0) * .55, amp=1.0)
    for name in cities:
        lon, lat = CITIES[name]
        b.fillp([(gx(lon) - 7 * SS, gy(lat) - 7 * SS), (gx(lon) + 7 * SS, gy(lat) - 7 * SS),
                 (gx(lon) + 7 * SS, gy(lat) + 7 * SS), (gx(lon) - 7 * SS, gy(lat) + 7 * SS)],
                INK, (cap_span or span)[0])
        b.text((gx(lon) + 14 * SS, gy(lat) - 20 * SS), name, 32, INK, (cap_span or span)[0])


# ---------------- 场景编排 ----------------

def p_s1(b: Board):
    b.line((150, 880), (1770, 880), GRAY, 2, .04, .10, amp=1.0)
    # The episode title is rendered by the fixed header. Keep the scene title
    # below it so camera crops can never cover the program chrome.
    b.text((150, 205), "靖难之役", 92, INK, .05, .17)
    b.text((160, 315), "—— 叔叔和侄子的火并", 40, BLUE, .16, .25)
    b.tag((140, 380), "洪武三十一年 · 1398", (.25, .33), fill=DARKRED)
    b.figure(700, 800, 320, (.26, .48), role="emperor", mood="neutral", beard=True)
    b.text((620, 830), "朱元璋", 36, INK, .42, .48)
    b.arrow([(830, 640), (940, 620)], (.46, .55), color=INK)
    b.figure(1080, 800, 290, (.46, .64), role="emperor", mood="worried")
    b.text((990, 830), "朱允炆·建文帝", 36, INK, .58, .66)
    u_spans = seq_spans(5, .62, .86)
    for i, (ux, uy) in enumerate(((1500, 700), (1660, 780), (1560, 570), (1730, 560), (1810, 700))):
        b.figure(ux, uy, 190, u_spans[i], role="wang", mood="angry", flip=i % 2 == 1)
    b.text((1240, 380), "手握兵权的叔叔们", 32, INK, .84, .92)
    b.tag((140, 460), "建文元年 · 1399", (.88, .96))


def p_s2(b: Board):
    gx, gy = make_proj(101.0, 41.4, 42, 430, 30)
    draw_map(b, gx, gy, (.03, .30), rivers=True)
    b.tag((140, 175), "洪武分封 · 诸王守边", (.28, .37), fill=BLUE, size=34)
    kings = [("北平", "燕王", True), ("大同", "代王", False), ("太原", "晋王", False),
             ("开封", "周王", False), ("青州", "齐王", False), ("兖州", "鲁王", False),
             ("荆州", "湘王", False), ("成都", "蜀王", False), ("昆明", "岷王", False),
             ("宣府", "谷王", False)]
    spans = seq_spans(10, .34, .80)
    for (city, title, big), sp in zip(kings, spans):
        lon, lat = CITIES[city]
        r = 13 * SS if big else 9 * SS
        b.fillp([(gx(lon) - r, gy(lat) - r), (gx(lon) + r, gy(lat) - r),
                 (gx(lon) + r, gy(lat) + r), (gx(lon) - r, gy(lat) + r)],
                RED if big else (146, 60, 52), sp[0])
        b.text((gx(lon) + 20 * SS, gy(lat) - 34 * SS), title, 36, INK, sp[0], sp[1])
        if big:
            b.text((gx(lon) + 20 * SS, gy(lat)), "战力天花板", 30, DARKRED, sp[1], sp[1] + .05)
    b.text((140, 950), "藩王手握兵权,替朝廷守边", 42, INK, .88, .96)


def p_s3(b: Board):
    gx, gy = make_proj(101.0, 41.4, 42, 430, 30)
    draw_map(b, gx, gy, (.02, .20), rivers=True)
    b.tag((140, 175), "建文削藩 · 一年五王", (.18, .27), fill=DARKRED, size=34)
    cuts = [("开封", "周王", "1398.08 被废"), ("青州", "齐王", "1399.03 被废"),
            ("荆州", "湘王", "1399.04 自焚"), ("大同", "代王", "1399.04 幽禁"),
            ("昆明", "岷王", "1399.06 被废")]
    spans = seq_spans(5, .28, .70)
    for (city, title, note), sp in zip(cuts, spans):
        lon, lat = CITIES[city]
        b.xmark(gx(lon), gy(lat), 16 * SS, sp, color=RED)
        b.text((gx(lon) + 26 * SS, gy(lat) - 30 * SS), title, 34, INK, sp[0], sp[1])
        b.text((gx(lon) + 26 * SS, gy(lat)), note, 28, DARKRED, sp[1], sp[1] + .04)
    b.tag((140, 700), "湘王阖宫自焚 · 举朝震动", (.70, .80), fill=RED, size=30)
    b.figure(1650, 850, 240, (.76, .92), role="official", mood="worried")
    b.text((1550, 880), "下一个:燕王?", 38, DARKRED, .90, .97)


def p_s4(b: Board):
    b.tag((140, 175), "建文元年 · 北平", (.04, .12), fill=BLUE)
    b.fillp([(280 + 62 * math.cos(a / 36 * 6.283), 330 + 62 * math.sin(a / 36 * 6.283))
             for a in range(36)], (238, 210, 120), .08)
    for a in range(10):
        b.line((280 + 70 * math.cos(a / 10 * 6.283), 330 + 70 * math.sin(a / 10 * 6.283)),
               (280 + 92 * math.cos(a / 10 * 6.283), 330 + 92 * math.sin(a / 10 * 6.283)),
               YELLOW_D, 4, .10, .16, amp=0.6)
    b.text((400, 300), "大夏天", 38, BLUE, .11, .17)
    b.line((150, 860), (1250, 860), GRAY, 3, .05, .10, amp=1.0)
    b.figure(700, 800, 360, (.13, .34), role="ragged", mood="sad", flip=True)
    b.text((600, 815), "朱棣", 34, INK, .30, .36)
    b.flame(890, 850, 46, (.30, .42))
    b.text((950, 870), "盛夏·披裘烤火", 30, INK, .38, .46)
    b.bubble(430, 430, 240, 92, (.42, .54))
    b.text((310, 400), "我疯了……", 40, INK, .47, .56)
    b.figure(1280, 800, 250, (.52, .68), role="official", mood="neutral")
    b.text((1180, 835), "朝廷探子", 32, BLUE, .62, .69)
    b.bubble(1560, 420, 250, 92, (.66, .78))
    b.text((1430, 395), "得,真疯了", 36, INK, .71, .80)
    b.tag((140, 560), "暗中:招兵买马 · 赶造兵器", (.78, .88), fill=DARKRED)
    b.fillr((1420, 620, 1830, 800), (228, 220, 202), .82, radius=8 * SS)
    for i, wx in enumerate((1500, 1600, 1700, 1800)):
        b.line((wx, 760), (wx + 30, 670), INK, 5, .84 + i * .01, .88 + i * .01)
    b.text((1430, 815), "王府后院", 28, INK, .88, .94)


def p_s5(b: Board):
    b.tag((140, 175), "建文元年七月 · 1399.07", (.04, .12), fill=DARKRED)
    b.wall(600, 1500, 830, 150, (.06, .26), gate=True, tower=True)
    b.text((620, 635), "北平城", 36, BLUE, .22, .30)
    b.figure(460, 800, 310, (.24, .44), role="soldier", mood="angry", prop="sword")
    b.figure(330, 810, 280, (.30, .48), role="soldier", mood="angry", prop="sword", flip=True)
    b.text((170, 470), "朱棣", 34, INK, .42, .48)
    crowd(b, 900, 880, 30, 9, (.40, .58))
    b.text((1000, 920), "八百死士 · 一夜控制全城", 32, INK, .54, .62)
    b.flag(1660, 880, 46, (.58, .74))
    b.text((1668, 570), "奉天靖难", 46, (250, 246, 238), .70, .80)
    b.text((1680, 618), "清君侧", 46, (250, 246, 238), .74, .84)
    b.tag((140, 380), "不是造反?祖训:清君侧", (.82, .93), fill=BLUE)


def p_s6(b: Board):
    gx, gy = make_proj(113.6, 40.9, 150, 820, 60)
    draw_map(b, gx, gy, (.03, .22), rivers=False,
             cities=("北平", "真定", "河间", "济南", "东昌"), cap_span=(.10, .20))
    b.tag((140, 175), "三年拉锯 · 1399-1402", (.04, .13), fill=BLUE)
    spans = seq_spans(3, .16, .44)
    for i, (city, note, c) in enumerate((("北平", "1399.10 李景隆 50 万围城,反被打崩", RED),
                                          ("济南", "1400.05 铁铉死守,啃不动", BLUE),
                                          ("东昌", "1400.12 燕军大败,张玉战死", RED))):
        sp = spans[i]
        lon, lat = CITIES[city]
        b.xmark(gx(lon), gy(lat), 14 * SS, sp, color=c)
        b.text((140, 240 + i * 92), note, 32, INK, sp[0], sp[1])
    b.poly([(gx(CITIES["真定"][0]), gy(CITIES["真定"][1])),
            (gx(CITIES["河间"][0]), gy(CITIES["河间"][1])),
            (gx(CITIES["济南"][0]), gy(CITIES["济南"][1]))],
           (170, 60, 50), 4, .42, .56, amp=2.0)
    b.text((150, 560), "拉锯战线反复横跳", 30, (170, 60, 50), .54, .62)
    b.tag((150, 660), "帝令:毋使朕有杀叔父名", (.62, .74), fill=DARKRED)
    b.text((150, 740), "—— 朱棣从此冲锋专挑箭雨最密处", 30, INK, .74, .84)
    b.figure(1620, 820, 270, (.78, .95), role="soldier", mood="smirk",
             prop="sword", flip=True)
    b.text((1520, 850), "战场生存 buff", 30, BLUE, .90, .97)


def p_s7(b: Board):
    gx, gy = make_proj(114.6, 40.5, 100, 260, 60)
    draw_map(b, gx, gy, (.02, .16), rivers=True)
    b.tag((150, 175), "建文四年 · 千里直捣", (.04, .13), fill=DARKRED)
    stops = ROUTE_1402
    pts = [(gx(lon), gy(lat)) for _, lon, lat in stops]
    route_t = (.16, .74)
    b.poly(pts, BLUE, 6, route_t[0], route_t[1], amp=1.2)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    d = math.hypot(x1 - x0, y1 - y0) or 1.0
    ux, uy = (x1 - x0) / d, (y1 - y0) / d
    px, py = -uy, ux
    b.poly([(x1, y1), (x1 - ux * 34 + px * 18, y1 - uy * 34 + py * 18),
            (x1 - ux * 34 - px * 18, y1 - uy * 34 - py * 18)], BLUE, 6, route_t[1], .80)
    # Keep route labels in a dedicated left rail.  The map carries only the
    # route and city marks; narrative dates no longer collide at the endpoint.
    marks = [("北平", "1402.01 南下", 0), ("灵璧", "1402.04 突破", 4),
             ("淮安", "渡淮", 5), ("瓜洲", "1402.06 渡江", 8), ("金川门", "开门投降", 9)]
    for row, (name, note, idx) in enumerate(marks):
        _, lon, lat = stops[idx]
        b.text((120, 260 + row * 58), f"{name}  {note}", 24, DARKRED,
               route_t[0] + idx * .05, route_t[0] + idx * .05 + .04)
    b.xmark(gx(CITIES["济南"][0]), gy(CITIES["济南"][1]), 16 * SS, (.30, .40), color=RED)
    b.xmark(gx(CITIES["徐州"][0]), gy(CITIES["徐州"][1]), 14 * SS, (.34, .44), color=RED)
    b.text((gx(CITIES["济南"][0]) + 26 * SS, gy(CITIES["济南"][1]) - 60 * SS),
           "重镇?绕开", 30, RED, .42, .50)
    nx, ny = gx(118.83), gy(32.09)
    b.fillr((nx - 150, ny - 90, nx + 150, ny + 55),
            (228, 220, 202), .74, radius=8)
    b.flame(nx - 72, ny - 18, 34, (.76, .86))
    b.flame(nx + 72, ny - 18, 34, (.80, .90))
    b.text((nx - 145, ny - 150), "皇宫起火", 28, INK, .84, .91)
    b.text((nx + 170, ny - 180), "建文帝不知所踪", 26, INK, .86, .96)
    b.text((nx + 145, ny - 330), "？", 96, RED, .86, .97)


def p_s8(b: Board):
    b.line((150, 890), (1770, 890), GRAY, 2, .03, .09, amp=1.0)
    b.tag((140, 175), "永乐时代 · 1403-1424", (.04, .12), fill=BLUE)
    b.wall(180, 620, 620, 120, (.08, .26), gate=True, tower=True)
    b.text((250, 660), "迁都北京 · 1421", 32, INK, .22, .30)
    b.fillp([(760, 660), (1180, 660), (1120, 760), (830, 760)], (146, 96, 62), .24)
    b.line((970, 655), (970, 420), INK, 5, .27, .35)
    b.fillp([(970, 425), (1150, 520), (970, 620)], (88, 120, 150), .30)
    for i in range(4):
        b.line((880 + i * 20, 700 - i * 14), (1060 - i * 20, 700 - i * 14), INK, 3,
               .32 + i * .01, .38 + i * .01, amp=0.8)
    b.poly([(700, 780), (1240, 780)], BLUE_L, 4, .36, .44, amp=2.0)
    b.text((820, 800), "郑和下西洋 · 1405 起", 32, INK, .40, .48)
    b.fillr((1420, 520, 1620, 760), (238, 233, 220), .44, radius=6 * SS)
    b.poly([(1420, 520), (1620, 520)], INK, 4 * SS, .44, .50, amp=0.6)
    for i, ly in enumerate((580, 630, 680)):
        b.line((1450, ly), (1590, ly), GRAY, 3, .46 + i * .02, .52 + i * .02, amp=0.6)
    b.text((1380, 800), "《永乐大典》· 1408 成书", 32, INK, .52, .60)
    b.figure(1730, 810, 260, (.56, .72), role="monk", mood="sad")
    b.text((1650, 540), "？", 120, RED, .64, .76)
    b.text((1560, 850), "建文帝去哪了", 34, INK, .70, .78)
    b.bubble(700, 320, 320, 100, (.76, .90))
    b.text((470, 292), "烧死了?出家了?海外?评论区聊", 34, INK, .82, .94)


def seq_spans(n: int, start=0.03, end=0.97, overlap=0.82):
    step = (end - start) / n
    return [(start + i * step, start + (i + overlap) * step) for i in range(n)]


def crowd(b: Board, cx, cy, s, n, span, color=INK):
    t0, t1 = span
    step = (t1 - t0) / max(n, 1)
    for i in range(n):
        x = cx + i * 2.0 * s
        a = t0 + i * step
        c = a + step * 0.7
        b.fillp([(x - s * .5, cy), (x - s * .35, cy - s * 1.5),
                 (x + s * .35, cy - s * 1.5), (x + s * .5, cy)], color, a)
        b.ellipse(x, cy - s * 1.9, s * .42, s * .46, color, 3, a, c)


def xmark_in(b: Board, cx, cy, s, span, color=RED):
    t0, t1 = span
    b.line((cx - s, cy - s), (cx + s, cy + s), color, 5, t0, t0 + (t1 - t0) * .5)
    b.line((cx - s, cy + s), (cx + s, cy - s), color, 5, t0 + (t1 - t0) * .5, t1)


# 给 Board 挂 xmark(与 v1 同名习惯)
Board.xmark = xmark_in
Board.arrow = lambda b, pts, span, color=BLUE, width=6: b.poly(
    pts, color, width * SS, span[0], span[1], amp=1.2)

PAINTERS = {"s1": p_s1, "s2": p_s2, "s3": p_s3, "s4": p_s4,
            "s5": p_s5, "s6": p_s6, "s7": p_s7, "s8": p_s8}

# 镜头语义:场景坐标窗口 (中心 cx, cy, 缩放 zoom),窗口高 = 700/zoom。
# 每场窗口必须覆盖本场全部内容带(顶部标签 ~161 到底部署性感官文字 ~990),
# 由 --preview 的 contact sheet 人工复核。
CAMS: dict[str, Callable[[float], tuple[float, float, float]]] = {
    "s1": lambda p: (960, 540, 0.90 + 0.03 * math.sin(p * 3.14159)),
    "s2": lambda p: (960, 515, 0.95 - 0.23 * min(1.0, p * 1.5)),
    "s3": lambda p: (960, 515, 0.74),
    "s4": lambda p: (960, 540, 0.90),
    "s5": lambda p: (960, 560, 0.84 + 0.03 * math.sin(p * 3.14159)),
    "s6": lambda p: (960, 555, 0.88),
    "s7": lambda p: (700, 350 + 580 * p, 0.90),
    "s8": lambda p: (960, 525, 0.95),
}


_BROLL_CACHE: dict[str, Image.Image] = {}


def _broll_base(src: Path, height: int) -> Image.Image:
    """按舞台宽高预缩放 broll 底图(进程级缓存,避免每帧重读)。"""
    key = f"{src}|{height}"
    if key not in _BROLL_CACHE:
        art = Image.open(src).convert("RGB")
        scale = max(WIDTH / art.width, height / art.height)
        _BROLL_CACHE[key] = art.resize(
            (int(art.width * scale) + 1, int(art.height * scale) + 1), Image.LANCZOS)
    return _BROLL_CACHE[key]


def _broll_segments(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    """把章节 broll 数组整理为按时间排序的节拍段。

    段类型: ai(默认,按 prompt 生成的插图) / diagram(矢量图解长驻节拍)。
    """
    segs = []
    for i, b in enumerate(chapter.get("broll") or []):
        at, hold = float(b.get("at", 0)), float(b.get("hold", 0))
        if hold <= 0:
            continue
        segs.append({"at": at, "hold": hold, "type": str(b.get("type", "ai")),
                     "src": ROOT / "work" / "broll" / CONTENT.stem / f"{chapter['kind']}_{i}.png",
                     "fit": b.get("fit")})
    segs.sort(key=lambda s: s["at"])
    return segs


def _segment_frame(seg: dict[str, Any], height: int, local: float,
                   stage_art: Image.Image) -> Image.Image:
    if seg["type"] == "diagram":
        return stage_art
    src = seg["src"]
    if not src.exists():
        raise RuntimeError(
            f"B-roll 插图缺失: {src} — 先运行 src/broll/generate.py --content {CONTENT}")
    if seg.get("fit") == "contain":
        # 沉浸式完整显示:同一张图模糊压暗铺满全舞台做背景(氛围),
        # 完整原图带圆角+柔和投影居中悬浮(信息),不裁任何像素。
        key = f"contain|{src}|{height}"
        if key not in _BROLL_CACHE:
            with Image.open(src) as im:
                art = im.convert("RGB")
            # 背景:cover 铺满 → 小图模糊(快) → 压暗
            small = art.resize((480, max(1, 480 * art.height // art.width)), Image.LANCZOS)
            bscale = max(WIDTH / small.width, height / small.height)
            bw, bh = int(small.width * bscale) + 2, int(small.height * bscale) + 2
            bgp = small.resize((bw, bh), Image.BILINEAR)
            bx, by = (bw - WIDTH) // 2, (bh - height) // 2
            bgp = bgp.crop((bx, by, bx + WIDTH, by + height)).filter(
                ImageFilter.GaussianBlur(16))
            bgp = Image.blend(bgp, Image.new("RGB", bgp.size, (10, 10, 13)), 0.32)
            # 前景:完整图,高度贴舞台(上下留 24px),圆角
            fscale = min((WIDTH - 64) / art.width, (height - 56) / art.height)
            w2, h2 = max(2, int(art.width * fscale)), max(2, int(art.height * fscale))
            art = art.resize((w2, h2), Image.LANCZOS)
            sh = Image.new("L", (w2 + 80, h2 + 80), 0)
            ImageDraw.Draw(sh).rounded_rectangle(
                (40, 40, w2 + 40, h2 + 40), radius=20, fill=170)
            sh = sh.filter(ImageFilter.GaussianBlur(18))
            x0, y0 = (WIDTH - w2) // 2, (height - h2) // 2
            bgp.paste((0, 0, 0), (x0 - 40, y0 - 40), sh)
            mask = Image.new("L", (w2, h2), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w2, h2), radius=18, fill=255)
            bgp.paste(art, (x0, y0), mask)
            _BROLL_CACHE[key] = bgp
        return _BROLL_CACHE[key].copy()
    base = _broll_base(src, height)
    zoom = 1.0 + 0.05 * local
    cw, chh = max(2, int(WIDTH / zoom)), max(2, int(height / zoom))
    x0, y0 = (base.width - cw) // 2, (base.height - chh) // 2
    return base.crop((x0, y0, x0 + cw, y0 + chh)).resize((WIDTH, height), Image.BILINEAR)


def _broll_frame_for(chapter: dict[str, Any], progress: float, height: int,
                     stage_art: Image.Image) -> Image.Image | None:
    """progress 命中的节拍帧;段间过渡为 AI↔AI(或图解)交叉淡化。

    矢量层只在 type=diagram 的图解节拍长驻出现(时长=该节拍 hold,想停多久停多久),
    不再作为节拍间隙的填充闪现。
    """
    segs = _broll_segments(chapter)
    if not segs:
        return None
    idx = max((i for i, s in enumerate(segs) if s["at"] <= progress), default=None)
    if idx is None:
        return None
    seg = segs[idx]
    local = min(1.0, (progress - seg["at"]) / max(seg["hold"], 1e-6))
    frame = _segment_frame(seg, height, local, stage_art)
    fade = 0.12
    if idx > 0 and local < fade and seg["hold"] > fade:
        prev = _segment_frame(segs[idx - 1], height, 1.0, stage_art)
        frame = Image.blend(prev, frame, local / fade)
    return frame


def _chapter_background(chapter: dict[str, Any]) -> Image.Image | None:
    """章节氛围底板(可选):内容 JSON 声明 bg 提示词后必须已生成,否则报错(门禁)。"""
    if not chapter.get("bg"):
        return None
    src = ROOT / "work" / "broll" / CONTENT.stem / f"{chapter['kind']}_bg.png"
    if not src.exists():
        raise RuntimeError(
            f"背景板缺失: {src} — 先运行 src/broll/generate.py --content {CONTENT}")
    key = f"bg|{src}"
    if key not in _BROLL_CACHE:
        with Image.open(src) as im:
            _BROLL_CACHE[key] = im.convert("RGB").copy()
    return _BROLL_CACHE[key]


def render_scene(chapter: dict[str, Any], progress: float, *, content: dict,
                 index: int, total: int, subtitle: str) -> Image.Image:
    """Render one scene with an isolated stage and fixed editorial overlays.

    Scene artwork is never allowed to paint into the header or subtitle band.  The
    board may still use its own camera for the middle viewport, but compositing is
    clipped once here before any overlay is drawn.
    """
    painter = PAINTERS.get(str(chapter.get("kind")), p_s1)
    board = Board(seed=2000 + index)
    painter(board)
    cam = CAMS.get(str(chapter.get("kind")), lambda p: (WIDTH / 2, 565, 0.843))
    progress = max(0.0, min(1.0, progress))
    stage_art = board.render(progress, cam(progress), (WIDTH, STAGE.height),
                             background=_chapter_background(chapter))
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    img.paste(stage_art, (STAGE.left, STAGE.top))

    broll_frame = _broll_frame_for(chapter, progress, STAGE.height, stage_art)
    if broll_frame is not None:
        img.paste(broll_frame, (STAGE.left, STAGE.top))

    d = ImageDraw.Draw(img)

    # Fixed header: a single baseline, no scene element can overlap it.
    d.rectangle((0, 0, WIDTH, HEADER.bottom), fill=PAPER)
    title_font = layout_font(30, bold=True)
    num_font = layout_font(30, bold=True)
    d.text((EDGE_MARGIN, 36), content.get("title", ""), font=title_font, fill=INK)
    num = f"{index + 1:02d} / {total:02d}"
    num_w = d.textlength(num, font=num_font)
    d.text((WIDTH - EDGE_MARGIN - num_w, 36), num, font=num_font, fill=INK)
    d.line((EDGE_MARGIN, 92, WIDTH - EDGE_MARGIN, 92), fill=(190, 181, 165), width=2)
    d.rectangle((EDGE_MARGIN, 92,
                 EDGE_MARGIN + int((WIDTH - 2 * EDGE_MARGIN) * ((index + progress) / max(total, 1))),
                 98), fill=RED)
    chapter_title = str(chapter.get("title", ""))
    d.text((EDGE_MARGIN, 112), chapter_title, font=layout_font(22, bold=True), fill=BLUE)

    source_line = "大明演义 · 动画图解 · 画面中的地图与日期为解释性可视化"
    draw_subtitle_band(img, subtitle, source_line=source_line)
    return img


def _contact_sheet(frames: list[Path], output: Path) -> None:
    tw, th, cols = 480, 270, 2
    sheet = Image.new("RGB", (cols * tw, math.ceil(len(frames) / cols) * th), INK)
    for i, p in enumerate(frames):
        with Image.open(p) as im:
            im.thumbnail((tw, th))
            sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    sheet.save(output, "PNG")


def _layout_samples(content, timeline, cues, out: Path) -> tuple[list[Path], list[dict]]:
    """Render dense temporal samples and validate the fixed overlay geometry."""
    frames_dir = out / "layout_samples"
    frames_dir.mkdir(exist_ok=True)
    total = len(timeline["chapters"])
    paths: list[Path] = []
    reports: list[dict] = []
    for i, chapter in enumerate(content["chapters"]):
        entry = timeline["chapters"][i]
        for sample_index, progress in enumerate((0.0, .15, .30, .45, .60, .75, .90, 1.0)):
            seconds = entry["start"] + entry["duration"] * min(progress, .999999)
            image = render_scene(chapter, progress, content=content, index=i, total=total,
                                 subtitle=_cue_for(cues, seconds))
            path = frames_dir / f"s{i + 1:02d}_{sample_index:02d}.png"
            image.save(path, "PNG")
            paths.append(path)
            # The renderer's fixed overlay is checked independently from artwork,
            # which is clipped to STAGE before the overlay is applied.
            overlay_boxes = draw_subtitle_band(Image.new("RGB", (WIDTH, HEIGHT), PAPER),
                                               _cue_for(cues, seconds),
                                               source_line="明朝故事 · 动画图解 · 画面中的地图与日期为解释性可视化")
            reports.append({"chapter": i, "progress": progress, "path": str(path),
                            "issues": validate_layout(overlay_boxes),
                            "black_edge_ratio": black_edge_ratio(image)})
    return paths, reports


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


def run(preview: bool = False, render: bool = False, out: Path | None = None,
        content_path: Path | None = None) -> dict:
    global CONTENT
    content_path = Path(content_path) if content_path else CONTENT
    out = Path(out) if out else OUT
    content = json.loads(content_path.read_text(encoding="utf-8"))
    globals()["CONTENT"] = content_path
    out.mkdir(parents=True, exist_ok=True)
    if preview:
        durations = [max(2.5, len(c.get("narration", "")) * 0.19)
                     for c in content["chapters"]]
    else:
        parts = _part_files(out)
        _, durations = assemble_audio(out, parts)
    timeline = build_timeline(content, durations)
    cues = build_subtitle_cues(content, timeline, max_chars=44, line_chars=44,
                               by_sentence=True)
    for cue in cues:  # 单行模式:去掉折行,整条一行显示
        cue["text"] = cue["text"].replace("\n", "")
    frames, layout_reports = _layout_samples(content, timeline, cues, out)
    result: dict[str, Any] = {"frames": [str(p) for p in frames]}
    report_path = out / "layout_report.json"
    report_payload = {
        "ok": not any(r["issues"] for r in layout_reports),
        "frame_count": len(layout_reports),
        "issue_count": sum(len(r["issues"]) for r in layout_reports),
        "frames": layout_reports,
    }
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    result["layout_report"] = str(report_path)
    if preview:
        sheet = out / "contact_sheet_v3.png"
        _contact_sheet(frames, sheet)
        result["contact_sheet"] = str(sheet)
    if not report_payload["ok"]:
        raise RuntimeError(f"布局校验失败: {report_path}")
    if render:
        audio = out / "audio.wav"
        (out / "timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
        write_srt(cues, out / "subtitles.srt")
        video = out / (content.get("video_name") or f"{content_path.stem}.mp4")
        result["report"] = render_video(content, timeline, cues, audio, video)
        result["video"] = str(video)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--content", type=Path, default=CONTENT,
                        help="内容 JSON(决定 broll/bg 资产目录与成片名)")
    args = parser.parse_args()
    try:
        result = run(preview=args.preview or not args.render,
                     render=args.render, out=args.out, content_path=args.content)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
