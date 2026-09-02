@echo off
setlocal EnableExtensions

cd /d "%~dp0\..\.."

echo ============================================================
echo  SalixTorrent Translation Provider/Memory Audit
echo ============================================================

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python was not found on PATH.
    exit /b 1
)

echo Python:
where python
python --version
echo.

echo [1/4] Canonical extraction and manifests...
python tools\localization\build_locales.py --extract
if errorlevel 1 exit /b %errorlevel%
echo.

echo [2/4] Deterministic extraction drift check...
python tools\localization\build_locales.py --check
if errorlevel 1 exit /b %errorlevel%
echo.

echo [3/4] Provider-neutral translation memory bootstrap...
python tools\localization\build_locales.py --memory-bootstrap --memory-status --providers
if errorlevel 1 exit /b %errorlevel%
echo.

echo [4/4] Provider/memory validation...
python tools\localization\build_locales.py --memory-check
if errorlevel 1 exit /b %errorlevel%
echo.

echo Provider-neutral translation memory: OK
exit /b 0
