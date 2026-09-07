from __future__ import annotations

import ast
import unittest

from tests.helpers import PROJECT_ROOT

from app.engine.state_grid_hosts import DearPyGuiStateGridHost
from app.engine.table_hosts import DearPyGuiTableHost
from app.framework.live_data import (
    LiveTable,
    StateGrid,
    StateGridBinding,
    StateGridCell,
    StateGridFrame,
    StateGridHost,
    TableBinding,
    TableCell,
    TableColumnBinding,
    TableColumnSpec,
    TableFrame,
    TableHost,
    TableRow,
    TableRowBinding,
)


class _TableProbeHost:
    def __init__(self):
        self.alive = set()
        self.created = []
        self.updated = []
        self.destroyed = []
        self.orders = []

    def create_table(self, *, parent, columns, header_row=True, resizable=True, scroll_y=True, height=None):
        del parent, header_row, resizable, scroll_y, height
        self.alive.add("table")
        return TableBinding("table", tuple(TableColumnBinding(column.key, column.key) for column in columns))

    def exists(self, item):
        return item in self.alive

    def destroy(self, item):
        self.alive.discard(item)

    def create_row(self, table, row):
        del table
        handle = f"row:{row.key}"
        self.created.append(row)
        self.alive.add(handle)
        return TableRowBinding(row.key, handle, tuple(f"{handle}:{i}" for i in range(len(row.cells))))

    def update_row(self, table, binding, row):
        del table
        self.updated.append((binding.key, row))

    def destroy_row(self, table, binding):
        del table
        self.destroyed.append(binding.key)
        self.alive.discard(binding.row)

    def reorder_rows(self, table, rows):
        del table
        self.orders.append(tuple(row.key for row in rows))


class _GridProbeHost:
    def __init__(self):
        self.alive = set()
        self.frames = []

    def create_state_grid(self, *, parent, height, minimum_columns=24, maximum_columns=128, minimum_cell_width=7):
        del parent, height, minimum_columns, maximum_columns, minimum_cell_width
        self.alive.add("grid")
        return StateGridBinding("grid")

    def exists(self, item):
        return item in self.alive

    def destroy(self, item):
        self.alive.discard(item)

    def set_cells(self, grid, cells):
        del grid
        self.frames.append(tuple(cells))




class _FakeDpgContext:
    def __init__(self, owner, tag):
        self.owner = owner
        self.tag = tag

    def __enter__(self):
        self.owner.alive.add(self.tag)
        return self.tag

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDpgStateGrid:
    def __init__(self):
        self.alive = set()
        self.width = 360.0
        self.resize_callback = None
        self.bound_registry = None
        self.draw_calls = []
        self.child_clears = 0

    def add_drawlist(self, **kwargs):
        del kwargs
        self.alive.add("grid")
        return "grid"

    def item_handler_registry(self, *, tag):
        return _FakeDpgContext(self, tag)

    def add_item_resize_handler(self, *, callback):
        self.resize_callback = callback
        return "resize-handler"

    def bind_item_handler_registry(self, item, registry):
        self.bound_registry = (item, registry)

    def does_item_exist(self, item):
        return item in self.alive

    def delete_item(self, item, children_only=False):
        if children_only:
            self.child_clears += 1
            self.draw_calls.clear()
            return
        self.alive.discard(item)

    def get_item_rect_size(self, item):
        assert item == "grid"
        return (self.width, 90.0)

    def draw_rectangle(self, p1, p2, **kwargs):
        self.draw_calls.append((p1, p2, kwargs))

class LiveTableContractTests(unittest.TestCase):
    def test_table_data_validates_keys_widths_colours_and_shape(self):
        with self.assertRaisesRegex(ValueError, "column key"):
            TableColumnSpec("", "Bad")
        with self.assertRaisesRegex(ValueError, "width_mode"):
            TableColumnSpec("a", "A", "magic", 1)
        with self.assertRaisesRegex(ValueError, "between 0 and 255"):
            TableCell("x", foreground=(999, 0, 0))
        with self.assertRaisesRegex(ValueError, "row keys"):
            TableFrame((TableRow("same", ("a",)), TableRow("same", ("b",))))

    def test_table_host_contract_is_backend_neutral(self):
        self.assertIsInstance(_TableProbeHost(), TableHost)
        self.assertIsInstance(DearPyGuiTableHost(), TableHost)

    def test_live_table_preserves_rows_updates_only_changed_and_removes_missing(self):
        host = _TableProbeHost()
        table = LiveTable(host, (TableColumnSpec("name", "Name"), TableColumnSpec("value", "Value")))
        table.build(parent="root")
        first = TableFrame((TableRow("a", ("A", "1")), TableRow("b", ("B", "2"))))
        table.render(first)
        self.assertEqual([row.key for row in host.created], ["a", "b"])
        self.assertEqual(host.updated, [])
        self.assertEqual(host.orders[-1], ("a", "b"))

        table.render(first)
        self.assertEqual(host.updated, [])
        self.assertEqual(len(host.orders), 1)

        table.render(TableFrame((TableRow("b", ("B", "3")), TableRow("c", ("C", "4")))))
        self.assertEqual(host.destroyed, ["a"])
        self.assertEqual([row.key for row in host.created], ["a", "b", "c"])
        self.assertEqual(host.updated[-1][0], "b")
        self.assertEqual(host.orders[-1], ("b", "c"))
        self.assertEqual(table.row_count, 2)

    def test_live_table_rejects_wrong_row_width(self):
        table = LiveTable(_TableProbeHost(), (TableColumnSpec("one", "One"), TableColumnSpec("two", "Two")))
        table.build(parent="root")
        with self.assertRaisesRegex(ValueError, "expected 2"):
            table.render(TableFrame((TableRow("a", ("only one",)),)))

    def test_live_table_clear_and_dispose_are_explicit(self):
        host = _TableProbeHost()
        table = LiveTable(host, (TableColumnSpec("one", "One"),))
        table.build(parent="root")
        table.render(TableFrame((TableRow("a", ("A",)),)))
        table.clear()
        self.assertEqual(table.row_count, 0)
        self.assertTrue(table.exists())
        table.dispose()
        self.assertFalse(table.exists())


