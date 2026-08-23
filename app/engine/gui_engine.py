# app/engine/gui_engine.py

from typing import Optional
import dearpygui.dearpygui as dpg
from app.engine.scene_manager import SceneManager


class GuiEngine:
    _instance: Optional["GuiEngine"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GuiEngine, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        dpg.create_context()
        dpg.create_viewport(title="SalixTorrent (Salix_T)", width=1100, height=700)
        dpg.setup_dearpygui()

        self.scene_mgr = SceneManager.get_instance()
        self.scene_mgr.engine = self
        self._initialized = True

    @classmethod
    def get_instance(cls) -> "GuiEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def switch_scene(self, scene_name: str, **kwargs):
        self.scene_mgr.switch_to(scene_name, **kwargs)

    def run(self):
        """Starts the native Dear PyGui render loop."""
        dpg.show_viewport()

        while dpg.is_dearpygui_running():
            if self.scene_mgr.current_scene:
                active_scene = self.scene_mgr.scenes.get(self.scene_mgr.current_scene)
                if active_scene and hasattr(active_scene, "update"):
                    active_scene.update(0.016)

            dpg.render_dearpygui_frame()

        dpg.destroy_context()
