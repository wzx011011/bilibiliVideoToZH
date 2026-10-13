# -*- coding: utf-8 -*-
"""溯源篇 S1《满天星斗·良渚》场景绘制。

vector_render painters 装载机制加载。考古大地皮肤:灰米纸底+玉青主色+朱砂强调。
本集无具名人物(史前无文字),画面锚=遗迹/器物/地层意象;人名签机制自然休眠。
"""
from __future__ import annotations

_STATE: dict = {}
C: dict = {}


def bind(content: dict) -> None:
    _STATE["content"] = content


def skin(vr) -> None:
    _STATE["vr"] = vr
    C.update(
        PAPER=(233, 228, 218), INK=(40, 36, 30), RED=(168, 60, 46),
        DARKRED=(122, 40, 30), JADE=(72, 122, 106), JADE_D=(48, 88, 76),
        YELLOW=(196, 148, 52), GRAY=(133, 127, 116), OCHRE=(150, 105, 60),
        SLIP=(235, 228, 206), CARD=(238, 233, 218), WATER=(108, 138, 148),
    )
    vr.PAPER = C["PAPER"]; vr.INK = C["INK"]; vr.RED = C["RED"]
    vr.DARKRED = C["DARKRED"]; vr.BLUE = C["JADE"]; vr.YELLOW = C["YELLOW"]
    vr.SEA = C["WATER"]; vr.GRAY = C["GRAY"]


def _vr():
    return _STATE["vr"]


def base_line(b, t0=.03, t1=.09):
    b.line((150, 890), (1770, 890), C["GRAY"], 2, t0, t1, amp=1.0)


def bottom(b, s, span):
    b.text((140, 935), s, 42, C["INK"], span[0], span[1])


def tally(b, x0, y0, cols, rows, s, gap, span, *, hot=0, hot_color=None):
    hot_color = hot_color or C["JADE"]
    t0, t1 = span
    n = cols * rows
    per = (t1 - t0) / n
    for i in range(n):
        r, ci = divmod(i, cols)
        x, y = x0 + ci * (s + gap), y0 + r * (s + gap)
        a = t0 + i * per
        b.fillr((x, y, x + s, y + s), hot_color if i < hot else (216, 208, 188), a, radius=3)


# ---------------- 场景 ----------------

def s1(b):
    base_line(b)
    b.text((150, 205), "一个没有文字的国度", 84, C["INK"], .05, .17)
    b.text((160, 322), "—— 五千年文明的实证", 40, C["JADE"], .16, .25)
    b.tag((140, 390), "2019 · 列入世界遗产名录", (.25, .33), fill=C["DARKRED"])
    b.text((150, 470), "没有文字 · 没有青铜", 34, C["DARKRED"], .30, .40)
    b.ellipse(1440, 660, 300, 190, C["JADE_D"], 5, .34, .46)
    b.ellipse(1440, 660, 210, 130, C["WATER"], 4, .44, .54)
    b.fillr((1360, 620, 1520, 700), C["SLIP"], .52, radius=6)
    b.text((1290, 730), "一座城 · 一组坝 · 一片王陵", 32, C["INK"], .58, .70)
    b.bubble(500, 760, 360, 104, (.66, .82))
    b.text((372, 732), "凭什么算文明?就凭这三样", 30, C["INK"], .70, .84)
    bottom(b, "中华五千年,不是口号,是证据链", (.86, .96))


def s2(b):
    b.tag((140, 175), "外围水利系统 · 11 条坝", (.04, .13), fill=C["DARKRED"], size=34)
    for i, (y, w) in enumerate(((300, 1500), (430, 1240), (560, 980))):
        b.line((210, y), (210 + w, y), C["OCHRE"], 9, .12 + i * .05, .26 + i * .05, amp=1.2)
    b.fillp([(420, 320), (1620, 320), (1560, 560), (480, 560)], (206, 216, 214), .30, )
    b.text((700, 420), "高库 · 低库", 34, C["WATER"], .34, .42)
    b.tag((140, 660), "土方 ≈ 1000 万 m³ = 4×胡夫金字塔", (.44, .56), fill=C["RED"], size=28)
    b.arrow([(1500, 250), (1560, 640)], (.56, .64), color=C["WATER"])
    b.text((1560, 200), "拦洪", 28, C["DARKRED"], .60, .66)
    b.text((140, 780), "同期全球最大水利工程,而他们没有金属工具", 32, C["INK"], .68, .80)
    bottom(b, "先治水,后筑城——文明的顺序", (.84, .96))


