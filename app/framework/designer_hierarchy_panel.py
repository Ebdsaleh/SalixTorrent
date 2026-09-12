"""Concrete hierarchy-panel presentation bridge for optional designer tooling.

The backend-neutral designer hierarchy model already owns stable node identity,
visible-row projection and ephemeral expanded/collapsed state.  This module is
only the presentation coordinator between one existing ``DesignerWorkspace``
and an injected hierarchy-panel host.  It never owns document, selection,
expansion, history, inspector or preview semantics and imports no GUI toolkit.

Concrete Dear PyGui/Tkinter hosts may rebuild their native row widgets whenever
this presenter refreshes.  The semantic source of truth remains the workspace;
backend items are disposable presentation bindings rather than designer state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from .designer_hierarchy import DesignerHierarchyRow
from .designer_hierarchy_drag import plan_hierarchy_reparent
from .designer_navigation import DesignerHierarchyReveal
from .designer_workspace import DesignerWorkspace


DesignerHierarchyPanelChangeHandler = Callable[[], object]
DesignerHierarchyPanelErrorHandler = Callable[[Exception], object]


@dataclass
class DesignerHierarchyPanelBinding:
    """Opaque host-owned hierarchy panel plus visible stable-ID row bindings."""

    panel: object
    rows: dict[str, object]
    title_item: object | None = None
    metadata: object | None = None


@runtime_checkable
class DesignerHierarchyPanelHost(Protocol):
    """Concrete adapter contract consumed by ``DesignerHierarchyPanel``."""

    def build(
        self,
        rows: tuple[DesignerHierarchyRow, ...],
        *,
        parent: object,
        title: str = "",
        on_select: Callable[[str], object],
        on_toggle: Callable[[str], object],
        on_reparent: Callable[[str, str], object],
    ) -> DesignerHierarchyPanelBinding:
        ...

    def update(
        self,
        binding: DesignerHierarchyPanelBinding,
        rows: tuple[DesignerHierarchyRow, ...],
    ) -> None:
        ...

    def exists(self, binding: DesignerHierarchyPanelBinding) -> bool:
        ...

    def dispose(self, binding: DesignerHierarchyPanelBinding) -> None:
        ...


def _host_errors(host: object) -> tuple[str, ...]:
    required = ("build", "update", "exists", "dispose")
    return tuple(name for name in required if not callable(getattr(host, name, None)))


def _node_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("designer hierarchy panel node id must be non-empty")
    return text


class DesignerHierarchyPanel:
    """Present current workspace hierarchy rows through one concrete host.

    Selection and expansion are always delegated back through
    ``DesignerWorkspace``.  ``refresh()`` re-reads the complete visible-row
    projection and lets the host replace presentation items as needed; no
    incremental toolkit mutation contract is implied by this first surface.
    """

    def __init__(
        self,
        workspace: DesignerWorkspace,
        host: DesignerHierarchyPanelHost,
        *,
        title: str = "Hierarchy",
        on_change: DesignerHierarchyPanelChangeHandler | None = None,
        on_error: DesignerHierarchyPanelErrorHandler | None = None,
    ):
        if not isinstance(workspace, DesignerWorkspace):
            raise TypeError("designer hierarchy panel requires DesignerWorkspace")
        missing = _host_errors(host)
        if missing:
            raise TypeError(
                "designer hierarchy panel host does not satisfy "
                "DesignerHierarchyPanelHost; missing: " + ", ".join(missing)
            )
        if on_change is not None and not callable(on_change):
            raise TypeError("designer hierarchy panel change handler must be callable")
        if on_error is not None and not callable(on_error):
            raise TypeError("designer hierarchy panel error handler must be callable")
        self._workspace = workspace
        self._host = host
        self._title = str(title)
        self._on_change = on_change
        self._on_error = on_error
        self._parent: object | None = None
        self._binding: DesignerHierarchyPanelBinding | None = None

    @property
    def workspace(self) -> DesignerWorkspace:
        return self._workspace

    @property
    def binding(self) -> DesignerHierarchyPanelBinding | None:
        return self._binding

    @property
    def rows(self) -> tuple[DesignerHierarchyRow, ...]:
        return self._workspace.state.hierarchy_rows

    @property
    def visible_ids(self) -> tuple[str, ...]:
        return tuple(row.node_id for row in self.rows)

    def build(self, *, parent: object) -> DesignerHierarchyPanelBinding:
        if self.exists():
            raise RuntimeError("designer hierarchy panel is already built")
        rows = self.rows
        binding = self._host.build(
            rows,
            parent=parent,
            title=self._title,
            on_select=self.select,
            on_toggle=self.toggle,
            on_reparent=self.reparent,
        )
        if not isinstance(binding, DesignerHierarchyPanelBinding):
            raise TypeError(
                "designer hierarchy panel host must return DesignerHierarchyPanelBinding"
            )
        expected = tuple(row.node_id for row in rows)
        if tuple(binding.rows) != expected:
            try:
                self._host.dispose(binding)
            finally:
                raise ValueError(
                    "designer hierarchy panel host returned row bindings in an unexpected shape"
                )
        self._parent = parent
        self._binding = binding
        return binding

    def exists(self) -> bool:
        return bool(
            self._binding is not None
            and self._host.exists(self._binding)
        )

    def require_binding(self) -> DesignerHierarchyPanelBinding:
        if not self.exists():
            raise RuntimeError(
                "designer hierarchy panel is not built or its backend binding is stale"
            )
        assert self._binding is not None
        return self._binding

    def refresh(self) -> DesignerHierarchyPanelBinding:
        """Render the current visible-row projection without taking ownership."""

        rows = self.rows
        if self._binding is None or not self._host.exists(self._binding):
            if self._parent is None:
                raise RuntimeError("designer hierarchy panel must be built before refresh")
            return self.build(parent=self._parent)
        self._host.update(self._binding, rows)
        return self._binding

    def _visible_row(self, node_id: object) -> DesignerHierarchyRow:
        resolved = _node_id(node_id)
        for row in self.rows:
            if row.node_id == resolved:
                return row
        raise KeyError(f"designer hierarchy panel row is not visible: {resolved}")

    def _notify_change(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def select(self, node_id: object) -> bool:
        """Select/focus one currently visible row through the workspace owner."""

        row = self._visible_row(node_id)
        changed = self._workspace.select_and_focus_node(row.node_id)
        self.refresh()
        self._notify_change()
        return changed

    def toggle(self, node_id: object) -> bool:
        """Toggle one visible expandable row through the workspace owner."""

        row = self._visible_row(node_id)
        if not row.expandable:
            return False
        changed = self._workspace.toggle_hierarchy_node(row.node_id)
        self.refresh()
        self._notify_change()
        return changed

    def reparent(self, node_id: object, parent_id: object) -> bool:
        """Append one dragged node beneath an unambiguous simple container.

        Native hosts report stable IDs only.  Slot/relationship policy is
        resolved here from the immutable designer snapshot before the existing
        checked reparent transaction runs.
        """

        try:
            plan = plan_hierarchy_reparent(
                self._workspace.session.snapshot,
                node_id,
                parent_id,
            )
            changed = self._workspace.reparent_node(
                plan.node_id,
                plan.parent_id,
                index=plan.index,
                slot=plan.slot,
                metadata=None,
                preserve_metadata=False,
            )
            if not changed:
                return False
            self._workspace.select_and_focus_node(plan.node_id)
            self._workspace.expand_hierarchy_node(plan.parent_id)
            self._workspace.reveal_selected_in_hierarchy()
            self.refresh()
            self._notify_change()
            return True
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            if self._on_error is not None:
                self._on_error(exc)
                return False
            raise

    def reveal_selected(self) -> DesignerHierarchyReveal | None:
        """Reveal the current selection using existing hierarchy semantics."""

        reveal = self._workspace.reveal_selected_in_hierarchy()
        self.refresh()
        self._notify_change()
        return reveal

    def dispose(self) -> bool:
        binding = self._binding
        self._binding = None
        if binding is None:
            return False
        try:
            if self._host.exists(binding):
                self._host.dispose(binding)
        finally:
            binding.rows.clear()
        return True


__all__ = [
    "DesignerHierarchyPanel",
    "DesignerHierarchyPanelChangeHandler",
    "DesignerHierarchyPanelErrorHandler",
    "DesignerHierarchyPanelBinding",
    "DesignerHierarchyPanelHost",
]
