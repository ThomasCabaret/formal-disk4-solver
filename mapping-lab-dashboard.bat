@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
py.exe -m formal_disk4.mapping_lab.dashboard --input output\mapping_lab\wheel-6\generations.jsonl
if errorlevel 1 pause
