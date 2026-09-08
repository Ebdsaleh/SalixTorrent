"""Reusable component composition containers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager

from .base import Component
from .controls import Label, Separator
from .layout import AUTO, FILL, ControlLayout, ControlLayoutTheme
from .placement import Insets, Placement, PositionedChild, insets, positioned
from .renderer import ComponentRenderer, get_default_renderer




class PlacedComponent(Component):
    """Parent-local explicit placement wrapper for one ordinary component.

    The wrapper itself participates in its parent's normal layout.  Its child is
    then positioned inside the wrapper at ``Placement(x, y)``.  The wrapper is
    resized to the child's occupied bounds, so automatic rows/columns/grids can
    grow around an explicitly offset child instead of clipping or ignoring it.
    """

    profile_key = "placed_component"

    def __init__(
        self,
        child: Component,
        *,
        x: int = 0,
        y: int = 0,
        margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
        placement: Placement | None = None,
    ):
        if not isinstance(child, Component):
            raise TypeError("PlacedComponent child must be a Component")
        super().__init__()
        self.child = child
        if placement is None:
            self.placement = Placement(x, y, margin=margin)
        elif isinstance(placement, Placement):
            self.placement = placement
        else:
            raise TypeError("placement must be a Placement")
        self.occupied_size: tuple[int, int] = (0, 0)

    def _hint(self, renderer: ComponentRenderer | None) -> tuple[int, int]:
        width, height = self.child.layout_size_hint(renderer=renderer)
        return self.placement.occupied_size(width or 0, height or 0)

    def layout_size_hint(
        self,
        *,
        renderer: ComponentRenderer | None = None,
    ) -> tuple[int | None, int | None]:
        active = renderer or self._renderer
        width, height = self._hint(active)
        return (width or None, height or None)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        hinted_width, hinted_height = self._hint(renderer)
        kwargs = {
            "width": max(1, hinted_width),
            "height": max(1, hinted_height),
            "border": False,
        }
        self._with_parent(kwargs, parent)
        with renderer.container("positioned_slot", **kwargs) as item:
            self._bind(renderer, item)
            self.child.build(renderer=renderer, parent=item)
            child_item = self.child.require_item()
            measured_width, measured_height = renderer.measure(child_item)
            hint_width, hint_height = self.child.layout_size_hint(renderer=renderer)
            child_width = max(measured_width, int(hint_width or 0))
            child_height = max(measured_height, int(hint_height or 0))
            occupied_width, occupied_height = self.placement.occupied_size(
                child_width, child_height
            )
            self.occupied_size = (occupied_width, occupied_height)
            renderer.configure(
                item,
                width=max(1, occupied_width),
                height=max(1, occupied_height),
            )
            renderer.place(
                child_item,
                self.placement.local_x,
                self.placement.local_y,
            )
        return self.require_item()


class PositionedPanel(Component):
    """Container whose direct children use explicit local coordinates.

    The panel remains an ordinary component to its own parent.  This permits
    recursive mixed layouts: a grid can contain a positioned panel, and that
    panel can itself contain another automatic row/grid/column.
    """

    profile_key = "positioned_panel"

    def __init__(
        self,
        children: Iterable[PositionedChild | tuple[Component, int, int]] = (),
        *,
        padding: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
        border: bool = False,
        fit_content: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.padding = insets(padding)
        self.border = bool(border)
        self.fit_content = bool(fit_content)
        self.children: list[PositionedChild] = []
        self.occupied_size: tuple[int, int] = (self.padding.horizontal, self.padding.vertical)
        for child in children:
            if isinstance(child, PositionedChild):
                self.children.append(child)
                continue
            try:
                component, x, y = child
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    "PositionedPanel children must be PositionedChild or (Component, x, y)"
                ) from exc
            self.children.append(positioned(component, x=x, y=y))

    def add(
        self,
        component: Component,
        *,
        x: int = 0,
        y: int = 0,
        margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
        affects_layout: bool = True,
    ) -> Component:
        self.children.append(
            positioned(
                component,
                x=x,
                y=y,
                margin=margin,
                affects_layout=affects_layout,
            )
        )
        return component

    def add_overlay(
        self,
        component: Component,
        *,
        x: int = 0,
        y: int = 0,
        margin: Insets | int | tuple[int, int] | tuple[int, int, int, int] = 0,
    ) -> Component:
        """Add a local overlay that does not enlarge the panel's measured bounds."""

        return self.add(
            component,
            x=x,
            y=y,
            margin=margin,
            affects_layout=False,
        )

    def _content_hint(self, renderer: ComponentRenderer | None) -> tuple[int, int]:
        width = self.padding.horizontal
        height = self.padding.vertical
        for entry in self.children:
            if not entry.placement.affects_layout:
                continue
            child_width, child_height = entry.component.layout_size_hint(renderer=renderer)
            occupied_width, occupied_height = entry.placement.occupied_size(
                child_width or 0, child_height or 0
            )
            width = max(
                width,
                self.padding.left + occupied_width + self.padding.right,
            )
            height = max(
                height,
                self.padding.top + occupied_height + self.padding.bottom,
            )
        return width, height

    def layout_size_hint(
        self,
        *,
        renderer: ComponentRenderer | None = None,
    ) -> tuple[int | None, int | None]:
        active = renderer or self._renderer
        resolved = self._resolve_layout(renderer=active)
        content_width, content_height = self._content_hint(active)
        width = resolved.width if isinstance(resolved.width, int) else None
        height = resolved.height if isinstance(resolved.height, int) else None
        if self.fit_content:
            width = max(int(width or 0), content_width) or None
            height = max(int(height or 0), content_height) or None
        return width, height

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        hinted_width, hinted_height = self._content_hint(renderer)

        width = resolved.width
        height = resolved.height
        if self.fit_content:
            if width is AUTO:
                width = max(1, hinted_width)
            elif isinstance(width, int):
                width = max(width, hinted_width)
            if height is AUTO:
                height = max(1, hinted_height)
            elif isinstance(height, int):
                height = max(height, hinted_height)

        kwargs = {}
        if width is FILL:
            kwargs["width"] = -1
        elif width is not AUTO:
            kwargs["width"] = int(width)
        if height is FILL:
            kwargs["height"] = -1
        elif height is not AUTO:
            kwargs["height"] = int(height)
        kwargs["border"] = self.border
        self._with_parent(kwargs, parent)

        max_width = self.padding.horizontal
        max_height = self.padding.vertical
        with renderer.container("positioned_panel", **kwargs) as item:
            self._bind(renderer, item)
            for entry in self.children:
                entry.component.build(renderer=renderer, parent=item)
                child_item = entry.component.require_item()
                measured_width, measured_height = renderer.measure(child_item)
                hint_width, hint_height = entry.component.layout_size_hint(renderer=renderer)
                child_width = max(measured_width, int(hint_width or 0))
                child_height = max(measured_height, int(hint_height or 0))
                renderer.place(
                    child_item,
                    self.padding.left + entry.placement.local_x,
                    self.padding.top + entry.placement.local_y,
                )
                if entry.placement.affects_layout:
                    occupied_width, occupied_height = entry.placement.occupied_size(
                        child_width, child_height
                    )
                    max_width = max(
                        max_width,
                        self.padding.left + occupied_width + self.padding.right,
                    )
                    max_height = max(
                        max_height,
                        self.padding.top + occupied_height + self.padding.bottom,
                    )

            self.occupied_size = (max_width, max_height)
            resize = {}
            if self.fit_content and width is not FILL:
                resize["width"] = max(1, max_width, int(width) if isinstance(width, int) else 0)
            if self.fit_content and height is not FILL:
                resize["height"] = max(1, max_height, int(height) if isinstance(height, int) else 0)
            if resize:
                renderer.configure(item, **resize)
        return self.require_item()

