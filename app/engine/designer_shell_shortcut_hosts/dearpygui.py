"""Dear PyGui host for backend-neutral designer-shell keyboard shortcuts."""

from __future__ import annotations

from app.framework.designer_shell_shortcuts import DesignerShellShortcutBinding


class DearPyGuiDesignerShellShortcutHost:
    _KEY_NAMES = {
        "D": "mvKey_D",
        "Delete": "mvKey_Delete",
        "Up": "mvKey_Up",
        "Down": "mvKey_Down",
    }

    @staticmethod
    def _dpg():
        import dearpygui.dearpygui as dpg

        return dpg

    @staticmethod
    def _modifiers(dpg) -> tuple[bool, bool, bool]:
        ctrl = bool(dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl))
        alt = bool(dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt))
        shift = bool(dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift))
        return ctrl, alt, shift

    def build(self, shortcuts, *, on_gesture):
        dpg = self._dpg()
        registry = dpg.add_handler_registry()
        callbacks = []

        def install(spec):
            parts = spec.gesture.split("+")
            key_name = parts[-1]
            attr = self._KEY_NAMES.get(key_name)
            if attr is None or not hasattr(dpg, attr):
                raise ValueError(f"Dear PyGui designer shortcut key is unsupported: {key_name}")
            key = getattr(dpg, attr)
            expect_ctrl = "Ctrl" in parts
            expect_alt = "Alt" in parts
            expect_shift = "Shift" in parts

            def callback(_sender=None, _app_data=None, _user_data=None):
                ctrl, alt, shift = self._modifiers(dpg)
                if (ctrl, alt, shift) == (expect_ctrl, expect_alt, expect_shift):
                    return on_gesture(spec.gesture)
                return False

            callbacks.append(callback)
            dpg.add_key_press_handler(key=key, callback=callback, parent=registry)

        for spec in shortcuts:
            install(spec)
        return DesignerShellShortcutBinding(
            handle=registry,
            gestures=tuple(spec.gesture for spec in shortcuts),
            metadata={"callbacks": callbacks},
        )

    def exists(self, binding: DesignerShellShortcutBinding) -> bool:
        try:
            return bool(self._dpg().does_item_exist(binding.handle))
        except Exception:
            return False

    def dispose(self, binding: DesignerShellShortcutBinding) -> None:
        dpg = self._dpg()
        if dpg.does_item_exist(binding.handle):
            dpg.delete_item(binding.handle)


__all__ = ["DearPyGuiDesignerShellShortcutHost"]
