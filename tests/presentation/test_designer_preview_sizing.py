"""Designer-preview sizing and explicit resize-control regressions."""

from __future__ import annotations

import unittest

from tests.helpers import PROJECT_ROOT
from tests.presentation.test_gui_components import RecordingRenderer

from app.framework.components import (
    FILL,
    Button,
    ComponentLayoutProfile,
    ControlColumn,
    ControlLayout,
    ControlLayoutDefaults,
    FRAMEWORK_COMPONENT_PROFILE,
)
from app.framework.designer import capture_component_tree
from app.framework.designer_editing import DesignerEditSession
from app.framework.designer_preview import (
    DESIGNER_PREVIEW_LAYOUT_DEFAULTS,
    DesignerPreviewContext,
    designer_preview_component_profile,
    reconstruct_designer_snapshot,
)
from app.framework.designer_preview_host import DesignerPreviewHost


class DesignerPreviewSizingTests(unittest.TestCase):
    def _button_session(self, *, layout=None, profile_key=None):
        source = ControlColumn((Button("Actions", layout=layout, profile_key=profile_key),))
        snapshot = capture_component_tree(source)
        node_id = snapshot.root.children[0].node.node_id
        return DesignerEditSession(snapshot), node_id

    @staticmethod
    def _last_button_kwargs(renderer: RecordingRenderer) -> dict:
        entries = [entry for entry in renderer.created if entry[0] == "button"]
        if not entries:
            raise AssertionError("recording renderer did not create a button")
        return entries[-1][2]

    def test_preview_profile_has_human_scale_control_defaults(self):
        self.assertEqual(120, DESIGNER_PREVIEW_LAYOUT_DEFAULTS["button"].width)
        self.assertEqual(28, DESIGNER_PREVIEW_LAYOUT_DEFAULTS["button"].height)
        self.assertEqual(180, DESIGNER_PREVIEW_LAYOUT_DEFAULTS["combo_box"].width)
        self.assertEqual(220, DESIGNER_PREVIEW_LAYOUT_DEFAULTS["text_input"].width)
        self.assertEqual(160, DESIGNER_PREVIEW_LAYOUT_DEFAULTS["numeric_stepper"].width)
        self.assertEqual(220, DESIGNER_PREVIEW_LAYOUT_DEFAULTS["progress_bar"].width)

    def test_preview_profile_preserves_explicit_parent_and_rejects_bad_parent(self):
        parent = ComponentLayoutProfile(
            name="application",
            parent=FRAMEWORK_COMPONENT_PROFILE,
            layouts={"application.special": ControlLayoutDefaults(width=333)},
        )
        profile = designer_preview_component_profile(parent)
        self.assertIs(parent, profile.parent)
        self.assertEqual(333, profile.layout_for("application.special").width)
        with self.assertRaises(TypeError):
            designer_preview_component_profile(object())  # type: ignore[arg-type]

    def test_preview_context_can_disable_preview_defaults_explicitly(self):
        self.assertTrue(DesignerPreviewContext().use_preview_control_defaults)
        context = DesignerPreviewContext(use_preview_control_defaults=False)
        self.assertFalse(context.use_preview_control_defaults)
        with self.assertRaises(TypeError):
            DesignerPreviewContext(use_preview_control_defaults=1)  # type: ignore[arg-type]

    def test_rendered_preview_applies_natural_button_default_without_document_mutation(self):
        session, node_id = self._button_session()
        before = session.snapshot.to_descriptor()
        renderer = RecordingRenderer()
        host = DesignerPreviewHost(session, renderer=renderer, parent="preview")
        kwargs = self._last_button_kwargs(renderer)
        self.assertEqual((120, 28), (kwargs["width"], kwargs["height"]))
        self.assertEqual(before, session.snapshot.to_descriptor())
        self.assertNotIn("layout.width", session.node(node_id).properties)
        self.assertNotIn("layout.height", session.node(node_id).properties)
        self.assertEqual(0, session.undo_depth)
        host.close()

    def test_explicit_document_size_overrides_preview_defaults(self):
        session, _node_id = self._button_session(layout=ControlLayout(width=240, height=42))
        renderer = RecordingRenderer()
        DesignerPreviewHost(session, renderer=renderer, parent="preview")
        kwargs = self._last_button_kwargs(renderer)
        self.assertEqual((240, 42), (kwargs["width"], kwargs["height"]))

    def test_explicit_fill_remains_authoritative_in_preview(self):
        session, _node_id = self._button_session(layout=ControlLayout(width=FILL))
        renderer = RecordingRenderer()
        DesignerPreviewHost(session, renderer=renderer, parent="preview")
        kwargs = self._last_button_kwargs(renderer)
        self.assertEqual(-1, kwargs["width"])
        self.assertEqual(28, kwargs["height"])

    def test_preview_renderer_view_never_mutates_application_renderer_profile(self):
        application = ComponentLayoutProfile(
            name="application",
            parent=FRAMEWORK_COMPONENT_PROFILE,
            layouts={"application.special": ControlLayoutDefaults(width=333)},
        )
        renderer = RecordingRenderer(application)
        session, _node_id = self._button_session()
        host = DesignerPreviewHost(session, renderer=renderer, parent="preview")
        self.assertIs(application, renderer.component_profile)
        self.assertEqual("designer-preview", host.preview.root.children[0]._renderer.component_profile.name)

    def test_custom_application_profile_key_remains_available_under_preview_profile(self):
        application = ComponentLayoutProfile(
            name="application",
            parent=FRAMEWORK_COMPONENT_PROFILE,
            layouts={"application.special": ControlLayoutDefaults(width=333, height=44)},
        )
        renderer = RecordingRenderer(application)
        session, _node_id = self._button_session(profile_key="application.special")
        DesignerPreviewHost(session, renderer=renderer, parent="preview")
        kwargs = self._last_button_kwargs(renderer)
        self.assertEqual((333, 44), (kwargs["width"], kwargs["height"]))

    def test_preview_defaults_can_be_disabled_for_exact_renderer_native_sizing(self):
        session, _node_id = self._button_session()
        renderer = RecordingRenderer()
        DesignerPreviewHost(
            session,
            renderer=renderer,
            parent="preview",
            context=DesignerPreviewContext(use_preview_control_defaults=False),
        )
        kwargs = self._last_button_kwargs(renderer)
        self.assertNotIn("width", kwargs)
        self.assertNotIn("height", kwargs)

    def test_inspector_resize_is_one_checked_edit_and_rebuilds_to_explicit_size(self):
        session, node_id = self._button_session()
        renderer = RecordingRenderer()
        host = DesignerPreviewHost(session, renderer=renderer, parent="preview")
        self.assertTrue(host.set_property(node_id, "layout.width", 196))
        self.assertEqual(1, session.undo_depth)
        self.assertEqual(196, self._last_button_kwargs(renderer)["width"])
        self.assertTrue(host.set_property(node_id, "layout.height", 36))
        self.assertEqual(2, session.undo_depth)
        self.assertEqual(36, self._last_button_kwargs(renderer)["height"])

    def test_clearing_explicit_size_restores_preview_default(self):
        session, node_id = self._button_session(layout=ControlLayout(width=196, height=36))
        renderer = RecordingRenderer()
        host = DesignerPreviewHost(session, renderer=renderer, parent="preview")
        self.assertTrue(host.clear_property(node_id, "layout.width"))
        self.assertEqual(120, self._last_button_kwargs(renderer)["width"])
        self.assertTrue(host.clear_property(node_id, "layout.height"))
        self.assertEqual(28, self._last_button_kwargs(renderer)["height"])

    def test_defaults_are_render_only_and_headless_reconstruction_remains_auto(self):
        session, node_id = self._button_session()
        preview = reconstruct_designer_snapshot(session.snapshot)
        button = preview.component(node_id)
        self.assertEqual((None, None), button.layout_size_hint())
        self.assertNotIn("layout.width", preview.recapture().root.children[0].node.properties)

    def test_desktop_preview_mount_and_dpg_inspector_do_not_reintroduce_fill_geometry(self):
        inspector_source = (
            PROJECT_ROOT
            / "app"
            / "engine"
            / "designer_inspector_panel_hosts"
            / "dearpygui.py"
        ).read_text(encoding="utf-8")
        self.assertIn("editor_width: int = 170", inspector_source)
        self.assertIn("width=self.editor_width", inspector_source)
        self.assertIn('label="Apply"', inspector_source)
        self.assertIn('label="Default"', inspector_source)
        self.assertIn("with dpg.group(horizontal=False):", inspector_source)
        self.assertNotIn("width=-1", inspector_source)

        example_source = (PROJECT_ROOT / "examples" / "ecosystem_designer_shell.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("preview_parent = SectionPanel(", example_source)
        self.assertIn('"Preview",', example_source)
        self.assertNotIn(
            "preview_parent = ControlColumn(layout=ControlLayout(width=FILL, height=FILL))",
            example_source,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
