# -*- coding: utf-8 -*-
"""S2→S3→S4 链式产线(Python 版,避开 cmd 代码页问题)。

每步:补齐缺图 → prod_episode(配音/渲染/对齐/QC/NAS)。全程日志 work/_chain.log。
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"E:\ai\bilibiliVideoToZH")
PY = str(ROOT / "work/.venv-ocr/Scripts/python.exe")
LOG = ROOT / "work/_chain.log"


def log(msg: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%m-%d %H:%M:%S}] {msg}\n")


def run(args: list[str], tag: str) -> int:
    log(f"{tag} 开始")
    r = subprocess.run([PY, "-u", *args], cwd=str(ROOT))
    log(f"{tag} EXIT {r.returncode}")
    return r.returncode


def main() -> int:
    log("CHAIN START (py)")
    eps = [
        ("sy-02-erlitou", "sy_ep02_images.json"),
        ("sy-03-jiaguwen", "sy_ep03_images.json"),
        ("sy-04-xizhou", "sy_ep04_images.json"),
    ]
    for slug, job in eps:
        run(["work/run_batch_detached.py", f"work/{job}"], f"{slug} 补图")
        rc = run(["src/mzx_story/prod_episode.py",
                  "--content", f"src/mzx_story/{slug}.json",
                  "--out", f"C:/render-tmp/{slug}",
                  "--nas-dir", "溯源篇"], f"{slug} 成片")
        if rc != 0:
            log(f"{slug} 成片失败,继续下一集")
    log("CHAIN DONE (py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
