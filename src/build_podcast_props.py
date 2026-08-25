# -*- coding: utf-8 -*-
"""构建播客版(Remotion)全片 props:修复后译文 + 重生成音频 + 顺序时间轴。

输入:work/studio/hinton-medicine-v2/work/narration/{runs,items_doubao}.json
      work/studio/hinton-medicine-v2/work/narration/parts_doubao/item_*.wav
输出:work/podcast-studio/public/audio_fixed/NNNN.wav
      work/podcast-studio/props-full.json(48 章,含分块渲染边界帧号)
"""
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path("E:/ai/bilibiliVideoToZH")
NR = ROOT / "work/studio/hinton-medicine-v2/work/narration"
STUDIO = ROOT / "work/podcast-studio"
FFPROBE = ROOT / "work/video-tools/ffprobe.exe"
FPS = 30
GAP = 0.3
SPEAKERS = {"A": "Eric Topol 主持人", "B": "Geoffrey Hinton"}


def probe(p: Path) -> float:
    out = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(p)], check=True,
                         capture_output=True, text=True).stdout.strip()
    return float(out)


def main():
    runs = json.loads((NR / "runs.json").read_text(encoding="utf-8"))
    items = {it["id"]: it for it in
             json.loads((NR / "items_doubao.json").read_text(encoding="utf-8"))}
    audio_dir = STUDIO / "public" / "audio_polished"
    audio_dir.mkdir(parents=True, exist_ok=True)

    chapters, cursor = [], 0.0
    prev_spk = None
    for r in runs:
        it = items[r["id"]]
        part = audio_dir / f"{r['id']:04d}.wav"
        if not part.exists():
            part = NR / "parts_doubao" / f"item_{r['id']:04d}.wav"
            dst = audio_dir / f"{r['id']:04d}.wav"
            shutil.copy2(part, dst)
        dur = probe(audio_dir / f"{r['id']:04d}.wav")
        # 换人停顿 0.7s,同人连续 0.45s(旧版统一 0.3s,显得急促)
        gap = 0.45 if it["speaker"] == prev_spk else 0.7
        cursor += 0.0 if prev_spk is None else gap
        chapters.append({
            "id": r["id"], "speaker": it["speaker"],
            "speakerName": SPEAKERS[it["speaker"]],
            "avatarFile": f"avatars/speaker-{it['speaker']}.jpg",
            "start": round(cursor, 3), "end": round(cursor + dur, 3),
            "text": it["text"], "audioFile": f"audio_polished/{r['id']:04d}.wav",
        })
        cursor += dur
        prev_spk = it["speaker"]

    total = chapters[-1]["end"]
    # 分块边界(每块 ~12 章,边界取章起点帧)
    bounds = [0] + [round(chapters[i]["start"] * FPS) for i in range(12, 48, 12)] + [int(total * FPS) + 60]
    props = {"title": "Hinton 访谈 · 中文播客 · 修复版(全片)", "chapters": chapters}
    (STUDIO / "props-full.json").write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"chapters={len(chapters)} total={total/60:.1f}min -> props-full.json")
    print(f"chunks: {[f'{bounds[i]}-{bounds[i+1]-1}' for i in range(len(bounds)-1)]}")
    print(f"durationInFrames 上限: {bounds[-1]}")


if __name__ == "__main__":
    main()
