# -*- coding: utf-8 -*-
"""ep16 崩坏段 A/B:定位质量不稳定的技术根因。

基线 A = 现有 s5_1.mp4(fp8 + cfg5 + VAE tile 256/64/8/8 + 人群大动作提示)。
B = 同图,提示词改"人物静止只动环境",技术参数不变 —— 隔离提示词因素。
C = 同 B 提示词,fp16 全精度 + cfg3.5 + VAE tile 512/128/16/16 —— 测技术升级收益。
"""
import hashlib
import subprocess
import sys
from pathlib import Path

IMG = "work/broll/ming-16-sanzheng2/s5_1.png"
OUT = Path("work/_wan_ab")
OUT.mkdir(exist_ok=True)
SEED = int(hashlib.sha256("s5_1".encode()).hexdigest()[:8], 16)

PROMPT = ("纸片与杂物在风中缓缓飘散,尘土轻轻扬起,摊位布幔与旗帜轻轻摆动,"
          "画面人物保持静止不动,保持原有绘画风格不变")
NEG_EXTRA = ("人物融合,人物变形,肢体扭曲,面部变形,多余肢体,人群走动,人群奔跑,"
             "动作幅度过大")

BASE_NEG = ("色调艳丽，过曝，细节模糊不清，字幕，风格，作品，画作，画面，整体发灰，"
            "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
            "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
            "杂乱的背景，三条腿，背景人很多，倒着走，"
            "镜头推进，镜头拉远，镜头旋转，画面缩放，镜头晃动")
NEG = BASE_NEG + "，" + NEG_EXTRA


def run(tag, extra):
    out = OUT / f"s5_1_{tag}.mp4"
    if out.exists() and out.stat().st_size > 100_000:
        print(f"[skip] {tag}")
        return
    cmd = [sys.executable, "work/wan22_i2v.py",
           "--image", IMG, "--prompt", PROMPT, "--neg", NEG,
           "--length", "121", "--steps", "30", "--seed", str(SEED),
           "--out", str(out), "--timeout", "7200"] + extra
    print(f"[run {tag}]", " ".join(extra) or "(baseline tech)", flush=True)
    r = subprocess.run(cmd)
    print(f"[done {tag}] rc={r.returncode}", flush=True)


run("B", [])
run("C", ["--weight-dtype", "default", "--cfg", "3.5",
          "--vae-tile", "512,128,16,16"])
print("AB-DONE", flush=True)
