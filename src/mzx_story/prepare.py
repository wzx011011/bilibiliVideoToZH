# -*- coding: utf-8 -*-
"""明朝故事线配音准备:content JSON → items/refs → CosyVoice3(WSL GPU)。

与 gpt_explainer 同链路;音色读内容 JSON 的 voice 字段(默认东方浩然)。
2026-09-12 起引擎固定 CV3(Fun-CosyVoice3-0.5B-2512,经 cv3_generate_voice.py
绕开 AutoModel 的 load_jit 不兼容);CV3 的 prompt_text 必须带 endofprompt 前缀。
支持多集参数化:
  python src/mzx_story/prepare.py                        # 第01集(默认)
  python src/mzx_story/prepare.py --content src/mzx_story/ming-02-yongle.json --out D:/mzx-ming02
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("D:/mzx-ming01")
CONTENT = Path(__file__).with_name("ming-01-jingnan.json")
GEN = "work/voice-clone-demo/cv3_generate_voice.py"
MODEL_DIR = "work/voice-clone-demo/models/Fun-CosyVoice3-0.5B-2512"
ENGINE = "cosyvoice3-0.5b-2512"
# CV3 零样本 prompt_text 新增格式要求(模型 README Basic Usage),CV2 不需要
PROMPT_PREFIX = "You are a helpful assistant.<|endofprompt|>"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", default=str(CONTENT))
    parser.add_argument("--out", default=None, help="输出目录(默认 D:/mzx-ming01)")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    content_path = Path(args.content)
    out = Path(args.out) if args.out else OUT
    content = json.loads(content_path.read_text(encoding="utf-8"))
    for chapter in content["chapters"]:
        assert chapter["narration"].strip()
    voice = content.get("voice", "doubao-东方浩然")
    vdir = ROOT / "work/studio/voices" / voice
    items = [{"id": i, "speaker": "A",
              # 同音字提示只进 TTS;字幕仍用 narration 正确写法。
              "text": c.get("tts_narration", c["narration"])}
             for i, c in enumerate(content["chapters"])]
    refs = {"A": {"ref_wav": str(vdir / "ref.wav"),
                  "ref_text_en": PROMPT_PREFIX
                  + (vdir / "ref.txt").read_text(encoding="utf-8").strip()}}
    # 指纹带引擎标记:换引擎即作废旧 parts,防止 CV2 旧音频被静默复用
    fp = hashlib.sha256(json.dumps([ENGINE, items, refs],
                                   ensure_ascii=False).encode()).hexdigest()
    out.mkdir(parents=True, exist_ok=True)
    marker = out / "tts_fingerprint.txt"
    if marker.exists() and marker.read_text() != fp:
        raise RuntimeError("文案或配音引擎已变更,请删除 tts_fingerprint.txt 与 parts 后重跑")
    for name, value in (("items.json", items), ("refs.json", refs)):
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    marker.write_text(fp)
    print("Prepared", len(items), "chapters ->", out, flush=True)
    if args.prepare_only:
        return

    mnt = "/mnt/" + out.as_posix()[0].lower() + out.as_posix()[2:]
    command = ("cd /mnt/e/ai/bilibiliVideoToZH && env "
               "HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 "
               f"/home/comfy/cosy-gpu-venv/bin/python {GEN} "
               f"--model-dir {MODEL_DIR} "
               f"--items-json {mnt}/items.json "
               f"--refs-json {mnt}/refs.json "
               f"--out-dir {mnt}/parts")
    subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-lc", command], check=True)


if __name__ == "__main__":
    main()
