"""Backend-neutral property-inspector projection for designer tooling.

Tranche 10 established typed ``DesignerPropertyState`` metadata and safe
snapshot editing.  Later tranches added stable-ID selection, project ownership,
hierarchy navigation and hierarchy projection.  This module turns the selected
node's property metadata into a deterministic inspector presentation model
without introducing toolkit widgets or a second property/editing contract.

The inspector is selection-driven and intentionally owns no document state.
Selection changes, property-row projection and editor hints do not dirty the
project, create undo history, alter hierarchy expansion or rebuild previews.
Concrete editors remain adapters over these records; actual mutations still go
through ``DesignerEditSession`` / ``DesignerPreviewHost`` so existing validation,
history and transactional preview semantics remain authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from .designer import DesignerValueKind
from .designer_editing import DesignerEditSession, DesignerPropertyState


class DesignerInspectorEditorKind(str, Enum):
    """Toolkit-neutral editor hints derived from ``DesignerValueKind``."""

    TEXT = "text"
    TOGGLE = "toggle"
    INTEGER = "integer"
    NUMBER = "number"
    CHOICE = "choice"
    STRING_LIST = "string_list"
    NUMBER_LIST = "number_list"
    DIMENSION = "dimension"
    INSETS = "insets"


_EDITOR_KIND_BY_VALUE_KIND = {
    DesignerValueKind.TEXT: DesignerInspectorEditorKind.TEXT,
    DesignerValueKind.BOOLEAN: DesignerInspectorEditorKind.TOGGLE,
    DesignerValueKind.INTEGER: DesignerInspectorEditorKind.INTEGER,
    DesignerValueKind.NUMBER: DesignerInspectorEditorKind.NUMBER,
    DesignerValueKind.CHOICE: DesignerInspectorEditorKind.CHOICE,
    DesignerValueKind.STRING_LIST: DesignerInspectorEditorKind.STRING_LIST,
    DesignerValueKind.NUMBER_LIST: DesignerInspectorEditorKind.NUMBER_LIST,
    DesignerValueKind.DIMENSION: DesignerInspectorEditorKind.DIMENSION,
    DesignerValueKind.INSETS: DesignerInspectorEditorKind.INSETS,
}


def inspector_editor_kind(kind: DesignerValueKind | str) -> DesignerInspectorEditorKind:
    """Return the semantic editor hint for one designer value kind."""

    resolved = DesignerValueKind(str(getattr(kind, "value", kind)).lower())
    return _EDITOR_KIND_BY_VALUE_KIND[resolved]


def _type_descriptor(session: DesignerEditSession, type_key: str) -> Mapping[str, object]:
    for descriptor in session.snapshot.types:
        if descriptor.get("key") == type_key:
            return descriptor
    raise KeyError(f"designer snapshot has no metadata for type: {type_key}")


@dataclass(frozen=True)
class DesignerInspectorRow:
    """One property row ready for a concrete property-inspector adapter."""

    property: DesignerPropertyState
    editor: DesignerInspectorEditorKind

    def __post_init__(self) -> None:
        if not isinstance(self.property, DesignerPropertyState):
            raise TypeError("designer inspector row requires DesignerPropertyState")
        object.__setattr__(self, "editor", DesignerInspectorEditorKind(self.editor))

    @classmethod
    def from_property_state(cls, state: DesignerPropertyState) -> "DesignerInspectorRow":
        if not isinstance(state, DesignerPropertyState):
            raise TypeError("designer inspector row requires DesignerPropertyState")
        return cls(state, inspector_editor_kind(state.kind))

    @property
    def node_id(self) -> str:
        return self.property.node_id

    @property
    def type_key(self) -> str:
        return self.property.type_key

    @property
    def key(self) -> str:
        return self.property.key

    @property
    def label(self) -> str:
        return self.property.label

    @property
    def kind(self) -> DesignerValueKind:
        return self.property.kind

    @property
    def editable(self) -> bool:
        return self.property.editable

    @property
    def serializable(self) -> bool:
        return self.property.serializable

    @property
    def nullable(self) -> bool:
        return self.property.nullable

    @property
    def unsettable(self) -> bool:
        return self.property.unsettable

    @property
    def is_set(self) -> bool:
        return self.property.is_set

    @property
    def value(self) -> object:
        return self.property.value

    @property
    def choices(self) -> tuple[object, ...]:
        return self.property.choices

    @property
    def minimum(self) -> int | float | None:
        return self.property.minimum

    @property
    def maximum(self) -> int | float | None:
        return self.property.maximum

    @property
    def can_edit(self) -> bool:
        """Whether a normal inspector editor may write this property."""

        return self.editable and self.serializable

    @property
    def can_clear(self) -> bool:
        """Whether the current explicit value may be cleared/inherited."""

        return self.can_edit and self.unsettable and self.is_set

    @property
    def has_choices(self) -> bool:
        return bool(self.choices)

    @property
    def is_bounded(self) -> bool:
        return self.minimum is not None or self.maximum is not None

    def to_descriptor(self) -> dict[str, object]:
        descriptor = self.property.to_descriptor()
        descriptor["editor"] = self.editor.value
        descriptor["can_edit"] = self.can_edit
        descriptor["can_clear"] = self.can_clear
        return descriptor


@dataclass(frozen=True)
class DesignerInspectorState:
    """Current selection-driven property-inspector presentation state."""

    node_id: str = ""
    type_key: str = ""
    type_label: str = ""
    category: str = ""
    rows: tuple[DesignerInspectorRow, ...] = ()

    def __post_init__(self) -> None:
        if not all(isinstance(row, DesignerInspectorRow) for row in self.rows):
            raise TypeError("designer inspector rows must be DesignerInspectorRow instances")
        if not self.node_id and any((self.type_key, self.type_label, self.category, self.rows)):
            raise ValueError("empty designer inspector state cannot contain target metadata")

    @property
    def has_target(self) -> bool:
        return bool(self.node_id)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def editable_count(self) -> int:
        return sum(1 for row in self.rows if row.can_edit)

    @property
    def clearable_count(self) -> int:
        return sum(1 for row in self.rows if row.can_clear)

    def row(self, property_key: object) -> DesignerInspectorRow | None:
        key = str(property_key or "").strip()
        if not key:
            raise ValueError("designer property key must be non-empty")
        return next((row for row in self.rows if row.key == key), None)

    def to_descriptor(self) -> dict[str, object]:
        if not self.has_target:
            return {"target": None, "rows": []}
        return {
            "target": {
                "node_id": self.node_id,
                "type": self.type_key,
                "label": self.type_label,
                "category": self.category,
            },
            "rows": [row.to_descriptor() for row in self.rows],
        }


class DesignerPropertyInspector:
    """Project selected-node metadata into deterministic inspector rows.

    The inspector deliberately reads the session's existing stable selection on
    every projection.  It does not cache selection, property values or document
    snapshots, so accepted edits and selection changes are reflected immediately.
    """

    def __init__(self, session: DesignerEditSession):
        if not isinstance(session, DesignerEditSession):
            raise TypeError("designer property inspector requires DesignerEditSession")
        self._session = session

    @property
    def session(self) -> DesignerEditSession:
        return self._session

    def state(self, *, include_read_only: bool = True) -> DesignerInspectorState:
        node = self._session.selected_node()
        if node is None:
            return DesignerInspectorState()

        descriptor = _type_descriptor(self._session, node.type_key)
        property_states = self._session.property_states(
            node.node_id,
            include_read_only=include_read_only,
        )
        rows = tuple(DesignerInspectorRow.from_property_state(state) for state in property_states)
        return DesignerInspectorState(
            node_id=node.node_id,
            type_key=node.type_key,
            type_label=str(descriptor.get("label", node.type_key)),
            category=str(descriptor.get("category", "component")),
            rows=rows,
        )

    def rows(self, *, include_read_only: bool = True) -> tuple[DesignerInspectorRow, ...]:
        return self.state(include_read_only=include_read_only).rows

    def row(
        self,
        property_key: object,
        *,
        include_read_only: bool = True,
    ) -> DesignerInspectorRow | None:
        return self.state(include_read_only=include_read_only).row(property_key)


__all__ = [
    "DesignerInspectorEditorKind",
    "DesignerInspectorRow",
    "DesignerInspectorState",
    "DesignerPropertyInspector",
    "inspector_editor_kind",
]
