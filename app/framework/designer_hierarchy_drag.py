"""Backend-neutral planning for the first designer hierarchy drag/reparent gesture.

The hierarchy UI may report only stable source/target node IDs.  This module
resolves that transient gesture into one explicit structural plan using the
current immutable ``DesignerSnapshot``.  Concrete toolkits never choose child
slots, relationship metadata, history behavior, or document ownership.

This first drag slice is intentionally conservative: dropping *onto* a target
means "append this node as a child" and is accepted only when the target exposes
one unambiguous child slot that requires no relationship metadata.  Grids,
tabs, split panes and positioned containers still require the explicit
Placement surface because silently inventing coordinates/keys would corrupt
structure semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable, Mapping

from .designer import DesignerSnapshot
from .designer_structure import locate_designer_node


def _node_id(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


def _find_node(snapshot: DesignerSnapshot, node_id: str):
    for node in snapshot.root.walk():
        if node.node_id == node_id:
            return node
    raise KeyError(f"designer node not found: {node_id}")


def _type_descriptor(snapshot: DesignerSnapshot, type_key: str) -> Mapping[str, object]:
    for descriptor in snapshot.types:
        if descriptor.get("key") == type_key:
            return descriptor
    raise KeyError(f"designer snapshot has no metadata for type: {type_key}")


def _simple_child_slot(snapshot: DesignerSnapshot, parent_id: str) -> str:
    parent = _find_node(snapshot, parent_id)
    descriptor = _type_descriptor(snapshot, parent.type_key)
    if not bool(descriptor.get("accepts_children", False)):
        raise ValueError("hierarchy drop target does not accept children")

    slots = descriptor.get("child_slots", ())
    if isinstance(slots, (str, bytes)) or not isinstance(slots, Iterable):
        raise TypeError("designer child-slot metadata must be iterable")
    resolved = tuple(slots)
    if len(resolved) != 1:
        raise ValueError(
            "hierarchy drop target requires explicit placement because its child slot is ambiguous"
        )
    slot = resolved[0]
    if not isinstance(slot, Mapping):
        raise TypeError("designer child-slot metadata entries must be mappings")
    key = _node_id(slot.get("key"), field="designer child slot")
    required = slot.get("required_metadata", ())
    if isinstance(required, (str, bytes)) or not isinstance(required, Iterable):
        raise TypeError("designer required child metadata must be iterable")
    if tuple(required):
        raise ValueError(
            "hierarchy drop target requires explicit relationship metadata; use Placement"
        )
    if not bool(slot.get("multiple", True)):
        parent = _find_node(snapshot, parent_id)
        if parent.children:
            raise ValueError("hierarchy drop target accepts only one child")
    return key


@dataclass(frozen=True)
class DesignerHierarchyReparentPlan:
    """One validated append-as-child hierarchy drag result."""

    node_id: str
    parent_id: str
    slot: str
    index: int | None = None

    def to_descriptor(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "slot": self.slot,
            "index": self.index,
        }


def plan_hierarchy_reparent(
    snapshot: DesignerSnapshot,
    node_id: object,
    parent_id: object,
) -> DesignerHierarchyReparentPlan:
    """Plan a hierarchy drop that appends one existing node under ``parent_id``.

    Stable identity is preserved.  Relationship metadata is intentionally reset
    to ``None`` only after the target slot has been proven metadata-free.
    Complex relationship-bearing containers remain the responsibility of the
    explicit Placement editor.
    """

    if not isinstance(snapshot, DesignerSnapshot):
        raise TypeError("hierarchy reparent planning requires DesignerSnapshot")
    source_id = _node_id(node_id, field="designer dragged node id")
    target_id = _node_id(parent_id, field="designer drop parent id")
    if source_id == target_id:
        raise ValueError("designer node cannot be dropped onto itself")

    source_location = locate_designer_node(snapshot, source_id)
    if source_location.parent_id is None:
        raise ValueError("designer snapshot root cannot be reparented")

    source = _find_node(snapshot, source_id)
    subtree_ids = {node.node_id for node in source.walk()}
    if target_id in subtree_ids:
        raise ValueError("designer node cannot be reparented into its own subtree")

    slot = _simple_child_slot(snapshot, target_id)
    target = _find_node(snapshot, target_id)
    # Appending to the node's current parent is a deterministic reorder to the
    # end of that slot, which is useful and remains one structural history step.
    index = len(target.children)
    if source_location.parent_id == target_id and source_location.index is not None:
        index = max(0, len(target.children) - 1)

    return DesignerHierarchyReparentPlan(source_id, target_id, slot, index)


__all__ = [
    "DesignerHierarchyReparentPlan",
    "plan_hierarchy_reparent",
]
