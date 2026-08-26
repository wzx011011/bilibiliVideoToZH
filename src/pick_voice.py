# -*- coding: utf-8 -*-
"""按原声自动选型配音音色:基频判性别 + campplus 声纹相似度排名。

每部视频的嘉宾声线不同(性别/年龄/音色),不能沿用固定配置。
本工具从原片锚点段提取说话人声纹,音色库按 ref.wav 基频分男女,
同性候选中按余弦相似度排名,输出推荐。

用法(voice-clone-demo venv):
  python pick_voice.py --audio audio16k.wav --at 563 --until 574 [--top 5]
  python pick_voice.py --audio audio16k.wav --at 552 --until 600 --json
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi
import onnxruntime

ROOT = Path(__file__).resolve().parents[1]
CAMPPLUS = ROOT / "work/voice-clone-demo/models/CosyVoice2-0.5B/campplus.onnx"
VOICES = ROOT / "work/studio/voices"
# 性别判别用 F0 的 10 分位:静音/摩擦段的检测噪声在中高分位,
# 实测男声 p10≈97-121Hz,女声 p10≈162Hz+,边界取中
F0_SPLIT = 145.0


def emb(wav: torch.Tensor, sr: int, sess) -> np.ndarray:
    feat = kaldi.fbank(wav, num_mel_bins=80, dither=0, sample_frequency=sr)
    feat -= feat.mean(dim=0, keepdim=True)
    v = sess.run(None, {sess.get_inputs()[0].name:
                        feat.unsqueeze(0).numpy()})[0].flatten()
    return v / np.linalg.norm(v)


def f0_p10(wav: torch.Tensor, sr: int) -> float:
    f0 = torchaudio.functional.detect_pitch_frequency(wav, sr)
    v = f0[f0 > 50].numpy()
    return float(np.percentile(v, 10)) if len(v) else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--at", type=float, required=True, help="说话段起点(秒)")
    ap.add_argument("--until", type=float, required=True, help="说话段终点(秒)")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    full, sr = torchaudio.load(str(args.audio))
    if full.shape[0] > 1:
        full = full.mean(0, keepdim=True)
    seg = full[:, int(args.at * sr):int(args.until * sr)]
    sess = onnxruntime.InferenceSession(str(CAMPPLUS),
                                        providers=["CPUExecutionProvider"])
    tgt = emb(seg, sr, sess)
    tgt_f0 = f0_p10(seg, sr)
    tgt_female = tgt_f0 > F0_SPLIT

    rows = []
    for f in sorted(glob.glob(str(VOICES / "*" / "ref.wav"))):
        name = Path(f).parent.name
        if name.startswith("orig-") or name == "doubao-":
            continue
        try:
            w, s = torchaudio.load(f)
            if w.shape[0] > 1:
                w = w.mean(0, keepdim=True)
            if s != 16000:
                w = torchaudio.functional.resample(w, s, 16000)
            f0 = f0_p10(w, 16000)
            if (f0 > F0_SPLIT) != tgt_female:
                continue  # 性别不符
            rows.append((float(tgt @ emb(w, 16000, sess)), name, round(f0)))
        except Exception:
            continue
    rows.sort(reverse=True)

    if args.json:
        print(json.dumps({"target_f0": round(tgt_f0),
                          "female": tgt_female,
                          "rank": [{"name": n, "sim": round(s, 3)}
                                   for s, n, _ in rows[:args.top]]},
                         ensure_ascii=False))
        return
    print(f"目标声纹 F0p10={tgt_f0:.0f}Hz({'女' if tgt_female else '男'}声),"
          f" 候选 {len(rows)} 个")
    for s, n, f0 in rows[:args.top]:
        print(f"  {s:.3f}  {n}(F0p10 {f0})")


if __name__ == "__main__":
    main()
