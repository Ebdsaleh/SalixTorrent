"""Visible cross-backend proof of the optional designer shell surfaces.

This is intentionally a compact editor-shell proof rather than a full RAD IDE.
It renders one reconstructed semantic component document, exposes the accepted
semantic command tree, presents a catalog-backed component palette plus explicit
placement resolver, the stable-ID hierarchy and property inspector, and keeps the
reconstructed preview selectable with a transient visual outline and a bottom-right
resize handle through the same workspace ownership on Dear PyGui and Tkinter. Palette activation opens a
backend-neutral placement form; only explicit parent/slot/index/metadata confirmation
may create a node through the existing checked structural transaction.
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
    SectionPanel,
    SplitOrientation,
    SplitPane,
    SplitPanel,
)
from app.framework.designer import DesignerIdentityMap, capture_component_tree
from app.framework.designer_component_palette import DesignerComponentPalette
from app.framework.designer_component_placement import DesignerComponentPlacementSurface
from app.framework.designer_hierarchy_panel import DesignerHierarchyPanel
from app.framework.designer_inspector_panel import DesignerInspectorPanel
from app.framework.designer_preview import DesignerPreviewContext
from app.framework.designer_preview_selection import DesignerPreviewSelectionSurface
from app.framework.designer_preview_resize import DesignerPreviewResizeSurface
from app.framework.designer_shell import DesignerShellCommands
from app.framework.designer_shell_menu import DesignerShellMenu
from app.framework.designer_shell_shortcuts import DesignerShellShortcuts
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
        width=1240,
        height=720,
        minimum_width=980,
        minimum_height=560,
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
    status = Label("Select/click the preview, drag the selected resize handle, edit properties/sizes, place components, or use structural commands/shortcuts.")
    palette_parent = ControlColumn(layout=ControlLayout(width=FILL, height=FILL))
    placement_parent = ControlColumn(layout=ControlLayout(width=FILL, height=FILL))
    hierarchy_parent = ControlColumn(layout=ControlLayout(width=FILL, height=FILL))
    # Use the same framework-owned split geometry vertically as the main editor
    # row. Dear PyGui groups are flow containers rather than clipping layout
    # regions, so stacking fixed-height group wrappers allowed the palette's
    # scrollable child to consume the whole left pane and hide Placement /
    # Hierarchy. Separate split panes give every editor surface an explicit,
    # non-overlapping viewport on both desktop backends.
    left_sidebar = SplitPanel(
        (
            SplitPane(
                "components",
                palette_parent,
                weight=0.30,
                minimum=150,
                maximum=180,
                border=False,
            ),
            SplitPane(
                "placement",
                placement_parent,
                weight=0.40,
                minimum=190,
                maximum=220,
                border=False,
            ),
            SplitPane(
                "hierarchy",
                hierarchy_parent,
                weight=0.30,
                minimum=120,
                border=False,
            ),
        ),
        orientation=SplitOrientation.VERTICAL,
        gap=6,
        coordinator=layout_coordinator,
        layout=ControlLayout(width=FILL, height=FILL),
    )
    # Use a structural child-window-backed preview mount rather than a fill-sized
    # ControlColumn/group. Dear PyGui groups propagate their width policy to
    # descendants, so a FILL group can make otherwise explicitly sized preview
    # controls consume the entire pane. SectionPanel keeps the pane extent
    # separate from child-control sizing on both desktop backends.
    preview_parent = SectionPanel(
        "Preview",
        (),
        separated=False,
        border=False,
        layout=ControlLayout(width=FILL, height=FILL),
    )
    inspector_parent = ControlColumn(layout=ControlLayout(width=FILL, height=FILL))

    def show_commands(_event=None):
        holder["menu"].show()

    workspace_split = SplitPanel(
        (
            SplitPane(
                "hierarchy",
                left_sidebar,
                weight=0.27,
                minimum=270,
                border=False,
            ),
            SplitPane(
                "preview",
                preview_parent,
                weight=0.44,
                minimum=380,
                border=False,
            ),
            SplitPane(
                "inspector",
                inspector_parent,
                weight=0.29,
                minimum=300,
                border=False,
            ),
        ),
        gap=8,
        coordinator=layout_coordinator,
        layout=ControlLayout(width=FILL, height=520),
    )
    chrome = ControlColumn((
        Label("Designer Shell Surface — post-v0.5.1 Tranche 9"),
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
        from app.engine.designer_component_palette_hosts import (
            DearPyGuiDesignerComponentPaletteHost,
        )
        from app.engine.designer_component_placement_hosts import (
            DearPyGuiDesignerComponentPlacementHost,
        )
        from app.engine.designer_hierarchy_panel_hosts import (
            DearPyGuiDesignerHierarchyPanelHost,
        )
        from app.engine.designer_inspector_panel_hosts import (
            DearPyGuiDesignerInspectorPanelHost,
        )
        from app.engine.designer_preview_pointer_arbiter import (
            DearPyGuiDesignerPreviewPointerArbiter,
        )
        from app.engine.designer_preview_selection_hosts import (
            DearPyGuiDesignerPreviewSelectionHost,
        )
        from app.engine.designer_preview_resize_hosts import (
            DearPyGuiDesignerPreviewResizeHost,
        )
        from app.engine.designer_shell_shortcut_hosts import (
            DearPyGuiDesignerShellShortcutHost,
        )

        palette_host = DearPyGuiDesignerComponentPaletteHost(height=150)
        placement_host = DearPyGuiDesignerComponentPlacementHost(height=195)
        hierarchy_host = DearPyGuiDesignerHierarchyPanelHost(height=120)
        inspector_host = DearPyGuiDesignerInspectorPanelHost(height=500)
        preview_pointer_arbiter = DearPyGuiDesignerPreviewPointerArbiter()
        preview_selection_host = DearPyGuiDesignerPreviewSelectionHost(
            pointer_arbiter=preview_pointer_arbiter
        )
        preview_resize_host = DearPyGuiDesignerPreviewResizeHost(
            pointer_arbiter=preview_pointer_arbiter
        )
        shortcut_host = DearPyGuiDesignerShellShortcutHost()
    else:
        from app.engine.designer_component_palette_hosts import (
            TkinterDesignerComponentPaletteHost,
        )
        from app.engine.designer_component_placement_hosts import (
            TkinterDesignerComponentPlacementHost,
        )
        from app.engine.designer_hierarchy_panel_hosts import (
            TkinterDesignerHierarchyPanelHost,
        )
        from app.engine.designer_inspector_panel_hosts import (
            TkinterDesignerInspectorPanelHost,
        )
        from app.engine.designer_preview_selection_hosts import (
            TkinterDesignerPreviewSelectionHost,
        )
        from app.engine.designer_preview_resize_hosts import (
            TkinterDesignerPreviewResizeHost,
        )
        from app.engine.designer_shell_shortcut_hosts import (
            TkinterDesignerShellShortcutHost,
        )

        palette_host = TkinterDesignerComponentPaletteHost(
            host.presentation.component_renderer,
            height_rows=5,
        )
        placement_host = TkinterDesignerComponentPlacementHost(
            host.presentation.component_renderer
        )
        hierarchy_host = TkinterDesignerHierarchyPanelHost(
            host.presentation.component_renderer,
            height_rows=6,
        )
        inspector_host = TkinterDesignerInspectorPanelHost(
            host.presentation.component_renderer,
            height=470,
        )
        preview_selection_host = TkinterDesignerPreviewSelectionHost(
            host.presentation.component_renderer
        )
        preview_resize_host = TkinterDesignerPreviewResizeHost(
            host.presentation.component_renderer
        )
        shortcut_host = TkinterDesignerShellShortcutHost(host.root)

    placement_activity = {"was_active": False}

    def on_placement_change(state):
        if state.request is None:
            if placement_activity["was_active"]:
                hierarchy = holder.get("hierarchy")
                inspector = holder.get("inspector")
                preview_selection = holder.get("preview_selection")
                preview_resize = holder.get("preview_resize")
                if hierarchy is not None:
                    hierarchy.refresh()
                if inspector is not None:
                    inspector.refresh()
                if preview_selection is not None:
                    preview_selection.refresh()
                if preview_resize is not None:
                    preview_resize.refresh()
                palette_ref = holder.get("palette")
                if palette_ref is not None:
                    palette_ref.refresh()
                status.set_text(f"Inserted component: {workspace.state.selected_id}")
            placement_activity["was_active"] = False
            return
        placement_activity["was_active"] = True
        if state.creation_error:
            status.set_text(f"Placement unavailable: {state.creation_error}")
        else:
            status.set_text(
                f"Placement: {state.request.label} -> {state.parent_id or '(choose parent)'} / {state.slot_key or '(choose slot)'}"
            )

    def on_placement_error(exc):
        status.set_text(f"Placement error: {exc}")

    placement = DesignerComponentPlacementSurface(
        workspace,
        placement_host,
        title="Placement",
        on_change=on_placement_change,
        on_error=on_placement_error,
    )
    placement.build(parent=placement_parent.require_item())
    holder["placement"] = placement

    def on_palette_request(request):
        state = placement.begin(request)
        target = request.target_hint or "(no selection)"
        if state.creation_error:
            status.set_text(f"Insert request: {request.label} -> {target}; {state.creation_error}")
        else:
            status.set_text(
                f"Insert request: {request.label} -> {target}; confirm Placement"
            )
        return request

    palette = DesignerComponentPalette(
        workspace,
        palette_host,
        title="Components",
        on_request=on_palette_request,
    )
    palette.build(parent=palette_parent.require_item())
    holder["palette"] = palette

    def on_inspector_change(state):
        preview_selection = holder.get("preview_selection")
        preview_resize = holder.get("preview_resize")
        if preview_selection is not None:
            preview_selection.refresh()
        if preview_resize is not None:
            preview_resize.refresh()
        status.set_text(f"Property edit: {state.type_label} [{state.node_id}]")

    def on_inspector_error(property_key, exc):
        status.set_text(f"Inspector error ({property_key}): {exc}")

    inspector_panel = DesignerInspectorPanel(
        workspace,
        inspector_host,
        title="Inspector",
        on_change=on_inspector_change,
        on_error=on_inspector_error,
    )
    inspector_panel.build(parent=inspector_parent.require_item())
    holder["inspector"] = inspector_panel

    def on_hierarchy_change():
        inspector_panel.refresh()
        preview_selection = holder.get("preview_selection")
        preview_resize = holder.get("preview_resize")
        if preview_selection is not None:
            preview_selection.refresh()
        if preview_resize is not None:
            preview_resize.refresh()

    hierarchy_panel = DesignerHierarchyPanel(
        workspace,
        hierarchy_host,
        title="Hierarchy",
        on_change=on_hierarchy_change,
    )
    hierarchy_panel.build(parent=hierarchy_parent.require_item())
    holder["hierarchy"] = hierarchy_panel

    def on_preview_select(node_id):
        hierarchy_panel.refresh()
        inspector_panel.refresh()
        preview_resize = holder.get("preview_resize")
        if preview_resize is not None:
            preview_resize.refresh()
        status.set_text(f"Preview selection: {node_id}")

    preview_selection = DesignerPreviewSelectionSurface(
        workspace,
        preview_selection_host,
        on_change=on_preview_select,
    )
    preview_selection.build(parent=preview_parent.require_item())
    holder["preview_selection"] = preview_selection

    def on_preview_resize(node_id, width, height):
        hierarchy_panel.refresh()
        inspector_panel.refresh()
        preview_selection.refresh()
        status.set_text(f"Preview resize: {node_id} -> {width} x {height}")

    def on_preview_resize_error(node_id, exc):
        status.set_text(f"Preview resize error ({node_id or 'selection'}): {exc}")

    preview_resize = DesignerPreviewResizeSurface(
        workspace,
        preview_resize_host,
        on_change=on_preview_resize,
        on_error=on_preview_resize_error,
    )
    preview_resize.build(parent=preview_parent.require_item())
    holder["preview_resize"] = preview_resize

    def on_request(request):
        status.set_text(f"Shell request: {request.kind.value}")
        return request

    def on_result(key, result):
        hierarchy_panel.refresh()
        inspector_panel.refresh()
        preview_selection.refresh()
        preview_resize.refresh()
        if result is not None and not hasattr(result, "kind"):
            status.set_text(f"Command: {key}")

    shell = DesignerShellCommands(workspace)
    menu = DesignerShellMenu(
        shell,
        host.presentation.command_menu_host,
        title="Designer",
        on_request=on_request,
        on_result=on_result,
    )
    menu.build()
    holder["menu"] = menu

    shortcuts = DesignerShellShortcuts(
        shell,
        shortcut_host,
        on_request=on_request,
        on_result=on_result,
    )
    shortcuts.build()
    holder["shortcuts"] = shortcuts

    runtime.services.register(
        "designer shell cleanup",
        CallbackService(
            on_stop=lambda: (
                shortcuts.dispose(),
                menu.dispose(),
                preview_resize.dispose(),
                preview_selection.dispose(),
                placement.dispose(),
                palette.dispose(),
                hierarchy_panel.dispose(),
                inspector_panel.dispose(),
                workspace.close(),
            )
        ),
    )

    runtime.services.register(
        "designer preview interaction initial refresh",
        CallbackService(on_start=lambda: (preview_selection.refresh(), preview_resize.refresh())),
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
