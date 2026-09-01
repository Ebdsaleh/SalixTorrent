"""SalixTorrent Phase-12 localization build orchestrator."""

from __future__ import annotations

import argparse

try:
    from .extract_strings import (
        extract_all,
        extract_records,
        extraction_drift,
        extraction_summary,
    )
    from .google_translate import (
        DEFAULT_LOCATION,
        DEFAULT_MODEL,
        TARGET_CODES,
        bootstrap_translation_cache,
        translate_locale,
        translation_plan,
    )
    from .stage6_support import all_generation_status, google_doctor
    from .stage7_support import (
        locale_manifest_drift,
        packaging_report,
        pseudo_audit,
        write_locale_manifest,
    )
    from .review import export_review, import_review, review_audit, review_summary
    from .validate_locales import validate_all
except ImportError:  # direct script execution
    from extract_strings import extract_all, extract_records, extraction_drift, extraction_summary
    from google_translate import (
        DEFAULT_LOCATION,
        DEFAULT_MODEL,
        TARGET_CODES,
        bootstrap_translation_cache,
        translate_locale,
        translation_plan,
    )
    from stage6_support import all_generation_status, google_doctor
    from stage7_support import (
        locale_manifest_drift,
        packaging_report,
        pseudo_audit,
        write_locale_manifest,
    )
    from review import export_review, import_review, review_audit, review_summary
    from validate_locales import validate_all


def _print_extraction_report() -> None:
    result = extract_records()
    summary = extraction_summary(result)
    print("Extraction report:")
    print(f"  UI entries: {summary['catalog_entries']['ui']}")
    print(f"  Help entries: {summary['catalog_entries']['help']}")
    print(f"  Glossary entries: {summary['catalog_entries']['glossary']}")
    print(f"  Total canonical entries: {summary['total_entries']}")
    print(f"  Entries with placeholders: {summary['placeholder_entries']}")
    print(f"  Reused localization keys: {summary['duplicate_keys']}")
    print(f"  Dynamic direct tr() calls: {summary['dynamic_tr_calls']}")
    print(f"  Malformed format strings: {summary['malformed_format_entries']}")

    duplicates = result.duplicate_keys
    if duplicates:
        print("  Reused-key detail (same canonical text; safe):")
        for catalog in sorted(duplicates):
            for key, occurrences in sorted(duplicates[catalog].items()):
                locations = ", ".join(f"{item.path}:{item.line}" for item in occurrences)
                print(f"    {catalog}:{key} -> {locations}")


def _print_translation_plan(locales: list[str], *, force: bool = False) -> None:
    print("Translation plan (no network, no files changed):")
    for locale in locales:
        stats = translation_plan(locale, force=force)
        print(
            f"  {locale}: cached={stats.cached}, overrides={stats.overridden}, "
            f"would_translate={stats.would_translate}"
        )



def _print_generation_status(locales: list[str]) -> None:
    print("Locale generation status:")
    for status in all_generation_status(locales):
        marker = "complete" if status.complete else "incomplete"
        print(
            f"  {status.locale}: packaged={status.packaged}/{status.canonical}, "
            f"cache_valid={status.cache_valid}, overrides={status.overrides}, "
            f"missing={status.missing} ({marker})"
        )


def _print_review_report(locales: list[str]) -> None:
    print("Translation review status:")
    for locale in locales:
        summary = review_summary(locale)
        marker = "complete" if summary.review_complete else "incomplete"
        print(
            f"  {locale}: total={summary.total}, missing={summary.missing}, "
            f"review_needed={summary.review_needed}, reviewed={summary.reviewed}, "
            f"locked={summary.locked}, stale={summary.stale}, invalid={summary.invalid} ({marker})"
        )


