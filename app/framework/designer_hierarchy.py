"""Backend-neutral hierarchy projection and expansion for designer tooling.

Tranche 17 established stable-ID hierarchy navigation over immutable
``DesignerSnapshot`` documents.  This module adds the next presentation-model
layer: a deterministic projection of the currently visible tree rows plus
*ephemeral* expanded/collapsed state.

Expansion is editor interaction state.  It is not part of the designer project
document, undo/redo history, preview generation or application runtime state.
A concrete hierarchy widget can render ``DesignerHierarchyRow`` records and
feed expand/collapse/reveal actions back into this model without becoming the
owner of designer semantics.

The model stores only designer node IDs.  It never retains live ``Component``
instances, renderer items or toolkit handles, and code-first applications do
not depend on this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .designer import DesignerSnapshot
from .designer_navigation import DesignerHierarchyNavigator, DesignerHierarchyReveal
from .designer_selection import DesignerSelectionState


def _require_snapshot(snapshot: DesignerSnapshot) -> DesignerSnapshot:
    if not isinstance(snapshot, DesignerSnapshot):
        raise TypeError("designer hierarchy projection requires DesignerSnapshot")
    return snapshot


def _node_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("designer node id must be non-empty")
    return text


def _selection_state(value: DesignerSelectionState | None) -> DesignerSelectionState:
    if value is None:
        return DesignerSelectionState()
    if not isinstance(value, DesignerSelectionState):
        raise TypeError("designer hierarchy rows require DesignerSelectionState")
    return value


@dataclass(frozen=True)
class DesignerHierarchyProjectionState:
    """Immutable inspection record for ephemeral expansion identities."""

    expanded_ids: tuple[str, ...] = ()

    @property
    def expanded_count(self) -> int:
        return len(self.expanded_ids)


@dataclass(frozen=True)
class DesignerHierarchyRow:
    """One visible hierarchy row independent of any concrete tree widget."""

    node_id: str
    type_key: str
    depth: int
    parent_id: str
    child_count: int
    expanded: bool
    selected: bool
    focused: bool

    @property
    def expandable(self) -> bool:
        return self.child_count > 0


class DesignerHierarchyProjection:
    """Own ephemeral expansion state and project visible stable-ID rows.

    The root begins expanded by default when it has children so a newly opened
    hierarchy surface exposes one useful level immediately.  Callers may opt
    out with ``expand_root=False``.  Expansion state is normalized into snapshot
    preorder for deterministic inspection.
    """

    def __init__(
        self,
        snapshot: DesignerSnapshot,
        *,
        expanded_ids: Iterable[object] | None = None,
        expand_root: bool = True,
    ):
        self._snapshot = _require_snapshot(snapshot)
        self._navigation = DesignerHierarchyNavigator(self._snapshot)
        self._expanded: set[str] = set()

        if expanded_ids is not None:
            for value in expanded_ids:
                node_id = _node_id(value)
                self._navigation.node(node_id)
                if self._navigation.child_ids(node_id):
                    self._expanded.add(node_id)

        root_id = self._navigation.root_id
        if expand_root and self._navigation.child_ids(root_id):
            self._expanded.add(root_id)

    @property
    def snapshot(self) -> DesignerSnapshot:
        return self._snapshot

    @property
    def state(self) -> DesignerHierarchyProjectionState:
        return DesignerHierarchyProjectionState(self.expanded_ids)

    @property
    def expanded_ids(self) -> tuple[str, ...]:
        return tuple(
            node_id
            for node_id in self._navigation.preorder_ids
            if node_id in self._expanded
        )

    def is_expanded(self, node_id: object) -> bool:
        resolved = self._navigation.node(_node_id(node_id)).node_id
        return resolved in self._expanded

    def expand(self, node_id: object) -> bool:
        resolved = self._navigation.node(_node_id(node_id)).node_id
        if not self._navigation.child_ids(resolved) or resolved in self._expanded:
            return False
        self._expanded.add(resolved)
        return True

    def collapse(self, node_id: object) -> bool:
        resolved = self._navigation.node(_node_id(node_id)).node_id
        if resolved not in self._expanded:
            return False
        self._expanded.remove(resolved)
        return True

    def toggle(self, node_id: object) -> bool:
        resolved = self._navigation.node(_node_id(node_id)).node_id
        if not self._navigation.child_ids(resolved):
            return False
        if resolved in self._expanded:
            self._expanded.remove(resolved)
        else:
            self._expanded.add(resolved)
        return True

    def reveal(self, node_id: object) -> DesignerHierarchyReveal:
        """Expand every ancestor required to make ``node_id`` visible."""

        reveal = self._navigation.reveal(_node_id(node_id))
        for ancestor_id in reveal.ancestor_ids:
            if self._navigation.child_ids(ancestor_id):
                self._expanded.add(ancestor_id)
        return reveal

    def rows(
        self,
        selection: DesignerSelectionState | None = None,
    ) -> tuple[DesignerHierarchyRow, ...]:
        """Return visible rows in deterministic snapshot/preorder order."""

        state = _selection_state(selection)
        result: list[DesignerHierarchyRow] = []

        def visit(node_id: str, depth: int) -> None:
            node = self._navigation.node(node_id)
            child_ids = self._navigation.child_ids(node_id)
            expanded = node_id in self._expanded and bool(child_ids)
            result.append(
                DesignerHierarchyRow(
                    node_id=node_id,
                    type_key=node.type_key,
                    depth=depth,
                    parent_id=self._navigation.parent_id(node_id) or "",
                    child_count=len(child_ids),
                    expanded=expanded,
                    selected=node_id == state.selected_id,
                    focused=node_id == state.focused_id,
                )
            )
            if expanded:
                for child_id in child_ids:
                    visit(child_id, depth + 1)

        visit(self._navigation.root_id, 0)
        return tuple(result)

    def visible_ids(
        self,
        selection: DesignerSelectionState | None = None,
    ) -> tuple[str, ...]:
        return tuple(row.node_id for row in self.rows(selection))

    def row(
        self,
        node_id: object,
        selection: DesignerSelectionState | None = None,
    ) -> DesignerHierarchyRow | None:
        resolved = self._navigation.node(_node_id(node_id)).node_id
        return next((row for row in self.rows(selection) if row.node_id == resolved), None)

    def reconcile(self, snapshot: DesignerSnapshot) -> bool:
        """Rebind to a new accepted snapshot while preserving surviving state.

        Expanded IDs survive property edits, moves, reparenting and undo/redo
        while their node still exists and remains expandable.  Removed nodes or
        nodes that become leaves are discarded.  If a custom edit replaces the
        root identity entirely, the new root begins expanded when possible.
        """

        after = _require_snapshot(snapshot)
        before_root = self._navigation.root_id
        before_expanded = set(self._expanded)

        navigation = DesignerHierarchyNavigator(after)
        surviving = set(navigation.preorder_ids)
        expanded = {
            node_id
            for node_id in before_expanded
            if node_id in surviving and navigation.child_ids(node_id)
        }

        if navigation.root_id != before_root and navigation.child_ids(navigation.root_id):
            expanded.add(navigation.root_id)

        changed = expanded != before_expanded
        self._snapshot = after
        self._navigation = navigation
        self._expanded = expanded
        return changed


__all__ = [
    "DesignerHierarchyProjection",
    "DesignerHierarchyProjectionState",
    "DesignerHierarchyRow",
]
