"""Document-level copy, paste and duplicate helpers for designer snapshots.

This module belongs to the optional designer/tooling layer.  It never touches a
GUI toolkit, operating-system clipboard, application service, or live component
instance.  Copying captures one immutable ``DesignerNode`` subtree plus its
source relationship metadata; paste/duplicate create fresh node identities and
reuse the structural validation boundary from ``designer_structure``.

The clipboard payload and ID-remapping rules are intentionally provisional. They
provide deterministic editor semantics without freezing a final project format,
system-clipboard contract, or public framework API.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Final

from .designer import DesignerChild, DesignerNode, DesignerSnapshot
from .designer_structure import InsertDesignerChild, locate_designer_node


DESIGNER_CLIPBOARD_KIND: Final = "salix-designer-subtree"
DESIGNER_CLIPBOARD_VERSION: Final = 1
_PRESERVE_RELATIONSHIP: Final = object()


def _key(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


def _json_copy(value: object) -> object:
    try:
        payload = json.dumps(value, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise TypeError("designer clipboard data must be JSON-safe") from exc
    return json.loads(payload)


def _find_node(snapshot: DesignerSnapshot, node_id: object) -> DesignerNode:
    resolved = _key(node_id, field="designer node id")
    for node in snapshot.root.walk():
        if node.node_id == resolved:
            return node
    raise KeyError(f"designer node not found: {resolved}")


def _safe_metadata(metadata: Mapping[str, object] | None) -> dict[str, object] | None:
    if metadata is None:
        return None
    if not isinstance(metadata, Mapping):
        raise TypeError("designer clipboard relationship metadata must be a mapping or None")
    safe = _json_copy(dict(metadata))
    if not isinstance(safe, dict):
        raise TypeError("designer clipboard relationship metadata must serialize as an object")
    return safe


@dataclass(frozen=True)
class DesignerClipboardPayload:
    """One copied designer subtree and its source relationship context."""

    root: DesignerNode
    slot: str | None = None
    metadata: Mapping[str, object] | None = None
    kind: str = DESIGNER_CLIPBOARD_KIND
    version: int = DESIGNER_CLIPBOARD_VERSION

    def __init__(
        self,
        root: DesignerNode,
        *,
        slot: object | None = None,
        metadata: Mapping[str, object] | None = None,
        kind: object = DESIGNER_CLIPBOARD_KIND,
        version: object = DESIGNER_CLIPBOARD_VERSION,
    ):
        if not isinstance(root, DesignerNode):
            raise TypeError("designer clipboard payload requires DesignerNode")
        resolved_kind = _key(kind, field="designer clipboard kind")
        if resolved_kind != DESIGNER_CLIPBOARD_KIND:
            raise ValueError("designer clipboard payload kind is invalid")
        if isinstance(version, bool):
            raise TypeError("designer clipboard payload version must be an integer")
        resolved_version = int(version)
        if resolved_version != DESIGNER_CLIPBOARD_VERSION:
            raise ValueError(f"unsupported designer clipboard version: {resolved_version}")
        object.__setattr__(self, "root", root)
        object.__setattr__(
            self,
            "slot",
            _key(slot, field="designer child slot") if slot is not None else None,
        )
        safe_metadata = _safe_metadata(metadata)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(safe_metadata) if safe_metadata is not None else None,
        )
        object.__setattr__(self, "kind", resolved_kind)
        object.__setattr__(self, "version", resolved_version)

    @property
    def node_count(self) -> int:
        return len(self.root.walk())

    @property
    def type_keys(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(node.type_key for node in self.root.walk()))

    def to_descriptor(self) -> dict:
        descriptor = {
            "kind": self.kind,
            "version": self.version,
            "root": self.root.to_descriptor(),
            "slot": self.slot,
        }
        if self.metadata is not None:
            descriptor["metadata"] = _json_copy(dict(self.metadata))
        return descriptor

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_descriptor(), indent=indent, sort_keys=True)

    @classmethod
    def from_descriptor(cls, descriptor: Mapping[str, object]) -> "DesignerClipboardPayload":
        if not isinstance(descriptor, Mapping):
            raise TypeError("designer clipboard descriptor must be a mapping")
        root = descriptor.get("root")
        if not isinstance(root, Mapping):
            raise TypeError("designer clipboard descriptor requires a root mapping")
        metadata = descriptor.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise TypeError("designer clipboard metadata must be a mapping")
        return cls(
            DesignerNode.from_descriptor(root),
            slot=descriptor.get("slot"),
            metadata=metadata,
            kind=descriptor.get("kind"),
            version=descriptor.get("version"),
        )

    @classmethod
    def from_json(cls, payload: str) -> "DesignerClipboardPayload":
        descriptor = json.loads(payload)
        if not isinstance(descriptor, Mapping):
            raise TypeError("designer clipboard JSON must contain an object")
        return cls.from_descriptor(descriptor)


@dataclass(frozen=True)
class DesignerSubtreeClone:
    """A copied subtree plus deterministic old-ID -> new-ID bindings."""

    root: DesignerNode
    id_map: Mapping[str, str]

    def __init__(self, root: DesignerNode, id_map: Mapping[str, str]):
        if not isinstance(root, DesignerNode):
            raise TypeError("designer subtree clone requires DesignerNode")
        resolved = {
            _key(source, field="designer source node id"): _key(
                target, field="designer cloned node id"
            )
            for source, target in id_map.items()
        }
        if len(resolved) != len(root.walk()):
            raise ValueError("designer subtree clone ID map must cover every cloned node")
        if len(set(resolved.values())) != len(resolved):
            raise ValueError("designer subtree clone IDs must be unique")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "id_map", MappingProxyType(resolved))

    def node_id(self, source_node_id: object) -> str:
        resolved = _key(source_node_id, field="designer source node id")
        try:
            return self.id_map[resolved]
        except KeyError as exc:
            raise KeyError(f"designer clone has no source node id: {resolved}") from exc

    def to_descriptor(self) -> dict:
        return {
            "root": self.root.to_descriptor(),
            "id_map": dict(self.id_map),
        }


def copy_designer_subtree(
    snapshot: DesignerSnapshot,
    node_id: object,
) -> DesignerClipboardPayload:
    """Capture ``node_id`` as immutable clipboard data without editing ``snapshot``."""

    if not isinstance(snapshot, DesignerSnapshot):
        raise TypeError("designer copy requires DesignerSnapshot")
    node = _find_node(snapshot, node_id)
    location = locate_designer_node(snapshot, node.node_id)
    return DesignerClipboardPayload(
        DesignerNode.from_descriptor(node.to_descriptor()),
        slot=location.slot,
        metadata=location.metadata,
    )


def _candidate_id(source_id: str, reserved: set[str], *, suffix: str) -> str:
    base = f"{source_id}-{suffix}"
    candidate = base
    index = 2
    while candidate in reserved:
        candidate = f"{base}-{index}"
        index += 1
    reserved.add(candidate)
    return candidate


def remap_designer_subtree_ids(
    node: DesignerNode,
    existing_ids: Iterable[object],
    *,
    suffix: object = "copy",
) -> DesignerSubtreeClone:
    """Clone ``node`` with deterministic fresh IDs that avoid ``existing_ids``.

    IDs are allocated in preorder.  The first available form is
    ``<source>-<suffix>`` followed by ``-2``, ``-3`` and so on.  The algorithm
    considers both target IDs and IDs allocated earlier in the same subtree.
    """

    if not isinstance(node, DesignerNode):
        raise TypeError("designer subtree remapping requires DesignerNode")
    resolved_suffix = _key(suffix, field="designer copy ID suffix")
    if isinstance(existing_ids, (str, bytes)):
        raise TypeError("designer existing IDs must be an iterable of node IDs")
    reserved = {_key(value, field="designer existing node id") for value in existing_ids}
    id_map: dict[str, str] = {}

    def clone(current: DesignerNode) -> DesignerNode:
        new_id = _candidate_id(current.node_id, reserved, suffix=resolved_suffix)
        id_map[current.node_id] = new_id
        children = tuple(
            DesignerChild(child.slot, clone(child.node), child.metadata)
            for child in current.children
        )
        return DesignerNode(new_id, current.type_key, current.properties, children)

    root = clone(node)
    return DesignerSubtreeClone(root, id_map)


@dataclass(frozen=True)
class PasteDesignerSubtree:
    """Paste copied subtree data under a target parent using fresh node IDs."""

    parent_id: str
    payload: DesignerClipboardPayload
    index: int | None
    slot: str | None
    metadata: object
    suffix: str

    def __init__(
        self,
        parent_id: object,
        payload: DesignerClipboardPayload,
        *,
        index: int | None = None,
        slot: object | None = None,
        metadata: Mapping[str, object] | None | object = _PRESERVE_RELATIONSHIP,
        suffix: object = "copy",
    ):
        if not isinstance(payload, DesignerClipboardPayload):
            raise TypeError("designer paste requires DesignerClipboardPayload")
        object.__setattr__(self, "parent_id", _key(parent_id, field="designer parent node id"))
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "index", index)
        object.__setattr__(
            self,
            "slot",
            _key(slot, field="designer child slot") if slot is not None else None,
        )
        if metadata is _PRESERVE_RELATIONSHIP:
            object.__setattr__(self, "metadata", _PRESERVE_RELATIONSHIP)
        else:
            object.__setattr__(self, "metadata", _safe_metadata(metadata))
        object.__setattr__(self, "suffix", _key(suffix, field="designer copy ID suffix"))

    @property
    def label(self) -> str:
        return f"Paste {self.payload.root.node_id}"

    def clone_for(self, snapshot: DesignerSnapshot) -> DesignerSubtreeClone:
        if not isinstance(snapshot, DesignerSnapshot):
            raise TypeError("designer paste requires DesignerSnapshot")
        return remap_designer_subtree_ids(
            self.payload.root,
            (node.node_id for node in snapshot.root.walk()),
            suffix=self.suffix,
        )

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        clone = self.clone_for(snapshot)
        slot = self.slot if self.slot is not None else (self.payload.slot or "children")
        metadata = (
            _safe_metadata(self.payload.metadata)
            if self.metadata is _PRESERVE_RELATIONSHIP
            else self.metadata
        )
        return InsertDesignerChild(
            self.parent_id,
            clone.root,
            slot=slot,
            metadata=metadata,  # type: ignore[arg-type]
            index=self.index,
        ).apply(snapshot)


@dataclass(frozen=True)
class DuplicateDesignerNode:
    """Duplicate one non-root node next to itself with fresh subtree IDs."""

    node_id: str
    index: int | None
    slot: str | None
    metadata: object
    suffix: str

    def __init__(
        self,
        node_id: object,
        *,
        index: int | None = None,
        slot: object | None = None,
        metadata: Mapping[str, object] | None | object = _PRESERVE_RELATIONSHIP,
        suffix: object = "copy",
    ):
        object.__setattr__(self, "node_id", _key(node_id, field="designer node id"))
        object.__setattr__(self, "index", index)
        object.__setattr__(
            self,
            "slot",
            _key(slot, field="designer child slot") if slot is not None else None,
        )
        if metadata is _PRESERVE_RELATIONSHIP:
            object.__setattr__(self, "metadata", _PRESERVE_RELATIONSHIP)
        else:
            object.__setattr__(self, "metadata", _safe_metadata(metadata))
        object.__setattr__(self, "suffix", _key(suffix, field="designer copy ID suffix"))

    @property
    def label(self) -> str:
        return f"Duplicate {self.node_id}"

    def paste_command(self, snapshot: DesignerSnapshot) -> PasteDesignerSubtree:
        if not isinstance(snapshot, DesignerSnapshot):
            raise TypeError("designer duplicate requires DesignerSnapshot")
        location = locate_designer_node(snapshot, self.node_id)
        if location.parent_id is None or location.index is None or location.slot is None:
            raise ValueError("designer snapshot root cannot be duplicated")
        payload = copy_designer_subtree(snapshot, self.node_id)
        index = self.index if self.index is not None else location.index + 1
        slot = self.slot if self.slot is not None else location.slot
        metadata = location.metadata if self.metadata is _PRESERVE_RELATIONSHIP else self.metadata
        return PasteDesignerSubtree(
            location.parent_id,
            payload,
            index=index,
            slot=slot,
            metadata=metadata,  # type: ignore[arg-type]
            suffix=self.suffix,
        )

    def clone_for(self, snapshot: DesignerSnapshot) -> DesignerSubtreeClone:
        return self.paste_command(snapshot).clone_for(snapshot)

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        return self.paste_command(snapshot).apply(snapshot)


__all__ = [
    "DESIGNER_CLIPBOARD_KIND",
    "DESIGNER_CLIPBOARD_VERSION",
    "DesignerClipboardPayload",
    "DesignerSubtreeClone",
    "DuplicateDesignerNode",
    "PasteDesignerSubtree",
    "copy_designer_subtree",
    "remap_designer_subtree_ids",
]
