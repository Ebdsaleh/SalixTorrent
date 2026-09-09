"""Backend-neutral coordination snapshot for optional designer workspaces.

Earlier designer tranches deliberately kept ownership split across small,
authoritative models: ``DesignerProjectFile`` owns file/path/dirty semantics,
``DesignerEditSession`` owns the immutable document and history,
``DesignerPreviewHost`` owns transactional preview replacement, stable-ID
selection/hierarchy projection remains session state, and
``DesignerPropertyInspector`` projects the current selection.

This module does not replace any of those owners.  It composes them into one
shell-facing workspace state and provides narrow delegation helpers suitable for
a future RAD/editor shell.  Concrete Dear PyGui/Tkinter widgets remain adapters
above this coordinator, and ordinary code-first applications never need to
import it.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from .components.renderer import ComponentRenderer
from .designer import DesignerNode, DesignerSnapshot
from .designer_clipboard import DesignerClipboardPayload
from .designer_editing import DesignerEditSession
from .designer_hierarchy import DesignerHierarchyRow
from .designer_inspector import DesignerInspectorRow, DesignerInspectorState
from .designer_navigation import DesignerHierarchyReveal, DesignerNavigationDirection
from .designer_preview import DesignerPreviewCatalog, DesignerPreviewContext
from .designer_preview_host import DesignerPreviewHost
from .designer_project import DesignerProjectFile


@dataclass(frozen=True)
class DesignerWorkspaceState:
    """Immutable shell-facing snapshot composed from existing designer owners."""

    closed: bool
    path: Path | None
    has_path: bool
    is_persisted: bool
    is_dirty: bool
    can_save: bool
    requires_save_as: bool
    can_undo: bool
    can_redo: bool
    undo_label: str
    redo_label: str
    has_clipboard: bool
    selected_id: str
    focused_id: str
    expanded_ids: tuple[str, ...]
    hierarchy_rows: tuple[DesignerHierarchyRow, ...]
    inspector: DesignerInspectorState
    preview_generation: int
    preview_available: bool
    preview_rendered: bool

    @property
    def has_selection(self) -> bool:
        return bool(self.selected_id)

    @property
    def has_focus(self) -> bool:
        return bool(self.focused_id)

    @property
    def hierarchy_row_count(self) -> int:
        return len(self.hierarchy_rows)

    def to_descriptor(self) -> dict[str, object]:
        """Return a deterministic JSON-safe presentation descriptor.

        This descriptor is for editor-shell inspection/tests only.  It is not
        the designer project persistence schema and must not be written into
        project files as editor state.
        """

        return {
            "closed": self.closed,
            "project": {
                "path": None if self.path is None else str(self.path),
                "has_path": self.has_path,
                "persisted": self.is_persisted,
                "dirty": self.is_dirty,
                "can_save": self.can_save,
                "requires_save_as": self.requires_save_as,
            },
            "history": {
                "can_undo": self.can_undo,
                "can_redo": self.can_redo,
                "undo_label": self.undo_label,
                "redo_label": self.redo_label,
            },
            "clipboard": {"has_payload": self.has_clipboard},
            "selection": {
                "selected_id": self.selected_id,
                "focused_id": self.focused_id,
            },
            "hierarchy": {
                "expanded_ids": list(self.expanded_ids),
                "rows": [
                    {
                        "node_id": row.node_id,
                        "type": row.type_key,
                        "depth": row.depth,
                        "parent_id": row.parent_id,
                        "child_count": row.child_count,
                        "expandable": row.expandable,
                        "expanded": row.expanded,
                        "selected": row.selected,
                        "focused": row.focused,
                    }
                    for row in self.hierarchy_rows
                ],
            },
            "inspector": self.inspector.to_descriptor(),
            "preview": {
                "generation": self.preview_generation,
                "available": self.preview_available,
                "rendered": self.preview_rendered,
            },
        }


class DesignerWorkspace:
    """Coordinate one designer project and its existing preview/session models.

    ``DesignerProjectFile`` remains the owner of the edit session and file
    semantics.  ``DesignerPreviewHost`` remains the owner of preview lifetime
    and checked edit transactions.  The workspace only composes those states
    for a future shell and delegates actions to the appropriate existing owner.
    """

    def __init__(
        self,
        project: DesignerProjectFile,
        *,
        preview_host: DesignerPreviewHost | None = None,
        catalog: DesignerPreviewCatalog | None = None,
        context: DesignerPreviewContext | None = None,
        renderer: ComponentRenderer | None = None,
        parent: object | None = None,
    ):
        if not isinstance(project, DesignerProjectFile):
            raise TypeError("designer workspace requires DesignerProjectFile")
        if preview_host is not None:
            if not isinstance(preview_host, DesignerPreviewHost):
                raise TypeError("designer workspace preview_host must be DesignerPreviewHost")
            if any(value is not None for value in (catalog, context, renderer, parent)):
                raise ValueError(
                    "explicit preview_host cannot be combined with preview construction options"
                )
            if preview_host.session is not project.session:
                raise ValueError("designer workspace project and preview must share one edit session")
            if preview_host.closed:
                raise ValueError("designer workspace cannot adopt a closed preview host")
            resolved_preview = preview_host
        else:
            resolved_preview = DesignerPreviewHost(
                project.session,
                catalog=catalog,
                context=context,
                renderer=renderer,
                parent=parent,
            )

        self._project = project
        self._preview = resolved_preview
        self._closed = False

    @classmethod
    def create(
        cls,
        snapshot: DesignerSnapshot,
        *,
        path: str | os.PathLike[str] | None = None,
        catalog: DesignerPreviewCatalog | None = None,
        context: DesignerPreviewContext | None = None,
        renderer: ComponentRenderer | None = None,
        parent: object | None = None,
    ) -> "DesignerWorkspace":
        return cls(
            DesignerProjectFile.create(snapshot, path=path),
            catalog=catalog,
            context=context,
            renderer=renderer,
            parent=parent,
        )

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        catalog: DesignerPreviewCatalog | None = None,
        context: DesignerPreviewContext | None = None,
        renderer: ComponentRenderer | None = None,
        parent: object | None = None,
    ) -> "DesignerWorkspace":
        return cls(
            DesignerProjectFile.open(path),
            catalog=catalog,
            context=context,
            renderer=renderer,
            parent=parent,
        )

    @property
    def project(self) -> DesignerProjectFile:
        return self._project

    @property
    def session(self) -> DesignerEditSession:
        return self._project.session

    @property
    def preview_host(self) -> DesignerPreviewHost:
        return self._preview

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def state(self) -> DesignerWorkspaceState:
        project = self._project
        session = project.session
        preview_available = False
        preview_rendered = False
        if not self._preview.closed:
            try:
                preview_state = self._preview.state
            except RuntimeError:
                pass
            else:
                preview_available = True
                preview_rendered = preview_state.rendered

        return DesignerWorkspaceState(
            closed=self._closed,
            path=project.path,
            has_path=project.has_path,
            is_persisted=project.is_persisted,
            is_dirty=project.is_dirty,
            can_save=project.has_path and project.is_dirty and not self._closed,
            requires_save_as=project.is_dirty and not project.has_path and not self._closed,
            can_undo=session.can_undo and not self._closed,
            can_redo=session.can_redo and not self._closed,
            undo_label=session.undo_label,
            redo_label=session.redo_label,
            has_clipboard=session.has_clipboard,
            selected_id=session.selected_node_id,
            focused_id=session.focused_node_id,
            expanded_ids=session.hierarchy_expanded_ids,
            hierarchy_rows=session.hierarchy_rows(),
            inspector=session.inspector_state(),
            preview_generation=self._preview.generation,
            preview_available=preview_available,
            preview_rendered=preview_rendered,
        )

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("designer workspace is closed")

    # Project-file ownership -------------------------------------------------
    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        self._require_open()
        return self._project.save(path)

    def save_as(self, path: str | os.PathLike[str]) -> Path:
        self._require_open()
        return self._project.save_as(path)

    # Stable selection / hierarchy / inspector ------------------------------
    def select_node(self, node_id: object, *, focus: bool = False) -> bool:
        self._require_open()
        return self._preview.select_node(node_id, focus=focus)

    def focus_node(self, node_id: object, *, select: bool = False) -> bool:
        self._require_open()
        return self._preview.focus_node(node_id, select=select)

    def select_and_focus_node(self, node_id: object) -> bool:
        self._require_open()
        return self._preview.select_and_focus_node(node_id)

    def clear_selection(self) -> bool:
        self._require_open()
        return self._preview.clear_selection()

    def clear_focus(self) -> bool:
        self._require_open()
        return self._preview.clear_focus()

    def navigate_selection(
        self,
        direction: DesignerNavigationDirection | str,
        *,
        focus: bool = False,
    ) -> bool:
        self._require_open()
        return self._preview.navigate_selection(direction, focus=focus)

    def expand_hierarchy_node(self, node_id: object) -> bool:
        self._require_open()
        return self._preview.expand_hierarchy_node(node_id)

    def collapse_hierarchy_node(self, node_id: object) -> bool:
        self._require_open()
        return self._preview.collapse_hierarchy_node(node_id)

    def toggle_hierarchy_node(self, node_id: object) -> bool:
        self._require_open()
        return self._preview.toggle_hierarchy_node(node_id)

    def reveal_selected_in_hierarchy(self) -> DesignerHierarchyReveal | None:
        self._require_open()
        return self._preview.reveal_selected_in_hierarchy()

    def inspector_state(self, *, include_read_only: bool = True) -> DesignerInspectorState:
        self._require_open()
        return self._preview.inspector_state(include_read_only=include_read_only)

    def inspector_rows(
        self, *, include_read_only: bool = True
    ) -> tuple[DesignerInspectorRow, ...]:
        self._require_open()
        return self._preview.inspector_rows(include_read_only=include_read_only)

    def set_selected_property(self, property_key: object, value: object) -> bool:
        self._require_open()
        return self._preview.set_selected_property(property_key, value)

    def clear_selected_property(self, property_key: object) -> bool:
        self._require_open()
        return self._preview.clear_selected_property(property_key)

    # Generic checked editing ----------------------------------------------
    def execute(self, command) -> bool:
        """Execute one backend-neutral designer command through preview validation."""

        self._require_open()
        return self._preview.execute(command)

    # Structural insertion --------------------------------------------------
    def insert_child(
        self,
        parent_id: object,
        node,
        *,
        slot: object = "children",
        metadata=None,
        index: int | None = None,
    ) -> bool:
        self._require_open()
        return self._preview.insert_child(
            parent_id,
            node,
            slot=slot,
            metadata=metadata,
            index=index,
        )

    # History / clipboard ---------------------------------------------------
    def undo(self) -> bool:
        self._require_open()
        return self._preview.undo()

    def redo(self) -> bool:
        self._require_open()
        return self._preview.redo()

    def copy_node(self, node_id: object) -> DesignerClipboardPayload:
        self._require_open()
        return self._preview.copy_node(node_id)

    def copy_selected(self) -> DesignerClipboardPayload:
        self._require_open()
        node_id = self.session.selected_node_id
        if not node_id:
            raise RuntimeError("designer workspace has no selected node to copy")
        return self._preview.copy_node(node_id)

    def clear_clipboard(self) -> bool:
        self._require_open()
        return self._preview.clear_clipboard()

    def paste(
        self,
        parent_id: object,
        *,
        payload: DesignerClipboardPayload | None = None,
        index: int | None = None,
        slot: object | None = None,
        metadata: Mapping[str, object] | None = None,
        preserve_relationship: bool = True,
        suffix: object = "copy",
    ) -> bool:
        self._require_open()
        return self._preview.paste(
            parent_id,
            payload=payload,
            index=index,
            slot=slot,
            metadata=metadata,
            preserve_relationship=preserve_relationship,
            suffix=suffix,
        )

    def duplicate_node(
        self,
        node_id: object,
        *,
        index: int | None = None,
        slot: object | None = None,
        metadata: Mapping[str, object] | None = None,
        preserve_relationship: bool = True,
        suffix: object = "copy",
    ) -> bool:
        self._require_open()
        return self._preview.duplicate_node(
            node_id,
            index=index,
            slot=slot,
            metadata=metadata,
            preserve_relationship=preserve_relationship,
            suffix=suffix,
        )

    def duplicate_selected(self, *, suffix: object = "copy") -> bool:
        self._require_open()
        node_id = self.session.selected_node_id
        if not node_id:
            raise RuntimeError("designer workspace has no selected node to duplicate")
        return self._preview.duplicate_node(node_id, suffix=suffix)

    # Preview synchronization / lifetime -----------------------------------
    def sync_preview(self, *, force: bool = False) -> bool:
        self._require_open()
        return self._preview.rebuild(force=force)

    def close(self) -> bool:
        if self._closed:
            return False
        self._closed = True
        self._preview.close()
        return True


__all__ = [
    "DesignerWorkspace",
    "DesignerWorkspaceState",
]