def s3(b):
    b.tag((140, 175), "良渚古城 · 约 300 万 m²", (.04, .13), fill=C["DARKRED"], size=34)
    b.ellipse(1080, 560, 480, 300, C["JADE_D"], 5, .12, .24)
    b.ellipse(1080, 560, 360, 220, (206, 214, 210), 4, .22, .32)
    b.fillr((880, 380, 1280, 540), C["SLIP"], .30, radius=8)
    b.text((960, 420), "莫角山宫殿", 30, C["INK"], .36, .44)
    b.fillr((1300, 620, 1400, 690), C["RED"], .44, radius=4)
    b.text((1180, 700), "反山王陵", 28, C["DARKRED"], .48, .56)
    b.tag((140, 760), "≈ 4 座紫禁城", (.56, .66), fill=C["RED"], size=30)
    b.text((140, 850), "五千年前地球上最大的城市之一", 32, C["INK"], .70, .80)
    bottom(b, "城,是文明的第一份答卷", (.84, .96))


def s4(b):
    b.tag((140, 175), "反山十二号墓 · 玉琮王", (.04, .13), fill=C["DARKRED"], size=34)
    b.fillr((620, 340, 1060, 780), C["JADE"], .12, radius=10)
    b.ellipse(840, 560, 130, 130, C["PAPER"], 6, .22, .32)
    b.text((560, 820), "外方 · 内圆", 30, C["GRAY"], .30, .38)
    b.text((1240, 300), "神人兽面 · 神徽", 34, C["INK"], .40, .50)
    for i in range(6):
        b.line((1280, 360 + i * 16), (1720, 360 + i * 16), C["JADE_D"], 2, .46 + i * .02, .56 + i * .02, amp=.4)
    b.tag((1240, 520), "1 毫米刻 4-5 条线", (.56, .66), fill=C["RED"], size=28)
    b.text((1240, 620), "比头发丝还细的阴刻线", 28, C["GRAY"], .64, .72)
    b.tag((140, 760), "高 8.9cm · 重 6.5kg", (.70, .80), fill=C["DARKRED"], size=28)
    bottom(b, "没有金属工具,却做出了微雕", (.84, .96))


