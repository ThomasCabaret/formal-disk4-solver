@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXIT_CODE=0"

echo ============================================================
echo Formal Contour Solver - Four-Piece Pizza Test
echo Working directory: %CD%
echo Map: k4-pizza
echo Configuration: config\pizza4.json
echo ============================================================
echo.
echo [INFO] This run enumerates four congruent disk sectors.
echo [INFO] It stops after the first fully filtered finite survivor.
echo [INFO] Power families are recognized but not expanded by default.
echo [INFO] Checkpoint and survivors are stored under output\pizza4\.
echo [INFO] A persistent transcript will be written under logs\.
echo [INFO] Use --restart to discard the existing pizza checkpoint.
echo.

set "FORMAL_DISK4_EXTRA_ARGS=%*"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" -Config "config\pizza4.json"
set "EXIT_CODE=%ERRORLEVEL%"
set "FORMAL_DISK4_EXTRA_ARGS="

echo.
if "%EXIT_CODE%"=="0" (
    echo [SUCCESS] Four-piece pizza run completed successfully.
) else (
    echo [ERROR] Four-piece pizza run stopped or failed with exit code %EXIT_CODE%.
    echo [ERROR] Read the messages above and the newest logs\run_pizza4_*.log file.
)

echo.
echo ============================================================
echo Script finished with exit code: %EXIT_CODE%
echo The command prompt will remain open.
echo Press any key when you are ready to close it.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
