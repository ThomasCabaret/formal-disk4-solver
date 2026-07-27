@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXIT_CODE=0"

echo ============================================================
echo Formal Contour Solver - Test Suite
echo Working directory: %CD%
echo ============================================================
echo.
echo [INFO] Starting unit and integration tests...
echo [INFO] A persistent transcript will be written under logs\.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\test.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo [SUCCESS] All tests passed.
) else (
    echo [ERROR] Test suite failed with exit code %EXIT_CODE%.
    echo [ERROR] Read the messages above and the newest logs\tests_*.log file.
)

echo.
echo ============================================================
echo Script finished with exit code: %EXIT_CODE%
echo The command prompt will remain open.
echo Press any key when you are ready to close it.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
