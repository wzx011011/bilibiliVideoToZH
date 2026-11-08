# -*- coding: utf-8 -*-
"""确定性网页动画 → MP4:Playwright 逐帧调用 renderFrame(t) 截图,JPEG 直接管道喂 ffmpeg。

页面约定(同 kinetic_demo 舞台):暴露 window.renderFrame(t) 与 window.__READY__,
可选 window.__DURATION__;以 ?render=1 打开时页面不自行播放。帧不落盘。

用法:
  python tools/render_html_video.py mech_demo.html work/mech_demo/mech_demo.mp4
  python tools/render_html_video.py mech_demo.html out.mp4 --audio narr.wav --duration 26
  python tools/render_html_video.py mech_demo.html stills/ --stills 3 8 20   # 抽帧检查
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "work/video-tools/ffmpeg.exe"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("html")
    ap.add_argument("out")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--duration", type=float, default=None, help="默认读 window.__DURATION__")
    ap.add_argument("--audio", default=None)
    ap.add_argument("--stills", type=float, nargs="+", default=None, help="只截这些时刻的 PNG")
    args = ap.parse_args()

    url = Path(args.html).resolve().as_uri() + "?render=1"
    out = Path(args.out)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--hide-scrollbars", "--force-device-scale-factor=1",
                                    "--disable-lcd-text"])
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(url)
        # 页面可能在加载时预计算底图(v3 地貌高度场数秒),给足就绪时间
        pg.wait_for_function("window.__READY__ === true", timeout=120000)
        if errors:
            raise SystemExit(f"[pageerror] {errors[0][:300]}")

        if args.stills:
            out.mkdir(parents=True, exist_ok=True)
            for t in args.stills:
                pg.evaluate("t => renderFrame(t)", t)
                pg.screenshot(path=str(out / f"t{t:05.1f}.png"))
            print(f"[ok] {len(args.stills)} stills -> {out}")
            b.close()
            return

        dur = args.duration or pg.evaluate("window.__DURATION__")
        if not dur:
            raise SystemExit("缺少时长:页面未定义 __DURATION__,请传 --duration")
        n = int(round(dur * args.fps))
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [str(FFMPEG), "-y", "-v", "error",
               "-f", "image2pipe", "-c:v", "mjpeg", "-framerate", str(args.fps), "-i", "-"]
        if args.audio:
            cmd += ["-i", args.audio, "-c:a", "aac", "-b:a", "192k", "-shortest"]
        cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "medium",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        assert ff.stdin is not None
        try:
            for i in range(n):
                pg.evaluate("t => renderFrame(t)", i / args.fps)
                ff.stdin.write(pg.screenshot(type="jpeg", quality=95))
                if i % 150 == 0:
                    print(f"  frame {i}/{n}", flush=True)
        finally:
            ff.stdin.close()
            b.close()
        if ff.wait() != 0 or errors:
            raise SystemExit(f"[fail] ffmpeg={ff.returncode} pageerror={errors[:1]}")
    print(f"[ok] {out} ({n} frames, {out.stat().st_size / 1048576:.1f}MB)")


if __name__ == "__main__":
    main()
