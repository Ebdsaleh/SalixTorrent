"""Phase-12 Stage-7 localization hardening helpers.

All functions here are development/build-time only and perform no network I/O.
They make locale packaging deterministic, expose script/direction metadata,
exercise the pseudo-locale contract, and verify that frozen-build resources are
actually declared in the PyInstaller specification.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.localization.locale_info import (
    CANONICAL_LOCALE,
    PSEUDO_LOCALE_INFO,
    SUPPORTED_LOCALES,
)
from app.localization.pseudo import PSEUDO_LOCALE, pseudo_localize

try:
    from .contracts import placeholder_names, source_hash
except ImportError:
    from contracts import placeholder_names, source_hash


LOCALE_ROOT = ROOT / "app" / "localization" / "locales"
CONTENT_ROOT = ROOT / "app" / "localization" / "content"
LOCALE_MANIFEST_PATH = LOCALE_ROOT / "manifest.json"
PACKAGING_SPEC = ROOT / "packaging" / "SalixTorrent.spec"
CATALOGS = ("ui", "help", "glossary")
MANIFEST_SCHEMA = 1


def _load_json(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected JSON object")
    return raw


def _catalog_strings(locale: str, catalog: str) -> dict[str, str]:
    path = LOCALE_ROOT / locale / f"{catalog}.json"
    raw = _load_json(path)
    values = raw.get("strings")
    if not isinstance(values, dict):
        raise ValueError(f"{path}: expected object mapping under 'strings'")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in values.items()):
        raise ValueError(f"{path}: catalog entries must map strings to strings")
    return dict(values)


def catalog_hash(strings: dict[str, str]) -> str:
    material = "\n".join(f"{key}\0{strings[key]}" for key in sorted(strings))
    return source_hash(material)


def build_locale_manifest() -> dict:
    canonical_catalogs = {name: _catalog_strings(CANONICAL_LOCALE, name) for name in CATALOGS}
    total_canonical = sum(len(values) for values in canonical_catalogs.values())
    locales: dict[str, dict] = {}

    for code, info in SUPPORTED_LOCALES.items():
        catalog_rows: dict[str, dict] = {}
        total_entries = 0
        total_missing = 0
        total_stale = 0
        for catalog in CATALOGS:
            strings = _catalog_strings(code, catalog)
            source = canonical_catalogs[catalog]
            missing = len(set(source) - set(strings))
            stale = len(set(strings) - set(source))
            total_entries += len(set(source) & set(strings))
            total_missing += missing
            total_stale += stale
            catalog_rows[catalog] = {
                "entries": len(strings),
                "canonical_entries": len(source),
                "missing": missing,
                "stale": stale,
                "catalog_hash": catalog_hash(strings),
                "canonical_hash": catalog_hash(source),
            }
        locales[code] = {
            "display_name": info.display_name,
            "native_name": info.native_name,
            "script": info.script,
            "text_direction": info.text_direction,
            "font_profile": info.font_profile,
            "support_status": info.support_status,
            "total_entries": total_entries,
            "canonical_entries": total_canonical,
            "missing_entries": total_missing,
            "stale_entries": total_stale,
            "complete": total_missing == 0 and total_stale == 0,
            "catalogs": catalog_rows,
        }

    return {
        "_meta": {
            "schema": MANIFEST_SCHEMA,
            "canonical_locale": CANONICAL_LOCALE,
            "generated_by": "tools/localization/stage7_support.py",
            "catalogs": list(CATALOGS),
        },
        "locales": locales,
        "development_locales": {
            PSEUDO_LOCALE: {
                "display_name": PSEUDO_LOCALE_INFO.display_name,
                "native_name": PSEUDO_LOCALE_INFO.native_name,
                "script": PSEUDO_LOCALE_INFO.script,
                "text_direction": PSEUDO_LOCALE_INFO.text_direction,
                "font_profile": PSEUDO_LOCALE_INFO.font_profile,
                "support_status": PSEUDO_LOCALE_INFO.support_status,
                "derived_from": CANONICAL_LOCALE,
                "packaged_catalog": False,
                "purpose": "In-memory text expansion and untranslated-string detection",
            }
        },
    }


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_locale_manifest() -> Path:
    LOCALE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCALE_MANIFEST_PATH.write_bytes(_json_bytes(build_locale_manifest()))
    return LOCALE_MANIFEST_PATH


def locale_manifest_drift() -> bool:
    expected = _json_bytes(build_locale_manifest())
    try:
        return LOCALE_MANIFEST_PATH.read_bytes() != expected
    except OSError:
        return True


@dataclass(frozen=True)
class PseudoAudit:
    entries: int
    placeholder_failures: tuple[str, ...]
    expansion_failures: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.placeholder_failures and not self.expansion_failures


def pseudo_audit() -> PseudoAudit:
    failures: list[str] = []
    expansion_failures: list[str] = []
    entries = 0
    for catalog in CATALOGS:
        source = _catalog_strings(CANONICAL_LOCALE, catalog)
        for key, text in source.items():
            entries += 1
            transformed = pseudo_localize(text)
            if placeholder_names(text) != placeholder_names(transformed):
                failures.append(f"{catalog}:{key}")
            # Very short/non-alphabetic strings are allowed to be dominated by
            # wrappers. Ordinary human text should never shrink.
            if any(char.isalpha() for char in text) and len(transformed) <= len(text):
                expansion_failures.append(f"{catalog}:{key}")
    return PseudoAudit(
        entries=entries,
        placeholder_failures=tuple(failures),
        expansion_failures=tuple(expansion_failures),
    )


@dataclass
class PackagingReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_resources: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def packaging_report(locales: Iterable[str] | None = None) -> PackagingReport:
    report = PackagingReport()
    selected = list(locales or SUPPORTED_LOCALES)

    required = [
        CONTENT_ROOT / "help.json",
        CONTENT_ROOT / "glossary.json",
        CONTENT_ROOT / "ui_static.json",
        LOCALE_MANIFEST_PATH,
    ]
    for locale in selected:
        for catalog in CATALOGS:
            required.append(LOCALE_ROOT / locale / f"{catalog}.json")

    for path in required:
        report.checked_resources += 1
        if not path.is_file():
            report.errors.append(f"Missing runtime localization resource: {path.relative_to(ROOT)}")
            continue
        try:
            if path.suffix == ".json":
                _load_json(path)
        except Exception as exc:
            report.errors.append(f"Invalid runtime localization resource {path.relative_to(ROOT)}: {exc}")

    try:
        spec = PACKAGING_SPEC.read_text(encoding="utf-8")
    except OSError as exc:
        report.errors.append(f"Cannot read PyInstaller spec: {exc}")
        return report

    contracts = (
        ('"app" / "localization" / "locales"', '"app/localization/locales"'),
        ('"app" / "localization" / "content"', '"app/localization/content"'),
    )
    for source_fragment, target_fragment in contracts:
        if source_fragment not in spec or target_fragment not in spec:
            report.errors.append(
                f"PyInstaller spec does not bundle localization contract {source_fragment} -> {target_fragment}"
            )

    if locale_manifest_drift():
        report.errors.append("Locale manifest is stale; run --extract or --manifest")
    return report
