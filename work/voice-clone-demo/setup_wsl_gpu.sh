#!/bin/bash
# WSL GPU 环境安装:ROCm 版 torch + CosyVoice 依赖 + 冒烟测试
set -e
VENV="$HOME/cosy-gpu-venv"
BASE="https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1"

"$VENV/bin/pip" install \
  "$BASE/torch-2.8.0%2Brocm7.2.1.lw.gitd733adb1-cp312-cp312-linux_x86_64.whl" \
  "$BASE/torchaudio-2.8.0%2Brocm7.2.1.git6e1c7fe9-cp312-cp312-linux_x86_64.whl" \
  "$BASE/triton-3.4.0%2Brocm7.2.1.git0cace8d2-cp312-cp312-linux_x86_64.whl"

"$VENV/bin/pip" install conformer diffusers HyperPyYAML librosa modelscope \
  onnxruntime transformers x-transformers wetext inflect omegaconf soundfile \
  gdown "numpy<2"

export HSA_ENABLE_DXG_DETECTION=1
export PATH="/opt/rocm/bin:$PATH"
"$VENV/bin/python" - <<'EOF'
import time
import torch
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0))
    a = torch.randn(4096, 4096, device="cuda", dtype=torch.float16)
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(20):
        a = a @ a
    torch.cuda.synchronize()
    dt = time.time() - t0
    print(f"matmul fp16: {20 * 2 * 4096**3 / dt / 1e12:.1f} TFLOPS")
EOF
