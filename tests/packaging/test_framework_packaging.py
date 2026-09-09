"""Framework packaging and relocation regressions.

Regression lineage:
- introduced during the post-v0.4.0 GUI/RAD framework extraction.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.helpers import PROJECT_ROOT


FRAMEWORK_ROOT = PROJECT_ROOT / "app" / "framework"


class FrameworkPackagingTests(unittest.TestCase):
    def _framework_python_files(self):
        return sorted(FRAMEWORK_ROOT.rglob("*.py"))

    def test_framework_internal_imports_are_package_relative(self):
        offenders = []
        for path in self._framework_python_files():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level == 0 and (
                        module == "app.framework" or module.startswith("app.framework.")
                    ):
                        offenders.append(
                            f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: from {module}"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "app.framework" or alias.name.startswith(
                            "app.framework."
                        ):
                            offenders.append(
                                f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: import {alias.name}"
                            )
        self.assertEqual([], offenders)

    def test_framework_absolute_dependencies_are_standard_library_only(self):
        third_party = []
        stdlib = set(sys.stdlib_module_names)

        for path in self._framework_python_files():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names.append(node.module)
                elif isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)

                for name in names:
                    root = name.split(".", 1)[0]
                    if root not in stdlib and root != "__future__":
                        third_party.append(
                            f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: {name}"
                        )

        self.assertEqual([], third_party)

    def test_framework_tree_imports_after_copy_and_package_rename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            relocated = temp_root / "portable_framework"
            shutil.copytree(FRAMEWORK_ROOT, relocated)

            probe = textwrap.dedent(
                f"""
                import importlib
                import pkgutil
                import sys

                sys.path.insert(0, {str(temp_root)!r})
                package = importlib.import_module("portable_framework")
                imported = [package.__name__]
                for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
                    importlib.import_module(module.name)
                    imported.append(module.name)

                assert "portable_framework.components" in imported
                assert "portable_framework.documentation" in imported
                assert "portable_framework.designer" in imported
                assert "portable_framework.designer_clipboard" in imported
                assert "portable_framework.designer_editing" in imported
                assert "portable_framework.designer_structure" in imported
                assert "portable_framework.designer_preview" in imported
                assert "portable_framework.designer_preview_host" in imported
                assert "portable_framework.designer_preview_selection" in imported
                assert "portable_framework.designer_component_palette" in imported
                assert "portable_framework.designer_project" in imported
                assert "portable_framework.designer_hierarchy" in imported
                assert "portable_framework.designer_inspector" in imported
                assert "portable_framework.designer_workspace" in imported
                assert "portable_framework.designer_shell" in imported
                assert "portable_framework.designer_shell_menu" in imported
                assert "portable_framework.designer_hierarchy_panel" in imported
                assert "portable_framework.designer_inspector_panel" in imported
                assert "portable_framework.designer_navigation" in imported
                assert "portable_framework.designer_selection" in imported
                assert "portable_framework.geometry" in imported
                assert "portable_framework.components.regions" in imported
                assert "portable_framework.live_data" in imported
                assert "portable_framework.command_menu" in imported
                assert "portable_framework.data_view" in imported
                assert "portable_framework.interactions" in imported
                assert "portable_framework.telemetry" in imported
                assert "portable_framework.visualization" in imported
                assert "portable_framework.property_cascade" in imported
                assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
                assert not any(name == "dearpygui" or name.startswith("dearpygui.") for name in sys.modules)
                print(len(imported))
                """
            )

            result = subprocess.run(
                [sys.executable, "-I", "-c", probe],
                cwd=temp_root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)
            self.assertGreaterEqual(int(result.stdout.strip()), 25)

    def test_relocated_framework_contracts_are_usable_without_application_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copytree(FRAMEWORK_ROOT, temp_root / "portable_framework")

            probe = textwrap.dedent(
                f"""
                import sys
                from pathlib import Path
                sys.path.insert(0, {str(temp_root)!r})

                from portable_framework.command_menu import CommandMenu, CommandMenuBinding
                from portable_framework.components import (
                    AxisAnchor,
                    Button,
                    ComponentLayoutProfile,
                    ControlLayout,
                    PlacedComponent,
                    PositionedPanel,
                    SizeConstraints,
                    SplitPane,
                    SplitPanel,
                    TabContainer,
                    TabPage,
                    anchored,
                    overlay,
                    placement_from_descriptor,
                    positioned,
                )
                from portable_framework.designer import (
                    DesignerIdentityMap,
                    DesignerNode,
                    DesignerSnapshot,
                    capture_component_tree,
                )
                from portable_framework.designer_clipboard import copy_designer_subtree
                from portable_framework.designer_component_palette import (
                    DesignerComponentPalette,
                    DesignerComponentPaletteBinding,
                )
                from portable_framework.designer_editing import DesignerEditSession
                from portable_framework.designer_structure import locate_designer_node
                from portable_framework.designer_preview import reconstruct_designer_snapshot
                from portable_framework.designer_preview_host import DesignerPreviewHost
                from portable_framework.designer_preview_selection import (
                    DesignerPreviewSelectionBinding,
                    DesignerPreviewSelectionSurface,
                )
                from portable_framework.designer_project import DesignerProjectFile
                from portable_framework.designer_hierarchy import DesignerHierarchyProjection
                from portable_framework.designer_inspector import (
                    DesignerInspectorEditorKind,
                    DesignerPropertyInspector,
                )
                from portable_framework.designer_navigation import (
                    DesignerHierarchyNavigator,
                    DesignerNavigationDirection,
                )
                from portable_framework.designer_selection import DesignerSelectionModel
                from portable_framework.designer_workspace import DesignerWorkspace
                from portable_framework.designer_shell import (
                    DESIGNER_COPY_COMMAND,
                    DESIGNER_DUPLICATE_COMMAND,
                    DESIGNER_UNDO_COMMAND,
                    DesignerShellCommands,
                )
                from portable_framework.designer_shell_menu import DesignerShellMenu
                from portable_framework.designer_hierarchy_panel import (
                    DesignerHierarchyPanel,
                    DesignerHierarchyPanelBinding,
                )
                from portable_framework.designer_inspector_panel import (
                    DesignerInspectorPanel,
                    DesignerInspectorPanelBinding,
                )
                from portable_framework.documentation import DocPage, DocumentationTheme
                from portable_framework.geometry import ContentMetrics, content_bounds, split_sizes
                from portable_framework.data_view import DataRecord, DataView, SortDirection, SortTerm
                from portable_framework.interactions import CommandSet, CommandSpec, OrderedItems, SelectionModel
                from portable_framework.live_data import (
                    LiveTable,
                    StateGrid,
                    StateGridBinding,
                    StateGridCell,
                    StateGridFrame,
                    TableBinding,
                    TableColumnBinding,
                    TableColumnSpec,
                    TableFrame,
                    TableRow,
                    TableRowBinding,
                )
                from portable_framework.property_cascade import PropertySource, resolve_property
                from portable_framework.responsive import LayoutCoordinator
                from portable_framework.telemetry import RollingTelemetry
                from portable_framework.visualization import (
                    PlotBinding,
                    PlotFrame,
                    PlotSeriesBinding,
                    PlotSeriesData,
                    PlotSeriesSpec,
                    RealtimeGraph,
                )

                button = Button("Run")
                designer_root = PositionedPanel((
                    positioned(button, x=12, y=8),
                ), layout=ControlLayout(width=140, height=70))
                designer_ids = DesignerIdentityMap(prefix="portable")
                designer_ids.bind(designer_root, "portable-root")
                designer_snapshot = capture_component_tree(
                    designer_root, identities=designer_ids
                )
                restored_designer_snapshot = DesignerSnapshot.from_json(
                    designer_snapshot.to_json()
                )
                assert restored_designer_snapshot.root.node_id == "portable-root"
                assert restored_designer_snapshot.node_count == 2
                assert restored_designer_snapshot.to_descriptor() == designer_snapshot.to_descriptor()
                designer_preview = reconstruct_designer_snapshot(restored_designer_snapshot)
                assert designer_preview.component("portable-root") is designer_preview.root
                assert designer_preview.recapture().to_descriptor() == restored_designer_snapshot.to_descriptor()
                portable_project_path = Path({str(temp_root / "portable-designer.project")!r})
                portable_project = DesignerProjectFile.create(restored_designer_snapshot)
                assert portable_project.is_dirty is True
                portable_project.save(portable_project_path)
                assert portable_project.is_dirty is False
                portable_loaded = DesignerProjectFile.open(portable_project_path)
                assert portable_loaded.session.snapshot == restored_designer_snapshot
                designer_session = portable_loaded.session
                designer_button = next(
                    node for node in designer_session.snapshot.root.walk()
                    if node.type_key == "control.button"
                )
                assert designer_session.set_property(designer_button.node_id, "label", "Edited") is True
                assert designer_session.node(designer_button.node_id).properties["label"] == "Edited"
                assert designer_session.undo() is True
                assert designer_session.node(designer_button.node_id).properties["label"] == "Run"
                preview_host = DesignerPreviewHost(designer_session)
                portable_selection = DesignerSelectionModel(
                    designer_session.snapshot,
                    selected=designer_button.node_id,
                    focused=designer_button.node_id,
                )
                assert portable_selection.selected_node(designer_session.snapshot).node_id == designer_button.node_id
                portable_nav = DesignerHierarchyNavigator(designer_session.snapshot)
                assert portable_nav.parent_id(designer_button.node_id) == "portable-root"
                assert portable_nav.target(
                    "portable-root", DesignerNavigationDirection.FIRST_CHILD
                ) == designer_button.node_id
                assert portable_nav.reveal(designer_button.node_id).path_ids == (
                    "portable-root", designer_button.node_id
                )
                portable_hierarchy = DesignerHierarchyProjection(designer_session.snapshot)
                assert portable_hierarchy.visible_ids() == (
                    "portable-root", designer_button.node_id
                )
                assert portable_hierarchy.reveal(designer_button.node_id).path_ids == (
                    "portable-root", designer_button.node_id
                )
                assert preview_host.select_and_focus_node(designer_button.node_id) is True
                selected_generation = preview_host.generation
                assert preview_host.selected_component is preview_host.component(designer_button.node_id)
                assert preview_host.generation == selected_generation
                assert preview_host.reveal_selected_in_hierarchy().path_ids == (
                    "portable-root", designer_button.node_id
                )
                hierarchy_row = next(
                    row for row in preview_host.hierarchy_rows()
                    if row.node_id == designer_button.node_id
                )
                assert hierarchy_row.selected is True
                assert hierarchy_row.focused is True
                portable_inspector = DesignerPropertyInspector(designer_session)
                inspector_state = portable_inspector.state()
                assert inspector_state.node_id == designer_button.node_id
                assert inspector_state.type_label == "Button"
                label_row = portable_inspector.row("label")
                assert label_row.value == "Run"
                assert label_row.editor is DesignerInspectorEditorKind.TEXT
                assert preview_host.inspected_property("label").value == "Run"
                assert preview_host.generation == selected_generation
                portable_workspace = DesignerWorkspace(
                    portable_loaded, preview_host=preview_host
                )

                class PortablePaletteHost:
                    def __init__(self):
                        self.on_activate = None
                    def build(self, state, *, parent, title="", on_activate=None):
                        self.on_activate = on_activate
                        return DesignerComponentPaletteBinding(
                            panel={{"alive": True, "parent": parent, "title": title}},
                            items={{entry.component_type_key: entry.component_type_key for entry in state.entries}},
                        )
                    def update(self, binding, state):
                        binding.items.clear()
                        binding.items.update({{entry.component_type_key: entry.component_type_key for entry in state.entries}})
                    def exists(self, binding):
                        return bool(binding.panel["alive"])
                    def dispose(self, binding):
                        binding.panel["alive"] = False

                portable_palette_host = PortablePaletteHost()
                portable_palette = DesignerComponentPalette(
                    portable_workspace,
                    portable_palette_host,
                    component_keys=("control.label", "control.button"),
                )
                portable_palette_binding = portable_palette.build(parent="palette")
                assert tuple(portable_palette_binding.items) == ("control.label", "control.button")
                palette_generation = preview_host.generation
                palette_request = portable_palette_host.on_activate("control.button")
                assert palette_request.component_type_key == "control.button"
                assert palette_request.target_hint == designer_button.node_id
                assert palette_request.requires_placement is True
                assert preview_host.generation == palette_generation

                workspace_state = portable_workspace.state
                assert workspace_state.selected_id == designer_button.node_id
                assert workspace_state.inspector.row("label").value == "Run"
                assert workspace_state.preview_generation == selected_generation
                assert workspace_state.is_dirty is False
                assert preview_host.navigate_selection("parent", focus=True) is True
                assert designer_session.selected_node_id == "portable-root"
                assert preview_host.reveal_selected().path_ids == ("portable-root",)
                assert preview_host.generation == selected_generation
                assert preview_host.select_and_focus_node(designer_button.node_id) is True
                assert portable_workspace.set_selected_property("label", "Hosted") is True
                assert preview_host.component(designer_button.node_id).label == "Hosted"
                assert portable_workspace.state.is_dirty is True
                assert portable_workspace.state.can_undo is True
                assert preview_host.selected_component is preview_host.component(designer_button.node_id)
                assert designer_session.selected_node_id == designer_button.node_id
                assert preview_host.undo() is True
                assert preview_host.component(designer_button.node_id).label == "Run"
                portable_shell = DesignerShellCommands(portable_workspace)
                assert portable_shell.command(DESIGNER_COPY_COMMAND).enabled is True

                class PortableInspectorHost:
                    def __init__(self):
                        self.on_set = None
                        self.on_clear = None
                        self.on_error = None
                    def build(self, state, *, parent, title="", on_set=None, on_clear=None, on_error=None):
                        self.on_set = on_set
                        self.on_clear = on_clear
                        self.on_error = on_error
                        return DesignerInspectorPanelBinding(
                            panel={{"alive": True, "parent": parent, "title": title}},
                            rows={{row.key: row.key for row in state.rows}},
                        )
                    def update(self, binding, state):
                        binding.rows.clear()
                        binding.rows.update({{row.key: row.key for row in state.rows}})
                    def exists(self, binding):
                        return bool(binding.panel["alive"])
                    def dispose(self, binding):
                        binding.panel["alive"] = False

                portable_inspector_host = PortableInspectorHost()
                portable_inspector_panel = DesignerInspectorPanel(
                    portable_workspace, portable_inspector_host
                )
                portable_inspector_binding = portable_inspector_panel.build(parent="inspector")
                assert "label" in portable_inspector_binding.rows
                inspector_generation = preview_host.generation
                assert portable_inspector_host.on_set(
                    designer_button.node_id, "label", "Panel"
                ) is True
                assert preview_host.component(designer_button.node_id).label == "Panel"
                assert preview_host.generation == inspector_generation + 1
                assert portable_workspace.undo() is True
                portable_inspector_panel.refresh()
                assert portable_inspector_panel.state.row("label").value == "Run"

                class PortableHierarchyHost:
                    def __init__(self):
                        self.on_select = None
                        self.on_toggle = None
                    def build(self, rows, *, parent, title="", on_select=None, on_toggle=None):
                        self.on_select = on_select
                        self.on_toggle = on_toggle
                        return DesignerHierarchyPanelBinding(
                            panel={{"alive": True, "parent": parent, "title": title}},
                            rows={{row.node_id: row.node_id for row in rows}},
                        )
                    def update(self, binding, rows):
                        binding.rows.clear()
                        binding.rows.update({{row.node_id: row.node_id for row in rows}})
                    def exists(self, binding):
                        return bool(binding.panel["alive"])
                    def dispose(self, binding):
                        binding.panel["alive"] = False

                portable_hierarchy_host = PortableHierarchyHost()
                portable_hierarchy_panel = DesignerHierarchyPanel(
                    portable_workspace,
                    portable_hierarchy_host,
                    on_change=portable_inspector_panel.refresh,
                )
                portable_hierarchy_binding = portable_hierarchy_panel.build(parent="hierarchy")
                assert tuple(portable_hierarchy_binding.rows) == (
                    "portable-root", designer_button.node_id
                )
                hierarchy_generation = preview_host.generation
                assert portable_hierarchy_host.on_select(designer_button.node_id) is False
                assert preview_host.generation == hierarchy_generation
                assert portable_hierarchy_panel.toggle("portable-root") is True
                assert tuple(portable_hierarchy_binding.rows) == ("portable-root",)
                assert portable_hierarchy_panel.toggle("portable-root") is True
                assert designer_button.node_id in portable_hierarchy_binding.rows

                class PortablePreviewSelectionHost:
                    def __init__(self):
                        self.on_select = None
                    def build(self, targets, *, parent, on_select=None):
                        self.on_select = on_select
                        return DesignerPreviewSelectionBinding(
                            surface={{"alive": True, "parent": parent}},
                            targets={{target.node_id: target.component for target in targets}},
                        )
                    def update(self, binding, targets):
                        binding.targets.clear()
                        binding.targets.update({{
                            target.node_id: target.component for target in targets
                        }})
                    def exists(self, binding):
                        return bool(binding.surface["alive"])
                    def dispose(self, binding):
                        binding.surface["alive"] = False

                portable_preview_selection_host = PortablePreviewSelectionHost()
                portable_preview_selection = DesignerPreviewSelectionSurface(
                    portable_workspace, portable_preview_selection_host
                )
                portable_preview_binding = portable_preview_selection.build(parent="preview")
                assert designer_button.node_id in portable_preview_binding.targets
                click_generation = preview_host.generation
                assert portable_preview_selection_host.on_select(designer_button.node_id) is False
                assert designer_session.selected_node_id == designer_button.node_id
                assert preview_host.generation == click_generation

                class PortableMenuHost:
                    def __init__(self):
                        self.callback = None
                        self.updated = 0
                    def build(self, commands, *, title="", on_command=None):
                        self.callback = on_command
                        return CommandMenuBinding(menu={{"alive": True}}, items={{}})
                    def update(self, binding, commands):
                        self.updated += 1
                    def show(self, binding):
                        return None
                    def hide(self, binding):
                        return None
                    def exists(self, binding):
                        return bool(binding.menu["alive"])
                    def dispose(self, binding):
                        binding.menu["alive"] = False

                portable_menu_host = PortableMenuHost()
                portable_menu = DesignerShellMenu(portable_shell, portable_menu_host)
                portable_menu.build()
                shell_generation = preview_host.generation
                assert portable_menu_host.callback(DESIGNER_COPY_COMMAND).root.node_id == designer_button.node_id
                assert preview_host.generation == shell_generation
                assert portable_menu_host.updated >= 1
                assert portable_shell.command(DESIGNER_DUPLICATE_COMMAND).enabled is True
                assert portable_menu_host.callback(DESIGNER_DUPLICATE_COMMAND) is True
                assert preview_host.component(designer_button.node_id + "-copy").label == "Run"
                assert portable_shell.command(DESIGNER_UNDO_COMMAND).enabled is True
                assert portable_menu_host.callback(DESIGNER_UNDO_COMMAND) is True
                assert portable_menu.dispose() is True
                assert portable_preview_selection.dispose() is True
                assert portable_hierarchy_panel.dispose() is True
                assert portable_inspector_panel.dispose() is True
                portable_payload = copy_designer_subtree(
                    designer_session.snapshot, designer_button.node_id
                )
                preview_generation = preview_host.generation
                assert preview_host.copy_node(designer_button.node_id).root.node_id == designer_button.node_id
                assert preview_host.generation == preview_generation
                assert preview_host.paste("portable-root", payload=portable_payload) is True
                portable_clone_id = designer_button.node_id + "-copy"
                assert preview_host.component(portable_clone_id).label == "Run"
                assert preview_host.undo() is True
                assert all(
                    node.node_id != portable_clone_id
                    for node in designer_session.snapshot.root.walk()
                )
                added_node = DesignerNode("portable-added", "control.button", {{"label": "Added"}})
                assert designer_session.insert_child(
                    "portable-root",
                    added_node,
                    slot="children",
                    metadata={{"placement": {{"kind": "fixed", "x": 2, "y": 3}}}},
                ) is True
                assert locate_designer_node(designer_session.snapshot, "portable-added").parent_id == "portable-root"
                assert designer_session.undo() is True
                assert all(node.node_id != "portable-added" for node in designer_session.snapshot.root.walk())
                profile = ComponentLayoutProfile("probe")
                page = DocPage(title="Portable")
                theme = DocumentationTheme()
                bounds = content_bounds(1000, metrics=ContentMetrics(horizontal_padding=20, maximum_width=700))
                resolved = resolve_property(
                    default="fallback",
                    validator=lambda value: isinstance(value, str),
                )

                class Host:
                    def install_viewport_resize(self, callback):
                        return True
                    def watch_item_resize(self, item, callback):
                        return None
                    def unwatch_item_resize(self, watch):
                        return None
                    def item_size(self, item):
                        return (400, 300)
                    def configure(self, item, **kwargs):
                        return True

                coordinator = LayoutCoordinator(Host())

                selection = SelectionModel("row-b")
                ordered = OrderedItems(("row-a", "row-b"))
                assert ordered.move_item_up("row-b") is True
                positioned_panel = PositionedPanel((
                    positioned(Button("Inside", layout=ControlLayout(width=80, height=24)), x=20, y=10),
                ), layout=ControlLayout(width=120, height=60))
                placed_panel = PlacedComponent(positioned_panel, x=30, y=15)
                overlay_panel = PositionedPanel((
                    positioned(Button("Base", layout=ControlLayout(width=80, height=24)), x=10, y=10),
                    overlay(Button("Overlay", layout=ControlLayout(width=60, height=20)), x=300, y=200),
                ), layout=ControlLayout(width=120, height=60))
                anchor_metadata = anchored(
                    Button("Pinned", layout=ControlLayout(width=80, height=24)),
                    horizontal=AxisAnchor.END,
                    vertical=AxisAnchor.START,
                    margin=8,
                    constraints=SizeConstraints(minimum_width=60, maximum_width=120),
                ).placement.to_descriptor()
                restored_anchor = placement_from_descriptor(anchor_metadata)
                assert restored_anchor.horizontal is AxisAnchor.END
                tabs = TabContainer((
                    TabPage("one", "One", (Button("One"),)),
                    TabPage("two", "Two", (Button("Two"),)),
                ))
                split = SplitPanel((
                    SplitPane("left", weight=1, minimum=100),
                    SplitPane("right", weight=2, minimum=200),
                ), coordinator=coordinator)
                split_probe = split_sizes(1000, (1, 2), minimums=(100, 200), gap=10)

                commands = CommandSet((
                    CommandSpec("open", "Open"),
                    CommandSpec("mode", "Mode", children=(CommandSpec("mode:a", "A"),)),
                ))
                command_seen = []
                commands.dispatch("open", lambda key: command_seen.append(key))
                data_view = DataView()
                data_view.set_search("alp", ("name",))
                data_view.set_sort((SortTerm("size", SortDirection.DESCENDING),))
                projection = data_view.project((
                    DataRecord("row-a", {{"name": "Beta", "size": 1}}),
                    DataRecord("row-b", {{"name": "Alpha", "size": 2}}),
                ))

                class MenuProbeHost:
                    def __init__(self):
                        self.alive = True
                        self.callback = None
                    def build(self, commands, *, title="", on_command):
                        self.callback = on_command
                        return CommandMenuBinding("menu", {{command.key: command.key for command in commands.commands}})
                    def update(self, binding, commands):
                        return None
                    def show(self, binding):
                        return None
                    def hide(self, binding):
                        return None
                    def exists(self, binding):
                        return self.alive
                    def dispose(self, binding):
                        self.alive = False

                menu_seen = []
                menu_host = MenuProbeHost()
                command_menu = CommandMenu(menu_host, on_command=menu_seen.append)
                command_menu.build(commands)
                menu_host.callback("open")

                telemetry = RollingTelemetry(
                    ("value",),
                    history_seconds=10,
                    sample_interval_seconds=1,
                    clock=lambda: 3.0,
                )
                telemetry.record({{"value": 2}}, timestamp=2.0)
                telemetry.record({{"value": 4}}, timestamp=3.0)
                telemetry_window = telemetry.snapshot(now=3.0)

                class PlotProbeHost:
                    def __init__(self):
                        self.alive = set()
                        self.series_values = []
                    def create_line_plot(self, *, parent, x_label, y_label, series, legend=True, width=None, height=None):
                        self.alive.add("plot")
                        return PlotBinding(
                            "plot",
                            "x",
                            "y",
                            tuple(PlotSeriesBinding(spec.key, spec.key) for spec in series),
                        )
                    def exists(self, item):
                        return item in self.alive
                    def destroy(self, item):
                        self.alive.discard(item)
                    def set_axis_label(self, axis, label):
                        return None
                    def set_axis_limits(self, axis, minimum, maximum):
                        return None
                    def set_series(self, series, x_values, y_values):
                        self.series_values.append((series, tuple(x_values), tuple(y_values)))

                class TableProbeHost:
                    def __init__(self):
                        self.alive = {{"table"}}
                        self.values = {{}}
                    def create_table(self, *, parent, columns, header_row=True, resizable=True, scroll_y=True, height=None):
                        return TableBinding("table", tuple(TableColumnBinding(spec.key, spec.key) for spec in columns))
                    def exists(self, item):
                        return item in self.alive
                    def destroy(self, item):
                        self.alive.discard(item)
                    def create_row(self, table, row):
                        self.values[row.key] = tuple(cell.text for cell in row.cells)
                        return TableRowBinding(row.key, row.key, tuple(range(len(row.cells))))
                    def update_row(self, table, binding, row):
                        self.values[row.key] = tuple(cell.text for cell in row.cells)
                    def destroy_row(self, table, binding):
                        self.values.pop(binding.key, None)
                    def reorder_rows(self, table, rows):
                        self.order = tuple(row.key for row in rows)

                table_host = TableProbeHost()
                live_table = LiveTable(table_host, (TableColumnSpec("name", "Name"),))
                live_table.build(parent="panel")
                live_table.render(TableFrame((TableRow("one", ("One",)),)))

                class GridProbeHost:
                    def __init__(self):
                        self.alive = {{"grid"}}
                        self.cells = ()
                    def create_state_grid(self, *, parent, height, minimum_columns=24, maximum_columns=128, minimum_cell_width=7):
                        return StateGridBinding("grid")
                    def exists(self, item):
                        return item in self.alive
                    def destroy(self, item):
                        self.alive.discard(item)
                    def set_cells(self, grid, cells):
                        self.cells = tuple(cells)

                grid_host = GridProbeHost()
                state_grid = StateGrid(grid_host)
                state_grid.build(parent="panel", height=80)
                state_grid.render(StateGridFrame((StateGridCell("one", (1, 2, 3)),)))

                plot_host = PlotProbeHost()
                graph = RealtimeGraph(plot_host, (PlotSeriesSpec("value", "Value"),))
                graph.build(parent="panel", x_label="Time", y_label="Value")
                graph.render(
                    PlotFrame(
                        x_limits=(-1, 0),
                        y_limits=(0, 5),
                        y_label="Value",
                        series=(PlotSeriesData("value", (-1, 0), (2, 4)),),
                    )
                )

                assert button.label == "Run"
                assert profile.name == "probe"
                assert page.title == "Portable"
                assert theme is not None
                assert bounds.width == 700
                assert coordinator.item_size("panel") == (400, 300)
                assert ordered.keys == ("row-b", "row-a")
                assert placed_panel.placement.x == 30
                assert positioned_panel.children[0].placement.y == 10
                assert overlay_panel.children[1].placement.affects_layout is False
                assert tuple(page.key for page in tabs.pages) == ("one", "two")
                assert tuple(pane.key for pane in split.panes) == ("left", "right")
                assert split_probe == (330, 660)
                assert menu_seen == ["open"]
                assert coordinator.width("panel", 320) is True
                assert telemetry_window.statistics("value").average == 3.0
                assert plot_host.series_values == [("value", (-1.0, 0.0), (2.0, 4.0))]
                assert table_host.values == {{"one": ("One",)}}
                assert len(grid_host.cells) == 1
                assert resolved.value == "fallback"
                assert resolved.source is PropertySource.DEFAULT
                assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
                """
            )

            result = subprocess.run(
                [sys.executable, "-I", "-c", probe],
                cwd=temp_root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_framework_package_root_does_not_freeze_a_final_public_api(self):
        source = (FRAMEWORK_ROOT / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("__version__", source)
        self.assertNotIn("from .components import *", source)
        self.assertNotIn("from .documentation import *", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
