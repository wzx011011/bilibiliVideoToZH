"""词级对齐结果 -> 停顿切 utterance -> campplus 重标说话人 -> 修正槽位归属。

旧方案的固定 5.5s 声纹窗口会混入两个说话人,边界归属经常错一位;
本工具按词间真实停顿(>gap 秒)切段,每段声纹只含单人,归属可靠。
只改 slots.json 的 speaker 字段(带 relabel_evidence 标记),不动文本与时间。

用法(voice-clone-demo venv,需 torch+onnxruntime):
  python src/label_speakers.py --words work/<slug>/work/words_align.json \
      --audio work/<slug>/work/audio16k.wav --slots work/<slug>/work/slots.json \
      --anchors '{"A":[3.5,18.8],"B":[547.3,566.1]}' --out work/<slug>/work/slots.json
"""
import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi

GAP = 0.6       # 词间停顿超过此值 -> utterance 边界
MIN_DUR = 0.8   # 短于此的 utterance 不做声纹标注
THRESH = 0.87   # campplus 同人相似度阈值(AGENTS 约定)
CAMPPLUS = Path(__file__).resolve().parents[1] / \
    "work/voice-clone-demo/models/CosyVoice2-0.5B/campplus.onnx"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--words", required=True, type=Path)
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--slots", required=True, type=Path)
    ap.add_argument("--anchors", required=True, help='{"A":[起,止],...}')
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    words = json.loads(args.words.read_text(encoding="utf-8"))
    anchors = json.loads(args.anchors)
    slots = json.loads(args.slots.read_text(encoding="utf-8"))
    full, sr = torchaudio.load(str(args.audio))
    sess = onnxruntime.InferenceSession(str(CAMPPLUS), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name

    def emb(s: float, e: float) -> np.ndarray:
        wav = full[:, int(s * sr):min(int(e * sr), full.shape[1])]
        feat = kaldi.fbank(wav, num_mel_bins=80, dither=0, sample_frequency=sr)
        feat -= feat.mean(dim=0, keepdim=True)
        v = sess.run(None, {inp: feat.unsqueeze(0).numpy()})[0].flatten()
        return v / np.linalg.norm(v)

    anchor_vecs = {k: emb(*v) for k, v in anchors.items()}

    # 1) 词 -> utterance(按停顿切)
    utts, buf = [], [words[0]]
    for w in words[1:]:
        if w["start"] - buf[-1]["end"] > GAP:
            utts.append(buf)
            buf = []
        buf.append(w)
    if buf:
        utts.append(buf)

    records = []
    for u in utts:
        s, e = u[0]["start"], u[-1]["end"]
        rec = {"start": round(s, 3), "end": round(e, 3), "dur": round(e - s, 3),
               "text": " ".join(x["text"] for x in u)}
        if e - s >= MIN_DUR:
            v = emb(s, e)
            sims = {k: float(v @ a) for k, a in anchor_vecs.items()}
            rec["sims"] = {k: round(x, 4) for k, x in sims.items()}
            rec["speaker"] = max(sims, key=sims.get)
            rec["margin"] = round(abs(sims["A"] - sims.get("B", 0.0)), 4)
            rec["confident"] = max(sims.values()) >= THRESH
        records.append(rec)

    # 2) 槽位按 utterance 覆盖率重标
    def utt_label(t0, t1):
        cov = {k: 0.0 for k in anchor_vecs}
        cov[None] = 0.0
        for r in records:
            if r["start"] >= t1 or r["end"] <= t0 or "speaker" not in r:
                continue
            ov = min(r["end"], t1) - max(r["start"], t0)
            if ov > 0:
                cov[r["speaker"]] += ov
        return max(cov, key=cov.get), cov

    diffs = 0
    for s in slots:
        lab, cov = utt_label(s["start"], s["end"])
        if lab and lab != s.get("speaker"):
            s["speaker"] = lab
            s["relabel_evidence"] = "word-align+campplus"
            diffs += 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(slots, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out.parent / "utterances.json").write_text(
        json.dumps(records, ensure_ascii=False), encoding="utf-8")

    conf = sum(1 for r in records if r.get("confident"))
    print(f"[✓] utterances={len(records)}(可信{conf}) 槽位归属修正 {diffs} 个 -> {args.out}")
    if diffs:
        print(f"    注意: {diffs} 个槽的说话人与旧标注不同,已按词级证据修正")


if __name__ == "__main__":
    main()
