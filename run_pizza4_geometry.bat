@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXIT_CODE=0"

echo ============================================================
echo Formal Contour Solver - Four-Piece Pizza Candidate Geometry
echo Working directory: %CD%
echo Formal candidates: output\pizza4\candidates.jsonl
echo Configuration: config\pizza4_geometry.json
echo ============================================================
echo.
echo [INFO] This command realizes the contour of one piece only.
echo [INFO] It does not place or render the four congruent copies.
echo [INFO] Generic curve templates use one intermediate point by default.
echo [INFO] Circular arcs are kept as exact circular arcs.
echo [INFO] Solutions are written under output\pizza4\geometry\.
echo [INFO] A persistent transcript will be written under logs\.
echo [INFO] Use --restart to discard the geometry checkpoint and solutions.
echo.

if not exist "output\pizza4\candidates.jsonl" (
   echo [ERROR] Formal candidate file not found: output\pizza4\candidates.jsonl
   echo [ERROR] Run run_pizza4.bat --restart first.
   set "EXIT_CODE=9"
   goto :finished
)

set "FORMAL_DISK4_EXTRA_ARGS=%*"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_geometry.ps1" -Config "config\pizza4_geometry.json"
set "EXIT_CODE=%ERRORLEVEL%"
set "FORMAL_DISK4_EXTRA_ARGS="

:finished
echo.
if "%EXIT_CODE%"=="0" (
   echo [SUCCESS] Four-piece pizza geometry run completed successfully.
   echo [INFO] Read output\pizza4\geometry\geometric_solutions.jsonl.
) else (
   echo [ERROR] Four-piece pizza geometry run stopped or failed with exit code %EXIT_CODE%.
   echo [ERROR] Read the messages above and the newest logs\geometry_pizza4_geometry_*.log file.
)

echo.
echo ============================================================
echo Script finished with exit code: %EXIT_CODE%
echo The command prompt will remain open.
echo Press any key when you are ready to close it.
echo ============================================================
pause >nul
exit /b %EXIT_CODE%
