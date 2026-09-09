"""Stable-ID selection/focus state for optional designer tooling.

This module deliberately models *editor interaction state*, not application
state and not project-document data.  Selection and keyboard/navigation focus
are stored only as designer node IDs, so they survive preview reconstruction
without retaining toolkit objects or stale component instances.

Code-first applications do not depend on this module.  Designer surfaces may
use it to coordinate hierarchy trees, inspectors and preview highlighting over
the same immutable ``DesignerSnapshot`` document used by the editing layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .designer import DesignerNode, DesignerSnapshot
from .designer_structure import DesignerNodeLocation, locate_designer_node


def _node_id(value: object, *, field: str = "designer node id") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


def _require_snapshot(snapshot: DesignerSnapshot) -> DesignerSnapshot:
    if not isinstance(snapshot, DesignerSnapshot):
        raise TypeError("designer selection requires DesignerSnapshot")
    return snapshot


def _node_ids(snapshot: DesignerSnapshot) -> set[str]:
    return {node.node_id for node in snapshot.root.walk()}


def _require_node(snapshot: DesignerSnapshot, node_id: object) -> str:
    resolved = _node_id(node_id)
    if resolved not in _node_ids(_require_snapshot(snapshot)):
        raise KeyError(f"designer node not found: {resolved}")
    return resolved


def _find_node(snapshot: DesignerSnapshot, node_id: str) -> DesignerNode:
    for node in snapshot.root.walk():
        if node.node_id == node_id:
            return node
    raise KeyError(f"designer node not found: {node_id}")


def _nearest_surviving_ancestor(
    before: DesignerSnapshot,
    after: DesignerSnapshot,
    node_id: str,
) -> str:
    """Return the nearest ancestor from *before* that still exists in *after*.

    The node itself is returned when it survives.  If the entire previous
    ancestry disappears (for example a custom command replaces the root), the
    selection is cleared instead of silently selecting an unrelated new root.
    """

    if not node_id:
        return ""
    surviving = _node_ids(after)
    if node_id in surviving:
        return node_id

    current = node_id
    while current:
        try:
            location = locate_designer_node(before, current)
        except KeyError:
            return ""
        parent_id = location.parent_id or ""
        if parent_id and parent_id in surviving:
            return parent_id
        current = parent_id
    return ""


@dataclass(frozen=True)
class DesignerSelectionState:
    """Immutable snapshot of ephemeral designer selection/focus identities."""

    selected_id: str = ""
    focused_id: str = ""

    @property
    def has_selection(self) -> bool:
        return bool(self.selected_id)

    @property
    def has_focus(self) -> bool:
        return bool(self.focused_id)


class DesignerSelectionModel:
    """Single-selection + single-focus state over stable designer node IDs.

    Selection and focus are intentionally distinct.  A hierarchy/preview may
    keep one object selected while keyboard focus moves to an inspector or a
    different node.  Neither state participates in dirty tracking, undo/redo or
    serialization.
    """

    def __init__(
        self,
        snapshot: DesignerSnapshot | None = None,
        *,
        selected: object | None = None,
        focused: object | None = None,
    ):
        self._selected_id = ""
        self._focused_id = ""
        if snapshot is None:
            if selected is not None or focused is not None:
                raise ValueError("initial designer selection requires a snapshot")
            return
        _require_snapshot(snapshot)
        if selected is not None and str(selected).strip():
            self._selected_id = _require_node(snapshot, selected)
        if focused is not None and str(focused).strip():
            self._focused_id = _require_node(snapshot, focused)

    @property
    def state(self) -> DesignerSelectionState:
        return DesignerSelectionState(self._selected_id, self._focused_id)

    @property
    def selected_id(self) -> str:
        return self._selected_id

    @property
    def focused_id(self) -> str:
        return self._focused_id

    @property
    def has_selection(self) -> bool:
        return bool(self._selected_id)

    @property
    def has_focus(self) -> bool:
        return bool(self._focused_id)

    def select(
        self,
        snapshot: DesignerSnapshot,
        node_id: object,
        *,
        focus: bool = False,
    ) -> bool:
        resolved = _require_node(snapshot, node_id)
        changed = resolved != self._selected_id
        self._selected_id = resolved
        if focus:
            changed = self.focus(snapshot, resolved) or changed
        return changed

    def focus(
        self,
        snapshot: DesignerSnapshot,
        node_id: object,
        *,
        select: bool = False,
    ) -> bool:
        resolved = _require_node(snapshot, node_id)
        changed = resolved != self._focused_id
        self._focused_id = resolved
        if select:
            changed = self.select(snapshot, resolved) or changed
        return changed

    def select_and_focus(self, snapshot: DesignerSnapshot, node_id: object) -> bool:
        resolved = _require_node(snapshot, node_id)
        changed = resolved != self._selected_id or resolved != self._focused_id
        self._selected_id = resolved
        self._focused_id = resolved
        return changed

    def clear_selection(self) -> bool:
        changed = bool(self._selected_id)
        self._selected_id = ""
        return changed

    def clear_focus(self) -> bool:
        changed = bool(self._focused_id)
        self._focused_id = ""
        return changed

    def clear(self) -> bool:
        changed = self.clear_selection()
        return self.clear_focus() or changed

    def selected_node(self, snapshot: DesignerSnapshot) -> DesignerNode | None:
        _require_snapshot(snapshot)
        if not self._selected_id:
            return None
        return _find_node(snapshot, self._selected_id)

    def focused_node(self, snapshot: DesignerSnapshot) -> DesignerNode | None:
        _require_snapshot(snapshot)
        if not self._focused_id:
            return None
        return _find_node(snapshot, self._focused_id)

    def selected_location(
        self,
        snapshot: DesignerSnapshot,
    ) -> DesignerNodeLocation | None:
        _require_snapshot(snapshot)
        if not self._selected_id:
            return None
        return locate_designer_node(snapshot, self._selected_id)

    def focused_location(
        self,
        snapshot: DesignerSnapshot,
    ) -> DesignerNodeLocation | None:
        _require_snapshot(snapshot)
        if not self._focused_id:
            return None
        return locate_designer_node(snapshot, self._focused_id)

    def reconcile(
        self,
        before: DesignerSnapshot,
        after: DesignerSnapshot,
    ) -> bool:
        """Retain IDs that survive, otherwise fall back to surviving ancestors.

        This is called after accepted document edits/undo/redo.  It keeps
        selection stable across property changes, moves and preview rebuilds;
        deleting a selected/focused subtree falls back to its nearest surviving
        ancestor.  The selection state itself is not added to edit history.
        """

        _require_snapshot(before)
        _require_snapshot(after)
        selected = _nearest_surviving_ancestor(before, after, self._selected_id)
        focused = _nearest_surviving_ancestor(before, after, self._focused_id)
        changed = selected != self._selected_id or focused != self._focused_id
        self._selected_id = selected
        self._focused_id = focused
        return changed


__all__ = [
    "DesignerSelectionModel",
    "DesignerSelectionState",
]
