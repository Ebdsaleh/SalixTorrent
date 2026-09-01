"""Offline runtime localization manager for SalixTorrent.

The released client reads only bundled JSON catalogs. Network translation is a
development-only concern under ``tools/localization``. Stage 7 adds explicit
catalog-health/fallback diagnostics and an in-memory pseudo locale for layout
stress testing.
"""

from __future__ import annotations

import json
import os
import string
import threading
from collections import Counter
from pathlib import Path
from typing import Dict, Mapping, Optional, Set

from app.engine.runtime_paths import resource_path
from .locale_info import (
    AUTO_LOCALE,
    CANONICAL_LOCALE,
    SUPPORTED_LOCALES,
    locale_info,
    resolve_requested_locale,
)
from .pseudo import PSEUDO_ENV, PSEUDO_LOCALE, pseudo_catalog


CATALOG_NAMES = ("ui", "help", "glossary")


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def placeholder_names(text: object) -> Set[str]:
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


class LocalizationManager:
    _instance: Optional["LocalizationManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._lock = threading.RLock()
        self.requested_locale = AUTO_LOCALE
        self.active_locale = CANONICAL_LOCALE
        self._catalogs: Dict[str, Dict[str, str]] = {}
        self._canonical_catalogs: Dict[str, Dict[str, str]] = {}
        self._fallback_keys: Set[str] = set()
        self._fallback_reasons: Counter[str] = Counter()
        self._format_error_keys: Set[str] = set()
        self._load_errors: list[str] = []
        self._catalog_health: Dict[str, str] = {}
        self._generation = 0
        self._initialized = True
        self.configure(AUTO_LOCALE)

    @classmethod
    def get_instance(cls) -> "LocalizationManager":
        return cls()

    @staticmethod
    def locale_root(locale_code: str) -> Path:
        return resource_path(Path("app") / "localization" / "locales" / locale_code)

    @staticmethod
    def _read_catalog(locale_code: str, catalog_name: str) -> Dict[str, str]:
        path = LocalizationManager.locale_root(locale_code) / f"{catalog_name}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path} does not contain a JSON object")
        meta = raw.get("_meta", {})
        if meta and not isinstance(meta, dict):
            raise ValueError(f"{path} has invalid _meta")
        if isinstance(meta, dict):
            declared_locale = str(meta.get("locale") or "")
            declared_catalog = str(meta.get("catalog") or "")
            if declared_locale and declared_locale != locale_code:
                raise ValueError(
                    f"{path} declares locale {declared_locale!r}, expected {locale_code!r}"
                )
            if declared_catalog and declared_catalog != catalog_name:
                raise ValueError(
                    f"{path} declares catalog {declared_catalog!r}, expected {catalog_name!r}"
                )
        strings = raw.get("strings", raw)
        if not isinstance(strings, dict):
            raise ValueError(f"{path} does not contain a string mapping")
        out: Dict[str, str] = {}
        for key, value in strings.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(f"{path} catalog entries must map strings to strings")
            out[key] = value
        return out

    def configure(self, requested_locale: object, *, system_locale: Optional[str] = None) -> str:
        with self._lock:
            pseudo_override = _truthy(os.environ.get(PSEUDO_ENV))
            effective_request = PSEUDO_LOCALE if pseudo_override else requested_locale
            self.requested_locale = str(effective_request or AUTO_LOCALE)
            resolved = resolve_requested_locale(
                effective_request,
                system_locale=system_locale,
                allow_pseudo=True,
            )
            if resolved != PSEUDO_LOCALE and resolved not in SUPPORTED_LOCALES:
                resolved = CANONICAL_LOCALE

            self._fallback_keys.clear()
            self._fallback_reasons.clear()
            self._format_error_keys.clear()
            self._load_errors.clear()
            self._catalog_health.clear()
            self._canonical_catalogs = {}
            self._catalogs = {}

            for name in CATALOG_NAMES:
                canonical_key = f"{CANONICAL_LOCALE}/{name}"
                try:
                    self._canonical_catalogs[name] = self._read_catalog(CANONICAL_LOCALE, name)
                    self._catalog_health[canonical_key] = "loaded"
                except Exception as exc:
                    self._canonical_catalogs[name] = {}
                    self._catalog_health[canonical_key] = "unavailable"
                    self._load_errors.append(f"{CANONICAL_LOCALE}/{name}: {exc}")

                if resolved == PSEUDO_LOCALE:
                    self._catalogs[name] = pseudo_catalog(self._canonical_catalogs[name])
                    self._catalog_health[f"{PSEUDO_LOCALE}/{name}"] = "generated-in-memory"
                    continue

                if resolved == CANONICAL_LOCALE:
                    self._catalogs[name] = dict(self._canonical_catalogs[name])
                    continue

                active_key = f"{resolved}/{name}"
                try:
                    self._catalogs[name] = self._read_catalog(resolved, name)
                    self._catalog_health[active_key] = "loaded"
                except Exception as exc:
                    # Fail closed to canonical per key. A corrupt/missing target
                    # must never make the desktop fail to launch.
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
            if self.active_locale != CANONICAL_LOCALE:
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
        info = locale_info(self.active_locale)
        return {
            "requested_locale": self.requested_locale,
            "active_locale": self.active_locale,
            "canonical_locale": CANONICAL_LOCALE,
            "bundled": self.active_locale != PSEUDO_LOCALE,
            "pseudo_locale": self.active_locale == PSEUDO_LOCALE,
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


_localization = LocalizationManager.get_instance()


def tr(key: str, default: Optional[str] = None, *, catalog: str = "ui", **values) -> str:
    return _localization.tr(key, default, catalog=catalog, **values)


def localization_manager() -> LocalizationManager:
    return _localization
