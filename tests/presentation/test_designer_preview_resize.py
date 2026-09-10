"""Regressions for selected-component pointer resizing in designer previews."""

from __future__ import annotations

import json
import unittest

from tests.helpers import PROJECT_ROOT
from tests.presentation.test_gui_components import RecordingRenderer

from app.engine.designer_preview_pointer_arbiter import DearPyGuiDesignerPreviewPointerArbiter
from app.engine.designer_preview_resize_hosts.dearpygui import DearPyGuiDesignerPreviewResizeHost
from app.engine.designer_preview_selection_hosts.dearpygui import DearPyGuiDesignerPreviewSelectionHost
from app.framework.components import Button, ControlColumn
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_preview_selection import DesignerPreviewSelectionTarget
from app.framework.designer_preview_resize import (
    DesignerPreviewResizeBinding,
    DesignerPreviewResizeSurface,
    DesignerPreviewResizeTarget,
)
from app.framework.designer_workspace import DesignerWorkspace


class RecordingResizeHost:
    def __init__(self):
        self.binding = None
        self.targets = []
        self.on_resize = None
        self.disposed = False

    def build(self, target, *, parent, on_resize):
        self.targets.append(target)
        self.on_resize = on_resize
        self.binding = DesignerPreviewResizeBinding(parent, target, {"alive": True})
        return self.binding

    def update(self, binding, target):
        self.targets.append(target)
        binding.target = target

    def exists(self, binding):
        return bool(binding is self.binding and not self.disposed)

    def dispose(self, binding):
        self.disposed = True
        if isinstance(binding.metadata, dict):
            binding.metadata.clear()

    def drag(self, node_id, width, height):
        if self.on_resize is None:
            raise RuntimeError("resize host was not built")
        return self.on_resize(node_id, width, height)


class _NativePreviewComponent:
    def __init__(self, item):
        self.item = item

    def require_item(self):
        return self.item


class _FakeDearPyGui:
    mvMouseButton_Left = 0
    mvKey_LShift = 1
    mvKey_RShift = 2
    mvKey_LControl = 3
    mvKey_RControl = 4

    def __init__(self):
        self._next = 100
        self.rects = {}
        self.mouse = (0.0, 0.0)
        self.hovered = set()
        self.items = set()
        self.mouse_down = []
        self.mouse_move = []
        self.mouse_release = []
        self.drawn = {}
        self.configured = []
        self.keys_down = set()

    def _id(self):
        self._next += 1
        self.items.add(self._next)
        return self._next

    def add_handler_registry(self):
        return self._id()

    def add_viewport_drawlist(self, **_kwargs):
        return self._id()

    def draw_rectangle(self, minimum, maximum, **_kwargs):
        item = self._id()
        self.drawn[item] = (tuple(minimum), tuple(maximum))
        return item

    def add_mouse_down_handler(self, *, callback, **_kwargs):
        self.mouse_down.append(callback)
        return self._id()

    def add_mouse_move_handler(self, *, callback, **_kwargs):
        self.mouse_move.append(callback)
        return self._id()

    def add_mouse_release_handler(self, *, callback, **_kwargs):
        self.mouse_release.append(callback)
        return self._id()

    def does_item_exist(self, item):
        return item in self.items or item in self.rects

    def delete_item(self, item):
        self.items.discard(item)
        self.drawn.pop(item, None)

    def get_item_rect_min(self, item):
        return self.rects[item][0]

    def get_item_rect_max(self, item):
        return self.rects[item][1]

    def get_mouse_pos(self, **_kwargs):
        return self.mouse

    def is_item_hovered(self, item):
        return item in self.hovered

    def is_key_down(self, key):
        return key in self.keys_down

    def configure_item(self, item, **kwargs):
        self.configured.append((item, dict(kwargs)))
        minimum, maximum = self.rects[item]
        width = kwargs.get("width", maximum[0] - minimum[0])
        height = kwargs.get("height", maximum[1] - minimum[1])
        self.rects[item] = (minimum, (minimum[0] + width, minimum[1] + height))


