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
checked replacement transaction as property and structural edits.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .components.base import Component
from .components.renderer import ComponentRenderer
from .designer import DesignerNode, DesignerSnapshot
from .designer_clipboard import (
    DesignerClipboardPayload,
    DuplicateDesignerNode,
    PasteDesignerSubtree,
)
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
    reconstruct_designer_snapshot,
)
from .designer_structure import (
    InsertDesignerChild,
    MoveDesignerNode,
    RemoveDesignerNode,
    ReparentDesignerNode,
)


class DesignerPreviewHostError(RuntimeError):
    """Raised when a preview host cannot complete a replacement transaction."""


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
            candidate.root.build(renderer=self.renderer, parent=self.parent)
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
