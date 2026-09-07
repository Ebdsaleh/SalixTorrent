# app/engine/scene_manager.py

from __future__ import annotations

from typing import Any, Optional

from app.runtime.scenes import SceneHost, SceneRegistry


class SceneManager:
    """SalixTorrent singleton facade over the reusable scene registry.

    The application keeps its historical singleton/access pattern while the
    reusable registration/activation semantics live in ``app.runtime.scenes``.
    Concrete visibility operations are supplied by the selected presentation
    backend through ``set_host(...)``.
    """

    _instance: Optional["SceneManager"] = None

    def __new__(cls, engine=None):
        if cls._instance is None:
            cls._instance = super(SceneManager, cls).__new__(cls)
            cls._instance.engine = engine
            cls._instance._registry = SceneRegistry()
        elif engine is not None:
            cls._instance.engine = engine
        return cls._instance

    @classmethod
    def get_instance(cls) -> "SceneManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def scenes(self) -> dict[str, Any]:
        return self._registry.scenes

    @property
    def current_scene(self) -> Optional[str]:
        return self._registry.current_name

    def set_host(self, host: SceneHost) -> SceneHost:
        return self._registry.set_host(host)

    def get_scene(self, name: str) -> Any | None:
        return self._registry.get(name)

    def active_scene(self) -> Any | None:
        return self._registry.active_scene()

    def register_scene(self, name: str, scene_instance: Any, container=None):
        if container is None:
            container = f"view_container_{name}"
        return self._registry.register(
            name,
            scene_instance,
            container=container,
        )

    def unregister_scene(self, name: str):
        return self._registry.unregister(name)

    def switch_to(self, name: str, **kwargs):
        return self._registry.activate(name, **kwargs)
