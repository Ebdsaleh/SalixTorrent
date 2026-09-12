"""Provisional designer metadata and serializable component-tree snapshots.

This module is intentionally smaller than a full RAD project/document model.  It
provides the pieces the future designer already needs to reason about proven
framework components without importing a GUI toolkit:

* stable type keys and editable-property metadata;
* stable per-object identities while a live component tree is being inspected;
* backend-neutral parent/child relationship metadata;
* JSON-safe snapshot round trips.

The descriptor keys are internal working contracts.  They are deliberately not
a public package/schema freeze and do not yet reconstruct executable component
instances, callbacks, application models, or toolkit resources.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
import json
from weakref import WeakKeyDictionary, WeakValueDictionary

from .components.base import Component
from .components.containers import (
    ControlColumn,
    ControlGrid,
    ControlRow,
    Dialog,
    PlacedComponent,
    PositionedPanel,
    SectionPanel,
)
from .components.controls import (
    Button,
    CheckBox,
    ComboBox,
    Label,
    NumericStepper,
    ProgressBar,
    Separator,
    Spacer,
    TextInput,
)
from .components.fields import (
    DurationEditor,
    LabeledComboField,
    LabeledField,
    LabeledNumericField,
    NumericUnitField,
)
from .components.placement import AnchoredChild, PositionedChild
from .components.regions import SplitPanel, TabContainer, TabPage
from .property_cascade import UNSET


DESIGNER_SNAPSHOT_KIND = "salix-component-snapshot"
DESIGNER_SNAPSHOT_VERSION = 1


def _key(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


class DesignerValueKind(str, Enum):
    """Portable editor-facing value categories for component properties."""

    TEXT = "text"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    CHOICE = "choice"
    STRING_LIST = "string_list"
    NUMBER_LIST = "number_list"
    DIMENSION = "dimension"
    INSETS = "insets"


@dataclass(frozen=True)
class DesignerPropertySpec:
    """Metadata for one inspectable/editable component property."""

    key: str
    label: str
    kind: DesignerValueKind
    attribute: str | None = None
    editable: bool = True
    serializable: bool = True
    nullable: bool = False
    unsettable: bool = False
    choices: tuple[object, ...] = ()
    minimum: float | int | None = None
    maximum: float | int | None = None

    def __init__(
        self,
        key: object,
        label: object,
        kind: DesignerValueKind | str,
        *,
        attribute: str | None = None,
        editable: bool = True,
        serializable: bool = True,
        nullable: bool = False,
        unsettable: bool = False,
        choices: Iterable[object] = (),
        minimum: float | int | None = None,
        maximum: float | int | None = None,
    ):
        resolved_kind = DesignerValueKind(str(getattr(kind, "value", kind)).lower())
        resolved_attribute = str(attribute).strip() if attribute else None
        resolved_choices = tuple(choices)
        if minimum is not None and isinstance(minimum, bool):
            raise TypeError("designer property minimum must be numeric or None")
        if maximum is not None and isinstance(maximum, bool):
            raise TypeError("designer property maximum must be numeric or None")
        if minimum is not None and maximum is not None and float(maximum) < float(minimum):
            raise ValueError("designer property maximum must be >= minimum")
        if resolved_choices and resolved_kind is not DesignerValueKind.CHOICE:
            raise ValueError("designer property choices require choice kind")
        object.__setattr__(self, "key", _key(key, field="designer property key"))
        object.__setattr__(self, "label", str(label))
        object.__setattr__(self, "kind", resolved_kind)
        object.__setattr__(self, "attribute", resolved_attribute)
        object.__setattr__(self, "editable", bool(editable))
        object.__setattr__(self, "serializable", bool(serializable))
        object.__setattr__(self, "nullable", bool(nullable))
        object.__setattr__(self, "unsettable", bool(unsettable))
        object.__setattr__(self, "choices", resolved_choices)
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)

    @property
    def attribute_path(self) -> str:
        return self.attribute or self.key

    def to_descriptor(self) -> dict:
        descriptor = {
            "key": self.key,
            "label": self.label,
            "kind": self.kind.value,
            "editable": self.editable,
            "serializable": self.serializable,
            "nullable": self.nullable,
            "unsettable": self.unsettable,
        }
        if self.choices:
            descriptor["choices"] = [_json_safe(value) for value in self.choices]
        if self.minimum is not None:
            descriptor["minimum"] = self.minimum
        if self.maximum is not None:
            descriptor["maximum"] = self.maximum
        return descriptor


@dataclass(frozen=True)
class DesignerChildSlotSpec:
    """Provisional structural metadata for one allowed child relationship slot.

    ``required_metadata`` lists relationship fields that must accompany children
    inserted into the slot. ``unique_by`` identifies metadata fields whose
    combined values must be unique among siblings in the same slot.  These are
    editor/document constraints only; they do not construct runtime components.
    """

    key: str
    label: str
    multiple: bool = True
    allowed_metadata: tuple[str, ...] = ()
    required_metadata: tuple[str, ...] = ()
    unique_by: tuple[str, ...] = ()

    def __init__(
        self,
        key: object,
        label: object,
        *,
        multiple: bool = True,
        allowed_metadata: Iterable[object] = (),
        required_metadata: Iterable[object] = (),
        unique_by: Iterable[object] = (),
    ):
        resolved_allowed = tuple(
            _key(value, field="designer child metadata key") for value in allowed_metadata
        )
        resolved_required = tuple(
            _key(value, field="designer child metadata key") for value in required_metadata
        )
        resolved_unique = tuple(
            _key(value, field="designer child metadata key") for value in unique_by
        )
        if len(resolved_allowed) != len(set(resolved_allowed)):
            raise ValueError("designer child allowed metadata keys must be unique")
        if len(resolved_required) != len(set(resolved_required)):
            raise ValueError("designer child required metadata keys must be unique")
        if len(resolved_unique) != len(set(resolved_unique)):
            raise ValueError("designer child uniqueness metadata keys must be unique")
        allowed = resolved_allowed or resolved_required
        missing_required = set(resolved_required).difference(allowed)
        if missing_required:
            raise ValueError(
                "designer child required metadata must also be allowed: "
                + ", ".join(sorted(missing_required))
            )
        missing = set(resolved_unique).difference(resolved_required)
        if missing:
            raise ValueError(
                "designer child uniqueness keys must also be required metadata: "
                + ", ".join(sorted(missing))
            )
        object.__setattr__(self, "key", _key(key, field="designer child slot"))
        object.__setattr__(self, "label", str(label))
        object.__setattr__(self, "multiple", bool(multiple))
        object.__setattr__(self, "allowed_metadata", allowed)
        object.__setattr__(self, "required_metadata", resolved_required)
        object.__setattr__(self, "unique_by", resolved_unique)

    def to_descriptor(self) -> dict:
        descriptor = {
            "key": self.key,
            "label": self.label,
            "multiple": self.multiple,
        }
        if self.allowed_metadata:
            descriptor["allowed_metadata"] = list(self.allowed_metadata)
        if self.required_metadata:
            descriptor["required_metadata"] = list(self.required_metadata)
        if self.unique_by:
            descriptor["unique_by"] = list(self.unique_by)
        return descriptor


@dataclass(frozen=True)
class DesignerChildSource:
    """One runtime child plus metadata describing its relationship to a parent."""

    component: Component
    slot: str = "children"
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.component, Component):
            raise TypeError("designer child source must reference a Component")
        object.__setattr__(self, "slot", _key(self.slot, field="designer child slot"))
        if self.metadata is not None:
            _json_safe(self.metadata)


ChildReader = Callable[[Component], Iterable[DesignerChildSource]]


@dataclass(frozen=True)
class DesignerComponentSpec:
    """Runtime binding between one component class and editor metadata."""

    key: str
    label: str
    category: str
    component_type: type[Component]
    properties: tuple[DesignerPropertySpec, ...] = ()
    child_reader: ChildReader | None = None
    child_slots: tuple[DesignerChildSlotSpec, ...] = ()

    def __init__(
        self,
        key: object,
        label: object,
        component_type: type[Component],
        *,
        category: object = "component",
        properties: Iterable[DesignerPropertySpec] = (),
        child_reader: ChildReader | None = None,
        child_slots: Iterable[DesignerChildSlotSpec] = (),
    ):
        if not isinstance(component_type, type) or not issubclass(component_type, Component):
            raise TypeError("designer component type must derive from Component")
        resolved_properties = tuple(properties)
        if not all(isinstance(prop, DesignerPropertySpec) for prop in resolved_properties):
            raise TypeError("designer properties must be DesignerPropertySpec instances")
        property_keys = tuple(prop.key for prop in resolved_properties)
        if len(property_keys) != len(set(property_keys)):
            raise ValueError("designer property keys must be unique within a component type")
        if child_reader is not None and not callable(child_reader):
            raise TypeError("designer child reader must be callable or None")
        resolved_child_slots = tuple(child_slots)
        if not all(isinstance(slot, DesignerChildSlotSpec) for slot in resolved_child_slots):
            raise TypeError("designer child slots must be DesignerChildSlotSpec instances")
        slot_keys = tuple(slot.key for slot in resolved_child_slots)
        if len(slot_keys) != len(set(slot_keys)):
            raise ValueError("designer child slot keys must be unique within a component type")
        if child_reader is None and resolved_child_slots:
            raise ValueError("designer leaf component types cannot declare child slots")
        object.__setattr__(self, "key", _key(key, field="designer component type key"))
        object.__setattr__(self, "label", str(label))
        object.__setattr__(self, "category", _key(category, field="designer category"))
        object.__setattr__(self, "component_type", component_type)
        object.__setattr__(self, "properties", resolved_properties)
        object.__setattr__(self, "child_reader", child_reader)
        object.__setattr__(self, "child_slots", resolved_child_slots)

    @property
    def accepts_children(self) -> bool:
        return self.child_reader is not None

    def to_descriptor(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "accepts_children": self.accepts_children,
            "child_slots": [slot.to_descriptor() for slot in self.child_slots],
            "properties": [prop.to_descriptor() for prop in self.properties],
        }

    def capture_properties(self, component: Component) -> dict[str, object]:
        if not isinstance(component, self.component_type):
            raise TypeError(
                f"component for {self.key!r} must be {self.component_type.__name__}"
            )
        values: dict[str, object] = {}
        for prop in self.properties:
            if not prop.serializable:
                continue
            value = _read_attribute(component, prop.attribute_path)
            if value is UNSET:
                continue
            values[prop.key] = _json_safe(value)
        return values

    def children_of(self, component: Component) -> tuple[DesignerChildSource, ...]:
        if self.child_reader is None:
            return ()
        children = tuple(self.child_reader(component))
        if not all(isinstance(child, DesignerChildSource) for child in children):
            raise TypeError("designer child reader must yield DesignerChildSource instances")
        return children


class DesignerCatalog:
    """Validated runtime catalog of provisional designer component metadata."""

    def __init__(self, specs: Iterable[DesignerComponentSpec] = ()):
        self._by_key: dict[str, DesignerComponentSpec] = {}
        self._by_type: dict[type[Component], DesignerComponentSpec] = {}
        for spec in specs:
            self.register(spec)

    @property
    def specs(self) -> tuple[DesignerComponentSpec, ...]:
        return tuple(self._by_key.values())

    def register(self, spec: DesignerComponentSpec) -> DesignerComponentSpec:
        if not isinstance(spec, DesignerComponentSpec):
            raise TypeError("designer catalog entries must be DesignerComponentSpec instances")
        if spec.key in self._by_key:
            raise ValueError(f"duplicate designer component type key: {spec.key}")
        if spec.component_type in self._by_type:
            raise ValueError(
                f"designer component type already registered: {spec.component_type.__name__}"
            )
        self._by_key[spec.key] = spec
        self._by_type[spec.component_type] = spec
        return spec

    def get(self, key: object) -> DesignerComponentSpec:
        return self._by_key[_key(key, field="designer component type key")]

    def for_type(self, component_type: type[Component]) -> DesignerComponentSpec:
        if not isinstance(component_type, type) or not issubclass(component_type, Component):
            raise TypeError("designer component type must derive from Component")
        exact = self._by_type.get(component_type)
        if exact is not None:
            return exact
        for base_type in component_type.__mro__[1:]:
            spec = self._by_type.get(base_type)
            if spec is not None:
                return spec
        raise KeyError(f"unregistered designer component type: {component_type.__name__}")

    def resolve(self, component: Component) -> DesignerComponentSpec:
        return self.for_type(type(component))

    def metadata_descriptor(self, *, keys: Iterable[object] | None = None) -> list[dict]:
        if keys is None:
            specs = self.specs
        else:
            requested = {_key(key, field="designer component type key") for key in keys}
            missing = requested.difference(self._by_key)
            if missing:
                raise KeyError(next(iter(sorted(missing))))
            specs = tuple(spec for spec in self.specs if spec.key in requested)
        return [spec.to_descriptor() for spec in specs]


class DesignerIdentityMap:
    """Stable identities for live component objects during designer inspection.

    Generated identities stay stable for as long as the component object is
    alive and this map is retained.  Callers may bind an explicit persisted key
    before capture.  Rebinding a different component to an existing key is
    rejected.  A later preview/runtime bridge can restore persisted identities;
    that bridge is intentionally outside this tranche.
    """

    def __init__(self, *, prefix: object = "node"):
        self.prefix = _key(prefix, field="designer identity prefix")
        self._ids: WeakKeyDictionary[Component, str] = WeakKeyDictionary()
        self._owners: WeakValueDictionary[str, Component] = WeakValueDictionary()
        self._next = 1

    def bind(self, component: Component, node_id: object) -> str:
        if not isinstance(component, Component):
            raise TypeError("designer identity can only bind Component instances")
        resolved = _key(node_id, field="designer node id")
        existing = self._ids.get(component)
        if existing is not None and existing != resolved:
            raise ValueError(f"component already has designer identity {existing!r}")
        owner = self._owners.get(resolved)
        if owner is not None and owner is not component:
            raise ValueError(f"designer node id already belongs to another component: {resolved}")
        self._ids[component] = resolved
        self._owners[resolved] = component
        return resolved

    def identify(self, component: Component) -> str:
        if not isinstance(component, Component):
            raise TypeError("designer identity can only identify Component instances")
        existing = self._ids.get(component)
        if existing is not None:
            return existing
        while True:
            candidate = f"{self.prefix}-{self._next:04d}"
            self._next += 1
            if candidate not in self._owners:
                return self.bind(component, candidate)


@dataclass(frozen=True)
class DesignerChild:
    slot: str
    node: "DesignerNode"
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", _key(self.slot, field="designer child slot"))
        if not isinstance(self.node, DesignerNode):
            raise TypeError("designer child node must be a DesignerNode")
        if self.metadata is not None:
            object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_descriptor(self) -> dict:
        descriptor = {"slot": self.slot, "node": self.node.to_descriptor()}
        if self.metadata:
            descriptor["metadata"] = _json_safe(self.metadata)
        return descriptor

    @classmethod
    def from_descriptor(cls, descriptor: Mapping[str, object]) -> "DesignerChild":
        if not isinstance(descriptor, Mapping):
            raise TypeError("designer child descriptor must be a mapping")
        node = descriptor.get("node")
        if not isinstance(node, Mapping):
            raise TypeError("designer child descriptor requires a node mapping")
        metadata = descriptor.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise TypeError("designer child metadata must be a mapping")
        return cls(
            descriptor.get("slot", "children"),
            DesignerNode.from_descriptor(node),
            metadata,
        )


@dataclass(frozen=True)
class DesignerNode:
    node_id: str
    type_key: str
    properties: Mapping[str, object]
    children: tuple[DesignerChild, ...] = ()

    def __init__(
        self,
        node_id: object,
        type_key: object,
        properties: Mapping[str, object] | None = None,
        children: Iterable[DesignerChild] = (),
    ):
        resolved_children = tuple(children)
        if not all(isinstance(child, DesignerChild) for child in resolved_children):
            raise TypeError("designer node children must be DesignerChild instances")
        safe_properties = _json_safe(properties or {})
        if not isinstance(safe_properties, dict):
            raise TypeError("designer node properties must serialize as an object")
        object.__setattr__(self, "node_id", _key(node_id, field="designer node id"))
        object.__setattr__(self, "type_key", _key(type_key, field="designer component type key"))
        object.__setattr__(self, "properties", safe_properties)
        object.__setattr__(self, "children", resolved_children)

    def walk(self) -> tuple["DesignerNode", ...]:
        nodes: list[DesignerNode] = []

        def visit(node: DesignerNode) -> None:
            nodes.append(node)
            for child in node.children:
                visit(child.node)

        visit(self)
        return tuple(nodes)

    def to_descriptor(self) -> dict:
        return {
            "id": self.node_id,
            "type": self.type_key,
            "properties": _json_safe(self.properties),
            "children": [child.to_descriptor() for child in self.children],
        }

    @classmethod
    def from_descriptor(cls, descriptor: Mapping[str, object]) -> "DesignerNode":
        if not isinstance(descriptor, Mapping):
            raise TypeError("designer node descriptor must be a mapping")
        properties = descriptor.get("properties", {})
        if not isinstance(properties, Mapping):
            raise TypeError("designer node properties must be a mapping")
        children = descriptor.get("children", ())
        if isinstance(children, (str, bytes)) or not isinstance(children, Iterable):
            raise TypeError("designer node children must be iterable")
        return cls(
            descriptor.get("id"),
            descriptor.get("type"),
            properties,
            (DesignerChild.from_descriptor(child) for child in children),
        )


@dataclass(frozen=True)
class DesignerSnapshot:
    """Self-describing JSON-safe capture of one component hierarchy."""

    root: DesignerNode
    types: tuple[Mapping[str, object], ...]
    kind: str = DESIGNER_SNAPSHOT_KIND
    version: int = DESIGNER_SNAPSHOT_VERSION

    def __init__(
        self,
        root: DesignerNode,
        types: Iterable[Mapping[str, object]],
        *,
        kind: object = DESIGNER_SNAPSHOT_KIND,
        version: object = DESIGNER_SNAPSHOT_VERSION,
    ):
        if not isinstance(root, DesignerNode):
            raise TypeError("designer snapshot root must be a DesignerNode")
        resolved_kind = _key(kind, field="designer snapshot kind")
        if isinstance(version, bool):
            raise TypeError("designer snapshot version must be an integer")
        resolved_version = int(version)
        if resolved_version != DESIGNER_SNAPSHOT_VERSION:
            raise ValueError(f"unsupported designer snapshot version: {resolved_version}")
        safe_types = tuple(_json_safe(value) for value in types)
        if not all(isinstance(value, dict) for value in safe_types):
            raise TypeError("designer snapshot type metadata must serialize as objects")
        type_keys = tuple(_key(value.get("key"), field="designer component type key") for value in safe_types)
        if len(type_keys) != len(set(type_keys)):
            raise ValueError("designer snapshot type metadata keys must be unique")
        nodes = root.walk()
        node_ids = tuple(node.node_id for node in nodes)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("designer snapshot node ids must be unique")
        missing = {node.type_key for node in nodes}.difference(type_keys)
        if missing:
            raise ValueError(
                "designer snapshot is missing type metadata for: " + ", ".join(sorted(missing))
            )
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "types", safe_types)
        object.__setattr__(self, "kind", resolved_kind)
        object.__setattr__(self, "version", resolved_version)

    @property
    def node_count(self) -> int:
        return len(self.root.walk())

    def to_descriptor(self) -> dict:
        return {
            "kind": self.kind,
            "version": self.version,
            "types": [_json_safe(value) for value in self.types],
            "root": self.root.to_descriptor(),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_descriptor(), indent=indent, sort_keys=True)

    @classmethod
    def from_descriptor(cls, descriptor: Mapping[str, object]) -> "DesignerSnapshot":
        if not isinstance(descriptor, Mapping):
            raise TypeError("designer snapshot descriptor must be a mapping")
        if descriptor.get("kind") != DESIGNER_SNAPSHOT_KIND:
            raise ValueError("designer snapshot kind is invalid")
        root = descriptor.get("root")
        if not isinstance(root, Mapping):
            raise TypeError("designer snapshot requires a root mapping")
        types = descriptor.get("types", ())
        if isinstance(types, (str, bytes)) or not isinstance(types, Iterable):
            raise TypeError("designer snapshot types must be iterable")
        return cls(
            DesignerNode.from_descriptor(root),
            types,
            kind=descriptor.get("kind"),
            version=descriptor.get("version", 0),
        )

    @classmethod
    def from_json(cls, text: str) -> "DesignerSnapshot":
        payload = json.loads(str(text))
        if not isinstance(payload, Mapping):
            raise TypeError("designer snapshot JSON must contain an object")
        return cls.from_descriptor(payload)


def capture_component_tree(
    root: Component,
    *,
    catalog: DesignerCatalog | None = None,
    identities: DesignerIdentityMap | None = None,
) -> DesignerSnapshot:
    """Capture a backend-neutral component hierarchy into a JSON-safe snapshot."""

    if not isinstance(root, Component):
        raise TypeError("designer snapshot root must be a Component")
    catalog = catalog or FRAMEWORK_DESIGNER_CATALOG
    identities = identities or DesignerIdentityMap()
    visited: set[int] = set()
    used_type_keys: set[str] = set()

    def capture(component: Component) -> DesignerNode:
        marker = id(component)
        if marker in visited:
            raise ValueError("designer component trees cannot contain cycles or reused components")
        visited.add(marker)
        spec = catalog.resolve(component)
        used_type_keys.add(spec.key)
        children = []
        for source in spec.children_of(component):
            children.append(
                DesignerChild(
                    source.slot,
                    capture(source.component),
                    source.metadata,
                )
            )
        return DesignerNode(
            identities.identify(component),
            spec.key,
            spec.capture_properties(component),
            children,
        )

    root_node = capture(root)
    return DesignerSnapshot(
        root_node,
        catalog.metadata_descriptor(keys=used_type_keys),
    )


def _read_attribute(component: Component, path: str) -> object:
    value: object = component
    for part in str(path).split("."):
        if value is None:
            return None
        value = getattr(value, part)
    return value


def _json_safe(value: object) -> object:
    if value is UNSET:
        return UNSET
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            result[str(key)] = _json_safe(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value):
        return _json_safe(asdict(value))
    raise TypeError(f"value is not JSON-safe designer metadata: {type(value).__name__}")


def _linear_children(component: Component) -> Iterable[DesignerChildSource]:
    for child in getattr(component, "children", ()):
        yield DesignerChildSource(child)


def _grid_children(component: Component) -> Iterable[DesignerChildSource]:
    for row_index, row in enumerate(component.rows):
        for column_index, child in enumerate(row):
            yield DesignerChildSource(
                child,
                slot="cell",
                metadata={"row": row_index, "column": column_index},
            )


def _placed_child(component: Component) -> Iterable[DesignerChildSource]:
    yield DesignerChildSource(
        component.child,
        slot="child",
        metadata={"placement": component.placement.to_descriptor()},
    )


def _positioned_children(component: Component) -> Iterable[DesignerChildSource]:
    for entry in component.children:
        if not isinstance(entry, (PositionedChild, AnchoredChild)):
            raise TypeError("positioned panel designer child has unsupported placement")
        yield DesignerChildSource(
            entry.component,
            metadata={"placement": entry.placement.to_descriptor()},
        )


def _tab_pages(component: Component) -> Iterable[DesignerChildSource]:
    for page in component.pages:
        yield DesignerChildSource(page, slot="page", metadata={"key": page.key})


def _split_children(component: Component) -> Iterable[DesignerChildSource]:
    for pane in component.panes:
        if pane.child is None:
            continue
        yield DesignerChildSource(
            pane.child,
            slot="pane",
            metadata={
                "key": pane.key,
                "weight": pane.weight,
                "minimum": pane.minimum,
                "maximum": pane.maximum,
                "border": pane.border,
            },
        )


def _labeled_children(component: Component) -> Iterable[DesignerChildSource]:
    yield DesignerChildSource(component.label, slot="label")
    yield DesignerChildSource(component.control, slot="control")
    for accessory in component.accessories:
        yield DesignerChildSource(accessory, slot="accessory")


def _duration_children(component: Component) -> Iterable[DesignerChildSource]:
    # Capture the semantic editable units rather than the internal helper grid.
    yield DesignerChildSource(component.heading, slot="heading")
    yield DesignerChildSource(component.days, slot="days")
    yield DesignerChildSource(component.hours, slot="hours")
    yield DesignerChildSource(component.minutes, slot="minutes")


_CHILDREN_SLOT = DesignerChildSlotSpec("children", "Children")
_GRID_CELL_SLOT = DesignerChildSlotSpec(
    "cell",
    "Grid cell",
    required_metadata=("row", "column"),
    unique_by=("row", "column"),
)
_PLACED_CHILD_SLOT = DesignerChildSlotSpec(
    "child",
    "Placed child",
    multiple=False,
    required_metadata=("placement",),
)
_POSITIONED_CHILD_SLOT = DesignerChildSlotSpec(
    "children",
    "Positioned children",
    required_metadata=("placement",),
)
_TAB_PAGE_SLOT = DesignerChildSlotSpec(
    "page",
    "Tab page",
    required_metadata=("key",),
    unique_by=("key",),
)
_SPLIT_PANE_SLOT = DesignerChildSlotSpec(
    "pane",
    "Split pane",
    allowed_metadata=("key", "weight", "minimum", "maximum", "border"),
    required_metadata=("key",),
    unique_by=("key",),
)
_LABELED_SLOTS = (
    DesignerChildSlotSpec("label", "Label", multiple=False),
    DesignerChildSlotSpec("control", "Control", multiple=False),
    DesignerChildSlotSpec("accessory", "Accessory"),
)
_DURATION_SLOTS = tuple(
    DesignerChildSlotSpec(key, key.title(), multiple=False)
    for key in ("heading", "days", "hours", "minutes")
)


_COMMON_LAYOUT_PROPERTIES = (
    DesignerPropertySpec(
        "profile_key",
        "Layout profile",
        DesignerValueKind.TEXT,
        editable=False,
    ),
    DesignerPropertySpec(
        "layout.width",
        "Width",
        DesignerValueKind.DIMENSION,
        unsettable=True,
    ),
    DesignerPropertySpec(
        "layout.height",
        "Height",
        DesignerValueKind.DIMENSION,
        unsettable=True,
    ),
    DesignerPropertySpec(
        "layout.spacing",
        "Spacing",
        DesignerValueKind.INTEGER,
        minimum=0,
        nullable=True,
        unsettable=True,
    ),
)


def _spec(
    key: str,
    label: str,
    component_type: type[Component],
    *,
    category: str,
    properties: Iterable[DesignerPropertySpec] = (),
    child_reader: ChildReader | None = None,
    child_slots: Iterable[DesignerChildSlotSpec] = (),
) -> DesignerComponentSpec:
    return DesignerComponentSpec(
        key,
        label,
        component_type,
        category=category,
        properties=(*_COMMON_LAYOUT_PROPERTIES, *tuple(properties)),
        child_reader=child_reader,
        child_slots=child_slots,
    )


def _framework_catalog() -> DesignerCatalog:
    specs = (
        _spec(
            "control.label",
            "Label",
            Label,
            category="control",
            properties=(
                DesignerPropertySpec("text", "Text", DesignerValueKind.TEXT),
                DesignerPropertySpec(
                    "wrap",
                    "Wrap",
                    DesignerValueKind.INTEGER,
                    minimum=1,
                    nullable=True,
                ),
                DesignerPropertySpec("bullet", "Bullet", DesignerValueKind.BOOLEAN),
            ),
        ),
        _spec(
            "control.button",
            "Button",
            Button,
            category="control",
            properties=(
                DesignerPropertySpec("label", "Label", DesignerValueKind.TEXT),
                DesignerPropertySpec("enabled", "Enabled", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("show", "Visible", DesignerValueKind.BOOLEAN),
            ),
        ),
        _spec(
            "control.combo_box",
            "Combo box",
            ComboBox,
            category="control",
            properties=(
                DesignerPropertySpec("items", "Items", DesignerValueKind.STRING_LIST),
                DesignerPropertySpec(
                    "default_value",
                    "Default value",
                    DesignerValueKind.TEXT,
                    nullable=True,
                ),
                DesignerPropertySpec("enabled", "Enabled", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("show", "Visible", DesignerValueKind.BOOLEAN),
            ),
        ),
        _spec(
            "control.text_input",
            "Text input",
            TextInput,
            category="control",
            properties=(
                DesignerPropertySpec(
                    "label",
                    "Label",
                    DesignerValueKind.TEXT,
                    nullable=True,
                ),
                DesignerPropertySpec("default_value", "Default value", DesignerValueKind.TEXT),
                DesignerPropertySpec(
                    "hint",
                    "Hint",
                    DesignerValueKind.TEXT,
                    nullable=True,
                ),
                DesignerPropertySpec("multiline", "Multiline", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("readonly", "Read only", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("enabled", "Enabled", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("show", "Visible", DesignerValueKind.BOOLEAN),
            ),
        ),
        _spec(
            "control.numeric_stepper",
            "Numeric stepper",
            NumericStepper,
            category="control",
            properties=(
                DesignerPropertySpec(
                    "kind",
                    "Numeric kind",
                    DesignerValueKind.CHOICE,
                    choices=("integer", "float"),
                ),
                DesignerPropertySpec("default_value", "Default value", DesignerValueKind.NUMBER),
                DesignerPropertySpec(
                    "min_value",
                    "Minimum value",
                    DesignerValueKind.NUMBER,
                    nullable=True,
                ),
                DesignerPropertySpec(
                    "max_value",
                    "Maximum value",
                    DesignerValueKind.NUMBER,
                    nullable=True,
                ),
                DesignerPropertySpec("min_clamped", "Clamp minimum", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("max_clamped", "Clamp maximum", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec(
                    "format",
                    "Format",
                    DesignerValueKind.TEXT,
                    nullable=True,
                ),
                DesignerPropertySpec("enabled", "Enabled", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("show", "Visible", DesignerValueKind.BOOLEAN),
            ),
        ),
        _spec(
            "control.progress_bar",
            "Progress bar",
            ProgressBar,
            category="control",
            properties=(
                DesignerPropertySpec("default_value", "Default value", DesignerValueKind.NUMBER),
                DesignerPropertySpec(
                    "overlay",
                    "Overlay",
                    DesignerValueKind.TEXT,
                    nullable=True,
                ),
                DesignerPropertySpec("show", "Visible", DesignerValueKind.BOOLEAN),
            ),
        ),
        _spec(
            "control.checkbox",
            "Check box",
            CheckBox,
            category="control",
            properties=(
                DesignerPropertySpec("label", "Label", DesignerValueKind.TEXT),
                DesignerPropertySpec("default_value", "Default value", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("enabled", "Enabled", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("show", "Visible", DesignerValueKind.BOOLEAN),
            ),
        ),
        _spec("control.separator", "Separator", Separator, category="control"),
        _spec("control.spacer", "Spacer", Spacer, category="control"),
        _spec(
            "container.row",
            "Row",
            ControlRow,
            category="container",
            properties=(
                DesignerPropertySpec(
                    "cross_axis",
                    "Cross-axis sizing",
                    DesignerValueKind.CHOICE,
                    choices=("natural", "stretch"),
                ),
            ),
            child_reader=_linear_children,
            child_slots=(_CHILDREN_SLOT,),
        ),
        _spec(
            "container.column",
            "Column",
            ControlColumn,
            category="container",
            properties=(
                DesignerPropertySpec(
                    "cross_axis",
                    "Cross-axis sizing",
                    DesignerValueKind.CHOICE,
                    choices=("natural", "stretch"),
                ),
            ),
            child_reader=_linear_children,
            child_slots=(_CHILDREN_SLOT,),
        ),
        _spec(
            "container.grid",
            "Grid",
            ControlGrid,
            category="container",
            properties=(
                DesignerPropertySpec(
                    "column_widths",
                    "Column widths",
                    DesignerValueKind.NUMBER_LIST,
                    editable=False,
                ),
            ),
            child_reader=_grid_children,
            child_slots=(_GRID_CELL_SLOT,),
        ),
        _spec(
            "container.section",
            "Section panel",
            SectionPanel,
            category="container",
            properties=(
                DesignerPropertySpec(
                    "heading",
                    "Heading",
                    DesignerValueKind.TEXT,
                    attribute="heading.text",
                ),
                DesignerPropertySpec("border", "Border", DesignerValueKind.BOOLEAN),
            ),
            child_reader=_linear_children,
            child_slots=(_CHILDREN_SLOT,),
        ),
        _spec(
            "container.dialog",
            "Dialog",
            Dialog,
            category="container",
            properties=(
                DesignerPropertySpec("label", "Title", DesignerValueKind.TEXT),
                DesignerPropertySpec("modal", "Modal", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("show", "Visible", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("no_resize", "Disable resize", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("no_move", "Disable move", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("no_collapse", "Disable collapse", DesignerValueKind.BOOLEAN),
            ),
            child_reader=_linear_children,
            child_slots=(_CHILDREN_SLOT,),
        ),
        _spec(
            "container.placed",
            "Placed component",
            PlacedComponent,
            category="layout",
            child_reader=_placed_child,
            child_slots=(_PLACED_CHILD_SLOT,),
        ),
        _spec(
            "container.positioned",
            "Positioned panel",
            PositionedPanel,
            category="layout",
            properties=(
                DesignerPropertySpec("padding", "Padding", DesignerValueKind.INSETS),
                DesignerPropertySpec("border", "Border", DesignerValueKind.BOOLEAN),
                DesignerPropertySpec("fit_content", "Fit content", DesignerValueKind.BOOLEAN),
            ),
            child_reader=_positioned_children,
            child_slots=(_POSITIONED_CHILD_SLOT,),
        ),
        _spec(
            "structure.tab_page",
            "Tab page",
            TabPage,
            category="structure",
            properties=(
                DesignerPropertySpec("key", "Page key", DesignerValueKind.TEXT, editable=False),
                DesignerPropertySpec("label", "Label", DesignerValueKind.TEXT),
            ),
            child_reader=_linear_children,
            child_slots=(_CHILDREN_SLOT,),
        ),
        _spec(
            "structure.tabs",
            "Tabs",
            TabContainer,
            category="structure",
            child_reader=_tab_pages,
            child_slots=(_TAB_PAGE_SLOT,),
        ),
        _spec(
            "structure.split",
            "Split panel",
            SplitPanel,
            category="structure",
            properties=(
                DesignerPropertySpec(
                    "orientation",
                    "Orientation",
                    DesignerValueKind.CHOICE,
                    choices=("horizontal", "vertical"),
                ),
                DesignerPropertySpec("gap", "Gap", DesignerValueKind.INTEGER, minimum=0),
            ),
            child_reader=_split_children,
            child_slots=(_SPLIT_PANE_SLOT,),
        ),
        _spec(
            "field.labeled",
            "Labeled field",
            LabeledField,
            category="field",
            child_reader=_labeled_children,
            child_slots=_LABELED_SLOTS,
        ),
        _spec(
            "field.labeled_combo",
            "Labeled combo field",
            LabeledComboField,
            category="field",
            child_reader=_labeled_children,
            child_slots=_LABELED_SLOTS,
        ),
        _spec(
            "field.labeled_numeric",
            "Labeled numeric field",
            LabeledNumericField,
            category="field",
            child_reader=_labeled_children,
            child_slots=_LABELED_SLOTS,
        ),
        _spec(
            "field.numeric_unit",
            "Numeric unit field",
            NumericUnitField,
            category="field",
            child_reader=_labeled_children,
            child_slots=_LABELED_SLOTS,
        ),
        _spec(
            "field.duration",
            "Duration editor",
            DurationEditor,
            category="field",
            child_reader=_duration_children,
            child_slots=_DURATION_SLOTS,
        ),
    )
    return DesignerCatalog(specs)


FRAMEWORK_DESIGNER_CATALOG = _framework_catalog()


__all__ = [
    "DESIGNER_SNAPSHOT_KIND",
    "DESIGNER_SNAPSHOT_VERSION",
    "DesignerCatalog",
    "DesignerChild",
    "DesignerChildSlotSpec",
    "DesignerChildSource",
    "DesignerComponentSpec",
    "DesignerIdentityMap",
    "DesignerNode",
    "DesignerPropertySpec",
    "DesignerSnapshot",
    "DesignerValueKind",
    "FRAMEWORK_DESIGNER_CATALOG",
    "capture_component_tree",
]
