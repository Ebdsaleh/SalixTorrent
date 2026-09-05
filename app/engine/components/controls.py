"""Reusable primitive GUI controls."""

from __future__ import annotations

from enum import Enum

from app.engine.components.base import Component, ValueComponent
from app.engine.components.layout import ControlLayout, ControlLayoutTheme
from app.engine.components.renderer import ComponentRenderer, get_default_renderer
from app.engine.property_cascade import UNSET


class NumericKind(str, Enum):
    INTEGER = "integer"
    FLOAT = "float"


class Label(Component):
    def __init__(
        self,
        text: str,
        *,
        color=None,
        wrap: int | None = None,
        bullet: bool = False,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
    ):
        super().__init__(theme=theme, layout=layout)
        self.text = str(text)
        self.color = color
        self.wrap = wrap
        self.bullet = bool(bullet)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout()
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(text=self.text, color=self.color, wrap=self.wrap, bullet=self.bullet)
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("label", **kwargs))

    def set_text(self, text: str) -> None:
        self.text = str(text)
        renderer = self._renderer or get_default_renderer()
        renderer.set_value(self.require_item(), self.text)


class Button(Component):
    def __init__(
        self,
        label: str,
        *,
        callback=None,
        user_data=None,
        enabled: bool = True,
        show: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
    ):
        super().__init__(theme=theme, layout=layout)
        self.label = str(label)
        self.callback = callback
        self.user_data = user_data
        self.enabled = bool(enabled)
        self.show = bool(show)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout()
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            label=self.label,
            callback=self.callback,
            user_data=self.user_data,
            enabled=self.enabled,
            show=self.show,
        )
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("button", **kwargs))


class ComboBox(ValueComponent):
    def __init__(
        self,
        items,
        *,
        default_value=None,
        callback=None,
        user_data=None,
        enabled: bool = True,
        show: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
    ):
        super().__init__(theme=theme, layout=layout)
        self.items = tuple(items)
        self.default_value = default_value
        self.callback = callback
        self.user_data = user_data
        self.enabled = bool(enabled)
        self.show = bool(show)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout()
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            items=list(self.items),
            default_value=self.default_value,
            callback=self.callback,
            user_data=self.user_data,
            enabled=self.enabled,
            show=self.show,
        )
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("combo_box", **kwargs))

    def set_items(self, items) -> None:
        self.items = tuple(items)
        self.configure(items=list(self.items))


class NumericStepper(ValueComponent):
    """Validated integer/float input with backend-native step buttons."""

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
        user_data=None,
        enabled: bool = True,
        show: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
    ):
        super().__init__(theme=theme, layout=layout)
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
        self.user_data = user_data
        self.enabled = bool(enabled)
        self.show = bool(show)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout()
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            default_value=self.default_value,
            min_value=self.min_value,
            max_value=self.max_value,
            min_clamped=self.min_clamped,
            max_clamped=self.max_clamped,
            format=self.format,
            callback=self.callback,
            user_data=self.user_data,
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


class CheckBox(ValueComponent):
    def __init__(
        self,
        label: str,
        *,
        default_value: bool = False,
        callback=None,
        user_data=None,
        enabled: bool = True,
        show: bool = True,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
    ):
        super().__init__(theme=theme, layout=layout)
        self.label = str(label)
        self.default_value = bool(default_value)
        self.callback = callback
        self.user_data = user_data
        self.enabled = bool(enabled)
        self.show = bool(show)

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout()
        kwargs = self._layout_kwargs(resolved)
        kwargs.update(
            label=self.label,
            default_value=self.default_value,
            callback=self.callback,
            user_data=self.user_data,
            enabled=self.enabled,
            show=self.show,
        )
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("checkbox", **kwargs))


class Spacer(Component):
    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        resolved = self._resolve_layout()
        kwargs = self._layout_kwargs(resolved)
        self._with_parent(kwargs, parent)
        return self._bind(renderer, renderer.create("spacer", **kwargs))
