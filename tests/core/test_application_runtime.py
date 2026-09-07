"""Application-runtime lifecycle, diagnostics and path-policy regressions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.runtime.diagnostics import ExceptionReporter
from app.runtime.lifecycle import (
    ApplicationRuntime,
    CallbackService,
    RuntimeState,
    ServiceRegistry,
)
from app.runtime.paths import RuntimePathSpec, RuntimePaths, env_truthy


class ApplicationRuntimeTests(unittest.TestCase):
    def test_services_start_in_registration_order_and_stop_in_reverse(self):
        calls = []
        registry = ServiceRegistry()
        registry.register(
            "one",
            CallbackService(
                on_start=lambda: calls.append("start-one"),
                on_stop=lambda: calls.append("stop-one"),
            ),
        )
        registry.register(
            "two",
            CallbackService(
                on_start=lambda: calls.append("start-two"),
                on_stop=lambda: calls.append("stop-two"),
            ),
        )
        runtime = ApplicationRuntime(services=registry)
        runtime.start()
        runtime.stop()
        self.assertEqual(
            calls,
            ["start-one", "start-two", "stop-two", "stop-one"],
        )

    def test_update_dispatches_only_while_runtime_is_running(self):
        deltas = []
        runtime = ApplicationRuntime()
        runtime.services.register(
            "probe",
            CallbackService(on_update=lambda delta: deltas.append(delta)),
        )
        with self.assertRaises(RuntimeError):
            runtime.update(0.1)
        runtime.start()
        runtime.update(0.25)
        runtime.stop()
        self.assertEqual(deltas, [0.25])

    def test_negative_update_delta_is_clamped_to_zero(self):
        deltas = []
        runtime = ApplicationRuntime()
        runtime.services.register(
            "probe",
            CallbackService(on_update=lambda delta: deltas.append(delta)),
        )
        runtime.start()
        runtime.update(-3)
        runtime.stop()
        self.assertEqual(deltas, [0.0])

    def test_update_failure_isolated_when_error_handler_is_installed(self):
        errors = []
        calls = []
        runtime = ApplicationRuntime(
            error_handler=lambda name, exc: errors.append((name, str(exc)))
        )
        runtime.services.register(
            "bad",
            CallbackService(on_update=lambda _delta: (_ for _ in ()).throw(ValueError("bad"))),
        )
        runtime.services.register(
            "good",
            CallbackService(on_update=lambda _delta: calls.append("good")),
        )
        runtime.start()
        runtime.update(0.1)
        runtime.stop()
        self.assertEqual(errors, [("bad", "bad")])
        self.assertEqual(calls, ["good"])

    def test_update_failure_propagates_without_error_handler(self):
        runtime = ApplicationRuntime()
        runtime.services.register(
            "bad",
            CallbackService(on_update=lambda _delta: (_ for _ in ()).throw(ValueError("bad"))),
        )
        runtime.start()
        try:
            with self.assertRaisesRegex(ValueError, "bad"):
                runtime.update(0.1)
        finally:
            runtime.stop()

    def test_start_failure_rolls_back_already_started_services(self):
        calls = []
        runtime = ApplicationRuntime()
        runtime.services.register(
            "one",
            CallbackService(
                on_start=lambda: calls.append("start-one"),
                on_stop=lambda: calls.append("stop-one"),
            ),
        )
        runtime.services.register(
            "two",
            CallbackService(
                on_start=lambda: (_ for _ in ()).throw(RuntimeError("start failed")),
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "start failed"):
            runtime.start()
        self.assertEqual(calls, ["start-one", "stop-one"])
        self.assertEqual(runtime.state, RuntimeState.STOPPED)
        self.assertEqual(runtime.services.started_names, ())

    def test_start_failure_attempts_cleanup_of_failing_service(self):
        calls = []
        runtime = ApplicationRuntime()
        runtime.services.register(
            "partial",
            CallbackService(
                on_start=lambda: (
                    calls.append("start"),
                    (_ for _ in ()).throw(RuntimeError("partial startup")),
                ),
                on_stop=lambda: calls.append("cleanup"),
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "partial startup"):
            runtime.start()
        self.assertEqual(calls, ["start", "cleanup"])
        self.assertEqual(runtime.services.started_names, ())

    def test_control_flow_baseexceptions_are_not_swallowed_by_update_isolation(self):
        runtime = ApplicationRuntime(error_handler=lambda _name, _exc: None)
        runtime.services.register(
            "interrupt",
            CallbackService(
                on_update=lambda _delta: (_ for _ in ()).throw(KeyboardInterrupt())
            ),
        )
        runtime.start()
        try:
            with self.assertRaises(KeyboardInterrupt):
                runtime.update(0.1)
        finally:
            runtime.stop()

    def test_duplicate_and_invalid_services_are_rejected(self):
        registry = ServiceRegistry()
        registry.register("probe", CallbackService())
        with self.assertRaises(ValueError):
            registry.register("probe", CallbackService())
        with self.assertRaises(ValueError):
            registry.register("", CallbackService())
        with self.assertRaises(TypeError):
            registry.register("broken", object())

    def test_started_service_cannot_be_unregistered(self):
        runtime = ApplicationRuntime()
        runtime.services.register("probe", CallbackService())
        runtime.start()
        try:
            with self.assertRaises(RuntimeError):
                runtime.services.unregister("probe")
        finally:
            runtime.stop()

    def test_stop_is_idempotent_and_runtime_can_restart(self):
        calls = []
        runtime = ApplicationRuntime()
        runtime.services.register(
            "probe",
            CallbackService(
                on_start=lambda: calls.append("start"),
                on_stop=lambda: calls.append("stop"),
            ),
        )
        runtime.stop()
        runtime.start()
        runtime.stop()
        runtime.stop()
        runtime.start()
        runtime.stop()
        self.assertEqual(calls, ["start", "stop", "start", "stop"])


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_repeated_exception_is_rate_limited(self):
        output = []
        now = [10.0]
        reporter = ExceptionReporter(
            output=output.append,
            clock=lambda: now[0],
            throttle_seconds=5,
        )
        error = ValueError("broken")
        self.assertTrue(reporter.report("update", error))
        self.assertFalse(reporter.report("update", error))
        now[0] = 16.0
        self.assertTrue(reporter.report("update", error))
        self.assertEqual(len(output), 2)

    def test_different_exception_signature_bypasses_throttle(self):
        output = []
        reporter = ExceptionReporter(output=output.append, clock=lambda: 1.0)
        reporter.report("one", ValueError("x"))
        reporter.report("two", ValueError("x"))
        reporter.report("two", TypeError("x"))
        self.assertEqual(len(output), 3)

    def test_reporter_appends_to_optional_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "logs" / "errors.log"
            reporter = ExceptionReporter(
                log_path=path,
                output=lambda _text: None,
                clock=lambda: 1.0,
                wall_clock=lambda: 0.0,
            )
            reporter.report("scene", RuntimeError("boom"))
            text = path.read_text(encoding="utf-8")
            self.assertIn("scene: RuntimeError: boom", text)


class RuntimePathPolicyTests(unittest.TestCase):
    def _spec(self):
        return RuntimePathSpec(
            app_name="ProbeApp",
            portable_env="PROBE_PORTABLE",
            state_dir_env="PROBE_STATE_DIR",
            download_dir_env="PROBE_DOWNLOAD_DIR",
        )

    def test_truthy_environment_parser_is_deliberately_small(self):
        for value in ("1", "true", "TRUE", "yes", "on"):
            self.assertTrue(env_truthy(value))
        for value in ("", "0", "false", "disabled", None):
            self.assertFalse(env_truthy(value))

    def test_portable_mode_places_state_and_downloads_beside_application(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = Path(temp_dir)
            paths = RuntimePaths(
                self._spec(),
                bundle_directory=app / "bundle",
                application_directory=app,
                environ={"PROBE_PORTABLE": "yes"},
                os_name="nt",
                home=app / "home",
            )
            self.assertTrue(paths.portable_mode())
            self.assertEqual(paths.state_directory(), app / "data")
            self.assertEqual(paths.default_download_directory(), app / "downloads")

    def test_runtime_roots_do_not_require_filesystem_canonicalization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "bundle"
            app = root / "app"
            with patch.object(
                Path,
                "resolve",
                side_effect=AssertionError(
                    "runtime roots must not be filesystem-canonicalized"
                ),
            ):
                paths = RuntimePaths(
                    self._spec(),
                    bundle_directory=bundle,
                    application_directory=app,
                    environ={},
                    home=root / "home",
                )

            self.assertEqual(paths.bundle_directory, bundle)
            self.assertEqual(paths.application_directory, app)

    def test_explicit_path_overrides_win_over_portable_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = RuntimePaths(
                self._spec(),
                bundle_directory=root / "bundle",
                application_directory=root / "app",
                environ={
                    "PROBE_PORTABLE": "yes",
                    "PROBE_STATE_DIR": str(root / "state-override"),
                    "PROBE_DOWNLOAD_DIR": str(root / "downloads-override"),
                },
                home=root / "home",
            )
            self.assertEqual(paths.state_directory(), (root / "state-override").resolve())
            self.assertEqual(
                paths.default_download_directory(),
                (root / "downloads-override").resolve(),
            )

    def test_platform_installed_state_locations_are_application_scoped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            windows = RuntimePaths(
                self._spec(),
                bundle_directory=root,
                application_directory=root,
                environ={"LOCALAPPDATA": str(root / "local")},
                os_name="nt",
                platform="win32",
                home=root / "home",
            )
            linux = RuntimePaths(
                self._spec(),
                bundle_directory=root,
                application_directory=root,
                environ={"XDG_STATE_HOME": str(root / "xdg")},
                os_name="posix",
                platform="linux",
                home=root / "home",
            )
            mac = RuntimePaths(
                self._spec(),
                bundle_directory=root,
                application_directory=root,
                environ={},
                os_name="posix",
                platform="darwin",
                home=root / "home",
            )
            self.assertEqual(windows.state_directory(), root / "local" / "ProbeApp")
            self.assertEqual(linux.state_directory(), root / "xdg" / "ProbeApp")
            self.assertEqual(
                mac.state_directory(),
                root / "home" / "Library" / "Application Support" / "ProbeApp",
            )

    def test_resource_resolution_prefers_external_then_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = root / "app"
            bundle = root / "bundle"
            app.mkdir()
            bundle.mkdir()
            (bundle / "asset.txt").write_text("bundle")
            paths = RuntimePaths(
                self._spec(),
                bundle_directory=bundle,
                application_directory=app,
                environ={},
                home=root / "home",
            )
            self.assertEqual(paths.resource_path("asset.txt"), bundle / "asset.txt")
            (app / "asset.txt").write_text("external")
            self.assertEqual(paths.resource_path("asset.txt"), app / "asset.txt")

    def test_snapshot_is_generic_and_contains_no_product_specific_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = RuntimePaths(
                self._spec(),
                bundle_directory=root,
                application_directory=root,
                environ={"PROBE_PORTABLE": "1"},
                home=root,
            )
            snapshot = paths.snapshot(frozen=False)
            self.assertEqual(
                set(snapshot),
                {
                    "frozen",
                    "portable",
                    "application_directory",
                    "bundle_directory",
                    "state_directory",
                    "default_download_directory",
                },
            )
            self.assertTrue(snapshot["portable"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
