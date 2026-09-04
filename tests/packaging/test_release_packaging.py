"""Windows release-packaging regressions.

Regression lineage:
- introduced during the Phase 10 packaging/runtime-path milestone.
"""

import unittest

from tests.helpers import PROJECT_ROOT


class ReleasePackagingTests(unittest.TestCase):
    def test_release_tooling_contains_gui_cli_portable_and_installer_paths(self):
        root = PROJECT_ROOT
        spec = (root / "packaging" / "SalixTorrent.spec").read_text()
        build = (root / "packaging" / "build_windows.ps1").read_text()
        installer = (root / "packaging" / "windows" / "SalixTorrent.iss").read_text()

        self.assertIn("SalixTorrentCLI", spec)
        self.assertIn("SALIX_BUILD_TARGET", spec)
        self.assertIn("portable.flag", build)
        self.assertIn("Compress-Archive", build)
        self.assertIn("--register-torrent-handler", installer)
        self.assertIn("--register-magnet-handler", installer)
        self.assertIn("ChangesAssociations=yes", installer)
        self.assertIn('Name: "magnetassoc"', installer)
        self.assertIn("Flags: unchecked", installer)
        self.assertIn("--unregister-torrent-handler", installer)
        self.assertIn("--unregister-magnet-handler", installer)

    def test_runtime_manager_no_longer_uses_cwd_download_fallback(self):
        root = PROJECT_ROOT
        manager_source = (root / "app" / "logic" / "torrent_manager.py").read_text()
        self.assertNotIn('os.path.abspath("downloads")', manager_source)
        self.assertIn("default_download_directory", manager_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
