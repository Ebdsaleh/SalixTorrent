"""Semantic Help/Glossary source loading and locale overlays.

Phase 12 Stage 3 deliberately keeps documentation *content* out of Dear PyGui
views.  Locale-neutral IDs/relationships and canonical en-AU authoring text live
under ``app/localization/content``.  Runtime locale catalogs contain only the
translated strings.  Views receive semantic objects and never need to know
where the wording came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Iterable, Mapping, Tuple

from app.engine.runtime_paths import resource_path
from .manager import localization_manager


CONTENT_ROOT = Path("app") / "localization" / "content"


@dataclass(frozen=True)
class HelpTopic:
    """Locale-neutral Help article identity plus rendered text fields.

    ``section_keys`` are stable semantic IDs.  They are intentionally separate
    from section titles so changing or translating a heading does not rename a
    translation key.  ``sections`` keeps the historical ``(title, body)`` shape
    used by HelpTopicsView and therefore avoids coupling the renderer to the
    storage schema.
    """

    key: str
    title: str
    summary: str
    sections: Tuple[Tuple[str, str], ...]
    related_terms: Tuple[str, ...] = ()
    section_keys: Tuple[str, ...] = ()


def _content_path(name: str) -> Path:
    return resource_path(CONTENT_ROOT / name)


def _read_json(name: str) -> Mapping[str, object]:
    path = _content_path(name)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return raw


@lru_cache(maxsize=1)
def help_source_document() -> Mapping[str, object]:
    """Return the canonical semantic Help authoring document."""
    return _read_json("help.json")


@lru_cache(maxsize=1)
def glossary_source_document() -> Mapping[str, object]:
    """Return the canonical semantic Glossary authoring document."""
    return _read_json("glossary.json")


def _help_records() -> tuple[Mapping[str, object], ...]:
    records = help_source_document().get("topics", ())
    if not isinstance(records, list):
        raise ValueError(f"{_content_path('help.json')}: 'topics' must be a list")
    return tuple(record for record in records if isinstance(record, dict))


def _glossary_records() -> tuple[Mapping[str, object], ...]:
    records = glossary_source_document().get("terms", ())
    if not isinstance(records, list):
        raise ValueError(f"{_content_path('glossary.json')}: 'terms' must be a list")
    return tuple(record for record in records if isinstance(record, dict))


@lru_cache(maxsize=1)
def canonical_help_topics() -> tuple[HelpTopic, ...]:
    """Build canonical Help topics from the renderer-neutral source document."""
    topics = []
    for record in _help_records():
        key = str(record.get("id", "")).strip()
        if not key:
            raise ValueError("Help topic is missing a stable 'id'")
        raw_sections = record.get("sections", ())
        if not isinstance(raw_sections, list):
            raise ValueError(f"Help topic {key!r}: 'sections' must be a list")
        section_keys = []
        sections = []
        for section in raw_sections:
            if not isinstance(section, dict):
                raise ValueError(f"Help topic {key!r}: section must be an object")
            section_key = str(section.get("id", "")).strip()
            if not section_key:
                raise ValueError(f"Help topic {key!r}: section is missing a stable 'id'")
            section_keys.append(section_key)
            sections.append((str(section.get("title", "")), str(section.get("body", ""))))
        related = record.get("related_terms", ())
        if not isinstance(related, list):
            raise ValueError(f"Help topic {key!r}: 'related_terms' must be a list")
        topics.append(
            HelpTopic(
                key=key,
                title=str(record.get("title", "")),
                summary=str(record.get("summary", "")),
                sections=tuple(sections),
                related_terms=tuple(str(value) for value in related),
                section_keys=tuple(section_keys),
            )
        )
    return tuple(topics)


@lru_cache(maxsize=1)
def canonical_glossary_entries() -> dict[str, Tuple[str, str]]:
    """Return canonical glossary entries keyed by stable locale-neutral term ID."""
    entries: dict[str, Tuple[str, str]] = {}
    for record in _glossary_records():
        key = str(record.get("id", "")).strip()
        if not key:
            raise ValueError("Glossary term is missing a stable 'id'")
        entries[key] = (str(record.get("title", "")), str(record.get("body", "")))
    return entries


def help_topic_value(topic_key: str, field: str, source: str) -> str:
    key = f"topic.{topic_key}.{field}"
    return localization_manager().tr(key, source, catalog="help")


def help_topic_section_value(topic_key: str, section_key: object, field: str, source: str) -> str:
    key = f"topic.{topic_key}.section.{section_key}.{field}"
    return localization_manager().tr(key, source, catalog="help")


def localize_help_topic(topic: HelpTopic | None):
    """Return a localized copy while preserving every semantic ID/relationship."""
    if topic is None:
        return None
    keys = tuple(topic.section_keys)
    if len(keys) != len(topic.sections):
        # Compatibility for any external HelpTopic-like object constructed with
        # the historical shape.  Built-in topics always carry stable keys.
        keys = tuple(str(index) for index in range(len(topic.sections)))
    sections = tuple(
        (
            help_topic_section_value(topic.key, keys[index], "title", heading),
            help_topic_section_value(topic.key, keys[index], "body", body),
        )
        for index, (heading, body) in enumerate(topic.sections)
    )
    return type(topic)(
        key=topic.key,
        title=help_topic_value(topic.key, "title", topic.title),
        summary=help_topic_value(topic.key, "summary", topic.summary),
        sections=sections,
        related_terms=tuple(topic.related_terms),
        section_keys=keys,
    )


def glossary_entry(
    key: str,
    source_entry: Tuple[str, str] | None = None,
) -> Tuple[str, str]:
    stable_key = str(key)
    if source_entry is None:
        source_entry = canonical_glossary_entries().get(stable_key, (stable_key, ""))
    title, body = source_entry
    manager = localization_manager()
    return (
        manager.tr(f"term.{stable_key}.title", title, catalog="glossary"),
        manager.tr(f"term.{stable_key}.body", body, catalog="glossary"),
    )


def localized_help_topics(topics: Iterable[HelpTopic] | None = None) -> tuple[HelpTopic, ...]:
    source = canonical_help_topics() if topics is None else tuple(topics)
    return tuple(localize_help_topic(topic) for topic in source)


def localized_glossary_entries(
    entries: Mapping[str, Tuple[str, str]] | None = None,
) -> dict[str, Tuple[str, str]]:
    source = canonical_glossary_entries() if entries is None else entries
    return {str(key): glossary_entry(str(key), tuple(value)) for key, value in source.items()}


def document_structure_snapshot() -> dict[str, object]:
    """Small deterministic semantic snapshot for diagnostics/tests/tooling."""
    topics = canonical_help_topics()
    terms = canonical_glossary_entries()
    return {
        "topic_count": len(topics),
        "section_count": sum(len(topic.sections) for topic in topics),
        "term_count": len(terms),
        "topic_ids": tuple(topic.key for topic in topics),
        "term_ids": tuple(terms),
        "section_ids": {
            topic.key: tuple(topic.section_keys)
            for topic in topics
        },
        "related_terms": {
            topic.key: tuple(topic.related_terms)
            for topic in topics
        },
    }
