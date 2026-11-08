import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(r"E:\ai\bilibiliVideoToZH")
PY = str(ROOT / "work/.venv-ocr/Scripts/python.exe")
LOG = ROOT / "work/_chain_zq.log"
SLUGS = ["zq-11-jiangxiang", "zq-12-quyuan", "zq-13-handan", "zq-14-fajia"]

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
    log("CHAIN START zq11-14")
    for slug in SLUGS:
        num = slug.split("-")[1]
        run(["work/run_batch_detached.py", "work/zq_ep" + num + "_images_r1.json"], slug + " batch")
        run(["src/mzx_story/prod_episode.py",
             "--content", "src/mzx_story/" + slug + ".json",
             "--out", "C:/render-tmp/" + slug], slug + " prod")
    log("CHAIN DONE zq11-14")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
