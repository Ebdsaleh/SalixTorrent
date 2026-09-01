@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem SalixTorrent Windows release build script.
rem Run this from an already activated project virtual environment:
rem     .venv\Scripts\activate
rem     packaging\build_windows.bat

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
pushd "%ROOT%" >nul || goto :fatal_root

if /I not "%OS%"=="Windows_NT" (
    call :fail "Phase 10 Windows artifacts must be built on Windows."
    goto :eof
)

if not defined VIRTUAL_ENV (
    echo.
    echo ERROR: No activated Python virtual environment was detected.
    echo.
    echo Activate your project environment first, for example:
    echo     .venv\Scripts\activate
    echo     packaging\build_windows.bat
    echo.
    echo Nothing has been installed or built by this script.
    goto :pause_fail
)

set "PYTHON=%VIRTUAL_ENV%\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo.
    echo ERROR: VIRTUAL_ENV is set, but this Python was not found:
    echo     %PYTHON%
    goto :pause_fail
)

set "SKIP_DEPS=0"
set "SKIP_TESTS=0"
set "SKIP_INSTALLER=0"

:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--skip-deps" (
    set "SKIP_DEPS=1"
) else if /I "%~1"=="--skip-tests" (
    set "SKIP_TESTS=1"
) else if /I "%~1"=="--skip-installer" (
    set "SKIP_INSTALLER=1"
) else if /I "%~1"=="-h" (
    goto :usage
) else if /I "%~1"=="--help" (
    goto :usage
) else (
    echo ERROR: Unknown option: %~1
    goto :usage_fail
)
shift
goto :parse_args

:args_done
echo.
echo ============================================================
echo  SalixTorrent Windows Build
echo ============================================================
echo Project root : %ROOT%
echo Virtual env  : %VIRTUAL_ENV%
echo Python       : %PYTHON%
"%PYTHON%" --version || goto :python_fail
"%PYTHON%" -m pip --version || goto :pip_fail
echo ============================================================
echo.

set "VERSION_FILE=%TEMP%\salix_version_%RANDOM%_%RANDOM%.txt"
"%PYTHON%" -c "from app.version import APP_VERSION; print(APP_VERSION)" > "%VERSION_FILE%"
if errorlevel 1 (
    if exist "%VERSION_FILE%" del /q "%VERSION_FILE%" >nul 2>&1
    call :fail "Could not execute app.version.APP_VERSION lookup."
    goto :eof
)
set "VERSION="
set /p "VERSION="<"%VERSION_FILE%"
del /q "%VERSION_FILE%" >nul 2>&1
if not defined VERSION (
    call :fail "Could not read app.version.APP_VERSION."
    goto :eof
)
echo SalixTorrent version: %VERSION%
echo.

if "%SKIP_DEPS%"=="0" (
    echo [1/6] Installing build/runtime requirements into THIS virtual environment...
    "%PYTHON%" -m pip install -r requirements.txt -r requirements-build.txt
    if errorlevel 1 (
        call :fail "Dependency installation failed."
        goto :eof
    )
) else (
    echo [1/6] Dependency installation skipped.
)

echo.
if "%SKIP_TESTS%"=="0" (
    echo [2/6] Running test suite...
    "%PYTHON%" -m unittest discover -v
    if errorlevel 1 (
        call :fail "Tests failed; refusing to package."
        goto :eof
    )
) else (
    echo [2/6] Tests skipped.
)

set "BUILD_ROOT=%ROOT%\build\phase10"
set "DIST_ROOT=%ROOT%\dist\phase10"
set "STANDALONE_ROOT=%DIST_ROOT%\standalone"
set "PORTABLE_ROOT=%DIST_ROOT%\portable\SalixTorrent"
set "INSTALLER_ROOT=%DIST_ROOT%\installer"

if exist "%BUILD_ROOT%" rmdir /s /q "%BUILD_ROOT%"
if exist "%DIST_ROOT%" rmdir /s /q "%DIST_ROOT%"
mkdir "%STANDALONE_ROOT%" || goto :mkdir_fail

echo.
echo [3/6] Building standalone desktop executable...
set "SALIX_BUILD_TARGET=gui"
"%PYTHON%" -m PyInstaller --noconfirm --clean --distpath "%STANDALONE_ROOT%" --workpath "%BUILD_ROOT%\gui" packaging\SalixTorrent.spec
if errorlevel 1 (
    set "SALIX_BUILD_TARGET="
    call :fail "SalixTorrent.exe build failed."
    goto :eof
)

echo.
echo [4/6] Building standalone console executable...
set "SALIX_BUILD_TARGET=cli"
"%PYTHON%" -m PyInstaller --noconfirm --clean --distpath "%STANDALONE_ROOT%" --workpath "%BUILD_ROOT%\cli" packaging\SalixTorrent.spec
if errorlevel 1 (
    set "SALIX_BUILD_TARGET="
    call :fail "SalixTorrentCLI.exe build failed."
    goto :eof
)
set "SALIX_BUILD_TARGET="

set "GUI_EXE=%STANDALONE_ROOT%\SalixTorrent.exe"
set "CLI_EXE=%STANDALONE_ROOT%\SalixTorrentCLI.exe"
if not exist "%GUI_EXE%" (
    call :fail "Missing SalixTorrent.exe after build."
    goto :eof
)
if not exist "%CLI_EXE%" (
    call :fail "Missing SalixTorrentCLI.exe after build."
    goto :eof
)

