from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import PROJECT_ROOT

from app.logic.torrent_manager import TorrentManager
from app.persistence import (
    AppSettingsStoreError,
    JsonAppSettingsStore,
    build_app_settings_store,
)
from app.persistence.settings_factory import (
    DEFAULT_SETTINGS_DATABASE,
    SETTINGS_BACKEND_ENV,
    SETTINGS_URL_ENV,
)

try:
    import salixorm
except ImportError:
    salixorm = None

if salixorm is not None:
    from app.persistence.settings_salixorm import (
        META_TABLE,
        MIGRATION_REVISION,
        SETTINGS_KIND,
        SETTINGS_SCHEMA,
        SETTINGS_TABLE,
        SalixORMAppSettingsStore,
    )


class _ManagerEnvironmentMixin:
    def setUp(self):
        self._old_state_dir = os.environ.get("SALIX_T_STATE_DIR")
        self._old_backend = os.environ.get(SETTINGS_BACKEND_ENV)
        self._old_url = os.environ.get(SETTINGS_URL_ENV)
        TorrentManager._instance = None

    def tearDown(self):
        instance = TorrentManager._instance
        if instance is not None:
            try:
                instance.shutdown()
            except Exception:
                pass
        TorrentManager._instance = None
        self._restore_env("SALIX_T_STATE_DIR", self._old_state_dir)
        self._restore_env(SETTINGS_BACKEND_ENV, self._old_backend)
        self._restore_env(SETTINGS_URL_ENV, self._old_url)

    @staticmethod
    def _restore_env(name: str, value: str | None):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


