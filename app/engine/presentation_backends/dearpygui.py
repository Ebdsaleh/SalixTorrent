"""Dear PyGui presentation-backend composition."""

from __future__ import annotations

from app.engine.command_menu_hosts import DearPyGuiCommandMenuHost
from app.engine.component_renderers import DearPyGuiRenderer
from app.engine.layout_hosts import DearPyGuiLayoutHost
from app.engine.plot_hosts import DearPyGuiPlotHost
from app.engine.scene_hosts import DearPyGuiSceneHost
from app.engine.state_grid_hosts import DearPyGuiStateGridHost
from app.engine.table_hosts import DearPyGuiTableHost
from app.framework.components.profile import ComponentLayoutProfile
from app.runtime.presentation import PresentationBackend


def create_dearpygui_backend(
    *, component_profile: ComponentLayoutProfile | None = None
) -> PresentationBackend:
    """Compose the current reference desktop adapters as one explicit bundle."""

    return PresentationBackend(
        "dearpygui",
        component_renderer=DearPyGuiRenderer(component_profile=component_profile),
        layout_host=DearPyGuiLayoutHost(),
        scene_host=DearPyGuiSceneHost(),
        plot_host=DearPyGuiPlotHost(),
        table_host=DearPyGuiTableHost(),
        state_grid_host=DearPyGuiStateGridHost(),
        command_menu_host=DearPyGuiCommandMenuHost(),
    )