class StateGridContractTests(unittest.TestCase):
    def test_state_grid_data_validates_identity_and_colours(self):
        with self.assertRaisesRegex(ValueError, "cell key"):
            StateGridCell("", (0, 0, 0))
        with self.assertRaisesRegex(ValueError, "cell keys"):
            StateGridFrame((StateGridCell("x", (0, 0, 0)), StateGridCell("x", (1, 1, 1))))
        cell = StateGridCell("x", (1, 2, 3))
        self.assertEqual(cell.fill, (1, 2, 3, 255))

    def test_state_grid_host_contract_is_backend_neutral(self):
        self.assertIsInstance(_GridProbeHost(), StateGridHost)
        self.assertIsInstance(DearPyGuiStateGridHost(), StateGridHost)

    def test_state_grid_skips_unchanged_frames_and_clears_explicitly(self):
        host = _GridProbeHost()
        grid = StateGrid(host)
        grid.build(parent="root", height=90)
        frame = StateGridFrame((StateGridCell("a", (1, 2, 3)), StateGridCell("b", (4, 5, 6))))
        grid.render(frame)
        grid.render(frame)
        self.assertEqual(len(host.frames), 1)
        grid.clear()
        self.assertEqual(host.frames[-1], ())
        grid.dispose()
        self.assertFalse(grid.exists())

    def test_dearpygui_state_grid_reflows_on_backend_resize_and_releases_registry(self):
        fake = _FakeDpgStateGrid()
        host = DearPyGuiStateGridHost()
        host._dpg = lambda: fake
        grid = StateGrid(host)
        binding = grid.build(
            parent="root",
            height=90,
            minimum_columns=2,
            maximum_columns=8,
            minimum_cell_width=40,
        )
        frame = StateGridFrame(
            tuple(StateGridCell(str(index), (index * 10, 40, 80)) for index in range(6))
        )
        grid.render(frame)
        self.assertEqual(len(fake.draw_calls), 6)
        self.assertIsNotNone(fake.resize_callback)
        registry = fake.bound_registry[1]
        self.assertIn(registry, fake.alive)

        first_width = fake.draw_calls[0][1][0] - fake.draw_calls[0][0][0]
        fake.width = 160.0
        fake.resize_callback()
        self.assertEqual(len(fake.draw_calls), 6)
        resized_width = fake.draw_calls[0][1][0] - fake.draw_calls[0][0][0]
        self.assertNotEqual(first_width, resized_width)

        # No new data frame was sent through StateGrid; the host itself owned
        # the physical resize reflow. Disposal must release both resources.
        self.assertEqual(grid.binding, binding)
        grid.dispose()
        self.assertNotIn("grid", fake.alive)
        self.assertNotIn(registry, fake.alive)


class SalixLiveDataMigrationTests(unittest.TestCase):
    def test_peer_source_piece_views_route_live_surfaces_through_generic_contracts(self):
        for name in ("peer_view.py", "source_view.py", "piece_view.py"):
            path = PROJECT_ROOT / "app" / "views" / name
            source = path.read_text(encoding="utf-8")
            self.assertIn("LiveTable", source, name)
            self.assertNotIn("dpg.table_row", source, name)
        piece_source = (PROJECT_ROOT / "app" / "views" / "piece_view.py").read_text(encoding="utf-8")
        self.assertIn("StateGrid", piece_source)
        self.assertNotIn("dpg.draw_rectangle", piece_source)
        self.assertNotIn("dpg.add_drawlist", piece_source)

    def test_dearpygui_live_data_hosts_do_not_import_toolkit_at_module_import_time(self):
        paths = (
            PROJECT_ROOT / "app" / "engine" / "table_hosts" / "dearpygui.py",
            PROJECT_ROOT / "app" / "engine" / "state_grid_hosts" / "dearpygui.py",
        )
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            top_level = []
            for node in tree.body:
                if isinstance(node, ast.Import):
                    top_level.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top_level.append(node.module)
            self.assertFalse(any(name == "dearpygui" or name.startswith("dearpygui.") for name in top_level))


if __name__ == "__main__":
    unittest.main(verbosity=2)
