"""Locale-generation preflight and reporting helpers.

These helpers are development-only.  They never run from SalixTorrent itself
and never persist credentials, access tokens, or credential file paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

try:
    from .google_translate import (
        CATALOGS,
        DEFAULT_LOCATION,
        DEFAULT_MODEL,
        SOURCE_LOCALE,
        TARGET_CODES,
        _cache_entry,
        _catalog_strings,
        _load_cache,
        _manifest_hash,
        _manual_overrides,
        _resolve_project_id,
    )
except ImportError:  # direct script execution
    from google_translate import (
        CATALOGS,
        DEFAULT_LOCATION,
        DEFAULT_MODEL,
        SOURCE_LOCALE,
        TARGET_CODES,
        _cache_entry,
        _catalog_strings,
        _load_cache,
        _manifest_hash,
        _manual_overrides,
        _resolve_project_id,
    )


@dataclass(frozen=True)
class GoogleDoctorReport:
    client_library: bool
    auth_library: bool
    credentials: bool
    credential_type: str
    project_id: str
    project_source: str
    location: str
    model: str
    probe_ok: bool | None
    detail: str

    @property
    def ready(self) -> bool:
        return self.client_library and self.auth_library and self.credentials and bool(self.project_id)


@dataclass(frozen=True)
class LocaleGenerationStatus:
    locale: str
    canonical: int
    packaged: int
    cache_valid: int
    overrides: int
    missing: int

    @property
    def complete(self) -> bool:
        return self.missing == 0 and self.packaged == self.canonical


def google_doctor(
    *,
    project_id: str | None = None,
    location: str | None = None,
    model: str | None = None,
    probe: bool = False,
    probe_factory: Callable[..., object] | None = None,
) -> GoogleDoctorReport:
    """Inspect local Google tooling/auth without exposing credential secrets.

    ``probe=False`` is entirely local.  ``probe=True`` performs one tiny
    authenticated Translation request so API enablement/model access can be
    verified before a full locale-generation run.
    """
    client_library = False
    auth_library = False
    credentials = False
    credential_type = "Unavailable"
    resolved_project = ""
    project_source = "Unavailable"
    chosen_location = str(location or DEFAULT_LOCATION).strip()
    chosen_model = str(model or DEFAULT_MODEL).strip()
    details: list[str] = []

    try:
        from google.cloud import translate_v3  # noqa: F401

        client_library = True
    except Exception as exc:
        details.append(f"Google Cloud Translation client unavailable: {exc}")

    try:
        import google.auth

        auth_library = True
        try:
            creds, adc_project = google.auth.default()
            credentials = creds is not None
            if creds is not None:
                credential_type = type(creds).__name__
            if adc_project:
                details.append("Application Default Credentials include a project hint.")
        except Exception as exc:
            details.append(f"Application Default Credentials unavailable: {exc}")
    except Exception as exc:
        details.append(f"Google authentication library unavailable: {exc}")

    try:
        resolved_project, project_source = _resolve_project_id(project_id)
    except Exception as exc:
        details.append(str(exc))

    probe_ok: bool | None = None
    if probe:
        if not (client_library and auth_library and credentials and resolved_project):
            probe_ok = False
            details.append("Network probe skipped because local Google setup is incomplete.")
        else:
            try:
                if probe_factory is None:
                    try:
                        from .google_translate import GoogleTranslator
                    except ImportError:
                        from google_translate import GoogleTranslator
                    factory = GoogleTranslator
                else:
                    factory = probe_factory
                translator = factory(
                    project_id=resolved_project,
                    location=chosen_location,
                    model=chosen_model,
                )
                values = translator.translate_batch(
                    ["SalixTorrent localization probe."],
                    TARGET_CODES["en-US"],
                )
                probe_ok = bool(values and str(values[0]).strip())
                details.append(
                    "Authenticated Translation probe succeeded."
                    if probe_ok
                    else "Authenticated Translation probe returned no usable text."
                )
            except Exception as exc:
                probe_ok = False
                details.append(f"Authenticated Translation probe failed: {exc}")

    return GoogleDoctorReport(
        client_library=client_library,
        auth_library=auth_library,
        credentials=credentials,
        credential_type=credential_type,
        project_id=resolved_project,
        project_source=project_source,
        location=chosen_location,
        model=chosen_model,
        probe_ok=probe_ok,
        detail=" ".join(details).strip() or "Local Google development setup looks healthy.",
    )


def locale_generation_status(locale: str) -> LocaleGenerationStatus:
    if locale not in TARGET_CODES:
        raise ValueError(f"Unsupported translation target {locale!r}")

    cache = _load_cache()
    overrides = _manual_overrides(locale)
    canonical = packaged = cache_valid = override_count = 0

    for catalog in CATALOGS:
        source = _catalog_strings(SOURCE_LOCALE, catalog)
        target = _catalog_strings(locale, catalog)
        catalog_overrides = overrides.get(catalog, {})
        canonical += len(source)
        packaged += sum(1 for key in source if key in target)
        override_count += sum(1 for key in source if key in catalog_overrides)

        for key, source_text in source.items():
            entry = _cache_entry(cache, locale, catalog, key)
            if (
                entry.get("source_hash") == _manifest_hash(catalog, key, source_text)
                and isinstance(entry.get("translation"), str)
            ):
                cache_valid += 1

    return LocaleGenerationStatus(
        locale=locale,
        canonical=canonical,
        packaged=packaged,
        cache_valid=cache_valid,
        overrides=override_count,
        missing=max(0, canonical - packaged),
    )


def all_generation_status(locales: Iterable[str] | None = None) -> list[LocaleGenerationStatus]:
    selected = list(locales) if locales is not None else sorted(TARGET_CODES)
    return [locale_generation_status(locale) for locale in selected]
