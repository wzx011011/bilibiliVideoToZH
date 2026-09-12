# -*- coding: utf-8 -*-
"""苹果发布会速览配音准备:content JSON → items/refs → CosyVoice(WSL GPU)。

与 mzx_story/prepare.py 同链路;音色默认东方浩然(新闻解说),可用 JSON voice 字段覆盖。
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("D:/apple-event-202609")
DEFAULT_CONTENT = Path(__file__).with_name("content-apple-2026-09.json")


def main():
    content_path = Path(sys.argv[sys.argv.index("--content") + 1]) \
        if "--content" in sys.argv else DEFAULT_CONTENT
    content = json.loads(content_path.read_text(encoding="utf-8"))
    for chapter in content["chapters"]:
        assert chapter["narration"].strip()
    voice = content.get("voice", "doubao-东方浩然")
    vdir = ROOT / "work/studio/voices" / voice
    items = [{"id": i, "speaker": "A",
              "text": c.get("tts_narration", c["narration"])}
             for i, c in enumerate(content["chapters"])]
    refs = {"A": {"ref_wav": str(vdir / "ref.wav"),
                  "ref_text_en": (vdir / "ref.txt").read_text(encoding="utf-8").strip()}}
    fp = hashlib.sha256(json.dumps([items, refs], ensure_ascii=False).encode()).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    marker = OUT / "tts_fingerprint.txt"
    if marker.exists() and marker.read_text() != fp:
        raise RuntimeError("文案已变更,请删除 tts_fingerprint.txt 与 parts 后重跑")
    for name, value in (("items.json", items), ("refs.json", refs)):
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    marker.write_text(fp)
    print("Prepared", len(items), "chapters", flush=True)
    if "--prepare-only" in sys.argv:
        return
    command = ("cd /mnt/e/ai/bilibiliVideoToZH && env "
               "HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 "
               "/home/comfy/cosy-gpu-venv/bin/python work/voice-clone-demo/generate_voice.py "
               f"--items-json /mnt/d/apple-event-202609/items.json "
               f"--refs-json /mnt/d/apple-event-202609/refs.json "
               f"--out-dir /mnt/d/apple-event-202609/parts")
    subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-lc", command], check=True)


if __name__ == "__main__":
    main()
