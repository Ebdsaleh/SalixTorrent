"""Immutable structural editing commands for provisional designer snapshots.

Tranches 9 and 10 established serializable hierarchy snapshots and property-level
undo/redo.  This module adds the next narrow RAD prerequisite: explicit
insert/remove/reorder/reparent operations on snapshot *document data*.

The commands deliberately do not create live framework components, invoke GUI
backends, perform drag/drop, or define the final project document schema.  Stable
node IDs and relationship metadata are preserved so a later preview/runtime
bridge can consume the edited snapshot without changing these command semantics.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from typing import Final

from .components.placement import placement_from_descriptor
from .designer import DesignerChild, DesignerNode, DesignerSnapshot


_PRESERVE_METADATA: Final = object()


def _key(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


def _json_copy(value: object) -> object:
    try:
        payload = json.dumps(value, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise TypeError("designer structural metadata must be JSON-safe") from exc
    return json.loads(payload)


def _type_descriptor(snapshot: DesignerSnapshot, type_key: str) -> Mapping[str, object]:
    for descriptor in snapshot.types:
        if descriptor.get("key") == type_key:
            return descriptor
    raise KeyError(f"designer snapshot has no metadata for type: {type_key}")


def _slot_descriptor(
    snapshot: DesignerSnapshot,
    parent: DesignerNode,
    slot: object,
) -> Mapping[str, object]:
    resolved = _key(slot, field="designer child slot")
    descriptor = _type_descriptor(snapshot, parent.type_key)
    if not bool(descriptor.get("accepts_children", False)):
        raise ValueError(f"designer node {parent.node_id!r} does not accept children")
    slots = descriptor.get("child_slots", ())
    if isinstance(slots, (str, bytes)) or not isinstance(slots, Iterable):
        raise TypeError("designer child-slot metadata must be iterable")
    for candidate in slots:
        if not isinstance(candidate, Mapping):
            raise TypeError("designer child-slot descriptors must be mappings")
        if candidate.get("key") == resolved:
            return candidate
    raise ValueError(
        f"designer parent type {parent.type_key!r} does not declare child slot {resolved!r}"
    )


def _snapshot_with_root(snapshot: DesignerSnapshot, root: DesignerNode) -> DesignerSnapshot:
    if root is snapshot.root:
        return snapshot
    return DesignerSnapshot(root, snapshot.types, kind=snapshot.kind, version=snapshot.version)


def _replace_node(
    current: DesignerNode,
    node_id: str,
    replacement,
) -> tuple[DesignerNode, bool]:
    if current.node_id == node_id:
        return replacement(current), True
    changed = False
    children = []
    for child in current.children:
        nested, nested_changed = _replace_node(child.node, node_id, replacement)
        if nested_changed:
            changed = True
            children.append(DesignerChild(child.slot, nested, child.metadata))
        else:
            children.append(child)
    if not changed:
        return current, False
    return DesignerNode(current.node_id, current.type_key, current.properties, children), True


def _find_node(snapshot: DesignerSnapshot, node_id: object) -> DesignerNode:
    resolved = _key(node_id, field="designer node id")
    for node in snapshot.root.walk():
        if node.node_id == resolved:
            return node
    raise KeyError(f"designer node not found: {resolved}")


@dataclass(frozen=True)
class DesignerNodeLocation:
    """One node's current structural position inside a snapshot hierarchy."""

    node_id: str
    parent_id: str | None
    parent_type_key: str | None
    index: int | None
    slot: str | None
    metadata: Mapping[str, object] | None
    depth: int

    def to_descriptor(self) -> dict:
        descriptor = {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "parent_type": self.parent_type_key,
            "index": self.index,
            "slot": self.slot,
            "depth": self.depth,
        }
        if self.metadata is not None:
            descriptor["metadata"] = _json_copy(self.metadata)
        return descriptor


