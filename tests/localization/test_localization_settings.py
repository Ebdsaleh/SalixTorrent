"""Localization application-setting regressions.

Regression lineage:
- introduced during the Phase 12 localization milestone.
"""

import unittest

from app.logic.torrent_manager import TorrentManager


class LocalizationSettingsTests(unittest.TestCase):
    def test_application_settings_persist_language_policy(self):
        defaults = TorrentManager._default_app_settings()
        self.assertEqual(defaults["language"], "auto")
        normalised = TorrentManager._normalise_app_settings({"language": "pt_BR"})
        self.assertEqual(normalised["language"], "pt-BR")
        unsupported = TorrentManager._normalise_app_settings({"language": "xx-YY"})
        self.assertEqual(unsupported["language"], "en-AU")


if __name__ == "__main__":
    unittest.main(verbosity=2)
