@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXIT_CODE=0"

echo ============================================================
echo Formal Contour Solver - Unbounded K4 Run
echo Working directory: %CD%
echo Configuration: config\full_k4.json
echo ============================================================
echo.
echo [WARNING] This configuration has no time, node, placement, or profile limit.
echo [WARNING] Press Ctrl+C to stop the solver. JSONL records already flushed remain usable.
echo [INFO] A persistent transcript will be written under logs\.
echo.

set "FORMAL_DISK4_EXTRA_ARGS=%*"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" -Config "config\full_k4.json"
set "EXIT_CODE=%ERRORLEVEL%"
set "FORMAL_DISK4_EXTRA_ARGS="

echo.
if "%EXIT_CODE%"=="0" (
    echo [SUCCESS] Full K4 run completed successfully.
) else (
    echo [ERROR] Full K4 run stopped or failed with exit code %EXIT_CODE%.
    echo [ERROR] Read the messages above and the newest logs\run_full_k4_*.log file.
)

echo.
echo ============================================================
echo Script finished with exit code: %EXIT_CODE%
echo The command prompt will remain open.
echo Press any key when you are ready to close it.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
