# -*- coding: utf-8 -*-
"""秦汉前传 ep01《长平之战》场景绘制。

由 vector_render painters 装载机制加载(内容 JSON "painters" 指向本文件)。
配色沿用秦汉皮肤(竹纸青灰/朱砂/铜绿);阵营色约定:秦=朱砂红,赵=铜绿。
"""
from __future__ import annotations

_STATE: dict = {}
C: dict = {}


def bind(content: dict) -> None:
    _STATE["content"] = content


def skin(vr) -> None:
    _STATE["vr"] = vr
    C.update(
        PAPER=(232, 227, 213), INK=(38, 35, 31), RED=(172, 44, 36),
        DARKRED=(126, 32, 26), GREEN=(58, 102, 88), YELLOW=(196, 148, 52),
        SEA=(213, 224, 221), GRAY=(133, 129, 120), OCHRE=(150, 105, 60),
        SLIP=(235, 228, 206), CARD=(238, 233, 218), QIN=(172, 44, 36), ZHAO=(58, 102, 88),
    )
    vr.PAPER = C["PAPER"]; vr.INK = C["INK"]; vr.RED = C["RED"]
    vr.DARKRED = C["DARKRED"]; vr.BLUE = C["GREEN"]; vr.YELLOW = C["YELLOW"]
    vr.SEA = C["SEA"]; vr.GRAY = C["GRAY"]


def _vr():
    return _STATE["vr"]


def base_line(b, t0=.03, t1=.09):
    b.line((150, 890), (1770, 890), C["GRAY"], 2, t0, t1, amp=1.0)


def bottom(b, s, span):
    b.text((140, 935), s, 42, C["INK"], span[0], span[1])


# ---------------- 场景 ----------------

def s1(b):
    vr = _vr()
    base_line(b)
    b.text((150, 205), "一块白捡的地", 88, C["INK"], .05, .17)
    b.text((160, 322), "—— 上党之祸", 40, C["GREEN"], .16, .25)
    b.tag((140, 390), "秦攻韩 · 前262", (.25, .33), fill=C["DARKRED"])
    gx, gy = vr.make_proj(108.71, 35.6, 170, 520, 560)
    yellow_mid = [(110.5, 36.4), (110.35, 35.7), (110.42, 34.98), (110.28, 34.62),
                  (110.9, 34.75), (112.2, 34.9), (113.4, 34.85), (114.3, 34.9)]
    b.poly([(gx(lo), gy(la)) for lo, la in yellow_mid], vr.BLUE_L, 4, .06, .30, amp=1.2)
    b.text((gx(111.6), gy(36.05)), "黄河", 26, C["GRAY"], .18, .26)
    cities = [("咸阳", 108.71, 34.33, C["QIN"], "秦都"),
              ("野王", 112.94, 35.09, C["GRAY"], ""),
              ("上党", 113.08, 36.19, C["YELLOW"], "十七城"),
              ("邯郸", 114.49, 36.61, C["ZHAO"], "赵都")]
    spans = vr.seq_spans(4, .24, .46)
    for (name, lon, lat, col, sub), sp in zip(cities, spans):
        b.fillp([(gx(lon) - 11, gy(lat) - 11), (gx(lon) + 11, gy(lat) - 11),
                 (gx(lon) + 11, gy(lat) + 11), (gx(lon) - 11, gy(lat) + 11)], col, sp[0])
        b.text((gx(lon) + 16, gy(lat) - 38), name, 32, C["INK"], sp[0], sp[1])
        if sub:
            b.text((gx(lon) + 16, gy(lat) - 2), sub, 24, C["DARKRED"], sp[1], sp[1] + .05)
    b.arrow([(gx(108.71) + 20, gy(34.33) - 16), (gx(112.94) - 24, gy(35.09) + 24)],
            (.46, .54), color=C["QIN"])
    b.xmark(gx(112.94) + 52, gy(35.09) - 36, 20, (.52, .58), color=C["QIN"])
    b.text((gx(112.4) - 210, gy(35.09) - 96), "切断韩道", 28, C["DARKRED"], .54, .62)
    b.arrow([(gx(113.08) + 8, gy(36.19) - 8), (gx(114.49) - 20, gy(36.61) + 22)],
            (.62, .70), color=C["ZHAO"])
    b.text((gx(113.7) - 60, gy(36.9) + 10), "献城于赵", 28, C["ZHAO"], .66, .74)
    b.figure(600, 880, 290, (.30, .48), role="official", mood="sad", flip=True)
    b.text((480, 905), "冯亭·上党郡守", 34, C["INK"], .42, .50)
    b.figure(1180, 880, 300, (.48, .66), role="official", mood="smirk")
    b.text((1070, 905), "平原君·赵胜", 34, C["INK"], .58, .66)
    b.bubble(1560, 350, 340, 104, (.68, .84))
    b.text((1430, 322), "白捡的便宜!", 34, C["INK"], .72, .86)
    bottom(b, "笑纳了地,也笑纳了秦国的怒火", (.86, .96))


