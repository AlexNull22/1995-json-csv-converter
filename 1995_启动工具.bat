@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "任务1995_PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%任务1995_PY%" set "任务1995_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%任务1995_PY%" (
  echo 请安装含Tkinter的Python 3.12，并按1995_使用说明.md运行。
  pause
  exit /b 2
)
"%任务1995_PY%" -B "%~dp01995_桌面工具.py"
if errorlevel 1 pause
endlocal