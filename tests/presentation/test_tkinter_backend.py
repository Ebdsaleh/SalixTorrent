from __future__ import annotations

import ast
import gc
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import PROJECT_ROOT

from app.engine.application_hosts.tkinter import TkinterApplicationHost
from app.engine.command_menu_hosts import TkinterCommandMenuHost
from app.engine.component_renderers import TkinterRenderer
from app.engine.designer_component_palette_hosts import TkinterDesignerComponentPaletteHost
from app.engine.designer_component_placement_hosts import TkinterDesignerComponentPlacementHost
from app.engine.designer_hierarchy_panel_hosts import TkinterDesignerHierarchyPanelHost
from app.engine.designer_inspector_panel_hosts import TkinterDesignerInspectorPanelHost
from app.engine.designer_preview_selection_hosts import TkinterDesignerPreviewSelectionHost
from app.engine.designer_preview_resize_hosts import TkinterDesignerPreviewResizeHost
from app.engine.designer_shell_shortcut_hosts import TkinterDesignerShellShortcutHost
from app.engine.layout_hosts import TkinterLayoutHost
from app.engine.plot_hosts import TkinterPlotHost
from app.engine.presentation_backends import create_tkinter_backend
from app.engine.scene_hosts import TkinterSceneHost
from app.engine.state_grid_hosts import TkinterStateGridHost
from app.engine.table_hosts import TkinterTableHost
from app.framework.components import (
    AxisAnchor,
    Button,
    CheckBox,
    ComboBox,
    ComponentEventType,
    ComponentRenderer,
    ControlColumn,
    ControlGrid,
    ControlLayout,
    Dialog,
    FILL,
    Label,
    NumericKind,
    NumericStepper,
    ProgressBar,
    TextInput,
    PlacedComponent,
    PositionedPanel,
    SizeConstraints,
    SplitPane,
    SplitPanel,
    STRETCH,
    TabContainer,
    TabPage,
    anchored,
    anchored_overlay,
    overlay,
    positioned,
)
from app.framework.command_menu import CommandMenu, CommandMenuHost
from app.framework.designer_component_palette import DesignerComponentInsertRequest, DesignerComponentPalette, DesignerComponentPaletteHost
from app.framework.designer_component_placement import DesignerComponentPlacementHost, DesignerComponentPlacementSurface
from app.framework.designer_editing import DesignerEditSession
from app.framework.designer_hierarchy_panel import DesignerHierarchyPanel, DesignerHierarchyPanelHost
from app.framework.designer_inspector_panel import DesignerInspectorPanel, DesignerInspectorPanelHost
from app.framework.designer_preview import DesignerPreviewContext, reconstruct_designer_snapshot
from app.framework.designer_preview_selection import (
    DesignerPreviewSelectionHost,
    DesignerPreviewSelectionSurface,
)
from app.framework.designer_preview_resize import (
    DesignerPreviewResizeHost,
    DesignerPreviewResizeSurface,
)
from app.framework.designer_preview_host import DesignerPreviewHost
from app.framework.designer_project import DesignerProjectFile
from app.framework.designer_workspace import DesignerWorkspace
from app.framework.designer_shell import (
    DESIGNER_COPY_COMMAND,
    DESIGNER_DUPLICATE_COMMAND,
    DESIGNER_MOVE_DOWN_COMMAND,
    DESIGNER_REMOVE_COMMAND,
    DESIGNER_UNDO_COMMAND,
    DesignerShellCommands,
)
from app.framework.designer_shell_menu import DesignerShellMenu
from app.framework.designer_shell_shortcuts import DesignerShellShortcuts
from app.framework.interactions import CommandSet, CommandSpec
from app.framework.live_data import (
    LiveTable,
    StateGrid,
    StateGridCell,
    StateGridFrame,
    StateGridHost,
    TableCell,
    TableColumnSpec,
    TableFrame,
    TableHost,
    TableRow,
)
from app.framework.responsive import LayoutCoordinator, LayoutHost
from app.framework.visualization import (
    PlotFrame,
    PlotHost,
    PlotSeriesData,
    PlotSeriesSpec,
    RealtimeGraph,
)
from app.runtime.application import ApplicationHost, ApplicationSpec
from app.runtime.lifecycle import ApplicationRuntime, CallbackService, RuntimeState
from app.runtime.presentation import PresentationCapability
from app.runtime.scenes import SceneHost, SceneRegistry


class TkinterSourceBoundaryTests(unittest.TestCase):
    def test_tkinter_adapters_do_not_import_dearpygui_or_salix_product_layers(self):
        paths = (
            PROJECT_ROOT / "app" / "engine" / "component_renderers" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "layout_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "plot_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "scene_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "table_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "state_grid_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "presentation_backends" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "application_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "command_menu_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "designer_component_palette_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "designer_component_placement_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "designer_hierarchy_panel_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "designer_inspector_panel_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "designer_preview_selection_hosts" / "tkinter.py",
            PROJECT_ROOT / "app" / "engine" / "designer_shell_shortcut_hosts" / "tkinter.py",
        )
        forbidden = ("dearpygui", "app.logic", "app.views", "app.localization")
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            self.assertFalse(
                any(name.startswith(forbidden) for name in imports),
                str(path.relative_to(PROJECT_ROOT)),
            )


class TkinterBackendLiveTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk

            self.root = tk.Tk()
            self.root.withdraw()
            self.root.geometry("640x480")
            self.root.update_idletasks()
        except Exception as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.renderer = TkinterRenderer(self.root)

    def tearDown(self):
        renderer = getattr(self, "renderer", None)
        if renderer is not None:
            try:
                renderer.close()
            except Exception:
                pass

        root = getattr(self, "root", None)
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass

        # Tkinter callback/Variable objects can form cycles.  Collect them
        # explicitly on the Tk owner thread so a later asyncio/to_thread worker
        # cannot become the thread that finalizes Tcl state.
        self.renderer = None
        self.root = None
        gc.collect()

    def test_renderer_and_hosts_satisfy_existing_backend_contracts(self):
        layout_host = TkinterLayoutHost(self.renderer)
        scene_host = TkinterSceneHost(self.renderer)
        plot_host = TkinterPlotHost(self.renderer)
        table_host = TkinterTableHost(self.renderer)
        state_grid_host = TkinterStateGridHost(self.renderer)
        command_menu_host = TkinterCommandMenuHost(self.root)
        palette_host = TkinterDesignerComponentPaletteHost(self.renderer)
        placement_host = TkinterDesignerComponentPlacementHost(self.renderer)
        hierarchy_panel_host = TkinterDesignerHierarchyPanelHost(self.renderer)
        inspector_panel_host = TkinterDesignerInspectorPanelHost(self.renderer)
        preview_selection_host = TkinterDesignerPreviewSelectionHost(self.renderer)
        preview_resize_host = TkinterDesignerPreviewResizeHost(self.renderer)
        self.assertIsInstance(self.renderer, ComponentRenderer)
        self.assertIsInstance(layout_host, LayoutHost)
        self.assertIsInstance(scene_host, SceneHost)
        self.assertIsInstance(plot_host, PlotHost)
        self.assertIsInstance(table_host, TableHost)
        self.assertIsInstance(state_grid_host, StateGridHost)
        self.assertIsInstance(command_menu_host, CommandMenuHost)
        self.assertIsInstance(palette_host, DesignerComponentPaletteHost)
        self.assertIsInstance(placement_host, DesignerComponentPlacementHost)
        self.assertIsInstance(hierarchy_panel_host, DesignerHierarchyPanelHost)
        self.assertIsInstance(inspector_panel_host, DesignerInspectorPanelHost)
        self.assertIsInstance(preview_selection_host, DesignerPreviewSelectionHost)
        self.assertIsInstance(preview_resize_host, DesignerPreviewResizeHost)

    def test_backend_factory_exposes_common_capabilities(self):
        backend = create_tkinter_backend(self.root)
        self.assertEqual(backend.name, "tkinter")
        for capability in (
            PresentationCapability.COMPONENTS,
            PresentationCapability.RESPONSIVE_LAYOUT,
            PresentationCapability.SCENES,
            PresentationCapability.REALTIME_PLOTS,
            PresentationCapability.LIVE_TABLES,
            PresentationCapability.STATE_GRIDS,
            PresentationCapability.COMMAND_MENUS,
        ):
            self.assertTrue(backend.supports(capability))

    def test_preview_host_rebuild_transaction_replaces_real_tkinter_tree(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(snapshot)
        preview_host = DesignerPreviewHost(
            session,
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        self.root.update_idletasks()
        old_root = preview_host.preview.root
        old_actions = preview_host.component(actions.node_id)
        self.assertTrue(old_root.exists())
        self.assertTrue(old_actions.exists())

        self.assertTrue(preview_host.set_property(actions.node_id, "label", "Changed"))
        self.root.update_idletasks()
        self.assertFalse(old_root.exists())
        self.assertFalse(old_actions.exists())
        self.assertTrue(preview_host.preview.root.exists())
        self.assertEqual("Changed", preview_host.component(actions.node_id).label)
        self.assertEqual(2, preview_host.generation)
        self.assertTrue(preview_host.undo())
        self.root.update_idletasks()
        self.assertEqual("Actions", preview_host.component(actions.node_id).label)
        self.assertEqual(3, preview_host.generation)
        preview_host.close()

    def test_saved_designer_project_reopens_into_real_tkinter_preview(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        with tempfile.TemporaryDirectory() as td:
            project_path = Path(td) / "blank-designer.project"
            project = DesignerProjectFile.create(snapshot)
            project.save(project_path)
            reopened = DesignerProjectFile.open(project_path)
            preview_host = DesignerPreviewHost(
                reopened.session,
                context=DesignerPreviewContext(
                    layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
                ),
                renderer=self.renderer,
            )
            self.root.update_idletasks()
            self.assertTrue(preview_host.preview.root.exists())
            self.assertTrue(preview_host.component(actions.node_id).exists())
            self.assertEqual("Actions", preview_host.component(actions.node_id).label)
            self.assertFalse(reopened.is_dirty)
            preview_host.close()

    def test_preview_host_selection_survives_real_tkinter_replacement_by_stable_id(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(snapshot)
        preview_host = DesignerPreviewHost(
            session,
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        self.root.update_idletasks()
        self.assertTrue(preview_host.select_and_focus_node(actions.node_id))
        old_selected = preview_host.selected_component
        self.assertTrue(old_selected.exists())
        generation = preview_host.generation

        self.assertTrue(preview_host.set_property(actions.node_id, "label", "Selected"))
        self.root.update_idletasks()
        self.assertFalse(old_selected.exists())
        self.assertEqual(actions.node_id, session.selected_node_id)
        self.assertEqual(actions.node_id, session.focused_node_id)
        self.assertIs(preview_host.selected_component, preview_host.focused_component)
        self.assertTrue(preview_host.selected_component.exists())
        self.assertEqual("Selected", preview_host.selected_component.label)
        self.assertEqual(generation + 1, preview_host.generation)
        preview_host.close()

    def test_preview_host_hierarchy_navigation_uses_stable_ids_without_rebuild(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(snapshot)
        preview_host = DesignerPreviewHost(
            session,
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        self.root.update_idletasks()
        self.assertTrue(preview_host.select_and_focus_node(actions.node_id))
        generation = preview_host.generation
        parent_id = preview_host.selection_navigation_target("parent")
        self.assertIsNotNone(parent_id)
        self.assertTrue(preview_host.navigate_selection("parent", focus=True))
        self.assertEqual(parent_id, session.selected_node_id)
        self.assertEqual(parent_id, session.focused_node_id)
        self.assertTrue(preview_host.selected_component.exists())
        self.assertEqual(generation, preview_host.generation)
        reveal = preview_host.reveal_selected()
        self.assertEqual(parent_id, reveal.node_id)
        self.assertEqual(snapshot.root.node_id, reveal.path_ids[0])
        self.assertTrue(preview_host.navigate_selection("first_child", focus=True))
        self.assertTrue(preview_host.selected_component.exists())
        self.assertEqual(generation, preview_host.generation)
        preview_host.close()

    def test_preview_host_hierarchy_projection_tracks_real_tkinter_selection_without_rebuild(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(snapshot)
        preview_host = DesignerPreviewHost(
            session,
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        self.root.update_idletasks()
        generation = preview_host.generation
        selected_component = preview_host.component(actions.node_id)
        self.assertTrue(selected_component.exists())
        self.assertTrue(preview_host.select_and_focus_node(actions.node_id))
        reveal = preview_host.reveal_selected_in_hierarchy()
        self.assertEqual(actions.node_id, reveal.node_id)
        self.assertEqual(snapshot.root.node_id, reveal.path_ids[0])
        row = next(
            row for row in preview_host.hierarchy_rows()
            if row.node_id == actions.node_id
        )
        self.assertTrue(row.selected)
        self.assertTrue(row.focused)
        self.assertIs(selected_component, preview_host.selected_component)
        self.assertEqual(generation, preview_host.generation)
        parent_id = reveal.ancestor_ids[-1]
        self.assertTrue(preview_host.collapse_hierarchy_node(parent_id))
        self.assertNotIn(actions.node_id, preview_host.visible_hierarchy_ids())
        self.assertTrue(preview_host.selected_component.exists())
        self.assertEqual(generation, preview_host.generation)
        preview_host.close()

    def test_preview_host_property_inspector_tracks_real_tkinter_replacement(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(snapshot)
        preview_host = DesignerPreviewHost(
            session,
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        self.root.update_idletasks()
        self.assertTrue(preview_host.select_and_focus_node(actions.node_id))
        generation = preview_host.generation
        old_actions = preview_host.selected_component
        self.assertTrue(old_actions.exists())
        state = preview_host.inspector_state()
        self.assertEqual(actions.node_id, state.node_id)
        self.assertEqual("Button", state.type_label)
        self.assertEqual("Actions", state.row("label").value)
        self.assertEqual(generation, preview_host.generation)

        self.assertTrue(preview_host.set_selected_property("label", "Inspector"))
        self.root.update_idletasks()
        self.assertFalse(old_actions.exists())
        self.assertEqual(generation + 1, preview_host.generation)
        self.assertEqual("Inspector", preview_host.inspector_state().row("label").value)
        self.assertEqual("Inspector", preview_host.selected_component.label)
        self.assertTrue(preview_host.selected_component.exists())
        preview_host.close()

    def test_designer_workspace_composes_real_tkinter_preview_and_shell_state(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        project = DesignerProjectFile.create(snapshot)
        workspace = DesignerWorkspace(
            project,
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        self.root.update_idletasks()
        initial = workspace.state
        self.assertTrue(initial.preview_available)
        self.assertTrue(initial.preview_rendered)
        self.assertTrue(initial.is_dirty)
        self.assertTrue(initial.requires_save_as)

        self.assertTrue(workspace.select_and_focus_node(actions.node_id))
        workspace.reveal_selected_in_hierarchy()
        selected = workspace.state
        generation = selected.preview_generation
        old_actions = workspace.preview_host.selected_component
        self.assertEqual(actions.node_id, selected.inspector.node_id)
        self.assertEqual("Actions", selected.inspector.row("label").value)
        self.assertTrue(old_actions.exists())

        self.assertTrue(workspace.set_selected_property("label", "Workspace"))
        self.root.update_idletasks()
        edited = workspace.state
        self.assertFalse(old_actions.exists())
        self.assertEqual(generation + 1, edited.preview_generation)
        self.assertTrue(edited.can_undo)
        self.assertTrue(edited.is_dirty)
        self.assertEqual("Workspace", edited.inspector.row("label").value)
        self.assertEqual("Workspace", workspace.preview_host.selected_component.label)

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "workspace.project"
            workspace.save(target)
            saved = workspace.state
            self.assertFalse(saved.is_dirty)
            self.assertEqual(target.absolute(), saved.path)
            self.assertEqual(edited.preview_generation, saved.preview_generation)

        self.assertTrue(workspace.close())

    def test_designer_shell_commands_drive_real_tkinter_workspace_without_owning_backend(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(snapshot),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        self.root.update_idletasks()
        workspace.select_and_focus_node(actions.node_id)
        shell = DesignerShellCommands(workspace)
        generation = workspace.state.preview_generation
        old_actions = workspace.preview_host.selected_component
        self.assertTrue(old_actions.exists())

        payload = shell.dispatch(DESIGNER_COPY_COMMAND)
        self.assertEqual(actions.node_id, payload.root.node_id)
        self.assertEqual(generation, workspace.state.preview_generation)
        self.assertTrue(shell.command(DESIGNER_DUPLICATE_COMMAND).enabled)
        self.assertTrue(shell.dispatch(DESIGNER_DUPLICATE_COMMAND))
        self.root.update_idletasks()
        clone_id = actions.node_id + "-copy"
        clone = workspace.preview_host.component(clone_id)
        self.assertTrue(clone.exists())
        self.assertEqual(generation + 1, workspace.state.preview_generation)
        self.assertTrue(shell.command(DESIGNER_UNDO_COMMAND).enabled)
        self.assertTrue(shell.dispatch(DESIGNER_UNDO_COMMAND))
        self.root.update_idletasks()
        with self.assertRaisesRegex(KeyError, "designer preview node not found"):
            workspace.preview_host.component(clone_id)
        self.assertTrue(workspace.preview_host.component(actions.node_id).exists())
        self.assertTrue(workspace.close())

    def test_designer_shell_menu_presents_and_dispatches_real_tkinter_commands(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(snapshot),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        workspace.select_and_focus_node(actions.node_id)
        shell = DesignerShellCommands(workspace)
        presenter = DesignerShellMenu(shell, TkinterCommandMenuHost(self.root))
        binding = presenter.build()
        generation = workspace.state.preview_generation

        copy_item = binding.items[DESIGNER_COPY_COMMAND]
        copy_item.menu.invoke(copy_item.index)
        self.assertTrue(workspace.state.has_clipboard)
        self.assertEqual(generation, workspace.state.preview_generation)

        duplicate_item = binding.items[DESIGNER_DUPLICATE_COMMAND]
        duplicate_item.menu.invoke(duplicate_item.index)
        self.root.update_idletasks()
        clone_id = actions.node_id + "-copy"
        self.assertTrue(workspace.preview_host.component(clone_id).exists())
        self.assertEqual(generation + 1, workspace.state.preview_generation)

        undo_item = binding.items[DESIGNER_UNDO_COMMAND]
        self.assertTrue(undo_item.menu.entrycget(undo_item.index, "label").startswith("Undo "))
        undo_item.menu.invoke(undo_item.index)
        self.root.update_idletasks()
        with self.assertRaisesRegex(KeyError, "designer preview node not found"):
            workspace.preview_host.component(clone_id)

        self.assertTrue(presenter.dispose())
        self.assertTrue(workspace.close())

    def test_designer_shell_shortcuts_dispatch_real_tkinter_structural_commands(self):
        from app.framework.designer import DesignerIdentityMap, capture_component_tree

        source = ControlColumn((Button("One"), Button("Two"), Button("Three")))
        identities = DesignerIdentityMap(prefix="tk-shortcuts")
        identities.bind(source, "root")
        identities.bind(source.children[0], "one")
        identities.bind(source.children[1], "two")
        identities.bind(source.children[2], "three")
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(capture_component_tree(source, identities=identities)),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        workspace.select_and_focus_node("two")
        shell = DesignerShellCommands(workspace)
        shortcuts = DesignerShellShortcuts(
            shell,
            TkinterDesignerShellShortcutHost(self.root),
        )
        binding = shortcuts.build()
        callbacks = {sequence: callback for sequence, _funcid, callback in binding.metadata["registrations"]}

        self.assertEqual("break", callbacks["<Alt-Down>"]())
        self.root.update_idletasks()
        self.assertEqual(("one", "three", "two"), tuple(child.node.node_id for child in workspace.session.snapshot.root.children))
        self.assertFalse(shell.command(DESIGNER_MOVE_DOWN_COMMAND).enabled)

        self.assertEqual("break", callbacks["<Control-Delete>"]())
        self.root.update_idletasks()
        with self.assertRaises(KeyError):
            workspace.session.node("two")
        self.assertEqual("root", workspace.state.selected_id)
        self.assertFalse(shell.command(DESIGNER_REMOVE_COMMAND).enabled)

        self.assertTrue(shortcuts.dispose())
        self.assertEqual([], binding.metadata["registrations"])
        self.assertTrue(workspace.close())

    def test_designer_component_palette_presents_real_tkinter_entries_and_requests(self):
        from app.framework.designer import DesignerIdentityMap, capture_component_tree

        source = ControlColumn((Label("Status"), Button("Run")))
        identities = DesignerIdentityMap(prefix="tk-palette")
        identities.bind(source, "root")
        identities.bind(source.children[0], "status")
        identities.bind(source.children[1], "run")
        workspace = DesignerWorkspace.create(capture_component_tree(source, identities=identities))
        workspace.select_and_focus_node("run")
        parent = ControlColumn(layout=ControlLayout(width=300, height=240))
        parent.build(renderer=self.renderer)
        requests = []
        palette = DesignerComponentPalette(
            workspace,
            TkinterDesignerComponentPaletteHost(self.renderer, height_rows=6),
            component_keys=("control.label", "control.button", "container.column"),
            on_request=requests.append,
        )
        binding = palette.build(parent=parent.require_item())
        tree = binding.metadata["tree"]
        self.root.update_idletasks()
        self.assertEqual(
            ("control.label", "control.button", "container.column"),
            tuple(binding.items),
        )
        tree.selection_set(binding.items["control.button"])
        tree.focus(binding.items["control.button"])
        binding.metadata["activate_current"]()
        self.root.update()
        self.assertEqual(1, len(requests))
        self.assertEqual("control.button", requests[0].component_type_key)
        self.assertEqual("run", requests[0].target_hint)
        self.assertFalse(workspace.state.can_undo)
        self.assertTrue(palette.dispose())
        self.assertTrue(workspace.close())

    def test_designer_component_placement_presents_real_tkinter_form_and_commits(self):
        from app.framework.designer import DesignerIdentityMap, capture_component_tree

        source = ControlColumn((Label("Status"), Button("Run")))
        identities = DesignerIdentityMap(prefix="tk-placement")
        identities.bind(source, "root")
        identities.bind(source.children[0], "status")
        identities.bind(source.children[1], "run")
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(capture_component_tree(source, identities=identities)),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        workspace.select_and_focus_node("run")
        parent = ControlColumn(layout=ControlLayout(width=360, height=220))
        parent.build(renderer=self.renderer)
        surface = DesignerComponentPlacementSurface(
            workspace,
            TkinterDesignerComponentPlacementHost(self.renderer),
        )
        binding = surface.build(parent=parent.require_item())
        state = surface.begin(
            DesignerComponentInsertRequest("control.label", "Label", "control", "run")
        )
        self.root.update_idletasks()
        self.assertEqual("root", state.parent_id)
        self.assertEqual("children", state.slot_key)
        self.assertEqual("normal", str(binding.fields["commit"].cget("state")))
        inserted_id = surface.commit()
        self.root.update()
        self.assertEqual(inserted_id, workspace.state.selected_id)
        self.assertEqual("Label", workspace.preview_host.preview.component(inserted_id).text)
        self.assertEqual(1, workspace.session.undo_depth)
        self.assertTrue(surface.dispose())
        self.assertTrue(workspace.close())

    def test_designer_hierarchy_panel_presents_real_tkinter_rows_and_dispatches(self):
        first = Label("First")
        run = Button("Run")
        stop = Button("Stop")
        inner = ControlColumn((run, stop))
        root = ControlColumn((first, inner))
        from app.framework.designer import DesignerIdentityMap, capture_component_tree

        identities = DesignerIdentityMap(prefix="tk-hierarchy")
        identities.bind(root, "root")
        identities.bind(first, "first")
        identities.bind(inner, "inner")
        identities.bind(run, "run")
        identities.bind(stop, "stop")
        snapshot = capture_component_tree(root, identities=identities)
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(snapshot),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        hierarchy_parent = ControlColumn(layout=ControlLayout(width=FILL, height=180))
        hierarchy_parent.build(renderer=self.renderer)
        panel = DesignerHierarchyPanel(
            workspace,
            TkinterDesignerHierarchyPanelHost(self.renderer, height_rows=8),
        )
        binding = panel.build(parent=hierarchy_parent.require_item())
        tree = binding.metadata["tree"]
        self.root.update_idletasks()
        generation = workspace.state.preview_generation
        self.assertEqual(("root", "first", "inner"), tuple(binding.rows))

        tree.focus(binding.rows["inner"])
        tree.event_generate("<<TreeviewOpen>>")
        self.root.update()
        self.assertIn("run", binding.rows)
        self.assertIn("stop", binding.rows)
        self.assertEqual(("root", "inner"), workspace.state.expanded_ids)
        self.assertEqual(generation, workspace.state.preview_generation)

        tree.selection_set(binding.rows["run"])
        tree.event_generate("<<TreeviewSelect>>")
        self.root.update()
        self.assertEqual("run", workspace.state.selected_id)
        self.assertEqual("run", workspace.state.focused_id)
        self.assertEqual(generation, workspace.state.preview_generation)

        tree.focus(binding.rows["inner"])
        tree.event_generate("<<TreeviewClose>>")
        self.root.update()
        self.assertNotIn("run", binding.rows)
        self.assertEqual(("root",), workspace.state.expanded_ids)
        self.assertTrue(panel.dispose())
        self.assertTrue(workspace.close())

    def test_designer_preview_selection_clicks_real_tkinter_preview_and_highlights(self):
        from app.framework.designer import DesignerIdentityMap, capture_component_tree

        first = Label("First")
        run = Button("Run")
        inner = ControlColumn((run,))
        root = ControlColumn((first, inner))
        identities = DesignerIdentityMap(prefix="tk-preview-select")
        identities.bind(root, "root")
        identities.bind(first, "first")
        identities.bind(inner, "inner")
        identities.bind(run, "run")
        snapshot = capture_component_tree(root, identities=identities)
        preview_parent = ControlColumn(layout=ControlLayout(width=FILL, height=220))
        preview_parent.build(renderer=self.renderer)
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(snapshot),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
            parent=preview_parent.require_item(),
        )
        workspace.select_and_focus_node("first")
        surface = DesignerPreviewSelectionSurface(
            workspace,
            TkinterDesignerPreviewSelectionHost(self.renderer),
        )
        binding = surface.build(parent=preview_parent.require_item())
        self.root.deiconify()
        self.root.update_idletasks()
        generation = workspace.state.preview_generation

        run_item = binding.targets["run"]
        run_widget = self.renderer.native_widget(run_item)
        run_widget.event_generate("<Button-1>")
        self.root.update()
        self.assertEqual("run", workspace.state.selected_id)
        self.assertEqual("run", workspace.state.focused_id)
        self.assertIn("inner", workspace.state.expanded_ids)
        self.assertEqual(generation, workspace.state.preview_generation)
        self.assertEqual(2, int(run_item.mount.cget("highlightthickness")))

        first_item = binding.targets["first"]
        self.assertEqual(0, int(first_item.mount.cget("highlightthickness")))
        self.assertTrue(surface.dispose())
        self.assertEqual(0, int(run_item.mount.cget("highlightthickness")))
        self.assertTrue(workspace.close())

    def test_designer_preview_selection_rebinds_after_real_tkinter_replacement(self):
        from app.framework.designer import DesignerIdentityMap, capture_component_tree

        action = Button("Run")
        root = ControlColumn((Label("Status"), action))
        identities = DesignerIdentityMap(prefix="tk-preview-rebind")
        identities.bind(root, "root")
        identities.bind(action, "action")
        snapshot = capture_component_tree(root, identities=identities)
        preview_parent = ControlColumn(layout=ControlLayout(width=FILL, height=220))
        preview_parent.build(renderer=self.renderer)
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(snapshot),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
            parent=preview_parent.require_item(),
        )
        workspace.select_and_focus_node("action")
        surface = DesignerPreviewSelectionSurface(
            workspace,
            TkinterDesignerPreviewSelectionHost(self.renderer),
        )
        binding = surface.build(parent=preview_parent.require_item())
        self.root.deiconify()
        self.root.update_idletasks()
        old_item = binding.targets["action"]
        old_generation = workspace.state.preview_generation

        self.assertTrue(workspace.set_selected_property("label", "Changed"))
        self.root.update_idletasks()
        self.assertGreater(workspace.state.preview_generation, old_generation)
        surface.refresh()
        new_item = binding.targets["action"]
        self.assertIsNot(old_item, new_item)
        self.assertFalse(self.renderer.exists(old_item))
        self.assertTrue(self.renderer.exists(new_item))
        self.assertEqual(2, int(new_item.mount.cget("highlightthickness")))

        self.renderer.native_widget(new_item).event_generate("<Button-1>")
        self.root.update()
        self.assertEqual("action", workspace.state.selected_id)
        self.assertTrue(surface.dispose())
        self.assertTrue(workspace.close())

    def test_designer_preview_defaults_and_explicit_resize_render_real_tkinter(self):
        from app.framework.designer import DesignerIdentityMap, capture_component_tree

        action = Button("Run")
        root = ControlColumn((action,))
        identities = DesignerIdentityMap(prefix="tk-preview-size")
        identities.bind(root, "root")
        identities.bind(action, "action")
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(capture_component_tree(root, identities=identities)),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        workspace.select_and_focus_node("action")
        self.root.update_idletasks()
        item = workspace.preview_host.selected_component.require_item()
        self.assertEqual(120, int(item.mount.cget("width")))
        self.assertEqual(28, int(item.mount.cget("height")))

        self.assertTrue(workspace.set_selected_property("layout.width", 196))
        self.assertTrue(workspace.set_selected_property("layout.height", 36))
        self.root.update_idletasks()
        item = workspace.preview_host.selected_component.require_item()
        self.assertEqual(196, int(item.mount.cget("width")))
        self.assertEqual(36, int(item.mount.cget("height")))

        self.assertTrue(workspace.clear_selected_property("layout.width"))
        self.assertTrue(workspace.clear_selected_property("layout.height"))
        self.root.update_idletasks()
        item = workspace.preview_host.selected_component.require_item()
        self.assertEqual(120, int(item.mount.cget("width")))
        self.assertEqual(28, int(item.mount.cget("height")))
        self.assertTrue(workspace.close())

    def test_designer_inspector_panel_presents_real_tkinter_editors_and_dispatches(self):
        from app.framework.designer import DesignerIdentityMap, capture_component_tree

        action = Button("Run", layout=ControlLayout(width=120, height=30, spacing=4))
        root = ControlColumn((Label("Status"), action))
        identities = DesignerIdentityMap(prefix="tk-inspector")
        identities.bind(root, "root")
        identities.bind(action, "action")
        snapshot = capture_component_tree(root, identities=identities)
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(snapshot),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        workspace.select_and_focus_node("action")
        parent = ControlColumn(layout=ControlLayout(width=FILL, height=260))
        parent.build(renderer=self.renderer)
        panel = DesignerInspectorPanel(
            workspace,
            TkinterDesignerInspectorPanelHost(self.renderer, height=220),
        )
        binding = panel.build(parent=parent.require_item())
        self.root.update_idletasks()
        generation = workspace.state.preview_generation
        self.assertIn("label", binding.rows)
        self.assertIn("layout.width", binding.rows)
        self.assertIn("enabled", binding.rows)

        binding.metadata["variables"]["label"].set("Tk Inspector")
        binding.metadata["apply_buttons"]["label"].invoke()
        self.root.update()
        self.assertEqual("Tk Inspector", workspace.state.inspector.row("label").value)
        self.assertEqual(generation + 1, workspace.state.preview_generation)
        self.assertEqual("Tk Inspector", workspace.preview_host.selected_component.label)

        binding.metadata["clear_buttons"]["layout.width"].invoke()
        self.root.update()
        self.assertFalse(workspace.state.inspector.row("layout.width").is_set)
        self.assertGreaterEqual(binding.rows["layout.height"].winfo_width(), 120)

        binding.metadata["clear_buttons"]["layout.height"].invoke()
        self.root.update()
        self.assertFalse(workspace.state.inspector.row("layout.height").is_set)
        self.assertGreaterEqual(binding.rows["layout.spacing"].winfo_width(), 120)

        binding.metadata["clear_buttons"]["layout.spacing"].invoke()
        self.root.update()
        self.assertFalse(workspace.state.inspector.row("layout.spacing").is_set)
        self.assertGreaterEqual(binding.rows["label"].winfo_width(), 120)

        enabled_var = binding.metadata["variables"]["enabled"]
        self.assertTrue(bool(enabled_var.get()))
        binding.rows["enabled"].invoke()
        self.root.update()
        self.assertFalse(workspace.state.inspector.row("enabled").value)
        self.assertTrue(panel.dispose())
        self.assertTrue(workspace.close())

    def test_designer_hierarchy_selection_retargets_real_tkinter_inspector_panel(self):
        from app.framework.designer import DesignerIdentityMap, capture_component_tree

        first = Label("First")
        run = Button("Run")
        inner = ControlColumn((run,))
        root = ControlColumn((first, inner))
        identities = DesignerIdentityMap(prefix="tk-surface-sync")
        identities.bind(root, "root")
        identities.bind(first, "first")
        identities.bind(inner, "inner")
        identities.bind(run, "run")
        snapshot = capture_component_tree(root, identities=identities)
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(snapshot),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        workspace.select_and_focus_node("first")
        left = ControlColumn(layout=ControlLayout(width=280, height=240))
        right = ControlColumn(layout=ControlLayout(width=320, height=240))
        left.build(renderer=self.renderer)
        right.build(renderer=self.renderer)
        inspector = DesignerInspectorPanel(
            workspace,
            TkinterDesignerInspectorPanelHost(self.renderer, height=200),
        )
        inspector_binding = inspector.build(parent=right.require_item())
        hierarchy = DesignerHierarchyPanel(
            workspace,
            TkinterDesignerHierarchyPanelHost(self.renderer, height_rows=8),
            on_change=inspector.refresh,
        )
        hierarchy_binding = hierarchy.build(parent=left.require_item())
        tree = hierarchy_binding.metadata["tree"]
        self.root.update_idletasks()
        self.assertEqual("first", inspector.state.node_id)
        self.assertIn("text", inspector_binding.rows)

        tree.focus(hierarchy_binding.rows["inner"])
        tree.event_generate("<<TreeviewOpen>>")
        self.root.update()
        tree.selection_set(hierarchy_binding.rows["run"])
        tree.event_generate("<<TreeviewSelect>>")
        self.root.update()
        self.assertEqual("run", inspector.state.node_id)
        self.assertIn("label", inspector_binding.rows)
        self.assertNotIn("text", inspector_binding.rows)
        self.assertTrue(hierarchy.dispose())
        self.assertTrue(inspector.dispose())
        self.assertTrue(workspace.close())

    def test_designer_inspector_actions_remain_inside_narrow_panel_after_refresh(self):
        from app.framework.designer import DesignerIdentityMap, capture_component_tree

        action = Button("Run", layout=ControlLayout(width=120, height=30, spacing=4))
        source = ControlColumn((action,))
        identities = DesignerIdentityMap(prefix="tk-inspector-narrow")
        identities.bind(source, "root")
        identities.bind(action, "action")
        snapshot = capture_component_tree(source, identities=identities)
        workspace = DesignerWorkspace(
            DesignerProjectFile.create(snapshot),
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        workspace.select_and_focus_node("action")
        parent = ControlColumn(layout=ControlLayout(width=320, height=300))
        parent.build(renderer=self.renderer)
        panel = DesignerInspectorPanel(
            workspace,
            TkinterDesignerInspectorPanelHost(self.renderer, height=260),
        )
        binding = panel.build(parent=parent.require_item())
        self.root.deiconify()
        self.root.update()

        def assert_actions_visible():
            canvas = binding.metadata["canvas"]
            self.root.update_idletasks()
            right_edge = canvas.winfo_rootx() + canvas.winfo_width()
            for buttons in (
                binding.metadata["apply_buttons"],
                binding.metadata["none_buttons"],
                binding.metadata["clear_buttons"],
            ):
                for button in buttons.values():
                    self.assertLessEqual(
                        button.winfo_rootx() + button.winfo_width(),
                        right_edge + 1,
                    )

        assert_actions_visible()
        binding.metadata["clear_buttons"]["layout.width"].invoke()
        self.root.update()
        assert_actions_visible()
        binding.metadata["clear_buttons"]["layout.height"].invoke()
        self.root.update()
        assert_actions_visible()
        binding.metadata["clear_buttons"]["layout.spacing"].invoke()
        self.root.update()
        assert_actions_visible()
        self.assertTrue(panel.dispose())
        self.assertTrue(workspace.close())

    def test_designer_preview_resize_sizegrip_commits_one_real_tkinter_edit(self):
        from app.engine.designer_preview_resize_hosts import TkinterDesignerPreviewResizeHost
        from app.framework.components import SectionPanel
        from app.framework.designer import DesignerIdentityMap, capture_component_tree
        from app.framework.designer_preview_resize import DesignerPreviewResizeSurface

        action = Button("Run")
        source = ControlColumn((action,))
        identities = DesignerIdentityMap(prefix="tk-resize")
        identities.bind(source, "root")
        identities.bind(action, "action")
        snapshot = capture_component_tree(source, identities=identities)
        preview_parent = SectionPanel(
            "Preview",
            (),
            separated=False,
            border=False,
            layout=ControlLayout(width=360, height=220),
        )
        preview_parent.build(renderer=self.renderer)
        workspace = DesignerWorkspace.create(
            snapshot,
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
            parent=preview_parent.require_item(),
        )
        workspace.select_and_focus_node("action")
        surface = DesignerPreviewResizeSurface(
            workspace,
            TkinterDesignerPreviewResizeHost(self.renderer),
        )
        binding = surface.build(parent=preview_parent.require_item())
        # The replacement designer handle is an ordinary child widget rather
        # than ttk.Sizegrip. Map the test window so synthetic pointer events are
        # delivered, and prove the outer window geometry remains unchanged.
        self.root.deiconify()
        self.root.update()
        root_size = (self.root.winfo_width(), self.root.winfo_height())
        handle = binding.metadata["handle"]
        self.assertEqual("Frame", handle.winfo_class())
        self.assertEqual("#555555", handle.cget("background"))
        self.assertTrue(handle.winfo_manager())
        start_width = int(surface.target.width)
        start_height = int(surface.target.height)
        handle.event_generate("<ButtonPress-1>", x=4, y=4)
        self.root.update()
        handle.event_generate("<B1-Motion>", x=44, y=24)
        self.root.update()
        handle.event_generate("<ButtonRelease-1>", x=44, y=24)
        self.root.update()
        self.assertEqual(1, workspace.session.undo_depth)
        self.assertEqual("Resize component", workspace.state.undo_label)
        self.assertGreaterEqual(workspace.session.node("action").properties["layout.width"], start_width + 30)
        self.assertGreaterEqual(workspace.session.node("action").properties["layout.height"], start_height + 10)
        self.assertEqual("action", workspace.state.selected_id)
        self.assertEqual(root_size, (self.root.winfo_width(), self.root.winfo_height()))
        self.assertTrue(surface.dispose())
        self.assertTrue(workspace.close())

    def test_designer_shell_example_runs_tkinter_backend_and_auto_closes(self):
        example = PROJECT_ROOT / "examples" / "ecosystem_designer_shell.py"
        result = subprocess.run(
            [
                sys.executable,
                str(example),
                "--ui-backend",
                "tkinter",
                "--smoke-seconds",
                "0.15",
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_preview_host_duplicate_rebuilds_real_tkinter_tree_with_fresh_identity(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        session = DesignerEditSession(snapshot)
        preview_host = DesignerPreviewHost(
            session,
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
            renderer=self.renderer,
        )
        self.root.update_idletasks()
        old_root = preview_host.preview.root
        self.assertTrue(old_root.exists())

        self.assertTrue(preview_host.duplicate_node(actions.node_id))
        self.root.update_idletasks()
        clone_id = f"{actions.node_id}-copy"
        self.assertFalse(old_root.exists())
        self.assertTrue(preview_host.component(clone_id).exists())
        self.assertEqual("Actions", preview_host.component(clone_id).label)
        self.assertEqual(2, preview_host.generation)

        self.assertTrue(preview_host.undo())
        self.root.update_idletasks()
        with self.assertRaises(KeyError):
            preview_host.component(clone_id)
        self.assertEqual(3, preview_host.generation)
        preview_host.close()

    def test_reconstructed_blank_snapshot_builds_through_real_tkinter_renderer(self):
        from app.engine.presentation_backends import create_dearpygui_backend
        from examples.ecosystem_blank_app import DemoView

        class SnapshotHost:
            presentation = create_dearpygui_backend()

        snapshot = DemoView(SnapshotHost()).capture_designer_snapshot()
        preview = reconstruct_designer_snapshot(
            snapshot,
            context=DesignerPreviewContext(
                layout_coordinator=LayoutCoordinator(TkinterLayoutHost(self.renderer))
            ),
        )
        preview.root.build(renderer=self.renderer)
        self.root.update_idletasks()
        self.assertTrue(preview.root.exists())
        actions = next(
            node
            for node in snapshot.root.walk()
            if node.type_key == "control.button" and node.properties.get("label") == "Actions"
        )
        self.assertTrue(preview.component(actions.node_id).exists())

    def test_common_component_tree_builds_and_round_trips_values(self):
        name = TextInput(default_value="Ada", layout=ControlLayout(width=180))
        mode = ComboBox(("One", "Two"), default_value="One")
        count = NumericStepper(kind=NumericKind.INTEGER, default_value=3)
        enabled = CheckBox("Enabled", default_value=True)
        progress = ProgressBar(default_value=0.25, overlay="25%")
        root = ControlColumn((Label("Demo"), name, mode, count, enabled, progress))
        root.build(renderer=self.renderer)
        self.root.update_idletasks()

        self.assertEqual(name.get_value(), "Ada")
        self.assertEqual(mode.get_value(), "One")
        self.assertEqual(int(count.get_value()), 3)
        self.assertTrue(bool(enabled.get_value()))
        self.assertAlmostEqual(float(progress.get_value()), 0.25)

        name.set_value("Grace")
        mode.set_value("Two")
        count.set_value(7)
        enabled.set_value(False)
        progress.set_value(0.75)
        progress.set_overlay("75%")
        self.assertEqual(name.get_value(), "Grace")
        self.assertEqual(mode.get_value(), "Two")
        self.assertEqual(int(count.get_value()), 7)
        self.assertFalse(bool(enabled.get_value()))
        self.assertAlmostEqual(float(progress.get_value()), 0.75)

        value_items = (name.require_item(), mode.require_item(), count.require_item(), enabled.require_item(), progress.require_item())
        self.renderer.close()
        self.assertTrue(self.renderer.closed)
        self.assertTrue(all(item.value_var is None for item in value_items))

    def test_button_dispatches_normalized_component_event(self):
        received = []
        button = Button("Run", callback=received.append, event_data={"id": 4})
        button.build(renderer=self.renderer)
        self.renderer.native_widget(button.require_item()).invoke()
        self.assertEqual(len(received), 1)
        self.assertIs(received[0].source, button)
        self.assertEqual(received[0].event_type, ComponentEventType.ACTIVATE)
        self.assertEqual(received[0].data, {"id": 4})

    def test_combo_items_visibility_enabled_state_and_disposal_are_backend_neutral(self):
        combo = ComboBox(("A", "B"), default_value="A")
        combo.build(renderer=self.renderer)
        combo.set_items(("B", "C"))
        widget = self.renderer.native_widget(combo.require_item())
        self.assertEqual(tuple(widget.cget("values")), ("B", "C"))

        combo.set_enabled(False)
        self.assertIn("disabled", widget.state())
        combo.set_enabled(True)
        self.assertNotIn("disabled", widget.state())

        mount = combo.require_item().mount
        combo.set_visible(False)
        self.assertEqual(mount.winfo_manager(), "")
        combo.set_visible(True)
        self.assertTrue(mount.winfo_manager())
        self.assertTrue(combo.dispose())
        self.assertFalse(combo.exists())

    def test_grid_and_dialog_composition_build_without_toolkit_leaks(self):
        grid = ControlGrid(
            ((Label("Name"), TextInput(default_value="Ada")),),
            column_widths=(90, 180),
        )
        grid.build(renderer=self.renderer)
        dialog = Dialog(
            "Example",
            (Label("Hello"),),
            show=False,
            minimum_size=(240, 120),
        )
        dialog.build(renderer=self.renderer)
        self.assertTrue(grid.exists())
        self.assertTrue(dialog.exists())
        dialog.show_centered()
        self.root.update_idletasks()
        widget = self.renderer.native_widget(dialog.require_item())
        self.assertNotEqual(str(widget.state()), "withdrawn")
        dialog.dispose()

    def test_tooltip_attachment_is_supported_by_compatibility_renderer(self):
        label = Label("Hover")
        label.build(renderer=self.renderer)
        tooltip = self.renderer.attach_tooltip(label.require_item(), "Details", wrap=220)
        self.assertIsNotNone(tooltip)
        tooltip.destroy()

    def test_control_column_natural_cross_axis_preserves_independent_child_widths(self):
        wide = Button("Wide", layout=ControlLayout(width=220, height=28))
        narrow = Button("Narrow", layout=ControlLayout(width=100, height=28))
        column = ControlColumn(
            (wide, narrow),
            layout=ControlLayout(width=300, height=100),
        )
        column.build(renderer=self.renderer)
        self.root.deiconify()
        self.root.update_idletasks()

        wide_width = wide.require_item().mount.winfo_width()
        narrow_width = narrow.require_item().mount.winfo_width()
        self.assertGreater(wide_width, narrow_width)
        self.assertGreaterEqual(wide_width, 200)
        self.assertLessEqual(narrow_width, 120)

    def test_control_column_cross_axis_stretch_is_explicit_opt_in(self):
        first = Button("One", layout=ControlLayout(width=220, height=28))
        second = Button("Two", layout=ControlLayout(width=100, height=28))
        column = ControlColumn(
            (first, second),
            cross_axis=STRETCH,
            layout=ControlLayout(width=300, height=100),
        )
        column.build(renderer=self.renderer)
        self.root.deiconify()
        self.root.update_idletasks()

        first_width = first.require_item().mount.winfo_width()
        second_width = second.require_item().mount.winfo_width()
        self.assertGreater(first_width, 250)
        self.assertEqual(first_width, second_width)

    def test_layout_coordinator_uses_tkinter_host_without_framework_changes(self):
        column = ControlColumn((Label("Sized"),), layout=ControlLayout(width=FILL))
        column.build(renderer=self.renderer)
        self.root.deiconify()
        self.root.update_idletasks()
        coordinator = LayoutCoordinator(TkinterLayoutHost(self.renderer))
        width, height = coordinator.item_size(column.require_item())
        self.assertGreaterEqual(width, 0)
        self.assertGreaterEqual(height, 0)
        self.assertTrue(coordinator.width(column.require_item(), 260))

    def test_scene_registry_switches_tkinter_containers_through_same_contract(self):
        first = ControlColumn((Label("First"),))
        second = ControlColumn((Label("Second"),))
        first.build(renderer=self.renderer)
        second.build(renderer=self.renderer)
        registry = SceneRegistry(TkinterSceneHost(self.renderer))
        registry.register("first", object(), container=first.require_item())
        registry.register("second", object(), container=second.require_item())
        self.assertTrue(registry.activate("first"))
        self.assertTrue(first.require_item().mount.winfo_manager())
        self.assertEqual(second.require_item().mount.winfo_manager(), "")
        self.assertTrue(registry.activate("second"))
        self.assertEqual(first.require_item().mount.winfo_manager(), "")
        self.assertTrue(second.require_item().mount.winfo_manager())

    def test_realtime_graph_renders_through_tkinter_canvas_host(self):
        parent = ControlColumn(layout=ControlLayout(width=FILL, height=220))
        parent.build(renderer=self.renderer)
        graph = RealtimeGraph(
            TkinterPlotHost(self.renderer),
            (PlotSeriesSpec("one", "One"), PlotSeriesSpec("two", "Two")),
        )
        graph.build(
            parent=parent.require_item(),
            x_label="Seconds",
            y_label="Value",
            width=420,
            height=180,
        )
        graph.render(
            PlotFrame(
                x_limits=(-2, 0),
                y_limits=(0, 10),
                y_label="Units",
                series=(
                    PlotSeriesData("one", (-2, -1, 0), (1, 4, 2)),
                    PlotSeriesData("two", (-2, -1, 0), (3, 2, 8)),
                ),
            )
        )
        self.root.deiconify()
        self.root.update_idletasks()
        binding = graph.require_binding()
        self.assertGreater(len(binding.plot.canvas.find_all()), 0)
        graph.clear()
        graph.dispose()
        self.assertFalse(graph.exists())


    def test_live_table_renders_updates_reorders_and_removes_rows(self):
        parent = ControlColumn(layout=ControlLayout(width=FILL, height=180))
        parent.build(renderer=self.renderer)
        table = LiveTable(
            TkinterTableHost(self.renderer),
            (
                TableColumnSpec("name", "Name", "stretch", 0.6),
                TableColumnSpec("state", "State", "fixed", 90),
            ),
        )
        binding = table.build(parent=parent.require_item(), height=140)
        table.render(
            TableFrame((
                TableRow("a", (TableCell("Alpha"), TableCell("Ready"))),
                TableRow("b", (TableCell("Beta"), TableCell("Busy"))),
            ))
        )
        self.root.deiconify()
        self.root.update_idletasks()
        self.assertEqual(table.row_count, 2)
        self.assertEqual(tuple(binding.table.item(item, "values") for item in binding.table.get_children()), (("Alpha", "Ready"), ("Beta", "Busy")))

        table.render(
            TableFrame((
                TableRow("b", (TableCell("Beta"), TableCell("Idle"))),
                TableRow("c", (TableCell("Gamma"), TableCell("Ready"))),
            ))
        )
        self.root.update_idletasks()
        self.assertEqual(table.row_count, 2)
        self.assertEqual(tuple(binding.table.item(item, "values") for item in binding.table.get_children()), (("Beta", "Idle"), ("Gamma", "Ready")))
        table.dispose()
        self.assertFalse(table.exists())

    def test_state_grid_renders_through_tkinter_canvas_host(self):
        parent = ControlColumn(layout=ControlLayout(width=FILL, height=90))
        parent.build(renderer=self.renderer)
        grid = StateGrid(TkinterStateGridHost(self.renderer))
        binding = grid.build(parent=parent.require_item(), height=70, minimum_columns=4, maximum_columns=8, minimum_cell_width=10)
        grid.render(
            StateGridFrame(
                StateGridCell(str(index), (20 + index * 10, 120, 180))
                for index in range(8)
            )
        )
        self.root.deiconify()
        self.root.update_idletasks()
        self.assertGreater(len(binding.grid.canvas.find_all()), 0)
        grid.clear()
        self.root.update_idletasks()
        self.assertEqual(len(binding.grid.canvas.find_all()), 0)
        grid.dispose()
        self.assertFalse(grid.exists())

    def test_mixed_layout_places_children_locally_and_reserves_grid_extent(self):
        panel = PositionedPanel(
            (
                positioned(Label("Local"), x=20, y=16),
                positioned(Button("Action", layout=ControlLayout(width=90, height=28)), x=150, y=52),
            ),
            layout=ControlLayout(width=280, height=110),
            padding=6,
        )
        wrapped = PlacedComponent(panel, x=40, y=25)
        grid = ControlGrid(((Label("Automatic"), wrapped),), column_widths=(100, 120))
        grid.build(renderer=self.renderer)
        self.root.deiconify()
        self.root.update_idletasks()

        panel_item = panel.require_item()
        panel_mount = panel_item.mount or panel_item.widget
        self.assertEqual("place", panel.children[0].component.require_item().geometry_manager)
        self.assertEqual("place", panel.children[1].component.require_item().geometry_manager)
        self.assertGreaterEqual(int(panel_mount.winfo_width()), 280)
        self.assertEqual((320, 135), wrapped.occupied_size)


    def test_tab_container_uses_same_keyed_selection_contract(self):
        seen = []
        tabs = TabContainer(
            (
                TabPage("one", "One", (Label("First"),)),
                TabPage("two", "Two", (Label("Second"),)),
            ),
            callback=lambda event: seen.append(event.value),
            layout=ControlLayout(width=FILL, height=180),
        )
        tabs.build(renderer=self.renderer)
        self.root.deiconify()
        self.root.update_idletasks()

        tabs.select("two", notify=True)
        self.root.update_idletasks()
        self.assertEqual("two", tabs.selected_key())
        self.assertEqual(["two"], seen)
        tabs.select("one")
        self.root.update_idletasks()
        self.assertEqual("one", tabs.selected_key())

    def test_split_panel_reflows_real_tkinter_panes(self):
        coordinator = LayoutCoordinator(TkinterLayoutHost(self.renderer))
        split = SplitPanel(
            (
                SplitPane("left", Label("Left"), weight=1, minimum=120, border=True),
                SplitPane("right", Label("Right"), weight=2, minimum=180, border=True),
            ),
            gap=6,
            coordinator=coordinator,
            layout=ControlLayout(width=600, height=160),
        )
        split.build(renderer=self.renderer)
        self.root.deiconify()
        self.root.update_idletasks()
        sizes = split.reflow()
        self.root.update_idletasks()

        self.assertEqual(2, len(sizes))
        self.assertGreater(sizes[1], sizes[0])
        left = self.renderer.native_widget(split.pane_item("left"))
        right = self.renderer.native_widget(split.pane_item("right"))
        self.assertGreaterEqual(int(left.winfo_width()), 1)
        self.assertGreaterEqual(int(right.winfo_width()), 1)

    def test_non_measuring_overlay_does_not_expand_tkinter_positioned_panel(self):
        base = Label("Base", layout=ControlLayout(width=120, height=30))
        badge = Button("Overlay", layout=ControlLayout(width=80, height=24))
        panel = PositionedPanel(
            (
                positioned(base, x=10, y=10),
                overlay(badge, x=500, y=300),
            ),
            padding=5,
        )
        panel.build(renderer=self.renderer)
        self.root.deiconify()
        self.root.update_idletasks()

        self.assertEqual((140, 50), panel.occupied_size)
        self.assertEqual("place", badge.require_item().geometry_manager)


    def test_anchored_positioned_panel_reflows_real_tkinter_children(self):
        coordinator = LayoutCoordinator(TkinterLayoutHost(self.renderer))
        pinned = Button("Pinned", layout=ControlLayout(width=80, height=24))
        stretched = Button("Stretch", layout=ControlLayout(height=26))
        panel = PositionedPanel(
            (
                anchored_overlay(
                    pinned,
                    horizontal=AxisAnchor.END,
                    vertical=AxisAnchor.START,
                    margin=10,
                ),
                anchored(
                    stretched,
                    horizontal=AxisAnchor.STRETCH,
                    vertical=AxisAnchor.END,
                    margin=(18, 8, 18, 8),
                    constraints=SizeConstraints(minimum_width=120, maximum_width=320),
                ),
            ),
            padding=5,
            fit_content=False,
            coordinator=coordinator,
            layout=ControlLayout(width=420, height=150),
        )
        panel.build(renderer=self.renderer)
        self.root.deiconify()
        self.root.update_idletasks()
        panel.reflow()
        self.root.update_idletasks()

        pinned_mount = pinned.require_item().mount
        stretched_mount = stretched.require_item().mount
        self.assertEqual("place", pinned.require_item().geometry_manager)
        self.assertEqual("place", stretched.require_item().geometry_manager)
        self.assertGreaterEqual(int(pinned_mount.winfo_x()), 250)
        self.assertGreaterEqual(int(stretched_mount.winfo_width()), 120)
        self.assertLessEqual(int(stretched_mount.winfo_width()), 320)

    def test_tkinter_command_menu_uses_same_semantic_command_tree(self):
        seen = []
        menu = CommandMenu(
            TkinterCommandMenuHost(self.root),
            title="Actions",
            on_command=seen.append,
        )
        commands = CommandSet((
            CommandSpec("run", "Run"),
            CommandSpec("mode", "Mode", children=(
                CommandSpec("mode:a", "A", checked=True),
                CommandSpec("mode:b", "B", checked=False),
            )),
        ))
        binding = menu.build(commands)
        self.assertTrue(menu.exists())
        item = binding.items["run"]
        checked_item = binding.items["mode:a"]
        item.menu.invoke(item.index)
        self.assertEqual(["run"], seen)
        menu.update(CommandSet((
            CommandSpec("run", "Run", enabled=False),
            CommandSpec("mode", "Mode", children=(
                CommandSpec("mode:a", "A", checked=False),
                CommandSpec("mode:b", "B", checked=True),
            )),
        )))
        self.assertTrue(menu.dispose())
        self.assertFalse(menu.exists())
        self.assertIsNone(checked_item.variable)
        self.assertEqual({}, binding.items)

    def test_blank_application_demo_runs_tkinter_backend_and_auto_closes(self):
        example = PROJECT_ROOT / "examples" / "ecosystem_blank_app.py"
        result = subprocess.run(
            [
                sys.executable,
                str(example),
                "--ui-backend",
                "tkinter",
                "--smoke-seconds",
                "0.15",
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_tkinter_application_host_drives_shared_runtime_and_closes_cleanly(self):
        root = self.root
        runtime = ApplicationRuntime()
        updates = []
        host = TkinterApplicationHost(
            ApplicationSpec("HostProbe", width=500, height=360),
            runtime=runtime,
            root=root,
        )
        runtime.services.register("probe", CallbackService(on_update=updates.append))
        host.build(ControlColumn((Label("Host"), Button("Stop", callback=lambda _e: host.request_stop()))))
        root.deiconify()
        root.after(80, host.request_stop)
        self.assertIsInstance(host, ApplicationHost)
        self.assertEqual(host.run(), 0)
        self.assertTrue(host.component_renderer.closed)
        self.root = None  # host owns/destroys the supplied root
        self.assertGreaterEqual(len(updates), 1)
        self.assertEqual(runtime.state, RuntimeState.STOPPED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
