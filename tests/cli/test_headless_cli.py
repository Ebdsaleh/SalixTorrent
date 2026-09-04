import hashlib
import io
import os
import queue
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import PROJECT_ROOT

from app.cli.headless import HeadlessOptions, HeadlessReporter, HeadlessRunner
from app.logic.bencode import Bencode
from app.logic.session import SessionState
from app.logic.torrent_manager import TorrentManager
from app.logic.transfer_add import (
    TransferAddHandle,
    TransferAddRequest,
    TransferSourceKind,
    classify_transfer_source,
)


ROOT = PROJECT_ROOT


class _TorrentStub:
    hex_info_hash = "a" * 40


class _SessionStub:
    torrent = _TorrentStub()


class _AddManagerStub:
    def __init__(self):
        self.magnet_calls = []
        self.torrent_calls = []
        self.started = []

    def add_magnet(self, uri, **kwargs):
        self.magnet_calls.append((uri, kwargs))
        return "b" * 40

    def add_torrent(self, path, **kwargs):
        self.torrent_calls.append((path, kwargs))
        return _SessionStub()

    def start_torrent(self, info_hash):
        self.started.append(info_hash)


class _HeadlessManagerStub:
    def __init__(self, event_queue):
        self.event_queue = event_queue
        self.started_engine = False
        self.shutdown_called = False
        self.request = None

    def start_engine(self):
        self.started_engine = True

    def add_transfer(self, request):
        self.request = request
        info_hash = "c" * 40
        self.event_queue.put(
            {
                "type": "MAGNET_PROGRESS",
                "info_hash": info_hash,
                "display_name": "Example",
                "stage": "Metadata",
                "progress": 0.5,
                "message": "Receiving metadata",
            }
        )
        self.event_queue.put(
            {
                "type": "MAGNET_READY",
                "info_hash": info_hash,
                "display_name": "Example",
                "stage": "Ready",
                "progress": 1.0,
                "message": "Metadata received",
            }
        )
        self.event_queue.put(
            {
                "type": "TRANSFER_STATS",
                "info_hash": info_hash,
                "torrent_name": "example.bin",
                "state": SessionState.SEEDING,
                "state_label": "Seeding",
                "wanted_progress": 1.0,
                "downloaded_bytes": 1024,
                "total_bytes": 1024,
                "speed_kbps": 0.0,
                "upload_speed_kbps": 12.5,
                "connected_peers": 2,
            }
        )
        return TransferAddHandle(
            kind=TransferSourceKind.MAGNET,
            source=request.source,
            info_hash=info_hash,
        )

    def shutdown(self):
        self.shutdown_called = True


class TestTransferAddContract(unittest.TestCase):
    def test_source_classification(self):
        self.assertEqual(
            classify_transfer_source("magnet:?xt=urn:btih:" + "a" * 40),
            TransferSourceKind.MAGNET,
        )
        self.assertEqual(
            classify_transfer_source("example.torrent"),
            TransferSourceKind.TORRENT,
        )
        with self.assertRaises(ValueError):
            classify_transfer_source("   ")

    def test_shared_add_path_routes_magnets_with_request_policy(self):
        manager = _AddManagerStub()
        request = TransferAddRequest(
            source="magnet:?xt=urn:btih:" + "b" * 40,
            start=False,
            persist=False,
            max_peers=11,
            download_dir="downloads-alt",
        )

        handle = TorrentManager.add_transfer(manager, request)

        self.assertEqual(handle.kind, TransferSourceKind.MAGNET)
        self.assertEqual(handle.info_hash, "b" * 40)
        self.assertIsNone(handle.session)
        self.assertEqual(len(manager.magnet_calls), 1)
        _uri, kwargs = manager.magnet_calls[0]
        self.assertFalse(kwargs["start"])
        self.assertFalse(kwargs["persist"])
        self.assertEqual(kwargs["max_peers"], 11)
        self.assertEqual(kwargs["download_dir"], "downloads-alt")

    def test_shared_add_path_routes_torrent_and_start_policy(self):
        manager = _AddManagerStub()
        request = TransferAddRequest(
            source="example.torrent",
            start=True,
            persist=False,
            max_peers=7,
            download_dir="downloads-alt",
        )

        handle = TorrentManager.add_transfer(manager, request)

        self.assertEqual(handle.kind, TransferSourceKind.TORRENT)
        self.assertEqual(handle.info_hash, "a" * 40)
        self.assertIsNotNone(handle.session)
        self.assertEqual(manager.started, ["a" * 40])
        _path, kwargs = manager.torrent_calls[0]
        self.assertFalse(kwargs["persist"])
        self.assertEqual(kwargs["max_peers"], 7)
        self.assertEqual(kwargs["download_dir"], "downloads-alt")


