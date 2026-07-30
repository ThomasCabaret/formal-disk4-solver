@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXIT_CODE=0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run setup.bat first.
    set "EXIT_CODE=5"
    goto :finish
)

set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"

.venv\Scripts\python.exe -m formal_disk4.campaigns.cyclic suite %*
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
echo ============================================================
echo Cycle suite runner finished with exit code: %EXIT_CODE%
echo Press any key when you are ready to close this window.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
