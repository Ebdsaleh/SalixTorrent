"""Renderer contract and explicit default-renderer installation.

The reusable component core deliberately does not choose a concrete GUI
backend.  Applications install one renderer at their composition root, while
tests and embedded callers may pass a renderer directly to ``build(...)``.
"""

from __future__ import annotations

from typing import Callable, ContextManager, Protocol, runtime_checkable

from .events import ComponentEvent, ComponentEventType
from .profile import ComponentLayoutProfile


@runtime_checkable
class ComponentRenderer(Protocol):
    """Minimal renderer contract consumed by the reusable component layer."""

    component_profile: ComponentLayoutProfile

    def set_component_profile(self, profile: ComponentLayoutProfile) -> None:
        ...

    def create(self, kind: str, **kwargs) -> object:
        ...

    def container(self, kind: str, **kwargs) -> ContextManager[object]:
        ...

    def get_value(self, item: object):
        ...

    def set_value(self, item: object, value) -> None:
        ...

    def configure(self, item: object, **kwargs) -> None:
        ...

    def place(self, item: object, x: int, y: int) -> None:
        ...

    def measure(self, item: object) -> tuple[int, int]:
        ...

    def exists(self, item: object) -> bool:
        ...

    def destroy(self, item: object) -> None:
        ...

    def event_callback(
        self,
        source: object,
        event_type: ComponentEventType,
        callback: Callable[[ComponentEvent], object] | None,
        *,
        data: object = None,
    ) -> object | None:
        ...

    def center(self, item: object, *, fallback_size: tuple[int, int] | None = None) -> None:
        ...

    def attach_tooltip(self, item: object, text: str, *, wrap: int = 450) -> object | None:
        ...


_default_renderer: ComponentRenderer | None = None


def _renderer_contract_errors(renderer: object) -> tuple[str, ...]:
    required_methods = (
        "set_component_profile",
        "create",
        "container",
        "get_value",
        "set_value",
        "configure",
        "place",
        "measure",
        "exists",
        "destroy",
        "event_callback",
        "center",
        "attach_tooltip",
    )
    missing = [name for name in required_methods if not callable(getattr(renderer, name, None))]
    if not hasattr(renderer, "component_profile"):
        missing.append("component_profile")
    return tuple(missing)


def set_default_renderer(renderer: ComponentRenderer) -> ComponentRenderer:
    """Install the process-local component renderer explicitly.

    The framework core owns only this small registry.  Concrete backend
    construction belongs to the application composition root.
    """

    missing = _renderer_contract_errors(renderer)
    if missing:
        raise TypeError(
            "default component renderer does not satisfy ComponentRenderer; "
            f"missing: {', '.join(missing)}"
        )

    global _default_renderer
    _default_renderer = renderer
    return renderer


def get_default_renderer() -> ComponentRenderer:
    """Return the installed renderer or fail clearly when none is configured."""

    if _default_renderer is None:
        raise RuntimeError(
            "no default component renderer is installed; pass renderer=... explicitly "
            "or install one at the application composition root"
        )
    return _default_renderer


def clear_default_renderer(
    renderer: ComponentRenderer | None = None,
) -> ComponentRenderer | None:
    """Clear the installed renderer, optionally only when identity matches.

    Returning the previous renderer makes deterministic test setup/teardown
    possible without introducing a hidden lifecycle manager.
    """

    global _default_renderer
    current = _default_renderer
    if current is None:
        return None
    if renderer is not None and current is not renderer:
        return None
    _default_renderer = None
    return current
