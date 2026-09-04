"""Runtime localization-catalog regressions.

Regression lineage:
- introduced during the Phase 12 localization milestone.
"""

import unittest

from app.localization import LocalizationManager
from app.localization.documents import glossary_entry


class RuntimeCatalogTests(unittest.TestCase):
    def setUp(self):
        self.manager = LocalizationManager.get_instance()
        self.manager.configure("en-AU", system_locale="en-AU")

    def tearDown(self):
        self.manager.configure("en-AU", system_locale="en-AU")

    def test_bundled_portuguese_ui_catalog_is_loaded_offline(self):
        self.manager.configure("pt-BR", system_locale="en-AU")
        self.assertEqual(self.manager.active_locale, "pt-BR")
        self.assertEqual(self.manager.tr("menu.file", "File"), "Arquivo")
        self.assertEqual(self.manager.tr("tray.exit", "Exit"), "Sair")

    def test_missing_translated_help_uses_canonical_en_au(self):
        self.manager.configure("pt-BR", system_locale="en-AU")
        value = self.manager.tr(
            "topic.basics.title",
            "BitTorrent Basics",
            catalog="help",
        )
        self.assertEqual(value, "BitTorrent Basics")
        self.assertGreaterEqual(self.manager.snapshot()["fallback_count"], 1)

    def test_bad_translated_placeholder_falls_back_to_source(self):
        self.manager.configure("pt-BR", system_locale="en-AU")
        self.manager._canonical_catalogs["ui"]["test.placeholder"] = "Peers: {count}"
        self.manager._catalogs["ui"]["test.placeholder"] = "Peers: {contador}"
        rendered = self.manager.tr("test.placeholder", "Peers: {count}", count=4)
        self.assertEqual(rendered, "Peers: 4")
        self.assertEqual(self.manager.snapshot()["format_error_count"], 1)

    def test_glossary_overlay_preserves_canonical_when_target_missing(self):
        self.manager.configure("fil-PH", system_locale="en-AU")
        title, body = glossary_entry("DHT", ("DHT - Distributed Hash Table", "Canonical body"))
        # The canonical real catalog wins over the fallback argument when the key exists.
        self.assertEqual(title, "DHT - Distributed Hash Table")
        self.assertIn("decentralized BitTorrent", body)

    def test_snapshot_reports_bundled_locale_state(self):
        self.manager.configure("en-US", system_locale="en-AU")
        snap = self.manager.snapshot()
        self.assertTrue(snap["bundled"])
        self.assertEqual(snap["active_locale"], "en-US")
        self.assertEqual(snap["canonical_locale"], "en-AU")
        self.assertGreater(snap["catalog_entries"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
