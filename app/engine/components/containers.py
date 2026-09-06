"""Reusable component composition containers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager

from app.engine.components.base import Component
from app.engine.components.controls import Label, Separator
from app.engine.components.layout import ControlLayout, ControlLayoutTheme
from app.engine.components.renderer import ComponentRenderer, get_default_renderer


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

        with renderer.container("grid", **kwargs) as item:
            self._bind(renderer, item)
            for index in range(column_count):
                column_kwargs = {"width_fixed": True}
                if resolved_columns:
                    column_kwargs["init_width_or_weight"] = resolved_columns[index]
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
