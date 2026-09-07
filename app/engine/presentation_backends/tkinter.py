"""Tkinter presentation-backend composition."""

from __future__ import annotations

from app.engine.component_renderers import TkinterRenderer
from app.engine.layout_hosts import TkinterLayoutHost
from app.engine.plot_hosts import TkinterPlotHost
from app.engine.scene_hosts import TkinterSceneHost
from app.framework.components.profile import ComponentLayoutProfile
from app.runtime.presentation import PresentationBackend


def create_tkinter_backend(
    root,
    *,
    component_profile: ComponentLayoutProfile | None = None,
) -> PresentationBackend:
    """Compose Tkinter adapters around one Tk root/container."""

    renderer = TkinterRenderer(root, component_profile=component_profile)
    return PresentationBackend(
        "tkinter",
        component_renderer=renderer,
        layout_host=TkinterLayoutHost(renderer),
        scene_host=TkinterSceneHost(renderer),
        plot_host=TkinterPlotHost(renderer),
    )
