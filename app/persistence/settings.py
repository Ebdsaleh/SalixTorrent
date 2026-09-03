"""Application-settings persistence contracts and deterministic JSON backend.

The normal SalixTorrent runtime still uses the long-standing ``settings.json``
file by default.  This module puts that behavior behind a small storage
contract so an alternative durable store can be exercised without coupling
``TorrentManager`` to a particular persistence technology.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable


class AppSettingsStoreError(RuntimeError):
    """Raised when an application-settings backend cannot safely continue."""


@runtime_checkable
class AppSettingsStore(Protocol):
    """Storage boundary used by ``TorrentManager`` for application settings."""

    @property
    def backend(self) -> str:
        ...

    @property
    def location(self) -> str:
        ...

    def load(self) -> dict | None:
        """Return persisted settings, or ``None`` when no state exists yet."""

    def save(self, settings: Mapping[str, object]) -> None:
        """Persist a complete normalized application-settings snapshot."""


class JsonAppSettingsStore:
    """Atomic file-backed implementation preserving the historical JSON format."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path).expanduser().resolve()

    @property
    def backend(self) -> str:
        return "json"

    @property
    def location(self) -> str:
        return str(self.path)

    def load(self) -> dict | None:
        try:
            if not self.path.exists():
                return None
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # Historical SalixTorrent behavior is to use defaults when the JSON
            # settings file is unavailable or malformed.
            return None
        return dict(raw) if isinstance(raw, dict) else None

    def save(self, settings: Mapping[str, object]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(dict(settings), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp_path, self.path)
        except (OSError, TypeError, ValueError) as exc:
            raise AppSettingsStoreError(
                f"Could not persist JSON application settings at {self.path}: {exc}"
            ) from exc


class FallbackAppSettingsStore:
    """Use a primary backend while retaining read-only bootstrap compatibility.

    The fallback is consulted only while the primary store has no settings.
    Saves always target the primary backend.  This lets an opt-in SalixORM
    backend import an existing ``settings.json`` snapshot naturally on the
    first user settings change without modifying or deleting the legacy file.
    """

    def __init__(
        self,
        primary: AppSettingsStore,
        fallback: AppSettingsStore,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    @property
    def backend(self) -> str:
        return self.primary.backend

    @property
    def location(self) -> str:
        return self.primary.location

    def load(self) -> dict | None:
        value = self.primary.load()
        if value is not None:
            return value
        return self.fallback.load()

    def save(self, settings: Mapping[str, object]) -> None:
        self.primary.save(settings)
