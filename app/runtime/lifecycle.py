"""Backend-neutral application and service lifecycle coordination."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol, runtime_checkable


class RuntimeState(str, Enum):
    """Explicit lifecycle states for :class:`ApplicationRuntime`."""

    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


@runtime_checkable
class RuntimeService(Protocol):
    """Minimal service contract supervised by the application runtime."""

    def start(self) -> None:
        ...

    def update(self, delta_seconds: float) -> None:
        ...

    def stop(self) -> None:
        ...


@dataclass
class CallbackService:
    """Explicit adapter for small lifecycle callbacks.

    The runtime intentionally does not discover arbitrary method names or
    mutate application objects implicitly.  Callers provide the callbacks they
    want supervised, while unused phases remain deterministic no-ops.
    """

    on_start: Callable[[], object] | None = None
    on_update: Callable[[float], object] | None = None
    on_stop: Callable[[], object] | None = None

    def start(self) -> None:
        if self.on_start is not None:
            self.on_start()

    def update(self, delta_seconds: float) -> None:
        if self.on_update is not None:
            self.on_update(float(delta_seconds))

    def stop(self) -> None:
        if self.on_stop is not None:
            self.on_stop()


def _service_contract_errors(service: object) -> tuple[str, ...]:
    required = ("start", "update", "stop")
    return tuple(name for name in required if not callable(getattr(service, name, None)))


class ServiceRegistry:
    """Ordered runtime-service registry with explicit lifecycle operations."""

    def __init__(self):
        self._services: OrderedDict[str, RuntimeService] = OrderedDict()
        self._started: list[str] = []

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._services)

    @property
    def started_names(self) -> tuple[str, ...]:
        return tuple(self._started)

    def register(self, name: str, service: RuntimeService) -> RuntimeService:
        key = str(name or "").strip()
        if not key:
            raise ValueError("runtime service name must not be empty")
        if key in self._services:
            raise ValueError(f"runtime service already registered: {key}")
        missing = _service_contract_errors(service)
        if missing:
            raise TypeError(
                "runtime service does not satisfy RuntimeService; "
                f"missing: {', '.join(missing)}"
            )
        self._services[key] = service
        return service

    def get(self, name: str) -> RuntimeService | None:
        return self._services.get(str(name))

    def unregister(self, name: str) -> RuntimeService | None:
        key = str(name)
        if key in self._started:
            raise RuntimeError("cannot unregister a started runtime service")
        return self._services.pop(key, None)

    def start_all(self) -> None:
        if self._started:
            raise RuntimeError("runtime services are already started")

        for name, service in self._services.items():
            try:
                service.start()
            except Exception:
                # A service can fail after partially acquiring resources. Give
                # that service one best-effort stop before rolling back earlier
                # successfully started services in reverse order. Cleanup
                # failures never replace the original startup exception.
                try:
                    service.stop()
                except Exception:
                    pass
                for started_name in reversed(self._started):
                    try:
                        self._services[started_name].stop()
                    except Exception:
                        pass
                self._started.clear()
                raise
            self._started.append(name)

    def update_all(
        self,
        delta_seconds: float,
        *,
        error_handler: Callable[[str, Exception], object] | None = None,
    ) -> None:
        delta = max(0.0, float(delta_seconds))
        for name in tuple(self._started):
            try:
                self._services[name].update(delta)
            except Exception as exc:
                if error_handler is None:
                    raise
                error_handler(name, exc)

    def stop_all(
        self,
        *,
        error_handler: Callable[[str, Exception], object] | None = None,
    ) -> None:
        first_error: Exception | None = None
        for name in reversed(self._started):
            try:
                self._services[name].stop()
            except Exception as exc:
                if error_handler is not None:
                    error_handler(name, exc)
                elif first_error is None:
                    first_error = exc
        self._started.clear()
        if first_error is not None:
            raise first_error


class ApplicationRuntime:
    """Supervise generic application services independently of presentation.

    A graphical engine, a CLI runner or a test harness may all drive the same
    runtime explicitly by calling ``start()``, ``update(delta)`` and ``stop()``.
    The runtime does not own a window, renderer, event loop or worker thread.
    """

    def __init__(
        self,
        *,
        services: ServiceRegistry | None = None,
        error_handler: Callable[[str, Exception], object] | None = None,
    ):
        self.services = services or ServiceRegistry()
        self.error_handler = error_handler
        self.state = RuntimeState.NEW

    @property
    def is_running(self) -> bool:
        return self.state is RuntimeState.RUNNING

    def start(self) -> None:
        if self.state is RuntimeState.RUNNING:
            return
        if self.state not in {RuntimeState.NEW, RuntimeState.STOPPED}:
            raise RuntimeError(f"cannot start runtime while state is {self.state.value}")

        self.state = RuntimeState.STARTING
        try:
            self.services.start_all()
        except Exception:
            self.state = RuntimeState.STOPPED
            raise
        self.state = RuntimeState.RUNNING

    def update(self, delta_seconds: float) -> None:
        if self.state is not RuntimeState.RUNNING:
            raise RuntimeError("application runtime must be running before update")
        self.services.update_all(
            delta_seconds,
            error_handler=self.error_handler,
        )

    def stop(self) -> None:
        if self.state in {RuntimeState.NEW, RuntimeState.STOPPED}:
            self.state = RuntimeState.STOPPED
            return
        if self.state is RuntimeState.STOPPING:
            return

        self.state = RuntimeState.STOPPING
        try:
            self.services.stop_all(error_handler=self.error_handler)
        finally:
            self.state = RuntimeState.STOPPED
