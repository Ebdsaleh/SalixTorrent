from __future__ import annotations

import ast
import json
import unittest

from tests.helpers import PROJECT_ROOT

from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_shell import (
    DESIGNER_DUPLICATE_COMMAND,
    DESIGNER_MOVE_DOWN_COMMAND,
    DESIGNER_MOVE_UP_COMMAND,
    DESIGNER_REMOVE_COMMAND,
    DesignerShellCommands,
)
from app.framework.designer_shell_shortcuts import (
    DEFAULT_DESIGNER_SHELL_SHORTCUTS,
    DesignerShellShortcutBinding,
    DesignerShellShortcutSpec,
    DesignerShellShortcuts,
)
from app.framework.designer_workspace import DesignerWorkspace


class FakeShortcutHost:
    def __init__(self):
        self.binding = None
        self.callback = None
        self.build_count = 0
        self.dispose_count = 0

    def build(self, shortcuts, *, on_gesture):
        self.callback = on_gesture
        self.build_count += 1
        self.binding = DesignerShellShortcutBinding(
            handle={"alive": True},
            gestures=tuple(spec.gesture for spec in shortcuts),
        )
        return self.binding

    def exists(self, binding):
        return bool(binding.handle["alive"])

    def dispose(self, binding):
        binding.handle["alive"] = False
        self.dispose_count += 1


