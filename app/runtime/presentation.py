"""Backend-neutral presentation capability and adapter-bundle contracts.

The runtime does not import any concrete GUI toolkit or framework package.  A
presentation backend is simply an explicit bundle of adapters installed by an
application composition root.  Keeping the bundle here lets graphical and
headless applications share one vocabulary without making GUI support a
runtime requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PresentationCapability(str, Enum):
    """Broad presentation capabilities that an application may query."""

    COMPONENTS = "components"
    RESPONSIVE_LAYOUT = "responsive_layout"
    SCENES = "scenes"
    REALTIME_PLOTS = "realtime_plots"
    LIVE_TABLES = "live_tables"
    STATE_GRIDS = "state_grids"


def _backend_name(value: object) -> str:
    name = str(value or "").strip().lower()
    if not name:
        raise ValueError("presentation backend name must not be empty")
    return name


@dataclass(frozen=True)
class PresentationBackend:
    """Explicit collection of presentation adapters for one backend.

    Adapter fields intentionally use ``object`` rather than importing the
    framework's Protocol types.  This keeps ``app.runtime`` standard-library
    only and relocatable.  Each framework subsystem validates the adapter it
    consumes at the point of use.
    """

    name: str
    component_renderer: object | None = None
    layout_host: object | None = None
    scene_host: object | None = None
    plot_host: object | None = None
    table_host: object | None = None
    state_grid_host: object | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _backend_name(self.name))

    @property
    def capabilities(self) -> frozenset[PresentationCapability]:
        values: set[PresentationCapability] = set()
        if self.component_renderer is not None:
            values.add(PresentationCapability.COMPONENTS)
        if self.layout_host is not None:
            values.add(PresentationCapability.RESPONSIVE_LAYOUT)
        if self.scene_host is not None:
            values.add(PresentationCapability.SCENES)
        if self.plot_host is not None:
            values.add(PresentationCapability.REALTIME_PLOTS)
        if self.table_host is not None:
            values.add(PresentationCapability.LIVE_TABLES)
        if self.state_grid_host is not None:
            values.add(PresentationCapability.STATE_GRIDS)
        return frozenset(values)

    def supports(self, capability: PresentationCapability | str) -> bool:
        try:
            resolved = PresentationCapability(str(getattr(capability, "value", capability)))
        except (TypeError, ValueError):
            return False
        return resolved in self.capabilities

    def require(self, capability: PresentationCapability | str) -> None:
        try:
            resolved = PresentationCapability(str(getattr(capability, "value", capability)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unknown presentation capability: {capability!r}") from exc
        if resolved not in self.capabilities:
            raise RuntimeError(
                f"presentation backend {self.name!r} does not provide {resolved.value!r}"
            )


HEADLESS_PRESENTATION = PresentationBackend("headless")
