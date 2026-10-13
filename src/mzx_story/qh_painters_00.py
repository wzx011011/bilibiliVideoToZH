# -*- coding: utf-8 -*-
"""秦汉前传 ep00《商鞅变法》场景绘制(试播集)。

由 vector_render 的 painters 装载机制加载(内容 JSON "painters" 字段指向本文件):
  bind(content)  存内容引用(s8 收尾卡读 takeaway/refs)
  skin(vr)       覆盖渲染器配色为秦汉皮肤(竹纸青灰/朱砂/铜绿),挂箭头等别名
  PAINTERS/CAMS  与 vector_render 同约定:kind → 画法/镜头

清晰度五件套在本集的落点:
  - 纪年角标+朝代条:渲染器 render_scene 按 era/year_val 画(本文件只提供数据)
  - 数量方块阵:tally()(编户齐民)
  - 机制收尾卡:s8 读 takeaway
  - 出场卡:人物首出场带"名·职务"标签(s1 秦孝公·嬴渠梁 / 卫鞅·自魏入秦)
  - 回调芯片:s8 takeaway.callback
"""
from __future__ import annotations
import math

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
        SLIP=(235, 228, 206), CARD=(238, 233, 218),
    )
    vr.PAPER = C["PAPER"]
    vr.INK = C["INK"]
    vr.RED = C["RED"]
    vr.DARKRED = C["DARKRED"]
    vr.BLUE = C["GREEN"]
    vr.YELLOW = C["YELLOW"]
    vr.SEA = C["SEA"]
    vr.GRAY = C["GRAY"]


def _vr():
    return _STATE["vr"]


def tally(b, x0, y0, cols, rows, s, gap, span, *, hot=0, hot_color=None,
          base=None, edge=None, width=2):
    """数量方块阵:cols×rows 小方块顺序出现,前 hot 个用强调色(数字可视化)。"""
    vr = _vr()
    hot_color = hot_color or C["RED"]
    base = base or (214, 206, 184)
    edge = edge or C["INK"]
    t0, t1 = span
    n = cols * rows
    per = (t1 - t0) / n
    for i in range(n):
        r, cix = divmod(i, cols)
        x = x0 + cix * (s + gap)
        y = y0 + r * (s + gap)
        a = t0 + i * per
        b.fillr((x, y, x + s, y + s), hot_color if i < hot else base, a, radius=3)
        b.poly([(x, y), (x + s, y), (x + s, y + s), (x, y + s)], edge, width,
               a, a + per * .6, close=True, amp=0.6)


def base_line(b, t0=.03, t1=.09):
    b.line((150, 890), (1770, 890), C["GRAY"], 2, t0, t1, amp=1.0)


def bottom(b, s, span):
    b.text((140, 935), s, 42, C["INK"], span[0], span[1])


# ---------------- 场景 ----------------

def s1(b):
    base_line(b)
    b.text((150, 205), "谁能让秦国强大", 92, C["INK"], .05, .17)
    b.text((160, 320), "—— 秦孝公的求贤令", 40, C["GREEN"], .16, .25)
    b.tag((140, 388), "秦孝公元年 · 前361", (.25, .33), fill=C["DARKRED"])
    b.text((150, 458), "六国卑秦 · 会盟不邀秦", 34, C["DARKRED"], .28, .38)
    b.figure(430, 880, 330, (.26, .46), role="emperor", mood="neutral", beard=True)
    b.text((310, 905), "秦孝公 · 嬴渠梁", 36, C["INK"], .40, .48)
    b.arrow([(1740, 690), (1300, 720)], (.46, .55), color=C["INK"])
    b.figure(1180, 880, 300, (.46, .64), role="official", mood="neutral", flip=True)
    b.text((1060, 905), "卫鞅 · 自魏入秦", 36, C["INK"], .58, .67)
    b.bubble(1500, 330, 340, 104, (.68, .84))
    b.text((1352, 300), "强国之术?我有!", 34, C["INK"], .73, .87)
    bottom(b, "一张求贤令,换来了帝国的总设计师", (.88, .96))


