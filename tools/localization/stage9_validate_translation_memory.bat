@echo off
setlocal

echo ============================================================
echo  SalixTorrent Phase 12 Stage 9 - Provider/Memory Audit
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

echo [4/4] Stage 9 provider/memory validation...
python tools\localization\build_locales.py --stage9-check
if errorlevel 1 exit /b %errorlevel%
echo.

echo Stage 9 provider-neutral translation memory: OK
exit /b 0
