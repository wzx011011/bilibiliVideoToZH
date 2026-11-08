"""instruct2 口音对比测试:显式指令压口音。"""

import json
import sys
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
    spk = cfg["A"]
    zh = cfg["chunks"][2]["zh"]
    for tag, instruct in [
        ("A1-instruct2", "请用地道流利的标准普通话自然地说这句话<|endofprompt|>"),
    ]:
        out = PILOT / "parts" / f"{tag}.wav"
        if out.exists() and out.stat().st_size > 1000:
            continue
        pieces = [r["tts_speech"] for r in model.inference_instruct2(
            zh, instruct, str(PILOT / spk["ref_wav"]), stream=False)]
        speech = torch.cat(pieces, dim=1)
        torchaudio.save(str(out), speech, model.sample_rate)
        print(tag, f"{speech.shape[1]/model.sample_rate:.1f}s")


if __name__ == "__main__":
    main()
