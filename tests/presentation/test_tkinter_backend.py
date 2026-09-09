from __future__ import annotations

import ast
import gc
import subprocess
import sys
import unittest

from tests.helpers import PROJECT_ROOT

from app.engine.application_hosts.tkinter import TkinterApplicationHost
from app.engine.command_menu_hosts import TkinterCommandMenuHost
from app.engine.component_renderers import TkinterRenderer
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
    TabContainer,
    TabPage,
    anchored,
    anchored_overlay,
    overlay,
    positioned,
)
from app.framework.command_menu import CommandMenu, CommandMenuHost
from app.framework.designer_editing import DesignerEditSession
from app.framework.designer_preview import DesignerPreviewContext, reconstruct_designer_snapshot
from app.framework.designer_preview_host import DesignerPreviewHost
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
        self.assertIsInstance(self.renderer, ComponentRenderer)
        self.assertIsInstance(layout_host, LayoutHost)
        self.assertIsInstance(scene_host, SceneHost)
        self.assertIsInstance(plot_host, PlotHost)
        self.assertIsInstance(table_host, TableHost)
        self.assertIsInstance(state_grid_host, StateGridHost)
        self.assertIsInstance(command_menu_host, CommandMenuHost)

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
