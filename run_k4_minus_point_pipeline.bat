@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "FORMAL_DISK4_CASE_ARGS=k4-minus-point pipeline %*"
set "EXIT_CODE=0"

echo ============================================================
echo Formal Contour Solver - k4-minus-point full pipeline
echo ============================================================
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_case.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
set "FORMAL_DISK4_CASE_ARGS="

echo.
echo ============================================================
echo Pipeline finished with exit code: %EXIT_CODE%
echo Press any key when you are ready to close this window.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
