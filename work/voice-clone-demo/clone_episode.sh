#!/bin/bash
# 一键用 CosyVoice2 克隆豆包音色生成整集配音(优先 WSL GPU,可切 CPU)
# 用法(在仓库根目录):
#   bash work/voice-clone-demo/clone_episode.sh 23        # GPU(7800 XT, rtf≈2.3)
#   bash work/voice-clone-demo/clone_episode.sh 23 --cpu  # Windows CPU(rtf≈7,保底)
# 断点续跑:重复执行自动跳过已生成的块(parts/*.wav)
set -e
EP="$1"
MODE="${2:---gpu}"
[ -n "$EP" ] || { echo "用法: bash work/voice-clone-demo/clone_episode.sh <集数> [--cpu]"; exit 1; }

ROOT="$(cd "$(dirname "$0")" && pwd)"
FFMPEG="$ROOT/../video-tools/ffmpeg.exe"
OUT_DIR="$ROOT/output/ep-$EP-clone"
WAV="$OUT_DIR/episode-$EP-cosyvoice2-clone.wav"
MP3="$OUT_DIR/episode-$EP-cosyvoice2-clone.mp3"

if [ "$MODE" = "--cpu" ]; then
    "$ROOT/.venv/Scripts/python.exe" "$ROOT/generate_full.py" --episode "$EP"
else
    # GPU 关键环境变量(缺一不可,详见 skill doubao-voice-clone):
    #   HSA_ENABLE_DXG_DETECTION=1  WSL2 下 ROCm 走 /dev/dxg 识别 GPU
    #   COSY_FP16=0                 必须 fp32;fp16 会生成乱码(bf16权重转fp16溢出)
    #   TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1  torch 2.8 加载旧 checkpoint
    MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- bash -c \
      "cd /mnt/e/ai/bilibiliVideoToZH && env HSA_ENABLE_DXG_DETECTION=1 COSY_FP16=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 /home/comfy/cosy-gpu-venv/bin/python work/voice-clone-demo/generate_full.py --episode $EP"
fi

"$FFMPEG" -y -hide_banner -loglevel error -i "$WAV" -c:a libmp3lame -b:a 192k "$MP3"
echo "完成: $WAV"
echo "完成: $MP3"
