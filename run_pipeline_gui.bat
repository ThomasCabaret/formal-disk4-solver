@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run setup.bat first.
    pause
    exit /b 5
)

set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

.venv\Scripts\python.exe -m formal_disk4.orchestration.gui
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Pipeline GUI exited with code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
