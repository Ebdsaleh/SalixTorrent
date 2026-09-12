"""Transactional ownership and rebuilding for designer previews.

The framework remains code-first at its core: ordinary applications can create
and compose ``Component`` objects directly and never import this module.  This
module belongs to the optional designer/tooling layer.  It connects an existing
``DesignerEditSession`` to the snapshot reconstruction bridge introduced by the
previous tranche and owns one replaceable preview tree.

Preview replacement is deliberately whole-tree and transactional.  A candidate
preview is reconstructed (and, when a renderer is supplied, built) before the
currently accepted preview is disposed.  Failed candidates are cleaned up and
never advance edit history, so document and preview state remain aligned.
Optional copy/paste/duplicate helpers stay at the document boundary: copy only
updates ephemeral session clipboard state, while paste/duplicate use the same
checked replacement transaction as property and structural edits. Stable-ID
selection/focus, hierarchy navigation, hierarchy expansion/projection and
property-inspector presentation state are delegated to the edit session and
never retain live component or toolkit references across preview replacement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .components.base import Component
from .components.renderer import ComponentRenderer
from .designer import DesignerNode, DesignerSnapshot
from .designer_clipboard import (
    DesignerClipboardPayload,
    DuplicateDesignerNode,
    PasteDesignerSubtree,
)
from .designer_hierarchy import (
    DesignerHierarchyProjectionState,
    DesignerHierarchyRow,
)
from .designer_navigation import DesignerHierarchyReveal, DesignerNavigationDirection
from .designer_editing import (
    ClearDesignerProperty,
    DesignerEditCommand,
    DesignerEditSession,
    SetDesignerProperty,
)
from .designer_preview import (
    DesignerPreviewBuild,
    DesignerPreviewCatalog,
    DesignerPreviewContext,
    FRAMEWORK_DESIGNER_PREVIEW_CATALOG,
    designer_preview_component_profile,
    reconstruct_designer_snapshot,
)
from .designer_structure import (
    InsertDesignerChild,
    MoveDesignerNode,
    RemoveDesignerNode,
    ReparentDesignerNode,
)

if TYPE_CHECKING:
    from .designer_inspector import DesignerInspectorRow, DesignerInspectorState


class DesignerPreviewHostError(RuntimeError):
    """Raised when a preview host cannot complete a replacement transaction."""


class _DesignerPreviewRenderer:
    """Delegate rendering while carrying a preview-only component profile.

    Components bind this small renderer view, so later ``dispose``/``measure``/
    ``configure`` operations continue to reach the concrete backend without
    mutating its application-level profile.
    """

    def __init__(self, renderer: ComponentRenderer):
        self._renderer = renderer
        self.component_profile = designer_preview_component_profile(
            renderer.component_profile
        )

    def set_component_profile(self, profile) -> None:
        self.component_profile = profile

    def create(self, kind: str, **kwargs):
        return self._renderer.create(kind, **kwargs)

    def container(self, kind: str, **kwargs):
        return self._renderer.container(kind, **kwargs)

    def get_value(self, item):
        return self._renderer.get_value(item)

    def set_value(self, item, value) -> None:
        self._renderer.set_value(item, value)

    def configure(self, item, **kwargs) -> None:
        self._renderer.configure(item, **kwargs)

    def place(self, item, x: int, y: int) -> None:
        self._renderer.place(item, x, y)

    def measure(self, item):
        return self._renderer.measure(item)

    def exists(self, item) -> bool:
        return self._renderer.exists(item)

    def destroy(self, item) -> None:
        self._renderer.destroy(item)

    def event_callback(self, source, event_type, callback, *, data=None):
        return self._renderer.event_callback(
            source, event_type, callback, data=data
        )

    def center(self, item, *, fallback_size=None) -> None:
        self._renderer.center(item, fallback_size=fallback_size)

    def attach_tooltip(self, item, text: str, *, wrap: int = 450):
        return self._renderer.attach_tooltip(item, text, wrap=wrap)


@dataclass(frozen=True)
class DesignerPreviewState:
    """Small immutable inspection record for the currently owned preview."""

    generation: int
    snapshot: DesignerSnapshot
    root: Component
    rendered: bool


class DesignerPreviewHost:
    """Own one reconstructed preview for a ``DesignerEditSession``.

    The host is optional tooling.  Code-composed applications do not need it.
    When ``renderer`` is omitted, it still owns a backend-neutral reconstructed
    component tree and can be used in headless/editor model tests.
    """

    def __init__(
        self,
        session: DesignerEditSession,
        *,
        catalog: DesignerPreviewCatalog | None = None,
        context: DesignerPreviewContext | None = None,
        renderer: ComponentRenderer | None = None,
        parent: object | None = None,
        build_immediately: bool = True,
    ):
        if not isinstance(session, DesignerEditSession):
            raise TypeError("designer preview host requires DesignerEditSession")
        if renderer is not None and not isinstance(renderer, ComponentRenderer):
            raise TypeError("designer preview renderer must satisfy ComponentRenderer")
        self.session = session
        self.catalog = catalog or FRAMEWORK_DESIGNER_PREVIEW_CATALOG
        self.context = context or DesignerPreviewContext()
        self.renderer = renderer
        self.parent = parent
        self._preview: DesignerPreviewBuild | None = None
        self._generation = 0
        self._closed = False
        if build_immediately:
            self.rebuild(force=True)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def preview(self) -> DesignerPreviewBuild:
        if self._preview is None:
            raise RuntimeError("designer preview host has no current preview")
        return self._preview

    @property
    def state(self) -> DesignerPreviewState:
        preview = self.preview
        return DesignerPreviewState(
            self._generation,
            preview.source_snapshot,
            preview.root,
            preview.root.exists() if self.renderer is not None else False,
        )

    def component(self, node_id: object) -> Component:
        return self.preview.component(node_id)

    @property
    def selected_component(self) -> Component | None:
        node_id = self.session.selected_node_id
        if not node_id:
            return None
        try:
            return self.preview.component(node_id)
        except KeyError:
            # External session edits may temporarily put the document ahead of
            # this host until ``sync()`` is called.
            return None

    @property
    def focused_component(self) -> Component | None:
        node_id = self.session.focused_node_id
        if not node_id:
            return None
        try:
            return self.preview.component(node_id)
        except KeyError:
            return None

    def select_node(self, node_id: object, *, focus: bool = False) -> bool:
        self._require_open()
        return self.session.select_node(node_id, focus=focus)

    def focus_node(self, node_id: object, *, select: bool = False) -> bool:
        self._require_open()
        return self.session.focus_node(node_id, select=select)

    def select_and_focus_node(self, node_id: object) -> bool:
        self._require_open()
        return self.session.select_and_focus_node(node_id)

    def clear_selection(self) -> bool:
        self._require_open()
        return self.session.clear_selection()

    def clear_focus(self) -> bool:
        self._require_open()
        return self.session.clear_focus()

    @property
    def hierarchy_projection_state(self) -> DesignerHierarchyProjectionState:
        self._require_open()
        return self.session.hierarchy_projection_state

    @property
    def hierarchy_expanded_ids(self) -> tuple[str, ...]:
        self._require_open()
        return self.session.hierarchy_expanded_ids

    def hierarchy_rows(self) -> tuple[DesignerHierarchyRow, ...]:
        self._require_open()
        return self.session.hierarchy_rows()

    def visible_hierarchy_ids(self) -> tuple[str, ...]:
        self._require_open()
        return self.session.visible_hierarchy_ids()

    def expand_hierarchy_node(self, node_id: object) -> bool:
        self._require_open()
        return self.session.expand_hierarchy_node(node_id)

    def collapse_hierarchy_node(self, node_id: object) -> bool:
        self._require_open()
        return self.session.collapse_hierarchy_node(node_id)

    def toggle_hierarchy_node(self, node_id: object) -> bool:
        self._require_open()
        return self.session.toggle_hierarchy_node(node_id)

    def reveal_hierarchy_node(self, node_id: object) -> DesignerHierarchyReveal:
        self._require_open()
        return self.session.reveal_hierarchy_node(node_id)

    def reveal_selected_in_hierarchy(self) -> DesignerHierarchyReveal | None:
        self._require_open()
        return self.session.reveal_selected_in_hierarchy()

    def reveal_focused_in_hierarchy(self) -> DesignerHierarchyReveal | None:
        self._require_open()
        return self.session.reveal_focused_in_hierarchy()

    def inspector_state(
        self, *, include_read_only: bool = True
    ) -> "DesignerInspectorState":
        self._require_open()
        return self.session.inspector_state(include_read_only=include_read_only)

    def inspector_rows(
        self, *, include_read_only: bool = True
    ) -> tuple["DesignerInspectorRow", ...]:
        self._require_open()
        return self.session.inspector_rows(include_read_only=include_read_only)

    def inspected_property(self, property_key: object) -> "DesignerInspectorRow | None":
        self._require_open()
        return self.session.inspected_property(property_key)

    def set_selected_property(self, property_key: object, value: object) -> bool:
        self._require_open()
        if not self.session.selected_node_id:
            raise RuntimeError("designer property inspector has no selected node")
        return self.set_property(self.session.selected_node_id, property_key, value)

    def clear_selected_property(self, property_key: object) -> bool:
        self._require_open()
        if not self.session.selected_node_id:
            raise RuntimeError("designer property inspector has no selected node")
        return self.clear_property(self.session.selected_node_id, property_key)

    def selection_navigation_target(
        self,
        direction: DesignerNavigationDirection | str,
    ) -> str | None:
        self._require_open()
        return self.session.selection_navigation_target(direction)

    def focus_navigation_target(
        self,
        direction: DesignerNavigationDirection | str,
    ) -> str | None:
        self._require_open()
        return self.session.focus_navigation_target(direction)

    def navigate_selection(
        self,
        direction: DesignerNavigationDirection | str,
        *,
        focus: bool = False,
    ) -> bool:
        self._require_open()
        return self.session.navigate_selection(direction, focus=focus)

    def navigate_focus(
        self,
        direction: DesignerNavigationDirection | str,
        *,
        select: bool = False,
    ) -> bool:
        self._require_open()
        return self.session.navigate_focus(direction, select=select)

    def reveal_node(self, node_id: object) -> DesignerHierarchyReveal:
        self._require_open()
        return self.session.reveal_node(node_id)

    def reveal_selected(self) -> DesignerHierarchyReveal | None:
        self._require_open()
        return self.session.reveal_selected()

    def reveal_focused(self) -> DesignerHierarchyReveal | None:
        self._require_open()
        return self.session.reveal_focused()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("designer preview host is closed")

    def _prepare(self, snapshot: DesignerSnapshot) -> DesignerPreviewBuild:
        candidate = reconstruct_designer_snapshot(
            snapshot,
            catalog=self.catalog,
            context=self.context,
        )
        if self.renderer is None:
            return candidate
        try:
            build_renderer = self.renderer
            if self.context.use_preview_control_defaults:
                build_renderer = _DesignerPreviewRenderer(self.renderer)
            candidate.root.build(renderer=build_renderer, parent=self.parent)
            return candidate
        except Exception:
            # Container roots own their rendered descendants, so disposing a
            # partially bound root is the generic cleanup path when available.
            try:
                candidate.root.dispose()
            except Exception:
                pass
            raise

    def _retire_previous(self, candidate: DesignerPreviewBuild) -> None:
        previous = self._preview
        if previous is None or previous is candidate:
            return
        try:
            previous.root.dispose()
        except Exception as exc:
            # The candidate has already been proven buildable.  If old-tree
            # disposal fails, remove the candidate and leave document/history
            # unchanged by raising inside the checked transaction gate.
            try:
                candidate.root.dispose()
            except Exception:
                pass
            raise DesignerPreviewHostError(
                "failed to dispose the previous designer preview"
            ) from exc

    def _install(self, candidate: DesignerPreviewBuild) -> DesignerPreviewBuild:
        self._preview = candidate
        self._generation += 1
        return candidate

    @property
    def has_preview_draft(self) -> bool:
        """Whether the rendered preview is an ephemeral draft of session state.

        Draft previews are used by direct-manipulation surfaces that need live
        visual feedback before one final checked/history-bearing commit.  They
        never change the authoritative edit-session snapshot or history.
        """

        return bool(
            self._preview is not None
            and self._preview.source_snapshot != self.session.snapshot
        )

    def preview_edit(self, command: DesignerEditCommand) -> bool:
        """Install one ephemeral candidate preview without editing history.

        The command is always applied to the authoritative session snapshot,
        not to the previous draft.  This makes pointer translation stable: a
        drag can repeatedly submit absolute candidate values while the document
        remains unchanged until release.
        """

        self._require_open()
        if not callable(getattr(command, "apply", None)):
            raise TypeError("designer preview draft requires an edit command")
        snapshot = command.apply(self.session.snapshot)
        if not isinstance(snapshot, DesignerSnapshot):
            raise TypeError("designer edit command must return DesignerSnapshot")
        if snapshot == self.session.snapshot:
            return self.cancel_preview_draft()
        candidate = self._prepare(snapshot)
        self._retire_previous(candidate)
        self._install(candidate)
        return True

    def preview_property(self, node_id: object, property_key: object, value: object) -> bool:
        """Preview one property value ephemerally without mutating the document."""

        return self.preview_edit(SetDesignerProperty(node_id, property_key, value))

    def cancel_preview_draft(self) -> bool:
        """Restore the authoritative session snapshot after a live draft."""

        self._require_open()
        if not self.has_preview_draft:
            return False
        candidate = self._prepare(self.session.snapshot)
        self._retire_previous(candidate)
        self._install(candidate)
        return True

    def rebuild(self, *, force: bool = False) -> bool:
        """Replace the preview with the session's current snapshot.

        Returns ``False`` when the existing preview already represents the same
        immutable snapshot and ``force`` is not requested.
        """

        self._require_open()
        snapshot = self.session.snapshot
        if (
            not force
            and self._preview is not None
            and self._preview.source_snapshot == snapshot
        ):
            return False
        candidate = self._prepare(snapshot)
        self._retire_previous(candidate)
        self._install(candidate)
        return True

    sync = rebuild

    def _checked_candidate(self, holder: list[DesignerPreviewBuild]):
        def check(snapshot: DesignerSnapshot) -> None:
            candidate = self._prepare(snapshot)
            self._retire_previous(candidate)
            holder.append(candidate)

        return check

    def execute(self, command: DesignerEditCommand) -> bool:
        """Execute one edit only if its prospective preview can be prepared."""

        self._require_open()
        holder: list[DesignerPreviewBuild] = []
        changed = self.session.execute_checked(command, self._checked_candidate(holder))
        if not changed:
            # A direct-manipulation surface may have installed a transient
            # candidate before release.  A semantic no-op must still restore
            # the accepted session preview so no draft can leak past commit.
            self.cancel_preview_draft()
            return False
        self._install(holder[0])
        return True

    def set_property(self, node_id: object, property_key: object, value: object) -> bool:
        return self.execute(SetDesignerProperty(node_id, property_key, value))

    def clear_property(self, node_id: object, property_key: object) -> bool:
        return self.execute(ClearDesignerProperty(node_id, property_key))

    def insert_child(
        self,
        parent_id: object,
        node: DesignerNode,
        *,
        slot: object = "children",
        metadata: Mapping[str, object] | None = None,
        index: int | None = None,
    ) -> bool:
        return self.execute(
            InsertDesignerChild(parent_id, node, slot=slot, metadata=metadata, index=index)
        )

    def remove_node(self, node_id: object) -> bool:
        return self.execute(RemoveDesignerNode(node_id))

    def copy_node(self, node_id: object) -> DesignerClipboardPayload:
        """Copy document data without rebuilding the current preview."""

        self._require_open()
        return self.session.copy_node(node_id)

    def clear_clipboard(self) -> bool:
        self._require_open()
        return self.session.clear_clipboard()

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
        source = payload if payload is not None else self.session.clipboard
        if source is None:
            raise RuntimeError("designer clipboard is empty")
        if preserve_relationship:
            if metadata is not None:
                raise ValueError("explicit metadata requires preserve_relationship=False")
            command = PasteDesignerSubtree(
                parent_id,
                source,
                index=index,
                slot=slot,
                suffix=suffix,
            )
        else:
            command = PasteDesignerSubtree(
                parent_id,
                source,
                index=index,
                slot=slot,
                metadata=metadata,
                suffix=suffix,
            )
        return self.execute(command)

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
        if preserve_relationship:
            if metadata is not None:
                raise ValueError("explicit metadata requires preserve_relationship=False")
            command = DuplicateDesignerNode(
                node_id,
                index=index,
                slot=slot,
                suffix=suffix,
            )
        else:
            command = DuplicateDesignerNode(
                node_id,
                index=index,
                slot=slot,
                metadata=metadata,
                suffix=suffix,
            )
        return self.execute(command)

    def move_node(self, node_id: object, index: object) -> bool:
        return self.execute(MoveDesignerNode(node_id, index))

    def reparent_node(
        self,
        node_id: object,
        parent_id: object,
        *,
        index: int | None = None,
        slot: object | None = None,
        metadata: Mapping[str, object] | None | object = None,
        preserve_metadata: bool = True,
    ) -> bool:
        if preserve_metadata:
            if metadata is not None:
                raise ValueError("explicit metadata requires preserve_metadata=False")
            command = ReparentDesignerNode(node_id, parent_id, index=index, slot=slot)
        else:
            command = ReparentDesignerNode(
                node_id,
                parent_id,
                index=index,
                slot=slot,
                metadata=metadata,
            )
        return self.execute(command)

    def undo(self) -> bool:
        self._require_open()
        holder: list[DesignerPreviewBuild] = []
        changed = self.session.undo_checked(self._checked_candidate(holder))
        if not changed:
            return False
        self._install(holder[0])
        return True

    def redo(self) -> bool:
        self._require_open()
        holder: list[DesignerPreviewBuild] = []
        changed = self.session.redo_checked(self._checked_candidate(holder))
        if not changed:
            return False
        self._install(holder[0])
        return True

    def close(self) -> bool:
        """Dispose the current preview and permanently close this host."""

        if self._closed:
            return False
        preview = self._preview
        self._preview = None
        self._closed = True
        if preview is None:
            return False
        return bool(preview.root.dispose())


__all__ = [
    "DesignerPreviewHost",
    "DesignerPreviewHostError",
    "DesignerPreviewState",
]