set "CLI_VERSION_FILE=%TEMP%\salix_cli_version_%RANDOM%_%RANDOM%.txt"
"%CLI_EXE%" --version > "%CLI_VERSION_FILE%" 2>&1
if errorlevel 1 (
    if exist "%CLI_VERSION_FILE%" type "%CLI_VERSION_FILE%"
    if exist "%CLI_VERSION_FILE%" del /q "%CLI_VERSION_FILE%" >nul 2>&1
    call :fail "Frozen CLI --version smoke test failed."
    goto :eof
)
if not exist "%CLI_VERSION_FILE%" (
    call :fail "Frozen CLI --version smoke test produced no output."
    goto :eof
)
for %%I in ("%CLI_VERSION_FILE%") do if %%~zI EQU 0 (
    del /q "%CLI_VERSION_FILE%" >nul 2>&1
    call :fail "Frozen CLI --version smoke test produced no output."
    goto :eof
)
findstr /C:"%VERSION%" "%CLI_VERSION_FILE%" >nul
if errorlevel 1 (
    type "%CLI_VERSION_FILE%"
    del /q "%CLI_VERSION_FILE%" >nul 2>&1
    call :fail "Frozen CLI --version smoke test did not report the expected version."
    goto :eof
)
del /q "%CLI_VERSION_FILE%" >nul 2>&1

echo.
echo [5/6] Creating portable bundle...
mkdir "%PORTABLE_ROOT%" || goto :mkdir_fail
copy /y "%GUI_EXE%" "%PORTABLE_ROOT%\SalixTorrent.exe" >nul || goto :copy_fail
copy /y "%CLI_EXE%" "%PORTABLE_ROOT%\SalixTorrentCLI.exe" >nul || goto :copy_fail
copy /y "%ROOT%\README.md" "%PORTABLE_ROOT%\README.md" >nul || goto :copy_fail
copy /y "%ROOT%\LICENSE" "%PORTABLE_ROOT%\LICENSE" >nul || goto :copy_fail

>"%PORTABLE_ROOT%\portable.flag" echo SalixTorrent portable mode marker.
>>"%PORTABLE_ROOT%\portable.flag" echo Keep this file beside SalixTorrent.exe to store application state in .\data and default downloads in .\downloads.

set "PORTABLE_ZIP=%DIST_ROOT%\SalixTorrent-%VERSION%-windows-x64-portable.zip"
"%PYTHON%" -c "from pathlib import Path; import zipfile; root=Path(r'''%PORTABLE_ROOT%'''); out=Path(r'''%PORTABLE_ZIP%'''); z=zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED); [z.write(p, p.relative_to(root)) for p in root.rglob('*') if p.is_file()]; z.close()"
if errorlevel 1 (
    call :fail "Portable ZIP creation failed."
    goto :eof
)

if "%SKIP_INSTALLER%"=="1" (
    echo.
    echo [6/6] Installer skipped.
    goto :success
)

echo.
echo [6/6] Building Inno Setup installer...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
if not defined ISCC (
    for /f "delims=" %%I in ('where /r "%SystemDrive%\Users" ISCC.exe 2^>nul') do (
        if not defined ISCC set "ISCC=%%I"
    )
)
if defined ISCC echo Inno Setup   : %ISCC%

if not defined ISCC (
    echo.
    echo ERROR: Inno Setup 6 ^(ISCC.exe^) was not found.
    echo The standalone executables and portable ZIP were built successfully.
    echo Install Inno Setup 6, or rerun with:
    echo     packaging\build_windows.bat --skip-installer
    goto :pause_fail
)

mkdir "%INSTALLER_ROOT%" 2>nul
"%ISCC%" "/DMyAppVersion=%VERSION%" "/DBuildDir=%STANDALONE_ROOT%" "/O%INSTALLER_ROOT%" packaging\windows\SalixTorrent.iss
if errorlevel 1 (
    call :fail "Inno Setup compilation failed."
    goto :eof
)

goto :success

:success
echo.
echo ============================================================
echo  SalixTorrent Windows artifacts complete

echo  Standalone GUI : %GUI_EXE%
echo  Standalone CLI : %CLI_EXE%
echo  Portable ZIP   : %PORTABLE_ZIP%
if "%SKIP_INSTALLER%"=="0" echo  Installer dir  : %INSTALLER_ROOT%
echo ============================================================
echo.
popd
exit /b 0

:usage
echo Usage: packaging\build_windows.bat [options]
echo.
echo Options:
echo   --skip-deps       Do not install requirements.
echo   --skip-tests      Do not run the test suite.
echo   --skip-installer  Build executables and portable ZIP only.
echo   --help            Show this help.
popd
exit /b 0

:usage_fail
call :usage
exit /b 2

:python_fail
call :fail "The virtual environment Python could not be executed."
goto :eof

:pip_fail
call :fail "pip is not available in the activated virtual environment."
goto :eof

:mkdir_fail
call :fail "Could not create a build output directory."
goto :eof

:copy_fail
call :fail "Could not copy a portable-bundle file."
goto :eof

:fatal_root
echo ERROR: Could not enter the SalixTorrent project root.
goto :pause_fail_no_popd

:fail
echo.
echo ERROR: %~1
echo.
goto :pause_fail

:pause_fail
echo Build stopped. The window will remain open so you can read the error.
pause
popd
exit /b 1

:pause_fail_no_popd
echo Build stopped. The window will remain open so you can read the error.
pause
exit /b 1
