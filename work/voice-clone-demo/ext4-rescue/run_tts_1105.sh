#!/bin/bash
# 单会话:解包 matcha(锁定版)-> 校验 -> CPU 合成 1105
set +e
rm -rf /home/comfy/cosyvoice-src/CosyVoice/third_party/Matcha-TTS/matcha
tar -xf /mnt/c/Users/67376/AppData/Local/Temp/matcha_pinned.tar -C /home/comfy/cosyvoice-src/CosyVoice/third_party/Matcha-TTS/
C=$(grep -c BASECFM /home/comfy/cosyvoice-src/CosyVoice/third_party/Matcha-TTS/matcha/models/components/flow_matching.py)
echo "BASECFM_COUNT=$C"
if [ "$C" -lt 1 ]; then echo EXTRACT_BAD; exit 9; fi
find /home/comfy/cosyvoice-src/CosyVoice/third_party/Matcha-TTS/matcha -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
cd /home/comfy/cosyvoice-src
env CUDA_VISIBLE_DEVICES='' TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 PYTHONIOENCODING=utf-8 \
  /home/comfy/cosy-gpu-venv/bin/python -u cv3_generate_voice.py \
  --items-json /home/comfy/tts1105_items.json \
  --refs-json /home/comfy/tts1105_refs.json \
  --out-dir /home/comfy/tts1105_out \
  --model-dir /home/comfy/models/Fun-CosyVoice3-0.5B-2512 2>&1 | grep -vE "Warning|warn|Sliding" | tail -4
echo "TTS_EXIT=$?"
echo "FILES=$(ls /home/comfy/tts1105_out 2>/dev/null | wc -l)"
