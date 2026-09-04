from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.localization import google_translate as gt
from tools.localization.build_locales import main as build_locales_main


class FakeProvider:
    provider_name = "fake-provider"
    model_name = "fake-model"

    def __init__(self, suffix=" [translated]", fail=False):
        self.suffix = suffix
        self.fail = fail
        self.calls: list[tuple[list[str], str]] = []

    def translate_batch(self, texts: list[str], target_code: str) -> list[str]:
        self.calls.append((list(texts), target_code))
        if self.fail:
            raise RuntimeError("provider failed")
        return [text + self.suffix for text in texts]


class TranslationPipelineFixture:
    def __init__(self, root: Path):
        self.root = root
        self.locale_root = root / "locales"
        self.cache = root / "translation_cache.json"
        self.manifest = root / "extraction_manifest.json"
        self.protected = root / "protected_terms.json"
        self.overrides = root / "manual_overrides"

    @staticmethod
    def _write(path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def build(self, *, target_strings=None, overrides=None):
        source = {
            "plain": "Open Torrent",
            "formatted": "Peers: {count}",
            "technical": "BitTorrent via DHT",
        }
        for catalog in gt.CATALOGS:
            values = source if catalog == "ui" else {}
            self._write(
                self.locale_root / "en-AU" / f"{catalog}.json",
                {"_meta": {}, "strings": values},
            )
            self._write(
                self.locale_root / "pt-BR" / f"{catalog}.json",
                {"_meta": {}, "strings": (target_strings or {}) if catalog == "ui" else {}},
            )
        self._write(
            self.manifest,
            {
                "_meta": {"schema": 1},
                "catalogs": {
                    "ui": {
                        "entries": {
                            key: {"source_hash": gt.source_hash(text)}
                            for key, text in source.items()
                        }
                    },
                    "help": {"entries": {}},
                    "glossary": {"entries": {}},
                },
            },
        )
        self._write(self.protected, {"terms": ["BitTorrent", "DHT"]})
        self._write(self.cache, gt._new_cache())
        self._write(
            self.overrides / "pt-BR.json",
            overrides or {"ui": {}, "help": {}, "glossary": {}},
        )
        return source

    def patches(self):
        return patch.multiple(
            gt,
            LOCALE_ROOT=self.locale_root,
            CACHE_PATH=self.cache,
            MANIFEST_PATH=self.manifest,
            PROTECTED_PATH=self.protected,
            OVERRIDES_ROOT=self.overrides,
            TARGET_CODES={"pt-BR": "pt-BR"},
        )


class TranslationPipelineTests(unittest.TestCase):
    def test_project_id_precedence_prefers_explicit_then_salix_environment(self):
        with patch.dict(os.environ, {"SALIX_T_GOOGLE_PROJECT": "env-project"}, clear=True):
            self.assertEqual(gt._resolve_project_id("explicit-project"), ("explicit-project", "argument"))
            self.assertEqual(gt._resolve_project_id(None), ("env-project", "SALIX_T_GOOGLE_PROJECT"))

    def test_protection_round_trip_preserves_placeholders_and_technical_terms(self):
        protected, mapping = gt.protect_text("BitTorrent peers: {count} via DHT")
        self.assertNotIn("BitTorrent", protected)
        self.assertNotIn("{count}", protected)
        self.assertEqual(gt.restore_text(protected, mapping), "BitTorrent peers: {count} via DHT")

    def test_bootstrap_adopts_existing_translation_with_current_source_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = TranslationPipelineFixture(Path(temp))
            fixture.build(target_strings={"plain": "Abrir Torrent"})
            with fixture.patches():
                stats = gt.bootstrap_translation_cache()
                self.assertEqual(stats["pt-BR"], 1)
                cache = json.loads(fixture.cache.read_text(encoding="utf-8"))
                entry = cache["entries"]["pt-BR"]["ui"]["plain"]
                self.assertEqual(entry["status"], "seeded-existing")
                self.assertEqual(entry["source_hash"], gt.source_hash("Open Torrent"))

    def test_changed_only_pipeline_uses_cache_and_translates_only_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = TranslationPipelineFixture(Path(temp))
            fixture.build(target_strings={"plain": "Abrir Torrent"})
            provider = FakeProvider()
            with fixture.patches():
                gt.bootstrap_translation_cache()
                result = gt.translate_locale("pt-BR", provider=provider)
                self.assertEqual(result["cached"], 1)
                self.assertEqual(result["translated"], 2)
                self.assertEqual(sum(len(call[0]) for call in provider.calls), 2)
                catalog = gt._catalog_strings("pt-BR", "ui")
                self.assertEqual(catalog["plain"], "Abrir Torrent")
                self.assertIn("{count}", catalog["formatted"])
                self.assertIn("BitTorrent", catalog["technical"])
                self.assertIn("DHT", catalog["technical"])

    def test_manual_override_wins_even_when_force_is_requested(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = TranslationPipelineFixture(Path(temp))
            fixture.build(overrides={"ui": {"plain": "ABRIR REVISADO"}, "help": {}, "glossary": {}})
            provider = FakeProvider()
            with fixture.patches():
                result = gt.translate_locale("pt-BR", force=True, provider=provider)
                self.assertEqual(result["overridden"], 1)
                self.assertEqual(gt._catalog_strings("pt-BR", "ui")["plain"], "ABRIR REVISADO")

    def test_no_network_rebuild_uses_only_hash_valid_cache_and_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = TranslationPipelineFixture(Path(temp))
            fixture.build(target_strings={"plain": "Abrir Torrent", "formatted": "VELHO {count}"})
            with fixture.patches():
                gt.bootstrap_translation_cache()
                # Invalidate only the formatted entry by changing its cached hash.
                cache = json.loads(fixture.cache.read_text(encoding="utf-8"))
                cache["entries"]["pt-BR"]["ui"]["formatted"]["source_hash"] = "stale"
                fixture._write(fixture.cache, cache)
                result = gt.translate_locale("pt-BR", no_network=True)
                catalog = gt._catalog_strings("pt-BR", "ui")
                self.assertIn("plain", catalog)
                self.assertNotIn("formatted", catalog)
                self.assertNotIn("technical", catalog)
                self.assertEqual(result["missing"], 2)

    def test_provider_failure_does_not_modify_target_or_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = TranslationPipelineFixture(Path(temp))
            fixture.build(target_strings={"plain": "KEEP ME"})
            before_target = (fixture.locale_root / "pt-BR" / "ui.json").read_bytes()
            before_cache = fixture.cache.read_bytes()
            with fixture.patches():
                with self.assertRaises(RuntimeError):
                    gt.translate_locale("pt-BR", provider=FakeProvider(fail=True))
            self.assertEqual((fixture.locale_root / "pt-BR" / "ui.json").read_bytes(), before_target)
            self.assertEqual(fixture.cache.read_bytes(), before_cache)

    def test_translation_plan_is_non_mutating_and_counts_work(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = TranslationPipelineFixture(Path(temp))
            fixture.build(target_strings={"plain": "Abrir Torrent"})
            with fixture.patches():
                gt.bootstrap_translation_cache()
                before = fixture.cache.read_bytes()
                plan = gt.translation_plan("pt-BR")
                self.assertEqual(plan.cached, 1)
                self.assertEqual(plan.would_translate, 2)
                self.assertEqual(fixture.cache.read_bytes(), before)

    def test_real_tree_dry_run_requires_no_google_credentials(self):
        # Real-tree smoke test: --dry-run must work with no Google auth/package use.
        result = build_locales_main(["--dry-run", "--locale", "pt-BR"])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
