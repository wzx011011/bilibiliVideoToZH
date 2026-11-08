@echo off
cd /d E:\ai\bilibiliVideoToZH
echo [%date% %time%] CHAIN START >> work\_chain.log
work\.venv-ocr\Scripts\python.exe -u src\mzx_story\prod_episode.py --content src\mzx_story\sy-02-erlitou.json --out C:/render-tmp/sy-02 --nas-dir 溯源篇 >> work\_chain.log 2>&1
echo [%date% %time%] S2 PROD EXIT %errorlevel% >> work\_chain.log
work\.venv-ocr\Scripts\python.exe -u work\run_batch_detached.py work\sy_ep03_images.json >> work\_chain.log 2>&1
work\.venv-ocr\Scripts\python.exe -u src\mzx_story\prod_episode.py --content src\mzx_story\sy-03-jiaguwen.json --out C:/render-tmp/sy-03 --nas-dir 溯源篇 >> work\_chain.log 2>&1
echo [%date% %time%] S3 PROD EXIT %errorlevel% >> work\_chain.log
work\.venv-ocr\Scripts\python.exe -u work\run_batch_detached.py work\sy_ep04_images.json >> work\_chain.log 2>&1
work\.venv-ocr\Scripts\python.exe -u src\mzx_story\prod_episode.py --content src\mzx_story\sy-04-xizhou.json --out C:/render-tmp/sy-04 --nas-dir 溯源篇 >> work\_chain.log 2>&1
echo [%date% %time%] S4 PROD EXIT %errorlevel% >> work\_chain.log
echo [%date% %time%] CHAIN DONE >> work\_chain.log