def s2(b):
    vr = _vr()
    b.tag((140, 175), "前261 · 长平对峙", (.04, .13), fill=C["DARKRED"], size=34)
    b.wall(220, 1050, 600, 200, (.08, .26), gate=True, tower=True)
    b.figure(640, 560, 240, (.24, .42), role="official", mood="neutral", beard=True)
    b.text((520, 585), "廉颇", 36, C["ZHAO"], .34, .42)
    b.text((260, 340), "坚壁 · 不出战", 40, C["ZHAO"], .30, .40)
    vr.crowd(b, 1210, 620, 30, 5, (.36, .56), C["QIN"])
    b.flag(1150, 430, 60, (.44, .52), color=C["QIN"])
    b.flag(1420, 470, 52, (.48, .56), color=C["QIN"])
    b.text((1210, 300), "秦军 · 利在速战", 36, C["DARKRED"], .50, .60)
    b.tag((140, 660), "一晃 · 一年多", (.58, .68), fill=C["RED"], size=30)
    b.fillr((1450, 620, 1700, 760), C["CARD"], .62, radius=6)
    b.text((1478, 632), "秦:粮道越拉越长", 28, C["DARKRED"], .64, .72)
    b.text((1478, 690), "赵:粮仓越挖越空", 28, C["ZHAO"], .70, .78)
    bottom(b, "老将不出,秦军没辙——两边都在熬", (.82, .94))


def s3(b):
    b.tag((140, 175), "前260 · 咸阳与邯郸", (.04, .13), fill=C["DARKRED"], size=34)
    b.text((240, 300), "咸阳", 40, C["QIN"], .08, .16)
    b.figure(380, 880, 300, (.10, .28), role="emperor", mood="neutral", beard=True)
    b.text((250, 905), "秦昭王", 34, C["INK"], .20, .28)
    b.figure(740, 880, 280, (.24, .42), role="official", mood="smirk")
    b.text((630, 905), "范雎·相国", 34, C["INK"], .34, .42)
    b.ellipse(940, 700, 34, 22, C["YELLOW"], 4, .36, .44)
    b.text((890, 730), "千金", 26, C["DARKRED"], .40, .48)
    b.arrow([(990, 690), (1330, 640)], (.48, .58), color=C["GRAY"])
    b.text((1080, 580), "流言入邯郸", 30, C["GRAY"], .52, .60)
    b.text((1360, 300), "邯郸", 40, C["ZHAO"], .56, .64)
    b.figure(1500, 880, 300, (.58, .76), role="emperor", mood="worried")
    b.text((1380, 905), "赵孝成王", 34, C["INK"], .68, .76)
    b.bubble(1560, 430, 380, 112, (.66, .82))
    b.text((1400, 402), "秦人独畏·赵括为将", 30, C["INK"], .70, .84)
    b.tag((140, 660), "换将!廉颇黯然离营", (.82, .92), fill=C["RED"], size=30)
    bottom(b, "反间计只用四两,赵王的急才是千斤", (.90, .98))


def s4(b):
    b.tag((140, 175), "将门虎子 · 纸上谈兵", (.04, .13), fill=C["DARKRED"], size=34)
    b.figure(1220, 880, 320, (.14, .34), role="official", mood="smirk")
    b.text((1100, 905), "赵括", 38, C["ZHAO"], .26, .34)
    for i in range(3):
        x = 760 + i * 90
        b.fillr((x, 700, x + 70, 850), C["SLIP"], .30 + i * .04, radius=3)
        b.line((x + 12, 724), (x + 58, 724), C["GRAY"], 2, .34 + i * .04, .40, amp=.5)
        b.line((x + 12, 756), (x + 58, 756), C["GRAY"], 2, .34 + i * .04, .40, amp=.5)
    b.text((790, 640), "兵书 · 倒背如流", 30, C["GRAY"], .38, .46)
    b.bubble(1560, 420, 360, 104, (.44, .60))
    b.text((1410, 392), "用兵?我熟!", 34, C["INK"], .48, .62)
    b.figure(420, 880, 300, (.56, .74), role="official", mood="sad", beard=True)
    b.text((300, 905), "赵奢·父", 36, C["INK"], .68, .76)
    b.bubble(420, 400, 420, 116, (.72, .88))
    b.text((262, 372), "破赵军者,必括也", 30, C["DARKRED"], .76, .90)
    bottom(b, "兵书烂熟,战场——一次都没上过", (.88, .98))


