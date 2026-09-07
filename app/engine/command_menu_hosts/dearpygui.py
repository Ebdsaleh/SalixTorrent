"""Dear PyGui host for renderer-neutral command menus."""

from __future__ import annotations

from app.framework.command_menu import CommandMenuBinding
from app.framework.interactions import CommandSet, CommandSpec


class DearPyGuiCommandMenuHost:
    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

    def _build_nodes(self, commands, items: dict[str, object], on_command) -> None:
        dpg = self._dpg()
        for command in commands:
            if command.children:
                with dpg.menu(label=command.label, enabled=command.enabled) as submenu:
                    items[command.key] = submenu
                    self._build_nodes(command.children, items, on_command)
                continue
            kwargs = {
                "label": command.label,
                "enabled": command.enabled,
                "user_data": command.key,
                "callback": lambda _s, _a, key: on_command(key),
            }
            if command.checked is not None:
                kwargs["check"] = True
                kwargs["default_value"] = bool(command.checked)
            items[command.key] = dpg.add_menu_item(**kwargs)

    def build(self, commands: CommandSet, *, title: str = "", on_command):
        if not isinstance(commands, CommandSet):
            raise TypeError("commands must be a CommandSet")
        dpg = self._dpg()
        items: dict[str, object] = {}
        title_item = None
        with dpg.window(popup=True, show=False, autosize=True, no_title_bar=True) as menu:
            if title:
                title_item = dpg.add_text(str(title))
                dpg.add_separator()
            self._build_nodes(commands.commands, items, on_command)
        return CommandMenuBinding(menu=menu, items=items, title_item=title_item)

    def update(self, binding: CommandMenuBinding, commands: CommandSet) -> None:
        dpg = self._dpg()

        def visit(nodes):
            for command in nodes:
                yield command
                yield from visit(command.children)

        for command in visit(commands.commands):
            item = binding.items.get(command.key)
            if item is None or not dpg.does_item_exist(item):
                continue
            try:
                dpg.configure_item(item, label=command.label, enabled=command.enabled)
                if command.checked is not None and not command.children:
                    dpg.set_value(item, bool(command.checked))
            except Exception:
                continue

    def show(self, binding: CommandMenuBinding) -> None:
        dpg = self._dpg()
        if dpg.does_item_exist(binding.menu):
            dpg.configure_item(binding.menu, show=True)

    def hide(self, binding: CommandMenuBinding) -> None:
        dpg = self._dpg()
        if dpg.does_item_exist(binding.menu):
            dpg.configure_item(binding.menu, show=False)

    def exists(self, binding: CommandMenuBinding) -> bool:
        try:
            return bool(self._dpg().does_item_exist(binding.menu))
        except Exception:
            return False

    def dispose(self, binding: CommandMenuBinding) -> None:
        dpg = self._dpg()
        if dpg.does_item_exist(binding.menu):
            dpg.delete_item(binding.menu)
