"""Backend-neutral reconstruction of designer snapshots into preview components.

Tranches 9-11 established self-describing component snapshots plus property and
structural editing.  This module adds the first deliberately narrow bridge back
from document data to executable framework components.  It reconstructs a
preview component tree without importing a GUI toolkit, application view, or
product model.  The returned tree may then be rendered by any existing
component backend.

The bridge is intentionally not a final project loader.  Runtime callbacks,
application services, bindings, resources, persisted undo history and arbitrary
custom component factories remain outside this first preview pass.  Unsupported
component type keys are reported before any partial tree is built.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

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
from .components.fields import LabeledField
from .components.layout import ControlLayout, ControlLayoutDefaults
from .components.profile import ComponentLayoutProfile, FRAMEWORK_COMPONENT_PROFILE
from .components.placement import (
    AnchoredChild,
    AnchoredPlacement,
    Insets,
    Placement,
    PositionedChild,
    placement_from_descriptor,
)
from .components.regions import SplitPane, SplitPanel, TabContainer, TabPage
from .designer import (
    DesignerCatalog,
    DesignerChild,
    DesignerIdentityMap,
    DesignerNode,
    DesignerSnapshot,
    FRAMEWORK_DESIGNER_CATALOG,
    capture_component_tree,
)
from .property_cascade import UNSET
from .responsive import LayoutCoordinator


class DesignerPreviewError(ValueError):
    """Base error for preview reconstruction failures."""


class DesignerPreviewUnsupportedTypeError(DesignerPreviewError):
    """Raised when a snapshot uses types with no registered preview builder."""

    def __init__(self, type_keys: Iterable[object]):
        resolved = tuple(sorted({str(value).strip() for value in type_keys if str(value).strip()}))
        self.type_keys = resolved
        joined = ", ".join(resolved) if resolved else "<unknown>"
        super().__init__(f"designer preview does not support component type(s): {joined}")


# Designer previews need deterministic, human-scale control defaults.  Ordinary
# applications retain the framework/application renderer profile unchanged; this
# overlay is used only while a DesignerPreviewHost renders reconstructed nodes.
# Explicit document width/height properties still win through the normal
# profile -> theme -> instance layout cascade.
DESIGNER_PREVIEW_LAYOUT_DEFAULTS = {
    "button": ControlLayoutDefaults(width=120, height=28),
    "combo_box": ControlLayoutDefaults(width=180),
    "text_input": ControlLayoutDefaults(width=220),
    "numeric_stepper": ControlLayoutDefaults(width=160),
    "progress_bar": ControlLayoutDefaults(width=220, height=22),
    "spacer": ControlLayoutDefaults(width=8, height=8),
}


def designer_preview_component_profile(
    parent: ComponentLayoutProfile | None = None,
) -> ComponentLayoutProfile:
    """Return the renderer-neutral component profile used by visual previews.

    ``parent`` preserves an application's named profile slots while the generic
    control keys above receive predictable editor-preview defaults.  The helper
    returns a fresh immutable profile so a preview never mutates the renderer's
    installed profile.
    """

    if parent is not None and not isinstance(parent, ComponentLayoutProfile):
        raise TypeError("designer preview profile parent must be ComponentLayoutProfile or None")
    return ComponentLayoutProfile(
        name="designer-preview",
        parent=parent or FRAMEWORK_COMPONENT_PROFILE,
        layouts=DESIGNER_PREVIEW_LAYOUT_DEFAULTS,
    )


@dataclass(frozen=True)
class DesignerPreviewContext:
    """Runtime-neutral dependencies used while reconstructing a preview tree."""

    layout_coordinator: LayoutCoordinator | None = None
    use_preview_control_defaults: bool = True

    def __post_init__(self) -> None:
        if self.layout_coordinator is not None and not isinstance(
            self.layout_coordinator, LayoutCoordinator
        ):
            raise TypeError("designer preview layout_coordinator must be LayoutCoordinator or None")
        if not isinstance(self.use_preview_control_defaults, bool):
            raise TypeError("designer preview use_preview_control_defaults must be bool")


@dataclass(frozen=True)
class DesignerPreviewChild:
    """One already-reconstructed child plus its snapshot relationship metadata."""

    source: DesignerChild
    component: Component

    @property
    def slot(self) -> str:
        return self.source.slot

    @property
    def metadata(self) -> Mapping[str, object] | None:
        return self.source.metadata


PreviewBuilder = Callable[
    [DesignerNode, tuple[DesignerPreviewChild, ...], DesignerPreviewContext],
    Component,
]


@dataclass(frozen=True)
class DesignerPreviewSpec:
    """One provisional type-key to preview-builder registration."""

    type_key: str
    builder: PreviewBuilder

    def __init__(self, type_key: object, builder: PreviewBuilder):
        resolved = str(type_key or "").strip()
        if not resolved:
            raise ValueError("designer preview type key must be non-empty")
        if not callable(builder):
            raise TypeError("designer preview builder must be callable")
        object.__setattr__(self, "type_key", resolved)
        object.__setattr__(self, "builder", builder)


class DesignerPreviewCatalog:
    """Validated registry for document-to-component preview builders."""

    def __init__(self, specs: Iterable[DesignerPreviewSpec] = ()):
        self._by_key: dict[str, DesignerPreviewSpec] = {}
        for spec in specs:
            self.register(spec)

    @property
    def specs(self) -> tuple[DesignerPreviewSpec, ...]:
        return tuple(self._by_key.values())

    @property
    def type_keys(self) -> tuple[str, ...]:
        return tuple(self._by_key)

    def register(self, spec: DesignerPreviewSpec) -> DesignerPreviewSpec:
        if not isinstance(spec, DesignerPreviewSpec):
            raise TypeError("designer preview catalog entries must be DesignerPreviewSpec instances")
        if spec.type_key in self._by_key:
            raise ValueError(f"duplicate designer preview type key: {spec.type_key}")
        self._by_key[spec.type_key] = spec
        return spec

    def supports(self, type_key: object) -> bool:
        return str(type_key or "").strip() in self._by_key

    def get(self, type_key: object) -> DesignerPreviewSpec:
        resolved = str(type_key or "").strip()
        if not resolved:
            raise ValueError("designer preview type key must be non-empty")
        try:
            return self._by_key[resolved]
        except KeyError as exc:
            raise DesignerPreviewUnsupportedTypeError((resolved,)) from exc


@dataclass(frozen=True)
class DesignerPreviewBuild:
    """Reconstructed preview root plus stable designer-id/component bindings."""

    source_snapshot: DesignerSnapshot
    root: Component
    components: Mapping[str, Component]

    def __init__(
        self,
        source_snapshot: DesignerSnapshot,
        root: Component,
        components: Mapping[str, Component],
    ):
        if not isinstance(source_snapshot, DesignerSnapshot):
            raise TypeError("designer preview build requires DesignerSnapshot")
        if not isinstance(root, Component):
            raise TypeError("designer preview root must be a Component")
        copied = dict(components)
        if source_snapshot.root.node_id not in copied:
            raise ValueError("designer preview component map is missing the root node id")
        if copied[source_snapshot.root.node_id] is not root:
            raise ValueError("designer preview root binding does not match the reconstructed root")
        if set(copied) != {node.node_id for node in source_snapshot.root.walk()}:
            raise ValueError("designer preview component map must cover every snapshot node exactly")
        if len({id(component) for component in copied.values()}) != len(copied):
            raise ValueError("designer preview component map cannot reuse component instances")
        object.__setattr__(self, "source_snapshot", source_snapshot)
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "components", MappingProxyType(copied))

    def component(self, node_id: object) -> Component:
        resolved = str(node_id or "").strip()
        if not resolved:
            raise ValueError("designer node id must be non-empty")
        try:
            return self.components[resolved]
        except KeyError as exc:
            raise KeyError(f"designer preview node not found: {resolved}") from exc

    def recapture(
        self,
        *,
        catalog: DesignerCatalog | None = None,
    ) -> DesignerSnapshot:
        """Capture the reconstructed tree while preserving source designer IDs.

        For snapshots originally captured from live framework components, the
        result should be descriptor-identical when every used type is supported.
        Sparse hand-authored/inserted nodes may materialize constructor defaults
        during this canonical recapture, which is intentional.
        """

        identities = DesignerIdentityMap(prefix="preview")
        for node_id, component in self.components.items():
            identities.bind(component, node_id)
        return capture_component_tree(
            self.root,
            catalog=catalog or FRAMEWORK_DESIGNER_CATALOG,
            identities=identities,
        )


def unsupported_preview_type_keys(
    snapshot: DesignerSnapshot,
    *,
    catalog: DesignerPreviewCatalog | None = None,
) -> tuple[str, ...]:
    """Return sorted snapshot type keys that cannot currently be reconstructed."""

    if not isinstance(snapshot, DesignerSnapshot):
        raise TypeError("designer preview support check requires DesignerSnapshot")
    active = catalog or FRAMEWORK_DESIGNER_PREVIEW_CATALOG
    return tuple(sorted({node.type_key for node in snapshot.root.walk() if not active.supports(node.type_key)}))


def reconstruct_designer_snapshot(
    snapshot: DesignerSnapshot,
    *,
    catalog: DesignerPreviewCatalog | None = None,
    context: DesignerPreviewContext | None = None,
) -> DesignerPreviewBuild:
    """Reconstruct a supported snapshot into backend-neutral framework components."""

    if not isinstance(snapshot, DesignerSnapshot):
        raise TypeError("designer preview reconstruction requires DesignerSnapshot")
    active_catalog = catalog or FRAMEWORK_DESIGNER_PREVIEW_CATALOG
    active_context = context or DesignerPreviewContext()
    unsupported = unsupported_preview_type_keys(snapshot, catalog=active_catalog)
    if unsupported:
        raise DesignerPreviewUnsupportedTypeError(unsupported)

    components: dict[str, Component] = {}
    component_markers: set[int] = set()

    def build_node(node: DesignerNode) -> Component:
        children = tuple(
            DesignerPreviewChild(child, build_node(child.node))
            for child in node.children
        )
        component = active_catalog.get(node.type_key).builder(node, children, active_context)
        if not isinstance(component, Component):
            raise TypeError(
                f"designer preview builder for {node.type_key!r} must return Component"
            )
        marker = id(component)
        if marker in component_markers:
            raise DesignerPreviewError(
                f"designer preview builder reused a Component instance for node {node.node_id!r}"
            )
        component_markers.add(marker)
        _apply_common_properties(component, node)
        components[node.node_id] = component
        return component

    root = build_node(snapshot.root)
    return DesignerPreviewBuild(snapshot, root, components)


def _properties(node: DesignerNode) -> Mapping[str, object]:
    return node.properties


def _value(node: DesignerNode, key: str, default: object = None) -> object:
    return _properties(node).get(key, default)


def _bool(node: DesignerNode, key: str, default: bool) -> bool:
    return bool(_value(node, key, default))


def _apply_common_properties(component: Component, node: DesignerNode) -> None:
    props = _properties(node)
    layout = ControlLayout(
        width=props.get("layout.width", UNSET),
        height=props.get("layout.height", UNSET),
        spacing=props.get("layout.spacing", UNSET),
    )
    component.layout = layout
    profile_key = props.get("profile_key")
    if profile_key is not None:
        resolved = str(profile_key).strip()
        if resolved:
            component.profile_key = resolved


def _slot_children(
    children: tuple[DesignerPreviewChild, ...],
    slot: str,
    *,
    exact: bool = False,
) -> tuple[DesignerPreviewChild, ...]:
    selected = tuple(child for child in children if child.slot == slot)
    if exact and len(selected) != len(children):
        unexpected = sorted({child.slot for child in children if child.slot != slot})
        raise DesignerPreviewError(
            f"designer preview expected only {slot!r} children; found: {', '.join(unexpected)}"
        )
    return selected


def _metadata(child: DesignerPreviewChild) -> Mapping[str, object]:
    if not isinstance(child.metadata, Mapping):
        raise DesignerPreviewError(
            f"designer preview relationship {child.slot!r} requires metadata"
        )
    return child.metadata


def _insets(value: object) -> Insets:
    if isinstance(value, Insets):
        return value
    if value is None:
        return Insets()
    if isinstance(value, Mapping):
        return Insets(
            value.get("left", 0),
            value.get("top", 0),
            value.get("right", 0),
            value.get("bottom", 0),
        )
    if isinstance(value, list):
        value = tuple(value)
    from .components.placement import insets

    return insets(value)  # type: ignore[arg-type]


def _label(node: DesignerNode, children, context) -> Component:
    return Label(
        str(_value(node, "text", "")),
        wrap=_value(node, "wrap"),
        bullet=_bool(node, "bullet", False),
    )


def _button(node: DesignerNode, children, context) -> Component:
    return Button(
        str(_value(node, "label", "")),
        callback=None,
        enabled=_bool(node, "enabled", True),
        show=_bool(node, "show", True),
    )


def _combo_box(node: DesignerNode, children, context) -> Component:
    items = _value(node, "items", ())
    if isinstance(items, (str, bytes)) or not isinstance(items, Iterable):
        raise DesignerPreviewError("combo-box preview items must be iterable")
    return ComboBox(
        tuple(str(item) for item in items),
        default_value=_value(node, "default_value"),
        callback=None,
        enabled=_bool(node, "enabled", True),
        show=_bool(node, "show", True),
    )


def _text_input(node: DesignerNode, children, context) -> Component:
    return TextInput(
        label=_value(node, "label"),
        default_value=str(_value(node, "default_value", "")),
        hint=_value(node, "hint"),
        multiline=_bool(node, "multiline", False),
        readonly=_bool(node, "readonly", False),
        callback=None,
        enabled=_bool(node, "enabled", True),
        show=_bool(node, "show", True),
    )


def _numeric_stepper(node: DesignerNode, children, context) -> Component:
    return NumericStepper(
        kind=_value(node, "kind", "integer"),
        default_value=_value(node, "default_value", 0),
        min_value=_value(node, "min_value"),
        max_value=_value(node, "max_value"),
        min_clamped=_bool(node, "min_clamped", False),
        max_clamped=_bool(node, "max_clamped", False),
        format=_value(node, "format"),
        callback=None,
        enabled=_bool(node, "enabled", True),
        show=_bool(node, "show", True),
    )


def _progress_bar(node: DesignerNode, children, context) -> Component:
    return ProgressBar(
        default_value=float(_value(node, "default_value", 0.0)),
        overlay=_value(node, "overlay"),
        show=_bool(node, "show", True),
    )


def _checkbox(node: DesignerNode, children, context) -> Component:
    return CheckBox(
        str(_value(node, "label", "")),
        default_value=_bool(node, "default_value", False),
        callback=None,
        enabled=_bool(node, "enabled", True),
        show=_bool(node, "show", True),
    )


def _separator(node: DesignerNode, children, context) -> Component:
    return Separator()


def _spacer(node: DesignerNode, children, context) -> Component:
    return Spacer()


def _linear(node: DesignerNode, children, context, component_type: type[Component]) -> Component:
    values = tuple(child.component for child in _slot_children(children, "children", exact=True))
    return component_type(values)  # type: ignore[call-arg]


def _row(node: DesignerNode, children, context) -> Component:
    values = tuple(child.component for child in _slot_children(children, "children", exact=True))
    return ControlRow(values, cross_axis=_value(node, "cross_axis", "natural"))


def _column(node: DesignerNode, children, context) -> Component:
    values = tuple(child.component for child in _slot_children(children, "children", exact=True))
    return ControlColumn(values, cross_axis=_value(node, "cross_axis", "natural"))


def _grid(node: DesignerNode, children, context) -> Component:
    cells = _slot_children(children, "cell", exact=True)
    if not cells:
        rows: tuple[tuple[Component, ...], ...] = ()
        column_count = 0
    else:
        positions: dict[tuple[int, int], Component] = {}
        maximum_row = -1
        maximum_column = -1
        for child in cells:
            metadata = _metadata(child)
            row = metadata.get("row")
            column = metadata.get("column")
            if isinstance(row, bool) or not isinstance(row, int) or row < 0:
                raise DesignerPreviewError("grid preview row metadata must be a non-negative integer")
            if isinstance(column, bool) or not isinstance(column, int) or column < 0:
                raise DesignerPreviewError("grid preview column metadata must be a non-negative integer")
            key = (row, column)
            if key in positions:
                raise DesignerPreviewError("grid preview cell coordinates must be unique")
            positions[key] = child.component
            maximum_row = max(maximum_row, row)
            maximum_column = max(maximum_column, column)
        column_count = maximum_column + 1
        expected = {(row, column) for row in range(maximum_row + 1) for column in range(column_count)}
        missing = expected.difference(positions)
        if missing:
            preview = ", ".join(f"({row},{column})" for row, column in sorted(missing)[:5])
            raise DesignerPreviewError(
                "grid preview requires dense rectangular cell coordinates; missing " + preview
            )
        rows = tuple(
            tuple(positions[(row, column)] for column in range(column_count))
            for row in range(maximum_row + 1)
        )
    column_widths = _value(node, "column_widths", ())
    if column_widths is None:
        column_widths = ()
    if isinstance(column_widths, (str, bytes)) or not isinstance(column_widths, Iterable):
        raise DesignerPreviewError("grid preview column_widths must be iterable")
    resolved_widths = tuple(int(value) for value in column_widths)
    if resolved_widths and column_count and len(resolved_widths) != column_count:
        raise DesignerPreviewError("grid preview column_widths must match reconstructed columns")
    return ControlGrid(rows, column_widths=resolved_widths or None)


def _section(node: DesignerNode, children, context) -> Component:
    values = tuple(child.component for child in _slot_children(children, "children", exact=True))
    heading = _value(node, "heading")
    if heading is not None:
        heading = str(heading)
    return SectionPanel(
        heading,
        values,
        border=_bool(node, "border", True),
    )


def _dialog(node: DesignerNode, children, context) -> Component:
    values = tuple(child.component for child in _slot_children(children, "children", exact=True))
    return Dialog(
        str(_value(node, "label", "")),
        values,
        modal=_bool(node, "modal", False),
        show=_bool(node, "show", False),
        no_resize=_bool(node, "no_resize", False),
        no_move=_bool(node, "no_move", False),
        no_collapse=_bool(node, "no_collapse", False),
    )


def _placed(node: DesignerNode, children, context) -> Component:
    values = _slot_children(children, "child", exact=True)
    if len(values) != 1:
        raise DesignerPreviewError("placed-component preview requires exactly one child")
    metadata = _metadata(values[0])
    descriptor = metadata.get("placement")
    if not isinstance(descriptor, Mapping):
        raise DesignerPreviewError("placed-component preview requires placement metadata")
    placement = placement_from_descriptor(descriptor)
    if not isinstance(placement, Placement):
        raise DesignerPreviewError("PlacedComponent only supports fixed placement metadata")
    return PlacedComponent(values[0].component, placement=placement)


def _positioned_panel(node: DesignerNode, children, context) -> Component:
    positioned_children: list[PositionedChild | AnchoredChild] = []
    for child in _slot_children(children, "children", exact=True):
        descriptor = _metadata(child).get("placement")
        if not isinstance(descriptor, Mapping):
            raise DesignerPreviewError("positioned-panel preview requires placement metadata")
        placement = placement_from_descriptor(descriptor)
        if isinstance(placement, AnchoredPlacement):
            positioned_children.append(AnchoredChild(child.component, placement=placement))
        elif isinstance(placement, Placement):
            positioned_children.append(PositionedChild(child.component, placement=placement))
        else:  # pragma: no cover - placement parser owns the concrete variants
            raise DesignerPreviewError("unsupported preview placement variant")
    return PositionedPanel(
        positioned_children,
        padding=_insets(_value(node, "padding", 0)),
        border=_bool(node, "border", False),
        fit_content=_bool(node, "fit_content", True),
        coordinator=context.layout_coordinator,
    )


def _tab_page(node: DesignerNode, children, context) -> Component:
    values = tuple(child.component for child in _slot_children(children, "children", exact=True))
    return TabPage(
        _value(node, "key", node.node_id),
        _value(node, "label", ""),
        values,
    )


def _tabs(node: DesignerNode, children, context) -> Component:
    pages = _slot_children(children, "page", exact=True)
    values: list[TabPage] = []
    for child in pages:
        if not isinstance(child.component, TabPage):
            raise DesignerPreviewError("tabs preview may only contain reconstructed TabPage components")
        metadata = _metadata(child)
        relationship_key = str(metadata.get("key", "")).strip()
        if relationship_key and relationship_key != child.component.key:
            raise DesignerPreviewError("tab preview relationship key must match the TabPage key")
        values.append(child.component)
    return TabContainer(values, callback=None)


def _split(node: DesignerNode, children, context) -> Component:
    panes: list[SplitPane] = []
    for child in _slot_children(children, "pane", exact=True):
        metadata = _metadata(child)
        key = str(metadata.get("key", "")).strip()
        if not key:
            raise DesignerPreviewError("split preview pane key must be non-empty")
        panes.append(
            SplitPane(
                key,
                child.component,
                weight=metadata.get("weight", 1.0),
                minimum=metadata.get("minimum", 1),
                maximum=metadata.get("maximum"),
                border=bool(metadata.get("border", False)),
            )
        )
    if not panes:
        raise DesignerPreviewError("split preview requires at least one pane")
    return SplitPanel(
        panes,
        orientation=_value(node, "orientation", "horizontal"),
        gap=int(_value(node, "gap", 8)),
        coordinator=context.layout_coordinator,
    )


def _labeled_field(node: DesignerNode, children, context) -> Component:
    labels = _slot_children(children, "label")
    controls = _slot_children(children, "control")
    accessories = _slot_children(children, "accessory")
    if len(labels) != 1 or not isinstance(labels[0].component, Label):
        raise DesignerPreviewError("labeled-field preview requires one Label child")
    if len(controls) != 1:
        raise DesignerPreviewError("labeled-field preview requires one control child")
    if len(labels) + len(controls) + len(accessories) != len(children):
        raise DesignerPreviewError("labeled-field preview contains an unsupported child slot")
    return LabeledField(
        labels[0].component,
        controls[0].component,
        accessories=tuple(child.component for child in accessories),
    )


def _preview_catalog() -> DesignerPreviewCatalog:
    # The first preview bridge intentionally supports the primitive/layout types
    # used by the product-neutral blank application plus the generic LabeledField.
    # Specialized semantic field composites remain explicit unsupported types
    # until their constructor-specific document contracts are proven.
    builders: tuple[tuple[str, PreviewBuilder], ...] = (
        ("control.label", _label),
        ("control.button", _button),
        ("control.combo_box", _combo_box),
        ("control.text_input", _text_input),
        ("control.numeric_stepper", _numeric_stepper),
        ("control.progress_bar", _progress_bar),
        ("control.checkbox", _checkbox),
        ("control.separator", _separator),
        ("control.spacer", _spacer),
        ("container.row", _row),
        ("container.column", _column),
        ("container.grid", _grid),
        ("container.section", _section),
        ("container.dialog", _dialog),
        ("container.placed", _placed),
        ("container.positioned", _positioned_panel),
        ("structure.tab_page", _tab_page),
        ("structure.tabs", _tabs),
        ("structure.split", _split),
        ("field.labeled", _labeled_field),
    )
    return DesignerPreviewCatalog(DesignerPreviewSpec(key, builder) for key, builder in builders)


FRAMEWORK_DESIGNER_PREVIEW_CATALOG = _preview_catalog()


__all__ = [
    "DESIGNER_PREVIEW_LAYOUT_DEFAULTS",
    "DesignerPreviewBuild",
    "DesignerPreviewCatalog",
    "DesignerPreviewChild",
    "DesignerPreviewContext",
    "DesignerPreviewError",
    "DesignerPreviewSpec",
    "DesignerPreviewUnsupportedTypeError",
    "FRAMEWORK_DESIGNER_PREVIEW_CATALOG",
    "designer_preview_component_profile",
    "reconstruct_designer_snapshot",
    "unsupported_preview_type_keys",
]
