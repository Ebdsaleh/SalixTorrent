"""Backend-neutral scene/view registration and activation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SceneHost(Protocol):
    """Presentation operations required to activate registered scene containers."""

    def exists(self, container: object) -> bool:
        ...

    def show(self, container: object) -> None:
        ...

    def hide(self, container: object) -> None:
        ...


def _scene_host_contract_errors(host: object) -> tuple[str, ...]:
    required = ("exists", "show", "hide")
    return tuple(name for name in required if not callable(getattr(host, name, None)))


@dataclass(frozen=True)
class SceneRecord:
    name: str
    scene: Any
    container: object


class SceneRegistry:
    """Own scene identities/lifecycle while delegating visibility to a host."""

    def __init__(self, host: SceneHost | None = None):
        self._host: SceneHost | None = None
        self._records: dict[str, SceneRecord] = {}
        self.current_name: str | None = None
        if host is not None:
            self.set_host(host)

    @property
    def host(self) -> SceneHost | None:
        return self._host

    @property
    def scenes(self) -> dict[str, Any]:
        return {name: record.scene for name, record in self._records.items()}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._records)

    def set_host(self, host: SceneHost) -> SceneHost:
        missing = _scene_host_contract_errors(host)
        if missing:
            raise TypeError(
                "scene host does not satisfy SceneHost; "
                f"missing: {', '.join(missing)}"
            )
        self._host = host
        return host

    def register(self, name: str, scene: Any, *, container: object) -> Any:
        key = str(name or "").strip()
        if not key:
            raise ValueError("scene name must not be empty")
        if key in self._records:
            raise ValueError(f"scene already registered: {key}")
        if container is None:
            raise ValueError("scene container must not be None")
        self._records[key] = SceneRecord(key, scene, container)
        return scene

    def unregister(self, name: str) -> Any | None:
        key = str(name)
        record = self._records.pop(key, None)
        if record is None:
            return None
        if self.current_name == key:
            self.current_name = None
        return record.scene

    def get(self, name: str) -> Any | None:
        record = self._records.get(str(name))
        return record.scene if record is not None else None

    def active_scene(self) -> Any | None:
        return self.get(self.current_name or "")

    def activate(self, name: str, **kwargs) -> bool:
        key = str(name)
        record = self._records.get(key)
        if record is None:
            return False
        if self._host is None:
            raise RuntimeError("no scene host is installed")

        for other in self._records.values():
            if self._host.exists(other.container):
                self._host.hide(other.container)

        if self._host.exists(record.container):
            self._host.show(record.container)

        self.current_name = key
        callback = getattr(record.scene, "on_show", None)
        if callable(callback):
            callback(**kwargs)
        return True