def locate_designer_node(snapshot: DesignerSnapshot, node_id: object) -> DesignerNodeLocation:
    """Return parent/index/relationship metadata for ``node_id``."""

    if not isinstance(snapshot, DesignerSnapshot):
        raise TypeError("designer location lookup requires DesignerSnapshot")
    resolved = _key(node_id, field="designer node id")

    def visit(node: DesignerNode, depth: int) -> DesignerNodeLocation | None:
        if node.node_id == resolved:
            return DesignerNodeLocation(node.node_id, None, None, None, None, None, depth)
        for index, child in enumerate(node.children):
            if child.node.node_id == resolved:
                metadata = _json_copy(child.metadata) if child.metadata is not None else None
                if metadata is not None and not isinstance(metadata, Mapping):
                    raise TypeError("designer child metadata must serialize as an object")
                return DesignerNodeLocation(
                    child.node.node_id,
                    node.node_id,
                    node.type_key,
                    index,
                    child.slot,
                    metadata,
                    depth + 1,
                )
            nested = visit(child.node, depth + 1)
            if nested is not None:
                return nested
        return None

    found = visit(snapshot.root, 0)
    if found is None:
        raise KeyError(f"designer node not found: {resolved}")
    return found


def _location_with_parent(
    snapshot: DesignerSnapshot,
    node_id: object,
) -> tuple[DesignerNodeLocation, DesignerNode | None]:
    location = locate_designer_node(snapshot, node_id)
    parent = _find_node(snapshot, location.parent_id) if location.parent_id is not None else None
    return location, parent


def _index(value: object | None, *, size: int) -> int:
    if value is None:
        return size
    if isinstance(value, bool):
        raise TypeError("designer child index must be an integer")
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError("designer child index must be an integer") from exc
    if resolved < 0 or resolved > size:
        raise IndexError(f"designer child index must be between 0 and {size}")
    return resolved


def _required_keys(descriptor: Mapping[str, object], field: str) -> tuple[str, ...]:
    values = descriptor.get(field, ())
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise TypeError(f"designer child-slot {field} metadata must be iterable")
    return tuple(_key(value, field="designer child metadata key") for value in values)


def _relationship_metadata(metadata: Mapping[str, object] | None) -> dict[str, object] | None:
    if metadata is None:
        return None
    if not isinstance(metadata, Mapping):
        raise TypeError("designer child metadata must be a mapping or None")
    safe = _json_copy(metadata)
    if not isinstance(safe, dict):
        raise TypeError("designer child metadata must serialize as an object")
    return safe


def _validate_relationship(
    snapshot: DesignerSnapshot,
    parent: DesignerNode,
    child_node: DesignerNode,
    *,
    slot: object,
    metadata: Mapping[str, object] | None,
    siblings: Iterable[DesignerChild],
) -> tuple[str, dict[str, object] | None]:
    resolved_slot = _key(slot, field="designer child slot")
    slot_descriptor = _slot_descriptor(snapshot, parent, resolved_slot)
    safe_metadata = _relationship_metadata(metadata)
    allowed = set(_required_keys(slot_descriptor, "allowed_metadata"))
    if safe_metadata:
        unexpected = sorted(set(safe_metadata).difference(allowed))
        if unexpected:
            raise ValueError(
                f"designer child slot {resolved_slot!r} does not allow metadata: "
                + ", ".join(unexpected)
            )
    required = _required_keys(slot_descriptor, "required_metadata")
    missing = [key for key in required if safe_metadata is None or key not in safe_metadata]
    if missing:
        raise ValueError(
            f"designer child slot {resolved_slot!r} requires metadata: " + ", ".join(missing)
        )

    same_slot = tuple(child for child in siblings if child.slot == resolved_slot)
    if not bool(slot_descriptor.get("multiple", True)) and same_slot:
        raise ValueError(f"designer child slot {resolved_slot!r} accepts only one child")

    unique_by = _required_keys(slot_descriptor, "unique_by")
    if unique_by:
        assert safe_metadata is not None
        identity = tuple(safe_metadata[key] for key in unique_by)
        for sibling in same_slot:
            sibling_metadata = sibling.metadata or {}
            if all(key in sibling_metadata for key in unique_by):
                if tuple(sibling_metadata[key] for key in unique_by) == identity:
                    joined = ", ".join(unique_by)
                    raise ValueError(
                        f"designer child slot {resolved_slot!r} requires unique metadata ({joined})"
                    )

    if parent.type_key == "container.grid" and resolved_slot == "cell":
        assert safe_metadata is not None
        for key in ("row", "column"):
            value = safe_metadata[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"grid {key} metadata must be a non-negative integer")
    elif parent.type_key == "structure.tabs" and resolved_slot == "page":
        assert safe_metadata is not None
        page_key = _key(safe_metadata.get("key"), field="designer tab page key")
        if child_node.type_key != "structure.tab_page":
            raise ValueError("tabs may only own structure.tab_page nodes in the page slot")
        node_key = child_node.properties.get("key")
        if node_key is not None and _key(node_key, field="designer tab page node key") != page_key:
            raise ValueError("tab page relationship key must match the tab-page node key")
    elif parent.type_key == "structure.split" and resolved_slot == "pane":
        assert safe_metadata is not None
        _key(safe_metadata.get("key"), field="designer split pane key")
    elif parent.type_key in {"container.placed", "container.positioned"}:
        assert safe_metadata is not None
        placement = safe_metadata.get("placement")
        if not isinstance(placement, Mapping):
            raise TypeError("designer placement metadata must be a mapping")
        placement_from_descriptor(placement)

    return resolved_slot, safe_metadata


