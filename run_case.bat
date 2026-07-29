@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "FORMAL_DISK4_CASE_ARGS=%*"
set "EXIT_CODE=0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_case.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
set "FORMAL_DISK4_CASE_ARGS="

echo.
echo ============================================================
echo Case runner finished with exit code: %EXIT_CODE%
echo Press any key when you are ready to close this window.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
