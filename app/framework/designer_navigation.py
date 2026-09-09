"""Stable-ID hierarchy navigation for optional designer tooling.

This module defines backend-neutral tree traversal over immutable
``DesignerSnapshot`` documents.  It does not own a toolkit tree widget, pointer
hit testing, keyboard bindings, or persisted project state.  A future hierarchy
surface can ask for parent/child/sibling/preorder targets and the ancestor path
needed to reveal a node, then decide how to present those semantics.

Navigation is expressed entirely in designer node IDs so it remains valid across
preview reconstruction and does not retain stale ``Component`` instances or
backend handles.  Code-first applications do not depend on this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .designer import DesignerNode, DesignerSnapshot
from .designer_structure import DesignerNodeLocation, locate_designer_node


class DesignerNavigationDirection(str, Enum):
    """Portable hierarchy traversal directions over snapshot order."""

    PARENT = "parent"
    FIRST_CHILD = "first_child"
    LAST_CHILD = "last_child"
    PREVIOUS_SIBLING = "previous_sibling"
    NEXT_SIBLING = "next_sibling"
    PREVIOUS_PREORDER = "previous_preorder"
    NEXT_PREORDER = "next_preorder"


def _direction(value: DesignerNavigationDirection | str) -> DesignerNavigationDirection:
    text = str(getattr(value, "value", value) or "").strip().lower()
    try:
        return DesignerNavigationDirection(text)
    except ValueError as exc:
        raise ValueError(f"unsupported designer navigation direction: {value!r}") from exc


def _node_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("designer node id must be non-empty")
    return text


def _require_snapshot(snapshot: DesignerSnapshot) -> DesignerSnapshot:
    if not isinstance(snapshot, DesignerSnapshot):
        raise TypeError("designer hierarchy navigation requires DesignerSnapshot")
    return snapshot


@dataclass(frozen=True)
class DesignerHierarchyReveal:
    """Stable-ID reveal information for one hierarchy node.

    ``ancestor_ids`` is ordered from the root through the immediate parent.  A
    tree widget can expand those IDs to reveal ``node_id`` without making
    expansion state part of the designer document or selection history.
    """

    node_id: str
    ancestor_ids: tuple[str, ...]

    @property
    def path_ids(self) -> tuple[str, ...]:
        return self.ancestor_ids + (self.node_id,)

    @property
    def depth(self) -> int:
        return len(self.ancestor_ids)


class DesignerHierarchyNavigator:
    """Read-only traversal/query model for one immutable designer snapshot."""

    def __init__(self, snapshot: DesignerSnapshot):
        self.snapshot = _require_snapshot(snapshot)
        nodes = self.snapshot.root.walk()
        self._nodes = {node.node_id: node for node in nodes}
        self._preorder = tuple(node.node_id for node in nodes)
        self._preorder_index = {node_id: index for index, node_id in enumerate(self._preorder)}
        self._parent: dict[str, str | None] = {self.snapshot.root.node_id: None}
        self._sibling_index: dict[str, int | None] = {self.snapshot.root.node_id: None}
        self._children: dict[str, tuple[str, ...]] = {}

        def index(node: DesignerNode) -> None:
            child_ids = tuple(child.node.node_id for child in node.children)
            self._children[node.node_id] = child_ids
            for child_index, child in enumerate(node.children):
                child_id = child.node.node_id
                self._parent[child_id] = node.node_id
                self._sibling_index[child_id] = child_index
                index(child.node)

        index(self.snapshot.root)

    @property
    def root_id(self) -> str:
        return self.snapshot.root.node_id

    @property
    def preorder_ids(self) -> tuple[str, ...]:
        return self._preorder

    def node(self, node_id: object) -> DesignerNode:
        resolved = _node_id(node_id)
        try:
            return self._nodes[resolved]
        except KeyError as exc:
            raise KeyError(f"designer node not found: {resolved}") from exc

    def location(self, node_id: object) -> DesignerNodeLocation:
        resolved = self.node(node_id).node_id
        return locate_designer_node(self.snapshot, resolved)

    def parent_id(self, node_id: object) -> str | None:
        resolved = self.node(node_id).node_id
        return self._parent[resolved]

    def child_ids(self, node_id: object) -> tuple[str, ...]:
        resolved = self.node(node_id).node_id
        return self._children[resolved]

    def first_child_id(self, node_id: object) -> str | None:
        children = self.child_ids(node_id)
        return children[0] if children else None

    def last_child_id(self, node_id: object) -> str | None:
        children = self.child_ids(node_id)
        return children[-1] if children else None

    def previous_sibling_id(self, node_id: object) -> str | None:
        resolved = self.node(node_id).node_id
        parent_id = self._parent[resolved]
        index = self._sibling_index[resolved]
        if parent_id is None or index is None or index <= 0:
            return None
        return self._children[parent_id][index - 1]

    def next_sibling_id(self, node_id: object) -> str | None:
        resolved = self.node(node_id).node_id
        parent_id = self._parent[resolved]
        index = self._sibling_index[resolved]
        if parent_id is None or index is None:
            return None
        siblings = self._children[parent_id]
        next_index = index + 1
        return siblings[next_index] if next_index < len(siblings) else None

    def previous_preorder_id(self, node_id: object) -> str | None:
        resolved = self.node(node_id).node_id
        index = self._preorder_index[resolved]
        return self._preorder[index - 1] if index > 0 else None

    def next_preorder_id(self, node_id: object) -> str | None:
        resolved = self.node(node_id).node_id
        index = self._preorder_index[resolved] + 1
        return self._preorder[index] if index < len(self._preorder) else None

    def ancestor_ids(self, node_id: object) -> tuple[str, ...]:
        resolved = self.node(node_id).node_id
        ancestors: list[str] = []
        current = resolved
        while True:
            parent_id = self.parent_id(current)
            if parent_id is None:
                break
            ancestors.append(parent_id)
            current = parent_id
        ancestors.reverse()
        return tuple(ancestors)

    def path_ids(self, node_id: object) -> tuple[str, ...]:
        resolved = self.node(node_id).node_id
        return self.ancestor_ids(resolved) + (resolved,)

    def reveal(self, node_id: object) -> DesignerHierarchyReveal:
        resolved = self.node(node_id).node_id
        return DesignerHierarchyReveal(resolved, self.ancestor_ids(resolved))

    def target(
        self,
        node_id: object,
        direction: DesignerNavigationDirection | str,
    ) -> str | None:
        resolved = self.node(node_id).node_id
        resolved_direction = _direction(direction)
        operations = {
            DesignerNavigationDirection.PARENT: self.parent_id,
            DesignerNavigationDirection.FIRST_CHILD: self.first_child_id,
            DesignerNavigationDirection.LAST_CHILD: self.last_child_id,
            DesignerNavigationDirection.PREVIOUS_SIBLING: self.previous_sibling_id,
            DesignerNavigationDirection.NEXT_SIBLING: self.next_sibling_id,
            DesignerNavigationDirection.PREVIOUS_PREORDER: self.previous_preorder_id,
            DesignerNavigationDirection.NEXT_PREORDER: self.next_preorder_id,
        }
        return operations[resolved_direction](resolved)


__all__ = [
    "DesignerHierarchyNavigator",
    "DesignerHierarchyReveal",
    "DesignerNavigationDirection",
]
