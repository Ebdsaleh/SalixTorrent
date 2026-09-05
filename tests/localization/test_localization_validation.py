from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.localization import LocalizationManager, locale_info, placeholder_names
from app.localization.pseudo import PSEUDO_ENV, PSEUDO_LOCALE, pseudo_localize
from tools.localization import google_translate as gt
from tools.localization import localization_validation as s7
from tools.localization.build_locales import main as build_locales_main
from tools.localization.validate_locales import (
    validate_catalog_metadata,
    validate_protected_terms,
    validate_translation_freshness,
)


class LocalizationValidationTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop(PSEUDO_ENV, None)
        LocalizationManager.get_instance().configure("en-AU", system_locale="en-AU")

    def test_locale_metadata_exposes_script_direction_and_font_profile(self):
        info = locale_info("pt-BR")
        self.assertEqual(info.script, "Latn")
        self.assertEqual(info.text_direction, "ltr")
        self.assertEqual(info.font_profile, "latin")

    def test_pseudo_locale_expands_text_without_changing_placeholders(self):
        source = "Downloading {name}: {progress:6.2f}%"
        target = pseudo_localize(source)
        self.assertGreater(len(target), len(source))
        self.assertEqual(placeholder_names(source), placeholder_names(target))
        self.assertIn("{progress:6.2f}", target)
        self.assertTrue(target.startswith("[!! "))

    def test_pseudo_locale_is_generated_in_memory_and_not_a_packaged_catalog(self):
        manager = LocalizationManager.get_instance()
        manager.configure(PSEUDO_LOCALE, system_locale="en-AU")
        snap = manager.snapshot()
        self.assertEqual(manager.active_locale, PSEUDO_LOCALE)
        self.assertTrue(snap["pseudo_locale"])
        self.assertFalse(snap["bundled"])
        self.assertEqual(snap["catalog_health"]["en-XA/ui"], "generated-in-memory")
        self.assertNotEqual(manager.tr("menu.file", "File"), "File")

    def test_environment_flag_can_force_pseudo_locale_for_desktop_smoke_testing(self):
        manager = LocalizationManager.get_instance()
        with patch.dict(os.environ, {PSEUDO_ENV: "1"}, clear=False):
            manager.configure("pt-BR", system_locale="pt-BR")
            self.assertEqual(manager.active_locale, PSEUDO_LOCALE)

    def test_corrupt_target_catalog_falls_back_to_canonical_without_crashing(self):
        manager = LocalizationManager.get_instance()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for catalog in ("ui", "help", "glossary"):
                source = {"sample": "Canonical"} if catalog == "ui" else {}
                path = root / "en-AU" / f"{catalog}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps({"_meta": {"locale": "en-AU", "catalog": catalog}, "strings": source}),
                    encoding="utf-8",
                )
                target = root / "pt-BR" / f"{catalog}.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                if catalog == "ui":
                    target.write_text("{ definitely not json", encoding="utf-8")
                else:
                    target.write_text(
                        json.dumps({"_meta": {"locale": "pt-BR", "catalog": catalog}, "strings": {}}),
                        encoding="utf-8",
                    )

            with patch.object(
                LocalizationManager,
                "locale_root",
                staticmethod(lambda locale: root / locale),
            ):
                manager.configure("pt-BR", system_locale="pt-BR")
                self.assertEqual(manager.tr("sample", "Call-site"), "Canonical")
                snap = manager.snapshot()
                self.assertTrue(snap["load_errors"])
                self.assertEqual(snap["catalog_health"]["pt-BR/ui"], "fallback-to-canonical")
                self.assertEqual(snap["fallback_by_reason"]["canonical"], 1)

    def test_locale_manifest_is_deterministic_current_and_records_partial_packs(self):
        first = s7.build_locale_manifest()
        second = s7.build_locale_manifest()
        self.assertEqual(first, second)
        self.assertFalse(s7.locale_manifest_drift())
        self.assertEqual(first["locales"]["en-AU"]["canonical_entries"], 1337)
        self.assertTrue(first["locales"]["en-AU"]["complete"])
        self.assertEqual(first["locales"]["pt-BR"]["missing_entries"], 1224)
        self.assertFalse(first["locales"]["pt-BR"]["complete"])
        self.assertIn("en-XA", first["development_locales"])

    def test_packaging_contract_and_pseudo_audit_are_clean(self):
        package = s7.packaging_report()
        pseudo = s7.pseudo_audit()
        self.assertTrue(package.ok, package.errors)
        self.assertGreaterEqual(package.checked_resources, 19)
        self.assertTrue(pseudo.ok)
        self.assertEqual(pseudo.entries, 1337)

    def test_stale_translation_source_hash_is_a_validation_error(self):
        with patch.object(gt, "_load_cache", return_value={}):
            with patch.object(gt, "_manual_overrides", return_value={"ui": {}}):
                with patch.object(gt, "_cache_entry", return_value={"source_hash": "old", "translation": "Abrir"}):
                    with patch.object(gt, "_manifest_hash", return_value="current"):
                        report = validate_translation_freshness(
                            "pt-BR", "ui", {"menu.open": "Open"}, {"menu.open": "Abrir"}
                        )
        self.assertFalse(report.ok)
        self.assertIn("stale translation source hash", report.errors[0])

    def test_protected_technical_terms_must_survive_translation(self):
        with patch.object(gt, "_protected_terms", return_value=["DHT"]):
            report = validate_protected_terms(
                "pt-BR", "ui", {"x": "Enable DHT"}, {"x": "Ativar tabela distribuída"}
            )
        self.assertFalse(report.ok)
        self.assertIn("DHT", report.errors[0])

    def test_canonical_metadata_hash_tampering_is_detected(self):
        strings = {"x": "One"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "en-AU" / "ui.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "_meta": {
                            "locale": "en-AU",
                            "source_locale": "en-AU",
                            "catalog": "ui",
                            "entry_count": 1,
                            "catalog_hash": "tampered",
                        },
                        "strings": strings,
                    }
                ),
                encoding="utf-8",
            )
            with patch("tools.localization.validate_locales.LOCALE_ROOT", root):
                report = validate_catalog_metadata("en-AU", "ui", strings)
        self.assertFalse(report.ok)
        self.assertTrue(any("catalog_hash" in error for error in report.errors))

    def test_offline_validation_cli_contract_is_fully_offline(self):
        self.assertEqual(build_locales_main(["--offline-validation-check", "--locale", "pt-BR"]), 0)

    def test_gitignore_tracks_validation_helper(self):
        text = (s7.ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!tools/localization/validate_localization.bat", text)


if __name__ == "__main__":
    unittest.main()
