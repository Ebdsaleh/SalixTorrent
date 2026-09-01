"""Locale metadata and system-locale resolution for SalixTorrent.

Runtime locale identifiers are SalixTorrent-owned BCP-47 tags. Translation
providers are deliberately kept behind a separate mapping so the application
never depends on Google-specific language codes.
"""

from __future__ import annotations

import ctypes
import locale as _locale
import os
import sys
from dataclasses import dataclass
from typing import Dict, Optional


CANONICAL_LOCALE = "en-AU"
AUTO_LOCALE = "auto"


@dataclass(frozen=True)
class LocaleInfo:
    code: str
    display_name: str
    native_name: str
    google_target: str


SUPPORTED_LOCALES: Dict[str, LocaleInfo] = {
    "en-AU": LocaleInfo("en-AU", "English (Australia)", "English (Australia)", "en-AU"),
    "en-GB": LocaleInfo("en-GB", "English (United Kingdom)", "English (United Kingdom)", "en-GB"),
    "en-US": LocaleInfo("en-US", "English (United States)", "English (United States)", "en-US"),
    "pt-BR": LocaleInfo("pt-BR", "Portuguese (Brazil)", "Português (Brasil)", "pt-BR"),
    "fil-PH": LocaleInfo("fil-PH", "Filipino", "Filipino", "fil"),
}


LANGUAGE_OPTION_LABELS = {
    AUTO_LOCALE: "System Default",
    **{code: info.native_name for code, info in SUPPORTED_LOCALES.items()},
}
LANGUAGE_LABEL_TO_CODE = {label: code for code, label in LANGUAGE_OPTION_LABELS.items()}


def _clean_locale_code(value: object) -> str:
    raw = str(value or "").strip().replace("_", "-")
    if not raw:
        return ""
    # Remove encoding/modifier suffixes such as en_AU.UTF-8 or en_AU@foo.
    raw = raw.split(".", 1)[0].split("@", 1)[0]
    parts = [part for part in raw.split("-") if part]
    if not parts:
        return ""
    language = parts[0].lower()
    region = ""
    if len(parts) >= 2 and len(parts[1]) in {2, 3}:
        region = parts[1].upper()
    return f"{language}-{region}" if region else language


def normalise_locale_code(value: object, *, allow_auto: bool = True) -> str:
    raw = str(value or "").strip()
    if allow_auto and raw.lower() in {"", "auto", "system", "system default"}:
        return AUTO_LOCALE

    cleaned = _clean_locale_code(raw)
    if cleaned in SUPPORTED_LOCALES:
        return cleaned

    language = cleaned.split("-", 1)[0].lower() if cleaned else ""
    if language == "en":
        # Unknown/generic English follows the project's canonical English.
        return CANONICAL_LOCALE
    if language == "pt":
        return "pt-BR"
    if language in {"fil", "tl"}:
        return "fil-PH"
    return CANONICAL_LOCALE


def locale_label(code: object) -> str:
    normalised = normalise_locale_code(code)
    return LANGUAGE_OPTION_LABELS.get(normalised, LANGUAGE_OPTION_LABELS[CANONICAL_LOCALE])


def locale_code_from_label(label: object) -> str:
    raw = str(label or "").strip()
    if raw in LANGUAGE_LABEL_TO_CODE:
        return LANGUAGE_LABEL_TO_CODE[raw]
    return normalise_locale_code(raw)


def _windows_user_locale() -> str:
    if os.name != "nt":
        return ""
    try:
        # LOCALE_NAME_MAX_LENGTH is 85 including the NUL terminator.
        buffer = ctypes.create_unicode_buffer(85)
        result = ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer))
        if result:
            return str(buffer.value or "")
    except Exception:
        pass
    return ""


def system_locale_name() -> str:
    """Return the best local OS/user locale identifier without network access."""
    win = _windows_user_locale()
    if win:
        return win

    # Python's locale APIs can return None in minimal/container environments,
    # so preserve ordinary POSIX environment variables as fallbacks.
    try:
        language, _encoding = _locale.getlocale()
        if language:
            return str(language)
    except Exception:
        pass

    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    return ""


def resolve_requested_locale(requested: object, *, system_locale: Optional[str] = None) -> str:
    requested_code = normalise_locale_code(requested)
    if requested_code != AUTO_LOCALE:
        return requested_code
    detected = system_locale if system_locale is not None else system_locale_name()
    return normalise_locale_code(detected, allow_auto=False)
