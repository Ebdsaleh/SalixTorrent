# PyInstaller build description for SalixTorrent desktop/CLI releases.
#
# SALIX_BUILD_TARGET=gui (default) -> windowed SalixTorrent executable
# SALIX_BUILD_TARGET=cli           -> console SalixTorrentCLI executable

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent
TARGET = str(os.environ.get("SALIX_BUILD_TARGET", "gui")).strip().lower()
if TARGET not in {"gui", "cli"}:
    raise SystemExit("SALIX_BUILD_TARGET must be 'gui' or 'cli'.")

entry_script = ROOT / ("cli_main.py" if TARGET == "cli" else "main.py")
exe_name = "SalixTorrentCLI" if TARGET == "cli" else "SalixTorrent"
console = TARGET == "cli"

datas = [
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "LICENSE"), "."),
    # Phase 12 locale packs are immutable runtime resources. They are bundled
    # into every frozen build so language selection never needs the network.
    (str(ROOT / "app" / "localization" / "locales"), "app/localization/locales"),
    # Locale-neutral semantic Help/Glossary topology and canonical authoring text.
    # Runtime locale catalogs overlay these stable IDs entirely offline.
    (str(ROOT / "app" / "localization" / "content"), "app/localization/content"),
]
binaries = []
hiddenimports = []

# Dear PyGui includes a native extension; aiohttp and Pillow can also carry
# dynamic/data dependencies that a static import walk does not always expose.
for package in ("dearpygui", "aiohttp", "PIL", "pystray", "AppKit", "Quartz"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception:
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

analysis = Analysis(
    [str(entry_script)],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
