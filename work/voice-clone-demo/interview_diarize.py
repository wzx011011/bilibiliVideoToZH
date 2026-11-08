"""全片说话人标注:窗口级 campplus 声纹 + 锚点最近邻,替代易漂移的交替启发式。"""

import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_refs import parse_vtt, clean_text, VTT  # noqa: E402

PILOT = Path(__file__).resolve().parent / "interview-pilot"
AUDIO = PILOT / "hinton-full.wav"
CAMPPLUS = Path(__file__).resolve().parent / "models" / "CosyVoice2-0.5B" / "campplus.onnx"

# 声纹验证过的锚点(见 embed_check.py)
ANCHORS = {"A": (3.5, 18.8), "B": (547.3, 566.1)}
WIN_TARGET = 6.0   # 窗口目标时长(秒)
WIN_MAX = 12.0


def fbanks(wav: torch.Tensor, sr: int) -> torch.Tensor:
    feat = kaldi.fbank(wav, num_mel_bins=80, dither=0, sample_frequency=sr)
    return feat - feat.mean(dim=0, keepdim=True)


def main() -> None:
    segs = parse_vtt(VTT)
    full, sr = torchaudio.load(str(AUDIO))
    assert sr == 16000
    sess = onnxruntime.InferenceSession(str(CAMPPLUS),
                                        providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name

    def embed_sec(s: float, e: float) -> np.ndarray:
        a, b = int(s * sr), min(int(e * sr), full.shape[1])
        v = sess.run(None, {inp: fbanks(full[:, a:b], sr).unsqueeze(0).numpy()})[0].flatten()
        return v / np.linalg.norm(v)

    anchors = {k: embed_sec(s, e) for k, (s, e) in ANCHORS.items()}

    # 字幕段聚成 6-16s 窗口
    windows = []
    cur = []
    for s, e, _t in segs:
        if cur and (e - cur[0][0] > WIN_TARGET or e - cur[0][0] > WIN_MAX and s > cur[-1][1]):
            windows.append(cur)
            cur = []
        cur.append((s, e))
        if e - cur[0][0] > WIN_MAX:
            windows.append(cur)
            cur = []
    if cur:
        windows.append(cur)

    labeled = []
    for w in windows:
        s, e = w[0][0], w[-1][1]
        if e - s < 2.5:
            continue
        emb = embed_sec(s, e)
        sims = {k: float(emb @ v) for k, v in anchors.items()}
        spk = max(sims, key=sims.get)
        margin = abs(sims["A"] - sims["B"])
        labeled.append({"start": s, "end": e, "speaker": spk, "margin": round(margin, 3)})

    # 合并同说话人窗口 → 轮次;低置信(<0.06)窗口并入前一轮
    turns = []
    for w in sorted(labeled, key=lambda x: x["start"]):
        if turns and (w["speaker"] == turns[-1]["speaker"] or w["margin"] < 0.04):
            turns[-1]["end"] = max(turns[-1]["end"], w["end"])
            turns[-1]["spk"] = turns[-1]["speaker"]
        else:
            turns.append(dict(w))
    # 过短轮次(<2.5s)并入前一轮
    merged = []
    for t in turns:
        if merged and t["end"] - t["start"] < 2.5:
            merged[-1]["end"] = t["end"]
        else:
            merged.append(t)

    # 挂接字幕文本
    for t in merged:
        texts = [txt for s, e, txt in segs if t["start"] - 0.3 <= s < t["end"]]
        t["text"] = clean_text(" ".join(texts))
        t.pop("margin", None)
        t.pop("spk", None)

    total_a = sum(t["end"] - t["start"] for t in merged if t["speaker"] == "A")
    total_b = sum(t["end"] - t["start"] for t in merged if t["speaker"] == "B")
    (PILOT / "turns.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"windows={len(labeled)} turns={len(merged)} "
          f"A_time={total_a:.0f}s B_time={total_b:.0f}s -> turns.json")
    for t in merged[:8]:
        print(f"  {t['speaker']} {t['start']:7.1f}-{t['end']:7.1f} {t['text'][:60]}")


if __name__ == "__main__":
    main()
