@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXIT_CODE=0"

echo ============================================================
echo Formal Contour Solver - Enumeration-Only Run
echo Working directory: %CD%
echo Configuration: config\enumeration_only.json
echo ============================================================
echo.
echo [INFO] Starting enumeration with the word solver disabled...
echo [INFO] A persistent transcript will be written under logs\.
echo.

set "FORMAL_DISK4_EXTRA_ARGS=%*"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" -Config "config\enumeration_only.json"
set "EXIT_CODE=%ERRORLEVEL%"
set "FORMAL_DISK4_EXTRA_ARGS="

echo.
if "%EXIT_CODE%"=="0" (
    echo [SUCCESS] Enumeration-only run completed successfully.
) else (
    echo [ERROR] Enumeration-only run failed with exit code %EXIT_CODE%.
    echo [ERROR] Read the messages above and the newest logs\run_enumeration_only_*.log file.
)

echo.
echo ============================================================
echo Script finished with exit code: %EXIT_CODE%
echo The command prompt will remain open.
echo Press any key when you are ready to close it.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