def _subtree_ids(node: DesignerNode) -> set[str]:
    return {item.node_id for item in node.walk()}


def _validate_inserted_subtree(snapshot: DesignerSnapshot, node: DesignerNode) -> None:
    existing = {item.node_id for item in snapshot.root.walk()}
    overlap = existing.intersection(_subtree_ids(node))
    if overlap:
        raise ValueError(
            "designer inserted subtree reuses existing node id(s): " + ", ".join(sorted(overlap))
        )
    type_keys = {str(item.get("key")) for item in snapshot.types}
    missing = {item.type_key for item in node.walk()}.difference(type_keys)
    if missing:
        raise ValueError(
            "designer inserted subtree uses unknown type metadata: " + ", ".join(sorted(missing))
        )


@dataclass(frozen=True)
class InsertDesignerChild:
    """Insert a detached designer subtree under one parent relationship slot."""

    parent_id: str
    node: DesignerNode
    slot: str = "children"
    metadata: Mapping[str, object] | None = None
    index: int | None = None

    def __init__(
        self,
        parent_id: object,
        node: DesignerNode,
        *,
        slot: object = "children",
        metadata: Mapping[str, object] | None = None,
        index: int | None = None,
    ):
        if not isinstance(node, DesignerNode):
            raise TypeError("designer insert requires a DesignerNode subtree")
        object.__setattr__(self, "parent_id", _key(parent_id, field="designer parent node id"))
        object.__setattr__(self, "node", node)
        object.__setattr__(self, "slot", _key(slot, field="designer child slot"))
        object.__setattr__(self, "metadata", _relationship_metadata(metadata))
        object.__setattr__(self, "index", index)

    @property
    def label(self) -> str:
        return f"Insert {self.node.node_id}"

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        if not isinstance(snapshot, DesignerSnapshot):
            raise TypeError("designer structural edit requires DesignerSnapshot")
        parent = _find_node(snapshot, self.parent_id)
        _validate_inserted_subtree(snapshot, self.node)
        slot, metadata = _validate_relationship(
            snapshot,
            parent,
            self.node,
            slot=self.slot,
            metadata=self.metadata,
            siblings=parent.children,
        )
        insert_at = _index(self.index, size=len(parent.children))

        def replacement(current: DesignerNode) -> DesignerNode:
            children = list(current.children)
            children.insert(insert_at, DesignerChild(slot, self.node, metadata))
            return DesignerNode(current.node_id, current.type_key, current.properties, children)

        root, changed = _replace_node(snapshot.root, parent.node_id, replacement)
        if not changed:
            raise KeyError(f"designer node not found: {parent.node_id}")
        return _snapshot_with_root(snapshot, root)


@dataclass(frozen=True)
class RemoveDesignerNode:
    """Remove one non-root designer node and its complete subtree."""

    node_id: str

    def __init__(self, node_id: object):
        object.__setattr__(self, "node_id", _key(node_id, field="designer node id"))

    @property
    def label(self) -> str:
        return f"Remove {self.node_id}"

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        location, parent = _location_with_parent(snapshot, self.node_id)
        if parent is None or location.index is None:
            raise ValueError("designer snapshot root cannot be removed")
        index = location.index

        def replacement(current: DesignerNode) -> DesignerNode:
            children = list(current.children)
            children.pop(index)
            return DesignerNode(current.node_id, current.type_key, current.properties, children)

        root, changed = _replace_node(snapshot.root, parent.node_id, replacement)
        if not changed:
            raise KeyError(f"designer node not found: {parent.node_id}")
        return _snapshot_with_root(snapshot, root)


