"""SalixTorrent runtime-path composition over the reusable path policy."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict

from app.runtime.paths import RuntimePathSpec, RuntimePaths


PORTABLE_FLAG_NAME = "portable.flag"
PORTABLE_ENV = "SALIX_T_PORTABLE"
STATE_DIR_ENV = "SALIX_T_STATE_DIR"
DOWNLOAD_DIR_ENV = "SALIX_T_DOWNLOAD_DIR"

_PATH_SPEC = RuntimePathSpec(
    app_name="SalixTorrent",
    portable_flag_name=PORTABLE_FLAG_NAME,
    portable_env=PORTABLE_ENV,
    state_dir_env=STATE_DIR_ENV,
    download_dir_env=DOWNLOAD_DIR_ENV,
)


def is_frozen() -> bool:
    """Return whether Python is executing from a freezer/bundler."""
    return bool(getattr(sys, "frozen", False))


def bundle_directory() -> Path:
    """Return the read-only bundle/project root containing application data."""
    return Path(__file__).resolve().parents[2]


def application_directory() -> Path:
    """Return the directory containing the user-launched application."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return bundle_directory()


def _paths() -> RuntimePaths:
    return RuntimePaths(
        _PATH_SPEC,
        bundle_directory=bundle_directory(),
        application_directory=application_directory(),
    )


def portable_flag_path() -> Path:
    return _paths().portable_flag_path()


def portable_mode() -> bool:
    """Return whether state/download defaults should stay beside the app."""
    return _paths().portable_mode()


def state_directory() -> Path:
    """Return SalixTorrent's writable state directory."""
    return _paths().state_directory()


def default_download_directory() -> Path:
    """Return the default payload folder for a new installation/profile."""
    return _paths().default_download_directory()


def resource_path(relative_path: os.PathLike[str] | str) -> Path:
    """Resolve a bundled/read-only resource without depending on cwd."""
    return _paths().resource_path(relative_path)


def runtime_snapshot() -> Dict[str, object]:
    """Return small diagnostics suitable for Help > Diagnostics/tests."""
    return _paths().snapshot(frozen=is_frozen())
