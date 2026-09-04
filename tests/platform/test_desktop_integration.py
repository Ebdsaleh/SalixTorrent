"""Cross-platform desktop integration regressions.

Regression lineage:
- introduced during the Phase 11 desktop-integration milestone.
"""

import os
import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import PROJECT_ROOT

from app.engine.desktop_integration import (
    DesktopCapabilities,
    DesktopIntegration,
    TRAY_ACTION_CLOSE_REQUESTED,
    TRAY_ACTION_MINIMIZE_REQUESTED,
    TRAY_ACTION_EXIT,
    TRAY_ACTION_PAUSE_ALL,
    TRAY_ACTION_RESTORE,
    TRAY_ACTION_RESUME_ALL,
    _PystrayTrayBackend,
    _TrayBackend,
    _WindowBackend,
    _is_bsd_platform,
    _make_tray_backend,
    _make_window_backend,
)
from app.logic.torrent_manager import TorrentManager


ROOT = PROJECT_ROOT


class FakeTray(_TrayBackend):
    name = "Fake tray"
    supported = True
    menu_supported = True
    notification_supported = True

    def __init__(self, actions, running=True):
        super().__init__(actions)
        self.running = running
        self.detail = "fake tray"
        self.start_calls = 0
        self.target_window = 0

    def set_target_window(self, handle):
        self.target_window = int(handle or 0)

    def start(self):
        self.start_calls += 1
        self.running = True
        return True

    def stop(self):
        self.running = False


class FakeWindow(_WindowBackend):
    name = "Fake window"
    hide_supported = True
    activation_supported = True
    minimize_detection_supported = True
    detail = "fake window"

    def __init__(self):
        super().__init__()
        self.hidden = False
        self.shown = False
        self.minimized = False
        self.bridge_installed = False

    def discover_handle(self):
        return int(self.handle or 0)

    def install_event_bridge(self, actions):
        self.bridge_installed = True
        self.actions = actions
        return bool(self.handle)

    def remove_event_bridge(self):
        self.bridge_installed = False

    def hide(self):
        self.hidden = True
        return True

    def minimize(self):
        self.minimized = True
        return True

    def show_and_activate(self):
        self.shown = True
        return True


