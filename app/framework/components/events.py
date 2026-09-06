"""Renderer-neutral callback metadata for reusable GUI components.

Component callbacks receive :class:`ComponentEvent` instances rather than a
backend-specific ``sender/app_data/user_data`` calling convention.  Applications
that only need a command-style no-argument callback can wrap it with
:func:`action_callback` explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Callable, TypeVar


class ComponentEventType(str, Enum):
    """Semantic event kinds emitted by reusable components."""

    ACTIVATE = "activate"
    CHANGE = "change"


@dataclass(frozen=True)
class ComponentEvent:
    """Backend-neutral event delivered to a component callback.

    ``source`` is the component object that owns the callback, ``value`` is the
    renderer's semantic event value (when one exists), and ``data`` is explicit
    application metadata captured by the component.  Backend widget IDs and
    renderer-specific callback arguments are deliberately not exposed here.
    """

    source: object
    event_type: ComponentEventType
    value: object = None
    data: object = None


_ResultT = TypeVar("_ResultT")


def action_callback(action: Callable[[], _ResultT]) -> Callable[[ComponentEvent], _ResultT]:
    """Adapt a no-argument application action to the component-event contract."""

    if not callable(action):
        raise TypeError("component action callback must be callable")

    @wraps(action)
    def dispatch(_event: ComponentEvent) -> _ResultT:
        return action()

    return dispatch
