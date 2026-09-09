"""Clickable preview-selection presentation bridge for optional designer tooling.

The existing designer workspace already owns stable-ID selection/focus,
hierarchy reveal state and transactional preview replacement.  This module adds
only a backend-neutral presentation coordinator that exposes the currently
rendered preview components as disposable click targets to an injected host.
It never owns document, selection, hierarchy, history, inspector or preview
semantics and imports no GUI toolkit.

Concrete hosts may use native hit-testing/bindings and draw a transient visual
selection outline.  Every interaction is revalidated against the current
``DesignerWorkspace`` before selection changes, and ``refresh()`` rebinds after
whole-preview replacement by using the latest stable-ID/component mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from .components.base import Component
from .designer_workspace import DesignerWorkspace


DesignerPreviewSelectionChangeHandler = Callable[[str], object]


@dataclass(frozen=True)
class DesignerPreviewSelectionTarget:
    """One ephemeral rendered preview target keyed by stable designer ID."""

    node_id: str
    component: Component
    depth: int
    selected: bool
    focused: bool


@dataclass
class DesignerPreviewSelectionBinding:
    """Opaque host-owned interaction surface plus stable-ID native bindings."""

    surface: object
    targets: dict[str, object]
    metadata: object | None = None


@runtime_checkable
class DesignerPreviewSelectionHost(Protocol):
    """Concrete adapter contract consumed by ``DesignerPreviewSelectionSurface``."""

    def build(
        self,
        targets: tuple[DesignerPreviewSelectionTarget, ...],
        *,
        parent: object,
        on_select: Callable[[str], object],
    ) -> DesignerPreviewSelectionBinding:
        ...

    def update(
        self,
        binding: DesignerPreviewSelectionBinding,
        targets: tuple[DesignerPreviewSelectionTarget, ...],
    ) -> None:
        ...

    def exists(self, binding: DesignerPreviewSelectionBinding) -> bool:
        ...

    def dispose(self, binding: DesignerPreviewSelectionBinding) -> None:
        ...


def _host_errors(host: object) -> tuple[str, ...]:
    required = ("build", "update", "exists", "dispose")
    return tuple(name for name in required if not callable(getattr(host, name, None)))


def _node_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("designer preview-selection node id must be non-empty")
    return text


class DesignerPreviewSelectionSurface:
    """Present clickable preview targets without becoming a semantic owner.

    Stable selection/focus and hierarchy expansion remain in
    :class:`DesignerWorkspace`.  The host receives current live preview
    components only as disposable presentation targets.  A whole-preview
    rebuild invalidates native items, so callers should invoke ``refresh()``
    after accepted document/history operations that advance preview generation.
    """

    def __init__(
        self,
        workspace: DesignerWorkspace,
        host: DesignerPreviewSelectionHost,
        *,
        on_change: DesignerPreviewSelectionChangeHandler | None = None,
    ):
        if not isinstance(workspace, DesignerWorkspace):
            raise TypeError("designer preview-selection surface requires DesignerWorkspace")
        missing = _host_errors(host)
        if missing:
            raise TypeError(
                "designer preview-selection host does not satisfy "
                "DesignerPreviewSelectionHost; missing: " + ", ".join(missing)
            )
        if on_change is not None and not callable(on_change):
            raise TypeError("designer preview-selection change handler must be callable")
        self._workspace = workspace
        self._host = host
        self._on_change = on_change
        self._parent: object | None = None
        self._binding: DesignerPreviewSelectionBinding | None = None
        self._generation = -1

    @property
    def workspace(self) -> DesignerWorkspace:
        return self._workspace

    @property
    def binding(self) -> DesignerPreviewSelectionBinding | None:
        return self._binding

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def targets(self) -> tuple[DesignerPreviewSelectionTarget, ...]:
        if self._workspace.closed:
            raise RuntimeError("designer workspace is closed")
        preview = self._workspace.preview_host.preview
        selected = self._workspace.session.selected_node_id
        focused = self._workspace.session.focused_node_id
        targets: list[DesignerPreviewSelectionTarget] = []

        def visit(node, depth: int) -> None:
            component = preview.component(node.node_id)
            targets.append(
                DesignerPreviewSelectionTarget(
                    node_id=node.node_id,
                    component=component,
                    depth=depth,
                    selected=node.node_id == selected,
                    focused=node.node_id == focused,
                )
            )
            for child in node.children:
                visit(child.node, depth + 1)

        visit(preview.source_snapshot.root, 0)
        return tuple(targets)

    @property
    def selected_id(self) -> str:
        return self._workspace.session.selected_node_id

    def build(self, *, parent: object) -> DesignerPreviewSelectionBinding:
        if self.exists():
            raise RuntimeError("designer preview-selection surface is already built")
        targets = self.targets
        binding = self._host.build(
            targets,
            parent=parent,
            on_select=self.select,
        )
        if not isinstance(binding, DesignerPreviewSelectionBinding):
            raise TypeError(
                "designer preview-selection host must return "
                "DesignerPreviewSelectionBinding"
            )
        expected = tuple(target.node_id for target in targets)
        if tuple(binding.targets) != expected:
            try:
                self._host.dispose(binding)
            finally:
                raise ValueError(
                    "designer preview-selection host returned target bindings "
                    "in an unexpected shape"
                )
        self._parent = parent
        self._binding = binding
        self._generation = self._workspace.state.preview_generation
        return binding

    def exists(self) -> bool:
        return bool(self._binding is not None and self._host.exists(self._binding))

    def require_binding(self) -> DesignerPreviewSelectionBinding:
        if not self.exists():
            raise RuntimeError(
                "designer preview-selection surface is not built or its backend binding is stale"
            )
        assert self._binding is not None
        return self._binding

    def refresh(self) -> DesignerPreviewSelectionBinding:
        """Rebind current preview items and refresh the visual selection state."""

        targets = self.targets
        if self._binding is None or not self._host.exists(self._binding):
            if self._parent is None:
                raise RuntimeError(
                    "designer preview-selection surface must be built before refresh"
                )
            return self.build(parent=self._parent)
        self._host.update(self._binding, targets)
        self._generation = self._workspace.state.preview_generation
        return self._binding

    def _target(self, node_id: object) -> DesignerPreviewSelectionTarget:
        resolved = _node_id(node_id)
        for target in self.targets:
            if target.node_id == resolved:
                return target
        raise KeyError(f"designer preview-selection node not found: {resolved}")

    def select(self, node_id: object) -> bool:
        """Select/focus one current preview target and reveal it in hierarchy."""

        target = self._target(node_id)
        changed = self._workspace.select_and_focus_node(target.node_id)
        self._workspace.reveal_selected_in_hierarchy()
        self.refresh()
        if self._on_change is not None:
            self._on_change(target.node_id)
        return changed

    def dispose(self) -> bool:
        binding = self._binding
        self._binding = None
        self._generation = -1
        if binding is None:
            return False
        try:
            if self._host.exists(binding):
                self._host.dispose(binding)
        finally:
            binding.targets.clear()
        return True


__all__ = [
    "DesignerPreviewSelectionBinding",
    "DesignerPreviewSelectionChangeHandler",
    "DesignerPreviewSelectionHost",
    "DesignerPreviewSelectionSurface",
    "DesignerPreviewSelectionTarget",
]
