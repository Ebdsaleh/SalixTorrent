"""Regression checks for the repository-level tranche validation helper."""

from __future__ import annotations

import unittest

from tests.helpers import PROJECT_ROOT


class TrancheValidationScriptTests(unittest.TestCase):
    def setUp(self):
        self.batch_path = PROJECT_ROOT / "validate_tranche.bat"
        self.runner_path = PROJECT_ROOT / "tools" / "validate_tranche.py"
        self.ignore_path = PROJECT_ROOT / ".gitignore"
        self.batch_source = self.batch_path.read_text(encoding="utf-8")
        self.runner_source = self.runner_path.read_text(encoding="utf-8")
        self.lower = (self.batch_source + "\n" + self.runner_source).lower()

    def test_validation_script_captures_required_non_visual_acceptance(self):
        self.assertTrue(self.batch_path.is_file())
        self.assertTrue(self.runner_path.is_file())
        self.assertIn("!validate_tranche.bat", self.ignore_path.read_text(encoding="utf-8"))
        self.assertIn(r"%USERPROFILE%\Desktop\console_output.txt", self.batch_source)
        self.assertIn(r"tools\validate_tranche.py", self.batch_source)
        self.assertNotIn(":build_command", self.batch_source)
        self.assertNotIn("EnableDelayedExpansion", self.batch_source)
        self.assertIn("tests.presentation.test_designer_editing", self.runner_source)
        self.assertIn("tests.presentation.test_designer_structure", self.runner_source)
        self.assertIn("tests.presentation.test_designer_preview", self.runner_source)
        self.assertIn("tests.presentation.test_designer_preview_host", self.runner_source)
        self.assertIn("tests.presentation.test_designer_clipboard", self.runner_source)
        self.assertIn("tests.presentation.test_designer_selection", self.runner_source)
        self.assertIn("tests.presentation.test_designer_project", self.runner_source)
        self.assertIn("tests.presentation.test_designer_navigation", self.runner_source)
        self.assertIn("tests.presentation.test_tkinter_backend", self.runner_source)
        self.assertIn("tools/localization/build_locales.py", self.runner_source)
        self.assertIn('"discover", "-s", "tests", "-t", "."', self.runner_source)
        self.assertIn('"-m", "unittest", "discover"', self.runner_source)
        self.assertIn('"--ui-backend", "headless"', self.runner_source)
        self.assertIn('"compileall", "-q", "app", "tests", "examples"', self.runner_source)
        self.assertIn('("git", "rev-parse", "origin/dev")', self.runner_source)
        self.assertIn('("git", "diff", "--check")', self.runner_source)
        self.assertIn("DISCOVERY_TEST_COUNT = 707", self.runner_source)
        self.assertIn("TRANCHE VALIDATION PASSED", self.runner_source)
        self.assertIn("TRANCHE VALIDATION FAILED", self.runner_source)

    def test_validation_script_never_stages_commits_or_pushes(self):
        self.assertNotIn("git add", self.lower)
        self.assertNotIn("git commit", self.lower)
        self.assertNotIn("git push", self.lower)
        self.assertNotIn("pre_commit_check.bat", self.lower)


if __name__ == "__main__":
    unittest.main(verbosity=2)
