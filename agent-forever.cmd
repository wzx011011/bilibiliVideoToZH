@echo off
REM PC agent watchdog: restart on crash after 5s
REM stdout/stderr captured for post-mortem(领取后无输出类故障的现场)
cd /d E:\ai\bilibiliVideoToZH
set STUDIO_SERVER=http://192.168.100.78:8766
set STUDIO_TOKEN=c5d0987a2d7a0105
set PYTHONIOENCODING=utf-8
:loop
echo ===== %date% %time% agent start ===== >> work\studio\agent-console.log
work\.venv-ocr\Scripts\python.exe -u src\studio_agent.py >> work\studio\agent-console.log 2>&1
echo ===== %date% %time% agent exit code %errorlevel% ===== >> work\studio\agent-console.log
timeout /t 5 /nobreak >nul
goto loop
