"""Shell-integration regressions.

Regression lineage:
- introduced during the Phase 10 packaging/runtime-path milestone.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.engine.shell_integration import ShellIntegration, open_command
from main import _build_argument_parser


class ShellIntegrationTests(unittest.TestCase):
    def test_source_registration_command_quotes_python_script_and_target(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.engine.shell_integration.is_frozen", return_value=False
        ), patch(
            "app.engine.shell_integration.application_directory",
            return_value=Path(temp_dir),
        ):
            command = open_command()
            self.assertIn(f'"{Path(sys.executable).resolve()}"', command)
            self.assertIn(f'"{Path(temp_dir).resolve() / "main.py"}"', command)
            self.assertTrue(command.endswith('"%1"'))

    def test_non_windows_shell_status_is_explicitly_unsupported(self):
        if os.name == "nt":
            self.skipTest("Non-Windows behavior only")
        status = ShellIntegration().status()
        self.assertFalse(status.supported)
        self.assertFalse(status.torrent_handler_registered)
        self.assertFalse(status.magnet_handler_registered)

    def test_cli_flags_parse_without_importing_gui(self):
        args = _build_argument_parser().parse_args(
            ["--portable", "--register-torrent-handler", "--quiet"]
        )
        self.assertTrue(args.portable)
        self.assertTrue(args.register_torrent_handler)
        self.assertTrue(args.quiet)


if __name__ == "__main__":
    unittest.main(verbosity=2)
