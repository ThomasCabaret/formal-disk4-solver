@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXIT_CODE=0"

echo ============================================================
echo Formal Contour Solver - Debug Run
echo Working directory: %CD%
echo Configuration: config\debug.json
echo ============================================================
echo.
echo [INFO] Starting the debug pipeline...
echo [INFO] A persistent transcript will be written under logs\.
echo.

set "FORMAL_DISK4_EXTRA_ARGS=%*"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" -Config "config\debug.json"
set "EXIT_CODE=%ERRORLEVEL%"
set "FORMAL_DISK4_EXTRA_ARGS="

echo.
if "%EXIT_CODE%"=="0" (
    echo [SUCCESS] Debug run completed successfully.
) else (
    echo [ERROR] Debug run failed with exit code %EXIT_CODE%.
    echo [ERROR] Read the messages above and the newest logs\run_debug_*.log file.
)

echo.
echo ============================================================
echo Script finished with exit code: %EXIT_CODE%
echo The command prompt will remain open.
echo Press any key when you are ready to close it.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
