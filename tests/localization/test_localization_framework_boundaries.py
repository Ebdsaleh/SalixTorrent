from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import PROJECT_ROOT

from app.localization import (
    JsonCatalogRepository,
    LocalizationProfile,
    LocaleDescriptor,
    SALIXTORRENT_LOCALIZATION_PROFILE,
)
from app.localization import LocalizationManager
from tools.localization.build_locales import main as build_locales_main
from tools.localization.framework_audit import framework_audit
from tools.localization.translation_memory import JsonTranslationMemory, memory_entry


class LocalizationFrameworkBoundaryTests(unittest.TestCase):
    def tearDown(self):
        LocalizationManager.get_instance().configure("en-AU", system_locale="en-AU")

    def test_framework_profile_contract_is_provider_neutral(self):
        profile = LocalizationProfile(
            application_id="example",
            canonical_locale="en-GB",
            auto_locale="auto",
            catalog_names=("ui",),
            locales={
                "en-GB": LocaleDescriptor(
                    code="en-GB",
                    display_name="English (UK)",
                    native_name="English (UK)",
                    support_status="canonical",
                )
            },
        )
        self.assertEqual(profile.canonical_locale, "en-GB")
        self.assertEqual(profile.locale("missing").code, "en-GB")
        self.assertFalse(hasattr(profile.locale("en-GB"), "google_target"))

    def test_salixtorrent_profile_is_a_thin_application_adapter(self):
        profile = SALIXTORRENT_LOCALIZATION_PROFILE
        self.assertEqual(profile.application_id, "salixtorrent")
        self.assertEqual(profile.canonical_locale, "en-AU")
        self.assertEqual(profile.catalog_names, ("ui", "help", "glossary"))
        self.assertIn("pt-BR", profile.locales)

    def test_generic_json_repository_validates_metadata_and_loads_strings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "pt-BR" / "ui.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "_meta": {"locale": "pt-BR", "catalog": "ui"},
                "strings": {"open": "Abrir"},
            }), encoding="utf-8")
            repo = JsonCatalogRepository(lambda locale: root / locale, allowed_catalogs=("ui",))
            self.assertEqual(repo.read("pt-BR", "ui"), {"open": "Abrir"})
            with self.assertRaises(ValueError):
                repo.read("pt-BR", "help")

    def test_existing_runtime_manager_still_loads_through_compatibility_adapter(self):
        manager = LocalizationManager.get_instance()
        manager.configure("pt-BR", system_locale="en-AU")
        self.assertEqual(manager.tr("menu.file", "File"), "Arquivo")

    def test_translation_memory_can_use_a_non_en_au_canonical_source_locale(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.json"
            memory = JsonTranslationMemory(path, source_locale="fr-FR")
            memory.put(memory_entry(
                target_locale="de-DE",
                catalog="ui",
                source="Ouvrir",
                translation="Öffnen",
                status="reviewed",
            ))
            memory.save()
            loaded = JsonTranslationMemory(path, source_locale="fr-FR")
            self.assertTrue(loaded.audit().ok)
            self.assertEqual(loaded.lookup("de-DE", "ui", "Ouvrir").translation, "Öffnen")

    def test_translation_memory_refuses_cross_source_locale_merge(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            en = JsonTranslationMemory(root / "en.json", source_locale="en-AU")
            fr = JsonTranslationMemory(root / "fr.json", source_locale="fr-FR")
            en.save()
            fr.save()
            with self.assertRaises(ValueError):
                en.merge_from(root / "fr.json")

    def test_framework_extraction_audit_is_clean(self):
        report = framework_audit()
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.extractable_count, 6)
        for module in report.modules:
            self.assertTrue(module.ok, (module.path, module.errors))

    def test_framework_check_is_offline_and_gitignore_tracks_helper(self):
        self.assertEqual(build_locales_main(["--framework-check"]), 0)
        root = PROJECT_ROOT
        text = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!tools/localization/validate_framework_extraction.bat", text)


if __name__ == "__main__":
    unittest.main()
