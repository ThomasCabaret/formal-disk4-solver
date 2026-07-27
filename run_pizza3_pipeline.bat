@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXIT_CODE=0"

echo ============================================================
echo Formal Contour Solver - Complete Pizza Pipeline
echo Working directory: %CD%
echo Stages: formal search, piece geometry, mapped assembly viewer
echo ============================================================
echo.
echo [INFO] Use --restart to discard both formal and geometry checkpoints.
echo [INFO] Without --restart, completed stages resume from their existing state.
echo [INFO] The final graphical window remains open until you close it.
echo [INFO] A persistent transcript will be written under logs\.
echo.

set "FORMAL_DISK4_EXTRA_ARGS=%*"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_pizza3_pipeline.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
set "FORMAL_DISK4_EXTRA_ARGS="

echo.
if "%EXIT_CODE%"=="0" (
   echo [SUCCESS] Complete pizza pipeline completed successfully.
) else (
   echo [ERROR] Complete pizza pipeline stopped or failed with exit code %EXIT_CODE%.
   echo [ERROR] Read the messages above and the newest logs\pizza3_full_pipeline_*.log file.
)

echo.
echo ============================================================
echo Script finished with exit code: %EXIT_CODE%
echo The command prompt will remain open.
echo Press any key when you are ready to close it.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
