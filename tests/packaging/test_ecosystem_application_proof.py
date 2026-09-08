"""Packaging/proof regressions for the provisional multi-backend application slice."""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest

from tests.helpers import PROJECT_ROOT

from app.engine.presentation_backends import create_dearpygui_backend, create_headless_backend
from app.framework.command_menu import CommandMenuHost
from app.framework.components import ComponentRenderer
from app.framework.live_data import StateGridHost, TableHost
from app.framework.responsive import LayoutHost
from app.framework.visualization import PlotHost
from app.runtime.presentation import PresentationCapability
from app.runtime.scenes import SceneHost


EXAMPLE = PROJECT_ROOT / "examples" / "ecosystem_blank_app.py"


class EcosystemApplicationProofTests(unittest.TestCase):
    def test_blank_application_example_is_tracked_product_neutral_source(self):
        source = EXAMPLE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(EXAMPLE))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        forbidden = ("app.logic", "app.views", "app.localization")
        self.assertFalse(any(name.startswith(forbidden) for name in imports))
        self.assertIn("--ui-backend", source)
        self.assertIn("LiveTable", source)
        self.assertIn("StateGrid", source)
        self.assertIn("PositionedPanel", source)
        self.assertIn("PlacedComponent", source)
        self.assertIn("CommandMenu", source)
        self.assertIn("TabContainer", source)
        self.assertIn("SplitPanel", source)
        self.assertIn("overlay", source)
        self.assertIn('("dearpygui", "tkinter", "headless")', source)

    def test_blank_demo_minimum_geometry_contains_fixed_position_proof(self):
        from examples import ecosystem_blank_app as example

        self.assertGreaterEqual(
            example.DEMO_MIXED_CONTENT_COLUMN_WIDTH,
            example.DEMO_POSITIONED_PANEL_X + example.DEMO_POSITIONED_PANEL_WIDTH,
        )
        self.assertGreaterEqual(
            example.DEMO_LAYOUT_PANE_MINIMUM,
            example.DEMO_MIXED_LABEL_COLUMN_WIDTH + example.DEMO_MIXED_CONTENT_COLUMN_WIDTH,
        )
        self.assertGreaterEqual(
            example.DEMO_POSITIONED_PANEL_WIDTH,
            example.DEMO_ACTION_X + example.DEMO_ACTION_WIDTH,
        )
        self.assertGreaterEqual(
            example.DEMO_WINDOW_MINIMUM_WIDTH,
            example.DEMO_LAYOUT_PANE_MINIMUM
            + example.DEMO_LIVE_PANE_MINIMUM
            + example.DEMO_SPLIT_GAP,
        )

    def test_blank_view_definition_does_not_branch_on_toolkit_name(self):
        source = EXAMPLE.read_text(encoding="utf-8")
        start = source.index("class DemoView:")
        end = source.index("\ndef _make_runtime", start)
        view_source = source[start:end]
        self.assertNotIn('== "dearpygui"', view_source)
        self.assertNotIn('== "tkinter"', view_source)
        self.assertNotIn("import dearpygui", view_source)
        self.assertNotIn("import tkinter", view_source)

    def test_headless_blank_application_runs_without_gui_dependency(self):
        result = subprocess.run(
            [sys.executable, str(EXAMPLE), "--ui-backend", "headless"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertIn("Headless runtime OK (3 updates)", result.stdout)

    def test_example_help_is_available_without_dearpygui_installed(self):
        result = subprocess.run(
            [sys.executable, str(EXAMPLE), "--help"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertIn("--ui-backend", result.stdout)
        self.assertIn("tkinter", result.stdout)
        self.assertIn("headless", result.stdout)

    def test_dearpygui_bundle_satisfies_existing_framework_contracts_without_importing_toolkit(self):
        before = set(sys.modules)
        backend = create_dearpygui_backend()
        loaded = set(sys.modules) - before
        self.assertEqual(backend.name, "dearpygui")
        self.assertIsInstance(backend.component_renderer, ComponentRenderer)
        self.assertIsInstance(backend.layout_host, LayoutHost)
        self.assertIsInstance(backend.scene_host, SceneHost)
        self.assertIsInstance(backend.plot_host, PlotHost)
        self.assertIsInstance(backend.table_host, TableHost)
        self.assertIsInstance(backend.state_grid_host, StateGridHost)
        self.assertIsInstance(backend.command_menu_host, CommandMenuHost)
        self.assertFalse(any(name == "dearpygui" or name.startswith("dearpygui.") for name in loaded))

    def test_headless_bundle_advertises_no_graphical_capabilities(self):
        backend = create_headless_backend()
        self.assertEqual(backend.name, "headless")
        for capability in PresentationCapability:
            self.assertFalse(backend.supports(capability))

    def test_application_host_modules_keep_product_layers_out_of_generic_hosts(self):
        paths = tuple((PROJECT_ROOT / "app" / "engine" / "application_hosts").glob("*.py"))
        forbidden = ("app.logic", "app.views", "app.localization")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
