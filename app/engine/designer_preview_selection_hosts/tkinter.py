"""Tkinter host for clickable designer preview selection and highlighting."""

from __future__ import annotations

from collections.abc import Callable

from app.framework.designer_preview_selection import (
    DesignerPreviewSelectionBinding,
    DesignerPreviewSelectionTarget,
)


class TkinterDesignerPreviewSelectionHost:
    """Bind clicks to rendered Tk widgets and outline the selected mount frame."""

    def __init__(self, renderer):
        if renderer is None or not callable(getattr(renderer, "native_widget", None)):
            raise TypeError(
                "Tkinter designer preview-selection host requires a Tkinter renderer"
            )
        self._renderer = renderer

    def _target_item(self, target: DesignerPreviewSelectionTarget):
        try:
            return target.component.require_item()
        except RuntimeError:
            return None

    def _widgets(self, item: object) -> tuple[object, ...]:
        if item is None:
            return ()
        widget = self._renderer.native_widget(item)
        mount = getattr(item, "mount", None)
        result = []
        for candidate in (widget, mount):
            if candidate is not None and candidate not in result:
                result.append(candidate)
        return tuple(result)

    @staticmethod
    def _widget_exists(widget: object) -> bool:
        try:
            return bool(int(widget.winfo_exists()))
        except Exception:
            return False

    def _clear_bindings(self, metadata: dict) -> None:
        for widget, bind_id in metadata.get("click_bindings", ()):
            try:
                if bind_id and self._widget_exists(widget):
                    widget.unbind("<Button-1>", bind_id)
            except Exception:
                pass
        metadata["click_bindings"] = []

    def _clear_highlight(self, metadata: dict) -> None:
        for widget, thickness, background, colour in metadata.get("highlights", ()):
            try:
                if self._widget_exists(widget):
                    widget.configure(
                        highlightthickness=thickness,
                        highlightbackground=background,
                        highlightcolor=colour,
                    )
            except Exception:
                pass
        metadata["highlights"] = []

    def _bind_targets(
        self,
        binding: DesignerPreviewSelectionBinding,
        targets: tuple[DesignerPreviewSelectionTarget, ...],
    ) -> None:
        metadata = binding.metadata
        assert isinstance(metadata, dict)
        self._clear_bindings(metadata)
        self._clear_highlight(metadata)
        binding.targets.clear()
        on_select = metadata["on_select"]

        selected_item = None
        for target in targets:
            item = self._target_item(target)
            binding.targets[target.node_id] = item
            if target.selected:
                selected_item = item
            for widget in self._widgets(item):
                if not self._widget_exists(widget):
                    continue

                def clicked(_event=None, node_id=target.node_id):
                    return on_select(node_id)

                try:
                    bind_id = widget.bind("<Button-1>", clicked, add="+")
                except Exception:
                    continue
                metadata["click_bindings"].append((widget, bind_id))

        if selected_item is None:
            return
        mount = getattr(selected_item, "mount", None)
        if mount is None:
            mount = self._renderer.native_widget(selected_item)
        if not self._widget_exists(mount):
            return
        try:
            old = (
                mount,
                mount.cget("highlightthickness"),
                mount.cget("highlightbackground"),
                mount.cget("highlightcolor"),
            )
            metadata["highlights"].append(old)
            mount.configure(
                highlightthickness=2,
                highlightbackground="#2f8ed8",
                highlightcolor="#2f8ed8",
            )
        except Exception:
            metadata["highlights"] = []

    def build(
        self,
        targets: tuple[DesignerPreviewSelectionTarget, ...],
        *,
        parent: object,
        on_select: Callable[[str], object],
    ) -> DesignerPreviewSelectionBinding:
        if not callable(on_select):
            raise TypeError("designer preview-selection on_select callback must be callable")
        metadata = {
            "on_select": on_select,
            "click_bindings": [],
            "highlights": [],
        }
        binding = DesignerPreviewSelectionBinding(parent, {}, metadata)
        self._bind_targets(binding, targets)
        return binding

    def update(
        self,
        binding: DesignerPreviewSelectionBinding,
        targets: tuple[DesignerPreviewSelectionTarget, ...],
    ) -> None:
        if not self.exists(binding):
            raise RuntimeError("Tkinter designer preview-selection binding is stale")
        self._bind_targets(binding, targets)

    def exists(self, binding: DesignerPreviewSelectionBinding) -> bool:
        if not isinstance(binding, DesignerPreviewSelectionBinding):
            return False
        try:
            if self._renderer.exists(binding.surface):
                return True
        except Exception:
            pass
        widget = self._renderer.native_widget(binding.surface)
        return self._widget_exists(widget)

    def dispose(self, binding: DesignerPreviewSelectionBinding) -> None:
        if not isinstance(binding, DesignerPreviewSelectionBinding):
            return
        metadata = binding.metadata
        if isinstance(metadata, dict):
            self._clear_bindings(metadata)
            self._clear_highlight(metadata)
            metadata.clear()
        binding.targets.clear()
