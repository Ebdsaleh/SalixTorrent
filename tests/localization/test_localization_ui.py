from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from tests.helpers import PROJECT_ROOT

from app.localization import LocalizationManager, canonical_choice, localized_choices, tr_value
from tools.localization.extract_strings import extract_python_ui_strings


ROOT = PROJECT_ROOT


class LocalizationUIStringTests(unittest.TestCase):
    def tearDown(self):
        LocalizationManager.get_instance().configure("en-AU", system_locale="en-AU")

    def test_direct_dearpygui_user_text_is_localization_aware(self):
        """New literal labels/status text must not bypass tr()."""
        direct_positions = {"add_text": 0, "set_value": 1}
        failures = []
        for path in sorted((ROOT / "app" / "views").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = ""
                is_dpg = False
                if isinstance(node.func, ast.Attribute):
                    func = node.func.attr
                    is_dpg = isinstance(node.func.value, ast.Name) and node.func.value.id == "dpg"
                elif isinstance(node.func, ast.Name):
                    func = node.func.id

                candidates = []
                if is_dpg:
                    index = direct_positions.get(func)
                    if index is not None and len(node.args) > index:
                        candidates.append(node.args[index])
                    candidates.extend(
                        kw.value for kw in node.keywords if kw.arg in {"label", "hint", "overlay"}
                    )
                elif func == "add_text_tooltip" and len(node.args) > 1:
                    candidates.append(node.args[1])

                for candidate in candidates:
                    if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
                        if candidate.value.strip():
                            failures.append(f"{path.name}:{node.lineno}: {candidate.value!r}")
                    elif isinstance(candidate, ast.JoinedStr):
                        failures.append(f"{path.name}:{node.lineno}: untranslated f-string")
        self.assertEqual(failures, [])

    def test_canonical_ui_catalog_covers_localized_views_and_cli(self):
        raw = json.loads(
            (ROOT / "app" / "localization" / "locales" / "en-AU" / "ui.json").read_text(
                encoding="utf-8"
            )
        )
        strings = raw["strings"]
        self.assertGreaterEqual(len(strings), 600)
        expected_prefixes = (
            "view.download_view.",
            "view.create_torrent_view.",
            "view.settings_view.",
            "view.file_view.",
            "view.peer_view.",
            "view.piece_view.",
            "view.source_view.",
            "view.speed_view.",
            "cli.",
            "notification.",
            "value.",
        )
        for prefix in expected_prefixes:
            self.assertTrue(any(key.startswith(prefix) for key in strings), prefix)

    def test_localized_choice_maps_back_to_canonical_internal_value(self):
        manager = LocalizationManager.get_instance()
        manager.configure("pt-BR", system_locale="en-AU")
        manager._catalogs["ui"]["value.high"] = "Alta"
        manager._catalogs["ui"]["value.normal"] = "Normal"
        manager._catalogs["ui"]["value.low"] = "Baixa"
        labels = localized_choices(("High", "Normal", "Low"))
        self.assertEqual(labels, ["Alta", "Normal", "Baixa"])
        self.assertEqual(canonical_choice("Alta", ("High", "Normal", "Low"), "Normal"), "High")
        self.assertEqual(canonical_choice("Baixa", ("High", "Normal", "Low"), "Normal"), "Low")

    def test_common_internal_state_translation_is_presentation_only(self):
        manager = LocalizationManager.get_instance()
        manager.configure("pt-BR", system_locale="en-AU")
        manager._catalogs["ui"]["value.downloading"] = "Baixando"
        self.assertEqual(tr_value("Downloading"), "Baixando")
        self.assertEqual(canonical_choice("Baixando", ("Downloading", "Seeding"), "Downloading"), "Downloading")

    def test_gitignore_tracks_localization_resources_without_obsolete_design_exclusion(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("SalixTorrent-Phase12-Localization-Design.md", text)
        self.assertNotIn("translation_cache.json\n", "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        ))
        self.assertIn("tools/localization/.credentials/", text)
        self.assertIn("tools/localization/service-account*.json", text)

    def test_cli_human_facing_strings_are_extractable(self):
        strings, _sources = extract_python_ui_strings(
            [ROOT / "main.py", ROOT / "app" / "cli" / "headless.py"]
        )
        self.assertIn("cli.parser.description", strings)
        self.assertIn("cli.transfer.status", strings)
        self.assertIn("cli.shutdown", strings)
        self.assertIn("notification.download_complete.title", json.loads(
            (ROOT / "app" / "localization" / "locales" / "en-AU" / "ui.json").read_text(encoding="utf-8")
        )["strings"])


if __name__ == "__main__":
    unittest.main()
