"""Transfer/session persistence contracts and deterministic JSON backend.

The desktop transfer queue historically lives in ``session.json``.  This
module moves that durable state behind a small storage contract while keeping
the JSON representation as the default/reference backend.  Alternative
backends therefore do not leak storage technology into ``TorrentManager``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable


CURRENT_SESSION_STATE_VERSION = 9
SUPPORTED_SESSION_STATE_VERSIONS = tuple(range(1, CURRENT_SESSION_STATE_VERSION + 1))


class SessionStateStoreError(RuntimeError):
    """Raised when a session-state backend cannot safely continue."""


@runtime_checkable
class SessionStateStore(Protocol):
    """Storage boundary used by ``TorrentManager`` for the desktop queue."""

    @property
    def backend(self) -> str:
        ...

    @property
    def location(self) -> str:
        ...

    def load(self) -> dict | None:
        """Return a persisted session snapshot, or ``None`` when absent."""

    def save(self, snapshot: Mapping[str, object]) -> None:
        """Persist one complete coherent session snapshot."""


def _valid_snapshot_shape(snapshot: object) -> bool:
    return isinstance(snapshot, dict) and isinstance(snapshot.get("torrents", []), list)


class JsonSessionStateStore:
    """Atomic file-backed implementation preserving historical JSON imports."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path).expanduser().resolve()

    @property
    def backend(self) -> str:
        return "json"

    @property
    def location(self) -> str:
        return str(self.path)

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            # Report the historical read failure while leaving the JSON backend
            # healthy so a later valid queue save can replace malformed state.
            raise SessionStateStoreError(
                f"Could not read JSON session state at {self.path}: {exc}"
            ) from exc
        return dict(raw) if _valid_snapshot_shape(raw) else None

    def save(self, snapshot: Mapping[str, object]) -> None:
        data = dict(snapshot)
        if not _valid_snapshot_shape(data):
            raise SessionStateStoreError(
                "Session snapshot must contain a torrents list"
            )
        if data.get("version") != CURRENT_SESSION_STATE_VERSION:
            raise SessionStateStoreError(
                "New session snapshots must use the current session-state version"
            )

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp_path, self.path)
        except (OSError, TypeError, ValueError) as exc:
            raise SessionStateStoreError(
                f"Could not persist JSON session state at {self.path}: {exc}"
            ) from exc


class FallbackSessionStateStore:
    """Use a primary backend with read-only historical JSON bootstrap.

    The fallback is consulted only while the primary backend has no snapshot.
    Saves target the primary backend only.  An opt-in SalixORM backend can thus
    restore an existing ``session.json`` and naturally migrate it on the next
    normal save without deleting or dual-writing the legacy artifact.
    """

    def __init__(self, primary: SessionStateStore, fallback: SessionStateStore) -> None:
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

    def save(self, snapshot: Mapping[str, object]) -> None:
        self.primary.save(snapshot)
