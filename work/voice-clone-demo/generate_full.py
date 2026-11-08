"""用 CosyVoice2 零样本克隆批量生成整集配音。

用法:
    python generate_full.py --episode 23            # 全量(断点续跑)
    python generate_full.py --episode 23 --limit 3  # 只生成前3块(测速)
    python generate_full.py --episode 23 --concat-only  # 只拼接已有块
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent
COSYVOICE_ROOT = ROOT / "CosyVoice"
sys.path.insert(0, str(COSYVOICE_ROOT))
sys.path.insert(0, str(COSYVOICE_ROOT / "third_party" / "Matcha-TTS"))

PROMPT_TEXT = (
    "早上好，很高兴你们都来了，我还担心这种糟糕的天气会没什么人过来，"
    "看到大家都到场，我十分开心。"
)
REFERENCE_WAV = ROOT / "output" / "doubao-reference.wav"

# 每块目标字数:句子聚合上限,块内由 CosyVoice 前端自行切分
BLOCK_MIN_CHARS = 90
BLOCK_MAX_CHARS = 160
PAUSE_SECONDS = 0.30  # 块间停顿


def load_script(asr_json: Path) -> list[str]:
    segments = json.loads(asr_json.read_text(encoding="utf-8"))
    text = "".join(s["text"] for s in segments).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
    blocks: list[str] = []
    buf = ""
    for sent in sentences:
        if buf and len(buf) + len(sent) > BLOCK_MAX_CHARS:
            blocks.append(buf)
            buf = sent
        else:
            buf += sent
        if len(buf) >= BLOCK_MIN_CHARS:
            blocks.append(buf)
            buf = ""
    if buf:
        blocks.append(buf)
    return blocks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", type=str, required=True)
    parser.add_argument("--limit", type=int, default=0, help="只生成前N块(测速)")
    parser.add_argument("--skip", type=int, default=0, help="跳过前N块(配合--limit测中段)")
    parser.add_argument("--concat-only", action="store_true")
    args = parser.parse_args()

    ep = args.episode
    asr_json = Path(f"work/ep-{ep}/episode-{ep}-audio.mp3.asr.json")
    out_dir = ROOT / "output" / f"ep-{ep}-clone"
    parts_dir = out_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    blocks = load_script(asr_json)
    index_path = out_dir / "blocks.json"
    if not index_path.exists():
        index_path.write_text(
            json.dumps(blocks, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    todo = list(enumerate(blocks))
    if args.skip:
        todo = todo[args.skip:]
    if args.limit:
        todo = todo[: args.limit]

    log_path = out_dir / "progress.log"

    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    if not args.concat_only:
        torch.manual_seed(20260817)
        if torch.cuda.is_available():
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
        from cosyvoice.cli.cosyvoice import AutoModel

        log(f"loading model, {len(blocks)} blocks total, {len(todo)} todo")
        model = AutoModel(
            model_dir=str(ROOT / "models" / "CosyVoice2-0.5B"),
            load_jit=False,
            load_trt=False,
            load_vllm=False,
            fp16=os.environ.get("COSY_FP16", "0") == "1",
        )
        done = 0
        total_audio = 0.0
        total_compute = 0.0
        for idx, text in todo:
            part = parts_dir / f"{idx:03d}.wav"
            if part.exists() and part.stat().st_size > 1000:
                continue
            t0 = time.perf_counter()
            chunks = []
            for result in model.inference_zero_shot(
                text, PROMPT_TEXT, str(REFERENCE_WAV), stream=False
            ):
                chunks.append(result["tts_speech"])
            if not chunks:
                log(f"block {idx:03d}: NO OUTPUT, text={text[:40]}")
                continue
            speech = torch.cat(chunks, dim=1)
            torchaudio.save(str(part), speech, model.sample_rate)
            secs = speech.shape[1] / model.sample_rate
            took = time.perf_counter() - t0
            done += 1
            total_audio += secs
            total_compute += took
            log(
                f"block {idx:03d}/{len(blocks) - 1}: {secs:.1f}s audio in {took:.1f}s "
                f"(rtf {took / secs:.2f}, avg rtf {total_compute / total_audio:.2f})"
            )

    # ---- 拼接 ----
    part_files = sorted(parts_dir.glob("*.wav"))
    if not part_files:
        log("no parts to concat")
        return
    expected = len(blocks)
    log(f"concat {len(part_files)}/{expected} parts")
    sample_rate = None
    pieces: list[torch.Tensor] = []
    pause_samples: int | None = None
    for pf in part_files:
        wav, sr = torchaudio.load(str(pf))
        sample_rate = sr
        if pause_samples is None:
            pause_samples = int(PAUSE_SECONDS * sr)
        pieces.append(wav)
        pieces.append(torch.zeros(1, pause_samples))
    full = torch.cat(pieces, dim=1)  # 尾部多一段停顿,无伤大雅
    final_wav = out_dir / f"episode-{ep}-cosyvoice2-clone.wav"
    torchaudio.save(str(final_wav), full, sample_rate)
    log(
        f"final: {final_wav.name} {full.shape[1] / sample_rate:.1f}s "
        f"({len(part_files)}/{expected} blocks)"
    )


if __name__ == "__main__":
    main()
