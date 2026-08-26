@echo off
REM PC 执行代理:轮询 NAS 控制面领任务。双击运行或加入开机启动。
REM 开机自启: Win+R 输入 shell:startup,把本文件快捷方式放进去。
setlocal
cd /d "%~dp0"
set STUDIO_SERVER=http://192.168.100.78:8766
set STUDIO_TOKEN=c5d0987a2d7a0105
work\.venv-ocr\Scripts\python.exe src\studio_agent.py
if errorlevel 1 pause
