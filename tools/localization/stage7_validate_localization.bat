@echo off
setlocal EnableExtensions

cd /d "%~dp0\..\.."

if /I not "%OS%"=="Windows_NT" (
    echo ERROR: This helper is intended for Windows Command Prompt.
    exit /b 1
)

if not defined VIRTUAL_ENV (
    echo ERROR: Activate the SalixTorrent virtual environment first.
    echo.
    echo     .venv\Scripts\activate
    echo.
    exit /b 1
)

set "PYTHON=%VIRTUAL_ENV%\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo ERROR: Python was not found at:
    echo     %PYTHON%
    exit /b 1
)

echo ============================================================
echo  SalixTorrent Phase 12 Stage 7 - Localization Hardening
echo ============================================================
echo Python: %PYTHON%
"%PYTHON%" --version

echo.
echo [1/3] Regenerating canonical catalogs and manifests...
"%PYTHON%" tools\localization\build_locales.py --extract || exit /b 1

echo.
echo [2/3] Verifying deterministic extraction state...
"%PYTHON%" tools\localization\build_locales.py --check || exit /b 1

echo.
echo [3/3] Running offline Stage 7 hardening checks...
"%PYTHON%" tools\localization\build_locales.py --stage7-check || exit /b 1

echo.
echo Stage 7 localization hardening: OK
exit /b 0
