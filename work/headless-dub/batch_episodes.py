"""批量生成第3-23集（沿用 RapidOCR + GPT-SoVITS speed=0.92 + 跳过复核）。

逐集串行跑（GPT-SoVITS 单实例不能并行）。每集独立工作目录 + 交付包。
单集失败记录后继续下一集，不中断整体。跑完输出汇总报告。

用法: python batch_episodes.py
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path("D:/work/wzx/outputs/harvard-positive-psychology")
SRC_DIR = BASE / "原版视频"
PIPELINE_DIR = Path("D:/work/wzx/work/headless-dub")
PYTHON = sys.executable

# 已完成的集（跳过）
DONE = {1, 2}
# 要跑的集范围
EPISODES = list(range(3, 24))  # 3..23

LOG = BASE / "batch-run.log"


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def find_source(ep: int) -> Path | None:
    """按 p{ep:02d} 匹配源视频文件。"""
    for f in sorted(os.listdir(SRC_DIR)):
        if re.search(rf"p{ep:02d}\b", f):
            return SRC_DIR / f
    return None


def delivery_exists(ep: int) -> bool:
    return (BASE / f"episode-{ep:02d}-delivery" / "video").is_dir()


def run_episode(ep: int) -> bool:
    """跑单集，返回是否成功。"""
    src = find_source(ep)
    if src is None:
        log(f"  ✗ 找不到第{ep}集源视频")
        return False

    work = BASE / f"episode-{ep:02d}-work"
    delivery = BASE / f"episode-{ep:02d}-delivery"

    cmd = [
        PYTHON, "-u", "dub_pipeline.py",
        "--input", str(src),
        "--full",
        "--output", str(work),
        "--subtitle-source", "ocr",
        "--ocr-model", "rapidocr",
        "--artifact-stem", f"episode-{ep:02d}",
        "--stage", "all",
        "--skip-review",
        "--delivery-dir", str(delivery),
        "--tts-speed", "0.92",
    ]
    log(f"  启动: {' '.join(cmd[:6])}...")
    t0 = time.time()
    result = subprocess.run(
        cmd, cwd=str(PIPELINE_DIR),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    dt = time.time() - t0

    # 写单集日志
    (work).mkdir(parents=True, exist_ok=True)
    (work / "build.stdout.log").write_text(result.stdout, encoding="utf-8")
    (work / "build.stderr.log").write_text(result.stderr, encoding="utf-8")

    if result.returncode != 0:
        log(f"  ✗ 失败 (exit={result.returncode}, {dt/60:.0f}分钟)")
        log(f"    stderr尾部: {result.stderr[-500:]}")
        return False

    ok = delivery_exists(ep)
    if ok:
        log(f"  ✓ 完成 ({dt/60:.0f}分钟) → {delivery.name}")
    else:
        log(f"  ✗ 退出码0但交付包未生成 ({dt/60:.0f}分钟)")
    return ok


def main() -> None:
    log("=" * 60)
    log(f"批量生成开始：第{EPISODES[0]}-{EPISODES[-1]}集（共{len(EPISODES)}集）")
    log(f"方案：RapidOCR + GPT-SoVITS(speed=0.92) + 跳过复核")
    log(f"预计单集约2小时，总计约{len(EPISODES)*2}小时")
    log("=" * 60)

    results: dict[int, bool] = {}
    for i, ep in enumerate(EPISODES, 1):
        log(f"\n[{i}/{len(EPISODES)}] 第{ep}集")
        if delivery_exists(ep):
            log(f"  ⊙ 交付包已存在，跳过")
            results[ep] = True
            continue
        results[ep] = run_episode(ep)

    # 汇总
    log("\n" + "=" * 60)
    ok = [e for e, s in results.items() if s]
    fail = [e for e, s in results.items() if not s]
    log(f"完成汇总：成功 {len(ok)} 集，失败 {len(fail)} 集")
    if fail:
        log(f"失败集：{fail}")
    log(f"交付包目录：{BASE}")
    for e in ok:
        log(f"  ✓ episode-{e:02d}-delivery")
    log("=" * 60)


if __name__ == "__main__":
    main()
