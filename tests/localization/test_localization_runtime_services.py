from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import PROJECT_ROOT

from app.localization import LocalizationManager
from app.localization.framework import JsonCatalogRepository, LocaleDescriptor, LocalizationProfile
from app.localization.runtime import LocalizationRuntime, placeholder_names
from app.localization.semantic import (
    JsonSemanticDocumentRepository,
    SemanticDocumentationService,
    SemanticDocumentationSource,
)
from app.localization.documents import document_structure_snapshot
from tools.localization.build_locales import main as build_locales_main
from tools.localization.framework_audit import framework_audit, runtime_boundary_audit


class LocalizationRuntimeServicesTests(unittest.TestCase):
    def tearDown(self):
        LocalizationManager.get_instance().configure("en-AU", system_locale="en-AU")

    def _runtime_tree(self, root: Path):
        profile = LocalizationProfile(
            application_id="example-app",
            canonical_locale="en-GB",
            auto_locale="auto",
            catalog_names=("ui",),
            locales={
                "en-GB": LocaleDescriptor(
                    code="en-GB",
                    display_name="English",
                    native_name="English",
                    support_status="canonical",
                ),
                "pt-BR": LocaleDescriptor(
                    code="pt-BR",
                    display_name="Portuguese",
                    native_name="Português",
                ),
            },
            pseudo_locale="en-XA",
            pseudo_environment="EXAMPLE_PSEUDO",
            pseudo_descriptor=LocaleDescriptor(
                code="en-XA",
                display_name="Pseudo",
                native_name="Pseudo",
                support_status="development-only",
            ),
        )
        for locale, strings in {
            "en-GB": {"open": "Open", "peers": "Peers: {count}"},
            "pt-BR": {"open": "Abrir", "peers": "Pares: {count}"},
        }.items():
            path = root / locale / "ui.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "_meta": {"locale": locale, "catalog": "ui"},
                "strings": strings,
            }), encoding="utf-8")

        def resolver(requested, *, system_locale=None, allow_pseudo=False):
            raw = str(requested or "")
            if allow_pseudo and raw == "en-XA":
                return "en-XA"
            if raw == "auto":
                raw = str(system_locale or "en-GB")
            return raw if raw in {"en-GB", "pt-BR"} else "en-GB"

        repository = JsonCatalogRepository(lambda locale: root / locale, allowed_catalogs=("ui",))
        return profile, repository, resolver

    def test_generic_runtime_uses_injected_profile_repository_and_resolver(self):
        with tempfile.TemporaryDirectory() as temp:
            profile, repository, resolver = self._runtime_tree(Path(temp))
            runtime = LocalizationRuntime(
                profile=profile,
                repository=repository,
                locale_resolver=resolver,
                pseudo_catalog_factory=lambda values: {k: f"[[{v}]]" for k, v in values.items()},
                environment={},
            )
            runtime.configure("pt-BR", system_locale="en-GB")
            self.assertEqual(runtime.tr("open", "Open"), "Abrir")
            self.assertEqual(runtime.tr("peers", "Peers: {count}", count=4), "Pares: 4")
            self.assertEqual(runtime.snapshot()["application_id"], "example-app")
            self.assertEqual(runtime.snapshot()["canonical_locale"], "en-GB")

    def test_generic_runtime_falls_back_and_preserves_format_contracts(self):
        with tempfile.TemporaryDirectory() as temp:
            profile, repository, resolver = self._runtime_tree(Path(temp))
            runtime = LocalizationRuntime(
                profile=profile,
                repository=repository,
                locale_resolver=resolver,
                environment={},
            )
            runtime.configure("pt-BR")
            runtime._catalogs["ui"]["peers"] = "Pares: {contador}"
            self.assertEqual(runtime.tr("peers", "Peers: {count}", count=2), "Peers: 2")
            self.assertEqual(runtime.snapshot()["format_error_count"], 1)
            self.assertEqual(placeholder_names("{user.name}: {count:02d}"), {"user", "count"})

    def test_semantic_document_services_are_storage_and_runtime_neutral(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "help.json").write_text(json.dumps({
                "topics": [{
                    "id": "intro",
                    "title": "Introduction",
                    "summary": "Welcome",
                    "sections": [{"id": "start", "title": "Start", "body": "Begin here."}],
                    "related_terms": ["OPEN"],
                }]
            }), encoding="utf-8")
            (root / "glossary.json").write_text(json.dumps({
                "terms": [{"id": "OPEN", "title": "Open", "body": "Open an item."}]
            }), encoding="utf-8")
            repository = JsonSemanticDocumentRepository(lambda name: root / name)
            source = SemanticDocumentationSource(repository)
            translations = {
                "topic.intro.title": "Introdução",
                "term.OPEN.title": "Abrir",
            }

            def translator(key, default=None, *, catalog="ui", **values):
                return translations.get(key, default or key)

            service = SemanticDocumentationService(source, translator)
            topic = service.localized_help_topics()[0]
            self.assertEqual(topic.key, "intro")
            self.assertEqual(topic.title, "Introdução")
            self.assertEqual(topic.section_keys, ("start",))
            self.assertEqual(topic.related_terms, ("OPEN",))
            self.assertEqual(service.glossary_entry("OPEN")[0], "Abrir")
            self.assertEqual(source.structure_snapshot()["topic_count"], 1)

    def test_salixtorrent_facade_is_backwards_compatible_with_generic_runtime(self):
        manager = LocalizationManager.get_instance()
        self.assertIsInstance(manager, LocalizationRuntime)
        manager.configure("pt-BR", system_locale="en-AU")
        self.assertEqual(manager.tr("menu.file", "File"), "Arquivo")
        self.assertEqual(manager.snapshot()["application_id"], "salixtorrent")

    def test_existing_semantic_documents_still_have_expected_structure(self):
        snapshot = document_structure_snapshot()
        self.assertEqual(snapshot["topic_count"], 20)
        self.assertEqual(snapshot["section_count"], 110)
        self.assertEqual(snapshot["term_count"], 191)

    def test_framework_audit_now_includes_runtime_and_semantic_services(self):
        report = framework_audit()
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.extractable_count, 6)
        paths = {item.path.replace("\\", "/") for item in report.modules}
        self.assertIn("app/localization/runtime.py", paths)
        self.assertIn("app/localization/semantic.py", paths)

    def test_runtime_boundary_audit_is_clean(self):
        self.assertEqual(runtime_boundary_audit(), ())

    def test_runtime_check_is_offline_and_helper_is_tracked(self):
        self.assertEqual(build_locales_main(["--runtime-check"]), 0)
        root = PROJECT_ROOT
        text = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!tools/localization/validate_runtime_boundaries.bat", text)


if __name__ == "__main__":
    unittest.main()