class DesignerPreviewResizeTests(unittest.TestCase):
    def _workspace(self):
        action = Button("Actions")
        source = ControlColumn((action, Button("Secondary")))
        identities = DesignerIdentityMap(prefix="resize")
        identities.bind(source, "root")
        identities.bind(action, "action")
        snapshot = capture_component_tree(source, identities=identities)
        workspace = DesignerWorkspace.create(
            snapshot,
            renderer=RecordingRenderer(),
            parent="preview",
        )
        return workspace

    def test_surface_requires_workspace_host_and_callbacks(self):
        workspace = self._workspace()
        with self.assertRaises(TypeError):
            DesignerPreviewResizeSurface(object(), RecordingResizeHost())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            DesignerPreviewResizeSurface(workspace, object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            DesignerPreviewResizeSurface(workspace, RecordingResizeHost(), on_change=object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            DesignerPreviewResizeSurface(workspace, RecordingResizeHost(), on_error=object())  # type: ignore[arg-type]
        workspace.close()

    def test_target_is_empty_without_selection(self):
        workspace = self._workspace()
        surface = DesignerPreviewResizeSurface(workspace, RecordingResizeHost())
        self.assertIsNone(surface.target)
        workspace.close()

    def test_selected_button_projects_preview_size_and_capabilities(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        target = DesignerPreviewResizeSurface(workspace, RecordingResizeHost()).target
        self.assertIsInstance(target, DesignerPreviewResizeTarget)
        assert target is not None
        self.assertEqual("action", target.node_id)
        self.assertEqual((120, 28), (target.width, target.height))
        self.assertTrue(target.can_resize_width)
        self.assertTrue(target.can_resize_height)
        self.assertTrue(target.resizable)
        self.assertEqual(
            {
                "node_id": "action",
                "width": 120,
                "height": 28,
                "can_resize_width": True,
                "can_resize_height": True,
            },
            target.to_descriptor(),
        )
        json.dumps(target.to_descriptor())
        workspace.close()

    def test_build_projects_current_target_and_parent(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        host = RecordingResizeHost()
        surface = DesignerPreviewResizeSurface(workspace, host)
        binding = surface.build(parent="preview-surface")
        self.assertTrue(surface.exists())
        self.assertEqual("preview-surface", binding.surface)
        self.assertEqual("action", host.targets[-1].node_id)
        with self.assertRaises(RuntimeError):
            surface.build(parent="again")
        workspace.close()

    def test_resize_commits_width_and_height_as_one_checked_history_step(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        host = RecordingResizeHost()
        changes = []
        surface = DesignerPreviewResizeSurface(
            workspace,
            host,
            on_change=lambda node_id, width, height: changes.append((node_id, width, height)),
        )
        surface.build(parent="preview")
        generation = workspace.state.preview_generation
        self.assertTrue(host.drag("action", 196, 36))
        self.assertEqual(1, workspace.session.undo_depth)
        self.assertEqual("Resize component", workspace.state.undo_label)
        self.assertEqual(196, workspace.session.node("action").properties["layout.width"])
        self.assertEqual(36, workspace.session.node("action").properties["layout.height"])
        self.assertEqual(generation + 1, workspace.state.preview_generation)
        self.assertEqual("action", workspace.state.selected_id)
        self.assertEqual([("action", 196, 36)], changes)
        self.assertEqual((196, 36), (surface.target.width, surface.target.height))
        workspace.close()

    def test_same_rendered_size_is_ephemeral_noop(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        host = RecordingResizeHost()
        surface = DesignerPreviewResizeSurface(workspace, host)
        surface.build(parent="preview")
        generation = workspace.state.preview_generation
        self.assertFalse(host.drag("action", 120, 28))
        self.assertEqual(0, workspace.session.undo_depth)
        self.assertEqual(generation, workspace.state.preview_generation)
        self.assertNotIn("layout.width", workspace.session.node("action").properties)
        self.assertNotIn("layout.height", workspace.session.node("action").properties)
        workspace.close()

    def test_resize_can_change_only_one_axis_without_extra_history_steps(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        host = RecordingResizeHost()
        surface = DesignerPreviewResizeSurface(workspace, host)
        surface.build(parent="preview")
        self.assertTrue(host.drag("action", 180, 28))
        self.assertEqual(1, workspace.session.undo_depth)
        self.assertEqual(180, workspace.session.node("action").properties["layout.width"])
        self.assertNotIn("layout.height", workspace.session.node("action").properties)
        workspace.close()

    def test_resize_undo_restores_default_size_and_stable_selection(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        surface = DesignerPreviewResizeSurface(workspace, RecordingResizeHost())
        surface.build(parent="preview")
        self.assertTrue(surface.resize("action", 184, 40))
        self.assertTrue(workspace.preview_host.undo())
        surface.refresh()
        self.assertEqual("action", workspace.state.selected_id)
        self.assertEqual((120, 28), (surface.target.width, surface.target.height))
        workspace.close()

    def test_invalid_pixels_are_rejected_before_document_mutation(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        surface = DesignerPreviewResizeSurface(workspace, RecordingResizeHost())
        surface.build(parent="preview")
        for width, height in ((0, 20), (20, 0), (True, 20), (20, "30")):
            with self.assertRaises((TypeError, ValueError)):
                surface.resize("action", width, height)  # type: ignore[arg-type]
        self.assertEqual(0, workspace.session.undo_depth)
        workspace.close()

    def test_stale_native_callback_cannot_resize_new_selection(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        host = RecordingResizeHost()
        errors = []
        surface = DesignerPreviewResizeSurface(
            workspace,
            host,
            on_error=lambda node_id, exc: errors.append((node_id, type(exc).__name__)),
        )
        surface.build(parent="preview")
        secondary_id = workspace.session.snapshot.root.children[1].node.node_id
        workspace.select_and_focus_node(secondary_id)
        self.assertFalse(host.drag("action", 200, 40))
        self.assertEqual([( "action", "RuntimeError")], errors)
        self.assertEqual(0, workspace.session.undo_depth)
        workspace.close()

    def test_refresh_rebinds_fresh_component_after_preview_replacement(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        host = RecordingResizeHost()
        surface = DesignerPreviewResizeSurface(workspace, host)
        surface.build(parent="preview")
        first_component = surface.target.component
        self.assertTrue(surface.resize("action", 190, 35))
        second_component = surface.target.component
        self.assertIsNot(first_component, second_component)
        self.assertEqual(workspace.state.preview_generation, surface.generation)
        self.assertGreaterEqual(len(host.targets), 2)
        workspace.close()

    def test_error_handler_converts_checked_resize_failure_to_false(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        host = RecordingResizeHost()
        errors = []
        surface = DesignerPreviewResizeSurface(
            workspace,
            host,
            on_error=lambda node_id, exc: errors.append((node_id, str(exc))),
        )
        surface.build(parent="preview")
        workspace.close()
        self.assertFalse(surface.resize("action", 180, 32))
        self.assertEqual("action", errors[-1][0])

    def test_dispose_is_explicit_and_idempotent(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("action")
        host = RecordingResizeHost()
        surface = DesignerPreviewResizeSurface(workspace, host)
        surface.build(parent="preview")
        self.assertTrue(surface.dispose())
        self.assertFalse(surface.dispose())
        self.assertTrue(host.disposed)
        workspace.close()

    def test_framework_surface_has_no_toolkit_or_product_imports(self):
        source = (PROJECT_ROOT / "app" / "framework" / "designer_preview_resize.py").read_text(
            encoding="utf-8"
        ).lower()
        self.assertNotIn("dearpygui", source)
        self.assertNotIn("tkinter", source)
        self.assertNotIn("salix_t", source)
        self.assertNotIn("torrent", source)

    def test_dpg_pointer_arbiter_blocks_handle_and_active_drag_selection(self):
        arbiter = DearPyGuiDesignerPreviewPointerArbiter()
        self.assertFalse(arbiter.blocks_selection(10, 10))
        arbiter.set_resize_handle_bounds((90.0, 40.0, 100.0, 50.0))
        self.assertTrue(arbiter.blocks_selection(95, 45))
        self.assertFalse(arbiter.blocks_selection(80, 45))
        arbiter.begin_resize("action")
        self.assertEqual("action", arbiter.resize_node_id)
        self.assertTrue(arbiter.blocks_selection(1, 1))
        arbiter.end_resize()
        self.assertFalse(arbiter.resizing)
        self.assertFalse(arbiter.blocks_selection(1, 1))

    def test_dpg_first_button_handle_press_cannot_promote_selection_to_parent(self):
        dpg = _FakeDearPyGui()
        root_item, first_item, second_item = 1, 2, 3
        dpg.rects = {
            root_item: ((0.0, 0.0), (120.0, 60.0)),
            first_item: ((0.0, 0.0), (120.0, 28.0)),
            second_item: ((0.0, 30.0), (120.0, 58.0)),
        }
        arbiter = DearPyGuiDesignerPreviewPointerArbiter()
        selection_host = DearPyGuiDesignerPreviewSelectionHost(pointer_arbiter=arbiter)
        resize_host = DearPyGuiDesignerPreviewResizeHost(pointer_arbiter=arbiter)
        selection_host._dpg = lambda: dpg
        resize_host._dpg = lambda: dpg

        selected = []
        selection_host.build(
            (
                DesignerPreviewSelectionTarget(
                    "root", _NativePreviewComponent(root_item), 0, False, False
                ),
                DesignerPreviewSelectionTarget(
                    "action", _NativePreviewComponent(first_item), 1, True, True
                ),
                DesignerPreviewSelectionTarget(
                    "secondary", _NativePreviewComponent(second_item), 1, False, False
                ),
            ),
            parent="preview",
            on_select=selected.append,
        )
        resized = []
        binding = resize_host.build(
            DesignerPreviewResizeTarget(
                "action", _NativePreviewComponent(first_item), 120, 28, True, True
            ),
            parent="preview",
            on_resize=lambda node_id, width, height: resized.append(
                (node_id, width, height)
            ) or True,
        )
        bounds = binding.metadata["handle_bounds"]
        self.assertIsNotNone(bounds)
        left, top, right, bottom = bounds
        self.assertGreaterEqual(left, 0.0)
        self.assertGreaterEqual(top, 0.0)
        self.assertLessEqual(right, 120.0)
        self.assertLessEqual(bottom, 28.0)

        dpg.mouse = ((left + right) / 2.0, (top + bottom) / 2.0)
        dpg.hovered = {root_item, first_item}
        # Exercise the worst callback ordering: selection runs before resize.
        dpg.mouse_down[0]()
        dpg.mouse_down[1]()
        self.assertEqual([], selected)
        self.assertEqual("action", arbiter.resize_node_id)

        dpg.mouse = (170.0, 60.0)
        for callback in dpg.mouse_move:
            callback()
        for callback in dpg.mouse_release:
            callback()
        self.assertFalse(arbiter.resizing)
        self.assertEqual("action", resized[-1][0])
        self.assertEqual([], selected)

    def test_dpg_selection_and_resize_hosts_share_pointer_arbitration(self):
        selection = (
            PROJECT_ROOT
            / "app"
            / "engine"
            / "designer_preview_selection_hosts"
            / "dearpygui.py"
        ).read_text(encoding="utf-8")
        example = (PROJECT_ROOT / "examples" / "ecosystem_designer_shell.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("pointer_arbiter.blocks_selection", selection)
        self.assertIn("add_mouse_down_handler", selection)
        self.assertNotIn("add_mouse_click_handler", selection)
        self.assertIn("DearPyGuiDesignerPreviewPointerArbiter", example)
        self.assertIn("pointer_arbiter=preview_pointer_arbiter", example)

    def test_dpg_resize_drag_respects_shift_and_ctrl_sensitivity(self):
        dpg = _FakeDearPyGui()
        item = 2
        dpg.rects[item] = ((0.0, 0.0), (120.0, 28.0))
        host = DearPyGuiDesignerPreviewResizeHost()
        host._dpg = lambda: dpg
        resized = []
        binding = host.build(
            DesignerPreviewResizeTarget(
                "action", _NativePreviewComponent(item), 120, 28, True, True
            ),
            parent="preview",
            on_resize=lambda node_id, width, height: resized.append((node_id, width, height)) or True,
        )
        left, top, right, bottom = binding.metadata["handle_bounds"]
        dpg.mouse = ((left + right) / 2.0, (top + bottom) / 2.0)
        dpg.mouse_down[0]()
        dpg.keys_down = {dpg.mvKey_LShift}
        dpg.mouse = (dpg.mouse[0] + 2.0, dpg.mouse[1] + 1.0)
        dpg.mouse_move[0]()
        self.assertEqual((140.0, 38.0), (dpg.rects[item][1][0], dpg.rects[item][1][1]))
        dpg.keys_down.clear()
        dpg.mouse_release[0]()
        self.assertEqual(("action", 140, 38), resized[-1])

        # A fresh drag with Ctrl translates ten pointer pixels into one pixel.
        dpg.rects[item] = ((0.0, 0.0), (120.0, 28.0))
        host.update(binding, DesignerPreviewResizeTarget(
            "action", _NativePreviewComponent(item), 120, 28, True, True
        ))
        left, top, right, bottom = binding.metadata["handle_bounds"]
        dpg.mouse = ((left + right) / 2.0, (top + bottom) / 2.0)
        dpg.mouse_down[0]()
        dpg.keys_down = {dpg.mvKey_LControl}
        dpg.mouse = (dpg.mouse[0] + 10.0, dpg.mouse[1])
        dpg.mouse_move[0]()
        self.assertEqual(121.0, dpg.rects[item][1][0])

    def test_concrete_hosts_keep_pointer_mechanics_outside_framework(self):
        dpg = (
            PROJECT_ROOT / "app" / "engine" / "designer_preview_resize_hosts" / "dearpygui.py"
        ).read_text(encoding="utf-8")
        tkinter = (
            PROJECT_ROOT / "app" / "engine" / "designer_preview_resize_hosts" / "tkinter.py"
        ).read_text(encoding="utf-8")
        self.assertIn("add_mouse_down_handler", dpg)
        self.assertIn("add_mouse_move_handler", dpg)
        self.assertIn("add_mouse_release_handler", dpg)
        self.assertIn("draw_rectangle", dpg)
        self.assertIn("tk.Frame", tkinter)
        self.assertNotIn("ttk.Sizegrip(", tkinter)
        self.assertIn('"<B1-Motion>"', tkinter)
        self.assertNotIn("SetDesignerProperty", dpg)
        self.assertNotIn("SetDesignerProperty", tkinter)


if __name__ == "__main__":
    unittest.main(verbosity=2)
