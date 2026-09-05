from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.localization import google_translate as gt
from tools.localization import locale_generation as s6
from tools.localization.build_locales import main as build_locales_main



class LocaleGenerationTests(unittest.TestCase):
    def test_generation_status_matches_current_translation_pipeline_baseline(self):
        status = s6.locale_generation_status("pt-BR")
        self.assertEqual(status.canonical, 1337)
        self.assertEqual(status.packaged, 113)
        self.assertEqual(status.cache_valid, 113)
        self.assertEqual(status.missing, 1224)
        self.assertFalse(status.complete)

    def test_status_cli_is_offline_and_non_mutating(self):
        cache_before = gt.CACHE_PATH.read_bytes()
        self.assertEqual(build_locales_main(["--status", "--locale", "pt-BR"]), 0)
        self.assertEqual(gt.CACHE_PATH.read_bytes(), cache_before)

    def test_doctor_reports_missing_local_setup_without_crashing(self):
        with patch("tools.localization.locale_generation._resolve_project_id", side_effect=RuntimeError("no project")):
            report = s6.google_doctor()
        self.assertIsInstance(report.ready, bool)
        self.assertIn("project", report.detail.lower())


    def test_generate_initial_refuses_stale_extraction_before_translation(self):
        with patch("tools.localization.build_locales.extraction_drift", return_value=[Path("stale.json")]):
            with patch("tools.localization.build_locales.translate_locale") as translate:
                result = build_locales_main(["--generate-initial", "--locale", "pt-BR"])
        self.assertEqual(result, 3)
        translate.assert_not_called()

    def test_generate_initial_translates_then_strict_validates(self):
        fake_stats = {"cached": 1, "overridden": 2, "translated": 3, "missing": 0, "batches": 1}
        fake_report = type("Report", (), {"warnings": [], "errors": [], "ok": True})()
        with patch("tools.localization.build_locales.extraction_drift", return_value=[]):
            with patch("tools.localization.build_locales.translate_locale", return_value=fake_stats) as translate:
                with patch("tools.localization.build_locales.validate_all", return_value=fake_report) as validate:
                    result = build_locales_main(["--generate-initial", "--locale", "pt-BR"])
        self.assertEqual(result, 0)
        translate.assert_called_once()
        validate.assert_called_once_with(strict_missing=True, locales=["en-AU", "pt-BR"])

    def test_gitignore_keeps_generation_helper_but_credentials_ignored(self):
        text = (gt.ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!tools/localization/generate_initial_locales.bat", text)
        self.assertIn("tools/localization/.credentials/", text)


if __name__ == "__main__":
    unittest.main()
