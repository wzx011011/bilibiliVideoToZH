# -*- coding: utf-8 -*-
"""zq-01~08 八集重渲链:渲染→对齐→终渲→QC(签条图替换后)。"""
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(r"E:\ai\bilibiliVideoToZH")
PY = str(ROOT / "work/.venv-ocr/Scripts/python.exe")
LOG = ROOT / "work/_chain_zq.log"
EPISODES = [
    ("zq-01-shewangjian", "东周线"),
    ("zq-02-hengwen", "东周线"),
    ("zq-03-mibing-wuyue", "东周线"),
    ("zq-04-kongzi", "东周线"),
    ("zq-05-sanfen", "东周线"),
    ("zq-06-weiguo", "东周线"),
    ("zq-07-baijia", "东周线"),
    ("zq-08-jixia", "东周线"),
]


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
    log("RERENDER START (cast tags)")
    for slug, nas in EPISODES:
        out = "C:/render-tmp/" + slug
        run(["src/mzx_story/vector_render.py", "--render",
             "--content", "src/mzx_story/" + slug + ".json",
             "--out", out], slug + " render")
        run(["src/mzx_story/align_beats.py",
             "--content", "src/mzx_story/" + slug + ".json",
             "--timeline", out + "/timeline.json",
             "--srt", out + "/subtitles.srt"], slug + " align")
        run(["src/mzx_story/vector_render.py", "--render",
             "--content", "src/mzx_story/" + slug + ".json",
             "--out", out], slug + " render-final")
        qc = Path(out) / "qc_report.json"
        if qc.exists():
            r = json.load(open(qc, encoding="utf-8"))
            log(slug + " QC " + str(r.get("status")) + " " + str(r.get("overall_hard_cer")))
    log("RERENDER DONE")


import json  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
