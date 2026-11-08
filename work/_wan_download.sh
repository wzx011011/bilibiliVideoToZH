#!/bin/bash
set -e
cd ~/ComfyUI/models
B=https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files
for f in diffusion_models/wan2.2_ti2v_5B_fp16.safetensors \
         text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors \
         vae/wan2.2_vae.safetensors; do
  if [ -s "$f" ]; then echo "SKIP $f"; continue; fi
  echo "GET $f"
  curl -sL -C - --retry 5 --retry-delay 3 -x http://127.0.0.1:7897 -o "$f" "$B/$f"
  echo "DONE $f $(du -h "$f" | cut -f1)"
done
echo ALL_DONE
