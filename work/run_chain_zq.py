# -*- coding: utf-8 -*-
"""东周线 ep01-04 链式产线:补图→成片 串联(脱离会话运行)。"""
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(r"E:\ai\bilibiliVideoToZH")
PY = str(ROOT / "work/.venv-ocr/Scripts/python.exe")
LOG = ROOT / "work/_chain_zq.log"


def log(msg: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%m-%d %H:%M:%S}] {msg}\n")


def run(args: list[str], tag: str) -> int:
    log(f"{tag} 开始")
    r = subprocess.run([PY, "-u", *args], cwd=str(ROOT))
    log(f"{tag} EXIT {r.returncode}")
    return r.returncode


def main() -> int:
    log("CHAIN START (zq 01-04)")
    for slug, job in [
        ("zq-01-shewangjian", "zq_ep01_images.json"),
        ("zq-02-hengwen", "zq_ep02_images.json"),
        ("zq-03-mibing-wuyue", "zq_ep03_images.json"),
        ("zq-04-kongzi", "zq_ep04_images.json"),
    ]:
        run(["work/run_batch_detached.py", f"work/{job}"], f"{slug} 补图")
        run(["src/mzx_story/prod_episode.py",
             "--content", f"src/mzx_story/{slug}.json",
             "--out", f"C:/render-tmp/{slug}",
             "--nas-dir", "东周线"], f"{slug} 成片")
    log("CHAIN DONE (zq 01-04)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
