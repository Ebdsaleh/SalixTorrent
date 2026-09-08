@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

rem Tranche-specific sequence lives in tools\validate_tranche.py
rem Complete report: %USERPROFILE%\Desktop\console_output.txt
"%PYTHON%" tools\validate_tranche.py
set "RC=%ERRORLEVEL%"

exit /b %RC%
