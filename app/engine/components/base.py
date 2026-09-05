"""Base classes shared by GUI primitives and composites."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.engine.components.layout import (
    DEFAULT_CONTROL_LAYOUT,
    ControlLayout,
    ControlLayoutDefaults,
    ControlLayoutTheme,
    ResolvedControlLayout,
    backend_dimension,
    resolve_control_layout,
)
from app.engine.components.renderer import ComponentRenderer, get_default_renderer


class Component(ABC):
    """Renderable framework component with resolved layout provenance."""

    layout_defaults = DEFAULT_CONTROL_LAYOUT

    def __init__(
        self,
        *,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
    ):
        self.theme = theme or ControlLayoutTheme()
        self.layout = layout or ControlLayout()
        self.item: object | None = None
        self.resolved_layout: ResolvedControlLayout | None = None
        self._renderer: ComponentRenderer | None = None

    def _resolve_layout(
        self,
        defaults: ControlLayoutDefaults | None = None,
    ) -> ResolvedControlLayout:
        resolved = resolve_control_layout(
            theme=self.theme,
            override=self.layout,
            defaults=defaults or self.layout_defaults,
        )
        self.resolved_layout = resolved
        return resolved

    @staticmethod
    def _layout_kwargs(resolved: ResolvedControlLayout) -> dict:
        width = backend_dimension(resolved.width)
        height = backend_dimension(resolved.height)
        kwargs = {}
        if width is not None:
            kwargs["width"] = width
        if height is not None:
            kwargs["height"] = height
        return kwargs

    @staticmethod
    def _with_parent(kwargs: dict, parent: object | None) -> dict:
        if parent is not None:
            kwargs["parent"] = parent
        return kwargs

    def _bind(self, renderer: ComponentRenderer, item: object) -> object:
        self._renderer = renderer
        self.item = item
        return item

    def require_item(self) -> object:
        if self.item is None:
            raise RuntimeError(f"{self.__class__.__name__} has not been built")
        return self.item

    @abstractmethod
    def build(
        self,
        *,
        renderer: ComponentRenderer | None = None,
        parent: object | None = None,
    ) -> object:
        ...


class ValueComponent(Component):
    """Component whose primary Dear PyGui item owns a value."""

    def get_value(self):
        renderer = self._renderer or get_default_renderer()
        return renderer.get_value(self.require_item())

    def set_value(self, value) -> None:
        renderer = self._renderer or get_default_renderer()
        renderer.set_value(self.require_item(), value)

    def configure(self, **kwargs) -> None:
        renderer = self._renderer or get_default_renderer()
        renderer.configure(self.require_item(), **kwargs)
