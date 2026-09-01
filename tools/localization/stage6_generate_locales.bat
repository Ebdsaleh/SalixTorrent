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

if /I "%~1"=="--run" goto :run
if /I "%~1"=="--probe" goto :probe
if not "%~1"=="" goto :usage

echo ============================================================
echo  SalixTorrent Phase 12 Stage 6 - Locale Generation Preflight
echo ============================================================
echo Python: %PYTHON%
"%PYTHON%" --version
echo.

echo [1/4] Canonical extraction...
"%PYTHON%" tools\localization\build_locales.py --extract || exit /b 1

echo.
echo [2/4] Extraction drift check...
"%PYTHON%" tools\localization\build_locales.py --check || exit /b 1

echo.
echo [3/4] Translation plan and locale status...
"%PYTHON%" tools\localization\build_locales.py --dry-run || exit /b 1
"%PYTHON%" tools\localization\build_locales.py --status || exit /b 1

echo.
echo [4/4] Google development setup doctor ^(local only^) ...
"%PYTHON%" tools\localization\build_locales.py --doctor
set "DOCTOR_RC=%ERRORLEVEL%"

echo.
if not "%DOCTOR_RC%"=="0" (
    echo Google setup is not ready yet. This is expected before first configuration.
    echo.
    echo 1. Install development-only Python dependencies:
    echo      python -m pip install -r requirements-localization.txt
    echo.
    echo 2. Install/initialize Google Cloud CLI, enable Cloud Translation,
    echo    create Application Default Credentials, and set your project for
    echo    this Command Prompt, for example:
    echo      gcloud init
    echo      gcloud services enable translate.googleapis.com --project YOUR_PROJECT_ID
    echo      gcloud auth application-default login
    echo      set SALIX_T_GOOGLE_PROJECT=YOUR_PROJECT_ID
    echo.
    echo 3. Re-run this preflight, then optionally test one tiny API call with:
    echo      tools\localization\stage6_generate_locales.bat --probe
    echo.
    echo 4. Generate all initial locale packs with:
    echo      tools\localization\stage6_generate_locales.bat --run
    exit /b %DOCTOR_RC%
)

echo Google setup looks ready.
echo Optional authenticated probe:
echo     tools\localization\stage6_generate_locales.bat --probe
echo.
echo Generate all four initial locale packs:
echo     tools\localization\stage6_generate_locales.bat --run
exit /b 0

:probe
echo ============================================================
echo  Stage 6 authenticated Translation API probe
echo ============================================================
"%PYTHON%" tools\localization\build_locales.py --doctor --probe
exit /b %ERRORLEVEL%

:run
echo ============================================================
echo  SalixTorrent Phase 12 Stage 6 - Generate Initial Locales
echo ============================================================
echo.
echo This command performs billable Google Cloud Translation requests for
echo only strings that are not already valid in the translation cache.
echo No credentials are written into SalixTorrent or the locale packs.
echo.
"%PYTHON%" -c "from google.cloud import translate_v3; import google.auth" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Development-only Google translation dependencies are missing.
    echo Run:
    echo     python -m pip install -r requirements-localization.txt
    exit /b 1
)

"%PYTHON%" tools\localization\build_locales.py --check || exit /b 1
"%PYTHON%" tools\localization\build_locales.py --doctor || exit /b 1
"%PYTHON%" tools\localization\build_locales.py --generate-initial
if errorlevel 1 exit /b %ERRORLEVEL%

echo.
echo Stage 6 generation completed. Final checks:
"%PYTHON%" tools\localization\build_locales.py --check || exit /b 1
"%PYTHON%" tools\localization\build_locales.py --validate --strict || exit /b 1
"%PYTHON%" tools\localization\build_locales.py --status || exit /b 1
exit /b 0

:usage
echo Usage:
echo     tools\localization\stage6_generate_locales.bat
echo         Safe local preflight; no Translation API calls.
echo.
echo     tools\localization\stage6_generate_locales.bat --probe
echo         One tiny authenticated API request to verify access.
echo.
echo     tools\localization\stage6_generate_locales.bat --run
echo         Generate all initial locale packs and strict-validate them.
exit /b 2
