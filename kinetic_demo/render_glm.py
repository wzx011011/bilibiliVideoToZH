# -*- coding: utf-8 -*-
"""GLM-5.3-Flash 讲解视频:数据注入 → Playwright 逐帧 → ffmpeg 合成。

音频由 build 前的 assemble 步骤生成(glm_audio.wav,与 glm_data.json
时间轴同源:LEAD_IN=0.5 起始 + 段间 0.55s),此处只负责画面+混流。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FFMPEG = HERE.parents[0] / "work/video-tools/ffmpeg.exe"
FPS = 30


def main(smoke: bool = False):
    data = json.loads((HERE / "glm_data.json").read_text(encoding="utf-8"))
    n = 6 if smoke else int(data["duration"] * FPS) + 1
    html = (HERE / "glm_stage.html").read_text(encoding="utf-8").replace(
        "__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    built = HERE / "issues" / "_glm_built.html"
    built.write_text(html, encoding="utf-8")

    frames = HERE / "_glm_frames"
    frames.mkdir(exist_ok=True)

    with sync_playwright() as p:
        b = p.chromium.launch(args=[
            "--enable-unsafe-swiftshader", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--disable-lcd-text"])
        pg = b.new_page(viewport={"width": 1920, "height": 1080},
                        device_scale_factor=1)
        pg.on("pageerror", lambda e: print("[pageerror]", str(e)[:300]))
        pg.goto(built.resolve().as_uri())
        pg.wait_for_function("window.__READY__ === true", timeout=15000)
        if smoke:
            # 冒烟:每个场景抽一帧
            ts = [seg["start"] + (seg["end"] - seg["start"]) * 0.75
                  for seg in data["segments"]]
        else:
            ts = [i / FPS for i in range(n)]
        for i, t in enumerate(ts):
            pg.evaluate("t => renderFrame(t)", t)
            pg.screenshot(path=str(frames / f"f_{i:05d}.jpg"),
                          type="jpeg", quality=92)
            if not smoke and i % 300 == 0:
                print(f"  frame {i}/{n}")
        b.close()

    if smoke:
        print(f"[ok] smoke {len(ts)} frames -> {frames}")
        return

    out = HERE / "glm_flash_video.mp4"
    subprocess.run([
        str(FFMPEG), "-y", "-v", "error",
        "-framerate", str(FPS), "-i", str(frames / "f_%05d.jpg"),
        "-i", str(HERE / "glm_video/glm_audio.wav"),
        "-c:v", "libx264", "-crf", "19", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(out)], check=True)
    print(f"[ok] {out} ({out.stat().st_size // 1048576}MB)")


if __name__ == "__main__":
    main(smoke="--smoke" in sys.argv)