def s2(b):
    b.tag((140, 175), "前356 · 变法先立信", (.04, .13), fill=C["DARKRED"], size=34)
    b.wall(200, 700, 760, 190, (.10, .30), gate=True, tower=True)
    b.text((250, 655), "南门", 32, C["INK"], .26, .33)
    b.line((1150, 790), (1150, 480), C["OCHRE"], 10, .28, .38)
    b.fillp([(1150, 480), (1216, 458), (1150, 436)], C["YELLOW"], .38)
    b.text((1220, 500), "三丈之木", 32, C["INK"], .38, .46)
    crowd_vr = _vr().crowd
    crowd_vr(b, 620, 872, 26, 6, (.40, .62), C["INK"])
    b.figure(1330, 880, 250, (.46, .62), role="ragged", mood="neutral")
    b.arrow([(1210, 700), (1300, 720)], (.52, .60), color=C["INK"])
    b.tag((1420, 560), "加到五十金", (.56, .65), fill=C["RED"], size=30)
    b.ellipse(1470, 660, 30, 20, C["YELLOW"], 4, .58, .66)
    b.bubble(860, 340, 340, 100, (.64, .80))
    b.text((742, 312), "真给钱?!", 34, C["INK"], .69, .82)
    bottom(b, "第二天,全国都知道:官府说话算数", (.86, .96))


def s3(b):
    b.tag((140, 175), "前356 起 · 编户齐民", (.04, .13), fill=C["DARKRED"], size=34)
    b.figure(330, 880, 300, (.10, .30), role="official", mood="neutral")
    b.fillr((440, 640, 580, 770), C["CARD"], .26, radius=6)
    for i, ly in enumerate((676, 712, 748)):
        b.line((462, ly), (558, ly), C["GRAY"], 3, .28 + i * .03, .34 + i * .03, amp=0.5)
    b.text((420, 600), "户籍账本", 28, C["GRAY"], .36, .44)
    b.text((740, 262), "把每一户,变成账本上的数字", 52, C["INK"], .12, .26)
    tally(b, 760, 430, 5, 4, 56, 16, (.24, .60), hot=5)
    b.text((760, 742), "五家一伍 · 十家一什", 32, C["INK"], .60, .70)
    b.text((760, 800), "一家犯法 · 四家连带", 32, C["DARKRED"], .68, .78)
    b.arrow([(1180, 500), (1310, 462)], (.62, .70), color=C["INK"])
    b.fillr((1320, 430, 1660, 500), C["CARD"], .68, radius=6)
    b.text((1342, 438), "能征多少兵", 30, C["INK"], .68, .78)
    b.arrow([(1180, 620), (1310, 650)], (.70, .76), color=C["INK"])
    b.fillr((1320, 618, 1660, 688), C["CARD"], .76, radius=6)
    b.text((1342, 626), "能收多少粮", 30, C["INK"], .76, .86)
    bottom(b, "国家第一次,把自己数清了", (.86, .96))


def s4(b):
    b.tag((140, 175), "前353 · 二十等军功爵", (.04, .13), fill=C["DARKRED"], size=34)
    names = ["公士", "上造", "不更", "大夫", "公乘", "关内侯", "彻侯"]
    spans = _vr().seq_spans(7, .14, .56)
    for i, name in enumerate(names):
        x = 620 + i * 128
        y = 830 - i * 92
        fill = C["YELLOW"] if i >= 5 else ((196, 188, 166) if i % 2 else (216, 208, 186))
        b.fillr((x, y, x + 128, 898), fill, spans[i][0], radius=3)
        b.text((x + 20, y + 18), name, 30, C["INK"], spans[i][0], spans[i][1])
    b.text((170, 300), "斩首一级", 38, C["INK"], .08, .17)
    b.arrow([(320, 350), (560, 500)], (.15, .24), color=C["RED"])
    b.text((180, 420), "爵升一级", 38, C["DARKRED"], .20, .30)
    b.figure(760, 738, 220, (.32, .48), role="ragged", mood="neutral")
    b.tag((1400, 240), "宗室无军功 · 不得入宗谱", (.60, .72), fill=C["DARKRED"], size=28)
    b.text((1560, 340), "世袭躺赢", 34, C["GRAY"], .56, .64)
    b.xmark(1600, 395, 26, (.60, .66), color=C["RED"])
    bottom(b, "躺着继承的时代结束,站着拼杀的时代开始", (.84, .94))


