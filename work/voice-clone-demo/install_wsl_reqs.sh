#!/bin/bash
set -e
VENV="$HOME/cosy-gpu-venv"
REQ=/mnt/e/ai/bilibiliVideoToZH/work/voice-clone-demo/CosyVoice/requirements.txt
FILTERED=$(mktemp)
grep -vE '^(torch==|torchaudio==|deepspeed|tensorrt|onnxruntime-gpu|gradio|--extra|#)' "$REQ" > "$FILTERED"
cat "$FILTERED"
"$VENV/bin/pip" install -r "$FILTERED" 2>&1 | tail -3
