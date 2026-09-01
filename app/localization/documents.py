"""SalixTorrent semantic Help/Glossary adapter.

Renderer-neutral parsing/localization now lives in ``app.localization.semantic``.
This module preserves the historical SalixTorrent helper API and supplies only
application content paths plus the active runtime translator.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Tuple

from .manager import localization_manager
from .profile import salixtorrent_content_path
from .semantic import (
    HelpTopic,
    JsonSemanticDocumentRepository,
    SemanticDocumentationService,
    SemanticDocumentationSource,
)


_repository = JsonSemanticDocumentRepository(salixtorrent_content_path)
_source = SemanticDocumentationSource(_repository)
_service = SemanticDocumentationService(_source, localization_manager().tr)


def help_source_document() -> Mapping[str, object]:
    return _source.help_source_document


def glossary_source_document() -> Mapping[str, object]:
    return _source.glossary_source_document


def canonical_help_topics() -> tuple[HelpTopic, ...]:
    return _source.help_topics


def canonical_glossary_entries() -> dict[str, Tuple[str, str]]:
    return dict(_source.glossary_entries)


def help_topic_value(topic_key: str, field: str, source: str) -> str:
    return _service.help_topic_value(topic_key, field, source)


def help_topic_section_value(topic_key: str, section_key: object, field: str, source: str) -> str:
    return _service.help_section_value(topic_key, section_key, field, source)


def localize_help_topic(topic: HelpTopic | None):
    return _service.localize_help_topic(topic)


def glossary_entry(
    key: str,
    source_entry: Tuple[str, str] | None = None,
) -> Tuple[str, str]:
    return _service.glossary_entry(key, source_entry)


def localized_help_topics(topics: Iterable[HelpTopic] | None = None) -> tuple[HelpTopic, ...]:
    return _service.localized_help_topics(topics)


def localized_glossary_entries(
    entries: Mapping[str, Tuple[str, str]] | None = None,
) -> dict[str, Tuple[str, str]]:
    return _service.localized_glossary_entries(entries)


def document_structure_snapshot() -> dict[str, object]:
    return _source.structure_snapshot()
