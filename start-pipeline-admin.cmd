@echo off
setlocal
cd /d "%~dp0"
if exist "work\.venv-ocr\Scripts\python.exe" (
  "work\.venv-ocr\Scripts\python.exe" "src\pipeline_admin.py" %*
) else (
  py -3 "src\pipeline_admin.py" %*
)
if errorlevel 1 pause
