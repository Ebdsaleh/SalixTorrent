from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT

from app.framework.command_menu import CommandMenu, CommandMenuBinding
from app.framework.interactions import CommandSet, CommandSpec


class FakeCommandMenuHost:
    def __init__(self):
        self.binding = None
        self.updated = []
        self.shown = 0
        self.hidden = 0
        self.disposed = 0
        self.callback = None

    def build(self, commands, *, title="", on_command):
        self.callback = on_command
        self.binding = CommandMenuBinding(
            menu={"alive": True, "title": title},
            items={command.key: object() for command in commands.commands},
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


class CommandMenuContractTests(unittest.TestCase):
    def test_command_menu_validates_host_contract(self):
        with self.assertRaisesRegex(TypeError, "CommandMenuHost"):
            CommandMenu(object(), on_command=lambda key: key)

    def test_build_update_show_hide_and_dispose_are_explicit(self):
        host = FakeCommandMenuHost()
        seen = []
        menu = CommandMenu(host, title="Actions", on_command=seen.append)
        commands = CommandSet((CommandSpec("run", "Run"),))

        binding = menu.build(commands)
        self.assertTrue(menu.exists())
        self.assertEqual("Actions", binding.menu["title"])
        menu.show()
        menu.hide()
        menu.update(CommandSet((CommandSpec("run", "Run now"),)))
        self.assertEqual((1, 1, 1), (host.shown, host.hidden, len(host.updated)))
        self.assertTrue(menu.dispose())
        self.assertFalse(menu.exists())

    def test_host_callback_dispatches_through_current_command_set(self):
        host = FakeCommandMenuHost()
        seen = []
        menu = CommandMenu(host, on_command=seen.append)
        menu.build(CommandSet((CommandSpec("save", "Save"),)))
        host.callback("save")
        self.assertEqual(["save"], seen)

        menu.update(CommandSet((CommandSpec("save", "Save", enabled=False),)))
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            host.callback("save")
        self.assertEqual(["save"], seen)

    def test_command_menu_framework_and_hosts_keep_product_layers_out(self):
        paths = (
            PROJECT_ROOT / "app" / "framework" / "command_menu.py",
            PROJECT_ROOT / "app" / "engine" / "command_menu_hosts" / "dearpygui.py",
            PROJECT_ROOT / "app" / "engine" / "command_menu_hosts" / "tkinter.py",
        )
        forbidden = ("app.views", "app.logic", "app.localization")
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            self.assertFalse(
                any(module.startswith(forbidden) for module in imports),
                str(path.relative_to(PROJECT_ROOT)),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
