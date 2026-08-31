param(
    [string]$Python = "python",
    [switch]$SkipDependencyInstall,
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if ($env:OS -ne "Windows_NT") {
    throw "Phase 10 Windows artifacts must be built on Windows. PyInstaller does not cross-build Windows executables."
}

$Version = (& $Python -c "from app.version import APP_VERSION; print(APP_VERSION)").Trim()
if (-not $Version) { throw "Could not read app.version.APP_VERSION" }

if (-not $SkipDependencyInstall) {
    & $Python -m pip install -r requirements.txt -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
}

if (-not $SkipTests) {
    & $Python -m unittest discover -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; refusing to package." }
}

$BuildRoot = Join-Path $Root "build\phase10"
$DistRoot = Join-Path $Root "dist\phase10"
$StandaloneRoot = Join-Path $DistRoot "standalone"
$PortableRoot = Join-Path $DistRoot "portable\SalixTorrent"
$InstallerRoot = Join-Path $DistRoot "installer"

Remove-Item $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $DistRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item $StandaloneRoot -ItemType Directory -Force | Out-Null

Write-Host "Building standalone desktop executable..."
$env:SALIX_BUILD_TARGET = "gui"
& $Python -m PyInstaller --noconfirm --clean `
    --distpath $StandaloneRoot `
    --workpath (Join-Path $BuildRoot "gui") `
    packaging\SalixTorrent.spec
if ($LASTEXITCODE -ne 0) { throw "SalixTorrent.exe build failed." }

Write-Host "Building standalone console executable..."
$env:SALIX_BUILD_TARGET = "cli"
& $Python -m PyInstaller --noconfirm --clean `
    --distpath $StandaloneRoot `
    --workpath (Join-Path $BuildRoot "cli") `
    packaging\SalixTorrent.spec
if ($LASTEXITCODE -ne 0) { throw "SalixTorrentCLI.exe build failed." }
Remove-Item Env:SALIX_BUILD_TARGET -ErrorAction SilentlyContinue

$GuiExe = Join-Path $StandaloneRoot "SalixTorrent.exe"
$CliExe = Join-Path $StandaloneRoot "SalixTorrentCLI.exe"
if (-not (Test-Path $GuiExe)) { throw "Missing $GuiExe" }
if (-not (Test-Path $CliExe)) { throw "Missing $CliExe" }

# The console build gives us an observable smoke test without forcing a GUI
# window to remain open in CI/release scripts.
$ReportedVersion = (& $CliExe --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $ReportedVersion -notmatch [regex]::Escape($Version)) {
    throw "Frozen CLI --version smoke test failed: '$ReportedVersion'"
}

Write-Host "Creating portable bundle..."
New-Item $PortableRoot -ItemType Directory -Force | Out-Null
Copy-Item $GuiExe $PortableRoot
Copy-Item $CliExe $PortableRoot
Copy-Item (Join-Path $Root "README.md") $PortableRoot
Copy-Item (Join-Path $Root "LICENSE") $PortableRoot
Set-Content -Path (Join-Path $PortableRoot "portable.flag") -Value @"
SalixTorrent portable mode marker.
Keep this file beside SalixTorrent.exe to store application state in .\data and default downloads in .\downloads.
"@ -Encoding UTF8

$PortableZip = Join-Path $DistRoot "SalixTorrent-$Version-windows-x64-portable.zip"
Compress-Archive -Path (Join-Path $PortableRoot "*") -DestinationPath $PortableZip -CompressionLevel Optimal

if (-not $SkipInstaller) {
    $Candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        "ISCC.exe"
    ) | Where-Object { $_ -and (Get-Command $_ -ErrorAction SilentlyContinue) }

    if (-not $Candidates) {
        throw "Inno Setup 6 (ISCC.exe) was not found. Re-run with -SkipInstaller to build only standalone/portable artifacts."
    }

    New-Item $InstallerRoot -ItemType Directory -Force | Out-Null
    $Iscc = [string]$Candidates[0]
    & $Iscc "/DMyAppVersion=$Version" "/DBuildDir=$StandaloneRoot" "/O$InstallerRoot" packaging\windows\SalixTorrent.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }
}

Write-Host ""
Write-Host "Phase 10 Windows artifacts complete:"
Write-Host "  Standalone GUI: $GuiExe"
Write-Host "  Standalone CLI: $CliExe"
Write-Host "  Portable ZIP:   $PortableZip"
if (-not $SkipInstaller) {
    Write-Host "  Installer dir:  $InstallerRoot"
}
