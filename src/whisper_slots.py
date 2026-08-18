"""无字幕视频:whisper ASR 直接生成配音时间槽(slots.json)。

输出与 prepare_fine_slots.py 同构:[{id,start,end,duration,speaker,text}],
speaker 恒 "A"(单人;多人无字幕场景需人工/后续声纹,当前不自动)。
供 translate → CosyVoice → assemble 链复用。

用法:
  python whisper_slots.py work/studio/<slug>/source-audio.wav \\
      -o work/studio/<slug>/slots.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import align_srt_asr  # noqa: E402

# 与 prepare_fine_slots 的聚槽参数一致
SLOT_MAX = 11.0
SEG_GAP = 2.0  # 段间停顿超过该值开新槽


def build_slots(segments: list[tuple[float, float, str]]) -> list[dict]:
    """whisper segments → ≤11s 朗读槽(段间停顿 >2s 或超上限时断槽)。"""
    slots: list[dict] = []
    for start, end, text in segments:
        text = text.strip()
        if not text:
            continue
        if slots and start - slots[-1]["end"] <= SEG_GAP \
                and end - slots[-1]["start"] <= SLOT_MAX:
            slots[-1]["end"] = max(slots[-1]["end"], end)
            slots[-1]["text"] += " " + text
        else:
            slots.append({"id": len(slots), "start": start, "end": end,
                          "speaker": "A", "text": text})
    for s in slots:
        s["start"] = round(s["start"], 3)
        s["end"] = round(s["end"], 3)
        s["duration"] = round(s["end"] - s["start"], 3)
    return slots


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audio", type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--language", default="en")
    ap.add_argument("--max-duration", type=float, default=None,
                    help="只处理前 N 秒(冒烟用)")
    args = ap.parse_args()

    cache = args.output.with_suffix(".asr.json")
    segments = align_srt_asr.transcribe(
        args.audio, language=args.language, cache_path=cache)
    if args.max_duration:
        segments = [s for s in segments if s[1] <= args.max_duration]
    slots = build_slots(segments)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(slots, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    total = sum(s["duration"] for s in slots)
    print(f"segments={len(segments)} slots={len(slots)} "
          f"total={total:.0f}s -> {args.output}")


if __name__ == "__main__":
    main()
