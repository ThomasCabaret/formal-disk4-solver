@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: create_double_cycle_case.bat N [--force]
  echo Example: create_double_cycle_case.bat 8
  pause
  exit /b 2
)
set "FORCE_ARG="
if /I "%~2"=="--force" set "FORCE_ARG=-Force"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\create_double_cycle_case.ps1" -Size %~1 %FORCE_ARG%
set "EXITCODE=%ERRORLEVEL%"
echo.
echo [INFO] Exit code: %EXITCODE%
pause
exit /b %EXITCODE%
