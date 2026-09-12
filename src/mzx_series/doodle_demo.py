# -*- coding: utf-8 -*-
"""混子哥式白板手绘风格可行性验证:抖动笔画 + 逐笔生长 + 笔尖跟随。

渲染同一场景在 t=0.35 / 0.7 / 1.0 的三个状态,验证"边画边讲"能否成立。
内容用《明朝那些事儿》线里的"靖难之役"做样片(风格自绘,非临摹任何原画)。
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BOARD = (250, 250, 248)
BLACK = (38, 38, 42)
BLUE = (28, 62, 148)
GRAY = (120, 120, 126)
OUT = Path("D:/mzx-lunchiuzhan")


def _font(size: int):
    for name in ("STXINGKA.TTF", "simkai.ttf", "msyh.ttc"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def _jitter_line(p0, p1, rng, amp=2.5, segs=None):
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = segs or max(3, int(length / 55))
    pts = []
    nx, ny = -(p1[1] - p0[1]), (p1[0] - p0[0])
    norm = math.hypot(nx, ny) or 1.0
    nx, ny = nx / norm, ny / norm
    for i in range(n + 1):
        t = i / n
        x = p0[0] + (p1[0] - p0[0]) * t + nx * rng.uniform(-amp, amp)
        y = p0[1] + (p1[1] - p0[1]) * t + ny * rng.uniform(-amp, amp)
        pts.append((x, y))
    pts[0], pts[-1] = p0, p1
    return pts


def _wobble_blob(cx, cy, rx, ry, rng, amp=3.0, n=26):
    pts = []
    phase = rng.uniform(0, 6.28)
    for i in range(n):
        a = 2 * math.pi * i / n
        k = 1 + rng.uniform(-amp / max(rx, 1), amp / max(rx, 1))
        pts.append((cx + rx * k * math.cos(a + phase * 0.0),
                    cy + ry * k * math.sin(a)))
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
            out.append((x1, y1))
            budget -= d
        else:
            t = budget / max(d, 1e-6)
            tip = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            out.append(tip)
            return out, tip
    return out, out[-1]


class Board:
    def __init__(self):
        self.rng = random.Random(20260907)
        self.strokes = []  # (pts, color, width, t0, t1)

    def line(self, p0, p1, color=BLACK, width=5, t0=0.0, t1=1.0, amp=2.5):
        self.strokes.append((_jitter_line(p0, p1, self.rng, amp), color, width, t0, t1))

    def poly(self, pts, color=BLACK, width=5, t0=0.0, t1=1.0, close=False):
        seq = list(pts) + ([pts[0]] if close else [])
        flat = []
        for a, b in zip(seq, seq[1:]):
            flat.extend(_jitter_line(a, b, self.rng, 2.5)[:-1])
            flat.append(b)
        self.strokes.append((flat, color, width, t0, t1))

    def blob(self, cx, cy, rx, ry, color=BLACK, width=5, t0=0.0, t1=1.0):
        self.strokes.append((_wobble_blob(cx, cy, rx, ry, self.rng), color, width, t0, t1))

    def castles(self, cx, cy, scale, color, t0, t1):
        """小城堡:城垛+门。"""
        s = scale
        self.line((cx - 3 * s, cy), (cx - 3 * s, cy - 3 * s), color, 5, t0, t0 + (t1 - t0) * .4)
        self.line((cx + 3 * s, cy), (cx + 3 * s, cy - 3 * s), color, 5, t0, t0 + (t1 - t0) * .4)
        self.line((cx - 3 * s, cy - 3 * s), (cx + 3 * s, cy - 3 * s), color, 5,
                  t0 + (t1 - t0) * .3, t0 + (t1 - t0) * .7)
        for i, x in enumerate((-3, -1.6, -0.2, 1.2, 2.6)):
            self.line((cx + x * s, cy - 3 * s), (cx + x * s, cy - 4 * s), color, 4,
                      t0 + (t1 - t0) * .6, min(t1, t0 + (t1 - t0) * .8 + i * 0.01))
        self.line((cx + 2.6 * s, cy - 4 * s), (cx + 3 * s, cy - 3 * s), color, 4,
                  t0 + (t1 - t0) * .85, t1)
        self.blob(cx, cy - s * 0.2, s * 0.8, s * 0.9, color, 4,
                  t0 + (t1 - t0) * .8, t1)

    def stickman(self, cx, cy, s, color, t0, t1, hat=False, sword=False):
        """火柴人:头+身+四肢,可选王冠/剑。"""
        steps = 6
        def win(k):
            return t0 + (t1 - t0) * k / steps, t0 + (t1 - t0) * (k + 1) / steps
        a, b = win(0)
        self.blob(cx, cy - 3.2 * s, s * 1.05, s * 1.2, color, 5, a, b)
        a, b = win(1)
        self.line((cx, cy - 2.1 * s), (cx, cy + 0.6 * s), color, 5, a, b)
        a, b = win(2)
        self.line((cx, cy - 1.2 * s), (cx - 1.5 * s, cy + 0.1 * s), color, 5, a, b)
        self.line((cx, cy - 1.2 * s), (cx + 1.5 * s, cy + 0.1 * s), color, 5, a, b)
        a, b = win(3)
        self.line((cx, cy + 0.6 * s), (cx - 1.1 * s, cy + 2.4 * s), color, 5, a, b)
        self.line((cx, cy + 0.6 * s), (cx + 1.1 * s, cy + 2.4 * s), color, 5, a, b)
        if hat:
            a, b = win(4)
            self.line((cx - 1.4 * s, cy - 4.4 * s), (cx + 1.4 * s, cy - 4.4 * s), color, 5, a, b)
            self.line((cx - 0.5 * s, cy - 4.4 * s), (cx - 0.7 * s, cy - 5.3 * s), color, 5, a, b)
            self.line((cx + 0.5 * s, cy - 4.4 * s), (cx + 0.7 * s, cy - 5.3 * s), color, 5, a, b)
        if sword:
            a, b = win(5)
            self.line((cx + 1.5 * s, cy + 0.1 * s), (cx + 3.1 * s, cy - 1.8 * s), color, 4, a, b)

    def text(self, d, xy, s, size, color, t, t0, t1):
        if t >= t1:
            d.text(xy, s, font=_font(size), fill=color)
        elif t > t0:
            f = (t - t0) / (t1 - t0)
            d.text(xy, s[:max(1, int(len(s) * f))], font=_font(size), fill=color)

    def render(self, t: float) -> Image.Image:
        img = Image.new("RGB", (W, H), BOARD)
        d = ImageDraw.Draw(img)
        tip = None
        for pts, color, width, t0, t1 in self.strokes:
            if t <= t0:
                continue
            f = 1.0 if t >= t1 else (t - t0) / max(t1 - t0, 1e-6)
            seg, end = _partial(pts, f)
            if len(seg) >= 2:
                d.line(seg, fill=color, width=width, joint="curve")
                for x, y in seg[::6]:
                    d.ellipse((x - width * .45, y - width * .45,
                               x + width * .45, y + width * .45), fill=color)
            if f < 1.0 and (tip is None or t0 >= tip[0]):
                tip = (t0, end)
        # 文字层
        self.text(d, (120, 90), "靖难之役", 96, BLUE, t, 0.02, 0.10)
        self.text(d, (120, 200), "朱棣 vs 建文帝 · 一场叔侄之争", 40, BLACK, t, 0.10, 0.16)
        self.text(d, (170, 750), "北平（朱棣）", 44, BLUE, t, 0.46, 0.54)
        self.text(d, (1280, 990), "南京（建文帝）", 44, BLUE, t, 0.62, 0.70)
        self.text(d, (820, 380), "四年拉锯", 44, BLACK, t, 0.78, 0.86)
        self.text(d, (935, 700), "南下", 40, BLACK, t, 0.70, 0.78)
        # 笔尖:跟随当前正在生长的笔画
        if tip and t < 1.0:
            _, (x, y) = tip
            d.polygon([(x, y), (x + 14, y - 26), (x + 44, y - 20), (x + 18, y + 2)],
                      fill=(50, 50, 55))
            d.rectangle((x + 34, y - 52, x + 76, y - 14), fill=(60, 60, 66))
        return img


def build_board() -> Board:
    b = Board()
    b.line((100, 320), (1820, 320), GRAY, 3, 0.16, 0.22, amp=2.0)          # 分隔线
    b.blob(560, 660, 190, 74, BLACK, 5, 0.22, 0.30)                        # 北平地形
    b.castles(560, 640, 30, BLACK, 0.26, 0.38)
    b.blob(1520, 900, 200, 80, BLACK, 5, 0.34, 0.42)                       # 南京地形
    b.castles(1520, 880, 34, BLACK, 0.38, 0.50)
    b.stickman(320, 600, 34, BLACK, 0.40, 0.52, hat=True, sword=True)      # 朱棣
    b.stickman(1730, 830, 30, BLACK, 0.52, 0.62)                           # 建文帝
    b.poly([(640, 640), (860, 700), (1050, 780), (1260, 830), (1400, 860)],
           BLUE, 7, 0.56, 0.70)                                            # 南下路线
    b.poly([(1400, 860), (1352, 826), (1372, 872)], BLUE, 7, 0.69, 0.72)   # 箭头
    b.line((900, 470), (1180, 470), BLACK, 6, 0.74, 0.80)                  # 拉锯括号线
    b.line((900, 470), (900, 445), BLACK, 5, 0.78, 0.82)
    b.line((1180, 470), (1180, 445), BLACK, 5, 0.80, 0.84)
    b.poly([(980, 950), (1120, 950), (1100, 1010), (960, 1010)], GRAY, 4, 0.88, 0.94)
    b.line((985, 978), (1100, 978), GRAY, 3, 0.92, 0.96)                   # 落款条
    return b


def main():
    OUT.mkdir(exist_ok=True)
    board = build_board()
    for i, t in enumerate((0.35, 0.7, 1.0)):
        p = OUT / f"doodle_t{int(t * 100):03d}.png"
        board.render(t).save(p, "PNG")
        print(p)


if __name__ == "__main__":
    main()
