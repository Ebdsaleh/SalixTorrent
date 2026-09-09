"""Backend-neutral placement resolution for designer component-palette requests.

The component palette deliberately emits a request instead of guessing where a
new node belongs.  This module is the next explicit seam: it projects candidate
parents and relationship slots from the current immutable designer snapshot,
keeps the pending placement form as ephemeral editor state, and commits one
validated structural insertion through :class:`DesignerWorkspace`.

Concrete GUI hosts only edit the projected form.  Parent/slot validation,
relationship metadata parsing, stable-ID allocation, sparse creation defaults,
history/dirty state and preview replacement remain backend-neutral.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Callable, Protocol, runtime_checkable

from .designer import (
    DesignerCatalog,
    DesignerChildSlotSpec,
    DesignerNode,
    DesignerSnapshot,
    FRAMEWORK_DESIGNER_CATALOG,
)
from .designer_component_palette import DesignerComponentInsertRequest
from .designer_preview import reconstruct_designer_snapshot
from .designer_structure import InsertDesignerChild, locate_designer_node
from .designer_workspace import DesignerWorkspace


def _key(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


def _json_metadata(text: object) -> Mapping[str, object] | None:
    source = str(text or "").strip()
    if not source:
        return None
    try:
        value = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError(f"designer placement metadata must be valid JSON: {exc.msg}") from exc
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("designer placement metadata JSON must be an object or null")
    return value


def _index(text: object) -> int | None:
    source = str(text or "").strip()
    if not source:
        return None
    try:
        value = int(source)
    except ValueError as exc:
        raise ValueError("designer placement index must be an integer or blank") from exc
    if value < 0:
        raise ValueError("designer placement index must be non-negative")
    return value


def _node(snapshot: DesignerSnapshot, node_id: str) -> DesignerNode:
    for candidate in snapshot.root.walk():
        if candidate.node_id == node_id:
            return candidate
    raise KeyError(f"designer node not found: {node_id}")


def _allocate_node_id(snapshot: DesignerSnapshot, component_type_key: str) -> str:
    stem = component_type_key.rsplit(".", 1)[-1].replace("_", "-") or "node"
    existing = {item.node_id for item in snapshot.root.walk()}
    number = 1
    while True:
        candidate = f"designer-{stem}-{number:04d}"
        if candidate not in existing:
            return candidate
        number += 1


def _initial_properties(
    component_type_key: str,
    label: str,
    node_id: str,
    metadata: Mapping[str, object] | None,
) -> dict[str, object]:
    """Return intentionally small visible defaults for a newly-created node.

    These are editor creation defaults, not a final template/schema contract.
    Sparse preview builders still supply normal runtime defaults for everything
    not listed here.
    """

    visible = str(label or "").strip()
    if component_type_key == "control.label":
        return {"text": visible or "Label"}
    if component_type_key in {"control.button", "control.checkbox"}:
        return {"label": visible}
    if component_type_key == "container.section":
        return {"heading": visible or "Section"}
    if component_type_key == "container.dialog":
        return {"label": visible or "Dialog"}
    if component_type_key == "structure.tab_page":
        relationship_key = None if metadata is None else metadata.get("key")
        page_key = str(relationship_key or node_id).strip()
        return {"key": page_key, "label": visible or "Tab page"}
    return {}


def _slot_compatible(parent_type: str, slot_key: str, child_type: str) -> bool:
    if parent_type == "structure.tabs" and slot_key == "page":
        return child_type == "structure.tab_page"
    return True


def _metadata_suggestion(
    parent: DesignerNode,
    slot: DesignerChildSlotSpec,
    *,
    node_id: str,
) -> str:
    metadata: dict[str, object] = {}
    if parent.type_key == "container.grid" and slot.key == "cell":
        coordinates = []
        for child in parent.children:
            if child.slot != "cell" or not isinstance(child.metadata, Mapping):
                continue
            row = child.metadata.get("row")
            column = child.metadata.get("column")
            if isinstance(row, int) and not isinstance(row, bool) and isinstance(column, int) and not isinstance(column, bool):
                coordinates.append((row, column))
        if not coordinates:
            metadata.update(row=0, column=0)
        else:
            maximum_row = max(row for row, _ in coordinates)
            maximum_column = max(column for _, column in coordinates)
            if maximum_row == 0:
                metadata.update(row=0, column=maximum_column + 1)
            elif maximum_column == 0:
                metadata.update(row=maximum_row + 1, column=0)
            else:
                # A single insertion cannot extend both dimensions of a dense
                # rectangular grid without creating a temporary hole.  Keep an
                # explicit suggestion that will be checked transactionally.
                metadata.update(row=maximum_row + 1, column=0)
    elif parent.type_key == "structure.tabs" and slot.key == "page":
        metadata["key"] = node_id
    elif parent.type_key == "structure.split" and slot.key == "pane":
        metadata["key"] = node_id
    elif parent.type_key in {"container.placed", "container.positioned"}:
        metadata["placement"] = {"kind": "fixed", "x": 0, "y": 0}
    else:
        for key in slot.required_metadata:
            if key == "key":
                metadata[key] = node_id
            else:
                metadata[key] = 0
    return "" if not metadata else json.dumps(metadata, sort_keys=True, separators=(",", ":"))




@dataclass(frozen=True)
class _InsertCatalogComponent:
    """One checked insertion that carries missing self-describing type metadata."""

    parent_id: str
    node: DesignerNode
    type_descriptor: Mapping[str, object]
    slot: str
    metadata: Mapping[str, object] | None
    index: int | None

    @property
    def label(self) -> str:
        return f"Insert {self.node.node_id}"

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        type_keys = {str(item.get("key", "")) for item in snapshot.types}
        active = snapshot
        if self.node.type_key not in type_keys:
            descriptors = (*snapshot.types, dict(self.type_descriptor))
            active = DesignerSnapshot(
                snapshot.root,
                descriptors,
                kind=snapshot.kind,
                version=snapshot.version,
            )
        return InsertDesignerChild(
            self.parent_id,
            self.node,
            slot=self.slot,
            metadata=self.metadata,
            index=self.index,
        ).apply(active)


@dataclass(frozen=True)
class DesignerPlacementSlotOption:
    key: str
    label: str
    multiple: bool
    required_metadata: tuple[str, ...]
    allowed_metadata: tuple[str, ...]

    @classmethod
    def from_spec(cls, spec: DesignerChildSlotSpec) -> "DesignerPlacementSlotOption":
        return cls(
            key=spec.key,
            label=spec.label,
            multiple=spec.multiple,
            required_metadata=spec.required_metadata,
            allowed_metadata=spec.allowed_metadata,
        )


@dataclass(frozen=True)
class DesignerPlacementParentOption:
    node_id: str
    type_key: str
    type_label: str
    depth: int
    slots: tuple[DesignerPlacementSlotOption, ...]

    @property
    def display_label(self) -> str:
        return f"{'  ' * self.depth}{self.type_label} [{self.node_id}]"


@dataclass(frozen=True)
class DesignerComponentPlacementState:
    closed: bool
    request: DesignerComponentInsertRequest | None
    node_id: str
    parents: tuple[DesignerPlacementParentOption, ...]
    parent_id: str
    slot_key: str
    index_text: str
    metadata_text: str
    creation_error: str = ""

    @property
    def active(self) -> bool:
        return self.request is not None

    @property
    def can_commit(self) -> bool:
        return bool(self.active and not self.closed and self.parent_id and self.slot_key and not self.creation_error)

    @property
    def current_parent(self) -> DesignerPlacementParentOption | None:
        for parent in self.parents:
            if parent.node_id == self.parent_id:
                return parent
        return None

    @property
    def current_slots(self) -> tuple[DesignerPlacementSlotOption, ...]:
        parent = self.current_parent
        return () if parent is None else parent.slots

    def to_descriptor(self) -> dict[str, object]:
        return {
            "closed": self.closed,
            "active": self.active,
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "slot_key": self.slot_key,
            "index_text": self.index_text,
            "metadata_text": self.metadata_text,
            "can_commit": self.can_commit,
            "creation_error": self.creation_error,
            "request": None if self.request is None else self.request.to_descriptor(),
            "parents": [
                {
                    "node_id": parent.node_id,
                    "type_key": parent.type_key,
                    "type_label": parent.type_label,
                    "depth": parent.depth,
                    "slots": [
                        {
                            "key": slot.key,
                            "label": slot.label,
                            "multiple": slot.multiple,
                            "required_metadata": list(slot.required_metadata),
                            "allowed_metadata": list(slot.allowed_metadata),
                        }
                        for slot in parent.slots
                    ],
                }
                for parent in self.parents
            ],
        }


@dataclass
class DesignerComponentPlacementBinding:
    panel: object
    fields: dict[str, object]
    title_item: object | None = None
    metadata: object | None = None


@runtime_checkable
class DesignerComponentPlacementHost(Protocol):
    def build(
        self,
        state: DesignerComponentPlacementState,
        *,
        parent: object,
        title: str,
        on_parent: Callable[[str], object],
        on_slot: Callable[[str], object],
        on_index: Callable[[str], object],
        on_metadata: Callable[[str], object],
        on_commit: Callable[[], object],
        on_cancel: Callable[[], object],
    ) -> DesignerComponentPlacementBinding:
        ...

    def update(
        self,
        binding: DesignerComponentPlacementBinding,
        state: DesignerComponentPlacementState,
    ) -> None:
        ...

    def exists(self, binding: DesignerComponentPlacementBinding) -> bool:
        ...

    def dispose(self, binding: DesignerComponentPlacementBinding) -> None:
        ...


def _host_errors(host: object) -> tuple[str, ...]:
    return tuple(
        name
        for name in ("build", "update", "exists", "dispose")
        if not callable(getattr(host, name, None))
    )


class DesignerComponentPlacementSurface:
    """Resolve and commit one palette request through existing structural owners."""

    def __init__(
        self,
        workspace: DesignerWorkspace,
        host: DesignerComponentPlacementHost,
        *,
        catalog: DesignerCatalog = FRAMEWORK_DESIGNER_CATALOG,
        title: str = "Placement",
        on_change: Callable[[DesignerComponentPlacementState], object] | None = None,
        on_error: Callable[[Exception], object] | None = None,
    ):
        if not isinstance(workspace, DesignerWorkspace):
            raise TypeError("designer component placement requires DesignerWorkspace")
        if not isinstance(catalog, DesignerCatalog):
            raise TypeError("designer component placement catalog must be DesignerCatalog")
        missing = _host_errors(host)
        if missing:
            raise TypeError(
                "designer component placement host does not satisfy DesignerComponentPlacementHost; missing: "
                + ", ".join(missing)
            )
        if on_change is not None and not callable(on_change):
            raise TypeError("designer component placement change handler must be callable")
        if on_error is not None and not callable(on_error):
            raise TypeError("designer component placement error handler must be callable")
        self._workspace = workspace
        self._host = host
        self._catalog = catalog
        self._title = str(title)
        self._on_change = on_change
        self._on_error = on_error
        self._request: DesignerComponentInsertRequest | None = None
        self._node_id = ""
        self._parent_id = ""
        self._slot_key = ""
        self._index_text = ""
        self._metadata_text = ""
        self._creation_error = ""
        self._parent: object | None = None
        self._binding: DesignerComponentPlacementBinding | None = None

    @property
    def workspace(self) -> DesignerWorkspace:
        return self._workspace

    @property
    def binding(self) -> DesignerComponentPlacementBinding | None:
        return self._binding

    def _parent_options(self) -> tuple[DesignerPlacementParentOption, ...]:
        snapshot = self._workspace.session.snapshot
        request = self._request
        child_type = "" if request is None else request.component_type_key
        values = []
        for candidate in snapshot.root.walk():
            spec = self._catalog.get(candidate.type_key)
            slots = tuple(
                DesignerPlacementSlotOption.from_spec(slot)
                for slot in spec.child_slots
                if _slot_compatible(candidate.type_key, slot.key, child_type)
            )
            if not slots:
                continue
            location = locate_designer_node(snapshot, candidate.node_id)
            values.append(
                DesignerPlacementParentOption(
                    node_id=candidate.node_id,
                    type_key=candidate.type_key,
                    type_label=spec.label,
                    depth=location.depth,
                    slots=slots,
                )
            )
        return tuple(values)

    @property
    def state(self) -> DesignerComponentPlacementState:
        return DesignerComponentPlacementState(
            closed=self._workspace.closed,
            request=self._request,
            node_id=self._node_id,
            parents=self._parent_options() if self._request is not None else (),
            parent_id=self._parent_id,
            slot_key=self._slot_key,
            index_text=self._index_text,
            metadata_text=self._metadata_text,
            creation_error=self._creation_error,
        )

    def build(self, *, parent: object) -> DesignerComponentPlacementBinding:
        if self.exists():
            raise RuntimeError("designer component placement is already built")
        binding = self._host.build(
            self.state,
            parent=parent,
            title=self._title,
            on_parent=self.choose_parent,
            on_slot=self.choose_slot,
            on_index=self.set_index_text,
            on_metadata=self.set_metadata_text,
            on_commit=self.commit,
            on_cancel=self.cancel,
        )
        if not isinstance(binding, DesignerComponentPlacementBinding):
            raise TypeError("designer component placement host must return DesignerComponentPlacementBinding")
        self._parent = parent
        self._binding = binding
        return binding

    def exists(self) -> bool:
        return bool(self._binding is not None and self._host.exists(self._binding))

    def require_binding(self) -> DesignerComponentPlacementBinding:
        if not self.exists():
            raise RuntimeError("designer component placement is not built or its backend binding is stale")
        assert self._binding is not None
        return self._binding

    def refresh(self) -> DesignerComponentPlacementBinding:
        if self._binding is None:
            raise RuntimeError("designer component placement is not built")
        if not self._host.exists(self._binding):
            if self._parent is None:
                raise RuntimeError("designer component placement parent is unavailable")
            self._binding = None
            return self.build(parent=self._parent)
        self._host.update(self._binding, self.state)
        return self._binding

    def _notify(self) -> None:
        if self.exists():
            self._host.update(self.require_binding(), self.state)
        if self._on_change is not None:
            self._on_change(self.state)

    def _creation_support_error(self, request: DesignerComponentInsertRequest, node_id: str) -> str:
        snapshot = self._workspace.session.snapshot
        properties = _initial_properties(request.component_type_key, request.label, node_id, None)
        candidate = DesignerNode(node_id, request.component_type_key, properties)
        type_keys = {str(item.get("key", "")) for item in snapshot.types}
        descriptors = snapshot.types
        if request.component_type_key not in type_keys:
            descriptors = (*snapshot.types, self._catalog.get(request.component_type_key).to_descriptor())
        try:
            reconstruct_designer_snapshot(
                DesignerSnapshot(candidate, descriptors, kind=snapshot.kind, version=snapshot.version)
            )
        except Exception as exc:
            return str(exc)
        return ""

    def begin(self, request: DesignerComponentInsertRequest) -> DesignerComponentPlacementState:
        if self._workspace.closed:
            raise RuntimeError("designer workspace is closed")
        if not isinstance(request, DesignerComponentInsertRequest):
            raise TypeError("designer component placement requires DesignerComponentInsertRequest")
        self._catalog.get(request.component_type_key)
        snapshot = self._workspace.session.snapshot
        self._request = request
        self._node_id = _allocate_node_id(snapshot, request.component_type_key)
        self._index_text = ""
        self._creation_error = self._creation_support_error(request, self._node_id)

        parents = self._parent_options()
        preferred = ""
        if request.target_hint:
            for parent in parents:
                if parent.node_id == request.target_hint:
                    preferred = parent.node_id
                    break
            if not preferred:
                try:
                    location = locate_designer_node(snapshot, request.target_hint)
                except (KeyError, ValueError):
                    location = None
                if location is not None and location.parent_id:
                    if any(parent.node_id == location.parent_id for parent in parents):
                        preferred = location.parent_id
        if not preferred and any(parent.node_id == snapshot.root.node_id for parent in parents):
            preferred = snapshot.root.node_id
        if not preferred and parents:
            preferred = parents[0].node_id
        self._parent_id = preferred
        self._slot_key = ""
        self._metadata_text = ""
        if preferred:
            self._reset_slot_for_parent()
        self._notify()
        return self.state

    def _reset_slot_for_parent(self) -> None:
        state = self.state
        parent = state.current_parent
        if parent is None or not parent.slots:
            self._slot_key = ""
            self._metadata_text = ""
            return
        self._slot_key = parent.slots[0].key
        self._reset_metadata_for_slot()

    def _reset_metadata_for_slot(self) -> None:
        if not self._parent_id or not self._slot_key:
            self._metadata_text = ""
            return
        snapshot = self._workspace.session.snapshot
        parent = _node(snapshot, self._parent_id)
        spec = self._catalog.get(parent.type_key)
        slot = next((item for item in spec.child_slots if item.key == self._slot_key), None)
        if slot is None:
            raise KeyError(f"designer parent does not expose slot: {self._slot_key}")
        self._metadata_text = _metadata_suggestion(parent, slot, node_id=self._node_id)

    def choose_parent(self, parent_id: object) -> DesignerComponentPlacementState:
        resolved = _key(parent_id, field="designer placement parent id")
        if not any(parent.node_id == resolved for parent in self._parent_options()):
            raise KeyError(f"designer placement parent is not available: {resolved}")
        self._parent_id = resolved
        self._index_text = ""
        self._reset_slot_for_parent()
        self._notify()
        return self.state

    def choose_slot(self, slot_key: object) -> DesignerComponentPlacementState:
        resolved = _key(slot_key, field="designer placement slot")
        parent = self.state.current_parent
        if parent is None or not any(slot.key == resolved for slot in parent.slots):
            raise KeyError(f"designer placement slot is not available: {resolved}")
        self._slot_key = resolved
        self._reset_metadata_for_slot()
        self._notify()
        return self.state

    def set_index_text(self, value: object) -> DesignerComponentPlacementState:
        self._index_text = str(value or "")
        self._notify()
        return self.state

    def set_metadata_text(self, value: object) -> DesignerComponentPlacementState:
        self._metadata_text = str(value or "")
        self._notify()
        return self.state

    def cancel(self) -> DesignerComponentPlacementState:
        self._request = None
        self._node_id = ""
        self._parent_id = ""
        self._slot_key = ""
        self._index_text = ""
        self._metadata_text = ""
        self._creation_error = ""
        self._notify()
        return self.state

    def commit(self) -> str:
        if self._workspace.closed:
            raise RuntimeError("designer workspace is closed")
        request = self._request
        if request is None:
            raise RuntimeError("designer component placement has no pending request")
        if self._creation_error:
            raise ValueError(
                "designer component cannot be created as a sparse node yet: " + self._creation_error
            )
        parent_id = _key(self._parent_id, field="designer placement parent id")
        slot_key = _key(self._slot_key, field="designer placement slot")
        metadata = _json_metadata(self._metadata_text)
        index = _index(self._index_text)
        properties = _initial_properties(
            request.component_type_key,
            request.label,
            self._node_id,
            metadata,
        )
        node = DesignerNode(self._node_id, request.component_type_key, properties)
        try:
            command = _InsertCatalogComponent(
                parent_id=parent_id,
                node=node,
                type_descriptor=self._catalog.get(request.component_type_key).to_descriptor(),
                slot=slot_key,
                metadata=metadata,
                index=index,
            )
            changed = self._workspace.execute(command)
            if not changed:
                raise RuntimeError("designer component placement produced no document change")
            self._workspace.select_and_focus_node(self._node_id)
            self._workspace.reveal_selected_in_hierarchy()
        except Exception as exc:
            if self._on_error is not None:
                self._on_error(exc)
            raise
        inserted_id = self._node_id
        self.cancel()
        return inserted_id

    def dispose(self) -> bool:
        binding = self._binding
        self._binding = None
        self._parent = None
        if binding is None:
            return False
        self._host.dispose(binding)
        return True


__all__ = [
    "DesignerComponentPlacementBinding",
    "DesignerComponentPlacementHost",
    "DesignerComponentPlacementState",
    "DesignerComponentPlacementSurface",
    "DesignerPlacementParentOption",
    "DesignerPlacementSlotOption",
]
