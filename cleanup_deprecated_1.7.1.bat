@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] git was not found in PATH.
  exit /b 2
)

git rev-parse --show-toplevel >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Run this script from inside the formal_disk4_solver Git repository.
  exit /b 3
)

echo ============================================================
echo Formal Disk4 1.7.1 deprecated-file cleanup
echo ============================================================
echo The following tracked legacy wrappers and duplicate configs will be removed:
echo.
echo   config/cases/double-cycle-6/
echo   create_double_cycle_case.bat
echo   scripts/create_double_cycle_case.ps1
echo   run_c3_pipeline.bat
echo   run_c4_pipeline.bat
echo   run_double_cycle_6_pipeline.bat
echo   run_k4_pipeline.bat
echo   run_k4_minus_arc_pipeline.bat
echo   run_k4_minus_point_pipeline.bat
echo   run_pizza3.bat
echo   run_pizza3_geometry.bat
echo   run_pizza3_pipeline.bat
echo   run_pizza3_visualizer.bat
echo   run_pizza4.bat
echo   run_pizza4_geometry.bat
echo   run_pizza4_pipeline.bat
echo   run_pizza4_visualizer.bat
echo   scripts/run_pizza3_pipeline.ps1
echo   scripts/run_pizza4_pipeline.ps1
echo   config/pizza3.json
echo   config/pizza3_geometry.json
echo   config/pizza3_visualizer.json
echo   config/pizza4.json
echo   config/pizza4_geometry.json
echo   config/pizza4_visualizer.json
echo.
echo Generic tools such as run_case.bat, run_cycle_case.bat,
echo run_cycle_suite.bat, setup.bat and run_tests.bat are preserved.
echo.

git rm -r --ignore-unmatch -- config/cases/double-cycle-6
if errorlevel 1 goto :failed

git rm --ignore-unmatch -- ^
  create_double_cycle_case.bat ^
  scripts/create_double_cycle_case.ps1 ^
  run_c3_pipeline.bat ^
  run_c4_pipeline.bat ^
  run_double_cycle_6_pipeline.bat ^
  run_k4_pipeline.bat ^
  run_k4_minus_arc_pipeline.bat ^
  run_k4_minus_point_pipeline.bat ^
  run_pizza3.bat ^
  run_pizza3_geometry.bat ^
  run_pizza3_pipeline.bat ^
  run_pizza3_visualizer.bat ^
  run_pizza4.bat ^
  run_pizza4_geometry.bat ^
  run_pizza4_pipeline.bat ^
  run_pizza4_visualizer.bat ^
  scripts/run_pizza3_pipeline.ps1 ^
  scripts/run_pizza4_pipeline.ps1 ^
  config/pizza3.json ^
  config/pizza3_geometry.json ^
  config/pizza3_visualizer.json ^
  config/pizza4.json ^
  config/pizza4_geometry.json ^
  config/pizza4_visualizer.json
if errorlevel 1 goto :failed

echo.
echo [DONE] Deprecated files are staged for deletion.
echo [INFO] Review the staged changes below, then commit them when ready.
echo.
git status --short
exit /b 0

:failed
echo.
echo [ERROR] git rm failed. No commit was created.
git status --short
exit /b 4
