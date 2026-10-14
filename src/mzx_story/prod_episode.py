# -*- coding: utf-8 -*-
"""单集全自动产线:图已就绪的前提下,一条命令跑完 配音→渲染→句级对齐→终渲→QC→NAS。

前置:work/broll/<slug>/ 下的图已由 qwen_cast_gen 生成(bg+各拍)。
用法:
  python src/mzx_story/prod_episode.py --content src/mzx_story/sy-02-erlitou.json \
      --out C:/render-tmp/sy-02 --nas-dir 溯源篇
步骤内含 wsl --shutdown(为 CV3 腾显存)与结尾的 WSL 关闭(磁盘/显存卫生)。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--content", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--nas-dir", default=None, help="NAS 临时-试听 下的系列目录名")
    a = ap.parse_args()
    content = Path(a.content)
    out = Path(a.out)

    subprocess.run(["wsl", "--shutdown"], cwd=ROOT)
    import time
    time.sleep(4)

    # 1) 配音(WSL CV3)
    run([PY, "src/mzx_story/prepare.py", "--content", str(content), "--out", str(out)])

    # 2) 渲染 v1(产出 timeline/srt 供对齐)
    run([PY, "src/mzx_story/vector_render.py", "--render",
         "--content", str(content), "--out", str(out)])

    # 3) 句级对齐 + 终渲
    run([PY, "src/mzx_story/align_beats.py", "--content", str(content),
         "--timeline", str(out / "timeline.json"), "--srt", str(out / "subtitles.srt")])
    run([PY, "src/mzx_story/vector_render.py", "--render",
         "--content", str(content), "--out", str(out)])

    # 4) QC(逐章转写)
    qc = out / "qc_report.json"
    qc_cmd = [PY, "src/av_qc.py", "--content", str(content),
              "--audio", str(out / "audio.wav"), "--timeline", str(out / "timeline.json"),
              "--srt", str(out / "subtitles.srt"), "--parts-dir", str(out / "parts"),
              "--out", str(qc)]
    print("+", " ".join(qc_cmd), flush=True)
    r = subprocess.run(qc_cmd, cwd=ROOT)
    if r.returncode != 0:
        print("[prod] QC FAIL,终止(不入 NAS)", file=sys.stderr)
        return 1

    # 5) NAS 归档
    if a.nas_dir:
        video = out / (json_video_name(content))
        base = "/volume1/share/视频汉化项目/临时-试听/" + a.nas_dir
        subprocess.run(["ssh", "nas", f"mkdir -p '{base}'"], cwd=ROOT)
        run(["scp", "-q", str(video), f"nas:{base}/"])
        run(["ssh", "nas", f"md5sum '{base}/{video.name}'"])
        run(["md5sum", str(video)])

    subprocess.run(["wsl", "--shutdown"], cwd=ROOT)
    print("[prod] 完成:", content.stem)
    return 0


def json_video_name(content: Path) -> str:
    import json
    return json.loads(content.read_text(encoding="utf-8")).get(
        "video_name", content.stem + ".mp4")


if __name__ == "__main__":
    raise SystemExit(main())
