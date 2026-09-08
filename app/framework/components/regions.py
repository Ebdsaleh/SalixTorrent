"""Backend-neutral structural region components.

These provisional components let applications compose larger surfaces without
making one layout strategy global. Tabs own page selection while split panels
own proportional parent-local pane sizing. Both remain renderer-neutral and can
contain any ordinary component, including positioned or automatic layouts.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

from ..geometry import split_sizes
from ..responsive import LayoutCoordinator
from .base import Component
from .events import ComponentEvent, ComponentEventType
from .layout import AUTO, FILL, ControlLayout, ControlLayoutTheme
from .renderer import ComponentRenderer, get_default_renderer


def _key(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


class SplitOrientation(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


@dataclass(frozen=True)
class SplitPane:
    """One named pane in a :class:`SplitPanel`."""

    key: str
    child: Component | None = None
    weight: float = 1.0
    minimum: int = 1
    border: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _key(self.key, field="split pane key"))
        if self.child is not None and not isinstance(self.child, Component):
            raise TypeError("split pane child must be a Component or None")
        if isinstance(self.weight, bool):
            raise TypeError("split pane weight must be numeric")
        try:
            weight = float(self.weight)
        except (TypeError, ValueError) as exc:
            raise TypeError("split pane weight must be numeric") from exc
        if weight < 0:
            raise ValueError("split pane weight must be non-negative")
        object.__setattr__(self, "weight", weight)
        if isinstance(self.minimum, bool):
            raise TypeError("split pane minimum must be an integer")
        minimum = int(self.minimum)
        if minimum < 1:
            raise ValueError("split pane minimum must be at least one")
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "border", bool(self.border))


class TabPage(Component):
    """One keyed page owned by a :class:`TabContainer`."""

    profile_key = "tab_page"

    def __init__(
        self,
        key: object,
        label: object,
        children: Iterable[Component] = (),
        *,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.key = _key(key, field="tab page key")
        self.label = str(label)
        self.children = list(children)
        if not all(isinstance(child, Component) for child in self.children):
            raise TypeError("tab page children must be Components")

    def add(self, component: Component) -> Component:
        if not isinstance(component, Component):
            raise TypeError("tab page child must be a Component")
        self.children.append(component)
        return component

    @contextmanager
    def context(self, *, renderer=None, parent=None):
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs["label"] = self.label
        self._with_parent(kwargs, parent)
        with renderer.container("tab_page", **kwargs) as item:
            self._bind(renderer, item)
            yield item

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        with self.context(renderer=renderer, parent=parent):
            for child in self.children:
                child.build(renderer=renderer)
        return self.require_item()


class TabContainer(Component):
    """Keyed tab/page structural container with semantic selection events."""

    profile_key = "tab_container"

    def __init__(
        self,
        pages: Iterable[TabPage] = (),
        *,
        callback: Callable[[ComponentEvent], object] | None = None,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.pages: list[TabPage] = []
        self.callback = callback
        for page in pages:
            self.add_page(page)

    def _validate_unique(self, key: str) -> None:
        if any(page.key == key for page in self.pages):
            raise ValueError(f"duplicate tab page key: {key!r}")

    def add_page(self, page: TabPage) -> TabPage:
        if not isinstance(page, TabPage):
            raise TypeError("tab container pages must be TabPage instances")
        self._validate_unique(page.key)
        self.pages.append(page)
        return page

    def page(self, key: object) -> TabPage:
        resolved = _key(key, field="tab page key")
        for page in self.pages:
            if page.key == resolved:
                return page
        raise KeyError(resolved)

    def page_item(self, key: object) -> object:
        return self.page(key).require_item()

    def _key_for_item(self, item: object) -> str | None:
        for page in self.pages:
            if page.item == item:
                return page.key
        # Some backends can return an equivalent primitive handle rather than
        # the exact wrapper object. Equality is a safe fallback for those.
        for page in self.pages:
            try:
                if page.item is not None and page.item == item:
                    return page.key
            except Exception:
                continue
        return None

    def _emit_key(self, key: str) -> None:
        if self.callback is None:
            return
        self.callback(
            ComponentEvent(
                source=self,
                event_type=ComponentEventType.CHANGE,
                value=key,
            )
        )

    def _on_backend_change(self, event: ComponentEvent) -> None:
        # Backends differ in what they place in tab-change callback data.
        # Tkinter supplies the semantic page wrapper directly, while Dear
        # PyGui may report the selected tab handle through the tab bar's
        # current value rather than callback app_data.  Prefer the event value
        # when it is useful, then fall back to the container's current value so
        # application code receives one stable semantic page key either way.
        key = self._key_for_item(event.value)
        if key is None:
            renderer = self._renderer or get_default_renderer()
            try:
                selected = renderer.get_value(self.require_item())
            except Exception:
                selected = None
            key = self._key_for_item(selected)
        if key is not None:
            self._emit_key(key)

    @contextmanager
    def context(self, *, renderer=None, parent=None):
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        if self.callback is not None:
            kwargs["callback"] = renderer.event_callback(
                self,
                ComponentEventType.CHANGE,
                self._on_backend_change,
            )
        self._with_parent(kwargs, parent)
        with renderer.container("tabs", **kwargs) as item:
            self._bind(renderer, item)
            yield item

    @contextmanager
    def page_context(
        self,
        key: object,
        label: object,
        *,
        renderer=None,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
    ):
        if self.item is None:
            raise RuntimeError("tab page contexts must be opened inside TabContainer.context()")
        renderer = renderer or self._renderer or get_default_renderer()
        page = TabPage(key, label, theme=theme, layout=layout)
        self.add_page(page)
        # Do not pass an explicit parent here. The active renderer container
        # stack owns the backend-specific tab relationship.
        with page.context(renderer=renderer) as item:
            yield item

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        with self.context(renderer=renderer, parent=parent):
            for page in self.pages:
                page.build(renderer=renderer)
        return self.require_item()

    def selected_key(self) -> str | None:
        renderer = self._renderer or get_default_renderer()
        selected = renderer.get_value(self.require_item())
        return self._key_for_item(selected)

    def select(self, key: object, *, notify: bool = False) -> bool:
        resolved = _key(key, field="tab page key")
        page = self.page(resolved)
        renderer = self._renderer or get_default_renderer()
        renderer.set_value(self.require_item(), page.require_item())
        if notify:
            self._emit_key(resolved)
        return True


class SplitPanel(Component):
    """Responsive row/column of named panes coordinated through LayoutHost.

    A split panel owns structural pane sizing, not the content inside each pane.
    Applications can build pane content declaratively through ``SplitPane.child``
    or incrementally with ``context()``/``pane_context()`` while migrating an
    existing view. The layout strategy remains local to this container.
    """

    profile_key = "split_panel"

    def __init__(
        self,
        panes: Iterable[SplitPane],
        *,
        orientation: SplitOrientation | str = SplitOrientation.HORIZONTAL,
        gap: int = 8,
        coordinator: LayoutCoordinator | None = None,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.panes = tuple(panes)
        if not self.panes:
            raise ValueError("split panel requires at least one pane")
        if not all(isinstance(pane, SplitPane) for pane in self.panes):
            raise TypeError("split panel panes must be SplitPane instances")
        keys = tuple(pane.key for pane in self.panes)
        if len(set(keys)) != len(keys):
            raise ValueError("split panel pane keys must be unique")
        self.orientation = SplitOrientation(str(getattr(orientation, "value", orientation)).lower())
        if isinstance(gap, bool):
            raise TypeError("split panel gap must be an integer")
        self.gap = max(0, int(gap))
        if coordinator is not None and not isinstance(coordinator, LayoutCoordinator):
            raise TypeError("split panel coordinator must be a LayoutCoordinator")
        self.coordinator = coordinator
        self._pane_items: dict[str, object] = {}
        self._watch_key = ("split_panel", id(self))
        self.current_sizes: tuple[int, ...] = tuple(pane.minimum for pane in self.panes)

    def pane(self, key: object) -> SplitPane:
        resolved = _key(key, field="split pane key")
        for pane in self.panes:
            if pane.key == resolved:
                return pane
        raise KeyError(resolved)

    def pane_item(self, key: object) -> object:
        resolved = _key(key, field="split pane key")
        item = self._pane_items.get(resolved)
        if item is None:
            raise RuntimeError(f"split pane {resolved!r} has not been built")
        return item

    @contextmanager
    def context(self, *, renderer=None, parent=None):
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        # Split geometry is framework-owned rather than delegated to a backend's
        # flow/group layout.  This is important for deterministic nesting: a
        # pane must keep its negotiated extent even when its descendants use
        # FILL sizing, tabs, plots or documentation surfaces.  The root is an
        # ordinary parent-local positioned container; reflow sizes and places
        # each pane explicitly through the renderer-neutral contracts.
        self._with_parent(kwargs, parent)
        with renderer.container("positioned_panel", **kwargs) as item:
            self._bind(renderer, item)
            self._pane_items.clear()
            try:
                yield item
            finally:
                if self.coordinator is not None:
                    # Give every pane a deterministic non-overlapping position
                    # even before the first backend resize event has produced a
                    # reliable rendered root size.  reflow() upgrades these
                    # minimum extents as soon as the real size is available.
                    self._apply_geometry(self.current_sizes, *self.coordinator.item_size(item))
                    self.coordinator.watch_item(item, self._watch_key, self.reflow)
                    self.reflow()

    @contextmanager
    def pane_context(self, key: object, *, renderer=None):
        if self.item is None:
            raise RuntimeError("split pane contexts must be opened inside SplitPanel.context()")
        renderer = renderer or self._renderer or get_default_renderer()
        pane = self.pane(key)
        if pane.key in self._pane_items:
            raise RuntimeError(f"split pane {pane.key!r} is already built")
        kwargs = {"border": pane.border}
        if self.orientation is SplitOrientation.HORIZONTAL:
            kwargs.update(width=max(1, pane.minimum), height=-1)
        else:
            kwargs.update(width=-1, height=max(1, pane.minimum))
        with renderer.container("split_pane", **kwargs) as item:
            self._pane_items[pane.key] = item
            yield item

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        with self.context(renderer=renderer, parent=parent):
            for pane in self.panes:
                with self.pane_context(pane.key, renderer=renderer):
                    if pane.child is not None:
                        pane.child.build(renderer=renderer)
        return self.require_item()

    def _apply_geometry(self, sizes: tuple[int, ...], width: int, height: int) -> None:
        if self.coordinator is None:
            return
        renderer = self._renderer or get_default_renderer()
        cursor = 0
        for pane, size in zip(self.panes, sizes):
            item = self._pane_items.get(pane.key)
            if item is None:
                continue
            if self.orientation is SplitOrientation.HORIZONTAL:
                self.coordinator.width(item, size)
                if height > 1:
                    self.coordinator.height(item, height)
                renderer.place(item, cursor, 0)
            else:
                self.coordinator.height(item, size)
                if width > 1:
                    self.coordinator.width(item, width)
                renderer.place(item, 0, cursor)
            cursor += size + self.gap

    def reflow(self) -> tuple[int, ...]:
        if self.coordinator is None or self.item is None:
            return self.current_sizes
        if len(self._pane_items) != len(self.panes):
            return self.current_sizes
        width, height = self.coordinator.item_size(self.item)
        total = width if self.orientation is SplitOrientation.HORIZONTAL else height
        if total <= 1:
            self._apply_geometry(self.current_sizes, width, height)
            return self.current_sizes
        sizes = split_sizes(
            total,
            tuple(pane.weight for pane in self.panes),
            minimums=tuple(pane.minimum for pane in self.panes),
            gap=self.gap,
        )
        self.current_sizes = sizes
        self._apply_geometry(sizes, width, height)
        return sizes

    def dispose(self) -> bool:
        if self.coordinator is not None:
            self.coordinator.unwatch_item(self._watch_key)
        self._pane_items.clear()
        return super().dispose()
