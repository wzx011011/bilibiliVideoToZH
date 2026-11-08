@echo off
cd /d E:iilibiliVideoToZH
start "" /min wsl -d Ubuntu-24.04 -- sleep infinity
work\.venv-ocr\Scripts\python.exe -u work\qwen_cast_gen.py --job work\zq_cast_fix.json > work\_castfix.log 2>&1
