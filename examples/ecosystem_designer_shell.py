"""Visible cross-backend proof of the optional designer shell surfaces.

This is intentionally a small editor-shell proof rather than a full RAD IDE.
It renders one reconstructed semantic component document, exposes the accepted
semantic command tree, and presents the current stable-ID hierarchy through the
same workspace ownership on Dear PyGui and Tkinter.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from app.framework.components import (
    Button,
    ControlColumn,
    ControlLayout,
    FILL,
    Label,
    SplitPane,
    SplitPanel,
)
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_hierarchy_panel import DesignerHierarchyPanel
from app.framework.designer_preview import DesignerPreviewContext
from app.framework.designer_shell import DesignerShellCommands
from app.framework.designer_shell_menu import DesignerShellMenu
from app.framework.designer_workspace import DesignerWorkspace
from app.framework.responsive import LayoutCoordinator
from app.runtime.application import ApplicationSpec
from app.runtime.lifecycle import ApplicationRuntime, CallbackService


def _designer_snapshot():
    actions = ControlColumn((
        Button("Actions"),
        Button("Secondary"),
    ))
    source = ControlColumn((
        Label("Editable preview document"),
        actions,
    ))
    identities = DesignerIdentityMap(prefix="designer-surface")
    identities.bind(source, "designer-surface-root")
    identities.bind(actions, "designer-surface-actions")
    return capture_component_tree(source, identities=identities)


def _run(backend_name: str, *, smoke_seconds: float = 0.0) -> int:
    spec = ApplicationSpec(
        "EcosystemDesignerShell",
        title="Ecosystem Designer Shell",
        width=900,
        height=620,
        minimum_width=720,
        minimum_height=500,
    )
    runtime = ApplicationRuntime()
    if backend_name == "dearpygui":
        from app.engine.application_hosts.dearpygui import DearPyGuiApplicationHost

        host = DearPyGuiApplicationHost(spec, runtime=runtime)
    else:
        from app.engine.application_hosts.tkinter import TkinterApplicationHost

        host = TkinterApplicationHost(spec, runtime=runtime)

    layout_coordinator = LayoutCoordinator(host.presentation.layout_host)
    holder = {}
    status = Label("Select a hierarchy row or open Designer Commands.")
    hierarchy_parent = ControlColumn(layout=ControlLayout(width=FILL, height=FILL))
    preview_parent = ControlColumn(layout=ControlLayout(width=FILL, height=FILL))

    def show_commands(_event=None):
        holder["menu"].show()

    workspace_split = SplitPanel(
        (
            SplitPane(
                "hierarchy",
                hierarchy_parent,
                weight=0.34,
                minimum=230,
                border=False,
            ),
            SplitPane(
                "preview",
                ControlColumn((Label("Preview"), preview_parent)),
                weight=0.66,
                minimum=360,
                border=False,
            ),
        ),
        gap=8,
        coordinator=layout_coordinator,
        layout=ControlLayout(width=FILL, height=430),
    )
    chrome = ControlColumn((
        Label("Designer Shell Surface — post-v0.5.1 Tranche 2"),
        Button("Designer Commands", callback=show_commands),
        status,
        workspace_split,
    ), layout=ControlLayout(width=FILL))
    host.build(chrome)

    workspace = DesignerWorkspace.create(
        _designer_snapshot(),
        context=DesignerPreviewContext(layout_coordinator=layout_coordinator),
        renderer=host.presentation.component_renderer,
        parent=preview_parent.require_item(),
    )
    actions = next(
        node
        for node in workspace.session.snapshot.root.walk()
        if node.type_key == "control.button" and node.properties.get("label") == "Actions"
    )
    workspace.select_and_focus_node(actions.node_id)
    workspace.reveal_selected_in_hierarchy()

    if backend_name == "dearpygui":
        from app.engine.designer_hierarchy_panel_hosts import (
            DearPyGuiDesignerHierarchyPanelHost,
        )

        hierarchy_host = DearPyGuiDesignerHierarchyPanelHost(height=390)
    else:
        from app.engine.designer_hierarchy_panel_hosts import (
            TkinterDesignerHierarchyPanelHost,
        )

        hierarchy_host = TkinterDesignerHierarchyPanelHost(
            host.presentation.component_renderer,
            height_rows=16,
        )

    hierarchy_panel = DesignerHierarchyPanel(
        workspace,
        hierarchy_host,
        title="Hierarchy",
    )
    hierarchy_panel.build(parent=hierarchy_parent.require_item())
    holder["hierarchy"] = hierarchy_panel

    def on_request(request):
        status.set_text(f"Shell request: {request.kind.value}")
        return request

    def on_result(key, result):
        hierarchy_panel.refresh()
        if result is not None and not hasattr(result, "kind"):
            status.set_text(f"Command: {key}")

    menu = DesignerShellMenu(
        DesignerShellCommands(workspace),
        host.presentation.command_menu_host,
        title="Designer",
        on_request=on_request,
        on_result=on_result,
    )
    menu.build()
    holder["menu"] = menu

    runtime.services.register(
        "designer shell cleanup",
        CallbackService(
            on_stop=lambda: (
                menu.dispose(),
                hierarchy_panel.dispose(),
                workspace.close(),
            )
        ),
    )

    if smoke_seconds > 0.0:
        elapsed = {"value": 0.0}

        def stop_after(delta_seconds):
            elapsed["value"] += max(0.0, float(delta_seconds))
            if elapsed["value"] >= smoke_seconds:
                host.request_stop()

        runtime.services.register("smoke stop", CallbackService(on_update=stop_after))

    return host.run()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ui-backend",
        choices=("dearpygui", "tkinter"),
        default="dearpygui",
    )
    parser.add_argument(
        "--smoke-seconds",
        type=float,
        default=0.0,
        help="automatically close after the requested graphical smoke duration",
    )
    args = parser.parse_args(argv)
    return _run(args.ui_backend, smoke_seconds=max(0.0, args.smoke_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