@dataclass(frozen=True)
class MoveDesignerNode:
    """Reorder one node among the existing children of its current parent."""

    node_id: str
    index: int

    def __init__(self, node_id: object, index: object):
        object.__setattr__(self, "node_id", _key(node_id, field="designer node id"))
        if isinstance(index, bool):
            raise TypeError("designer child index must be an integer")
        try:
            resolved = int(index)
        except (TypeError, ValueError) as exc:
            raise TypeError("designer child index must be an integer") from exc
        object.__setattr__(self, "index", resolved)

    @property
    def label(self) -> str:
        return f"Move {self.node_id}"

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        location, parent = _location_with_parent(snapshot, self.node_id)
        if parent is None or location.index is None:
            raise ValueError("designer snapshot root cannot be moved")
        source_index = location.index
        remaining = list(parent.children)
        entry = remaining.pop(source_index)
        target_index = _index(self.index, size=len(remaining))
        if source_index == target_index:
            return snapshot
        remaining.insert(target_index, entry)

        def replacement(current: DesignerNode) -> DesignerNode:
            return DesignerNode(current.node_id, current.type_key, current.properties, remaining)

        root, changed = _replace_node(snapshot.root, parent.node_id, replacement)
        if not changed:
            raise KeyError(f"designer node not found: {parent.node_id}")
        return _snapshot_with_root(snapshot, root)


@dataclass(frozen=True)
class ReparentDesignerNode:
    """Move an existing subtree to another parent, preserving identity."""

    node_id: str
    parent_id: str
    index: int | None
    slot: str | None
    metadata: object

    def __init__(
        self,
        node_id: object,
        parent_id: object,
        *,
        index: int | None = None,
        slot: object | None = None,
        metadata: Mapping[str, object] | None | object = _PRESERVE_METADATA,
    ):
        object.__setattr__(self, "node_id", _key(node_id, field="designer node id"))
        object.__setattr__(self, "parent_id", _key(parent_id, field="designer parent node id"))
        object.__setattr__(self, "index", index)
        object.__setattr__(
            self,
            "slot",
            _key(slot, field="designer child slot") if slot is not None else None,
        )
        if metadata is _PRESERVE_METADATA:
            object.__setattr__(self, "metadata", _PRESERVE_METADATA)
        else:
            object.__setattr__(self, "metadata", _relationship_metadata(metadata))

    @property
    def label(self) -> str:
        return f"Reparent {self.node_id}"

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        location, source_parent = _location_with_parent(snapshot, self.node_id)
        if source_parent is None or location.index is None or location.slot is None:
            raise ValueError("designer snapshot root cannot be reparented")
        node = _find_node(snapshot, self.node_id)
        if self.parent_id in _subtree_ids(node):
            raise ValueError("designer node cannot be reparented into its own subtree")
        _find_node(snapshot, self.parent_id)

        source_index = location.index

        def remove_source(current: DesignerNode) -> DesignerNode:
            children = list(current.children)
            children.pop(source_index)
            return DesignerNode(current.node_id, current.type_key, current.properties, children)

        root_after_remove, changed = _replace_node(snapshot.root, source_parent.node_id, remove_source)
        if not changed:
            raise KeyError(f"designer node not found: {source_parent.node_id}")
        temporary = _snapshot_with_root(snapshot, root_after_remove)
        target_parent = _find_node(temporary, self.parent_id)
        slot = self.slot if self.slot is not None else location.slot
        metadata = location.metadata if self.metadata is _PRESERVE_METADATA else self.metadata
        slot, safe_metadata = _validate_relationship(
            temporary,
            target_parent,
            node,
            slot=slot,
            metadata=metadata,  # type: ignore[arg-type]
            siblings=target_parent.children,
        )
        target_index = _index(self.index, size=len(target_parent.children))

        def insert_target(current: DesignerNode) -> DesignerNode:
            children = list(current.children)
            children.insert(target_index, DesignerChild(slot, node, safe_metadata))
            return DesignerNode(current.node_id, current.type_key, current.properties, children)

        final_root, changed = _replace_node(temporary.root, target_parent.node_id, insert_target)
        if not changed:
            raise KeyError(f"designer node not found: {target_parent.node_id}")
        return _snapshot_with_root(temporary, final_root)


__all__ = [
    "DesignerNodeLocation",
    "InsertDesignerChild",
    "MoveDesignerNode",
    "RemoveDesignerNode",
    "ReparentDesignerNode",
    "locate_designer_node",
]