def s5(b):
    b.tag((140, 175), "前350 · 第三刀:改操作系统", (.04, .14), fill=C["DARKRED"], size=34)
    slips = [("废井田", "土地私有"), ("行县制", "县令君任命"),
             ("度量衡", "全国统一"), ("迁咸阳", "定鼎关中")]
    spans = _vr().seq_spans(4, .14, .70)
    for i, (t1_, t2_) in enumerate(slips):
        x = 400 + i * 330
        sp = spans[i]
        b.fillr((x, 300, x + 220, 860), C["SLIP"], sp[0], radius=4)
        for ly in (318, 842):
            b.line((x + 16, ly), (x + 204, ly), C["GRAY"], 2, sp[0], sp[1], amp=0.5)
        b.text((x + 34, 380), t1_, 44, C["INK"], sp[0], sp[1])
        b.text((x + 34, 470), t2_, 30, C["GREEN"], sp[0] + .02, sp[1] + .02)
        if i == 3:
            b.fillr((x + 60, 600, x + 160, 700), C["DARKRED"], sp[0] + .04, radius=4)
    b.arrow([(380, 912), (1760, 912)], (.74, .82), color=C["GRAY"], width=4)
    bottom(b, "贵族的联邦,改成了上下贯通的机器", (.84, .94))


def s6(b):
    vr = _vr()
    gx, gy = vr.make_proj(107.6, 32.6, 150, 350, 930)
    vr.draw_map(b, gx, gy, (.03, .40), rivers=True)
    # 黄河中游(晋陕峡谷—潼关折东)与渭水:渲染器内置河网只覆盖下游,战国道一带手补
    yellow_mid = [(110.5, 36.4), (110.35, 35.7), (110.42, 34.98), (110.28, 34.62),
                  (110.9, 34.75), (112.2, 34.9), (113.4, 34.85), (114.3, 34.9)]
    b.poly([(gx(lo), gy(la)) for lo, la in yellow_mid], vr.BLUE_L, 4, .05, .38, amp=1.2)
    b.poly([(gx(108.6), gy(34.52)), (gx(109.5), gy(34.55)), (gx(110.24), gy(34.62))],
           vr.BLUE_L, 3, .20, .38, amp=1.0)
    b.tag((140, 175), "前340 · 商鞅伐魏", (.40, .50), fill=C["DARKRED"], size=34)
    b.text((gx(109.15), gy(35.15)), "河西", 36, C["GREEN"], .44, .52)
    cities = [("咸阳", 108.71, 34.33, True), ("少梁", 110.45, 35.42, False),
              ("大梁", 114.35, 34.78, False)]
    spans = vr.seq_spans(3, .40, .56)
    for (name, lon, lat, big), sp in zip(cities, spans):
        r = 12 if big else 9
        b.fillp([(gx(lon) - r, gy(lat) - r), (gx(lon) + r, gy(lat) - r),
                 (gx(lon) + r, gy(lat) + r), (gx(lon) - r, gy(lat) + r)],
                C["RED"] if big else C["GRAY"], sp[0])
        tx = gx(lon) + 22 if lon < 114 else gx(lon) - 30
        ty = gy(lat) - 56 if lon < 114 else gy(lat) - 60
        b.text((tx, ty), name, 32, C["INK"], sp[0], sp[1])
        if big:
            b.text((gx(lon) + 22, gy(lat) - 18), "秦都", 26, C["DARKRED"], sp[1], sp[1] + .06)
    b.arrow([(gx(108.71) + 24, gy(34.33) - 18), (gx(110.45) - 26, gy(35.42) + 30)],
            (.56, .64), color=C["RED"])
    b.xmark(gx(110.45) + 110, gy(35.42) - 10, 22, (.62, .68), color=C["RED"])
    b.text((gx(110.45) + 96, gy(35.42) - 96), "公子卬被俘", 30, C["DARKRED"], .64, .74)
    b.tag((140, 246), "封十五邑 · 号商君", (.74, .84), fill=C["RED"], size=30)
    bottom(b, "河西归秦——魏国的门户,开了", (.86, .96))