class DesktopIntegrationTests(unittest.TestCase):
    def tearDown(self):
        DesktopIntegration._reset_for_tests()

    @staticmethod
    def make_integration(*, tray_running=True):
        integration = object.__new__(DesktopIntegration)
        integration._initialized = True
        integration._settings = {
            "system_tray_enabled": True,
            "minimize_to_tray": True,
            "close_to_tray": True,
            "native_notifications": True,
        }
        integration._actions = queue.Queue()
        integration._tray = FakeTray(integration._actions, running=tray_running)
        integration._window = FakeWindow()
        integration._window.set_handle(123)
        integration._viewport_handle = 123
        integration._tray.set_target_window(123)
        integration._last_maintain_at = 0.0
        return integration

    def test_default_settings_include_separate_close_to_tray_policy(self):
        defaults = TorrentManager._default_app_settings()
        self.assertTrue(defaults["system_tray_enabled"])
        self.assertTrue(defaults["minimize_to_tray"])
        self.assertTrue(defaults["close_to_tray"])
        normalised = TorrentManager._normalise_app_settings({})
        self.assertTrue(normalised["close_to_tray"])

    def test_capability_snapshot_exposes_independent_desktop_features(self):
        integration = self.make_integration()
        caps = integration.capability_snapshot()
        self.assertIsInstance(caps, DesktopCapabilities)
        self.assertEqual(caps.tray_backend, "Fake tray")
        self.assertTrue(caps.tray_running)
        self.assertTrue(caps.tray_menu_supported)
        self.assertTrue(caps.notifications_supported)
        self.assertTrue(caps.minimize_to_tray_supported)
        self.assertTrue(caps.close_to_tray_supported)
        self.assertIn("fake tray", caps.detail)
        self.assertIn("fake window", caps.detail)
        self.assertEqual(caps.as_dict()["tray_backend"], "Fake tray")

    def test_hide_to_tray_is_fail_safe_when_tray_is_not_live(self):
        integration = self.make_integration(tray_running=False)
        self.assertFalse(integration.should_minimize_to_tray())
        self.assertFalse(integration.should_close_to_tray())
        self.assertFalse(integration.hide_viewport())
        self.assertFalse(integration._window.hidden)

    def test_live_tray_allows_minimize_close_and_restore(self):
        integration = self.make_integration(tray_running=True)
        self.assertTrue(integration.should_minimize_to_tray())
        self.assertTrue(integration.should_close_to_tray())
        self.assertTrue(integration.hide_viewport())
        self.assertTrue(integration.show_viewport())
        self.assertTrue(integration._window.hidden)
        self.assertTrue(integration._window.shown)

    def test_tray_actions_remain_semantic_and_main_thread_consumable(self):
        integration = self.make_integration()
        expected = [
            TRAY_ACTION_RESTORE,
            TRAY_ACTION_PAUSE_ALL,
            TRAY_ACTION_RESUME_ALL,
            TRAY_ACTION_MINIMIZE_REQUESTED,
            TRAY_ACTION_CLOSE_REQUESTED,
            TRAY_ACTION_EXIT,
        ]
        for action in expected:
            integration.queue_action(action)
        self.assertEqual(integration.poll_actions(), expected)

    def test_viewport_binding_propagates_to_tray_and_installs_event_bridge(self):
        integration = self.make_integration()
        integration._window.set_handle(0)
        integration._viewport_handle = 0
        integration._tray.set_target_window(0)

        with patch.object(integration._window, "discover_handle", return_value=456):
            resolved = integration.set_viewport_handle(0)

        self.assertEqual(resolved, 456)
        self.assertEqual(integration._viewport_handle, 456)
        self.assertEqual(integration._window.handle, 456)
        self.assertEqual(integration._tray.target_window, 456)
        self.assertTrue(integration._window.bridge_installed)

    def test_normal_minimize_fallback_is_available(self):
        integration = self.make_integration()
        self.assertTrue(integration.minimize_viewport())
        self.assertTrue(integration._window.minimized)

    def test_maintain_restarts_requested_dead_tray(self):
        integration = self.make_integration(tray_running=False)
        integration.maintain()
        self.assertEqual(integration._tray.start_calls, 1)
        self.assertTrue(integration._tray.running)

    def test_bsd_detection_and_pystray_default_backend_contract(self):
        with patch.object(sys, "platform", "openbsd7"):
            self.assertTrue(_is_bsd_platform())
            self.assertTrue(_PystrayTrayBackend._is_bsd())
        with patch.object(sys, "platform", "freebsd14"):
            self.assertTrue(_is_bsd_platform())
        with patch.object(sys, "platform", "linux"):
            self.assertFalse(_is_bsd_platform())

    def test_backend_selection_contracts_cover_linux_macos_and_fallback(self):
        actions = queue.Queue()
        with patch.object(os, "name", "posix"), patch.object(sys, "platform", "linux"):
            self.assertIsInstance(_make_tray_backend(actions), _PystrayTrayBackend)
            self.assertEqual(_make_window_backend().name, "X11")
        with patch.object(os, "name", "posix"), patch.object(sys, "platform", "darwin"):
            self.assertIsInstance(_make_tray_backend(actions), _PystrayTrayBackend)
            self.assertEqual(_make_window_backend().name, "AppKit")
        with patch.object(os, "name", "posix"), patch.object(sys, "platform", "plan9"):
            self.assertEqual(_make_tray_backend(actions).name, "Unavailable")
            self.assertEqual(_make_window_backend().name, "Unavailable")

    def test_source_and_packaging_contracts(self):
        gui = (ROOT / "app/engine/gui_engine.py").read_text(encoding="utf-8")
        desktop = (ROOT / "app/engine/desktop_integration.py").read_text(encoding="utf-8")
        settings = (ROOT / "app/views/settings_view.py").read_text(encoding="utf-8")
        help_topics = (ROOT / "app/views/help_topics_view.py").read_text(encoding="utf-8")
        help_content = (ROOT / "app/localization/content/help.json").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        spec = (ROOT / "packaging/SalixTorrent.spec").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("disable_close=self._intercept_viewport_close", gui)
        self.assertIn("dpg.set_exit_callback", gui)
        self.assertIn("TRAY_ACTION_CLOSE_REQUESTED", gui)
        self.assertIn("TRAY_ACTION_MINIMIZE_REQUESTED", gui)
        self.assertIn("getattr(dpg, \"get_viewport_platform_handle\"", gui)
        self.assertIn("EnumWindows", desktop)
        self.assertIn("SetWindowLongPtrW", desktop)
        self.assertIn("SetForegroundWindow", desktop)
        self.assertIn("AttachThreadInput", desktop)
        self.assertIn("_request_restore", desktop)
        self.assertIn("TaskbarCreated", desktop)
        self.assertIn("pystray", desktop)
        self.assertIn("Close window to system tray", settings)
        # The semantic-documentation migration moved canonical wording out of the
        # renderer. The desktop-integration article must still exist in semantic Help data.
        self.assertIn("canonical_help_topics", help_topics)
        self.assertIn("Desktop Integration & System Tray", help_content)
        self.assertIn("pystray>=0.19.5", requirements)
        self.assertIn("pyobjc-framework-Quartz", requirements)
        self.assertIn('"pystray"', spec)
        self.assertIn("!packaging/build_windows.bat", gitignore)
        self.assertTrue((ROOT / "packaging/build_windows.bat").is_file())


if __name__ == "__main__":
    unittest.main()
