"""Reusable primitive GUI controls."""

from __future__ import annotations

from enum import Enum

from .base import Component, ValueComponent
from .events import ComponentEventType
from .layout import ControlLayout, ControlLayoutTheme
from .renderer import ComponentRenderer, get_default_renderer
from ..property_cascade import UNSET


class NumericKind(str, Enum):
    INTEGER = "integer"
    FLOAT = "float"


class Label(Component):
    profile_key = "label"

    def __init__(
        self,
        text: str,
        *,
        color=None,
        wrap: int | None = None,
        bullet: bool = False,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.text = str(text)
        self.color = color
        self.wrap = wrap
        self.bullet = bool(bullet)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(text=self.text, color=self.color, wrap=self.wrap, bullet=self.bullet)
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("label", **kwargs))

    def set_text(self, text: str) -> None:
        self.text = str(text)
        renderer = self._renderer or get_default_renderer()
        renderer.set_value(self.require_item(), self.text)


class Button(Component):
    profile_key = "button"

    def __init__(
        self,
        label: str,
        *,
        callback=None,
        event_data=None,
        enabled: bool = True,
        show: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.label = str(label)
        self.callback = callback
        self.event_data = event_data
        self.enabled = bool(enabled)
        self.show = bool(show)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            label=self.label,
            callback=renderer.event_callback(
                self,
                ComponentEventType.ACTIVATE,
                self.callback,
                data=self.event_data,
            ),
            enabled=self.enabled,
            show=self.show,
        )
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("button", **kwargs))


class ComboBox(ValueComponent):
    profile_key = "combo_box"

    def __init__(
        self,
        items,
        *,
        default_value=None,
        callback=None,
        event_data=None,
        enabled: bool = True,
        show: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.items = tuple(items)
        self.default_value = default_value
        self.callback = callback
        self.event_data = event_data
        self.enabled = bool(enabled)
        self.show = bool(show)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            items=list(self.items),
            default_value=self.default_value,
            callback=renderer.event_callback(
                self,
                ComponentEventType.CHANGE,
                self.callback,
                data=self.event_data,
            ),
            enabled=self.enabled,
            show=self.show,
        )
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("combo_box", **kwargs))

    def set_items(self, items) -> None:
        self.items = tuple(items)
        self.configure(items=list(self.items))


class TextInput(ValueComponent):
    profile_key = "text_input"

    def __init__(
        self,
        *,
        label: str | None = None,
        default_value: str = "",
        hint: str | None = None,
        multiline: bool = False,
        readonly: bool = False,
        callback=None,
        event_data=None,
        enabled: bool = True,
        show: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.label = None if label is None else str(label)
        self.default_value = str(default_value)
        self.hint = hint
        self.multiline = bool(multiline)
        self.readonly = bool(readonly)
        self.callback = callback
        self.event_data = event_data
        self.enabled = bool(enabled)
        self.show = bool(show)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            label=self.label,
            default_value=self.default_value,
            hint=self.hint,
            multiline=self.multiline,
            readonly=self.readonly,
            callback=renderer.event_callback(
                self,
                ComponentEventType.CHANGE,
                self.callback,
                data=self.event_data,
            ),
            enabled=self.enabled,
            show=self.show,
        )
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("text_input", **kwargs))


class NumericStepper(ValueComponent):
    """Validated integer/float input with backend-native step buttons."""

    profile_key = "numeric_stepper"

    def __init__(
        self,
        *,
        kind: NumericKind | str = NumericKind.INTEGER,
        default_value=0,
        min_value=None,
        max_value=None,
        min_clamped: bool = False,
        max_clamped: bool = False,
        format: str | None = None,
        step=UNSET,
        step_fast=UNSET,
        callback=None,
        event_data=None,
        enabled: bool = True,
        show: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.kind = NumericKind(str(getattr(kind, "value", kind)).lower())
        self.default_value = default_value
        self.min_value = min_value
        self.max_value = max_value
        self.min_clamped = bool(min_clamped)
        self.max_clamped = bool(max_clamped)
        self.format = format
        self.step = step
        self.step_fast = step_fast
        self.callback = callback
        self.event_data = event_data
        self.enabled = bool(enabled)
        self.show = bool(show)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            default_value=self.default_value,
            min_value=self.min_value,
            max_value=self.max_value,
            min_clamped=self.min_clamped,
            max_clamped=self.max_clamped,
            format=self.format,
            callback=renderer.event_callback(
                self,
                ComponentEventType.CHANGE,
                self.callback,
                data=self.event_data,
            ),
            enabled=self.enabled,
            show=self.show,
        )
        if self.step is not UNSET:
            kwargs["step"] = self.step
        if self.step_fast is not UNSET:
            kwargs["step_fast"] = self.step_fast
        self._with_parent(kwargs, parent)
        kind = "numeric_int" if self.kind is NumericKind.INTEGER else "numeric_float"
        return self._bind(renderer, renderer.create(kind, **kwargs))


class ProgressBar(ValueComponent):
    """Backend-neutral progress indicator with a normalized numeric value."""

    profile_key = "progress_bar"

    def __init__(
        self,
        *,
        default_value: float = 0.0,
        overlay: str | None = None,
        show: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.default_value = float(default_value)
        self.overlay = overlay
        self.show = bool(show)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            default_value=self.default_value,
            overlay=self.overlay,
            show=self.show,
        )
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("progress_bar", **kwargs))

    def set_overlay(self, overlay: str | None) -> None:
        self.overlay = None if overlay is None else str(overlay)
        self.configure(overlay=self.overlay)


class CheckBox(ValueComponent):
    profile_key = "checkbox"

    def __init__(
        self,
        label: str,
        *,
        default_value: bool = False,
        callback=None,
        event_data=None,
        enabled: bool = True,
        show: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.label = str(label)
        self.default_value = bool(default_value)
        self.callback = callback
        self.event_data = event_data
        self.enabled = bool(enabled)
        self.show = bool(show)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            label=self.label,
            default_value=self.default_value,
            callback=renderer.event_callback(
                self,
                ComponentEventType.CHANGE,
                self.callback,
                data=self.event_data,
            ),
            enabled=self.enabled,
            show=self.show,
        )
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("checkbox", **kwargs))


class Separator(Component):
    """Backend-neutral visual separator used by structural composites."""

    profile_key = "separator"

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        self._resolve_layout(renderer=renderer)
        kwargs = {}
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("separator", **kwargs))


class Spacer(Component):
    profile_key = "spacer"
    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout(renderer=renderer)
        kwargs = self._layout_kwargs(resolved)
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("spacer", **kwargs))
