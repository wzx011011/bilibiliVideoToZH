"""从 YouTube 滚动 VTT 恢复真实短语时间槽，并用 campplus 声纹标注说话人。

已参数化(默认值 = Hinton 试点原值,向后兼容):
  python prepare_fine_slots.py --vtt X.vtt --audio full.wav       --anchors '{"A":[3.5,18.8],"B":[547.3,566.1]}' --out fine/slots.json
单人视频只给 {"A":[起,止]} 一个锚点即可(全部标为 A)。
"""

import argparse
import json
import re
from pathlib import Path

import numpy as np
import onnxruntime
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi

ROOT = Path(__file__).resolve().parent
PILOT = ROOT / "interview-pilot"
FINE = PILOT / "fine"
CAMPPLUS = ROOT / "models" / "CosyVoice2-0.5B" / "campplus.onnx"


def _rel(p: str) -> Path:
    """相对路径按脚本目录解析(Windows/WSL 两栖)。"""
    q = Path(p)
    return q if q.is_absolute() else ROOT / q


def ts(v: str) -> float:
    h, m, rest = v.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def parse_phrases() -> list[dict]:
    """0.01s plain cue 的 start 是对应短语的真实结束点。"""
    blocks = re.split(r"\n\s*\n", VTT.read_text(encoding="utf-8"))
    first_start = None
    endpoints = []
    for block in blocks:
        lines = [x.strip() for x in block.splitlines() if x.strip()]
        time_line = next((x for x in lines if "-->" in x), None)
        if not time_line:
            continue
        a, b = [x.strip().split()[0] for x in time_line.split("-->")]
        s, e = ts(a), ts(b)
        if first_start is None:
            first_start = s
        text_lines = [x for x in lines if x != time_line and not x.startswith(("WEBVTT", "Kind:", "Language:"))]
        text = " ".join(text_lines).strip()
        if e - s <= 0.03 and text and "<" not in text:
            endpoints.append((s, re.sub(r"\s+", " ", text)))
    out = []
    prev = first_start or 0.0
    for end, text in endpoints:
        if end > prev + 0.15:
            out.append({"start": prev, "end": end, "text": text})
        prev = max(prev, end)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vtt", default=str(next((ROOT.parent.parent / "youtube" / "geoffrey-hinton").glob("*.en-orig.vtt"))))
    ap.add_argument("--audio", default=str(PILOT / "hinton-full.wav"))
    ap.add_argument("--anchors", default='{"A":[3.5,18.8],"B":[547.3,566.1]}',
                    help='声纹锚点 JSON,如 {"A":[3.5,18.8],"B":[547.3,566.1]}')
    ap.add_argument("--out", default=str(FINE / "slots.json"))
    ap.add_argument("--pre-target", type=float, default=5.5, help="声纹预窗口秒数")
    ap.add_argument("--slot-max", type=float, default=11.0, help="单槽上限秒数")
    ap.add_argument("--campplus", default=str(CAMPPLUS))
    args = ap.parse_args()

    global VTT, AUDIO, ANCHORS, PRE_TARGET, SLOT_MAX
    VTT = _rel(args.vtt)
    AUDIO = _rel(args.audio)
    ANCHORS = {k: tuple(v) for k, v in json.loads(args.anchors).items()}
    PRE_TARGET, SLOT_MAX = args.pre_target, args.slot_max
    out_path = _rel(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    campplus_path = _rel(args.campplus)

    phrases = parse_phrases()
    full, sr = torchaudio.load(str(AUDIO))
    sess = onnxruntime.InferenceSession(str(campplus_path), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name

    def emb(s: float, e: float) -> np.ndarray:
        wav = full[:, int(s * sr):min(int(e * sr), full.shape[1])]
        feat = kaldi.fbank(wav, num_mel_bins=80, dither=0, sample_frequency=sr)
        feat -= feat.mean(dim=0, keepdim=True)
        v = sess.run(None, {inp: feat.unsqueeze(0).numpy()})[0].flatten()
        return v / np.linalg.norm(v)

    anchors = {k: emb(*v) for k, v in ANCHORS.items()}

    # 先聚合成约 5.5s 声纹窗口
    pre, buf = [], []
    for p in phrases:
        if buf and p["end"] - buf[0]["start"] > PRE_TARGET:
            pre.append(buf)
            buf = []
        buf.append(p)
    if buf:
        pre.append(buf)

    labeled = []
    for w in pre:
        s, e = w[0]["start"], w[-1]["end"]
        if e - s < 1.2:
            continue
        v = emb(s, e)
        sims = {k: float(v @ a) for k, a in anchors.items()}
        labeled.append({
            "start": s, "end": e, "speaker": max(sims, key=sims.get),
            "margin": round(abs(sims["A"] - sims["B"]), 3),
            "text": " ".join(x["text"] for x in w),
        })

    # 同人相邻窗口合并，但每槽不超过 11s
    slots = []
    for w in labeled:
        can_merge = (slots and slots[-1]["speaker"] == w["speaker"]
                     and w["end"] - slots[-1]["start"] <= SLOT_MAX)
        if can_merge:
            slots[-1]["end"] = w["end"]
            slots[-1]["text"] += " " + w["text"]
            slots[-1]["margin"] = min(slots[-1]["margin"], w["margin"])
        else:
            slots.append(dict(w))
    for i, s in enumerate(slots):
        s["id"] = i
        s["start"] = round(s["start"], 3)
        s["end"] = round(s["end"], 3)
        s["duration"] = round(s["end"] - s["start"], 3)

    out_path.write_text(json.dumps(slots, ensure_ascii=False, indent=1), encoding="utf-8")
    a = sum(x["duration"] for x in slots if x["speaker"] == "A")
    b = sum(x["duration"] for x in slots if x["speaker"] == "B")
    print(f"phrases={len(phrases)} prewindows={len(labeled)} slots={len(slots)} A={a:.0f}s B={b:.0f}s")
    for s in slots[:10]:
        print(f"{s['id']:03d} {s['speaker']} {s['start']:6.1f}-{s['end']:6.1f} ({s['duration']:4.1f}s) {s['text'][:55]}")


if __name__ == "__main__":
    main()
