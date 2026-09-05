from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import PROJECT_ROOT

from app.logic.bencode import Bencode
from app.logic.seeding_policy import (
    SEEDING_GOAL_EITHER,
    SEEDING_GOAL_FOREVER,
    SEEDING_GOAL_RATIO,
    SEEDING_GOAL_TIME,
)
from app.logic.torrent_file import TorrentFile
from app.logic.torrent_manager import TorrentManager
from app.persistence import (
    CURRENT_SESSION_STATE_VERSION,
    JsonSessionStateStore,
    SessionStateStoreError,
    build_session_state_store,
)
from app.persistence.session_factory import (
    DEFAULT_SESSION_DATABASE,
    SESSION_BACKEND_ENV,
    SESSION_URL_ENV,
)

try:
    import salixorm
except ImportError:
    salixorm = None

if salixorm is not None:
    from salixorm import Database, MigrationManager, MigrationRegistry

    from app.persistence.session_salixorm import (
        INITIAL_MIGRATION_REVISION,
        SEEDING_GOAL_MIGRATION_REVISION,
        META_TABLE,
        MIGRATION_REVISION,
        SESSION_KIND,
        SESSION_SCHEMA,
        TORRENTS_TABLE,
        SalixORMSessionStateStore,
        _AddSeedingGoalState,
        _CreateSessionStateSchema,
        _sqlite_url_for_path,
    )


def _snapshot(*, selected: str = "hash-a", hashes=("hash-a", "hash-b")) -> dict:
    entries = []
    for index, info_hash in enumerate(hashes):
        entries.append(
            {
                "info_hash": info_hash,
                "torrent_path": f"C:/source/{info_hash}.torrent",
                "cached_torrent_path": f"C:/cache/{info_hash}.torrent",
                "max_peers": 20 + index,
                "download_dir": f"C:/downloads/{info_hash}",
                "intent": "paused" if index == 0 else "stopped",
                "paused_from_state": "downloading" if index == 0 else None,
                "download_limit_value": 1.5 + index,
                "download_limit_unit": "MB/s",
                "upload_limit_value": 256 + index,
                "upload_limit_unit": "KB/s",
                "uploaded_bytes": 1000 + index,
                "seed_source_path": f"C:/seed/{info_hash}",
                "protocol_policy": "Auto",
                "file_priorities": ["High", "Normal"],
                "queue_priority": "High" if index == 0 else "Low",
                "seeding_goal_mode": (
                    SEEDING_GOAL_EITHER if index == 0 else SEEDING_GOAL_RATIO
                ),
                "seeding_ratio_limit": 1.5 + index,
                "seeding_time_limit_minutes": 45 + index,
                "seeding_elapsed_seconds": 120.5 + index,
                "seeding_time_goal_baseline_seconds": 20.0 + index,
                "seeding_time_days": 0,
                "seeding_time_hours": 0,
                "seeding_time_minutes_component": 45 + index,
            }
        )
    return {
        "version": CURRENT_SESSION_STATE_VERSION,
        "selected_info_hash": selected if hashes else "",
        "torrents": entries,
    }


def _write_torrent(
    path: Path,
    *,
    payload: bytes = b"session-persistence-test",
    name: bytes = b"session.bin",
) -> TorrentFile:
    info = {
        b"name": name,
        b"piece length": 16 * 1024,
        b"pieces": hashlib.sha1(payload).digest(),
        b"length": len(payload),
    }
    path.write_bytes(Bencode.encode({b"info": info}))
    return TorrentFile(str(path))


class _ManagerEnvironmentMixin:
    def setUp(self):
        self._old_state_dir = os.environ.get("SALIX_T_STATE_DIR")
        self._old_backend = os.environ.get(SESSION_BACKEND_ENV)
        self._old_url = os.environ.get(SESSION_URL_ENV)

        # Every test owns its persistence configuration.  In particular, do not
        # let a live GUI smoke-test environment (for example, an opt-in SalixORM
        # backend) change what a JSON/default-backend regression test exercises.
        os.environ.pop("SALIX_T_STATE_DIR", None)
        os.environ.pop(SESSION_BACKEND_ENV, None)
        os.environ.pop(SESSION_URL_ENV, None)
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
        self._restore_env(SESSION_BACKEND_ENV, self._old_backend)
        self._restore_env(SESSION_URL_ENV, self._old_url)

    @staticmethod
    def _restore_env(name: str, value: str | None):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


