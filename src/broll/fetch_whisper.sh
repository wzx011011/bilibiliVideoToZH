#!/usr/bin/env bash
# 下载 faster-whisper large-v3-turbo 模型到 ~/models/(QC ASR 用)
# 双源:先 hf-mirror 直连,401/失败则改走 Clash 代理连 huggingface.co
set -e
DEST="$HOME/models/faster-whisper-large-v3-turbo"
REPO="deepdml/faster-whisper-large-v3-turbo-ct2"
mkdir -p "$DEST"
cd "$DEST"
for f in config.json model.bin preprocessor_config.json tokenizer.json vocabulary.txt; do
  if [ -s "$f" ]; then
    echo "[skip] $f ($(stat -c%s "$f") bytes)"
    continue
  fi
  echo "[get] $f ..."
  if ! curl -fL --retry 2 -sS -o "$f" "https://hf-mirror.com/$REPO/resolve/main/$f" 2>/dev/null; then
    rm -f "$f"
    echo "  [fallback] huggingface.co via proxy ..."
    curl -fL --retry 2 -sS -x http://127.0.0.1:7897 -o "$f" \
      "https://huggingface.co/$REPO/resolve/main/$f"
  fi
  echo "[ok] $f ($(stat -c%s "$f") bytes)"
done
echo "DONE: $DEST"
