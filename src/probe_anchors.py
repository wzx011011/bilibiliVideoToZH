# -*- coding: utf-8 -*-
"""声纹自聚类探测锚点:不依赖语义判断,找开头里差异最大的两个说话窗口。

锚点的硬需求是"A/B 两段是不同的人"(选错会导致全片单人)。
方案:开头 15 分钟切 20s 窗 → campplus 声纹 → 贪心二聚类 →
两簇各取与对方簇差异最大的窗作锚点,并打印各簇代表文本供人工定 A/B。

用法(voice-clone-demo venv):
  python probe_anchors.py --audio audio16k.wav [--vtt x.en.vtt] [--head 900]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import onnxruntime
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi

CAMPPLUS = Path(__file__).resolve().parents[1] / \
    "work/voice-clone-demo/models/CosyVoice2-0.5B/campplus.onnx"
WIN = 20.0
STEP = 25.0


def vtt_spans(path: Path, head: float):
    """有语音的字幕时间范围(无 vtt 则整段用)。"""
    ts = re.compile(r"(\d+):(\d+):(\d+)\.(\d+) --> (\d+):(\d+):(\d+)\.(\d+)")
    spans = []
    for block in path.read_text(encoding="utf-8").split("\n\n"):
        m = ts.search(block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        s = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        e = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = " ".join(l for l in block.splitlines()
                        if "-->" not in l and not l.strip().isdigit())
        text = re.sub(r"<[^>]+>", "", text).strip()
        if s < head and text:
            spans.append((s, e, text))
    return spans


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--vtt", type=Path,
                    help="有则只取字幕覆盖的窗口(跳过片头音乐/静音)")
    ap.add_argument("--head", type=float, default=900.0)
    args = ap.parse_args()

    full, sr = torchaudio.load(str(args.audio))
    limit = min(args.head, full.shape[1] / sr)
    texts = []
    if args.vtt and args.vtt.exists():
        texts = vtt_spans(args.vtt, limit)

    sess = onnxruntime.InferenceSession(str(CAMPPLUS),
                                        providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name

    def emb(s: float, e: float):
        wav = full[:, int(s * sr):min(int(e * sr), full.shape[1])]
        feat = kaldi.fbank(wav, num_mel_bins=80, dither=0,
                           sample_frequency=sr)
        feat -= feat.mean(dim=0, keepdim=True)
        v = sess.run(None, {inp: feat.unsqueeze(0).numpy()})[0].flatten()
        return v / np.linalg.norm(v)

    # 窗口(有 vtt 时要求 ≥60% 被字幕覆盖)
    wins = []
    t = 0.0
    while t + WIN <= limit:
        if texts:
            cov = sum(min(e, t + WIN) - max(s, t)
                      for s, e, _ in texts if e > t and s < t + WIN)
            if cov < WIN * 0.6:
                t += STEP
                continue
        wins.append((t, t + WIN))
        t += STEP
    if len(wins) < 6:
        raise SystemExit("可用窗口不足(检查音频/字幕)")

    vecs = np.stack([emb(s, e) for s, e in wins])
    sim = vecs @ vecs.T

    # 贪心二分:最不相似的两窗作种子
    i, j = np.unravel_index(np.argmin(sim), sim.shape)
    lab = np.zeros(len(wins), dtype=int)
    for k in range(len(wins)):
        lab[k] = 0 if sim[k, i] >= sim[k, j] else 1
    # 各簇取与对方簇平均差异最大的窗
    anchors = {}
    sizes = {0: int((lab == 0).sum()), 1: int((lab == 1).sum())}
    for c, seed in ((0, i), (1, j)):
        members = np.where(lab == c)[0]
        opp = np.where(lab != c)[0]
        if len(members) < 2 or len(opp) < 2:
            raise SystemExit("聚类退化(可能全片单人或窗口太少)")
        score = sim[members][:, opp].mean(axis=1)
        best = members[np.argmax(score)]
        anchors[str(c + 1)] = [round(wins[best][0], 1),
                               round(wins[best][1], 1)]

    # 打印两锚点段文本辅助人工定 A(主持)/B(嘉宾)
    for tag, (a0, a1) in anchors.items():
        seg = " ".join(t for s, e, t in texts
                       if e > a0 and s < a1)[:160] if texts else "(无字幕)"
        print(f"簇{tag} {a0}-{a1}s 窗{sizes[int(tag) - 1]}个: {seg}",
              file=__import__("sys").stderr)
    print(json.dumps(anchors))


if __name__ == "__main__":
    main()
