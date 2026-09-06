"""Base classes shared by GUI primitives and composites."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from .layout import (
    DEFAULT_CONTROL_LAYOUT,
    ControlLayout,
    ControlLayoutDefaults,
    ControlLayoutTheme,
    ResolvedControlLayout,
    backend_dimension,
    resolve_control_layout,
)
from .profile import FRAMEWORK_COMPONENT_PROFILE
from .renderer import ComponentRenderer, get_default_renderer


class Component(ABC):
    """Renderable framework component with resolved layout provenance."""

    layout_defaults = DEFAULT_CONTROL_LAYOUT
    profile_key = "component"

    def __init__(
        self,
        *,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        self.theme = theme or ControlLayoutTheme()
        self.layout = layout or ControlLayout()
        self.profile_key = str(profile_key).strip() if profile_key else self.profile_key
        self.item: object | None = None
        self.resolved_layout: ResolvedControlLayout | None = None
        self._renderer: ComponentRenderer | None = None
        self._attachments: list[Callable[[object, ComponentRenderer], None]] = []

    def _resolve_layout(
        self,
        defaults: ControlLayoutDefaults | None = None,
        *,
        renderer: ComponentRenderer | None = None,
    ) -> ResolvedControlLayout:
        if defaults is None:
            active_renderer = renderer or self._renderer
            profile = getattr(active_renderer, "component_profile", None)
            if profile is None:
                profile = FRAMEWORK_COMPONENT_PROFILE
            defaults = profile.layout_for(
                self.profile_key,
                fallback_key=getattr(self.__class__, "profile_key", "component"),
                fallback=self.layout_defaults,
            )
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

    def attach(
        self,
        attachment: Callable[[object, ComponentRenderer], None],
    ) -> "Component":
        """Attach backend-neutral post-build behavior to this component.

        Attachments receive the created backend item and active renderer.  The
        framework does not interpret their semantics; applications can use the
        hook for tooltips, accessibility metadata, diagnostics, or other
        renderer-adjacent behavior without teaching generic components about
        product-specific concepts.
        """

        if not callable(attachment):
            raise TypeError("component attachment must be callable")
        self._attachments.append(attachment)
        if self.item is not None and self._renderer is not None and self.exists():
            attachment(self.item, self._renderer)
        return self

    def _bind(self, renderer: ComponentRenderer, item: object) -> object:
        self._renderer = renderer
        self.item = item
        for attachment in tuple(self._attachments):
            attachment(item, renderer)
        return item

    def require_item(self) -> object:
        if self.item is None:
            raise RuntimeError(f"{self.__class__.__name__} has not been built")
        renderer = self._renderer or get_default_renderer()
        if not renderer.exists(self.item):
            raise RuntimeError(
                f"{self.__class__.__name__} rendered item no longer exists; rebuild the component"
            )
        return self.item

    def exists(self) -> bool:
        """Return whether the rendered backend item still exists."""

        if self.item is None:
            return False
        renderer = self._renderer or get_default_renderer()
        return bool(renderer.exists(self.item))

    def dispose(self) -> bool:
        """Release this component's rendered root through its active renderer.

        Disposal is explicit and idempotent.  A container's backend root owns
        its backend descendants, so destroying that root may also invalidate
        separately referenced child components.  Those wrappers then report
        ``exists() == False`` and reject stale-handle access through
        :meth:`require_item`.  Attachments remain registered so a later rebuild
        can reapply them.
        """

        if self.item is None:
            return False

        renderer = self._renderer or get_default_renderer()
        item = self.item
        existed = bool(renderer.exists(item))
        if existed:
            renderer.destroy(item)

        self.item = None
        self._renderer = None
        self.resolved_layout = None
        return existed

    def configure(self, **kwargs) -> None:
        """Configure the rendered item through the active renderer."""

        renderer = self._renderer or get_default_renderer()
        renderer.configure(self.require_item(), **kwargs)

    def set_enabled(self, enabled: bool) -> None:
        """Set interactive enabled state without exposing backend APIs."""

        self.configure(enabled=bool(enabled))

    def set_visible(self, visible: bool) -> None:
        """Set visibility without exposing backend-specific ``show`` calls."""

        self.configure(show=bool(visible))

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
