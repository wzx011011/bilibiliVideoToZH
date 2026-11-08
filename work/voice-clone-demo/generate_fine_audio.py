"""GPU 生成字幕时间槽的双音色中文配音，断点续跑(已生成的 wav 自动跳过)。

已参数化(默认值 = Hinton 试点原值)。refs JSON 格式(pilot.json 同构):
  {"A": {"ref_wav": "refs/t0-intro.wav", "ref_text_en": "..."},
   "B": {"ref_wav": "...", "ref_text_en": "..."}}
ref_wav 相对路径按 refs JSON 所在目录解析;音色库(voice_lib)导出的
meta.json 可直接作为 --refs-json 使用。

GPU 运行(Windows 侧调用):
  MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- bash -c     "cd /mnt/e/ai/bilibiliVideoToZH && env HSA_ENABLE_DXG_DETECTION=1      COSY_FP16=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1      /home/comfy/cosy-gpu-venv/bin/python      work/voice-clone-demo/generate_fine_audio.py --slots ... --refs-json ..."
"""

import argparse
import json
import sys
import time
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "CosyVoice"))
sys.path.insert(0, str(ROOT / "CosyVoice" / "third_party" / "Matcha-TTS"))
PILOT = ROOT / "interview-pilot"
FINE = PILOT / "fine"


def _rel(p: str, base: Path) -> Path:
    q = Path(p)
    return q if q.is_absolute() else base / q


def _norm_path(p: str) -> Path:
    """跨系统路径:Windows 绝对路径在 WSL/Linux 侧转 /mnt/<drive>/...。
    必须用字符串正则检测盘符——Linux 的 Path('E:\...').drive 是空,
    会被当相对路径拼到 ROOT 下(实测踩坑)。"""
    import os as _os
    import re as _re
    s = str(p)
    m = _re.match(r"^([A-Za-z]):[\\/](.*)$", s)
    if m:
        if _os.name != "nt":
            return Path("/mnt/" + m.group(1).lower() + "/"
                        + m.group(2).replace("\\", "/"))
        return Path(s)
    q = Path(s)
    return q if q.is_absolute() else ROOT / q


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slots", default=str(FINE / "slots.json"))
    ap.add_argument("--slots-zh", default=str(FINE / "slots_zh_v2.json"))
    ap.add_argument("--refs-json", default=str(PILOT / "pilot.json"))
    ap.add_argument("--parts-dir", default=str(FINE / "parts"))
    ap.add_argument("--model-dir", default=str(ROOT / "models" / "CosyVoice2-0.5B"))
    ap.add_argument("--seed", type=int, default=20260818)
    args = ap.parse_args()

    slots_path = _norm_path(args.slots)
    zh_path = _norm_path(args.slots_zh)
    refs_path = _norm_path(args.refs_json)
    parts = _norm_path(args.parts_dir)
    model_dir = _norm_path(args.model_dir)
    parts.mkdir(parents=True, exist_ok=True)

    slots = json.loads(slots_path.read_text(encoding="utf-8"))
    zh = json.loads(zh_path.read_text(encoding="utf-8"))
    refs = json.loads(refs_path.read_text(encoding="utf-8"))
    for spk, ref in refs.items():  # ref_wav 相对路径 → 相对 refs JSON 目录
        ref["ref_wav_abs"] = str(_norm_path(ref["ref_wav"]))

    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    from cosyvoice.cli.cosyvoice import AutoModel
    model = AutoModel(model_dir=str(model_dir),
                      load_jit=False, load_trt=False, load_vllm=False, fp16=False)

    t0 = time.time(); made = 0
    for n, s in enumerate(slots, 1):
        out = parts / f"slot_{s['id']:03d}.wav"
        if out.exists() and out.stat().st_size > 1000:
            continue
        spk = refs[s["speaker"]]
        pieces = [r["tts_speech"] for r in model.inference_zero_shot(
            zh[str(s["id"])], spk["ref_text_en"], spk["ref_wav_abs"], stream=False)]
        speech = torch.cat(pieces, dim=1)
        torchaudio.save(str(out), speech, model.sample_rate)
        made += 1
        dur = speech.shape[1] / model.sample_rate
        print(f"[{time.strftime('%H:%M:%S')}] {n}/{len(slots)} s{s['id']:03d} {s['speaker']} "
              f"gen={dur:.1f}s slot={s['duration']:.1f}s ratio={dur/s['duration']:.2f}", flush=True)
    print(f"done made={made} total={len(slots)} elapsed={(time.time()-t0)/60:.1f}min")


if __name__ == "__main__":
    main()
