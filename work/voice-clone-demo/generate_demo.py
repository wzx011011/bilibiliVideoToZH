import sys
from pathlib import Path

import torch
import torchaudio


ROOT = Path(__file__).resolve().parent
COSYVOICE_ROOT = ROOT / "CosyVoice"
sys.path.insert(0, str(COSYVOICE_ROOT))
sys.path.insert(0, str(COSYVOICE_ROOT / "third_party" / "Matcha-TTS"))

from cosyvoice.cli.cosyvoice import AutoModel


PROMPT_TEXT = (
    "早上好，很高兴你们都来了，我还担心这种糟糕的天气会没什么人过来，"
    "看到大家都到场，我十分开心。"
)
TEST_TEXT = (
    "真正的改变，往往不是来自某个惊天动地的决定，"
    "而是来自每天一点点、持续而温柔的行动。"
)


def main() -> None:
    torch.manual_seed(20260817)
    model = AutoModel(
        model_dir=str(ROOT / "models" / "CosyVoice2-0.5B"),
        load_jit=False,
        load_trt=False,
        load_vllm=False,
        fp16=False,
    )
    chunks = []
    for result in model.inference_zero_shot(
        TEST_TEXT,
        PROMPT_TEXT,
        str(ROOT / "output" / "doubao-reference.wav"),
        stream=False,
    ):
        chunks.append(result["tts_speech"])
    if not chunks:
        raise RuntimeError("CosyVoice returned no audio")
    output = ROOT / "output" / "cosyvoice2-doubao-clone.wav"
    torchaudio.save(str(output), torch.cat(chunks, dim=1), model.sample_rate)
    print(output)


if __name__ == "__main__":
    main()
