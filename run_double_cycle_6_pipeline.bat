@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo Formal Contour Solver - double-cycle-6 full pipeline
echo ============================================================
set "FORMAL_DISK4_CASE_ARGS=double-cycle-6 pipeline %*"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_case.ps1"
set "EXITCODE=%ERRORLEVEL%"
echo.
echo [INFO] Exit code: %EXITCODE%
pause
exit /b %EXITCODE%
