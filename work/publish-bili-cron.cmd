@echo off
rem Ming dynasty bilibili auto-publish wrapper (Task Scheduler 1200/1700 daily)
rem ASCII-only + CRLF on purpose: cmd parses batch files with the ANSI codepage,
rem UTF-8 Chinese comment bytes can swallow the newline and kill the next line.
cd /d E:\ai\bilibiliVideoToZH
set PATH=F:\Program Files\Git\usr\bin;C:\Program Files\Git\usr\bin;%PATH%
set PYTHONIOENCODING=utf-8
echo ===== %date% %time% ===== >> E:\ai\bilibiliVideoToZH\work\publish-cron.log
work\.venv-ocr\Scripts\python.exe src\mzx_story\publish_bilibili.py >> E:\ai\bilibiliVideoToZH\work\publish-cron.log 2>&1
