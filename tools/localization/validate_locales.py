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

ROOT = Path(__file__).resolve().parents[2]
LOCALE_ROOT = ROOT / "app" / "localization" / "locales"
CONTENT_ROOT = ROOT / "app" / "localization" / "content"
CANONICAL = "en-AU"
CATALOGS = ("ui", "help", "glossary")


def placeholders(text: str) -> set[str]:
    """Compatibility alias for the shared Stage-4 placeholder contract."""
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
