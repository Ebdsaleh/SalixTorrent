"""Reusable semantic field composites built from GUI primitives."""

from __future__ import annotations

from collections.abc import Iterable

from app.framework.components.base import Component
from app.framework.components.containers import ControlColumn, ControlGrid, ControlRow
from app.framework.components.controls import ComboBox, Label, NumericKind, NumericStepper
from app.framework.components.layout import ControlLayout, ControlLayoutTheme
from app.framework.components.renderer import get_default_renderer


class LabeledField(Component):
    """One-row field composition with an arbitrary trailing accessory set.

    The framework owns only composition.  The primary control and any accessories
    remain normal components, so applications can attach semantics such as Help
    tooltips without teaching this generic layer about application concepts.
    """

    profile_key = "control_row"

    def __init__(
        self,
        label: str | Label,
        control: Component,
        *,
        accessories: Iterable[Component] = (),
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.label = label if isinstance(label, Label) else Label(label)
        self.control = control
        self.accessories = list(accessories)
        self.row = ControlRow(
            (self.label, self.control, *self.accessories),
            theme=self.theme,
            layout=self.layout,
            profile_key=self.profile_key,
        )

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        item = self.row.build(renderer=renderer, parent=parent)
        self.resolved_layout = self.row.resolved_layout
        return self._bind(renderer, item)

    def accessory_items(self) -> tuple[object, ...]:
        return tuple(component.require_item() for component in self.accessories)


class LabeledComboField(LabeledField):
    def __init__(
        self,
        label: str,
        items,
        *,
        default_value=None,
        control_width: int | None = None,
        control_profile_key: str | None = None,
        callback=None,
        event_data=None,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        control_layout = ControlLayout(width=control_width) if control_width else ControlLayout()
        control = ComboBox(
            items,
            default_value=default_value,
            callback=callback,
            event_data=event_data,
            layout=control_layout,
            profile_key=control_profile_key,
        )
        super().__init__(
            label,
            control,
            theme=theme,
            layout=layout,
            profile_key=profile_key,
        )


class LabeledNumericField(LabeledField):
    def __init__(
        self,
        label: str,
        *,
        kind: NumericKind | str = NumericKind.INTEGER,
        default_value=0,
        min_value=None,
        max_value=None,
        min_clamped: bool = False,
        max_clamped: bool = False,
        format: str | None = None,
        step=None,
        step_fast=None,
        control_width: int | None = None,
        control_profile_key: str | None = None,
        callback=None,
        event_data=None,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        control_layout = ControlLayout(width=control_width) if control_width else ControlLayout()

        numeric_kwargs = dict(
            kind=kind,
            default_value=default_value,
            min_value=min_value,
            max_value=max_value,
            min_clamped=min_clamped,
            max_clamped=max_clamped,
            format=format,
            callback=callback,
            event_data=event_data,
            layout=control_layout,
            profile_key=control_profile_key,
        )
        if step is not None:
            numeric_kwargs["step"] = step
        if step_fast is not None:
            numeric_kwargs["step_fast"] = step_fast

        super().__init__(
            label,
            NumericStepper(**numeric_kwargs),
            theme=theme,
            layout=layout,
            profile_key=profile_key,
        )


class NumericUnitField(LabeledField):
    """Numeric value plus a unit selector, composed as one reusable field row."""

    def __init__(
        self,
        label: str,
        units,
        *,
        default_value=0.0,
        default_unit=None,
        kind: NumericKind | str = NumericKind.FLOAT,
        min_value=None,
        max_value=None,
        min_clamped: bool = False,
        max_clamped: bool = False,
        format: str | None = None,
        step=None,
        step_fast=None,
        value_width: int | None = None,
        unit_width: int | None = None,
        value_profile_key: str = "numeric_unit.value",
        unit_profile_key: str = "numeric_unit.unit",
        callback=None,
        event_data=None,
        unit_callback=None,
        unit_event_data=None,
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        value_layout = ControlLayout(width=value_width) if value_width else ControlLayout()
        unit_layout = ControlLayout(width=unit_width) if unit_width else ControlLayout()

        numeric_kwargs = dict(
            kind=kind,
            default_value=default_value,
            min_value=min_value,
            max_value=max_value,
            min_clamped=min_clamped,
            max_clamped=max_clamped,
            format=format,
            callback=callback,
            event_data=event_data,
            layout=value_layout,
            profile_key=value_profile_key,
        )
        if step is not None:
            numeric_kwargs["step"] = step
        if step_fast is not None:
            numeric_kwargs["step_fast"] = step_fast

        self.value_control = NumericStepper(**numeric_kwargs)
        self.unit_control = ComboBox(
            units,
            default_value=default_unit,
            callback=unit_callback,
            event_data=unit_event_data,
            layout=unit_layout,
            profile_key=unit_profile_key,
        )
        super().__init__(
            label,
            self.value_control,
            accessories=(self.unit_control,),
            theme=theme,
            layout=layout,
            profile_key=profile_key,
        )

    def value_items(self) -> tuple[object, object]:
        return self.value_control.require_item(), self.unit_control.require_item()


class DurationEditor(Component):
    """Three-part Days/Hours/Minutes editor with one aligned grid."""

    profile_key = "control_column"

    def __init__(
        self,
        *,
        heading: str,
        day_label: str,
        hour_label: str,
        minute_label: str,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        maximum_days: int = 365,
        maximum_hours: int = 23,
        maximum_minutes: int = 59,
        input_width: int | None = None,
        grid_width: int | None = None,
        label_column_width: int | None = None,
        control_column_width: int | None = None,
        input_profile_key: str = "duration_editor.input",
        grid_profile_key: str = "duration_editor.grid",
        columns_profile_key: str = "duration_editor.columns",
        theme: ControlLayoutTheme | None = None,
        layout: ControlLayout | None = None,
        profile_key: str | None = None,
    ):
        super().__init__(theme=theme, layout=layout, profile_key=profile_key)
        self.heading = Label(heading)
        self.day_label = Label(day_label)
        self.hour_label = Label(hour_label)
        self.minute_label = Label(minute_label)
        value_layout = ControlLayout(width=input_width) if input_width else ControlLayout()
        self.days = NumericStepper(
            kind=NumericKind.INTEGER,
            default_value=days,
            min_value=0,
            max_value=maximum_days,
            min_clamped=True,
            max_clamped=True,
            layout=value_layout,
            profile_key=input_profile_key,
        )
        self.hours = NumericStepper(
            kind=NumericKind.INTEGER,
            default_value=hours,
            min_value=0,
            max_value=maximum_hours,
            min_clamped=True,
            max_clamped=True,
            layout=value_layout,
            profile_key=input_profile_key,
        )
        self.minutes = NumericStepper(
            kind=NumericKind.INTEGER,
            default_value=minutes,
            min_value=0,
            max_value=maximum_minutes,
            min_clamped=True,
            max_clamped=True,
            layout=value_layout,
            profile_key=input_profile_key,
        )
        explicit_columns = ()
        if label_column_width is not None or control_column_width is not None:
            if label_column_width is None or control_column_width is None:
                raise ValueError(
                    "label_column_width and control_column_width must be supplied together"
                )
            explicit_columns = (int(label_column_width), int(control_column_width))

        self.grid = ControlGrid(
            (
                (self.day_label, self.days),
                (self.hour_label, self.hours),
                (self.minute_label, self.minutes),
            ),
            column_widths=explicit_columns,
            column_profile_key=columns_profile_key,
            layout=ControlLayout(width=grid_width) if grid_width else ControlLayout(),
            profile_key=grid_profile_key,
        )
        self.column = ControlColumn(
            (self.heading, self.grid),
            theme=self.theme,
            layout=self.layout,
            profile_key=self.profile_key,
        )

    def build(self, *, renderer=None, parent=None) -> object:
        renderer = renderer or get_default_renderer()
        item = self.column.build(renderer=renderer, parent=parent)
        self.resolved_layout = self.column.resolved_layout
        return self._bind(renderer, item)

    def value_items(self) -> tuple[object, object, object]:
        return (
            self.days.require_item(),
            self.hours.require_item(),
            self.minutes.require_item(),
        )
