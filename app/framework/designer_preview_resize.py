"""Pointer-resize presentation bridge for optional designer previews.

The designer workspace already owns immutable document/history state, selected
stable IDs and transactional preview replacement.  This module adds only a
backend-neutral coordinator for resizing the *currently selected* rendered
component.  Concrete hosts own pointer hit-testing, drag feedback and native
handle geometry; a completed gesture is committed once through the existing
``layout.width`` / ``layout.height`` edit contract.

No toolkit is imported here and no drag state is persisted in project data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from .components.base import Component
from .designer_editing import CompositeDesignerEdit, SetDesignerProperty
from .designer_workspace import DesignerWorkspace


DesignerPreviewResizeChangeHandler = Callable[[str, int, int], object]
DesignerPreviewResizeErrorHandler = Callable[[str, Exception], object]


@dataclass(frozen=True)
class DesignerPreviewResizeTarget:
    """Current selected preview component plus resize capabilities."""

    node_id: str
    component: Component
    width: int | None
    height: int | None
    can_resize_width: bool
    can_resize_height: bool

    @property
    def resizable(self) -> bool:
        return self.can_resize_width or self.can_resize_height

    def to_descriptor(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "width": self.width,
            "height": self.height,
            "can_resize_width": self.can_resize_width,
            "can_resize_height": self.can_resize_height,
        }


@dataclass
class DesignerPreviewResizeBinding:
    """Opaque host-owned pointer surface for one current target."""

    surface: object
    target: object | None = None
    metadata: object | None = None


@runtime_checkable
class DesignerPreviewResizeHost(Protocol):
    """Concrete pointer/handle adapter consumed by the resize surface."""

    def build(
        self,
        target: DesignerPreviewResizeTarget | None,
        *,
        parent: object,
        on_resize: Callable[[str, int, int], bool],
    ) -> DesignerPreviewResizeBinding:
        ...

    def update(
        self,
        binding: DesignerPreviewResizeBinding,
        target: DesignerPreviewResizeTarget | None,
    ) -> None:
        ...

    def exists(self, binding: DesignerPreviewResizeBinding) -> bool:
        ...

    def dispose(self, binding: DesignerPreviewResizeBinding) -> None:
        ...


def _host_errors(host: object) -> tuple[str, ...]:
    required = ("build", "update", "exists", "dispose")
    return tuple(name for name in required if not callable(getattr(host, name, None)))


def _positive_pixel(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"designer preview resize {field} must be an integer")
    resolved = int(value)
    if resolved <= 0:
        raise ValueError(f"designer preview resize {field} must be positive")
    return resolved


class DesignerPreviewResizeSurface:
    """Coordinate one selected-component pointer resize gesture.

    Native hosts may temporarily resize the live preview item while the pointer
    moves, but a release commits at most one checked ``CompositeDesignerEdit``.
    The stable selected ID is revalidated immediately before commit, so stale
    native callbacks cannot resize a newly selected node.
    """

    def __init__(
        self,
        workspace: DesignerWorkspace,
        host: DesignerPreviewResizeHost,
        *,
        on_change: DesignerPreviewResizeChangeHandler | None = None,
        on_error: DesignerPreviewResizeErrorHandler | None = None,
    ):
        if not isinstance(workspace, DesignerWorkspace):
            raise TypeError("designer preview resize surface requires DesignerWorkspace")
        missing = _host_errors(host)
        if missing:
            raise TypeError(
                "designer preview resize host does not satisfy DesignerPreviewResizeHost; missing: "
                + ", ".join(missing)
            )
        if on_change is not None and not callable(on_change):
            raise TypeError("designer preview resize change handler must be callable")
        if on_error is not None and not callable(on_error):
            raise TypeError("designer preview resize error handler must be callable")
        self._workspace = workspace
        self._host = host
        self._on_change = on_change
        self._on_error = on_error
        self._parent: object | None = None
        self._binding: DesignerPreviewResizeBinding | None = None
        self._generation = -1

    @property
    def workspace(self) -> DesignerWorkspace:
        return self._workspace

    @property
    def binding(self) -> DesignerPreviewResizeBinding | None:
        return self._binding

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def target(self) -> DesignerPreviewResizeTarget | None:
        if self._workspace.closed:
            raise RuntimeError("designer workspace is closed")
        node_id = self._workspace.session.selected_node_id
        if not node_id:
            return None

        inspector = self._workspace.inspector_state()
        try:
            width_row = inspector.row("layout.width")
        except KeyError:
            width_row = None
        try:
            height_row = inspector.row("layout.height")
        except KeyError:
            height_row = None

        can_width = bool(width_row is not None and width_row.can_edit)
        can_height = bool(height_row is not None and height_row.can_edit)
        if not (can_width or can_height):
            return None

        component = self._workspace.preview_host.component(node_id)
        resolved = component.resolved_layout
        width = resolved.width if resolved is not None and isinstance(resolved.width, int) else None
        height = resolved.height if resolved is not None and isinstance(resolved.height, int) else None
        return DesignerPreviewResizeTarget(
            node_id=node_id,
            component=component,
            width=width,
            height=height,
            can_resize_width=can_width,
            can_resize_height=can_height,
        )

    def build(self, *, parent: object) -> DesignerPreviewResizeBinding:
        if self.exists():
            raise RuntimeError("designer preview resize surface is already built")
        binding = self._host.build(self.target, parent=parent, on_resize=self.resize)
        if not isinstance(binding, DesignerPreviewResizeBinding):
            raise TypeError("designer preview resize host must return DesignerPreviewResizeBinding")
        self._parent = parent
        self._binding = binding
        self._generation = self._workspace.state.preview_generation
        return binding

    def exists(self) -> bool:
        return bool(self._binding is not None and self._host.exists(self._binding))

    def require_binding(self) -> DesignerPreviewResizeBinding:
        if not self.exists():
            raise RuntimeError(
                "designer preview resize surface is not built or its backend binding is stale"
            )
        assert self._binding is not None
        return self._binding

    def refresh(self) -> DesignerPreviewResizeBinding:
        target = self.target
        if self._binding is None or not self._host.exists(self._binding):
            if self._parent is None:
                raise RuntimeError("designer preview resize surface must be built before refresh")
            return self.build(parent=self._parent)
        self._host.update(self._binding, target)
        self._generation = self._workspace.state.preview_generation
        return self._binding

    def resize(self, node_id: str, width: int, height: int) -> bool:
        """Commit one completed pointer resize through checked designer history."""

        try:
            target = self.target
            if target is None:
                raise RuntimeError("designer preview resize requires a selected resizable node")
            resolved_id = str(node_id or "").strip()
            if not resolved_id:
                raise ValueError("designer preview resize node id must be non-empty")
            if resolved_id != target.node_id:
                raise RuntimeError("designer preview resize callback is stale for current selection")

            resolved_width = _positive_pixel(width, field="width")
            resolved_height = _positive_pixel(height, field="height")
            commands = []
            if target.can_resize_width and target.width != resolved_width:
                commands.append(SetDesignerProperty(target.node_id, "layout.width", resolved_width))
            if target.can_resize_height and target.height != resolved_height:
                commands.append(SetDesignerProperty(target.node_id, "layout.height", resolved_height))
            if not commands:
                self.refresh()
                return False

            changed = self._workspace.execute(
                CompositeDesignerEdit(commands, label="Resize component")
            )
            self.refresh()
            if changed and self._on_change is not None:
                current = self.target
                final_width = resolved_width if current is None or current.width is None else current.width
                final_height = resolved_height if current is None or current.height is None else current.height
                self._on_change(target.node_id, int(final_width), int(final_height))
            return changed
        except Exception as exc:
            if self._binding is not None and self._host.exists(self._binding):
                try:
                    self._host.update(self._binding, self.target)
                except Exception:
                    pass
            if self._on_error is not None:
                self._on_error(str(node_id or ""), exc)
                return False
            raise

    def dispose(self) -> bool:
        binding = self._binding
        self._binding = None
        self._generation = -1
        if binding is None:
            return False
        if self._host.exists(binding):
            self._host.dispose(binding)
        return True


__all__ = [
    "DesignerPreviewResizeBinding",
    "DesignerPreviewResizeChangeHandler",
    "DesignerPreviewResizeErrorHandler",
    "DesignerPreviewResizeHost",
    "DesignerPreviewResizeSurface",
    "DesignerPreviewResizeTarget",
]
