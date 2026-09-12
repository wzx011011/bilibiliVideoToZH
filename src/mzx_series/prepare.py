"""毛选推演系列配音准备:生成 items/refs 并调用 CosyVoice(与 gpt_explainer 同链路)。"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("D:/mzx-lunchiuzhan")
CONTENT = Path(__file__).with_name("lunchiuzhan.json")


def main():
    content = json.loads(CONTENT.read_text(encoding="utf-8"))
    ids = {s["id"] for s in content["sources"]}
    for chapter in content["chapters"]:
        assert chapter["narration"].strip() and set(chapter["source_ids"]) <= ids
    voice = ROOT / "work/studio/voices/doubao-东方浩然"
    items = [{"id": i, "speaker": "A", "text": c["narration"]}
             for i, c in enumerate(content["chapters"])]
    refs = {"A": {"ref_wav": str(voice / "ref.wav"),
                  "ref_text_en": (voice / "ref.txt").read_text(encoding="utf-8").strip()}}
    fp = hashlib.sha256(json.dumps([items, refs], ensure_ascii=False).encode()).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    marker = OUT / "tts_fingerprint.txt"
    if marker.exists() and marker.read_text() != fp:
        raise RuntimeError("文案已变更,请换新输出目录或清空 parts 后重跑")
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
               "--items-json /mnt/d/mzx-lunchiuzhan/items.json "
               "--refs-json /mnt/d/mzx-lunchiuzhan/refs.json "
               "--out-dir /mnt/d/mzx-lunchiuzhan/parts")
    subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-lc", command], check=True)


if __name__ == "__main__":
    main()