def s7(b):
    b.tag((140, 175), "前338 · 孝公卒,惠文王立", (.04, .14), fill=C["DARKRED"], size=34)
    b.fillr((560, 560, 900, 860), C["SLIP"], .14, radius=4)
    b.fillp([(540, 560), (920, 560), (730, 462)], C["OCHRE"], .16)
    b.fillr((700, 740, 774, 860), C["OCHRE"], .18, radius=2)
    b.text((580, 888), "客栈 · 投宿一夜", 30, C["GRAY"], .20, .28)
    b.figure(1130, 880, 260, (.24, .42), role="ragged", mood="sad")
    b.text((1040, 905), "商鞅", 36, C["INK"], .36, .44)
    b.bubble(740, 400, 400, 112, (.42, .60))
    b.text((568, 370), "商君之法:无凭证者不宿", 28, C["INK"], .46, .62)
    b.text((1060, 620), "宿?不可。", 36, C["DARKRED"], .46, .56)
    cx, cy = (1520, 600)
    b.ellipse(cx, cy, 26, 26, C["INK"], 4, .66, .72)
    dirs = [(0, -170), (118, 130), (-118, 130), (140, -70), (-140, -70)]
    sp = _vr().seq_spans(5, .66, .84)
    for (dx, dy), s_ in zip(dirs, sp):
        b.arrow([(cx + dx * .3, cy + dy * .3), (cx + dx, cy + dy)], s_, color=C["RED"])
    b.text((1450, 780), "车裂", 36, C["DARKRED"], .80, .88)
    bottom(b, "他被自己的法,堵死了所有退路", (.86, .96))


def s8(b):
    base_line(b)
    b.tag((140, 175), "前338 · 商君虽死,其法犹存", (.04, .12), fill=C["DARKRED"], size=34)
    b.text((140, 268), "一套停不下来的机器", 60, C["INK"], .08, .20)
    b.figure(960, 880, 300, (.18, .36), role="soldier", mood="neutral")
    b.bubble(1480, 760, 340, 104, (.56, .72))
    b.text((1352, 732), "你愿意吗?评论区聊", 30, C["INK"], .60, .74)
    bottom(b, "商君虽死,秦法不废——机器已经启动", (.82, .94))


def s9(b):
    base_line(b)
    b.tag((140, 175), "趣闻 · 名字的来历", (.04, .12), fill=C["DARKRED"], size=34)
    b.text((150, 268), "三个名字,讲完一生", 56, C["INK"], .06, .18)
    names = [("卫鞅", 320, (208, 200, 180)), ("公孙鞅", 830, (208, 200, 180)), ("商鞅", 1400, C["RED"])]
    spans = _vr().seq_spans(3, .18, .52)
    for (nm, x, col), sp in zip(names, spans):
        b.fillr((x, 480, x + 300, 640), col, sp[0], radius=10)
        b.text((x + 150 - len(nm) * 34, 528), nm, 56, C["INK"] if col != C["RED"] else (245, 238, 220), sp[0], sp[1])
    b.arrow([(640, 560), (800, 560)], (.44, .50), color=C["GRAY"])
    b.arrow([(1150, 560), (1370, 560)], (.50, .56), color=C["GRAY"])
    b.tag((1290, 690), "封商於十五邑 · 前340", (.56, .68), fill=C["RED"], size=28)
    b.text((320, 780), "生在卫国·公族之后", 32, C["GRAY"], .30, .40)
    bottom(b, "最响亮的名字,是自己挣来的", (.80, .94))


PAINTERS = {"s1": s1, "s2": s2, "s3": s3, "s4": s4,
            "s5": s5, "s6": s6, "s7": s7, "s8": s8, "s9": s9}

# 镜头:窗口高 = 700/zoom。本集各场内容带 y≈170–990,统一 .80(窗口 875,
# y114–989)保证底部结论行与顶部标签都在窗口内;s8 稍收。
CAMS = {k: (lambda p, _z=z: (960, 552, _z)) for k, z in
        {"s1": .80, "s2": .80, "s3": .80, "s4": .80,
         "s5": .80, "s6": .80, "s7": .80, "s8": .82, "s9": .80}.items()}
