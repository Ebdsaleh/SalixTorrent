"""Deterministic framework property resolution.

Every configurable property follows the same precedence chain::

    framework default -> active theme -> explicit instance override

Candidates are validated independently.  An invalid higher-precedence value
falls back to the next valid layer; a value that is valid but larger than the
current runtime geometry remains the configured value and is constrained later
by the layout engine.  Keeping configuration resolution separate from runtime
constraint resolution makes responsive layouts predictable and inspectable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Generic, TypeVar, cast


T = TypeVar("T")


class _UnsetType:
    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _UnsetType()
"""Sentinel meaning "inherit from the next lower-precedence layer".

``None`` is intentionally *not* used for inheritance because ``None`` may be a
valid explicit property value (for example ``maximum_width=None`` meaning no
configured maximum).
"""


class PropertySource(str, Enum):
    DEFAULT = "default"
    THEME = "theme"
    INSTANCE = "instance"


@dataclass(frozen=True)
class RejectedPropertyCandidate:
    source: PropertySource
    value: object
    reason: str = "invalid value"


@dataclass(frozen=True)
class ResolvedProperty(Generic[T]):
    value: T
    source: PropertySource
    rejected: tuple[RejectedPropertyCandidate, ...] = ()


Validator = Callable[[object], bool]
Normalizer = Callable[[object], T]


def is_unset(value: object) -> bool:
    return value is UNSET


def resolve_property(
    *,
    default: object,
    theme: object = UNSET,
    override: object = UNSET,
    validator: Validator | None = None,
    normalizer: Normalizer[T] | None = None,
) -> ResolvedProperty[T]:
    """Resolve one property using default -> theme -> instance precedence.

    ``default`` is required to be valid because framework primitives must
    always possess a safe fallback.  Theme and instance values are sparse:
    ``UNSET`` means inherit.  Invalid candidates are recorded for diagnostics
    and skipped without affecting unrelated properties.
    """

    def _normalise(candidate: object) -> T:
        if normalizer is None:
            return cast(T, candidate)
        return normalizer(candidate)

    def _accept(candidate: object) -> tuple[bool, T | None, str]:
        try:
            if validator is not None and not validator(candidate):
                return False, None, "validator rejected value"
            return True, _normalise(candidate), ""
        except (TypeError, ValueError, OverflowError) as exc:
            return False, None, str(exc) or exc.__class__.__name__

    ok, default_value, reason = _accept(default)
    if not ok:
        raise ValueError(f"framework default is invalid: {default!r} ({reason})")

    value = cast(T, default_value)
    source = PropertySource.DEFAULT
    rejected: list[RejectedPropertyCandidate] = []

    for candidate_source, candidate in (
        (PropertySource.THEME, theme),
        (PropertySource.INSTANCE, override),
    ):
        if is_unset(candidate):
            continue
        accepted, normalised, candidate_reason = _accept(candidate)
        if not accepted:
            rejected.append(
                RejectedPropertyCandidate(
                    source=candidate_source,
                    value=candidate,
                    reason=candidate_reason or "invalid value",
                )
            )
            continue
        value = cast(T, normalised)
        source = candidate_source

    return ResolvedProperty(value=value, source=source, rejected=tuple(rejected))
