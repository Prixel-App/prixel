@echo off
cd /d "%~dp0"
python -m archiviste %*
if errorlevel 1 pause
