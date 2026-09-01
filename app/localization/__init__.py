"""SalixTorrent offline localization runtime."""

from .locale_info import (
    AUTO_LOCALE,
    CANONICAL_LOCALE,
    LANGUAGE_OPTION_LABELS,
    SUPPORTED_LOCALES,
    locale_code_from_label,
    locale_label,
    locale_info,
    normalise_locale_code,
    resolve_requested_locale,
    system_locale_name,
)
from .manager import LocalizationManager, localization_manager, placeholder_names, tr
from .framework import (
    CatalogRepository,
    JsonCatalogRepository,
    LocaleDescriptor,
    LocalizationProfile,
)
from .profile import SALIXTORRENT_LOCALIZATION_PROFILE
from .pseudo import PSEUDO_ENV, PSEUDO_LOCALE, pseudo_catalog, pseudo_localize
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
    "CatalogRepository",
    "JsonCatalogRepository",
    "LocaleDescriptor",
    "LocalizationProfile",
    "SALIXTORRENT_LOCALIZATION_PROFILE",
    "localization_manager",
    "locale_code_from_label",
    "locale_label",
    "locale_info",
    "normalise_locale_code",
    "placeholder_names",
    "PSEUDO_ENV",
    "PSEUDO_LOCALE",
    "pseudo_catalog",
    "pseudo_localize",
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


