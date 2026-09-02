"""Offline translation review/provenance tooling for SalixTorrent.

Translation review deliberately separates *review state* from the translation provider.
Machine/provider output, seeded translations, and human-reviewed overrides all
flow through one deterministic report/export/import contract.  Runtime locale
files remain ordinary JSON and SalixTorrent never needs this module at runtime.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Dict, Iterable, Mapping

try:
    from .contracts import placeholder_names
    from .google_translate import (
        CATALOGS,
        LOCALE_ROOT,
        MANIFEST_PATH,
        OVERRIDES_ROOT,
        SOURCE_LOCALE,
        TARGET_CODES,
        _cache_entry,
        _catalog_strings,
        _load_cache,
        _load_json,
        _manifest_hash,
        _manual_override_records,
        _protected_terms,
        _validate_final,
    )
except ImportError:  # direct script execution
    from contracts import placeholder_names
    from google_translate import (
        CATALOGS,
        LOCALE_ROOT,
        MANIFEST_PATH,
        OVERRIDES_ROOT,
        SOURCE_LOCALE,
        TARGET_CODES,
        _cache_entry,
        _catalog_strings,
        _load_cache,
        _load_json,
        _manifest_hash,
        _manual_override_records,
        _protected_terms,
        _validate_final,
    )


TOOLS_ROOT = Path(__file__).resolve().parent
REVIEW_EXPORT_ROOT = TOOLS_ROOT / "review_exports"
REVIEW_EXPORT_SCHEMA = 1
MANUAL_OVERRIDE_SCHEMA = 1
REVIEW_STATES = ("pending", "reviewed", "locked")
ENTRY_STATUSES = ("missing", "review-needed", "reviewed", "locked", "stale", "invalid")


@dataclass(frozen=True)
class ReviewEntry:
    locale: str
    catalog: str
    key: str
    source: str
    source_hash: str
    translation: str
    status: str
    provenance: str
    provider: str = ""
    model: str = ""
    placeholders: tuple[str, ...] = ()
    occurrences: tuple[Mapping[str, object], ...] = ()
    reviewer: str = ""
    note: str = ""
    reviewed_at: str = ""
    locked: bool = False
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewSummary:
    locale: str
    total: int
    missing: int
    review_needed: int
    reviewed: int
    locked: int
    stale: int
    invalid: int

    @property
    def review_complete(self) -> bool:
        return self.total > 0 and self.missing == 0 and self.review_needed == 0 and self.stale == 0 and self.invalid == 0

    @property
    def infrastructure_ok(self) -> bool:
        return self.stale == 0 and self.invalid == 0

    def as_dict(self) -> dict[str, int | str | bool]:
        return {
            "locale": self.locale,
            "total": self.total,
            "missing": self.missing,
            "review_needed": self.review_needed,
            "reviewed": self.reviewed,
            "locked": self.locked,
            "stale": self.stale,
            "invalid": self.invalid,
            "review_complete": self.review_complete,
            "infrastructure_ok": self.infrastructure_ok,
        }


@dataclass
class ReviewAudit:
    summaries: list[ReviewSummary] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ReviewImportResult:
    locale: str
    reviewed: int
    locked: int
    unchanged: int
    output_path: Path


class ReviewImportError(ValueError):
    """Raised when a review bundle cannot be safely promoted."""


def _manifest() -> dict:
    raw = _load_json(MANIFEST_PATH, {})
    return raw if isinstance(raw, dict) else {}


def _entry_metadata(catalog: str, key: str) -> dict:
    manifest = _manifest()
    try:
        value = manifest["catalogs"][catalog]["entries"][key]
    except (KeyError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _translation_contract_issues(
    source: str,
    translation: str,
    *,
    protected_terms: Iterable[str] | None = None,
) -> list[str]:
    issues: list[str] = []
    try:
        _validate_final("review", "review", "entry", source, translation)
    except ValueError as exc:
        issues.append(str(exc))
    terms = protected_terms if protected_terms is not None else _protected_terms()
    for term in terms:
        if term in source and term not in translation:
            issues.append(f"protected term missing/changed: {term}")
    return issues


def _override_status(record: Mapping[str, object]) -> str:
    if bool(record.get("locked")) or str(record.get("status") or "").lower() == "locked":
        return "locked"
    return "reviewed"


def review_entries(locale: str) -> tuple[ReviewEntry, ...]:
    """Return deterministic review state for every canonical entry."""
    if locale not in TARGET_CODES:
        raise ValueError(f"Unsupported review locale {locale!r}")

    cache = _load_cache()
    override_records = _manual_override_records(locale)
    manifest = _manifest()
    protected_terms = _protected_terms()
    rows: list[ReviewEntry] = []

    for catalog in CATALOGS:
        source = _catalog_strings(SOURCE_LOCALE, catalog)
        target = _catalog_strings(locale, catalog)
        records = override_records.get(catalog, {})

        for key in sorted(source):
            source_text = source[key]
            try:
                meta = manifest["catalogs"][catalog]["entries"][key]
            except (KeyError, TypeError):
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            expected_hash = str(meta.get("source_hash") or _manifest_hash(catalog, key, source_text))
            occurrences = meta.get("occurrences", ())
            if not isinstance(occurrences, list):
                occurrences = []

            translation = ""
            status = "missing"
            provenance = "none"
            provider = ""
            model = ""
            reviewer = ""
            note = ""
            reviewed_at = ""
            locked = False
            issues: list[str] = []

            override = records.get(key)
            if isinstance(override, dict):
                translation = str(override.get("translation") or "")
                provenance = "manual-override"
                locked = bool(override.get("locked")) or str(override.get("status") or "").lower() == "locked"
                reviewer = str(override.get("reviewer") or "")
                note = str(override.get("note") or override.get("review_note") or "")
                reviewed_at = str(override.get("reviewed_at") or "")
                recorded_hash = str(override.get("source_hash") or "")
                if recorded_hash and recorded_hash != expected_hash:
                    status = "stale"
                    issues.append("manual override source hash is stale")
                else:
                    status = _override_status(override)
                    if not recorded_hash:
                        # Legacy manual overrides remain authoritative for
                        # compatibility, but the review report makes the lack of
                        # freshness provenance visible until re-imported.
                        issues.append("manual override has no source-hash provenance")
                issues.extend(_translation_contract_issues(source_text, translation, protected_terms=protected_terms))
                if any("placeholders" in issue or "empty" in issue or "protected term" in issue for issue in issues):
                    status = "invalid"
            else:
                translation = str(target.get(key) or "")
                if translation:
                    cache_entry = _cache_entry(cache, locale, catalog, key)
                    recorded_hash = str(cache_entry.get("source_hash") or "")
                    if recorded_hash and recorded_hash != expected_hash:
                        status = "stale"
                        provenance = str(cache_entry.get("status") or "cache")
                        issues.append("packaged translation source hash is stale")
                    else:
                        status = "review-needed"
                        if cache_entry:
                            provenance = str(cache_entry.get("status") or "cache")
                            provider = str(cache_entry.get("provider") or "")
                            model = str(cache_entry.get("model") or "")
                            cached_translation = cache_entry.get("translation")
                            if isinstance(cached_translation, str) and cached_translation != translation:
                                issues.append("packaged translation differs from hash-valid cache")
                        else:
                            provenance = "packaged-unprovenanced"
                    issues.extend(_translation_contract_issues(source_text, translation, protected_terms=protected_terms))
                    if any("placeholders" in issue or "empty" in issue or "protected term" in issue for issue in issues):
                        status = "invalid"

            rows.append(
                ReviewEntry(
                    locale=locale,
                    catalog=catalog,
                    key=key,
                    source=source_text,
                    source_hash=expected_hash,
                    translation=translation,
                    status=status,
                    provenance=provenance,
                    provider=provider,
                    model=model,
                    placeholders=tuple(sorted(placeholder_names(source_text))),
                    occurrences=tuple(copy.deepcopy(occurrences)),
                    reviewer=reviewer,
                    note=note,
                    reviewed_at=reviewed_at,
                    locked=locked,
                    issues=tuple(issues),
                )
            )
    return tuple(rows)


def review_summary(locale: str) -> ReviewSummary:
    rows = review_entries(locale)
    counts = {status: 0 for status in ENTRY_STATUSES}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return ReviewSummary(
        locale=locale,
        total=len(rows),
        missing=counts["missing"],
        review_needed=counts["review-needed"],
        reviewed=counts["reviewed"],
        locked=counts["locked"],
        stale=counts["stale"],
        invalid=counts["invalid"],
    )


def review_audit(locales: Iterable[str] | None = None) -> ReviewAudit:
    selected = list(locales or sorted(TARGET_CODES))
    audit = ReviewAudit()
    for locale in selected:
        override_path = OVERRIDES_ROOT / f"{locale}.json"
        raw_override = _load_json(override_path, {})
        if not isinstance(raw_override, dict):
            audit.errors.append(f"{locale}: manual override file must be a JSON object")
        else:
            meta = raw_override.get("_meta")
            if not isinstance(meta, dict):
                audit.warnings.append(f"{locale}: manual override file uses legacy metadata-less schema")
            else:
                try:
                    schema = int(meta.get("schema") or 0)
                except (TypeError, ValueError):
                    schema = 0
                expected = {
                    "schema": MANUAL_OVERRIDE_SCHEMA,
                    "kind": "salix-manual-overrides",
                    "locale": locale,
                    "source_locale": SOURCE_LOCALE,
                }
                actual = {
                    "schema": schema,
                    "kind": meta.get("kind"),
                    "locale": meta.get("locale"),
                    "source_locale": meta.get("source_locale"),
                }
                if actual != expected:
                    audit.errors.append(f"{locale}: manual override metadata is invalid/stale")

        try:
            summary = review_summary(locale)
        except Exception as exc:
            audit.errors.append(f"{locale}: review state could not be built: {exc}")
            continue
        audit.summaries.append(summary)
        if summary.stale:
            audit.errors.append(f"{locale}: {summary.stale} stale review/translation entr{'y' if summary.stale == 1 else 'ies'}")
        if summary.invalid:
            audit.errors.append(f"{locale}: {summary.invalid} invalid review/translation entr{'y' if summary.invalid == 1 else 'ies'}")
        if summary.missing or summary.review_needed:
            audit.warnings.append(
                f"{locale}: review incomplete ({summary.missing} missing, {summary.review_needed} awaiting review)"
            )
    return audit


def build_review_bundle(locale: str) -> dict:
    rows = review_entries(locale)
    catalogs: dict[str, dict[str, dict]] = {catalog: {} for catalog in CATALOGS}
    for row in rows:
        review_state = row.status if row.status in {"reviewed", "locked"} else "pending"
        catalogs[row.catalog][row.key] = {
            "source": row.source,
            "source_hash": row.source_hash,
            "translation": row.translation,
            "current_status": row.status,
            "review_state": review_state,
            "provenance": row.provenance,
            "provider": row.provider,
            "model": row.model,
            "placeholders": list(row.placeholders),
            "occurrences": [dict(item) for item in row.occurrences],
            "reviewer": row.reviewer,
            "note": row.note,
            "reviewed_at": row.reviewed_at,
            "issues": list(row.issues),
        }
    summary = review_summary(locale)
    return {
        "_meta": {
            "schema": REVIEW_EXPORT_SCHEMA,
            "kind": "salix-translation-review",
            "locale": locale,
            "source_locale": SOURCE_LOCALE,
            "canonical_entries": len(rows),
            "instructions": (
                "Edit translation and set review_state to reviewed or locked only after human review. "
                "Leave pending entries unchanged. Do not edit source/source_hash/catalog keys."
            ),
        },
        "summary": summary.as_dict(),
        "catalogs": catalogs,
    }


def _json_payload(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export_review(locale: str, path: Path | str | None = None) -> Path:
    if locale not in TARGET_CODES:
        raise ValueError(f"Unsupported review locale {locale!r}")
    output = Path(path) if path is not None else REVIEW_EXPORT_ROOT / f"{locale}.review.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(_json_payload(build_review_bundle(locale)), encoding="utf-8")
    os.replace(temporary, output)
    return output


def _load_review_bundle(path: Path | str) -> dict:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReviewImportError(f"Cannot read review bundle {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewImportError(f"Review bundle is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReviewImportError("Review bundle root must be an object")
    return raw


def _normalise_override_file(locale: str, raw: object) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    result = copy.deepcopy(raw)
    result["_meta"] = {
        "schema": MANUAL_OVERRIDE_SCHEMA,
        "kind": "salix-manual-overrides",
        "locale": locale,
        "source_locale": SOURCE_LOCALE,
    }
    for catalog in CATALOGS:
        if not isinstance(result.get(catalog), dict):
            result[catalog] = {}
    return result


def _target_payload(locale: str, catalog: str) -> dict:
    path = LOCALE_ROOT / locale / f"{catalog}.json"
    raw = _load_json(path, {})
    if not isinstance(raw, dict):
        raw = {}
    meta = raw.get("_meta") if isinstance(raw.get("_meta"), dict) else {}
    strings = raw.get("strings") if isinstance(raw.get("strings"), dict) else {}
    return {
        "_meta": {
            **meta,
            "locale": locale,
            "source_locale": SOURCE_LOCALE,
            "catalog": catalog,
        },
        "strings": {str(k): str(v) for k, v in strings.items() if isinstance(v, str)},
    }


def _write_atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(_json_payload(value), encoding="utf-8")
    os.replace(temporary, path)


def import_review(path: Path | str, *, now: datetime | None = None) -> ReviewImportResult:
    """Promote reviewed/locked bundle entries into authoritative overrides.

    The complete bundle is validated before any file is changed.  Pending rows
    are ignored.  Accepted rows update the packaged locale first and the manual
    override file last so an interrupted import can never create an authoritative
    override that runtime has not yet received.
    """
    bundle = _load_review_bundle(path)
    meta = bundle.get("_meta")
    if not isinstance(meta, dict):
        raise ReviewImportError("Review bundle is missing _meta")
    try:
        schema = int(meta.get("schema") or 0)
    except (TypeError, ValueError):
        schema = 0
    if meta.get("kind") != "salix-translation-review" or schema != REVIEW_EXPORT_SCHEMA:
        raise ReviewImportError("Unsupported review bundle schema/kind")
    locale = str(meta.get("locale") or "")
    if locale not in TARGET_CODES:
        raise ReviewImportError(f"Unsupported review locale {locale!r}")
    if meta.get("source_locale") != SOURCE_LOCALE:
        raise ReviewImportError("Review bundle source locale does not match canonical locale")

    catalogs = bundle.get("catalogs")
    if not isinstance(catalogs, dict):
        raise ReviewImportError("Review bundle is missing catalogs")

    accepted: list[tuple[str, str, str, str, str, str, bool]] = []
    unchanged = 0
    errors: list[str] = []
    protected_terms = _protected_terms()
    manifest = _manifest()

    unknown_catalogs = sorted(set(catalogs) - set(CATALOGS))
    for catalog in unknown_catalogs:
        errors.append(f"Unknown review catalog {catalog!r}")

    for catalog in CATALOGS:
        values = catalogs.get(catalog)
        if not isinstance(values, dict):
            errors.append(f"{catalog}: review entries must be an object")
            continue
        canonical = _catalog_strings(SOURCE_LOCALE, catalog)
        missing_keys = sorted(set(canonical) - set(values))
        unknown_keys = sorted(set(values) - set(canonical))
        if missing_keys:
            errors.append(f"{catalog}: review bundle is missing {len(missing_keys)} canonical key(s)")
        if unknown_keys:
            errors.append(f"{catalog}: review bundle contains {len(unknown_keys)} stale/unknown key(s)")

        for key in sorted(set(values) & set(canonical)):
            record = values[key]
            if not isinstance(record, dict):
                errors.append(f"{catalog}:{key}: review entry must be an object")
                continue
            state = str(record.get("review_state") or "pending").strip().lower()
            if state not in REVIEW_STATES:
                errors.append(f"{catalog}:{key}: invalid review_state {state!r}")
                continue

            source_text = canonical[key]
            try:
                meta_entry = manifest["catalogs"][catalog]["entries"][key]
                expected_hash = str(meta_entry.get("source_hash") or "")
            except (KeyError, TypeError, AttributeError):
                expected_hash = _manifest_hash(catalog, key, source_text)
            supplied_hash = str(record.get("source_hash") or "")
            supplied_source = str(record.get("source") or "")
            if supplied_hash != expected_hash:
                errors.append(f"{catalog}:{key}: source hash changed since review export")
                continue
            if supplied_source != source_text:
                errors.append(f"{catalog}:{key}: canonical source text was edited in review bundle")
                continue

            if state == "pending":
                unchanged += 1
                continue

            translation = str(record.get("translation") or "")
            contract_issues = _translation_contract_issues(source_text, translation, protected_terms=protected_terms)
            if contract_issues:
                errors.extend(f"{catalog}:{key}: {issue}" for issue in contract_issues)
                continue
            reviewer = str(record.get("reviewer") or "").strip()
            note = str(record.get("note") or "").strip()
            accepted.append((catalog, str(key), translation, expected_hash, reviewer, note, state == "locked"))

    if errors:
        raise ReviewImportError("Review import refused:\n  " + "\n  ".join(errors))

    override_path = OVERRIDES_ROOT / f"{locale}.json"
    override_raw = _load_json(override_path, {})
    override_payload = _normalise_override_file(locale, override_raw)
    target_payloads = {catalog: _target_payload(locale, catalog) for catalog in CATALOGS}

    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    reviewed_count = 0
    locked_count = 0
    for catalog, key, translation, source_hash, reviewer, note, locked in accepted:
        state = "locked" if locked else "reviewed"
        override_payload[catalog][key] = {
            "translation": translation,
            "source_hash": source_hash,
            "status": state,
            "locked": locked,
            "reviewer": reviewer,
            "note": note,
            "reviewed_at": stamp,
        }
        target_payloads[catalog]["strings"][key] = translation
        if locked:
            locked_count += 1
        else:
            reviewed_count += 1

    # Commit runtime-facing files first, then the authoritative override ledger.
    for catalog in CATALOGS:
        target_payloads[catalog]["strings"] = dict(sorted(target_payloads[catalog]["strings"].items()))
        _write_atomic_json(LOCALE_ROOT / locale / f"{catalog}.json", target_payloads[catalog])
    _write_atomic_json(override_path, override_payload)

    return ReviewImportResult(
        locale=locale,
        reviewed=reviewed_count,
        locked=locked_count,
        unchanged=unchanged,
        output_path=override_path,
    )
