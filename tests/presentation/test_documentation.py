import unittest
from unittest import mock

from app.framework.documentation.layout import (
    DEFAULT_DOCUMENTATION_LAYOUT,
    DocLayout,
    DocumentationLayoutTheme,
    documentation_bounds,
    resolve_documentation_layout,
)
from app.framework.documentation.model import (
    DocMediaKind,
    DocPage,
    DocParagraph,
    DocRole,
    DocSection,
)
from app.engine.documentation.renderer import DocumentationRenderer
from app.framework.documentation.typography import (
    documentation_scale_from_label,
    documentation_scale_label,
    icon_marker,
    normalise_documentation_scale,
    role_font_size,
)
from app.framework.documentation.model import DocIconKind
from app.framework.property_cascade import PropertySource, UNSET, resolve_property
from app.logic.torrent_manager import TorrentManager
from app.framework.geometry import (
    ContentMetrics,
    HorizontalAlign,
    aligned_offset,
    content_bounds,
)


class DocumentationSubsystemTests(unittest.TestCase):
    def test_parent_relative_alignment_is_deterministic(self):
        self.assertEqual(aligned_offset(1000, 200, HorizontalAlign.LEFT), 0)
        self.assertEqual(aligned_offset(1000, 200, HorizontalAlign.CENTER), 400)
        self.assertEqual(aligned_offset(1000, 200, HorizontalAlign.RIGHT), 800)

    def test_readable_content_width_centers_inside_parent(self):
        bounds = content_bounds(
            1440,
            metrics=ContentMetrics(
                horizontal_padding=22,
                minimum_width=420,
                maximum_width=980,
            ),
        )
        self.assertEqual(bounds.width, 980)
        self.assertEqual(bounds.x, 230)
        self.assertEqual(bounds.right, 1210)

    def test_narrow_document_uses_available_width_without_overflow(self):
        bounds = content_bounds(
            390,
            metrics=ContentMetrics(
                horizontal_padding=22,
                minimum_width=420,
                maximum_width=980,
            ),
        )
        self.assertEqual(bounds.x, 22)
        self.assertEqual(bounds.width, 346)
        self.assertLessEqual(bounds.right, 390)

    def test_semantic_typography_preserves_hierarchy(self):
        body = role_font_size(DocRole.BODY, 15, 100)
        section = role_font_size(DocRole.SECTION_TITLE, 15, 100)
        title = role_font_size(DocRole.PAGE_TITLE, 15, 100)
        self.assertEqual(body, 15)
        self.assertGreater(section, body)
        self.assertGreater(title, section)
        self.assertGreater(role_font_size(DocRole.BODY, 15, 130), body)

    def test_documentation_scale_round_trip_and_clamp(self):
        self.assertEqual(normalise_documentation_scale(114), 115)
        self.assertEqual(documentation_scale_label(115), "115% - Large")
        self.assertEqual(documentation_scale_from_label("130% - Extra Large"), 130)

    def test_media_fit_preserves_aspect_ratio_and_never_upscales(self):
        self.assertEqual(DocumentationRenderer._fit_media(1600, 900, 800, 700), (800, 450))
        self.assertEqual(DocumentationRenderer._fit_media(320, 180, 800, 700), (320, 180))

    def test_semantic_icon_has_portable_fallback(self):
        self.assertEqual(icon_marker(DocIconKind.WARNING), "[!]")
        self.assertEqual(
            icon_marker(DocIconKind.WARNING, emoji="⚠", unicode_symbols=True),
            "⚠",
        )

    def test_documentation_scale_is_persisted_as_a_bounded_setting(self):
        settings = TorrentManager._normalise_app_settings({"documentation_scale": 121})
        self.assertEqual(settings["documentation_scale"], 115)


    def test_generic_property_cascade_prefers_valid_instance_then_theme_then_default(self):
        resolved = resolve_property(
            default=10,
            theme=12,
            override=14,
            validator=lambda value: isinstance(value, int) and value > 0,
            normalizer=int,
        )
        self.assertEqual(resolved.value, 14)
        self.assertEqual(resolved.source, PropertySource.INSTANCE)

        fallback = resolve_property(
            default=10,
            theme=12,
            override=-4,
            validator=lambda value: isinstance(value, int) and value > 0,
            normalizer=int,
        )
        self.assertEqual(fallback.value, 12)
        self.assertEqual(fallback.source, PropertySource.THEME)
        self.assertEqual(fallback.rejected[0].source, PropertySource.INSTANCE)

    def test_unset_inherits_but_none_remains_explicit_when_valid(self):
        inherited = resolve_property(
            default=980,
            theme=1100,
            override=UNSET,
            validator=lambda value: value is None or (isinstance(value, int) and value > 0),
        )
        self.assertEqual(inherited.value, 1100)
        self.assertEqual(inherited.source, PropertySource.THEME)

        explicit_none = resolve_property(
            default=980,
            theme=1100,
            override=None,
            validator=lambda value: value is None or (isinstance(value, int) and value > 0),
        )
        self.assertIsNone(explicit_none.value)
        self.assertEqual(explicit_none.source, PropertySource.INSTANCE)

    def test_document_layout_theme_is_sparse_and_preserves_framework_defaults(self):
        resolved = resolve_documentation_layout(
            theme=DocumentationLayoutTheme(maximum_width=1180),
        )
        self.assertEqual(resolved.maximum_width, 1180)
        self.assertEqual(resolved.source_for("maximum_width"), PropertySource.THEME)
        self.assertEqual(resolved.padding_left, DEFAULT_DOCUMENTATION_LAYOUT.padding_left)
        self.assertEqual(resolved.source_for("padding_left"), PropertySource.DEFAULT)

    def test_manual_page_override_wins_without_copying_theme(self):
        resolved = resolve_documentation_layout(
            theme=DocumentationLayoutTheme(maximum_width=1180, padding_left=18),
            override=DocLayout(maximum_width=1400, padding_right=9),
        )
        self.assertEqual(resolved.maximum_width, 1400)
        self.assertEqual(resolved.source_for("maximum_width"), PropertySource.INSTANCE)
        self.assertEqual(resolved.padding_left, 18)
        self.assertEqual(resolved.source_for("padding_left"), PropertySource.THEME)
        self.assertEqual(resolved.padding_right, 9)
        self.assertEqual(resolved.source_for("padding_right"), PropertySource.INSTANCE)

    def test_invalid_manual_layout_falls_back_to_valid_theme_then_default(self):
        themed = resolve_documentation_layout(
            theme=DocumentationLayoutTheme(maximum_width=1100),
            override=DocLayout(maximum_width=-50),
        )
        self.assertEqual(themed.maximum_width, 1100)
        self.assertEqual(themed.source_for("maximum_width"), PropertySource.THEME)
        self.assertEqual(themed.rejected[0][0], "maximum_width")
        self.assertEqual(themed.rejected[0][1].source, PropertySource.INSTANCE)

        defaulted = resolve_documentation_layout(
            theme=DocumentationLayoutTheme(maximum_width="not-a-width"),
            override=DocLayout(),
        )
        self.assertEqual(defaulted.maximum_width, DEFAULT_DOCUMENTATION_LAYOUT.maximum_width)
        self.assertEqual(defaulted.source_for("maximum_width"), PropertySource.DEFAULT)

    def test_valid_large_layout_is_runtime_constrained_not_rejected(self):
        resolved = resolve_documentation_layout(
            theme=DocumentationLayoutTheme(maximum_width=1100),
            override=DocLayout(maximum_width=1400),
        )
        bounded = documentation_bounds(700, 500, layout=resolved)
        self.assertEqual(resolved.maximum_width, 1400)
        self.assertEqual(resolved.source_for("maximum_width"), PropertySource.INSTANCE)
        self.assertLessEqual(bounded.document.right, 700)
        self.assertGreater(bounded.content.width, 0)

    def test_margin_padding_and_title_alignment_resolve_independently(self):
        resolved = resolve_documentation_layout(
            theme=DocumentationLayoutTheme(
                maximum_width=1000,
                padding_left=60,
                padding_right=20,
            ),
            override=DocLayout(title_alignment="center"),
        )
        bounded = documentation_bounds(1200, 700, layout=resolved)
        self.assertEqual(bounded.document.width, 1000)
        self.assertEqual(bounded.document.x, 100)
        self.assertEqual(bounded.content.x, 160)
        self.assertEqual(bounded.content.width, 920)
        self.assertEqual(resolved.title_alignment, HorizontalAlign.CENTER)
        self.assertEqual(resolved.source_for("title_alignment"), PropertySource.INSTANCE)

    def test_renderer_layout_snapshot_exposes_provenance_for_theme_debugging(self):
        # This is a renderer-neutral layout/provenance test.  On a normal
        # SalixTorrent development install Dear PyGui is available, but no DPG
        # context exists during unittest discovery.  Calling add_text() in that
        # state can terminate the native DPG process before unittest can report
        # a failure.  Force the renderer's documented headless path so this test
        # measures only the semantic/layout contract it is intended to cover.
        with mock.patch("app.engine.documentation.renderer.dpg", None):
            renderer = DocumentationRenderer(
                "headless-parent",
                layout_theme=DocumentationLayoutTheme(maximum_width=1180, padding_left=18),
            )
            page = DocPage(
                title="Inspect me",
                layout=DocLayout(maximum_width=1320, padding_right=10),
            )
            renderer.render_page(page)
            snapshot = renderer.layout_snapshot(1600, 800)

        self.assertEqual(snapshot["configured"]["maximum_width"], 1320)
        self.assertEqual(snapshot["sources"]["maximum_width"], "instance")
        self.assertEqual(snapshot["sources"]["padding_left"], "theme")
        self.assertEqual(snapshot["sources"]["padding_right"], "instance")
        self.assertEqual(snapshot["rejected"], ())
        self.assertLessEqual(snapshot["document_bounds"].right, 1600)

    def test_document_model_is_renderer_neutral(self):
        page = DocPage(
            title="Example",
            lead="Lead",
            sections=(
                DocSection("Section", (DocParagraph("Body"),)),
            ),
        )
        self.assertEqual(page.title, "Example")
        self.assertEqual(page.sections[0].blocks[0].text, "Body")
        self.assertEqual(DocMediaKind.VIDEO.value, "video")


    def test_framework_documentation_boundary_is_product_and_backend_neutral(self):
        import ast
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[2]
        framework_dir = project_root / "app" / "framework"
        candidate_files = (
            framework_dir / "geometry.py",
            *(framework_dir / "documentation").glob("*.py"),
        )
        forbidden_prefixes = (
            "app.engine",
            "app.views",
            "app.logic",
            "app.localization",
            "dearpygui",
        )

        for path in candidate_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            self.assertFalse(
                any(module.startswith(forbidden_prefixes) for module in imports),
                str(path.relative_to(project_root)),
            )

    def test_framework_documentation_exports_do_not_claim_concrete_renderer_ownership(self):
        import app.framework.documentation as framework_docs

        self.assertFalse(hasattr(framework_docs, "DocumentationRenderer"))
        self.assertTrue(hasattr(framework_docs, "DocPage"))
        self.assertTrue(hasattr(framework_docs, "DocumentationTheme"))

    def test_legacy_documentation_modules_are_compatibility_facades(self):
        from app.engine.documentation.layout import DocLayout as LegacyDocLayout
        from app.engine.documentation.model import DocPage as LegacyDocPage
        from app.engine.documentation.typography import DocumentationTheme as LegacyTheme
        from app.framework.documentation import DocLayout, DocPage, DocumentationTheme

        self.assertIs(LegacyDocLayout, DocLayout)
        self.assertIs(LegacyDocPage, DocPage)
        self.assertIs(LegacyTheme, DocumentationTheme)

    def test_concrete_documentation_renderer_remains_engine_backend_adapter(self):
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[2]
        source = (
            project_root / "app" / "engine" / "documentation" / "renderer.py"
        ).read_text(encoding="utf-8")

        self.assertIn("import dearpygui.dearpygui as dpg", source)
        self.assertIn("from app.engine.runtime_paths import resource_path", source)
        self.assertIn("from app.engine.ui_typography import UiTypography", source)
        self.assertIn("from app.framework.documentation", source)

    def test_responsive_layout_reexports_framework_geometry_identity(self):
        from app.engine.responsive_layout import (
            ContentBounds as LegacyContentBounds,
            HorizontalAlign as LegacyHorizontalAlign,
        )
        from app.framework.geometry import ContentBounds, HorizontalAlign

        self.assertIs(LegacyContentBounds, ContentBounds)
        self.assertIs(LegacyHorizontalAlign, HorizontalAlign)

    def test_application_surfaces_use_framework_documentation_contracts(self):
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[2]
        help_source = (project_root / "app" / "views" / "help_topics_view.py").read_text(
            encoding="utf-8"
        )
        settings_source = (project_root / "app" / "views" / "settings_view.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("from app.framework.documentation import (", help_source)
        self.assertIn("from app.engine.documentation.renderer import DocumentationRenderer", help_source)
        self.assertNotIn("from app.engine.documentation import (", help_source)
        self.assertIn("from app.framework.documentation import (", settings_source)



if __name__ == "__main__":
    unittest.main()
