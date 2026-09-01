@echo off
setlocal

cd /d "%~dp0\..\.."

if "%VIRTUAL_ENV%"=="" (
    echo ERROR: Activate the SalixTorrent .venv before running Stage 8A review tooling.
    exit /b 1
)

echo ============================================================
echo  SalixTorrent Phase 12 Stage 8A - Translation Review Audit
echo ============================================================
echo Python: %VIRTUAL_ENV%\Scripts\python.exe
python --version
if errorlevel 1 exit /b %errorlevel%

echo.
echo [1/4] Canonical extraction and manifests...
python tools\localization\build_locales.py --extract
if errorlevel 1 exit /b %errorlevel%

echo.
echo [2/4] Deterministic extraction drift check...
python tools\localization\build_locales.py --check
if errorlevel 1 exit /b %errorlevel%

echo.
echo [3/4] Translation review status...
python tools\localization\build_locales.py --review-report
if errorlevel 1 exit /b %errorlevel%

echo.
echo [4/4] Stage 8A review/provenance validation...
python tools\localization\build_locales.py --stage8-check
if errorlevel 1 exit /b %errorlevel%

echo.
echo Stage 8A translation review infrastructure: OK
exit /b 0
