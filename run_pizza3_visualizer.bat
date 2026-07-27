@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXIT_CODE=0"

echo ============================================================
echo Formal Contour Solver - Pizza Assembly Visualizer
echo Working directory: %CD%
echo Geometric solutions: output\pizza3\geometry\geometric_solutions.jsonl
echo Configuration: config\pizza3_visualizer.json
echo ============================================================
echo.
echo [INFO] This stage reconstructs all copies from formal contact mappings.
echo [INFO] It does not search for geometric placements.
echo [INFO] Pieces are filled with distinct solid colors and no outlines.
echo [INFO] Use the checkboxes to show or hide individual pieces.
echo [INFO] Use Previous and Next, or the left and right arrow keys, to navigate.
echo [INFO] A persistent transcript will be written under logs\.
echo.

if not exist "output\pizza3\geometry\geometric_solutions.jsonl" (
   echo [ERROR] Geometric solution file not found.
   echo [ERROR] Run run_pizza3.bat and run_pizza3_geometry.bat first.
   set "EXIT_CODE=9"
   goto :finished
)

set "FORMAL_DISK4_EXTRA_ARGS=%*"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_visualizer.ps1" -Config "config\pizza3_visualizer.json"
set "EXIT_CODE=%ERRORLEVEL%"
set "FORMAL_DISK4_EXTRA_ARGS="

:finished
echo.
if "%EXIT_CODE%"=="0" (
   echo [SUCCESS] Pizza visualizer completed successfully.
) else (
   echo [ERROR] Pizza visualizer stopped or failed with exit code %EXIT_CODE%.
   echo [ERROR] Read the messages above and the newest logs\visualizer_pizza3_visualizer_*.log file.
)

echo.
echo ============================================================
echo Script finished with exit code: %EXIT_CODE%
echo The command prompt will remain open.
echo Press any key when you are ready to close it.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
