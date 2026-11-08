# -*- coding: utf-8 -*-
"""云海天阙:静帧 → 伪深度视差/云雾/光尘动画 → 1920x1080 30s MP4。

音频:空灵垫(失谐正弦簇 + 慢包络)+ 风声(滤波噪声)+ 远钟。
"""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FFMPEG = HERE.parents[0] / "work/video-tools/ffmpeg.exe"
FPS, DUR = 30, 30
W, H = 1920, 1080


def prep_still() -> str:
    """上采样静帧到目标尺寸(Lanczos),返回 data URL。"""
    src = HERE / "epic_still.jpg"
    with Image.open(src) as im:
        img = im.convert("RGB").resize((W, H), Image.LANCZOS)
    out = HERE / "_epic_up.jpg"
    img.save(out, quality=94)
    return "data:image/jpeg;base64," + base64.b64encode(out.read_bytes()).decode()


def build_audio() -> Path:
    out = HERE / "epic_audio.wav"
    # 空灵垫:A2/E3/A3 微失谐簇,慢 LFO;远钟:每 8s 一次的衰减正弦;风:棕噪带通
    pad = (
        "0.05*sin(2*PI*110*t)*(0.6+0.4*sin(2*PI*0.045*t))"
        "+0.05*sin(2*PI*110.6*t)*(0.6+0.4*sin(2*PI*0.05*t+1.0))"
        "+0.042*sin(2*PI*164.81*t)*(0.6+0.4*sin(2*PI*0.04*t+2.0))"
        "+0.035*sin(2*PI*220.4*t)"
        "+0.028*sin(2*PI*329.63*t)*(0.5+0.5*sin(2*PI*0.035*t+4.0))"
    )
    bell = "0.22*sin(2*PI*660*t)*exp(-3.2*t)" \
           "+0.11*sin(2*PI*1320*t)*exp(-4.5*t)"
    subprocess.run([
        str(FFMPEG), "-y", "-v", "error",
        "-f", "lavfi", "-i", f"aevalsrc={pad}:s=48000:d=30",
        "-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.35:duration=30:sample_rate=48000",
        "-f", "lavfi", "-i", f"aevalsrc={bell}:s=48000:d=30",
        "-filter_complex",
        "[0]aecho=0.7:0.45:600:0.4,aecho=0.5:0.3:1200:0.3[a0];"
        "[1]bandpass=f=600:width_type=h:w=900,volume=0.35[wind];"
        "[2]adelay=8000|8000,volume=0.5[bell];"
        "[a0][wind][bell]amix=inputs=3:normalize=0,"
        "afade=t=in:d=4,afade=t=out:st=24:d=6,alimiter=limit=0.85",
        "-c:a", "pcm_s16le", str(out),
    ], check=True)
    return out


def main(smoke: bool = False):
    still = prep_still()
    audio = build_audio()
    frames = HERE / "_epic_frames"
    frames.mkdir(exist_ok=True)
    n = 3 if smoke else DUR * FPS

    with sync_playwright() as p:
        b = p.chromium.launch(args=[
            "--enable-unsafe-swiftshader", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--disable-lcd-text",
        ])
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        pg.on("pageerror", lambda e: print("[pageerror]", str(e)[:300]))
        pg.goto((HERE / "epic_stage.html").resolve().as_uri())
        pg.wait_for_function("window.__READY__ === true", timeout=15000)
        pg.evaluate("b => setStill(b)", still)
        pg.wait_for_function("window.__TEX__ === true", timeout=15000)
        ts = [2.5, 15.0, 29.0] if smoke else [i / FPS for i in range(n)]
        for i, t in enumerate(ts):
            pg.evaluate("t => renderFrame(t)", t)
            pg.screenshot(path=str(frames / f"f_{i:05d}.jpg"),
                          type="jpeg", quality=93)
        b.close()

    if smoke:
        print(f"[ok] smoke frames in {frames}")
        return
    out = HERE / "epic_demo.mp4"
    subprocess.run([
        str(FFMPEG), "-y", "-v", "error",
        "-framerate", str(FPS), "-i", str(frames / "f_%05d.jpg"),
        "-i", str(audio),
        "-c:v", "libx264", "-crf", "19", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-shortest", str(out),
    ], check=True)
    print(f"[ok] {out} ({out.stat().st_size // 1048576}MB, {n} frames)")


if __name__ == "__main__":
    import sys
    main(smoke="--smoke" in sys.argv)
