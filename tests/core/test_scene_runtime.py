"""Backend-neutral scene-registry regressions."""

from __future__ import annotations

import unittest

from app.runtime.scenes import SceneRegistry


class Host:
    def __init__(self):
        self.alive = set()
        self.visible = set()
        self.calls = []

    def exists(self, container):
        return container in self.alive

    def show(self, container):
        self.calls.append(("show", container))
        self.visible.add(container)

    def hide(self, container):
        self.calls.append(("hide", container))
        self.visible.discard(container)


class Scene:
    def __init__(self):
        self.shown = []

    def on_show(self, **kwargs):
        self.shown.append(dict(kwargs))


class SceneRegistryTests(unittest.TestCase):
    def test_registration_requires_unique_name_and_container(self):
        registry = SceneRegistry(Host())
        scene = Scene()
        registry.register("main", scene, container="main-container")
        with self.assertRaises(ValueError):
            registry.register("main", scene, container="duplicate")
        with self.assertRaises(ValueError):
            registry.register("", scene, container="bad")
        with self.assertRaises(ValueError):
            registry.register("other", scene, container=None)

    def test_host_contract_is_validated(self):
        with self.assertRaises(TypeError):
            SceneRegistry(object())

    def test_activation_requires_host_but_unknown_scene_is_safe_false(self):
        registry = SceneRegistry()
        registry.register("main", Scene(), container="main")
        self.assertFalse(registry.activate("missing"))
        with self.assertRaises(RuntimeError):
            registry.activate("main")

    def test_activation_hides_registered_containers_and_shows_target(self):
        host = Host()
        host.alive.update({"one", "two"})
        registry = SceneRegistry(host)
        registry.register("one", Scene(), container="one")
        registry.register("two", Scene(), container="two")
        self.assertTrue(registry.activate("two"))
        self.assertEqual(registry.current_name, "two")
        self.assertEqual(host.visible, {"two"})
        self.assertEqual(
            host.calls,
            [("hide", "one"), ("hide", "two"), ("show", "two")],
        )

    def test_on_show_receives_explicit_activation_data(self):
        host = Host()
        host.alive.add("main")
        scene = Scene()
        registry = SceneRegistry(host)
        registry.register("main", scene, container="main")
        registry.activate("main", topic="network", glossary=True)
        self.assertEqual(scene.shown, [{"topic": "network", "glossary": True}])

    def test_missing_rendered_container_still_updates_scene_lifecycle(self):
        host = Host()
        scene = Scene()
        registry = SceneRegistry(host)
        registry.register("main", scene, container="missing")
        self.assertTrue(registry.activate("main"))
        self.assertEqual(registry.current_name, "main")
        self.assertEqual(scene.shown, [{}])
        self.assertEqual(host.calls, [])

    def test_unregister_clears_active_identity(self):
        host = Host()
        host.alive.add("main")
        scene = Scene()
        registry = SceneRegistry(host)
        registry.register("main", scene, container="main")
        registry.activate("main")
        self.assertIs(registry.unregister("main"), scene)
        self.assertIsNone(registry.current_name)
        self.assertEqual(registry.names, ())

    def test_scene_mapping_is_a_snapshot_not_mutable_internal_state(self):
        registry = SceneRegistry(Host())
        scene = Scene()
        registry.register("main", scene, container="main")
        mapping = registry.scenes
        mapping.clear()
        self.assertIs(registry.get("main"), scene)


if __name__ == "__main__":
    unittest.main(verbosity=2)
