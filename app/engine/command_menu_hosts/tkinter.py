"""Tkinter host for renderer-neutral command menus."""

from __future__ import annotations

from dataclasses import dataclass

from app.framework.command_menu import CommandMenuBinding
from app.framework.interactions import CommandSet


@dataclass(eq=False)
class _TkMenuItem:
    menu: object
    index: int
    variable: object | None = None


class TkinterCommandMenuHost:
    def __init__(self, root):
        if root is None:
            raise ValueError("TkinterCommandMenuHost requires a Tk root")
        self.root = root
        self._callbacks: dict[int, object] = {}
        self._titles: dict[int, str] = {}

    @staticmethod
    def _tk():
        import tkinter as tk

        return tk

    def _populate(self, menu, commands, items: dict[str, object], on_command) -> None:
        tk = self._tk()
        for command in commands:
            if command.children:
                submenu = tk.Menu(menu, tearoff=False)
                menu.add_cascade(
                    label=command.label,
                    menu=submenu,
                    state="normal" if command.enabled else "disabled",
                )
                index = int(menu.index("end"))
                items[command.key] = _TkMenuItem(menu, index)
                self._populate(submenu, command.children, items, on_command)
                continue
            state = "normal" if command.enabled else "disabled"
            if command.checked is not None:
                variable = tk.BooleanVar(master=self.root, value=bool(command.checked))
                menu.add_checkbutton(
                    label=command.label,
                    variable=variable,
                    state=state,
                    command=lambda key=command.key: on_command(key),
                )
            else:
                variable = None
                menu.add_command(
                    label=command.label,
                    state=state,
                    command=lambda key=command.key: on_command(key),
                )
            index = int(menu.index("end"))
            items[command.key] = _TkMenuItem(menu, index, variable)

    def _rebuild(self, binding: CommandMenuBinding, commands: CommandSet) -> None:
        menu = binding.menu
        callback = self._callbacks[id(menu)]
        title = self._titles.get(id(menu), "")
        menu.delete(0, "end")
        items: dict[str, object] = {}
        title_item = None
        if title:
            menu.add_command(label=title, state="disabled")
            title_item = _TkMenuItem(menu, 0)
            menu.add_separator()
        self._populate(menu, commands.commands, items, callback)
        binding.items.clear()
        binding.items.update(items)
        binding.title_item = title_item

    def build(self, commands: CommandSet, *, title: str = "", on_command):
        tk = self._tk()
        menu = tk.Menu(self.root, tearoff=False)
        binding = CommandMenuBinding(menu=menu, items={})
        self._callbacks[id(menu)] = on_command
        self._titles[id(menu)] = str(title)
        self._rebuild(binding, commands)
        return binding

    def update(self, binding: CommandMenuBinding, commands: CommandSet) -> None:
        self._rebuild(binding, commands)

    def show(self, binding: CommandMenuBinding) -> None:
        menu = binding.menu
        try:
            x = int(self.root.winfo_pointerx())
            y = int(self.root.winfo_pointery())
            menu.tk_popup(x, y)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def hide(self, binding: CommandMenuBinding) -> None:
        try:
            binding.menu.unpost()
        except Exception:
            pass

    def exists(self, binding: CommandMenuBinding) -> bool:
        try:
            return bool(int(binding.menu.winfo_exists()))
        except Exception:
            return False

    def dispose(self, binding: CommandMenuBinding) -> None:
        menu = binding.menu
        self._callbacks.pop(id(menu), None)
        self._titles.pop(id(menu), None)
        try:
            menu.destroy()
        except Exception:
            pass
