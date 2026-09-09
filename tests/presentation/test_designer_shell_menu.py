from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT

from app.framework.command_menu import CommandMenuBinding
from app.framework.components import Button, ControlColumn, Label
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_editing import DESIGNER_UNDO_COMMAND
from app.framework.designer_shell import (
    DESIGNER_COPY_COMMAND,
    DESIGNER_DUPLICATE_COMMAND,
    DESIGNER_NEW_PROJECT_COMMAND,
    DESIGNER_PASTE_COMMAND,
    DesignerShellCommandRequest,
    DesignerShellCommands,
    DesignerShellRequestKind,
)
from app.framework.designer_shell_menu import DesignerShellMenu
from app.framework.designer_workspace import DesignerWorkspace


class FakeMenuHost:
    def __init__(self):
        self.binding = None
        self.callback = None
        self.built = []
        self.updated = []
        self.shown = 0
        self.hidden = 0
        self.disposed = 0

    def build(self, commands, *, title="", on_command=None):
        self.callback = on_command
        self.built.append(commands)
        self.binding = CommandMenuBinding(
            menu={"alive": True, "title": str(title)},
            items={},
        )
        return self.binding

    def update(self, binding, commands):
        self.updated.append(commands)

    def show(self, binding):
        self.shown += 1

    def hide(self, binding):
        self.hidden += 1

    def exists(self, binding):
        return bool(binding.menu["alive"])

    def dispose(self, binding):
        binding.menu["alive"] = False
        self.disposed += 1


