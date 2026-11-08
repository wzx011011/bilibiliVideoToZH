"""访谈双人克隆试点:按说话人各自参考音频做 zero-shot,并输出对话式拼接 demo。

在 WSL GPU 环境运行(见 clone_episode.sh 的环境变量说明)。
"""

import json
import sys
import time
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "CosyVoice"))
sys.path.insert(0, str(ROOT / "CosyVoice" / "third_party" / "Matcha-TTS"))

PILOT = ROOT / "interview-pilot"


def main() -> None:
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

    parts_dir = PILOT / "parts"
    parts_dir.mkdir(exist_ok=True)

    for chunk in cfg["chunks"]:
        out = parts_dir / f"{chunk['id']}.wav"
        if out.exists() and out.stat().st_size > 1000:
            continue
        spk = cfg[chunk["spk"]]
        ref_wav = str(PILOT / spk["ref_wav"])
        t0 = time.perf_counter()
        pieces = []
        for r in model.inference_zero_shot(
                chunk["zh"], spk["ref_text_en"], ref_wav, stream=False):
            pieces.append(r["tts_speech"])
        speech = torch.cat(pieces, dim=1)
        torchaudio.save(str(out), speech, model.sample_rate)
        print(f"[{time.strftime('%H:%M:%S')}] {chunk['id']} ({chunk['spk']}): "
              f"{speech.shape[1]/model.sample_rate:.1f}s in "
              f"{time.perf_counter()-t0:.1f}s", flush=True)

    # 对比样:A1 用 cross_lingual(不需要参考文本)
    a1 = parts_dir / "A1-host-projection.wav"
    xout = parts_dir / "A1-crosslingual.wav"
    if a1.exists() and not xout.exists():
        spk = cfg["A"]
        pieces = [r["tts_speech"] for r in model.inference_cross_lingual(
            cfg["chunks"][2]["zh"], str(PILOT / spk["ref_wav"]), stream=False)]
        speech = torch.cat(pieces, dim=1)
        torchaudio.save(str(xout), speech, model.sample_rate)
        print(f"cross_lingual A1: {speech.shape[1]/model.sample_rate:.1f}s",
              flush=True)

    # 对话式拼接(按 chunks 顺序,块间 0.5s)
    ordered = ["A2-host-paper", "B2-hinton-georgedahl",
               "A1-host-projection", "B1-hinton-prize"]
    gap = int(0.5 * model.sample_rate)
    buf = []
    for cid in ordered:
        wav, sr = torchaudio.load(str(parts_dir / f"{cid}.wav"))
        buf += [wav, torch.zeros(1, gap)]
    demo = PILOT / "interview-pilot-demo.wav"
    torchaudio.save(str(demo), torch.cat(buf, dim=1), sr)
    print("demo:", demo)


if __name__ == "__main__":
    main()
