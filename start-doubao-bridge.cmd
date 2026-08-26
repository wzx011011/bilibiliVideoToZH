@echo off
setlocal
cd /d "%~dp0"
if exist "C:\Python311\python.exe" (
  "C:\Python311\python.exe" "src\doubao_bridge.py" start
) else (
  py -3 "src\doubao_bridge.py" start
)
if errorlevel 1 pause
