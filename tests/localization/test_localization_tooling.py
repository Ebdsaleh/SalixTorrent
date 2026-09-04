"""Localization developer-tool regressions.

Regression lineage:
- introduced during the Phase 12 localization milestone.
"""

import tempfile
import unittest
from pathlib import Path

from app.localization import placeholder_names
from tools.localization.extract_strings import extract_python_ui_strings
from tools.localization.google_translate import protect_text, restore_text
from tools.localization.validate_locales import placeholders


class LocalizationToolingTests(unittest.TestCase):
    def test_ast_extractor_reads_only_explicit_tr_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.py"
            path.write_text(
                'ignored = "Do not translate me"\n'
                'label = tr("sample.key", "Translate me")\n',
                encoding="utf-8",
            )
            strings, sources = extract_python_ui_strings([path])
            self.assertEqual(strings, {"sample.key": "Translate me"})
            self.assertIn("sample.key", sources)

    def test_protected_translation_tokens_round_trip(self):
        source = "SalixTorrent connected {count} IPv6 peers using DHT."
        protected, mapping = protect_text(source)
        self.assertNotIn("{count}", protected)
        self.assertNotIn("SalixTorrent", protected)
        self.assertEqual(restore_text(protected, mapping), source)

    def test_placeholder_helpers_preserve_named_contract(self):
        text = "{name}: {count} at {rate:.2f}"
        self.assertEqual(placeholder_names(text), {"name", "count", "rate"})
        self.assertEqual(placeholders(text), {"name", "count", "rate"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
