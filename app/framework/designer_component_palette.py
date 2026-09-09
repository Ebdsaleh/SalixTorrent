"""Backend-neutral component-palette request surface for optional designer tooling.

The designer catalog already describes the reusable semantic component types that
can appear in a designer document.  This module exposes those catalog entries as
an editor palette without inventing construction defaults or hierarchy placement
policy.

Activating a palette entry therefore produces an immutable
:class:`DesignerComponentInsertRequest`.  The request identifies the desired
component type and carries the current stable selection only as a *hint* for a
future placement UI.  It does not mutate the document, allocate a designer node,
choose a parent/slot, fabricate relationship metadata, dirty the project, add
history, or rebuild the preview.

Concrete Dear PyGui/Tkinter hosts remain disposable presentation adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Protocol, runtime_checkable

from .designer import DesignerCatalog, DesignerComponentSpec, FRAMEWORK_DESIGNER_CATALOG
from .designer_workspace import DesignerWorkspace


DesignerComponentPaletteRequestHandler = Callable[["DesignerComponentInsertRequest"], object]


def _key(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


@dataclass(frozen=True)
class DesignerComponentPaletteEntry:
    """One catalog-backed palette item; never a runtime component instance."""

    component_type_key: str
    label: str
    category: str
    accepts_children: bool

    @classmethod
    def from_spec(cls, spec: DesignerComponentSpec) -> "DesignerComponentPaletteEntry":
        if not isinstance(spec, DesignerComponentSpec):
            raise TypeError("designer component palette entry requires DesignerComponentSpec")
        return cls(
            component_type_key=spec.key,
            label=str(spec.label),
            category=spec.category,
            accepts_children=spec.accepts_children,
        )

    def to_descriptor(self) -> dict[str, object]:
        return {
            "component_type_key": self.component_type_key,
            "label": self.label,
            "category": self.category,
            "accepts_children": self.accepts_children,
        }


@dataclass(frozen=True)
class DesignerComponentInsertRequest:
    """Explicit shell follow-up required before a palette insertion can occur.

    ``target_hint`` is the stable node currently selected when the user activates
    the tool.  It is deliberately not called ``parent_id``: the selected item may
    be a leaf, may need sibling placement, or may require a structural slot with
    metadata.  A later placement surface must make that decision explicitly.
    """

    component_type_key: str
    label: str
    category: str
    target_hint: str = ""
    requires_placement: bool = True

    def to_descriptor(self) -> dict[str, object]:
        return {
            "component_type_key": self.component_type_key,
            "label": self.label,
            "category": self.category,
            "target_hint": self.target_hint,
            "requires_placement": self.requires_placement,
        }


@dataclass(frozen=True)
class DesignerComponentPaletteState:
    """Immutable presentation projection of one component palette."""

    closed: bool
    target_hint: str
    entries: tuple[DesignerComponentPaletteEntry, ...]

    @property
    def categories(self) -> tuple[str, ...]:
        seen: list[str] = []
        for entry in self.entries:
            if entry.category not in seen:
                seen.append(entry.category)
        return tuple(seen)

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    def entry(self, component_type_key: object) -> DesignerComponentPaletteEntry:
        resolved = _key(component_type_key, field="designer palette component type key")
        for entry in self.entries:
            if entry.component_type_key == resolved:
                return entry
        raise KeyError(f"designer palette component type is not exposed: {resolved}")

    def to_descriptor(self) -> dict[str, object]:
        return {
            "closed": self.closed,
            "target_hint": self.target_hint,
            "categories": list(self.categories),
            "entries": [entry.to_descriptor() for entry in self.entries],
        }


@dataclass
class DesignerComponentPaletteBinding:
    """Opaque host-owned panel plus stable component-type item bindings."""

    panel: object
    items: dict[str, object]
    title_item: object | None = None
    metadata: object | None = None


@runtime_checkable
class DesignerComponentPaletteHost(Protocol):
    """Concrete adapter contract consumed by :class:`DesignerComponentPalette`."""

    def build(
        self,
        state: DesignerComponentPaletteState,
        *,
        parent: object,
        title: str = "",
        on_activate: Callable[[str], object],
    ) -> DesignerComponentPaletteBinding:
        ...

    def update(
        self,
        binding: DesignerComponentPaletteBinding,
        state: DesignerComponentPaletteState,
    ) -> None:
        ...

    def exists(self, binding: DesignerComponentPaletteBinding) -> bool:
        ...

    def dispose(self, binding: DesignerComponentPaletteBinding) -> None:
        ...


def _host_errors(host: object) -> tuple[str, ...]:
    required = ("build", "update", "exists", "dispose")
    return tuple(name for name in required if not callable(getattr(host, name, None)))


class DesignerComponentPalette:
    """Present catalog component types without assuming insertion placement.

    The palette is intentionally request-only in this tranche.  It validates an
    activation against its currently exposed catalog projection, snapshots the
    current selection as a hint, and returns/forwards one immutable request.
    """

    def __init__(
        self,
        workspace: DesignerWorkspace,
        host: DesignerComponentPaletteHost,
        *,
        catalog: DesignerCatalog = FRAMEWORK_DESIGNER_CATALOG,
        component_keys: Iterable[object] | None = None,
        title: str = "Components",
        on_request: DesignerComponentPaletteRequestHandler | None = None,
    ):
        if not isinstance(workspace, DesignerWorkspace):
            raise TypeError("designer component palette requires DesignerWorkspace")
        if not isinstance(catalog, DesignerCatalog):
            raise TypeError("designer component palette catalog must be DesignerCatalog")
        missing = _host_errors(host)
        if missing:
            raise TypeError(
                "designer component palette host does not satisfy DesignerComponentPaletteHost; "
                "missing: " + ", ".join(missing)
            )
        if on_request is not None and not callable(on_request):
            raise TypeError("designer component palette request handler must be callable")

        if component_keys is None:
            keys = tuple(spec.key for spec in catalog.specs)
        else:
            keys = tuple(
                _key(value, field="designer palette component type key")
                for value in component_keys
            )
            if len(keys) != len(set(keys)):
                raise ValueError("designer component palette keys must be unique")
            for key in keys:
                catalog.get(key)

        self._workspace = workspace
        self._host = host
        self._catalog = catalog
        self._component_keys = keys
        self._title = str(title)
        self._on_request = on_request
        self._parent: object | None = None
        self._binding: DesignerComponentPaletteBinding | None = None

    @property
    def workspace(self) -> DesignerWorkspace:
        return self._workspace

    @property
    def catalog(self) -> DesignerCatalog:
        return self._catalog

    @property
    def binding(self) -> DesignerComponentPaletteBinding | None:
        return self._binding

    @property
    def state(self) -> DesignerComponentPaletteState:
        workspace_state = self._workspace.state
        entries = tuple(
            DesignerComponentPaletteEntry.from_spec(self._catalog.get(key))
            for key in self._component_keys
        )
        return DesignerComponentPaletteState(
            closed=workspace_state.closed,
            target_hint=workspace_state.selected_id,
            entries=entries,
        )

    def build(self, *, parent: object) -> DesignerComponentPaletteBinding:
        if self.exists():
            raise RuntimeError("designer component palette is already built")
        state = self.state
        binding = self._host.build(
            state,
            parent=parent,
            title=self._title,
            on_activate=self.activate,
        )
        if not isinstance(binding, DesignerComponentPaletteBinding):
            raise TypeError(
                "designer component palette host must return DesignerComponentPaletteBinding"
            )
        expected = tuple(entry.component_type_key for entry in state.entries)
        if tuple(binding.items) != expected:
            try:
                self._host.dispose(binding)
            finally:
                raise ValueError(
                    "designer component palette host returned item bindings in an unexpected shape"
                )
        self._parent = parent
        self._binding = binding
        return binding

    def exists(self) -> bool:
        return bool(self._binding is not None and self._host.exists(self._binding))

    def require_binding(self) -> DesignerComponentPaletteBinding:
        if not self.exists():
            raise RuntimeError(
                "designer component palette is not built or its backend binding is stale"
            )
        assert self._binding is not None
        return self._binding

    def refresh(self) -> DesignerComponentPaletteBinding:
        state = self.state
        if self._binding is None or not self._host.exists(self._binding):
            if self._parent is None:
                raise RuntimeError("designer component palette must be built before refresh")
            return self.build(parent=self._parent)
        self._host.update(self._binding, state)
        return self._binding

    def activate(self, component_type_key: object) -> DesignerComponentInsertRequest:
        """Return one explicit placement request without changing the document."""

        state = self.state
        if state.closed:
            raise RuntimeError("designer workspace is closed")
        entry = state.entry(component_type_key)
        request = DesignerComponentInsertRequest(
            component_type_key=entry.component_type_key,
            label=entry.label,
            category=entry.category,
            target_hint=state.target_hint,
        )
        if self._on_request is not None:
            self._on_request(request)
        return request

    def dispose(self) -> bool:
        binding = self._binding
        self._binding = None
        if binding is None:
            return False
        try:
            if self._host.exists(binding):
                self._host.dispose(binding)
        finally:
            binding.items.clear()
        return True


__all__ = [
    "DesignerComponentInsertRequest",
    "DesignerComponentPalette",
    "DesignerComponentPaletteBinding",
    "DesignerComponentPaletteEntry",
    "DesignerComponentPaletteHost",
    "DesignerComponentPaletteRequestHandler",
    "DesignerComponentPaletteState",
]
