from __future__ import annotations

import unittest

from app.framework.data_view import DataRecord, DataView, SortDirection, SortTerm
from app.framework.interactions import CommandSet, CommandSpec, SelectionModel


class SelectionModelTests(unittest.TestCase):
    def test_selection_is_explicit_and_reports_changes(self):
        model = SelectionModel()
        self.assertTrue(model.select("a"))
        self.assertFalse(model.select("a"))
        self.assertEqual(model.selected, "a")
        self.assertTrue(model.clear())
        self.assertFalse(model.clear())

    def test_selection_retain_clears_missing_identity(self):
        model = SelectionModel("b")
        self.assertFalse(model.retain(("a", "b")))
        self.assertTrue(model.retain(("a",)))
        self.assertFalse(model.has_selection)

    def test_selection_rejects_empty_key(self):
        with self.assertRaisesRegex(ValueError, "selection key"):
            SelectionModel().select("")


class CommandModelTests(unittest.TestCase):
    def test_command_tree_validates_unique_recursive_keys(self):
        with self.assertRaisesRegex(ValueError, "duplicate command key"):
            CommandSet((
                CommandSpec("menu", "Menu", children=(CommandSpec("x", "X"),)),
                CommandSpec("x", "Duplicate"),
            ))

    def test_command_state_is_backend_neutral(self):
        command = CommandSpec("pause", "Pause", enabled=False, checked=True)
        self.assertFalse(command.enabled)
        self.assertTrue(command.checked)

    def test_enabled_leaf_dispatches_by_stable_key(self):
        commands = CommandSet((CommandSpec("start", "Start"),))
        seen = []
        result = commands.dispatch("start", lambda key: seen.append(key) or "ok")
        self.assertEqual("ok", result)
        self.assertEqual(["start"], seen)

    def test_disabled_or_submenu_command_cannot_dispatch(self):
        commands = CommandSet((
            CommandSpec("disabled", "Disabled", enabled=False),
            CommandSpec("submenu", "Submenu", children=(CommandSpec("child", "Child"),)),
        ))
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            commands.dispatch("disabled", lambda key: key)
        with self.assertRaisesRegex(RuntimeError, "submenu"):
            commands.dispatch("submenu", lambda key: key)


class DataViewTests(unittest.TestCase):
    def setUp(self):
        self.records = (
            DataRecord("a", {"name": "Zulu", "state": "Downloading", "size": 20, "speed": (5.0, 1.0)}),
            DataRecord("b", {"name": "alpha", "state": "Seeding", "size": 10, "speed": (0.0, 3.0)}),
            DataRecord("c", {"name": "Beta", "state": "Paused", "size": 30, "speed": (0.0, 0.0)}),
        )

    def test_search_is_case_insensitive_over_selected_fields(self):
        view = DataView()
        view.set_search("ALP", ("name",))
        self.assertEqual(("b",), view.project(self.records).keys)

    def test_choice_filter_is_exact_and_removable(self):
        view = DataView()
        view.set_choice_filter("state", ("Seeding", "Paused"))
        self.assertEqual(("b", "c"), view.project(self.records).keys)
        view.set_choice_filter("state", None)
        self.assertEqual(3, view.project(self.records).visible_count)

    def test_multi_column_sort_uses_stable_declared_priority(self):
        records = (
            DataRecord("a", {"group": 1, "name": "z"}),
            DataRecord("b", {"group": 1, "name": "a"}),
            DataRecord("c", {"group": 0, "name": "m"}),
        )
        view = DataView()
        view.set_sort((SortTerm("group"), SortTerm("name")))
        self.assertEqual(("c", "b", "a"), view.project(records).keys)

    def test_descending_numeric_and_tuple_values_are_supported(self):
        view = DataView()
        view.set_sort((SortTerm("speed", SortDirection.DESCENDING),))
        self.assertEqual(("a", "b", "c"), view.project(self.records).keys)

    def test_projection_reports_total_and_visible_counts(self):
        view = DataView()
        view.set_choice_filter("state", ("Paused",))
        result = view.project(self.records)
        self.assertEqual(3, result.total_count)
        self.assertEqual(1, result.visible_count)

    def test_duplicate_record_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "record keys"):
            DataView().project((DataRecord("x", {}), DataRecord("x", {})))

    def test_sort_term_rejects_invalid_direction(self):
        with self.assertRaisesRegex(ValueError, "sort direction"):
            SortTerm("name", "sideways")

    def test_clear_filters_does_not_clear_sort(self):
        view = DataView()
        view.set_sort((SortTerm("size", SortDirection.DESCENDING),))
        view.set_search("z", ("name",))
        view.set_choice_filter("state", ("Downloading",))
        view.clear_filters()
        self.assertEqual(("c", "a", "b"), view.project(self.records).keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
