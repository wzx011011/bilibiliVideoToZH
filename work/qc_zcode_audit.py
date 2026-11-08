# -*- coding: utf-8 -*-
"""zcode-audit 成片 QC:逐段(parts16) ASR 回环 + 同音容错 CER(av_qc 同款逻辑)。

kinetic 管线没有 av_qc 需要的 chapters/timeline 格式,这里按 items 逐段转写拼总,
整体 hard CER ≤6% 为 PASS。共享一个 WhisperModel(8 段×20s,CPU 几分钟)。
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from av_qc import normalize_spoken, chapter_diff  # noqa: E402

SLUG = "zcode-audit"
AUDIO_MODEL = ROOT / "work/models/faster-whisper-large-v3-turbo"
WORK = ROOT / "kinetic_demo" / f"{SLUG}_video"
CFG = ROOT / "kinetic_demo" / "content" / f"{SLUG}.json"


def main() -> int:
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    items = {it["id"]: it["text"] for it in cfg["items"]}

    from faster_whisper import WhisperModel
    model = WhisperModel(str(AUDIO_MODEL), device="cpu", compute_type="int8")

    expected_all, got_all, hard_all = "", "", 0
    n_chars = 0
    for sid in cfg["order"]:
        wav = WORK / "parts16" / f"item_{sid:04d}.wav"
        segments, _ = model.transcribe(str(wav), language="zh",
                                       beam_size=5, vad_filter=True)
        got = "".join(s.text for s in segments)
        exp = items[sid]
        diff = chapter_diff(normalize_spoken(exp), normalize_spoken(got))
        hard = (sum(len(x["expected"]) for x in diff["substitutions"]
                    if not x["homophone"])
                + sum(len(m["expected"]) for m in diff["missing"]))
        hard_all += hard
        n_chars += len(normalize_spoken(exp))
        expected_all += normalize_spoken(exp)
        got_all += normalize_spoken(got)
        print(f"seg id={sid} cer={diff['cer']:.3f} hard={hard}", flush=True)

    hard_cer = hard_all / max(1, n_chars)
    diff = chapter_diff(expected_all, got_all)
    print(json.dumps({"overall_cer": diff["cer"],
                      "hard_cer": round(hard_cer, 4),
                      "status": "PASS" if hard_cer <= 0.06 else "FAIL"},
                     ensure_ascii=False))
    return 0 if hard_cer <= 0.06 else 1


if __name__ == "__main__":
    raise SystemExit(main())
