# -*- coding: utf-8 -*-
"""Playwright 逐帧渲染 stage.html → JPEG 序列 → ffmpeg 合成 MP4(含音频)。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
FFMPEG = ROOT / "work/video-tools/ffmpeg.exe"
FPS = 30

def main():
    data = json.loads((HERE / "demo_data.json").read_text(encoding="utf-8"))
    n = data["n_frames"]
    html = (HERE / "stage.html").read_text(encoding="utf-8").replace(
        "__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    built = HERE / "issues" / "_stage_built.html"
    built.write_text(html, encoding="utf-8")

    frames = HERE / "_frames"
    frames.mkdir(exist_ok=True)

    with sync_playwright() as p:
        b = p.chromium.launch(args=[
            "--enable-unsafe-swiftshader", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--disable-lcd-text",
        ])
        pg = b.new_page(viewport={"width": 1080, "height": 1920},
                        device_scale_factor=1)
        pg.on("console", lambda m: m.type in ("error", "warning")
              and print("[console]", m.type, m.text[:200]))
        pg.goto(built.as_uri())
        pg.wait_for_function("window.__READY__ === true", timeout=15000)
        for i in range(n):
            pg.evaluate("t => renderFrame(t)", i / FPS)
            pg.screenshot(path=str(frames / f"f_{i:05d}.jpg"),
                          type="jpeg", quality=92)
            if i % 150 == 0:
                print(f"  frame {i}/{n}")
        b.close()

    out = HERE / "kinetic_demo.mp4"
    subprocess.run([
        str(FFMPEG), "-y", "-v", "error",
        "-framerate", str(FPS), "-i", str(frames / "f_%05d.jpg"),
        "-i", str(HERE / "demo_audio.wav"),
        "-c:v", "libx264", "-crf", "19", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(out),
    ], check=True)
    print(f"[ok] {out} ({out.stat().st_size // 1048576}MB, {n} frames)")


if __name__ == "__main__":
    sys.exit(main())