class TestHeadlessPresentation(unittest.TestCase):
    def test_headless_module_has_no_dearpygui_dependency(self):
        # unittest discovery imports every test module before executing tests, so
        # another GUI-focused test may legitimately have imported Dear PyGui in
        # this process already.  Probe the headless import contract in a clean
        # interpreter instead of depending on global test-order state.
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "import app.cli.headless; "
                    "print(int('dearpygui.dearpygui' in sys.modules))"
                ),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), "0")

    def test_reporter_emits_structured_json_status(self):
        stream = io.StringIO()
        reporter = HeadlessReporter(stream=stream, status_interval=0.1, json_status=True)
        reporter.transfer_event(
            {
                "type": "TRANSFER_STATS",
                "info_hash": "d" * 40,
                "torrent_name": "sample.iso",
                "state": SessionState.DOWNLOADING,
                "state_label": "Downloading",
                "wanted_progress": 0.25,
                "downloaded_bytes": 256,
                "total_bytes": 1024,
                "speed_kbps": 100.0,
                "upload_speed_kbps": 5.0,
                "connected_peers": 3,
            },
            force=True,
        )
        output = stream.getvalue()
        self.assertIn('"type": "status"', output)
        self.assertIn('"progress": 0.25', output)
        self.assertIn('"state": "Downloading"', output)

    def test_runner_uses_nonpersistent_shared_add_and_clean_shutdown(self):
        events = queue.Queue()
        manager = _HeadlessManagerStub(events)
        stream = io.StringIO()
        runner = HeadlessRunner(manager, events, stream=stream)

        result = runner.run(
            "magnet:?xt=urn:btih:" + "c" * 40,
            HeadlessOptions(
                max_peers=9,
                download_dir="headless-downloads",
                status_interval=0.1,
                exit_on_complete=True,
            ),
        )

        self.assertEqual(result, 0)
        self.assertTrue(manager.started_engine)
        self.assertTrue(manager.shutdown_called)
        self.assertIsInstance(manager.request, TransferAddRequest)
        self.assertFalse(manager.request.persist)
        self.assertTrue(manager.request.start)
        self.assertEqual(manager.request.max_peers, 9)
        self.assertEqual(manager.request.download_dir, "headless-downloads")
        self.assertIn("[Magnet] Metadata", stream.getvalue())
        self.assertIn("Seeding", stream.getvalue())


class TestHeadlessPersistenceIsolation(unittest.TestCase):
    def tearDown(self):
        instance = TorrentManager._instance
        if instance is not None:
            try:
                instance.shutdown()
            except Exception:
                pass
        TorrentManager._instance = None


    def test_nonpersistent_magnet_resolves_through_real_manager_without_desktop_state(self):
        old_state = os.environ.get("SALIX_T_STATE_DIR")
        raw_info = Bencode.encode(
            {
                b"name": b"headless.bin",
                b"piece length": 16 * 1024,
                b"pieces": hashlib.sha1(b"headless").digest(),
                b"length": len(b"headless"),
            }
        )
        info_hash = hashlib.sha1(raw_info).hexdigest()
        magnet_uri = f"magnet:?xt=urn:btih:{info_hash}&dn=headless.bin"

        class FakeFetcher:
            def __init__(self, *_args, progress_callback=None, **_kwargs):
                self.progress_callback = progress_callback

            async def resolve(self):
                if self.progress_callback:
                    self.progress_callback("Metadata", 0.5, "Receiving fake metadata")
                return raw_info

            def cancel(self):
                return None

        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["SALIX_T_STATE_DIR"] = td
                Path(td, "settings.json").write_text(
                    '{"enable_upnp": false, "enable_natpmp": false, "enable_dht": false, '
                    '"enable_lan_discovery": false}',
                    encoding="utf-8",
                )
                TorrentManager._instance = None
                events = queue.Queue()
                manager = TorrentManager(
                    ui_queue=events,
                    session_persistence_enabled=False,
                )
                manager.start_engine()
                with mock.patch(
                    "app.logic.torrent_manager.MagnetMetadataFetcher",
                    FakeFetcher,
                ):
                    handle = manager.add_transfer(
                        TransferAddRequest(
                            source=magnet_uri,
                            start=False,
                            persist=False,
                            download_dir=str(Path(td, "downloads")),
                        )
                    )
                    self.assertEqual(handle.info_hash, info_hash)

                    ready = None
                    deadline = __import__("time").monotonic() + 3.0
                    while __import__("time").monotonic() < deadline:
                        try:
                            event = events.get(timeout=0.1)
                        except queue.Empty:
                            continue
                        if event.get("type") == "MAGNET_READY":
                            ready = event
                            break
                    self.assertIsNotNone(ready)
                    self.assertIn(info_hash, manager.sessions)
                    self.assertNotIn(info_hash, manager._persistent_sessions)
                    self.assertFalse(Path(td, "session.json").exists())
                    self.assertFalse((Path(td) / "torrents" / f"{info_hash}.torrent").exists())
                    ephemeral = list(manager._ephemeral_torrent_paths)
                    self.assertEqual(len(ephemeral), 1)
                    self.assertTrue(Path(ephemeral[0]).is_file())

                manager.shutdown()
                self.assertFalse(Path(ephemeral[0]).exists())
                TorrentManager._instance = None
        finally:
            if old_state is None:
                os.environ.pop("SALIX_T_STATE_DIR", None)
            else:
                os.environ["SALIX_T_STATE_DIR"] = old_state

    def test_disabled_session_persistence_does_not_touch_desktop_state_file(self):
        old_state = os.environ.get("SALIX_T_STATE_DIR")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["SALIX_T_STATE_DIR"] = td
                TorrentManager._instance = None
                manager = TorrentManager(
                    ui_queue=queue.Queue(),
                    session_persistence_enabled=False,
                )
                manager.save_session_state(force=True)
                self.assertFalse(Path(td, "session.json").exists())
        finally:
            if old_state is None:
                os.environ.pop("SALIX_T_STATE_DIR", None)
            else:
                os.environ["SALIX_T_STATE_DIR"] = old_state


if __name__ == "__main__":
    unittest.main(verbosity=2)
