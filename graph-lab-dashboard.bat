@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
py.exe -m formal_disk4.graph_lab.dashboard --input output\graph_lab\up-to-13\training_metrics.jsonl
if errorlevel 1 pause
