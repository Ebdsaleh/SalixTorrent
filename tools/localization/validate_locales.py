"""Validate SalixTorrent locale catalogs and semantic documentation before packaging."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable

try:
    from .contracts import placeholder_names
except ImportError:  # direct script execution
    from contracts import placeholder_names

try:
    from .localization_validation import catalog_hash, locale_manifest_drift
except ImportError:  # direct script execution
    from localization_validation import catalog_hash, locale_manifest_drift

ROOT = Path(__file__).resolve().parents[2]
LOCALE_ROOT = ROOT / "app" / "localization" / "locales"
CONTENT_ROOT = ROOT / "app" / "localization" / "content"
CANONICAL = "en-AU"
CATALOGS = ("ui", "help", "glossary")


def placeholders(text: str) -> set[str]:
    """Compatibility alias for the shared localization placeholder contract."""
    return placeholder_names(text)


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_catalog(locale: str, catalog: str) -> Dict[str, str]:
    path = LOCALE_ROOT / locale / f"{catalog}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    values = raw.get("strings", raw) if isinstance(raw, dict) else None
    if not isinstance(values, dict):
        raise ValueError(f"{path}: expected object mapping under 'strings'")
    out = {}
    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(f"{path}: catalog entries must map strings to strings")
        out[key] = value
    return out


def load_catalog_payload(locale: str, catalog: str) -> dict:
    path = LOCALE_ROOT / locale / f"{catalog}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected JSON object")
    return raw


def validate_catalog_metadata(locale: str, catalog: str, strings: Dict[str, str]) -> ValidationReport:
    report = ValidationReport()
    path = LOCALE_ROOT / locale / f"{catalog}.json"
    try:
        raw = load_catalog_payload(locale, catalog)
    except Exception as exc:
        report.errors.append(f"{locale}/{catalog}: {exc}")
        return report

    meta = raw.get("_meta")
    if not isinstance(meta, dict):
        report.errors.append(f"{locale}/{catalog}: missing/invalid _meta object")
        return report

    expected = {
        "locale": locale,
        "source_locale": CANONICAL,
        "catalog": catalog,
    }
    for field_name, expected_value in expected.items():
        actual = meta.get(field_name)
        if actual != expected_value:
            report.errors.append(
                f"{locale}/{catalog}: _meta.{field_name}={actual!r}, expected {expected_value!r}"
            )

    if "entry_count" in meta:
        try:
            declared_count = int(meta.get("entry_count"))
        except (TypeError, ValueError):
            declared_count = -1
        if declared_count != len(strings):
            report.errors.append(
                f"{locale}/{catalog}: _meta.entry_count={meta.get('entry_count')!r}, actual {len(strings)}"
            )
    elif locale == CANONICAL:
        report.errors.append(f"{locale}/{catalog}: canonical catalog missing _meta.entry_count")

    expected_hash = catalog_hash(strings)
    declared_hash = str(meta.get("catalog_hash") or "")
    if declared_hash:
        if declared_hash != expected_hash:
            report.errors.append(
                f"{locale}/{catalog}: _meta.catalog_hash does not match catalog contents"
            )
    elif locale == CANONICAL:
        report.errors.append(f"{locale}/{catalog}: canonical catalog missing _meta.catalog_hash")
    return report


def validate_translation_freshness(locale: str, catalog: str, source: Dict[str, str], target: Dict[str, str]) -> ValidationReport:
    """Reject target/review strings whose recorded source hash is stale."""
    report = ValidationReport()
    if locale == CANONICAL:
        return report
    try:
        try:
            from .google_translate import (
                _cache_entry,
                _load_cache,
                _manual_override_records,
                _manifest_hash,
            )
        except ImportError:
            from google_translate import _cache_entry, _load_cache, _manual_override_records, _manifest_hash
        cache = _load_cache()
        overrides = _manual_override_records(locale).get(catalog, {})
    except Exception as exc:
        report.errors.append(f"{locale}/{catalog}: cannot validate translation freshness: {exc}")
        return report

    for key in sorted(set(source) & set(target)):
        expected_hash = _manifest_hash(catalog, key, source[key])
        override = overrides.get(key)
        if isinstance(override, dict):
            recorded_hash = str(override.get("source_hash") or "")
            if recorded_hash and recorded_hash != expected_hash:
                report.errors.append(
                    f"{locale}/{catalog}:{key}: stale manual-review source hash; re-review canonical text"
                )
            elif not recorded_hash:
                report.warnings.append(
                    f"{locale}/{catalog}:{key}: legacy manual override has no source-hash provenance"
                )
            if str(override.get("translation") or "") != target[key]:
                report.warnings.append(
                    f"{locale}/{catalog}:{key}: packaged translation differs from authoritative manual override"
                )
            continue

        entry = _cache_entry(cache, locale, catalog, key)
        if not entry:
            report.warnings.append(
                f"{locale}/{catalog}:{key}: translation has no source-hash provenance"
            )
            continue
        if entry.get("source_hash") != expected_hash:
            report.errors.append(
                f"{locale}/{catalog}:{key}: stale translation source hash; regenerate or review"
            )
        elif entry.get("translation") != target[key]:
            report.warnings.append(
                f"{locale}/{catalog}:{key}: packaged translation differs from hash-valid cache"
            )
    return report


def validate_manual_overrides(locale: str, catalog: str, source: Dict[str, str], target: Dict[str, str]) -> ValidationReport:
    """Validate reviewed/locked override metadata and contracts."""
    report = ValidationReport()
    if locale == CANONICAL:
        return report
    try:
        try:
            from .google_translate import _manual_override_records, _manifest_hash, _protected_terms
        except ImportError:
            from google_translate import _manual_override_records, _manifest_hash, _protected_terms
        records = _manual_override_records(locale).get(catalog, {})
        protected_terms = _protected_terms()
    except Exception as exc:
        report.errors.append(f"{locale}/{catalog}: cannot validate manual overrides: {exc}")
        return report

    for key, record in sorted(records.items()):
        if key not in source:
            report.errors.append(f"{locale}/{catalog}:{key}: manual override key is not canonical")
            continue
        translation = str(record.get("translation") or "")
        expected_hash = _manifest_hash(catalog, key, source[key])
        recorded_hash = str(record.get("source_hash") or "")
        if recorded_hash and recorded_hash != expected_hash:
            report.errors.append(f"{locale}/{catalog}:{key}: manual override source hash is stale")
        if source[key].strip() and not translation.strip():
            report.errors.append(f"{locale}/{catalog}:{key}: manual override translation is empty")
        if placeholders(source[key]) != placeholders(translation):
            report.errors.append(f"{locale}/{catalog}:{key}: manual override placeholder mismatch")
        missing_terms = [term for term in protected_terms if term in source[key] and term not in translation]
        if missing_terms:
            report.errors.append(
                f"{locale}/{catalog}:{key}: manual override changed/missing protected term(s): {', '.join(missing_terms)}"
            )
        status = str(record.get("status") or "reviewed").lower()
        if status not in {"reviewed", "locked"}:
            report.errors.append(f"{locale}/{catalog}:{key}: invalid manual review status {status!r}")
        if bool(record.get("locked")) != (status == "locked"):
            report.warnings.append(
                f"{locale}/{catalog}:{key}: locked flag/status disagree; review importer will normalize them"
            )
        if key not in target:
            report.warnings.append(
                f"{locale}/{catalog}:{key}: authoritative manual override is not packaged in target locale"
            )
    return report


def validate_protected_terms(locale: str, catalog: str, source: Dict[str, str], target: Dict[str, str]) -> ValidationReport:
    report = ValidationReport()
    if locale == CANONICAL:
        return report
    try:
        try:
            from .google_translate import _protected_terms
        except ImportError:
            from google_translate import _protected_terms
        terms = _protected_terms()
    except Exception as exc:
        report.errors.append(f"{locale}/{catalog}: cannot validate protected terminology: {exc}")
        return report

    for key in sorted(set(source) & set(target)):
        src = source[key]
        dst = target[key]
        missing_terms = [term for term in terms if term in src and term not in dst]
        if missing_terms:
            report.errors.append(
                f"{locale}/{catalog}:{key}: protected term(s) changed/missing: {', '.join(missing_terms)}"
            )
    return report


def validate_locale_manifest() -> ValidationReport:
    report = ValidationReport()
    try:
        if locale_manifest_drift():
            report.errors.append("locale manifest is stale/missing; run --extract or --manifest")
    except Exception as exc:
        report.errors.append(f"locale manifest validation failed: {exc}")
    return report


def _read_content(name: str) -> dict:
    path = CONTENT_ROOT / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return raw


def _semantic_catalogs(report: ValidationReport) -> tuple[dict[str, str], dict[str, str]]:
    """Validate locale-neutral documentation topology and return flattened source."""
    help_strings: dict[str, str] = {}
    glossary_strings: dict[str, str] = {}

    try:
        glossary = _read_content("glossary")
        terms = glossary.get("terms")
        if not isinstance(terms, list):
            raise ValueError("'terms' must be a list")
    except Exception as exc:
        report.errors.append(f"semantic/glossary: {exc}")
        terms = []

    term_ids: set[str] = set()
    for index, term in enumerate(terms):
        if not isinstance(term, dict):
            report.errors.append(f"semantic/glossary: term #{index} is not an object")
            continue
        term_id = str(term.get("id", "")).strip()
        if not term_id:
            report.errors.append(f"semantic/glossary: term #{index} has no stable id")
            continue
        if term_id in term_ids:
            report.errors.append(f"semantic/glossary: duplicate term id {term_id!r}")
            continue
        term_ids.add(term_id)
        title = str(term.get("title", ""))
        body = str(term.get("body", ""))
        if not title.strip():
            report.errors.append(f"semantic/glossary:{term_id}: empty canonical title")
        if not body.strip():
            report.errors.append(f"semantic/glossary:{term_id}: empty canonical body")
        glossary_strings[f"term.{term_id}.title"] = title
        glossary_strings[f"term.{term_id}.body"] = body

    try:
        help_doc = _read_content("help")
        topics = help_doc.get("topics")
        if not isinstance(topics, list):
            raise ValueError("'topics' must be a list")
    except Exception as exc:
        report.errors.append(f"semantic/help: {exc}")
        topics = []

    topic_ids: set[str] = set()
    for topic_index, topic in enumerate(topics):
        if not isinstance(topic, dict):
            report.errors.append(f"semantic/help: topic #{topic_index} is not an object")
            continue
        topic_id = str(topic.get("id", "")).strip()
        if not topic_id:
            report.errors.append(f"semantic/help: topic #{topic_index} has no stable id")
            continue
        if topic_id in topic_ids:
            report.errors.append(f"semantic/help: duplicate topic id {topic_id!r}")
            continue
        topic_ids.add(topic_id)
        title = str(topic.get("title", ""))
        summary = str(topic.get("summary", ""))
        if not title.strip():
            report.errors.append(f"semantic/help:{topic_id}: empty canonical title")
        if not summary.strip():
            report.errors.append(f"semantic/help:{topic_id}: empty canonical summary")
        help_strings[f"topic.{topic_id}.title"] = title
        help_strings[f"topic.{topic_id}.summary"] = summary

        sections = topic.get("sections")
        if not isinstance(sections, list):
            report.errors.append(f"semantic/help:{topic_id}: sections must be a list")
            sections = []
        section_ids: set[str] = set()
        for section_index, section in enumerate(sections):
            if not isinstance(section, dict):
                report.errors.append(
                    f"semantic/help:{topic_id}: section #{section_index} is not an object"
                )
                continue
            section_id = str(section.get("id", "")).strip()
            if not section_id:
                report.errors.append(
                    f"semantic/help:{topic_id}: section #{section_index} has no stable id"
                )
                continue
            if section_id in section_ids:
                report.errors.append(
                    f"semantic/help:{topic_id}: duplicate section id {section_id!r}"
                )
                continue
            section_ids.add(section_id)
            section_title = str(section.get("title", ""))
            section_body = str(section.get("body", ""))
            if not section_title.strip():
                report.errors.append(
                    f"semantic/help:{topic_id}/{section_id}: empty canonical title"
                )
            if not section_body.strip():
                report.errors.append(
                    f"semantic/help:{topic_id}/{section_id}: empty canonical body"
                )
            prefix = f"topic.{topic_id}.section.{section_id}"
            help_strings[f"{prefix}.title"] = section_title
            help_strings[f"{prefix}.body"] = section_body

        related = topic.get("related_terms", ())
        if not isinstance(related, list):
            report.errors.append(f"semantic/help:{topic_id}: related_terms must be a list")
            related = []
        seen_related: set[str] = set()
        for raw_term in related:
            term_id = str(raw_term)
            if term_id in seen_related:
                report.warnings.append(
                    f"semantic/help:{topic_id}: duplicate related term {term_id!r}"
                )
            seen_related.add(term_id)
            if term_id not in term_ids:
                report.errors.append(
                    f"semantic/help:{topic_id}: related glossary id {term_id!r} does not exist"
                )

    return help_strings, glossary_strings


def validate_document_structure() -> ValidationReport:
    report = ValidationReport()
    help_source, glossary_source = _semantic_catalogs(report)
    for name, expected in (("help", help_source), ("glossary", glossary_source)):
        try:
            canonical = load_catalog(CANONICAL, name)
        except Exception as exc:
            report.errors.append(f"{CANONICAL}/{name}: {exc}")
            continue
        missing = sorted(set(expected) - set(canonical))
        stale = sorted(set(canonical) - set(expected))
        changed = sorted(key for key in set(expected) & set(canonical) if expected[key] != canonical[key])
        if missing:
            report.errors.append(
                f"{CANONICAL}/{name}: {len(missing)} key(s) missing from generated canonical catalog; run --extract"
            )
        if stale:
            report.errors.append(
                f"{CANONICAL}/{name}: {len(stale)} stale key(s) not present in semantic source; run --extract"
            )
        if changed:
            report.errors.append(
                f"{CANONICAL}/{name}: {len(changed)} value(s) differ from semantic source; run --extract"
            )
    return report


def validate_locale(locale: str, *, strict_missing: bool = False) -> ValidationReport:
    report = ValidationReport()
    for catalog in CATALOGS:
        try:
            source = load_catalog(CANONICAL, catalog)
        except Exception as exc:
            report.errors.append(f"{CANONICAL}/{catalog}: {exc}")
            continue
        try:
            target = load_catalog(locale, catalog)
        except Exception as exc:
            report.errors.append(f"{locale}/{catalog}: {exc}")
            continue

        metadata = validate_catalog_metadata(locale, catalog, target)
        report.errors.extend(metadata.errors)
        report.warnings.extend(metadata.warnings)

        missing = sorted(set(source) - set(target))
        stale = sorted(set(target) - set(source))
        if missing:
            message = f"{locale}/{catalog}: {len(missing)} missing key(s); runtime will use en-AU fallback"
            (report.errors if strict_missing else report.warnings).append(message)
        if stale:
            report.warnings.append(f"{locale}/{catalog}: {len(stale)} stale/unknown key(s)")

        for key in sorted(set(source) & set(target)):
            src_placeholders = placeholders(source[key])
            dst_placeholders = placeholders(target[key])
            if src_placeholders != dst_placeholders:
                report.errors.append(
                    f"{locale}/{catalog}:{key}: placeholder mismatch "
                    f"source={sorted(src_placeholders)} target={sorted(dst_placeholders)}"
                )
            if not target[key].strip() and source[key].strip():
                message = f"{locale}/{catalog}:{key}: empty translation"
                (report.errors if strict_missing else report.warnings).append(message)

        freshness = validate_translation_freshness(locale, catalog, source, target)
        report.errors.extend(freshness.errors)
        report.warnings.extend(freshness.warnings)
        protected = validate_protected_terms(locale, catalog, source, target)
        report.errors.extend(protected.errors)
        report.warnings.extend(protected.warnings)
        manual = validate_manual_overrides(locale, catalog, source, target)
        report.errors.extend(manual.errors)
        report.warnings.extend(manual.warnings)
    return report


def supported_locales() -> list[str]:
    return sorted(path.name for path in LOCALE_ROOT.iterdir() if path.is_dir())


def validate_extraction_sources() -> ValidationReport:
    """Validate that generated canonical catalogs match authoritative source."""
    report = ValidationReport()
    try:
        try:
            from .extract_strings import extract_records, extraction_drift
        except ImportError:
            from extract_strings import extract_records, extraction_drift
        result = extract_records()
    except Exception as exc:
        report.errors.append(f"extraction: {exc}")
        return report

    if result.dynamic_calls:
        locations = ", ".join(
            f"{item.path}:{item.line}" for item in result.dynamic_calls[:8]
        )
        suffix = " ..." if len(result.dynamic_calls) > 8 else ""
        report.errors.append(
            f"extraction: {len(result.dynamic_calls)} dynamic direct tr() call(s) are not "
            f"extractable: {locations}{suffix}"
        )

    malformed = [
        f"{catalog}:{key}"
        for catalog, entries in result.catalogs.items()
        for key, entry in entries.items()
        if entry.placeholders.malformed
    ]
    if malformed:
        report.errors.append(
            f"extraction: {len(malformed)} malformed canonical format string(s): "
            + ", ".join(malformed[:8])
            + (" ..." if len(malformed) > 8 else "")
        )

    drift = extraction_drift(result)
    if drift:
        report.errors.append(
            "extraction: generated canonical localization files are stale; run --extract: "
            + ", ".join(drift)
        )
    return report


def validate_all(
    *,
    strict_missing: bool = False,
    locales: Iterable[str] | None = None,
) -> ValidationReport:
    combined = validate_extraction_sources()
    manifest_report = validate_locale_manifest()
    combined.errors.extend(manifest_report.errors)
    combined.warnings.extend(manifest_report.warnings)
    document_report = validate_document_structure()
    combined.errors.extend(document_report.errors)
    combined.warnings.extend(document_report.warnings)
    selected = list(locales or supported_locales())
    for locale in selected:
        report = validate_locale(locale, strict_missing=strict_missing)
        combined.errors.extend(report.errors)
        combined.warnings.extend(report.warnings)
    return combined


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", action="append", dest="locales")
    parser.add_argument("--strict", action="store_true", help="Treat missing translations as errors")
    args = parser.parse_args(argv)
    report = validate_all(strict_missing=args.strict, locales=args.locales)
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    for error in report.errors:
        print(f"ERROR: {error}")
    print(
        f"Validation: {'OK' if report.ok else 'FAILED'} "
        f"({len(report.errors)} error(s), {len(report.warnings)} warning(s))"
    )
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
