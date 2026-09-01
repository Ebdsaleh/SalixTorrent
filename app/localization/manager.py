"""Offline runtime localization manager for SalixTorrent.

The released client reads only bundled JSON catalogs. Network translation is a
development-only concern under ``tools/localization``.
"""

from __future__ import annotations

import json
import string
import threading
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Set

from app.engine.runtime_paths import resource_path
from .locale_info import (
    AUTO_LOCALE,
    CANONICAL_LOCALE,
    SUPPORTED_LOCALES,
    resolve_requested_locale,
)


CATALOG_NAMES = ("ui", "help", "glossary")


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
        self._format_error_keys: Set[str] = set()
        self._load_errors: list[str] = []
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
        strings = raw.get("strings", raw) if isinstance(raw, dict) else {}
        if not isinstance(strings, dict):
            raise ValueError(f"{path} does not contain a string mapping")
        return {str(key): str(value) for key, value in strings.items() if isinstance(value, str)}

    def configure(self, requested_locale: object, *, system_locale: Optional[str] = None) -> str:
        with self._lock:
            self.requested_locale = str(requested_locale or AUTO_LOCALE)
            resolved = resolve_requested_locale(requested_locale, system_locale=system_locale)
            if resolved not in SUPPORTED_LOCALES:
                resolved = CANONICAL_LOCALE

            self._fallback_keys.clear()
            self._format_error_keys.clear()
            self._load_errors.clear()
            self._canonical_catalogs = {}
            self._catalogs = {}

            for name in CATALOG_NAMES:
                try:
                    self._canonical_catalogs[name] = self._read_catalog(CANONICAL_LOCALE, name)
                except Exception as exc:
                    self._canonical_catalogs[name] = {}
                    self._load_errors.append(f"{CANONICAL_LOCALE}/{name}: {exc}")

                if resolved == CANONICAL_LOCALE:
                    self._catalogs[name] = dict(self._canonical_catalogs[name])
                    continue
                try:
                    self._catalogs[name] = self._read_catalog(resolved, name)
                except Exception as exc:
                    self._catalogs[name] = {}
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

    def lookup(self, key: str, default: Optional[str] = None, *, catalog: str = "ui") -> str:
        key = str(key)
        active = self._catalogs.get(catalog, {})
        canonical = self._canonical_catalogs.get(catalog, {})
        if key in active and str(active[key]).strip():
            return active[key]
        if key in canonical:
            if self.active_locale != CANONICAL_LOCALE:
                self._fallback_keys.add(f"{catalog}:{key}")
            return canonical[key]
        if default is not None:
            if self.active_locale != CANONICAL_LOCALE:
                self._fallback_keys.add(f"{catalog}:{key}")
            return str(default)
        self._fallback_keys.add(f"{catalog}:{key}")
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
            text = str(source or default or key)
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            self._format_error_keys.add(f"{catalog}:{key}")
            fallback = str(source or default or key)
            try:
                return fallback.format(**values)
            except Exception:
                return fallback

    def snapshot(self) -> Dict[str, object]:
        active_count = sum(len(values) for values in self._catalogs.values())
        canonical_count = sum(len(values) for values in self._canonical_catalogs.values())
        return {
            "requested_locale": self.requested_locale,
            "active_locale": self.active_locale,
            "canonical_locale": CANONICAL_LOCALE,
            "bundled": True,
            "catalog_entries": active_count,
            "canonical_entries": canonical_count,
            "fallback_count": len(self._fallback_keys),
            "fallback_keys": tuple(sorted(self._fallback_keys)),
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