class JsonAppSettingsPersistenceTests(_ManagerEnvironmentMixin, unittest.TestCase):
    def test_json_store_preserves_historical_atomic_settings_format(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            store = JsonAppSettingsStore(path)
            self.assertIsNone(store.load())
            store.save({"language": "en-AU", "listen_port": 6881})
            self.assertEqual(
                store.load(),
                {"language": "en-AU", "listen_port": 6881},
            )
            self.assertFalse(Path(str(path) + ".tmp").exists())

            path.write_text("{broken", encoding="utf-8")
            self.assertIsNone(store.load())

    def test_default_runtime_remains_json_and_does_not_import_salixorm(self):
        env = dict(os.environ)
        env.pop(SETTINGS_BACKEND_ENV, None)
        env.pop(SETTINGS_URL_ENV, None)
        root = str(PROJECT_ROOT)
        env["PYTHONPATH"] = root
        code = (
            "import os, sys, tempfile; "
            "os.environ['SALIX_T_STATE_DIR']=tempfile.mkdtemp(); "
            "from app.logic.torrent_manager import TorrentManager; "
            "m=TorrentManager(session_persistence_enabled=False); "
            "print(m.settings_backend); "
            "print('salixorm' in sys.modules); "
            "print('app.persistence.settings_salixorm' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.splitlines(), ["json", "False", "False"])

    def test_torrent_manager_default_json_behavior_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["SALIX_T_STATE_DIR"] = td
            os.environ.pop(SETTINGS_BACKEND_ENV, None)
            os.environ.pop(SETTINGS_URL_ENV, None)
            Path(td, "settings.json").write_text(
                json.dumps({"listen_port": 7000, "language": "en-GB"}),
                encoding="utf-8",
            )
            manager = TorrentManager(session_persistence_enabled=False)
            self.assertEqual(manager.settings_backend, "json")
            self.assertTrue(manager.settings_storage_healthy)
            self.assertEqual(
                Path(manager.settings_path),
                (Path(td) / "settings.json").resolve(),
            )
            self.assertEqual(manager.get_app_settings()["listen_port"], 7000)
            self.assertEqual(manager.get_app_settings()["language"], "en-GB")

            manager.update_app_settings({"listen_port": 7001})
            saved = json.loads(Path(td, "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["listen_port"], 7001)
            self.assertFalse(Path(td, DEFAULT_SETTINGS_DATABASE).exists())


@unittest.skipUnless(
    salixorm is not None,
    "SalixORM v0.2.0+ is not installed in this environment",
)
class SalixORMAppSettingsPersistenceTests(_ManagerEnvironmentMixin, unittest.TestCase):
    def test_salixorm_store_round_trips_complete_settings_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / DEFAULT_SETTINGS_DATABASE
            store = SalixORMAppSettingsStore(db_path)
            settings = {
                "download_dir": str(Path(td) / "downloads"),
                "listen_port": 51413,
                "enable_dht": False,
                "global_download_limit_value": 2.5,
                "language": "en-AU",
            }
            self.assertIsNone(store.load())
            store.save(settings)
            self.assertEqual(SalixORMAppSettingsStore(db_path).load(), settings)

            con = sqlite3.connect(db_path)
            try:
                self.assertEqual(
                    con.execute(
                        f"SELECT kind, schema_version FROM {META_TABLE} WHERE id=1"
                    ).fetchone(),
                    (SETTINGS_KIND, SETTINGS_SCHEMA),
                )
                self.assertEqual(
                    con.execute(f"SELECT COUNT(*) FROM {SETTINGS_TABLE}").fetchone()[0],
                    len(settings),
                )
                self.assertEqual(
                    con.execute(
                        "SELECT revision FROM _salixorm_migrations ORDER BY applied_at DESC LIMIT 1"
                    ).fetchone()[0],
                    MIGRATION_REVISION,
                )
            finally:
                con.close()

    def test_salixorm_store_replaces_removed_keys_transactionally(self):
        with tempfile.TemporaryDirectory() as td:
            store = SalixORMAppSettingsStore(Path(td) / "settings.db")
            store.save({"alpha": 1, "beta": 2})
            store.save({"beta": 3, "gamma": True})
            self.assertEqual(store.load(), {"beta": 3, "gamma": True})

    def test_salixorm_store_rejects_in_memory_and_non_sqlite_urls(self):
        with self.assertRaises(AppSettingsStoreError):
            SalixORMAppSettingsStore("sqlite:///:memory:")
        with self.assertRaises(AppSettingsStoreError):
            SalixORMAppSettingsStore("postgresql://localhost/salix")

    def test_salixorm_store_refuses_corrupt_semantic_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.db"
            store = SalixORMAppSettingsStore(path)
            store.save({"language": "en-AU"})
            con = sqlite3.connect(path)
            try:
                con.execute(
                    f"UPDATE {META_TABLE} SET kind='wrong-kind' WHERE id=1"
                )
                con.commit()
            finally:
                con.close()
            with self.assertRaises(AppSettingsStoreError):
                SalixORMAppSettingsStore(path).load()

    def test_salixorm_factory_bootstraps_reads_from_existing_json_then_moves_forward_in_db(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            legacy = JsonAppSettingsStore(state_dir / "settings.json")
            legacy.save({"language": "en-GB", "listen_port": 7000})

            store = build_app_settings_store(state_dir, backend="salixorm")
            self.assertEqual(store.backend, "salixorm")
            self.assertEqual(
                store.load(),
                {"language": "en-GB", "listen_port": 7000},
            )

            store.save({"language": "en-US", "listen_port": 7001})
            self.assertEqual(
                build_app_settings_store(state_dir, backend="salixorm").load(),
                {"language": "en-US", "listen_port": 7001},
            )
            # The legacy JSON is a compatibility/bootstrap artifact, not a
            # second write target whose failure could compromise DB commits.
            self.assertEqual(
                legacy.load(),
                {"language": "en-GB", "listen_port": 7000},
            )

    def test_torrent_manager_can_opt_into_salixorm_without_moving_session_state(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            os.environ["SALIX_T_STATE_DIR"] = td
            os.environ[SETTINGS_BACKEND_ENV] = "salixorm"
            os.environ.pop(SETTINGS_URL_ENV, None)
            JsonAppSettingsStore(state_dir / "settings.json").save(
                {"listen_port": 7000, "language": "en-GB"}
            )

            manager = TorrentManager(session_persistence_enabled=False)
            self.assertEqual(manager.settings_backend, "salixorm")
            self.assertTrue(manager.settings_storage_healthy)
            self.assertEqual(
                Path(manager.settings_path),
                (state_dir / DEFAULT_SETTINGS_DATABASE).resolve(),
            )
            self.assertEqual(manager.get_app_settings()["listen_port"], 7000)
            self.assertEqual(
                Path(manager.session_state_path),
                (state_dir / "session.json").resolve(),
            )

            manager.update_app_settings({"listen_port": 7002, "language": "en-US"})
            self.assertTrue((state_dir / DEFAULT_SETTINGS_DATABASE).is_file())
            self.assertEqual(
                JsonAppSettingsStore(state_dir / "settings.json").load()["listen_port"],
                7000,
            )

            TorrentManager._instance = None
            restored = TorrentManager(session_persistence_enabled=False)
            self.assertEqual(restored.settings_backend, "salixorm")
            self.assertEqual(restored.get_app_settings()["listen_port"], 7002)
            self.assertEqual(restored.get_app_settings()["language"], "en-US")

    def test_manager_refuses_to_overwrite_corrupt_salixorm_settings_state(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            db_path = state_dir / DEFAULT_SETTINGS_DATABASE
            store = SalixORMAppSettingsStore(db_path)
            store.save({"listen_port": 7000})
            con = sqlite3.connect(db_path)
            try:
                con.execute(
                    f"UPDATE {META_TABLE} SET kind='wrong-kind' WHERE id=1"
                )
                con.commit()
            finally:
                con.close()

            os.environ["SALIX_T_STATE_DIR"] = td
            os.environ[SETTINGS_BACKEND_ENV] = "salixorm"
            manager = TorrentManager(session_persistence_enabled=False)
            self.assertFalse(manager.settings_storage_healthy)
            manager.update_app_settings({"listen_port": 7005})

            con = sqlite3.connect(db_path)
            try:
                self.assertEqual(
                    con.execute(f"SELECT kind FROM {META_TABLE} WHERE id=1").fetchone()[0],
                    "wrong-kind",
                )
                self.assertEqual(
                    con.execute(f"SELECT COUNT(*) FROM {SETTINGS_TABLE}").fetchone()[0],
                    1,
                )
            finally:
                con.close()

    def test_custom_salixorm_settings_target_is_honored(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            custom = state_dir / "nested" / "settings.db"
            os.environ["SALIX_T_STATE_DIR"] = td
            os.environ[SETTINGS_BACKEND_ENV] = "salixorm"
            os.environ[SETTINGS_URL_ENV] = str(custom)
            manager = TorrentManager(session_persistence_enabled=False)
            manager.update_app_settings({"listen_port": 7003})
            self.assertEqual(Path(manager.settings_path), custom.resolve())
            self.assertTrue(custom.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
