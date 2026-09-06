"""Reusable component composition containers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.engine.components.base import Component
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

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        if resolved.spacing is not None:
            kwargs["horizontal_spacing"] = resolved.spacing
        self._with_parent(kwargs, parent)

        with renderer.container("row", **kwargs) as item:
            self._bind(renderer, item)
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

    def build(self, *, renderer=None, parent=None) -> object:
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
