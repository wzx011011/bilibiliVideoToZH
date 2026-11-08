# -*- coding: utf-8 -*-
"""CV3 版逐段中文配音:与 generate_voice.py 同参数同输出,仅加载方式不同。

CosyVoice3.__init__ 不收 load_jit,而 AutoModel 原样转发 **kwargs 会
TypeError(实测冒烟踩坑),故绕过 AutoModel 直接实例化 CosyVoice3。
推理循环/断点续跑/拼接逻辑与 generate_voice.py 保持一致。
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CosyVoice"))
sys.path.insert(0, str(ROOT / "CosyVoice" / "third_party" / "Matcha-TTS"))
from generate_voice import _norm_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--items-json", required=True)
    ap.add_argument("--refs-json", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--concat-out", default=None)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--gap-ms", type=int, default=250)
    args = ap.parse_args()

    items = json.loads(_norm_path(args.items_json).read_text(encoding="utf-8"))
    refs = json.loads(_norm_path(args.refs_json).read_text(encoding="utf-8"))
    for spk, ref in refs.items():
        ref["ref_wav_abs"] = str(_norm_path(ref["ref_wav"]))
    out_dir = _norm_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    from cosyvoice.cli.cosyvoice import CosyVoice3
    model = CosyVoice3(model_dir=str(_norm_path(args.model_dir)),
                       load_trt=False, load_vllm=False, fp16=False)

    t0 = time.time()
    made = 0
    for n, it in enumerate(items, 1):
        out = out_dir / f"item_{int(it['id']):04d}.wav"
        if out.exists() and out.stat().st_size > 1000:
            continue
        spk = refs[it["speaker"]]
        pieces = [r["tts_speech"] for r in model.inference_zero_shot(
            it["text"], spk["ref_text_en"], spk["ref_wav_abs"], stream=False)]
        speech = torch.cat(pieces, dim=1)
        torchaudio.save(str(out), speech, model.sample_rate)
        made += 1
        dur = speech.shape[1] / model.sample_rate
        print(f"[{time.strftime('%H:%M:%S')}] {n}/{len(items)} "
              f"id={it['id']} {it['speaker']} gen={dur:.1f}s", flush=True)

    print(f"parts done made={made} total={len(items)} "
          f"elapsed={(time.time() - t0) / 60:.1f}min", flush=True)

    if args.concat_out:
        concat = _norm_path(args.concat_out)
        gap = torch.zeros(1, int(model.sample_rate * args.gap_ms / 1000))
        clips = []
        for it in items:
            w, _ = torchaudio.load(
                str(out_dir / f"item_{int(it['id']):04d}.wav"))
            clips.append(w)
        combined = clips[0]
        for w in clips[1:]:
            combined = torch.cat([combined, gap, w], dim=1)
        torchaudio.save(str(concat), combined, model.sample_rate)
        total = combined.shape[1] / model.sample_rate
        print(f"concat {len(clips)} 段 -> {concat} ({total / 60:.1f}min)",
              flush=True)


if __name__ == "__main__":
    main()
