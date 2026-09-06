"""Backend-neutral responsive-layout coordination contracts.

The framework owns callback registration, refresh/trigger semantics and
low-churn geometry application. Concrete GUI toolkits provide a small
``LayoutHost`` adapter that owns their native resize hooks, item handles and
configuration calls.
"""

from __future__ import annotations

from typing import Callable, Hashable, Iterable, Protocol, runtime_checkable

from .geometry import DialogMetrics, Number, clamp, fill_height


@runtime_checkable
class LayoutHost(Protocol):
    """Backend operations required by :class:`LayoutCoordinator`.

    Native callback signatures and handler/registry ownership stay behind this
    contract. Framework callbacks are always zero-argument callables.
    """

    def install_viewport_resize(self, callback: Callable[[], object]) -> bool:
        ...

    def watch_item_resize(
        self,
        item: object,
        callback: Callable[[], object],
    ) -> object | None:
        ...

    def unwatch_item_resize(self, watch: object) -> None:
        ...

    def item_size(self, item: object) -> tuple[int, int]:
        ...

    def configure(self, item: object, **kwargs) -> bool:
        ...


def _layout_host_contract_errors(host: object) -> tuple[str, ...]:
    required_methods = (
        "install_viewport_resize",
        "watch_item_resize",
        "unwatch_item_resize",
        "item_size",
        "configure",
    )
    return tuple(
        name for name in required_methods if not callable(getattr(host, name, None))
    )


class LayoutCoordinator:
    """Coordinate responsive callbacks and memoized geometry through a host.

    The coordinator deliberately knows nothing about Dear PyGui, Qt, Tk or any
    other GUI toolkit. Applications choose and construct a concrete
    :class:`LayoutHost`, then either use this object directly or wrap it in an
    application-level singleton/service.
    """

    def __init__(self, host: LayoutHost):
        missing = _layout_host_contract_errors(host)
        if missing:
            raise TypeError(
                "layout host does not satisfy LayoutHost; "
                f"missing: {', '.join(missing)}"
            )

        self.host = host
        self._viewport_callbacks: dict[Hashable, Callable[[], object]] = {}
        self._item_callbacks: dict[Hashable, Callable[[], object]] = {}
        self._item_watches: dict[Hashable, object] = {}
        self._applied: dict[tuple[object, str], object] = {}
        self._viewport_installed = False

    @staticmethod
    def _invoke(callback: Callable[[], object]) -> bool:
        try:
            callback()
            return True
        except Exception:
            # Responsive layout must not terminate the application when one
            # view-level callback encounters transient/stale UI state.
            return False

    def install_viewport_callback(self) -> bool:
        """Install one host viewport hook that dispatches registered callbacks."""
        if self._viewport_installed:
            return False
        try:
            installed = bool(self.host.install_viewport_resize(self._on_viewport_resize))
        except Exception:
            return False
        if installed:
            self._viewport_installed = True
        return installed

    def register_viewport(self, key: Hashable, callback: Callable[[], object]) -> None:
        if not callable(callback):
            raise TypeError("responsive viewport callback must be callable")
        self._viewport_callbacks[key] = callback

    def unregister_viewport(self, key: Hashable) -> None:
        self._viewport_callbacks.pop(key, None)

    def watch_item(
        self,
        item: object,
        key: Hashable,
        callback: Callable[[], object],
    ) -> object | None:
        """Register a callback and ask the host to watch one rendered item."""
        if not callable(callback):
            raise TypeError("responsive item callback must be callable")

        old_watch = self._item_watches.pop(key, None)
        if old_watch is not None:
            try:
                self.host.unwatch_item_resize(old_watch)
            except Exception:
                pass

        self._item_callbacks[key] = callback

        def _resized() -> None:
            self.trigger(key)

        try:
            watch = self.host.watch_item_resize(item, _resized)
        except Exception:
            watch = None
        if watch is not None:
            self._item_watches[key] = watch
        return watch

    def unwatch_item(self, key: Hashable) -> None:
        self._item_callbacks.pop(key, None)
        watch = self._item_watches.pop(key, None)
        if watch is None:
            return
        try:
            self.host.unwatch_item_resize(watch)
        except Exception:
            return

    def trigger(self, key: Hashable) -> bool:
        callback = self._item_callbacks.get(key) or self._viewport_callbacks.get(key)
        if callback is None:
            return False
        return self._invoke(callback)

    def refresh_all(self) -> None:
        """Refresh every registered geometry callback from stable snapshots."""
        for callback in tuple(self._viewport_callbacks.values()):
            self._invoke(callback)
        for callback in tuple(self._item_callbacks.values()):
            self._invoke(callback)

    def _on_viewport_resize(self) -> None:
        for callback in tuple(self._viewport_callbacks.values()):
            self._invoke(callback)

    def item_size(self, item: object) -> tuple[int, int]:
        try:
            width, height = self.host.item_size(item)
            return max(0, int(width)), max(0, int(height))
        except Exception:
            return (0, 0)

    def _apply(self, item: object, name: str, value: object, **kwargs) -> bool:
        key = (item, name)
        if self._applied.get(key) == value:
            return False
        try:
            applied = bool(self.host.configure(item, **kwargs))
        except Exception:
            return False
        if applied:
            self._applied[key] = value
        return applied

    def width(self, item: object, value: Number) -> bool:
        target = int(value)
        return self._apply(item, "width", target, width=target)

    def height(self, item: object, value: Number) -> bool:
        target = int(value)
        return self._apply(item, "height", target, height=target)

    def size(self, item: object, width: Number, height: Number) -> bool:
        target = (int(width), int(height))
        return self._apply(
            item,
            "size",
            target,
            width=target[0],
            height=target[1],
        )

    def wrap(self, item: object, value: Number) -> bool:
        target = max(1, int(value))
        return self._apply(item, "wrap", target, wrap=target)

    def wraps(self, items: Iterable[object], value: Number) -> None:
        for item in tuple(items):
            self.wrap(item, value)

    def indent(self, item: object, value: Number) -> bool:
        target = max(0, int(value))
        return self._apply(item, "indent", target, indent=target)

    def dialog(
        self,
        window: object,
        content: object,
        *,
        metrics: DialogMetrics,
        wrap_items: Iterable[object] = (),
    ) -> None:
        """Resize a dialog's fill region and text measure from rendered size."""
        width, height = self.item_size(window)
        if width <= 1 or height <= 1:
            return
        self.height(
            content,
            fill_height(
                height,
                metrics.reserved_height,
                minimum=metrics.minimum_content_height,
            ),
        )
        wrap_width = clamp(
            width - metrics.horizontal_margin,
            metrics.minimum_wrap,
            metrics.maximum_wrap,
        )
        self.wraps(wrap_items, wrap_width)
