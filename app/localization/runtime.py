"""Framework-neutral offline localization runtime.

The runtime owns catalog loading, locale fallback, placeholder contracts,
pseudo-localization hooks, and diagnostics. Applications provide only a
LocalizationProfile, a CatalogRepository, and a locale resolver.
"""

from __future__ import annotations

import os
import string
import threading
from collections import Counter
from typing import Callable, Dict, Mapping, Optional, Protocol, Set

from .framework import CatalogRepository, LocalizationProfile


class LocaleResolver(Protocol):
    """Resolve an application request to one concrete locale code."""

    def __call__(
        self,
        requested: object,
        *,
        system_locale: Optional[str] = None,
        allow_pseudo: bool = False,
    ) -> str: ...


CatalogTransform = Callable[[dict[str, str]], dict[str, str]]


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def placeholder_names(text: object) -> Set[str]:
    """Return root named ``str.format`` fields used by *text*.

    Nested access such as ``{user.name}`` and ``{items[0]}`` is represented by
    the root field (``user`` / ``items``), matching runtime call-site kwargs.
    Invalid format strings fail closed to an empty contract.
    """

    names: Set[str] = set()
    formatter = string.Formatter()
    try:
        for _literal, field_name, _format_spec, _conversion in formatter.parse(str(text or "")):
            if field_name:
                root = field_name.split(".", 1)[0].split("[", 1)[0]
                if root:
                    names.add(root)
    except ValueError:
        return set()
    return names