def s5(b):
    b.tag((140, 175), "前260 · 秘密换将", (.04, .13), fill=C["DARKRED"], size=34)
    b.figure(400, 880, 320, (.10, .30), role="soldier", mood="angry")
    b.text((270, 905), "白起·武安君", 36, C["QIN"], .22, .30)
    b.tag((140, 260), "泄密者 · 斩", (.28, .38), fill=C["RED"], size=30)
    b.figure(760, 880, 270, (.30, .46), role="emperor", mood="neutral", beard=True)
    b.text((655, 905), "秦昭王", 34, C["INK"], .40, .48)
    b.wall(1080, 1700, 640, 160, (.44, .60), gate=True, tower=False)
    b.text((1210, 690), "秦营", 30, C["GRAY"], .56, .62)
    b.arrow([(1560, 560), (1780, 470)], (.58, .66), color=C["QIN"])
    b.text((1560, 400), "佯败 · 后撤", 30, C["DARKRED"], .62, .70)
    b.figure(1640, 860, 260, (.66, .82), role="official", mood="smirk")
    b.tag((140, 660), "赵括:敌退可追!", (.72, .82), fill=C["ZHAO"], size=30)
    b.text((1420, 905), "赵括·倾巢而出", 30, C["ZHAO"], .78, .86)
    bottom(b, "杀神就位,口袋张开", (.88, .98))


def s6(b):
    vr = _vr()
    b.tag((140, 175), "前260 · 断粮 · 合围", (.03, .10), fill=C["DARKRED"], size=34)
    cx, cy = 1000, 600
    # 粮道自邯郸方向画出,粮车行进
    b.line((180, 560), (cx - 360, 560), C["OCHRE"], 8, .06, .16, amp=1.0)
    b.text((190, 466), "邯郸方向 · 粮道", 26, C["GRAY"], .14, .20)
    for x, sp in ((330, (.10, .16)), (470, (.14, .20)), (610, (.18, .24))):
        b.fillr((x - 17, 538, x + 17, 582), C["YELLOW"], sp[0], radius=3)
    # 红X 斩断
    b.xmark(700, 560, 32, (.26, .34), color=C["QIN"])
    b.tag((560, 626), "粮道已断", (.30, .38), fill=C["RED"], size=28)
    # 四路合围,箭头推进
    dirs = [((cx - 540, cy - 280), (cx - 190, cy - 120)),
            ((cx + 540, cy - 280), (cx + 190, cy - 120)),
            ((cx - 540, cy + 300), (cx - 190, cy + 130)),
            ((cx + 540, cy + 300), (cx + 190, cy + 130))]
    for i, ((sx, sy), (ex, ey)) in enumerate(dirs):
        b.arrow([(sx, sy), (ex, ey)], (.30 + i * .05, .44 + i * .05), color=C["QIN"])
    b.ellipse(cx, cy, 340, 230, C["GRAY"], 3, .34, .44)
    vr.crowd(b, cx - 160, cy + 50, 24, 6, (.40, .55), C["ZHAO"])
    vr.crowd(b, cx - 160, cy + 50, 24, 6, (.64, .78), C["GRAY"])
    # 计日翻牌:同位 tag 顺序覆盖
    for d, t0 in ((7, .40), (14, .46), (21, .52), (28, .58), (35, .64), (40, .70), (44, .76), (46, .80)):
        b.tag((1568, 214), f"第 {d} 天", (t0, t0 + .05), fill=C["DARKRED"], size=30)
    for i in range(46):
        b.fillr((1336 + i * 10, 300, 1344 + i * 10, 314),
                C["QIN"] if i % 7 == 6 else (198, 128, 116), .38 + i * .0098, radius=0)
    b.text((1336, 332), "0 → 46 天", 24, C["GRAY"], .84, .90)
    b.tag((140, 850), "援兵与粮车 · 一辆也进不来", (.78, .88), fill=C["RED"], size=30)
    bottom(b, "围而不打,耗到粮尽", (.90, .98))

def s7(b):
    vr = _vr()
    b.tag((140, 175), "前260年九月 · 突围", (.04, .13), fill=C["DARKRED"], size=34)
    cx, cy = 760, 560
    for dx, dy, t0 in ((0, -240, .10), (240, 120, .16), (-240, 120, .22)):
        b.arrow([(cx, cy), (cx + dx, cy + dy)], (t0, t0 + .08), color=C["ZHAO"])
    b.figure(cx, cy + 220, 260, (.26, .42), role="official", mood="sad")
    b.text((cx - 100, cy + 245), "赵括", 34, C["ZHAO"], .36, .44)
    b.xmark(cx + 130, cy + 60, 24, (.42, .48), color=C["QIN"])
    b.text((cx + 180, cy - 20), "中流箭 · 亡", 28, C["DARKRED"], .46, .54)
    b.text((1350, 300), "40万", 130, C["RED"], .50, .68)
    b.text((1350, 470), "赵军放下武器", 34, C["INK"], .60, .70)
    b.tag((1330, 560), "放回二百四十人报信", (.66, .78), fill=C["GRAY"], size=26)
    vr.crowd(b, 1380, 830, 20, 4, (.72, .86), C["GRAY"])
    b.tag((140, 660), "余者 · 坑杀", (.78, .88), fill=C["DARKRED"], size=30)
    bottom(b, "赵国一朝,折了整整一代男人", (.88, .98))


