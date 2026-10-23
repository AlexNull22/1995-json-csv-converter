@echo off
chcp 65001 >nul
setlocal
set "TASK1995_URL=https://www.upwork.com/jobs/Simple-JSON-CSV-Converter_~022110021927515828718/"
if exist "%ProgramFiles%\Mozilla Firefox\firefox.exe" (
    start "" "%ProgramFiles%\Mozilla Firefox\firefox.exe" "%TASK1995_URL%"
    exit /b 0
)
if exist "%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe" (
    start "" "%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe" "%TASK1995_URL%"
    exit /b 0
)
if exist "%LOCALAPPDATA%\Mozilla Firefox\firefox.exe" (
    start "" "%LOCALAPPDATA%\Mozilla Firefox\firefox.exe" "%TASK1995_URL%"
    exit /b 0
)
where firefox.exe >nul 2>nul
if errorlevel 1 (
    echo 未找到 Firefox。请安装 Firefox 后重新运行本文件。
    pause
    exit /b 1
)
start "" firefox.exe "%TASK1995_URL%"
endlocal
