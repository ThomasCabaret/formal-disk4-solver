@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXIT_CODE=0"

echo ============================================================
echo Formal Contour Solver - 20-Second K4 Stage Profile
echo Working directory: %CD%
echo Configuration: config\profile_k4.json
echo ============================================================
echo.
echo [INFO] This run performs no checkpointing and writes no candidates.
echo [INFO] It stops after approximately 20 seconds, including inside the word solver.
echo [INFO] Stage timings and LP cache statistics are written to output\profile_k4\run_summary.json.
echo [INFO] Additional command-line arguments are accepted, for example --max-seconds 60.
echo [INFO] A persistent transcript will be written under logs\.
echo.

set "FORMAL_DISK4_EXTRA_ARGS=%* --restart"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" -Config "config\profile_k4.json"
set "EXIT_CODE=%ERRORLEVEL%"
set "FORMAL_DISK4_EXTRA_ARGS="

echo.
if "%EXIT_CODE%"=="0" (
   echo [SUCCESS] K4 stage profile completed successfully.
   echo [INFO] Read output\profile_k4\run_summary.json.
) else (
   echo [ERROR] K4 stage profile failed with exit code %EXIT_CODE%.
)

echo.
echo ============================================================
echo Script finished with exit code: %EXIT_CODE%
echo The command prompt will remain open.
echo Press any key when you are ready to close it.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
