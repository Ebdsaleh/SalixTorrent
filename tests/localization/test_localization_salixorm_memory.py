from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import PROJECT_ROOT

from tools.localization import google_translate as gt
from tools.localization.build_locales import main as build_locales_main
from tools.localization.translation_memory import (
    JsonTranslationMemory,
    memory_entry,
)
from tools.localization.translation_memory_factory import (
    MEMORY_BACKEND_ENV,
    MEMORY_URL_ENV,
    create_translation_memory_store,
)

try:
    import salixorm
except ImportError:
    salixorm = None


class FailingSecondProvider:
    provider_name = "fake-provider"
    model_name = "fake-model"

    def __init__(self):
        self.calls = 0

    def translate_batch(self, texts, target_code):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("simulated provider failure")
        return [f"{text} TRANSLATED" for text in texts]


class TranslationMemoryFactoryTests(unittest.TestCase):
    def test_default_factory_remains_json_and_backward_compatible(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.json"
            store = create_translation_memory_store(memory_path=path)
            self.assertIsInstance(store, JsonTranslationMemory)
            store.put(memory_entry(
                target_locale="pt-BR",
                catalog="ui",
                source="Open",
                translation="Abrir",
                status="reviewed",
            ))
            store.save()
            self.assertEqual(
                JsonTranslationMemory(path).lookup("pt-BR", "ui", "Open").translation,
                "Abrir",
            )


    def test_historical_json_memory_environment_path_remains_json(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory-from-env.json"
            with patch.dict(os.environ, {"SALIX_LOCALIZATION_MEMORY": str(path)}, clear=False):
                os.environ.pop(MEMORY_BACKEND_ENV, None)
                os.environ.pop(MEMORY_URL_ENV, None)
                store = create_translation_memory_store()
            self.assertIsInstance(store, JsonTranslationMemory)
            self.assertEqual(store.path.resolve(), path.resolve())

    def test_default_salixorm_memory_artifacts_are_ignored(self):
        ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("tools/localization/translation_memory.db", ignore)
        self.assertIn("tools/localization/translation_memory.db-shm", ignore)
        self.assertIn("tools/localization/translation_memory.db-wal", ignore)


@unittest.skipUnless(salixorm is not None, "SalixORM v0.2.0+ is not installed in this environment")
class SalixORMTranslationMemoryTests(unittest.TestCase):
    def _store(self, path: Path, *, source_locale: str = "en-AU"):
        from tools.localization.translation_memory_salixorm import SalixORMTranslationMemory
        return SalixORMTranslationMemory(path, source_locale=source_locale)

    def test_salixorm_backend_and_url_environment_select_the_optional_store(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory-env.db"
            resolved = path.resolve().as_posix()
            if os.name == "nt" or (len(resolved) >= 2 and resolved[1] == ":"):
                url = f"sqlite:///{resolved}"
            else:
                url = "sqlite:////" + resolved.lstrip("/")
            with patch.dict(
                os.environ,
                {MEMORY_BACKEND_ENV: "salixorm", MEMORY_URL_ENV: url},
                clear=False,
            ):
                store = create_translation_memory_store()
            self.assertEqual(Path(store.path).resolve(), path.resolve())
            self.assertFalse(path.exists())
            store.save()
            self.assertTrue(path.is_file())

    def test_salixorm_factory_is_lazy_and_save_is_the_persistence_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.db"
            store = create_translation_memory_store(
                backend="salixorm",
                memory_path=path,
            )
            store.put(memory_entry(
                target_locale="pt-BR",
                catalog="ui",
                source="Open",
                translation="Abrir",
                status="reviewed",
            ))
            self.assertEqual(store.lookup("pt-BR", "ui", "Open").translation, "Abrir")
            self.assertFalse(path.exists())
            store.save()
            self.assertTrue(path.is_file())

            reopened = self._store(path)
            self.assertEqual(reopened.lookup("pt-BR", "ui", "Open").translation, "Abrir")
            self.assertTrue(reopened.audit().ok)

    def test_salixorm_store_preserves_metadata_stats_and_reusable_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.db"
            store = self._store(path)
            store.put(memory_entry(
                target_locale="pt-BR",
                catalog="ui",
                source="Open",
                translation="Abrir",
                status="reviewed",
                provider="provider-a",
                model="model-a",
            ))
            store.put(memory_entry(
                target_locale="pt-BR",
                catalog="help",
                source="Hidden",
                translation="Oculto",
                status="machine",
                provider="provider-b",
                model="model-b",
                reusable=False,
            ))
            store.save()

            reopened = self._store(path)
            visible = reopened.lookup("pt-BR", "ui", "Open")
            self.assertEqual(visible.provider, "provider-a")
            self.assertEqual(visible.model, "model-a")
            self.assertIsNone(reopened.lookup("pt-BR", "help", "Hidden"))
            stats = reopened.stats()
            self.assertEqual(stats.entries, 2)
            self.assertEqual(stats.reusable, 1)
            self.assertEqual(stats.reviewed, 1)
            self.assertEqual(stats.machine, 1)

    def test_ledger_only_first_migration_state_is_recoverable(self):
        from salixorm import MigrationManager

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.db"
            seed = self._store(path)
            with seed._new_database() as db:
                MigrationManager(db)

            store = self._store(path)
            self.assertEqual(store.stats().entries, 0)
            store.put(memory_entry(
                target_locale="pt-BR",
                catalog="ui",
                source="Open",
                translation="Abrir",
                status="reviewed",
            ))
            store.save()
            self.assertEqual(self._store(path).lookup("pt-BR", "ui", "Open").translation, "Abrir")

    def test_schema_only_interrupted_first_save_can_recover_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.db"
            store = self._store(path)
            store.save()
            conn = sqlite3.connect(path)
            try:
                conn.execute("DELETE FROM salix_translation_memory_meta")
                conn.commit()
            finally:
                conn.close()

            recovered = self._store(path)
            self.assertEqual(recovered.stats().entries, 0)
            recovered.put(memory_entry(
                target_locale="pt-BR",
                catalog="ui",
                source="Open",
                translation="Abrir",
                status="reviewed",
            ))
            recovered.save()
            self.assertEqual(self._store(path).lookup("pt-BR", "ui", "Open").translation, "Abrir")

    def test_missing_metadata_with_persisted_entries_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.db"
            store = self._store(path)
            store.put(memory_entry(
                target_locale="pt-BR",
                catalog="ui",
                source="Open",
                translation="Abrir",
                status="reviewed",
            ))
            store.save()
            conn = sqlite3.connect(path)
            try:
                conn.execute("DELETE FROM salix_translation_memory_meta")
                conn.commit()
            finally:
                conn.close()
            with self.assertRaisesRegex(ValueError, "metadata row is missing"):
                self._store(path)

    def test_salixorm_store_records_explicit_migration_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.db"
            store = self._store(path)
            store.save()
            conn = sqlite3.connect(path)
            try:
                revisions = [row[0] for row in conn.execute(
                    "SELECT revision FROM _salixorm_migrations ORDER BY applied_at;"
                ).fetchall()]
            finally:
                conn.close()
            self.assertEqual(revisions, ["translation-memory-0001"])

    def test_salixorm_store_refuses_cross_source_locale_open(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.db"
            store = self._store(path, source_locale="en-AU")
            store.save()
            with self.assertRaisesRegex(ValueError, "source locale"):
                self._store(path, source_locale="fr-FR")

    def test_salixorm_store_refuses_persisted_source_hash_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory.db"
            store = self._store(path)
            store.put(memory_entry(
                target_locale="pt-BR",
                catalog="ui",
                source="Open",
                translation="Abrir",
                status="reviewed",
            ))
            store.save()
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    "UPDATE salix_translation_memory_entries SET source = ?",
                    ("Different source",),
                )
                conn.commit()
            finally:
                conn.close()
            with self.assertRaisesRegex(ValueError, "source hash"):
                self._store(path)

    def test_json_to_salixorm_merge_is_fail_closed_on_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target_path = root / "memory.db"
            source_path = root / "incoming.json"

            target = self._store(target_path)
            target.put(memory_entry(
                target_locale="pt-BR", catalog="ui", source="Open",
                translation="Abrir", status="reviewed",
            ))
            target.save()

            incoming = JsonTranslationMemory(source_path)
            incoming.put(memory_entry(
                target_locale="pt-BR", catalog="ui", source="Open",
                translation="Abra", status="reviewed",
            ))
            incoming.save()

            result = gt.merge_translation_memory(
                source_path,
                memory_backend="salixorm",
                memory_path=target_path,
            )
            self.assertEqual(result, {"added": 0, "reused": 0, "conflicts": 1})
            reopened = self._store(target_path)
            self.assertEqual(reopened.lookup("pt-BR", "ui", "Open").translation, "Abrir")

    def test_no_network_pipeline_reuses_salixorm_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            locale_root = root / "locales"
            cache_path = root / "translation_cache.json"
            memory_path = root / "translation_memory.db"
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

            memory = self._store(memory_path)
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
                    memory_backend="salixorm",
                    memory_path=memory_path,
                )
                self.assertEqual(result["memory"], 1)
                self.assertEqual(result["missing"], 0)
                self.assertEqual(gt._catalog_strings("pt-BR", "ui")["same"], "Abrir")

    def test_provider_failure_does_not_partially_persist_salixorm_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            locale_root = root / "locales"
            cache_path = root / "translation_cache.json"
            memory_path = root / "translation_memory.db"
            overrides_root = root / "manual_overrides"
            manifest_path = root / "extraction_manifest.json"
            protected_path = root / "protected_terms.json"

            sources = {
                "ui": {"ui.one": "First"},
                "help": {"help.one": "Second"},
                "glossary": {},
            }
            for catalog, values in sources.items():
                (locale_root / "en-AU").mkdir(parents=True, exist_ok=True)
                (locale_root / "pt-BR").mkdir(parents=True, exist_ok=True)
                (locale_root / "en-AU" / f"{catalog}.json").write_text(
                    json.dumps({"_meta": {}, "strings": values}), encoding="utf-8"
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
                    catalog: {
                        "entries": {
                            key: {"source_hash": gt.source_hash(value)}
                            for key, value in values.items()
                        }
                    }
                    for catalog, values in sources.items()
                }
            }), encoding="utf-8")

            with patch.multiple(
                gt,
                LOCALE_ROOT=locale_root,
                CACHE_PATH=cache_path,
                MANIFEST_PATH=manifest_path,
                PROTECTED_PATH=protected_path,
                OVERRIDES_ROOT=overrides_root,
                TARGET_CODES={"pt-BR": "pt-BR"},
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated provider failure"):
                    gt.translate_locale(
                        "pt-BR",
                        provider=FailingSecondProvider(),
                        memory_backend="salixorm",
                        memory_path=memory_path,
                    )
            self.assertFalse(memory_path.exists())

    def test_project_json_memory_round_trips_all_entries_through_salixorm(self):
        from tools.localization.salixorm_memory_audit import salixorm_memory_parity_audit
        audit = salixorm_memory_parity_audit()
        self.assertTrue(audit.ok, audit.errors)
        self.assertEqual(audit.json_entries, 432)
        self.assertEqual(audit.salixorm_entries, 432)
        self.assertEqual(audit.conflicts, 0)

    def test_salixorm_memory_check_is_offline_and_helper_is_tracked(self):
        self.assertEqual(build_locales_main(["--salixorm-memory-check"]), 0)
        root = PROJECT_ROOT
        text = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!tools/localization/validate_salixorm_memory.bat", text)


if __name__ == "__main__":
    unittest.main()
