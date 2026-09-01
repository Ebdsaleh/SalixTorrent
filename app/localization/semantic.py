"""Framework-neutral semantic documentation source and localization services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol, Tuple


@dataclass(frozen=True)
class HelpTopic:
    """Stable semantic Help identity plus renderer-ready text fields."""

    key: str
    title: str
    summary: str
    sections: Tuple[Tuple[str, str], ...]
    related_terms: Tuple[str, ...] = ()
    section_keys: Tuple[str, ...] = ()


class SemanticDocumentRepository(Protocol):
    def read(self, name: str) -> Mapping[str, object]: ...


DocumentPathResolver = Callable[[str], Path]
Translator = Callable[..., str]


class JsonSemanticDocumentRepository:
    """Load semantic JSON documents from an injected application path resolver."""

    def __init__(self, path_resolver: DocumentPathResolver) -> None:
        self._path_resolver = path_resolver

    def path(self, name: str) -> Path:
        cleaned = str(name or "").strip()
        if not cleaned:
            raise ValueError("semantic document name cannot be empty")
        return Path(self._path_resolver(cleaned))

    def read(self, name: str) -> Mapping[str, object]:
        path = self.path(name)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: expected a JSON object")
        return raw


class SemanticDocumentationSource:
    """Parse stable Help/Glossary structures independent of any renderer."""

    def __init__(
        self,
        repository: SemanticDocumentRepository,
        *,
        help_document: str = "help.json",
        glossary_document: str = "glossary.json",
    ) -> None:
        self.repository = repository
        self.help_document = help_document
        self.glossary_document = glossary_document

    @cached_property
    def help_source_document(self) -> Mapping[str, object]:
        return self.repository.read(self.help_document)

    @cached_property
    def glossary_source_document(self) -> Mapping[str, object]:
        return self.repository.read(self.glossary_document)

    @cached_property
    def help_topics(self) -> tuple[HelpTopic, ...]:
        records = self.help_source_document.get("topics", ())
        if not isinstance(records, list):
            raise ValueError(f"{self.help_document}: 'topics' must be a list")
        topics: list[HelpTopic] = []
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"{self.help_document}: Help topic must be an object")
            key = str(record.get("id", "")).strip()
            if not key:
                raise ValueError("Help topic is missing a stable 'id'")
            raw_sections = record.get("sections", ())
            if not isinstance(raw_sections, list):
                raise ValueError(f"Help topic {key!r}: 'sections' must be a list")
            section_keys: list[str] = []
            sections: list[tuple[str, str]] = []
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

    @cached_property
    def glossary_entries(self) -> dict[str, Tuple[str, str]]:
        records = self.glossary_source_document.get("terms", ())
        if not isinstance(records, list):
            raise ValueError(f"{self.glossary_document}: 'terms' must be a list")
        entries: dict[str, Tuple[str, str]] = {}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"{self.glossary_document}: Glossary term must be an object")
            key = str(record.get("id", "")).strip()
            if not key:
                raise ValueError("Glossary term is missing a stable 'id'")
            if key in entries:
                raise ValueError(f"duplicate Glossary term id {key!r}")
            entries[key] = (str(record.get("title", "")), str(record.get("body", "")))
        return entries

    def structure_snapshot(self) -> dict[str, object]:
        topics = self.help_topics
        terms = self.glossary_entries
        return {
            "topic_count": len(topics),
            "section_count": sum(len(topic.sections) for topic in topics),
            "term_count": len(terms),
            "topic_ids": tuple(topic.key for topic in topics),
            "term_ids": tuple(terms),
            "section_ids": {topic.key: tuple(topic.section_keys) for topic in topics},
            "related_terms": {topic.key: tuple(topic.related_terms) for topic in topics},
        }


class SemanticDocumentationService:
    """Overlay localized text while preserving semantic IDs and relationships."""

    def __init__(
        self,
        source: SemanticDocumentationSource,
        translator: Translator,
        *,
        help_catalog: str = "help",
        glossary_catalog: str = "glossary",
    ) -> None:
        self.source = source
        self.translator = translator
        self.help_catalog = help_catalog
        self.glossary_catalog = glossary_catalog

    def help_topic_value(self, topic_key: str, field: str, source: str) -> str:
        return self.translator(
            f"topic.{topic_key}.{field}",
            source,
            catalog=self.help_catalog,
        )

    def help_section_value(
        self,
        topic_key: str,
        section_key: object,
        field: str,
        source: str,
    ) -> str:
        return self.translator(
            f"topic.{topic_key}.section.{section_key}.{field}",
            source,
            catalog=self.help_catalog,
        )

    def localize_help_topic(self, topic: HelpTopic | None):
        if topic is None:
            return None
        keys = tuple(topic.section_keys)
        if len(keys) != len(topic.sections):
            keys = tuple(str(index) for index in range(len(topic.sections)))
        sections = tuple(
            (
                self.help_section_value(topic.key, keys[index], "title", heading),
                self.help_section_value(topic.key, keys[index], "body", body),
            )
            for index, (heading, body) in enumerate(topic.sections)
        )
        return type(topic)(
            key=topic.key,
            title=self.help_topic_value(topic.key, "title", topic.title),
            summary=self.help_topic_value(topic.key, "summary", topic.summary),
            sections=sections,
            related_terms=tuple(topic.related_terms),
            section_keys=keys,
        )

    def glossary_entry(
        self,
        key: str,
        source_entry: Tuple[str, str] | None = None,
    ) -> Tuple[str, str]:
        stable_key = str(key)
        if source_entry is None:
            source_entry = self.source.glossary_entries.get(stable_key, (stable_key, ""))
        title, body = source_entry
        return (
            self.translator(
                f"term.{stable_key}.title",
                title,
                catalog=self.glossary_catalog,
            ),
            self.translator(
                f"term.{stable_key}.body",
                body,
                catalog=self.glossary_catalog,
            ),
        )

    def localized_help_topics(
        self,
        topics: Iterable[HelpTopic] | None = None,
    ) -> tuple[HelpTopic, ...]:
        source = self.source.help_topics if topics is None else tuple(topics)
        return tuple(self.localize_help_topic(topic) for topic in source)

    def localized_glossary_entries(
        self,
        entries: Mapping[str, Tuple[str, str]] | None = None,
    ) -> dict[str, Tuple[str, str]]:
        source = self.source.glossary_entries if entries is None else entries
        return {str(key): self.glossary_entry(str(key), tuple(value)) for key, value in source.items()}
