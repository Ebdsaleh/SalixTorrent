"""Runtime/application path policy for source, installed and portable builds.

Phase 10 deliberately keeps three concepts separate:

* bundled resources belong to the application bundle and are read-only;
* installed application state belongs in the platform's per-user state area;
* portable state belongs beside the executable when ``portable.flag`` is present.

This keeps file/magnet shell launches independent of the process working
folder and gives PyInstaller one-file builds the same behavior as source runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict


PORTABLE_FLAG_NAME = "portable.flag"
PORTABLE_ENV = "SALIX_T_PORTABLE"
STATE_DIR_ENV = "SALIX_T_STATE_DIR"
DOWNLOAD_DIR_ENV = "SALIX_T_DOWNLOAD_DIR"


def _env_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_frozen() -> bool:
    """Return whether Python is executing from a freezer/bundler."""
    return bool(getattr(sys, "frozen", False))


def bundle_directory() -> Path:
    """Return the read-only bundle/project root containing application data.

    PyInstaller 4.3+ gives bundled modules a useful absolute ``__file__``.
    The module lives at ``app/engine/runtime_paths.py``, therefore two parents
    above ``app`` is the application root in both source and frozen builds.
    """
    return Path(__file__).resolve().parents[2]


def application_directory() -> Path:
    """Return the directory containing the user-launched application."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return bundle_directory()


def portable_flag_path() -> Path:
    return application_directory() / PORTABLE_FLAG_NAME


def portable_mode() -> bool:
    """Return whether state/download defaults should stay beside the app."""
    if _env_truthy(os.environ.get(PORTABLE_ENV)):
        return True
    try:
        return portable_flag_path().is_file()
    except OSError:
        return False


def state_directory() -> Path:
    """Return SalixTorrent's writable state directory."""
    override = os.environ.get(STATE_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()

    if portable_mode():
        return application_directory() / "data"

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "SalixTorrent"
        return Path.home() / "AppData" / "Local" / "SalixTorrent"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SalixTorrent"

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home) / "SalixTorrent"
    return Path.home() / ".local" / "state" / "SalixTorrent"


def default_download_directory() -> Path:
    """Return the default payload folder for a new installation/profile."""
    override = os.environ.get(DOWNLOAD_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()

    if portable_mode():
        return application_directory() / "downloads"

    # Do not use cwd here: Explorer file associations, Start Menu shortcuts and
    # URL protocol launches may start with unrelated working directories.
    downloads = Path.home() / "Downloads"
    return downloads / "SalixTorrent"


def resource_path(relative_path: os.PathLike[str] | str) -> Path:
    """Resolve a bundled/read-only resource without depending on cwd.

    External files beside the executable win when present. This lets a portable
    bundle carry README/LICENSE or future media next to the executable, while a
    one-file PyInstaller build can fall back to its extracted bundle contents.
    """
    relative = Path(relative_path)
    if relative.is_absolute():
        return relative

    external = application_directory() / relative
    try:
        if external.exists():
            return external
    except OSError:
        pass
    return bundle_directory() / relative


def runtime_snapshot() -> Dict[str, object]:
    """Return small diagnostics suitable for Help > Diagnostics/tests."""
    return {
        "frozen": is_frozen(),
        "portable": portable_mode(),
        "application_directory": str(application_directory()),
        "bundle_directory": str(bundle_directory()),
        "state_directory": str(state_directory()),
        "default_download_directory": str(default_download_directory()),
    }
