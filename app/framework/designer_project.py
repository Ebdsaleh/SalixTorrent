"""Provisional file ownership and save/load for designer documents.

The designer model already has immutable ``DesignerSnapshot`` documents,
command-based editing, ephemeral clipboard/selection state and optional preview
reconstruction.  This module adds the deliberately small persistence seam those
pieces need before a future RAD editor can own an on-disk document:

* a versioned JSON envelope around one ``DesignerSnapshot``;
* strict/deterministic parsing and serialization;
* explicit file ownership for one ``DesignerEditSession``;
* atomic save/save-as with dirty-state reconciliation only after success.

This is *not* a final application-project schema.  It deliberately stores no
callbacks, services, assets, runtime settings, selection/focus, clipboard,
undo/redo history or concrete GUI objects.  Code-first applications do not need
this module and may continue constructing framework ``Component`` trees
entirely in Python.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .designer import DesignerSnapshot
from .designer_editing import DesignerEditSession


DESIGNER_PROJECT_KIND = "salix-designer-project"
DESIGNER_PROJECT_VERSION = 1


class DesignerProjectFormatError(ValueError):
    """Raised when serialized designer-project content is not valid."""


@dataclass(frozen=True)
class DesignerProjectDocument:
    """Minimal versioned persistence envelope around one designer snapshot."""

    snapshot: DesignerSnapshot
    kind: str = DESIGNER_PROJECT_KIND
    version: int = DESIGNER_PROJECT_VERSION

    def __init__(
        self,
        snapshot: DesignerSnapshot,
        *,
        kind: object = DESIGNER_PROJECT_KIND,
        version: object = DESIGNER_PROJECT_VERSION,
    ):
        if not isinstance(snapshot, DesignerSnapshot):
            raise TypeError("designer project document requires DesignerSnapshot")
        if not isinstance(kind, str):
            raise TypeError("designer project kind must be text")
        resolved_kind = kind.strip()
        if resolved_kind != DESIGNER_PROJECT_KIND:
            raise DesignerProjectFormatError("designer project kind is invalid")
        if isinstance(version, bool) or not isinstance(version, int):
            raise TypeError("designer project version must be an integer")
        resolved_version = version
        if resolved_version != DESIGNER_PROJECT_VERSION:
            raise DesignerProjectFormatError(
                f"unsupported designer project version: {resolved_version}"
            )
        object.__setattr__(self, "snapshot", snapshot)
        object.__setattr__(self, "kind", resolved_kind)
        object.__setattr__(self, "version", resolved_version)

    def to_descriptor(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "version": self.version,
            "snapshot": self.snapshot.to_descriptor(),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """Return deterministic UTF-8-compatible JSON text.

        ``allow_nan=False`` keeps the on-disk format inside portable JSON even
        if malformed custom metadata somehow introduced a non-finite float.
        """

        return json.dumps(
            self.to_descriptor(),
            ensure_ascii=False,
            allow_nan=False,
            indent=indent,
            sort_keys=True,
        )

    @classmethod
    def from_descriptor(cls, descriptor: Mapping[str, object]) -> "DesignerProjectDocument":
        if not isinstance(descriptor, Mapping):
            raise TypeError("designer project descriptor must be a mapping")
        expected = {"kind", "version", "snapshot"}
        supplied = set(descriptor)
        missing = expected.difference(supplied)
        unexpected = supplied.difference(expected)
        if missing:
            raise DesignerProjectFormatError(
                "designer project descriptor is missing: " + ", ".join(sorted(missing))
            )
        if unexpected:
            raise DesignerProjectFormatError(
                "designer project descriptor has unexpected fields: "
                + ", ".join(sorted(str(key) for key in unexpected))
            )
        kind = descriptor.get("kind")
        if not isinstance(kind, str):
            raise TypeError("designer project kind must be text")
        if kind.strip() != DESIGNER_PROJECT_KIND:
            raise DesignerProjectFormatError("designer project kind is invalid")
        version = descriptor.get("version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise TypeError("designer project version must be an integer")
        resolved_version = version
        if resolved_version != DESIGNER_PROJECT_VERSION:
            raise DesignerProjectFormatError(
                f"unsupported designer project version: {resolved_version}"
            )
        snapshot = descriptor.get("snapshot")
        if not isinstance(snapshot, Mapping):
            raise DesignerProjectFormatError("designer project snapshot must be an object")
        try:
            restored = DesignerSnapshot.from_descriptor(snapshot)
        except (TypeError, ValueError, KeyError) as exc:
            raise DesignerProjectFormatError("designer project snapshot is invalid") from exc
        return cls(restored, kind=kind, version=resolved_version)

    @classmethod
    def from_json(cls, text: str) -> "DesignerProjectDocument":
        if not isinstance(text, str):
            raise TypeError("designer project JSON must be text")
        try:
            payload = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_object_keys,
                parse_constant=_reject_non_finite_json,
            )
        except (json.JSONDecodeError, DesignerProjectFormatError) as exc:
            if isinstance(exc, DesignerProjectFormatError):
                raise
            raise DesignerProjectFormatError("designer project JSON is invalid") from exc
        if not isinstance(payload, Mapping):
            raise DesignerProjectFormatError("designer project JSON must contain an object")
        return cls.from_descriptor(payload)


@dataclass(frozen=True)
class DesignerProjectFileState:
    """Inspection record for one owned designer-project file."""

    path: Path | None
    has_path: bool
    is_dirty: bool
    is_persisted: bool


class DesignerProjectFile:
    """Own one edit session and its optional on-disk project-document path.

    New in-memory projects are dirty until first saved.  Opened projects begin
    clean.  The path and clean baseline change only after an atomic write has
    succeeded, so a failed Save As cannot silently steal document ownership or
    mark unsaved edits clean.
    """

    def __init__(
        self,
        session: DesignerEditSession,
        *,
        path: str | os.PathLike[str] | None = None,
        persisted: bool = False,
    ):
        if not isinstance(session, DesignerEditSession):
            raise TypeError("designer project file requires DesignerEditSession")
        resolved_path = _project_path(path) if path is not None else None
        if persisted and resolved_path is None:
            raise ValueError("persisted designer project requires a path")
        self._session = session
        self._path = resolved_path
        self._persisted = bool(persisted)
        if self._persisted:
            self._session.mark_clean()

    @classmethod
    def create(
        cls,
        snapshot: DesignerSnapshot,
        *,
        path: str | os.PathLike[str] | None = None,
    ) -> "DesignerProjectFile":
        """Create an unsaved project around *snapshot*.

        Providing ``path`` establishes a prospective save destination only; it
        does not pretend that a file already exists or mark the document clean.
        """

        if not isinstance(snapshot, DesignerSnapshot):
            raise TypeError("designer project creation requires DesignerSnapshot")
        return cls(DesignerEditSession(snapshot), path=path, persisted=False)

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "DesignerProjectFile":
        resolved = _project_path(path)
        text = resolved.read_text(encoding="utf-8")
        document = DesignerProjectDocument.from_json(text)
        return cls(
            DesignerEditSession(document.snapshot),
            path=resolved,
            persisted=True,
        )

    @property
    def session(self) -> DesignerEditSession:
        return self._session

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def has_path(self) -> bool:
        return self._path is not None

    @property
    def is_persisted(self) -> bool:
        return self._persisted

    @property
    def is_dirty(self) -> bool:
        return not self._persisted or self._session.is_dirty

    @property
    def document(self) -> DesignerProjectDocument:
        return DesignerProjectDocument(self._session.snapshot)

    @property
    def state(self) -> DesignerProjectFileState:
        return DesignerProjectFileState(
            self._path,
            self.has_path,
            self.is_dirty,
            self._persisted,
        )

    def save(
        self,
        path: str | os.PathLike[str] | None = None,
    ) -> Path:
        """Atomically save current snapshot and return the owned absolute path.

        ``path`` acts as Save As.  With no argument, an existing owned path is
        required.  Ownership and the clean baseline are committed only after
        the replacement write succeeds.
        """

        target = _project_path(path) if path is not None else self._path
        if target is None:
            raise ValueError("designer project has no save path")
        payload = self.document.to_json(indent=2) + "\n"
        _atomic_write_text(target, payload)
        self._path = target
        self._persisted = True
        self._session.mark_clean()
        return target

    def save_as(self, path: str | os.PathLike[str]) -> Path:
        return self.save(path)


def load_designer_project(path: str | os.PathLike[str]) -> DesignerProjectFile:
    """Open a persisted designer project file."""

    return DesignerProjectFile.open(path)


def _project_path(path: str | os.PathLike[str]) -> Path:
    if isinstance(path, str) and not path.strip():
        raise ValueError("designer project path must be non-empty")
    try:
        resolved = Path(path).expanduser().absolute()
    except TypeError as exc:
        raise TypeError("designer project path must be path-like") from exc
    return resolved


def _atomic_write_text(path: Path, text: str) -> None:
    parent = path.parent
    if not parent.is_dir():
        raise FileNotFoundError(f"designer project parent directory does not exist: {parent}")
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=parent,
        )
        temporary = Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = None
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DesignerProjectFormatError(
                f"designer project JSON contains duplicate key: {key}"
            )
        result[key] = value
    return result


def _reject_non_finite_json(value: str) -> object:
    raise DesignerProjectFormatError(
        f"designer project JSON contains non-finite number: {value}"
    )


__all__ = [
    "DESIGNER_PROJECT_KIND",
    "DESIGNER_PROJECT_VERSION",
    "DesignerProjectDocument",
    "DesignerProjectFile",
    "DesignerProjectFileState",
    "DesignerProjectFormatError",
    "load_designer_project",
]
