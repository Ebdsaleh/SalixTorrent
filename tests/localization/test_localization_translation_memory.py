from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.localization import google_translate as gt
from tools.localization.build_locales import main as build_locales_main
from tools.localization.provider_registry import create_provider, provider_descriptors
from tools.localization.translation_memory import (
    JsonTranslationMemory,
    memory_entry,
    resolve_memory_path,
)


class FakeProvider:
    provider_name = "fake-provider"
    model_name = "fake-model"

    def __init__(self):
        self.calls = []

    def translate_batch(self, texts, target_code):
        self.calls.append((list(texts), target_code))
        return [f"{text} TRANSLATED" for text in texts]


class TranslationMemoryTests(unittest.TestCase):
    def test_memory_identity_is_source_based_not_application_key_based(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.json"
            memory = JsonTranslationMemory(path)
            memory.put(memory_entry(
                target_locale="pt-BR",
                catalog="ui",
                source="Open",
                translation="Abrir",
                status="reviewed",
            ))
            memory.save()
            loaded = JsonTranslationMemory(path)
            self.assertEqual(
                loaded.lookup("pt-BR", "ui", "Open").translation,
                "Abrir",
            )

    def test_memory_keeps_semantic_catalogs_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.json"
            memory = JsonTranslationMemory(path)
            memory.put(memory_entry(
                target_locale="pt-BR",
                catalog="ui",
                source="Open",
                translation="Abrir",
                status="machine",
            ))
            self.assertIsNotNone(memory.lookup("pt-BR", "ui", "Open"))
            self.assertIsNone(memory.lookup("pt-BR", "help", "Open"))

    def test_memory_refuses_placeholder_damage(self):
        with tempfile.TemporaryDirectory() as temp:
            memory = JsonTranslationMemory(Path(temp) / "memory.json")
            with self.assertRaises(ValueError):
                memory.put(memory_entry(
                    target_locale="pt-BR",
                    catalog="ui",
                    source="Peers: {count}",
                    translation="Peers",
                    status="machine",
                ))

    def test_memory_merge_is_fail_closed_on_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            a_path = Path(temp) / "a.json"
            b_path = Path(temp) / "b.json"
            a = JsonTranslationMemory(a_path)
            b = JsonTranslationMemory(b_path)
            a.put(memory_entry(
                target_locale="pt-BR", catalog="ui", source="Open",
                translation="Abrir", status="reviewed",
            ))
            b.put(memory_entry(
                target_locale="pt-BR", catalog="ui", source="Open",
                translation="Abra", status="reviewed",
            ))
            a.save()
            b.save()
            result = a.merge_from(b_path)
            self.assertEqual(result["conflicts"], 1)
            self.assertEqual(a.lookup("pt-BR", "ui", "Open").translation, "Abrir")

    def test_default_memory_path_follows_patched_cache_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "translation_cache.json"
            memory_path = resolve_memory_path(cache_path=cache)
            self.assertEqual(memory_path.name, "translation_memory.json")
            # Windows development shells may expose the same temporary directory
            # through an 8.3 short path while Path.resolve() returns its long name.
            # Compare directory identity rather than spelling.
            self.assertTrue(os.path.samefile(memory_path.parent, Path(temp)))

    def test_real_tree_memory_bootstrap_is_deduplicated(self):
        stats = gt.bootstrap_translation_memory(write=False)
        # There are 113 key-cache entries per locale but five exact-source
        # duplicates, so the portable memory contains 108 candidates.
        self.assertEqual(stats, {"en-GB": 0, "en-US": 0, "fil-PH": 0, "pt-BR": 0})
        memory_stats = gt.translation_memory_status()
        self.assertEqual(memory_stats.entries, 432)
        self.assertEqual(memory_stats.target_locales, 4)

    def test_no_network_pipeline_can_reuse_memory_when_key_cache_is_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            locale_root = root / "locales"
            cache_path = root / "translation_cache.json"
            memory_path = root / "translation_memory.json"
            overrides_root = root / "manual_overrides"
            manifest_path = root / "extraction_manifest.json"
            protected_path = root / "protected_terms.json"

            for catalog in gt.CATALOGS:
                (locale_root / "en-AU").mkdir(parents=True, exist_ok=True)
                (locale_root / "pt-BR").mkdir(parents=True, exist_ok=True)
                source = {"same": "Open"} if catalog == "ui" else {}
                (locale_root / "en-AU" / f"{catalog}.json").write_text(
                    json.dumps({"_meta": {}, "strings": source}), encoding="utf-8"
                )
                (locale_root / "pt-BR" / f"{catalog}.json").write_text(
                    json.dumps({"_meta": {}, "strings": {}}), encoding="utf-8"
                )
            cache_path.write_text(json.dumps(gt._new_cache()), encoding="utf-8")
            overrides_root.mkdir(parents=True)
            (overrides_root / "pt-BR.json").write_text(
                json.dumps({"ui": {}, "help": {}, "glossary": {}}), encoding="utf-8"
            )
            protected_path.write_text(json.dumps({"terms": []}), encoding="utf-8")
            manifest_path.write_text(json.dumps({
                "catalogs": {
                    "ui": {"entries": {"same": {"source_hash": gt.source_hash("Open")}}},
                    "help": {"entries": {}},
                    "glossary": {"entries": {}},
                }
            }), encoding="utf-8")
            memory = JsonTranslationMemory(memory_path)
            memory.put(memory_entry(
                target_locale="pt-BR", catalog="ui", source="Open",
                translation="Abrir", status="reviewed",
            ))
            memory.save()

            with patch.multiple(
                gt,
                LOCALE_ROOT=locale_root,
                CACHE_PATH=cache_path,
                MANIFEST_PATH=manifest_path,
                PROTECTED_PATH=protected_path,
                OVERRIDES_ROOT=overrides_root,
                TARGET_CODES={"pt-BR": "pt-BR"},
            ):
                result = gt.translate_locale(
                    "pt-BR",
                    no_network=True,
                    memory_path=memory_path,
                )
                self.assertEqual(result["memory"], 1)
                self.assertEqual(result["missing"], 0)
                self.assertEqual(gt._catalog_strings("pt-BR", "ui")["same"], "Abrir")

    def test_provider_registry_is_lazy_and_lists_google(self):
        names = [item.name for item in provider_descriptors()]
        self.assertIn("google-cloud", names)

    def test_memory_check_is_offline(self):
        self.assertEqual(build_locales_main(["--memory-check"]), 0)

    def test_gitignore_tracks_memory_validation_helper(self):
        text = (gt.ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!tools/localization/validate_translation_memory.bat", text)


if __name__ == "__main__":
    unittest.main()