class DesignerShellShortcutTests(unittest.TestCase):
    def _snapshot(self):
        inner = ControlColumn((Button("One"), Button("Two"), Button("Three")))
        root = ControlColumn((Label("Title"), inner))
        ids = DesignerIdentityMap(prefix="shortcut")
        ids.bind(root, "root")
        ids.bind(inner, "actions")
        ids.bind(inner.children[0], "one")
        ids.bind(inner.children[1], "two")
        ids.bind(inner.children[2], "three")
        return capture_component_tree(root, identities=ids)

    def _workspace(self):
        return DesignerWorkspace.create(self._snapshot())

    def test_structural_command_availability_tracks_sibling_boundaries(self):
        workspace = self._workspace()
        shell = DesignerShellCommands(workspace)
        workspace.select_and_focus_node("one")
        self.assertTrue(shell.command(DESIGNER_REMOVE_COMMAND).enabled)
        self.assertFalse(shell.command(DESIGNER_MOVE_UP_COMMAND).enabled)
        self.assertTrue(shell.command(DESIGNER_MOVE_DOWN_COMMAND).enabled)
        workspace.select_and_focus_node("three")
        self.assertTrue(shell.command(DESIGNER_MOVE_UP_COMMAND).enabled)
        self.assertFalse(shell.command(DESIGNER_MOVE_DOWN_COMMAND).enabled)
        workspace.select_and_focus_node("root")
        self.assertFalse(shell.command(DESIGNER_REMOVE_COMMAND).enabled)
        self.assertFalse(shell.command(DESIGNER_MOVE_UP_COMMAND).enabled)
        self.assertFalse(shell.command(DESIGNER_MOVE_DOWN_COMMAND).enabled)
        workspace.close()

    def test_move_down_dispatch_reorders_one_sibling_and_preserves_selection(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("one")
        shell = DesignerShellCommands(workspace)
        generation = workspace.state.preview_generation
        self.assertTrue(shell.dispatch(DESIGNER_MOVE_DOWN_COMMAND))
        self.assertEqual(("two", "one", "three"), tuple(child.node.node_id for child in workspace.session.node("actions").children))
        self.assertEqual("one", workspace.state.selected_id)
        self.assertEqual(generation + 1, workspace.state.preview_generation)
        self.assertTrue(workspace.state.can_undo)
        workspace.close()

    def test_move_up_dispatch_reorders_one_sibling_and_undo_restores(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("three")
        shell = DesignerShellCommands(workspace)
        self.assertTrue(shell.dispatch(DESIGNER_MOVE_UP_COMMAND))
        self.assertEqual(("one", "three", "two"), tuple(child.node.node_id for child in workspace.session.node("actions").children))
        self.assertTrue(workspace.undo())
        self.assertEqual(("one", "two", "three"), tuple(child.node.node_id for child in workspace.session.node("actions").children))
        workspace.close()

    def test_remove_dispatch_deletes_subtree_and_falls_back_to_parent_selection(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("two")
        shell = DesignerShellCommands(workspace)
        self.assertTrue(shell.dispatch(DESIGNER_REMOVE_COMMAND))
        self.assertEqual(("one", "three"), tuple(child.node.node_id for child in workspace.session.node("actions").children))
        self.assertEqual("actions", workspace.state.selected_id)
        with self.assertRaises(KeyError):
            workspace.session.node("two")
        self.assertTrue(workspace.undo())
        self.assertEqual(("one", "two", "three"), tuple(child.node.node_id for child in workspace.session.node("actions").children))
        workspace.close()

    def test_disabled_structural_dispatch_is_rejected_without_mutation(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("one")
        shell = DesignerShellCommands(workspace)
        before = workspace.session.snapshot
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            shell.dispatch(DESIGNER_MOVE_UP_COMMAND)
        self.assertEqual(before, workspace.session.snapshot)
        workspace.close()

    def test_workspace_selected_helpers_are_checked_and_boundary_safe(self):
        workspace = self._workspace()
        with self.assertRaisesRegex(RuntimeError, "no selected node"):
            workspace.remove_selected()
        workspace.select_and_focus_node("one")
        self.assertFalse(workspace.move_selected_up())
        workspace.select_and_focus_node("three")
        self.assertFalse(workspace.move_selected_down())
        workspace.close()

    def test_shortcut_spec_normalizes_gesture_and_descriptor(self):
        spec = DesignerShellShortcutSpec("control-delete", DESIGNER_REMOVE_COMMAND, "Remove")
        self.assertEqual("Ctrl+Delete", spec.gesture)
        json.dumps(spec.to_descriptor(), allow_nan=False, sort_keys=True)
        with self.assertRaisesRegex(ValueError, "exactly one key"):
            DesignerShellShortcutSpec("Ctrl+Alt", DESIGNER_REMOVE_COMMAND)

    def test_default_shortcuts_cover_duplicate_remove_and_sibling_moves(self):
        mapping = {spec.gesture: spec.command_key for spec in DEFAULT_DESIGNER_SHELL_SHORTCUTS}
        self.assertEqual(DESIGNER_DUPLICATE_COMMAND, mapping["Ctrl+D"])
        self.assertEqual(DESIGNER_REMOVE_COMMAND, mapping["Ctrl+Delete"])
        self.assertEqual(DESIGNER_MOVE_UP_COMMAND, mapping["Alt+Up"])
        self.assertEqual(DESIGNER_MOVE_DOWN_COMMAND, mapping["Alt+Down"])

    def test_shortcut_surface_requires_semantic_shell_valid_host_and_specs(self):
        workspace = self._workspace()
        shell = DesignerShellCommands(workspace)
        with self.assertRaisesRegex(TypeError, "DesignerShellCommands"):
            DesignerShellShortcuts(object(), FakeShortcutHost())
        with self.assertRaisesRegex(TypeError, "host is missing"):
            DesignerShellShortcuts(shell, object())
        with self.assertRaisesRegex(TypeError, "DesignerShellShortcutSpec"):
            DesignerShellShortcuts(shell, FakeShortcutHost(), shortcuts=(object(),))
        with self.assertRaisesRegex(ValueError, "unique"):
            DesignerShellShortcuts(
                shell,
                FakeShortcutHost(),
                shortcuts=(
                    DesignerShellShortcutSpec("Ctrl+D", DESIGNER_DUPLICATE_COMMAND),
                    DesignerShellShortcutSpec("Ctrl+D", DESIGNER_REMOVE_COMMAND),
                ),
            )
        workspace.close()

    def test_build_exists_and_dispose_lifecycle_are_explicit(self):
        workspace = self._workspace()
        host = FakeShortcutHost()
        surface = DesignerShellShortcuts(DesignerShellCommands(workspace), host)
        binding = surface.build()
        self.assertTrue(surface.exists())
        self.assertEqual(tuple(spec.gesture for spec in DEFAULT_DESIGNER_SHELL_SHORTCUTS), binding.gestures)
        self.assertIs(binding, surface.build())
        self.assertEqual(1, host.build_count)
        self.assertTrue(surface.dispose())
        self.assertFalse(surface.exists())
        self.assertFalse(surface.dispose())
        self.assertEqual(1, host.dispose_count)
        workspace.close()

    def test_disabled_shortcut_is_inert_instead_of_raising_command_error(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("one")
        surface = DesignerShellShortcuts(DesignerShellCommands(workspace), FakeShortcutHost())
        before = workspace.session.snapshot
        self.assertFalse(surface.dispatch_gesture("Alt+Up"))
        self.assertEqual(before, workspace.session.snapshot)
        workspace.close()

    def test_shortcuts_dispatch_duplicate_move_and_remove_through_shell(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("two")
        host = FakeShortcutHost()
        surface = DesignerShellShortcuts(DesignerShellCommands(workspace), host)
        surface.build()
        self.assertTrue(host.callback("Alt+Up"))
        self.assertEqual(("two", "one", "three"), tuple(child.node.node_id for child in workspace.session.node("actions").children))
        self.assertTrue(host.callback("Ctrl+D"))
        clone_id = "two-copy"
        self.assertIsNotNone(workspace.session.node(clone_id))
        workspace.select_and_focus_node(clone_id)
        self.assertTrue(host.callback("Ctrl+Delete"))
        with self.assertRaises(KeyError):
            workspace.session.node(clone_id)
        surface.dispose()
        workspace.close()

    def test_result_callback_observes_completed_structural_shortcut(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("two")
        seen = []
        surface = DesignerShellShortcuts(
            DesignerShellCommands(workspace),
            FakeShortcutHost(),
            on_result=lambda key, result: seen.append((key, result)),
        )
        self.assertTrue(surface.dispatch_gesture("Alt+Down"))
        self.assertEqual((DESIGNER_MOVE_DOWN_COMMAND, True), seen[-1])
        workspace.close()

    def test_unknown_gesture_is_rejected_without_semantic_mutation(self):
        workspace = self._workspace()
        workspace.select_and_focus_node("two")
        surface = DesignerShellShortcuts(DesignerShellCommands(workspace), FakeShortcutHost())
        before = workspace.session.snapshot
        with self.assertRaisesRegex(KeyError, "not bound"):
            surface.dispatch_gesture("Ctrl+X")
        self.assertEqual(before, workspace.session.snapshot)
        workspace.close()

    def test_descriptor_is_json_safe(self):
        workspace = self._workspace()
        surface = DesignerShellShortcuts(DesignerShellCommands(workspace), FakeShortcutHost())
        json.dumps(surface.to_descriptor(), allow_nan=False, sort_keys=True)
        workspace.close()

    def test_framework_shortcut_surface_keeps_toolkits_and_product_layers_out(self):
        path = PROJECT_ROOT / "app" / "framework" / "designer_shell_shortcuts.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        forbidden = ("dearpygui", "tkinter", "app.views", "app.logic", "app.localization")
        self.assertFalse(any(name.startswith(forbidden) for name in imports))

        # The designer-shell proof must allocate Components / Placement /
        # Hierarchy as real vertical split panes. A plain Dear PyGui group is a
        # flow container and does not provide the clipping/sizing semantics
        # required for three independently scrollable editor regions.
        example = (PROJECT_ROOT / "examples" / "ecosystem_designer_shell.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("orientation=SplitOrientation.VERTICAL", example)
        self.assertIn('"components",', example)
        self.assertIn('"placement",', example)
        self.assertIn('"hierarchy",', example)

        # DPG places native item labels after their widgets and some Windows
        # builds allow width=-1 table-cell editors to overrun the bounded
        # sidebar cell.  The placement host must use explicit horizontal rows
        # with a conservative fixed editor width and separate left captions.
        placement_host = (
            PROJECT_ROOT
            / "app"
            / "engine"
            / "designer_component_placement_hosts"
            / "dearpygui.py"
        ).read_text(encoding="utf-8")
        self.assertIn("horizontal_spacing=8", placement_host)
        self.assertIn("editor_width: int = 150", placement_host)
        self.assertIn('dpg.add_text(f"{caption:<13}")', placement_host)
        self.assertNotIn("width=-1", placement_host)
        self.assertNotIn("with dpg.table(", placement_host)
        for field_label in ("Parent", "Slot", "Index", "Metadata JSON"):
            self.assertIn(f'            "{field_label}",', placement_host)
            self.assertNotIn(f'label="{field_label}"', placement_host)


if __name__ == "__main__":
    unittest.main(verbosity=2)