class JsonSessionStatePersistenceTests(_ManagerEnvironmentMixin, unittest.TestCase):
    def test_json_store_round_trips_current_snapshot_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.json"
            store = JsonSessionStateStore(path)
            self.assertIsNone(store.load())
            snapshot = _snapshot()
            store.save(snapshot)
            self.assertEqual(store.load(), snapshot)
            self.assertFalse(Path(str(path) + ".tmp").exists())

    def test_json_store_accepts_historical_versions_one_through_eight(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.json"
            store = JsonSessionStateStore(path)
            for version in range(1, 9):
                path.write_text(
                    json.dumps(
                        {
                            "version": version,
                            "selected_info_hash": "",
                            "max_active_downloads": 9,
                            "torrents": [],
                        }
                    ),
                    encoding="utf-8",
                )
                self.assertEqual(store.load()["version"], version)

    def test_json_store_reports_malformed_state_and_leaves_version_policy_to_manager(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.json"
            store = JsonSessionStateStore(path)
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(SessionStateStoreError):
                store.load()
            path.write_text(json.dumps({"version": 999, "torrents": []}), encoding="utf-8")
            self.assertEqual(store.load()["version"], 999)

    def test_new_json_saves_require_current_version(self):
        with tempfile.TemporaryDirectory() as td:
            store = JsonSessionStateStore(Path(td) / "session.json")
            with self.assertRaises(SessionStateStoreError):
                store.save({"version": 6, "selected_info_hash": "", "torrents": []})

    def test_default_runtime_session_backend_is_json_without_salixorm_import(self):
        env = dict(os.environ)
        env.pop(SESSION_BACKEND_ENV, None)
        env.pop(SESSION_URL_ENV, None)
        root = str(PROJECT_ROOT)
        env["PYTHONPATH"] = root
        code = (
            "import os,sys,tempfile; "
            "os.environ['SALIX_T_STATE_DIR']=tempfile.mkdtemp(); "
            "from app.logic.torrent_manager import TorrentManager; "
            "m=TorrentManager(); "
            "print(m.session_backend); "
            "print('salixorm' in sys.modules); "
            "print('app.persistence.session_salixorm' in sys.modules)"
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

    def test_disabled_session_persistence_forces_json_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["SALIX_T_STATE_DIR"] = td
            os.environ[SESSION_BACKEND_ENV] = "salixorm"
            manager = TorrentManager(session_persistence_enabled=False)
            self.assertEqual(manager.session_backend, "json")
            manager.save_session_state(force=True)
            self.assertFalse(Path(td, "session.json").exists())
            self.assertFalse(Path(td, DEFAULT_SESSION_DATABASE).exists())

    def test_current_session_no_longer_duplicates_max_active_downloads(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["SALIX_T_STATE_DIR"] = td
            Path(td, "settings.json").write_text(
                json.dumps({"max_active_downloads": 7}), encoding="utf-8"
            )
            manager = TorrentManager()
            manager.save_session_state(force=True)
            saved = JsonSessionStateStore(Path(td, "session.json")).load()
            self.assertEqual(saved["version"], CURRENT_SESSION_STATE_VERSION)
            self.assertNotIn("max_active_downloads", saved)
            self.assertEqual(manager.get_max_active_downloads(), 7)

    def test_legacy_session_queue_limit_cannot_override_application_settings(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["SALIX_T_STATE_DIR"] = td
            Path(td, "settings.json").write_text(
                json.dumps({"max_active_downloads": 7}), encoding="utf-8"
            )
            Path(td, "session.json").write_text(
                json.dumps(
                    {
                        "version": 6,
                        "selected_info_hash": "",
                        "max_active_downloads": 1,
                        "torrents": [],
                    }
                ),
                encoding="utf-8",
            )
            manager = TorrentManager()
            self.assertEqual(manager.restore_previous_session(), 0)
            self.assertEqual(manager.get_max_active_downloads(), 7)
            self.assertEqual(manager.get_app_settings()["max_active_downloads"], 7)


    def test_application_default_changes_only_affect_new_torrents(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["SALIX_T_STATE_DIR"] = td
            manager = TorrentManager()
            manager.update_app_settings(
                {
                    "default_seeding_goal_mode": SEEDING_GOAL_RATIO,
                    "default_seeding_ratio": 2.0,
                    "default_seeding_time_minutes": 90,
                }
            )

            first_path = root / "first.torrent"
            _write_torrent(first_path, payload=b"first-payload", name=b"first.bin")
            first = manager.add_torrent(str(first_path), persist=False)
            self.assertEqual(first.seeding_goal_mode, SEEDING_GOAL_RATIO)
            self.assertEqual(first.seeding_ratio_limit, 2.0)

            manager.update_app_settings(
                {
                    "default_seeding_goal_mode": SEEDING_GOAL_TIME,
                    "default_seeding_ratio": 5.0,
                    "default_seeding_time_minutes": 30,
                }
            )

            # Changing Preferences changes the template for future torrents only.
            self.assertEqual(first.seeding_goal_mode, SEEDING_GOAL_RATIO)
            self.assertEqual(first.seeding_ratio_limit, 2.0)
            self.assertEqual(first.seeding_time_limit_minutes, 90)

            second_path = root / "second.torrent"
            _write_torrent(second_path, payload=b"second-payload", name=b"second.bin")
            second = manager.add_torrent(str(second_path), persist=False)
            self.assertEqual(second.seeding_goal_mode, SEEDING_GOAL_TIME)
            self.assertEqual(second.seeding_ratio_limit, 5.0)
            self.assertEqual(second.seeding_time_limit_minutes, 30)

    def test_explicit_bulk_seeding_goal_apply_persists_every_existing_torrent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["SALIX_T_STATE_DIR"] = td
            manager = TorrentManager()

            first_path = root / "bulk-first.torrent"
            second_path = root / "bulk-second.torrent"
            first_torrent = _write_torrent(
                first_path, payload=b"bulk-first", name=b"bulk-first.bin"
            )
            second_torrent = _write_torrent(
                second_path, payload=b"bulk-second", name=b"bulk-second.bin"
            )
            manager.add_torrent(str(first_path), persist=True)
            manager.add_torrent(str(second_path), persist=True)

            applied = manager.apply_seeding_goal_to_all_existing(
                SEEDING_GOAL_EITHER, 2.75, 33
            )
            self.assertEqual(applied, 2)
            for session in manager.sessions.values():
                self.assertEqual(session.seeding_goal_mode, SEEDING_GOAL_EITHER)
                self.assertEqual(session.seeding_ratio_limit, 2.75)
                self.assertEqual(session.seeding_time_limit_minutes, 33)

            persisted = JsonSessionStateStore(root / "session.json").load()
            self.assertIsNotNone(persisted)
            self.assertEqual(len(persisted["torrents"]), 2)
            for entry in persisted["torrents"]:
                self.assertEqual(entry["seeding_goal_mode"], SEEDING_GOAL_EITHER)
                self.assertEqual(entry["seeding_ratio_limit"], 2.75)
                self.assertEqual(entry["seeding_time_limit_minutes"], 33)

            # Prove the per-torrent values survive a normal manager restart.
            manager.shutdown()
            TorrentManager._instance = None
            restored = TorrentManager()
            self.assertEqual(restored.restore_previous_session(), 2)
            for info_hash in (first_torrent.hex_info_hash, second_torrent.hex_info_hash):
                session = restored.sessions[info_hash]
                self.assertEqual(session.seeding_goal_mode, SEEDING_GOAL_EITHER)
                self.assertEqual(session.seeding_ratio_limit, 2.75)
                self.assertEqual(session.seeding_time_limit_minutes, 33)

    def test_running_manager_bulk_apply_uses_command_boundary_and_emits_updates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["SALIX_T_STATE_DIR"] = td
            manager = TorrentManager()

            first_path = root / "running-first.torrent"
            second_path = root / "running-second.torrent"
            _write_torrent(first_path, payload=b"running-first", name=b"running-first.bin")
            _write_torrent(second_path, payload=b"running-second", name=b"running-second.bin")
            manager.add_torrent(str(first_path), persist=True)
            manager.add_torrent(str(second_path), persist=True)

            while True:
                try:
                    manager.ui_queue.get_nowait()
                except Exception:
                    break

            manager.start_engine()
            self.assertEqual(
                manager.apply_seeding_goal_to_all_existing(SEEDING_GOAL_TIME, 4.0, 17),
                2,
            )

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if all(
                    session.seeding_goal_mode == SEEDING_GOAL_TIME
                    and session.seeding_time_limit_minutes == 17
                    for session in manager.sessions.values()
                ):
                    break
                time.sleep(0.01)
            else:
                self.fail("Timed out waiting for bulk seeding-goal command")

            update_hashes = set()
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and len(update_hashes) < 2:
                try:
                    event = manager.ui_queue.get_nowait()
                except Exception:
                    time.sleep(0.01)
                    continue
                if event.get("type") == "SEEDING_GOAL_UPDATED":
                    update_hashes.add(event.get("info_hash"))
            self.assertEqual(update_hashes, set(manager.sessions))

    def test_historical_v8_timed_goal_starts_a_fresh_instance_window(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["SALIX_T_STATE_DIR"] = td
            torrent_path = root / "historical-v8.torrent"
            torrent = _write_torrent(torrent_path)
            elapsed = 70 * 60.0
            Path(td, "session.json").write_text(
                json.dumps(
                    {
                        "version": 8,
                        "selected_info_hash": torrent.hex_info_hash,
                        "torrents": [
                            {
                                "info_hash": torrent.hex_info_hash,
                                "torrent_path": str(torrent_path),
                                "cached_torrent_path": "",
                                "max_peers": 25,
                                "download_dir": str(root / "downloads"),
                                "intent": "stopped",
                                "paused_from_state": None,
                                "download_limit_value": 0.0,
                                "download_limit_unit": "KB/s",
                                "upload_limit_value": 0.0,
                                "upload_limit_unit": "KB/s",
                                "uploaded_bytes": 0,
                                "seed_source_path": "",
                                "protocol_policy": "Auto",
                                "file_priorities": ["Normal"],
                                "queue_priority": "Normal",
                                "seeding_goal_mode": SEEDING_GOAL_TIME,
                                "seeding_ratio_limit": 1.0,
                                "seeding_time_limit_minutes": 60,
                                "seeding_elapsed_seconds": elapsed,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            manager = TorrentManager()
            self.assertEqual(manager.restore_previous_session(), 1)
            session = manager.sessions[torrent.hex_info_hash]
            self.assertEqual(session.seeding_elapsed_seconds, elapsed)
            self.assertEqual(session.seeding_time_goal_baseline_seconds, elapsed)
            self.assertEqual(session.seeding_goal_elapsed_seconds, 0.0)
            self.assertFalse(session.seeding_goal_status().reached)

            rewritten = JsonSessionStateStore(root / "session.json").load()
            self.assertEqual(rewritten["version"], CURRENT_SESSION_STATE_VERSION)
            entry = rewritten["torrents"][0]
            self.assertEqual(entry["seeding_time_goal_baseline_seconds"], elapsed)

    def test_historical_v7_restore_defaults_to_indefinite_seeding_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["SALIX_T_STATE_DIR"] = td
            torrent_path = root / "historical-v7.torrent"
            torrent = _write_torrent(torrent_path)
            Path(td, "settings.json").write_text(
                json.dumps(
                    {
                        "default_seeding_goal_mode": SEEDING_GOAL_RATIO,
                        "default_seeding_ratio": 3.0,
                        "default_seeding_time_minutes": 240,
                    }
                ),
                encoding="utf-8",
            )
            legacy = _snapshot(selected=torrent.hex_info_hash, hashes=(torrent.hex_info_hash,))
            legacy["version"] = 7
            entry = legacy["torrents"][0]
            for key in (
                "seeding_goal_mode",
                "seeding_ratio_limit",
                "seeding_time_limit_minutes",
                "seeding_elapsed_seconds",
            ):
                entry.pop(key, None)
            entry.update(
                {
                    "torrent_path": str(torrent_path),
                    "cached_torrent_path": "",
                    "download_dir": str(root / "downloads"),
                    "intent": "stopped",
                    "paused_from_state": None,
                }
            )
            Path(td, "session.json").write_text(json.dumps(legacy), encoding="utf-8")

            manager = TorrentManager()
            self.assertEqual(manager.restore_previous_session(), 1)
            session = manager.sessions[torrent.hex_info_hash]
            self.assertEqual(session.seeding_goal_mode, SEEDING_GOAL_FOREVER)
            self.assertEqual(session.seeding_ratio_limit, 1.0)
            self.assertEqual(session.seeding_time_limit_minutes, 60)
            self.assertEqual(session.seeding_elapsed_seconds, 0.0)

            rewritten = JsonSessionStateStore(root / "session.json").load()
            self.assertEqual(rewritten["version"], CURRENT_SESSION_STATE_VERSION)
            self.assertEqual(
                rewritten["torrents"][0]["seeding_goal_mode"],
                SEEDING_GOAL_FOREVER,
            )

    def test_manager_snapshot_persists_per_torrent_seeding_goal_and_elapsed_time(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["SALIX_T_STATE_DIR"] = td
            torrent_path = root / "policy.torrent"
            torrent = _write_torrent(torrent_path)
            manager = TorrentManager()
            session = manager.add_torrent(
                str(torrent_path),
                persist=True,
                download_dir=str(root / "downloads"),
            )
            session._seeding_elapsed_seconds = 321.5
            session.set_seeding_goal(
                SEEDING_GOAL_EITHER,
                2.25,
                75,
                time_components=(0, 1, 15),
                restart_time_window=True,
                emit=False,
            )

            snapshot = manager._build_persistent_state()
            entry = next(
                item for item in snapshot["torrents"]
                if item["info_hash"] == torrent.hex_info_hash
            )
            self.assertEqual(snapshot["version"], CURRENT_SESSION_STATE_VERSION)
            self.assertEqual(entry["seeding_goal_mode"], SEEDING_GOAL_EITHER)
            self.assertEqual(entry["seeding_ratio_limit"], 2.25)
            self.assertEqual(entry["seeding_time_limit_minutes"], 75)
            self.assertEqual(entry["seeding_elapsed_seconds"], 321.5)
            self.assertEqual(entry["seeding_time_goal_baseline_seconds"], 321.5)
            self.assertEqual(entry["seeding_time_days"], 0)
            self.assertEqual(entry["seeding_time_hours"], 1)
            self.assertEqual(entry["seeding_time_minutes_component"], 15)


    def test_queue_table_starts_in_persisted_queue_order_mode(self):
        source = (PROJECT_ROOT / "app/views/download_view.py").read_text(encoding="utf-8")
        start = source.index("                with dpg.table(")
        end = source.index("                ) as self.queue_table:", start)
        table_config = source[start:end]
        self.assertIn("sortable=True", table_config)
        self.assertIn("sort_tristate=True", table_config)
        self.assertNotIn("default_sort=True", table_config)

    def test_manual_queue_reorder_exits_visual_sort_mode(self):
        source = (PROJECT_ROOT / "app/views/download_view.py").read_text(encoding="utf-8")
        for start_name, end_name in (
            ("    def _move_torrent_up", "    def _move_torrent_down"),
            ("    def _move_torrent_down", "    def _refresh_context_menu_state"),
        ):
            start = source.index(start_name)
            end = source.index(end_name, start + len(start_name))
            handler = source[start:end]
            self.assertIn("if self._sort_specs:", handler)
            self.assertIn("self._clear_queue_sort()", handler)
            self.assertNotIn("self._apply_queue_sort()", handler)


    def test_restore_drops_entry_when_source_and_cached_metainfo_are_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["SALIX_T_STATE_DIR"] = td
            missing_hash = "a" * 40
            snapshot = _snapshot(selected=missing_hash, hashes=(missing_hash,))
            entry = snapshot["torrents"][0]
            entry["torrent_path"] = str(root / "missing-source.torrent")
            entry["cached_torrent_path"] = str(root / "missing-cache.torrent")
            JsonSessionStateStore(root / "session.json").save(snapshot)

            manager = TorrentManager()
            self.assertEqual(manager.restore_previous_session(), 0)
            self.assertEqual(manager.sessions, {})
            self.assertEqual(manager._queue_order, [])
            self.assertEqual(manager.get_selected_torrent(), "")

            rewritten = JsonSessionStateStore(root / "session.json").load()
            self.assertEqual(rewritten["version"], CURRENT_SESSION_STATE_VERSION)
            self.assertEqual(rewritten["selected_info_hash"], "")
            self.assertEqual(rewritten["torrents"], [])

    def test_restore_refuses_metainfo_when_saved_info_hash_does_not_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["SALIX_T_STATE_DIR"] = td
            torrent_path = root / "actual.torrent"
            torrent = _write_torrent(torrent_path)
            wrong_hash = "b" * len(torrent.hex_info_hash)
            self.assertNotEqual(wrong_hash, torrent.hex_info_hash)

            snapshot = _snapshot(selected=wrong_hash, hashes=(wrong_hash,))
            entry = snapshot["torrents"][0]
            entry.update(
                {
                    "torrent_path": str(torrent_path),
                    "cached_torrent_path": "",
                    "download_dir": str(root / "downloads"),
                    "intent": "stopped",
                }
            )
            JsonSessionStateStore(root / "session.json").save(snapshot)

            manager = TorrentManager()
            self.assertEqual(manager.restore_previous_session(), 0)
            self.assertNotIn(torrent.hex_info_hash, manager.sessions)
            self.assertEqual(manager._queue_order, [])
            self.assertEqual(manager.get_selected_torrent(), "")

            rewritten = JsonSessionStateStore(root / "session.json").load()
            self.assertEqual(rewritten["selected_info_hash"], "")
            self.assertEqual(rewritten["torrents"], [])


@unittest.skipUnless(salixorm is not None, "SalixORM v0.2.0+ is not installed")
class SalixORMSessionStatePersistenceTests(_ManagerEnvironmentMixin, unittest.TestCase):
    def test_salixorm_store_round_trips_complete_snapshot_and_order(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / DEFAULT_SESSION_DATABASE
            store = SalixORMSessionStateStore(path)
            snapshot = _snapshot()
            self.assertIsNone(store.load())
            store.save(snapshot)
            self.assertEqual(SalixORMSessionStateStore(path).load(), snapshot)

    def test_salixorm_store_persists_schema_metadata_and_revision(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / DEFAULT_SESSION_DATABASE
            SalixORMSessionStateStore(path).save(_snapshot())
            con = sqlite3.connect(path)
            try:
                self.assertEqual(
                    con.execute(
                        f"SELECT kind, schema_version, snapshot_version FROM {META_TABLE} WHERE id=1"
                    ).fetchone(),
                    (SESSION_KIND, SESSION_SCHEMA, CURRENT_SESSION_STATE_VERSION),
                )
                self.assertEqual(
                    con.execute(f"SELECT COUNT(*) FROM {TORRENTS_TABLE}").fetchone()[0],
                    2,
                )
                self.assertEqual(
                    con.execute(
                        "SELECT revision FROM _salixorm_migrations ORDER BY applied_at DESC LIMIT 1"
                    ).fetchone()[0],
                    MIGRATION_REVISION,
                )
            finally:
                con.close()

    def test_initial_session_migration_checksum_remains_immutable(self):
        self.assertEqual(
            _CreateSessionStateSchema().compute_checksum(),
            "e0d8b8f62f187fe7d458507d0ce6b6e32c17b0d094a50b8ef21a8273ec058c99",
        )

    def test_v8_seeding_goal_migration_checksum_remains_immutable(self):
        self.assertEqual(
            _AddSeedingGoalState().compute_checksum(),
            "3cb516ab6f4db35197ea5f4d7e8204e03fca42a2caa561d2bdb6c0394c87098c",
        )

    def test_salixorm_v8_database_migrates_to_instanced_time_goal_state(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / DEFAULT_SESSION_DATABASE
            url = _sqlite_url_for_path(path)
            v8_registry = MigrationRegistry([
                _CreateSessionStateSchema,
                _AddSeedingGoalState,
            ])
            elapsed = 70 * 60.0
            with Database(url, options={"foreign_keys": True}) as db:
                MigrationManager(db).upgrade_to(
                    v8_registry, SEEDING_GOAL_MIGRATION_REVISION
                )
                db.execute(
                    f"INSERT INTO {META_TABLE} "
                    "(id, kind, schema_version, snapshot_version, selected_info_hash) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (1, SESSION_KIND, SESSION_SCHEMA, 8, "hash-a"),
                )
                db.execute(
                    f"INSERT INTO {TORRENTS_TABLE} ("
                    "info_hash, queue_position, torrent_path, cached_torrent_path, "
                    "max_peers, download_dir, intent, paused_from_state, "
                    "download_limit_value, download_limit_unit, upload_limit_value, "
                    "upload_limit_unit, uploaded_bytes, seed_source_path, protocol_policy, "
                    "file_priorities_json, queue_priority, seeding_goal_mode, "
                    "seeding_ratio_limit, seeding_time_limit_minutes, seeding_elapsed_seconds"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "hash-a", 0, "C:/source/hash-a.torrent", "C:/cache/hash-a.torrent",
                        25, "C:/downloads/hash-a", "stopped", "", 0.0, "KB/s",
                        0.0, "KB/s", 1234, "", "Auto", "[]", "Normal",
                        SEEDING_GOAL_TIME, 1.0, 60, elapsed,
                    ),
                )

            restored = SalixORMSessionStateStore(path).load()
            self.assertEqual(restored["version"], CURRENT_SESSION_STATE_VERSION)
            entry = restored["torrents"][0]
            self.assertEqual(entry["seeding_time_goal_baseline_seconds"], elapsed)
            self.assertEqual(entry["seeding_time_days"], 0)
            self.assertEqual(entry["seeding_time_hours"], 0)
            self.assertEqual(entry["seeding_time_minutes_component"], 0)

            con = sqlite3.connect(path)
            try:
                self.assertEqual(
                    con.execute(
                        "SELECT revision FROM _salixorm_migrations "
                        "ORDER BY applied_at DESC LIMIT 1"
                    ).fetchone()[0],
                    MIGRATION_REVISION,
                )
            finally:
                con.close()

    def test_salixorm_v7_database_migrates_through_current_session_schema(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / DEFAULT_SESSION_DATABASE
            url = _sqlite_url_for_path(path)
            initial_registry = MigrationRegistry([_CreateSessionStateSchema])
            with Database(url, options={"foreign_keys": True}) as db:
                MigrationManager(db).upgrade_to(
                    initial_registry, INITIAL_MIGRATION_REVISION
                )
                db.execute(
                    f"INSERT INTO {META_TABLE} "
                    "(id, kind, schema_version, snapshot_version, selected_info_hash) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (1, SESSION_KIND, SESSION_SCHEMA, 7, "hash-a"),
                )
                db.execute(
                    f"INSERT INTO {TORRENTS_TABLE} ("
                    "info_hash, queue_position, torrent_path, cached_torrent_path, "
                    "max_peers, download_dir, intent, paused_from_state, "
                    "download_limit_value, download_limit_unit, upload_limit_value, "
                    "upload_limit_unit, uploaded_bytes, seed_source_path, protocol_policy, "
                    "file_priorities_json, queue_priority"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "hash-a", 0, "C:/source/hash-a.torrent", "C:/cache/hash-a.torrent",
                        25, "C:/downloads/hash-a", "stopped", "", 0.0, "KB/s",
                        0.0, "KB/s", 1234, "", "Auto", "[]", "Normal",
                    ),
                )

            restored = SalixORMSessionStateStore(path).load()
            self.assertEqual(restored["version"], CURRENT_SESSION_STATE_VERSION)
            self.assertEqual(restored["selected_info_hash"], "hash-a")
            entry = restored["torrents"][0]
            self.assertEqual(entry["seeding_goal_mode"], SEEDING_GOAL_FOREVER)
            self.assertEqual(entry["seeding_ratio_limit"], 1.0)
            self.assertEqual(entry["seeding_time_limit_minutes"], 60)
            self.assertEqual(entry["seeding_elapsed_seconds"], 0.0)

            con = sqlite3.connect(path)
            try:
                columns = {
                    row[1] for row in con.execute(f"PRAGMA table_info({TORRENTS_TABLE})")
                }
                self.assertTrue(
                    {
                        "seeding_goal_mode",
                        "seeding_ratio_limit",
                        "seeding_time_limit_minutes",
                        "seeding_elapsed_seconds",
                        "seeding_time_goal_baseline_seconds",
                        "seeding_time_days",
                        "seeding_time_hours",
                        "seeding_time_minutes_component",
                    }.issubset(columns)
                )
                self.assertEqual(
                    con.execute(
                        "SELECT revision FROM _salixorm_migrations "
                        "ORDER BY applied_at DESC LIMIT 1"
                    ).fetchone()[0],
                    MIGRATION_REVISION,
                )
            finally:
                con.close()

    def test_salixorm_store_supports_empty_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / DEFAULT_SESSION_DATABASE
            snapshot = _snapshot(selected="", hashes=())
            store = SalixORMSessionStateStore(path)
            store.save(snapshot)
            self.assertEqual(store.load(), snapshot)

    def test_salixorm_store_rejects_in_memory_and_non_sqlite_urls(self):
        with self.assertRaises(SessionStateStoreError):
            SalixORMSessionStateStore("sqlite:///:memory:")
        with self.assertRaises(SessionStateStoreError):
            SalixORMSessionStateStore("postgresql://localhost/salix")

    def test_salixorm_store_refuses_corrupt_semantic_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / DEFAULT_SESSION_DATABASE
            SalixORMSessionStateStore(path).save(_snapshot())
            con = sqlite3.connect(path)
            try:
                con.execute(f"UPDATE {META_TABLE} SET kind='wrong-kind' WHERE id=1")
                con.commit()
            finally:
                con.close()
            with self.assertRaises(SessionStateStoreError):
                SalixORMSessionStateStore(path).load()

    def test_salixorm_store_refuses_noncontiguous_queue_positions(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / DEFAULT_SESSION_DATABASE
            SalixORMSessionStateStore(path).save(_snapshot())
            con = sqlite3.connect(path)
            try:
                con.execute(
                    f"UPDATE {TORRENTS_TABLE} SET queue_position=5 WHERE queue_position=1"
                )
                con.commit()
            finally:
                con.close()
            with self.assertRaises(SessionStateStoreError):
                SalixORMSessionStateStore(path).load()

    def test_failed_salixorm_save_does_not_replace_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / DEFAULT_SESSION_DATABASE
            store = SalixORMSessionStateStore(path)
            original = _snapshot()
            store.save(original)
            broken = _snapshot()
            broken["torrents"][1]["info_hash"] = broken["torrents"][0]["info_hash"]
            with self.assertRaises(SessionStateStoreError):
                store.save(broken)
            self.assertEqual(SalixORMSessionStateStore(path).load(), original)

    def test_factory_bootstraps_legacy_json_then_moves_forward_in_db(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            legacy = JsonSessionStateStore(state_dir / "session.json")
            legacy_snapshot = {
                "version": 6,
                "selected_info_hash": "",
                "max_active_downloads": 4,
                "torrents": [],
            }
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "session.json").write_text(
                json.dumps(legacy_snapshot), encoding="utf-8"
            )

            store = build_session_state_store(state_dir, backend="salixorm")
            self.assertEqual(store.load(), legacy_snapshot)
            current = _snapshot(selected="", hashes=())
            store.save(current)
            self.assertEqual(
                build_session_state_store(state_dir, backend="salixorm").load(), current
            )
            self.assertEqual(legacy.load(), legacy_snapshot)

    def test_manager_can_opt_into_salixorm_session_store(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["SALIX_T_STATE_DIR"] = td
            os.environ[SESSION_BACKEND_ENV] = "salixorm"
            os.environ.pop(SESSION_URL_ENV, None)
            manager = TorrentManager()
            self.assertEqual(manager.session_backend, "salixorm")
            self.assertTrue(manager.session_storage_healthy)
            self.assertEqual(
                Path(manager.session_state_path),
                (Path(td) / DEFAULT_SESSION_DATABASE).resolve(),
            )
            manager.save_session_state(force=True)
            self.assertTrue((Path(td) / DEFAULT_SESSION_DATABASE).is_file())
            self.assertFalse((Path(td) / "session.json").exists())

    def test_manager_refuses_to_overwrite_corrupt_salixorm_session_state(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            path = state_dir / DEFAULT_SESSION_DATABASE
            SalixORMSessionStateStore(path).save(_snapshot(selected="", hashes=()))
            con = sqlite3.connect(path)
            try:
                con.execute(f"UPDATE {META_TABLE} SET kind='wrong-kind' WHERE id=1")
                con.commit()
            finally:
                con.close()

            os.environ["SALIX_T_STATE_DIR"] = td
            os.environ[SESSION_BACKEND_ENV] = "salixorm"
            manager = TorrentManager()
            self.assertIsNone(manager._load_session_state())
            self.assertFalse(manager.session_storage_healthy)
            manager.save_session_state(force=True)

            con = sqlite3.connect(path)
            try:
                self.assertEqual(
                    con.execute(f"SELECT kind FROM {META_TABLE} WHERE id=1").fetchone()[0],
                    "wrong-kind",
                )
            finally:
                con.close()

    def test_custom_salixorm_session_target_is_honored(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            custom = state_dir / "nested" / "queue.db"
            os.environ["SALIX_T_STATE_DIR"] = td
            os.environ[SESSION_BACKEND_ENV] = "salixorm"
            os.environ[SESSION_URL_ENV] = str(custom)
            manager = TorrentManager()
            manager.save_session_state(force=True)
            self.assertEqual(Path(manager.session_state_path), custom.resolve())
            self.assertTrue(custom.is_file())

    def test_salixorm_snapshot_can_restore_real_stopped_torrent_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            torrent_path = root / "restore.torrent"
            torrent = _write_torrent(torrent_path)
            info_hash = torrent.hex_info_hash
            snapshot = _snapshot(selected=info_hash, hashes=(info_hash,))
            entry = snapshot["torrents"][0]
            entry.update(
                {
                    "torrent_path": str(torrent_path),
                    "cached_torrent_path": "",
                    "download_dir": str(root / "downloads"),
                    "intent": "stopped",
                    "paused_from_state": None,
                    "file_priorities": ["High"],
                    "queue_priority": "High",
                    "protocol_policy": "Auto",
                }
            )
            SalixORMSessionStateStore(root / DEFAULT_SESSION_DATABASE).save(snapshot)

            os.environ["SALIX_T_STATE_DIR"] = td
            os.environ[SESSION_BACKEND_ENV] = "salixorm"
            manager = TorrentManager()
            restored = manager.restore_previous_session()
            self.assertEqual(restored, 1)
            self.assertEqual(manager.get_selected_torrent(), info_hash)
            self.assertEqual(manager._queue_order, [info_hash])
            session = manager.sessions.get(info_hash)
            self.assertIsNotNone(session)
            self.assertEqual(session.queue_priority, "High")
            self.assertEqual(session.uploaded_bytes, 1000)
            self.assertEqual(session.seeding_goal_mode, SEEDING_GOAL_EITHER)
            self.assertEqual(session.seeding_ratio_limit, 1.5)
            self.assertEqual(session.seeding_time_limit_minutes, 45)
            self.assertEqual(session.seeding_elapsed_seconds, 120.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
