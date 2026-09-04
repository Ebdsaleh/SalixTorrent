"""Localization packaging/dependency regressions.

Regression lineage:
- introduced during the Phase 12 localization milestone.
"""

import unittest

from tests.helpers import PROJECT_ROOT


class LocalizationPackagingTests(unittest.TestCase):
    def test_pyinstaller_spec_bundles_locale_directory(self):
        spec = (PROJECT_ROOT / "packaging" / "SalixTorrent.spec").read_text(encoding="utf-8")
        self.assertIn('"app" / "localization" / "locales"', spec)
        self.assertIn('"app/localization/locales"', spec)

    def test_runtime_requirements_do_not_contain_google_translation(self):
        runtime = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        build = (PROJECT_ROOT / "requirements-build.txt").read_text(encoding="utf-8").lower()
        localize = (PROJECT_ROOT / "requirements-localization.txt").read_text(encoding="utf-8").lower()
        self.assertNotIn("google-cloud-translate", runtime)
        self.assertNotIn("google-cloud-translate", build)
        self.assertIn("google-cloud-translate", localize)


if __name__ == "__main__":
    unittest.main(verbosity=2)
