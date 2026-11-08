"""基准测试:线程数与 int8 量化对 CosyVoice2 CPU 推理速度的影响。"""

import json
import sys
import time
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "CosyVoice"))
sys.path.insert(0, str(ROOT / "CosyVoice" / "third_party" / "Matcha-TTS"))

from cosyvoice.cli.cosyvoice import AutoModel

PROMPT_TEXT = (
    "早上好，很高兴你们都来了，我还担心这种糟糕的天气会没什么人过来，"
    "看到大家都到场，我十分开心。"
)
REFERENCE_WAV = ROOT / "output" / "doubao-reference.wav"


def bench(model, tag: str, text: str, out_dir: Path) -> None:
    torch.manual_seed(20260817)
    t0 = time.perf_counter()
    chunks = [r["tts_speech"] for r in model.inference_zero_shot(
        text, PROMPT_TEXT, str(REFERENCE_WAV), stream=False)]
    took = time.perf_counter() - t0
    speech = torch.cat(chunks, dim=1)
    secs = speech.shape[1] / model.sample_rate
    torchaudio.save(str(out_dir / f"bench-{tag}.wav"), speech, model.sample_rate)
    print(f"[BENCH] {tag}: {secs:.1f}s audio in {took:.1f}s rtf={took/secs:.2f}",
          flush=True)


def main() -> None:
    blocks = json.loads((ROOT / "output" / "ep-23-clone" / "blocks.json")
                        .read_text(encoding="utf-8"))
    text = blocks[8]
    print(f"[BENCH] block 8 ({len(text)} chars): {text[:60]}", flush=True)

    torch.manual_seed(20260817)
    model = AutoModel(
        model_dir=str(ROOT / "models" / "CosyVoice2-0.5B"),
        load_jit=False, load_trt=False, load_vllm=False, fp16=False,
    )
    bench_dir = ROOT / "output" / "bench"
    bench_dir.mkdir(exist_ok=True)

    bench(model, "t8_fp32", text, bench_dir)

    torch.set_num_threads(16)
    bench(model, "t16_fp32", text, bench_dir)

    import torch.ao.quantization as q
    try:
        model.model.llm = q.quantize_dynamic(
            model.model.llm, {torch.nn.Linear}, dtype=torch.qint8)
        model.model.flow = q.quantize_dynamic(
            model.model.flow, {torch.nn.Linear}, dtype=torch.qint8)
        print("[BENCH] int8 dynamic quant applied to llm+flow", flush=True)
    except Exception as e:
        print(f"[BENCH] quant failed: {e}", flush=True)
        return
    bench(model, "t16_int8", text, bench_dir)

    torch.set_num_threads(8)
    bench(model, "t8_int8", text, bench_dir)


if __name__ == "__main__":
    main()
