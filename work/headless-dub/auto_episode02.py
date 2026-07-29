"""第2集自动化衔接：等 RapidOCR 跑完后，自动调用 dub_pipeline 出完整交付包。

逻辑：
  1. 轮询 events.json，等所有事件都填上 text（OCR 完成）
  2. 调 dub_pipeline.py --stage all --skip-review，复用现有 OCR 结果，
     走合成→混音→封装→交付包
"""
import json
import subprocess
import sys
import time
from pathlib import Path

WORK = Path("D:/work/wzx/outputs/harvard-positive-psychology/episode-02-work")
EVENTS = WORK / "episode-02.source.events.json"
INPUT_VIDEO = "D:/work/wzx/outputs/harvard-positive-psychology/原版视频/02 - 【哈佛大学】积极心理学 Talben Shahar（全23讲） p02 第2讲 为什么要学习积极心理学.mp4"
DELIVERY = "D:/work/wzx/outputs/harvard-positive-psychology/episode-02-delivery"
POLL_INTERVAL = 60  # 秒


def ocr_progress():
    """返回 (已识别数, 总数)。"""
    d = json.loads(EVENTS.read_text(encoding="utf-8"))
    ev = d["events"]
    total = len(ev)
    done = sum(1 for e in ev if (e.get("text") or "").strip())
    return done, total


def wait_for_ocr():
    print("[wait] 等 RapidOCR 跑完...", flush=True)
    last = -1
    while True:
        done, total = ocr_progress()
        if done != last:
            pct = 100 * done // total if total else 0
            print(f"[wait] OCR {done}/{total} ({pct}%)", flush=True)
            last = done
        if done >= total:
            print(f"[wait] OCR 全部完成 ({done}/{total})", flush=True)
            return
        time.sleep(POLL_INTERVAL)


def run_pipeline():
    cmd = [
        sys.executable, "dub_pipeline.py",
        "--input", INPUT_VIDEO,
        "--full",
        "--output", str(WORK),
        "--subtitle-source", "ocr",
        "--ocr-model", "rapidocr",
        "--artifact-stem", "episode-02",
        "--stage", "all",
        "--skip-review",
        "--delivery-dir", DELIVERY,
        "--tts-speed", "0.92",
    ]
    print("[pipe] 启动 dub_pipeline: " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd="D:/work/wzx/work/headless-dub")
    if result.returncode != 0:
        print(f"[pipe] ✗ dub_pipeline 失败 exit={result.returncode}", flush=True)
        sys.exit(1)
    print(f"[pipe] ✓ 交付包已生成: {DELIVERY}", flush=True)


if __name__ == "__main__":
    wait_for_ocr()
    run_pipeline()
