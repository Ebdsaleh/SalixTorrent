@echo off
setlocal EnableExtensions

cd /d "%~dp0\..\.."

REM Validate the optional SalixORM-backed translation-memory adapter.

python -c "import salixorm; print('SalixORM', salixorm.__version__)"
if errorlevel 1 (
    echo.
    echo SalixORM v0.2.0 or newer is required for translation-memory validation.
    echo From the SalixTorrent virtual environment, install the sibling checkout with:
    echo   python -m pip install -e ..\SalixORM
    exit /b 12
)

python tools\localization\build_locales.py --salixorm-memory-check
if errorlevel 1 exit /b %errorlevel%

echo.
echo SalixORM translation-memory storage adapter: OK
