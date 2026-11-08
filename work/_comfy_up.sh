#!/bin/bash
cd /home/comfy/ComfyUI || exit 1
HSA_ENABLE_DXG_DETECTION=1 nohup /home/comfy/cosy-gpu-venv/bin/python main.py --listen 127.0.0.1 --port 8188 > /mnt/e/ai/bilibiliVideoToZH/work/comfy.log 2>&1 < /dev/null &
echo "launched $!"
