# -*- coding: utf-8 -*-
"""《AI 快讯》杂志版封面生成(B 方向,安全区版)。

B 站手机端信息流卡片约 4:3,16:9 封面按高度撑满后左右各裁 ~12%。
本脚本把全部关键内容压进中央安全区 x∈[SAFE_X0, SAFE_X1],星空/辉光可出血。

用法:改底部 CONFIG 后运行
  work/.venv-ocr/Scripts/python.exe kinetic_demo/make_cover_magazine.py
"""
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
LANCZOS = Image.Resampling.LANCZOS

W, H = 1920, 1080
# 信息流 4:3 中心裁切可见区:x 240~1680;再留 20px 呼吸
SAFE_X0, SAFE_X1 = 260, 1660
AMBER = (251, 191, 36)
ORANGE = (234, 88, 12)
TEAL = (52, 211, 153)
WHITE = (245, 248, 252)

FB = "C:/Windows/Fonts/msyhbd.ttc"
FR = "C:/Windows/Fonts/msyh.ttc"


def f(path, size):
    return ImageFont.truetype(path, size)


def make_cover(out_path, badge_line, title_lines, pill_text, bullets, thumbs, seed=8):
    """thumbs: [(path, crop 或 None), ...] 最多 3 张,竖排右侧。"""
    im = Image.new("RGBA", (W, H), (13, 27, 42, 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-200, -300, 1100, 700], fill=(234, 88, 12, 60))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    im = Image.alpha_composite(im, glow)
    d = ImageDraw.Draw(im)
    random.seed(seed)
    for _ in range(110):
        x, y = random.randint(0, W - 1), random.randint(0, H - 1)
        r = random.choice([1, 1, 1, 2])
        d.ellipse([x, y, x + r, y + r], fill=(200, 215, 235, random.randint(70, 160)))

    # ---- 右侧缩略卡列:收进安全区 ----
    tw = 470
    tx1 = SAFE_X1
    tx0 = tx1 - tw
    ty = 96
    step = (H - 2 * 96) / max(len(thumbs), 1)
    th = int(step - 26)
    for path, crop in thumbs:
        pic = Image.open(path).convert("RGBA")
        if crop:
            pic = pic.crop(crop)
        r = min(tw / pic.width, th / pic.height)
        pic = pic.resize((int(pic.width * r), int(pic.height * r)), LANCZOS)
        card = Image.new("RGBA", (tw + 16, th + 16), (0, 0, 0, 0))
        mask = Image.new("L", pic.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, pic.width, pic.height], radius=14, fill=255)
        card.paste(pic, (8, 8), mask)
        im.alpha_composite(card, (tx0 - 8, int(ty)))
        ty += step

    d = ImageDraw.Draw(im)
    # ---- 左侧文字:全部起笔于 SAFE_X0 ----
    bx = SAFE_X0
    d.rectangle([bx, 120, bx + 12, 216], fill=ORANGE)
    bf = f(FB, 46)
    d.text((bx + 34, 122), badge_line[0], font=bf, fill=WHITE)
    bw = d.textlength(badge_line[0], font=bf)
    d.text((bx + 34 + bw + 22, 130), badge_line[1], font=f(FB, 40), fill=AMBER)

    ty0 = 322
    tsize = 132
    while any(d.textlength(t, font=f(FB, tsize)) > (SAFE_X1 - SAFE_X0) * 0.62 for t in title_lines) and tsize > 88:
        tsize -= 6
    for i, line in enumerate(title_lines):
        d.text((bx - 6, ty0 + i * (tsize + 22)), line, font=f(FB, tsize),
               fill=WHITE if i == 0 else AMBER,
               stroke_width=5, stroke_fill=(12, 16, 28) if i == 0 else (32, 22, 4))
    ty_pill = ty0 + len(title_lines) * (tsize + 22) + 18
    pill_f = f(FB, 34)
    pw = d.textlength(pill_text, font=pill_f) + 72
    d.rounded_rectangle([bx - 4, ty_pill, bx - 4 + pw, ty_pill + 62], radius=31,
                        outline=(150, 165, 185), width=3)
    d.text((bx + 32, ty_pill + 12), pill_text, font=pill_f, fill=(210, 220, 232))

    yb = ty_pill + 106
    for b in bullets:
        d.ellipse([bx - 2, yb + 11, bx + 14, yb + 27], fill=TEAL)
        d.text((bx + 36, yb), b, font=f(FR, 33), fill=(222, 230, 240))
        yb += 56

    tag = "AI 快讯 · 每天 8 点 · 只讲昨天的事"
    tw2 = d.textlength(tag, font=f(FR, 28))
    d.text((SAFE_X1 + 20 - tw2, 1018), tag, font=f(FR, 28), fill=(235, 240, 246),
           stroke_width=2, stroke_fill=(10, 12, 20))
    im.convert("RGB").save(out_path, quality=92)
    print("saved", out_path)


def feed_preview(src_path, out_path):
    """模拟 B 站信息流 4:3 中心裁切,自检安全区。"""
    im = Image.open(src_path)
    cw = int(H * 4 / 3)
    x0 = (W - cw) // 2
    im.crop((x0, 0, x0 + cw, H)).save(out_path, quality=90)
    print("preview", out_path)


if __name__ == "__main__":
    B = "E:/ai/bilibiliVideoToZH/kinetic_demo/broll/ai-news-1101/"
    make_cover(
        B + "cover.jpg",
        badge_line=("AI 快讯", "11月1日早报"),
        title_lines=["Anthropic 债券", "或获垃圾级评级"],
        pill_text="10.31 新闻 · 五条要闻",
        bullets=["法国通过 0.055 欧/GB 下载税", "恶意软件用 LLM 给受害者排富"],
        thumbs=[
            (B + "card-junk.png", None),
            (B + "card-france.png", None),
            (B + "card-selloff.png", None),
        ],
        seed=222,
    )
    feed_preview(B + "cover.jpg", B + "cover_feed_preview.jpg")
