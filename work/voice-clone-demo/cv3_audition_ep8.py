# -*- coding: utf-8 -*-
"""CosyVoice3 试音:明朝第八集文稿,CV3 出两版(原文/纠音文本),与 CV2 成品 A/B。

- narr 组: chapters[].narration 原文(含 朱祐樘/斋醮 正确写法,不纠音)——测 CV3 原生发音
- tts  组: chapters[].tts_narration(与 CV2 基线同文本)——公平对比
- 音色与线上完全一致:doubao-京腔侃爷 同 ref.wav/ref.txt,同 seed
- 产物: D:/mzx-ming08/cv3-audition/{smoke,narr,tts}/
不动任何现有管线代码与成品;复用 generate_voice.py(它按 --model-dir 加载 CV3)。
"""
from pathlib import Path
import argparse
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "src/mzx_story/ming-08-hongzhi.json"
VOICE_DIR = ROOT / "work/studio/voices/doubao-京腔侃爷"
OUT = Path("D:/mzx-ming08/cv3-audition")
MODEL = ROOT / "work/voice-clone-demo/models/Fun-CosyVoice3-0.5B-2512"

ENV = "HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1"
PY = "/home/comfy/cosy-gpu-venv/bin/python"
SMOKE_TEXT = "弘治中兴，成色十足。"
# CV3 零样本 prompt_text 新增格式要求(模型 README Basic Usage),CV2 不需要
PROMPT_PREFIX = "You are a helpful assistant.<|endofprompt|>"


def run_wsl(gen_args: str) -> None:
    inner = (f"cd /mnt/e/ai/bilibiliVideoToZH && env {ENV} {PY} "
             f"work/voice-clone-demo/cv3_generate_voice.py {gen_args}")
    r = subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-lc", inner])
    if r.returncode != 0:
        raise SystemExit(f"WSL 调用失败 rc={r.returncode}: {gen_args}")


def write_items(work: Path, texts: list[str]) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "items.json").write_text(json.dumps(
        [{"id": i, "speaker": "A", "text": t} for i, t in enumerate(texts)],
        ensure_ascii=False), encoding="utf-8")
    (work / "refs.json").write_text(json.dumps({"A": {
        "ref_wav": str(VOICE_DIR / "ref.wav"),
        "ref_text_en": PROMPT_PREFIX
        + (VOICE_DIR / "ref.txt").read_text(encoding="utf-8").strip(),
    }}, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--groups", default="narr,tts",
                    help="逗号分隔: smoke,narr,tts 的子集")
    args = ap.parse_args()
    groups = args.groups.split(",")

    content = json.loads(CONTENT.read_text(encoding="utf-8"))
    chapters = content["chapters"]
    texts = {
        "narr": [c["narration"] for c in chapters],
        "tts": [c.get("tts_narration") or c["narration"] for c in chapters],
    }

    for g in groups:
        work = OUT / g
        if g == "smoke":
            write_items(work, [SMOKE_TEXT])
        else:
            write_items(work, texts[g])
        gen_args = (
            f"--items-json {work.as_posix()}/items.json "
            f"--refs-json {work.as_posix()}/refs.json "
            f"--out-dir {work.as_posix()}/parts "
            f"--concat-out {work.as_posix()}/audio.wav "
            f"--model-dir {MODEL.as_posix()}")
        print(f"=== 组 {g}: {len(texts.get(g, [SMOKE_TEXT]))} 段 ===", flush=True)
        run_wsl(gen_args)
        n = len(list((work / "parts").glob("item_*.wav")))
        print(f"[{'ok' if n else 'FAIL'}] {g}: parts={n}", flush=True)


if __name__ == "__main__":
    main()
