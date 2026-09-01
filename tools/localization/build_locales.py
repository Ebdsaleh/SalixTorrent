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
        bootstrap_translation_memory,
        merge_translation_memory,
        translate_locale,
        translation_memory_audit,
        translation_memory_status,
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
    from .provider_registry import provider_descriptors
    from .framework_audit import extraction_map, framework_audit, runtime_boundary_audit
    from .validate_locales import validate_all
except ImportError:  # direct script execution
    from extract_strings import extract_all, extract_records, extraction_drift, extraction_summary
    from google_translate import (
        DEFAULT_LOCATION,
        DEFAULT_MODEL,
        TARGET_CODES,
        bootstrap_translation_cache,
        bootstrap_translation_memory,
        merge_translation_memory,
        translate_locale,
        translation_memory_audit,
        translation_memory_status,
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
    from provider_registry import provider_descriptors
    from framework_audit import extraction_map, framework_audit, runtime_boundary_audit
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


def _print_translation_plan(locales: list[str], *, force: bool = False, memory_path=None) -> None:
    print("Translation plan (no network, no files changed):")
    for locale in locales:
        stats = translation_plan(locale, force=force, memory_path=memory_path)
        print(
            f"  {locale}: cached={stats.cached}, memory={stats.memory}, "
            f"overrides={stats.overridden}, would_translate={stats.would_translate}"
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


def _print_provider_report() -> None:
    print("Translation providers:")
    for item in provider_descriptors():
        mode = "network" if item.network else "offline"
        print(f"  {item.name}: {mode}; {item.description}")


def _print_memory_status(path=None) -> None:
    stats = translation_memory_status(path)
    print("Translation memory:")
    print(f"  Path: {stats.path}")
    print(f"  Source locale: {stats.source_locale}")
    print(f"  Target locales: {stats.target_locales}")
    print(f"  Entries: {stats.entries}")
    print(f"  Reusable: {stats.reusable}")
    print(f"  Reviewed/locked: {stats.reviewed}")
    print(f"  Machine: {stats.machine}")
    print(f"  Seeded existing: {stats.seeded}")




def _print_framework_report() -> None:
    mapping = extraction_map()
    print("Framework extraction map:")
    print("  Extractable now:")
    for path in mapping["extractable_now"]:
        print(f"    {path}")
    print("  SalixTorrent application adapters:")
    for path in mapping["application_adapters"]:
        print(f"    {path}")
    print("  Development/provider adapters:")
    for path in mapping["development_adapters"]:
        print(f"    {path}")


def _run_framework_audit() -> bool:
    audit = framework_audit()
    for module in audit.modules:
        marker = "OK" if module.ok else "FAILED"
        print(f"  {marker}: {module.path}")
        for error in module.errors:
            print(f"    ERROR: {error}")
    for error in audit.errors:
        print(f"ERROR: {error}")
    print(
        f"Framework extraction audit: {'OK' if audit.ok else 'FAILED'} "
        f"({audit.extractable_count} extractable module(s))"
    )
    return audit.ok

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
    parser.add_argument("--providers", action="store_true", help="List registered development translation providers")
    parser.add_argument("--provider", default="google-cloud", help="Translation provider name for network generation")
    parser.add_argument("--memory-status", action="store_true", help="Show provider-neutral translation-memory statistics")
    parser.add_argument("--memory-bootstrap", action="store_true", help="Seed translation memory from current hash-valid project cache")
    parser.add_argument("--memory-path", help="Translation-memory JSON path (otherwise env/default beside cache)")
    parser.add_argument("--memory-merge", metavar="FILE", help="Merge another compatible translation-memory JSON file")
    parser.add_argument("--stage9-check", action="store_true", help="Run Stage 9 provider/memory infrastructure checks")
    parser.add_argument("--framework-report", action="store_true", help="Show Stage 10 framework extraction map")
    parser.add_argument("--framework-audit", action="store_true", help="Audit extractable localization modules for app/GUI/provider coupling")
    parser.add_argument("--stage10-check", action="store_true", help="Run Stage 10 framework-extraction readiness checks")
    parser.add_argument("--runtime-boundary-audit", action="store_true", help="Audit Stage 11 generic runtime/semantic facade boundaries")
    parser.add_argument("--stage11-check", action="store_true", help="Run Stage 11 generic runtime-kernel extraction checks")
    parser.add_argument("--bootstrap-cache", action="store_true", help="Adopt current pre-Stage-5 locale entries into the source-hash cache")
    parser.add_argument("--project-id", help="Google Cloud project ID/number (otherwise use environment/ADC discovery)")
    parser.add_argument("--location", default=None, help=f"Google Translation location (default: {DEFAULT_LOCATION})")
    parser.add_argument("--model", default=None, help=f"Google Translation model ID (default: {DEFAULT_MODEL})")
    parser.add_argument("--strict", action="store_true", help="Treat missing translations as validation errors")
    args = parser.parse_args(argv)

    do_extract = args.extract or args.all
    do_translate = args.translate or args.all
    do_validate = args.validate or args.all
    if not any((do_extract, do_translate, do_validate, args.check, args.report, args.bootstrap_cache, args.dry_run, args.status, args.doctor, args.generate_initial, args.manifest, args.package_check, args.pseudo_check, args.stage7_check, args.review_report, args.review_export, args.review_import, args.stage8_check, args.providers, args.memory_status, args.memory_bootstrap, args.memory_merge, args.stage9_check, args.framework_report, args.framework_audit, args.stage10_check, args.runtime_boundary_audit, args.stage11_check)):
        parser.error("choose --extract, --check, --report, --translate, --validate, --bootstrap-cache, --dry-run, --status, --doctor, --generate-initial, --manifest, --package-check, --pseudo-check, --stage7-check, --review-report, --review-export, --review-import, --stage8-check, --providers, --memory-status, --memory-bootstrap, --memory-merge, --stage9-check, --framework-report, --framework-audit, --stage10-check, --runtime-boundary-audit, --stage11-check or --all")

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

    if args.providers:
        _print_provider_report()

    if args.framework_report:
        _print_framework_report()

    if args.memory_bootstrap:
        stats = bootstrap_translation_memory(memory_path=args.memory_path)
        for locale in sorted(stats):
            print(f"{locale}: seeded {stats[locale]} translation-memory entrie(s)")

    if args.memory_merge:
        merged = merge_translation_memory(
            args.memory_merge,
            memory_path=args.memory_path,
        )
        print(
            f"Translation memory merge: added={merged['added']}, "
            f"reused={merged['reused']}, conflicts={merged['conflicts']}"
        )
        if merged["conflicts"]:
            print("Translation memory merge refused to write because conflicts require review.")
            return 9

    if args.memory_status:
        _print_memory_status(args.memory_path)

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
        _print_translation_plan(locales, force=args.force, memory_path=args.memory_path)
        for locale in locales:
            stats = translate_locale(
                locale,
                force=args.force,
                no_network=False,
                project_id=args.project_id,
                location=args.location,
                model=args.model,
                provider_name=args.provider,
                memory_path=args.memory_path,
            )
            print(
                f"{locale}: cached={stats['cached']}, memory={stats.get('memory', 0)}, "
                f"overrides={stats['overridden']}, translated={stats['translated']}, "
                f"missing={stats['missing']}, "
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
        _print_translation_plan(locales, force=args.force, memory_path=args.memory_path)

    if do_translate and not args.dry_run:
        for locale in locales:
            stats = translate_locale(
                locale,
                force=args.force,
                no_network=args.no_network,
                project_id=args.project_id,
                location=args.location,
                model=args.model,
                provider_name=args.provider,
                memory_path=args.memory_path,
            )
            print(
                f"{locale}: cached={stats['cached']}, memory={stats.get('memory', 0)}, "
                f"overrides={stats['overridden']}, translated={stats['translated']}, "
                f"missing={stats['missing']}, "
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

    if args.stage9_check:
        drift = extraction_drift()
        manifest_stale = locale_manifest_drift()
        if drift or manifest_stale:
            print("Stage 9 drift check: FAILED")
            return 3
        descriptors = provider_descriptors()
        if not descriptors:
            print("Stage 9 provider registry: FAILED (no providers registered)")
            return 9
        print(f"Stage 9 provider registry: OK ({len(descriptors)} provider(s))")
        seeded = bootstrap_translation_memory(memory_path=args.memory_path, write=False)
        print(
            "Stage 9 memory bootstrap audit: OK ("
            + ", ".join(f"{locale}={count}" for locale, count in sorted(seeded.items()))
            + ")"
        )
        audit = translation_memory_audit(args.memory_path)
        if not audit.ok:
            print("Stage 9 translation memory audit: FAILED")
            for error in audit.errors:
                print(f"ERROR: {error}")
            return 9
        print("Stage 9 translation memory audit: OK")
        _print_memory_status(args.memory_path)
        print("Stage 9 provider-neutral translation memory: OK")

    if args.framework_audit and not (args.stage10_check or args.stage11_check):
        if not _run_framework_audit():
            return 10

    if args.runtime_boundary_audit and not args.stage11_check:
        boundary_errors = runtime_boundary_audit()
        if boundary_errors:
            print("Stage 11 runtime/semantic boundary: FAILED")
            for error in boundary_errors:
                print(f"ERROR: {error}")
            return 11
        print("Stage 11 runtime/semantic boundary: OK")

    if args.stage10_check:
        drift = extraction_drift()
        manifest_stale = locale_manifest_drift()
        if drift or manifest_stale:
            print("Stage 10 drift check: FAILED")
            for path in drift:
                print(f"ERROR: stale/missing: {path}")
            if manifest_stale:
                print("ERROR: stale/missing: app/localization/locales/manifest.json")
            return 3
        print("Stage 10 drift check: OK")
        if not _run_framework_audit():
            return 10
        memory_audit = translation_memory_audit(args.memory_path)
        if not memory_audit.ok:
            print("Stage 10 translation-memory boundary: FAILED")
            for error in memory_audit.errors:
                print(f"ERROR: {error}")
            return 10
        print("Stage 10 translation-memory boundary: OK")
        print("Stage 10 framework extraction readiness: OK")

    if args.stage11_check:
        drift = extraction_drift()
        manifest_stale = locale_manifest_drift()
        if drift or manifest_stale:
            print("Stage 11 drift check: FAILED")
            for path in drift:
                print(f"ERROR: stale/missing: {path}")
            if manifest_stale:
                print("ERROR: stale/missing: app/localization/locales/manifest.json")
            return 3
        print("Stage 11 drift check: OK")
        if not _run_framework_audit():
            return 11
        boundary_errors = runtime_boundary_audit()
        if boundary_errors:
            print("Stage 11 runtime/semantic boundary: FAILED")
            for error in boundary_errors:
                print(f"ERROR: {error}")
            return 11
        print("Stage 11 runtime/semantic boundary: OK")
        print("Stage 11 generic localization runtime kernel: OK")

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
