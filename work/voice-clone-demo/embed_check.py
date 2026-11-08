"""声纹验证:对候选轮次算 campplus 声纹余弦相似度,验证说话人归属。"""

import subprocess
import sys
from pathlib import Path

import numpy as np
import onnxruntime
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi

PILOT = Path(__file__).resolve().parent / "interview-pilot"
AUDIO = PILOT / "hinton-full.wav"
FFMPEG = Path(__file__).resolve().parent.parent / "video-tools" / "ffmpeg.exe"
CAMPPLUS = Path(__file__).resolve().parent / "models" / "CosyVoice2-0.5B" / "campplus.onnx"

# (标签, 起始, 结束, 语义假设)
CANDS = [
    ("t0-intro",    3.5,   18.8, "A主持人"),
    ("t2-dahl",    80.2,  107.2, "B-Hinton"),
    ("t4-comp",   124.4,  134.8, "B-Hinton"),
    ("t8-paper",  265.9,  322.8, "A主持人"),
    ("t12-proj",  520.2,  543.2, "A主持人"),
    ("t13-egos",  547.3,  566.1, "B-Hinton"),
]


def cut(tag: str, start: float, end: float) -> Path:
    out = PILOT / "refs" / f"{tag}.wav"
    subprocess.run([str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(AUDIO), "-ss", str(start), "-to", str(end),
                    "-ac", "1", "-ar", "16000", str(out)], check=True)
    return out


def embed(path: Path) -> np.ndarray:
    wav, _ = torchaudio.load(str(path))
    feat = kaldi.fbank(wav, num_mel_bins=80, dither=0, sample_frequency=16000)
    feat = feat - feat.mean(dim=0, keepdim=True)
    sess = onnxruntime.InferenceSession(str(CAMPPLUS),
                                        providers=["CPUExecutionProvider"])
    emb = sess.run(None, {sess.get_inputs()[0].name:
                          feat.unsqueeze(dim=0).numpy()})[0].flatten()
    return emb / np.linalg.norm(emb)


def main() -> None:
    tags, embs, hyps = [], [], []
    for tag, s, e, hyp in CANDS:
        wav = cut(tag, s, e)
        embs.append(embed(wav))
        tags.append(tag)
        hyps.append(hyp)
    m = np.array(embs)
    sim = m @ m.T
    print("            " + " ".join(f"{t.split('-')[0]:>8}" for t in tags))
    for i, tag in enumerate(tags):
        row = " ".join(f"{sim[i, j]:8.3f}" for j in range(len(tags)))
        print(f"{tag:>12} {row}   hyp={hyps[i]}")
    print("\n同假设内均值 vs 跨假设均值:")
    same, cross = [], []
    for i in range(len(tags)):
        for j in range(i + 1, len(tags)):
            (same if hyps[i] == hyps[j] else cross).append(sim[i, j])
    print(f"  same={np.mean(same):.3f}  cross={np.mean(cross):.3f}")


if __name__ == "__main__":
    sys.exit(main())
