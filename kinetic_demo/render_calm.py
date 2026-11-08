# -*- coding: utf-8 -*-
"""深夜电台氛围片头:合成音频 → Playwright 逐帧渲染 calm_stage.html → MP4。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FFMPEG = HERE.parents[0] / "work/video-tools/ffmpeg.exe"
FPS, DUR = 30, 30


def build_audio() -> Path:
    """ffmpeg 合成:粉噪雨声 + 棕噪低频垫 + A 大调微弱和弦垫(带回声/慢LFO)。"""
    out = HERE / "calm_audio.wav"
    pad = (
        "0.045*sin(2*PI*110*t)*(0.7+0.3*sin(2*PI*0.06*t))"
        "+0.036*sin(2*PI*164.81*t)*(0.7+0.3*sin(2*PI*0.05*t+1.0))"
        "+0.027*sin(2*PI*220.3*t)"
        "+0.020*sin(2*PI*277.18*t)*(0.6+0.4*sin(2*PI*0.045*t+2.0))"
    )
    subprocess.run([
        str(FFMPEG), "-y", "-v", "error",
        "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.30:duration=30:sample_rate=48000",
        "-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.45:duration=30:sample_rate=48000",
        "-f", "lavfi", "-i", f"aevalsrc={pad}:s=48000:d=30",
        "-filter_complex",
        "[0]highpass=f=500,lowpass=f=7000,volume=0.85[a0];"
        "[1]lowpass=f=380,volume=0.45[a1];"
        "[2]aecho=0.7:0.4:480:0.35,aecho=0.5:0.3:900:0.25,volume=0.8[a2];"
        "[a0][a1][a2]amix=inputs=3:normalize=0,"
        "afade=t=in:d=3,afade=t=out:st=25:d=5",
        "-c:a", "pcm_s16le", str(out),
    ], check=True)
    return out


def main(smoke: bool = False):
    n = 3 if smoke else DUR * FPS
    audio = build_audio()
    frames = HERE / "_calm_frames"
    frames.mkdir(exist_ok=True)

    with sync_playwright() as p:
        b = p.chromium.launch(args=[
            "--enable-unsafe-swiftshader", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--disable-lcd-text",
        ])
        pg = b.new_page(viewport={"width": 1080, "height": 1920},
                        device_scale_factor=1)
        pg.on("pageerror", lambda e: print("[pageerror]", str(e)[:300]))
        pg.goto((HERE / "calm_stage.html").resolve().as_uri())
        pg.wait_for_function("window.__READY__ === true", timeout=15000)
        ts = [3.0, 15.0, 29.0] if smoke else [i / FPS for i in range(n)]
        for i, t in enumerate(ts):
            pg.evaluate("t => renderFrame(t)", t)
            pg.screenshot(path=str(frames / f"f_{i:05d}.jpg"),
                          type="jpeg", quality=92)
        b.close()

    if smoke:
        print(f"[ok] smoke frames in {frames}")
        return
    out = HERE / "calm_demo.mp4"
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
