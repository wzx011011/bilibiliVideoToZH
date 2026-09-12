# -*- coding: utf-8 -*-
"""明朝故事线音色试听:同一段文案,多个候选音色各出一版小样。"""
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "work/voice-clone-demo/generate_voice.py"
OUT = Path("D:/voice-audition-ming01")
TEXT = ("朱棣的应对方式相当迷惑：装疯。大夏天的裹着棉被在街上烤火，"
        "抢人家酒食，满嘴胡话。朝廷派来的探子一看，得，真疯了。")
VOICES = ["doubao-京腔侃爷", "doubao-率性阿哲", "doubao-东方浩然",
          "doubao-渊博小叔", "doubao-清爽男大"]

ENV = ("HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1")
PY = "/home/comfy/cosy-gpu-venv/bin/python"

for i, voice in enumerate(VOICES):
    vdir = ROOT / "work/studio/voices" / voice
    if not (vdir / "ref.wav").exists():
        print(f"[skip] {voice}: 缺 ref.wav", flush=True)
        continue
    work = OUT / voice
    work.mkdir(parents=True, exist_ok=True)
    (work / "items.json").write_text(json.dumps(
        [{"id": 0, "speaker": "A", "text": TEXT}], ensure_ascii=False), encoding="utf-8")
    (work / "refs.json").write_text(json.dumps({"A": {
        "ref_wav": str(vdir / "ref.wav"),
        "ref_text_en": (vdir / "ref.txt").read_text(encoding="utf-8").strip(),
    }}, ensure_ascii=False), encoding="utf-8")
    args = (f"--items-json /mnt/d/voice-audition-ming01/{voice}/items.json "
            f"--refs-json /mnt/d/voice-audition-ming01/{voice}/refs.json "
            f"--out-dir /mnt/d/voice-audition-ming01/{voice}/parts")
    inner = f"cd /mnt/e/ai/bilibiliVideoToZH && env {ENV} {PY} work/voice-clone-demo/generate_voice.py {args}"
    r = subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-lc", inner])
    wav = work / "parts" / "item_0000.wav"
    print(f"[{'ok' if wav.exists() else 'FAIL'}] {voice}", flush=True)
