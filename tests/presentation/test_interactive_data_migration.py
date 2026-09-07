from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT


class InteractiveDataMigrationTests(unittest.TestCase):
    def test_download_queue_routes_filtering_and_sorting_through_data_view(self):
        source = (PROJECT_ROOT / "app" / "views" / "download_view.py").read_text(encoding="utf-8")
        self.assertIn("DataView", source)
        self.assertIn("DataRecord", source)
        self.assertIn("SortTerm", source)
        self.assertNotIn("def _queue_sort_value", source)
        self.assertNotIn("def _row_matches_filter", source)

    def test_file_view_uses_live_table_and_command_state_models(self):
        source = (PROJECT_ROOT / "app" / "views" / "file_view.py").read_text(encoding="utf-8")
        self.assertIn("LiveTable", source)
        self.assertIn("CommandSet", source)
        self.assertNotIn("dpg.table_row", source)
        self.assertNotIn("with dpg.table(", source)

    def test_new_framework_interaction_modules_are_standard_library_only(self):
        for name in ("data_view.py", "interactions.py"):
            path = PROJECT_ROOT / "app" / "framework" / name
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            roots = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.extend(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    roots.append(node.module.split(".", 1)[0])
            self.assertTrue(set(roots) <= {"__future__", "dataclasses", "enum", "typing"}, (name, roots))


if __name__ == "__main__":
    unittest.main(verbosity=2)
