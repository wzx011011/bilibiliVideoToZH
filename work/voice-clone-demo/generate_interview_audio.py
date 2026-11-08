"""GPU 双音色克隆:逐轮次生成中文配音(WSL 环境,见 clone_episode.sh 说明)。"""

import json
import re
import sys
import time
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "CosyVoice"))
sys.path.insert(0, str(ROOT / "CosyVoice" / "third_party" / "Matcha-TTS"))

PILOT = ROOT / "interview-pilot"
BLOCK_MAX_CHARS = 160
INTERNAL_GAP = 0.25  # 轮内块间停顿


def split_blocks(text: str) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
    blocks, buf = [], ""
    for s in sentences:
        if buf and len(buf) + len(s) > BLOCK_MAX_CHARS:
            blocks.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        blocks.append(buf)
    return blocks


def main() -> None:
    turns = json.loads((PILOT / "turns.json").read_text(encoding="utf-8"))
    zh = json.loads((PILOT / "turns_zh.json").read_text(encoding="utf-8"))
    cfg = json.loads((PILOT / "pilot.json").read_text(encoding="utf-8"))

    torch.manual_seed(20260818)
    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    from cosyvoice.cli.cosyvoice import AutoModel

    model = AutoModel(
        model_dir=str(ROOT / "models" / "CosyVoice2-0.5B"),
        load_jit=False, load_trt=False, load_vllm=False, fp16=False,
    )
    gap = int(INTERNAL_GAP * model.sample_rate)
    parts = PILOT / "parts"
    parts.mkdir(exist_ok=True)

    manifest = []
    total_dur = 0.0
    for i, t in enumerate(turns):
        out = parts / f"turn_{i:02d}.wav"
        if not (out.exists() and out.stat().st_size > 1000):
            text = zh.get(str(i), "").strip()
            if not text:
                print(f"turn {i:02d}: NO ZH TEXT, skip", flush=True)
                continue
            spk = cfg[t["speaker"]]
            pieces = []
            t0 = time.perf_counter()
            for b in split_blocks(text):
                for r in model.inference_zero_shot(
                        b, spk["ref_text_en"],
                        str(PILOT / spk["ref_wav"]), stream=False):
                    pieces.append(r["tts_speech"])
                pieces.append(torch.zeros(1, gap))
            speech = torch.cat(pieces, dim=1)[:, :-gap]
            torchaudio.save(str(out), speech, model.sample_rate)
            print(f"[{time.strftime('%H:%M:%S')}] turn {i:02d} ({t['speaker']}): "
                  f"{speech.shape[1]/model.sample_rate:.1f}s audio in "
                  f"{time.perf_counter()-t0:.1f}s", flush=True)
        wav, _ = torchaudio.load(str(out))
        dur = wav.shape[1] / model.sample_rate
        total_dur += dur
        # 时间槽:到下一轮开始;最后一轮给原时长+6s 尾巴
        next_start = turns[i + 1]["start"] if i + 1 < len(turns) else t["end"] + 6.0
        slot = next_start - t["start"]
        manifest.append({
            "id": i, "speaker": t["speaker"], "start": t["start"],
            "slot": round(slot, 2), "gen_dur": round(dur, 2),
            "atempo": round(max(1.0, dur / slot), 4),
        })

    (PILOT / "audio_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    tight = [m for m in manifest if m["atempo"] > 1.15]
    print(f"total speech={total_dur:.0f}s, turns={len(manifest)}, "
          f"need>1.15x_speed={len(tight)} -> audio_manifest.json")


if __name__ == "__main__":
    main()
