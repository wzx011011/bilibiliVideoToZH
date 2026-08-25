"""ForcedAligner 词级对齐 worker(WSL qwen-aligner-venv 内运行)。

VTT 短语 + 音频 -> 每词精确 [start,end],窗口按短语边界切分(≤window-max 秒)。
平台阶段与命令行共用。

用法:
  ~/qwen-aligner-venv/bin/python src/align_worker.py \
      --audio work/<slug>/work/audio16k.wav --vtt xxx.en-orig.vtt \
      --out work/<slug>/work/words_align.json [--window-max 280]
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

MODEL_ID = "Qwen/Qwen3-ForcedAligner-0.6B-hf"
SR = 16000


def norm(p: str) -> Path:
    """Windows 路径(E:\\x\\y) -> WSL(/mnt/e/x/y);其余原样。"""
    m = re.match(r"^([A-Za-z]):[\\/](.*)", p)
    if m:
        return Path("/mnt/" + m.group(1).lower() + "/" + m.group(2).replace("\\", "/"))
    return Path(p)


def ts(v: str) -> float:
    h, m, rest = v.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def load_phrases(vtt_path: Path):
    """0.01s cue 的 start = 短语真实结束点(YouTube 滚动 VTT 约定)。"""
    blocks = re.split(r"\n\s*\n", vtt_path.read_text(encoding="utf-8"))
    first_start = None
    endpoints = []
    for block in blocks:
        lines = [x.strip() for x in block.splitlines() if x.strip()]
        tl = next((x for x in lines if "-->" in x), None)
        if not tl:
            continue
        a, b = [x.strip().split()[0] for x in tl.split("-->")]
        s, e = ts(a), ts(b)
        if first_start is None:
            first_start = s
        text = " ".join(x for x in lines if x != tl
                        and not x.startswith(("WEBVTT", "Kind:", "Language:"))).strip()
        if e - s <= 0.03 and text and "<" not in text:
            endpoints.append((e, re.sub(r"\s+", " ", text)))
    phrases, prev = [], first_start or 0.0
    for end, text in endpoints:
        if end > prev + 0.15:
            phrases.append((prev, end, text))
        prev = max(prev, end)
    return phrases


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--vtt", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--window-max", type=float, default=280.0)
    args = ap.parse_args()
    args.audio, args.vtt, args.out = (norm(str(args.audio)), norm(str(args.vtt)),
                                      norm(str(args.out)))

    phrases = load_phrases(args.vtt)
    total = phrases[-1][1]
    windows, buf = [], []
    for p in phrases:
        if buf and p[1] - buf[0][0] > args.window_max:
            windows.append(buf)
            buf = []
        buf.append(p)
    if buf:
        windows.append(buf)
    print(f"phrases={len(phrases)} total={total:.0f}s windows={len(windows)}", flush=True)

    from transformers import AutoProcessor, AutoModelForTokenClassification
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForTokenClassification.from_pretrained(
        MODEL_ID, dtype=torch.float32, device_map="cpu")

    wav, sr = sf.read(str(args.audio), dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    assert sr == SR, f"音频需 {SR}Hz,实际 {sr}"

    all_words = []
    for wi, w in enumerate(windows, 1):
        w0 = max(0.0, w[0][0] - 1.0)
        w1 = min(total, w[-1][1] + 1.0)
        seg = wav[int(w0 * SR):int(w1 * SR)]
        transcript = " ".join(t for _, _, t in w)
        inputs, word_lists = processor.prepare_forced_aligner_inputs(
            audio=seg, transcript=transcript, language="English")
        inputs = inputs.to(model.device, model.dtype)
        with torch.inference_mode():
            outputs = model(**inputs)
        words = processor.decode_forced_alignment(
            logits=outputs.logits, input_ids=inputs["input_ids"],
            word_lists=word_lists,
            timestamp_token_id=model.config.timestamp_token_id)[0]
        for x in words:
            all_words.append({"text": x["text"],
                              "start": round(x["start_time"] + w0, 3),
                              "end": round(x["end_time"] + w0, 3)})
        print(f"  window {wi}/{len(windows)}: {w0:.0f}-{w1:.0f}s words={len(words)}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(all_words, ensure_ascii=False), encoding="utf-8")
    bad = sum(1 for a, b in zip(all_words, all_words[1:]) if b["start"] < a["start"] - 0.01)
    print(f"[✓] {len(all_words)} 词 -> {args.out} (时序异常 {bad})")


if __name__ == "__main__":
    main()
