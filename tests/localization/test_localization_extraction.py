from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import PROJECT_ROOT

from tools.localization.build_locales import main as build_locales_main
from tools.localization.contracts import placeholder_contract, source_hash
from tools.localization.extract_strings import (
    ExtractionError,
    MANIFEST_PATH,
    extract_python_ui_records,
    extract_records,
    extraction_drift,
    generated_payloads,
)
from tools.localization.validate_locales import validate_extraction_sources


ROOT = PROJECT_ROOT


class LocalizationExtractionTests(unittest.TestCase):
    def test_ast_records_source_hash_placeholders_and_location(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.py"
            path.write_text(
                'label = tr("sample.peers", "Peers: {count} at {rate:.2f}")\n',
                encoding="utf-8",
            )
            records, dynamic = extract_python_ui_records([path])
            self.assertEqual(dynamic, [])
            entry = records["sample.peers"]
            self.assertEqual(entry.hash, source_hash("Peers: {count} at {rate:.2f}"))
            self.assertEqual(entry.placeholders.names, ("count", "rate"))
            self.assertEqual(entry.placeholders.fields, ("{count}", "{rate:.2f}"))
            self.assertEqual(entry.occurrences[0].line, 1)
            self.assertEqual(entry.occurrences[0].column, 9)

    def test_same_key_and_same_text_is_detected_as_safe_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.py"
            path.write_text(
                'a = tr("sample.key", "Same")\n'
                'b = tr("sample.key", "Same")\n',
                encoding="utf-8",
            )
            records, dynamic = extract_python_ui_records([path])
            self.assertEqual(dynamic, [])
            self.assertEqual(len(records["sample.key"].occurrences), 2)

    def test_conflicting_duplicate_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.py"
            path.write_text(
                'a = tr("sample.key", "First")\n'
                'b = tr("sample.key", "Second")\n',
                encoding="utf-8",
            )
            with self.assertRaises(ExtractionError):
                extract_python_ui_records([path])

    def test_dynamic_direct_tr_call_is_reported_instead_of_silently_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.py"
            path.write_text(
                'key = "sample.key"\n'
                'label = tr(key, "Dynamic")\n',
                encoding="utf-8",
            )
            records, dynamic = extract_python_ui_records([path])
            self.assertEqual(records, {})
            self.assertEqual(len(dynamic), 1)
            self.assertEqual(dynamic[0].line, 2)

    def test_static_ui_source_replaces_generated_catalog_carry_forward(self):
        result = extract_records()
        entry = result.catalogs["ui"]["language.english_au"]
        self.assertEqual(entry.text, "English (Australia)")
        self.assertTrue(any(item.kind == "static-ui" for item in entry.occurrences))
        self.assertEqual(len(result.catalogs["ui"]), 653)

    def test_manifest_tracks_all_catalogs_hashes_placeholders_and_duplicates(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["_meta"]["schema"], 1)
        self.assertEqual(set(manifest["catalogs"]), {"ui", "help", "glossary"})
        self.assertEqual(manifest["catalogs"]["ui"]["entry_count"], 653)
        entry = manifest["catalogs"]["ui"]["entries"]["cli.transfer.status"]
        self.assertEqual(len(entry["source_hash"]), 64)
        self.assertIn("name", entry["placeholders"])
        self.assertIn("{progress:6.2f}", entry["format_fields"])
        self.assertIn("ui", manifest["duplicate_keys"])
        self.assertEqual(manifest["dynamic_tr_calls"], [])

    def test_generated_payloads_are_deterministic_and_current(self):
        first = generated_payloads(extract_records())
        second = generated_payloads(extract_records())
        self.assertEqual(first, second)
        self.assertEqual(extraction_drift(), [])
        self.assertEqual(build_locales_main(["--check"]), 0)

    def test_extraction_validator_accepts_current_source_contract(self):
        report = validate_extraction_sources()
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.errors, [])
        self.assertFalse(placeholder_contract("{name}: {rate:.1f}").malformed)


if __name__ == "__main__":
    unittest.main()
