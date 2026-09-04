from __future__ import annotations

from datetime import datetime, timezone
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.localization import google_translate as gt
from tools.localization import review
from tools.localization.build_locales import main as build_locales_main
from tools.localization.validate_locales import validate_translation_freshness


class TranslationReviewTests(unittest.TestCase):
    def _isolated_review_tree(self, temp: str):
        root = Path(temp)
        locale_root = root / "locales"
        overrides_root = root / "manual_overrides"
        manifest = root / "extraction_manifest.json"
        shutil.copytree(gt.LOCALE_ROOT, locale_root)
        shutil.copytree(gt.OVERRIDES_ROOT, overrides_root)
        shutil.copy2(gt.MANIFEST_PATH, manifest)
        return locale_root, overrides_root, manifest

    def _patch_review_tree(self, locale_root: Path, overrides_root: Path, manifest: Path):
        return patch.multiple(
            review,
            LOCALE_ROOT=locale_root,
            OVERRIDES_ROOT=overrides_root,
            MANIFEST_PATH=manifest,
        )

    def _patch_google_tree(self, locale_root: Path, overrides_root: Path, manifest: Path):
        return patch.multiple(
            gt,
            LOCALE_ROOT=locale_root,
            OVERRIDES_ROOT=overrides_root,
            MANIFEST_PATH=manifest,
        )

    def test_current_review_summary_separates_missing_from_awaiting_review(self):
        summary = review.review_summary("pt-BR")
        self.assertEqual(summary.total, 1271)
        self.assertEqual(summary.missing, 1158)
        self.assertEqual(summary.review_needed, 113)
        self.assertEqual(summary.reviewed, 0)
        self.assertEqual(summary.locked, 0)
        self.assertEqual(summary.stale, 0)
        self.assertEqual(summary.invalid, 0)
        self.assertFalse(summary.review_complete)
        self.assertTrue(summary.infrastructure_ok)

    def test_review_export_contains_source_hash_context_and_editable_state(self):
        bundle = review.build_review_bundle("pt-BR")
        self.assertEqual(bundle["_meta"]["kind"], "salix-translation-review")
        self.assertEqual(bundle["_meta"]["canonical_entries"], 1271)
        entry = bundle["catalogs"]["ui"]["menu.file"]
        self.assertEqual(entry["source"], "File")
        self.assertEqual(len(entry["source_hash"]), 64)
        self.assertEqual(entry["review_state"], "pending")
        self.assertTrue(entry["occurrences"])
        self.assertIn(entry["current_status"], {"review-needed", "missing"})

    def test_review_import_promotes_reviewed_translation_and_packages_it(self):
        with tempfile.TemporaryDirectory() as temp:
            locale_root, overrides_root, manifest = self._isolated_review_tree(temp)
            with self._patch_review_tree(locale_root, overrides_root, manifest), self._patch_google_tree(locale_root, overrides_root, manifest):
                bundle = review.build_review_bundle("pt-BR")
                entry = bundle["catalogs"]["ui"]["menu.file"]
                entry["translation"] = "Arquivo"
                entry["review_state"] = "reviewed"
                entry["reviewer"] = "manual-test"
                entry["note"] = "Reviewed in context"
                path = Path(temp) / "pt-BR.review.json"
                path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
                result = review.import_review(
                    path,
                    now=datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc),
                )

                self.assertEqual(result.reviewed, 1)
                raw = json.loads((overrides_root / "pt-BR.json").read_text(encoding="utf-8"))
                record = raw["ui"]["menu.file"]
                self.assertEqual(record["translation"], "Arquivo")
                self.assertEqual(record["status"], "reviewed")
                self.assertFalse(record["locked"])
                self.assertEqual(record["reviewer"], "manual-test")
                self.assertEqual(record["reviewed_at"], "2026-09-01T16:00:00Z")
                target = json.loads((locale_root / "pt-BR" / "ui.json").read_text(encoding="utf-8"))
                self.assertEqual(target["strings"]["menu.file"], "Arquivo")

    def test_locked_review_becomes_authoritative_even_for_force_translation(self):
        with tempfile.TemporaryDirectory() as temp:
            locale_root, overrides_root, manifest = self._isolated_review_tree(temp)
            with self._patch_review_tree(locale_root, overrides_root, manifest), self._patch_google_tree(locale_root, overrides_root, manifest):
                bundle = review.build_review_bundle("pt-BR")
                entry = bundle["catalogs"]["ui"]["menu.file"]
                entry["translation"] = "Arquivo"
                entry["review_state"] = "locked"
                path = Path(temp) / "locked.review.json"
                path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
                review.import_review(path, now=datetime(2026, 9, 1, tzinfo=timezone.utc))
                records = gt._manual_override_records("pt-BR")
                self.assertTrue(records["ui"]["menu.file"]["locked"])
                plan = gt.translation_plan("pt-BR", force=True)
                self.assertGreaterEqual(plan.overridden, 1)

    def test_review_import_rejects_stale_source_hash_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            locale_root, overrides_root, manifest = self._isolated_review_tree(temp)
            before = (overrides_root / "pt-BR.json").read_bytes()
            with self._patch_review_tree(locale_root, overrides_root, manifest), self._patch_google_tree(locale_root, overrides_root, manifest):
                bundle = review.build_review_bundle("pt-BR")
                entry = bundle["catalogs"]["ui"]["menu.file"]
                entry["translation"] = "Arquivo"
                entry["review_state"] = "reviewed"
                entry["source_hash"] = "0" * 64
                path = Path(temp) / "stale.review.json"
                path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(review.ReviewImportError):
                    review.import_review(path)
            self.assertEqual((overrides_root / "pt-BR.json").read_bytes(), before)

    def test_review_import_rejects_placeholder_damage(self):
        with tempfile.TemporaryDirectory() as temp:
            locale_root, overrides_root, manifest = self._isolated_review_tree(temp)
            with self._patch_review_tree(locale_root, overrides_root, manifest), self._patch_google_tree(locale_root, overrides_root, manifest):
                bundle = review.build_review_bundle("pt-BR")
                chosen = None
                for catalog, values in bundle["catalogs"].items():
                    for key, entry in values.items():
                        if entry["placeholders"]:
                            chosen = (catalog, key, entry)
                            break
                    if chosen:
                        break
                self.assertIsNotNone(chosen)
                _catalog, _key, entry = chosen
                entry["translation"] = "Translation without required format field"
                entry["review_state"] = "reviewed"
                path = Path(temp) / "bad-placeholder.review.json"
                path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(review.ReviewImportError) as caught:
                    review.import_review(path)
                self.assertIn("placeholders", str(caught.exception))

    def test_review_import_rejects_protected_term_damage(self):
        with tempfile.TemporaryDirectory() as temp:
            locale_root, overrides_root, manifest = self._isolated_review_tree(temp)
            with self._patch_review_tree(locale_root, overrides_root, manifest), self._patch_google_tree(locale_root, overrides_root, manifest):
                bundle = review.build_review_bundle("pt-BR")
                chosen = None
                for catalog, values in bundle["catalogs"].items():
                    for key, entry in values.items():
                        if "DHT" in entry["source"]:
                            chosen = (catalog, key, entry)
                            break
                    if chosen:
                        break
                self.assertIsNotNone(chosen)
                _catalog, _key, entry = chosen
                entry["translation"] = "Tradução que remove o termo técnico protegido"
                entry["review_state"] = "reviewed"
                path = Path(temp) / "bad-term.review.json"
                path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(review.ReviewImportError) as caught:
                    review.import_review(path)
                self.assertIn("DHT", str(caught.exception))

    def test_validator_rejects_stale_rich_manual_override(self):
        source = {"menu.file": "File"}
        target = {"menu.file": "Arquivo"}
        with patch.object(gt, "_load_cache", return_value={}):
            with patch.object(
                gt,
                "_manual_override_records",
                return_value={"ui": {"menu.file": {"translation": "Arquivo", "source_hash": "old", "status": "reviewed"}}},
            ):
                with patch.object(gt, "_manifest_hash", return_value="current"):
                    report = validate_translation_freshness("pt-BR", "ui", source, target)
        self.assertFalse(report.ok)
        self.assertIn("stale manual-review source hash", report.errors[0])

    def test_review_check_is_offline_and_accepts_incomplete_review(self):
        self.assertEqual(build_locales_main(["--review-check", "--locale", "pt-BR"]), 0)

    def test_gitignore_tracks_review_helper_and_ignores_review_exports(self):
        text = (gt.ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!tools/localization/review_localization.bat", text)
        self.assertIn("/tools/localization/review_exports/", text)


if __name__ == "__main__":
    unittest.main()
