#!/bin/bash
f=$(ls -t ~/ComfyUI/output/wan22_i2v_*.mp4 2>/dev/null | head -1)
if [ -n "$f" ]; then
  cp "$f" /mnt/d/mzx-ming16-i2v/s3_2.mp4 && echo "COPIED $f"
  ls -la /mnt/d/mzx-ming16-i2v/s3_2.mp4
else
  echo "NO OUTPUT FOUND"
fi
