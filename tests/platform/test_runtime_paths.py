"""Runtime-path regressions.

Regression lineage:
- introduced during the Phase 10 packaging/runtime-path milestone.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.engine import runtime_paths


class RuntimePathTests(unittest.TestCase):
    def _clean_runtime_env(self):
        return patch.dict(
            os.environ,
            {
                "SALIX_T_PORTABLE": "",
                "SALIX_T_STATE_DIR": "",
                "SALIX_T_DOWNLOAD_DIR": "",
            },
            clear=False,
        )

    def test_explicit_state_override_remains_release_testable(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"SALIX_T_STATE_DIR": temp_dir}, clear=False
        ):
            self.assertEqual(runtime_paths.state_directory(), Path(temp_dir).resolve())

    def test_frozen_portable_flag_moves_state_and_downloads_beside_executable(self):
        with tempfile.TemporaryDirectory() as temp_dir, self._clean_runtime_env():
            app_dir = Path(temp_dir)
            exe = app_dir / "SalixTorrent.exe"
            exe.touch()
            (app_dir / runtime_paths.PORTABLE_FLAG_NAME).write_text("portable\n")
            with patch.object(runtime_paths, "is_frozen", return_value=True), patch.object(
                runtime_paths.sys, "executable", str(exe)
            ):
                self.assertTrue(runtime_paths.portable_mode())
                application_dir = runtime_paths.application_directory()
                state_dir = runtime_paths.state_directory()
                download_dir = runtime_paths.default_download_directory()

                # Windows native-tool shells may expose TEMP using an 8.3 short
                # path while runtime path resolution returns the equivalent long
                # path. Compare filesystem identity for the existing parent and
                # then the deterministic child names.
                self.assertTrue(os.path.samefile(application_dir, app_dir))
                self.assertEqual(state_dir.name, "data")
                self.assertTrue(os.path.samefile(state_dir.parent, app_dir))
                self.assertEqual(download_dir.name, "downloads")
                self.assertTrue(os.path.samefile(download_dir.parent, app_dir))

    def test_installed_default_download_path_is_cwd_independent(self):
        with tempfile.TemporaryDirectory() as fake_home, tempfile.TemporaryDirectory() as random_cwd, self._clean_runtime_env():
            with patch.object(runtime_paths.Path, "home", return_value=Path(fake_home)):
                before = Path.cwd()
                try:
                    os.chdir(random_cwd)
                    expected = Path(fake_home) / "Downloads" / "SalixTorrent"
                    self.assertEqual(runtime_paths.default_download_directory(), expected)
                finally:
                    os.chdir(before)

    def test_resource_path_prefers_external_portable_file_then_bundle(self):
        with tempfile.TemporaryDirectory() as app_temp, tempfile.TemporaryDirectory() as bundle_temp:
            app_dir = Path(app_temp)
            bundle_dir = Path(bundle_temp)
            (bundle_dir / "README.md").write_text("bundled")
            with patch.object(runtime_paths, "application_directory", return_value=app_dir), patch.object(
                runtime_paths, "bundle_directory", return_value=bundle_dir
            ):
                self.assertEqual(runtime_paths.resource_path("README.md"), bundle_dir / "README.md")
                (app_dir / "README.md").write_text("external")
                self.assertEqual(runtime_paths.resource_path("README.md"), app_dir / "README.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)
