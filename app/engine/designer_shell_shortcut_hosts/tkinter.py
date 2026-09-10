"""Tkinter host for backend-neutral designer-shell keyboard shortcuts."""

from __future__ import annotations

from app.framework.designer_shell_shortcuts import DesignerShellShortcutBinding


class TkinterDesignerShellShortcutHost:
    _SEQUENCES = {
        "Ctrl+D": "<Control-d>",
        "Ctrl+Delete": "<Control-Delete>",
        "Alt+Up": "<Alt-Up>",
        "Alt+Down": "<Alt-Down>",
    }

    def __init__(self, root):
        if root is None:
            raise ValueError("TkinterDesignerShellShortcutHost requires a Tk root")
        self.root = root

    def build(self, shortcuts, *, on_gesture):
        registrations = []
        for spec in shortcuts:
            try:
                sequence = self._SEQUENCES[spec.gesture]
            except KeyError as exc:
                raise ValueError(f"Tkinter designer shortcut is unsupported: {spec.gesture}") from exc

            def callback(_event=None, gesture=spec.gesture):
                result = on_gesture(gesture)
                return "break" if result is not False else None

            funcid = self.root.bind(sequence, callback, add="+")
            registrations.append((sequence, funcid, callback))
        return DesignerShellShortcutBinding(
            handle=self.root,
            gestures=tuple(spec.gesture for spec in shortcuts),
            metadata={"registrations": registrations},
        )

    def exists(self, binding: DesignerShellShortcutBinding) -> bool:
        try:
            return bool(int(self.root.winfo_exists()))
        except Exception:
            return False

    def dispose(self, binding: DesignerShellShortcutBinding) -> None:
        metadata = binding.metadata if isinstance(binding.metadata, dict) else {}
        for sequence, funcid, _callback in metadata.get("registrations", ()):
            try:
                self.root.unbind(sequence, funcid)
            except Exception:
                pass
        metadata["registrations"] = []


__all__ = ["TkinterDesignerShellShortcutHost"]
