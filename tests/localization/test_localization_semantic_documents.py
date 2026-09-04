from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import PROJECT_ROOT

from app.localization import LocalizationManager
from app.localization.documents import (
    canonical_glossary_entries,
    canonical_help_topics,
    document_structure_snapshot,
    glossary_entry,
    localized_help_topics,
)
from tools.localization.extract_strings import extract_glossary_strings, extract_help_strings
from tools.localization.validate_locales import validate_document_structure


ROOT = PROJECT_ROOT


class SemanticDocumentationTests(unittest.TestCase):
    def tearDown(self):
        LocalizationManager.get_instance().configure("en-AU", system_locale="en-AU")

    def test_help_and_glossary_wording_no_longer_lives_in_views(self):
        help_view = (ROOT / "app/views/help_topics_view.py").read_text(encoding="utf-8")
        terms_view = (ROOT / "app/views/help_terms.py").read_text(encoding="utf-8")
        self.assertNotIn("HELP_TOPICS: Tuple[HelpTopic, ...] = (", help_view)
        self.assertIn("canonical_help_topics()", help_view)
        self.assertNotIn("HELP_TERMS = {", terms_view)
        self.assertIn("canonical_glossary_entries()", terms_view)

    def test_semantic_source_has_stable_unique_ids_and_expected_shape(self):
        snapshot = document_structure_snapshot()
        self.assertEqual(snapshot["topic_count"], 19)
        self.assertEqual(snapshot["section_count"], 104)
        self.assertEqual(snapshot["term_count"], 186)
        self.assertEqual(len(snapshot["topic_ids"]), len(set(snapshot["topic_ids"])))
        self.assertEqual(len(snapshot["term_ids"]), len(set(snapshot["term_ids"])))
        for topic_id, section_ids in snapshot["section_ids"].items():
            self.assertTrue(topic_id)
            self.assertEqual(len(section_ids), len(set(section_ids)))
            self.assertTrue(all(section_id and not section_id.isdigit() for section_id in section_ids))

    def test_related_help_terms_reference_real_glossary_ids(self):
        snapshot = document_structure_snapshot()
        term_ids = set(snapshot["term_ids"])
        missing = {
            (topic_id, term_id)
            for topic_id, related in snapshot["related_terms"].items()
            for term_id in related
            if term_id not in term_ids
        }
        self.assertEqual(missing, set())

    def test_semantic_sources_flatten_exactly_to_canonical_catalogs(self):
        help_catalog = json.loads(
            (ROOT / "app/localization/locales/en-AU/help.json").read_text(encoding="utf-8")
        )["strings"]
        glossary_catalog = json.loads(
            (ROOT / "app/localization/locales/en-AU/glossary.json").read_text(encoding="utf-8")
        )["strings"]
        self.assertEqual(extract_help_strings(), help_catalog)
        self.assertEqual(extract_glossary_strings(), glossary_catalog)

    def test_localization_overlay_preserves_semantic_topology(self):
        manager = LocalizationManager.get_instance()
        canonical = canonical_help_topics()
        manager.configure("pt-BR", system_locale="en-AU")
        localized = localized_help_topics(canonical)
        self.assertEqual([topic.key for topic in localized], [topic.key for topic in canonical])
        self.assertEqual(
            [topic.section_keys for topic in localized],
            [topic.section_keys for topic in canonical],
        )
        self.assertEqual(
            [topic.related_terms for topic in localized],
            [topic.related_terms for topic in canonical],
        )
        # Generated pt-BR semantic documentation is intentionally incomplete, so
        # canonical en-AU wording must be used offline through fallback.
        self.assertEqual(localized[0].title, canonical[0].title)
        self.assertGreater(manager.snapshot()["fallback_count"], 0)

    def test_glossary_lookup_uses_semantic_source_when_no_source_tuple_is_passed(self):
        entries = canonical_glossary_entries()
        self.assertIn("DHT", entries)
        title, body = glossary_entry("DHT")
        self.assertEqual(title, entries["DHT"][0])
        self.assertEqual(body, entries["DHT"][1])

    def test_semantic_validator_and_packaging_contract(self):
        report = validate_document_structure()
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.errors, [])
        spec = (ROOT / "packaging/SalixTorrent.spec").read_text(encoding="utf-8")
        self.assertIn('"app" / "localization" / "content"', spec)
        self.assertIn('"app/localization/content"', spec)


if __name__ == "__main__":
    unittest.main()