def s5(b):
    b.tag((140, 175), "玉 = 身份系统", (.04, .13), fill=C["DARKRED"], size=34)
    tiers = ((260, 560, 460, C["RED"], "王 · 琮璧钺成套"),
             (560, 780, 640, C["JADE"], "贵族 · 零星几件"),
             (780, 940, 820, (196, 188, 166), "平民 · 几乎无玉"))
    sp = [( .12, .26), (.26, .38), (.38, .50)]
    for (y0, y1, w, col, lab), s in zip(tiers, sp):
        b.fillr((220 + (760 - w) // 2, y0, 220 + (760 - w) // 2 + w, y1), col, s[0], radius=6)
        b.text((250, y0 + 24), lab, 30, C["PAPER"] if col != (196, 188, 166) else C["INK"], s[0], s[1])
    tally(b, 1300, 420, 6, 5, 34, 12, (.50, .78), hot=3)
    b.text((1290, 720), "玉器从王到平民递减", 28, C["GRAY"], .78, .86)
    b.text((140, 960 - 20), "漆器 · 黑陶 · 丝绸,金字塔形社会摆在地下", 28, C["INK"], .82, .92)


def s6(b):
    b.tag((140, 175), "饭稻羹鱼 · 池中寺粮仓", (.04, .13), fill=C["DARKRED"], size=34)
    b.fillr((220, 340, 760, 700), C["SLIP"], .10, radius=10)
    b.poly([(240, 340), (740, 340), (700, 280), (280, 280)], C["OCHRE"], 6, .14, .22, close=True)
    tally(b, 250, 380, 8, 6, 40, 10, (.20, .52), hot=6)
    b.text((240, 740), "碳化稻谷 ≈ 20 万公斤", 30, C["DARKRED"], .54, .62)
    b.line((1240, 660), (1440, 460), C["OCHRE"], 10, .58, .66)
    b.fillp([(1440, 460), (1560, 430), (1520, 520)], C["GRAY"], .64)
    b.text((1220, 720), "骨耜", 28, C["GRAY"], .66, .72)
    b.tag((1240, 260), "养活数万人口", (.68, .78), fill=C["JADE_D"], size=30)
    bottom(b, "南方,从此是中国的大粮仓", (.82, .94))


def s7(b):
    b.tag((140, 175), "同代群星 · 满天星斗", (.04, .13), fill=C["DARKRED"], size=34)
    stars = [(380, 380, "红山", 30), (960, 300, "凌家滩", 24), (1500, 420, "石家河", 26),
             (500, 650, "仰韶", 26), (1200, 700, "龙山", 24), (960, 540, "良渚", 40)]
    sp = [(.12, .26), (.18, .32), (.24, .38), (.30, .44), (.36, .50), (.44, .62)]
    for (x, y, nm, r), s in zip(stars, sp):
        b.ellipse(x, y, r, r, C["JADE"], 4, s[0], s[1])
        if nm == "良渚":
            b.ellipse(x, y, r + 14, r + 14, C["RED"], 3, s[0] + .04, s[1])
        b.text((x - 34, y + r + 12), nm, 28, C["INK"], s[0], s[1])
    b.text((150, 820), "苏秉琦:中华文明起源,如满天星斗", 32, C["INK"], .66, .78)
    b.tag((140, 660), "多元一体", (.78, .88), fill=C["RED"], size=30)
    bottom(b, "良渚不是孤星,是最亮的那颗", (.88, .98))


def s8(b):
    b.tag((140, 175), "前2300 · 衰落与远行", (.04, .13), fill=C["DARKRED"], size=34)
    b.ellipse(560, 520, 240, 150, C["GRAY"], 4, .10, .20)
    b.line((400, 520), (400, 640), C["WATER"], 6, .18, .26, amp=1.0)
    b.line((560, 500), (560, 660), C["WATER"], 6, .20, .28, amp=1.0)
    b.line((720, 520), (720, 640), C["WATER"], 6, .22, .30, amp=1.0)
    b.text((380, 720), "水患 · 最大的嫌疑人", 28, C["GRAY"], .30, .38)
    b.fillr((1000, 440, 1180, 620), C["JADE"], .40, radius=10)
    b.ellipse(1090, 530, 46, 46, C["PAPER"], 4, .46, .54)
    b.arrow([(1180, 530), (1640, 530)], (.52, .60), color=C["JADE"])
    b.text((1440, 460), "玉,北上中原", 30, C["JADE_D"], .58, .66)
    b.tag((140, 780), "商周王墓玉琮,源头在此", (.66, .78), fill=C["DARKRED"], size=28)
    bottom(b, "文明没有消失,只是换了方式往前走", (.82, .94))


def s9(b):
    base_line(b)
    b.tag((140, 178), "趣闻 · 换一张考卷", (.04, .12), fill=C["RED"], size=34)
    b.text((150, 268), "三要素,良渚全缺", 60, C["INK"], .08, .20)
    for i, nm in enumerate(("文字", "城市", "青铜")):
        x = 320 + i * 300
        b.tag((x, 420), nm, (.20 + i * .06, .30 + i * .06), fill=(196, 188, 166), size=32)
        b.xmark(x + 60, 500, 26, (.30 + i * .06, .38 + i * .06), color=C["RED"])
    for i, nm in enumerate(("城市", "阶级", "王权")):
        x = 1320 + i * 160
        b.tag((x, 640), nm, (.46 + i * .05, .54 + i * .05), fill=C["JADE_D"], size=28)
    b.text((1240, 560), "中国方案 ↓", 28, C["JADE"], .52, .60)
    b.text((150, 620), "老教材的文明三要素", 28, C["GRAY"], .24, .34)
    bottom(b, "良渚申遗成功 = 全世界承认了这张考卷", (.80, .94))


PAINTERS = {"s1": s1, "s2": s2, "s3": s3, "s4": s4,
            "s5": s5, "s6": s6, "s7": s7, "s8": s8, "s9": s9}

CAMS = {k: (lambda p, _z=z: (960, 552, _z)) for k, z in
        {"s1": .80, "s2": .80, "s3": .80, "s4": .80,
         "s5": .80, "s6": .80, "s7": .78, "s8": .80, "s9": .82}.items()}
