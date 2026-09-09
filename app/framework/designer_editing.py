"""Provisional command-based editing and undo/redo for designer snapshots.

Tranche 9 established backend-neutral component/type metadata and immutable,
JSON-safe hierarchy snapshots.  This module adds the next deliberately narrow
RAD prerequisite: explicit commands that edit *snapshot data* plus deterministic
undo/redo history.

The editing boundary intentionally does not rebuild or mutate live component
objects. Property commands, structural hierarchy commands and optional
copy/paste/duplicate document commands share the same immutable-snapshot history.
Clipboard and stable-ID selection/focus state are ephemeral editor state rather
than project persistence or undoable document data. Preview hosts may consume
checked candidate snapshots, but toolkit objects, callbacks,
application models, drag/drop behavior and the final project-document schema
remain outside this module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
import math
from typing import Callable, Protocol

from .designer import (
    DesignerChild,
    DesignerNode,
    DesignerSnapshot,
    DesignerValueKind,
)
from .designer_clipboard import (
    DesignerClipboardPayload,
    DuplicateDesignerNode,
    PasteDesignerSubtree,
    copy_designer_subtree,
)
from .designer_selection import DesignerSelectionModel, DesignerSelectionState
from .designer_structure import (
    DesignerNodeLocation,
    InsertDesignerChild,
    MoveDesignerNode,
    RemoveDesignerNode,
    ReparentDesignerNode,
    locate_designer_node,
)
from .interactions import CommandSet, CommandSpec


DESIGNER_UNDO_COMMAND = "designer.undo"
DESIGNER_REDO_COMMAND = "designer.redo"


def _key(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


def _json_copy(value: object) -> object:
    """Return a detached JSON-safe copy and reject non-finite numbers."""

    try:
        payload = json.dumps(value, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise TypeError("designer edit value must be JSON-safe") from exc
    return json.loads(payload)


def _type_descriptor(snapshot: DesignerSnapshot, type_key: str) -> Mapping[str, object]:
    for descriptor in snapshot.types:
        if descriptor.get("key") == type_key:
            return descriptor
    raise KeyError(f"designer snapshot has no metadata for type: {type_key}")


def _property_descriptor(
    snapshot: DesignerSnapshot,
    node: DesignerNode,
    property_key: object,
) -> Mapping[str, object]:
    resolved_key = _key(property_key, field="designer property key")
    type_descriptor = _type_descriptor(snapshot, node.type_key)
    properties = type_descriptor.get("properties", ())
    if isinstance(properties, (str, bytes)) or not isinstance(properties, Iterable):
        raise TypeError("designer type property metadata must be iterable")
    for descriptor in properties:
        if not isinstance(descriptor, Mapping):
            raise TypeError("designer property metadata must be mappings")
        if descriptor.get("key") == resolved_key:
            return descriptor
    raise KeyError(
        f"designer property {resolved_key!r} is not defined for type {node.type_key!r}"
    )


def _find_node(snapshot: DesignerSnapshot, node_id: object) -> DesignerNode:
    resolved = _key(node_id, field="designer node id")
    for node in snapshot.root.walk():
        if node.node_id == resolved:
            return node
    raise KeyError(f"designer node not found: {resolved}")


def _replace_node(
    node: DesignerNode,
    target_id: str,
    replacement,
) -> tuple[DesignerNode, bool]:
    if node.node_id == target_id:
        updated = replacement(node)
        if not isinstance(updated, DesignerNode):
            raise TypeError("designer node replacement must return DesignerNode")
        return updated, True

    changed = False
    children: list[DesignerChild] = []
    for child in node.children:
        updated_node, child_changed = _replace_node(child.node, target_id, replacement)
        changed = changed or child_changed
        if child_changed:
            children.append(DesignerChild(child.slot, updated_node, child.metadata))
        else:
            children.append(child)
    if not changed:
        return node, False
    return DesignerNode(node.node_id, node.type_key, node.properties, children), True


def _snapshot_with_root(snapshot: DesignerSnapshot, root: DesignerNode) -> DesignerSnapshot:
    return DesignerSnapshot(
        root,
        snapshot.types,
        kind=snapshot.kind,
        version=snapshot.version,
    )


def _number(value: object, *, field: str, integer: bool) -> int | float:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be {'an integer' if integer else 'numeric'}")
    if integer:
        if not isinstance(value, int):
            raise TypeError(f"{field} must be an integer")
        return int(value)
    if not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    resolved = int(value) if isinstance(value, int) else float(value)
    if not math.isfinite(float(resolved)):
        raise ValueError(f"{field} must be finite")
    return resolved


def _bounded_number(
    value: object,
    descriptor: Mapping[str, object],
    *,
    field: str,
    integer: bool,
) -> int | float:
    resolved = _number(value, field=field, integer=integer)
    minimum = descriptor.get("minimum")
    maximum = descriptor.get("maximum")
    if minimum is not None and float(resolved) < float(minimum):
        raise ValueError(f"{field} must be >= {minimum}")
    if maximum is not None and float(resolved) > float(maximum):
        raise ValueError(f"{field} must be <= {maximum}")
    return resolved


def _list_value(value: object, *, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be a list-like value")
    return tuple(value)


def _insets_value(value: object, *, field: str) -> dict[str, int]:
    names = ("left", "top", "right", "bottom")
    if isinstance(value, Mapping):
        unknown = set(value).difference(names)
        if unknown:
            raise ValueError(f"{field} contains unknown inset fields: {', '.join(sorted(map(str, unknown)))}")
        if set(value) != set(names):
            raise ValueError(f"{field} mapping must contain left, top, right and bottom")
        parts = tuple(value[name] for name in names)
    elif isinstance(value, bool):
        raise TypeError(f"{field} must be an inset mapping, integer, 2-tuple or 4-tuple")
    elif isinstance(value, int):
        parts = (value, value, value, value)
    else:
        compact = _list_value(value, field=field)
        if len(compact) == 2:
            horizontal, vertical = compact
            parts = (horizontal, vertical, horizontal, vertical)
        elif len(compact) == 4:
            parts = compact
        else:
            raise ValueError(f"{field} inset sequence must contain 2 or 4 values")

    result = {}
    for name, part in zip(names, parts):
        resolved = _number(part, field=f"{field} {name}", integer=True)
        if resolved < 0:
            raise ValueError(f"{field} {name} must be non-negative")
        result[name] = int(resolved)
    return result


def normalize_designer_property_value(
    descriptor: Mapping[str, object],
    value: object,
) -> object:
    """Validate and normalize one property value from snapshot metadata.

    The metadata travels inside :class:`DesignerSnapshot`, so this function does
    not need a runtime component class or GUI backend to validate an edit.
    """

    if not isinstance(descriptor, Mapping):
        raise TypeError("designer property metadata must be a mapping")
    key = _key(descriptor.get("key"), field="designer property key")
    field = f"designer property {key!r}"
    nullable = bool(descriptor.get("nullable", False))
    if value is None:
        if nullable:
            return None
        raise TypeError(f"{field} does not allow None")

    try:
        kind = DesignerValueKind(str(descriptor.get("kind", "")).lower())
    except ValueError as exc:
        raise ValueError(f"{field} has unsupported value kind") from exc

    if kind is DesignerValueKind.TEXT:
        if not isinstance(value, str):
            raise TypeError(f"{field} must be text")
        return value

    if kind is DesignerValueKind.BOOLEAN:
        if not isinstance(value, bool):
            raise TypeError(f"{field} must be boolean")
        return value

    if kind is DesignerValueKind.INTEGER:
        return _bounded_number(value, descriptor, field=field, integer=True)

    if kind is DesignerValueKind.NUMBER:
        return _bounded_number(value, descriptor, field=field, integer=False)

    if kind is DesignerValueKind.CHOICE:
        choices = descriptor.get("choices", ())
        if isinstance(choices, (str, bytes)) or not isinstance(choices, Iterable):
            raise TypeError(f"{field} choice metadata must be iterable")
        safe_value = _json_copy(value)
        safe_choices = tuple(_json_copy(choice) for choice in choices)
        if safe_value not in safe_choices:
            raise ValueError(f"{field} must be one of the declared choices")
        return safe_value

    if kind is DesignerValueKind.STRING_LIST:
        values = _list_value(value, field=field)
        if not all(isinstance(item, str) for item in values):
            raise TypeError(f"{field} must contain only text values")
        return list(values)

    if kind is DesignerValueKind.NUMBER_LIST:
        values = _list_value(value, field=field)
        return [
            _number(item, field=f"{field} item", integer=False)
            for item in values
        ]

    if kind is DesignerValueKind.DIMENSION:
        if isinstance(value, str):
            resolved = value.strip().lower()
            if resolved not in {"auto", "fill"}:
                raise ValueError(f"{field} must be 'auto', 'fill' or a positive integer")
            return resolved
        resolved = _number(value, field=field, integer=True)
        if resolved <= 0:
            raise ValueError(f"{field} integer dimensions must be positive")
        return int(resolved)

    if kind is DesignerValueKind.INSETS:
        return _insets_value(value, field=field)

    raise ValueError(f"{field} has unsupported value kind")


@dataclass(frozen=True)
class DesignerPropertyState:
    """Inspector-facing value plus the metadata required to edit it safely."""

    node_id: str
    type_key: str
    key: str
    label: str
    kind: DesignerValueKind
    editable: bool
    serializable: bool
    nullable: bool
    unsettable: bool
    is_set: bool
    value: object = None
    choices: tuple[object, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None

    def to_descriptor(self) -> dict[str, object]:
        result: dict[str, object] = {
            "node_id": self.node_id,
            "type": self.type_key,
            "key": self.key,
            "label": self.label,
            "kind": self.kind.value,
            "editable": self.editable,
            "serializable": self.serializable,
            "nullable": self.nullable,
            "unsettable": self.unsettable,
            "is_set": self.is_set,
        }
        if self.is_set:
            result["value"] = _json_copy(self.value)
        if self.choices:
            result["choices"] = [_json_copy(value) for value in self.choices]
        if self.minimum is not None:
            result["minimum"] = self.minimum
        if self.maximum is not None:
            result["maximum"] = self.maximum
        return result


class DesignerEditCommand(Protocol):
    """Typed contract for one explicit designer-snapshot mutation."""

    @property
    def label(self) -> str:
        ...

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        ...


@dataclass(frozen=True)
class SetDesignerProperty:
    """Set one serializable editable property on one designer node."""

    node_id: str
    property_key: str
    value: object

    def __init__(self, node_id: object, property_key: object, value: object):
        object.__setattr__(self, "node_id", _key(node_id, field="designer node id"))
        object.__setattr__(
            self,
            "property_key",
            _key(property_key, field="designer property key"),
        )
        object.__setattr__(self, "value", value)

    @property
    def label(self) -> str:
        return f"Set {self.property_key}"

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        return _set_property(snapshot, self.node_id, self.property_key, self.value)


@dataclass(frozen=True)
class ClearDesignerProperty:
    """Remove an explicit property so a later runtime can inherit/default it."""

    node_id: str
    property_key: str

    def __init__(self, node_id: object, property_key: object):
        object.__setattr__(self, "node_id", _key(node_id, field="designer node id"))
        object.__setattr__(
            self,
            "property_key",
            _key(property_key, field="designer property key"),
        )

    @property
    def label(self) -> str:
        return f"Reset {self.property_key}"

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        return _clear_property(snapshot, self.node_id, self.property_key)


@dataclass(frozen=True)
class CompositeDesignerEdit:
    """Group several explicit edits into one undo/redo history step."""

    commands: tuple[DesignerEditCommand, ...]
    label: str

    def __init__(
        self,
        commands: Iterable[DesignerEditCommand],
        *,
        label: object = "Edit properties",
    ):
        resolved = tuple(commands)
        if not resolved:
            raise ValueError("composite designer edit requires at least one command")
        for command in resolved:
            if not callable(getattr(command, "apply", None)):
                raise TypeError("composite designer edits require command objects")
            _key(getattr(command, "label", ""), field="designer edit label")
        object.__setattr__(self, "commands", resolved)
        object.__setattr__(self, "label", _key(label, field="designer edit label"))

    def apply(self, snapshot: DesignerSnapshot) -> DesignerSnapshot:
        result = snapshot
        for command in self.commands:
            result = command.apply(result)
            if not isinstance(result, DesignerSnapshot):
                raise TypeError("designer edit command must return DesignerSnapshot")
        return result


@dataclass(frozen=True)
class _DesignerHistoryEntry:
    label: str
    before: DesignerSnapshot
    after: DesignerSnapshot


def _editable_serializable_property(
    snapshot: DesignerSnapshot,
    node: DesignerNode,
    property_key: object,
) -> Mapping[str, object]:
    descriptor = _property_descriptor(snapshot, node, property_key)
    key = _key(descriptor.get("key"), field="designer property key")
    if not bool(descriptor.get("editable", True)):
        raise ValueError(f"designer property {key!r} is read-only")
    if not bool(descriptor.get("serializable", True)):
        raise ValueError(f"designer property {key!r} is not snapshot-serializable")
    return descriptor


def _set_property(
    snapshot: DesignerSnapshot,
    node_id: object,
    property_key: object,
    value: object,
) -> DesignerSnapshot:
    if not isinstance(snapshot, DesignerSnapshot):
        raise TypeError("designer edit requires DesignerSnapshot")
    resolved_id = _key(node_id, field="designer node id")
    node = _find_node(snapshot, resolved_id)
    descriptor = _editable_serializable_property(snapshot, node, property_key)
    key = _key(descriptor.get("key"), field="designer property key")
    normalized = normalize_designer_property_value(descriptor, value)

    if key in node.properties and node.properties[key] == normalized:
        return snapshot

    def replacement(current: DesignerNode) -> DesignerNode:
        properties = dict(current.properties)
        properties[key] = _json_copy(normalized)
        return DesignerNode(current.node_id, current.type_key, properties, current.children)

    root, changed = _replace_node(snapshot.root, resolved_id, replacement)
    if not changed:
        raise KeyError(f"designer node not found: {resolved_id}")
    return _snapshot_with_root(snapshot, root)


def _clear_property(
    snapshot: DesignerSnapshot,
    node_id: object,
    property_key: object,
) -> DesignerSnapshot:
    if not isinstance(snapshot, DesignerSnapshot):
        raise TypeError("designer edit requires DesignerSnapshot")
    resolved_id = _key(node_id, field="designer node id")
    node = _find_node(snapshot, resolved_id)
    descriptor = _editable_serializable_property(snapshot, node, property_key)
    key = _key(descriptor.get("key"), field="designer property key")
    if not bool(descriptor.get("unsettable", False)):
        raise ValueError(f"designer property {key!r} cannot be unset")
    if key not in node.properties:
        return snapshot

    def replacement(current: DesignerNode) -> DesignerNode:
        properties = dict(current.properties)
        properties.pop(key, None)
        return DesignerNode(current.node_id, current.type_key, properties, current.children)

    root, changed = _replace_node(snapshot.root, resolved_id, replacement)
    if not changed:
        raise KeyError(f"designer node not found: {resolved_id}")
    return _snapshot_with_root(snapshot, root)


class DesignerEditSession:
    """Current snapshot plus explicit edit history and inspector state.

    Whole immutable snapshots are retained for history in this provisional
    implementation.  That favors correctness and simple recovery while the
    designer contract is still evolving; a later project-document layer can
    adopt more compact deltas without changing the command semantics.
    """

    def __init__(self, snapshot: DesignerSnapshot):
        if not isinstance(snapshot, DesignerSnapshot):
            raise TypeError("designer edit session requires DesignerSnapshot")
        self._snapshot = snapshot
        self._clean = snapshot
        self._undo: list[_DesignerHistoryEntry] = []
        self._redo: list[_DesignerHistoryEntry] = []
        self._clipboard: DesignerClipboardPayload | None = None
        self._selection = DesignerSelectionModel()

    @property
    def snapshot(self) -> DesignerSnapshot:
        return self._snapshot

    @property
    def is_dirty(self) -> bool:
        return self._snapshot != self._clean

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def has_clipboard(self) -> bool:
        return self._clipboard is not None

    @property
    def clipboard(self) -> DesignerClipboardPayload | None:
        return self._clipboard

    @property
    def selection_state(self) -> DesignerSelectionState:
        return self._selection.state

    @property
    def selected_node_id(self) -> str:
        return self._selection.selected_id

    @property
    def focused_node_id(self) -> str:
        return self._selection.focused_id

    @property
    def has_selection(self) -> bool:
        return self._selection.has_selection

    @property
    def has_focus(self) -> bool:
        return self._selection.has_focus

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    @property
    def redo_depth(self) -> int:
        return len(self._redo)

    @property
    def undo_label(self) -> str:
        return self._undo[-1].label if self._undo else ""

    @property
    def redo_label(self) -> str:
        return self._redo[-1].label if self._redo else ""

    def mark_clean(self) -> None:
        self._clean = self._snapshot

    def select_node(self, node_id: object, *, focus: bool = False) -> bool:
        return self._selection.select(self._snapshot, node_id, focus=focus)

    def focus_node(self, node_id: object, *, select: bool = False) -> bool:
        return self._selection.focus(self._snapshot, node_id, select=select)

    def select_and_focus_node(self, node_id: object) -> bool:
        return self._selection.select_and_focus(self._snapshot, node_id)

    def clear_selection(self) -> bool:
        return self._selection.clear_selection()

    def clear_focus(self) -> bool:
        return self._selection.clear_focus()

    def clear_selection_and_focus(self) -> bool:
        return self._selection.clear()

    def selected_node(self) -> DesignerNode | None:
        return self._selection.selected_node(self._snapshot)

    def focused_node(self) -> DesignerNode | None:
        return self._selection.focused_node(self._snapshot)

    def selected_location(self) -> DesignerNodeLocation | None:
        return self._selection.selected_location(self._snapshot)

    def focused_location(self) -> DesignerNodeLocation | None:
        return self._selection.focused_location(self._snapshot)

    def node(self, node_id: object) -> DesignerNode:
        return _find_node(self._snapshot, node_id)

    def property_state(self, node_id: object, property_key: object) -> DesignerPropertyState:
        node = self.node(node_id)
        descriptor = _property_descriptor(self._snapshot, node, property_key)
        key = _key(descriptor.get("key"), field="designer property key")
        kind = DesignerValueKind(str(descriptor.get("kind", "")).lower())
        choices = descriptor.get("choices", ())
        if isinstance(choices, (str, bytes)) or not isinstance(choices, Iterable):
            raise TypeError("designer property choice metadata must be iterable")
        is_set = key in node.properties
        value = _json_copy(node.properties[key]) if is_set else None
        return DesignerPropertyState(
            node.node_id,
            node.type_key,
            key,
            str(descriptor.get("label", key)),
            kind,
            bool(descriptor.get("editable", True)),
            bool(descriptor.get("serializable", True)),
            bool(descriptor.get("nullable", False)),
            bool(descriptor.get("unsettable", False)),
            is_set,
            value,
            tuple(_json_copy(choice) for choice in choices),
            descriptor.get("minimum"),  # type: ignore[arg-type]
            descriptor.get("maximum"),  # type: ignore[arg-type]
        )

    def property_states(
        self,
        node_id: object,
        *,
        include_read_only: bool = True,
    ) -> tuple[DesignerPropertyState, ...]:
        node = self.node(node_id)
        type_descriptor = _type_descriptor(self._snapshot, node.type_key)
        properties = type_descriptor.get("properties", ())
        if isinstance(properties, (str, bytes)) or not isinstance(properties, Iterable):
            raise TypeError("designer type property metadata must be iterable")
        states = []
        for descriptor in properties:
            if not isinstance(descriptor, Mapping):
                raise TypeError("designer property metadata must be mappings")
            if not include_read_only and not bool(descriptor.get("editable", True)):
                continue
            states.append(self.property_state(node.node_id, descriptor.get("key")))
        return tuple(states)

    def execute_checked(
        self,
        command: DesignerEditCommand,
        check: Callable[[DesignerSnapshot], object],
    ) -> bool:
        """Apply *command* only after ``check(candidate_snapshot)`` succeeds.

        The check runs before current snapshot/history state is mutated.  This
        gives higher layers such as preview hosts a generic transaction gate
        without making the editing core depend on renderers or toolkits.
        """

        if not callable(check):
            raise TypeError("designer checked edit requires a callable check")
        apply = getattr(command, "apply", None)
        if not callable(apply):
            raise TypeError("designer edit session requires a command with apply(snapshot)")
        label = _key(getattr(command, "label", ""), field="designer edit label")
        before = self._snapshot
        after = apply(before)
        if not isinstance(after, DesignerSnapshot):
            raise TypeError("designer edit command must return DesignerSnapshot")
        if after == before:
            return False
        check(after)
        self._snapshot = after
        self._selection.reconcile(before, after)
        self._undo.append(_DesignerHistoryEntry(label, before, after))
        self._redo.clear()
        return True

    def execute(self, command: DesignerEditCommand) -> bool:
        return self.execute_checked(command, lambda _snapshot: None)

    def set_property(self, node_id: object, property_key: object, value: object) -> bool:
        return self.execute(SetDesignerProperty(node_id, property_key, value))

    def clear_property(self, node_id: object, property_key: object) -> bool:
        return self.execute(ClearDesignerProperty(node_id, property_key))

    def location(self, node_id: object) -> DesignerNodeLocation:
        return locate_designer_node(self._snapshot, node_id)

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
            InsertDesignerChild(
                parent_id,
                node,
                slot=slot,
                metadata=metadata,
                index=index,
            )
        )

    def remove_node(self, node_id: object) -> bool:
        return self.execute(RemoveDesignerNode(node_id))

    def copy_node(self, node_id: object) -> DesignerClipboardPayload:
        """Copy one subtree into ephemeral session clipboard state.

        Copying never mutates the document, dirty state, undo depth or redo
        branch.  The returned payload can also be transferred explicitly to a
        different compatible ``DesignerEditSession``.
        """

        payload = copy_designer_subtree(self._snapshot, node_id)
        self._clipboard = payload
        return payload

    def clear_clipboard(self) -> bool:
        if self._clipboard is None:
            return False
        self._clipboard = None
        return True

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
        source = payload if payload is not None else self._clipboard
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

    def undo_checked(self, check: Callable[[DesignerSnapshot], object]) -> bool:
        """Undo only after ``check`` accepts the prospective snapshot."""

        if not callable(check):
            raise TypeError("designer checked undo requires a callable check")
        if not self._undo:
            return False
        entry = self._undo[-1]
        check(entry.before)
        current = self._snapshot
        self._undo.pop()
        self._snapshot = entry.before
        self._selection.reconcile(current, entry.before)
        self._redo.append(entry)
        return True

    def undo(self) -> bool:
        return self.undo_checked(lambda _snapshot: None)

    def redo_checked(self, check: Callable[[DesignerSnapshot], object]) -> bool:
        """Redo only after ``check`` accepts the prospective snapshot."""

        if not callable(check):
            raise TypeError("designer checked redo requires a callable check")
        if not self._redo:
            return False
        entry = self._redo[-1]
        check(entry.after)
        current = self._snapshot
        self._redo.pop()
        self._snapshot = entry.after
        self._selection.reconcile(current, entry.after)
        self._undo.append(entry)
        return True

    def redo(self) -> bool:
        return self.redo_checked(lambda _snapshot: None)

    def history_commands(self) -> CommandSet:
        undo_label = "Undo" if not self.undo_label else f"Undo {self.undo_label}"
        redo_label = "Redo" if not self.redo_label else f"Redo {self.redo_label}"
        return CommandSet(
            (
                CommandSpec(DESIGNER_UNDO_COMMAND, undo_label, enabled=self.can_undo),
                CommandSpec(DESIGNER_REDO_COMMAND, redo_label, enabled=self.can_redo),
            )
        )

    def dispatch_history_command(self, key: object) -> bool:
        commands = self.history_commands()

        def dispatch(command_key: str) -> bool:
            if command_key == DESIGNER_UNDO_COMMAND:
                return self.undo()
            if command_key == DESIGNER_REDO_COMMAND:
                return self.redo()
            raise KeyError(command_key)

        return bool(commands.dispatch(key, dispatch))


__all__ = [
    "DESIGNER_REDO_COMMAND",
    "DESIGNER_UNDO_COMMAND",
    "ClearDesignerProperty",
    "DesignerClipboardPayload",
    "CompositeDesignerEdit",
    "DesignerEditCommand",
    "DesignerEditSession",
    "DesignerPropertyState",
    "SetDesignerProperty",
    "normalize_designer_property_value",
]
