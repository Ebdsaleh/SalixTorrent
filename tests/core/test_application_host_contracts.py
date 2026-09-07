from __future__ import annotations

import unittest

from app.engine.application_hosts import HeadlessApplicationHost
from app.runtime.application import ApplicationHost, ApplicationSpec
from app.runtime.lifecycle import ApplicationRuntime, CallbackService, RuntimeState
from app.runtime.presentation import (
    HEADLESS_PRESENTATION,
    PresentationBackend,
    PresentationCapability,
)


class ApplicationSpecTests(unittest.TestCase):
    def test_application_spec_normalizes_title_and_frame_interval(self):
        spec = ApplicationSpec("Demo", title="", target_fps=50)
        self.assertEqual(spec.name, "Demo")
        self.assertEqual(spec.title, "Demo")
        self.assertAlmostEqual(spec.frame_interval_seconds, 0.02)
        self.assertEqual(spec.frame_interval_milliseconds, 20)

    def test_application_spec_rejects_empty_name(self):
        with self.assertRaisesRegex(ValueError, "name"):
            ApplicationSpec("   ")

    def test_application_spec_rejects_invalid_window_geometry(self):
        with self.assertRaisesRegex(ValueError, "minimum width"):
            ApplicationSpec("Demo", width=400, minimum_width=401)
        with self.assertRaisesRegex(ValueError, "minimum height"):
            ApplicationSpec("Demo", height=300, minimum_height=301)

    def test_application_spec_rejects_boolean_numeric_fields(self):
        with self.assertRaisesRegex(TypeError, "width"):
            ApplicationSpec("Demo", width=True)


class PresentationBackendTests(unittest.TestCase):
    def test_capabilities_are_inferred_from_installed_adapters(self):
        renderer = object()
        scenes = object()
        backend = PresentationBackend(
            "Sample",
            component_renderer=renderer,
            scene_host=scenes,
        )
        self.assertEqual(backend.name, "sample")
        self.assertEqual(
            backend.capabilities,
            frozenset(
                {
                    PresentationCapability.COMPONENTS,
                    PresentationCapability.SCENES,
                }
            ),
        )

    def test_supports_accepts_enum_or_canonical_string(self):
        backend = PresentationBackend("sample", plot_host=object())
        self.assertTrue(backend.supports(PresentationCapability.REALTIME_PLOTS))
        self.assertTrue(backend.supports("realtime_plots"))
        self.assertFalse(backend.supports("components"))

    def test_require_reports_missing_capability(self):
        with self.assertRaisesRegex(RuntimeError, "realtime_plots"):
            HEADLESS_PRESENTATION.require(PresentationCapability.REALTIME_PLOTS)

    def test_unknown_capability_is_not_reported_as_supported(self):
        self.assertFalse(HEADLESS_PRESENTATION.supports("future_backend_magic"))
        with self.assertRaisesRegex(ValueError, "unknown presentation capability"):
            HEADLESS_PRESENTATION.require("future_backend_magic")

    def test_headless_presentation_has_no_gui_capabilities(self):
        self.assertEqual(HEADLESS_PRESENTATION.name, "headless")
        self.assertEqual(HEADLESS_PRESENTATION.capabilities, frozenset())

    def test_presentation_backend_rejects_empty_name(self):
        with self.assertRaisesRegex(ValueError, "name"):
            PresentationBackend(" ")


class HeadlessApplicationHostTests(unittest.TestCase):
    def test_headless_host_satisfies_application_host_contract(self):
        host = HeadlessApplicationHost(ApplicationSpec("Demo"))
        self.assertIsInstance(host, ApplicationHost)

    def test_headless_host_drives_shared_runtime_for_fixed_frames(self):
        runtime = ApplicationRuntime()
        deltas = []
        runtime.services.register(
            "probe",
            CallbackService(on_update=deltas.append),
        )
        host = HeadlessApplicationHost(
            ApplicationSpec("Demo", target_fps=20),
            runtime=runtime,
            frames=3,
        )
        self.assertEqual(host.run(), 0)
        self.assertEqual(deltas, [0.05, 0.05, 0.05])
        self.assertEqual(runtime.state, RuntimeState.STOPPED)

    def test_headless_host_stop_request_ends_future_updates(self):
        runtime = ApplicationRuntime()
        calls = []
        host = HeadlessApplicationHost(
            ApplicationSpec("Demo"),
            runtime=runtime,
            frames=5,
        )

        def update(delta):
            calls.append(delta)
            host.request_stop()

        runtime.services.register("probe", CallbackService(on_update=update))
        host.run()
        self.assertEqual(len(calls), 1)

    def test_headless_host_refuses_component_build(self):
        host = HeadlessApplicationHost(ApplicationSpec("Demo"))
        with self.assertRaisesRegex(RuntimeError, "does not provide GUI"):
            host.build(object())


if __name__ == "__main__":
    unittest.main(verbosity=2)
