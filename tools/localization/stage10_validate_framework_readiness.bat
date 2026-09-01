@echo off
setlocal

echo ============================================================
echo  SalixTorrent Phase 12 Stage 10 - Framework Readiness Audit
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

echo [3/4] Framework extraction map...
python tools\localization\build_locales.py --framework-report
if errorlevel 1 exit /b %errorlevel%
echo.

echo [4/4] Framework/provider-memory boundary validation...
python tools\localization\build_locales.py --stage10-check
if errorlevel 1 exit /b %errorlevel%
echo.

echo Stage 10 framework extraction readiness: OK
exit /b 0
