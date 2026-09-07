"""Scene-manager and concrete presentation-host boundary regressions."""

from __future__ import annotations

import inspect
import unittest

from app.engine.scene_manager import SceneManager
from app.runtime.scenes import SceneRegistry


class Host:
    def __init__(self):
        self.alive = set()
        self.visible = set()

    def exists(self, item):
        return item in self.alive

    def show(self, item):
        self.visible.add(item)

    def hide(self, item):
        self.visible.discard(item)


class SceneRuntimeAdapterTests(unittest.TestCase):
    def setUp(self):
        SceneManager._instance = None

    def tearDown(self):
        SceneManager._instance = None

    def test_scene_manager_is_composition_over_generic_registry(self):
        manager = SceneManager.get_instance()
        self.assertIsInstance(manager._registry, SceneRegistry)

    def test_scene_manager_module_no_longer_imports_dearpygui(self):
        import app.engine.scene_manager as module

        source = inspect.getsource(module)
        self.assertNotIn("dearpygui", source.lower())

    def test_historical_container_convention_is_application_facade_only(self):
        host = Host()
        host.alive.add("view_container_Main")
        manager = SceneManager.get_instance()
        manager.set_host(host)
        scene = object()
        manager.register_scene("Main", scene)
        self.assertTrue(manager.switch_to("Main"))
        self.assertEqual(manager.current_scene, "Main")
        self.assertIs(manager.scenes["Main"], scene)
        self.assertIs(manager.get_scene("Main"), scene)
        self.assertIs(manager.active_scene(), scene)
        self.assertEqual(host.visible, {"view_container_Main"})

    def test_dearpygui_scene_host_is_concrete_engine_adapter(self):
        import app.engine.scene_hosts.dearpygui as adapter

        source = inspect.getsource(adapter)
        self.assertIn("dearpygui", source.lower())
        self.assertNotIn("app.views", source)
        self.assertNotIn("app.logic", source)

    def test_gui_engine_installs_scene_host_and_generic_runtime(self):
        from pathlib import Path
        from tests.helpers import PROJECT_ROOT

        source = (PROJECT_ROOT / "app" / "engine" / "gui_engine.py").read_text(encoding="utf-8")
        self.assertIn("DearPyGuiSceneHost", source)
        self.assertIn("ApplicationRuntime", source)
        self.assertIn("CallbackService", source)
        self.assertIn("self.runtime.update(delta_seconds)", source)
        self.assertIn("self.runtime.stop()", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
