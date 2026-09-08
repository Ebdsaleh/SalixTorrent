from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT


class StructuralMigrationTests(unittest.TestCase):
    def test_download_detail_tabs_route_through_generic_tab_container(self):
        source = (PROJECT_ROOT / "app" / "views" / "download_view.py").read_text(encoding="utf-8")
        self.assertIn("TabContainer", source)
        self.assertIn("self.detail_tabs.page_context", source)
        self.assertNotIn("with dpg.tab_bar(", source)
        self.assertNotIn("with dpg.tab(", source)
        self.assertNotIn("_detail_tab_ids", source)

    def test_download_general_regions_route_through_generic_split_panel(self):
        source = (PROJECT_ROOT / "app" / "views" / "download_view.py").read_text(encoding="utf-8")
        self.assertIn("SplitPanel", source)
        self.assertIn('SplitPane("transfer"', source)
        self.assertIn('pane_context("swarm")', source)
        self.assertIn('pane_context("info")', source)
        self.assertIn("self.general_split_component.reflow()", source)

    def test_application_menu_selects_detail_tabs_by_semantic_key(self):
        source = (PROJECT_ROOT / "app" / "views" / "application_menu.py").read_text(encoding="utf-8")
        method = source[source.index("    def _show_detail_tab"):]
        method = method[: method.index("\n    def ", 5)]
        self.assertIn("detail_tabs", method)
        self.assertIn("tabs.select(tab_name, notify=True)", method)
        self.assertNotIn("dpg.set_value", method)

    def test_help_index_uses_generic_split_and_tabs(self):
        source = (PROJECT_ROOT / "app" / "views" / "help_topics_view.py").read_text(encoding="utf-8")
        self.assertIn("self.help_split = SplitPanel", source)
        self.assertIn("self.left_tabs = TabContainer", source)
        self.assertNotIn("dpg.add_tab_bar", source)
        self.assertNotIn("dpg.add_tab(", source)
        self.assertNotIn("split_widths", source)

    def test_structural_framework_module_has_no_backend_or_product_dependencies(self):
        path = PROJECT_ROOT / "app" / "framework" / "components" / "regions.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imports.append(node.module)
        forbidden = ("dearpygui", "tkinter", "app.engine", "app.views", "app.logic", "app.localization")
        self.assertFalse(any(name.startswith(forbidden) for name in imports), imports)


if __name__ == "__main__":
    unittest.main(verbosity=2)
