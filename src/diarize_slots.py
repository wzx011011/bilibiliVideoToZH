"""无字幕多人槽位声纹标注:槽聚合窗口 + campplus 锚点最近邻。

替代 voice-clone-demo/interview_diarize.py(那是 Hinton 试点硬编码脚本,
不接受参数,平台调用实际无效)。本工具:
  1. 相邻槽聚成 4~12s 窗口(同一窗口默认同人,gap>2s 或超长切窗)
  2. 每窗 campplus 声纹与锚点余弦最近邻,低置信(margin<0.04)沿用前窗
  3. 窗口标签写回其聚合的每个槽(speaker + relabel_evidence)

用法(voice-clone-demo venv,需 torch+onnxruntime):
  python diarize_slots.py --audio audio16k.wav --slots slots.json \
      --anchors '{"A":[60,80],"B":[563,574]}' --out slots.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi

CAMPPLUS = Path(__file__).resolve().parents[1] / \
    "work/voice-clone-demo/models/CosyVoice2-0.5B/campplus.onnx"
WIN_TARGET = 6.0
WIN_MAX = 12.0
GAP = 2.0     # 槽间停顿超过此值切窗
LOW_MARGIN = 0.04


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--slots", required=True, type=Path)
    ap.add_argument("--anchors", required=True, help='{"A":[起,止],...}')
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    slots = json.loads(args.slots.read_text(encoding="utf-8"))
    anchors = json.loads(args.anchors)
    if len(anchors) < 2:
        print("[跳过] 单锚点无法区分说话人,槽位保持默认")
        return

    full, sr = torchaudio.load(str(args.audio))
    sess = onnxruntime.InferenceSession(str(CAMPPLUS),
                                        providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name

    def emb(s: float, e: float) -> np.ndarray:
        wav = full[:, int(s * sr):min(int(e * sr), full.shape[1])]
        feat = kaldi.fbank(wav, num_mel_bins=80, dither=0,
                           sample_frequency=sr)
        feat -= feat.mean(dim=0, keepdim=True)
        v = sess.run(None, {inp: feat.unsqueeze(0).numpy()})[0].flatten()
        return v / np.linalg.norm(v)

    anchor_vecs = {k: emb(float(v[0]), float(v[1]))
                   for k, v in anchors.items()}

    # 1) 槽聚合窗口
    windows, cur = [], []
    for s in slots:
        if cur and (s["start"] - cur[-1]["end"] > GAP
                    or s["end"] - cur[0]["start"] > WIN_MAX):
            windows.append(cur)
            cur = []
        cur.append(s)
        if s["end"] - cur[0]["start"] > WIN_MAX:
            windows.append(cur)
            cur = []
    if cur:
        windows.append(cur)

    # 2) 窗口分类(低置信沿用前窗,保持轮次连续性)
    prev = None
    stats = {k: 0.0 for k in anchors}
    for w in windows:
        s, e = w[0]["start"], w[-1]["end"]
        spk, margin = prev, LOW_MARGIN
        if e - s >= 2.5:
            v = emb(s, e)
            sims = {k: float(v @ a) for k, a in anchor_vecs.items()}
            spk = max(sims, key=sims.get)
            margin = max(sims.values()) - sorted(sims.values())[-2] \
                if len(sims) > 1 else 1.0
        if margin < LOW_MARGIN and prev is not None:
            spk = prev
        prev = spk
        for slot in w:
            slot["speaker"] = spk
            slot["relabel_evidence"] = "campplus-window"
        stats[spk] = stats.get(spk, 0.0) + (e - s)

    args.out.write_text(json.dumps(slots, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    total = sum(stats.values()) or 1.0
    dist = " ".join(f"{k}={v/60:.0f}min({v/total*100:.0f}%)" for k, v in stats.items())
    print(f"[✓] {len(slots)} 槽 / {len(windows)} 窗 -> {args.out.name}  {dist}")
    # 轮次样例(同说话人连续窗口合并)
    runs = []
    for s in slots:
        if runs and runs[-1][0] == s["speaker"]:
            runs[-1][2] = s["end"]
        else:
            runs.append([s["speaker"], s["start"], s["end"]])
    for r in runs[:10]:
        print(f"  {r[0]} {r[1]:7.1f}-{r[2]:7.1f}")


if __name__ == "__main__":
    main()