class DesignerShellMenuTests(unittest.TestCase):
    def _snapshot(self):
        root = ControlColumn((
            Label("Project"),
            ControlColumn((Button("Run"), Button("Stop"))),
        ))
        identities = DesignerIdentityMap(prefix="surface")
        identities.bind(root, "surface-root")
        return capture_component_tree(root, identities=identities)

    @staticmethod
    def _node(workspace, label):
        return next(
            node
            for node in workspace.session.snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == label
        )

    def test_requires_semantic_shell_and_valid_command_menu_host(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        with self.assertRaisesRegex(TypeError, "DesignerShellCommands"):
            DesignerShellMenu(object(), FakeMenuHost())
        with self.assertRaisesRegex(TypeError, "CommandMenuHost"):
            DesignerShellMenu(DesignerShellCommands(workspace), object())
        workspace.close()

    def test_build_uses_current_shell_command_tree_and_title(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        host = FakeMenuHost()
        presenter = DesignerShellMenu(
            DesignerShellCommands(workspace), host, title="Editor"
        )
        binding = presenter.build()
        self.assertTrue(presenter.exists())
        self.assertEqual("Editor", binding.menu["title"])
        self.assertEqual(("File", "Edit", "Navigate"), tuple(
            command.label for command in host.built[-1].commands
        ))
        presenter.dispose()
        workspace.close()

    def test_show_refreshes_enablement_from_live_workspace_state(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        host = FakeMenuHost()
        shell = DesignerShellCommands(workspace)
        presenter = DesignerShellMenu(shell, host)
        presenter.build()
        self.assertFalse(shell.command(DESIGNER_COPY_COMMAND).enabled)
        run = self._node(workspace, "Run")
        workspace.select_and_focus_node(run.node_id)
        presenter.show()
        self.assertEqual(1, host.shown)
        self.assertTrue(host.updated[-1].get(DESIGNER_COPY_COMMAND).enabled)
        presenter.dispose()
        workspace.close()

    def test_dispatch_revalidates_against_current_semantic_state(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        host = FakeMenuHost()
        presenter = DesignerShellMenu(DesignerShellCommands(workspace), host)
        presenter.build()
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            host.callback(DESIGNER_COPY_COMMAND)
        run = self._node(workspace, "Run")
        workspace.select_and_focus_node(run.node_id)
        presenter.refresh()
        payload = host.callback(DESIGNER_COPY_COMMAND)
        self.assertEqual(run.node_id, payload.root.node_id)
        presenter.dispose()
        workspace.close()

    def test_request_actions_are_forwarded_without_guessing_shell_policy(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        host = FakeMenuHost()
        seen = []
        presenter = DesignerShellMenu(
            DesignerShellCommands(workspace),
            host,
            on_request=lambda request: seen.append(request) or "handled",
        )
        presenter.build()
        result = host.callback(DESIGNER_NEW_PROJECT_COMMAND)
        self.assertEqual("handled", result)
        self.assertEqual(DesignerShellRequestKind.NEW_PROJECT, seen[-1].kind)
        presenter.dispose()
        workspace.close()

    def test_unhandled_request_is_returned_to_the_concrete_shell(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        host = FakeMenuHost()
        presenter = DesignerShellMenu(DesignerShellCommands(workspace), host)
        presenter.build()
        request = host.callback(DESIGNER_NEW_PROJECT_COMMAND)
        self.assertIsInstance(request, DesignerShellCommandRequest)
        self.assertEqual(DesignerShellRequestKind.NEW_PROJECT, request.kind)
        presenter.dispose()
        workspace.close()

    def test_result_callback_observes_completed_semantic_dispatch(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, "Run")
        workspace.select_and_focus_node(run.node_id)
        host = FakeMenuHost()
        seen = []
        presenter = DesignerShellMenu(
            DesignerShellCommands(workspace),
            host,
            on_result=lambda key, result: seen.append((key, result)),
        )
        presenter.build()
        payload = host.callback(DESIGNER_COPY_COMMAND)
        self.assertEqual((DESIGNER_COPY_COMMAND, payload), seen[-1])
        presenter.dispose()
        workspace.close()

    def test_copy_refresh_enables_paste_without_preview_rebuild(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, "Run")
        workspace.select_and_focus_node(run.node_id)
        generation = workspace.state.preview_generation
        host = FakeMenuHost()
        shell = DesignerShellCommands(workspace)
        presenter = DesignerShellMenu(shell, host)
        presenter.build()
        self.assertFalse(shell.command(DESIGNER_PASTE_COMMAND).enabled)
        host.callback(DESIGNER_COPY_COMMAND)
        self.assertEqual(generation, workspace.state.preview_generation)
        self.assertTrue(host.updated[-1].get(DESIGNER_PASTE_COMMAND).enabled)
        presenter.dispose()
        workspace.close()

    def test_duplicate_and_undo_refresh_dynamic_history_labels(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        run = self._node(workspace, "Run")
        workspace.select_and_focus_node(run.node_id)
        host = FakeMenuHost()
        presenter = DesignerShellMenu(DesignerShellCommands(workspace), host)
        presenter.build()
        self.assertTrue(host.callback(DESIGNER_DUPLICATE_COMMAND))
        undo = host.updated[-1].get(DESIGNER_UNDO_COMMAND)
        self.assertTrue(undo.enabled)
        self.assertTrue(undo.label.startswith("Undo "))
        self.assertTrue(host.callback(DESIGNER_UNDO_COMMAND))
        presenter.dispose()
        workspace.close()

    def test_hide_dispose_and_dead_binding_lifecycle_are_explicit(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        host = FakeMenuHost()
        presenter = DesignerShellMenu(DesignerShellCommands(workspace), host)
        presenter.build()
        presenter.hide()
        self.assertEqual(1, host.hidden)
        host.binding.menu["alive"] = False
        presenter.refresh()
        self.assertEqual(2, len(host.built))
        self.assertTrue(presenter.dispose())
        self.assertEqual(1, host.disposed)
        workspace.close()

    def test_callback_contracts_are_validated(self):
        workspace = DesignerWorkspace.create(self._snapshot())
        shell = DesignerShellCommands(workspace)
        with self.assertRaisesRegex(TypeError, "request handler"):
            DesignerShellMenu(shell, FakeMenuHost(), on_request=object())
        with self.assertRaisesRegex(TypeError, "result handler"):
            DesignerShellMenu(shell, FakeMenuHost(), on_result=object())
        workspace.close()

    def test_framework_surface_bridge_keeps_product_and_toolkits_out(self):
        path = PROJECT_ROOT / "app" / "framework" / "designer_shell_menu.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        forbidden = ("dearpygui", "tkinter", "app.views", "app.logic", "app.localization")
        self.assertFalse(any(name.startswith(forbidden) for name in imports))


if __name__ == "__main__":
    unittest.main(verbosity=2)
