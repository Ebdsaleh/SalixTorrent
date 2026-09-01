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
    parser.add_argument("--bootstrap-cache", action="store_true", help="Adopt current pre-Stage-5 locale entries into the source-hash cache")
    parser.add_argument("--project-id", help="Google Cloud project ID/number (otherwise use environment/ADC discovery)")
    parser.add_argument("--location", default=None, help=f"Google Translation location (default: {DEFAULT_LOCATION})")
    parser.add_argument("--model", default=None, help=f"Google Translation model ID (default: {DEFAULT_MODEL})")
    parser.add_argument("--strict", action="store_true", help="Treat missing translations as validation errors")
    args = parser.parse_args(argv)

    do_extract = args.extract or args.all
    do_translate = args.translate or args.all
    do_validate = args.validate or args.all
    if not any((do_extract, do_translate, do_validate, args.check, args.report, args.bootstrap_cache, args.dry_run)):
        parser.error("choose --extract, --check, --report, --translate, --validate, --bootstrap-cache, --dry-run or --all")

    if args.dry_run and args.bootstrap_cache:
        parser.error("--dry-run and --bootstrap-cache cannot be combined")
    if args.dry_run and args.all:
        parser.error("--dry-run cannot be combined with --all")

    if do_extract:
        for name, path in extract_all().items():
            print(f"Extracted {name}: {path}")

    if args.check:
        drift = extraction_drift()
        if drift:
            print("Extraction check: FAILED")
            for path in drift:
                print(f"  stale/missing: {path}")
            print("Run: python tools\\localization\\build_locales.py --extract")
            return 3
        print("Extraction check: OK (canonical catalogs and manifest are current)")

    if args.report:
        _print_extraction_report()

    locales = args.locales or sorted(TARGET_CODES)

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
