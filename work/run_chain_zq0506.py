# -*- coding: utf-8 -*-
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(r"E:\ai\bilibiliVideoToZH")
PY = str(ROOT / "work/.venv-ocr/Scripts/python.exe")
LOG = ROOT / "work/_chain_zq.log"

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        stamp = datetime.now().strftime("%m-%d %H:%M:%S")
        f.write("[" + stamp + "] " + msg + "\n")

def run(args, tag):
    log(tag + " start")
    r = subprocess.run([PY, "-u"] + [str(a) for a in args], cwd=str(ROOT))
    log(tag + " EXIT " + str(r.returncode))
    return r.returncode

def main():
    log("CHAIN START zq05-06")
    for slug, job in [("zq-05-sanfen", "zq_ep05_images.json"),
                      ("zq-06-weiguo", "zq_ep06_images.json")]:
        run(["work/run_batch_detached.py", "work/" + job], slug + " batch")
        run(["src/mzx_story/prod_episode.py",
             "--content", "src/mzx_story/" + slug + ".json",
             "--out", "C:/render-tmp/" + slug,
             "--nas-dir", "dongzhou"], slug + " prod")
    log("CHAIN DONE zq05-06")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
