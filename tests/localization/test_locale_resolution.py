"""Locale-resolution regressions.

Regression lineage:
- introduced during the Phase 12 localization milestone.
"""

import unittest

from app.localization import (
    AUTO_LOCALE,
    CANONICAL_LOCALE,
    locale_code_from_label,
    locale_label,
    normalise_locale_code,
    resolve_requested_locale,
)


class LocaleResolutionTests(unittest.TestCase):
    def test_supported_and_common_locale_forms_normalise(self):
        self.assertEqual(normalise_locale_code("en_AU.UTF-8"), "en-AU")
        self.assertEqual(normalise_locale_code("en-GB"), "en-GB")
        self.assertEqual(normalise_locale_code("en_US"), "en-US")
        self.assertEqual(normalise_locale_code("pt_BR.UTF-8"), "pt-BR")
        self.assertEqual(normalise_locale_code("fil_PH"), "fil-PH")
        self.assertEqual(normalise_locale_code("tl_PH"), "fil-PH")

    def test_unsupported_locale_fails_safely_to_canonical(self):
        self.assertEqual(normalise_locale_code("de-DE"), CANONICAL_LOCALE)
        self.assertEqual(resolve_requested_locale("auto", system_locale="de-DE"), CANONICAL_LOCALE)

    def test_auto_resolves_supported_system_locale_without_network(self):
        self.assertEqual(resolve_requested_locale("auto", system_locale="pt-BR"), "pt-BR")
        self.assertEqual(resolve_requested_locale("auto", system_locale="en_GB.UTF-8"), "en-GB")

    def test_language_labels_round_trip(self):
        for code in (AUTO_LOCALE, "en-AU", "en-GB", "en-US", "pt-BR", "fil-PH"):
            self.assertEqual(locale_code_from_label(locale_label(code)), code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