def s8(b):
    vr = _vr()
    base_line(b)
    b.tag((140, 175), "前259 · 长平之后", (.04, .12), fill=C["DARKRED"], size=34)
    b.text((140, 268), "六国,再无对手", 64, C["INK"], .08, .20)
    b.fillr((220, 480, 760, 860), C["QIN"], .20, radius=8)
    b.text((460, 630), "秦", 64, (240, 232, 216), .28, .38)
    states = [("赵", 900), ("燕", 1010), ("齐", 1120), ("魏", 1230), ("韩", 1340), ("楚", 1450)]
    spans = vr.seq_spans(6, .30, .62)
    for (nm, x), sp in zip(states, spans):
        b.fillr((x, 560, x + 84, 720), (196, 188, 166), sp[0], radius=6)
        b.text((x + 22, 606), nm, 34, C["INK"], sp[0], sp[1])
    b.arrow([(790, 660), (870, 660)], (.60, .68), color=C["QIN"])
    b.text((220, 900), "一台机器,对六个迟暮的国家", 36, C["INK"], .66, .76)
    b.bubble(1450, 780, 380, 110, (.72, .88))
    b.text((1315, 752), "你是赵王,换不换将?评论区聊", 24, C["INK"], .76, .90)
    bottom(b, "此战之后,天下只剩一个问题:谁先被灭", (.86, .97))


def s9(b):
    base_line(b)
    b.tag((140, 175), "趣闻 · 纸上谈兵?", (.04, .12), fill=C["DARKRED"], size=34)
    b.text((150, 268), "一个穿越道具", 60, C["INK"], .06, .18)
    for i in range(3):
        y = 430 + i * 90
        b.fillr((300, y, 500, y + 70), C["SLIP"], .16 + i * .04, radius=4)
        b.line((320, y + 24), (480, y + 24), C["GRAY"], 2, .20 + i * .04, .28, amp=.5)
        b.line((320, y + 46), (480, y + 46), C["GRAY"], 2, .20 + i * .04, .28, amp=.5)
    b.text((300, 720), "竹简 · 赵括的兵书", 30, C["INK"], .30, .40)
    b.fillr((1200, 450, 1440, 640), (248, 246, 240), .40, radius=4)
    b.poly([(1200, 450), (1440, 450)], C["GRAY"], 3, .40, .46, amp=.6)
    b.poly([(1200, 505), (1440, 505)], C["GRAY"], 3, .42, .48, amp=.6)
    b.poly([(1200, 560), (1440, 560)], C["GRAY"], 3, .44, .50, amp=.6)
    b.text((1150, 740), "纸 · 四百年后才出生", 30, C["DARKRED"], .48, .60)
    b.xmark(1320, 545, 40, (.62, .70), color=C["RED"])
    b.tag((140, 800), "真要严谨:该叫简上谈兵", (.70, .82), fill=C["DARKRED"], size=30)
    bottom(b, "成语定型,晚到清代的书里", (.84, .96))


PAINTERS = {"s1": s1, "s2": s2, "s3": s3, "s4": s4,
            "s5": s5, "s6": s6, "s7": s7, "s8": s8, "s9": s9}

# 镜头语义:每场缓动,避免静止感。z 缩放(窗口高=700/zoom),cx/cy 平移。
CAMS = {
    "s1": lambda p: (960, 552, 0.76 + 0.08 * min(1.0, p * 1.4)),          # 地图场缓慢推近
    "s2": lambda p: (960, 540 + 40 * p, 0.82),                            # 自壁垒下移看秦营
    "s3": lambda p: (520 + 880 * p, 552, 0.84),                           # 咸阳→邯郸横向跟随
    "s4": lambda p: (960, 552, 0.86 - 0.08 * min(1.0, p * 1.4)),          # 拉远显父子对望
    "s5": lambda p: (960, 552, 0.74 + 0.12 * min(1.0, p * 1.3)),          # 推向杀神
    "s6": lambda p: (960, 552, 0.88 - 0.12 * min(1.0, p * 1.4)),          # 拉远显合围全貌
    "s7": lambda p: (960, 545, 0.92 - 0.10 * min(1.0, p * 1.4)),          # 冲锋后缓缓拉远
    "s8": lambda p: (960, 552, 0.82),                                     # 收尾
    "s9": lambda p: (960, 552, 0.80),                                     # 趣闻尾声
}
