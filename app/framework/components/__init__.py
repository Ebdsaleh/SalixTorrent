"""Reusable GUI component contracts inside the provisional framework boundary."""

from app.framework.components.layout import (
    AUTO,
    FILL,
    ControlLayout,
    ControlLayoutDefaults,
    ControlLayoutTheme,
    DimensionMode,
    ResolvedControlLayout,
    resolve_control_layout,
)
from app.framework.components.attachments import Tooltip
from app.framework.components.events import ComponentEvent, ComponentEventType, action_callback
from app.framework.components.profile import (
    ComponentLayoutProfile,
    FRAMEWORK_COMPONENT_PROFILE,
)
from app.framework.components.controls import (
    Button,
    CheckBox,
    ComboBox,
    Label,
    NumericKind,
    NumericStepper,
    ProgressBar,
    Separator,
    Spacer,
    TextInput,
)
from app.framework.components.containers import (
    ControlColumn,
    ControlGrid,
    ControlRow,
    Dialog,
    SectionPanel,
)
from app.framework.components.fields import (
    DurationEditor,
    LabeledComboField,
    LabeledField,
    LabeledNumericField,
    NumericUnitField,
)
from app.framework.components.state import ComponentGroup
from app.framework.components.bindings import BindingSet, ValueBinding
from app.framework.components.renderer import (
    ComponentRenderer,
    clear_default_renderer,
    get_default_renderer,
    set_default_renderer,
)

__all__ = [
    "AUTO",
    "FILL",
    "FRAMEWORK_COMPONENT_PROFILE",
    "BindingSet",
    "Button",
    "CheckBox",
    "ComboBox",
    "ComponentEvent",
    "ComponentEventType",
    "ComponentGroup",
    "ComponentLayoutProfile",
    "ComponentRenderer",
    "ControlColumn",
    "ControlGrid",
    "ControlLayout",
    "ControlLayoutDefaults",
    "ControlLayoutTheme",
    "ControlRow",
    "Dialog",
    "DimensionMode",
    "DurationEditor",
    "Label",
    "LabeledComboField",
    "LabeledField",
    "LabeledNumericField",
    "NumericKind",
    "NumericStepper",
    "ProgressBar",
    "NumericUnitField",
    "ResolvedControlLayout",
    "SectionPanel",
    "Separator",
    "Spacer",
    "TextInput",
    "Tooltip",
    "ValueBinding",
    "action_callback",
    "clear_default_renderer",
    "get_default_renderer",
    "resolve_control_layout",
    "set_default_renderer",
]
