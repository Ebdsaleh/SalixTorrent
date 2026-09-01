"""SalixTorrent offline localization runtime."""

from .locale_info import (
    AUTO_LOCALE,
    CANONICAL_LOCALE,
    LANGUAGE_OPTION_LABELS,
    SUPPORTED_LOCALES,
    locale_code_from_label,
    locale_label,
    normalise_locale_code,
    resolve_requested_locale,
    system_locale_name,
)
from .manager import LocalizationManager, localization_manager, placeholder_names, tr
from .documents import (
    HelpTopic,
    canonical_glossary_entries,
    canonical_help_topics,
    document_structure_snapshot,
    glossary_entry,
    localized_glossary_entries,
    localized_help_topics,
)
from .values import COMMON_VALUE_SOURCES, canonical_choice, localized_choices, tr_value

__all__ = [
    "AUTO_LOCALE",
    "CANONICAL_LOCALE",
    "LANGUAGE_OPTION_LABELS",
    "SUPPORTED_LOCALES",
    "LocalizationManager",
    "localization_manager",
    "locale_code_from_label",
    "locale_label",
    "normalise_locale_code",
    "placeholder_names",
    "resolve_requested_locale",
    "system_locale_name",
    "tr",
    "HelpTopic",
    "canonical_glossary_entries",
    "canonical_help_topics",
    "document_structure_snapshot",
    "glossary_entry",
    "localized_glossary_entries",
    "localized_help_topics",
    "COMMON_VALUE_SOURCES",
    "canonical_choice",
    "localized_choices",
    "tr_value",
]
