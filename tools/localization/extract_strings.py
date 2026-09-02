"""Extract SalixTorrent's canonical en-AU localization catalogs.

Localization extraction is reproducible and auditable. Only explicit literal
``tr(key, source_text, ...)`` calls, renderer-neutral semantic Help/Glossary
sources, stable presentation-value sources, and the explicit ``ui_static``
source are included. Arbitrary Python string literals are never translated.
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Mapping, Tuple

try:
    from .contracts import placeholder_contract, source_hash
except ImportError:  # direct script execution
    from contracts import placeholder_contract, source_hash


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LOCALE_ROOT = ROOT / "app" / "localization" / "locales"
CONTENT_ROOT = ROOT / "app" / "localization" / "content"
TOOLS_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = TOOLS_ROOT / "extraction_manifest.json"
CANONICAL = "en-AU"
CATALOGS = ("ui", "help", "glossary")


class ExtractionError(ValueError):
    """Raised when canonical localization source cannot be extracted safely."""


@dataclass(frozen=True)
class SourceOccurrence:
    path: str
    line: int
    column: int
    kind: str = "python-tr"

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
        }


@dataclass
class ExtractedEntry:
    key: str
    text: str
    occurrences: list[SourceOccurrence] = field(default_factory=list)

    @property
    def hash(self) -> str:
        return source_hash(self.text)

    @property
    def placeholders(self):
        return placeholder_contract(self.text)

    def as_manifest_dict(self) -> dict:
        contract = self.placeholders
        return {
            "source_hash": self.hash,
            "placeholders": list(contract.names),
            "format_fields": list(contract.fields),
            "malformed_format": bool(contract.malformed),
            "occurrences": [occ.as_dict() for occ in self.occurrences],
        }


@dataclass
class ExtractionResult:
    catalogs: dict[str, dict[str, ExtractedEntry]]
    dynamic_calls: list[SourceOccurrence] = field(default_factory=list)

    @property
    def duplicate_keys(self) -> dict[str, dict[str, list[SourceOccurrence]]]:
        result: dict[str, dict[str, list[SourceOccurrence]]] = {}
        for catalog, entries in self.catalogs.items():
            duplicates = {
                key: entry.occurrences
                for key, entry in entries.items()
                if len(entry.occurrences) > 1
            }
            if duplicates:
                result[catalog] = duplicates
        return result


def _literal_string(node: ast.AST) -> str | None:
    try:
        value = ast.literal_eval(node)
    except Exception:
        return None
    return value if isinstance(value, str) else None


def _render_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _occurrence(path: Path, node: ast.AST, *, kind: str = "python-tr") -> SourceOccurrence:
    return SourceOccurrence(
        path=_render_path(path),
        line=int(getattr(node, "lineno", 0) or 0),
        column=int(getattr(node, "col_offset", 0) or 0) + 1,
        kind=kind,
    )


def _merge_entry(
    entries: dict[str, ExtractedEntry],
    key: str,
    text: str,
    occurrence: SourceOccurrence,
    *,
    catalog: str,
) -> None:
    previous = entries.get(key)
    if previous is not None:
        if previous.text != text:
            previous_locations = ", ".join(
                f"{item.path}:{item.line}" for item in previous.occurrences
            ) or "unknown source"
            raise ExtractionError(
                f"{catalog}: localization key {key!r} has conflicting canonical text:\n"
                f"  existing {previous.text!r} at {previous_locations}\n"
                f"  new      {text!r} at {occurrence.path}:{occurrence.line}"
            )
        previous.occurrences.append(occurrence)
        return
    entries[key] = ExtractedEntry(key=key, text=text, occurrences=[occurrence])


def extract_python_ui_records(paths: Iterable[Path]) -> tuple[dict[str, ExtractedEntry], list[SourceOccurrence]]:
    """Extract literal direct ``tr()`` calls and report dynamic direct calls.

    Attribute calls such as ``manager.tr(...)`` are runtime localization
    internals and are not source declarations. Direct dynamic ``tr()`` calls
    are surfaced rather than silently ignored so developers can ensure those
    strings have another authoritative extraction source.
    """
    entries: dict[str, ExtractedEntry] = {}
    dynamic_calls: list[SourceOccurrence] = []

    for path in sorted((Path(p) for p in paths), key=lambda p: p.as_posix().lower()):
        try:
            source_text = path.read_text(encoding="utf-8")
            tree = ast.parse(source_text, filename=str(path))
        except OSError as exc:
            raise ExtractionError(f"Could not read {path}: {exc}") from exc
        except SyntaxError as exc:
            raise ExtractionError(f"Could not parse {path}:{exc.lineno}: {exc.msg}") from exc

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Only direct tr(...) calls declare canonical UI source. Calls on
            # LocalizationManager are runtime consumers, not extraction sites.
            if not isinstance(node.func, ast.Name) or node.func.id != "tr":
                continue
            occurrence = _occurrence(path, node)
            if len(node.args) < 2:
                dynamic_calls.append(occurrence)
                continue
            key = _literal_string(node.args[0])
            text = _literal_string(node.args[1])
            if not key or text is None:
                dynamic_calls.append(occurrence)
                continue
            _merge_entry(entries, key, text, occurrence, catalog="ui")

    return entries, dynamic_calls


def extract_python_ui_strings(paths: Iterable[Path]) -> Tuple[Dict[str, str], Dict[str, list[str]]]:
    """Compatibility wrapper returning the original public tuple shape."""
    records, _dynamic = extract_python_ui_records(paths)
    strings = {key: entry.text for key, entry in records.items()}
    sources = {
        key: [f"{occ.path}:{occ.line}" for occ in entry.occurrences]
        for key, entry in records.items()
    }
    return strings, sources


def _read_semantic_source(name: str) -> dict:
    path = CONTENT_ROOT / f"{name}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"{path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ExtractionError(f"{path}: expected a JSON object")
    return raw


def _semantic_occurrence(name: str, stable_id: str) -> SourceOccurrence:
    return SourceOccurrence(
        path=f"app/localization/content/{name}.json",
        line=0,
        column=0,
        kind=f"semantic-{name}:{stable_id}",
    )


def extract_help_records() -> dict[str, ExtractedEntry]:
    path = CONTENT_ROOT / "help.json"
    raw = _read_semantic_source("help")
    topics = raw.get("topics")
    if not isinstance(topics, list):
        raise ExtractionError(f"{path}: 'topics' must be a list")

    entries: dict[str, ExtractedEntry] = {}
    topic_ids: set[str] = set()
    for topic in topics:
        if not isinstance(topic, dict):
            raise ExtractionError(f"{path}: Help topic must be an object")
        topic_id = str(topic.get("id", "")).strip()
        if not topic_id:
            raise ExtractionError(f"{path}: Help topic is missing an id")
        if topic_id in topic_ids:
            raise ExtractionError(f"{path}: duplicate Help topic id {topic_id!r}")
        topic_ids.add(topic_id)
        for suffix, value in (("title", topic.get("title", "")), ("summary", topic.get("summary", ""))):
            key = f"topic.{topic_id}.{suffix}"
            _merge_entry(
                entries,
                key,
                str(value),
                _semantic_occurrence("help", topic_id),
                catalog="help",
            )

        sections = topic.get("sections", ())
        if not isinstance(sections, list):
            raise ExtractionError(f"{path}: topic {topic_id!r} sections must be a list")
        section_ids: set[str] = set()
        for section in sections:
            if not isinstance(section, dict):
                raise ExtractionError(f"{path}: topic {topic_id!r} section must be an object")
            section_id = str(section.get("id", "")).strip()
            if not section_id:
                raise ExtractionError(f"{path}: topic {topic_id!r} section is missing an id")
            if section_id in section_ids:
                raise ExtractionError(
                    f"{path}: topic {topic_id!r} has duplicate section id {section_id!r}"
                )
            section_ids.add(section_id)
            prefix = f"topic.{topic_id}.section.{section_id}"
            for suffix, value in (("title", section.get("title", "")), ("body", section.get("body", ""))):
                _merge_entry(
                    entries,
                    f"{prefix}.{suffix}",
                    str(value),
                    _semantic_occurrence("help", f"{topic_id}/{section_id}"),
                    catalog="help",
                )
    return entries


def extract_help_strings() -> Dict[str, str]:
    return {key: entry.text for key, entry in extract_help_records().items()}


def extract_glossary_records() -> dict[str, ExtractedEntry]:
    path = CONTENT_ROOT / "glossary.json"
    raw = _read_semantic_source("glossary")
    terms = raw.get("terms")
    if not isinstance(terms, list):
        raise ExtractionError(f"{path}: 'terms' must be a list")

    entries: dict[str, ExtractedEntry] = {}
    term_ids: set[str] = set()
    for term in terms:
        if not isinstance(term, dict):
            raise ExtractionError(f"{path}: glossary term must be an object")
        term_id = str(term.get("id", "")).strip()
        if not term_id:
            raise ExtractionError(f"{path}: glossary term is missing an id")
        if term_id in term_ids:
            raise ExtractionError(f"{path}: duplicate glossary term id {term_id!r}")
        term_ids.add(term_id)
        for suffix, value in (("title", term.get("title", "")), ("body", term.get("body", ""))):
            _merge_entry(
                entries,
                f"term.{term_id}.{suffix}",
                str(value),
                _semantic_occurrence("glossary", term_id),
                catalog="glossary",
            )
    return entries


def extract_glossary_strings() -> Dict[str, str]:
    return {key: entry.text for key, entry in extract_glossary_records().items()}


def extract_common_value_records() -> dict[str, ExtractedEntry]:
    from app.localization.values import COMMON_VALUE_SOURCES, _value_key

    entries: dict[str, ExtractedEntry] = {}
    for value, text in COMMON_VALUE_SOURCES.items():
        key = _value_key(value)
        _merge_entry(
            entries,
            key,
            str(text),
            SourceOccurrence(
                path="app/localization/values.py",
                line=0,
                column=0,
                kind=f"presentation-value:{value}",
            ),
            catalog="ui",
        )
    return entries


def extract_common_value_strings() -> Dict[str, str]:
    return {key: entry.text for key, entry in extract_common_value_records().items()}


def extract_static_ui_records() -> dict[str, ExtractedEntry]:
    path = CONTENT_ROOT / "ui_static.json"
    raw = _read_semantic_source("ui_static")
    strings = raw.get("strings")
    if not isinstance(strings, dict):
        raise ExtractionError(f"{path}: 'strings' must be an object")
    entries: dict[str, ExtractedEntry] = {}
    for raw_key, raw_text in strings.items():
        if not isinstance(raw_key, str) or not raw_key.strip() or not isinstance(raw_text, str):
            raise ExtractionError(f"{path}: static UI entries must map non-empty strings to strings")
        key = raw_key.strip()
        _merge_entry(
            entries,
            key,
            raw_text,
            SourceOccurrence(
                path="app/localization/content/ui_static.json",
                line=0,
                column=0,
                kind="static-ui",
            ),
            catalog="ui",
        )
    return entries


def _merge_catalog_entries(
    destination: dict[str, ExtractedEntry],
    source: Mapping[str, ExtractedEntry],
    *,
    catalog: str,
) -> None:
    for key, incoming in source.items():
        for occurrence in incoming.occurrences or [SourceOccurrence("unknown", 0, 0, "unknown")]:
            _merge_entry(destination, key, incoming.text, occurrence, catalog=catalog)


def default_python_paths() -> list[Path]:
    paths = list((ROOT / "app").rglob("*.py"))
    paths.extend((ROOT / "main.py", ROOT / "cli_main.py"))
    return [path for path in paths if path.exists() and "__pycache__" not in path.parts]


def extract_records() -> ExtractionResult:
    ui_python, dynamic = extract_python_ui_records(default_python_paths())
    ui: dict[str, ExtractedEntry] = {}
    _merge_catalog_entries(ui, ui_python, catalog="ui")
    _merge_catalog_entries(ui, extract_common_value_records(), catalog="ui")
    _merge_catalog_entries(ui, extract_static_ui_records(), catalog="ui")

    return ExtractionResult(
        catalogs={
            "ui": ui,
            "help": extract_help_records(),
            "glossary": extract_glossary_records(),
        },
        dynamic_calls=dynamic,
    )


def _catalog_payload(name: str, entries: Mapping[str, ExtractedEntry]) -> dict:
    strings = {key: entries[key].text for key in sorted(entries)}
    digest_material = "\n".join(f"{key}\0{strings[key]}" for key in sorted(strings))
    return {
        "_meta": {
            "locale": CANONICAL,
            "source_locale": CANONICAL,
            "catalog": name,
            "generated_by": "tools/localization/extract_strings.py",
            "entry_count": len(strings),
            "catalog_hash": source_hash(digest_material),
        },
        "strings": strings,
    }


def _manifest_payload(result: ExtractionResult) -> dict:
    catalogs: dict[str, dict] = {}
    for catalog in CATALOGS:
        entries = result.catalogs[catalog]
        catalogs[catalog] = {
            "entry_count": len(entries),
            "entries": {
                key: entries[key].as_manifest_dict()
                for key in sorted(entries)
            },
        }
    duplicates = {
        catalog: {
            key: [occ.as_dict() for occ in occurrences]
            for key, occurrences in sorted(values.items())
        }
        for catalog, values in sorted(result.duplicate_keys.items())
    }
    return {
        "_meta": {
            "source_locale": CANONICAL,
            "generated_by": "tools/localization/extract_strings.py",
            "schema": 1,
        },
        "catalogs": catalogs,
        "duplicate_keys": duplicates,
        "dynamic_tr_calls": [occ.as_dict() for occ in result.dynamic_calls],
    }


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return path


def generated_payloads(result: ExtractionResult | None = None) -> dict[Path, dict]:
    result = result or extract_records()
    payloads: dict[Path, dict] = {}
    for catalog in CATALOGS:
        payloads[LOCALE_ROOT / CANONICAL / f"{catalog}.json"] = _catalog_payload(
            catalog, result.catalogs[catalog]
        )
    payloads[MANIFEST_PATH] = _manifest_payload(result)
    return payloads


def extraction_drift(result: ExtractionResult | None = None) -> list[str]:
    """Return generated files that differ from authoritative extraction source."""
    drift: list[str] = []
    for path, expected in generated_payloads(result).items():
        try:
            actual = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            drift.append(_render_path(path))
            continue
        if actual != expected:
            drift.append(_render_path(path))
    return drift


def extract_all() -> dict[str, Path]:
    result = extract_records()
    outputs: dict[str, Path] = {}
    for path, payload in generated_payloads(result).items():
        _write_json(path, payload)
        name = path.stem if path != MANIFEST_PATH else "manifest"
        outputs[name] = path
    return outputs


def extraction_summary(result: ExtractionResult | None = None) -> dict:
    result = result or extract_records()
    return {
        "catalog_entries": {
            catalog: len(entries) for catalog, entries in result.catalogs.items()
        },
        "total_entries": sum(len(entries) for entries in result.catalogs.values()),
        "duplicate_keys": sum(
            len(values) for values in result.duplicate_keys.values()
        ),
        "dynamic_tr_calls": len(result.dynamic_calls),
        "placeholder_entries": sum(
            1
            for entries in result.catalogs.values()
            for entry in entries.values()
            if entry.placeholders.names
        ),
        "malformed_format_entries": sum(
            1
            for entries in result.catalogs.values()
            for entry in entries.values()
            if entry.placeholders.malformed
        ),
    }


if __name__ == "__main__":
    outputs = extract_all()
    for name, path in outputs.items():
        print(f"{name}: {path.relative_to(ROOT)}")
    print(json.dumps(extraction_summary(), indent=2))
