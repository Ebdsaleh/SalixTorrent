"""Reusable runtime-path policy independent of one application name."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def env_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimePathSpec:
    """Application-specific names consumed by generic path resolution."""

    app_name: str
    portable_flag_name: str = "portable.flag"
    portable_env: str = ""
    state_dir_env: str = ""
    download_dir_env: str = ""
    portable_state_directory: str = "data"
    portable_download_directory: str = "downloads"

    def __post_init__(self):
        if not str(self.app_name or "").strip():
            raise ValueError("runtime path app_name must not be empty")


class RuntimePaths:
    """Resolve application, state, download and resource paths explicitly."""

    def __init__(
        self,
        spec: RuntimePathSpec,
        *,
        bundle_directory: Path,
        application_directory: Path,
        environ: Mapping[str, str] | None = None,
        os_name: str | None = None,
        platform: str | None = None,
        home: Path | None = None,
    ):
        if not isinstance(spec, RuntimePathSpec):
            raise TypeError("spec must be a RuntimePathSpec")
        self.spec = spec
        self.bundle_directory = Path(os.path.abspath(os.fspath(bundle_directory)))
        self.application_directory = Path(
            os.path.abspath(os.fspath(application_directory))
        )
        self.environ = environ if environ is not None else os.environ
        self.os_name = str(os_name if os_name is not None else os.name)
        self.platform = str(platform if platform is not None else sys.platform)
        self.home = Path(home) if home is not None else Path.home()

    def _override(self, name: str) -> Path | None:
        if not name:
            return None
        value = self.environ.get(name)
        if not value:
            return None
        return Path(value).expanduser().resolve()

    def portable_flag_path(self) -> Path:
        return self.application_directory / self.spec.portable_flag_name

    def portable_mode(self) -> bool:
        if self.spec.portable_env and env_truthy(
            self.environ.get(self.spec.portable_env)
        ):
            return True
        try:
            return self.portable_flag_path().is_file()
        except OSError:
            return False

    def state_directory(self) -> Path:
        override = self._override(self.spec.state_dir_env)
        if override is not None:
            return override
        if self.portable_mode():
            return self.application_directory / self.spec.portable_state_directory

        app_name = self.spec.app_name
        if self.os_name == "nt":
            base = self.environ.get("LOCALAPPDATA")
            if base:
                return Path(base) / app_name
            return self.home / "AppData" / "Local" / app_name
        if self.platform == "darwin":
            return self.home / "Library" / "Application Support" / app_name

        xdg_state_home = self.environ.get("XDG_STATE_HOME")
        if xdg_state_home:
            return Path(xdg_state_home) / app_name
        return self.home / ".local" / "state" / app_name

    def default_download_directory(self) -> Path:
        override = self._override(self.spec.download_dir_env)
        if override is not None:
            return override
        if self.portable_mode():
            return self.application_directory / self.spec.portable_download_directory
        return self.home / "Downloads" / self.spec.app_name

    def resource_path(self, relative_path: os.PathLike[str] | str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute():
            return relative
        external = self.application_directory / relative
        try:
            if external.exists():
                return external
        except OSError:
            pass
        return self.bundle_directory / relative

    def snapshot(self, *, frozen: bool) -> dict[str, object]:
        return {
            "frozen": bool(frozen),
            "portable": self.portable_mode(),
            "application_directory": str(self.application_directory),
            "bundle_directory": str(self.bundle_directory),
            "state_directory": str(self.state_directory()),
            "default_download_directory": str(self.default_download_directory()),
        }
