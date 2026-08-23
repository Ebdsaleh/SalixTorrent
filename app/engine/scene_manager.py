# app/engine/scene_manager.py

from typing import Optional, Dict, Any
import dearpygui.dearpygui as dpg


class SceneManager:
    _instance: Optional["SceneManager"] = None

    def __new__(cls, engine=None):
        if cls._instance is None:
            cls._instance = super(SceneManager, cls).__new__(cls)
            cls._instance.engine = engine
            cls._instance.scenes: Dict[str, Any] = {}
            cls._instance.current_scene: Optional[str] = None
        return cls._instance

    @classmethod
    def get_instance(cls) -> "SceneManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_scene(self, name: str, scene_instance: Any):
        self.scenes[name] = scene_instance

    def switch_to(self, name: str, **kwargs):
        if name not in self.scenes:
            return

        # Hide all registered container groups
        for scene_key in self.scenes:
            container_tag = f"view_container_{scene_key}"
            if dpg.does_item_exist(container_tag):
                dpg.hide_item(container_tag)

        # Show target container
        target_tag = f"view_container_{name}"
        if dpg.does_item_exist(target_tag):
            dpg.show_item(target_tag)

        self.current_scene = name
        target_scene = self.scenes[name]
        if hasattr(target_scene, "on_show"):
            target_scene.on_show(**kwargs)