class LocalizationRuntime:
    """Reusable, provider-neutral runtime localization engine.

    This class performs no network translation and knows nothing about GUI
    toolkits, application resource paths, or translation providers.
    """

    def __init__(
        self,
        *,
        profile: LocalizationProfile,
        repository: CatalogRepository,
        locale_resolver: LocaleResolver,
        pseudo_catalog_factory: CatalogTransform | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.profile = profile
        self.repository = repository
        self.locale_resolver = locale_resolver
        self.pseudo_catalog_factory = pseudo_catalog_factory
        self.environment = os.environ if environment is None else environment

        self._lock = threading.RLock()
        self.requested_locale = profile.auto_locale
        self.active_locale = profile.canonical_locale
        self._catalogs: Dict[str, Dict[str, str]] = {}
        self._canonical_catalogs: Dict[str, Dict[str, str]] = {}
        self._fallback_keys: Set[str] = set()
        self._fallback_reasons: Counter[str] = Counter()
        self._format_error_keys: Set[str] = set()
        self._load_errors: list[str] = []
        self._catalog_health: Dict[str, str] = {}
        self._generation = 0
        self.configure(profile.auto_locale)

    def _read_catalog(self, locale_code: str, catalog_name: str) -> Dict[str, str]:
        return self.repository.read(locale_code, catalog_name)

    def configure(self, requested_locale: object, *, system_locale: Optional[str] = None) -> str:
        with self._lock:
            pseudo_override = False
            if self.profile.pseudo_environment:
                pseudo_override = _truthy(self.environment.get(self.profile.pseudo_environment))

            effective_request = (
                self.profile.pseudo_locale
                if pseudo_override and self.profile.pseudo_locale
                else requested_locale
            )
            self.requested_locale = str(effective_request or self.profile.auto_locale)
            resolved = self.locale_resolver(
                effective_request,
                system_locale=system_locale,
                allow_pseudo=bool(self.profile.pseudo_locale),
            )
            if resolved != self.profile.pseudo_locale and resolved not in self.profile.locales:
                resolved = self.profile.canonical_locale

            self._fallback_keys.clear()
            self._fallback_reasons.clear()
            self._format_error_keys.clear()
            self._load_errors.clear()
            self._catalog_health.clear()
            self._canonical_catalogs = {}
            self._catalogs = {}

            for name in self.profile.catalog_names:
                canonical_key = f"{self.profile.canonical_locale}/{name}"
                try:
                    self._canonical_catalogs[name] = self._read_catalog(
                        self.profile.canonical_locale,
                        name,
                    )
                    self._catalog_health[canonical_key] = "loaded"
                except Exception as exc:
                    self._canonical_catalogs[name] = {}
                    self._catalog_health[canonical_key] = "unavailable"
                    self._load_errors.append(f"{self.profile.canonical_locale}/{name}: {exc}")

                if resolved == self.profile.pseudo_locale and self.profile.pseudo_locale:
                    if self.pseudo_catalog_factory is None:
                        self._catalogs[name] = dict(self._canonical_catalogs[name])
                        self._catalog_health[f"{resolved}/{name}"] = "pseudo-transform-unavailable"
                        self._load_errors.append(
                            f"{resolved}/{name}: pseudo locale requested without a catalog transform"
                        )
                    else:
                        self._catalogs[name] = self.pseudo_catalog_factory(self._canonical_catalogs[name])
                        self._catalog_health[f"{resolved}/{name}"] = "generated-in-memory"
                    continue

                if resolved == self.profile.canonical_locale:
                    self._catalogs[name] = dict(self._canonical_catalogs[name])
                    continue

                active_key = f"{resolved}/{name}"
                try:
                    self._catalogs[name] = self._read_catalog(resolved, name)
                    self._catalog_health[active_key] = "loaded"
                except Exception as exc:
                    self._catalogs[name] = {}
                    self._catalog_health[active_key] = "fallback-to-canonical"
                    self._load_errors.append(f"{resolved}/{name}: {exc}")

            self.active_locale = resolved
            self._generation += 1
            return self.active_locale

    @property
    def generation(self) -> int:
        return self._generation

    def catalog(self, name: str) -> Mapping[str, str]:
        return self._catalogs.get(str(name), {})

    def canonical_catalog(self, name: str) -> Mapping[str, str]:
        return self._canonical_catalogs.get(str(name), {})

    def _record_fallback(self, catalog: str, key: str, reason: str) -> None:
        self._fallback_keys.add(f"{catalog}:{key}")
        self._fallback_reasons[str(reason)] += 1

    def lookup(self, key: str, default: Optional[str] = None, *, catalog: str = "ui") -> str:
        key = str(key)
        active = self._catalogs.get(catalog, {})
        canonical = self._canonical_catalogs.get(catalog, {})
        if key in active and str(active[key]).strip():
            return active[key]
        if key in canonical:
            if self.active_locale != self.profile.canonical_locale:
                self._record_fallback(catalog, key, "canonical")
            return canonical[key]
        if default is not None:
            self._record_fallback(catalog, key, "call-site-default")
            return str(default)
        self._record_fallback(catalog, key, "key")
        return key

    def tr(self, key: str, default: Optional[str] = None, *, catalog: str = "ui", **values) -> str:
        text = self.lookup(key, default, catalog=catalog)
        if not values:
            return text

        source = self._canonical_catalogs.get(catalog, {}).get(str(key), default or "")
        expected = placeholder_names(source)
        actual = placeholder_names(text)
        if expected != actual:
            self._format_error_keys.add(f"{catalog}:{key}")
            self._fallback_reasons["format-contract"] += 1
            text = str(source or default or key)
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            self._format_error_keys.add(f"{catalog}:{key}")
            self._fallback_reasons["format-error"] += 1
            fallback = str(source or default or key)
            try:
                return fallback.format(**values)
            except Exception:
                return fallback

    def snapshot(self) -> Dict[str, object]:
        active_count = sum(len(values) for values in self._catalogs.values())
        canonical_count = sum(len(values) for values in self._canonical_catalogs.values())
        info = self.profile.locale(self.active_locale)
        pseudo_active = bool(self.profile.pseudo_locale and self.active_locale == self.profile.pseudo_locale)
        return {
            "application_id": self.profile.application_id,
            "requested_locale": self.requested_locale,
            "active_locale": self.active_locale,
            "canonical_locale": self.profile.canonical_locale,
            "bundled": not pseudo_active,
            "pseudo_locale": pseudo_active,
            "script": info.script,
            "text_direction": info.text_direction,
            "font_profile": info.font_profile,
            "support_status": info.support_status,
            "catalog_entries": active_count,
            "canonical_entries": canonical_count,
            "catalog_health": dict(sorted(self._catalog_health.items())),
            "fallback_count": len(self._fallback_keys),
            "fallback_keys": tuple(sorted(self._fallback_keys)),
            "fallback_by_reason": dict(sorted(self._fallback_reasons.items())),
            "format_error_count": len(self._format_error_keys),
            "format_error_keys": tuple(sorted(self._format_error_keys)),
            "load_errors": tuple(self._load_errors),
            "generation": self._generation,
        }
