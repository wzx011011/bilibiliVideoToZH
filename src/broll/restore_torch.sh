#!/usr/bin/env bash
# 恢复 cosy-gpu-venv 的 ROCm torch 栈(被 CUDA torch 顶掉后的修复)。
# 来源: repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/ (doubao-voice-clone skill 记录)
set -e
P=/home/comfy/cosy-gpu-venv/bin/pip
PY=/home/comfy/cosy-gpu-venv/bin/python
BASE=https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1

echo "[1/3] 卸载 CUDA torch..."
$P uninstall -y torch

echo "[2/3] 重装 ROCm torch/torchaudio/torchvision/triton (--no-deps)..."
$P install --no-deps \
  "$BASE/torch-2.8.0%2Brocm7.2.1.lw.gitd733adb1-cp312-cp312-linux_x86_64.whl" \
  "$BASE/torchaudio-2.8.0%2Brocm7.2.1.git6e1c7fe9-cp312-cp312-linux_x86_64.whl" \
  "$BASE/torchvision-0.23.0%2Brocm7.2.1.git824e8c87-cp312-cp312-linux_x86_64.whl" \
  "$BASE/triton-3.3.1%2Brocm7.2.1.git28a7371e-cp312-cp312-linux_x86_64.whl"

echo "[3/3] 验证..."
$PY -c "import torch; print('ver:', torch.__version__, '| hip:', torch.version.hip)"
HSA_ENABLE_DXG_DETECTION=1 $PY -c "import torch; print('cuda avail:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0))"
echo "RESTORE DONE"