class ControlRow(Component):
    """Arbitrary components constrained to one horizontal layout row."""

    profile_key = "control_row"

    def __init__(
        self,
        children: Iterable[Component] = (),
        *,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.children = list(children)

    def add(self, component: Component) -> Component:
        self.children.append(component)
        return component

    @contextmanager
    def context(self, *, renderer=None, parent=None):
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        if resolved.spacing is not None:
            kwargs["horizontal_spacing"] = resolved.spacing
        self._with_parent(kwargs, parent)

        with renderer.container("row", **kwargs) as item:
            self._bind(renderer, item)
            yield item

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        with self.context(renderer=renderer, parent=parent):
            for child in self.children:
                child.build(renderer=renderer)
        return self.require_item()


class ControlColumn(Component):
    """Vertical composition container for arbitrary framework components."""

    profile_key = "control_column"

    def __init__(
        self,
        children: Iterable[Component] = (),
        *,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.children = list(children)

    def add(self, component: Component) -> Component:
        self.children.append(component)
        return component

    @contextmanager
    def context(self, *, renderer=None, parent=None):
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        if resolved.spacing is not None:
            # Dear PyGui's vertical group does not expose a separate vertical
            # spacing argument. Keep the resolved value available for backend
            # implementations that do; the DPG bridge simply uses theme spacing.
            pass
        self._with_parent(kwargs, parent)

        with renderer.container("column", **kwargs) as item:
            self._bind(renderer, item)
            yield item

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        with self.context(renderer=renderer, parent=parent):
            for child in self.children:
                child.build(renderer=renderer)
        return self.require_item()


class ControlGrid(Component):
    """Borderless aligned grid for repeated form rows."""

    profile_key = "control_grid"

    def __init__(
        self,
        rows: Sequence[Sequence[Component]],
        *,
        column_widths: Sequence[int] | None = None,
        column_profile_key: str | None = None,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.rows = [list(row) for row in rows]
        self.column_widths = tuple(int(value) for value in (column_widths or ()))
        self.column_profile_key = str(column_profile_key).strip() if column_profile_key else None
        self._validate_rows()

    def _validate_rows(self) -> None:
        if not self.rows:
            return
        width = len(self.rows[0])
        if width <= 0:
            raise ValueError("control-grid rows must not be empty")
        if any(len(row) != width for row in self.rows):
            raise ValueError("all control-grid rows must contain the same number of components")
        if self.column_widths and len(self.column_widths) != width:
            raise ValueError("column_widths must match the number of grid columns")
        if any(value <= 0 for value in self.column_widths):
            raise ValueError("control-grid column widths must be positive")

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            header_row=False,
            policy="fixed_fit",
            borders_outerH=False,
            borders_innerH=False,
            borders_outerV=False,
            borders_innerV=False,
        )
        self._with_parent(kwargs, parent)

        profile = getattr(renderer, "component_profile", None)
        resolved_columns = self.column_widths
        if not resolved_columns and profile is not None and self.column_profile_key:
            resolved_columns = profile.columns_for(self.column_profile_key)
        column_count = len(self.rows[0]) if self.rows else len(resolved_columns)
        if resolved_columns and len(resolved_columns) != column_count:
            raise ValueError("profile column widths must match the number of grid columns")

        # Explicitly sized/placed children contribute a minimum column extent.
        # This is what lets a PositionedPanel wrapped with PlacedComponent live
        # inside a normal grid cell without the grid pretending the offset does
        # not occupy space.  AUTO-sized children remain backend-natural.
        column_hints = [0] * column_count
        for row in self.rows:
            for index, child in enumerate(row):
                width_hint, _height_hint = child.layout_size_hint(renderer=renderer)
                if width_hint is not None:
                    column_hints[index] = max(column_hints[index], int(width_hint))

        with renderer.container("grid", **kwargs) as item:
            self._bind(renderer, item)
            for index in range(column_count):
                column_kwargs = {"width_fixed": True}
                requested = resolved_columns[index] if resolved_columns else 0
                requested = max(int(requested or 0), column_hints[index])
                if requested > 0:
                    column_kwargs["init_width_or_weight"] = requested
                renderer.create("grid_column", **column_kwargs)

            for row in self.rows:
                with renderer.container("grid_row"):
                    for child in row:
                        child.build(renderer=renderer)
        return self.require_item()


class SectionPanel(Component):
    """Bordered structural region with an optional heading and separator.

    ``context()`` supports incremental migration of existing imperative views:
    the framework owns the panel contract while callers may continue building
    proven content inside the yielded backend item.  ``build()`` provides the
    normal declarative child path for new code.
    """

    profile_key = "section_panel"

    def __init__(
        self,
        heading: str | Label | None = None,
        children: Iterable[Component] = (),
        *,
        heading_color=None,
        separated: bool = True,
        border: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        if isinstance(heading, Label):
            self.heading = heading
        elif heading is None:
            self.heading = None
        else:
            self.heading = Label(str(heading), color=heading_color)
        self.separator = Separator() if separated and self.heading is not None else None
        self.children = list(children)
        self.border = bool(border)

    def add(self, component: Component) -> Component:
        self.children.append(component)
        return component

    @contextmanager
    def context(self, *, renderer=None, parent=None):
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs["border"] = self.border
        self._with_parent(kwargs, parent)

        with renderer.container("panel", **kwargs) as item:
            self._bind(renderer, item)
            if self.heading is not None:
                self.heading.build(renderer=renderer)
            if self.separator is not None:
                self.separator.build(renderer=renderer)
            yield item

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        with self.context(renderer=renderer, parent=parent):
            for child in self.children:
                child.build(renderer=renderer)
        return self.require_item()


class Dialog(Component):
    """Window/dialog structural container with semantic component sizing."""

    profile_key = "dialog"

    def __init__(
        self,
        label: str,
        children: Iterable[Component] = (),
        *,
        modal: bool = False,
        show: bool = False,
        no_resize: bool = False,
        no_move: bool = False,
        no_collapse: bool = False,
        minimum_size: tuple[int, int] | None = None,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.label = str(label)
        self.children = list(children)
        self.modal = bool(modal)
        self.show = bool(show)
        self.no_resize = bool(no_resize)
        self.no_move = bool(no_move)
        self.no_collapse = bool(no_collapse)
        if minimum_size is None:
            self.minimum_size = None
        else:
            if len(minimum_size) != 2:
                raise ValueError("dialog minimum_size must contain width and height")
            minimum_width, minimum_height = (int(value) for value in minimum_size)
            if minimum_width <= 0 or minimum_height <= 0:
                raise ValueError("dialog minimum_size values must be positive")
            self.minimum_size = (minimum_width, minimum_height)

    def add(self, component: Component) -> Component:
        self.children.append(component)
        return component

    @contextmanager
    def context(self, *, renderer=None, parent=None):
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            label=self.label,
            modal=self.modal,
            show=self.show,
            no_resize=self.no_resize,
            no_move=self.no_move,
            no_collapse=self.no_collapse,
            min_size=list(self.minimum_size) if self.minimum_size else None,
        )
        self._with_parent(kwargs, parent)

        with renderer.container("dialog", **kwargs) as item:
            self._bind(renderer, item)
            yield item

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        with self.context(renderer=renderer, parent=parent):
            for child in self.children:
                child.build(renderer=renderer)
        return self.require_item()

    def center(self) -> None:
        """Center the rendered dialog without exposing backend viewport APIs."""

        renderer = self._renderer or get_default_renderer()
        fallback_size = None
        resolved = self.resolved_layout
        if resolved is not None:
            if isinstance(resolved.width, int) and isinstance(resolved.height, int):
                fallback_size = (resolved.width, resolved.height)
        renderer.center(self.require_item(), fallback_size=fallback_size)

    def show_centered(self) -> None:
        self.set_visible(True)
        self.center()
