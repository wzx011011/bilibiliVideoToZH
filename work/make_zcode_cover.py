# -*- coding: utf-8 -*-
"""zcode-audit 封面:成片结论场景抽帧 + 本地 PIL 合成标题字(标题不靠模型生成)。"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "work/video-tools/ffmpeg.exe"
VIDEO = ROOT / "kinetic_demo/zcode-audit_video.mp4"
RAW = ROOT / "kinetic_demo/zcode-audit_cover_raw.png"
OUT = ROOT / "videos/cover-zcode-audit.jpg"

TITLE_L1 = "AI 编程工具"
TITLE_L2 = "会偷传你的代码吗？"
BRAND = "AI 工具深挖 · 取证实录"


def main() -> None:
    # 片尾 tail 段(建议场景完整展开、无字幕条)做底,整体压暗 + 居中大标题
    subprocess.run([str(FFMPEG), "-y", "-v", "error", "-ss", "144.5",
                    "-i", str(VIDEO), "-frames:v", "1", str(RAW)], check=True)
    from PIL import Image, ImageDraw, ImageFont
    img = Image.open(RAW).convert("RGB")

    overlay = Image.new("RGBA", img.size, (5, 8, 14, 170))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(img)

    f_big = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 132)
    f_brand = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 38)

    def center(text, y, fill, font=f_big):
        w = d.textlength(text, font=font)
        d.text(((1920 - w) / 2 + 5, y + 5), text, font=font, fill=(0, 0, 0))
        d.text(((1920 - w) / 2, y), text, font=font, fill=fill)

    center(TITLE_L1, 300, (240, 246, 252))
    center(TITLE_L2, 465, (245, 158, 11))
    center(BRAND, 905, (150, 205, 170), f_brand)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, quality=92)
    print(f"cover -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