def _print_google_doctor(report, *, probed: bool) -> None:
    print("Google localization development setup:")
    print(f"  Cloud Translation client: {'Available' if report.client_library else 'Missing'}")
    print(f"  Google auth library: {'Available' if report.auth_library else 'Missing'}")
    print(f"  Application Default Credentials: {'Available' if report.credentials else 'Missing'}")
    print(f"  Credential type: {report.credential_type}")
    print(f"  Project: {report.project_id or '--'}")
    print(f"  Project source: {report.project_source}")
    print(f"  Location: {report.location}")
    print(f"  Model: {report.model}")
    if probed:
        print(f"  Authenticated API probe: {'OK' if report.probe_ok else 'FAILED'}")
    else:
        print("  Authenticated API probe: Not requested (local-only doctor run)")
    print(f"  Ready for Stage 6: {'Yes' if report.ready else 'No'}")
    print(f"  Detail: {report.detail}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true", help="Regenerate canonical en-AU catalogs and extraction manifest")
    parser.add_argument("--check", action="store_true", help="Check generated canonical catalogs/manifest without modifying files")
    parser.add_argument("--report", action="store_true", help="Print canonical extraction/source-contract report")
    parser.add_argument("--translate", action="store_true", help="Translate new/changed strings through Google Cloud")
    parser.add_argument("--validate", action="store_true", help="Validate locale catalogs")
    parser.add_argument("--all", action="store_true", help="Extract, translate and validate")
    parser.add_argument("--locale", action="append", dest="locales", choices=sorted(TARGET_CODES))
    parser.add_argument("--force", action="store_true", help="Ignore translation cache for selected targets (manual overrides still win)")
    parser.add_argument("--no-network", action="store_true", help="Never contact Google; rebuild selected locales from cache/overrides only")
    parser.add_argument("--dry-run", action="store_true", help="Show changed-only translation plan; never contact Google or modify files")
    parser.add_argument("--status", action="store_true", help="Show packaged/cache completeness for the target locale packs")
    parser.add_argument("--doctor", action="store_true", help="Check local Google client/auth/project setup without translating")
    parser.add_argument("--probe", action="store_true", help="With --doctor, perform one tiny authenticated Translation API probe")
    parser.add_argument("--generate-initial", action="store_true", help="Stage 6: translate selected initial locales and require strict completeness")
    parser.add_argument("--manifest", action="store_true", help="Regenerate deterministic runtime locale metadata manifest")
    parser.add_argument("--package-check", action="store_true", help="Validate localization resources and PyInstaller packaging contract")
    parser.add_argument("--pseudo-check", action="store_true", help="Validate the in-memory en-XA pseudo-localization contract")
    parser.add_argument("--stage7-check", action="store_true", help="Run Stage 7 offline hardening checks (drift, validation, packaging, pseudo locale)")
    parser.add_argument("--review-report", action="store_true", help="Show human-review/missing/stale status for target locale entries")
    parser.add_argument("--review-export", action="store_true", help="Export editable offline review bundle(s) for selected locale(s)")
    parser.add_argument("--review-export-path", help="Output file for --review-export (requires exactly one --locale)")
    parser.add_argument("--review-import", metavar="FILE", help="Import reviewed/locked entries from an offline review bundle")
    parser.add_argument("--stage8-check", action="store_true", help="Run Stage 8A offline review/provenance infrastructure checks")
    parser.add_argument("--bootstrap-cache", action="store_true", help="Adopt current pre-Stage-5 locale entries into the source-hash cache")
    parser.add_argument("--project-id", help="Google Cloud project ID/number (otherwise use environment/ADC discovery)")
    parser.add_argument("--location", default=None, help=f"Google Translation location (default: {DEFAULT_LOCATION})")
    parser.add_argument("--model", default=None, help=f"Google Translation model ID (default: {DEFAULT_MODEL})")
    parser.add_argument("--strict", action="store_true", help="Treat missing translations as validation errors")
    args = parser.parse_args(argv)

    do_extract = args.extract or args.all
    do_translate = args.translate or args.all
    do_validate = args.validate or args.all
    if not any((do_extract, do_translate, do_validate, args.check, args.report, args.bootstrap_cache, args.dry_run, args.status, args.doctor, args.generate_initial, args.manifest, args.package_check, args.pseudo_check, args.stage7_check, args.review_report, args.review_export, args.review_import, args.stage8_check)):
        parser.error("choose --extract, --check, --report, --translate, --validate, --bootstrap-cache, --dry-run, --status, --doctor, --generate-initial, --manifest, --package-check, --pseudo-check, --stage7-check, --review-report, --review-export, --review-import, --stage8-check or --all")

    if args.dry_run and args.bootstrap_cache:
        parser.error("--dry-run and --bootstrap-cache cannot be combined")
    if args.dry_run and args.all:
        parser.error("--dry-run cannot be combined with --all")
    if args.probe and not args.doctor:
        parser.error("--probe must be combined with --doctor")
    if args.generate_initial and args.no_network:
        parser.error("--generate-initial cannot be combined with --no-network")
    if args.generate_initial and args.dry_run:
        parser.error("--generate-initial cannot be combined with --dry-run")
    if args.review_export_path and not args.review_export:
        parser.error("--review-export-path requires --review-export")
    if args.review_export_path and (not args.locales or len(args.locales) != 1):
        parser.error("--review-export-path requires exactly one --locale")
    if args.review_import and (args.review_export or args.review_export_path):
        parser.error("--review-import cannot be combined with --review-export")

    if do_extract:
        for name, path in extract_all().items():
            print(f"Extracted {name}: {path}")
        print(f"Extracted locale manifest: {write_locale_manifest()}")

    if args.manifest and not do_extract:
        print(f"Extracted locale manifest: {write_locale_manifest()}")

    if args.check:
        drift = extraction_drift()
        manifest_stale = locale_manifest_drift()
        if drift or manifest_stale:
            print("Extraction check: FAILED")
            for path in drift:
                print(f"  stale/missing: {path}")
            if manifest_stale:
                print("  stale/missing: app/localization/locales/manifest.json")
            print(r"Run: python tools\localization\build_locales.py --extract")
            return 3
        print("Extraction check: OK (canonical catalogs and manifests are current)")

    if args.report:
        _print_extraction_report()

    locales = args.locales or sorted(TARGET_CODES)

    if args.status:
        _print_generation_status(locales)

    if args.review_report:
        _print_review_report(locales)

    if args.review_export:
        for locale in locales:
            output = export_review(locale, args.review_export_path if len(locales) == 1 else None)
            print(f"Review export {locale}: {output}")

    if args.review_import:
        try:
            imported = import_review(args.review_import)
        except Exception as exc:
            print(f"Review import: FAILED ({exc})")
            return 7
        write_locale_manifest()
        print(
            f"Review import {imported.locale}: reviewed={imported.reviewed}, "
            f"locked={imported.locked}, pending/unchanged={imported.unchanged}"
        )
        print(f"Authoritative overrides: {imported.output_path}")

    if args.doctor:
        report = google_doctor(
            project_id=args.project_id,
            location=args.location,
            model=args.model,
            probe=args.probe,
        )
        _print_google_doctor(report, probed=args.probe)
        if not report.ready or (args.probe and not report.probe_ok):
            return 4

    if args.generate_initial:
        drift = extraction_drift()
        if drift:
            print("Stage 6 generation refused: canonical extraction is stale.")
            for path in drift:
                print(f"  stale/missing: {path}")
            print("Run: python tools\\localization\\build_locales.py --extract")
            return 3
        _print_translation_plan(locales, force=args.force)
        for locale in locales:
            stats = translate_locale(
                locale,
                force=args.force,
                no_network=False,
                project_id=args.project_id,
                location=args.location,
                model=args.model,
            )
            print(
                f"{locale}: cached={stats['cached']}, overrides={stats['overridden']}, "
                f"translated={stats['translated']}, missing={stats['missing']}, "
                f"batches={stats['batches']}"
            )
        write_locale_manifest()
        report = validate_all(strict_missing=True, locales=["en-AU", *locales])
        for warning in report.warnings:
            print(f"WARNING: {warning}")
        for error in report.errors:
            print(f"ERROR: {error}")
        if not report.ok:
            print(
                f"Stage 6 strict validation: FAILED "
                f"({len(report.errors)} error(s), {len(report.warnings)} warning(s))"
            )
            return 2
        print("Stage 6 strict validation: OK (all selected locale packs complete)")
        _print_generation_status(locales)

    if args.bootstrap_cache:
        stats = bootstrap_translation_cache()
        for locale in sorted(stats):
            print(f"{locale}: adopted {stats[locale]} existing translation(s) into cache")

    if args.dry_run:
        _print_translation_plan(locales, force=args.force)

    if do_translate and not args.dry_run:
        for locale in locales:
            stats = translate_locale(
                locale,
                force=args.force,
                no_network=args.no_network,
                project_id=args.project_id,
                location=args.location,
                model=args.model,
            )
            print(
                f"{locale}: cached={stats['cached']}, overrides={stats['overridden']}, "
                f"translated={stats['translated']}, missing={stats['missing']}, "
                f"batches={stats['batches']}"
            )

    if do_translate and not args.dry_run:
        write_locale_manifest()

    if args.pseudo_check or args.stage7_check:
        pseudo = pseudo_audit()
        print(
            f"Pseudo-locale check: {'OK' if pseudo.ok else 'FAILED'} "
            f"({pseudo.entries} entries; placeholder failures={len(pseudo.placeholder_failures)}, "
            f"expansion failures={len(pseudo.expansion_failures)})"
        )
        if not pseudo.ok:
            for key in pseudo.placeholder_failures[:12]:
                print(f"ERROR: pseudo placeholder contract failed: {key}")
            for key in pseudo.expansion_failures[:12]:
                print(f"ERROR: pseudo expansion contract failed: {key}")
            return 5

    if args.package_check or args.stage7_check:
        package = packaging_report(["en-AU", *locales])
        for warning in package.warnings:
            print(f"WARNING: {warning}")
        for error in package.errors:
            print(f"ERROR: {error}")
        print(
            f"Packaging check: {'OK' if package.ok else 'FAILED'} "
            f"({package.checked_resources} runtime resources checked)"
        )
        if not package.ok:
            return 6

    if args.stage7_check:
        drift = extraction_drift()
        manifest_stale = locale_manifest_drift()
        if drift or manifest_stale:
            print("Stage 7 drift check: FAILED")
            for path in drift:
                print(f"ERROR: stale/missing: {path}")
            if manifest_stale:
                print("ERROR: stale/missing: app/localization/locales/manifest.json")
            return 3
        print("Stage 7 drift check: OK")
        report = validate_all(strict_missing=False, locales=["en-AU", *locales])
        for warning in report.warnings:
            print(f"WARNING: {warning}")
        for error in report.errors:
            print(f"ERROR: {error}")
        print(
            f"Stage 7 validation: {'OK' if report.ok else 'FAILED'} "
            f"({len(report.errors)} error(s), {len(report.warnings)} warning(s))"
        )
        if not report.ok:
            return 2

    if args.stage8_check:
        drift = extraction_drift()
        manifest_stale = locale_manifest_drift()
        if drift or manifest_stale:
            print("Stage 8A drift check: FAILED")
            for path in drift:
                print(f"ERROR: stale/missing: {path}")
            if manifest_stale:
                print("ERROR: stale/missing: app/localization/locales/manifest.json")
            return 3
        audit = review_audit(locales)
        for warning in audit.warnings:
            print(f"WARNING: {warning}")
        for error in audit.errors:
            print(f"ERROR: {error}")
        _print_review_report(locales)
        report = validate_all(strict_missing=False, locales=["en-AU", *locales])
        for warning in report.warnings:
            print(f"WARNING: {warning}")
        for error in report.errors:
            print(f"ERROR: {error}")
        ok = audit.ok and report.ok
        print(
            f"Stage 8A review infrastructure: {'OK' if ok else 'FAILED'} "
            f"({len(audit.errors) + len(report.errors)} error(s), "
            f"{len(audit.warnings) + len(report.warnings)} warning(s))"
        )
        if not ok:
            return 8

    if do_validate:
        validate_locales = ["en-AU", *locales]
        report = validate_all(strict_missing=args.strict, locales=validate_locales)
        for warning in report.warnings:
            print(f"WARNING: {warning}")
        for error in report.errors:
            print(f"ERROR: {error}")
        print(
            f"Validation: {'OK' if report.ok else 'FAILED'} "
            f"({len(report.errors)} error(s), {len(report.warnings)} warning(s))"
        )
        if not report.ok:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
