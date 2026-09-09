"""Concrete property-inspector presentation bridge for optional designer tooling.

The backend-neutral designer inspector already projects selected-node property
metadata, editor hints and edit/clear affordances.  This module is only the
presentation coordinator between one existing :class:`DesignerWorkspace` and
an injected inspector-panel host.  It never owns document, selection, history,
validation or preview state and imports no GUI toolkit.

Concrete Dear PyGui/Tkinter hosts may rebuild their native editor widgets on
every refresh.  The workspace remains authoritative: edits still flow through
``DesignerPreviewHost`` / ``DesignerEditSession`` so validation, undo/redo,
dirty tracking and transactional preview replacement keep their existing
semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable, Protocol, runtime_checkable

from .designer_inspector import (
    DesignerInspectorEditorKind,
    DesignerInspectorRow,
    DesignerInspectorState,
)
from .designer_workspace import DesignerWorkspace


DesignerInspectorPanelChangeHandler = Callable[[DesignerInspectorState], object]
DesignerInspectorPanelErrorHandler = Callable[[str, Exception], object]


@dataclass
class DesignerInspectorPanelBinding:
    """Opaque host-owned panel plus stable property-key row bindings."""

    panel: object
    rows: dict[str, object]
    title_item: object | None = None
    target_item: object | None = None
    metadata: object | None = None


@runtime_checkable
class DesignerInspectorPanelHost(Protocol):
    """Concrete adapter contract consumed by :class:`DesignerInspectorPanel`."""

    def build(
        self,
        state: DesignerInspectorState,
        *,
        parent: object,
        title: str = "",
        on_set: Callable[[str, str, object], object],
        on_clear: Callable[[str, str], object],
        on_error: Callable[[str, str, Exception], object],
    ) -> DesignerInspectorPanelBinding:
        ...

    def update(
        self,
        binding: DesignerInspectorPanelBinding,
        state: DesignerInspectorState,
    ) -> None:
        ...

    def exists(self, binding: DesignerInspectorPanelBinding) -> bool:
        ...

    def dispose(self, binding: DesignerInspectorPanelBinding) -> None:
        ...


def _host_errors(host: object) -> tuple[str, ...]:
    required = ("build", "update", "exists", "dispose")
    return tuple(name for name in required if not callable(getattr(host, name, None)))


def _property_key(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("designer inspector panel property key must be non-empty")
    return text


def _node_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("designer inspector panel node id must be non-empty")
    return text


def format_inspector_editor_value(row: DesignerInspectorRow) -> object:
    """Return a deterministic host-friendly representation of one row value.

    Scalar controls keep their native scalar value.  List/inset values use
    compact JSON so both desktop adapters share one unambiguous text format.
    An unset or explicit ``None`` value renders as an empty editor; concrete
    hosts expose separate ``Default`` / ``None`` affordances so those states do
    not have to be encoded into the editable text itself.
    """

    if not isinstance(row, DesignerInspectorRow):
        raise TypeError("inspector editor formatting requires DesignerInspectorRow")
    if not row.is_set or row.value is None:
        return ""

    if row.editor is DesignerInspectorEditorKind.TOGGLE:
        return bool(row.value)
    if row.editor is DesignerInspectorEditorKind.CHOICE:
        return row.value
    if row.editor in {
        DesignerInspectorEditorKind.STRING_LIST,
        DesignerInspectorEditorKind.NUMBER_LIST,
        DesignerInspectorEditorKind.INSETS,
    }:
        return json.dumps(row.value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(row.value)


def parse_inspector_editor_text(row: DesignerInspectorRow, value: object) -> object:
    """Parse one text-based concrete editor value into semantic Python data.

    This is a renderer-neutral presentation codec only.  It deliberately does
    not duplicate property validation; the parsed value is still validated by
    the existing designer edit/session contract when the workspace applies it.
    """

    if not isinstance(row, DesignerInspectorRow):
        raise TypeError("inspector editor parsing requires DesignerInspectorRow")
    text = str(value)

    if row.editor is DesignerInspectorEditorKind.TEXT:
        return text
    if row.editor is DesignerInspectorEditorKind.INTEGER:
        return int(text.strip())
    if row.editor is DesignerInspectorEditorKind.NUMBER:
        return float(text.strip())
    if row.editor is DesignerInspectorEditorKind.DIMENSION:
        resolved = text.strip().lower()
        if resolved in {"auto", "fill"}:
            return resolved
        return int(resolved)
    if row.editor in {
        DesignerInspectorEditorKind.STRING_LIST,
        DesignerInspectorEditorKind.NUMBER_LIST,
        DesignerInspectorEditorKind.INSETS,
    }:
        return json.loads(text)
    raise TypeError(f"{row.editor.value} inspector editors do not use text parsing")


class DesignerInspectorPanel:
    """Present the workspace's current inspector projection through one host."""

    def __init__(
        self,
        workspace: DesignerWorkspace,
        host: DesignerInspectorPanelHost,
        *,
        title: str = "Inspector",
        on_change: DesignerInspectorPanelChangeHandler | None = None,
        on_error: DesignerInspectorPanelErrorHandler | None = None,
    ):
        if not isinstance(workspace, DesignerWorkspace):
            raise TypeError("designer inspector panel requires DesignerWorkspace")
        missing = _host_errors(host)
        if missing:
            raise TypeError(
                "designer inspector panel host does not satisfy "
                "DesignerInspectorPanelHost; missing: " + ", ".join(missing)
            )
        if on_change is not None and not callable(on_change):
            raise TypeError("designer inspector panel change handler must be callable")
        if on_error is not None and not callable(on_error):
            raise TypeError("designer inspector panel error handler must be callable")
        self._workspace = workspace
        self._host = host
        self._title = str(title)
        self._on_change = on_change
        self._on_error = on_error
        self._parent: object | None = None
        self._binding: DesignerInspectorPanelBinding | None = None

    @property
    def workspace(self) -> DesignerWorkspace:
        return self._workspace

    @property
    def binding(self) -> DesignerInspectorPanelBinding | None:
        return self._binding

    @property
    def state(self) -> DesignerInspectorState:
        return self._workspace.inspector_state()

    @property
    def rows(self) -> tuple[DesignerInspectorRow, ...]:
        return self.state.rows

    def build(self, *, parent: object) -> DesignerInspectorPanelBinding:
        if self.exists():
            raise RuntimeError("designer inspector panel is already built")
        state = self.state
        binding = self._host.build(
            state,
            parent=parent,
            title=self._title,
            on_set=self._host_set,
            on_clear=self._host_clear,
            on_error=self._host_error,
        )
        if not isinstance(binding, DesignerInspectorPanelBinding):
            raise TypeError(
                "designer inspector panel host must return DesignerInspectorPanelBinding"
            )
        self._validate_binding_shape(binding, state)
        self._parent = parent
        self._binding = binding
        return binding

    @staticmethod
    def _validate_binding_shape(
        binding: DesignerInspectorPanelBinding,
        state: DesignerInspectorState,
    ) -> None:
        expected = tuple(row.key for row in state.rows)
        if tuple(binding.rows) != expected:
            raise ValueError(
                "designer inspector panel host returned row bindings in an unexpected shape"
            )

    def exists(self) -> bool:
        return bool(self._binding is not None and self._host.exists(self._binding))

    def require_binding(self) -> DesignerInspectorPanelBinding:
        if not self.exists():
            raise RuntimeError(
                "designer inspector panel is not built or its backend binding is stale"
            )
        assert self._binding is not None
        return self._binding

    def refresh(self) -> DesignerInspectorPanelBinding:
        """Render the current selected-node property projection."""

        state = self.state
        if self._binding is None or not self._host.exists(self._binding):
            if self._parent is None:
                raise RuntimeError("designer inspector panel must be built before refresh")
            return self.build(parent=self._parent)
        self._host.update(self._binding, state)
        self._validate_binding_shape(self._binding, state)
        return self._binding

    def _current_row(
        self,
        property_key: object,
        *,
        expected_node_id: object | None = None,
    ) -> DesignerInspectorRow:
        state = self.state
        if not state.has_target:
            raise RuntimeError("designer inspector panel has no selected target")
        if expected_node_id is not None:
            expected = _node_id(expected_node_id)
            if expected != state.node_id:
                raise KeyError(
                    "designer inspector panel callback target is stale: "
                    f"{expected} != {state.node_id}"
                )
        key = _property_key(property_key)
        row = state.row(key)
        if row is None:
            raise KeyError(f"designer inspector panel property is unavailable: {key}")
        return row

    def _notify_change(self) -> None:
        if self._on_change is not None:
            self._on_change(self.state)

    def _report_error(self, property_key: object, exc: Exception) -> bool:
        if self._on_error is None:
            raise exc
        self._on_error(_property_key(property_key), exc)
        if self._binding is not None:
            try:
                self.refresh()
            except Exception:
                pass
        return False

    def _set_for_target(
        self,
        node_id: object,
        property_key: object,
        value: object,
    ) -> bool:
        row = self._current_row(property_key, expected_node_id=node_id)
        if not row.can_edit:
            raise ValueError(f"designer inspector property {row.key!r} is not editable")
        changed = self._workspace.set_selected_property(row.key, value)
        self.refresh()
        self._notify_change()
        return changed

    def _clear_for_target(self, node_id: object, property_key: object) -> bool:
        row = self._current_row(property_key, expected_node_id=node_id)
        if not row.can_clear:
            raise ValueError(f"designer inspector property {row.key!r} cannot be cleared")
        changed = self._workspace.clear_selected_property(row.key)
        self.refresh()
        self._notify_change()
        return changed

    def _host_set(self, node_id: str, property_key: str, value: object) -> bool:
        try:
            return self._set_for_target(node_id, property_key, value)
        except Exception as exc:
            return self._report_error(property_key, exc)

    def _host_clear(self, node_id: str, property_key: str) -> bool:
        try:
            return self._clear_for_target(node_id, property_key)
        except Exception as exc:
            return self._report_error(property_key, exc)

    def _host_error(self, _node_id: str, property_key: str, exc: Exception) -> bool:
        if not isinstance(exc, Exception):
            exc = ValueError(str(exc))
        return self._report_error(property_key, exc)

    def set_value(self, property_key: object, value: object) -> bool:
        """Set one current selected-node property through existing validation."""

        state = self.state
        if not state.has_target:
            raise RuntimeError("designer inspector panel has no selected target")
        return self._set_for_target(state.node_id, property_key, value)

    def clear_value(self, property_key: object) -> bool:
        """Clear one current selected-node property through existing semantics."""

        state = self.state
        if not state.has_target:
            raise RuntimeError("designer inspector panel has no selected target")
        return self._clear_for_target(state.node_id, property_key)

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
    "DesignerInspectorPanel",
    "DesignerInspectorPanelBinding",
    "DesignerInspectorPanelChangeHandler",
    "DesignerInspectorPanelErrorHandler",
    "DesignerInspectorPanelHost",
    "format_inspector_editor_value",
    "parse_inspector_editor_text",
]
